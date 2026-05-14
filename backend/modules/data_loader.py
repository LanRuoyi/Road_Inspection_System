# modules/data_loader.py
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.geo_utils import coordinate_converter
from modules.data_utils import (
    _normalize_disease_type,
    _extract_boxes,
    _pick_primary_type_bbox,
    _extract_lat_lon,
    nms_merge_boxes,
    _strip_channel_suffix,
    _parse_image_stamp_ns,
)

DUAL_CHANNEL_MAX_DELTA_NS = 350_000_000  # 350ms, consistent with capture_node match_tolerance_s


def _build_single_record(json_file: Path, img_path: Path, data: dict) -> Optional[dict]:
    """Pass 1: build a record dict from a single JSON file (original logic)."""
    fallback_type = _normalize_disease_type(data.get("type"))
    boxes = _extract_boxes(data, fallback_type)
    disease_type, bbox = _pick_primary_type_bbox(boxes, fallback_type)
    type_set = set()
    for item in boxes:
        if not isinstance(item, dict):
            continue
        t = _normalize_disease_type(item.get("type"))
        if t:
            type_set.add(t)
    type_list = sorted(type_set)
    if not disease_type and type_list:
        disease_type = type_list[0]
    lat, lon = _extract_lat_lon(data)
    if lat is not None and lon is not None:
        lat, lon = coordinate_converter(lat, lon)

    return {
        "lat": lat,
        "lon": lon,
        "img_path": str(img_path),
        "type": disease_type,
        "bbox": bbox,
        "boxes": boxes,
        "types": type_list,
        "target_count": len(boxes),
        "count": 1,
        "record_id": json_file.stem,
        "created_at": data.get("created_at"),
        "channel": data.get("channel"),
        "_image_stamp_ns": _parse_image_stamp_ns(data),
    }


def _merge_dual_records(rec_a: dict, rec_b: dict) -> dict:
    """Create a merged record from two single-channel records.

    rec_a is ch0 (preferred for GPS / base name), rec_b is ch1.
    """
    base_name, _ = _strip_channel_suffix(rec_a["record_id"])
    merged_id = f"{base_name}_dual" if base_name else rec_a["record_id"]

    lat = rec_a.get("lat") if rec_a.get("lat") is not None else rec_b.get("lat")
    lon = rec_a.get("lon") if rec_a.get("lon") is not None else rec_b.get("lon")

    merged_boxes = nms_merge_boxes(rec_a.get("boxes", []), rec_b.get("boxes", []))

    type_set = set()
    for b in merged_boxes:
        if not isinstance(b, dict):
            continue
        t = _normalize_disease_type(b.get("type"))
        if t:
            type_set.add(t)
    type_list = sorted(type_set)
    primary_type = type_list[0] if type_list else _normalize_disease_type(rec_a.get("type"))

    primary_bbox = []
    if merged_boxes:
        largest = max(
            merged_boxes,
            key=lambda x: float(x.get("bbox", [0, 0, 0, 0])[2]) * float(x.get("bbox", [0, 0, 0, 0])[3]),
        )
        primary_bbox = list(largest.get("bbox", []))

    created_at = rec_a.get("created_at") or rec_b.get("created_at")
    default_img_path = rec_a.get("img_path") or rec_b.get("img_path")

    channels = {
        "0": {"record_id": rec_a["record_id"], "img_path": rec_a.get("img_path")},
        "1": {"record_id": rec_b["record_id"], "img_path": rec_b.get("img_path")},
    }

    return {
        "lat": lat,
        "lon": lon,
        "img_path": default_img_path,
        "type": primary_type,
        "bbox": primary_bbox,
        "boxes": merged_boxes,
        "types": type_list,
        "target_count": len(merged_boxes),
        "count": 1,
        "record_id": merged_id,
        "created_at": created_at,
        "channel": None,
        "has_dual_channel": True,
        "channels": channels,
    }


def load_disease_records(directory):
    """
    Scan *.json files under directory, match same-named .jpg images,
    pair ch0/ch1 records by image_stamp proximity, and merge detection
    results of paired records via per-type NMS.
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    # --- Pass 1: collect raw per-channel records ---
    ch0_records: List[dict] = []
    ch1_records: List[dict] = []
    single_records: List[dict] = []

    for json_file in directory.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error parsing {json_file}: {e}")
            continue

        img_path = json_file.with_suffix(".jpg")
        if not img_path.exists():
            continue

        if not isinstance(data, dict):
            data = {}

        record = _build_single_record(json_file, img_path, data)
        if record is None:
            continue

        base_name, channel = _strip_channel_suffix(json_file.stem)
        if channel == 0:
            ch0_records.append(record)
        elif channel == 1:
            ch1_records.append(record)
        else:
            single_records.append(record)

    # --- Pass 2: pair within each date group by temporal order ---
    merged: List[dict] = []
    MAX_DELTA = DUAL_CHANNEL_MAX_DELTA_NS

    # Group records by date prefix (YYYYMMDD) to avoid cross-dataset mispairing
    def _date_key(rec):
        rid = rec.get("record_id", "")
        return rid[:8] if len(rid) >= 8 else ""

    ch0_by_date: Dict[str, List[dict]] = {}
    for r in ch0_records:
        ch0_by_date.setdefault(_date_key(r), []).append(r)

    ch1_by_date: Dict[str, List[dict]] = {}
    for r in ch1_records:
        ch1_by_date.setdefault(_date_key(r), []).append(r)

    all_dates = sorted(set(list(ch0_by_date.keys()) + list(ch1_by_date.keys())))

    for date_key in all_dates:
        c0 = sorted(ch0_by_date.get(date_key, []), key=lambda r: r.get("_image_stamp_ns") or 0)
        c1 = sorted(ch1_by_date.get(date_key, []), key=lambda r: r.get("_image_stamp_ns") or 0)

        # Greedy closest-timestamp pairing: enumerate all candidate pairs within the
        # time window, then match from smallest delta to largest. This avoids index-
        # shift mispairing when one channel has extra unpaired records at the front.
        candidates: List[Tuple[int, int, int]] = []  # (delta_ns, idx_c0, idx_c1)
        for i, r0 in enumerate(c0):
            ns0 = r0.get("_image_stamp_ns")
            if ns0 is None:
                continue
            for j, r1 in enumerate(c1):
                ns1 = r1.get("_image_stamp_ns")
                if ns1 is None:
                    continue
                delta = abs(ns0 - ns1)
                if delta <= MAX_DELTA:
                    candidates.append((delta, i, j))

        candidates.sort(key=lambda x: x[0])  # closest pairs first

        paired_c0: set = set()
        paired_c1: set = set()
        for _delta, i, j in candidates:
            if i not in paired_c0 and j not in paired_c1:
                merged.append(_merge_dual_records(c0[i], c1[j]))
                paired_c0.add(i)
                paired_c1.add(j)

        # Unpaired records stay as single-channel
        for i, r in enumerate(c0):
            if i not in paired_c0:
                merged.append(r)
        for j, r in enumerate(c1):
            if j not in paired_c1:
                merged.append(r)

    merged.extend(single_records)

    return merged

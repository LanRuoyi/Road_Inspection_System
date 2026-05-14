# modules/data_utils.py — 共享数据规范化工具

from typing import Any, Dict, List, Optional, Tuple


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _strip_type(v: Any, default: str = "Unknown") -> str:
    if isinstance(v, str):
        s = v.strip()
        if s:
            return s
    return default


_UNKNOWN_TYPE_VALUES = {"unknown", "unknow", "none", "null", "n/a", "na", "-", "--"}


def _normalize_disease_type(v: Any) -> str:
    s = _strip_type(v, "")
    if not s:
        return ""
    if s.lower() in _UNKNOWN_TYPE_VALUES:
        return ""
    return s


def _normalize_bbox(x: Any, y: Any, w: Any, h: Any) -> Optional[List[float]]:
    try:
        xf = float(x)
        yf = float(y)
        wf = float(w)
        hf = float(h)
    except Exception:
        return None
    if wf <= 0 or hf <= 0:
        return None
    return [xf, yf, wf, hf]


def _extract_boxes(data: Dict[str, Any], fallback_type: str) -> List[Dict[str, Any]]:
    boxes: List[Dict[str, Any]] = []
    seen = set()

    def add_box(box_type: str, bbox: Optional[List[float]]) -> None:
        if not bbox:
            return
        t = _normalize_disease_type(box_type) or fallback_type
        key = (t, round(bbox[0], 3), round(bbox[1], 3), round(bbox[2], 3), round(bbox[3], 3))
        if key in seen:
            return
        seen.add(key)
        boxes.append({"type": t, "bbox": bbox})

    top_bbox = data.get("bbox")
    if isinstance(top_bbox, list) and len(top_bbox) >= 4:
        add_box(
            _normalize_disease_type(data.get("type")) or fallback_type,
            _normalize_bbox(top_bbox[0], top_bbox[1], top_bbox[2], top_bbox[3]),
        )

    detection = data.get("detection")
    if isinstance(detection, dict):
        targets = detection.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, dict):
                    continue
                target_type = _normalize_disease_type(target.get("type")) or fallback_type
                rois = target.get("rois")
                if not isinstance(rois, list):
                    continue
                for roi in rois:
                    if not isinstance(roi, dict):
                        continue
                    rect = roi.get("rect")
                    if not isinstance(rect, dict):
                        continue
                    bbox = _normalize_bbox(
                        rect.get("x_offset", 0) or 0,
                        rect.get("y_offset", 0) or 0,
                        rect.get("width", 0) or 0,
                        rect.get("height", 0) or 0,
                    )
                    roi_type = _normalize_disease_type(roi.get("type")) or target_type
                    add_box(roi_type, bbox)

    return boxes


def _pick_primary_type_bbox(boxes: List[Dict[str, Any]], fallback_type: str) -> Tuple[str, List[float]]:
    if not boxes:
        return fallback_type, []

    primary = max(
        boxes,
        key=lambda item: float(item.get("bbox", [0, 0, 0, 0])[2]) * float(item.get("bbox", [0, 0, 0, 0])[3]),
    )
    return _normalize_disease_type(primary.get("type")) or fallback_type, list(primary.get("bbox") or [])


def _iou(box_a: List[float], box_b: List[float]) -> float:
    """Calculate IoU between two [x, y, w, h] boxes."""
    ax, ay, aw, ah = box_a[0], box_a[1], box_a[2], box_a[3]
    bx, by, bw, bh = box_b[0], box_b[1], box_b[2], box_b[3]
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix = max(0.0, min(ax2, bx2) - max(ax, bx))
    iy = max(0.0, min(ay2, by2) - max(ay, by))
    intersection = ix * iy
    if intersection <= 0:
        return 0.0
    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def nms_merge_boxes(
    boxes_a: List[Dict[str, Any]], boxes_b: List[Dict[str, Any]], iou_threshold: float = 0.5
) -> List[Dict[str, Any]]:
    """Combine boxes from two channels and deduplicate via per-type NMS."""
    combined = list(boxes_a) + list(boxes_b)
    if not combined:
        return []

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for item in combined:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        t = _normalize_disease_type(item.get("type"))
        if not t:
            continue
        by_type.setdefault(t, []).append(item)

    merged: List[Dict[str, Any]] = []
    for t, items in by_type.items():
        items.sort(
            key=lambda x: float(x.get("bbox", [0, 0, 0, 0])[2]) * float(x.get("bbox", [0, 0, 0, 0])[3]),
            reverse=True,
        )
        kept: List[Dict[str, Any]] = []
        for item in items:
            bbox_a = item["bbox"]
            suppressed = False
            for k in kept:
                if _iou(bbox_a, k["bbox"]) > iou_threshold:
                    suppressed = True
                    break
            if not suppressed:
                kept.append(item)
        merged.extend(kept)

    return merged


def _strip_channel_suffix(stem: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract base name and channel number from a filename stem.

    e.g. '20260327T084657_886372Z_ch0' -> ('20260327T084657_886372Z', 0)
    """
    import re
    m = re.search(r'_ch(\d+)$', stem)
    if m:
        return stem[:m.start()], int(m.group(1))
    return None, None


def _parse_image_stamp_ns(data: Dict[str, Any]) -> Optional[int]:
    """Extract image_stamp as total nanoseconds since epoch."""
    stamp = data.get("image_stamp")
    if isinstance(stamp, dict):
        sec = stamp.get("sec", 0)
        nsec = stamp.get("nanosec", 0)
        try:
            return int(sec) * 1_000_000_000 + int(nsec)
        except (ValueError, TypeError):
            pass
    return None


def _extract_lat_lon(data: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    lat = _safe_float(data.get("lat"))
    lon = _safe_float(data.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon

    flight_state = data.get("flight_state")
    if isinstance(flight_state, dict):
        lat = _safe_float(flight_state.get("lat"))
        lon = _safe_float(flight_state.get("lon"))
        if lat is not None and lon is not None:
            return lat, lon

    return None, None

# modules/data_loader.py
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import coordinate_converter


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


def _extract_type_bbox(data: Dict[str, Any]) -> Tuple[str, List[float]]:
    if isinstance(data.get("type"), str) and data.get("type").strip():
        t = data.get("type").strip()
    else:
        t = "Unknown"

    bbox = data.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        try:
            return t, [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        except Exception:
            pass

    detection = data.get("detection")
    if not isinstance(detection, dict):
        return t, []

    targets = detection.get("targets")
    if not isinstance(targets, list):
        return t, []

    for target in targets:
        if not isinstance(target, dict):
            continue
        target_type = _strip_type(target.get("type"), t)
        rois = target.get("rois")
        if not isinstance(rois, list):
            continue
        for roi in rois:
            if not isinstance(roi, dict):
                continue
            rect = roi.get("rect")
            if not isinstance(rect, dict):
                continue
            try:
                x = float(rect.get("x_offset", 0) or 0)
                y = float(rect.get("y_offset", 0) or 0)
                w = float(rect.get("width", 0) or 0)
                h = float(rect.get("height", 0) or 0)
            except Exception:
                continue
            if w > 0 and h > 0:
                roi_type = _strip_type(roi.get("type"), target_type)
                return roi_type, [x, y, w, h]

    return t, []


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

def load_disease_records(directory):
    """
    扫描目录下的 json 文件，并匹配同名图片。
    返回格式：[{'lat':, 'lon':, 'img_path':, 'details': []}, ...]
    """
    records = []
    directory = Path(directory)
    if not directory.exists():
        return records

    for json_file in directory.glob("*.json"):
        try:
            # 使用 utf-8-sig 兼容可能存在的 BOM（Windows 生成文件场景）
            with open(json_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            img_path = json_file.with_suffix(".jpg")  # 假设是 jpg，可根据实际修改

            if img_path.exists():
                if not isinstance(data, dict):
                    data = {}

                disease_type, bbox = _extract_type_bbox(data)
                lat, lon = _extract_lat_lon(data)
                if lat is not None and lon is not None:
                    lat, lon = coordinate_converter(lat, lon)

                records.append({
                    "lat": lat,
                    "lon": lon,
                    "img_path": str(img_path),
                    "type": disease_type,
                    "bbox": bbox,  # [x, y, w, h]
                    "count": 1,  # 基础计数
                    "record_id": json_file.stem,
                    "created_at": data.get("created_at"),
                    "channel": data.get("channel"),
                })
        except Exception as e:
            print(f"Error parsing {json_file}: {e}")

    return records
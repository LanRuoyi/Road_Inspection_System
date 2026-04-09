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

    # 选面积最大的目标作为主类型，兼容旧前端筛选与主图标展示。
    primary = max(
        boxes,
        key=lambda item: float(item.get("bbox", [0, 0, 0, 0])[2]) * float(item.get("bbox", [0, 0, 0, 0])[3]),
    )
    return _normalize_disease_type(primary.get("type")) or fallback_type, list(primary.get("bbox") or [])


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

                records.append({
                    "lat": lat,
                    "lon": lon,
                    "img_path": str(img_path),
                    "type": disease_type,
                    "bbox": bbox,  # [x, y, w, h]
                    "boxes": boxes,
                    "types": type_list,
                    "target_count": len(boxes),
                    "count": 1,  # 基础计数
                    "record_id": json_file.stem,
                    "created_at": data.get("created_at"),
                    "channel": data.get("channel"),
                })
        except Exception as e:
            print(f"Error parsing {json_file}: {e}")

    return records
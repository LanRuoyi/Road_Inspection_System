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

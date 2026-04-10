# backend/main.py
import os
import cv2
import io
import asyncio
import time
import json
import hashlib
import math
from copy import deepcopy
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# 导入现有的数据加载和图像处理逻辑
from modules.data_loader import load_disease_records
from modules.image_utils import draw_bbox_on_image
from modules.ros_manager import ROSManager
from scripts.pci import (
    DistressMeasurement,
    DistressType,
    PavementPerformanceModel,
    PavementSection,
    PCICalculator,
    CDICalculator,
    SeverityLevel,
)
from config.settings import (
    BASE_DIR,
    DEFAULT_LOCATION,
    DATA_PATH,
    MAP_TYPES,
    DISEASE_TYPES,
    coordinate_converter,
    ANALYSIS_INSTANCE_DEFAULTS,
    ANALYSIS_PARAM_SCHEMA,
    ANALYSIS_RESULT_SCHEMA,
    ANALYSIS_THRESHOLDS,
    ANALYSIS_STATUS_COLORS,
)

app = FastAPI(title="Road Inspection System API")

# --- 跨域配置 (CORS) ---
# 因为前端 Vue 运行在不同端口（如 5173），必须允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议改为具体的域名
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 数据模型 ---
class DiseaseRecord(BaseModel):
    id: str
    lat: float
    lon: float
    type: str
    area: float = 1.0  # 新增：BBox 面积或权重，用于热力图
    types: List[str] = []
    target_count: int = 0
    created_at: Optional[str] = None

class MapType(BaseModel):
    value: str
    label: str
    url: str
    subdomains: List[str]

class DiseaseType(BaseModel):
    value: str
    label: str


class SegmentAssessmentPayload(BaseModel):
    instance_id: str
    points: List[List[float]] = Field(default_factory=list)
    record_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class SegmentAssessmentRequest(BaseModel):
    segments: List[SegmentAssessmentPayload]


class AnalysisInstancesUpdateRequest(BaseModel):
    instances: List[Dict[str, Any]] = Field(default_factory=list)


class AnalysisInstancesDeleteRequest(BaseModel):
    instance_ids: List[str] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    default_location: Optional[List[float]] = None
    map_types: Optional[List[Dict[str, Any]]] = None
    disease_types: Optional[List[Dict[str, Any]]] = None
    analysis_instance_defaults: Optional[Dict[str, Any]] = None
    analysis_param_schema: Optional[List[Dict[str, Any]]] = None
    analysis_result_schema: Optional[List[Dict[str, Any]]] = None
    analysis_thresholds: Optional[Dict[str, Any]] = None
    analysis_status_colors: Optional[Dict[str, Any]] = None

# --- 全局变量存储数据（模拟数据库） ---
records_store = {}
ros_manager = ROSManager()

SETTINGS_OVERRIDE_PATH = BASE_DIR / "config" / "settings_runtime_override.json"
ANALYSIS_INSTANCE_STORE_PATH = BASE_DIR / "data" / "analysis" / "instances.json"

settings_lock = Lock()
analysis_instance_lock = Lock()
analysis_instances_store: List[Dict[str, Any]] = []

DEFAULT_SETTINGS_SNAPSHOT = {
    "default_location": list(DEFAULT_LOCATION),
    "map_types": deepcopy(MAP_TYPES),
    "disease_types": deepcopy(DISEASE_TYPES),
    "analysis_instance_defaults": deepcopy(ANALYSIS_INSTANCE_DEFAULTS),
    "analysis_param_schema": deepcopy(ANALYSIS_PARAM_SCHEMA),
    "analysis_result_schema": deepcopy(ANALYSIS_RESULT_SCHEMA),
    "analysis_thresholds": deepcopy(ANALYSIS_THRESHOLDS),
    "analysis_status_colors": deepcopy(ANALYSIS_STATUS_COLORS),
}


class ROSConnectRequest(BaseModel):
    host: str = "100.68.153.103"
    port: int = 9090

class ROSSubscribeTopic(BaseModel):
    name: str
    type: Optional[str] = None


class ROSBatchSubscribeRequest(BaseModel):
    topics: List[ROSSubscribeTopic]


class UploadInitRequest(BaseModel):
    item_id: str
    file_name: str
    file_size: int
    file_sha256: str


class UploadCompleteRequest(BaseModel):
    item_id: str
    file_name: str
    json_file_name: str
    json_payload: Dict[str, Any]


class DeviceManifestRequest(BaseModel):
    device_id: str
    items: List[Dict[str, Any]]


class PullStartRequest(BaseModel):
    item_ids: List[str]


class PullAckRequest(BaseModel):
    item_ids: List[str]


UPLOAD_TMP_DIR = DATA_PATH.parent / "upload_tmp"
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
upload_sessions: Dict[str, Dict[str, Any]] = {}
upload_lock = Lock()
device_manifests: Dict[str, Dict[str, Any]] = {}
device_pull_tasks: Dict[str, List[str]] = {}

pci_calculator = PCICalculator()
cdi_calculator = CDICalculator()

SUPPORTED_DISTRESS_VALUES = {
    item.get("value")
    for item in DISEASE_TYPES
    if isinstance(item, dict) and item.get("value") and item.get("value") != "all"
}

RECORD_TYPE_TO_DISTRESS = {
    "fatigue_cracking": DistressType.FATIGUE_CRACKING,
    "potholes": DistressType.POTHOLES,
    "rutting": DistressType.RUTTING,
    "longitudinal_cracking": DistressType.LONGITUDINAL_CRACKING,
    "transverse_cracking": DistressType.TRANSVERSE_CRACKING,
    "block_cracking": DistressType.BLOCK_CRACKING,
    "edge_cracking": DistressType.EDGE_CRACKING,
    "patching": DistressType.PATCHING,
    "bleeding": DistressType.BLEEDING,
    "raveling": DistressType.RAVELING,
}

DEFAULT_SEVERITY_BY_TYPE = {
    "fatigue_cracking": SeverityLevel.HIGH,
    "potholes": SeverityLevel.HIGH,
    "rutting": SeverityLevel.MEDIUM,
    "longitudinal_cracking": SeverityLevel.MEDIUM,
    "transverse_cracking": SeverityLevel.MEDIUM,
    "block_cracking": SeverityLevel.MEDIUM,
    "edge_cracking": SeverityLevel.MEDIUM,
    "patching": SeverityLevel.LOW,
    "bleeding": SeverityLevel.LOW,
    "raveling": SeverityLevel.MEDIUM,
}

DISTRESS_LENGTH_TYPES = {
    DistressType.LONGITUDINAL_CRACKING,
    DistressType.TRANSVERSE_CRACKING,
    DistressType.EDGE_CRACKING,
}


def _compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


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


def _extract_boxes_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    fallback_type = _normalize_disease_type(payload.get("type"))
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

    top_bbox = payload.get("bbox")
    if isinstance(top_bbox, list) and len(top_bbox) >= 4:
        add_box(
            _normalize_disease_type(payload.get("type")) or fallback_type,
            _normalize_bbox(top_bbox[0], top_bbox[1], top_bbox[2], top_bbox[3]),
        )

    detection = payload.get("detection")
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
                    add_box(
                        _normalize_disease_type(roi.get("type")) or target_type,
                        _normalize_bbox(
                            rect.get("x_offset", 0) or 0,
                            rect.get("y_offset", 0) or 0,
                            rect.get("width", 0) or 0,
                            rect.get("height", 0) or 0,
                        ),
                    )

    return boxes


def _pick_primary_type_bbox(boxes: List[Dict[str, Any]], fallback_type: str) -> tuple[str, List[float]]:
    if not boxes:
        return fallback_type, []

    primary = max(
        boxes,
        key=lambda item: float(item.get("bbox", [0, 0, 0, 0])[2]) * float(item.get("bbox", [0, 0, 0, 0])[3]),
    )
    return _normalize_disease_type(primary.get("type")) or fallback_type, list(primary.get("bbox") or [])


def _extract_type_bbox_from_payload(payload: Dict[str, Any]) -> tuple[str, List[float]]:
    boxes = _extract_boxes_from_payload(payload)
    return _pick_primary_type_bbox(boxes, _normalize_disease_type(payload.get("type")))


def _normalize_uploaded_payload(payload: Any, item_id: str, file_name: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    detection = payload.get("detection")
    if not isinstance(detection, dict):
        detection = {
            "header": {"stamp": {"sec": 0, "nanosec": 0}, "frame_id": ""},
            "fps": 0,
            "perfs": [],
            "targets": [],
            "disappeared_targets": [],
        }

    flight_state = payload.get("flight_state")
    if not isinstance(flight_state, dict):
        flight_state = {
            "connected": False,
            "armed": False,
            "mode": "UNKNOWN",
            "system_status": 0,
            "lat": None,
            "lon": None,
            "alt_m": None,
            "local_ned": {"x": None, "y": None, "z": None},
            "gps_fix": 0,
            "satellites": 0,
            "mission_current": None,
            "last_heartbeat_time": 0.0,
        }

    match = payload.get("match")
    if not isinstance(match, dict):
        match = {
            "timestamp_match": False,
            "image_stamp_ns": 0,
            "detection_stamp_ns": 0,
            "abs_diff_ms": 0.0,
            "tolerance_ms": 0.0,
        }

    normalized = dict(payload)
    for redundant_key in ("json_file", "type", "bbox", "lat", "lon", "boxes", "types", "target_count"):
        normalized.pop(redundant_key, None)
    normalized["id"] = str(payload.get("id") or item_id)
    normalized["image_file"] = str(payload.get("image_file") or (DATA_PATH / file_name))
    normalized["detection"] = detection
    normalized["flight_state"] = flight_state
    normalized["match"] = match
    source_topics = payload.get("source_topics")
    if not isinstance(source_topics, dict):
        normalized["source_topics"] = {
            "image_topic": "",
            "detection_topic": "",
            "flight_state_topic": "/uav/mavlink/state",
        }
    else:
        normalized["source_topics"] = {
            "image_topic": str(source_topics.get("image_topic", "") or ""),
            "detection_topic": str(source_topics.get("detection_topic", "") or ""),
            "flight_state_topic": str(source_topics.get("flight_state_topic", "/uav/mavlink/state") or "/uav/mavlink/state"),
        }

    image_stamp = payload.get("image_stamp")
    if not isinstance(image_stamp, dict):
        normalized["image_stamp"] = {"sec": 0, "nanosec": 0, "frame_id": ""}
    else:
        normalized["image_stamp"] = {
            "sec": int(image_stamp.get("sec", 0) or 0),
            "nanosec": int(image_stamp.get("nanosec", 0) or 0),
            "frame_id": str(image_stamp.get("frame_id", "") or ""),
        }
    return normalized


def _extract_converted_lat_lon(payload: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    lat = _safe_float(payload.get("lat"))
    lon = _safe_float(payload.get("lon"))
    if lat is None or lon is None:
        flight_state = payload.get("flight_state")
        if isinstance(flight_state, dict):
            lat = _safe_float(flight_state.get("lat"))
            lon = _safe_float(flight_state.get("lon"))
    if lat is not None and lon is not None:
        lat, lon = coordinate_converter(lat, lon)
    return lat, lon


def _build_record_store_entry(payload: Dict[str, Any], final_img_path: Path) -> Dict[str, Any]:
    boxes = _extract_boxes_from_payload(payload)
    disease_type, bbox = _pick_primary_type_bbox(boxes, _normalize_disease_type(payload.get("type")))

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

    lat, lon = _extract_converted_lat_lon(payload)

    return {
        "lat": lat,
        "lon": lon,
        "img_path": str(final_img_path),
        "type": disease_type,
        "bbox": bbox,
        "boxes": boxes,
        "types": type_list,
        "target_count": len(boxes),
        "count": 1,
        "channel": payload.get("channel"),
        "created_at": payload.get("created_at"),
    }

def init_data():
    """初始化时加载所有 JSON 记录"""
    global records_store
    records_store = {}
    try:
        raw_data = load_disease_records(DATA_PATH)
    except Exception as e:
        print(f"init_data failed: {e}")
        raw_data = []

    for item in raw_data:
        try:
            file_id = os.path.basename(item["img_path"]).split(".")[0]
            records_store[file_id] = item
        except Exception:
            continue


def _safe_json_load(path: Path, default_value: Any) -> Any:
    if not path.exists():
        return deepcopy(default_value)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return deepcopy(default_value)


def _safe_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _sanitize_map_types(value: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(value, list):
        return None
    sanitized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        map_value = str(item.get("value") or "").strip()
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not map_value or not label or not url:
            continue
        subdomains = item.get("subdomains")
        if not isinstance(subdomains, list):
            subdomains = ["1", "2", "3", "4"]
        subdomains = [str(sub).strip() for sub in subdomains if str(sub).strip()]
        sanitized.append({
            "value": map_value,
            "label": label,
            "url": url,
            "subdomains": subdomains or ["1", "2", "3", "4"],
        })
    return sanitized or None


def _sanitize_disease_types(value: Any) -> Optional[List[Dict[str, str]]]:
    if not isinstance(value, list):
        return None
    sanitized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        disease_value = str(item.get("value") or "").strip()
        label = str(item.get("label") or "").strip()
        if not disease_value or not label:
            continue
        sanitized.append({"value": disease_value, "label": label})
    return sanitized or None


def _collect_runtime_settings() -> Dict[str, Any]:
    return {
        "default_location": list(DEFAULT_LOCATION),
        "map_types": deepcopy(MAP_TYPES),
        "disease_types": deepcopy(DISEASE_TYPES),
        "analysis_instance_defaults": dict(ANALYSIS_INSTANCE_DEFAULTS),
        "analysis_param_schema": deepcopy(ANALYSIS_PARAM_SCHEMA),
        "analysis_result_schema": deepcopy(ANALYSIS_RESULT_SCHEMA),
        "analysis_thresholds": dict(ANALYSIS_THRESHOLDS),
        "analysis_status_colors": dict(ANALYSIS_STATUS_COLORS),
    }


def _apply_settings_overrides(payload: Dict[str, Any], persist: bool = False) -> Dict[str, Any]:
    with settings_lock:
        if "default_location" in payload:
            loc = payload.get("default_location")
            if not isinstance(loc, list):
                loc = None
            if isinstance(loc, list) and len(loc) >= 2:
                lat = _safe_float(loc[0])
                lon = _safe_float(loc[1])
                if lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon):
                    DEFAULT_LOCATION[:] = [lat, lon]

        if "map_types" in payload:
            map_types = _sanitize_map_types(payload.get("map_types"))
            if map_types:
                MAP_TYPES[:] = map_types

        if "disease_types" in payload:
            disease_types = _sanitize_disease_types(payload.get("disease_types"))
            if disease_types:
                DISEASE_TYPES[:] = disease_types

        if "analysis_instance_defaults" in payload and isinstance(payload.get("analysis_instance_defaults"), dict):
            ANALYSIS_INSTANCE_DEFAULTS.clear()
            ANALYSIS_INSTANCE_DEFAULTS.update(payload.get("analysis_instance_defaults") or {})

        if "analysis_param_schema" in payload:
            schema = payload.get("analysis_param_schema")
            if isinstance(schema, list):
                ANALYSIS_PARAM_SCHEMA[:] = [item for item in schema if isinstance(item, dict)]

        if "analysis_result_schema" in payload:
            result_schema = payload.get("analysis_result_schema")
            if isinstance(result_schema, list):
                ANALYSIS_RESULT_SCHEMA[:] = [item for item in result_schema if isinstance(item, dict)]

        if "analysis_thresholds" in payload and isinstance(payload.get("analysis_thresholds"), dict):
            ANALYSIS_THRESHOLDS.clear()
            ANALYSIS_THRESHOLDS.update(payload.get("analysis_thresholds") or {})

        if "analysis_status_colors" in payload and isinstance(payload.get("analysis_status_colors"), dict):
            ANALYSIS_STATUS_COLORS.clear()
            ANALYSIS_STATUS_COLORS.update(payload.get("analysis_status_colors") or {})

        runtime_settings = _collect_runtime_settings()
        if persist:
            _safe_json_write(SETTINGS_OVERRIDE_PATH, runtime_settings)
        return runtime_settings


def _load_settings_overrides() -> None:
    payload = _safe_json_load(SETTINGS_OVERRIDE_PATH, {})
    if isinstance(payload, dict) and payload:
        _apply_settings_overrides(payload, persist=False)


def _sanitize_analysis_instance(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    instance_id = str(item.get("id") or "").strip()
    if not instance_id:
        return None

    points_raw = item.get("points")
    if not isinstance(points_raw, list):
        points_raw = []

    points = []
    for p in points_raw:
        if not isinstance(p, dict):
            continue
        lat = _safe_float(p.get("lat"))
        lon = _safe_float(p.get("lon"))
        if lat is None or lon is None:
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        points.append({
            "id": str(p.get("id") or f"{instance_id}_{len(points)}"),
            "lat": lat,
            "lon": lon,
        })

    if not points:
        return None

    parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
    status = str(item.get("status") or "no_data")
    color = str(item.get("color") or ANALYSIS_STATUS_COLORS.get("no_data", "rgba(128, 128, 128, 0.35)"))
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else None

    return {
        "id": instance_id,
        "points": points,
        "parameters": parameters,
        "status": status,
        "color": color,
        "metrics": metrics,
    }


def _load_analysis_instances_from_disk() -> None:
    global analysis_instances_store
    raw = _safe_json_load(ANALYSIS_INSTANCE_STORE_PATH, [])
    sanitized = []
    if isinstance(raw, list):
        for item in raw:
            normalized = _sanitize_analysis_instance(item)
            if normalized is not None:
                sanitized.append(normalized)
    with analysis_instance_lock:
        analysis_instances_store = sanitized
    if not ANALYSIS_INSTANCE_STORE_PATH.exists():
        _safe_json_write(ANALYSIS_INSTANCE_STORE_PATH, sanitized)


def _save_analysis_instances_to_disk(instances: List[Dict[str, Any]]) -> None:
    _safe_json_write(ANALYSIS_INSTANCE_STORE_PATH, instances)

@app.on_event("startup")
async def startup_event():
    _load_settings_overrides()
    _load_analysis_instances_from_disk()
    init_data()


@app.on_event("shutdown")
async def shutdown_event():
    ros_manager.disconnect()


def _normalize_subscribe_topics(topics: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized = []
    for item in topics:
        if not isinstance(item, dict):
            continue
        topic_name = (item.get("name") or "").strip()
        topic_type = (item.get("type") or "").strip()
        if not topic_name:
            continue
        if not topic_type:
            topic_type = ros_manager.get_topic_type(topic_name) or ""
        if not topic_type:
            continue
        normalized.append({"name": topic_name, "type": topic_type})
    return normalized


def _get_topic_catalog(topic_type: Optional[str] = None) -> Dict[str, Any]:
    items = ros_manager.get_topics_with_types()
    if topic_type:
        items = [item for item in items if item.get("type") == topic_type]
    topic_types = sorted({item.get("type", "unknown") for item in items})
    return {
        "connected": ros_manager.is_connected,
        "topic_types": topic_types,
        "topics": items,
    }


def _build_disease_types() -> List[Dict[str, str]]:
    base = []
    seen = set()

    for item in DISEASE_TYPES:
        if not isinstance(item, dict):
            continue
        value = _normalize_disease_type(item.get("value"))
        if not value or value in seen:
            continue
        base.append({
            "value": value,
            "label": _strip_type(item.get("label"), value),
        })
        seen.add(value)

    if "all" not in seen:
        base.insert(0, {"value": "all", "label": "全部"})

    return base


def _safe_positive_float(v: Any, default: float, min_value: float = 0.0) -> float:
    n = _safe_float(v)
    if n is None or not math.isfinite(n):
        return default
    if n < min_value:
        return default
    return float(n)


def _safe_int(v: Any, default: int, min_value: int = 0) -> int:
    try:
        n = int(v)
    except Exception:
        return default
    if n < min_value:
        return default
    return n


def _normalize_points(points: List[List[float]]) -> List[List[float]]:
    normalized = []
    for p in points:
        if not isinstance(p, list) or len(p) < 2:
            continue
        lat = _safe_float(p[0])
        lon = _safe_float(p[1])
        if lat is None or lon is None:
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        normalized.append([lat, lon])
    return normalized


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _polyline_length_m(points: List[List[float]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for idx in range(len(points) - 1):
        p1 = points[idx]
        p2 = points[idx + 1]
        total += _haversine_m(p1[0], p1[1], p2[0], p2[1])
    return total


def _distress_type_from_name(name: str) -> Optional[DistressType]:
    key = (name or "").strip().lower()
    return RECORD_TYPE_TO_DISTRESS.get(key)


def _severity_from_name(name: str) -> SeverityLevel:
    key = (name or "").strip().lower()
    return DEFAULT_SEVERITY_BY_TYPE.get(key, SeverityLevel.MEDIUM)


def _get_record_boxes(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    boxes = record.get("boxes")
    normalized: List[Dict[str, Any]] = []

    if isinstance(boxes, list):
        for item in boxes:
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            t = _normalize_disease_type(item.get("type"))
            if t not in SUPPORTED_DISTRESS_VALUES:
                continue
            normalized.append({"type": t, "bbox": bbox})

    if normalized:
        return normalized

    bbox = record.get("bbox")
    t = _normalize_disease_type(record.get("type"))
    if isinstance(bbox, list) and len(bbox) >= 4 and t in SUPPORTED_DISTRESS_VALUES:
        return [{"type": t, "bbox": bbox}]

    return []


def _measurement_from_bbox(
    distress_type: DistressType,
    severity: SeverityLevel,
    bbox: List[float],
    pixel_to_meter: float,
    sample_unit_area: float,
) -> Optional[DistressMeasurement]:
    try:
        width_px = max(0.0, float(bbox[2]))
        height_px = max(0.0, float(bbox[3]))
    except Exception:
        return None

    if width_px <= 0 or height_px <= 0:
        return None

    if distress_type in DISTRESS_LENGTH_TYPES:
        quantity = max(width_px, height_px) * pixel_to_meter
        unit = "length"
    else:
        quantity = (width_px * pixel_to_meter) * (height_px * pixel_to_meter)
        unit = "area"

    if quantity <= 0:
        return None

    return DistressMeasurement(
        distress_type=distress_type,
        severity=severity,
        quantity=max(quantity, 0.0001),
        unit=unit,
        sample_unit_area=sample_unit_area,
    )


def _build_distresses(record_ids: List[str], sample_unit_area: float, pixel_to_meter: float) -> List[DistressMeasurement]:
    distresses: List[DistressMeasurement] = []

    for record_id in record_ids:
        record = records_store.get(str(record_id))
        if not isinstance(record, dict):
            continue

        boxes = _get_record_boxes(record)
        for item in boxes:
            t = str(item.get("type") or "")
            distress_type = _distress_type_from_name(t)
            if distress_type is None:
                continue

            measurement = _measurement_from_bbox(
                distress_type=distress_type,
                severity=_severity_from_name(t),
                bbox=list(item.get("bbox") or []),
                pixel_to_meter=pixel_to_meter,
                sample_unit_area=sample_unit_area,
            )
            if measurement is not None:
                distresses.append(measurement)

    return distresses


def _merge_analysis_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(ANALYSIS_INSTANCE_DEFAULTS)
    if isinstance(parameters, dict):
        for key, value in parameters.items():
            if key in merged:
                merged[key] = value
    return merged


def _build_section(instance_id: str, points: List[List[float]], params: Dict[str, Any]) -> PavementSection:
    section_length = max(1.0, _polyline_length_m(points))
    section_width = _safe_positive_float(params.get("section_width_m"), ANALYSIS_INSTANCE_DEFAULTS["section_width_m"], 0.1)

    return PavementSection(
        section_id=instance_id,
        length=section_length,
        width=section_width,
        surface_type=str(params.get("surface_type") or ANALYSIS_INSTANCE_DEFAULTS["surface_type"]),
        construction_year=_safe_int(params.get("construction_year"), ANALYSIS_INSTANCE_DEFAULTS["construction_year"], 1900),
        last_maintenance_year=_safe_int(
            params.get("last_maintenance_year"),
            ANALYSIS_INSTANCE_DEFAULTS["last_maintenance_year"],
            1900,
        ),
        asphalt_thickness=_safe_positive_float(
            params.get("asphalt_thickness_m"), ANALYSIS_INSTANCE_DEFAULTS["asphalt_thickness_m"], 0.01
        ),
        base_thickness=_safe_positive_float(
            params.get("base_thickness_m"), ANALYSIS_INSTANCE_DEFAULTS["base_thickness_m"], 0.01
        ),
        subgrade_modulus=_safe_positive_float(
            params.get("subgrade_modulus_mpa"), ANALYSIS_INSTANCE_DEFAULTS["subgrade_modulus_mpa"], 1
        ),
        aadtt=_safe_positive_float(params.get("aadtt_k_per_day"), ANALYSIS_INSTANCE_DEFAULTS["aadtt_k_per_day"], 0.01),
        traffic_growth_rate=_safe_positive_float(
            params.get("traffic_growth_rate"), ANALYSIS_INSTANCE_DEFAULTS["traffic_growth_rate"], 0
        ),
        lane_distribution_factor=_safe_positive_float(
            params.get("lane_distribution_factor"), ANALYSIS_INSTANCE_DEFAULTS["lane_distribution_factor"], 0.01
        ),
    )


def _evaluate_segment(segment: SegmentAssessmentPayload) -> Dict[str, Any]:
    thresholds = dict(ANALYSIS_THRESHOLDS)
    colors = dict(ANALYSIS_STATUS_COLORS)

    merged_params = _merge_analysis_parameters(segment.parameters or {})
    points = _normalize_points(segment.points)

    # 使用去重后的 record_ids，避免重复统计同一条记录。
    matched_record_ids = [str(item) for item in dict.fromkeys(segment.record_ids or [])]
    section = _build_section(segment.instance_id, points, merged_params)
    section_area_m2 = max(1.0, float(section.total_area))

    if not matched_record_ids:
        return {
            "instance_id": segment.instance_id,
            "status": "no_data",
            "color": colors.get("no_data"),
            "matched_record_count": 0,
            "current_pci": None,
            "current_cdi": None,
            "predicted_pci": None,
            "predicted_cdi": None,
            "sawi": None,
            "sawi_risk_level": "NO_DATA",
            "reasons": ["当前路段范围内无病害记录"],
            "input_snapshot": {
                "section_length_m": round(section.length, 2),
                "section_width_m": round(section.width, 2),
                "section_area_m2": round(section_area_m2, 2),
                "prediction_years": _safe_positive_float(
                    merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
                ),
                "pixel_to_meter": _safe_positive_float(
                    merged_params.get("pixel_to_meter"), ANALYSIS_INSTANCE_DEFAULTS["pixel_to_meter"], 0.0001
                ),
            },
        }

    pixel_to_meter = _safe_positive_float(
        merged_params.get("pixel_to_meter"), ANALYSIS_INSTANCE_DEFAULTS["pixel_to_meter"], 0.0001
    )
    # Use actual section area so PCI density responds to length/width changes.
    sample_unit_area = section_area_m2
    distresses = _build_distresses(matched_record_ids, sample_unit_area, pixel_to_meter)

    if not distresses:
        return {
            "instance_id": segment.instance_id,
            "status": "no_data",
            "color": colors.get("no_data"),
            "matched_record_count": 0,
            "current_pci": None,
            "current_cdi": None,
            "predicted_pci": None,
            "predicted_cdi": None,
            "sawi": None,
            "sawi_risk_level": "NO_DATA",
            "reasons": ["病害记录类型无法映射到分析模型"],
            "input_snapshot": {
                "section_length_m": round(section.length, 2),
                "section_width_m": round(section.width, 2),
                "section_area_m2": round(section_area_m2, 2),
                "prediction_years": _safe_positive_float(
                    merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
                ),
                "pixel_to_meter": pixel_to_meter,
            },
        }

    prediction_years = _safe_positive_float(
        merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
    )
    observed_pci_drop = _safe_positive_float(
        merged_params.get("observed_pci_drop"), ANALYSIS_INSTANCE_DEFAULTS["observed_pci_drop"], 0
    )
    observed_years = _safe_positive_float(
        merged_params.get("observed_years"), ANALYSIS_INSTANCE_DEFAULTS["observed_years"], 0.1
    )

    current_pci = pci_calculator.calculate_pci(distresses)
    current_cdi = cdi_calculator.calculate_cdi_from_pci(current_pci, distresses)

    model = PavementPerformanceModel(section)
    predicted_cdi = model.formula_1_predict_cdi(current_cdi, prediction_years)
    predicted_pci = predicted_cdi

    sawi_result = model.formula_2_sawi(observed_pci_drop, observed_years)
    sawi = float(sawi_result.get("sawi", 0))

    status = "warning"
    reasons = []
    if sawi > float(thresholds.get("sawi_danger_threshold", 1.5)):
        status = "danger"
        reasons.append("SAWI 超过危险阈值")
    elif predicted_pci < float(thresholds.get("prediction_pci_warning_threshold", 70.0)):
        status = "warning"
        reasons.append("预测PCI将在设定年限内跌破阈值")
    elif (
        current_pci > float(thresholds.get("healthy_pci_threshold", 70.0))
        and sawi <= float(thresholds.get("sawi_normal_max", 1.0))
    ):
        status = "healthy"
        reasons.append("PCI 高于阈值且 SAWI 处于正常范围")
    else:
        status = "warning"
        reasons.append("当前指标处于临界区间，建议关注")

    return {
        "instance_id": segment.instance_id,
        "status": status,
        "color": colors.get(status, colors.get("warning")),
        "matched_record_count": len(matched_record_ids),
        "current_pci": round(float(current_pci), 2),
        "current_cdi": round(float(current_cdi), 2),
        "predicted_pci": round(float(predicted_pci), 2),
        "predicted_cdi": round(float(predicted_cdi), 2),
        "sawi": round(float(sawi), 3),
        "sawi_risk_level": sawi_result.get("risk_level"),
        "reasons": reasons,
        "risk_detail": sawi_result,
        "input_snapshot": {
            "section_length_m": round(section.length, 2),
            "section_width_m": round(section.width, 2),
            "section_area_m2": round(section_area_m2, 2),
            "prediction_years": prediction_years,
            "aadtt_k_per_day": round(float(section.aadtt), 4),
            "pixel_to_meter": pixel_to_meter,
        },
    }

# --- API 接口 ---

@app.get("/api/records", response_model=List[DiseaseRecord])
async def get_records():
    """
    接口 1: 获取所有病害的基础点位信息
    用于地图上渲染 Marker 和 热力图
    """
    records = []
    for k, v in records_store.items():
        lat = _safe_float(v.get("lat"))
        lon = _safe_float(v.get("lon"))
        if lat is None or lon is None:
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue

        boxes = v.get("boxes") if isinstance(v.get("boxes"), list) else []
        if not boxes and isinstance(v.get("bbox"), list):
            boxes = [{"type": _normalize_disease_type(v.get("type")), "bbox": v.get("bbox", [])}]

        type_set = set()
        supported_boxes = []
        for item in boxes:
            if not isinstance(item, dict):
                continue
            t = _normalize_disease_type(item.get("type"))
            if t in SUPPORTED_DISTRESS_VALUES:
                type_set.add(t)
                supported_boxes.append(item)
        type_list = sorted(type_set)
        target_count = len(supported_boxes) if supported_boxes else len(type_list)

        disease_type = _normalize_disease_type(v.get("type"))
        if disease_type not in SUPPORTED_DISTRESS_VALUES:
            disease_type = ""
        if not disease_type and type_list:
            disease_type = type_list[0]

        # 多目标场景下使用全部框面积和作为热力图权重。
        raw_area = 0.0
        for item in supported_boxes:
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            try:
                raw_area += max(0.0, float(bbox[2])) * max(0.0, float(bbox[3]))
            except (ValueError, TypeError):
                continue
        bbox_area = max(1.0, raw_area / 1000.0)

        records.append({
            "id": k, 
            "lat": lat,
            "lon": lon,
            "type": disease_type,
            "area": bbox_area,
            "types": type_list,
            "target_count": target_count,
            "created_at": str(v.get("created_at") or "").strip() or None,
        })
    return records

@app.get("/api/image/{record_id}")
async def get_image(record_id: str):
    """
    接口 2: 根据 ID 返回实时渲染 BBox 的图片流
    """
    if record_id not in records_store:
        raise HTTPException(status_code=404, detail="Record not found")
    
    record = records_store[record_id]
    
    # 绘制多目标 BBox（按类别区分颜色）
    img = draw_bbox_on_image(
        record['img_path'],
        record.get('bbox', []),
        record.get('type', 'Unknown'),
        boxes=record.get('boxes', []),
    )
    
    if img is None:
        raise HTTPException(status_code=500, detail="Image processing failed")
    
    # 将 OpenCV 图像编码为 JPEG 格式的字节流
    res, frame = cv2.imencode('.jpg', img)
    if not res:
        raise HTTPException(status_code=500, detail="Image encoding failed")
    
    return StreamingResponse(io.BytesIO(frame.tobytes()), media_type="image/jpeg")

@app.get("/api/map-types", response_model=List[MapType])
async def get_map_types():
    """
    接口 3: 获取地图类型配置
    用于前端加载瓦片地图的URL
    """
    return MAP_TYPES

@app.get("/api/disease-types", response_model=List[DiseaseType])
async def get_disease_types():
    """
    接口 4: 获取病害类型配置
    """
    return _build_disease_types()


@app.get("/api/analysis/config")
async def get_analysis_config():
    return {
        "instance_defaults": ANALYSIS_INSTANCE_DEFAULTS,
        "param_schema": ANALYSIS_PARAM_SCHEMA,
        "result_schema": ANALYSIS_RESULT_SCHEMA,
        "thresholds": ANALYSIS_THRESHOLDS,
        "status_colors": ANALYSIS_STATUS_COLORS,
    }


@app.get("/api/analysis/instances")
async def get_analysis_instances():
    with analysis_instance_lock:
        instances = deepcopy(analysis_instances_store)
    return {
        "count": len(instances),
        "instances": instances,
        "store_path": str(ANALYSIS_INSTANCE_STORE_PATH),
    }


@app.put("/api/analysis/instances")
async def put_analysis_instances(request: AnalysisInstancesUpdateRequest):
    sanitized = []
    for item in request.instances:
        normalized = _sanitize_analysis_instance(item)
        if normalized is not None:
            sanitized.append(normalized)

    with analysis_instance_lock:
        global analysis_instances_store
        analysis_instances_store = sanitized
        _save_analysis_instances_to_disk(analysis_instances_store)

    return {
        "ok": True,
        "count": len(sanitized),
        "store_path": str(ANALYSIS_INSTANCE_STORE_PATH),
    }


@app.delete("/api/analysis/instances")
async def delete_analysis_instances(request: AnalysisInstancesDeleteRequest = Body(default=AnalysisInstancesDeleteRequest())):
    target_ids = {str(item).strip() for item in request.instance_ids if str(item).strip()}

    with analysis_instance_lock:
        global analysis_instances_store
        if not target_ids:
            analysis_instances_store = []
        else:
            analysis_instances_store = [
                item for item in analysis_instances_store if str(item.get("id") or "") not in target_ids
            ]
        _save_analysis_instances_to_disk(analysis_instances_store)
        remain_count = len(analysis_instances_store)

    return {
        "ok": True,
        "count": remain_count,
        "store_path": str(ANALYSIS_INSTANCE_STORE_PATH),
    }


@app.get("/api/system/settings")
async def get_system_settings():
    return _collect_runtime_settings()


@app.put("/api/system/settings")
async def put_system_settings(request: SettingsUpdateRequest):
    payload = request.dict(exclude_none=True)
    updated = _apply_settings_overrides(payload, persist=True)
    return {
        "ok": True,
        "settings": updated,
        "override_path": str(SETTINGS_OVERRIDE_PATH),
    }


@app.post("/api/system/settings/reset")
async def reset_system_settings():
    updated = _apply_settings_overrides(deepcopy(DEFAULT_SETTINGS_SNAPSHOT), persist=True)
    return {
        "ok": True,
        "settings": updated,
        "override_path": str(SETTINGS_OVERRIDE_PATH),
    }


@app.post("/api/analysis/assess")
async def assess_analysis_segments(request: SegmentAssessmentRequest):
    results = []
    for segment in request.segments:
        try:
            results.append(_evaluate_segment(segment))
        except Exception as exc:
            results.append(
                {
                    "instance_id": segment.instance_id,
                    "status": "warning",
                    "color": ANALYSIS_STATUS_COLORS.get("warning"),
                    "matched_record_count": 0,
                    "current_pci": None,
                    "current_cdi": None,
                    "predicted_pci": None,
                    "predicted_cdi": None,
                    "sawi": None,
                    "sawi_risk_level": "ERROR",
                    "reasons": [f"评估失败: {exc}"],
                }
            )

    return {
        "thresholds": ANALYSIS_THRESHOLDS,
        "status_colors": ANALYSIS_STATUS_COLORS,
        "results": results,
    }


@app.post("/api/ros/connect")
async def connect_ros(request: ROSConnectRequest):
    connected = ros_manager.connect(request.host, request.port)
    if not connected:
        raise HTTPException(status_code=503, detail="ROS bridge connection failed")

    return {
        "connected": True,
        "host": request.host,
        "port": request.port,
    }


@app.post("/api/ros/disconnect")
async def disconnect_ros():
    ros_manager.disconnect()
    return {"connected": False}


@app.get("/api/ros/status")
async def get_ros_status():
    return {
        "connected": ros_manager.is_connected,
        "active_subscriptions": list(ros_manager.topics.keys()),
    }


@app.get("/api/ros/topic-types")
async def get_ros_topic_types():
    if not ros_manager.is_connected:
        return {"connected": False, "topic_types": []}
    return {
        "connected": True,
        "topic_types": ros_manager.get_topic_types(),
    }


@app.get("/api/ros/topics")
async def get_ros_topics(topic_type: Optional[str] = None):
    if not ros_manager.is_connected:
        return {"connected": False, "topics": [], "topic_types": []}
    return _get_topic_catalog(topic_type=topic_type)


@app.post("/api/ros/subscribe")
async def subscribe_ros_topics(request: ROSBatchSubscribeRequest):
    if not ros_manager.is_connected:
        raise HTTPException(status_code=503, detail="ROS bridge is not connected")

    normalized_topics = _normalize_subscribe_topics([topic.dict() for topic in request.topics])
    if not normalized_topics:
        raise HTTPException(status_code=400, detail="No valid topics to subscribe")

    for topic in normalized_topics:
        ros_manager.subscribe(topic["name"], topic["type"])

    return {
        "subscribed": normalized_topics,
        "count": len(normalized_topics),
    }


@app.get("/api/ros/messages")
async def get_ros_topic_messages(topics: Optional[str] = None):
    if not ros_manager.is_connected:
        return {"connected": False, "data": {}}

    topic_names: List[str] = []
    if topics:
        topic_names = [item.strip() for item in topics.split(",") if item and item.strip()]

    data = {}
    for topic_name in topic_names:
        frame = ros_manager.get_frame(topic_name)
        if frame is not None:
            data[topic_name] = frame

    return {
        "connected": True,
        "timestamp": time.time(),
        "data": data,
    }


@app.websocket("/api/ros/ws")
async def ros_topics_websocket(websocket: WebSocket):
    await websocket.accept()

    client_topics: Dict[str, str] = {}
    last_sent: Dict[str, Any] = {}

    async def cleanup():
        for topic_name in list(client_topics.keys()):
            ros_manager.unsubscribe_topic(topic_name)
        client_topics.clear()

    try:
        await websocket.send_json({
            "event": "connected",
            "connected": ros_manager.is_connected,
            "timestamp": time.time(),
        })

        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=0.2)
                action = payload.get("action")

                if action == "ping":
                    await websocket.send_json({"event": "pong", "timestamp": time.time()})

                elif action == "subscribe":
                    if not ros_manager.is_connected:
                        await websocket.send_json({"event": "error", "message": "ROS bridge is not connected"})
                        continue

                    topics_payload = payload.get("topics", [])
                    normalized = _normalize_subscribe_topics(topics_payload)
                    subscribed = []

                    for topic in normalized:
                        name = topic["name"]
                        topic_type = topic["type"]
                        if name in client_topics:
                            continue
                        ros_manager.subscribe(name, topic_type)
                        client_topics[name] = topic_type
                        subscribed.append(topic)

                    await websocket.send_json({
                        "event": "subscribed",
                        "topics": subscribed,
                        "all_topics": [{"name": n, "type": t} for n, t in client_topics.items()],
                    })

                elif action == "unsubscribe":
                    topics_payload = payload.get("topics", [])
                    topic_names = []
                    for item in topics_payload:
                        if isinstance(item, dict):
                            name = (item.get("name") or "").strip()
                        else:
                            name = str(item).strip()
                        if name:
                            topic_names.append(name)

                    for topic_name in topic_names:
                        if topic_name in client_topics:
                            ros_manager.unsubscribe_topic(topic_name)
                            client_topics.pop(topic_name, None)
                            last_sent.pop(topic_name, None)

                    await websocket.send_json({
                        "event": "unsubscribed",
                        "topics": topic_names,
                        "all_topics": [{"name": n, "type": t} for n, t in client_topics.items()],
                    })

                elif action == "set_subscriptions":
                    if not ros_manager.is_connected:
                        await websocket.send_json({"event": "error", "message": "ROS bridge is not connected"})
                        continue

                    topics_payload = payload.get("topics", [])
                    normalized = _normalize_subscribe_topics(topics_payload)
                    target_map = {item["name"]: item["type"] for item in normalized}

                    remove_topics = [name for name in client_topics.keys() if name not in target_map]
                    add_topics = [name for name in target_map.keys() if name not in client_topics]

                    for topic_name in remove_topics:
                        ros_manager.unsubscribe_topic(topic_name)
                        client_topics.pop(topic_name, None)
                        last_sent.pop(topic_name, None)

                    for topic_name in add_topics:
                        ros_manager.subscribe(topic_name, target_map[topic_name])
                        client_topics[topic_name] = target_map[topic_name]

                    await websocket.send_json({
                        "event": "subscriptions_updated",
                        "all_topics": [{"name": n, "type": t} for n, t in client_topics.items()],
                    })

                elif action == "catalog":
                    topic_type = payload.get("topic_type")
                    await websocket.send_json({"event": "catalog", **_get_topic_catalog(topic_type=topic_type)})

                else:
                    await websocket.send_json({
                        "event": "error",
                        "message": "Unsupported action",
                        "supported_actions": ["ping", "subscribe", "unsubscribe", "set_subscriptions", "catalog"],
                    })

            except asyncio.TimeoutError:
                pass

            if not client_topics:
                continue

            updates = {}
            for topic_name in list(client_topics.keys()):
                frame = ros_manager.get_frame(topic_name)
                if frame is None:
                    continue
                if frame != last_sent.get(topic_name):
                    updates[topic_name] = frame
                    last_sent[topic_name] = frame

            if updates:
                await websocket.send_json({
                    "event": "message",
                    "timestamp": time.time(),
                    "data": updates,
                })

    except WebSocketDisconnect:
        await cleanup()
    except Exception:
        await cleanup()
        await websocket.close(code=1011)


@app.get("/api/ros/ws")
async def ros_topics_websocket_http_fallback():
    return {
        "ok": False,
        "message": "This endpoint requires WebSocket upgrade.",
        "hint": "Install websockets support: pip install \"uvicorn[standard]\" or pip install websockets wsproto",
    }


@app.post("/api/uav/upload/init")
async def uav_upload_init(request: UploadInitRequest):
    if request.file_size < 0:
        raise HTTPException(status_code=400, detail="invalid file_size")

    upload_id = f"{request.item_id}_{request.file_sha256[:8]}"
    tmp_path = UPLOAD_TMP_DIR / f"{upload_id}.part"

    with upload_lock:
        upload_sessions[upload_id] = {
            "item_id": request.item_id,
            "file_name": request.file_name,
            "file_size": request.file_size,
            "file_sha256": request.file_sha256,
            "tmp_path": str(tmp_path),
        }

    if not tmp_path.exists():
        tmp_path.touch()

    return {
        "ok": True,
        "upload_id": upload_id,
        "received_size": tmp_path.stat().st_size,
    }


@app.get("/api/uav/upload/status/{upload_id}")
async def uav_upload_status(upload_id: str):
    with upload_lock:
        session = upload_sessions.get(upload_id)

    if not session:
        raise HTTPException(status_code=404, detail="upload_id not found")

    tmp_path = Path(session["tmp_path"])
    return {
        "ok": True,
        "upload_id": upload_id,
        "received_size": tmp_path.stat().st_size if tmp_path.exists() else 0,
        "file_size": session["file_size"],
    }


@app.patch("/api/uav/upload/chunk/{upload_id}")
async def uav_upload_chunk(upload_id: str, offset: int, request: Request):
    with upload_lock:
        session = upload_sessions.get(upload_id)

    if not session:
        raise HTTPException(status_code=404, detail="upload_id not found")

    tmp_path = Path(session["tmp_path"])
    if not tmp_path.exists():
        tmp_path.touch()

    current_size = tmp_path.stat().st_size
    if offset != current_size:
        raise HTTPException(status_code=409, detail={"received_size": current_size})

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty chunk")

    with open(tmp_path, "ab") as f:
        f.write(body)

    return {
        "ok": True,
        "upload_id": upload_id,
        "received_size": tmp_path.stat().st_size,
    }


@app.post("/api/uav/upload/complete/{upload_id}")
async def uav_upload_complete(upload_id: str, request: UploadCompleteRequest):
    with upload_lock:
        session = upload_sessions.get(upload_id)

    if not session:
        raise HTTPException(status_code=404, detail="upload_id not found")

    tmp_path = Path(session["tmp_path"])
    if not tmp_path.exists():
        raise HTTPException(status_code=400, detail="upload temp file missing")

    if tmp_path.stat().st_size != session["file_size"]:
        raise HTTPException(status_code=400, detail="incomplete upload")

    sha256_actual = _compute_sha256(tmp_path)
    if sha256_actual.lower() != str(session["file_sha256"]).lower():
        raise HTTPException(status_code=400, detail="sha256 mismatch")

    final_img_path = DATA_PATH / request.file_name
    final_json_path = DATA_PATH / request.json_file_name

    DATA_PATH.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(final_img_path)

    normalized_payload = _normalize_uploaded_payload(
        request.json_payload,
        request.item_id,
        request.file_name,
    )

    with open(final_json_path, "w", encoding="utf-8") as f:
        json.dump(normalized_payload, f, ensure_ascii=False, indent=2)

    # 同步更新内存记录，便于前端地图无需重启即可看到新数据
    file_id = Path(request.file_name).stem
    records_store[file_id] = _build_record_store_entry(normalized_payload, final_img_path)

    with upload_lock:
        upload_sessions.pop(upload_id, None)

    return {
        "ok": True,
        "item_id": request.item_id,
        "image": str(final_img_path),
        "json": str(final_json_path),
    }


@app.get("/api/uav/local-records")
async def uav_local_records():
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    records = []
    for json_file in sorted(DATA_PATH.glob("*.json")):
        image_file = json_file.with_suffix(".jpg")
        item = {
            "item_id": json_file.stem,
            "json_file": str(json_file),
            "image_file": str(image_file) if image_file.exists() else None,
            "has_image": image_file.exists(),
            "metadata": {},
        }
        try:
            with open(json_file, "r", encoding="utf-8-sig") as f:
                item["metadata"] = json.load(f)
        except Exception:
            item["metadata"] = {}
        records.append(item)
    return {
        "ok": True,
        "count": len(records),
        "records": records,
    }


@app.get("/api/uav/devices")
async def uav_devices():
    devices = sorted(device_manifests.keys())
    return {"ok": True, "devices": devices}


@app.post("/api/uav/devices/{device_id}/manifest")
async def uav_device_manifest(device_id: str, request: DeviceManifestRequest):
    if request.device_id != device_id:
        raise HTTPException(status_code=400, detail="device_id mismatch")

    device_manifests[device_id] = {
        "updated_at": time.time(),
        "items": request.items,
    }
    device_pull_tasks.setdefault(device_id, [])
    return {"ok": True, "device_id": device_id, "count": len(request.items)}


@app.get("/api/uav/devices/{device_id}/manifest")
async def uav_get_device_manifest(device_id: str):
    data = device_manifests.get(device_id, {"updated_at": 0, "items": []})
    return {
        "ok": True,
        "device_id": device_id,
        "updated_at": data.get("updated_at", 0),
        "items": data.get("items", []),
    }


@app.post("/api/uav/devices/{device_id}/pull-start")
async def uav_pull_start(device_id: str, request: PullStartRequest):
    pending = device_pull_tasks.setdefault(device_id, [])
    known = set(pending)
    for item_id in request.item_ids:
        if item_id not in known:
            pending.append(item_id)
            known.add(item_id)
    return {"ok": True, "device_id": device_id, "pending_count": len(pending)}


@app.get("/api/uav/devices/{device_id}/pull-tasks")
async def uav_pull_tasks(device_id: str):
    pending = device_pull_tasks.get(device_id, [])
    return {"ok": True, "device_id": device_id, "item_ids": pending}


@app.post("/api/uav/devices/{device_id}/pull-ack")
async def uav_pull_ack(device_id: str, request: PullAckRequest):
    pending = device_pull_tasks.get(device_id, [])
    ack_set = set(request.item_ids)
    remained = [item_id for item_id in pending if item_id not in ack_set]
    device_pull_tasks[device_id] = remained
    return {"ok": True, "device_id": device_id, "pending_count": len(remained)}

if __name__ == "__main__":
    import uvicorn
    # 启动服务：uvicorn main:app --reload
    uvicorn.run(app, host="0.0.0.0", port=8000)
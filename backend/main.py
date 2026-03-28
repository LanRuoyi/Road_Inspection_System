# backend/main.py
import os
import cv2
import io
import asyncio
import time
import json
import hashlib
import math
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

# 导入现有的数据加载和图像处理逻辑
from modules.data_loader import load_disease_records
from modules.image_utils import draw_bbox_on_image
from modules.ros_manager import ROSManager
from config.settings import DATA_PATH, MAP_TYPES, DISEASE_TYPES

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

class MapType(BaseModel):
    value: str
    label: str
    url: str
    subdomains: List[str]

class DiseaseType(BaseModel):
    value: str
    label: str

# --- 全局变量存储数据（模拟数据库） ---
records_store = {}
ros_manager = ROSManager()


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
    fallback_type = _strip_type(payload.get("type"), "Unknown")
    boxes: List[Dict[str, Any]] = []
    seen = set()

    def add_box(box_type: str, bbox: Optional[List[float]]) -> None:
        if not bbox:
            return
        t = _strip_type(box_type, fallback_type)
        key = (t, round(bbox[0], 3), round(bbox[1], 3), round(bbox[2], 3), round(bbox[3], 3))
        if key in seen:
            return
        seen.add(key)
        boxes.append({"type": t, "bbox": bbox})

    top_bbox = payload.get("bbox")
    if isinstance(top_bbox, list) and len(top_bbox) >= 4:
        add_box(
            _strip_type(payload.get("type"), fallback_type),
            _normalize_bbox(top_bbox[0], top_bbox[1], top_bbox[2], top_bbox[3]),
        )

    detection = payload.get("detection")
    if isinstance(detection, dict):
        targets = detection.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, dict):
                    continue
                target_type = _strip_type(target.get("type"), fallback_type)
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
                        _strip_type(roi.get("type"), target_type),
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
        return _strip_type(fallback_type, "Unknown"), []

    primary = max(
        boxes,
        key=lambda item: float(item.get("bbox", [0, 0, 0, 0])[2]) * float(item.get("bbox", [0, 0, 0, 0])[3]),
    )
    return _strip_type(primary.get("type"), fallback_type), list(primary.get("bbox") or [])


def _extract_type_bbox_from_payload(payload: Dict[str, Any]) -> tuple[str, List[float]]:
    boxes = _extract_boxes_from_payload(payload)
    return _pick_primary_type_bbox(boxes, _strip_type(payload.get("type"), "Unknown"))


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

    boxes = _extract_boxes_from_payload({**payload, "detection": detection})
    disease_type, bbox = _pick_primary_type_bbox(boxes, _strip_type(payload.get("type"), "Unknown"))
    type_list = sorted({
        _strip_type(item.get("type"), "Unknown")
        for item in boxes
        if isinstance(item, dict)
    })

    lat = _safe_float(payload.get("lat"))
    lon = _safe_float(payload.get("lon"))
    if lat is None or lon is None:
        lat = _safe_float(flight_state.get("lat"))
        lon = _safe_float(flight_state.get("lon"))

    normalized = dict(payload)
    normalized["id"] = str(payload.get("id") or item_id)
    normalized["image_file"] = str(payload.get("image_file") or (DATA_PATH / file_name))
    normalized["detection"] = detection
    normalized["flight_state"] = flight_state
    normalized["match"] = match
    normalized["type"] = _strip_type(payload.get("type"), disease_type)
    normalized["bbox"] = payload.get("bbox") if isinstance(payload.get("bbox"), list) else bbox
    normalized["boxes"] = boxes
    normalized["types"] = type_list
    normalized["target_count"] = len(boxes)
    normalized["lat"] = lat
    normalized["lon"] = lon
    return normalized

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

@app.on_event("startup")
async def startup_event():
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
        value = _strip_type(item.get("value"), "")
        if not value or value in seen:
            continue
        base.append({
            "value": value,
            "label": _strip_type(item.get("label"), value),
        })
        seen.add(value)

    dynamic_types = set()
    for item in records_store.values():
        if not isinstance(item, dict):
            continue

        primary_type = _strip_type(item.get("type"), "")
        if primary_type and primary_type != "all":
            dynamic_types.add(primary_type)

        types = item.get("types")
        if isinstance(types, list):
            for t in types:
                value = _strip_type(t, "")
                if value and value != "all":
                    dynamic_types.add(value)

    for t in sorted(dynamic_types):
        if t in seen:
            continue
        base.append({"value": t, "label": t})
        seen.add(t)

    if "all" not in seen:
        base.insert(0, {"value": "all", "label": "全部"})

    return base

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
            boxes = [{"type": _strip_type(v.get("type"), "Unknown"), "bbox": v.get("bbox", [])}]

        type_list = sorted({
            _strip_type(item.get("type"), "Unknown")
            for item in boxes
            if isinstance(item, dict)
        })
        target_count = len(boxes)

        # 多目标场景下使用全部框面积和作为热力图权重。
        raw_area = 0.0
        for item in boxes:
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

        disease_type = _strip_type(v.get("type"), "Unknown")
        if disease_type == "Unknown" and type_list:
            disease_type = type_list[0]

        records.append({
            "id": k, 
            "lat": lat,
            "lon": lon,
            "type": disease_type,
            "area": bbox_area,
            "types": type_list,
            "target_count": target_count,
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
    lat = _safe_float(normalized_payload.get("lat"))
    lon = _safe_float(normalized_payload.get("lon"))
    file_id = Path(request.file_name).stem
    records_store[file_id] = {
        "lat": lat,
        "lon": lon,
        "img_path": str(final_img_path),
        "type": _strip_type(normalized_payload.get("type"), "Unknown"),
        "bbox": normalized_payload.get("bbox", []),
        "boxes": normalized_payload.get("boxes", []),
        "types": normalized_payload.get("types", []),
        "target_count": int(normalized_payload.get("target_count") or 0),
        "count": 1,
        "channel": normalized_payload.get("channel"),
        "created_at": normalized_payload.get("created_at"),
    }

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
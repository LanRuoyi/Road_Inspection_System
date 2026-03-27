# backend/main.py
import os
import cv2
import io
import asyncio
import time
import json
import hashlib
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
    host: str = "localhost"
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

def init_data():
    """初始化时加载所有 JSON 记录"""
    global records_store
    raw_data = load_disease_records(DATA_PATH)
    for item in raw_data:
        # 使用图片文件名作为唯一 ID（例如：'img_001'）
        file_id = os.path.basename(item['img_path']).split('.')[0]
        records_store[file_id] = item

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

# --- API 接口 ---

@app.get("/api/records", response_model=List[DiseaseRecord])
async def get_records():
    """
    接口 1: 获取所有病害的基础点位信息
    用于地图上渲染 Marker 和 热力图
    """
    records = []
    for k, v in records_store.items():
        # 计算 bbox 面积作为权重 (w * h)
        # 假设 bbox 格式为 [x, y, w, h]
        bbox_area = 1.0
        if "bbox" in v and isinstance(v["bbox"], list) and len(v["bbox"]) >= 4:
            try:
                # 简单计算面积：宽 * 高
                # 根据实际像素值可能很大，建议做归一化或缩放，防止热力图权重过大
                raw_area = float(v["bbox"][2]) * float(v["bbox"][3])
                # 这里缩小比例，例如除以 1000，基础权重至少为 1.0
                bbox_area = max(1.0, raw_area / 1000.0)
            except (ValueError, TypeError):
                bbox_area = 1.0

        records.append({
            "id": k, 
            "lat": v["lat"], 
            "lon": v["lon"], 
            "type": v["type"],
            "area": bbox_area
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
    
    # 绘制 BBox
    img = draw_bbox_on_image(record['img_path'], record['bbox'], record['type'])
    
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
    return DISEASE_TYPES


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

    with open(final_json_path, "w", encoding="utf-8") as f:
        json.dump(request.json_payload, f, ensure_ascii=False, indent=2)

    # 同步更新内存记录，便于前端地图无需重启即可看到新数据
    if isinstance(request.json_payload, dict):
        lat = request.json_payload.get("lat")
        lon = request.json_payload.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            file_id = Path(request.file_name).stem
            records_store[file_id] = {
                "lat": float(lat),
                "lon": float(lon),
                "img_path": str(final_img_path),
                "type": request.json_payload.get("type", "Unknown"),
                "bbox": request.json_payload.get("bbox", []),
                "count": 1,
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
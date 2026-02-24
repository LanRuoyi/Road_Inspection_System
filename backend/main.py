# backend/main.py
import os
import cv2
import io
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from pydantic import BaseModel

# 导入现有的数据加载和图像处理逻辑
from modules.data_loader import load_disease_records
from modules.image_utils import draw_bbox_on_image
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

# --- API 接口 ---

@app.get("/api/records", response_model=List[DiseaseRecord])
async def get_records():
    """
    接口 1: 获取所有病害的基础点位信息
    用于地图上渲染 Marker
    """
    return [
        {
            "id": k, 
            "lat": v["lat"], 
            "lon": v["lon"], 
            "type": v["type"]
        } for k, v in records_store.items()
    ]

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

if __name__ == "__main__":
    import uvicorn
    # 启动服务：uvicorn main:app --reload
    uvicorn.run(app, host="0.0.0.0", port=8000)
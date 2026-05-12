# modules/data_loader.py
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.geo_utils import coordinate_converter
from modules.data_utils import (
    _normalize_disease_type,
    _extract_boxes,
    _pick_primary_type_bbox,
    _extract_lat_lon,
)

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
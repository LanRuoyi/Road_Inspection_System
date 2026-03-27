# modules/data_loader.py
import json
from pathlib import Path
from config.settings import DATA_PATH, coordinate_converter

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
                lat, lon = coordinate_converter(data["lat"], data["lon"])

                records.append({
                    "lat": lat,
                    "lon": lon,
                    "img_path": str(img_path),
                    "type": data.get("type", "Unknown"),
                    "bbox": data.get("bbox", []),  # [x, y, w, h]
                    "count": 1,  # 基础计数
                })
        except Exception as e:
            print(f"Error parsing {json_file}: {e}")

    return records
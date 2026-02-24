# modules/data_loader.py
import os
import json
import glob
from config.settings import DATA_PATH, coordinate_converter

def load_disease_records(directory):
    """
    扫描目录下的json文件，并匹配对应的同名图片
    返回格式：[{'lat':, 'lon':, 'img_path':, 'details': []}, ...]
    """
    records = []
    if not os.path.exists(directory):
        return records

    json_files = glob.glob(os.path.join(directory, "*.json"))
    
    for j_file in json_files:
        try:
            with open(j_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            base_name = os.path.splitext(j_file)[0]
            img_path = base_name + ".jpg" # 假设是jpg，可根据实际修改
            
            if os.path.exists(img_path):
                # 调用预留的坐标转换
                lat, lon = coordinate_converter(data['lat'], data['lon'])
                
                records.append({
                    "lat": lat,
                    "lon": lon,
                    "img_path": img_path,
                    "type": data.get("type", "Unknown"),
                    "bbox": data.get("bbox", []), # [x, y, w, h]
                    "count": 1 # 基础计数
                })
        except Exception as e:
            print(f"Error parsing {j_file}: {e}")
            
    return records
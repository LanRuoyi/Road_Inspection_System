# config/settings.py

import math
from pathlib import Path

# 项目根目录，统一构建相对路径，避免启动目录不同导致找不到文件
BASE_DIR = Path(__file__).resolve().parent.parent

# 地图配置
# 高德地图瓦片地址（支持中国境内，坐标系为GCJ-02）
AMAP_TILE_URL = "http://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"

# 默认中心点（大致位置，后期可由系统定位覆盖）
DEFAULT_LOCATION = [39.9042, 116.4074]  # 北京

# 离线缓存路径
TILE_CACHE_DIR = BASE_DIR / "cache" / "tiles"
DATA_PATH = BASE_DIR / "data" / "records"

# 地图类型配置
MAP_TYPES = [
    {
        "value": "normal",
        "label": "标准地图",
        "url": "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        "subdomains": ["1", "2", "3", "4"]
    },
    {
        "value": "satellite",
        "label": "卫星地图", 
        "url": "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
        "subdomains": ["1", "2", "3", "4"]
    },
    {
        "value": "terrain",
        "label": "地形地图",
        "url": "https://webst0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",
        "subdomains": ["1", "2", "3", "4"]
    }
]

# 病害类型配置
DISEASE_TYPES = [
    {"value": "all", "label": "全部"},
    {"value": "crack", "label": "裂缝"},
    {"value": "pothole", "label": "坑槽"},
    {"value": "repair", "label": "维修"},
    {"value": "rut", "label": "车辙"},
]

_COORD_A = 6378245.0
_COORD_EE = 0.00669342162296594323


def _out_of_china(lat: float, lon: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if _out_of_china(lat, lon):
        return lat, lon

    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _COORD_EE * magic * magic
    sqrt_magic = math.sqrt(magic)

    d_lat = (d_lat * 180.0) / (((_COORD_A * (1 - _COORD_EE)) / (magic * sqrt_magic)) * math.pi)
    d_lon = (d_lon * 180.0) / ((_COORD_A / sqrt_magic) * math.cos(rad_lat) * math.pi)

    mg_lat = lat + d_lat
    mg_lon = lon + d_lon
    return mg_lat, mg_lon


#sym:coordinate_converter
def coordinate_converter(lat, lon, target_sys="GCJ02"):
    """
    坐标转换入口。
    默认将 Pixhawk/M9N 输出的 WGS84 坐标转换为 GCJ-02，便于在高德底图上正确落点。
    target_sys:
      - "GCJ02"/"GCJ-02": 返回 GCJ-02
      - "WGS84"/"WGS-84": 返回原始 WGS84
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return lat, lon

    normalized_target = str(target_sys or "GCJ02").strip().upper().replace("-", "")
    if normalized_target in {"WGS84", "WGS"}:
        return lat_f, lon_f
    if normalized_target in {"GCJ02", "GCJ"}:
        return _wgs84_to_gcj02(lat_f, lon_f)

    return lat_f, lon_f
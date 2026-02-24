# config/settings.py

# 地图配置
# 高德地图瓦片地址（支持中国境内，坐标系为GCJ-02）
AMAP_TILE_URL = 'http://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}'

# 默认中心点（大致位置，后期可由系统定位覆盖）
DEFAULT_LOCATION = [39.9042, 116.4074]  # 北京

# 离线缓存路径
TILE_CACHE_DIR = "./cache/tiles"
DATA_PATH = "./data/records"

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
]

def coordinate_converter(lat, lon, target_sys="WGS84"):
    """
    预留坐标转换接口。
    目前直接返回，未来可在此处添加 GCJ-02 与 WGS-84 的转换逻辑。
    """
    return lat, lon
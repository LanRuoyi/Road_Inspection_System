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
    {"value": "fatigue_cracking", "label": "疲劳裂缝"},
    {"value": "rutting", "label": "车辙"},
    {"value": "potholes", "label": "坑洞"},
    {"value": "longitudinal_cracking", "label": "纵向裂缝"},
    {"value": "transverse_cracking", "label": "横向裂缝"},
    {"value": "block_cracking", "label": "块状裂缝"},
    {"value": "edge_cracking", "label": "边缘裂缝"},
    {"value": "patching", "label": "修补"},
    {"value": "bleeding", "label": "泛油"},
    {"value": "raveling", "label": "松散/剥落"},
]

# 病害分析与交互式路段建模默认配置
# 说明：
# 1. 这些默认值用于新建路段实例时初始化参数。
# 2. 前后端均通过 /api/analysis/config 获取，保证参数口径一致。
ANALYSIS_INSTANCE_DEFAULTS = {
    "pixel_to_meter": 0.01,
    "section_width_m": 7.5,
    "surface_type": "AC",
    "construction_year": 2020,
    "last_maintenance_year": 2020,
    "asphalt_thickness_m": 0.15,
    "base_thickness_m": 0.30,
    "subgrade_modulus_mpa": 50.0,
    "aadtt_k_per_day": 2.0,
    "traffic_growth_rate": 0.02,
    "lane_distribution_factor": 0.8,
    "observed_pci_drop": 5.0,
    "observed_years": 1.0,
    "prediction_years": 3.0,
}

# 参数面板元数据（供前端动态渲染）
ANALYSIS_PARAM_SCHEMA = [
    {
        "key": "pixel_to_meter",
        "label": "像素缩放系数(m/px)",
        "description": "将 YOLO 框像素尺寸换算为物理尺寸。物理宽=像素宽*该系数。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.0001,
        "max": 1,
        "step": 0.0001,
    },
    {
        "key": "section_width_m",
        "label": "路段宽度(m)",
        "description": "用于生成路段带状多边形并计算路段面积。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.5,
        "max": 50,
        "step": 0.1,
    },
    {
        "key": "prediction_years",
        "label": "预测年限(年)",
        "description": "用于 CDI 衰减预测，改变后会实时更新路段颜色。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 30,
        "step": 1,
    },
    {
        "key": "aadtt_k_per_day",
        "label": "AADTT(千辆/日)",
        "description": "年平均日货车流量，公式中的交通荷载输入。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.1,
        "max": 50,
        "step": 0.1,
    },
    {
        "key": "traffic_growth_rate",
        "label": "交通增长率",
        "description": "交通量长期增长趋势参数，可用于后续扩展预测模型。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 0.2,
        "step": 0.005,
    },
    {
        "key": "lane_distribution_factor",
        "label": "车道分配系数",
        "description": "反映货车在目标车道上的分配比例。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.1,
        "max": 1.5,
        "step": 0.01,
    },
    {
        "key": "surface_type",
        "label": "路面类型",
        "description": "路面材料类型，会影响结构解释与后续扩展建模。",
        "source": "manual",
        "editable": True,
        "input": "select",
        "options": [
            {"label": "沥青混凝土(AC)", "value": "AC"},
            {"label": "水泥混凝土(PCC)", "value": "PCC"},
        ],
    },
    {
        "key": "construction_year",
        "label": "建成年份",
        "description": "路段建成年份，用于形成完整路段背景信息。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 1900,
        "max": 2100,
        "step": 1,
    },
    {
        "key": "last_maintenance_year",
        "label": "最近养护年份",
        "description": "最后一次养护时间，用于后续维护策略扩展。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 1900,
        "max": 2100,
        "step": 1,
    },
    {
        "key": "asphalt_thickness_m",
        "label": "沥青层厚度(m)",
        "description": "用于计算结构数 SN 的沥青层厚度。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.02,
        "max": 1,
        "step": 0.01,
    },
    {
        "key": "base_thickness_m",
        "label": "基层厚度(m)",
        "description": "用于计算结构数 SN 的基层厚度。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.02,
        "max": 1.5,
        "step": 0.01,
    },
    {
        "key": "subgrade_modulus_mpa",
        "label": "路基回弹模量(MPa)",
        "description": "路基强度参数，用于后续模型扩展。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 5,
        "max": 500,
        "step": 1,
    },
    {
        "key": "observed_pci_drop",
        "label": "观测PCI下降值",
        "description": "用于 SAWI 计算的实测 PCI 下降量。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 100,
        "step": 0.1,
    },
    {
        "key": "observed_years",
        "label": "观测周期(年)",
        "description": "用于 SAWI 计算的观测时间跨度。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.1,
        "max": 30,
        "step": 0.1,
    },
]

# 病害分析结果字段元数据（后端计算只读）
ANALYSIS_RESULT_SCHEMA = [
    {
        "key": "matched_record_count",
        "label": "匹配病害记录数",
        "description": "当前路段带状范围内命中的病害记录数量。",
        "source": "computed",
    },
    {
        "key": "current_pci",
        "label": "当前 PCI",
        "description": "基于当前病害计算的路面状况指数，值越高表示状况越好。",
        "source": "computed",
    },
    {
        "key": "current_cdi",
        "label": "当前 CDI",
        "description": "综合病害指数，考虑结构性病害权重。",
        "source": "computed",
    },
    {
        "key": "predicted_pci",
        "label": "预测 PCI",
        "description": "按预测年限计算的未来路况指标。",
        "source": "computed",
    },
    {
        "key": "predicted_cdi",
        "label": "预测 CDI",
        "description": "按预测年限计算的未来综合病害指数。",
        "source": "computed",
    },
    {
        "key": "sawi",
        "label": "SAWI 指标",
        "description": "结构异常预警指标，越高表示风险越高。",
        "source": "computed",
    },
    {
        "key": "sawi_risk_level",
        "label": "SAWI 风险等级",
        "description": "由 SAWI 阈值分段得到的风险等级（NORMAL/WARNING/CRITICAL）。",
        "source": "computed",
    },
    {
        "key": "status",
        "label": "渲染状态",
        "description": "用于地图着色的状态（no_data/healthy/warning/danger）。",
        "source": "computed",
    },
]

# 病害分析阈值（用于状态渲染）
ANALYSIS_THRESHOLDS = {
    "healthy_pci_threshold": 70.0,
    "prediction_pci_warning_threshold": 70.0,
    "sawi_normal_max": 1.0,
    "sawi_danger_threshold": 1.5,
}

# 不同状态的默认渲染色（前端可直接使用）
ANALYSIS_STATUS_COLORS = {
    "no_data": "rgba(128, 128, 128, 0.35)",
    "healthy": "rgba(46, 204, 113, 0.35)",
    "warning": "rgba(241, 196, 15, 0.40)",
    "danger": "rgba(231, 76, 60, 0.42)",
}

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
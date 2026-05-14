# config/settings.py

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
    "prediction_years": 3.0,
    "climate_zone": "wet_no_freeze",
    "default_rutting_mm": 0.0,
    "default_fatigue_crack_m2": 0.0,
    "default_transverse_crack_m": 0.0,
    "default_bleeding_m2": 0.0,
    "default_raveling_m2": 0.0,
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
        "description": "用于 PCI 退化预测的年限。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 30,
        "step": 1,
    },
    {
        "key": "climate_zone",
        "label": "气候分区",
        "description": "选择回归模型对应的气候区域，影响公式系数。",
        "source": "manual",
        "editable": True,
        "input": "select",
        "options": [
            {"label": "湿润冰冻区 (Wet Freeze)", "value": "wet_freeze"},
            {"label": "湿润非冰冻区 (Wet No-Freeze)", "value": "wet_no_freeze"},
        ],
    },
    {
        "key": "aadtt_k_per_day",
        "label": "AADTT(千辆/日)",
        "description": "年平均日货车流量，交通荷载输入参数。",
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
        "description": "交通量年增长率，用于病害量前向投影。",
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
        "description": "路面材料类型，影响结构解释与后续扩展建模。",
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
        "description": "路段建成年份，用于计算路龄(Age)。",
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
        "description": "最后一次养护时间，影响路龄计算。",
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
        "description": "用于了解路段结构背景。",
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
        "description": "用于了解路段结构背景。",
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
        "key": "default_rutting_mm",
        "label": "车辙深度默认值(mm)",
        "description": "当前 YOLO 无法检测车辙深度，以手动默认值替代。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 50,
        "step": 0.5,
    },
    {
        "key": "default_fatigue_crack_m2",
        "label": "疲劳裂缝默认值(m^2)",
        "description": "当前 YOLO 未训练疲劳裂缝类别，以默认值替代。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 200,
        "step": 1,
    },
    {
        "key": "default_transverse_crack_m",
        "label": "横向裂缝默认值(m)",
        "description": "当前 YOLO 未训练横向裂缝类别，以默认值替代。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 200,
        "step": 1,
    },
    {
        "key": "default_bleeding_m2",
        "label": "泛油默认值(m^2)",
        "description": "当前 YOLO 未训练泛油类别，以默认值替代。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 100,
        "step": 1,
    },
    {
        "key": "default_raveling_m2",
        "label": "松散剥落默认值(m^2)",
        "description": "当前 YOLO 未训练剥落类别，以默认值替代。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 100,
        "step": 1,
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
        "description": "基于 ASTM D6433 标准计算的当前路面状况指数。",
        "source": "computed",
    },
    {
        "key": "predicted_pci",
        "label": "预测 PCI",
        "description": "基于已发表回归模型的预测年限后路面状况指数。",
        "source": "computed",
    },
    {
        "key": "anomaly_z_score",
        "label": "异常退化指数 (z-score)",
        "description": "标准化预测残差，|z|大表示实测退化偏离模型预期。",
        "source": "computed",
    },
    {
        "key": "anomaly_level",
        "label": "异常等级",
        "description": "基于 z-score 的异常等级判定 (NORMAL/WARNING/CRITICAL)。",
        "source": "computed",
    },
    {
        "key": "status",
        "label": "渲染状态",
        "description": "用于地图着色的状态 (no_data/healthy/warning/danger)。",
        "source": "computed",
    },
]

# 病害分析阈值（用于状态渲染和异常判定）
ANALYSIS_THRESHOLDS = {
    "healthy_pci_threshold": 60.0,
    "anomaly_warning_z": 1.0,
    "anomaly_danger_z": 2.0,
}

# 不同状态的默认渲染色（前端可直接使用）
ANALYSIS_STATUS_COLORS = {
    "no_data": "rgba(128, 128, 128, 0.35)",
    "healthy": "rgba(46, 204, 113, 0.35)",
    "warning": "rgba(241, 196, 15, 0.40)",
    "danger": "rgba(231, 76, 60, 0.42)",
}

# 坐标转换工具已提取至 modules/geo_utils.py，此处保留重导出以兼容旧引用
from modules.geo_utils import coordinate_converter  # noqa: F401
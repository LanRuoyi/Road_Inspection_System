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
    {"value": "potholes", "label": "坑槽"},
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
    "construction_year": 2020,
    "last_maintenance_year": 2020,
    "asphalt_thickness_m": 0.15,
    "base_thickness_m": 0.30,
    "aadtt_k_per_day": 2.0,
    "traffic_growth_rate": 0.02,
    "prediction_years": 3.0,
    "climate_zone": "wet_no_freeze",
    # HDM-4 增量模型参数
    "avg_lef": 1.0,           # 平均荷载等效因子
    "comp_pct": 95.0,         # 相对压实度 %
    "defl_mm": 0.5,           # Benkelman 梁弯沉值 mm
    "mmp_mm_per_month": 50.0, # 月均降水量 mm/月
    # 病害默认值（仅 YOLO 无法检测的变量）
    "default_rutting_mm": 0.0,
    "default_longitudinal_crack_m": 0.0,
    "default_transverse_crack_m": 0.0,
    "default_bleeding_m2": 0.0,
    "default_raveling_m2": 0.0,
}

# 参数面板元数据（供前端动态渲染）
# 每项 description 面向实际用户：解释参数含义 + 如何取值 + 典型参考值
ANALYSIS_PARAM_SCHEMA = [
    {
        "key": "pixel_to_meter",
        "label": "像素缩放系数 (m/px)",
        "description": "单个像素对应地面的实际宽度(米)。取值=飞行高度(m)×像元尺寸(μm)÷焦距(mm)÷1000。典型值：航高25m、焦距4mm、像元3μm时约为0.019m/px。默认0.01对应约15m航高。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.0001,
        "max": 1,
        "step": 0.0001,
    },
    {
        "key": "section_width_m",
        "label": "路段宽度 (m)",
        "description": "道路行车道总宽度(米)。双向2车道约7-8m，4车道约14-15m，6车道约21-22m。用于生成路段评估面并计算路段面积。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.5,
        "max": 50,
        "step": 0.1,
    },
    {
        "key": "prediction_years",
        "label": "预测年限 (年)",
        "description": "从当前时刻向前预测PCI的年数。HDM-4逐年迭代推演到此年限为止。受模型假设稳定性限制，建议不超过10年。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 1,
        "max": 30,
        "step": 1,
    },
    {
        "key": "climate_zone",
        "label": "气候分区",
        "description": "决定使用哪组Ali回归系数。湿润冰冻区(Wet Freeze)适用于北方存在冻融循环的地区，湿润非冰冻区(Wet No-Freeze)适用于南方无冻结地区。按路段实际所在地选择。",
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
        "label": "AADTT (千辆/日)",
        "description": "年平均日货车流量，单位千辆/日。是交通荷载的核心输入。高速公路5-8，国道3-5，省道1.5-3，县乡道0.1-1。仅统计货车(≥2轴)，不含小客车。可通过交通量调查或区域路网数据获取。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 50,
        "step": 0.01,
    },
    {
        "key": "traffic_growth_rate",
        "label": "交通增长率",
        "description": "交通量的年增长率。快速城镇化区域取0.03-0.05，成熟区域取0.01-0.02，交通量萎缩路段可填0。用于逐年推演时YE4的增长(式6-7)。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 0.2,
        "step": 0.005,
    },
    {
        "key": "construction_year",
        "label": "建成年份",
        "description": "路段建成通车的年份。路龄=当前年份-max(建成年份,最近养护年份)。",
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
        "description": "最近一次大修或加铺罩面的年份。若从未大修则填建成年份。路龄从该年份与建成年份中较晚者起算。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 1900,
        "max": 2100,
        "step": 1,
    },
    {
        "key": "asphalt_thickness_m",
        "label": "沥青面层厚度 (m)",
        "description": "沥青混凝土面层的总厚度(米)。高速公路通常0.15-0.20m，普通公路0.08-0.12m。用于计算路面结构数SNP(式6-6)，直接影响HDM-4裂缝萌生时间和车辙发展速率。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.02,
        "max": 1,
        "step": 0.01,
    },
    {
        "key": "base_thickness_m",
        "label": "基层厚度 (m)",
        "description": "粒料基层或半刚性基层的总厚度(米)。通常0.20-0.40m。与沥青面层厚度共同输入SNP结构数计算(式6-6)。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.02,
        "max": 1.5,
        "step": 0.01,
    },
    {
        "key": "avg_lef",
        "label": "平均荷载等效因子 LEF",
        "description": "所有通行货车的荷载等效因子加权平均值。以轻货(2轴、总重<10t)为主取0.5-1.0，以重车(5轴及以上)为主取1.0-3.0，不确定时取1.0。用于将货车流量换算为80kN等效标准轴载(式6-7)。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0.001,
        "max": 10,
        "step": 0.001,
    },
    {
        "key": "comp_pct",
        "label": "相对压实度 (%)",
        "description": "路面基层的压实度百分比，取施工验收报告值或设计值。规范要求≥95%，低等级道路或年久失修路段可能低至80%-90%。影响HDM-4开裂前阶段的车辙发展速率(式6-11)。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 30,
        "max": 100,
        "step": 1,
    },
    {
        "key": "defl_mm",
        "label": "弯沉值 (mm)",
        "description": "路面在Benkelman梁标准荷载下的回弹弯沉值(毫米)，反映路面整体结构刚度。可通过FWD或Benkelman梁实测获取。典型值：刚性路面0.2-0.5mm，中等强度0.5-1.0mm，软弱路基1.0-2.0mm。参与HDM-4初始压密计算(式6-10)。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 5,
        "step": 0.1,
    },
    {
        "key": "mmp_mm_per_month",
        "label": "月均降水量 (mm/月)",
        "description": "多年平均月降水量=年降水量÷12。用于估计水分入渗对开裂后车辙发展的加速效应(式6-12)。北方干燥区<30，华北40-70，南方湿润区80-150。可从当地气象站数据获取。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 500,
        "step": 5,
    },
    {
        "key": "default_rutting_mm",
        "label": "车辙深度默认值 (mm)",
        "description": "当未搭载3D传感器无法自动测量车辙时，使用此手动设定值。新建或刚养护路面填0-2mm，肉眼可见轻度车辙填2-5mm，明显凹陷填5-15mm，严重变形>15mm。注意：此值直接影响PCI预测，应尽量准确估计。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 50,
        "step": 0.5,
    },
    {
        "key": "default_longitudinal_crack_m",
        "label": "纵向裂缝默认值 (m)",
        "description": "路段内纵向裂缝的总长度(米)—沿行车方向的裂缝。当前YOLO模型未单独训练纵向裂缝类别，需手动估计后填入。无数据时保持0。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 200,
        "step": 1,
    },
    {
        "key": "default_transverse_crack_m",
        "label": "横向裂缝默认值 (m)",
        "description": "路段内横向裂缝的总长度(米)—垂直于行车方向的裂缝。当前YOLO模型未单独训练横向裂缝类别，需手动估计后填入。无数据时保持0。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 200,
        "step": 1,
    },
    {
        "key": "default_bleeding_m2",
        "label": "泛油默认值 (m²)",
        "description": "路段内泛油(沥青上浮形成光亮表面)的总面积(平方米)。当前YOLO模型未训练泛油类别，需手动估计后填入。无数据时保持0。",
        "source": "manual",
        "editable": True,
        "input": "number",
        "min": 0,
        "max": 100,
        "step": 1,
    },
    {
        "key": "default_raveling_m2",
        "label": "松散剥落默认值 (m²)",
        "description": "路段内骨料松散脱落的总面积(平方米)。当前YOLO模型未训练剥落类别，需手动估计后填入。无数据时保持0。",
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
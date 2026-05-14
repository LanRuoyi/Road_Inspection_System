// 默认回退地图中心 (北京)
export const FALLBACK_CENTER = {
  lat: 39.9042,
  lon: 116.4074,
}

// 高德地图瓦片图层配置
export const DEFAULT_MAP_TYPES = [
  {
    value: 'normal',
    label: '标准地图',
    url: 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4']
  },
  {
    value: 'satellite',
    label: '卫星地图',
    url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4']
  },
  {
    value: 'terrain',
    label: '地形地图',
    url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4']
  }
]

// 默认病害类型列表（后端不可用时的回退）
export const DEFAULT_DISEASE_TYPES = [
  { value: 'all', label: '全部' },
  { value: 'fatigue_cracking', label: '疲劳裂缝' },
  { value: 'rutting', label: '车辙' },
  { value: 'potholes', label: '坑洞' },
  { value: 'longitudinal_cracking', label: '纵向裂缝' },
  { value: 'transverse_cracking', label: '横向裂缝' },
  { value: 'block_cracking', label: '块状裂缝' },
  { value: 'edge_cracking', label: '边缘裂缝' },
  { value: 'patching', label: '修补' },
  { value: 'bleeding', label: '泛油' },
  { value: 'raveling', label: '松散/剥落' }
]

// 未知/无效的病害类型名称集合
export const UNKNOWN_TYPE_SET = new Set(['unknown', 'unknow', 'none', 'null', 'n/a', 'na', '-', '--'])

// 多选混合值标记
export const MIXED_VALUE_TOKEN = '__MIXED__'

// 热力图渐变配色
export const HEATMAP_GRADIENT = {
  0.0: 'rgba(0,0,255,0)',
  0.2: 'rgba(0,0,255,0.8)',
  0.4: 'cyan',
  0.6: 'lime',
  0.8: 'yellow',
  1.0: 'red'
}

// 热力图默认参数
export const HEATMAP_DEFAULTS = {
  radius: 50,
  blur: 35,
  maxZoom: 18,
  maxMultiplier: 0.8,
  minOpacity: 0.0,
}

// 路段分析默认参数 (与后端 settings.py ANALYSIS_INSTANCE_DEFAULTS 对齐)
export const ANALYSIS_INSTANCE_DEFAULTS = {
  section_width_m: 7.5,
  prediction_years: 3,
  climate_zone: 'wet_no_freeze',
  aadtt_k_per_day: 2,
  traffic_growth_rate: 0.02,
  lane_distribution_factor: 0.8,
  surface_type: 'AC',
  construction_year: 2020,
  last_maintenance_year: 2020,
  pixel_to_meter: 0.01,
  asphalt_thickness_m: 0.15,
  base_thickness_m: 0.3,
  subgrade_modulus_mpa: 50,
  default_rutting_mm: 0,
  default_fatigue_crack_m2: 0,
  default_transverse_crack_m: 0,
  default_bleeding_m2: 0,
  default_raveling_m2: 0,
}

// 分析状态回退颜色
export const FALLBACK_STATUS_COLORS = {
  no_data: 'rgba(128, 128, 128, 0.35)',
  healthy: 'rgba(46, 204, 113, 0.35)',
  warning: 'rgba(241, 196, 15, 0.40)',
  danger: 'rgba(231, 76, 60, 0.42)',
}

// 定时/轮询常量 (ms)
export const POLLING = {
  ROS_MESSAGES: 500,
  UAV_LOCAL_RECORDS: 8000,
  UAV_DEVICES: 5000,
  UAV_HEARTBEAT: 1000,
  UAV_LINK_STALE_SECONDS: 20,
}

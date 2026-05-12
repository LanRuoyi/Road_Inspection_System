# 道路巡检系统 - 后端架构文档

## 1. 工程概述

本系统用于 **无人机路面病害检测与分析**。通过无人机航拍获取路面影像，使用 YOLO 模型检测路面病害（裂缝、坑洞、车辙等），在 Web 前端交互式地图上可视化，并依据 ASTM D6433-23 标准计算 PCI（路面状况指数）、CDI（综合病害指数）、SAWI（结构异常预警指数）等路面性能指标。

- **后端框架**: FastAPI (Python)
- **前端框架**: Vue 3 + Vite + Leaflet
- **检测模型**: YOLO (hobot_dnn_modified 子模块)
- **计算标准**: ASTM D6433-23, AASHTO 设计指南

---

## 2. 目录结构与模块职责

```
backend/
├── main.py                        # FastAPI 主应用：records/image/map-types/ROS/UAV/settings 端点
├── requirements.txt               # Python 依赖
├── __init__.py                    # 包标记
│
├── config/
│   ├── __init__.py
│   ├── settings.py                # 全局配置：地图类型、病害类型、分析默认值/阈值/着色
│   └── settings_runtime_override.json  # 运行时覆写持久化（gitignore）
│
├── modules/
│   ├── __init__.py
│   ├── data_loader.py             # 扫描 data/records/*.json，提取坐标/类型/bbox
│   ├── data_utils.py              # 共享规范化工具 (_safe_float, _normalize_bbox, _extract_boxes 等)
│   ├── image_utils.py             # OpenCV/Pillow 渲染 YOLO 边界框
│   ├── geo_utils.py               # WGS84 → GCJ-02 坐标转换（高德底图适配）
│   ├── ros_manager.py             # roslibpy 封装：连接/订阅(引用计数)/消息缓存
│   ├── pci.py                     # 路面性能分析引擎（1072行，ASTM D6433-23）
│   ├── analysis_router.py         # 路面分析 REST 路由 (/api/analysis/*)
│   └── app_state.py               # 应用级共享全局状态
│
├── scripts/                       # 独立参考/测试脚本（不纳入版本控制）
│   ├── pci.py                     # PCI 分析参考实现
│   ├── dev_server.py              # Windows 开发服务器启动器
│   └── randomize_records_tiananmen.py  # 测试数据 GPS 随机化
│
└── data/
    ├── records/                   # 无人机巡检 JSON + JPG 记录
    ├── analysis/instances.json    # 分析路段实例持久化
    └── upload_tmp/                # 分块上传暂存
```

---

## 3. API 接口清单

| 方法 | 路径 | 模块 | 说明 |
|------|------|------|------|
| GET | `/api/records` | main.py | 获取所有病害点位（地图 Marker/热力图） |
| GET | `/api/image/{record_id}` | main.py | 实时渲染 BBox 标注的图片流 |
| GET | `/api/map-types` | main.py | 地图类型配置（标准/卫星/地形） |
| GET | `/api/disease-types` | main.py | 病害类型配置 |
| GET | `/api/analysis/config` | analysis_router.py | 分析参数默认值/架构/阈值 |
| GET | `/api/analysis/instances` | analysis_router.py | 获取已保存的分析路段 |
| PUT | `/api/analysis/instances` | analysis_router.py | 批量保存分析路段 |
| DELETE | `/api/analysis/instances` | analysis_router.py | 删除分析路段 |
| POST | `/api/analysis/assess` | analysis_router.py | **路段评估**（PCI/CDI/SAWI 计算） |
| GET | `/api/system/settings` | main.py | 获取运行时设置 |
| PUT | `/api/system/settings` | main.py | 更新运行时设置 |
| POST | `/api/system/settings/reset` | main.py | 重置运行时设置 |
| POST | `/api/ros/connect` | main.py | 连接 ROS Bridge |
| POST | `/api/ros/disconnect` | main.py | 断开 ROS Bridge |
| GET | `/api/ros/status` | main.py | ROS 连接状态 |
| GET | `/api/ros/topics` | main.py | ROS Topic 列表 |
| POST | `/api/ros/subscribe` | main.py | 订阅 ROS Topic |
| WS | `/api/ros/ws` | main.py | ROS 实时数据 WebSocket |
| POST | `/api/uav/upload/init` | main.py | UAV 上传初始化 |
| PATCH | `/api/uav/upload/chunk/{id}` | main.py | 分块上传 |
| POST | `/api/uav/upload/complete/{id}` | main.py | 上传完成校验 |
| POST | `/api/uav/devices/{id}/manifest` | main.py | 设备文件清单上报 |
| POST | `/api/uav/devices/{id}/pull-start` | main.py | 拉取任务下发 |
| POST | `/api/uav/devices/{id}/pull-ack` | main.py | 拉取确认 |

---

## 4. 道路病害预测完整流程

整个预测流程的核心文件是 `modules/pci.py`（生产模块），其实现了基于 ASTM D6433-23 的路面性能分析引擎。

### 4.1 数据流转总览

```
无人机航拍图像
    │
    ▼
YOLO 病害检测 (hobot_dnn_modified)
    │
    ▼
JSON 记录 (bbox列表 + GPS坐标 + 病害类型)
    │
    ▼
data_loader.py → records_store (内存字典)
    │
    ▼
用户在前端绘制路段 → POST /api/analysis/assess
    │
    ▼
analysis_router.py:
  1. 规范化路段参数 (_merge_analysis_parameters)
  2. 匹配路段范围内病害记录 (_build_distresses)
  3. BBox → 物理尺寸 (_measurement_from_bbox)
  4. 构造 DistressMeasurement 列表
    │
    ▼
modules/pci.py:
  5. PCI 计算 (PCICalculator)
  6. CDI 计算 (CDICalculator)
  7. CDI 预测 (PavementPerformanceModel.formula_1)
  8. SAWI 预警 (PavementPerformanceModel.formula_2)
    │
    ▼
返回 JSON: {PCI, CDI, predicted_CDI, SAWI, risk_level, status, color}
```

### 4.2 数据结构

#### 4.2.1 病害类型枚举 `DistressType`

| 枚举值 | 中文名 | 描述 |
|--------|--------|------|
| `FATIGUE_CRACKING` | 疲劳裂缝 | 鳄鱼纹裂缝，结构性病害，权重最高 |
| `RUTTING` | 车辙 | 与重载交通和高温相关的永久变形 |
| `POTHOLES` | 坑洞 | 安全相关，扣分值高 |
| `LONGITUDINAL_CRACKING` | 纵向裂缝 | 沿道路方向的裂缝 |
| `TRANSVERSE_CRACKING` | 横向裂缝 | 垂直于道路方向的裂缝 |
| `BLOCK_CRACKING` | 块状裂缝 | 与温度变化相关的网状裂缝 |
| `EDGE_CRACKING` | 边缘裂缝 | 路面边缘处的裂缝 |
| `PATCHING` | 修补 | 已修补的区域 |
| `BLEEDING` | 泛油 | 功能性病害，沥青上浮 |
| `RAVELING` | 松散/剥落 | 表面集料脱落 |

#### 4.2.2 严重等级枚举 `SeverityLevel`

| 等级 | 值 | 对计算的影响 |
|------|-----|-------------|
| `LOW` | `"L"` | 严重度系数 0.5 |
| `MEDIUM` | `"M"` | 严重度系数 1.0 |
| `HIGH` | `"H"` | 严重度系数 1.5 |

#### 4.2.3 病害测量 `DistressMeasurement`

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `distress_type` | DistressType | 必填 | 病害类型 |
| `severity` | SeverityLevel | 必填 | 严重等级 |
| `quantity` | float | 必填 | 测量值（面积 m² / 长度 m / 计数） |
| `unit` | str | 必填 | 单位：`"area"` / `"length"` / `"count"` |
| `sample_unit_area` | float | 232.0 | 样本单元面积(m²)，ASTM 标准 2500 ft² |

#### 4.2.4 路段参数 `PavementSection`

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `section_id` | str | 必填 | 路段唯一标识 |
| `length` | float | 必填 | 路段长度 (m) |
| `width` | float | 必填 | 路段宽度 (m) |
| `surface_type` | str | `"AC"` | 路面类型（AC=沥青混凝土, PCC=水泥混凝土） |
| `construction_year` | int | 2020 | 建成年份 |
| `last_maintenance_year` | int | 2020 | 最近养护年份 |
| `asphalt_thickness` | float | 0.15 | 沥青层厚度 (m)，默认 15cm |
| `base_thickness` | float | 0.30 | 基层厚度 (m)，默认 30cm |
| `subgrade_modulus` | float | 50.0 | 路基回弹模量 (MPa) |
| `aadtt` | float | 2.0 | 年平均日货车交通量 (**千辆/天**)，手动设置常量 |
| `traffic_growth_rate` | float | 0.02 | 交通增长率（默认 2%/年） |
| `lane_distribution_factor` | float | 0.8 | 车道分配系数 |

**计算属性**: `total_area = length × width` （路段总面积 m²）

---

### 4.3 PCI 计算流程（路面状况指数）

PCI 是 ASTM D6433-23 标准的核心指标，取值范围 0-100，值越高表示路面状况越好。

#### 第 1 步：计算病害密度

每种病害首先计算其在样本单元中的密度百分比：

- **面积型病害**（裂缝、坑洞、车辙等）：
  ```
  density = (quantity / sample_unit_area) × 100
  ```
- **长度型病害**（纵向裂缝、横向裂缝、边缘裂缝）：
  ```
  density = (quantity / √sample_unit_area) × 100
  ```
  其中 `√232 ≈ 15.23m` 为特征样本单元长度。

**参数说明**:
- `quantity`: 从 YOLO bbox 转换的物理尺寸（面积 m² 或长度 m）
- `sample_unit_area`: 固定为 232 m²（对应 ASTM 标准的 2500 平方英尺）

#### 第 2 步：计算扣减值 (Deduct Value)

对每种病害，使用三次多项式曲线计算扣减值：

```
DV = a × D³ + b × D² + c × D
```

其中 D 为密度百分比，a/b/c 为根据不同病害类型和严重等级预校准的曲线参数。

扣减值被限制在 `[0, max_dv]` 范围内。

**各病害类型的扣减曲线参数表**：

| 病害类型 | 严重度 | a | b | c | 最大扣减值 |
|----------|--------|-----|-----|----|-----------|
| FATIGUE_CRACKING | LOW | 0.001 | -0.025 | 2.05 | 25 |
| FATIGUE_CRACKING | MEDIUM | 0.002 | -0.03 | 2.8 | 45 |
| FATIGUE_CRACKING | HIGH | 0.003 | -0.04 | 3.5 | 65 |
| RUTTING | LOW | 0.0008 | -0.02 | 1.5 | 20 |
| RUTTING | MEDIUM | 0.0015 | -0.025 | 2.2 | 35 |
| RUTTING | HIGH | 0.002 | -0.03 | 2.8 | 50 |
| POTHOLES | LOW | 0.002 | -0.03 | 2.5 | 30 |
| POTHOLES | MEDIUM | 0.003 | -0.04 | 3.5 | 50 |
| POTHOLES | HIGH | 0.004 | -0.05 | 4.5 | 70 |
| LONGITUDINAL_CRACKING | LOW | 0.0005 | -0.015 | 1.2 | 18 |
| LONGITUDINAL_CRACKING | MEDIUM | 0.001 | -0.02 | 1.8 | 30 |
| LONGITUDINAL_CRACKING | HIGH | 0.0015 | -0.025 | 2.3 | 40 |
| TRANSVERSE_CRACKING | LOW | 0.0005 | -0.015 | 1.2 | 18 |
| TRANSVERSE_CRACKING | MEDIUM | 0.001 | -0.02 | 1.8 | 30 |
| TRANSVERSE_CRACKING | HIGH | 0.0015 | -0.025 | 2.3 | 40 |
| BLOCK_CRACKING | LOW | 0.0006 | -0.018 | 1.4 | 20 |
| BLOCK_CRACKING | MEDIUM | 0.0012 | -0.024 | 2.0 | 32 |
| BLOCK_CRACKING | HIGH | 0.0018 | -0.03 | 2.6 | 45 |
| EDGE_CRACKING | LOW | 0.0004 | -0.012 | 1.0 | 15 |
| EDGE_CRACKING | MEDIUM | 0.0008 | -0.016 | 1.5 | 25 |
| EDGE_CRACKING | HIGH | 0.0012 | -0.02 | 2.0 | 35 |
| PATCHING | LOW | 0.0006 | -0.015 | 1.3 | 20 |
| PATCHING | MEDIUM | 0.001 | -0.02 | 1.9 | 32 |
| PATCHING | HIGH | 0.0015 | -0.025 | 2.4 | 42 |
| BLEEDING | LOW | 0.0003 | -0.01 | 0.8 | 12 |
| BLEEDING | MEDIUM | 0.0006 | -0.012 | 1.2 | 20 |
| BLEEDING | HIGH | 0.001 | -0.015 | 1.6 | 28 |
| RAVELING | LOW | 0.0004 | -0.012 | 1.0 | 15 |
| RAVELING | MEDIUM | 0.0008 | -0.016 | 1.5 | 25 |
| RAVELING | HIGH | 0.0012 | -0.02 | 2.0 | 35 |

**回退曲线**（未知病害类型）：`{a:0.001, b:-0.02, c:1.5, max_dv:30}`

#### 第 3 步：计算修正扣减值 (Corrected Deduct Value, CDV)

当存在多种病害时，ASTM D6433 使用 CDV 方法修正边际递减效应：

1. 将所有扣减值按降序排列
2. 根据最高扣减值确定允许的最大扣减项数 m：

   | 最高 DV | 允许项数 m |
   |---------|-----------|
   | ≥ 50 | 1 |
   | ≥ 40 | 2 |
   | ≥ 30 | 3 |
   | ≥ 20 | 4 |
   | < 20 | 5 |

3. 取前 m 个扣减值求和：`total_dv = sum(dv[0:m])`
4. 应用修正系数：

   ```
   若 m = 1:  CDV = total_dv
   若 m ≥ 2:  correction_factor = 1 - 0.05 × (m - 1)
              CDV = 100 - (100 - total_dv) × correction_factor
   ```

5. 裁剪至 `[0, 100]`

**参数说明**:
- `correction_factor`: 每多一个病害项，修正系数递减 0.05，体现边际效应递减规律

#### 第 4 步：得出 PCI

```
PCI = 100 - CDV
```

**PCI 评级标准（ASTM D6433 七级）**:

| PCI 范围 | 等级 | 建议措施 |
|----------|------|----------|
| 86 - 100 | Good（良好） | 常规监测 |
| 71 - 85 | Satisfactory（满意） | 预防性维护 |
| 56 - 70 | Fair（一般） | 小修 |
| 41 - 55 | Poor（较差） | 大修或罩面 |
| 26 - 40 | Very Poor（很差） | 结构重建 |
| 11 - 25 | Serious（严重） | 需要重建 |
| 0 - 10 | Failed（完全损坏） | 立即重建 |

---

### 4.4 CDI 计算流程（综合病害指数）

CDI 是对 PCI 的增强，额外考虑结构性病害的权重差异和时间衰减影响。

#### 结构性病害权重

不同病害类型对结构安全的影响不同，CDI 采用差异化的权重系数：

| 病害类型 | 权重 | 理由 |
|----------|------|------|
| FATIGUE_CRACKING | **1.5** | 结构性，与重载交通直接相关 |
| POTHOLES | **1.4** | 安全和结构双重问题 |
| RUTTING | **1.3** | 结构性变形 |
| LONGITUDINAL_CRACKING | 1.0 | 基准权重 |
| TRANSVERSE_CRACKING | 0.9 | - |
| EDGE_CRACKING | 0.9 | - |
| BLOCK_CRACKING | 0.8 | 主要由温度引起 |
| PATCHING | 0.7 | 维护痕迹 |
| RAVELING | 0.6 | 表面退化 |
| BLEEDING | 0.4 | 功能性问题 |

#### 加权病害得分

```
对每种病害：
  severity_factor = {LOW: 0.5, MEDIUM: 1.0, HIGH: 1.5}
  weighted_score = density × weight × severity_factor

total_weighted_score = sum(所有病害的 weighted_score)
normalized_score = min(100, (total_weighted_score / 50) × 100)
```

**参数说明**:
- `density`: 病害密度百分比（来自 DistressMeasurement.calculate_density()）
- `weight`: 结构权重（上表），区分结构性与功能性病害
- `severity_factor`: 严重度放大系数
- `50`: 假设的最大合理密度基准值，用于归一化到 0-100 范围

#### 从 PCI 计算 CDI

```
structural_penalty = normalized_score × 0.1
CDI = PCI - structural_penalty
```

CDI 限制在 `[0, 100]`。

**参数说明**:
- `structural_penalty`: 结构性罚分，取加权得分的 10%，确保 CDI ≤ PCI

#### CDI 直接计算（不依赖 PCI）

```
CDI = 100 - normalized_score
```

---

### 4.5 公式 1：CDI 退化预测（交通荷载驱动）

#### 公式

```
结构数 SN = a1 × D1 + a2 × D2 × m2

ΔCDI = β_t × AADTT^1.2 × Δt / √SN × β_c

CDI_future = CDI_current - ΔCDI
```

#### 参数详解

| 参数 | 符号 | 默认值 | 说明 |
|------|------|--------|------|
| 沥青层厚度 | D1 | 0.15 m | 通过 `asphalt_thickness` 配置 |
| 基层厚度 | D2 | 0.30 m | 通过 `base_thickness` 配置 |
| 沥青层系数 | a1 | 0.44 /inch | AASHTO 标准沥青层结构系数 |
| 基层系数 | a2 | 0.14 /inch | AASHTO 标准粒料基层结构系数 |
| 排水系数 | m2 | 1.0 | 良好排水条件 |
| 结构数 | SN | 计算值 | 综合反映路面结构承载能力。默认 4.5（二级公路标准），限制在 [3.0, 6.0] |
| 交通损伤系数 | β_t | 0.12 | 基于 LTPP 实测数据校准的经验系数 |
| 气候系数 | β_c | 1.0 | 中纬度湿润地区默认值 |
| 日均货车交通量 | AADTT | 2.0 | **千辆/天**。参考值：高速 5-8，国道 3-5，省道 1.5-3，县道 < 1 |
| 预测年限 | Δt | 3.0 | 通过 `prediction_years` 配置 |
| 交通量指数 | 1.2 | - | 交通量对损伤的幂指数关系 |
| 结构数指数 | 0.5 | - | 结构数取平方根（√SN），体现路面结构的非线性退化特征 |

**厚度单位转换**：米转英寸 = × 39.37（1 m = 39.37 inch）

#### 物理含义

公式 1 描述的是：路面在交通荷载反复作用下，CDI 随时间的退化过程。退化速率取决于三个因素：
1. **交通量**（AADTT^1.2）：交通量越大，退化越快
2. **路面结构强度**（√SN）：结构越强，退化越慢
3. **环境因素**（β_c）：气候条件对退化的放大效应

公式 1 的结果用于：
- 预测未来 CDI 值
- 判断是否触发维护建议（CDI < 70 时标记维护触发）
- 在地图上渲染预测状况颜色

---

### 4.6 公式 2：SAWI 计算（结构异常预警指数）

#### 公式

```
SAWI = ΔPCI_observed / (k_pci × AADTT × Δt)
```

其中：
```
expected_pci_drop = k_pci × AADTT × Δt
SAWI = observed_pci_drop / expected_pci_drop
```

#### 参数详解

| 参数 | 符号 | 默认值 | 说明 |
|------|------|--------|------|
| 实测 PCI 下降 | ΔPCI_observed | 通过 `observed_pci_drop` 配置，默认 5.0 | 两次检测之间的实际 PCI 变化值 |
| 观测周期 | Δt | 通过 `observed_years` 配置，默认 1.0 | 两次检测的时间间隔（年） |
| 校准退化率 | k_pci | 3.0 | 基于 LTPP 数据库校准的 PCI 退化速率常数 |
| 日均货车交通量 | AADTT | 2.0 | 与公式 1 同义，千辆/天 |

#### 风险等级判定

| SAWI 范围 | 风险等级 | 含义 | 建议措施 |
|-----------|----------|------|----------|
| ≤ 1.0 | **NORMAL** | 病害发展符合交通量预期，属于正常磨损 | 继续常规监测，按计划维护 |
| 1.0 - 1.5 | **WARNING** | 病害超前发展，可能存在隐蔽风险（排水失效、基层弱化） | 增加监测频率，进行 FWD 弯沉检测 |
| > 1.5 | **CRITICAL** | 存在极高风险，可能地基塌陷、深层脱空 | 立即限制通行，进行 GPR 雷达扫描和钻芯验证 |

#### 物理含义

SAWI 的核心思想是：**将实测 PCI 下降速率与基于交通量的预期下降速率进行比较**。

- 如果 SAWI ≈ 1.0：病害按照交通荷载预期的节奏发展，正常
- 如果 SAWI > 1.0：病害发展快于预期，可能存在交通量之外的原因（结构缺陷、排水问题、施工质量问题）
- 如果 SAWI > 1.5：严重异常，可能存在深层结构失效

**边界情况**：
- 如果预期下降 = 0（无交通量）且实测下降 > 0：`sawi = inf`，触发 CRITICAL 预警
- 如果实测下降 = 0 且预期下降 > 0：`sawi = 0`，正常状态

---

### 4.7 从原始 BBox 到计算输入

这是连接 YOLO 检测结果和 PCI 计算引擎的关键转换步骤：

#### 步骤 1: BBox 像素 → 物理尺寸

```python
物理宽度(m)  = bbox_宽度(px) × pixel_to_meter
物理高度(m)  = bbox_高度(px) × pixel_to_meter
```

**参数说明**:
- `pixel_to_meter`: 像素到米的缩放系数，默认 0.01 m/px（即 1 像素 = 1 cm）
- 该系数取决于无人机飞行高度和相机参数，可通过分析参数面板调整

#### 步骤 2: 确定计量单位

- **长度型病害**（LONGITUDINAL_CRACKING, TRANSVERSE_CRACKING, EDGE_CRACKING）：取较长边 × pixel_to_meter，单位 `"length"`
- **面积型病害**（其余类型）：宽 × 高 × pixel_to_meter²，单位 `"area"`

#### 步骤 3: 构造测量对象

```python
DistressMeasurement(
    distress_type = 类型映射[病害类型字符串],
    severity = 默认严重度表[病害类型],
    quantity = 物理尺寸,
    unit = "area" | "length",
    sample_unit_area = section_area_m2  # 实际路段面积
)
```

**病害类型映射**：`RECORD_TYPE_TO_DISTRESS` 字典将前端字符串（`"fatigue_cracking"`, `"potholes"` 等）映射到 `DistressType` 枚举。

**默认严重度赋值**：每种病害类型预设一个默认严重度等级：
- HIGH: 疲劳裂缝、坑洞（结构性高风险病害）
- MEDIUM: 车辙、纵向裂缝、横向裂缝、块状裂缝、边缘裂缝、松散/剥落
- LOW: 修补、泛油

---

### 4.8 路段匹配逻辑

`POST /api/analysis/assess` 的评估对象是 **路段 + 病害记录** 的组合。病害记录通过前端交互标记与路段关联（`record_ids` 参数），系统并不自动按地理位置进行空间匹配。路段的核心作用是为 PCI 计算提供 **样本单元面积**（`sample_unit_area = length × width`）。

---

## 5. 坐标系统

### 转换链

```
Pixhawk/M9N GPS (WGS84) → geo_utils.coordinate_converter() → 高德底图 (GCJ-02)
```

### 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `_COORD_A` | 6378245.0 | 椭球长半轴 (m) |
| `_COORD_EE` | 0.00669342162296594323 | 椭球偏心率平方 |
| 中国境内判定 | 73.66 < lon < 135.05 & 3.86 < lat < 53.55 | 境外坐标不做 GCJ-02 偏移 |

### 实现

`modules/geo_utils.py` 提供 `coordinate_converter(lat, lon, target_sys="GCJ02")` 函数：
- `target_sys="GCJ02"`：WGS84 → GCJ-02
- `target_sys="WGS84"`：返回原始坐标
- 非中国境内坐标不做转换

---

## 6. 配置系统

`config/settings.py` 定义全局配置，所有列表/字典对象在内存中是可变的，支持运行时覆写。

### 可配置项

| 配置 | 类型 | 说明 |
|------|------|------|
| `DEFAULT_LOCATION` | [lat, lon] | 地图默认中心点（北京 39.90, 116.41） |
| `MAP_TYPES` | List[dict] | 高德地图瓦片配置（标准/卫星/地形） |
| `DISEASE_TYPES` | List[dict] | 病害类型列表 |
| `ANALYSIS_INSTANCE_DEFAULTS` | dict | 分析参数默认值（15 项） |
| `ANALYSIS_PARAM_SCHEMA` | List[dict] | 前端参数面板元数据 |
| `ANALYSIS_RESULT_SCHEMA` | List[dict] | 计算结果字段元数据 |
| `ANALYSIS_THRESHOLDS` | dict | 状态渲染阈值 |
| `ANALYSIS_STATUS_COLORS` | dict | 状态 RGBA 颜色 |

### 运行时覆写

`PUT /api/system/settings` → `_apply_settings_overrides(payload, persist=True)` → 内存对象 + 写入 `settings_runtime_override.json`
启动时通过 `_load_settings_overrides()` 加载。

---

## 7. 共享状态

`modules/app_state.py` 集中管理应用级全局状态，避免散布在 main.py 中的全局变量：

| 变量 | 类型 | 说明 |
|------|------|------|
| `records_store` | Dict | 所有病害记录缓存（key=文件名stem） |
| `ros_manager` | ROSManager | ROS 桥接管理器单例 |
| `upload_sessions` | Dict | UAV 分块上传会话 |
| `upload_lock` | Lock | 上传操作互斥锁 |
| `device_manifests` | Dict | 设备文件清单 |
| `device_pull_tasks` | Dict | 设备拉取任务队列 |
| `settings_lock` | Lock | 设置写操作互斥锁 |

---

## 8. ROS 桥接

`modules/ros_manager.py` 封装 roslibpy，提供：

- **引用计数订阅**：多个 WebSocket 客户端共享同一 ROS Topic，`unsubscribe_topic` 仅在引用计数归零时真正断开
- **消息缓存**：`data_cache` 字典存储最新消息帧，`get_frame()` 无锁快读
- **自省 API**：`get_topics_with_types()`, `get_topic_type()`, `get_topic_types()`

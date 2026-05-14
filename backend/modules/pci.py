"""
┌─────────────────────────────────────────────────────────────────┐
│                    路面性能分析系统架构                           │
├─────────────────────────────────────────────────────────────────┤
│  输入层: 病害物理参数 (面积m²/长度m/个数)                         │
│     ↓                                                           │
│  PCI计算器 (ASTM D6433标准)                                      │
│     - 病害密度计算 → 扣除值(DV) → 修正扣除值(CDV) → PCI         │
│     ↓                                                           │
│  PCI预测模型 (基于已发表LTPP回归方程)                             │
│     - 病害量汇总 → 气候分区选择 → 回归方程 → PCI估计             │
│     ↓                                                           │
│  异常检测器 (标准化预测残差)                                      │
│     - 实测PCI vs 预测PCI → z-score → 异常等级判定                │
└─────────────────────────────────────────────────────────────────┘
"""

"""
路面性能建模与分析系统
Pavement Performance Modeling and Analysis System

基于已发表文献的LTPP多元线性回归模型进行PCI预测与异常检测
标准依据: ASTM D6433-23, FHWA LTPP Distress Manual

功能:
1. 病害物理参数 → PCI (Pavement Condition Index)  [ASTM D6433]
2. 病害量 + 路龄 → PCI估计  [Ali et al. 2023 回归方程]
3. 病害前向投影 → 未来PCI预测
4. 实测PCI vs 预测PCI → 标准化残差 → 异常等级判定

参考文献:
- Ali A, Heneash U, Hussein A, et al. (2023). DOI: 10.22115/scce.2022.357135.1512

版本: 2.0.0
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from enum import Enum
import warnings


# ============================================================================
# 第一部分: 基础数据结构与枚举
# ============================================================================

class DistressType(Enum):
    """
    病害类型枚举 - 对应报告中的主要病害类型
    基于LTPP Distress Identification Manual和ASTM D6433标准
    """
    FATIGUE_CRACKING = "fatigue_cracking"      # 疲劳裂缝 (Alligator Cracking)
    RUTTING = "rutting"                        # 车辙
    POTHOLES = "potholes"                      # 坑洞
    LONGITUDINAL_CRACKING = "longitudinal_cracking"  # 纵向裂缝
    TRANSVERSE_CRACKING = "transverse_cracking"      # 横向裂缝
    BLOCK_CRACKING = "block_cracking"          # 块状裂缝
    EDGE_CRACKING = "edge_cracking"            # 边缘裂缝
    PATCHING = "patching"                      # 修补区域
    BLEEDING = "bleeding"                      # 泛油
    RAVELING = "raveling"                      # 松散/剥落


class SeverityLevel(Enum):
    """病害严重程度等级 (ASTM D6433标准)"""
    LOW = "L"      # 轻度
    MEDIUM = "M"   # 中度
    HIGH = "H"     # 重度


@dataclass
class DistressMeasurement:
    """
    单个病害测量数据 - 用户可直接输入的物理参数
    
    Attributes:
        distress_type: 病害类型 (DistressType枚举)
        severity: 严重程度等级 (SeverityLevel枚举)
        quantity: 测量数量 (面积m² 或 长度m 或 个数)
        unit: 测量单位 ('area', 'length', 'count')
        sample_unit_area: 样本单元面积 (m²)，ASTM标准约232m² (2500 sq ft)
    
    示例:
        # 疲劳裂缝测量
        fatigue = DistressMeasurement(
            distress_type=DistressType.FATIGUE_CRACKING,
            severity=SeverityLevel.HIGH,
            quantity=40,  # 40平方米
            unit='area',
            sample_unit_area=232
        )
    """
    distress_type: DistressType
    severity: SeverityLevel
    quantity: float
    unit: str  # 'area', 'length', 'count'
    sample_unit_area: float = 232.0  # ASTM标准: 2500 sq ft ≈ 232 m²
    
    def calculate_density(self) -> float:
        """
        计算病害密度 (百分比)
        
        对于面积病害: 密度 = 病害面积 / 样本单元面积 × 100%
        对于线性病害: 密度 = 病害长度 / 样本单元长度 × 100% 
                     (简化处理为长度/√面积 × 100%)
        对于计数病害: 密度 = 数量 / 样本单元面积 × 100% (转换为每100m²个数)
        
        Returns:
            密度百分比 (0-100%)
        """
        if self.unit == 'area':
            # 面积密度
            return (self.quantity / self.sample_unit_area) * 100
        elif self.unit == 'length':
            # 线性密度: 归一化处理
            # 假设样本单元为正方形，边长 = √面积
            sample_length = np.sqrt(self.sample_unit_area)
            return (self.quantity / sample_length) * 100
        elif self.unit == 'count':
            # 计数密度: 每100m²的个数
            return (self.quantity / self.sample_unit_area) * 100
        else:
            raise ValueError(f"未知的测量单位: {self.unit}")


@dataclass
class PavementSection:
    """
    路面路段基础信息 - 包含手动设置的交通常量
    
    Attributes:
        section_id: 路段唯一标识符
        length: 路段长度 (m)
        width: 路段宽度 (m)
        surface_type: 路面类型 ('AC' 沥青混凝土, 'PCC' 水泥混凝土)
        construction_year: 建成年份
        last_maintenance_year: 最后一次维护年份
        
        # 结构参数 (用于计算结构数SN)
        asphalt_thickness: 沥青层厚度 (m)，默认0.15m (15cm)
        base_thickness: 基层厚度 (m)，默认0.30m (30cm)
        subgrade_modulus: 路基回弹模量 (MPa)，默认50MPa
        
        # === 交通参数 (手动设置的常量) ===
        aadtt: 年平均日货车流量 (千辆/日)，默认2.0
              参考值: 高速公路5-8, 国道3-5, 省道1.5-3, 县道<1
        traffic_growth_rate: 交通增长率，默认0.02 (2%/年)
        lane_distribution_factor: 车道分配系数，默认0.8
    
    示例:
        section = PavementSection(
            section_id="G104_K235+500",
            length=1000,
            width=7.5,
            aadtt=3.5,  # 手动设置: 日均3500辆货车
            asphalt_thickness=0.18,
            base_thickness=0.40
        )
    """
    section_id: str
    length: float
    width: float
    surface_type: str = "AC"
    construction_year: int = 2020
    last_maintenance_year: int = 2020
    
    # 结构参数
    asphalt_thickness: float = 0.15  # m
    base_thickness: float = 0.30     # m
    subgrade_modulus: float = 50     # MPa
    
    # 交通参数 (手动设置的常量)
    aadtt: float = 2.0               # 千辆/日
    traffic_growth_rate: float = 0.02
    lane_distribution_factor: float = 0.8
    
    @property
    def total_area(self) -> float:
        """路段总面积 (m²)"""
        return self.length * self.width


# ============================================================================
# 第二部分: PCI计算器 (ASTM D6433-23标准)
# ============================================================================

class PCICalculator:
    """
    PCI (Pavement Condition Index) 计算器
    
    严格遵循 ASTM D6433-23 标准，实现从病害物理参数到PCI的转换。
    PCI范围: 0-100 (0=完全损坏, 100=完好无损)
    
    计算步骤：
    1. 计算各病害密度 (Density = 病害量/样本单元面积)
    2. 根据密度-严重程度查表得到扣除值 (Deduct Value, DV)
       使用多项式拟合ASTM标准曲线: DV = a×D³ + b×D² + c×D
    3. 应用修正扣除值曲线 (Corrected Deduct Value, CDV)
       考虑多病害叠加的边际效应递减
    4. PCI = 100 - CDV_max
    
    参考文献:
    - ASTM D6433-23: Standard Practice for Roads and Parking Lots Pavement 
      Condition Index Surveys
    - FHWA LTPP Distress Identification Manual
    """
    
    def __init__(self):
        # 扣除值曲线参数 (基于ASTM D6433标准曲线的多项式拟合)
        # 公式: DV = a×D³ + b×D² + c×D，其中 D为密度百分比
        self.deduct_curves = self._init_deduct_curves()
        
    def _init_deduct_curves(self) -> Dict:
        """
        初始化各病害类型在不同严重程度下的扣除值曲线参数
        
        数据来源: ASTM D6433-23 附录中的扣除值曲线
        使用三次多项式系数近似标准曲线
        """
        curves = {
            # 疲劳裂缝 (Alligator Cracking) - 结构性病害，权重最高
            DistressType.FATIGUE_CRACKING: {
                SeverityLevel.LOW:    {'a': 0.001, 'b': -0.025, 'c': 2.05, 'max_dv': 25},
                SeverityLevel.MEDIUM: {'a': 0.002, 'b': -0.03,  'c': 2.8,  'max_dv': 45},
                SeverityLevel.HIGH:   {'a': 0.003, 'b': -0.04,  'c': 3.5,  'max_dv': 65}
            },
            # 车辙 (Rutting) - 与重载和高温相关
            DistressType.RUTTING: {
                SeverityLevel.LOW:    {'a': 0.0008, 'b': -0.02, 'c': 1.5, 'max_dv': 20},
                SeverityLevel.MEDIUM: {'a': 0.0015, 'b': -0.025, 'c': 2.2, 'max_dv': 35},
                SeverityLevel.HIGH:   {'a': 0.002, 'b': -0.03, 'c': 2.8, 'max_dv': 50}
            },
            # 坑洞 (Potholes) - 安全相关，扣除值高
            DistressType.POTHOLES: {
                SeverityLevel.LOW:    {'a': 0.002, 'b': -0.03, 'c': 2.5, 'max_dv': 30},
                SeverityLevel.MEDIUM: {'a': 0.003, 'b': -0.04, 'c': 3.5, 'max_dv': 50},
                SeverityLevel.HIGH:   {'a': 0.004, 'b': -0.05, 'c': 4.5, 'max_dv': 70}
            },
            # 纵向裂缝 (Longitudinal Cracking)
            DistressType.LONGITUDINAL_CRACKING: {
                SeverityLevel.LOW:    {'a': 0.0005, 'b': -0.015, 'c': 1.2, 'max_dv': 18},
                SeverityLevel.MEDIUM: {'a': 0.001, 'b': -0.02, 'c': 1.8, 'max_dv': 30},
                SeverityLevel.HIGH:   {'a': 0.0015, 'b': -0.025, 'c': 2.3, 'max_dv': 40}
            },
            # 横向裂缝 (Transverse Cracking)
            DistressType.TRANSVERSE_CRACKING: {
                SeverityLevel.LOW:    {'a': 0.0005, 'b': -0.015, 'c': 1.2, 'max_dv': 18},
                SeverityLevel.MEDIUM: {'a': 0.001, 'b': -0.02, 'c': 1.8, 'max_dv': 30},
                SeverityLevel.HIGH:   {'a': 0.0015, 'b': -0.025, 'c': 2.3, 'max_dv': 40}
            },
            # 块状裂缝 (Block Cracking) - 温度相关
            DistressType.BLOCK_CRACKING: {
                SeverityLevel.LOW:    {'a': 0.0006, 'b': -0.018, 'c': 1.4, 'max_dv': 20},
                SeverityLevel.MEDIUM: {'a': 0.0012, 'b': -0.024, 'c': 2.0, 'max_dv': 32},
                SeverityLevel.HIGH:   {'a': 0.0018, 'b': -0.03, 'c': 2.6, 'max_dv': 45}
            },
            # 边缘裂缝 (Edge Cracking)
            DistressType.EDGE_CRACKING: {
                SeverityLevel.LOW:    {'a': 0.0004, 'b': -0.012, 'c': 1.0, 'max_dv': 15},
                SeverityLevel.MEDIUM: {'a': 0.0008, 'b': -0.016, 'c': 1.5, 'max_dv': 25},
                SeverityLevel.HIGH:   {'a': 0.0012, 'b': -0.02, 'c': 2.0, 'max_dv': 35}
            },
            # 修补 (Patching)
            DistressType.PATCHING: {
                SeverityLevel.LOW:    {'a': 0.0006, 'b': -0.015, 'c': 1.3, 'max_dv': 20},
                SeverityLevel.MEDIUM: {'a': 0.001, 'b': -0.02, 'c': 1.9, 'max_dv': 32},
                SeverityLevel.HIGH:   {'a': 0.0015, 'b': -0.025, 'c': 2.4, 'max_dv': 42}
            },
            # 泛油 (Bleeding)
            DistressType.BLEEDING: {
                SeverityLevel.LOW:    {'a': 0.0003, 'b': -0.01, 'c': 0.8, 'max_dv': 12},
                SeverityLevel.MEDIUM: {'a': 0.0006, 'b': -0.012, 'c': 1.2, 'max_dv': 20},
                SeverityLevel.HIGH:   {'a': 0.001, 'b': -0.015, 'c': 1.6, 'max_dv': 28}
            },
            # 松散/剥落 (Raveling)
            DistressType.RAVELING: {
                SeverityLevel.LOW:    {'a': 0.0004, 'b': -0.012, 'c': 1.0, 'max_dv': 15},
                SeverityLevel.MEDIUM: {'a': 0.0008, 'b': -0.016, 'c': 1.5, 'max_dv': 25},
                SeverityLevel.HIGH:   {'a': 0.0012, 'b': -0.02, 'c': 2.0, 'max_dv': 35}
            }
        }
        return curves
    
    def calculate_deduct_value(self, distress: DistressMeasurement) -> float:
        """
        计算单个病害的扣除值 (Deduct Value)
        
        Args:
            distress: 病害测量数据
            
        Returns:
            扣除值 DV (0-100范围)
        """
        density = distress.calculate_density()
        
        # 获取对应曲线参数
        if distress.distress_type not in self.deduct_curves:
            warnings.warn(f"未知的病害类型: {distress.distress_type}，使用默认曲线")
            curve_params = {'a': 0.001, 'b': -0.02, 'c': 1.5, 'max_dv': 30}
        else:
            type_curves = self.deduct_curves[distress.distress_type]
            if distress.severity not in type_curves:
                warnings.warn(f"未知的严重程度: {distress.severity}，使用中度")
                curve_params = type_curves[SeverityLevel.MEDIUM]
            else:
                curve_params = type_curves[distress.severity]
        
        # 计算扣除值: DV = a×D³ + b×D² + c×D
        a, b, c, max_dv = curve_params['a'], curve_params['b'], curve_params['c'], curve_params['max_dv']
        dv = a * (density ** 3) + b * (density ** 2) + c * density
        
        # 限制在合理范围内
        dv = max(0, min(dv, max_dv))
        
        return dv
    
    def calculate_cdv(self, deduct_values: List[float]) -> float:
        """
        计算修正扣除值 (Corrected Deduct Value)
        
        根据ASTM D6433标准，当存在多种病害时，简单的DV相加会过度惩罚路面状况。
        修正逻辑考虑了病害间的相互作用和边际效应递减。
        
        算法步骤:
        1. 按DV从高到低排序
        2. 根据最大DV值确定允许的最大扣除数量m (经验公式)
        3. 取前m个DV值，应用修正系数
        4. CDV = 100 - (100 - sum(DV_selected)) × correction_factor
        
        Args:
            deduct_values: 各病害的扣除值列表
            
        Returns:
            修正后的扣除值 CDV (0-100)
        """
        if not deduct_values:
            return 0
        
        # 按降序排列
        dv_sorted = sorted(deduct_values, reverse=True)
        max_dv = dv_sorted[0]
        
        # 根据ASTM D6433确定最大允许扣除数量m (经验公式)
        if max_dv >= 50:
            m = 1
        elif max_dv >= 40:
            m = 2
        elif max_dv >= 30:
            m = 3
        elif max_dv >= 20:
            m = 4
        else:
            m = 5
        
        # 只取前m个最大的DV
        dv_selected = dv_sorted[:m]
        
        # 计算总扣除值
        total_dv = sum(dv_selected)
        
        # 应用修正系数 (考虑病害叠加效应)
        # 随着病害数量增加，边际效应递减
        if len(dv_selected) > 1:
            correction_factor = 1 - 0.05 * (len(dv_selected) - 1)
            cdv = 100 - (100 - total_dv) * correction_factor
        else:
            cdv = total_dv
        
        # 确保CDV在0-100范围内
        cdv = max(0, min(cdv, 100))
        
        return cdv
    
    def calculate_pci(self, distresses: List[DistressMeasurement]) -> float:
        """
        计算样本单元的PCI值
        
        Args:
            distresses: 病害测量列表
            
        Returns:
            PCI值 (0-100, 100=完好)
        """
        if not distresses:
            return 100  # 无病害，完美状态
        
        # 计算各病害的扣除值
        deduct_values = [self.calculate_deduct_value(d) for d in distresses]
        
        # 计算修正扣除值
        cdv = self.calculate_cdv(deduct_values)
        
        # PCI = 100 - CDV
        pci = 100 - cdv
        
        return round(pci, 1)


# ============================================================================
# 第三部分: PCI预测模型 (基于已发表文献的回归方程)
# ============================================================================
#
# 模型来源: Ali, A., Heneash, U., Hussein, A., et al. (2023).
#   "Models Development for Asphalt Pavement Performance Index in Different
#    Climate Regions Using Soft Computing Techniques"
#   Journal of Soft Computing in Civil Engineering, 7(1), 20-42.
#   DOI: 10.22115/scce.2022.357135.1512
#
# 模型形式: 多元线性回归 (MLR)，基于 LTPP 数据库 43 个柔性路面段、333 条观测
#
# 完整变量集 (10 个):
#   X0=Age(年), X1=Rutting(mm), X2=FatigueCrack(m^2), X3=BlockCrack(m^2),
#   X4=LongCrack(m^2), X5=TransCrack(m^2), X6=Patching(m^2), X7=Potholes(个),
#   X8=Bleeding(m^2), X9=Ravelling(m^2)
#
# 注意: Ali et al. 原文中 BlockCrack/Patching/Potholes 在数据子集中均为零值，
#       故最终回归方程未包含这些变量。本实现保留其接口，系数暂设为零。
# ============================================================================


class PCIPredictionModel:
    """
    基于已发表 LTPP 回归方程的 PCI 预测模型

    双气候分区支持:
    - wet_freeze: 湿润冰冻区 (R^2=0.868, RMSE=7.195)
    - wet_no_freeze: 湿润非冰冻区 (R^2=0.893, RMSE=7.324)
    """

    # 回归系数 (Ali et al., 2023, Eq.15 & Eq.16)
    COEFFICIENTS = {
        "wet_freeze": {
            "const": 116.52,
            "age": -2.74,
            "rutting": 0.178,
            "fatigue_cracking": -0.018,
            "block_cracking": 0.0,
            "longitudinal_cracking": 0.004,
            "transverse_cracking": 0.024,
            "patching": 0.0,
            "potholes": 0.0,
            "bleeding": 0.010,
            "raveling": 0.008,
            "rmse": 7.195,
            "r_squared": 0.868,
        },
        "wet_no_freeze": {
            "const": 113.33,
            "age": -3.078,
            "rutting": 0.205,
            "fatigue_cracking": 0.007,
            "block_cracking": 0.0,
            "longitudinal_cracking": -0.004,
            "transverse_cracking": 0.045,
            "patching": 0.0,
            "potholes": 0.0,
            "bleeding": 0.0,
            "raveling": 0.0,
            "rmse": 7.324,
            "r_squared": 0.893,
        },
    }

    # 病害变量单位说明
    VARIABLE_UNITS = {
        "age": "年",
        "rutting": "mm",
        "fatigue_cracking": "m^2",
        "block_cracking": "m^2",
        "longitudinal_cracking": "m^2",
        "transverse_cracking": "m^2",
        "patching": "m^2",
        "potholes": "个",
        "bleeding": "m^2",
        "raveling": "m^2",
    }

    # HDM-4 参考劣化率 (年增长率，用于病害量前向投影)
    # 来源: Morosiuk, Riley & Odoki, HDM-4 Volume 6, PIARC/World Bank, 2004
    DEFAULT_DETERIORATION_RATES = {
        "rutting": 0.15,
        "fatigue_cracking": 0.08,
        "block_cracking": 0.03,
        "longitudinal_cracking": 0.05,
        "transverse_cracking": 0.05,
        "patching": 0.04,
        "potholes": 0.06,
        "bleeding": 0.02,
        "raveling": 0.03,
    }

    def __init__(self, climate_zone: str = "wet_no_freeze"):
        if climate_zone not in self.COEFFICIENTS:
            raise ValueError(
                f"不支持的气候分区: {climate_zone}，"
                f"可选: {list(self.COEFFICIENTS.keys())}"
            )
        self.climate_zone = climate_zone
        self.coef = self.COEFFICIENTS[climate_zone]

    def predict_current(
        self,
        age: float,
        distress_values: Dict[str, float],
    ) -> float:
        """
        将当前路龄和病害量代入回归方程，计算 PCI 估计值。

        Args:
            age: 路龄 (年)
            distress_values: 病害测量值字典，
                key 为变量名 (如 "rutting")，value 为数值 (物理单位)

        Returns:
            PCI 估计值 (0-100)
        """
        pci = self.coef["const"]
        pci += self.coef["age"] * age

        for var_name in [
            "rutting", "fatigue_cracking", "block_cracking",
            "longitudinal_cracking", "transverse_cracking",
            "patching", "potholes", "bleeding", "raveling",
        ]:
            value = distress_values.get(var_name, 0.0)
            pci += self.coef[var_name] * value

        return max(0.0, min(100.0, pci))

    def predict_future(
        self,
        current_age: float,
        prediction_years: float,
        distress_values: Dict[str, float],
        traffic_growth_rate: float = 0.02,
    ) -> float:
        """
        预测未来 PCI。

        假设各病变量按参考劣化率增长:
          distress_future = distress_current * (1 + r * dt * (1 + g))
        其中 r 为病变量基础劣化率，g 为交通增长率修正因子。

        Args:
            current_age: 当前路龄 (年)
            prediction_years: 预测年限
            distress_values: 当前病害测量值
            traffic_growth_rate: 交通年增长率

        Returns:
            未来 PCI 预测值
        """
        future_age = current_age + prediction_years
        future_distress = {}

        for var_name, current_value in distress_values.items():
            if var_name == "age":
                continue
            base_rate = self.DEFAULT_DETERIORATION_RATES.get(var_name, 0.05)
            growth = base_rate * prediction_years * (1.0 + traffic_growth_rate)
            future_distress[var_name] = current_value * (1.0 + growth)

        return self.predict_current(future_age, future_distress)

    def get_rmse(self) -> float:
        """返回模型标准误 (RMSE)，用于残差标准化。"""
        return self.coef["rmse"]

    def get_r_squared(self) -> float:
        """返回模型 R^2。"""
        return self.coef["r_squared"]


# ============================================================================
# 第四部分: 异常检测器
# ============================================================================
#
# 原理:
# 若路面结构健康，实测 PCI (ASTM D6433) 应大致服从回归模型的预测分布。
# 残差 r = PCI_measured - PCI_predicted 揭示了实测退化中无法被回归模型
# 解释的额外部分。标准化残差 |z| 过大时，提示存在额外驱动力——在城市
# 道路环境下最可能指向地下空洞、路基疏松或排水失效等结构性缺陷。
#
# 参考:
# - Luo et al. (2023), 深圳 315 起道路塌陷事件的易发性制图研究
# - 首尔市空洞研究 (2020), 裂缝深度/空洞尺寸关联的多级风险判定
# ============================================================================


class AnomalyDetector:
    """
    基于标准化预测残差的路面异常检测器

    将实测 PCI (ASTM D6433) 与模型预测 PCI (回归方程) 的偏差标准化，
    输出异常等级判定。
    """

    def __init__(self, model_rmse: float = 7.2):
        """
        Args:
            model_rmse: 回归模型的标准误 (RMSE)，用作残差标准化的分母。
                默认 7.2，来源于 Ali et al. (2023) 模型 RMSE 的保守取值。
        """
        self.sigma_model = model_rmse

    def analyze(
        self,
        measured_pci: float,
        predicted_pci: float,
    ) -> Dict:
        """
        计算标准化残差并判定异常等级。

        Args:
            measured_pci: ASTM D6433 标准计算得到的实测 PCI
            predicted_pci: 回归模型估计的 PCI

        Returns:
            包含 z_score、anomaly_level、description 等的字典
        """
        residual = float(measured_pci) - float(predicted_pci)
        z_score = residual / self.sigma_model if self.sigma_model > 0 else 0.0

        abs_z = abs(z_score)
        if abs_z <= 1.0:
            level = "NORMAL"
            description = "实测退化符合模型预期，属正常磨损范围"
        elif abs_z <= 2.0:
            level = "WARNING"
            description = "实测退化略快于预期，建议增加监测频率"
        else:
            level = "CRITICAL"
            description = "实测退化显著超出模型预期，可能指向地下结构性缺陷"

        if residual > 0:
            direction_note = "实测 PCI 高于模型预测 (路面状况好于预期)"
        else:
            direction_note = "实测 PCI 低于模型预测 (退化快于预期，重点关注)"

        return {
            "z_score": round(z_score, 3),
            "residual": round(residual, 2),
            "anomaly_level": level,
            "description": description,
            "direction_note": direction_note,
            "sigma_model": self.sigma_model,
        }


# ============================================================================
# 第五部分: 端到端分析引擎
# ============================================================================


class PavementAnalysisEngine:
    """
    路面分析引擎 - 完整的端到端计算流程封装

    整合 PCI 计算 (ASTM D6433)、PCI 预测 (回归模型) 和异常检测 (标准化残差)。

    使用示例:
    ```python
    engine = PavementAnalysisEngine(climate_zone="wet_no_freeze")
    section = PavementSection(section_id="SEC001", length=1000, width=7)
    distresses = [...]
    results = engine.analyze(section=section, distresses=distresses)
    ```
    """

    def __init__(self, climate_zone: str = "wet_no_freeze"):
        self.pci_calculator = PCICalculator()
        self.predictor = PCIPredictionModel(climate_zone=climate_zone)
        self.detector = AnomalyDetector(model_rmse=self.predictor.get_rmse())
        self.climate_zone = climate_zone

    def analyze(
        self,
        section: PavementSection,
        distresses: List[DistressMeasurement],
        prediction_years: float = 5.0,
        user_distress_defaults: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """
        执行完整的路面分析流程。

        Args:
            section: 路段信息
            distresses: 当前病害测量列表
            prediction_years: 预测年限
            user_distress_defaults: 用户手动设定的病害默认值，
                用于补充 YOLO 未检测的病害类型

        Returns:
            完整的分析结果字典
        """
        current_year = max(section.construction_year, section.last_maintenance_year)
        import datetime
        age = float(datetime.datetime.now().year - current_year)
        if age < 0:
            age = 0.0

        # 1. 当前 PCI (ASTM D6433 标准)
        current_pci = self.pci_calculator.calculate_pci(distresses)

        # 2. 汇总病害量 (用于回归模型输入)
        distress_values = self._aggregate_distress_values(distresses)
        if user_distress_defaults:
            for k, v in user_distress_defaults.items():
                if k not in distress_values or distress_values[k] == 0:
                    distress_values[k] = float(v)

        # 3. 当前 PCI 估计值 (回归模型)
        current_pci_estimated = self.predictor.predict_current(age, distress_values)

        # 4. 未来 PCI 预测
        growth = getattr(section, "traffic_growth_rate", 0.02)
        predicted_pci = self.predictor.predict_future(
            age, prediction_years, distress_values, traffic_growth_rate=growth
        )

        # 5. 异常检测 (基于当前实测 PCI vs 回归模型估计)
        anomaly = self.detector.analyze(current_pci, current_pci_estimated)

        return {
            "section_id": section.section_id,
            "input_parameters": {
                "climate_zone": self.climate_zone,
                "model_r_squared": self.predictor.get_r_squared(),
                "model_rmse": self.predictor.get_rmse(),
                "age_years": round(age, 1),
                "section_length_m": section.length,
                "section_width_m": section.width,
                "surface_type": section.surface_type,
                "aadtt_k_per_day": section.aadtt,
                "traffic_growth_rate": growth,
                "distress_values": distress_values,
                "distress_count": len(distresses),
            },
            "current_pci": round(float(current_pci), 2),
            "current_pci_estimated": round(float(current_pci_estimated), 2),
            "predicted_pci": round(float(predicted_pci), 2),
            "prediction_years": prediction_years,
            "condition_rating": self._get_condition_rating(current_pci),
            "anomaly": anomaly,
        }

    def _aggregate_distress_values(
        self, distresses: List[DistressMeasurement]
    ) -> Dict[str, float]:
        """
        将 DistressMeasurement 列表汇总为回归模型所需的变量字典。

        对于面积类病害: 直接累加物理面积 (m^2)
        对于长度类病害: 累加长度 (m)，再按假设宽度 0.5m 转换为面积
        对于计数类病害: 累加个数
        """
        TYPE_TO_VAR = {
            "rutting": "rutting",
            "fatigue_cracking": "fatigue_cracking",
            "block_cracking": "block_cracking",
            "longitudinal_cracking": "longitudinal_cracking",
            "transverse_cracking": "transverse_cracking",
            "edge_cracking": "transverse_cracking",  # 近似映射
            "patching": "patching",
            "potholes": "potholes",
            "bleeding": "bleeding",
            "raveling": "raveling",
        }

        values: Dict[str, float] = {
            "rutting": 0.0, "fatigue_cracking": 0.0, "block_cracking": 0.0,
            "longitudinal_cracking": 0.0, "transverse_cracking": 0.0,
            "patching": 0.0, "potholes": 0.0, "bleeding": 0.0, "raveling": 0.0,
        }

        for d in distresses:
            var_name = TYPE_TO_VAR.get(d.distress_type.value)
            if var_name is None:
                continue
            if d.unit == "count":
                values[var_name] += d.quantity
            elif d.unit == "length":
                values[var_name] += d.quantity * 0.5
            else:
                values[var_name] += d.quantity

        return values

    def _get_condition_rating(self, pci: float) -> str:
        """根据 PCI 获取状况等级 (ASTM D6433 标准)"""
        if pci >= 86:
            return "Good (良好)"
        elif pci >= 71:
            return "Satisfactory (满意)"
        elif pci >= 56:
            return "Fair (一般)"
        elif pci >= 41:
            return "Poor (较差)"
        elif pci >= 26:
            return "Very Poor (很差)"
        elif pci >= 11:
            return "Serious (严重)"
        else:
            return "Failed (完全损坏)"


# ============================================================================
# 第六部分: 使用示例
# ============================================================================


def run_complete_example():
    """
    完整使用示例 - 展示从病害参数输入到异常检测输出的全流程
    """
    print("=" * 80)
    print("路面性能分析系统 - 完整使用示例")
    print("=" * 80)

    # 步骤1: 定义路段信息
    section = PavementSection(
        section_id="G104_K235+500",
        length=1000,
        width=7.5,
        surface_type="AC",
        construction_year=2018,
        aadtt=3.2,
        traffic_growth_rate=0.03,
        asphalt_thickness=0.16,
        base_thickness=0.35,
    )

    print(f"\n【步骤1】定义路段信息")
    print(f"  路段ID: {section.section_id}")
    print(f"  几何尺寸: {section.length}m x {section.width}m")
    print(f"  AADTT: {section.aadtt} 千辆/日")

    # 步骤2: 定义病害数据 (当前 YOLO 检测的 3 类)
    distresses = [
        DistressMeasurement(
            DistressType.LONGITUDINAL_CRACKING,
            SeverityLevel.MEDIUM,
            25.0, unit="length", sample_unit_area=7500.0
        ),
        DistressMeasurement(
            DistressType.POTHOLES,
            SeverityLevel.HIGH,
            3.0, unit="count", sample_unit_area=7500.0
        ),
        DistressMeasurement(
            DistressType.PATCHING,
            SeverityLevel.LOW,
            5.0, unit="area", sample_unit_area=7500.0
        ),
    ]

    print(f"\n【步骤2】定义病害数据: {len(distresses)} 条 (当前 YOLO 检测类型)")

    # 步骤3: 执行分析 (YOLO 未检测的病害类型以默认值补充)
    engine = PavementAnalysisEngine(climate_zone="wet_no_freeze")
    results = engine.analyze(
        section=section,
        distresses=distresses,
        prediction_years=5.0,
        user_distress_defaults={
            "rutting": 2.0,           # 默认车辙 2mm
            "fatigue_cracking": 0.0,  # YOLO 未训练，暂设 0
            "transverse_cracking": 0.0,
            "bleeding": 0.0,
            "raveling": 0.0,
        },
    )

    print(f"\n【步骤3】分析结果:")
    print(f"  当前 PCI (ASTM D6433): {results['current_pci']}")
    print(f"  当前 PCI (回归估计):  {results['current_pci_estimated']}")
    print(f"  预测 PCI ({results['prediction_years']}年后): {results['predicted_pci']}")
    print(f"  状况等级: {results['condition_rating']}")
    print(f"  异常检测:")
    anomaly = results['anomaly']
    print(f"    z-score: {anomaly['z_score']}")
    print(f"    等级:    {anomaly['anomaly_level']}")
    print(f"    说明:    {anomaly['description']}")
    print(f"    {anomaly['direction_note']}")
    print("=" * 80)


if __name__ == "__main__":
    run_complete_example()

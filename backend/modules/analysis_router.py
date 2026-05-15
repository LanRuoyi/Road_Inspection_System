# modules/analysis_router.py — 路面分析 API 路由

import math
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from config.settings import (
    BASE_DIR,
    DISEASE_TYPES,
    ANALYSIS_INSTANCE_DEFAULTS,
    ANALYSIS_PARAM_SCHEMA,
    ANALYSIS_RESULT_SCHEMA,
    ANALYSIS_THRESHOLDS,
    ANALYSIS_STATUS_COLORS,
)
from modules.pci import (
    DistressMeasurement,
    DistressType,
    PavementSection,
    PCICalculator,
    PCIPredictionModel,
    AnomalyDetector,
    SeverityLevel,
)
from modules.data_utils import _safe_float, _normalize_disease_type, _strip_type
from modules.app_state import records_store, _safe_json_load, _safe_json_write

router = APIRouter()

# ---- 数据模型 ----

class SegmentAssessmentPayload(BaseModel):
    instance_id: str
    points: List[List[float]] = Field(default_factory=list)
    record_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class SegmentAssessmentRequest(BaseModel):
    segments: List[SegmentAssessmentPayload]


class AnalysisInstancesUpdateRequest(BaseModel):
    instances: List[Dict[str, Any]] = Field(default_factory=list)


class AnalysisInstancesDeleteRequest(BaseModel):
    instance_ids: List[str] = Field(default_factory=list)


# ---- 全局状态 ----

ANALYSIS_INSTANCE_STORE_PATH = BASE_DIR / "data" / "analysis" / "instances.json"
analysis_instance_lock = Lock()
analysis_instances_store: List[Dict[str, Any]] = []

pci_calculator = PCICalculator()

# 预测模型实例按需创建 (气候分区来自请求参数)
_predictor_cache: Dict[str, PCIPredictionModel] = {}
_detector_cache: Dict[str, AnomalyDetector] = {}

def _get_predictor(climate_zone: str) -> PCIPredictionModel:
    if climate_zone not in _predictor_cache:
        _predictor_cache[climate_zone] = PCIPredictionModel(climate_zone=climate_zone)
    return _predictor_cache[climate_zone]

def _get_detector(predictor: PCIPredictionModel) -> AnomalyDetector:
    key = predictor.climate_zone
    if key not in _detector_cache:
        _detector_cache[key] = AnomalyDetector(model_rmse=predictor.get_rmse())
    return _detector_cache[key]

SUPPORTED_DISTRESS_VALUES = {
    item.get("value")
    for item in DISEASE_TYPES
    if isinstance(item, dict) and item.get("value") and item.get("value") != "all"
}

RECORD_TYPE_TO_DISTRESS = {
    "fatigue_cracking": DistressType.FATIGUE_CRACKING,
    "potholes": DistressType.POTHOLES,
    "rutting": DistressType.RUTTING,
    "longitudinal_cracking": DistressType.LONGITUDINAL_CRACKING,
    "transverse_cracking": DistressType.TRANSVERSE_CRACKING,
    "block_cracking": DistressType.BLOCK_CRACKING,
    "edge_cracking": DistressType.EDGE_CRACKING,
    "patching": DistressType.PATCHING,
    "bleeding": DistressType.BLEEDING,
    "raveling": DistressType.RAVELING,
}

DEFAULT_SEVERITY_BY_TYPE = {
    "fatigue_cracking": SeverityLevel.HIGH,
    "potholes": SeverityLevel.HIGH,
    "rutting": SeverityLevel.MEDIUM,
    "longitudinal_cracking": SeverityLevel.MEDIUM,
    "transverse_cracking": SeverityLevel.MEDIUM,
    "block_cracking": SeverityLevel.MEDIUM,
    "edge_cracking": SeverityLevel.MEDIUM,
    "patching": SeverityLevel.LOW,
    "bleeding": SeverityLevel.LOW,
    "raveling": SeverityLevel.MEDIUM,
}

DISTRESS_LENGTH_TYPES = {
    DistressType.LONGITUDINAL_CRACKING,
    DistressType.TRANSVERSE_CRACKING,
    DistressType.EDGE_CRACKING,
}


# ---- 辅助函数 ----

def _safe_positive_float(v: Any, default: float, min_value: float = 0.0) -> float:
    n = _safe_float(v)
    if n is None or not math.isfinite(n):
        return default
    if n < min_value:
        return default
    return float(n)


def _safe_int(v: Any, default: int, min_value: int = 0) -> int:
    try:
        n = int(v)
    except Exception:
        return default
    if n < min_value:
        return default
    return n


def _normalize_points(points: List[List[float]]) -> List[List[float]]:
    normalized = []
    for p in points:
        if not isinstance(p, list) or len(p) < 2:
            continue
        lat = _safe_float(p[0])
        lon = _safe_float(p[1])
        if lat is None or lon is None:
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        normalized.append([lat, lon])
    return normalized


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _polyline_length_m(points: List[List[float]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for idx in range(len(points) - 1):
        p1 = points[idx]
        p2 = points[idx + 1]
        total += _haversine_m(p1[0], p1[1], p2[0], p2[1])
    return total


def _distress_type_from_name(name: str) -> Optional[DistressType]:
    key = (name or "").strip().lower()
    return RECORD_TYPE_TO_DISTRESS.get(key)


def _severity_from_name(name: str) -> SeverityLevel:
    key = (name or "").strip().lower()
    return DEFAULT_SEVERITY_BY_TYPE.get(key, SeverityLevel.MEDIUM)


def _get_record_boxes(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    boxes = record.get("boxes")
    normalized: List[Dict[str, Any]] = []

    if isinstance(boxes, list):
        for item in boxes:
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            t = _normalize_disease_type(item.get("type"))
            if t not in SUPPORTED_DISTRESS_VALUES:
                continue
            normalized.append({"type": t, "bbox": bbox})

    if normalized:
        return normalized

    bbox = record.get("bbox")
    t = _normalize_disease_type(record.get("type"))
    if isinstance(bbox, list) and len(bbox) >= 4 and t in SUPPORTED_DISTRESS_VALUES:
        return [{"type": t, "bbox": bbox}]

    return []


def _measurement_from_bbox(
    distress_type: DistressType,
    severity: SeverityLevel,
    bbox: List[float],
    pixel_to_meter: float,
    sample_unit_area: float,
) -> Optional[DistressMeasurement]:
    try:
        width_px = max(0.0, float(bbox[2]))
        height_px = max(0.0, float(bbox[3]))
    except Exception:
        return None

    if width_px <= 0 or height_px <= 0:
        return None

    if distress_type in DISTRESS_LENGTH_TYPES:
        quantity = max(width_px, height_px) * pixel_to_meter
        unit = "length"
    else:
        quantity = (width_px * pixel_to_meter) * (height_px * pixel_to_meter)
        unit = "area"

    if quantity <= 0:
        return None

    return DistressMeasurement(
        distress_type=distress_type,
        severity=severity,
        quantity=max(quantity, 0.0001),
        unit=unit,
        sample_unit_area=sample_unit_area,
    )


def _build_distresses(record_ids: List[str], sample_unit_area: float, pixel_to_meter: float) -> List[DistressMeasurement]:
    distresses: List[DistressMeasurement] = []

    for record_id in record_ids:
        record = records_store.get(str(record_id))
        if not isinstance(record, dict):
            continue

        boxes = _get_record_boxes(record)
        for item in boxes:
            t = str(item.get("type") or "")
            distress_type = _distress_type_from_name(t)
            if distress_type is None:
                continue

            measurement = _measurement_from_bbox(
                distress_type=distress_type,
                severity=_severity_from_name(t),
                bbox=list(item.get("bbox") or []),
                pixel_to_meter=pixel_to_meter,
                sample_unit_area=sample_unit_area,
            )
            if measurement is not None:
                distresses.append(measurement)

    return distresses


def _merge_analysis_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(ANALYSIS_INSTANCE_DEFAULTS)
    if isinstance(parameters, dict):
        for key, value in parameters.items():
            if key in merged:
                merged[key] = value
    return merged


def _build_section(instance_id: str, points: List[List[float]], params: Dict[str, Any]) -> PavementSection:
    section_length = max(1.0, _polyline_length_m(points))
    section_width = _safe_positive_float(params.get("section_width_m"), ANALYSIS_INSTANCE_DEFAULTS["section_width_m"], 0.1)

    return PavementSection(
        section_id=instance_id,
        length=section_length,
        width=section_width,
        construction_year=_safe_int(params.get("construction_year"), ANALYSIS_INSTANCE_DEFAULTS["construction_year"], 1900),
        last_maintenance_year=_safe_int(
            params.get("last_maintenance_year"),
            ANALYSIS_INSTANCE_DEFAULTS["last_maintenance_year"],
            1900,
        ),
        asphalt_thickness=_safe_positive_float(
            params.get("asphalt_thickness_m"), ANALYSIS_INSTANCE_DEFAULTS["asphalt_thickness_m"], 0.01
        ),
        base_thickness=_safe_positive_float(
            params.get("base_thickness_m"), ANALYSIS_INSTANCE_DEFAULTS["base_thickness_m"], 0.01
        ),
        aadtt=_safe_positive_float(params.get("aadtt_k_per_day"), ANALYSIS_INSTANCE_DEFAULTS["aadtt_k_per_day"], 0),
        traffic_growth_rate=_safe_positive_float(
            params.get("traffic_growth_rate"), ANALYSIS_INSTANCE_DEFAULTS["traffic_growth_rate"], 0
        ),
        avg_lef=_safe_positive_float(
            params.get("avg_lef"), ANALYSIS_INSTANCE_DEFAULTS.get("avg_lef", 1.0), 0
        ),
        comp=_safe_positive_float(
            params.get("comp_pct"), ANALYSIS_INSTANCE_DEFAULTS.get("comp_pct", 95.0), 1.0
        ),
        defl=_safe_positive_float(
            params.get("defl_mm"), ANALYSIS_INSTANCE_DEFAULTS.get("defl_mm", 0.5), 0
        ),
        mmp=_safe_positive_float(
            params.get("mmp_mm_per_month"), ANALYSIS_INSTANCE_DEFAULTS.get("mmp_mm_per_month", 50.0), 0
        ),
    )


def _evaluate_segment(segment: SegmentAssessmentPayload) -> Dict[str, Any]:
    thresholds = dict(ANALYSIS_THRESHOLDS)
    colors = dict(ANALYSIS_STATUS_COLORS)

    merged_params = _merge_analysis_parameters(segment.parameters or {})
    points = _normalize_points(segment.points)

    matched_record_ids = [str(item) for item in dict.fromkeys(segment.record_ids or [])]
    section = _build_section(segment.instance_id, points, merged_params)
    section_area_m2 = max(1.0, float(section.total_area))

    prediction_years = _safe_positive_float(
        merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
    )
    pixel_to_meter = _safe_positive_float(
        merged_params.get("pixel_to_meter"), ANALYSIS_INSTANCE_DEFAULTS["pixel_to_meter"], 0.0001
    )

    if not matched_record_ids:
        return {
            "instance_id": segment.instance_id,
            "status": "no_data",
            "color": colors.get("no_data"),
            "matched_record_count": 0,
            "current_pci": None,
            "predicted_pci": None,
            "anomaly_z_score": None,
            "anomaly_level": "NO_DATA",
            "reasons": ["当前路段范围内无病害记录"],
            "input_snapshot": {
                "section_length_m": round(section.length, 2),
                "section_width_m": round(section.width, 2),
                "section_area_m2": round(section_area_m2, 2),
                "prediction_years": prediction_years,
                "pixel_to_meter": pixel_to_meter,
            },
        }

    sample_unit_area = section_area_m2
    distresses = _build_distresses(matched_record_ids, sample_unit_area, pixel_to_meter)

    if not distresses:
        return {
            "instance_id": segment.instance_id,
            "status": "no_data",
            "color": colors.get("no_data"),
            "matched_record_count": 0,
            "current_pci": None,
            "predicted_pci": None,
            "anomaly_z_score": None,
            "anomaly_level": "NO_DATA",
            "reasons": ["病害记录类型无法映射到分析模型"],
            "input_snapshot": {
                "section_length_m": round(section.length, 2),
                "section_width_m": round(section.width, 2),
                "section_area_m2": round(section_area_m2, 2),
                "prediction_years": prediction_years,
                "pixel_to_meter": pixel_to_meter,
            },
        }

    # 当前 PCI (ASTM D6433 标准)
    current_pci = pci_calculator.calculate_pci(distresses)

    # 构建回归模型输入
    climate_zone = str(merged_params.get("climate_zone") or ANALYSIS_INSTANCE_DEFAULTS["climate_zone"])
    predictor = _get_predictor(climate_zone)
    detector = _get_detector(predictor)

    # 汇总病害量 (使用模块级聚合函数)
    from .pci import PavementAnalysisEngine as _Engine
    distress_values = _Engine._aggregate_distress_values_static(distresses)

    # 补充 YOLO 无法检测的病害变量默认值
    # 注意: fatigue_cracking(疲劳裂缝)由 YOLO 自动检测，不设手动默认值
    for key, default_key in [
        ("rutting", "default_rutting_mm"),
        ("longitudinal_cracking", "default_longitudinal_crack_m"),
        ("transverse_cracking", "default_transverse_crack_m"),
        ("bleeding", "default_bleeding_m2"),
        ("raveling", "default_raveling_m2"),
    ]:
        if distress_values.get(key, 0) == 0:
            default_val = _safe_positive_float(
                merged_params.get(default_key),
                ANALYSIS_INSTANCE_DEFAULTS.get(default_key, 0.0),
                0
            )
            if key in ("longitudinal_cracking", "transverse_cracking"):
                # 长度类转换 (默认值单位为 m → 面积 m²，乘以假定的裂缝宽度 0.5 m)
                distress_values[key] = default_val * 0.5
            elif key == "rutting":
                # 车辙单位为 mm，直接使用
                distress_values[key] = default_val
            else:
                distress_values[key] = default_val

    # 路龄计算
    import datetime
    current_year = max(section.construction_year, section.last_maintenance_year)
    age = float(datetime.datetime.now().year - current_year)
    if age < 0:
        age = 0.0

    # 回归模型 PCI 估计
    current_pci_estimated = predictor.predict_current(age, distress_values)

    # 未来 PCI 预测 (HDM-4 增量模型推演)
    section_params = {
        "asphalt_thickness_m": float(section.asphalt_thickness),
        "base_thickness_m": float(section.base_thickness),
        "aadtt_k_per_day": float(section.aadtt),
        "avg_lef": float(getattr(section, "avg_lef", 1.0)),
        "traffic_growth_rate": float(getattr(section, "traffic_growth_rate", 0.02)),
        "comp_pct": float(getattr(section, "comp", 95.0)),
        "defl_mm": float(getattr(section, "defl", 0.5)),
        "mmp_mm_per_month": float(getattr(section, "mmp", 50.0)),
    }
    predicted_pci = predictor.predict_future(
        age, prediction_years, distress_values,
        section_params=section_params,
    )

    # 异常检测
    anomaly = detector.analyze(current_pci, current_pci_estimated)
    z_score = float(anomaly.get("z_score", 0))
    anomaly_level = str(anomaly.get("anomaly_level", "NORMAL"))

    # 状态判定
    abs_z = abs(z_score)
    healthy_pci_threshold = float(thresholds.get("healthy_pci_threshold", 60.0))
    warning_z = float(thresholds.get("anomaly_warning_z", 1.0))
    danger_z = float(thresholds.get("anomaly_danger_z", 2.0))

    reasons = []
    if abs_z > danger_z:
        status = "danger"
        reasons.append(f"异常退化指数 |z|={abs_z:.2f} 超过危险阈值 {danger_z}")
    elif abs_z > warning_z or predicted_pci < healthy_pci_threshold:
        status = "warning"
        if abs_z > warning_z:
            reasons.append(f"异常退化指数 |z|={abs_z:.2f} 超过警告阈值 {warning_z}")
        if predicted_pci < healthy_pci_threshold:
            reasons.append(f"预测 PCI={predicted_pci:.1f} 将在 {prediction_years} 年内跌破 {healthy_pci_threshold}")
    else:
        status = "healthy"
        reasons.append("PCI 和异常退化指数均在正常范围")

    return {
        "instance_id": segment.instance_id,
        "status": status,
        "color": colors.get(status, colors.get("warning")),
        "matched_record_count": len(matched_record_ids),
        "current_pci": round(float(current_pci), 2),
        "predicted_pci": round(float(predicted_pci), 2),
        "anomaly_z_score": round(z_score, 3),
        "anomaly_level": anomaly_level,
        "anomaly_detail": anomaly,
        "reasons": reasons,
        "input_snapshot": {
            "section_length_m": round(section.length, 2),
            "section_width_m": round(section.width, 2),
            "section_area_m2": round(section_area_m2, 2),
            "climate_zone": climate_zone,
            "age_years": round(age, 1),
            "prediction_years": prediction_years,
            "aadtt_k_per_day": round(float(section.aadtt), 4),
            "traffic_growth_rate": round(float(getattr(section, "traffic_growth_rate", 0.02)), 4),
            "avg_lef": round(float(getattr(section, "avg_lef", 1.0)), 4),
            "asphalt_thickness_m": round(float(section.asphalt_thickness), 3),
            "base_thickness_m": round(float(section.base_thickness), 3),
            "comp_pct": round(float(getattr(section, "comp", 95.0)), 1),
            "defl_mm": round(float(getattr(section, "defl", 0.5)), 2),
            "mmp_mm_per_month": round(float(getattr(section, "mmp", 50.0)), 1),
            "pixel_to_meter": pixel_to_meter,
            "distress_values": {k: round(v, 4) for k, v in distress_values.items()},
        },
    }


def _sanitize_analysis_instance(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    instance_id = str(item.get("id") or "").strip()
    if not instance_id:
        return None

    points_raw = item.get("points")
    if not isinstance(points_raw, list):
        points_raw = []

    points = []
    for p in points_raw:
        if not isinstance(p, dict):
            continue
        lat = _safe_float(p.get("lat"))
        lon = _safe_float(p.get("lon"))
        if lat is None or lon is None:
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        points.append({
            "id": str(p.get("id") or f"{instance_id}_{len(points)}"),
            "lat": lat,
            "lon": lon,
        })

    if not points:
        return None

    parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
    status = str(item.get("status") or "no_data")
    color = str(item.get("color") or ANALYSIS_STATUS_COLORS.get("no_data", "rgba(128, 128, 128, 0.35)"))
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else None

    return {
        "id": instance_id,
        "points": points,
        "parameters": parameters,
        "status": status,
        "color": color,
        "metrics": metrics,
    }


def _load_analysis_instances_from_disk() -> None:
    global analysis_instances_store
    raw = _safe_json_load(ANALYSIS_INSTANCE_STORE_PATH, [])
    sanitized = []
    if isinstance(raw, list):
        for item in raw:
            normalized = _sanitize_analysis_instance(item)
            if normalized is not None:
                sanitized.append(normalized)
    with analysis_instance_lock:
        analysis_instances_store = sanitized
    if not ANALYSIS_INSTANCE_STORE_PATH.exists():
        _safe_json_write(ANALYSIS_INSTANCE_STORE_PATH, sanitized)


def _save_analysis_instances_to_disk(instances: List[Dict[str, Any]]) -> None:
    _safe_json_write(ANALYSIS_INSTANCE_STORE_PATH, instances)


# ---- API 端点 ----

@router.get("/api/analysis/config")
async def get_analysis_config():
    return {
        "instance_defaults": ANALYSIS_INSTANCE_DEFAULTS,
        "param_schema": ANALYSIS_PARAM_SCHEMA,
        "result_schema": ANALYSIS_RESULT_SCHEMA,
        "thresholds": ANALYSIS_THRESHOLDS,
        "status_colors": ANALYSIS_STATUS_COLORS,
    }


@router.get("/api/analysis/instances")
async def get_analysis_instances():
    with analysis_instance_lock:
        instances = deepcopy(analysis_instances_store)
    return {
        "count": len(instances),
        "instances": instances,
        "store_path": str(ANALYSIS_INSTANCE_STORE_PATH),
    }


@router.put("/api/analysis/instances")
async def put_analysis_instances(request: AnalysisInstancesUpdateRequest):
    sanitized = []
    for item in request.instances:
        normalized = _sanitize_analysis_instance(item)
        if normalized is not None:
            sanitized.append(normalized)

    with analysis_instance_lock:
        global analysis_instances_store
        analysis_instances_store = sanitized
        _save_analysis_instances_to_disk(analysis_instances_store)

    return {
        "ok": True,
        "count": len(sanitized),
        "store_path": str(ANALYSIS_INSTANCE_STORE_PATH),
    }


@router.delete("/api/analysis/instances")
async def delete_analysis_instances(request: AnalysisInstancesDeleteRequest = Body(default=AnalysisInstancesDeleteRequest())):
    target_ids = {str(item).strip() for item in request.instance_ids if str(item).strip()}
    if not target_ids:
        raise HTTPException(status_code=400, detail="instance_ids is required and must not be empty")

    return {
        "ok": True,
        "count": remain_count,
        "store_path": str(ANALYSIS_INSTANCE_STORE_PATH),
    }


@router.post("/api/analysis/assess")
async def assess_analysis_segments(request: SegmentAssessmentRequest):
    results = []
    for segment in request.segments:
        try:
            results.append(_evaluate_segment(segment))
        except Exception as exc:
            results.append(
                {
                    "instance_id": segment.instance_id,
                    "status": "warning",
                    "color": ANALYSIS_STATUS_COLORS.get("warning"),
                    "matched_record_count": 0,
                    "current_pci": None,
                    "predicted_pci": None,
                    "anomaly_z_score": None,
                    "anomaly_level": "ERROR",
                    "reasons": [f"评估失败: {exc}"],
                }
            )

    return {
        "thresholds": ANALYSIS_THRESHOLDS,
        "status_colors": ANALYSIS_STATUS_COLORS,
        "results": results,
    }

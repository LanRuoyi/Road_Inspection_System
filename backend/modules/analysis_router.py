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
    PavementPerformanceModel,
    PavementSection,
    PCICalculator,
    CDICalculator,
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
cdi_calculator = CDICalculator()

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
        surface_type=str(params.get("surface_type") or ANALYSIS_INSTANCE_DEFAULTS["surface_type"]),
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
        subgrade_modulus=_safe_positive_float(
            params.get("subgrade_modulus_mpa"), ANALYSIS_INSTANCE_DEFAULTS["subgrade_modulus_mpa"], 1
        ),
        aadtt=_safe_positive_float(params.get("aadtt_k_per_day"), ANALYSIS_INSTANCE_DEFAULTS["aadtt_k_per_day"], 0.01),
        traffic_growth_rate=_safe_positive_float(
            params.get("traffic_growth_rate"), ANALYSIS_INSTANCE_DEFAULTS["traffic_growth_rate"], 0
        ),
        lane_distribution_factor=_safe_positive_float(
            params.get("lane_distribution_factor"), ANALYSIS_INSTANCE_DEFAULTS["lane_distribution_factor"], 0.01
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

    if not matched_record_ids:
        return {
            "instance_id": segment.instance_id,
            "status": "no_data",
            "color": colors.get("no_data"),
            "matched_record_count": 0,
            "current_pci": None,
            "current_cdi": None,
            "predicted_pci": None,
            "predicted_cdi": None,
            "sawi": None,
            "sawi_risk_level": "NO_DATA",
            "reasons": ["当前路段范围内无病害记录"],
            "input_snapshot": {
                "section_length_m": round(section.length, 2),
                "section_width_m": round(section.width, 2),
                "section_area_m2": round(section_area_m2, 2),
                "prediction_years": _safe_positive_float(
                    merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
                ),
                "pixel_to_meter": _safe_positive_float(
                    merged_params.get("pixel_to_meter"), ANALYSIS_INSTANCE_DEFAULTS["pixel_to_meter"], 0.0001
                ),
            },
        }

    pixel_to_meter = _safe_positive_float(
        merged_params.get("pixel_to_meter"), ANALYSIS_INSTANCE_DEFAULTS["pixel_to_meter"], 0.0001
    )
    sample_unit_area = section_area_m2
    distresses = _build_distresses(matched_record_ids, sample_unit_area, pixel_to_meter)

    if not distresses:
        return {
            "instance_id": segment.instance_id,
            "status": "no_data",
            "color": colors.get("no_data"),
            "matched_record_count": 0,
            "current_pci": None,
            "current_cdi": None,
            "predicted_pci": None,
            "predicted_cdi": None,
            "sawi": None,
            "sawi_risk_level": "NO_DATA",
            "reasons": ["病害记录类型无法映射到分析模型"],
            "input_snapshot": {
                "section_length_m": round(section.length, 2),
                "section_width_m": round(section.width, 2),
                "section_area_m2": round(section_area_m2, 2),
                "prediction_years": _safe_positive_float(
                    merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
                ),
                "pixel_to_meter": pixel_to_meter,
            },
        }

    prediction_years = _safe_positive_float(
        merged_params.get("prediction_years"), ANALYSIS_INSTANCE_DEFAULTS["prediction_years"], 0
    )
    observed_pci_drop = _safe_positive_float(
        merged_params.get("observed_pci_drop"), ANALYSIS_INSTANCE_DEFAULTS["observed_pci_drop"], 0
    )
    observed_years = _safe_positive_float(
        merged_params.get("observed_years"), ANALYSIS_INSTANCE_DEFAULTS["observed_years"], 0.1
    )

    current_pci = pci_calculator.calculate_pci(distresses)
    current_cdi = cdi_calculator.calculate_cdi_from_pci(current_pci, distresses)

    model = PavementPerformanceModel(section)
    predicted_cdi = model.formula_1_predict_cdi(current_cdi, prediction_years)
    predicted_pci = predicted_cdi

    sawi_result = model.formula_2_sawi(observed_pci_drop, observed_years)
    sawi = float(sawi_result.get("sawi", 0))

    status = "warning"
    reasons = []
    if sawi > float(thresholds.get("sawi_danger_threshold", 1.5)):
        status = "danger"
        reasons.append("SAWI 超过危险阈值")
    elif predicted_pci < float(thresholds.get("prediction_pci_warning_threshold", 70.0)):
        status = "warning"
        reasons.append("预测PCI将在设定年限内跌破阈值")
    elif (
        current_pci > float(thresholds.get("healthy_pci_threshold", 70.0))
        and sawi <= float(thresholds.get("sawi_normal_max", 1.0))
    ):
        status = "healthy"
        reasons.append("PCI 高于阈值且 SAWI 处于正常范围")
    else:
        status = "warning"
        reasons.append("当前指标处于临界区间，建议关注")

    return {
        "instance_id": segment.instance_id,
        "status": status,
        "color": colors.get(status, colors.get("warning")),
        "matched_record_count": len(matched_record_ids),
        "current_pci": round(float(current_pci), 2),
        "current_cdi": round(float(current_cdi), 2),
        "predicted_pci": round(float(predicted_pci), 2),
        "predicted_cdi": round(float(predicted_cdi), 2),
        "sawi": round(float(sawi), 3),
        "sawi_risk_level": sawi_result.get("risk_level"),
        "reasons": reasons,
        "risk_detail": sawi_result,
        "input_snapshot": {
            "section_length_m": round(section.length, 2),
            "section_width_m": round(section.width, 2),
            "section_area_m2": round(section_area_m2, 2),
            "prediction_years": prediction_years,
            "aadtt_k_per_day": round(float(section.aadtt), 4),
            "pixel_to_meter": pixel_to_meter,
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
                    "current_cdi": None,
                    "predicted_pci": None,
                    "predicted_cdi": None,
                    "sawi": None,
                    "sawi_risk_level": "ERROR",
                    "reasons": [f"评估失败: {exc}"],
                }
            )

    return {
        "thresholds": ANALYSIS_THRESHOLDS,
        "status_colors": ANALYSIS_STATUS_COLORS,
        "results": results,
    }

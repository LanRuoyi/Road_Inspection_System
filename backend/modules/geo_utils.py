# modules/geo_utils.py — 坐标转换工具

import math

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


def coordinate_converter(lat, lon, target_sys="GCJ02"):
    """WGS84→GCJ-02 坐标转换入口，用于在高德底图上正确落点。"""
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

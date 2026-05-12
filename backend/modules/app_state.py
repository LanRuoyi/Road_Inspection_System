# modules/app_state.py — 应用级共享状态

import os
import json
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

from config.settings import BASE_DIR, DATA_PATH
from modules.data_loader import load_disease_records
from modules.ros_manager import ROSManager

SETTINGS_OVERRIDE_PATH = BASE_DIR / "config" / "settings_runtime_override.json"
UPLOAD_TMP_DIR = DATA_PATH.parent / "upload_tmp"
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)

records_store: Dict[str, Dict[str, Any]] = {}
ros_manager = ROSManager()
upload_sessions: Dict[str, Dict[str, Any]] = {}
upload_lock = Lock()
device_manifests: Dict[str, Dict[str, Any]] = {}
device_pull_tasks: Dict[str, List[str]] = {}
settings_lock = Lock()


def init_data():
    try:
        raw_data = load_disease_records(DATA_PATH)
    except Exception as e:
        print(f"init_data failed: {e}")
        raw_data = []

    records_store.clear()
    for item in raw_data:
        try:
            file_id = os.path.basename(item["img_path"]).split(".")[0]
            records_store[file_id] = item
        except Exception:
            continue


def _safe_json_load(path: Path, default_value: Any) -> Any:
    if not path.exists():
        return deepcopy(default_value)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return deepcopy(default_value)


def _safe_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)

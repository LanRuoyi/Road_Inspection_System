import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class StatusStore:
    """持久化采集/上传状态，供采集节点与上传节点共享。"""

    def __init__(self, status_file: Path):
        self.status_file = Path(status_file)
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.status_file.exists():
            self._write({"version": 1, "updated_at": self._now_iso(), "items": {}})

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "items" not in data:
                    data["items"] = {}
                return data
        except Exception:
            return {"version": 1, "updated_at": self._now_iso(), "items": {}}

    def _write(self, data: Dict[str, Any]) -> None:
        temp_file = self.status_file.with_suffix(self.status_file.suffix + ".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.replace(self.status_file)

    def upsert_item(self, item_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            items = data["items"]
            old = items.get(item_id, {})
            merged = {**old, **payload}
            merged["item_id"] = item_id
            merged["updated_at"] = self._now_iso()
            items[item_id] = merged
            data["updated_at"] = self._now_iso()
            self._write(data)

    def set_state(self, item_id: str, state: str, extra: Optional[Dict[str, Any]] = None) -> None:
        extra = extra or {}
        self.upsert_item(item_id, {"state": state, **extra})

    def list_items(self, states: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            items = list(data.get("items", {}).values())
        if states:
            state_set = set(states)
            items = [x for x in items if x.get("state") in state_set]
        items.sort(key=lambda x: x.get("created_at", ""))
        return items

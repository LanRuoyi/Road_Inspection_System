import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

import requests
import rclpy
from rclpy.node import Node

from .status_store import StatusStore


class UploaderNode(Node):
    """支持实时与批量两种模式的回传节点，带断点续传。"""

    def __init__(self):
        super().__init__("uploader_node")

        self.records_dir = Path(self.declare_parameter(
            "records_dir",
            str(Path(__file__).resolve().parent.parent.parent / "backend" / "data" / "records"),
        ).value).expanduser().resolve()
        self.status_file = Path(self.declare_parameter(
            "status_file",
            str(self.records_dir / "status_index.json"),
        ).value).expanduser().resolve()

        self.upload_mode = self.declare_parameter("upload_mode", "realtime").value  # realtime|batch
        self.scan_interval_s = float(self.declare_parameter("scan_interval_s", 3.0).value)
        self.device_id = self.declare_parameter("device_id", "rdk_x5_01").value
        self.manifest_sync_interval_s = float(self.declare_parameter("manifest_sync_interval_s", 5.0).value)
        self.chunk_size = int(self.declare_parameter("chunk_size", 262144).value)
        self.backend_base_url = self.declare_parameter("backend_base_url", "http://127.0.0.1:8000").value.rstrip("/")
        self.delete_after_upload = bool(self.declare_parameter("delete_after_upload", False).value)
        self.http_timeout_s = float(self.declare_parameter("http_timeout_s", 8.0).value)

        self.store = StatusStore(self.status_file)
        self.session = requests.Session()
        self._last_manifest_sync_sec = 0.0

        self.create_timer(self.scan_interval_s, self.scan_timer_callback)

        self.get_logger().info(
            f"Uploader started | mode={self.upload_mode} backend={self.backend_base_url} status={self.status_file} device={self.device_id}"
        )

    def scan_timer_callback(self):
        now_sec = self.get_clock().now().nanoseconds / 1e9
        if (now_sec - self._last_manifest_sync_sec) >= self.manifest_sync_interval_s:
            self._push_manifest()
            self._last_manifest_sync_sec = now_sec

        if self.upload_mode == "pull":
            self._run_pull_mode()
            return

        states = ["pending_upload", "upload_failed"]
        items = self.store.list_items(states=states)
        if not items:
            return

        if self.upload_mode == "realtime":
            self._upload_item(items[0])
            return

        for item in items:
            self._upload_item(item)

    def _run_pull_mode(self):
        try:
            url = f"{self.backend_base_url}/api/uav/devices/{self.device_id}/pull-tasks"
            resp = self.session.get(url, timeout=self.http_timeout_s)
            resp.raise_for_status()
            data = resp.json()
            target_ids = list(data.get("item_ids", []))
        except Exception as e:
            self.get_logger().warning(f"poll pull tasks failed: {e}")
            return

        if not target_ids:
            return

        for item_id in target_ids:
            item = self._get_item_by_id(item_id)
            if item is None:
                continue
            self._upload_item(item)

        try:
            ack_url = f"{self.backend_base_url}/api/uav/devices/{self.device_id}/pull-ack"
            self.session.post(ack_url, json={"item_ids": target_ids}, timeout=self.http_timeout_s)
        except Exception:
            pass

    def _get_item_by_id(self, item_id: str):
        items = self.store.list_items(states=None)
        for item in items:
            if item.get("item_id") == item_id:
                return item
        return None

    def _push_manifest(self):
        items = self.store.list_items(states=None)
        manifest_items = []
        for item in items:
            manifest_items.append({
                "item_id": item.get("item_id"),
                "state": item.get("state"),
                "created_at": item.get("created_at"),
                "image_path": item.get("image_path"),
                "json_path": item.get("json_path"),
            })

        url = f"{self.backend_base_url}/api/uav/devices/{self.device_id}/manifest"
        payload = {
            "device_id": self.device_id,
            "items": manifest_items,
        }
        try:
            resp = self.session.post(url, json=payload, timeout=self.http_timeout_s)
            resp.raise_for_status()
        except Exception as e:
            self.get_logger().warning(f"push manifest failed: {e}")

    def _upload_item(self, item: Dict[str, Any]):
        item_id = item.get("item_id")
        if not item_id:
            return

        image_path = Path(item.get("image_path", ""))
        json_path = Path(item.get("json_path", ""))

        if (not image_path.exists()) or (not json_path.exists()):
            self.store.set_state(item_id, "missing", {
                "last_error": "image or json missing",
            })
            return

        self.store.set_state(item_id, "uploading")

        try:
            upload_id = self._init_upload(item_id, image_path)
            offset = self._query_offset(upload_id)
            self._send_chunks(upload_id, image_path, offset)
            self._complete_upload(upload_id, item_id, image_path, json_path)

            extra = {
                "uploaded_at": self._now_iso(),
                "last_error": "",
            }

            if self.delete_after_upload:
                self._safe_remove(image_path)
                self._safe_remove(json_path)
                extra["deleted_at"] = self._now_iso()
                self.store.set_state(item_id, "uploaded_deleted", extra)
            else:
                self.store.set_state(item_id, "uploaded", extra)

            self.get_logger().info(f"uploaded: {item_id}")

        except Exception as e:
            attempts = int(item.get("upload_attempts", 0)) + 1
            self.store.set_state(item_id, "upload_failed", {
                "upload_attempts": attempts,
                "last_error": str(e),
            })
            self.get_logger().warning(f"upload failed: {item_id}, err={e}")

    def _now_iso(self) -> str:
        import datetime
        return datetime.datetime.utcnow().isoformat() + "Z"

    def _sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    def _init_upload(self, item_id: str, image_path: Path) -> str:
        url = f"{self.backend_base_url}/api/uav/upload/init"
        payload = {
            "item_id": item_id,
            "file_name": image_path.name,
            "file_size": image_path.stat().st_size,
            "file_sha256": self._sha256_file(image_path),
        }
        resp = self.session.post(url, json=payload, timeout=self.http_timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return data["upload_id"]

    def _query_offset(self, upload_id: str) -> int:
        url = f"{self.backend_base_url}/api/uav/upload/status/{upload_id}"
        resp = self.session.get(url, timeout=self.http_timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return int(data.get("received_size", 0))

    def _send_chunks(self, upload_id: str, image_path: Path, offset: int):
        url = f"{self.backend_base_url}/api/uav/upload/chunk/{upload_id}"
        total = image_path.stat().st_size
        if offset > total:
            offset = 0

        with open(image_path, "rb") as f:
            f.seek(offset)
            current = offset
            while current < total:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                resp = self.session.patch(
                    url,
                    params={"offset": current},
                    data=chunk,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=self.http_timeout_s,
                )
                if resp.status_code == 409:
                    data = resp.json()
                    if isinstance(data, dict):
                        if isinstance(data.get("detail"), dict):
                            current = int(data["detail"].get("received_size", current))
                        else:
                            current = int(data.get("received_size", current))
                    f.seek(current)
                    continue
                resp.raise_for_status()
                current += len(chunk)

    def _complete_upload(self, upload_id: str, item_id: str, image_path: Path, json_path: Path):
        with open(json_path, "r", encoding="utf-8") as f:
            json_payload = json.load(f)

        url = f"{self.backend_base_url}/api/uav/upload/complete/{upload_id}"
        payload = {
            "item_id": item_id,
            "file_name": image_path.name,
            "json_file_name": json_path.name,
            "json_payload": json_payload,
        }
        resp = self.session.post(url, json=payload, timeout=self.http_timeout_s)
        resp.raise_for_status()

    def _safe_remove(self, path: Path):
        try:
            if path.exists():
                os.remove(path)
        except Exception:
            pass


def main(args=None):
    rclpy.init(args=args)
    node = UploaderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

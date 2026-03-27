import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .status_store import StatusStore


class CaptureNode(Node):
    """按时间间隔采集图片与推理结果，统一写入状态文件。"""

    def __init__(self):
        super().__init__("capture_node")

        self.output_dir = Path(self.declare_parameter(
            "output_dir",
            str(Path(__file__).resolve().parent.parent.parent / "backend" / "data" / "records"),
        ).value).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.status_file = Path(self.declare_parameter(
            "status_file",
            str(self.output_dir / "status_index.json"),
        ).value).expanduser().resolve()
        self.capture_interval_s = float(self.declare_parameter("capture_interval_s", 2.0).value)
        self.match_tolerance_s = float(self.declare_parameter("match_tolerance_s", 0.35).value)
        self.image_buffer_size = int(self.declare_parameter("image_buffer_size", 20).value)
        self.detection_buffer_size = int(self.declare_parameter("detection_buffer_size", 40).value)
        self.image_topic = self.declare_parameter("image_topic", "/camera/image_raw").value
        self.detection_topic = self.declare_parameter("detection_topic", "/dnn_node/detections").value
        self.flight_state_topic = self.declare_parameter("flight_state_topic", "/uav/mavlink/state").value

        self.bridge = CvBridge()
        self.store = StatusStore(self.status_file)

        self._lock = threading.Lock()
        self.image_buffer = deque(maxlen=max(2, self.image_buffer_size))
        self.detection_buffer = deque(maxlen=max(2, self.detection_buffer_size))
        self.latest_detection: Dict[str, Any] = {}
        self.latest_flight_state: Dict[str, Any] = {}
        self.latest_flight_state_ns = 0
        self.last_capture_sec = 0.0

        self.create_subscription(Image, self.image_topic, self.image_callback, 10)
        self.create_subscription(String, self.detection_topic, self.detection_callback, 10)
        self.create_subscription(String, self.flight_state_topic, self.flight_state_callback, 10)

        self.create_timer(0.2, self.capture_timer_callback)

        self.get_logger().info(
            f"Capture node started | out={self.output_dir} status={self.status_file} interval={self.capture_interval_s}s "
            f"match_tol={self.match_tolerance_s}s"
        )

    @staticmethod
    def _header_to_ns(header) -> int:
        if header is None:
            return 0
        sec = int(getattr(header.stamp, "sec", 0))
        nanosec = int(getattr(header.stamp, "nanosec", 0))
        return sec * 1_000_000_000 + nanosec

    @staticmethod
    def _extract_detection_stamp_ns(payload: Dict[str, Any], fallback_ns: int) -> int:
        # 兼容几种常见推理时间戳字段命名
        if not isinstance(payload, dict):
            return fallback_ns

        stamp = payload.get("stamp")
        if isinstance(stamp, dict):
            sec = int(stamp.get("sec", 0) or 0)
            nanosec = int(stamp.get("nanosec", 0) or 0)
            ts = sec * 1_000_000_000 + nanosec
            if ts > 0:
                return ts

        header = payload.get("header")
        if isinstance(header, dict) and isinstance(header.get("stamp"), dict):
            sec = int(header["stamp"].get("sec", 0) or 0)
            nanosec = int(header["stamp"].get("nanosec", 0) or 0)
            ts = sec * 1_000_000_000 + nanosec
            if ts > 0:
                return ts

        for key in ("timestamp_ns", "ts_ns"):
            if key in payload:
                try:
                    ts = int(payload[key])
                    if ts > 0:
                        return ts
                except Exception:
                    pass

        return fallback_ns

    def image_callback(self, msg: Image):
        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warning(f"image convert failed: {e}")
            return

        image_ns = self._header_to_ns(msg.header)
        if image_ns <= 0:
            image_ns = int(self.get_clock().now().nanoseconds)

        with self._lock:
            self.image_buffer.append({
                "stamp_ns": image_ns,
                "image": image,
                "header": msg.header,
            })

    def detection_callback(self, msg: String):
        recv_ns = int(self.get_clock().now().nanoseconds)
        try:
            payload = json.loads(msg.data)
        except Exception:
            payload = {"raw": msg.data}

        det_ns = self._extract_detection_stamp_ns(payload, recv_ns)

        with self._lock:
            self.latest_detection = payload
            self.detection_buffer.append({
                "stamp_ns": det_ns,
                "payload": payload,
            })

    def flight_state_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except Exception:
            payload = {"raw": msg.data}

        with self._lock:
            self.latest_flight_state = payload
            self.latest_flight_state_ns = int(self.get_clock().now().nanoseconds)

    def _find_best_detection_for_image(self, image_stamp_ns: int):
        if not self.detection_buffer:
            return None, None

        best = None
        best_diff = None
        tol_ns = int(self.match_tolerance_s * 1_000_000_000)

        for item in self.detection_buffer:
            diff = abs(int(item.get("stamp_ns", 0)) - image_stamp_ns)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = item

        if best is None:
            return None, None

        if best_diff is not None and best_diff > tol_ns:
            return None, best_diff
        return best, best_diff

    def capture_timer_callback(self):
        now = self.get_clock().now().nanoseconds / 1e9
        if (now - self.last_capture_sec) < self.capture_interval_s:
            return

        with self._lock:
            if not self.image_buffer:
                image_item = None
            else:
                image_item = self.image_buffer[-1]
            detection_latest = self.latest_detection
            flight = self.latest_flight_state

        if image_item is None:
            return

        image = image_item["image"]
        image_header = image_item["header"]
        image_stamp_ns = int(image_item["stamp_ns"])

        with self._lock:
            matched_detection, diff_ns = self._find_best_detection_for_image(image_stamp_ns)

        if matched_detection is not None:
            detection = matched_detection["payload"]
            matched_detection_ns = int(matched_detection["stamp_ns"])
            timestamp_match = True
        else:
            detection = detection_latest
            matched_detection_ns = 0
            timestamp_match = False

        ts = datetime.now(timezone.utc)
        ts_name = ts.strftime("%Y%m%dT%H%M%S_%fZ")
        item_id = ts_name

        img_path = self.output_dir / f"{item_id}.jpg"
        json_path = self.output_dir / f"{item_id}.json"

        ok = cv2.imwrite(str(img_path), image)
        if not ok:
            self.get_logger().error(f"failed to write image: {img_path}")
            return

        record: Dict[str, Any] = {
            "id": item_id,
            "created_at": ts.isoformat(),
            "image_file": str(img_path),
            "detection": detection,
            "flight_state": flight,
            "match": {
                "timestamp_match": timestamp_match,
                "image_stamp_ns": image_stamp_ns,
                "detection_stamp_ns": matched_detection_ns,
                "abs_diff_ms": round((diff_ns or 0) / 1_000_000.0, 3),
                "tolerance_ms": round(self.match_tolerance_s * 1000.0, 3),
            },
        }

        if image_header is not None:
            record["image_stamp"] = {
                "sec": int(image_header.stamp.sec),
                "nanosec": int(image_header.stamp.nanosec),
                "frame_id": image_header.frame_id,
            }

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.get_logger().error(f"failed to write json: {json_path}, err={e}")
            return

        self.store.upsert_item(item_id, {
            "state": "pending_upload",
            "created_at": ts.isoformat(),
            "image_path": str(img_path),
            "json_path": str(json_path),
            "upload_attempts": 0,
            "last_error": "",
        })

        self.last_capture_sec = now
        self.get_logger().info(f"captured: {item_id}")


def main(args=None):
    rclpy.init(args=args)
    node = CaptureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

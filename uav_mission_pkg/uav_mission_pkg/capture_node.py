import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import cv2
import rclpy
from ai_msgs.msg import PerceptionTargets
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
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
        self.image_transport = str(self.declare_parameter("image_transport", "compressed").value).strip().lower()
        self.stats_log_interval_s = float(self.declare_parameter("stats_log_interval_s", 5.0).value)

        # 通道控制: 0 | 1 | both
        self.capture_channel = str(self.declare_parameter("capture_channel", "both").value).strip().lower()

        # 与 my_dnn_node.launch.py 对齐的双路默认话题
        image_topic_0 = self.declare_parameter("image_topic_0", "/image_0").value
        image_topic_1 = self.declare_parameter("image_topic_1", "/image_1").value
        detection_topic_0 = self.declare_parameter("detection_topic_0", "/hobot_dnn_detection").value
        detection_topic_1 = self.declare_parameter("detection_topic_1", "/hobot_dnn_detection_1").value

        # 兼容旧参数: image_topic / detection_topic 覆盖0路
        legacy_image_topic = self.declare_parameter("image_topic", "").value
        legacy_detection_topic = self.declare_parameter("detection_topic", "").value
        if legacy_image_topic:
            image_topic_0 = legacy_image_topic
        if legacy_detection_topic:
            detection_topic_0 = legacy_detection_topic

        self.channel_topics: Dict[str, Dict[str, str]] = {
            "0": {
                "image_topic": image_topic_0,
                "detection_topic": detection_topic_0,
            },
            "1": {
                "image_topic": image_topic_1,
                "detection_topic": detection_topic_1,
            },
        }

        self.active_channels = self._resolve_active_channels(self.capture_channel)
        self.flight_state_topic = self.declare_parameter("flight_state_topic", "/uav/mavlink/state").value

        self.bridge = CvBridge()
        self.store = StatusStore(self.status_file)

        self._lock = threading.Lock()
        self.channel_state: Dict[str, Dict[str, Any]] = {}
        for channel in self.active_channels:
            self.channel_state[channel] = {
                "image_buffer": deque(maxlen=max(2, self.image_buffer_size)),
                "detection_buffer": deque(maxlen=max(2, self.detection_buffer_size)),
                "latest_detection": self._default_detection_payload(),
                "last_capture_sec": 0.0,
                "image_count": 0,
                "detection_count": 0,
                "capture_count": 0,
                "last_image_ns": 0,
                "last_detection_ns": 0,
            }

        self.latest_flight_state: Dict[str, Any] = self._default_flight_state_payload()
        self.latest_flight_state_ns = 0
        self._subscriptions = []

        for channel in self.active_channels:
            image_topic = self.channel_topics[channel]["image_topic"]
            detection_topic = self.channel_topics[channel]["detection_topic"]

            self._create_image_subscriptions(channel, image_topic)
            self._subscriptions.append(
                self.create_subscription(
                    PerceptionTargets,
                    detection_topic,
                    lambda msg, ch=channel: self.detection_callback(ch, msg),
                    10,
                )
            )

        self._subscriptions.append(
            self.create_subscription(String, self.flight_state_topic, self.flight_state_callback, 10)
        )

        self.create_timer(0.2, self.capture_timer_callback)
        self.create_timer(max(1.0, self.stats_log_interval_s), self.log_stats_timer_callback)

        self.get_logger().info(
            f"Capture node started | channels={self.active_channels} out={self.output_dir} "
            f"status={self.status_file} interval={self.capture_interval_s}s match_tol={self.match_tolerance_s}s "
            f"image_transport={self.image_transport}"
        )

        for channel in self.active_channels:
            image_topic = self.channel_topics[channel]["image_topic"]
            detection_topic = self.channel_topics[channel]["detection_topic"]
            self.get_logger().info(
                f"ch{channel} topics | image={image_topic} detection={detection_topic}"
            )

    def _create_image_subscriptions(self, channel: str, image_topic: str):
        mode = self.image_transport
        if mode != "compressed":
            self.get_logger().warning(
                f"Only sensor_msgs/CompressedImage is supported, ignore image_transport={mode}"
            )
            self.image_transport = "compressed"

        self._subscriptions.append(
            self.create_subscription(
                CompressedImage,
                image_topic,
                lambda msg, ch=channel: self.image_callback_compressed(ch, msg),
                10,
            )
        )

    @staticmethod
    def _resolve_active_channels(mode: str) -> List[str]:
        m = str(mode or "").strip().strip('"\'').lower()
        if m in ("0", "channel0", "ch0", "cam0"):
            return ["0"]
        if m in ("1", "channel1", "ch1", "cam1"):
            return ["1"]
        return ["0", "1"]

    @staticmethod
    def _default_detection_payload() -> Dict[str, Any]:
        return {
            "header": {
                "stamp": {"sec": 0, "nanosec": 0},
                "frame_id": "",
            },
            "fps": 0,
            "perfs": [],
            "targets": [],
            "disappeared_targets": [],
        }

    @staticmethod
    def _default_flight_state_payload() -> Dict[str, Any]:
        return {
            "connected": False,
            "armed": False,
            "mode": "UNKNOWN",
            "system_status": 0,
            "lat": None,
            "lon": None,
            "alt_m": None,
            "local_ned": {
                "x": None,
                "y": None,
                "z": None,
            },
            "gps_fix": 0,
            "satellites": 0,
            "mission_current": None,
            "last_heartbeat_time": 0.0,
        }

    @staticmethod
    def _header_to_ns(header) -> int:
        if header is None:
            return 0
        sec = int(getattr(header.stamp, "sec", 0))
        nanosec = int(getattr(header.stamp, "nanosec", 0))
        return sec * 1_000_000_000 + nanosec

    @staticmethod
    def _time_to_ns(stamp: Any) -> int:
        sec = int(getattr(stamp, "sec", 0) or 0)
        nanosec = int(getattr(stamp, "nanosec", 0) or 0)
        return sec * 1_000_000_000 + nanosec

    @staticmethod
    def _msg_to_primitive(value: Any):
        # 将ROS消息递归转换为可JSON序列化结构
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [CaptureNode._msg_to_primitive(v) for v in value]
        if hasattr(value, "items"):
            return {str(k): CaptureNode._msg_to_primitive(v) for k, v in value.items()}
        if hasattr(value, "get_fields_and_field_types"):
            fields = {}
            for field_name in value.get_fields_and_field_types().keys():
                fields[field_name] = CaptureNode._msg_to_primitive(getattr(value, field_name))
            return fields
        return str(value)

    @staticmethod
    def _perception_to_dict(msg: PerceptionTargets) -> Dict[str, Any]:
        payload = CaptureNode._msg_to_primitive(msg)
        if not isinstance(payload, dict):
            return CaptureNode._default_detection_payload()

        payload.setdefault("header", {"stamp": {"sec": 0, "nanosec": 0}, "frame_id": ""})
        payload.setdefault("fps", 0)
        payload.setdefault("perfs", [])
        payload.setdefault("targets", [])
        payload.setdefault("disappeared_targets", [])

        targets = payload.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if isinstance(target, dict):
                    if isinstance(target.get("type"), str):
                        target["type"] = target["type"].strip()
                    rois = target.get("rois")
                    if isinstance(rois, list):
                        for roi in rois:
                            if isinstance(roi, dict) and isinstance(roi.get("type"), str):
                                roi["type"] = roi["type"].strip()
        return payload

    def _normalize_flight_state(self, payload: Any) -> Dict[str, Any]:
        result = self._default_flight_state_payload()
        if not isinstance(payload, dict):
            return result

        for key in result.keys():
            if key == "local_ned":
                local_ned = payload.get("local_ned")
                if isinstance(local_ned, dict):
                    result["local_ned"]["x"] = local_ned.get("x")
                    result["local_ned"]["y"] = local_ned.get("y")
                    result["local_ned"]["z"] = local_ned.get("z")
                continue
            if key in payload:
                result[key] = payload.get(key)

        for key, value in payload.items():
            if key not in result:
                result[key] = value
        return result

    def image_callback_compressed(self, channel: str, msg: CompressedImage):
        try:
            image = self.bridge.compressed_imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warning(f"image convert failed (ch={channel}): {e}")
            return

        image_ns = self._header_to_ns(msg.header)
        if image_ns <= 0:
            image_ns = int(self.get_clock().now().nanoseconds)

        self._store_image(channel, image_ns, msg.header, image)

    def _store_image(self, channel: str, image_ns: int, header: Any, image: Any):
        with self._lock:
            state = self.channel_state.get(channel)
            if state is None:
                return
            state["image_buffer"].append({
                "stamp_ns": image_ns,
                "image": image,
                "header": header,
            })
            state["image_count"] = int(state.get("image_count", 0)) + 1
            state["last_image_ns"] = image_ns

    def detection_callback(self, channel: str, msg: PerceptionTargets):
        payload = self._perception_to_dict(msg)
        det_ns = self._time_to_ns(msg.header.stamp)
        if det_ns <= 0:
            det_ns = int(self.get_clock().now().nanoseconds)

        with self._lock:
            state = self.channel_state.get(channel)
            if state is None:
                return
            state["latest_detection"] = payload
            state["detection_buffer"].append({
                "stamp_ns": det_ns,
                "payload": payload,
            })
            state["detection_count"] = int(state.get("detection_count", 0)) + 1
            state["last_detection_ns"] = det_ns

    def flight_state_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except Exception:
            payload = {"raw": msg.data}

        with self._lock:
            self.latest_flight_state = self._normalize_flight_state(payload)
            self.latest_flight_state_ns = int(self.get_clock().now().nanoseconds)

    def _find_best_detection_for_image(self, image_stamp_ns: int, detection_buffer: List[Dict[str, Any]]):
        if not detection_buffer:
            return None, None

        best = None
        best_diff = None
        tol_ns = int(self.match_tolerance_s * 1_000_000_000)

        for item in detection_buffer:
            diff = abs(int(item.get("stamp_ns", 0)) - image_stamp_ns)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = item

        if best is None:
            return None, None

        if best_diff is not None and best_diff > tol_ns:
            return None, best_diff
        return best, best_diff

    def _capture_one_channel(self, channel: str, now: float):
        with self._lock:
            state = self.channel_state.get(channel)
            if state is None:
                return

            if (now - float(state.get("last_capture_sec", 0.0))) < self.capture_interval_s:
                return

            image_buffer = state.get("image_buffer")
            if not image_buffer:
                return

            image_item = image_buffer[-1]
            detection_latest = state.get("latest_detection") or self._default_detection_payload()
            detection_buffer = list(state.get("detection_buffer") or [])
            flight = dict(self.latest_flight_state)

        image = image_item["image"]
        image_header = image_item["header"]
        image_stamp_ns = int(image_item["stamp_ns"])

        matched_detection, diff_ns = self._find_best_detection_for_image(image_stamp_ns, detection_buffer)

        if matched_detection is not None:
            detection = matched_detection["payload"]
            matched_detection_ns = int(matched_detection["stamp_ns"])
            timestamp_match = True
        else:
            detection = detection_latest or self._default_detection_payload()
            matched_detection_ns = 0
            timestamp_match = False

        if not isinstance(flight, dict) or not flight:
            flight = self._default_flight_state_payload()

        ts = datetime.now(timezone.utc)
        ts_name = ts.strftime("%Y%m%dT%H%M%S_%fZ")
        item_id = f"{ts_name}_ch{channel}"

        img_path = self.output_dir / f"{item_id}.jpg"
        json_path = self.output_dir / f"{item_id}.json"

        ok = cv2.imwrite(str(img_path), image)
        if not ok:
            self.get_logger().error(f"failed to write image: {img_path}")
            return

        record: Dict[str, Any] = {
            "id": item_id,
            "channel": int(channel),
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
            "source_topics": {
                "image_topic": self.channel_topics[channel]["image_topic"],
                "detection_topic": self.channel_topics[channel]["detection_topic"],
                "flight_state_topic": self.flight_state_topic,
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
            "channel": int(channel),
        })

        with self._lock:
            state = self.channel_state.get(channel)
            if state is not None:
                state["last_capture_sec"] = now
                state["capture_count"] = int(state.get("capture_count", 0)) + 1

        self.get_logger().info(f"captured: {item_id}")

    def capture_timer_callback(self):
        now = self.get_clock().now().nanoseconds / 1e9
        for channel in self.active_channels:
            self._capture_one_channel(channel, now)

    def log_stats_timer_callback(self):
        now_ns = int(self.get_clock().now().nanoseconds)
        with self._lock:
            snapshot = {
                ch: {
                    "image_count": int(st.get("image_count", 0)),
                    "detection_count": int(st.get("detection_count", 0)),
                    "capture_count": int(st.get("capture_count", 0)),
                    "last_image_ns": int(st.get("last_image_ns", 0)),
                    "last_detection_ns": int(st.get("last_detection_ns", 0)),
                }
                for ch, st in self.channel_state.items()
            }

        for channel in self.active_channels:
            st = snapshot.get(channel, {})
            image_count = int(st.get("image_count", 0))
            det_count = int(st.get("detection_count", 0))
            cap_count = int(st.get("capture_count", 0))
            last_image_ns = int(st.get("last_image_ns", 0))
            last_det_ns = int(st.get("last_detection_ns", 0))

            image_age_s = -1.0
            det_age_s = -1.0
            if last_image_ns > 0:
                image_age_s = max(0.0, (now_ns - last_image_ns) / 1_000_000_000.0)
            if last_det_ns > 0:
                det_age_s = max(0.0, (now_ns - last_det_ns) / 1_000_000_000.0)

            self.get_logger().info(
                f"ch{channel} stats | image={image_count} detection={det_count} capture={cap_count} "
                f"image_age={image_age_s:.2f}s det_age={det_age_s:.2f}s"
            )

            if image_count == 0:
                self.get_logger().warning(
                    f"ch{channel} has no image yet, check topic={self.channel_topics[channel]['image_topic']}"
                )


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

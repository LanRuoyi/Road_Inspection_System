#!/usr/bin/env python3
"""
MissionCaptureNode: 距离触发式采集节点。
- 订阅飞控位姿、相机图像、推理结果。
- 每飞行固定距离保存一张图片和对应推理结果 JSON。
- 仅负责本地落盘，回传建议独立为上传节点（README 有说明）。
"""
import json
import math
import threading
from datetime import datetime
from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String


class MissionCaptureNode(Node):
    def __init__(self):
        super().__init__("mission_capture_node")

        # 可调参数
        self.mission_id = self.declare_parameter("mission_id", "mission").value
        self.distance_step_m = float(self.declare_parameter("distance_step_m", 10.0).value)
        self.min_interval_s = float(self.declare_parameter("min_interval_s", 2.0).value)
        self.output_dir = Path(self.declare_parameter(
            "output_dir",
            str(Path(__file__).resolve().parent.parent / "backend" / "data" / "records"),
        ).value).expanduser().resolve()
        self.image_topic = self.declare_parameter("image_topic", "/camera/image_raw").value
        self.detection_topic = self.declare_parameter("detection_topic", "/dnn_node/detections").value
        self.pose_topic = self.declare_parameter("pose_topic", "/mavros/local_position/pose").value

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.bridge = CvBridge()
        self.lock = threading.Lock()
        self.seq = 0
        self.last_pose = None
        self.last_capture_time = 0.0
        self.accum_distance = 0.0
        self.latest_image = None
        self.latest_image_header = None
        self.latest_detection = None

        self.pose_sub = self.create_subscription(PoseStamped, self.pose_topic, self.pose_callback, 10)
        self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, 5)
        self.det_sub = self.create_subscription(String, self.detection_topic, self.detection_callback, 5)

        self.get_logger().info(
            f"MissionCaptureNode started | mission={self.mission_id} step={self.distance_step_m} m "
            f"out={self.output_dir} img_topic={self.image_topic} det_topic={self.detection_topic} pose_topic={self.pose_topic}"
        )

    def pose_callback(self, msg: PoseStamped):
        with self.lock:
            if self.last_pose is None:
                self.last_pose = msg
                return

            dist = self._pose_distance(self.last_pose, msg)
            self.accum_distance += dist
            self.last_pose = msg

            now_sec = self.get_clock().now().nanoseconds / 1e9
            if self.accum_distance >= self.distance_step_m and (now_sec - self.last_capture_time) >= self.min_interval_s:
                self._capture(msg, dist_travelled=self.accum_distance)
                self.accum_distance = 0.0
                self.last_capture_time = now_sec

    def image_callback(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warning(f"cv_bridge conversion failed: {e}")
            return
        with self.lock:
            self.latest_image = cv_image
            self.latest_image_header = msg.header

    def detection_callback(self, msg: String):
        # 期望为 JSON 文本；如果解析失败则原样存储字符串
        try:
            data = json.loads(msg.data)
        except Exception:
            data = {"raw": msg.data}
        with self.lock:
            self.latest_detection = data

    def _capture(self, pose_msg: PoseStamped, dist_travelled: float):
        if self.latest_image is None:
            self.get_logger().warning("Skip capture: no image available yet")
            return

        self.seq += 1
        stamp_str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        base_name = f"{self.mission_id}_{self.seq:05d}_{stamp_str}"
        img_path = self.output_dir / f"{base_name}.jpg"
        json_path = self.output_dir / f"{base_name}.json"

        # 保存图片
        try:
            cv2.imwrite(str(img_path), self.latest_image)
        except Exception as e:
            self.get_logger().error(f"Failed to save image {img_path}: {e}")
            return

        detection_payload = self.latest_detection if self.latest_detection is not None else {}

        pose = pose_msg.pose
        position = pose.position
        orientation = pose.orientation
        header = pose_msg.header
        image_header = self.latest_image_header

        record = {
            "mission_id": self.mission_id,
            "seq": self.seq,
            "stamp_iso": stamp_str,
            "pose_frame": header.frame_id,
            "position_m": {
                "x": position.x,
                "y": position.y,
                "z": position.z,
            },
            "orientation_xyzw": [orientation.x, orientation.y, orientation.z, orientation.w],
            "distance_since_last_m": round(dist_travelled, 3),
            "image_file": str(img_path),
            "detection": detection_payload,
        }

        if image_header:
            record["image_stamp"] = {
                "sec": int(image_header.stamp.sec),
                "nanosec": int(image_header.stamp.nanosec),
                "frame_id": image_header.frame_id,
            }

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.get_logger().error(f"Failed to save json {json_path}: {e}")
            return

        self.get_logger().info(f"Captured seq={self.seq} dist={dist_travelled:.2f}m -> {img_path.name}")

    @staticmethod
    def _pose_distance(p1: PoseStamped, p2: PoseStamped) -> float:
        dx = p2.pose.position.x - p1.pose.position.x
        dy = p2.pose.position.y - p1.pose.position.y
        dz = p2.pose.position.z - p1.pose.position.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)


def main(args=None):
    rclpy.init(args=args)
    node = MissionCaptureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

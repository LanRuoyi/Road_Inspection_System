import json
import threading
import time
from typing import Any, Dict

import rclpy
from geometry_msgs.msg import PoseStamped
from pymavlink import mavutil
from rclpy.node import Node
from std_msgs.msg import String


class MAVLinkBridgeNode(Node):
    """串口唯一拥有者：负责 MAVLink 读写，其他节点通过 ROS 话题交互。"""

    def __init__(self):
        super().__init__("mavlink_bridge_node")

        self.serial_port = self.declare_parameter("serial_port", "/dev/ttyS3").value
        self.baudrate = int(self.declare_parameter("baudrate", 57600).value)
        self.source_system = int(self.declare_parameter("source_system", 245).value)
        self.heartbeat_timeout_s = float(self.declare_parameter("heartbeat_timeout_s", 5.0).value)

        self.state_pub = self.create_publisher(String, "/uav/mavlink/state", 10)
        self.pose_pub = self.create_publisher(PoseStamped, "/uav/mavlink/local_pose", 20)
        self.command_sub = self.create_subscription(String, "/uav/mavlink/command", self.command_callback, 20)

        self.master = None
        self.master_lock = threading.Lock()

        self.state: Dict[str, Any] = {
            "connected": False,
            "armed": False,
            "mode": "UNKNOWN",
            "system_status": 0,
            "lat": None,
            "lon": None,
            "alt_m": None,
            "local_ned": {"x": None, "y": None, "z": None},
            "gps_fix": 0,
            "satellites": 0,
            "mission_current": None,
            "last_heartbeat_time": 0.0,
        }

        self._connect()

        self.create_timer(0.02, self.read_timer_callback)
        self.create_timer(1.0, self.publish_state_timer_callback)
        self.create_timer(2.0, self.health_timer_callback)

    def _connect(self):
        try:
            self.get_logger().info(f"Connecting MAVLink serial {self.serial_port} @ {self.baudrate} ...")
            master = mavutil.mavlink_connection(
                self.serial_port,
                baud=self.baudrate,
                source_system=self.source_system,
                autoreconnect=True,
            )
            master.wait_heartbeat(timeout=self.heartbeat_timeout_s)
            with self.master_lock:
                self.master = master
            self.state["connected"] = True
            self.state["last_heartbeat_time"] = time.time()
            self.get_logger().info("MAVLink connected")
        except Exception as e:
            self.state["connected"] = False
            self.get_logger().error(f"MAVLink connect failed: {e}")

    def _disconnect(self):
        with self.master_lock:
            if self.master is not None:
                try:
                    self.master.close()
                except Exception:
                    pass
                self.master = None
        self.state["connected"] = False

    def health_timer_callback(self):
        now = time.time()
        last_hb = float(self.state.get("last_heartbeat_time") or 0.0)

        if not self.state.get("connected", False):
            self._connect()
            return

        if last_hb > 0 and (now - last_hb) > (self.heartbeat_timeout_s * 2.0):
            self.get_logger().warning("Heartbeat timeout, reconnecting MAVLink ...")
            self._disconnect()
            self._connect()

    def publish_state_timer_callback(self):
        msg = String()
        msg.data = json.dumps(self.state, ensure_ascii=False)
        self.state_pub.publish(msg)

    def read_timer_callback(self):
        with self.master_lock:
            master = self.master

        if master is None:
            return

        # 每个周期尽量多取几帧，降低队列堆积
        for _ in range(20):
            try:
                m = master.recv_match(blocking=False)
            except Exception:
                return
            if m is None:
                return
            self._handle_message(m)

    def _handle_message(self, m):
        msg_type = m.get_type()

        if msg_type == "HEARTBEAT":
            self.state["last_heartbeat_time"] = time.time()
            self.state["armed"] = bool(m.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            try:
                self.state["mode"] = mavutil.mode_string_v10(m)
            except Exception:
                self.state["mode"] = "UNKNOWN"
            self.state["system_status"] = int(m.system_status)
            self.state["connected"] = True

        elif msg_type == "GLOBAL_POSITION_INT":
            self.state["lat"] = float(m.lat) / 1e7
            self.state["lon"] = float(m.lon) / 1e7
            self.state["alt_m"] = float(m.relative_alt) / 1000.0

        elif msg_type == "GPS_RAW_INT":
            self.state["gps_fix"] = int(m.fix_type)
            self.state["satellites"] = int(getattr(m, "satellites_visible", 0))

        elif msg_type == "MISSION_CURRENT":
            self.state["mission_current"] = int(m.seq)

        elif msg_type == "LOCAL_POSITION_NED":
            x = float(m.x)
            y = float(m.y)
            z = float(m.z)
            self.state["local_ned"] = {"x": x, "y": y, "z": z}

            pose_msg = PoseStamped()
            pose_msg.header.stamp = self.get_clock().now().to_msg()
            pose_msg.header.frame_id = "local_ned"
            pose_msg.pose.position.x = x
            pose_msg.pose.position.y = y
            pose_msg.pose.position.z = z
            pose_msg.pose.orientation.w = 1.0
            self.pose_pub.publish(pose_msg)

    def command_callback(self, msg: String):
        with self.master_lock:
            master = self.master

        if master is None:
            self.get_logger().warning("Ignore command: MAVLink not connected")
            return

        try:
            payload = json.loads(msg.data)
        except Exception as e:
            self.get_logger().warning(f"Invalid command json: {e}")
            return

        action = (payload.get("action") or "").strip().lower()
        if not action:
            return

        try:
            if action == "arm":
                arm_value = 1 if payload.get("value", True) else 0
                master.mav.command_long_send(
                    master.target_system,
                    master.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0,
                    float(arm_value),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                )

            elif action == "set_mode":
                mode_name = (payload.get("mode") or "GUIDED").upper()
                mode_map = master.mode_mapping()
                if mode_name not in mode_map:
                    self.get_logger().warning(f"Mode not supported: {mode_name}")
                    return
                master.set_mode(mode_map[mode_name])

            elif action == "set_position_ned":
                x = float(payload.get("x", 0.0))
                y = float(payload.get("y", 0.0))
                z = float(payload.get("z", 0.0))
                yaw = float(payload.get("yaw", 0.0))
                type_mask = int(
                    mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
                )
                master.mav.set_position_target_local_ned_send(
                    0,
                    master.target_system,
                    master.target_component,
                    mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                    type_mask,
                    x,
                    y,
                    z,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    yaw,
                    0,
                )

            elif action == "set_velocity_ned":
                vx = float(payload.get("vx", 0.0))
                vy = float(payload.get("vy", 0.0))
                vz = float(payload.get("vz", 0.0))
                yaw_rate = float(payload.get("yaw_rate", 0.0))
                type_mask = int(
                    mavutil.mavlink.POSITION_TARGET_TYPEMASK_X_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Y_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Z_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
                    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
                )
                master.mav.set_position_target_local_ned_send(
                    0,
                    master.target_system,
                    master.target_component,
                    mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                    type_mask,
                    0,
                    0,
                    0,
                    vx,
                    vy,
                    vz,
                    0,
                    0,
                    0,
                    0,
                    yaw_rate,
                )

            elif action == "command_long":
                command = int(payload.get("command", 0))
                params = payload.get("params", [0, 0, 0, 0, 0, 0, 0])
                params = list(params) + [0] * (7 - len(params))
                master.mav.command_long_send(
                    master.target_system,
                    master.target_component,
                    command,
                    0,
                    float(params[0]),
                    float(params[1]),
                    float(params[2]),
                    float(params[3]),
                    float(params[4]),
                    float(params[5]),
                    float(params[6]),
                )

            else:
                self.get_logger().warning(f"Unsupported action: {action}")
                return

        except Exception as e:
            self.get_logger().error(f"Send command failed ({action}): {e}")


def main(args=None):
    rclpy.init(args=args)
    node = MAVLinkBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

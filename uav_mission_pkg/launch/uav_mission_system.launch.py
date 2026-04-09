from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():
    return LaunchDescription([
        Node(
            package="uav_mission_pkg",
            executable="mavlink_bridge_node",
            name="mavlink_bridge_node",
            output="screen",
            parameters=[
                {"serial_port": ParameterValue("/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0", value_type=str)},
                {"baudrate": ParameterValue(57600, value_type=int)},
                {"source_system": ParameterValue(245, value_type=int)},
                {"source_component": ParameterValue(190, value_type=int)},
                {"heartbeat_timeout_s": ParameterValue(5.0, value_type=float)},
                {"stream_rate_hz": ParameterValue(10, value_type=int)},
            ],
        ),
        Node(
            package="uav_mission_pkg",
            executable="capture_node",
            name="capture_node",
            output="screen",
            parameters=[
                {"capture_interval_s": ParameterValue(2.0, value_type=float)},
                {"output_dir": ParameterValue("/data/records", value_type=str)},
                {"status_file": ParameterValue("/data/records/status_index.json", value_type=str)},
                {"match_tolerance_s": ParameterValue(0.35, value_type=float)},
                {"image_buffer_size": ParameterValue(20, value_type=int)},
                {"detection_buffer_size": ParameterValue(40, value_type=int)},
                {"capture_channel": ParameterValue('"0"', value_type=str)},
                {"image_transport": ParameterValue("compressed", value_type=str)},
                {"stats_log_interval_s": ParameterValue(5.0, value_type=float)},
                {"image_topic_0": ParameterValue("/image_0", value_type=str)},
                {"image_topic_1": ParameterValue("/image_1", value_type=str)},
                {"detection_topic_0": ParameterValue("/hobot_dnn_detection", value_type=str)},
                {"detection_topic_1": ParameterValue("/hobot_dnn_detection_1", value_type=str)},
                {"image_topic": ParameterValue("", value_type=str)},
                {"detection_topic": ParameterValue("", value_type=str)},
                {"flight_state_topic": ParameterValue("/uav/mavlink/state", value_type=str)},
            ],
        ),
        Node(
            package="uav_mission_pkg",
            executable="uploader_node",
            name="uploader_node",
            output="screen",
            parameters=[
                {"upload_mode": ParameterValue("pull", value_type=str)},
                {"backend_base_url": ParameterValue("http://100.99.89.17:8001", value_type=str)},
                {"delete_after_upload": ParameterValue(True, value_type=bool)},
            ],
        ),
    ])

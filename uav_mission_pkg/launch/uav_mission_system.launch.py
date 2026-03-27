from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="uav_mission_pkg",
            executable="mavlink_bridge_node",
            name="mavlink_bridge_node",
            output="screen",
        ),
        Node(
            package="uav_mission_pkg",
            executable="capture_node",
            name="capture_node",
            output="screen",
        ),
        Node(
            package="uav_mission_pkg",
            executable="uploader_node",
            name="uploader_node",
            output="screen",
        ),
    ])

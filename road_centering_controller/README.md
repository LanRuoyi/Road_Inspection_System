# road_centering_controller

ROS2 node for road-centering closed-loop control using YOLO11-seg perception output.

## Features

- Subscribes to perception result topic (`ai_msgs/msg/PerceptionTargets`)
- Extracts road mask center offset from segmentation captures
- Runs PID controller to produce body-frame lateral velocity command (`vy`)
- Adds GPS safety gate: if current GPS deviates too much from reference, command is forced to zero
- Recommended: publish velocity command JSON to `/uav/mavlink/command` and let `mavlink_bridge_node` own MAVLink serial
- Optional fallback: direct MAVLink serial output using `SET_POSITION_TARGET_LOCAL_NED`
- Key runtime parameters are configurable from launch/YAML

## Topics

- Subscribe: DNN topic (`dnn_topic`)
- Subscribe: current GPS (`gps.current_topic`, `sensor_msgs/msg/NavSatFix`)
- Subscribe: reference GPS (`gps.reference_topic`, `sensor_msgs/msg/NavSatFix`)

## MAVLink

This node sends message ID 84 (`SET_POSITION_TARGET_LOCAL_NED`) and controls only `vy` while masking other fields.

## Build

```bash
colcon build --packages-select road_centering_controller
```

## Run

```bash
ros2 launch road_centering_controller road_centering_controller.launch.py
```

Pass custom params file:

```bash
ros2 launch road_centering_controller road_centering_controller.launch.py \
  params_file:=/absolute/path/to/controller_params.yaml
```

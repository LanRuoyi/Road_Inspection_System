# uav_mission_pkg

面向你当前硬件链路（Pixhawk6C Mini + ArduPilot + RDK X5）的整合功能包，包含 3 个 ROS2 节点：

- `mavlink_bridge_node`：唯一串口读写节点（独占 MAVLink 串口），发布飞控状态，接收控制命令。
- `capture_node`：按时间间隔采集图片和推理结果，按时间戳命名，写入统一目录并维护状态文件。
- `uploader_node`：回传节点，支持实时/批量模式，带断点续传，按状态文件驱动上传与删除。

## 为什么串口必须单节点

多个节点同时打开同一个串口设备会导致：

- 字节流竞争读写，消息被抢读或拆包；
- 控制命令互相覆盖；
- 连接重连和心跳管理混乱。

建议架构：

- 只有 `mavlink_bridge_node` 访问串口。
- 其他功能包（含你的“微调位置”包）只通过 ROS 话题发命令到 `/uav/mavlink/command`，并订阅 `/uav/mavlink/state`。

## 飞控会实时给主控什么

常见 MAVLink 实时消息（本包已处理核心项）：

- `HEARTBEAT`：连接状态、飞行模式、解锁状态。
- `GLOBAL_POSITION_INT`：经纬度与相对高度。
- `LOCAL_POSITION_NED`：局部坐标（x,y,z）。
- `GPS_RAW_INT`：GPS fix、卫星数。
- `MISSION_CURRENT`：当前任务航点序号。

## 目录与状态文件

默认记录目录：`backend/data/records`。
每次采集会生成：

- `YYYYmmddTHHMMSS_microZ.jpg`
- `YYYYmmddTHHMMSS_microZ.json`

统一状态文件：`backend/data/records/status_index.json`
状态流转建议：

- `pending_upload` -> `uploading` -> `uploaded` / `uploaded_deleted`
- 异常状态：`upload_failed`、`missing`

## MAVLink 命令接口（给微调包使用）

发布到 `/uav/mavlink/command`，消息类型 `std_msgs/String`，内容为 JSON。

示例：

```json
{"action":"set_velocity_ned","vx":0.3,"vy":0.0,"vz":0.0,"yaw_rate":0.0}
```

支持动作：

- `arm`：`{"action":"arm","value":true}`
- `set_mode`：`{"action":"set_mode","mode":"GUIDED"}`
- `set_position_ned`：`{"action":"set_position_ned","x":1.0,"y":0.0,"z":-2.0,"yaw":0.0}`
- `set_velocity_ned`：`{"action":"set_velocity_ned","vx":0.2,"vy":0.0,"vz":0.0,"yaw_rate":0.0}`
- `command_long`：通用命令转发

## 回传模式

`uploader_node` 参数 `upload_mode`：

- `realtime`：每次扫描上传一个待传文件，适合边飞边回传。
- `batch`：每次扫描上传全部待传文件，适合任务结束后集中回传。

后端接口（本仓库 `backend/main.py` 已实现）：

- `POST /api/uav/upload/init`
- `GET /api/uav/upload/status/{upload_id}`
- `PATCH /api/uav/upload/chunk/{upload_id}?offset=...`
- `POST /api/uav/upload/complete/{upload_id}`

## 构建与运行

```bash
# 在 ROS2 工作区
colcon build --packages-select uav_mission_pkg
source install/setup.bash

# 启动整套节点
ros2 launch uav_mission_pkg uav_mission_system.launch.py
```

可按需覆盖参数：

```bash
ros2 run uav_mission_pkg mavlink_bridge_node --ros-args -p serial_port:=/dev/ttyS3 -p baudrate:=57600
ros2 run uav_mission_pkg capture_node --ros-args -p capture_interval_s:=2.0 -p output_dir:=/data/records
ros2 run uav_mission_pkg uploader_node --ros-args -p upload_mode:=batch -p backend_base_url:=http://192.168.1.10:8000 -p delete_after_upload:=true
```

## 与 Mission Planner 的关系

你当前航线规划不经过主控时，主控确实不知道“任务开始事件”。本包采用时间戳命名和统一状态文件，不依赖任务开始信号，能直接工作。
后续如果你愿意，可再增加一个“任务边界标记”节点（手动按钮/遥控通道/飞控 mode 变化触发），用于更精细的数据分组。

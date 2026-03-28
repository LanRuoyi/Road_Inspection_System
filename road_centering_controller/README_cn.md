# road_centering_controller

基于 YOLO11-seg 感知结果的道路居中控制 ROS2 节点。

## 功能概述

- 订阅分割推理结果话题（`ai_msgs/msg/PerceptionTargets`）
- 从分割掩码中估计道路中心与图像中心的偏移量
- 主路跟踪增强：以上一帧中心为先验，优先选择最近且面积大的连通域
- 遮挡鲁棒增强：开闭运算 + 连通域面积筛选 + RANSAC 道路中心线拟合
- 时序稳态增强：一阶低通滤波 + 岔路口短时冻结策略
- 使用 PID 控制器生成机体系横向速度指令 `vy`
- 引入 GPS 安全门控：当当前位置偏离参考航线过大时强制输出 `vy=0`
- 通过桥接话题 `/uav/mavlink/command` 发送控制量（推荐），由 `mavlink_bridge_node` 统一下发 MAVLink
- 可选串口直连发送（兼容模式）
- 支持通过 launch 和 YAML 参数进行自定义

## 包结构

- `src/road_centering_controller_node.cpp`：核心节点实现
- `config/controller_params.yaml`：默认参数
- `launch/road_centering_controller.launch.py`：启动文件

## 订阅话题

- 感知结果：`dnn_topic`（默认 `/hobot_dnn_detection`）
- 当前 GPS：`gps.current_topic`（默认 `/mavros/global_position/raw/fix`）
- 参考 GPS：`gps.reference_topic`（默认 `/road_centering/reference_fix`）

## 关键参数说明

### 感知相关

- `dnn_topic`：推理结果输入话题
- `road_target_type`：道路目标类型名称（用于匹配 `target.type`）
- `mask_threshold`：掩码阈值（像素值大于等于该值视为道路）
- `bottom_ratio`：用于偏移估计的图像底部区域比例

### 增强策略相关（`enhance.*`）

- `enhance.main_track_enabled`：是否启用主路跟踪
- `enhance.morph_open_radius`：开运算半径（去除小噪点）
- `enhance.morph_close_radius`：闭运算半径（填补小空洞）
- `enhance.min_component_area`：连通域最小面积阈值
- `enhance.prior_max_distance_px`：与上一帧中心的最大允许偏差
- `enhance.ransac_enabled`：是否启用 RANSAC 中心线拟合
- `enhance.ransac_iterations`：RANSAC 迭代次数
- `enhance.ransac_inlier_threshold_px`：RANSAC 内点阈值（像素）
- `enhance.ransac_min_inliers`：RANSAC 最小内点数量
- `enhance.lowpass_alpha`：一阶低通滤波系数（0~1）
- `enhance.branch_freeze_s`：岔路口冻结持续时长（秒）
- `enhance.branch_ambiguity_ratio`：次大/最大连通域面积比阈值
- `enhance.branch_center_dist_px`：判定岔路分离的中心距离阈值（像素）

### 控制相关

- `control_rate_hz`：控制循环频率
- `vision_timeout_s`：视觉结果超时阈值
- `pid.kp`、`pid.ki`、`pid.kd`：PID 参数
- `pid.integral_limit`：积分限幅
- `pid.vy_limit`：`vy` 输出限幅
- `pid.invert_error_sign`：偏移符号反转开关

### GPS 安全门控

- `gps.use_safety_gate`：是否启用 GPS 安全门控
- `gps.max_deviation_m`：最大允许偏离距离（米）
- `gps.timeout_s`：GPS 数据超时阈值

### MAVLink 串口

- `mavlink.serial_enabled`：是否启用串口输出
- `mavlink.serial_port`：串口设备（默认 `/dev/ttyUSB0`）
- `mavlink.baudrate`：串口波特率（默认 `115200`）
- `mavlink.sys_id`、`mavlink.comp_id`：本节点 MAVLink 标识
- `mavlink.target_sys_id`、`mavlink.target_comp_id`：飞控目标标识
- `mavlink.body_ned_frame`：是否使用 `MAV_FRAME_BODY_NED`

### 桥接链路（推荐）

- `bridge.enabled`：是否启用桥接话题控制（默认 `true`）
- `bridge.command_topic`：桥接命令话题（默认 `/uav/mavlink/command`）

## 构建

```bash
colcon build --packages-select road_centering_controller
```

## 运行

```bash
ros2 launch road_centering_controller road_centering_controller.launch.py
```

指定自定义参数文件：

```bash
ros2 launch road_centering_controller road_centering_controller.launch.py \
  params_file:=/absolute/path/to/controller_params.yaml
```

## 调参建议

- 首先确保 `dnn_topic` 与 `road_target_type` 匹配实际推理输出
- 先调 `enhance.min_component_area` 与形态学半径，稳定道路主区域
- 再调 `enhance.lowpass_alpha` 与 `enhance.branch_freeze_s`，抑制岔路抖动
- 在遮挡场景下可适当提高 `enhance.ransac_inlier_threshold_px`
- 初期先降低 `pid.kp`，将 `pid.ki` 设小，避免振荡
- 开启 GPS 门控并设置保守的 `gps.max_deviation_m`，优先保证飞行安全
- 串口联调时先验证飞控是否正确接收 MAVLink 消息，再逐步放开 `vy_limit`

## 注意事项

- 当前实现在非 Windows 平台启用串口发送逻辑
- 若视觉结果超时或 GPS 安全门控触发，节点会自动输出零横向速度

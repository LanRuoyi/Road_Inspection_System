# MissionCaptureNode

距离触发式采集节点（ROS2，Python）。每飞行指定步长自动保存一张图片与推理结果 JSON，写入 `backend/data/records`（可通过参数修改）。本节点只负责本地落盘，实时/批量回传建议独立成上传节点，避免占用飞控带宽。

## 推荐分层
- 采集节点（本文件夹）：订阅飞控位姿、相机图像、推理结果，按距离落盘。
- 上传节点（未实现）：可选实时上传（低分辨率缩略图）或任务结束后批量上传；通过 HTTP/Tus/S3 等协议，带断点续传。

## 依赖
- ROS2 (rclpy)、cv_bridge、geometry_msgs、sensor_msgs、std_msgs。
- 相机话题：默认 `/camera/image_raw`。
- 位姿话题：默认 `/mavros/local_position/pose`（MAVLink→Mavros→PoseStamped）。
- 推理结果话题：默认 `/dnn_node/detections`，类型 `std_msgs/String`，期望 JSON 文本；解析失败则以 `{"raw": "..."}` 存储。

## 主要参数
- `mission_id`：任务名，文件名前缀。
- `distance_step_m`：触发步长，单位米，默认 10.0。
- `min_interval_s`：最小时间间隔，避免高频写盘，默认 2s。
- `output_dir`：输出目录，默认 `../backend/data/records`（相对仓库）。
- `image_topic` / `detection_topic` / `pose_topic`：可按实际话题修改。

## 运行示例
```bash
# 进入 ROS2 工作空间源环境后
ros2 run drone_capture_node mission_capture_node \
  --ros-args \
  -p mission_id:=task001 \
  -p distance_step_m:=15.0 \
  -p output_dir:=/data/records \
  -p image_topic:=/camera/image_raw \
  -p detection_topic:=/dnn_node/detections \
  -p pose_topic:=/mavros/local_position/pose
```
（如果不打算制作 ROS package，可直接 `python mission_capture_node.py`，前提是已通过 `source` 导出 ROS2 环境。）

## 数据格式
生成两类文件：
- `mission_xxxxx_00001_20260101T010203Z.jpg`
- `mission_xxxxx_00001_20260101T010203Z.json`

JSON 示例：
```json
{
  "mission_id": "task001",
  "seq": 1,
  "stamp_iso": "20260101T010203Z",
  "pose_frame": "map",
  "position_m": {"x": 1.2, "y": 3.4, "z": 10.5},
  "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
  "distance_since_last_m": 10.05,
  "image_file": "/data/records/task001_00001_20260101T010203Z.jpg",
  "detection": {"raw": "..."},
  "image_stamp": {"sec": 123, "nanosec": 456000000, "frame_id": "camera"}
}
```

## 组网建议
- 实时回传：发送压缩/缩略图到地面站，低带宽预览；全分辨率留待批量回传。
- 批量回传：任务结束后按文件名排序上传；支持断点续传（建议 Tus/S3 分片协议）。
- 清理策略：仅在收到后端校验成功后删除本地文件，或保留 manifest 作为审计/补传依据。

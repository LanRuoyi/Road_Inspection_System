#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <limits>
#include <memory>
#include <queue>
#include <string>
#include <utility>
#include <vector>

#include "ai_msgs/msg/perception_targets.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/nav_sat_fix.hpp"
#include "std_msgs/msg/string.hpp"

#ifndef _WIN32
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#endif

namespace {

constexpr double kEarthRadiusMeters = 6371000.0;
constexpr double kPi = 3.14159265358979323846;

struct Pixel {
  int x{0};
  int y{0};
};

struct Component {
  int area{0};
  double sum_x{0.0};
  double sum_y{0.0};
  std::vector<Pixel> pixels;
};

uint16_t X25CrcAccumulate(uint8_t data, uint16_t crc) {
  uint8_t tmp = data ^ static_cast<uint8_t>(crc & 0xff);
  tmp ^= (tmp << 4);
  return static_cast<uint16_t>(
      (crc >> 8) ^ (static_cast<uint16_t>(tmp) << 8) ^
      (static_cast<uint16_t>(tmp) << 3) ^ (static_cast<uint16_t>(tmp) >> 4));
}

uint16_t X25CrcCalculate(const uint8_t *buffer, size_t length) {
  uint16_t crc = 0xffff;
  for (size_t i = 0; i < length; ++i) {
    crc = X25CrcAccumulate(buffer[i], crc);
  }
  return crc;
}

double Deg2Rad(double deg) {
  return deg * kPi / 180.0;
}

double HaversineMeters(double lat1, double lon1, double lat2, double lon2) {
  const double d_lat = Deg2Rad(lat2 - lat1);
  const double d_lon = Deg2Rad(lon2 - lon1);
  const double a = std::sin(d_lat / 2.0) * std::sin(d_lat / 2.0) +
                   std::cos(Deg2Rad(lat1)) * std::cos(Deg2Rad(lat2)) *
                       std::sin(d_lon / 2.0) * std::sin(d_lon / 2.0);
  const double c = 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
  return kEarthRadiusMeters * c;
}

size_t MaskIndex(int x, int y, int width) {
  return static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(x);
}

void Dilate(const std::vector<uint8_t> &src, std::vector<uint8_t> &dst,
            int width, int height, int radius) {
  if (radius <= 0) {
    dst = src;
    return;
  }
  dst.assign(src.size(), 0);
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      bool on = false;
      const int y0 = std::max(0, y - radius);
      const int y1 = std::min(height - 1, y + radius);
      const int x0 = std::max(0, x - radius);
      const int x1 = std::min(width - 1, x + radius);
      for (int ny = y0; ny <= y1 && !on; ++ny) {
        for (int nx = x0; nx <= x1; ++nx) {
          if (src[MaskIndex(nx, ny, width)] != 0) {
            on = true;
            break;
          }
        }
      }
      if (on) {
        dst[MaskIndex(x, y, width)] = 1;
      }
    }
  }
}

void Erode(const std::vector<uint8_t> &src, std::vector<uint8_t> &dst,
           int width, int height, int radius) {
  if (radius <= 0) {
    dst = src;
    return;
  }
  dst.assign(src.size(), 0);
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      bool all_on = true;
      const int y0 = std::max(0, y - radius);
      const int y1 = std::min(height - 1, y + radius);
      const int x0 = std::max(0, x - radius);
      const int x1 = std::min(width - 1, x + radius);
      for (int ny = y0; ny <= y1 && all_on; ++ny) {
        for (int nx = x0; nx <= x1; ++nx) {
          if (src[MaskIndex(nx, ny, width)] == 0) {
            all_on = false;
            break;
          }
        }
      }
      if (all_on) {
        dst[MaskIndex(x, y, width)] = 1;
      }
    }
  }
}

void Opening(std::vector<uint8_t> &mask, int width, int height, int radius) {
  std::vector<uint8_t> tmp;
  Erode(mask, tmp, width, height, radius);
  Dilate(tmp, mask, width, height, radius);
}

void Closing(std::vector<uint8_t> &mask, int width, int height, int radius) {
  std::vector<uint8_t> tmp;
  Dilate(mask, tmp, width, height, radius);
  Erode(tmp, mask, width, height, radius);
}

std::vector<Component> ConnectedComponents8(const std::vector<uint8_t> &mask,
                                            int width, int height,
                                            int min_area) {
  std::vector<Component> components;
  std::vector<uint8_t> visited(mask.size(), 0);
  const std::array<int, 8> dx = {-1, 0, 1, -1, 1, -1, 0, 1};
  const std::array<int, 8> dy = {-1, -1, -1, 0, 0, 1, 1, 1};

  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      const size_t seed_idx = MaskIndex(x, y, width);
      if (visited[seed_idx] || mask[seed_idx] == 0) {
        continue;
      }

      Component comp;
      std::queue<Pixel> q;
      q.push({x, y});
      visited[seed_idx] = 1;

      while (!q.empty()) {
        const Pixel p = q.front();
        q.pop();
        comp.area += 1;
        comp.sum_x += static_cast<double>(p.x);
        comp.sum_y += static_cast<double>(p.y);
        comp.pixels.push_back(p);

        for (size_t k = 0; k < dx.size(); ++k) {
          const int nx = p.x + dx[k];
          const int ny = p.y + dy[k];
          if (nx < 0 || nx >= width || ny < 0 || ny >= height) {
            continue;
          }
          const size_t nidx = MaskIndex(nx, ny, width);
          if (visited[nidx] || mask[nidx] == 0) {
            continue;
          }
          visited[nidx] = 1;
          q.push({nx, ny});
        }
      }

      if (comp.area >= min_area) {
        components.emplace_back(std::move(comp));
      }
    }
  }

  return components;
}

bool FitLineLeastSquares(const std::vector<Pixel> &points, double *a, double *b) {
  if (points.size() < 2 || a == nullptr || b == nullptr) {
    return false;
  }

  double sum_y = 0.0;
  double sum_x = 0.0;
  double sum_yy = 0.0;
  double sum_yx = 0.0;
  for (const auto &p : points) {
    const double y = static_cast<double>(p.y);
    const double x = static_cast<double>(p.x);
    sum_y += y;
    sum_x += x;
    sum_yy += y * y;
    sum_yx += y * x;
  }

  const double n = static_cast<double>(points.size());
  const double denom = n * sum_yy - sum_y * sum_y;
  if (std::abs(denom) < 1e-6) {
    return false;
  }

  *a = (n * sum_yx - sum_y * sum_x) / denom;
  *b = (sum_x - (*a) * sum_y) / n;
  return true;
}

bool RansacLine(const std::vector<Pixel> &points,
                int iterations,
                double inlier_threshold_px,
                int min_inliers,
                double *best_a,
                double *best_b) {
  if (points.size() < 2 || best_a == nullptr || best_b == nullptr) {
    return false;
  }

  int best_count = -1;
  double candidate_a = 0.0;
  double candidate_b = 0.0;

  const int n = static_cast<int>(points.size());
  for (int i = 0; i < iterations; ++i) {
    const int i0 = (i * 37) % n;
    const int i1 = (i * 53 + 7) % n;
    if (i0 == i1) {
      continue;
    }
    const auto &p0 = points[i0];
    const auto &p1 = points[i1];
    const double dy = static_cast<double>(p1.y - p0.y);
    if (std::abs(dy) < 1e-6) {
      continue;
    }

    const double a = static_cast<double>(p1.x - p0.x) / dy;
    const double b = static_cast<double>(p0.x) - a * static_cast<double>(p0.y);

    int inlier_count = 0;
    for (const auto &pt : points) {
      const double pred_x = a * static_cast<double>(pt.y) + b;
      const double err = std::abs(pred_x - static_cast<double>(pt.x));
      if (err <= inlier_threshold_px) {
        ++inlier_count;
      }
    }

    if (inlier_count > best_count) {
      best_count = inlier_count;
      candidate_a = a;
      candidate_b = b;
    }
  }

  if (best_count < min_inliers) {
    return false;
  }

  std::vector<Pixel> inliers;
  inliers.reserve(points.size());
  for (const auto &pt : points) {
    const double pred_x = candidate_a * static_cast<double>(pt.y) + candidate_b;
    const double err = std::abs(pred_x - static_cast<double>(pt.x));
    if (err <= inlier_threshold_px) {
      inliers.push_back(pt);
    }
  }

  if (static_cast<int>(inliers.size()) < min_inliers) {
    return false;
  }

  return FitLineLeastSquares(inliers, best_a, best_b);
}

}  // namespace

class RoadCenteringControllerNode : public rclcpp::Node {
 public:
  RoadCenteringControllerNode() : Node("road_centering_controller") {
    start_stamp_ = now();

    dnn_topic_ = declare_parameter<std::string>("dnn_topic", "/hobot_dnn_detection");
    road_target_type_ = declare_parameter<std::string>("road_target_type", "road");
    mask_threshold_ = declare_parameter<int>("mask_threshold", 1);
    bottom_ratio_ = declare_parameter<double>("bottom_ratio", 0.35);

    main_track_enabled_ = declare_parameter<bool>("enhance.main_track_enabled", true);
    morph_open_radius_ = declare_parameter<int>("enhance.morph_open_radius", 1);
    morph_close_radius_ = declare_parameter<int>("enhance.morph_close_radius", 1);
    min_component_area_ = declare_parameter<int>("enhance.min_component_area", 120);
    prior_max_distance_px_ = declare_parameter<double>("enhance.prior_max_distance_px", 120.0);

    ransac_enabled_ = declare_parameter<bool>("enhance.ransac_enabled", true);
    ransac_iterations_ = declare_parameter<int>("enhance.ransac_iterations", 50);
    ransac_inlier_threshold_px_ = declare_parameter<double>("enhance.ransac_inlier_threshold_px", 2.5);
    ransac_min_inliers_ = declare_parameter<int>("enhance.ransac_min_inliers", 60);

    lowpass_alpha_ = declare_parameter<double>("enhance.lowpass_alpha", 0.35);
    branch_freeze_s_ = declare_parameter<double>("enhance.branch_freeze_s", 0.6);
    branch_ambiguity_ratio_ = declare_parameter<double>("enhance.branch_ambiguity_ratio", 0.65);
    branch_center_dist_px_ = declare_parameter<double>("enhance.branch_center_dist_px", 40.0);

    control_rate_hz_ = declare_parameter<double>("control_rate_hz", 20.0);
    vision_timeout_s_ = declare_parameter<double>("vision_timeout_s", 0.25);

    kp_ = declare_parameter<double>("pid.kp", 0.7);
    ki_ = declare_parameter<double>("pid.ki", 0.03);
    kd_ = declare_parameter<double>("pid.kd", 0.08);
    integral_limit_ = declare_parameter<double>("pid.integral_limit", 1.0);
    vy_limit_ = declare_parameter<double>("pid.vy_limit", 1.2);
    invert_error_sign_ = declare_parameter<bool>("pid.invert_error_sign", false);

    use_gps_safety_ = declare_parameter<bool>("gps.use_safety_gate", true);
    gps_current_topic_ = declare_parameter<std::string>("gps.current_topic", "/mavros/global_position/raw/fix");
    gps_reference_topic_ = declare_parameter<std::string>("gps.reference_topic", "/road_centering/reference_fix");
    gps_max_deviation_m_ = declare_parameter<double>("gps.max_deviation_m", 8.0);
    gps_timeout_s_ = declare_parameter<double>("gps.timeout_s", 1.0);

    serial_enabled_ = declare_parameter<bool>("mavlink.serial_enabled", true);
    serial_port_ = declare_parameter<std::string>("mavlink.serial_port", "/dev/ttyUSB0");
    serial_baudrate_ = declare_parameter<int>("mavlink.baudrate", 115200);
    sys_id_ = declare_parameter<int>("mavlink.sys_id", 246);
    comp_id_ = declare_parameter<int>("mavlink.comp_id", 191);
    target_sys_id_ = declare_parameter<int>("mavlink.target_sys_id", 1);
    target_comp_id_ = declare_parameter<int>("mavlink.target_comp_id", 1);
    body_ned_frame_ = declare_parameter<bool>("mavlink.body_ned_frame", true);

    bridge_enabled_ = declare_parameter<bool>("bridge.enabled", true);
    bridge_command_topic_ = declare_parameter<std::string>("bridge.command_topic", "/uav/mavlink/command");

    dnn_sub_ = create_subscription<ai_msgs::msg::PerceptionTargets>(
        dnn_topic_, rclcpp::SensorDataQoS(),
        std::bind(&RoadCenteringControllerNode::OnPerception, this, std::placeholders::_1));

    if (use_gps_safety_) {
      gps_current_sub_ = create_subscription<sensor_msgs::msg::NavSatFix>(
          gps_current_topic_, rclcpp::QoS(10),
          std::bind(&RoadCenteringControllerNode::OnGpsCurrent, this, std::placeholders::_1));
      gps_reference_sub_ = create_subscription<sensor_msgs::msg::NavSatFix>(
          gps_reference_topic_, rclcpp::QoS(10),
          std::bind(&RoadCenteringControllerNode::OnGpsReference, this, std::placeholders::_1));
    }

    if (bridge_enabled_) {
      bridge_command_pub_ = create_publisher<std_msgs::msg::String>(bridge_command_topic_, rclcpp::QoS(20));
    }

#ifndef _WIN32
    if (serial_enabled_) {
      OpenSerial();
    }
#else
    if (serial_enabled_) {
      RCLCPP_WARN(get_logger(), "Windows build detected, MAVLink serial is disabled in this source implementation.");
    }
    serial_enabled_ = false;
#endif

    const auto period = std::chrono::duration<double>(1.0 / std::max(control_rate_hz_, 1.0));
    control_timer_ = create_wall_timer(
        std::chrono::duration_cast<std::chrono::milliseconds>(period),
        std::bind(&RoadCenteringControllerNode::ControlLoop, this));

    RCLCPP_INFO(get_logger(),
                "Road centering controller started. dnn_topic=%s, gps_safety=%s, bridge=%s, serial=%s",
                dnn_topic_.c_str(),
                use_gps_safety_ ? "on" : "off",
                bridge_enabled_ ? "on" : "off",
                serial_enabled_ ? "on" : "off");
  }

  ~RoadCenteringControllerNode() override {
#ifndef _WIN32
    if (serial_fd_ >= 0) {
      close(serial_fd_);
      serial_fd_ = -1;
    }
#endif
  }

 private:
  void OnPerception(const ai_msgs::msg::PerceptionTargets::ConstSharedPtr msg) {
    float error = 0.0f;
    if (!ExtractRoadOffset(*msg, error)) {
      return;
    }

    if (invert_error_sign_) {
      error = -error;
    }

    latest_error_ = static_cast<double>(error);
    last_vision_stamp_ = now();
    has_vision_ = true;
  }

  void OnGpsCurrent(const sensor_msgs::msg::NavSatFix::ConstSharedPtr msg) {
    current_fix_ = *msg;
    has_current_fix_ = IsGpsValid(current_fix_);
    last_current_fix_stamp_ = now();
  }

  void OnGpsReference(const sensor_msgs::msg::NavSatFix::ConstSharedPtr msg) {
    reference_fix_ = *msg;
    has_reference_fix_ = IsGpsValid(reference_fix_);
    last_reference_fix_stamp_ = now();
  }

  bool IsGpsValid(const sensor_msgs::msg::NavSatFix &fix) const {
    return std::isfinite(fix.latitude) && std::isfinite(fix.longitude) &&
           !(std::abs(fix.latitude) < 1e-8 && std::abs(fix.longitude) < 1e-8);
  }

  bool GpsSafetyPass(double *distance_m) {
    if (!use_gps_safety_) {
      if (distance_m != nullptr) {
        *distance_m = 0.0;
      }
      return true;
    }

    const auto now_ts = now();
    if (!has_current_fix_ || !has_reference_fix_) {
      return false;
    }

    if ((now_ts - last_current_fix_stamp_).seconds() > gps_timeout_s_ ||
        (now_ts - last_reference_fix_stamp_).seconds() > gps_timeout_s_) {
      return false;
    }

    const double dist = HaversineMeters(current_fix_.latitude, current_fix_.longitude,
                                        reference_fix_.latitude, reference_fix_.longitude);
    if (distance_m != nullptr) {
      *distance_m = dist;
    }
    return dist <= gps_max_deviation_m_;
  }

  bool ExtractRoadOffset(const ai_msgs::msg::PerceptionTargets &msg, float &offset_norm) {
    for (const auto &target : msg.targets) {
      if (!road_target_type_.empty() && target.type != road_target_type_) {
        continue;
      }
      if (target.captures.empty()) {
        continue;
      }

      const auto &capture = target.captures.front();
      const auto width = static_cast<int>(capture.img.width);
      const auto height = static_cast<int>(capture.img.height);
      if (width <= 1 || height <= 1) {
        continue;
      }

      const int step = std::max(1, static_cast<int>(capture.img.step));
      const size_t row_size = static_cast<size_t>(width) * step;
      if (capture.features.size() < row_size * static_cast<size_t>(height)) {
        continue;
      }

      const int y_start = std::max(0, static_cast<int>(height * (1.0 - bottom_ratio_)));
      const int roi_h = std::max(1, height - y_start);
      std::vector<uint8_t> roi_mask(static_cast<size_t>(width) * roi_h, 0);

      for (int y = 0; y < roi_h; ++y) {
        const int src_y = y + y_start;
        const size_t row_offset = static_cast<size_t>(src_y) * row_size;
        for (int x = 0; x < width; ++x) {
          const size_t idx = row_offset + static_cast<size_t>(x) * step;
          if (capture.features[idx] >= static_cast<uint8_t>(mask_threshold_)) {
            roi_mask[MaskIndex(x, y, width)] = 1;
          }
        }
      }

      Opening(roi_mask, width, roi_h, morph_open_radius_);
      Closing(roi_mask, width, roi_h, morph_close_radius_);

      auto components = ConnectedComponents8(roi_mask, width, roi_h, min_component_area_);
      if (components.empty()) {
        continue;
      }

      std::sort(components.begin(), components.end(), [](const Component &lhs, const Component &rhs) {
        return lhs.area > rhs.area;
      });

      int selected_idx = 0;
      if (main_track_enabled_ && has_prev_center_x_) {
        double best_dist = std::numeric_limits<double>::max();
        int best_idx = -1;
        for (size_t i = 0; i < components.size(); ++i) {
          const double cx = components[i].sum_x / std::max(1, components[i].area);
          const double dist = std::abs(cx - prev_center_x_);
          if (dist > prior_max_distance_px_) {
            continue;
          }
          if (dist < best_dist) {
            best_dist = dist;
            best_idx = static_cast<int>(i);
          } else if (std::abs(dist - best_dist) < 1e-6 && best_idx >= 0 &&
                     components[i].area > components[static_cast<size_t>(best_idx)].area) {
            best_idx = static_cast<int>(i);
          }
        }
        if (best_idx >= 0) {
          selected_idx = best_idx;
        }
      }

      if (components.size() >= 2) {
        const double a0 = static_cast<double>(components[0].area);
        const double a1 = static_cast<double>(components[1].area);
        const double ambiguity = a1 / std::max(1.0, a0);
        const double c0 = components[0].sum_x / std::max(1, components[0].area);
        const double c1 = components[1].sum_x / std::max(1, components[1].area);
        const double dist = std::abs(c0 - c1);
        if (ambiguity >= branch_ambiguity_ratio_ && dist >= branch_center_dist_px_) {
          freeze_until_ = now() + rclcpp::Duration::from_seconds(branch_freeze_s_);
          freeze_error_ = has_filtered_error_ ? filtered_error_ : latest_error_;
        }
      }

      const auto &selected = components[static_cast<size_t>(selected_idx)];
      double road_cx = selected.sum_x / std::max(1, selected.area);
      if (ransac_enabled_) {
        double a = 0.0;
        double b = 0.0;
        const bool fit_ok = RansacLine(selected.pixels,
                                       ransac_iterations_,
                                       ransac_inlier_threshold_px_,
                                       ransac_min_inliers_,
                                       &a,
                                       &b);
        if (fit_ok) {
          const double y_eval = static_cast<double>(roi_h - 1);
          road_cx = a * y_eval + b;
        }
      }

      road_cx = std::clamp(road_cx, 0.0, static_cast<double>(width - 1));
      prev_center_x_ = road_cx;
      has_prev_center_x_ = true;

      const double img_cx = static_cast<double>(width - 1) / 2.0;
      double raw_offset = (road_cx - img_cx) / std::max(img_cx, 1.0);

      lowpass_alpha_ = std::clamp(lowpass_alpha_, 0.0, 1.0);
      if (!has_filtered_error_) {
        filtered_error_ = raw_offset;
        has_filtered_error_ = true;
      } else {
        filtered_error_ = lowpass_alpha_ * raw_offset + (1.0 - lowpass_alpha_) * filtered_error_;
      }

      const auto now_ts = now();
      if (now_ts < freeze_until_) {
        offset_norm = static_cast<float>(freeze_error_);
      } else {
        freeze_error_ = filtered_error_;
        offset_norm = static_cast<float>(filtered_error_);
      }

      return true;
    }

    return false;
  }

  void ControlLoop() {
    const auto now_ts = now();

    double gps_dist = 0.0;
    const bool gps_ok = GpsSafetyPass(&gps_dist);
    const bool vision_ok = has_vision_ &&
                           ((now_ts - last_vision_stamp_).seconds() <= vision_timeout_s_);

    double vy_cmd = 0.0;

    if (vision_ok && gps_ok) {
      const double dt = last_control_stamp_.nanoseconds() == 0
                            ? (1.0 / std::max(control_rate_hz_, 1.0))
                            : std::max(1e-3, (now_ts - last_control_stamp_).seconds());

      integral_error_ += latest_error_ * dt;
      integral_error_ = std::clamp(integral_error_, -integral_limit_, integral_limit_);

      const double derivative = (latest_error_ - prev_error_) / dt;
      const double output = kp_ * latest_error_ + ki_ * integral_error_ + kd_ * derivative;
      vy_cmd = std::clamp(output, -vy_limit_, vy_limit_);
      prev_error_ = latest_error_;
    } else {
      integral_error_ = 0.0;
      prev_error_ = 0.0;
      vy_cmd = 0.0;
    }

    SendVelocityCommand(static_cast<float>(vy_cmd));

    if (!gps_ok) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                           "GPS safety gate active, hold vy=0. gps_dist=%.2f m (limit=%.2f m)",
                           gps_dist, gps_max_deviation_m_);
    } else if (!vision_ok) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                           "Vision result timeout, hold vy=0.");
    }

    last_control_stamp_ = now_ts;
  }

  void SendVelocityCommand(float vy) {
    if (bridge_enabled_ && bridge_command_pub_ != nullptr) {
      std_msgs::msg::String cmd;
      cmd.data = std::string("{\"action\":\"set_velocity_ned\",\"vx\":0.0,\"vy\":") +
                 std::to_string(vy) +
                 ",\"vz\":0.0,\"yaw_rate\":0.0}";
      bridge_command_pub_->publish(cmd);
    }

    if (!serial_enabled_) {
      return;
    }
#ifndef _WIN32
    if (serial_fd_ < 0) {
      return;
    }

    std::array<uint8_t, 53> payload{};
    uint32_t boot_ms = static_cast<uint32_t>((now() - start_stamp_).nanoseconds() / 1000000ULL);

    const float x = 0.0f;
    const float y = 0.0f;
    const float z = 0.0f;
    const float vx = 0.0f;
    const float vz = 0.0f;
    const float afx = 0.0f;
    const float afy = 0.0f;
    const float afz = 0.0f;
    const float yaw = 0.0f;
    const float yaw_rate = 0.0f;

    uint16_t type_mask = 0;
    type_mask |= (1 << 0);   // ignore x
    type_mask |= (1 << 1);   // ignore y
    type_mask |= (1 << 2);   // ignore z
    type_mask |= (1 << 3);   // ignore vx
    type_mask |= (1 << 5);   // ignore vz
    type_mask |= (1 << 6);   // ignore afx
    type_mask |= (1 << 7);   // ignore afy
    type_mask |= (1 << 8);   // ignore afz
    type_mask |= (1 << 10);  // ignore yaw
    type_mask |= (1 << 11);  // ignore yaw_rate

    const uint8_t target_system = static_cast<uint8_t>(target_sys_id_);
    const uint8_t target_component = static_cast<uint8_t>(target_comp_id_);
    const uint8_t coordinate_frame = static_cast<uint8_t>(body_ned_frame_ ? 8 : 1);

    auto put_u32 = [&payload](size_t offset, uint32_t value) {
      std::memcpy(payload.data() + offset, &value, sizeof(uint32_t));
    };
    auto put_u16 = [&payload](size_t offset, uint16_t value) {
      std::memcpy(payload.data() + offset, &value, sizeof(uint16_t));
    };
    auto put_f32 = [&payload](size_t offset, float value) {
      std::memcpy(payload.data() + offset, &value, sizeof(float));
    };

    put_u32(0, boot_ms);
    put_f32(4, x);
    put_f32(8, y);
    put_f32(12, z);
    put_f32(16, vx);
    put_f32(20, vy);
    put_f32(24, vz);
    put_f32(28, afx);
    put_f32(32, afy);
    put_f32(36, afz);
    put_f32(40, yaw);
    put_f32(44, yaw_rate);
    put_u16(48, type_mask);
    payload[50] = target_system;
    payload[51] = target_component;
    payload[52] = coordinate_frame;

    std::array<uint8_t, 6> header{};
    header[0] = 0xFE;                 // MAVLink v1 STX
    header[1] = static_cast<uint8_t>(payload.size());
    header[2] = sequence_++;
    header[3] = static_cast<uint8_t>(sys_id_);
    header[4] = static_cast<uint8_t>(comp_id_);
    header[5] = 84;                   // SET_POSITION_TARGET_LOCAL_NED

    std::array<uint8_t, 59> crc_buffer{};
    std::memcpy(crc_buffer.data(), header.data() + 1, 5);
    std::memcpy(crc_buffer.data() + 5, payload.data(), payload.size());

    uint16_t crc = X25CrcCalculate(crc_buffer.data(), crc_buffer.size());
    crc = X25CrcAccumulate(143, crc);  // CRC extra for msg id 84

    std::array<uint8_t, 61> packet{};
    std::memcpy(packet.data(), header.data(), header.size());
    std::memcpy(packet.data() + header.size(), payload.data(), payload.size());
    packet[59] = static_cast<uint8_t>(crc & 0xff);
    packet[60] = static_cast<uint8_t>((crc >> 8) & 0xff);

    const ssize_t written = write(serial_fd_, packet.data(), packet.size());
    if (written != static_cast<ssize_t>(packet.size())) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                           "MAVLink write incomplete: %ld/%zu", static_cast<long>(written), packet.size());
    }
#endif
  }

#ifndef _WIN32
  speed_t ToTermiosBaud(int baud) const {
    switch (baud) {
      case 57600:
        return B57600;
      case 115200:
      default:
        return B115200;
    }
  }

  void OpenSerial() {
    serial_fd_ = open(serial_port_.c_str(), O_RDWR | O_NOCTTY | O_SYNC);
    if (serial_fd_ < 0) {
      RCLCPP_ERROR(get_logger(), "Open serial failed: %s", serial_port_.c_str());
      serial_enabled_ = false;
      return;
    }

    termios tty{};
    if (tcgetattr(serial_fd_, &tty) != 0) {
      RCLCPP_ERROR(get_logger(), "tcgetattr failed on %s", serial_port_.c_str());
      close(serial_fd_);
      serial_fd_ = -1;
      serial_enabled_ = false;
      return;
    }

    cfsetospeed(&tty, ToTermiosBaud(serial_baudrate_));
    cfsetispeed(&tty, ToTermiosBaud(serial_baudrate_));

    tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
    tty.c_iflag &= ~IGNBRK;
    tty.c_lflag = 0;
    tty.c_oflag = 0;
    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;
    tty.c_iflag &= ~(IXON | IXOFF | IXANY);
    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~(PARENB | PARODD);
    tty.c_cflag &= ~CSTOPB;
    tty.c_cflag &= ~CRTSCTS;

    if (tcsetattr(serial_fd_, TCSANOW, &tty) != 0) {
      RCLCPP_ERROR(get_logger(), "tcsetattr failed on %s", serial_port_.c_str());
      close(serial_fd_);
      serial_fd_ = -1;
      serial_enabled_ = false;
      return;
    }

    RCLCPP_INFO(get_logger(), "MAVLink serial ready: %s @ %d", serial_port_.c_str(), serial_baudrate_);
  }
#endif

 private:
  std::string dnn_topic_;
  std::string road_target_type_;
  int mask_threshold_{1};
  double bottom_ratio_{0.35};

  double control_rate_hz_{20.0};
  double vision_timeout_s_{0.25};

  bool main_track_enabled_{true};
  int morph_open_radius_{1};
  int morph_close_radius_{1};
  int min_component_area_{120};
  double prior_max_distance_px_{120.0};

  bool ransac_enabled_{true};
  int ransac_iterations_{50};
  double ransac_inlier_threshold_px_{2.5};
  int ransac_min_inliers_{60};

  double lowpass_alpha_{0.35};
  double branch_freeze_s_{0.6};
  double branch_ambiguity_ratio_{0.65};
  double branch_center_dist_px_{40.0};

  double kp_{0.7};
  double ki_{0.03};
  double kd_{0.08};
  double integral_limit_{1.0};
  double vy_limit_{1.2};
  bool invert_error_sign_{false};

  bool use_gps_safety_{true};
  std::string gps_current_topic_;
  std::string gps_reference_topic_;
  double gps_max_deviation_m_{8.0};
  double gps_timeout_s_{1.0};

  bool serial_enabled_{true};
  std::string serial_port_;
  int serial_baudrate_{115200};
  int sys_id_{246};
  int comp_id_{191};
  int target_sys_id_{1};
  int target_comp_id_{1};
  bool body_ned_frame_{true};
  bool bridge_enabled_{true};
  std::string bridge_command_topic_;

  rclcpp::Subscription<ai_msgs::msg::PerceptionTargets>::SharedPtr dnn_sub_;
  rclcpp::Subscription<sensor_msgs::msg::NavSatFix>::SharedPtr gps_current_sub_;
  rclcpp::Subscription<sensor_msgs::msg::NavSatFix>::SharedPtr gps_reference_sub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr bridge_command_pub_;

  sensor_msgs::msg::NavSatFix current_fix_;
  sensor_msgs::msg::NavSatFix reference_fix_;
  bool has_current_fix_{false};
  bool has_reference_fix_{false};

  bool has_vision_{false};
  double latest_error_{0.0};
  double prev_error_{0.0};
  double integral_error_{0.0};
  bool has_prev_center_x_{false};
  double prev_center_x_{0.0};
  bool has_filtered_error_{false};
  double filtered_error_{0.0};
  double freeze_error_{0.0};

  rclcpp::Time start_stamp_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_vision_stamp_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_control_stamp_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_current_fix_stamp_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_reference_fix_stamp_{0, 0, RCL_ROS_TIME};
  rclcpp::Time freeze_until_{0, 0, RCL_ROS_TIME};

  rclcpp::TimerBase::SharedPtr control_timer_;

#ifndef _WIN32
  int serial_fd_{-1};
#endif
  uint8_t sequence_{0};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<RoadCenteringControllerNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}

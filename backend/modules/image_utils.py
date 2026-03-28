# backend/modules/image_utils.py
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

TYPE_COLOR_MAP = {
    "crack": (40, 60, 230),
    "pothole": (10, 150, 250),
    "subsidence": (50, 180, 60),
    "repair": (180, 90, 200),
    "unknown": (120, 120, 120),
}


def _normalize_label(v):
    if isinstance(v, str):
        s = v.strip()
        if s:
            return s
    return "Unknown"


def _label_color_bgr(label):
    normalized = _normalize_label(label).lower()
    if normalized in TYPE_COLOR_MAP:
        return TYPE_COLOR_MAP[normalized]

    # 未知类别通过哈希稳定映射颜色，保证不同类别可区分。
    h = abs(hash(normalized))
    b = 40 + (h % 180)
    g = 40 + ((h >> 8) % 180)
    r = 40 + ((h >> 16) % 180)
    return (int(b), int(g), int(r))


def _normalize_bbox(bbox):
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    try:
        x, y, w, h = [int(float(v)) for v in bbox[:4]]
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return [x, y, w, h]


def _collect_annotations(bbox, label, boxes):
    annotations = []

    if isinstance(boxes, list):
        for item in boxes:
            if not isinstance(item, dict):
                continue
            rect = _normalize_bbox(item.get("bbox"))
            if not rect:
                continue
            item_label = _normalize_label(item.get("type"))
            annotations.append({"bbox": rect, "label": item_label})

    if not annotations:
        rect = _normalize_bbox(bbox)
        if rect:
            annotations.append({"bbox": rect, "label": _normalize_label(label)})

    return annotations


def _load_font(size=20):
    try:
        font_paths = [
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/msyh.ttc",
        ]
        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    except Exception:
        pass
    return ImageFont.load_default()


def draw_bbox_on_image(image_path, bbox, label, boxes=None):
    """
    在图像上渲染病害框，支持中文显示
    bbox: [x, y, w, h]
    """
    # 读取图像
    img = cv2.imread(image_path)
    if img is None:
        return None
    
    annotations = _collect_annotations(bbox, label, boxes)
    if not annotations:
        return img

    overlay = img.copy()

    # 坐标裁剪，避免越界
    h_img, w_img = img.shape[:2]

    normalized = []
    for item in annotations:
        x, y, w, h = item["bbox"]
        x = max(0, min(x, w_img - 1))
        y = max(0, min(y, h_img - 1))
        w = max(1, min(w, w_img - x))
        h = max(1, min(h, h_img - y))
        label_text = _normalize_label(item.get("label"))
        color = _label_color_bgr(label_text)
        normalized.append({
            "bbox": [x, y, w, h],
            "label": label_text,
            "color": color,
        })

    for item in normalized:
        x, y, w, h = item["bbox"]
        color = item["color"]
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)

    alpha = 0.3  # 透明度
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

    for item in normalized:
        x, y, w, h = item["bbox"]
        color = item["color"]
        cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)

    # 使用PIL绘制中文文本
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)
    font = _load_font(20)

    for item in normalized:
        x, y, _, _ = item["bbox"]
        label_text = item["label"]
        b, g, r = item["color"]
        color_rgb = (r, g, b)
        text_bbox = draw.textbbox((x, y), label_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        bg_x0 = x
        bg_y1 = max(0, y)
        bg_y0 = max(0, bg_y1 - text_height - 10)
        bg_x1 = min(w_img - 1, x + text_width + 10)

        draw.rectangle([bg_x0, bg_y0, bg_x1, bg_y1], fill=color_rgb)
        draw.text((bg_x0 + 5, bg_y0 + 5), label_text, fill=(255, 255, 255), font=font)

    # 转换回OpenCV格式
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    return img
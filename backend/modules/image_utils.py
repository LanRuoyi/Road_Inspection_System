# backend/modules/image_utils.py
import cv2
import numpy as np
import io
from PIL import Image, ImageDraw, ImageFont

def draw_bbox_on_image(image_path, bbox, label):
    """
    在图像上渲染病害框，支持中文显示
    bbox: [x, y, w, h]
    """
    # 读取图像
    img = cv2.imread(image_path)
    if img is None:
        return None
    
    overlay = img.copy()
    
    # 确保坐标是整数
    try:
        x, y, w, h = [int(v) for v in bbox]
    except Exception:
        return img
        
    color = (0, 0, 255)  # BGR 格式：红色
    
    # 1. 内部半透明填充
    cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
    alpha = 0.3  # 透明度
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    
    # 2. 外部实线边界
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    
    # 3. 使用PIL绘制中文文本
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)
    
    # 尝试加载中文字体，如果失败则使用默认字体
    try:
        # 常见的中文字体路径
        font_paths = [
            'C:/Windows/Fonts/simhei.ttf',  # 黑体
            'C:/Windows/Fonts/simsun.ttc',  # 宋体
            'C:/Windows/Fonts/msyh.ttc',    # 微软雅黑
        ]
        font = None
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, 20)
                break
            except:
                continue
        
        if font is None:
            # 如果没有找到中文字体，使用默认字体
            font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
    
    # 绘制文本背景（增强可读性）
    text_bbox = draw.textbbox((x, y - 30), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # 绘制文本背景
    cv2.rectangle(img, (x, y - 30 - text_height), 
                  (x + text_width + 10, y - 10), color, -1)
    
    # 重新转换为PIL图像（因为上面修改了原图）
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)
    
    # 绘制中文文本
    text_color = (255, 255, 255)  # 白色文本
    draw.text((x + 5, y - 30 - text_height + 5), label, fill=text_color, font=font)
    
    # 转换回OpenCV格式
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    
    return img
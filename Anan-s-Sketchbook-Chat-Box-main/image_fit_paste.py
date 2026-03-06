# filename: image_fit_paste.py
from io import BytesIO
from typing import Tuple, Literal, Union, Optional, List
from PIL import Image
import os

Align = Literal["left", "center", "right"]
VAlign = Literal["top", "middle", "bottom"]

def paste_image_auto(
    image_source: Union[str, Image.Image],
    top_left: Tuple[int, int],
    bottom_right: Tuple[int, int],
    content_image: Image.Image,
    align: Align = "center",
    valign: VAlign = "middle",
    padding: int = 0,
    allow_upscale: bool = False,
    keep_alpha: bool = True,
    image_overlay: Union[str, Image.Image,None]=None,
    auto_detect_region: bool = False,
    detect_search_margin: int = 0,
    detect_bright_threshold: int = 230,
    detect_min_width: int = 120,
    detect_min_height: int = 60,
    detect_region_padding: int = 10,
) -> bytes:
    """
    在指定矩形内放置一张图片（content_image），按比例缩放至“最大但不超过”该矩形。
    - base_image: 底图（会被复制，原图不改）
    - top_left / bottom_right: 指定矩形区域（左上/右下坐标）
    - content_image: 待放入的图片（PIL.Image.Image）
    - align / valign: 水平/垂直对齐方式
    - padding: 矩形内边距（像素），四边统一
    - allow_upscale: 是否允许放大（默认只缩小不放大）
    - keep_alpha: True 时保留透明通道并用其作为粘贴蒙版

    返回：最终 PNG 的 bytes。
    """
    if not isinstance(content_image, Image.Image):
        raise TypeError("content_image 必须为 PIL.Image.Image")

    if isinstance(image_source, Image.Image):
        img = image_source.copy()
    else:
        img = Image.open(image_source).convert("RGBA")

    if image_overlay is not None:
        if isinstance(image_overlay, Image.Image):
            img_overlay = image_overlay.copy()
        else:
            img_overlay = Image.open(image_overlay).convert("RGBA") if os.path.isfile(image_overlay) else None

    def _find_largest_blank_rect(base_img: Image.Image) -> Optional[Tuple[int, int, int, int]]:
        """
        在图像中查找近似“白色空白区”的最大矩形。
        使用最大直方图矩形算法，返回 (x1, y1, x2, y2)。
        """
        rgb = base_img.convert("RGB")
        w, h = rgb.size

        x_start = min(max(detect_search_margin, 0), w)
        y_start = min(max(detect_search_margin, 0), h)
        x_end = max(x_start + 1, w - max(detect_search_margin, 0))
        y_end = max(y_start + 1, h - max(detect_search_margin, 0))

        search_w = x_end - x_start
        search_h = y_end - y_start

        pixels = rgb.load()
        heights = [0] * search_w
        best_area = 0
        best_rect: Optional[Tuple[int, int, int, int]] = None

        for y in range(search_h):
            py = y + y_start
            for x in range(search_w):
                px = x + x_start
                r, g, b = pixels[px, py]
                if min(r, g, b) >= detect_bright_threshold:
                    heights[x] += 1
                else:
                    heights[x] = 0

            stack: List[int] = []
            for i in range(search_w + 1):
                cur_h = heights[i] if i < search_w else 0
                while stack and heights[stack[-1]] > cur_h:
                    top = stack.pop()
                    height_val = heights[top]
                    left_idx = stack[-1] + 1 if stack else 0
                    width_val = i - left_idx

                    if height_val < detect_min_height or width_val < detect_min_width:
                        continue

                    area = height_val * width_val
                    if area > best_area:
                        best_area = area
                        rect_x1 = left_idx + x_start
                        rect_x2 = i + x_start
                        rect_y2 = py + 1
                        rect_y1 = rect_y2 - height_val
                        best_rect = (rect_x1, rect_y1, rect_x2, rect_y2)
                stack.append(i)

        return best_rect

    if auto_detect_region:
        detected_rect = _find_largest_blank_rect(img)
        if detected_rect is not None:
            x1, y1, x2, y2 = detected_rect
            if detect_region_padding > 0:
                x1 = min(max(0, x1 + detect_region_padding), img.width)
                y1 = min(max(0, y1 + detect_region_padding), img.height)
                x2 = min(max(0, x2 - detect_region_padding), img.width)
                y2 = min(max(0, y2 - detect_region_padding), img.height)
        else:
            x1, y1 = top_left
            x2, y2 = bottom_right
            print("Warning: 未检测到可用空白区域，回退到配置坐标。")
    else:
        x1, y1 = top_left
        x2, y2 = bottom_right

    if not (x2 > x1 and y2 > y1):
        raise ValueError("无效的粘贴区域。")

    # 计算可用区域（考虑 padding）
    region_w = max(1, (x2 - x1) - 2 * padding)
    region_h = max(1, (y2 - y1) - 2 * padding)

    cw, ch = content_image.size
    if cw <= 0 or ch <= 0:
        raise ValueError("content_image 尺寸无效。")

    # 计算缩放比例（contain：不超过区域，并保持纵横比）
    scale_w = region_w / cw
    scale_h = region_h / ch
    scale = min(scale_w, scale_h)

    if not allow_upscale:
        scale = min(1.0, scale)

    # 至少保证 1x1
    new_w = max(1, int(round(cw * scale)))
    new_h = max(1, int(round(ch * scale)))

    # 选择高质量插值
    resized = content_image.resize((new_w, new_h), Image.LANCZOS)

    # 计算粘贴坐标（考虑对齐与 padding）
    if align == "left":
        px = x1 + padding
    elif align == "center":
        px = x1 + padding + (region_w - new_w) // 2
    else:  # "right"
        px = x2 - padding - new_w

    if valign == "top":
        py = y1 + padding
    elif valign == "middle":
        py = y1 + padding + (region_h - new_h) // 2
    else:  # "bottom"
        py = y2 - padding - new_h

    # 处理透明度：若 keep_alpha=True 且有 alpha，则用 alpha 作为 mask 粘贴
    if keep_alpha and ("A" in resized.getbands()):
        img.paste(resized, (px, py), resized)
    else:
        # 没有 alpha 就直接粘贴（会覆盖底图该区域）
        img.paste(resized, (px, py))

    # 覆盖置顶图层（如果有）
    if image_overlay is not None and img_overlay is not None:
        img.paste(img_overlay, (0, 0), img_overlay)
    elif image_overlay is not None and img_overlay is None:
        print("Warning: overlay image is not exist.")

    # 输出 PNG bytes
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

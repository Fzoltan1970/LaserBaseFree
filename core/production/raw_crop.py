from __future__ import annotations

import math

from PIL import Image, ImageDraw


def compute_center_crop_box(
    img_w: int,
    img_h: int,
    target_aspect: float,
) -> tuple[int, int, int, int]:
    if img_w <= 0 or img_h <= 0:
        raise ValueError("img_w and img_h must be positive")
    if target_aspect <= 0:
        raise ValueError("target_aspect must be positive")

    img_aspect = img_w / img_h

    if img_aspect > target_aspect:
        new_w = max(1, int(round(img_h * target_aspect)))
        new_w = min(new_w, img_w)
        left = max(0, (img_w - new_w) // 2)
        right = min(img_w, left + new_w)
        top = 0
        bottom = img_h
    else:
        new_h = max(1, int(round(img_w / target_aspect)))
        new_h = min(new_h, img_h)
        top = max(0, (img_h - new_h) // 2)
        bottom = min(img_h, top + new_h)
        left = 0
        right = img_w

    if right <= left:
        right = min(img_w, left + 1)
    if bottom <= top:
        bottom = min(img_h, top + 1)

    return left, top, right, bottom


def apply_circle_mask(img_l: Image.Image) -> Image.Image:
    if img_l.mode != "L":
        img_l = img_l.convert("L")

    w, h = img_l.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w - 1, h - 1), fill=255)

    out = Image.new("L", (w, h), 255)
    out.paste(img_l, (0, 0), mask)
    return out


def normalize_raw_crop_box(
    crop_box: tuple[float, float, float, float] | tuple[int, int, int, int],
    img_w: int,
    img_h: int,
) -> tuple[int, int, int, int] | None:
    if img_w <= 0 or img_h <= 0:
        return None
    if crop_box is None or len(crop_box) != 4:
        return None

    left_f, top_f, right_f, bottom_f = crop_box

    left = max(0, min(img_w, int(math.floor(left_f))))
    top = max(0, min(img_h, int(math.floor(top_f))))
    right = max(0, min(img_w, int(math.ceil(right_f))))
    bottom = max(0, min(img_h, int(math.ceil(bottom_f))))

    if right <= left:
        right = min(img_w, left + 1)
    if bottom <= top:
        bottom = min(img_h, top + 1)

    return (left, top, right, bottom)


def apply_raw_crop(
    img: Image.Image,
    crop_box: tuple[float, float, float, float] | tuple[int, int, int, int] | None,
    crop_shape: str | None = None,
) -> tuple[Image.Image, tuple[int, int, int, int] | None]:
    if crop_box is None:
        return img, None

    normalized = normalize_raw_crop_box(crop_box, img.width, img.height)
    if normalized is None:
        return img, None

    cropped = img.crop(normalized)
    if crop_shape == "circle":
        cropped = apply_circle_mask(cropped)

    return cropped, normalized

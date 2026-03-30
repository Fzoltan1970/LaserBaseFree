from __future__ import annotations

import os
import tempfile
from time import perf_counter

import numpy as np
from numbers import Real

from PIL import Image, ImageFilter
from core.deterministic.image_conditioner import condition_for_engraving
from core.model.processed_image_info import BaseTuningInfo, ProcessedImageInfo
from core.production.dithering import (
    DITHER_MODES,
    ORDERED_DITHER_MODES,
    apply_dither_mode,
    is_binary_dither_mode,
)
from core.production.raw_crop import apply_raw_crop


_GEOMETRY_RESAMPLE_CACHE: dict[tuple, str] = {}


# ---------------------------------------------------------
# PUBLIC ENTRY
# ---------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_unit_control(value) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    parsed = _parse_float(value)
    if parsed is None:
        return None, True
    return _clamp(parsed, -1.0, 1.0), False


def _fill_isolated_white_holes(
    img_l: Image.Image, negative: bool = False
) -> Image.Image:
    if img_l.mode != "L":
        img_l = img_l.convert("L")

    arr = np.asarray(img_l, dtype=np.uint8)
    black = arr < 128
    working_black = black if not negative else (~black)
    target_pixels = (~black) if not negative else black
    if not np.any(working_black):
        return img_l

    padded = np.pad(working_black.astype(np.uint8), 1, mode="constant", constant_values=0)
    neighbors = (
        padded[:-2, :-2] + padded[:-2, 1:-1] + padded[:-2, 2:]
        + padded[1:-1, :-2] + padded[1:-1, 2:]
        + padded[2:, :-2] + padded[2:, 1:-1] + padded[2:, 2:]
    )
    local_padded = np.pad(
        working_black.astype(np.uint8), 2, mode="constant", constant_values=0
    )
    local_black = (
        local_padded[:-4, :-4] + local_padded[:-4, 1:-3] + local_padded[:-4, 2:-2]
        + local_padded[:-4, 3:-1] + local_padded[:-4, 4:]
        + local_padded[1:-3, :-4] + local_padded[1:-3, 1:-3] + local_padded[1:-3, 2:-2]
        + local_padded[1:-3, 3:-1] + local_padded[1:-3, 4:]
        + local_padded[2:-2, :-4] + local_padded[2:-2, 1:-3] + local_padded[2:-2, 2:-2]
        + local_padded[2:-2, 3:-1] + local_padded[2:-2, 4:]
        + local_padded[3:-1, :-4] + local_padded[3:-1, 1:-3] + local_padded[3:-1, 2:-2]
        + local_padded[3:-1, 3:-1] + local_padded[3:-1, 4:]
        + local_padded[4:, :-4] + local_padded[4:, 1:-3] + local_padded[4:, 2:-2]
        + local_padded[4:, 3:-1] + local_padded[4:, 4:]
    )
    local_black_ratio = local_black.astype(np.float32) / 25.0
    top_band = (
        local_padded[:-4, :-4] + local_padded[:-4, 1:-3] + local_padded[:-4, 2:-2]
        + local_padded[:-4, 3:-1] + local_padded[:-4, 4:]
    )
    bottom_band = (
        local_padded[4:, :-4] + local_padded[4:, 1:-3] + local_padded[4:, 2:-2]
        + local_padded[4:, 3:-1] + local_padded[4:, 4:]
    )
    left_band = (
        local_padded[:-4, :-4] + local_padded[1:-3, :-4] + local_padded[2:-2, :-4]
        + local_padded[3:-1, :-4] + local_padded[4:, :-4]
    )
    right_band = (
        local_padded[:-4, 4:] + local_padded[1:-3, 4:] + local_padded[2:-2, 4:]
        + local_padded[3:-1, 4:] + local_padded[4:, 4:]
    )
    isolated = (
        target_pixels
        & (neighbors == 8)
        & (local_black_ratio >= 0.92)
        & (top_band >= 4)
        & (bottom_band >= 4)
        & (left_band >= 4)
        & (right_band >= 4)
    )
    if not np.any(isolated):
        return img_l
    cleaned = arr.copy()
    cleaned[isolated] = 255 if negative else 0
    return Image.fromarray(cleaned, mode="L")


def apply_base_tuning(
    img_l: Image.Image,
    base_tuning: dict | None,
) -> tuple[Image.Image, BaseTuningInfo, str]:
    tuning_info = {
        "requested": {},
        "effective_mode": "Grayscale",
        "requested_gamma": None,
        "effective_gamma": None,
        "applied": False,
        "invalid_fields": [],
    }

    if img_l.mode != "L":
        img_l = img_l.convert("L")

    if base_tuning is None:
        return img_l, BaseTuningInfo(**tuning_info), "Grayscale"

    if not isinstance(base_tuning, dict):
        tuning_info["invalid_fields"].append("base_tuning")
        return img_l, BaseTuningInfo(**tuning_info), "Grayscale"

    tuning_info["requested"] = dict(base_tuning)

    result = img_l

    negative_enabled = bool(base_tuning.get("negative", False))
    if negative_enabled:
        work = np.asarray(result)
        if np.issubdtype(work.dtype, np.floating):
            work = 255.0 - work
        else:
            work = 255 - work
        result = Image.fromarray(np.clip(work, 0, 255).astype(np.uint8), mode="L")
        tuning_info["applied"] = True

    contrast_norm, contrast_invalid = _normalize_unit_control(
        base_tuning.get("contrast")
    )
    if contrast_invalid:
        tuning_info["invalid_fields"].append("contrast")

    brightness_norm, brightness_invalid = _normalize_unit_control(
        base_tuning.get("brightness")
    )
    if brightness_invalid:
        tuning_info["invalid_fields"].append("brightness")
    if contrast_norm is not None or brightness_norm is not None:
        work = np.asarray(result, dtype=np.float32)
        contrast_alpha = 1.0
        brightness_beta = 0.0

        if contrast_norm is not None:
            contrast_alpha = _clamp(1.0 + contrast_norm, 0.0, 3.0)
            work = (work - 128.0) * contrast_alpha + 128.0

        if brightness_norm is not None:
            brightness_beta = brightness_norm * 255.0
            work = work + brightness_beta

        work = np.clip(work, 0.0, 255.0)
        result = Image.fromarray(work.astype(np.uint8), mode="L")

        if contrast_alpha != 1.0 or brightness_beta != 0.0:
            tuning_info["applied"] = True

    gamma_raw = base_tuning.get("gamma")
    gamma_value = _parse_float(gamma_raw)
    if gamma_raw is not None and gamma_value is None:
        tuning_info["invalid_fields"].append("gamma")
    elif gamma_value is not None:
        tuning_info["requested_gamma"] = gamma_value
        gamma_effective = _clamp(gamma_value, 0.3, 2.0)
        tuning_info["effective_gamma"] = gamma_effective
        if gamma_effective != 1.0:
            inv_gamma = 1.0 / gamma_effective
            lut = [int(((i / 255.0) ** inv_gamma) * 255.0 + 0.5) for i in range(256)]
            result = result.point(lut)
            tuning_info["applied"] = True

    radius_raw = base_tuning.get("radius")
    amount_raw = base_tuning.get("amount")
    radius_value = _parse_float(radius_raw)
    amount_value = _parse_float(amount_raw)
    if radius_raw is not None and radius_value is None:
        tuning_info["invalid_fields"].append("radius")
    if amount_raw is not None and amount_value is None:
        tuning_info["invalid_fields"].append("amount")

    if radius_value is not None:
        radius_value = max(0.0, radius_value)
    if amount_value is not None:
        percent = _clamp(amount_value, 0, 1500)
        percent_int = int(round(percent))
        if radius_value is not None and radius_value > 0 and percent_int > 0:
            result = result.filter(
                ImageFilter.UnsharpMask(
                    radius=radius_value, percent=percent_int, threshold=0
                )
            )
            tuning_info["applied"] = True

    mirror_x = bool(base_tuning.get("mirror_x", False))
    mirror_y = bool(base_tuning.get("mirror_y", False))
    if mirror_x:
        result = result.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        tuning_info["applied"] = True
    if mirror_y:
        result = result.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        tuning_info["applied"] = True

    requested_mode = base_tuning.get("mode")
    if requested_mode is not None and not isinstance(requested_mode, str):
        tuning_info["invalid_fields"].append("mode")
        requested_mode = None

    requested_mode_key = "Grayscale"
    if isinstance(requested_mode, str):
        mode_key = requested_mode.strip().casefold()
        mode_map = {
            "grayscale": "Grayscale",
            "floyd–steinberg": "FloydSteinberg",
            "floyd-steinberg": "FloydSteinberg",
            "floydsteinberg": "FloydSteinberg",
            "atkinson": "Atkinson",
            "jarvis–judice–ninke (jjn)": "JJN",
            "jarvis-judice-ninke (jjn)": "JJN",
            "jjn": "JJN",
            "stucki": "Stucki",
            "bayer": "BAYER",
            "blue-noise (1 bit)": "BLUE_NOISE_1BIT",
            "blue_noise_1bit": "BLUE_NOISE_1BIT",
            "blue-noise (4 szint)": "BLUE_NOISE_4LEVEL",
            "blue_noise_4level": "BLUE_NOISE_4LEVEL",
            "blue-noise (scanline-aware)": "SCANLINE_AWARE_BLUE_NOISE",
            "scanline_aware_blue_noise": "SCANLINE_AWARE_BLUE_NOISE",
        }
        effective_mode = mode_map.get(mode_key)
        if (
            effective_mode in DITHER_MODES
            or effective_mode in ORDERED_DITHER_MODES
        ):
            tuning_info["effective_mode"] = effective_mode
            requested_mode_key = effective_mode
        elif effective_mode == "Grayscale":
            tuning_info["effective_mode"] = effective_mode
            requested_mode_key = "Grayscale"
        elif requested_mode:
            tuning_info["invalid_fields"].append("mode")

    return result, BaseTuningInfo(**tuning_info), requested_mode_key


def build_base_image(
    job,
    context: dict,
    base_tuning: dict | None = None,
    raw_crop_box: tuple[int, int, int, int] | None = None,
    raw_crop_shape: str | None = None,
    crop_enabled: bool = False,
    crop_valid: bool = False,
    crop_rect: tuple[int, int, int, int] | None = None,
):
    """
    Deterministic production step.

    INPUT:
        job.raw_image_path
        job.size_mm
        snapped context from evaluate_job_geometry

    OUTPUT:
        PIL.Image (engraveable bitmap)
        ProcessedImageInfo
    """

    if not context:
        raise ValueError("Missing context")

    source_path = job.raw_image_path
    geometry_resample_ms = 0.0

    img = Image.open(source_path).convert("L")

    # IMPORTANT: crop is defined in RAW image coordinate space (UI).
    # Apply it on RAW before any conditioning/resample path.
    applied_crop_box = None
    requested_crop_box = None
    if crop_enabled and crop_valid and crop_rect is not None:
        requested_crop_box = crop_rect
    elif raw_crop_box is not None:
        requested_crop_box = raw_crop_box

    if requested_crop_box is not None:
        img, applied_crop_box = apply_raw_crop(img, requested_crop_box, raw_crop_shape)

    preprocessed_source_path = None
    if context.get("needs_resample"):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            preprocessed_source_path = tmp.name
        img.save(preprocessed_source_path)
        source_path = preprocessed_source_path

    if context.get("needs_resample"):
        cache_key = (
            job.raw_image_path,
            applied_crop_box,
            raw_crop_shape,
            context.get("real_lines"),
            context.get("effective_dpi"),
            context.get("effective_width_mm"),
            context.get("effective_height_mm"),
            context.get("engrave_axis"),
        )
        cached = _GEOMETRY_RESAMPLE_CACHE.get(cache_key)
        if cached is not None and os.path.exists(cached):
            source_path = cached
        else:
            if cached is not None:
                _GEOMETRY_RESAMPLE_CACHE.pop(cache_key, None)
            resample_start = perf_counter()
            source_path = condition_for_engraving(source_path, context)
            geometry_resample_ms = (perf_counter() - resample_start) * 1000.0
            _GEOMETRY_RESAMPLE_CACHE[cache_key] = source_path

    if context.get("needs_resample"):
        img = Image.open(source_path).convert("L")

    if preprocessed_source_path is not None and os.path.exists(preprocessed_source_path):
        try:
            os.remove(preprocessed_source_path)
        except OSError:
            pass

    img, tuning_info, dither_mode = apply_base_tuning(img, base_tuning)

    required_keys = (
        "effective_width_mm",
        "effective_height_mm",
        "effective_dpi",
        "step_axis_steps_per_mm",
        "steps_per_line",
        "real_lines",
    )
    missing = [k for k in required_keys if k not in context]
    if missing:
        raise ValueError(f"Missing required context keys: {', '.join(missing)}")

    width_mm = context["effective_width_mm"]
    height_mm = context["effective_height_mm"]
    if not isinstance(width_mm, Real) or not isinstance(height_mm, Real):
        raise TypeError("effective_width_mm and effective_height_mm must be float-like")

    effective_dpi = float(context["effective_dpi"])
    axis = context.get("engrave_axis")
    real_lines = int(context["real_lines"])

    target_w_px = int(round(float(width_mm) / 25.4 * effective_dpi))
    target_h_px = int(round(float(height_mm) / 25.4 * effective_dpi))

    if axis == "X":
        target_h_px = real_lines
    elif axis == "Y":
        target_w_px = real_lines

    base_image = img.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)

    tuning_dither_ms = 0.0
    if dither_mode in DITHER_MODES or dither_mode in ORDERED_DITHER_MODES:
        dither_start = perf_counter()
        base_image = apply_dither_mode(base_image, dither_mode, base_tuning=base_tuning)
        tuning_dither_ms = (perf_counter() - dither_start) * 1000.0
        tuning_info.applied = True

    if (
        isinstance(base_tuning, dict)
        and bool(base_tuning.get("one_pixel_off", False))
        and is_binary_dither_mode(dither_mode)
    ):
        base_image = _fill_isolated_white_holes(
            base_image, negative=bool(base_tuning.get("negative", False))
        )

    tuning_info.geometry_resample_ms = geometry_resample_ms
    tuning_info.tuning_dither_ms = tuning_dither_ms

    expected_step_span = real_lines * float(context["steps_per_line"])
    real_span_steps = float(context["step_axis_steps_per_mm"]) * (
        float(height_mm) if axis == "X" else float(width_mm)
    )
    step_aligned = abs(real_span_steps - expected_step_span) <= 1e-6

    processed_info = ProcessedImageInfo(
        px_width=target_w_px,
        px_height=target_h_px,
        dpi=effective_dpi,
        size_mm=(float(width_mm), float(height_mm)),
        engrave_axis=axis,
        steps_per_line=int(context["steps_per_line"]),
        step_aligned=step_aligned,
        step_axis_steps_per_mm=float(context["step_axis_steps_per_mm"]),
        pitch_mm=float(context["pitch_mm"]),
        real_lines=real_lines,
        effective_dpi=effective_dpi,
        effective_size_mm=(float(width_mm), float(height_mm)),
        base_tuning=tuning_info,
        geometry_resample_ms=geometry_resample_ms,
        tuning_dither_ms=tuning_dither_ms,
    )

    return base_image, processed_info

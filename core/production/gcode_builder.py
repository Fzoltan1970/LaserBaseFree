from __future__ import annotations

from dataclasses import asdict, is_dataclass
from io import StringIO
from typing import Any

from PIL import Image

from core.production.dithering import is_binary_dither_mode


def _info_to_dict(processed_info: Any) -> dict:
    if isinstance(processed_info, dict):
        return processed_info
    if processed_info is not None and is_dataclass(processed_info):
        return asdict(processed_info)
    raise ValueError("processed_info is missing")


def _pitch_mm_from_info(info: dict) -> float:
    pitch = info.get("pitch_mm")
    if pitch is not None:
        return float(pitch)

    dpi = info.get("dpi") or info.get("effective_dpi")
    if dpi is None:
        raise ValueError("processed_info must contain pitch_mm or dpi")
    dpi_value = float(dpi)
    if dpi_value <= 0:
        raise ValueError("dpi must be > 0")
    return 25.4 / dpi_value


def _pixel_to_power(
    pixel: int,
    s_min: float,
    s_max: float,
    s_range_min: float,
    s_range_max: float,
) -> int:
    tone = (255 - int(pixel)) / 255.0
    power = round(s_min + (s_max - s_min) * tone)
    return int(max(float(s_range_min), min(float(s_range_max), float(power))))


def _effective_mode_from_info(info: dict) -> str | None:
    base_tuning = info.get("base_tuning")
    if isinstance(base_tuning, dict):
        return base_tuning.get("effective_mode")
    if base_tuning is not None and is_dataclass(base_tuning):
        return asdict(base_tuning).get("effective_mode")
    return None


def _pixel(gray: Image.Image, axis: str, fixed: int, scan: int) -> int:
    if axis == "X":
        return int(gray.getpixel((scan, fixed)))
    return int(gray.getpixel((fixed, scan)))


def _fmt_delta(value: float) -> str:
    rounded = round(float(value), 3)
    if abs(rounded) < 0.0005:
        rounded = 0.0
    text = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _grayscale_context(
    img: Image.Image,
    processed_info: Any,
    engrave_axis: str,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    info = _info_to_dict(processed_info)
    px_width = info.get("px_width")
    px_height = info.get("px_height")
    if px_width is None or px_height is None:
        raise ValueError("processed_info must contain px_width and px_height")

    width = int(px_width)
    height = int(px_height)
    if img.size != (width, height):
        raise ValueError(
            f"Image size mismatch: image={img.size} processed_info=({width}, {height})"
        )

    pitch_mm = _pitch_mm_from_info(info)
    s_min = float(cfg.get("s_min"))
    s_max = float(cfg.get("s_max"))
    s_range_min = float(cfg.get("s_range_min", 0.0))
    s_range_max = float(cfg.get("s_range_max", 1000.0))

    gray = img.convert("L")
    gray_access = gray.load()
    axis = (engrave_axis or "X").upper()
    if axis not in ("X", "Y"):
        raise ValueError("engrave_axis must be 'X' or 'Y'")

    effective_mode = _effective_mode_from_info(info)
    is_dither = is_binary_dither_mode(effective_mode)
    is_grayscale = effective_mode in (None, "Grayscale")

    grayscale_power_lut: list[int] | None = None
    if is_grayscale and not is_dither:
        grayscale_power_lut = [0] * 256
        for px in range(256):
            power = _pixel_to_power(px, s_min, s_max, s_range_min, s_range_max)
            grayscale_power_lut[px] = int(power)

    axis_is_x = axis == "X"
    total_lines = height if axis_is_x else width
    scan_len = width if axis_is_x else height

    if axis == "X":

        def _read_pixel(fixed_idx: int, scan_idx: int) -> int:
            return int(gray_access[scan_idx, fixed_idx])

    else:

        def _read_pixel(fixed_idx: int, scan_idx: int) -> int:
            return int(gray_access[fixed_idx, scan_idx])

    if is_dither:
        dither_power = int(min(s_range_max, max(s_range_min, s_max)))

        def power_at(fixed_idx: int, scan_idx: int) -> int:
            return dither_power if _read_pixel(fixed_idx, scan_idx) < 128 else 0

    elif grayscale_power_lut is not None:

        def power_at(fixed_idx: int, scan_idx: int) -> int:
            return grayscale_power_lut[_read_pixel(fixed_idx, scan_idx)]

    else:

        def power_at(fixed_idx: int, scan_idx: int) -> int:
            px = _read_pixel(fixed_idx, scan_idx)
            power = _pixel_to_power(px, s_min, s_max, s_range_min, s_range_max)
            return int(power)

    return {
        "info": info,
        "width": width,
        "height": height,
        "pitch_mm": pitch_mm,
        "axis": axis,
        "effective_mode": effective_mode,
        "is_dither": is_dither,
        "is_grayscale": is_grayscale,
        "total_lines": total_lines,
        "scan_len": scan_len,
        "power_at": power_at,
    }


def _count_runs_for_line(row_powers: list[int], direction: int, tolerance: int) -> int:
    scan_len = len(row_powers)
    i = 0 if direction > 0 else scan_len - 1
    line_runs = 0
    exact_match_only = tolerance <= 0
    row = row_powers
    tolerance_f = float(tolerance)
    while True:
        run_power = row[i]
        run_sum = run_power
        run_count = 1
        j = i
        if exact_match_only:
            while True:
                next_j = j + direction
                if next_j < 0 or next_j >= scan_len:
                    break

                next_power = row[next_j]
                if next_power != run_power:
                    break

                j = next_j
        else:
            run_sum_f = float(run_sum)
            run_count_f = float(run_count)
            while True:
                next_j = j + direction
                if next_j < 0 or next_j >= scan_len:
                    break

                next_power = row[next_j]
                if (next_power == 0) != (row[j] == 0):
                    break
                next_power_f = float(next_power)
                new_mean = (run_sum_f + next_power_f) / (run_count_f + 1.0)
                if abs(next_power_f - new_mean) > tolerance_f:
                    break
                run_sum_f += next_power_f
                run_count_f += 1.0

                j = next_j

        line_runs += 1
        next_i = j + direction
        if next_i < 0 or next_i >= scan_len:
            break
        i = next_i
    return line_runs


def preflight_grayscale_streamability(
    img: Image.Image,
    processed_info: Any,
    engrave_axis: str,
    cfg: dict[str, Any],
    baudrate: int,
) -> dict[str, Any]:
    ctx = _grayscale_context(
        img=img,
        processed_info=processed_info,
        engrave_axis=engrave_axis,
        cfg=cfg,
    )
    if not ctx["is_grayscale"] or ctx["is_dither"]:
        return {"applies": False}

    total_lines = int(ctx["total_lines"])
    scan_len = int(ctx["scan_len"])
    pitch_mm = float(ctx["pitch_mm"])
    power_at = ctx["power_at"]

    try:
        feed_rate = float(cfg.get("feed_rate_mm_min"))
    except (TypeError, ValueError):
        feed_rate = 0.0
    strict_runs = 0
    rows: list[tuple[list[int], int]] = []
    sampled_line_indices = list(range(0, total_lines, 10))
    if total_lines > 0 and sampled_line_indices and sampled_line_indices[-1] != total_lines - 1:
        sampled_line_indices.append(total_lines - 1)
    scan_indices = range(scan_len)
    direction_positive = 1
    direction_negative = -1
    for fixed in sampled_line_indices:
        row_powers = [power_at(fixed, scan_idx) for scan_idx in scan_indices]
        direction = direction_positive if fixed % 2 == 0 else direction_negative
        rows.append((row_powers, direction))
        strict_runs += _count_runs_for_line(row_powers, direction, tolerance=0)

    usable_bytes_per_s = (max(0.0, float(baudrate)) / 10.0) * 0.95
    feed_mm_s = feed_rate / 60.0
    bytes_per_mm_allowed = float("inf")
    if feed_mm_s > 0:
        bytes_per_mm_allowed = usable_bytes_per_s / feed_mm_s
    bytes_per_run = 18.0
    runs_per_mm_allowed = bytes_per_mm_allowed / bytes_per_run

    total_scan_distance_mm = (
        float(len(sampled_line_indices)) * float(scan_len) * float(pitch_mm)
    )

    def _runs_per_mm(run_count: int) -> float:
        if total_scan_distance_mm <= 0:
            return 0.0
        return float(run_count) / total_scan_distance_mm

    def _fits(run_count: int) -> bool:
        return _runs_per_mm(run_count) <= runs_per_mm_allowed

    if _fits(strict_runs):
        return {
            "applies": True,
            "likely_streamable": True,
            "recommended_tolerance": 0,
            "strict_runs": strict_runs,
            "simplified_runs": strict_runs,
            "baudrate": int(baudrate),
        }

    max_tolerance = min(max(0, int(cfg.get("s_max", 0) or 0)), 32)
    runs_cache: dict[int, int] = {0: strict_runs}

    def _total_runs_for_tolerance(tolerance: int) -> int:
        cached = runs_cache.get(tolerance)
        if cached is not None:
            return cached
        total_runs = 0
        for row_powers, direction in rows:
            total_runs += _count_runs_for_line(row_powers, direction, tolerance=tolerance)
        runs_cache[tolerance] = total_runs
        return total_runs

    low = 0
    high = max_tolerance
    best_tolerance = max_tolerance
    while low <= high:
        mid = (low + high) // 2
        mid_runs = _total_runs_for_tolerance(mid)
        if _fits(mid_runs):
            best_tolerance = mid
            high = mid - 1
        else:
            low = mid + 1

    recommended_tolerance = best_tolerance
    simplified_runs = _total_runs_for_tolerance(recommended_tolerance)

    return {
        "applies": True,
        "likely_streamable": False,
        "recommended_tolerance": recommended_tolerance,
        "strict_runs": strict_runs,
        "simplified_runs": simplified_runs,
        "baudrate": int(baudrate),
    }


def build_bidirectional_raster_gcode(
    img: Image.Image,
    processed_info: Any,
    engrave_axis: str,
    cfg: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if img is None:
        raise ValueError("Missing BASE image")

    ctx = _grayscale_context(
        img=img,
        processed_info=processed_info,
        engrave_axis=engrave_axis,
        cfg=cfg,
    )
    info = ctx["info"]
    width = int(ctx["width"])
    height = int(ctx["height"])
    pitch_mm = float(ctx["pitch_mm"])

    feed_rate = float(cfg.get("feed_rate_mm_min"))
    s_min = float(cfg.get("s_min"))
    s_max = float(cfg.get("s_max"))
    s_range_min = float(cfg.get("s_range_min", 0.0))
    s_range_max = float(cfg.get("s_range_max", 1000.0))
    laser_mode = str(cfg.get("laser_mode", "M4"))
    overscan_mode = str(cfg.get("overscan_mode", "off"))
    overscan_mm = max(0.0, float(cfg.get("overscan_mm", 0.0) or 0.0))
    if overscan_mode == "off":
        overscan_mm = 0.0
    invert_x = False
    invert_y = False

    axis = str(ctx["axis"])
    effective_mode = ctx["effective_mode"]
    is_dither = bool(ctx["is_dither"])
    is_grayscale = bool(ctx["is_grayscale"])

    header_lines: list[str] = [
        f"; overscan={overscan_mode} overscan_mm={overscan_mm:.3f} speed_mm_min={feed_rate:.3f}",
        f"; overscan_accel_mm_s2={cfg.get('overscan_used_accel', 'N/A')}",
        f"; pwm_max={s_range_max:.3f} invert_x={int(invert_x)} invert_y={int(invert_y)}",
        "G90",
        "G21",
        "M5",
        laser_mode,
        f"F{feed_rate:.3f}",
        "G91",
    ]
    body_buffer = StringIO()
    body_write = body_buffer.write
    fmt_delta = _fmt_delta
    abs_value = abs
    move_count = 0

    travel_count = 0
    power_at = ctx["power_at"]

    raster_started = False

    def emit_g1(
        dx: float | None = None, dy: float | None = None, s: int | None = None
    ) -> bool:
        nonlocal raster_started

        has_dx = dx is not None and abs_value(dx) >= 0.0005
        has_dy = dy is not None and abs_value(dy) >= 0.0005
        if not has_dx and not has_dy:
            return False

        if s is not None:
            s_int = int(s)
            s_out = s_int if s_int > 0 else 0
        else:
            s_out = 0

        if has_dx and has_dy:
            body_write(f"G1 X{fmt_delta(dx)} Y{fmt_delta(dy)} S{s_out}\n")
        elif has_dx:
            body_write(f"G1 X{fmt_delta(dx)} S{s_out}\n")
        else:
            body_write(f"G1 Y{fmt_delta(dy)} S{s_out}\n")
        raster_started = True
        return True

    def emit_scan_move(delta_mm: float, s: int = 0) -> bool:
        if axis == "X":
            return emit_g1(dx=delta_mm, s=s)
        return emit_g1(dy=delta_mm, s=s)

    total_lines = height if axis == "X" else width
    scan_len = width if axis == "X" else height

    scan_distance_per_line_mm = (float(scan_len) * float(pitch_mm)) + (
        2.0 * float(overscan_mm)
    )
    total_scan_distance_mm = float(total_lines) * scan_distance_per_line_mm
    total_step_distance_mm = float(max(0, total_lines - 1)) * float(pitch_mm)
    initial_scan_align_mm = float(overscan_mm) if total_lines > 0 else 0.0
    feed_rate_mm_s = float(feed_rate) / 60.0
    estimated_time_s = 0
    if feed_rate_mm_s > 0:
        estimated_time_s = int(
            round(
                (
                    total_scan_distance_mm
                    + total_step_distance_mm
                    + initial_scan_align_mm
                )
                / feed_rate_mm_s
            )
        )

    # Track scan position in mm (G91 relative stream, but we need an absolute-in-line
    # reference to make overscan part of the scan interval and avoid ghosting).
    scan_pos_mm = 0.0

    def emit_to_mm(target_mm: float, s: int) -> bool:
        nonlocal scan_pos_mm
        target_mm_f = float(target_mm)
        delta = target_mm_f - scan_pos_mm
        if abs_value(delta) < 0.0005:
            return False
        if axis == "X":
            moved = emit_g1(dx=delta, s=s)
        else:
            moved = emit_g1(dy=delta, s=s)
        if moved:
            scan_pos_mm = target_mm_f
        return moved

    # Image and scan bounds in mm (overscan is part of scan interval, LightBurn-like)
    image_start_mm = 0.0
    image_end_mm = float(scan_len) * float(pitch_mm)
    scan_start_mm = image_start_mm - float(overscan_mm)
    scan_end_mm = image_end_mm + float(overscan_mm)

    pitch_mm_f = float(pitch_mm)
    scan_indices = range(scan_len)

    for fixed in range(total_lines):
        row_powers = [power_at(fixed, scan_idx) for scan_idx in scan_indices]
        direction = 1 if fixed % 2 == 0 else -1
        # Scan interval is constant each line: [scan_start_mm .. scan_end_mm],
        # direction just flips traversal.
        if direction > 0:
            line_start_mm = scan_start_mm
            line_end_mm = scan_end_mm
            edge_mm = image_start_mm
            i = 0
        else:
            line_start_mm = scan_end_mm
            line_end_mm = scan_start_mm
            edge_mm = image_end_mm
            i = scan_len - 1

        # 0) align to scan interval edge (outside image)
        if emit_to_mm(line_start_mm, s=0):
            travel_count += 1

        # 1) lead-in to image edge at S0 (part of scan interval, not extra overscan)
        if emit_to_mm(edge_mm, s=0):
            travel_count += 1

        # 2) full-width monotonic run-length scan across the image region (includes S0 runs)
        run_power = row_powers[i]

        while True:
            j = i
            # target is the end of the current pixel run in the direction of travel
            target_mm = (float(j + 1) * pitch_mm_f) if direction > 0 else (float(j) * pitch_mm_f)

            while True:
                next_j = j + direction
                if next_j < 0 or next_j >= scan_len:
                    break
                
                next_power = row_powers[next_j]
                if next_power != run_power:
                    break

                j = next_j
                target_mm = (float(j + 1) * pitch_mm_f) if direction > 0 else (float(j) * pitch_mm_f)

            run_power = row_powers[i]

            if emit_to_mm(target_mm, s=run_power):
                if run_power > 0:
                    move_count += 1
                else:
                    travel_count += 1

            next_i = j + direction
            if next_i < 0 or next_i >= scan_len:
                break
            i = next_i
            run_power = row_powers[i]

        # 3) lead-out to scan interval edge at S0 (outside image)
        if emit_to_mm(line_end_mm, s=0):
            travel_count += 1

        if fixed < total_lines - 1 and raster_started:
            if axis == "X":
                emit_g1(dy=pitch_mm, s=0)
            else:
                emit_g1(dx=pitch_mm, s=0)

    output_buffer = StringIO()
    output_buffer.write(f";ESTIMATED_TIME_S={estimated_time_s}\n")
    for line in header_lines:
        output_buffer.write(line)
        output_buffer.write("\n")
    output_buffer.write(body_buffer.getvalue())
    output_buffer.write("G90\n")
    output_buffer.write("S0\n")
    output_buffer.write("M5\n")
    output_buffer.write("G0 X0 Y0\n")

    stats = {
        "axis": axis,
        "width_px": width,
        "height_px": height,
        "pitch_mm": pitch_mm,
        "feed_rate_mm_min": feed_rate,
        "s_min": s_min,
        "s_max": s_max,
        "effective_mode": effective_mode,
        "is_dither": is_dither,
        "is_grayscale": is_grayscale,
        "move_count": move_count,
        "travel_count": travel_count,
        "overscan_mode": overscan_mode,
        "overscan_mm": overscan_mm,
        "pwm_max": s_range_max,
        "invert_x": invert_x,
        "invert_y": invert_y,
    }

    return output_buffer.getvalue(), stats

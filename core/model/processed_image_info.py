from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseTuningInfo:
    requested: dict[str, Any] = field(default_factory=dict)
    effective_mode: str | None = None
    requested_gamma: float | None = None
    effective_gamma: float | None = None
    applied: bool = False
    invalid_fields: list[str] = field(default_factory=list)
    geometry_resample_ms: float | None = None
    tuning_dither_ms: float | None = None


@dataclass
class ProcessedImageInfo:
    # raster
    width_px: int | None = None
    height_px: int | None = None
    scale_ratio: float | None = None
    bit_depth: int | None = None
    processed: bool = False

    # physical
    width_mm: float | None = None
    height_mm: float | None = None
    dpi: float | None = None
    pitch_mm: float | None = None
    rows: int | None = None
    cols: int | None = None

    # mechanical
    steps_per_row: float | None = None
    alignment: str | None = None      # "exact" | "fractional"
    banding_risk: str | None = None   # "none" | "possible" | "likely"

    # canonical snapped geometry
    step_axis_steps_per_mm: float | None = None
    steps_per_line: int | None = None
    real_lines: int | None = None
    effective_dpi: float | None = None
    effective_size_mm: tuple[float, float] | None = None
    step_aligned: bool | None = None


    # ui/runtime view
    px_width: int | None = None
    px_height: int | None = None
    size_mm: tuple[float, float] | None = None
    engrave_axis: str | None = None


    base_tuning: BaseTuningInfo | None = None

    geometry_resample_ms: float | None = None
    tuning_dither_ms: float | None = None
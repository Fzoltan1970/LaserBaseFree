"""
Mechanical DPI coherence and banding risk analysis.

This module maps a requested engraving DPI onto the machine step grid
and detects mechanical quantization effects that can cause banding.

It does NOT decide, optimize, or clamp values.
It only describes physical coherence.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict
import math


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class MechanicalDpiResult:
    target_dpi: float
    steps_per_mm: float

    pitch_mm: float
    steps_per_row: float
    step_fraction: float

    quant_period_rows: float | None
    quant_period_mm: float | None

    banding_risk: str  # "LOW" | "MED" | "HIGH"

    safe_dpi_candidates: List[float]
    suggested_safe_dpi: float


# ----------------------------------------------------------------------
# Core analysis
# ----------------------------------------------------------------------

def analyze_mechanical_dpi(
    target_dpi: float,
    steps_per_mm: float,
    search_radius: int = 3,
) -> MechanicalDpiResult:
    """
    Analyze mechanical coherence of a given DPI.

    :param target_dpi: Requested engraving DPI
    :param steps_per_mm: Machine axis resolution (e.g. GRBL $100)
    :param search_radius: How many neighboring integer step counts to evaluate
    """

    if target_dpi <= 0:
        raise ValueError("target_dpi must be positive")

    if steps_per_mm <= 0:
        raise ValueError("steps_per_mm must be positive")

    # --- Continuous geometry ---
    pitch_mm = 25.4 / target_dpi
    steps_per_row = pitch_mm * steps_per_mm

    nearest_int = round(steps_per_row)
    step_fraction = abs(steps_per_row - nearest_int)

    # --- Quantization period ---
    # If not integer, the controller alternates between floor/ceil steps
    # period_rows ≈ 1 / |fraction|
    if step_fraction > 1e-6:
        quant_period_rows = 1.0 / step_fraction
        quant_period_mm = quant_period_rows * pitch_mm
    else:
        quant_period_rows = None
        quant_period_mm = None

    # --- Risk heuristic (mechanical only) ---
    # Tuned for diode engravers in 200–400 DPI class
    if step_fraction < 0.02:
        banding_risk = "LOW"
    elif step_fraction < 0.10:
        banding_risk = "MED"
    else:
        banding_risk = "HIGH"

    # --- Find mechanically coherent DPI candidates ---
    # Solve: steps_per_row = N  =>  dpi = 25.4 * steps_per_mm / N
    N_center = max(1, int(round(25.4 * steps_per_mm / target_dpi)))

    safe_candidates: List[float] = []

    for N in range(N_center - search_radius, N_center + search_radius + 1):
        if N <= 0:
            continue
        dpi = 25.4 * steps_per_mm / N
        safe_candidates.append(dpi)

    # Sort by closeness to target
    safe_candidates.sort(key=lambda d: abs(d - target_dpi))

    suggested_safe_dpi = safe_candidates[0]

    return MechanicalDpiResult(
        target_dpi=target_dpi,
        steps_per_mm=steps_per_mm,
        pitch_mm=pitch_mm,
        steps_per_row=steps_per_row,
        step_fraction=step_fraction,
        quant_period_rows=quant_period_rows,
        quant_period_mm=quant_period_mm,
        banding_risk=banding_risk,
        safe_dpi_candidates=safe_candidates,
        suggested_safe_dpi=suggested_safe_dpi,
    )
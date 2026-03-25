from dataclasses import dataclass
import math


@dataclass
class MechanicalRasterResult:
    valid: bool
    steps_per_line: int | None
    real_pitch_mm: float | None
    real_dpi: float | None
    dpi_error: float | None

def snap_line_count(requested_span_mm: float, pitch_mm: float) -> tuple[int, float]:
    """
    Deterministic line-count snapping on a mechanical pitch grid.
    """
    if pitch_mm <= 0:
        raise ValueError("pitch_mm must be positive")

    ideal_lines = float(requested_span_mm) / float(pitch_mm)
    snapped_lines = max(1, int(round(ideal_lines)))
    effective_span_mm = snapped_lines * float(pitch_mm)

    return snapped_lines, effective_span_mm


def _is_sender_stable(steps: int, steps_per_mm: float, precision_digits: int) -> bool:
    """
    Megnézi hogy a G-code kerekítés után is egész lépés marad-e.
    """
    pitch = steps / steps_per_mm
    sent_pitch = round(pitch, precision_digits)
    reconstructed_steps = sent_pitch * steps_per_mm

    return abs(reconstructed_steps - round(reconstructed_steps)) < 1e-9


def choose_mechanical_raster(requested_dpi: float,
                             steps_per_mm: float,
                             precision_digits: int = 2) -> MechanicalRasterResult:
    """
    A user DPI-jéhez legközelebbi stabil mechanikai raszter kiválasztása.
    """

    if requested_dpi <= 0 or steps_per_mm <= 0:
        return MechanicalRasterResult(False, None, None, None, None)

    # 1) elméleti pitch
    pitch = 25.4 / requested_dpi

    # 2) elméleti lépésszám
    steps_f = pitch * steps_per_mm

    # 3) jelöltek
    candidates = {math.floor(steps_f), math.ceil(steps_f)}

    valid_candidates = []

    for s in candidates:
        if s <= 0:
            continue

        if _is_sender_stable(s, steps_per_mm, precision_digits):
            error = abs(s - steps_f)
            valid_candidates.append((s, error))

    if not valid_candidates:
        return MechanicalRasterResult(False, None, None, None, None)

    # 4) legközelebbi kiválasztása
    chosen_steps = min(valid_candidates, key=lambda x: x[1])[0]

    real_pitch = chosen_steps / steps_per_mm
    real_dpi = 25.4 / real_pitch
    dpi_error = real_dpi - requested_dpi

    return MechanicalRasterResult(True, chosen_steps, real_pitch, real_dpi, dpi_error)

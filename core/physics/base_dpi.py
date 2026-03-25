# core/base_dpi.py

"""
BASE-side DPI processing logic for LaserBase.

Pure geometric / physical derivations.
No UI, no DB, no optimization logic.
"""

from __future__ import annotations


# Fixed mapping: laser module wattage -> spot cross size (mm)
SPOT_CROSS_MM_BY_WATT = {
    1.5: 0.02,
    5.0: 0.04,
    10.0: 0.06,
    20.0: 0.10,
    40.0: 0.15,
    60.0: 0.20,
}


def compute_base_dpi_geometry(dpi: float, module_watt: float) -> dict:
    """
    Compute BASE-side DPI related geometric values.

    :param dpi: Engraving DPI value
    :param module_watt: Laser module power in watts
    :return: dict with pitch_mm, spot_cross_mm, overlap_geom
    """

    if dpi <= 0:
        raise ValueError("DPI must be positive")

    if module_watt not in SPOT_CROSS_MM_BY_WATT:
        raise ValueError(f"Unsupported laser module wattage: {module_watt}")

    pitch_mm = 25.4 / float(dpi)
    spot_cross_mm = SPOT_CROSS_MM_BY_WATT[module_watt]
    overlap_geom = spot_cross_mm / pitch_mm

    return {
        "dpi": float(dpi),
        "pitch_mm": pitch_mm,
        "spot_cross_mm": spot_cross_mm,
        "overlap_geom": overlap_geom,
    }

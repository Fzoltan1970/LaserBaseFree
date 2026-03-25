# core/laser_optimizer.py

"""
Updated version – uses real image analysis.
DPI geometry is delegated to BASE-side logic.
Pure analysis / data-return module.
"""

from core.deterministic.image_analyzer import analyze_image
from core.physics.dpi_estimator import estimate_dpi_from_quality
from core.physics.base_dpi import compute_base_dpi_geometry
from core.physics.mechanical_raster import choose_mechanical_raster, snap_line_count
from PIL import Image
from core.contracts.job_config import JobConfig
from typing import Tuple


def _debug_return(scope: str, result):
    print(f"[DEBUG] {scope} return type:", type(result))
    if isinstance(result, dict):
        print(f"[DEBUG] {scope} return keys:", list(result.keys()))
    else:
        print(f"[DEBUG] {scope} return value:", result)
    return result


def optimize_for_engraving(
    image_path: str,
    target_dpi: int = 254,
    laser_info: dict | None = None,
    *,
    size_mm: Tuple[float, float],
    engrave_axis: str = "X",
    effective_source_px: Tuple[int, int] | None = None,
) -> dict:
    """
    Main optimization function: combines image analysis and BASE DPI geometry.
    """

    if laser_info is None:
        laser_info = {"max_dpi": target_dpi, "pwm": False}

    analysis = {
        "sharpness": None,
        "contrast": None,
        "brightness": None,
        "resolution_px": None,
        "noise": None,
    }
    dpi_quality_estimation = None
    quality_metrics = {}

    # 1) Image analysis
    try:
        analysis = analyze_image(image_path)
    except Exception as exc:
        analysis = {"error": str(exc)}

    # 2) DPI estimation (quality-based)
    if "error" not in analysis:
        try:
            dpi_quality_estimation = estimate_dpi_from_quality(
                analysis,
                target_dpi,
                laser_info,
            )
            quality_metrics = dpi_quality_estimation.get("quality_metrics", {})
        except Exception as exc:
            dpi_quality_estimation = {
                "suggested_dpi": target_dpi,
                "quality_metrics": {},
            }
            quality_metrics = {"dpi_calc_error": str(exc)}
    else:
        dpi_quality_estimation = {"suggested_dpi": target_dpi, "quality_metrics": {}}

    suggested_dpi = dpi_quality_estimation.get("suggested_dpi", target_dpi)

    # --- BASE DPI GEOMETRY ---
    try:
        module_str = None
        if isinstance(laser_info, dict):
            module_str = laser_info.get("laser_module")

        if module_str is None:
            raise ValueError("Missing laser module")

        module_watt = float(str(module_str).replace("W", ""))

        base_geom = compute_base_dpi_geometry(
            dpi=suggested_dpi,
            module_watt=module_watt,
        )
    except Exception:
        base_geom = {}

    # Burn risk estimation (existing heuristic)
    burn_risk = "Unknown"
    try:
        risk_score = 0.0
        overlap = base_geom.get("overlap_geom")
        if overlap is not None:
            risk_score += overlap * 0.5
        if analysis.get("brightness", 50) < 40:
            risk_score += 0.25
        if analysis.get("contrast", 50) < 30:
            risk_score += 0.25

        if risk_score < 0.3:
            burn_risk = "Low"
        elif risk_score < 0.6:
            burn_risk = "Medium"
        else:
            burn_risk = "High"
    except Exception:
        burn_risk = "Unknown"

    result = {
        "dpi": {
            "estimated_quality": dpi_quality_estimation.get("suggested_dpi"),
            "target": target_dpi,
            "suggested": suggested_dpi,
        },
        "physics": {
            "pitch_mm": base_geom.get("pitch_mm"),
            "spot_cross_mm": base_geom.get("spot_cross_mm"),
            "overlap_geom": base_geom.get("overlap_geom"),
        },
        "risk": {"burn": burn_risk},
        "debug": analysis,
        "quality_metrics": quality_metrics,
    }

    if analysis.get("sharpness", 0) < 50:
        result["explanation_key"] = "laser.explain.low_detail"
    else:
        result["explanation_key"] = "laser.explain.default"

    # --------------------------------------------------
    # CANONICAL GEOMETRY DECISION (single source of truth)
    # --------------------------------------------------
    try:
        job = JobConfig(
            raw_image_path=image_path,
            size_mm=size_mm,
            requested_dpi=target_dpi,
            machine_profile=laser_info,
            engrave_axis=engrave_axis,
        )

        geom = evaluate_job_geometry(job, effective_source_px=effective_source_px)

    except Exception:
        geom = {"decision": "INVALID_INTERNAL", "context": None}

    # merge analysis + decision into single contract
    return _debug_return(
        "optimize_for_engraving",
        {
            "decision": geom.get("decision", "INVALID_INTERNAL"),
            "context": geom.get("context"),
            "analysis": result,
        },
    )


# ----------------------------------------------------------------------
# KANONIKUS GEOMETRIAI DÖNTÉS (EDDIG HIBÁSAN A KERNELBEN VOLT)
# ----------------------------------------------------------------------
def evaluate_job_geometry(job, effective_source_px: Tuple[int, int] | None = None) -> dict:
    """
    PURE deterministic decision.
    No UI meaning.
    No image processing.
    Only answers:

        képből gravírozható?
        kell javítás?
        milyen valódi raszter lesz?

    Ez az a logika ami NEM tartozhat a kernelbe.
    """

    try:
        profile = job.machine_profile
        if not isinstance(profile, dict):
            return _debug_return(
                "evaluate_job_geometry",
                {"decision": "INVALID_MACHINE", "context": None},
            )
        if any(k in profile for k in ("steps_per_mm", "max_rate", "acceleration")):
            return _debug_return(
                "evaluate_job_geometry",
                {"decision": "INVALID_MACHINE", "context": None},
            )

        x_axis = profile.get("x")
        y_axis = profile.get("y")
        if not isinstance(x_axis, dict) or not isinstance(y_axis, dict):
            return _debug_return(
                "evaluate_job_geometry",
                {"decision": "INVALID_MACHINE", "context": None},
            )

        # --- read raw image geometry ---
        if effective_source_px is None:
            with Image.open(job.raw_image_path) as img:
                img.load()
                image_w_px = img.width
                image_h_px = img.height
        else:
            image_w_px = int(effective_source_px[0])
            image_h_px = int(effective_source_px[1])
            if image_w_px <= 0 or image_h_px <= 0:
                return _debug_return(
                    "evaluate_job_geometry",
                    {"decision": "INVALID_IMAGE", "context": None},
                )

        requested_width_mm, requested_height_mm = job.size_mm

        # --- physical requirement ---
        axis = job.engrave_axis or "X"
        if axis not in ("X", "Y"):
            return _debug_return(
                "evaluate_job_geometry",
                {"decision": "INVALID_MACHINE", "context": None},
            )

        if axis == "X":
            step_axis_steps = profile["y"]["steps_per_mm"]
            if step_axis_steps <= 0:
                return _debug_return(
                    "evaluate_job_geometry",
                    {"decision": "INVALID_MACHINE", "context": None},
                )
            raster = choose_mechanical_raster(
                requested_dpi=job.requested_dpi,
                steps_per_mm=step_axis_steps,
            )
            if not raster.valid:
                return _debug_return(
                    "evaluate_job_geometry",
                    {"decision": "INVALID_MACHINE", "context": None},
                )
            real_pitch_mm = raster.real_pitch_mm
            real_lines, effective_height_mm = snap_line_count(
                requested_height_mm,
                real_pitch_mm,
            )
            image_lines_available = image_h_px
            effective_width_mm = float(requested_width_mm)
        else:
            step_axis_steps = profile["x"]["steps_per_mm"]
            if step_axis_steps <= 0:
                return _debug_return(
                    "evaluate_job_geometry",
                    {"decision": "INVALID_MACHINE", "context": None},
                )
            raster = choose_mechanical_raster(
                requested_dpi=job.requested_dpi,
                steps_per_mm=step_axis_steps,
            )
            if not raster.valid:
                return _debug_return(
                    "evaluate_job_geometry",
                    {"decision": "INVALID_MACHINE", "context": None},
                )
            real_pitch_mm = raster.real_pitch_mm
            real_lines, effective_width_mm = snap_line_count(
                requested_width_mm,
                real_pitch_mm,
            )
            image_lines_available = image_w_px
            effective_height_mm = float(requested_height_mm)

        needs_resample = real_lines > image_lines_available
        decision = "REPAIR" if needs_resample else "BASE"

        effective_dpi = 25.4 / real_pitch_mm


        context = {
            "image_width_px": image_w_px,
            "image_height_px": image_h_px,
            "requested_width_mm": requested_width_mm,
            "requested_height_mm": requested_height_mm,
            "requested_dpi": job.requested_dpi,
            "engrave_axis": axis,
            "real_pitch_mm": real_pitch_mm,
            "pitch_mm": real_pitch_mm,
            "step_axis_steps_per_mm": step_axis_steps,
            "steps_per_line": int(raster.steps_per_line),
            "real_lines": real_lines,
            "needs_resample": needs_resample,
            "real_dpi": effective_dpi,
            "effective_dpi": effective_dpi,
            "effective_width_mm": effective_width_mm,
            "effective_height_mm": effective_height_mm,
            "effective_size_mm": (effective_width_mm, effective_height_mm),
        }

        return _debug_return(
            "evaluate_job_geometry",
            {"decision": decision, "context": context},
        )

    except Exception:
        return _debug_return(
            "evaluate_job_geometry",
            {"decision": "INVALID_IMAGE", "context": None},
        )

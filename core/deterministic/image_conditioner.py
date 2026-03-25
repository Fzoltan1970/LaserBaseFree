"""
image_conditioner.py

Deterministic RAW image conditioning for laser-oriented workflows.
"""

from pathlib import Path
import tempfile
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import cv2
from PIL import Image


# ----------------------------------------------------------------------
# Data contracts
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PhysicalIntent:
    physical_size_mm: Tuple[float, float]
    target_dpi: float


@dataclass(frozen=True)
class ConditioningResult:
    image: np.ndarray
    diagnostics: Dict[str, str]


# ----------------------------------------------------------------------
# Core conditioner
# ----------------------------------------------------------------------


class ImageConditioner:
    """
    Deterministic RAW image conditioner.
    Stateless by design.
    """

    def condition(
        self,
        origin_raw: np.ndarray,
        intent: PhysicalIntent,
    ) -> ConditioningResult:

        diagnostics: Dict[str, str] = {}

        image = self._normalize_numeric_domain(origin_raw, diagnostics)

        scale_factor = self._compute_required_scale(
            image.shape,
            intent,
            diagnostics,
        )

        if scale_factor > 1.0:
            image = self._upscale(image, scale_factor, diagnostics)
        else:
            diagnostics["upscale"] = "not required"

        image = self._stabilize_statistics(image, diagnostics)

        return ConditioningResult(image=image, diagnostics=diagnostics)

    # ------------------------------------------------------------------

    def _normalize_numeric_domain(
        self,
        image: np.ndarray,
        diagnostics: Dict[str, str],
    ) -> np.ndarray:

        if image.dtype != np.float32:
            image = image.astype(np.float32) / 255.0
            diagnostics["dtype"] = "normalized to float32 [0..1]"
        else:
            diagnostics["dtype"] = "float32"

        return image

    # ------------------------------------------------------------------

    def _compute_required_scale(
        self,
        shape: Tuple[int, int],
        intent: PhysicalIntent,
        diagnostics: Dict[str, str],
    ) -> float:

        height_px, width_px = shape[:2]
        width_mm, _ = intent.physical_size_mm

        width_inch = width_mm / 25.4
        effective_dpi = width_px / width_inch

        diagnostics["effective_dpi"] = f"{effective_dpi:.2f}"
        diagnostics["target_dpi"] = f"{intent.target_dpi:.2f}"

        scale = intent.target_dpi / effective_dpi

        if scale <= 1.0:
            return 1.0

        diagnostics["scale_factor"] = f"{scale:.3f}"
        return scale

    # ------------------------------------------------------------------

    def _upscale(
        self,
        image: np.ndarray,
        scale: float,
        diagnostics: Dict[str, str],
    ) -> np.ndarray:

        new_h = int(round(image.shape[0] * scale))
        new_w = int(round(image.shape[1] * scale))

        image_up = cv2.resize(
            image,
            (new_w, new_h),
            interpolation=cv2.INTER_LANCZOS4,
        )

        diagnostics["upscale"] = (
            f"lanczos {image.shape[1]}x{image.shape[0]} -> {new_w}x{new_h}"
        )

        return image_up

    # ------------------------------------------------------------------

    def _stabilize_statistics(
        self,
        image: np.ndarray,
        diagnostics: Dict[str, str],
    ) -> np.ndarray:

        image = cv2.GaussianBlur(image, (3, 3), 0.3)
        diagnostics["noise_control"] = "gaussian blur (3x3, sigma=0.3)"

        gamma = 0.95
        image = np.power(image, gamma)
        diagnostics["gamma"] = f"{gamma}"

        image = np.clip(image, 0.0, 1.0)

        return image


# ----------------------------------------------------------------------
# PUBLIC KERNEL ENTRY POINT (UNICODE SAFE)
# ----------------------------------------------------------------------


def condition_for_engraving(input_path: str, context: dict) -> str:
    """
    Kernel-safe wrapper.
    Takes an image path and returns a repaired temporary image path.
    Unicode safe for Windows.
    """

    path = Path(input_path)

    # ---- UNICODE SAFE LOAD ----
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)

    if img is None:
        raise RuntimeError(f"Failed to load image for conditioning: {input_path}")

    # ---- minimal deterministic repair/upscale on step-axis when needed ----
    target_w = int(img.shape[1])
    target_h = int(img.shape[0])

    if isinstance(context, dict):
        axis = context.get("engrave_axis")
        real_lines = context.get("real_lines")
        try:
            required_lines = int(real_lines)
        except (TypeError, ValueError):
            required_lines = None

        if required_lines is not None and required_lines > 0:
            if axis == "X" and required_lines > target_h:
                target_h = required_lines
            elif axis == "Y" and required_lines > target_w:
                target_w = required_lines

    if target_w != img.shape[1] or target_h != img.shape[0]:
        current_w = int(img.shape[1])
        current_h = int(img.shape[0])

        scale_w = (target_w / current_w) if current_w > 0 else 1.0
        scale_h = (target_h / current_h) if current_h > 0 else 1.0
        scale = max(scale_w, scale_h)

        stage_multipliers = []
        if scale <= 1.6:
            stage_multipliers = []
        elif scale <= 2.6:
            stage_multipliers = [2]
        elif scale <= 4.5:
            stage_multipliers = [3]
        elif scale <= 9.0:
            stage_multipliers = [3, 6]
        else:
            stage_multipliers = [3, 6, 12]

        base_w = current_w
        base_h = current_h

        for mul in stage_multipliers:
            next_w = current_w
            next_h = current_h

            if target_w > current_w:
                next_w = int(round(base_w * mul))
            if target_h > current_h:
                next_h = int(round(base_h * mul))

            if next_w != current_w or next_h != current_h:
                img = cv2.resize(img, (next_w, next_h), interpolation=cv2.INTER_LANCZOS4)
                current_w, current_h = next_w, next_h

        if current_w != target_w or current_h != target_h:
            img = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

    # ---- deterministic conditioning ----
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)

    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    img = cv2.filter2D(img, -1, kernel)

    img = cv2.GaussianBlur(img, (3, 3), 0)

    # ---- UNICODE SAFE SAVE ----
    with tempfile.NamedTemporaryFile(
        prefix="lb_repaired_",
        suffix=".png",
        delete=False,
    ) as tmp:
        out_path = Path(tmp.name)

    ok, encoded = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("Failed to encode repaired image")

    repaired_image = Image.open(BytesIO(encoded.tobytes()))
    dpi = context.get("real_dpi") if isinstance(context, dict) else None
    if dpi is None:
        repaired_image.save(str(out_path), format="PNG")
    else:
        repaired_image.save(str(out_path), format="PNG", dpi=(dpi, dpi))

    return str(out_path)


def generate_engrave_image(job, decision_result) -> dict:
    """
    Egyetlen hely ahol tényleges kép keletkezhet.
    A kernel ezt hívja — semmi mást.
    """

    if decision_result.get("decision") == "INVALID_MACHINE":
        return {"ok": False, "error": "Invalid machine"}

    from PIL import Image

    img = Image.open(job.raw_image_path).convert("L")

    width_mm = float(decision_result["context"]["requested_width_mm"])
    height_mm = float(decision_result["context"]["requested_height_mm"])

    # BASE = nincs javítás, csak normalizált forrás
    return {
        "ok": True,
        "engrave_image": img,
        "processed_info": {
            "px_width": img.width,
            "px_height": img.height,
            "dpi": decision_result["context"]["real_dpi"],
            "size_mm": (width_mm, height_mm),
        },
    }

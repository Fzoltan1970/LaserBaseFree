# ------------------------------------------------------------------
# ROLE NOTE (IMPORTANT)
#
# This module DOES NOT participate in DPI estimation, size validation,
# or workflow decisions.
#
# Intended canonical role:
# - Descriptive visual analysis of an image (contrast, noise, sharpness, etc.)
# - To be displayed ONLY AFTER a BASE image exists
# - Placement: bottom informational bar (non-decisional UI zone)
#
# This analysis is:
# - NOT RAW source of truth
# - NOT geometric
# - NOT size-dependent
#
# The module is currently informational only.
# ------------------------------------------------------------------


import os
import cv2
import numpy as np


def _safe_scale(value, divisor, min_val=0, max_val=100):
    """Skálázó segédfüggvény 0–100 közé."""
    return float(np.clip(value / divisor, min_val, max_val))


def analyze_image(image_path: str) -> dict:
    # 🔧 Path normalizálás (ékezet és visszafelé perjel)
    image_path = os.path.normpath(image_path)

    # 🔓 Unicode kompatibilis betöltés (Windows-on ajánlott)
    try:
        img = cv2.imdecode(
            np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
        )
    except Exception:
        img = None

    # 🚨 Ha sikertelen volt – próbáljuk meg klasszikus módszerrel is
    if img is None:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

    if img is None:
        raise ValueError(f"Kép nem található vagy sérült: {image_path}")

    try:
        height, width = img.shape

        # 🎯 1. Élesség
        laplacian = cv2.Laplacian(img, cv2.CV_64F).var()
        sharpness = _safe_scale(laplacian, 10, 1)

        # 🎯 2. Kontraszt
        std_dev = img.std()
        contrast = _safe_scale(std_dev, 2.5, 1)

        # 🎯 3. Fényerő
        brightness = _safe_scale(img.mean(), 2.55)

        # 🎯 4. Zajszint
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        noise_map = cv2.absdiff(img, blurred)
        noise_var = float(np.var(noise_map))
        noise = _safe_scale(noise_var, 5, 0, 100)

        return {
            "sharpness": round(sharpness, 2),
            "contrast": round(contrast, 2),
            "brightness": round(brightness, 2),
            "noise": round(noise, 2),
            "resolution_px": (width, height),
        }

    except Exception as e:
        raise ValueError(f"Képanalízis során hiba történt: {e}")

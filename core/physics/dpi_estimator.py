"""
core/dpi_estimator.py

Kép fájl alapú automatikus DPI becslés képgravírozáshoz.

"""

from core.deterministic.image_analyzer import analyze_image
from PIL import Image
from PIL.TiffImagePlugin import IFDRational


def estimate_dpi_from_quality(
    analysis: dict, target_dpi_user: int, laser_info: dict
) -> dict:
    """
    :param analysis: image_analyzer kimeneti dict (sharpness, contrast, noise)
    :param target_dpi_user: felhasználó által megadott DPI kívánság
    :param laser_info: dict, pl. {"max_dpi": 318}
    :return: RAW quality elemzés eredménye (suggested_dpi + quality_metrics)
    :raises ValueError: ha az elemzési adatok hiányosak
    """

    try:
        sharp = float(analysis.get("sharpness", 0))
        contrast = float(analysis.get("contrast", 0))
        noise = float(
            analysis.get("noise", 50)
        )  # ha nincs megadva, közepes zajszinttel dolgozunk

        # ⚠ Biztonsági ellenőrzés
        if sharp <= 0 or contrast <= 0:
            raise ValueError(
                "A képanalízis értékei hibásak vagy nullák - nem számítható DPI minőség."
            )

        # 📐 DPI minőség számítás súly alapján
        dpi_quality = (sharp * 0.6) + (contrast * 0.25) + ((100 - noise) * 0.15)

        # 📉 Minimális DPI garancia (gyenge képnél is)
        dpi_quality = max(80, dpi_quality)

        # 📈 Maximális DPI korlát technikai oldalról
        max_dpi_by_laser = int(laser_info.get("max_dpi", dpi_quality))
        dpi_quality = min(dpi_quality, max_dpi_by_laser)

        # 🧊 Felhasználói cél korlát
        dpi_quality = min(dpi_quality, target_dpi_user)

        return {
            "suggested_dpi": int(round(dpi_quality)),
            "quality_metrics": {
                "sharpness": sharp,
                "contrast": contrast,
                "noise": noise,
                "quality_score": float(dpi_quality),
                "target_dpi_user": int(target_dpi_user),
                "max_dpi_by_laser": max_dpi_by_laser,
            },
        }

    except Exception as e:
        raise ValueError(f"DPI minőségbecslő számítási hiba: {e}")


def estimate_dpi(
    image_path: str,
    target_dpi_user: int,
    laser_info: dict | None = None,
) -> dict:
    """
    Teljes RAW quality DPI becslés.
    :param image_path: kép fájlútvonal
    :param target_dpi_user: felhasználó által megadott DPI cél
    :param laser_info: gépprofil (max_dpi), opcionális
    :return: kizárólag suggested_dpi + quality_metrics
    """
    analysis = analyze_image(image_path)
    if laser_info is None:
        laser_info = {}

    quality_result = estimate_dpi_from_quality(
        analysis,
        int(target_dpi_user),
        laser_info,
    )

    return {
        "suggested_dpi": quality_result["suggested_dpi"],
        "quality_metrics": {
            **quality_result["quality_metrics"],
            "image_analysis": analysis,
        },
    }


def estimate_raw_info(image_path: str) -> dict:
    """
    RAW-only image self-description.
    Intended ONLY for infobar display.
    """
    img = Image.open(image_path)
    width_px, height_px = img.size

    raw_dpi = None
    dpi_source = None

    def _to_float(value):
        try:
            if isinstance(value, IFDRational):
                return float(value)
            if isinstance(value, tuple) and len(value) == 2 and value[1]:
                return float(value[0]) / float(value[1])
            return float(value)
        except Exception:
            return None

    # 1️⃣ EXIF (JPEG / TIFF)
    try:
        exif = img.getexif()
        if exif:
            x_res = _to_float(exif.get(282))  # XResolution
            y_res = _to_float(exif.get(283))  # YResolution
            unit = exif.get(296)  # ResolutionUnit

            res = x_res or y_res
            if res and res > 0:
                if unit == 3:  # cm
                    raw_dpi = res * 2.54
                else:  # inch or missing
                    raw_dpi = res
                dpi_source = "exif"
    except Exception:
        pass

    # 2️⃣ JFIF density (JPEG)
    if raw_dpi is None:
        try:
            density = img.info.get("jfif_density")
            unit = img.info.get("jfif_unit")
            if density and density[0] > 0:
                if unit == 1:  # DPI
                    raw_dpi = float(density[0])
                    dpi_source = "jfif"
                elif unit == 2:  # DPCM
                    raw_dpi = float(density[0]) * 2.54
                    dpi_source = "jfif"
        except Exception:
            pass

    # 3️⃣ PNG DPI (Pillow standard: img.info["dpi"])
    if raw_dpi is None:
        try:
            dpi_info = img.info.get("dpi")
            if dpi_info and isinstance(dpi_info, (tuple, list)):
                x_dpi = float(dpi_info[0])
                if x_dpi > 0:
                    raw_dpi = x_dpi
                    dpi_source = "png_dpi"
        except Exception:
            pass

    # 4️⃣ PNG pHYs (pixels per meter)
    if raw_dpi is None:
        try:
            phys = img.info.get("physical")
            if phys and len(phys) == 3:
                ppm_x, ppm_y, unit = phys
                if unit == 1 and ppm_x > 0:
                    raw_dpi = float(ppm_x) * 0.0254
                    dpi_source = "png_phys"
        except Exception:
            pass

    # 5️⃣ Physical size ONLY if RAW DPI exists
    if raw_dpi and raw_dpi > 0:
        physical_mm = (
            width_px / raw_dpi * 25.4,
            height_px / raw_dpi * 25.4,
        )
    else:
        physical_mm = None

    return {
        "resolution_px": (width_px, height_px),
        "raw_dpi": raw_dpi,
        "raw_physical_mm": physical_mm,
        "raw_dpi_source": dpi_source,
    }

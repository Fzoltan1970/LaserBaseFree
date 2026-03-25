import cv2
import numpy as np


class SimplifyTool:
    """
    Vonal egyszerűsítés és kisimítás.
    """

    def __init__(self, strength=1):
        # 1..3 ajánlott
        self.strength = max(1, int(strength))

    # --------------------------------------------------
    # FŐ MŰVELET
    # --------------------------------------------------
    def apply(self, sketch):
        """
        sketch: uint8 grayscale rajz (0..255)
        return: egyszerűsített rajz
        """

        if sketch is None:
            return sketch

        # bináris (fekete = vonal)
        binary = (sketch < 200).astype(np.uint8) * 255

        # morfológiai nyitás/zárás kisimít
        k = 1 + self.strength * 2
        kernel = np.ones((k, k), np.uint8)

        smooth = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        smooth = cv2.morphologyEx(smooth, cv2.MORPH_OPEN, kernel, iterations=1)

        # vissza grayscale formába
        result = sketch.copy()
        result[smooth == 0] = 255
        result[smooth > 0] = 0

        return result



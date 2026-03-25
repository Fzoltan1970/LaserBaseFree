import cv2
import numpy as np


class CleanTool:
    """
    Apró zajok eltávolítása a kész rajzból.
    """

    def __init__(self, min_size=25):
        # ennél kisebb komponensek törlődnek
        self.min_size = min_size

    # --------------------------------------------------
    # FŐ MŰVELET
    # --------------------------------------------------
    def apply(self, sketch):
        """
        sketch: uint8 grayscale rajz (0..255)
        return: tisztított rajz
        """

        if sketch is None:
            return sketch

        # bináris (fekete = rajz)
        binary = (sketch < 200).astype(np.uint8)

        num, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

        cleaned = sketch.copy()

        for i in range(1, num):  # 0 = háttér
            area = stats[i, cv2.CC_STAT_AREA]

            if area < self.min_size:
                cleaned[labels == i] = 255  # törlés (fehér)

        return cleaned

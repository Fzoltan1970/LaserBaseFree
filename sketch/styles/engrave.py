import cv2
import numpy as np
from .base import SketchStyle


class EngraveStyle(SketchStyle):

    name = "Engrave"

    def generate(self, gray, detail, strength):

        # --------------------------------------------------
        # 1) ERŐS SIMÍTÁS (zaj tiltva)
        # --------------------------------------------------
        smooth = cv2.bilateralFilter(gray, 9, 70, 70)
        smooth = cv2.GaussianBlur(smooth, (0, 0), 2)

        # --------------------------------------------------
        # 2) BINÁRIS TÓNUS (nem szürke!)
        # --------------------------------------------------
        block = 25 + int((100-detail)/3)

        tone = cv2.adaptiveThreshold(
            smooth,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block | 1,
            4
        )

        # --------------------------------------------------
        # 3) FORMÁK KITÖLTÉSE
        # --------------------------------------------------
        kernel = np.ones((3,3), np.uint8)
        tone = cv2.morphologyEx(tone, cv2.MORPH_CLOSE, kernel, iterations=2)

        # --------------------------------------------------
        # 4) ERŐS KONTÚR
        # --------------------------------------------------
        edges = self.p.line_sketch(smooth, detail, strength)

        # csak nagy élek maradjanak
        big = cv2.GaussianBlur(gray, (0,0), 4)
        big_grad = cv2.Laplacian(big, cv2.CV_32F)
        big_grad = cv2.convertScaleAbs(big_grad)
        edges[big_grad < 18] = 0

        # kontúr vastagítás
        thick = 1 + int(strength / 20)
        k = np.ones((thick, thick), np.uint8)
        edges = cv2.dilate(edges, k, iterations=1)

        # --------------------------------------------------
        # 5) KONTÚR + TÖMEG EGYESÍTÉS
        # --------------------------------------------------
        tone = cv2.bitwise_and(tone, cv2.bitwise_not(edges))

        return tone, edges

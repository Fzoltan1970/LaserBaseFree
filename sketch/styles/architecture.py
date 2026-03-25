import cv2
import numpy as np
from .base import SketchStyle


class ArchitectureStyle(SketchStyle):

    name = "Architecture"

    def generate(self, gray, detail, strength):

        # --------------------------------------------------
        # 1) TEXTÚRA ELTÁVOLÍTÁS (fal, tégla, vakolat)
        # --------------------------------------------------
        smooth = cv2.bilateralFilter(gray, 11, 60, 60)
        smooth = cv2.GaussianBlur(smooth, (0, 0), 1.5)

        # --------------------------------------------------
        # 2) TÓNUS (lapos felületek)
        # --------------------------------------------------
        tone = self.p.tone_sketch(smooth.astype(np.uint8), detail, strength)

        # tónus kvantálás (rajzos síkok)
        levels = 6 + int(detail / 20)
        tone = (tone.astype(np.float32) / 255.0)
        tone = np.floor(tone * levels) / levels
        tone = (tone * 255).astype(np.uint8)

        # --------------------------------------------------
        # 3) ÉLEK (geometriai él prioritás)
        # --------------------------------------------------
        edges = self.p.line_sketch(smooth, detail, strength)

        # --------------------------------------------------
        # 4) EGYENESEK KIEMELÉSE (Hough)
        # --------------------------------------------------
        canny = cv2.Canny(smooth, 60, 140)
        lines = cv2.HoughLinesP(canny, 1, np.pi/180, 60,
                                minLineLength=40, maxLineGap=10)

        if lines is not None:
            for l in lines:
                x1, y1, x2, y2 = l[0]
                cv2.line(edges, (x1, y1), (x2, y2), 255, 2)

        # --------------------------------------------------
        # 5) APRÓ ÉL TÖRLÉS
        # --------------------------------------------------
        small = cv2.Laplacian(gray, cv2.CV_32F)
        small = cv2.convertScaleAbs(small)
        edges[small < 14] = 0

        return tone, edges

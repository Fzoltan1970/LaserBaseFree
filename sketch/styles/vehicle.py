import cv2
import numpy as np
from .base import SketchStyle


class VehicleStyle(SketchStyle):

    name = "Vehicle"

    def generate(self, gray, detail, strength):

        # --------------------------------------------------
        # 1) KAROSSZÉRIA SIMÍTÁS (fényes felület)
        # --------------------------------------------------
        body = cv2.bilateralFilter(gray, 9, 55, 55)
        body = cv2.GaussianBlur(body, (0, 0), 1.2)

        # apró textúra csökkentés
        texture = cv2.subtract(gray, body)
        body = (
            cv2.add(body.astype("float32"), (texture.astype("float32") * 0.25))
            .clip(0, 255)
            .astype("uint8")
        )

        # --------------------------------------------------
        # 2) TÓNUS
        # --------------------------------------------------
        tone = self.p.tone_sketch(body.astype(np.uint8), detail, strength)

        # ablakok sötétítése (tipikus jármű jelleg)
        dark = cv2.GaussianBlur(gray, (0, 0), 4)
        window_mask = dark < 85
        tone[window_mask] = tone[window_mask] * 0.7

        # --------------------------------------------------
        # 3) STRUKTURÁLT ÉLEK
        # --------------------------------------------------
        structure = cv2.bilateralFilter(gray, 7, 35, 35)
        edges = self.p.line_sketch(structure, detail, strength)

        # --------------------------------------------------
        # 4) APRÓ RÁCS / ZAJ ELTÁVOLÍTÁS
        # --------------------------------------------------
        small = cv2.Laplacian(gray, cv2.CV_32F)
        small = cv2.convertScaleAbs(small)
        edges[small < 14] = 0

        # --------------------------------------------------
        # 5) JELLEGZETES RÉSZEK KIEMELÉSE
        # kerekek + lámpák
        # --------------------------------------------------
        big = cv2.GaussianBlur(gray, (0, 0), 3)
        big_grad = cv2.Laplacian(big, cv2.CV_32F)
        big_grad = cv2.convertScaleAbs(big_grad)

        focus = big_grad > 18
        edges[focus] = np.clip(edges[focus] * 1.35, 0, 255)

        return tone, edges

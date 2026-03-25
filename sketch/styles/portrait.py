import cv2
import numpy as np
from .base import SketchStyle


class PortraitStyle(SketchStyle):

    name = "Portrait"

    def generate(self, gray, detail, strength):

        # --------------------------------------------------
        # 1) BŐR SIMÍTÁS (strukturális blur, nem sima blur)
        # --------------------------------------------------
        smooth = cv2.bilateralFilter(gray, 9, 40 + detail, 40 + detail)

        # textúra kivonása
        texture = cv2.subtract(gray, smooth)

        # bőr textúra gyengítése
        texture = cv2.GaussianBlur(texture, (0, 0), 1.2)
        skin_soft = (
            cv2.add(smooth.astype("float32"), (texture.astype("float32") * 0.35))
            .clip(0, 255)
            .astype("uint8")
        )

        # --------------------------------------------------
        # 2) TÓNUS (a meglévő motorral)
        # --------------------------------------------------
        tone = self.p.tone_sketch(skin_soft.astype(np.uint8), detail, strength)

        # --------------------------------------------------
        # 3) FONTOS ÉLEK (nem minden él!)
        # --------------------------------------------------
        structure = cv2.bilateralFilter(gray, 7, 25, 25)

        edges = self.p.line_sketch(structure, detail, strength)

        # --------------------------------------------------
        # 4) ÁRNYÉKBAN NINCS KONTÚR (nagyon fontos portrénál)
        # --------------------------------------------------
        shadow_mask = tone < 90
        edges[shadow_mask] = (edges[shadow_mask] * 0.4).astype(np.uint8)

        # --------------------------------------------------
        # 5) SZEM + SZÁJ KONTRASZT KIEMELÉS
        # (lokális kontraszt → arc élőbb lesz)
        # --------------------------------------------------
        lap = cv2.Laplacian(gray, cv2.CV_32F)
        lap = cv2.convertScaleAbs(lap)

        focus = lap > 18
        edges[focus] = np.clip(edges[focus] * 1.25, 0, 255)

        return tone, edges

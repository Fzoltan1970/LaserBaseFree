class SketchStyle:
    """
    Alap osztály minden rajz stílushoz.

    A stílus feladata:
    - a szürke képből tone és line képet készíteni
    - NEM kever, NEM jelenít meg
    - NEM foglalkozik soft/strong móddal

    A keverést az ImageProcessor végzi.
    """

    name = "Base"

    def __init__(self, processor):
        # hozzáférés a meglévő motor függvényeihez
        self.p = processor

    # --------------------------------------------------
    # Kötelező: rajz generálás
    # --------------------------------------------------
    def generate(self, gray, detail, strength):
        """
        Paraméterek
        ----------
        gray : np.ndarray
            előkészített szürke kép (auto_prep után)

        detail : int (0-100)
            absztrakció mértéke

        strength : int (0-100)
            eszköz erőssége

        Visszatérés
        ----------
        tone : np.ndarray uint8
        line : np.ndarray uint8
        """
        raise NotImplementedError("Style must implement generate()")

import cv2
import numpy as np


class ImageProcessor:

    def __init__(self, model_manager):
        self.models = model_manager
        self.active_model = None

        # cache az AI maszkhoz
        self._cached_mask = None
        self._cached_mask_img = None

    # --------------------------------------------------------
    # GYORS KÉP AZONOSÍTÓ
    # --------------------------------------------------------
    def _img_id(self, img):
        h, w = img.shape[:2]
        step_h = max(h // 4, 1)
        step_w = max(w // 4, 1)
        sample = img[::step_h, ::step_w]
        return hash(sample.tobytes())

    # --------------------------------------------------------
    # AI MASZK (U2Net)
    # --------------------------------------------------------
    def ai_mask(self, img):
        session = self.models.get(self.active_model)
        if session is None:
            return None

        h, w = img.shape[:2]

        small = cv2.resize(img, (320, 320))
        inp = small.astype(np.float32) / 255.0
        inp = np.transpose(inp, (2, 0, 1))[np.newaxis, :, :, :]

        input_name = session.get_inputs()[0].name
        pred = session.run(None, {input_name: inp})[0][0][0]

        pred = cv2.resize(pred, (w, h))
        pred = cv2.normalize(pred, None, 0, 1, cv2.NORM_MINMAX)

        return pred.astype(np.float32)

    # --------------------------------------------------------
    # ELŐKÉSZÍTÉS
    # --------------------------------------------------------
    def auto_prep(self, img):

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        if self.active_model == "Téma kiemelés":

            img_id = self._img_id(img)

            if self._cached_mask_img != img_id:
                self._cached_mask = self.ai_mask(img)
                self._cached_mask_img = img_id

            mask = self._cached_mask

            if mask is not None:
                background = cv2.GaussianBlur(gray, (0, 0), 5)
                gray = (gray * mask + background * (1 - mask)).astype(np.uint8)

        return gray

    # --------------------------------------------------------
    # TÓNUS RAJZ
    # --------------------------------------------------------
    def tone_sketch(self, img, detail=50, strength=50):

        gray = img.copy()

        g = gray.astype(np.float32) / 255.0
        g = np.power(g, 1.35)
        gray = (g * 255).astype(np.uint8)

        inv = 255 - gray

        blur_size = int(15 + (100 - detail) * 0.6)
        if blur_size % 2 == 0:
            blur_size += 1

        blur = cv2.GaussianBlur(inv, (blur_size, blur_size), 0)

        denom = 255 - blur
        denom = np.maximum(denom, 8)
        sketch = (gray.astype(np.float32) / denom.astype(np.float32)) * 256.0
        sketch = np.clip(sketch, 0, 255).astype(np.uint8)

        alpha = 1.0 + strength / 40.0
        sketch = cv2.convertScaleAbs(sketch, alpha=alpha, beta=-20)

        _, sketch = cv2.threshold(sketch, 240, 255, cv2.THRESH_TRUNC)

        return sketch

    # --------------------------------------------------------
    # VONAL RAJZ
    # --------------------------------------------------------
    def line_sketch(self, img, detail=50, strength=50):

        gray = img.copy()

        light = cv2.GaussianBlur(gray, (0, 0), 25)
        norm = cv2.divide(gray, light, scale=255)

        def sobel_mag(src, k):
            gx = cv2.Sobel(src, cv2.CV_32F, 1, 0, ksize=k)
            gy = cv2.Sobel(src, cv2.CV_32F, 0, 1, ksize=k)
            return cv2.magnitude(gx, gy)

        mag_small = sobel_mag(norm, 3)
        mag_mid = sobel_mag(norm, 5)
        mag_big = sobel_mag(norm, 9)

        mag = 0.5 * mag_small + 0.35 * mag_mid + 0.15 * mag_big

        gx = cv2.Sobel(norm, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(norm, cv2.CV_32F, 0, 1, ksize=3)
        angle = cv2.phase(gx, gy, angleInDegrees=False)
        angle_smooth = cv2.GaussianBlur(angle, (9, 9), 0)

        coherence = np.abs(np.sin(angle - angle_smooth))
        coherence = cv2.normalize(coherence, None, 0, 1, cv2.NORM_MINMAX)

        mag = mag * (1 - coherence)

        mag = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

        blur = int(3 + (100 - detail) / 18) | 1
        mag = cv2.GaussianBlur(mag, (blur, blur), 0)

        local_var = cv2.GaussianBlur(mag.astype(np.float32)**2, (31,31),0) - \
                    cv2.GaussianBlur(mag.astype(np.float32), (31,31),0)**2

        local_var = cv2.normalize(local_var, None, 0, 1, cv2.NORM_MINMAX)

        base_t = 140 - detail * 0.9
        T = base_t + (local_var * 60)

        bw = (mag > T).astype(np.uint8) * 255
        bw = 255 - bw

        thickness = 1 + int(strength / 12)
        kernel = np.ones((thickness, thickness), np.uint8)
        bw = cv2.dilate(bw, kernel, iterations=1)

        return bw

    # --------------------------------------------------------
    # FŐ FÜGGVÉNY  (CSAK EZ VÁLTOZOTT!)
    # --------------------------------------------------------
    def process(self, img, mode="soft", detail=50, strength=50):

        prep = self.auto_prep(img)

        tone = self.tone_sketch(prep, detail, strength)
        line = self.line_sketch(prep, detail, strength)

        if mode == "soft":
            line_w = 0.35 + strength/300.0
        else:
            line_w = 0.85 + strength/150.0

        # ---- SZUBTRAKTÍV GRAFIT MODELL ----
        line_mask = line.astype(np.float32) / 255.0
        line_mask = cv2.GaussianBlur(line_mask, (0, 0), 0.6)

        sketch = tone.astype(np.float32) * (1 - line_mask * line_w)
        sketch = np.clip(sketch, 0, 255).astype(np.uint8)

        return sketch

import cv2
import numpy as np

from styles.default import DefaultStyle


class ImageProcessor:

    def __init__(self, model_manager=None):
        self.models = model_manager
        self.active_model = None

        # cache az AI maszkhoz
        self._cached_mask = None
        self._cached_mask_img = None

        # aktuális kép (crop után)
        self._current_image = None

        # aktív rajz stílus
        self.style = DefaultStyle(self)

        # last line layer for edit system
        self.last_line = None
        self._cached_prep_key = None
        self._cached_proc_img = None
        self._cached_proc_scale = None
        self._cached_prep = None

    # --------------------------------------------------------
    # KÉP BETÖLTÉS (CACHE RESET)
    # --------------------------------------------------------
    def set_image(self, img):
        """Új kép beállítása – cache törlése"""
        self._cached_mask = None
        self._cached_mask_img = None
        self._cached_prep_key = None
        self._cached_proc_img = None
        self._cached_proc_scale = None
        self._cached_prep = None

        if img is not None:
            self._current_image = self.auto_crop(img)
        else:
            self._current_image = None

    # --------------------------------------------------------
    # AUTO CROP (keret eltávolítás)
    # --------------------------------------------------------
    def auto_crop(self, img):

        if img is None:
            return img

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 20, 80)

        coords = cv2.findNonZero(edges)
        if coords is None:
            return img

        x, y, w, h = cv2.boundingRect(coords)

        area_original = img.shape[0] * img.shape[1]
        area_crop = w * h

        if area_crop > area_original * 0.97:
            return img

        pad = 4
        x = max(x - pad, 0)
        y = max(y - pad, 0)
        w = min(w + pad * 2, img.shape[1] - x)
        h = min(h + pad * 2, img.shape[0] - y)

        return img[y : y + h, x : x + w]

    # --------------------------------------------------------
    # GYORSÍTÁS – feldolgozási felbontás limit
    # --------------------------------------------------------
    def _resize_for_processing(self, img, max_side=1600):
        h, w = img.shape[:2]
        scale = min(1.0, max_side / max(h, w))

        if scale == 1.0:
            return img, 1.0

        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return resized, scale

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
        session = self.models.get(self.active_model) if self.models else None
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
    # HÁTTÉR MASZK ALKALMAZÁS (eredeti működés)
    # --------------------------------------------------------
    def apply_mask(self, sketch, mask, clean):

        if mask is None:
            return sketch

        m = np.clip(mask, 0, 1).astype(np.float32)

        # háttér fehérítés erőssége
        if clean < 100:
            fade = clean / 100.0
            background = (sketch * (1 - fade) + 255 * fade).astype(np.uint8)
        else:
            background = np.full_like(sketch, 255)

        result = sketch * m + background * (1 - m)
        return result.astype(np.uint8)

    # --------------------------------------------------------
    # ELŐKÉSZÍTÉS
    # --------------------------------------------------------
    def auto_prep(self, img, clean=0):

        # clean slider paraméter (jelenleg kompatibilitás miatt)
        _ = clean

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        if self.active_model == "Téma kiemelés":

            img_id = (self._img_id(img), img.shape[1], img.shape[0])

            if self._cached_mask_img != img_id:
                self._cached_mask = self.ai_mask(img)
                self._cached_mask_img = img_id

            mask = self._cached_mask

            if mask is not None:
                background = cv2.GaussianBlur(gray, (0, 0), 5)
                gray = (gray * mask + background * (1 - mask)).astype(np.uint8)
        # --- TONE RECONSTRUCTION (csak lapos képre) ---
        if gray.std() < (18 + 0.01 * gray.mean()):
            gray = self.reconstruct_tone(gray)

        return gray

    def reconstruct_tone(self, gray):

        # 1. Nagyléptékű fény (forma)
        large = cv2.GaussianBlur(gray, (0,0), 35)

        # 2. Közép léptékű árnyék
        medium = cv2.GaussianBlur(gray, (0,0), 9)

        # 3. Textúra eltávolítás
        detail = cv2.subtract(medium, large)

        # 4. Forma visszaépítés
        tone = cv2.addWeighted(large, 1.2, detail, 0.6, 0)

        # 5. Normalizálás
        tone = cv2.normalize(tone, None, 0, 255, cv2.NORM_MINMAX)

        return tone.astype(np.uint8)

    # --------------------------------------------------------
    # TÓNUS RAJZ (méretfüggetlen blur)
    # --------------------------------------------------------
    def tone_sketch(self, img, detail=50, strength=50):

        gray = img.copy()

        g = gray.astype(np.float32) / 255.0
        g = np.power(g, 1.35)
        gray = (g * 255).astype(np.uint8)

        inv = 255 - gray

        # --- FELBONTÁSFÜGGŐ BLUR MÉRET ---
        h, w = gray.shape[:2]
        diag = (h * h + w * w) ** 0.5
        scale = diag / 1500.0  # referencia méret ~1.5MP

        blur_size = int((15 + (100 - detail) * 0.6) * scale)
        blur_size = max(3, blur_size)
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

        local_var = (
            cv2.GaussianBlur(mag.astype(np.float32) ** 2, (31, 31), 0)
            - cv2.GaussianBlur(mag.astype(np.float32), (31, 31), 0) ** 2
        )

        local_var = cv2.normalize(local_var, None, 0, 1, cv2.NORM_MINMAX)

        base_t = 140 - detail * 0.9
        T = base_t + (local_var * 60)

        bw = (mag > T).astype(np.uint8) * 255
        bw = 255 - bw

        thickness = 1 + int(strength / 12)
        kernel = np.ones((thickness, thickness), np.uint8)
        bw = cv2.dilate(bw, kernel, iterations=1)

        self.last_line = bw.copy()
        return bw

    # --------------------------------------------------------
    # FŐ FÜGGVÉNY
    # --------------------------------------------------------
    def process(self, img=None, mode="soft", detail=50, strength=50, clean=0):

        if img is not None:
            self.set_image(img)

        if self._current_image is None:
            return None

        prep_key = (
            self._img_id(self._current_image),
            self._current_image.shape[1],
            self._current_image.shape[0],
            self.active_model,
        )
        if self._cached_prep_key == prep_key and self._cached_prep is not None:
            proc_img = self._cached_proc_img.copy()
            scale = self._cached_proc_scale
            prep = self._cached_prep.copy()
        else:
            proc_img, scale = self._resize_for_processing(self._current_image, 1600)
            prep = self.auto_prep(proc_img, clean)
            self._cached_prep_key = prep_key
            self._cached_proc_img = proc_img.copy()
            self._cached_proc_scale = scale
            self._cached_prep = prep.copy()

        if self.style is None:
            # EREDETI PROGRAM
            tone = self.tone_sketch(prep, detail, strength)
            line = self.line_sketch(prep, detail, strength)
        else:
            # CSAK PRESET esetén
            tone, line = self.style.generate(prep, detail, strength)

        line_inv = 255 - line

        if mode == "soft":
            # EREDETI CERUZA
            tone_w = 1.0
            line_w = 0.35 + strength / 300.0
            sketch = cv2.addWeighted(tone, tone_w, line_inv, line_w, 0)

        else:
            # EREDETI TOLL
            tone_w = 0.75
            line_w = 0.85 + strength / 150.0
            sketch = cv2.addWeighted(tone, tone_w, line_inv, line_w, 0)

        # line layer visszaméretezése az edit rendszerhez
        if scale != 1.0:
            self.last_line = cv2.resize(
                line,
                (self._current_image.shape[1], self._current_image.shape[0]),
                interpolation=cv2.INTER_NEAREST
            )
        else:
            self.last_line = line

        # --------------------------------------------------
        # PORTRAIT BACKGROUND CLEAN
        # --------------------------------------------------
        if clean > 0:
            sigma_space = 2 + clean * 0.25
            sigma_color = 10 + clean * 1.2

            sketch = cv2.bilateralFilter(
                sketch,
                d=0,
                sigmaColor=sigma_color,
                sigmaSpace=sigma_space
            )

        # visszaméretezés
        if scale != 1.0:
            sketch = cv2.resize(
                sketch,
                (self._current_image.shape[1], self._current_image.shape[0]),
                interpolation=cv2.INTER_LINEAR
            )

        # AI maszk (mérethelyesen!)
        if self.active_model == "Téma kiemelés" and self._cached_mask is not None:

            mask = self._cached_mask

            # stabil perem (mindig kell)
            mask_bin = (mask > 0.5).astype(np.uint8) * 255

            if scale != 1.0:
                mask = cv2.resize(
                    mask_bin,
                    (self._current_image.shape[1], self._current_image.shape[0]),
                    interpolation=cv2.INTER_NEAREST
                ).astype(np.float32) / 255.0
            else:
                mask = mask_bin.astype(np.float32) / 255.0

            sketch = self.apply_mask(sketch, mask, clean)

        return sketch

       


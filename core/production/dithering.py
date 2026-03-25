from __future__ import annotations

from PIL import Image
import numpy as np

# --- optional numba (nem kötelező függőség) ---
try:
    from numba import njit

    _HAS_NUMBA = True
except Exception:
    _HAS_NUMBA = False

print(f"[dither] numba available: {_HAS_NUMBA}")

Kernel = list[tuple[int, int, int]]

FLOYD_STEINBERG_KERNEL: Kernel = [
    (1, 0, 7),
    (-1, 1, 3),
    (0, 1, 5),
    (1, 1, 1),
]

ATKINSON_KERNEL: Kernel = [
    (1, 0, 1),
    (2, 0, 1),
    (-1, 1, 1),
    (0, 1, 1),
    (1, 1, 1),
    (0, 2, 1),
]

JJN_KERNEL: Kernel = [
    (1, 0, 7),
    (2, 0, 5),
    (-2, 1, 3),
    (-1, 1, 5),
    (0, 1, 7),
    (1, 1, 5),
    (2, 1, 3),
    (-2, 2, 1),
    (-1, 2, 3),
    (0, 2, 5),
    (1, 2, 3),
    (2, 2, 1),
]

STUCKI_KERNEL: Kernel = [
    (1, 0, 8),
    (2, 0, 4),
    (-2, 1, 2),
    (-1, 1, 4),
    (0, 1, 8),
    (1, 1, 4),
    (2, 1, 2),
    (-2, 2, 1),
    (-1, 2, 2),
    (0, 2, 4),
    (1, 2, 2),
    (2, 2, 1),
]

DITHER_MODES: dict[str, tuple[Kernel, int]] = {
    "FloydSteinberg": (FLOYD_STEINBERG_KERNEL, 16),
    "Atkinson": (ATKINSON_KERNEL, 8),
    "JJN": (JJN_KERNEL, 48),
    "Stucki": (STUCKI_KERNEL, 42),
}

ORDERED_DITHER_MODES = {
    "BAYER",
}

BINARY_DITHER_MODES = set(DITHER_MODES.keys()) | {
    "BAYER",
}

# --- kernel packing cache (mode_name -> arrays) ---
# pack: (dx_ltr, dy_ltr, w_ltr, dx_rtl, dy_rtl, w_rtl, divisor)
_KERNEL_PACKS: dict[
    str,
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int],
] = {}


def _kernel_to_arrays(kernel: Kernel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k = np.asarray(kernel, dtype=np.int32)  # (n,3)
    dx = k[:, 0].copy()
    dy = k[:, 1].copy()
    w = k[:, 2].copy()
    return dx, dy, w


def _get_kernel_pack(mode_name: str, kernel: Kernel, divisor: int):
    pack = _KERNEL_PACKS.get(mode_name)
    if pack is not None:
        return pack
    dx_ltr, dy_ltr, w_ltr = _kernel_to_arrays(kernel)
    dx_rtl = (-dx_ltr).copy()
    dy_rtl = dy_ltr.copy()
    w_rtl = w_ltr.copy()
    pack = (dx_ltr, dy_ltr, w_ltr, dx_rtl, dy_rtl, w_rtl, int(divisor))
    _KERNEL_PACKS[mode_name] = pack
    return pack


if _HAS_NUMBA:

    @njit(cache=True, fastmath=True)
    def _dither_ed_numba(
        work: np.ndarray,  # float32 HxW
        out: np.ndarray,  # uint8  HxW
        dx_ltr: np.ndarray,
        dy_ltr: np.ndarray,
        w_ltr: np.ndarray,
        dx_rtl: np.ndarray,
        dy_rtl: np.ndarray,
        w_rtl: np.ndarray,
        divisor: int,
        serpentine: bool,
        threshold: float,
    ) -> None:
        h, w = work.shape
        div = float(divisor)

        for y in range(h):
            left_to_right = (not serpentine) or (y % 2 == 0)

            if left_to_right:
                dx = dx_ltr
                dy = dy_ltr
                ww = w_ltr
                x0 = 0
                x1 = w
                xs = 1
            else:
                dx = dx_rtl
                dy = dy_rtl
                ww = w_rtl
                x0 = w - 1
                x1 = -1
                xs = -1

            for x in range(x0, x1, xs):
                old_val = work[y, x]
                new_val = 255.0 if old_val >= threshold else 0.0
                out[y, x] = 255 if new_val > 0.0 else 0

                err = old_val - new_val
                if err == 0.0:
                    continue

                for i in range(dx.shape[0]):
                    nx = x + dx[i]
                    ny = y + dy[i]
                    if 0 <= nx < w and 0 <= ny < h:
                        v = work[ny, nx] + err * (float(ww[i]) / div)
                        # clamp 0..255
                        if v < 0.0:
                            v = 0.0
                        elif v > 255.0:
                            v = 255.0
                        work[ny, nx] = v


def dither_error_diffusion(
    gray_img: Image.Image,
    kernel: Kernel,
    divisor: int,
    serpentine: bool = False,
    threshold: int = 128,
    mode_name: str | None = None,
) -> Image.Image:
    if gray_img.mode != "L":
        gray_img = gray_img.convert("L")

    if divisor <= 0:
        raise ValueError("divisor must be > 0")

    work = np.asarray(gray_img, dtype=np.float32).copy()
    out = np.zeros(work.shape, dtype=np.uint8)

    if _HAS_NUMBA:
        if mode_name is None:
            mode_name = f"kernel_n{len(kernel)}_d{divisor}"
        dx_ltr, dy_ltr, w_ltr, dx_rtl, dy_rtl, w_rtl, div = _get_kernel_pack(
            mode_name, kernel, divisor
        )
        _dither_ed_numba(
            work,
            out,
            dx_ltr,
            dy_ltr,
            w_ltr,
            dx_rtl,
            dy_rtl,
            w_rtl,
            div,
            serpentine,
            float(threshold),
        )
        return Image.fromarray(out, mode="L")

    height, width = work.shape
    rtl_kernel = [(-dx, dy, weight) for dx, dy, weight in kernel]

    for y in range(height):
        left_to_right = not serpentine or (y % 2 == 0)
        if left_to_right:
            x_iter = range(width)
            row_kernel = kernel
        else:
            x_iter = range(width - 1, -1, -1)
            row_kernel = rtl_kernel

        for x in x_iter:
            old_val = float(work[y, x])
            new_val = 255.0 if old_val >= threshold else 0.0
            out[y, x] = np.uint8(new_val)

            err = old_val - new_val
            if err == 0.0:
                continue

            for dx, dy, weight in row_kernel:
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    v = work[ny, nx] + err * (weight / divisor)
                    if v < 0.0:
                        v = 0.0
                    elif v > 255.0:
                        v = 255.0
                    work[ny, nx] = v

    return Image.fromarray(out, mode="L")


def _bayer8_thresholds() -> np.ndarray:
    bayer8 = np.array(
        [
            [0, 48, 12, 60, 3, 51, 15, 63],
            [32, 16, 44, 28, 35, 19, 47, 31],
            [8, 56, 4, 52, 11, 59, 7, 55],
            [40, 24, 36, 20, 43, 27, 39, 23],
            [2, 50, 14, 62, 1, 49, 13, 61],
            [34, 18, 46, 30, 33, 17, 45, 29],
            [10, 58, 6, 54, 9, 57, 5, 53],
            [42, 26, 38, 22, 41, 25, 37, 21],
        ],
        dtype=np.float32,
    )
    return np.floor((bayer8 + 0.5) * (256.0 / 64.0)).astype(np.uint8)


def _clustered_thresholds(cell_size: int) -> np.ndarray:
    n = max(2, int(cell_size))
    if n % 2:
        n += 1
    yy, xx = np.indices((n, n), dtype=np.float32)
    cx = (n - 1) * 0.5
    cy = (n - 1) * 0.5
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    ranks = np.argsort(dist2, axis=None, kind="stable").reshape(n, n)
    return np.floor((ranks.astype(np.float32) + 0.5) * (256.0 / float(n * n))).astype(
        np.uint8
    )


def _ordered_1bit(gray_img: Image.Image, thresholds_u8: np.ndarray, x_phase_mul: int = 0) -> Image.Image:
    work = np.asarray(gray_img.convert("L"), dtype=np.uint8)
    h, w = work.shape
    n = thresholds_u8.shape[0]
    y = np.arange(h, dtype=np.int32) % n
    x = np.arange(w, dtype=np.int32)
    if x_phase_mul:
        x_offsets = (np.arange(h, dtype=np.int32) * x_phase_mul) % n
        x_idx = (x[None, :] + x_offsets[:, None]) % n
    else:
        x_idx = x[None, :] % n
    t = thresholds_u8[y[:, None], x_idx]
    # Polarity contract for pre-GCode raster: 0=black/on, 255=white/off.
    out = np.where(work < t, 0, 255).astype(np.uint8)
    return Image.fromarray(out, mode="L")


def _hybrid_pattern(h: int, w: int) -> np.ndarray:
    yy, xx = np.indices((h, w), dtype=np.uint32)
    v = xx * np.uint32(374761393) + yy * np.uint32(668265263)
    v = np.bitwise_xor(v, np.right_shift(v, np.uint32(13)))
    v = v * np.uint32(1274126177)
    v = np.bitwise_xor(v, np.right_shift(v, np.uint32(16)))
    pattern = (v % np.uint32(3)).astype(np.int8) - np.int8(1)
    return pattern.astype(np.float32)


def hybrid_grayscale(gray_img: Image.Image, base_amp: float = 1.0) -> Image.Image:
    gray = gray_img.convert("L")
    work = np.asarray(gray, dtype=np.float32)
    h, w = work.shape

    pattern = _hybrid_pattern(h, w)

    tone = work / 255.0
    mid = 1.0 - np.abs((2.0 * tone) - 1.0)
    amp = max(0.0, float(base_amp)) * mid

    delta = pattern * amp
    out = np.rint(np.clip(work + delta, 0.0, 255.0)).astype(np.uint8)
    return Image.fromarray(out, mode="L")


def apply_dither_mode(gray_img: Image.Image, mode: str, base_tuning: dict | None = None) -> Image.Image:
    if mode in DITHER_MODES:
        kernel, divisor = DITHER_MODES[mode]
        serpentine = False
        if isinstance(base_tuning, dict):
            serpentine = bool(base_tuning.get("serpentine_scan", False))
        return dither_error_diffusion(
            gray_img, kernel, divisor, serpentine=serpentine, mode_name=mode
        )
    if mode == "BAYER":
        return _ordered_1bit(gray_img, _bayer8_thresholds())
    return gray_img


def is_binary_dither_mode(mode: str | None) -> bool:
    return bool(mode in BINARY_DITHER_MODES)

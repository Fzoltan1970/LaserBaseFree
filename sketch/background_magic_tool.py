from collections import deque

import cv2
import numpy as np


def _to_intensity(image):
    if image is None:
        return None
    if len(image.shape) == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def compute_region_mask(image, seed_x, seed_y, tolerance=15):
    gray = _to_intensity(image)
    if gray is None:
        return None

    h, w = gray.shape[:2]
    if seed_x < 0 or seed_y < 0 or seed_x >= w or seed_y >= h:
        return np.zeros((h, w), dtype=np.uint8)

    seed_value = int(gray[seed_y, seed_x])
    visited = np.zeros((h, w), dtype=bool)
    mask = np.zeros((h, w), dtype=np.uint8)

    queue = deque([(seed_x, seed_y)])

    while queue:
        x, y = queue.pop()

        if visited[y, x]:
            continue
        visited[y, x] = True

        if abs(int(gray[y, x]) - seed_value) > tolerance:
            continue

        mask[y, x] = 255

        for ny in range(max(0, y - 1), min(h, y + 2)):
            for nx in range(max(0, x - 1), min(w, x + 2)):
                if not visited[ny, nx]:
                    queue.append((nx, ny))

    return mask


def apply_mask_fill(image, mask, value=255):
    if image is None or mask is None:
        return image

    result = image.copy()
    if len(result.shape) == 2:
        result[mask > 0] = value
        return result

    result[mask > 0] = [value] * result.shape[2]
    return result

# vectorizer.py
import time

import cv2
import numpy as np

MAX_MERGE_DIST = 8.0
CLOSED_CONTOUR_EPS = 1.5


class Vectorizer:
    def __init__(self, min_length=15, epsilon=1.5):
        self.min_length = min_length
        self.epsilon = epsilon
        self._simplify_calls = 0
        self._simplify_total = 0.0

    # ---------------------------------------------------------
    # PUBLIC
    # ---------------------------------------------------------
    def vectorize(self, line_map, detail=None, smooth=None, merge=None, mode="line"):
        start = time.perf_counter()
        print("[SKETCH TRACE] Vectorizer.vectorize start")
        try:
            self._simplify_calls = 0
            self._simplify_total = 0.0

            trace_calls = 0
            trace_total = 0.0

            gray_prepare_start = time.perf_counter()
            if len(line_map.shape) == 3:
                gray_convert_start = time.perf_counter()
                gray = cv2.cvtColor(line_map, cv2.COLOR_BGR2GRAY)
                gray_convert_duration = time.perf_counter() - gray_convert_start
                print(
                    f"[SKETCH TRACE] vectorize.gray_convert end ({gray_convert_duration:.3f}s)"
                )
            else:
                gray_copy_start = time.perf_counter()
                gray = line_map.copy()
                gray_copy_duration = time.perf_counter() - gray_copy_start
                print(f"[SKETCH TRACE] vectorize.gray_copy end ({gray_copy_duration:.3f}s)")
            gray_prepare_duration = time.perf_counter() - gray_prepare_start
            print(f"[SKETCH TRACE] vectorize.gray_prepare end ({gray_prepare_duration:.3f}s)")

            bw_create_start = time.perf_counter()
            threshold_start = time.perf_counter()
            bw = (gray < 200).astype(np.uint8)
            threshold_duration = time.perf_counter() - threshold_start
            print(
                f"[SKETCH TRACE] vectorize.threshold_binary end ({threshold_duration:.3f}s)"
            )
            bw_create_duration = time.perf_counter() - bw_create_start
            print(f"[SKETCH TRACE] vectorize.bw_create end ({bw_create_duration:.3f}s)")
            # ======================================================
            # SHAPE RECONSTRUCT (forma alapú középvonal)
            # ======================================================
            shape_preprocess_start = time.perf_counter()
            if mode == "shape":

                # 1) felületek létrehozása (EZ HIÁNYZOTT)
                posterize_start = time.perf_counter()
                gray = self._posterize(gray, levels=7)
                posterize_duration = time.perf_counter() - posterize_start
                print(f"[SKETCH TRACE] vectorize.posterize end ({posterize_duration:.3f}s)")

                # 2) felület határok keresése
                canny_start = time.perf_counter()
                edges = cv2.Canny(gray, 30, 90)
                canny_duration = time.perf_counter() - canny_start
                print(f"[SKETCH TRACE] vectorize.canny end ({canny_duration:.3f}s)")

                # 3) vékonyítás (középvonal)
                thinning_start = time.perf_counter()
                bw = cv2.ximgproc.thinning(edges) // 255
                thinning_duration = time.perf_counter() - thinning_start
                print(f"[SKETCH TRACE] vectorize.thinning end ({thinning_duration:.3f}s)")
            shape_preprocess_duration = time.perf_counter() - shape_preprocess_start
            print(
                f"[SKETCH TRACE] vectorize.shape_preprocess end ({shape_preprocess_duration:.3f}s)"
            )

            # --- slider értékek alkalmazása ---
            slider_start = time.perf_counter()
            detail_smooth_merge_start = time.perf_counter()
            if detail is not None:
                self.min_length = 2 + (100 - detail) * 0.25  # rövid vonalak szűrése

            if smooth is not None:
                self.epsilon = 0.5 + smooth * 0.04  # görbe simítása

            merge_dist_px = 0.0
            if merge is not None:
                merge_unit = np.clip(merge, 0, 100) / 100.0
                merge_dist_px = merge_unit * MAX_MERGE_DIST
            detail_smooth_merge_duration = time.perf_counter() - detail_smooth_merge_start
            slider_duration = time.perf_counter() - slider_start
            print(f"[SKETCH TRACE] vectorize.slider_apply end ({slider_duration:.3f}s)")
            print(
                f"[SKETCH TRACE] vectorize.detail_smooth_merge end ({detail_smooth_merge_duration:.3f}s)"
            )

            print("ink pixels:", np.count_nonzero(bw))
            print("image size:", bw.shape)

            visited_alloc_start = time.perf_counter()
            visited = np.zeros_like(bw, dtype=np.uint8)
            visited_alloc_duration = time.perf_counter() - visited_alloc_start
            print(
                f"[SKETCH TRACE] vectorize.visited_alloc end ({visited_alloc_duration:.3f}s)"
            )
            h, w = bw.shape
            paths = []

            bw_local = bw
            visited_local = visited
            w_local = w
            h_local = h

            def trace(x, y):
                path = [(x, y)]
                visited_local[y, x] = 1
                path_append = path.append
                bw_arr = bw_local
                visited_arr = visited_local
                w_lim = w_local
                h_lim = h_local

                cx, cy = x, y
                while True:
                    x_left = cx - 1
                    x_right = cx + 1
                    y_up = cy - 1
                    y_down = cy + 1

                    if y_up >= 0:
                        bw_row = bw_arr[y_up]
                        visited_row = visited_arr[y_up]

                        if x_left >= 0 and bw_row[x_left] and not visited_row[x_left]:
                            visited_row[x_left] = 1
                            path_append((x_left, y_up))
                            cx, cy = x_left, y_up
                            continue

                        if bw_row[cx] and not visited_row[cx]:
                            visited_row[cx] = 1
                            path_append((cx, y_up))
                            cy = y_up
                            continue

                        if x_right < w_lim and bw_row[x_right] and not visited_row[x_right]:
                            visited_row[x_right] = 1
                            path_append((x_right, y_up))
                            cx, cy = x_right, y_up
                            continue

                    bw_row = bw_arr[cy]
                    visited_row = visited_arr[cy]

                    if x_left >= 0 and bw_row[x_left] and not visited_row[x_left]:
                        visited_row[x_left] = 1
                        path_append((x_left, cy))
                        cx = x_left
                        continue

                    if x_right < w_lim and bw_row[x_right] and not visited_row[x_right]:
                        visited_row[x_right] = 1
                        path_append((x_right, cy))
                        cx = x_right
                        continue

                    if y_down < h_lim:
                        bw_row = bw_arr[y_down]
                        visited_row = visited_arr[y_down]

                        if x_left >= 0 and bw_row[x_left] and not visited_row[x_left]:
                            visited_row[x_left] = 1
                            path_append((x_left, y_down))
                            cx, cy = x_left, y_down
                            continue

                        if bw_row[cx] and not visited_row[cx]:
                            visited_row[cx] = 1
                            path_append((cx, y_down))
                            cy = y_down
                            continue

                        if x_right < w_lim and bw_row[x_right] and not visited_row[x_right]:
                            visited_row[x_right] = 1
                            path_append((x_right, y_down))
                            cx, cy = x_right, y_down
                            continue

                    break
                return path

            scan_start = time.perf_counter()
            min_length = self.min_length
            simplify = self._simplify
            paths_append = paths.append
            for y in range(h):
                bw_row = bw_local[y]
                visited_row = visited_local[y]
                for x in range(w):
                    if bw_row[x] and not visited_row[x]:
                        trace_start = time.perf_counter()
                        p = trace(x, y)
                        trace_total_local = time.perf_counter() - trace_start
                        trace_total += trace_total_local
                        trace_calls += 1
                        if len(p) > min_length:
                            paths_append(simplify(p))
            scan_duration = time.perf_counter() - scan_start
            print(f"[SKETCH TRACE] vectorize.scan end ({scan_duration:.3f}s)")
            print(f"[SKETCH TRACE] vectorize.full_scan_total end ({scan_duration:.3f}s)")

            trace_avg = trace_total / trace_calls if trace_calls else 0.0
            print(
                f"[SKETCH TRACE] vectorize.trace calls={trace_calls} "
                f"total={trace_total:.3f}s avg={trace_avg:.6f}s"
            )

            simplify_avg = (
                self._simplify_total / self._simplify_calls if self._simplify_calls else 0.0
            )
            print(
                f"[SKETCH TRACE] vectorize.simplify calls={self._simplify_calls} "
                f"total={self._simplify_total:.3f}s avg={simplify_avg:.6f}s"
            )

            merge_stage_start = time.perf_counter()
            if merge_dist_px > 0:
                paths = self._merge_paths(paths, merge_dist_px)
            merge_stage_duration = time.perf_counter() - merge_stage_start
            print(f"[SKETCH TRACE] vectorize.merge end ({merge_stage_duration:.3f}s)")

            print("paths:", len(paths))
            return paths
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] Vectorizer.vectorize end ({duration:.3f}s)")

    def _merge_paths(self, paths, dist=2.5):
        start = time.perf_counter()
        print("[SKETCH TRACE] Vectorizer._merge_paths start")
        try:
            def point_dist(a, b):
                return float(np.hypot(a[0] - b[0], a[1] - b[1]))

            def is_closed(path):
                if len(path) < 2:
                    return False
                return point_dist(path[0], path[-1]) <= CLOSED_CONTOUR_EPS

            def merge_pair(p1, p2, mode):
                # mode: 0=end-start, 1=start-end, 2=start-start, 3=end-end
                if mode == 0:
                    return p1 + p2[1:]
                if mode == 1:
                    return p2 + p1[1:]
                if mode == 2:
                    return p1[::-1] + p2[1:]
                return p1 + p2[::-1][1:]

            merged_paths = [list(path) for path in paths]

            while True:
                best = None

                for i in range(len(merged_paths)):
                    p1 = merged_paths[i]
                    if len(p1) < 2 or is_closed(p1):
                        continue

                    for j in range(i + 1, len(merged_paths)):
                        p2 = merged_paths[j]
                        if len(p2) < 2 or is_closed(p2):
                            continue

                        endpoint_pairs = [
                            (0, point_dist(p1[-1], p2[0])),
                            (1, point_dist(p1[0], p2[-1])),
                            (2, point_dist(p1[0], p2[0])),
                            (3, point_dist(p1[-1], p2[-1])),
                        ]

                        for mode, d in endpoint_pairs:
                            if d > dist:
                                continue
                            candidate = (d, i, j, mode)
                            if best is None or candidate < best:
                                best = candidate

                if best is None:
                    break

                _, i, j, mode = best
                merged_paths[i] = merge_pair(merged_paths[i], merged_paths[j], mode)
                del merged_paths[j]

            return merged_paths
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] Vectorizer._merge_paths end ({duration:.3f}s)")

    # ---------------------------------------------------------
    # TRACE CONTOURS
    # ---------------------------------------------------------
    def _trace_strokes(self, edge):
        img = (edge * 255).astype(np.uint8)
        contours, _ = cv2.findContours(img, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

        paths = []
        for c in contours:
            pts = [(int(p[0][0]), int(p[0][1])) for p in c]
            if len(pts) > 1:
                paths.append(pts)
        return paths

    # ---------------------------------------------------------
    # SIMPLIFY POLYLINE
    # ---------------------------------------------------------
    def _simplify(self, path):
        start = time.perf_counter()
        try:
            cnt = np.array(path, dtype=np.int32).reshape((-1, 1, 2))
            approx = cv2.approxPolyDP(cnt, self.epsilon, False)
            return [(int(p[0][0]), int(p[0][1])) for p in approx]
        finally:
            self._simplify_calls += 1
            self._simplify_total += time.perf_counter() - start

    def _structure_smooth(self, gray):

        # textúra eltüntetés, él megtartás
        smooth = cv2.ximgproc.edgePreservingFilter(
            gray, flags=1, sigma_s=60, sigma_r=0.4
        )

        return smooth

    def _posterize(self, gray, levels=7):

        # zaj kisimítása
        smooth = cv2.bilateralFilter(gray, 9, 35, 35)

        # kvantálás (felületek létrehozása)
        step = 256 // levels
        quant = (smooth // step) * step

        # kis foltok eltüntetése
        kernel = np.ones((3, 3), np.uint8)
        quant = cv2.medianBlur(quant, 5)
        quant = cv2.morphologyEx(quant, cv2.MORPH_OPEN, kernel)

        return quant

    # ---------------------------------------------------------
    # PREVIEW
    # ---------------------------------------------------------
    def draw_preview(self, shape, paths):
        start = time.perf_counter()
        print("[SKETCH TRACE] Vectorizer.draw_preview start")
        try:
            h, w = shape[:2]
            canvas = np.ones((h, w, 3), dtype=np.uint8) * 255

            for path in paths:
                for i in range(len(path) - 1):
                    cv2.line(canvas, path[i], path[i + 1], (0, 0, 0), 1, cv2.LINE_AA)

            return canvas
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] Vectorizer.draw_preview end ({duration:.3f}s)")

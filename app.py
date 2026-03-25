# app.py
# Job-based processing kernel.
# No incremental UI workflow state is handled here.
# NOTE:
# image_analyzer output is NOT used here.
# Geometric and DPI-related decisions must never depend on it.

# Do not modify CONTROL FLOW or WORKFLOW SEMANTICS
# without updating that document.

# ------------------------------------------------------------------
# KERNEL IMPLEMENTATION SCOPE (IMPORTANT)
#
# Allowed WITHOUT workflow update:
# - refactoring internal logic inside existing states
# - stabilizing event handling (ordering, guards, idempotency)
# - improving parsing robustness (without changing meaning)
# - reorganizing code for clarity or safety
#
# NOT allowed here:
# - introducing new workflow states
# - changing state transition meaning
# - skipping or merging canonical workflow steps
#
# If a change alters when or why a state transition happens,
# STOP and update the workflow document.
# BETÖLTÖTT RAW
#        │
#        ▼
# GÉP + DPI + MÉRET VIZSGÁLAT
#        │
#        ├─ Minden OK
#        │      → BASE
#        │
#        ├─ Mechanika nem képes
#        │      → BASE (figyelmeztetéssel)
#        │
#        └─ Kép javítás szükséges
#               → JAVÍTÁS → BASEx

# ------------------------------------------------------------------


from __future__ import annotations

"""
LaserBase – Application Kernel (MAG)
"""

from dataclasses import asdict, is_dataclass

from PyQt6.QtNetwork import QLocalServer

from core.infrastructure.config_manager import ConfigManager
from ui.workspaces.laser_image_editor.image_workspace_window import (
    ImagePreviewWindow,
)
from core.contracts.job_config import JobConfig
from core.physics.laser_optimizer import optimize_for_engraving
from core.production.base_builder import build_base_image
from core.production.raw_crop import normalize_raw_crop_box
from core.production.gcode_builder import (
    build_bidirectional_raster_gcode,
    preflight_grayscale_streamability,
)
from PIL import Image


class Application:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()

        self.language = self.config.get("language", "en")
        self.workspace = None

        self._ipc_server_name = "LaserBaseFreeSketchIPC"
        self._ipc_server: QLocalServer | None = None

        self.length_unit = self.config.get("unit", self.config.get("length_unit", "mm"))
        self.machine_mode = self.config.get("mode", "diode")
        self.raw_image_path: str | None = None
        self._last_job = None
        self._last_result = None
        self._last_context = None
        self._last_base_image = None
        self._last_processed_info = None
        self._last_raw_crop_box = None
        self._last_raw_crop_shape = None
        self._last_crop_enabled = False
        self._last_crop_valid = False
        self._last_crop_rect = None

    def _processed_info_as_dict(self, processed_info) -> dict:
        if isinstance(processed_info, dict):
            return dict(processed_info)

        if is_dataclass(processed_info):
            try:
                return asdict(processed_info)
            except Exception:
                return {}

        return {}

    def _ensure_processed_info_resolution(
        self, processed_info: dict, context: dict | None
    ) -> dict:
        if not isinstance(processed_info, dict):
            processed_info = {}

        ctx = context if isinstance(context, dict) else {}

        if processed_info.get("pitch_mm") is None:
            pitch_mm = ctx.get("pitch_mm")
            if pitch_mm is not None:
                processed_info["pitch_mm"] = pitch_mm

        if processed_info.get("pitch_mm") is None and processed_info.get("dpi") is None:
            effective_dpi = ctx.get("effective_dpi")
            if effective_dpi is not None:
                processed_info["dpi"] = effective_dpi

        if processed_info.get("pitch_mm") is None and processed_info.get("dpi") is None:
            requested_dpi = ctx.get("requested_dpi")
            if requested_dpi is not None:
                processed_info["dpi"] = requested_dpi

        return processed_info

    def start(self, open_path: str | None = None):
        self._setup_sketch_ipc_server()
        self._show_workspace()
        if open_path:
            self._open_image_workspace_path(open_path)
        return True

    # RAW IMAGE STATE (UI NOTIFICATION ONLY)
    # --------------------------------------------------
    def set_raw_image(self, path: str | None) -> None:
        """
        UI notifies kernel that a raw image was loaded.
        No analysis, no workflow decision here.
        Only state cache.
        """
        self._last_base_image = None
        self._last_processed_info = None

        if not path:
            self.raw_image_path = None
            return

        self.raw_image_path = str(path)

    def _show_workspace(self) -> None:
        if self.workspace is None:
            self.workspace = ImagePreviewWindow(self, parent=None)
            self.workspace.apply_machine_mode(self.machine_mode)
            self.workspace.apply_language()

        self.workspace.show()

    def _setup_sketch_ipc_server(self) -> None:
        if self._ipc_server is not None:
            return

        try:
            QLocalServer.removeServer(self._ipc_server_name)
        except Exception:
            pass

        server = QLocalServer()
        server.newConnection.connect(self._on_sketch_ipc_connection)
        if not server.listen(self._ipc_server_name):
            return
        self._ipc_server = server

    def _on_sketch_ipc_connection(self) -> None:
        if not self._ipc_server:
            return

        while self._ipc_server.hasPendingConnections():
            socket = self._ipc_server.nextPendingConnection()
            if socket is None:
                continue
            socket.waitForReadyRead(1000)
            data = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
            socket.disconnectFromServer()
            if data:
                self._open_image_workspace_path(data)

    def _open_image_workspace_path(self, path: str) -> None:
        normalized = str(path or "").strip()
        if not normalized:
            return

        self._show_workspace()

        if self.workspace is None:
            return

        self.workspace.show()
        self.workspace.raise_()
        self.workspace.activateWindow()
        self.workspace.import_image_from_path(normalized)

    def tr(self, key: str, default: str | None = None) -> str:
        return self.config_manager.translate(key, default)

    def set_language(self, new_lang: str):
        if not new_lang:
            return

        if self.language == new_lang:
            return

        self.language = new_lang
        self.config["language"] = new_lang
        self.config_manager.save(self.config)

        if self.workspace is not None:
            self.workspace.apply_language()

    def process(
        self,
        job: JobConfig,
        raw_crop_box: tuple[int, int, int, int] | None = None,
        raw_crop_shape: str | None = None,
        crop_enabled: bool = False,
        crop_valid: bool = False,
        crop_rect: tuple[int, int, int, int] | None = None,
    ) -> dict:
        if job.size_mm is None:
            raise ValueError("size_mm must be provided by user")

        effective_source_px = None
        if (
            crop_enabled
            and crop_valid
            and isinstance(raw_crop_box, tuple)
            and len(raw_crop_box) == 4
        ):
            with Image.open(job.raw_image_path) as raw_img:
                normalized_crop = normalize_raw_crop_box(
                    raw_crop_box,
                    raw_img.width,
                    raw_img.height,
                )
            if normalized_crop is not None:
                left, top, right, bottom = normalized_crop
                crop_w = max(1, int(right - left))
                crop_h = max(1, int(bottom - top))
                effective_source_px = (crop_w, crop_h)

        result = optimize_for_engraving(
            image_path=job.raw_image_path,
            target_dpi=job.requested_dpi,
            laser_info=job.machine_profile,
            size_mm=job.size_mm,
            engrave_axis=job.engrave_axis,
            effective_source_px=effective_source_px,
        )

        self._last_job = job
        self._last_raw_crop_box = raw_crop_box
        self._last_raw_crop_shape = raw_crop_shape
        self._last_crop_enabled = bool(crop_enabled)
        self._last_crop_valid = bool(crop_valid)
        self._last_crop_rect = crop_rect
        self._last_result = result
        print("[DEBUG] Application.process return type:", type(result))
        if isinstance(result, dict):
            print("[DEBUG] Application.process return keys:", list(result.keys()))
        else:
            print("[DEBUG] Application.process return value:", result)
        return result

    def _extract_context(self, payload: dict | None = None) -> dict | None:
        if isinstance(payload, dict):
            context = payload.get("result", {}).get("context")
            if context:
                self._last_context = context
                return context

        if isinstance(self._last_result, dict):
            context = self._last_result.get("context")
            if context:
                self._last_context = context
                return context

        return self._last_context

    def rebuild_base_with_control(self, control: dict | None = None) -> dict:

        if not self._last_job:
            return {"ok": False, "error": "Missing processing state"}

        context = self._extract_context()
        if not context:
            return {"ok": False, "error": "Invalid context"}

        base_control, geometry_control = self._split_rebuild_controls(control)
        if geometry_control:
            print(
                "[rebuild] geometry controls were provided to rebuild_base_with_control and ignored:",
                geometry_control,
            )

        try:
            base_img, info = build_base_image(
                self._last_job,
                context,
                base_tuning=base_control,
                raw_crop_box=self._last_raw_crop_box,
                raw_crop_shape=self._last_raw_crop_shape,
                crop_enabled=self._last_crop_enabled,
                crop_valid=self._last_crop_valid,
                crop_rect=self._last_crop_rect,
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}

        processed_info = self._processed_info_as_dict(info)
        processed_info = self._ensure_processed_info_resolution(processed_info, context)
        print(
            "[DEBUG] processed_info resolution committed:",
            {
                "pitch_mm": processed_info.get("pitch_mm"),
                "dpi": processed_info.get("dpi"),
            },
        )

        self._last_base_image = base_img
        self._last_processed_info = processed_info

        return {
            "ok": True,
            "engrave_image": base_img,
            "processed_info": processed_info,
        }

    def _split_rebuild_controls(self, control: dict | None) -> tuple[dict | None, dict]:
        if not isinstance(control, dict):
            return control, {}

        geometry_keys = {
            "width",
            "width_mm",
            "height",
            "height_mm",
            "dpi",
            "pitch",
            "pitch_mm",
            "effective_width_mm",
            "effective_height_mm",
            "effective_dpi",
            "steps_per_line",
            "real_lines",
            "engrave_axis",
        }
        geometry_control = {k: v for k, v in control.items() if k in geometry_keys}
        base_control = {k: v for k, v in control.items() if k not in geometry_keys}
        return base_control, geometry_control

    def _resolve_overscan(
        self, control: dict, axis: str
    ) -> dict[str, float | str | bool | None]:
        mode = "off"
        overscan_mm = 0.0

        safety_factor = control.get("overscan_safety_factor", 1.15)
        try:
            safety_factor = float(safety_factor)
        except (TypeError, ValueError):
            safety_factor = 1.15

        override = control.get("overscan_mm")
        if override is not None:
            try:
                overscan_mm = max(0.0, float(override))
                mode = "manual"
            except (TypeError, ValueError):
                overscan_mm = 0.0
                mode = "off"
        elif bool(control.get("overscan_enabled", False)):
            speed = control.get("speed")
            accel = None
            if self._last_job is not None and isinstance(
                self._last_job.machine_profile, dict
            ):
                axis_profile = self._last_job.machine_profile.get(axis.lower())
                if isinstance(axis_profile, dict):
                    accel = axis_profile.get("acceleration")

            try:
                speed_mm_s = float(speed) / 60.0
                accel_mm_s2 = float(accel)
                if accel_mm_s2 > 0:
                    overscan_mm = max(
                        0.0, safety_factor * ((speed_mm_s**2) / (2.0 * accel_mm_s2))
                    )
                    mode = "auto"
            except (TypeError, ValueError, ZeroDivisionError):
                overscan_mm = 0.0
                mode = "off"

        return {
            "mode": mode,
            "overscan_mm": overscan_mm,
            "safety_factor": safety_factor,
        }

    def _prepare_gcode_export_state(self, control: dict) -> dict:
        if self._last_base_image is None:
            raise ValueError("Missing BASE image")
        if self._last_processed_info is None:
            raise ValueError("Missing processed info")
        if self._last_job is None and self._last_context is None:
            raise ValueError("Missing processing state")

        axis = None
        if self._last_job is not None:
            axis = getattr(self._last_job, "engrave_axis", None)
        if not axis and isinstance(self._last_context, dict):
            axis = self._last_context.get("engrave_axis")
        axis = (axis or "X").upper()

        overscan = self._resolve_overscan(control, axis)
        machine_profile = self._last_job.machine_profile if self._last_job else {}
        axis_profile = (
            machine_profile.get(axis.lower(), {})
            if isinstance(machine_profile, dict)
            else {}
        )
        used_accel = (
            axis_profile.get("acceleration") if isinstance(axis_profile, dict) else None
        )

        gcode_profile = (
            machine_profile.get("gcode_control", {})
            if isinstance(machine_profile, dict)
            else {}
        )
        pwm_max = control.get("pwm_max")
        if pwm_max is None and isinstance(gcode_profile, dict):
            pwm_max = gcode_profile.get("pwm_max")
        pwm_min = control.get("pwm_min")
        if pwm_min is None and isinstance(gcode_profile, dict):
            pwm_min = gcode_profile.get("pwm_min")

        try:
            s_range_max = float(pwm_max)
        except (TypeError, ValueError):
            s_range_max = 1000.0
        try:
            s_range_min = float(pwm_min)
        except (TypeError, ValueError):
            s_range_min = 0.0

        try:
            min_power_pct = float(control.get("min_power", 0.0))
        except (TypeError, ValueError):
            min_power_pct = 0.0
        try:
            max_power_pct = float(control.get("max_power", 100.0))
        except (TypeError, ValueError):
            max_power_pct = 100.0
        s_min = (min_power_pct / 100.0) * s_range_max
        s_max = (max_power_pct / 100.0) * s_range_max
        if s_min > s_max:
            s_min, s_max = s_max, s_min
        s_min = max(s_range_min, min(s_range_max, s_min))
        s_max = max(s_range_min, min(s_range_max, s_max))

        cfg = {
            "feed_rate_mm_min": float(control.get("speed")),
            "s_min": s_min,
            "s_max": s_max,
            "s_range_min": s_range_min,
            "s_range_max": s_range_max,
            "laser_mode": "M4",
            "overscan_mode": overscan["mode"],
            "overscan_mm": overscan["overscan_mm"],
            "overscan_safety_factor": overscan["safety_factor"],
            "overscan_used_accel": used_accel,
            "speed_mm_min": float(control.get("speed")),
            "grayscale_simplify": bool(control.get("grayscale_simplify", False)),
            "grayscale_merge_tolerance": int(
                control.get("grayscale_merge_tolerance", 0) or 0
            ),
        }

        processed_info = self._processed_info_as_dict(self._last_processed_info)
        processed_info = self._ensure_processed_info_resolution(
            processed_info,
            self._last_context,
        )
        if not processed_info:
            processed_info = {}
        processed_info.setdefault("px_width", self._last_base_image.size[0])
        processed_info.setdefault("px_height", self._last_base_image.size[1])
        processing_meta = dict(processed_info.get("processing_meta", {}))
        processing_meta["pwm_max"] = s_range_max
        processed_info["processing_meta"] = processing_meta

        baudrate = control.get("baudrate")
        if baudrate is None and isinstance(gcode_profile, dict):
            baudrate = gcode_profile.get("baudrate")
        try:
            baudrate_int = int(baudrate)
        except (TypeError, ValueError):
            baudrate_int = 115200

        return {
            "img": self._last_base_image,
            "processed_info": processed_info,
            "axis": axis,
            "cfg": cfg,
            "baudrate": baudrate_int,
        }

    def preflight_grayscale_gcode(self, control: dict) -> dict:
        try:
            prepared = self._prepare_gcode_export_state(control)
            preflight = preflight_grayscale_streamability(
                img=prepared["img"],
                processed_info=prepared["processed_info"],
                engrave_axis=prepared["axis"],
                cfg=prepared["cfg"],
                baudrate=prepared["baudrate"],
            )
            preflight["ok"] = True
            return preflight
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def export_gcode(self, control: dict) -> dict:
        try:
            prepared = self._prepare_gcode_export_state(control)
            gcode, stats = build_bidirectional_raster_gcode(
                img=prepared["img"],
                processed_info=prepared["processed_info"],
                engrave_axis=prepared["axis"],
                cfg=prepared["cfg"],
            )
            return {"ok": True, "gcode": gcode, "stats": stats}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --------------------------------------------------
    # EXECUTION PHASE (USER CONFIRMED)
    # --------------------------------------------------
    # --------------------------------------------------
    # EXECUTION PHASE (USER CONFIRMED)
    # --------------------------------------------------
    def execute_processing(self, payload: dict | None = None) -> dict:

        if not self._last_job or not payload:
            return {"ok": False, "error": "Missing processing state"}

        context = self._extract_context(payload)
        if not context:
            return {"ok": False, "error": "Invalid context"}
        print(
            "[DEBUG] payload.result.decision:",
            payload.get("result", {}).get("decision"),
        )
        print("[DEBUG] payload.result.context:", context)
        print("[DEBUG] type(context):", type(context))
        print(
            "[DEBUG] context keys:",
            list(context.keys()) if hasattr(context, "keys") else None,
        )
        print(
            "[DEBUG] context.requested_width_mm:",
            context.get("requested_width_mm") if hasattr(context, "get") else None,
        )
        print(
            "[DEBUG] context.requested_height_mm:",
            context.get("requested_height_mm") if hasattr(context, "get") else None,
        )
        print("[DEBUG] context.engrave_axis:", context.get("engrave_axis"))
        print("[DEBUG] context.real_pitch_mm:", context.get("real_pitch_mm"))
        print("[DEBUG] context.real_lines:", context.get("real_lines"))
        print("[DEBUG] type(self._last_job):", type(self._last_job))
        print("[DEBUG] self._last_job.size_mm (w,h):", self._last_job.size_mm)
        print("[DEBUG] self._last_job.requested_dpi:", self._last_job.requested_dpi)

        base_tuning = payload.get("control") if isinstance(payload, dict) else None

        return self.rebuild_base_with_control(base_tuning)

    # --------------------------------------------------
    # MACHINE PROFILE PERSISTENCE
    # --------------------------------------------------
    def create_machine_profile(self, profile: dict) -> None:
        if not profile:
            return
        self.config_manager.add_machine_profile(profile)


def create_app() -> Application:
    return Application()

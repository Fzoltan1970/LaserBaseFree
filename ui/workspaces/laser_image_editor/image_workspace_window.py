# ui/workspaces/laser_image_editor/image_workspace_window.py
from __future__ import annotations
import math
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QSizePolicy,
    QLineEdit,
    QLayout,
    QComboBox,
    QSlider,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QMenu,
)
from PyQt6.QtGui import (
    QPixmap,
    QImage,
    QPainter,
    QColor,
    QPen,
    QPainterPath,
    QStandardItem,
)
from PyQt6.QtCore import (
    Qt,
    QObject,
    QThread,
    QEvent,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QMetaObject,
    QTimer,
    QSignalBlocker,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QCloseEvent
from serial.tools import list_ports
import threading
from core.infrastructure.grbl_reader import GrblReader
from enum import Enum, auto
from serial.tools import list_ports
from core.contracts.job_config import JobConfig
from core.infrastructure.paths import KNOWLEDGE_DIR
from ui.dialogs.processing_decision_dialog import ProcessingDecisionDialog
from ui.dialogs.markdown_viewer_dialog import MarkdownViewerDialog
from PIL import Image
from PIL.ImageQt import ImageQt
from dataclasses import asdict, is_dataclass
from core.production.raw_crop import apply_raw_crop, normalize_raw_crop_box


class RightViewMode(Enum):
    NONE = auto()
    VIRTUAL = auto()
    BASE = auto()


class GCodeExportWorker(QObject):
    success = pyqtSignal(dict)
    error = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, app, control: dict):
        super().__init__()
        self._app = app
        self._control = control

    @pyqtSlot()
    def run(self):
        try:
            result = self._app.export_gcode(self._control)
            self.success.emit(result)
        except Exception as e:
            self.error.emit(e)
        finally:
            self.finished.emit()


class PortComboBox(QComboBox):
    def mousePressEvent(self, event):
        self._refresh_ports()
        super().mousePressEvent(event)

    def _refresh_ports(self):
        current = self.currentText()
        self.blockSignals(True)
        self.clear()
        for p in list_ports.comports():
            self.addItem(p.device)
        index = self.findText(current)
        if index >= 0:
            self.setCurrentIndex(index)
        self.blockSignals(False)


class LabeledSlider(QWidget):
    def __init__(
        self,
        short_label: str,
        tooltip: str,
        minimum: int,
        maximum: int,
        default: int,
        row_height: int,
        display_divisor: float = 1.0,
        display_decimals: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._display_divisor = max(1e-9, float(display_divisor))
        self._display_decimals = max(0, int(display_decimals))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.label = QLabel(short_label)
        self.label.setToolTip(tooltip)
        self.label.setFixedWidth(14)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(default)

        min_display = self._raw_to_display(minimum)
        max_display = self._raw_to_display(maximum)
        initial_display = self._raw_to_display(default)
        is_float_display = any(
            isinstance(x, float) and not x.is_integer()
            for x in [min_display, max_display, initial_display]
        )

        if is_float_display:
            self.value_input = QDoubleSpinBox()
            self.value_input.setDecimals(self._display_decimals)
        else:
            self.value_input = QSpinBox()

        self.value_input.setToolTip(tooltip)
        self.value_input.setFixedWidth(52)

        if is_float_display:
            self.value_input.setRange(min_display, max_display)
        else:
            min_display_i = int(round(min_display))
            max_display_i = int(round(max_display))
            self.value_input.setRange(min_display_i, max_display_i)
        slider_step = next(
            (
                step
                for step in (
                    self.slider.singleStep(),
                    self.slider.tickInterval(),
                    self.slider.pageStep(),
                )
                if step > 0
            ),
            1,
        )
        if is_float_display:
            float_step = slider_step / self._display_divisor
            self.value_input.setSingleStep(float_step if float_step > 0 else 0.1)
        else:
            self.value_input.setSingleStep(max(1, int(round(slider_step))))
        self.value_input.setKeyboardTracking(False)
        if is_float_display:
            self.value_input.setValue(initial_display)
        else:
            self.value_input.setValue(int(round(initial_display)))

        self.slider.valueChanged.connect(self._on_slider_changed)
        self.value_input.valueChanged.connect(self._on_input_changed)

        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_input)

        self.setFixedHeight(row_height)
        self.label.setFixedHeight(row_height)
        self.slider.setFixedHeight(row_height)
        self.value_input.setFixedHeight(row_height)

    def _on_slider_changed(self, value: int):
        disp = self._raw_to_display(value)
        if not isinstance(self.value_input, QDoubleSpinBox):
            disp = int(round(disp))
        with QSignalBlocker(self.value_input):
            self.value_input.setValue(disp)

    def _on_input_changed(self, value: float):
        raw_value = self._display_to_raw(value)
        if raw_value == self.slider.value():
            return
        with QSignalBlocker(self.slider):
            self.slider.setValue(raw_value)
        self.slider.valueChanged.emit(self.slider.value())

    def _raw_to_display(self, raw_value: int) -> float:
        return raw_value / self._display_divisor

    def _display_to_raw(self, display_value: float) -> int:
        value = int(round(display_value * self._display_divisor))
        return max(self._minimum, min(self._maximum, value))

    def value(self) -> int:
        return self.slider.value()


# 🔍 Zoomolható QLabel
class ZoomableLabel(QLabel):
    viewChanged = pyqtSignal(float, float, float)

    def __init__(self, parent=None, interactive=True):
        super().__init__(parent)
        self._interactive = interactive
        self._syncing = False
        self._scale = 1.0
        self._world_scale = 1.0
        self._use_world = False
        self._px_per_mm = None
        self._cached_gray_image = None
        self.original_pixmap = None
        self.offset = QPoint(0, 0)
        self.drag_start = None
        self.zoom = 1.0
        self.pan_px = QPointF(0.0, 0.0)
        self.min_zoom = 1.0
        self.max_zoom = 8.0
        self._dragging = False
        self._last_pos = QPoint()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #e6e6e6; border: 1px solid #888;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._user_touched = False
        self._external_transform_active = False
        self._nearest_preview = False
        self._img_display_rect = None
        self._img_scale = 1.0
        self._img_size = None
        self._last_fit_debug_signature = None

    def setPixmap(self, pixmap):
        self.original_pixmap = pixmap
        self._cached_gray_image = None
        self._user_touched = False
        if pixmap is not None:
            self._img_size = (pixmap.width(), pixmap.height())
        else:
            self._img_size = None
        if (
            not self._use_world
            and not hasattr(self, "_skip_auto_reset")
            and not self._external_transform_active
        ):
            self._reset_view()
        self._update_fit_metrics(debug_reason="pixmap")
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._use_world:
            return
        if not self._user_touched and not self._external_transform_active:
            self._reset_view()
        self._clamp_pan()
        self._update_fit_metrics(debug_reason="resize")

    def _reset_view(self):
        self.zoom = 1.0
        self.pan_px = QPointF(0.0, 0.0)

        self._update_fit_metrics(debug_reason="reset")

    def reset_zoom(self):
        self._reset_view()
        self.update()

    def _clamp_offset(self):
        # Fit mode keeps image fully visible; offset is controlled by fit geometry.
        self._update_fit_metrics(debug_reason="clamp")

    def _clamp_pan(self):
        if not self.original_pixmap:
            return

        img_w = self.original_pixmap.width()
        img_h = self.original_pixmap.height()
        vp_w = max(1, self.width())
        vp_h = max(1, self.height())

        base_scale, _draw_w, _draw_h, offset_x, offset_y, _display_rect = (
            self._compute_fit_geometry(
                img_w=img_w,
                img_h=img_h,
                viewport_w=vp_w,
                viewport_h=vp_h,
            )
        )
        draw_scale = base_scale * self.zoom
        draw_w = max(1, round(img_w * draw_scale))
        draw_h = max(1, round(img_h * draw_scale))

        pan_x = self.pan_px.x()
        pan_y = self.pan_px.y()

        if draw_w <= vp_w:
            pan_x = 0.0
        else:
            min_pan_x = float(vp_w - draw_w - offset_x)
            max_pan_x = float(-offset_x)
            pan_x = max(min_pan_x, min(max_pan_x, pan_x))

        if draw_h <= vp_h:
            pan_y = 0.0
        else:
            min_pan_y = float(vp_h - draw_h - offset_y)
            max_pan_y = float(-offset_y)
            pan_y = max(min_pan_y, min(max_pan_y, pan_y))

        self.pan_px = QPointF(pan_x, pan_y)

    @staticmethod
    def _compute_fit_geometry(img_w: int, img_h: int, viewport_w: int, viewport_h: int):
        viewport_w = max(1, int(viewport_w))
        viewport_h = max(1, int(viewport_h))
        img_w = max(1, int(img_w))
        img_h = max(1, int(img_h))

        scale = min(viewport_w / img_w, viewport_h / img_h)
        draw_w = max(1, round(img_w * scale))
        draw_h = max(1, round(img_h * scale))
        offset_x = (viewport_w - draw_w) // 2
        offset_y = (viewport_h - draw_h) // 2
        display_rect = QRect(offset_x, offset_y, draw_w, draw_h)
        return scale, draw_w, draw_h, offset_x, offset_y, display_rect

    def _update_fit_metrics(self, debug_reason: str = ""):
        if not self.original_pixmap:
            self._img_display_rect = None
            self._img_scale = 1.0
            self.offset = QPoint(0, 0)
            self._scale = 1.0
            return

        img_w = self.original_pixmap.width()
        img_h = self.original_pixmap.height()
        vp_w = max(1, self.width())
        vp_h = max(1, self.height())

        base_scale, _draw_w, _draw_h, offset_x, offset_y, _display_rect = (
            self._compute_fit_geometry(
                img_w=img_w,
                img_h=img_h,
                viewport_w=vp_w,
                viewport_h=vp_h,
            )
        )
        draw_scale = base_scale * self.zoom
        draw_w = max(1, round(img_w * draw_scale))
        draw_h = max(1, round(img_h * draw_scale))
        pan_x = int(round(self.pan_px.x()))
        pan_y = int(round(self.pan_px.y()))
        display_rect = QRect(offset_x + pan_x, offset_y + pan_y, draw_w, draw_h)

        self._img_scale = draw_scale
        self._img_display_rect = display_rect
        self.offset = QPoint(display_rect.x(), display_rect.y())
        self._scale = draw_scale
        self._img_size = (img_w, img_h)

        signature = (
            vp_w,
            vp_h,
            img_w,
            img_h,
            round(base_scale, 8),
            round(self.zoom, 6),
            round(self.pan_px.x(), 3),
            round(self.pan_px.y(), 3),
            display_rect,
        )
        if signature != self._last_fit_debug_signature:
            self._last_fit_debug_signature = signature
            print(
                f"PREVIEW FIT [{debug_reason or 'update'}] "
                f"viewport={vp_w}x{vp_h} img={img_w}x{img_h} "
                f"base={base_scale:.6f} zoom={self.zoom:.4f} scale={draw_scale:.6f} "
                f"pan={self.pan_px.x():.1f},{self.pan_px.y():.1f} "
                f"rect={display_rect.x()},{display_rect.y()},"
                f"{display_rect.width()}x{display_rect.height()}"
            )

    def _can_interact(self) -> bool:
        return self._interactive and self.original_pixmap is not None

    def get_view_state(self):
        return float(self.zoom), QPointF(self.pan_px)

    def set_view_state(self, zoom: float, pan_px: QPointF, *, repaint: bool = True):
        clamped_zoom = max(self.min_zoom, min(self.max_zoom, float(zoom)))
        self.zoom = clamped_zoom
        self.pan_px = QPointF(pan_px)
        self._user_touched = (self.zoom != 1.0) or (self.pan_px != QPointF(0.0, 0.0))
        self._update_fit_metrics(debug_reason="set_view_state")
        if repaint:
            self.update()

    def _emit_view_changed(self):
        self.viewChanged.emit(self.zoom, self.pan_px.x(), self.pan_px.y())

    def get_transform(self):
        return self._scale, QPoint(self.offset)

    def set_transform(self, scale, offset):
        self._external_transform_active = True
        if self._use_world:
            self._world_scale = max(0.0001, scale)
            self._img_scale = self._world_scale
        else:
            # BASE/RAW view is always fit-to-viewport.
            self._reset_view()
            self.update()
            return
        self.offset = QPoint(offset)
        self.update()

    def wheelEvent(self, event):
        if not self._can_interact():
            return
        self._user_touched = True
        steps = event.angleDelta().y() / 120.0
        new_zoom = self.zoom * (1.15**steps)
        self.zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
        self._clamp_pan()
        self._update_fit_metrics(debug_reason="wheel")
        self.update()
        self._emit_view_changed()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and hasattr(
            self, "_preview_window"
        ):
            self._preview_window.open_right_preview_fullscreen()
            event.accept()
            return
        if not self._can_interact():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            self._user_touched = True

    def mouseMoveEvent(self, event):
        if not self._can_interact():
            return
        if self._dragging:
            delta = event.pos() - self._last_pos
            self.pan_px += QPointF(float(delta.x()), float(delta.y()))
            self._clamp_pan()
            self._last_pos = event.pos()
            self._update_fit_metrics(debug_reason="drag")
            self.update()
            self._emit_view_changed()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def mouseDoubleClickEvent(self, event):
        if not self._can_interact():
            return
        self._user_touched = False
        self._reset_view()
        self.update()
        self._emit_view_changed()

    def update_scaled(self):
        pass  # renderelés paintEvent-ben

    def set_nearest_preview(self, enabled: bool) -> None:
        self._nearest_preview = bool(enabled)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._nearest_preview:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), self.palette().window())

        if self._use_world:
            painter.translate(self.offset)
            painter.scale(self._world_scale, self._world_scale)

        if self.original_pixmap:
            if self._use_world:
                if self._cached_gray_image is None:
                    self._cached_gray_image = (
                        self.original_pixmap.toImage().convertToFormat(
                            QImage.Format.Format_Grayscale8
                        )
                    )
                painter.drawImage(0, 0, self._cached_gray_image)
            else:
                self._update_fit_metrics(debug_reason="paint")
                rect = self._img_display_rect
                if rect and rect.width() > 0 and rect.height() > 0:
                    transform_mode = (
                        Qt.TransformationMode.FastTransformation
                        if self._nearest_preview
                        else Qt.TransformationMode.SmoothTransformation
                    )
                    scaled = self.original_pixmap.scaled(
                        rect.width(),
                        rect.height(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        transform_mode,
                    )
                    painter.drawPixmap(rect.x(), rect.y(), scaled)

        if self._use_world and self._px_per_mm:
            step_mm = 1
            step_px = self._px_per_mm * step_mm
            rect = painter.viewport()
            left = int((-self.offset.x()) / self._world_scale)
            top = int((-self.offset.y()) / self._world_scale)
            right = int((rect.width() - self.offset.x()) / self._world_scale)
            bottom = int((rect.height() - self.offset.y()) / self._world_scale)

            pen = painter.pen()
            pen.setColor(Qt.GlobalColor.gray)
            painter.setPen(pen)

            x = int(left // step_px * step_px)
            while x <= right:
                painter.drawLine(int(x), int(top), int(x), int(bottom))
                x += step_px

            y = int(top // step_px * step_px)
            while y <= bottom:
                painter.drawLine(int(left), int(y), int(right), int(y))
                y += step_px
        painter.end()

    def view_to_image(self, px: QPoint):
        if self._img_display_rect is None:
            return None
        rect = self._img_display_rect
        if not rect.contains(px):
            return None
        scale = self._img_scale
        if scale <= 0:
            return None
        x_img = (px.x() - rect.x()) / scale
        y_img = (px.y() - rect.y()) / scale
        return x_img, y_img

    def image_to_view(self, x_img: float, y_img: float) -> QPoint:
        if self._img_display_rect is None:
            return QPoint(0, 0)
        rect = self._img_display_rect
        scale = self._img_scale
        x_view = rect.x() + x_img * scale
        y_view = rect.y() + y_img * scale
        return QPoint(int(round(x_view)), int(round(y_view)))


class CropOverlayLabel(ZoomableLabel):
    CORNER_HANDLE_SIZE_VIEW_PX = 12.0
    HANDLE_HIT_TOLERANCE_VIEW_PX = 22.0

    def __init__(self, owner, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner = owner
        self._crop_dragging = False
        self._crop_drag_anchor = QPointF(0.0, 0.0)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._owner.crop_enabled
            and self._owner.crop_valid
            and isinstance(self._owner.crop_rect, QRectF)
        ):
            img_pt = self.view_to_image(event.pos())
            if img_pt is not None:
                image_pos = QPointF(img_pt[0], img_pt[1])
                handle = self._owner._detect_crop_handle(event.pos())
                if handle:
                    self._owner.crop_drag_mode = handle
                    self._owner._drag_start_pos = image_pos
                    self._owner._original_crop_rect = QRectF(self._owner.crop_rect)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._owner.crop_drag_mode and self._owner.crop_enabled:
            img_pt = self.view_to_image(event.pos())
            if img_pt is None:
                return
            image_pos = QPointF(img_pt[0], img_pt[1])
            self._owner._update_crop_drag(image_pos)
            self.update()
            return

        cursor_mode = self._owner._detect_crop_handle(event.pos())
        cursor = Qt.CursorShape.ArrowCursor
        if cursor_mode == "move":
            cursor = Qt.CursorShape.SizeAllCursor
        elif cursor_mode in {"resize_tl", "resize_br"}:
            cursor = Qt.CursorShape.SizeFDiagCursor
        elif cursor_mode in {"resize_tr", "resize_bl"}:
            cursor = Qt.CursorShape.SizeBDiagCursor
        elif cursor_mode in {"resize_l", "resize_r"}:
            cursor = Qt.CursorShape.SizeHorCursor
        elif cursor_mode in {"resize_t", "resize_b"}:
            cursor = Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._owner.crop_drag_mode:
            self._owner.crop_drag_mode = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if bool(getattr(self._owner, "_left_shows_cropped_source", False)):
            return
        if not self._owner.crop_enabled or not isinstance(
            self._owner.crop_rect, QRectF
        ):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # IMPORTANT:
        # Crop logic must never modify zoom, pan, or preview scaling.
        # It only draws overlay in image space.
        crop_rect = self._owner.crop_rect
        tl = self.image_to_view(crop_rect.left(), crop_rect.top())
        br = self.image_to_view(crop_rect.right(), crop_rect.bottom())
        crop_view = QRectF(QPointF(tl), QPointF(br)).normalized()

        painter.setPen(QPen(Qt.GlobalColor.green, 2))
        if self._owner.crop_shape_mode == "circle":
            painter.drawEllipse(crop_view)
        else:
            painter.drawRect(crop_view)

        handle_half = self.CORNER_HANDLE_SIZE_VIEW_PX / 2.0
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(QColor(255, 255, 255))
        for corner in (
            crop_view.topLeft(),
            crop_view.topRight(),
            crop_view.bottomLeft(),
            crop_view.bottomRight(),
        ):
            handle_rect = QRectF(
                corner.x() - handle_half,
                corner.y() - handle_half,
                self.CORNER_HANDLE_SIZE_VIEW_PX,
                self.CORNER_HANDLE_SIZE_VIEW_PX,
            )
            painter.drawRect(handle_rect)

        overlay = QPainterPath()
        overlay.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        if self._owner.crop_shape_mode == "circle":
            hole.addEllipse(crop_view)
        else:
            hole.addRect(crop_view)
        painter.fillPath(overlay.subtracted(hole), QColor(0, 0, 0, 100))
        painter.end()


# 🖼 Fő előnézet ablak
class ImagePreviewWindow(QWidget):
    GAMMA_MIN = 0.3
    GAMMA_MAX = 3.0
    GAMMA_DEFAULT_SLIDER = int(
        round(
            (math.log(1.0 / GAMMA_MIN) / math.log(GAMMA_MAX / GAMMA_MIN))
            * 100.0
        )
    )

    # ------------------------------------------------------------------
    # UI TECHNICAL SCOPE (IMPORTANT FOR IMPLEMENTATION)
    #
    # The DISPLAY layer is allowed to:
    # - mitigate noisy or high-frequency UI events (e.g. debounce, throttle)
    # - perform temporary / ergonomic pre-filtering of user input
    # - suppress obviously incomplete intermediate UI states
    # - improve usability and determinism of UI → MAG communication
    #
    # These actions are considered TECHNICAL, NOT DECISIONAL, as long as:
    # - no kernel state is created or modified here
    # - no workflow branch is chosen here
    # - no value is persisted or finalized here
    #
    # If a change would affect workflow state, analysis triggering,
    # or semantic meaning, STOP and escalate.
    # ------------------------------------------------------------------

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        # App reference must exist BEFORE any tr() call
        self.app = app
        self.tr = self._workspace_tr

        # Preview fizikai referencia: hány képernyőpixel feleljen meg 1 mm-nek

        self.setWindowTitle(
            self.tr(
                "laser.preview.title",
                "Image preview - Laser simulation",
            )
        )

        # Preview ablak minimális mérete – kép nem tolhatja szét
        self.setMinimumSize(1000, 650)

        self.resize(1200, 800)
        self.setObjectName("imagePreviewWindow")
        self.setStyleSheet(
            """
        QWidget#imagePreviewWindow {
            background-color: #f0f0f0;
        }
        """
        )

        self.original_pixmap = None
        self.simulated_pixmap = None
        self._fs_show_original = False
        self._right_view_mode = RightViewMode.NONE

        # --- Layout constants (deterministic geometry) ---
        self.UI_MARGIN = 5  # outer margins
        self.UI_GAP = 5  # gap between left/right views
        self.INFO_BAR_HEIGHT = 24  # ~1 line
        self.EXPLAIN_BAR_HEIGHT = 36  # ~2 lines

        # --- Deterministic toolbar vertical grid ---
        TOOLBAR_HEIGHT = 120
        PANEL_WIDTH = 100
        PANEL_PADDING = 4
        PANEL_BORDER = 1
        PANEL_ROW_GAP = 6

        # Inner content height:
        # TOOLBAR_HEIGHT - 2*border - 2*padding
        # 120 - 2 - 8 = 110
        # 3 rows + 2 gaps
        _inner_h = TOOLBAR_HEIGHT - 2 * PANEL_BORDER - 2 * PANEL_PADDING
        PANEL_ROW_HEIGHT = int((_inner_h - 2 * PANEL_ROW_GAP) / 3)
        TOOLBAR_ROW = PANEL_ROW_HEIGHT

        TOOLBAR_GAP = 2

        FIELD_STYLE = """
QLineEdit, QPushButton {
    background-color: #ffffff;
    border: 1px solid #b0b0b0;
    border-radius: 3px;
}
"""

        # references for normal view (for resize-sync)
        self._left_view = None
        self._right_view = None
        self._shared_view_zoom = 1.0
        self._shared_view_pan = QPointF(0.0, 0.0)
        self._preview_fullscreen = False
        self._preview_was_maximized = False
        self._fs_dialog = None
        self._fs_view = None
        self._fs_controls_old_parent = None
        self._fs_controls_old_layout = None
        self._fs_controls_old_index = None
        self._fs_drag_active = False
        self._fs_drag_offset = None
        self._gcode_export_thread = None
        self._gcode_export_worker = None
        self._gcode_export_running = False
        self._pending_frame_options = None
        self._export_freeze_state = []

        # UI elements (for i18n refresh)
        self.btn_load = None
        self.btn_process = None

        self.engrave_width_input: QLineEdit | None = None
        self.engrave_height_input: QLineEdit | None = None
        self._size_field_sync_lock = False
        self._last_size_field_edited = "width"
        self.crop_enabled = False
        self.crop_ratio = None
        self.crop_rect = None
        self.crop_valid = False
        self.crop_drag_mode = None
        self.crop_min_size_px = 200
        self.crop_shape_mode = "square"
        self._left_shows_cropped_source = False
        self._drag_start_pos = QPointF(0.0, 0.0)
        self._original_crop_rect = QRectF()
        self._crop_enabled: bool = False
        self._crop_rect_img: tuple[int, int, int, int] | None = None

        self.current_view = None

        self.image_path = None
        self.current_image_path = None

        self.raw_analysis = None
        self.raw_info = None
        self.current_machine_profile = None
        self.processed_info = None  # ← kernel által visszaadott fizikai kép adatai
        self.final_engrave_image = None
        self._updating_ui = False
        self._rebuild_request_trace: list[str] = []
        self._rebuild_start_counter = 0
        self._base_rebuild_timer = QTimer(self)
        self._base_rebuild_timer.setSingleShot(True)
        self._base_rebuild_timer.timeout.connect(self._on_base_rebuild_timeout)
        self.serpentine_scan = False
        self._last_mode_index = 0
        self.machine_mode = str(getattr(self.app, "machine_mode", "diode") or "diode").strip().lower()
        if self.machine_mode not in ("diode", "fiber"):
            self.machine_mode = "diode"

        # RAW image description is immutable and created ONLY on image open
        # Preview / pixmap must NEVER act as image metadata source

        # Info bar
        self.info_label = QLabel(self.tr("laser.preview.no_image", "No image loaded"))
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.info_label.setFixedHeight(self.INFO_BAR_HEIGHT)
        self.info_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        # Explanation / decision hint (bottom-most)
        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.explanation_label.setFixedHeight(self.EXPLAIN_BAR_HEIGHT)
        self.explanation_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        # Visual style for explanation panel
        self.explanation_label.setStyleSheet(
            """
            color: #555555;
            font-size: 10px;
            background-color: #f5f5f5;
            padding: 6px 8px;
            border-top: 1px solid #dddddd;
            """
        )

        # TEMP: explanation placeholder
        self.explanation_label.setText(
            self.tr(
                "laser.explain.placeholder",
                "Explanation text will appear here based on image analysis.",
            )
        )

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            self.UI_MARGIN, self.UI_MARGIN, self.UI_MARGIN, self.UI_MARGIN
        )
        main_layout.setSpacing(self.UI_GAP)

        # Toolbar – Excel-style 2×5 grid (outer layout)
        from PyQt6.QtWidgets import QGridLayout

        toolbar = QGridLayout()
        toolbar.setHorizontalSpacing(10)
        toolbar.setVerticalSpacing(2)

        # --- Toolbar column contract (proportional scaling) ---
        # Base layout at ~1000px:
        # P1 = 120, P2 = 120, P3 = 120, P4 = 430, P5 = 120
        # These ratios must scale together on resize
        toolbar.setColumnMinimumWidth(0, PANEL_WIDTH)
        toolbar.setColumnMinimumWidth(1, PANEL_WIDTH)
        toolbar.setColumnMinimumWidth(2, PANEL_WIDTH)
        toolbar.setColumnMinimumWidth(3, PANEL_WIDTH)
        toolbar.setColumnMinimumWidth(4, PANEL_WIDTH)

        toolbar.setColumnStretch(0, 120)  # Panel 1
        toolbar.setColumnStretch(1, 120)  # Panel 2
        toolbar.setColumnStretch(2, 120)  # Panel 3
        toolbar.setColumnStretch(3, 430)  # Panel 4 (module grid)
        toolbar.setColumnStretch(4, 120)  # Panel 5

        # Two fixed rows (Engrave / DPI)
        toolbar.setRowStretch(0, 0)
        toolbar.setRowStretch(1, 0)

        # --- Panel host widgets (visual zones) ---
        def make_panel():
            w = QWidget()
            w.setObjectName("imageWorkspaceToolbarPanel")
            w.setFixedHeight(TOOLBAR_HEIGHT)
            # Card-like panel style (StartOverlay-inspired, but light theme)
            w.setStyleSheet(
                f"""
                QWidget#imageWorkspaceToolbarPanel {{
                    background-color: #9BB7DA;
                    border: {PANEL_BORDER}px solid #ffffff; /* cool gray/blue edge */
                    border-radius: 6px;                     /* softer, card-like */
                }}
            """
            )
            w.setContentsMargins(
                PANEL_PADDING,
                PANEL_PADDING,
                PANEL_PADDING,
                PANEL_PADDING,
            )
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            return w, lay

        main_layout.addLayout(toolbar)

        panel1, panel1_lay = make_panel()
        panel1.setMinimumWidth(PANEL_WIDTH)

        self.btn_load = QPushButton(self.tr("common.load_image", "Load image"))
        self.btn_load.clicked.connect(self._on_load_image_clicked)

        BTN_STYLE = """
        QPushButton {
            background-color: palette(Window);
        }
        """
        self.btn_load.setStyleSheet(BTN_STYLE)
        self.btn_load.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        panel1_lay.addWidget(self.btn_load)

        # A1  → Load
        toolbar.addWidget(panel1, 0, 0, 1, 1)

        # --- Panel 2 (Crop panel): checkbox + shape mode buttons ---
        panel2, panel2_lay = make_panel()
        panel2.setMinimumWidth(PANEL_WIDTH)
        panel2_lay.setSpacing(PANEL_ROW_GAP)

        self.crop_checkbox = QCheckBox(
            self.tr("workspace.image.toolbar.crop", "Crop")
        )
        self.crop_square_btn = QPushButton(
            self.tr("workspace.image.toolbar.crop_square", "□ Square")
        )
        self.crop_circle_btn = QPushButton(
            self.tr("workspace.image.toolbar.crop_circle", "○ Circle")
        )

        self.crop_square_btn.setCheckable(True)
        self.crop_circle_btn.setCheckable(True)
        self.crop_checkbox.setChecked(False)
        self.crop_square_btn.setEnabled(False)
        self.crop_circle_btn.setEnabled(False)
        self.crop_square_btn.setChecked(True)
        self.crop_circle_btn.setChecked(False)

        self.crop_checkbox.toggled.connect(self._on_crop_toggled)
        self.crop_square_btn.clicked.connect(self._on_crop_square_clicked)
        self.crop_circle_btn.clicked.connect(self._on_crop_circle_clicked)

        panel2_lay.addWidget(self.crop_checkbox)
        panel2_lay.addWidget(self.crop_square_btn)
        panel2_lay.addWidget(self.crop_circle_btn)
        self._update_crop_shape_buttons_visual()

        # B1/B2  → Crop
        toolbar.addWidget(panel2, 0, 1, 2, 1)

        # toolbar buttons (no panel abstraction)
        self._toolbar_load_button = self.btn_load

        # legacy flow-layout reference removed

        self.engrave_width_input = QLineEdit()
        self.engrave_width_input.setPlaceholderText(
            self.tr("workspace.image.ph.width_mm", "Width mm")
        )
        self.engrave_width_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.engrave_height_input = QLineEdit()
        self.engrave_height_input.setPlaceholderText(
            self.tr("workspace.image.ph.height_mm", "Height mm")
        )
        self.engrave_height_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.engrave_width_input.textChanged.connect(self._on_width_mm_changed)
        self.engrave_height_input.textChanged.connect(self._on_height_mm_changed)
        self.engrave_width_input.editingFinished.connect(self._on_width_mm_finished)
        self.engrave_height_input.editingFinished.connect(self._on_height_mm_finished)
        self.engrave_width_input.returnPressed.connect(
            self._update_crop_from_size_fields
        )
        self.engrave_height_input.returnPressed.connect(
            self._update_crop_from_size_fields
        )

        # --- DPI size input (User FIELD) ---
        self.engrave_dpi_input = QLineEdit()
        self.engrave_dpi_input.setPlaceholderText(
            self.tr(
                "user.preview.dpi_size_placeholder",
                "DPI size (e.g. 318)",
            )
        )
        self.engrave_dpi_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.engrave_axis = "X"
        self.scan_axis_input = QComboBox()
        self.scan_axis_input.addItems(["X", "Y"])
        self.scan_axis_input.setCurrentText(self.engrave_axis)
        self.scan_axis_input.currentTextChanged.connect(self._on_scan_axis_changed)

        # --- User modul size input (User FIELD) ---
        self.engrave_user_modul_input = QLineEdit()
        self.engrave_user_modul_input.setPlaceholderText(
            self.tr(
                "user.preview.user_modul_size_placeholder",
                "Modul size (e.g. 318)",
            )
        )
        self.engrave_user_modul_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- Engrave port load ---
        self.engrave_port_load_input = PortComboBox()
        self.engrave_port_load_input.setEditable(True)
        # explicit user action only
        self.engrave_port_load_input.activated.connect(self.commit_engrave_port_load)
        self.engrave_port_load_input.lineEdit().returnPressed.connect(
            self.commit_engrave_port_load
        )

        # --- Config save ouput (User FIELD) ---
        self.engrave_save_config_input = QPushButton(
            self.tr("user.preview.save_config_placeholder", "Save config")
        )
        # Panel 3 grid cell: must fill 26×80 exactly
        self.engrave_save_config_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.engrave_save_config_input.setFixedHeight(TOOLBAR_ROW)
        self.engrave_save_config_input.setMinimumHeight(0)
        self.engrave_save_config_input.setMinimumSize(0, 0)

        # --- Config load input (User FIELD) ---
        self.engrave_config_load_input = QPushButton(
            self.tr("user.preview.config_load_placeholder", "Load config")
        )
        # Panel 3 grid cell: must fill 26×80 exactly
        self.engrave_config_load_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.engrave_config_load_input.setFixedHeight(TOOLBAR_ROW)
        self.engrave_config_load_input.setMinimumHeight(0)
        self.engrave_config_load_input.setMinimumSize(0, 0)

        # Panel 3 top row must follow grid cell width (80px)
        # so these MUST be expanding, not fixed
        self.engrave_user_modul_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.engrave_user_modul_input.setMinimumSize(0, 0)

        self.engrave_port_load_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.engrave_port_load_input.setMinimumSize(0, 0)

        # Engrave block should expand horizontally
        self.engrave_width_input.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.engrave_height_input.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.engrave_dpi_input.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        ROW_HEIGHT = TOOLBAR_ROW

        for w in (
            self.engrave_width_input,
            self.engrave_height_input,
            self.engrave_dpi_input,
            self.engrave_user_modul_input,
            self.engrave_port_load_input,
        ):
            w.setFixedHeight(ROW_HEIGHT)

        # UI-only: szöveg szerkesztés, NEM küld workflow eseményt
        # snapshot model – no live kernel communication
        # --- Panel 3 (Engrave panel): 1 column, 3 rows (width + height + dpi) ---
        panel3, panel3_lay = make_panel()
        panel3.setMinimumWidth(PANEL_WIDTH)

        # inner layout: two rows with the same 6px middle gap as the spec
        panel3_lay.setSpacing(PANEL_ROW_GAP)

        self.engrave_width_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.engrave_height_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.engrave_dpi_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        panel3_lay.addWidget(self.engrave_width_input)
        panel3_lay.addWidget(self.engrave_height_input)
        panel3_lay.addWidget(self.engrave_dpi_input)

        # Column C → Engrave panel (rowspan=2)
        toolbar.addWidget(panel3, 0, 2, 2, 1)

        # snapshot model – no live kernel communication

        self.engrave_user_modul_input.textChanged.connect(
            self._on_user_modul_text_changed
        )

        self.xrate_input = QLineEdit()
        self.xrate_input.setPlaceholderText(
            self.tr("workspace.image.ph.x_rate", "xRate")
        )

        self.xmaxrate_input = QLineEdit()
        self.xmaxrate_input.setPlaceholderText(
            self.tr("workspace.image.ph.x_max", "xMax")
        )

        self.xaccel_input = QLineEdit()
        self.xaccel_input.setPlaceholderText(
            self.tr("workspace.image.ph.x_accel", "xAccel")
        )

        self.yrate_input = QLineEdit()
        self.yrate_input.setPlaceholderText(
            self.tr("workspace.image.ph.y_steps_mm", "Y Steps/mm")
        )

        self.ymaxrate_input = QLineEdit()
        self.ymaxrate_input.setPlaceholderText(
            self.tr("workspace.image.ph.y_max_rate", "Y Max rate")
        )

        self.yaccel_input = QLineEdit()
        self.yaccel_input.setPlaceholderText(
            self.tr("workspace.image.ph.y_acceleration", "Y Acceleration")
        )

        from PyQt6.QtWidgets import QGridLayout

        module_grid = QGridLayout()
        module_grid.setHorizontalSpacing(6)
        # Panel 3: 2 rows, gap via spacing ONLY
        module_grid.setVerticalSpacing(PANEL_ROW_GAP)
        module_grid.setRowMinimumHeight(0, PANEL_ROW_HEIGHT)
        module_grid.setRowMinimumHeight(1, PANEL_ROW_HEIGHT)
        module_grid.setRowMinimumHeight(2, PANEL_ROW_HEIGHT)
        module_grid.setRowStretch(0, 0)
        module_grid.setRowStretch(1, 0)
        module_grid.setRowStretch(2, 0)

        # Panel 3 – enforce 4×80px columns
        for _col in range(4):
            module_grid.setColumnMinimumWidth(_col, 80)

        # Allow proportional expansion inside Panel3
        module_grid.setColumnStretch(0, 1)
        module_grid.setColumnStretch(1, 1)
        module_grid.setColumnStretch(2, 1)
        module_grid.setColumnStretch(3, 1)

        # top row
        module_grid.addWidget(self.engrave_user_modul_input, 0, 0)

        module_grid.addWidget(self.engrave_port_load_input, 0, 1)

        self.engrave_save_config_input.clicked.connect(self._on_save_config_clicked)
        module_grid.addWidget(self.engrave_save_config_input, 0, 2)

        self.engrave_config_load_input.clicked.connect(self._on_load_config_clicked)
        module_grid.addWidget(self.engrave_config_load_input, 0, 3)

        # bottom row
        module_grid.addWidget(self.xrate_input, 1, 0)
        module_grid.addWidget(self.xmaxrate_input, 1, 1)
        module_grid.addWidget(self.xaccel_input, 1, 2)

        module_grid.addWidget(self.yrate_input, 2, 0)
        module_grid.addWidget(self.ymaxrate_input, 2, 1)
        module_grid.addWidget(self.yaccel_input, 2, 2)

        # current profile display (UI-only placeholder)
        self.current_profile_display = QLineEdit()
        self.current_profile_display.setReadOnly(True)
        self.current_profile_display.setPlaceholderText(
            self.tr("user.preview.current_profile", "Current profile")
        )

        axis_host = QWidget()
        axis_host.setFixedHeight(TOOLBAR_ROW)
        axis_row = QHBoxLayout(axis_host)
        axis_row.setContentsMargins(0, 0, 0, 0)
        axis_row.setSpacing(6)

        self.axis_lbl = QLabel(
            self.tr("workspace.image.toolbar.scan_axis", "Scan axis")
        )
        self.axis_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        self.scan_axis_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.scan_axis_input.setFixedHeight(TOOLBAR_ROW)

        axis_row.addWidget(self.axis_lbl)
        axis_row.addWidget(self.scan_axis_input, 1)
        # IMPORTANT: add to grid ONLY after widgets exist
        self.current_profile_display.setFixedHeight(TOOLBAR_ROW)
        self.current_profile_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        axis_host.setFixedHeight(TOOLBAR_ROW)

        module_grid.addWidget(self.current_profile_display, 1, 3)
        module_grid.addWidget(axis_host, 2, 3)

        for w in (
            self.xrate_input,
            self.xmaxrate_input,
            self.xaccel_input,
            self.yrate_input,
            self.ymaxrate_input,
            self.yaccel_input,
            self.current_profile_display,
        ):
            w.setFixedHeight(TOOLBAR_ROW)

        panel4, panel4_lay = make_panel()
        panel4_lay.addLayout(module_grid, 1)
        panel4_lay.setStretch(0, 1)

        # Column D → ModuleGrid panel (2 rows)
        toolbar.addWidget(panel4, 0, 3, 2, 1)

        panel5, panel5_lay = make_panel()
        panel5.setMinimumWidth(PANEL_WIDTH)

        self.btn_process = QPushButton(self.tr("laser.preview.process", "Process"))
        self.btn_process.clicked.connect(self.run_processing_dialog)
        self.btn_process.setStyleSheet(BTN_STYLE)
        self.btn_process.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        panel5_lay.addWidget(self.btn_process)

        # ---------------------------------------------------------
        # GRBL CONNECTION INDICATOR (UI TELEMETRY ONLY)
        # ---------------------------------------------------------
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)

        self.grbl_status_dot = QLabel()
        self.grbl_status_dot.setFixedSize(10, 10)
        self.grbl_status_dot.setStyleSheet("background:#888; border-radius:5px;")

        self.grbl_status_label = QLabel(
            self.tr("workspace.image.grbl.unknown", "GRBL: unknown")
        )
        self.grbl_status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.grbl_status_label.setStyleSheet("font-size:10px; color:#222;")

        status_row.addWidget(self.grbl_status_dot)
        status_row.addWidget(self.grbl_status_label, 1)

        status_host = QWidget()
        status_host.setLayout(status_row)
        panel5_lay.addWidget(status_host)

        # Column E → Process panel (2 rows)
        toolbar.addWidget(panel5, 0, 4, 2, 1)
        self._toolbar_panels = (panel1, panel2, panel3, panel4, panel5)

        # --- Toolbar deterministic width model (c-based columns) ---
        # Keep references so resizeEvent can re-apply.
        # toolbar root is now a grid; legacy flow-layout references removed
        self._toolbar_module_grid = module_grid
        self._toolbar_row_height = ROW_HEIGHT

        # Engrave column widgets (size + dpi)
        self._toolbar_engrave_fields = (
            self.engrave_width_input,
            self.engrave_height_input,
            self.engrave_dpi_input,
        )
        # ModuleGrid fields (2×4 table)
        self._toolbar_module_fields = (
            self.engrave_user_modul_input,
            self.engrave_port_load_input,
            self.engrave_save_config_input,
            self.engrave_config_load_input,
            self.xrate_input,
            self.xmaxrate_input,
            self.xaccel_input,
            self.yrate_input,
            self.ymaxrate_input,
            self.yaccel_input,
            self.current_profile_display,
        )

        # Apply once after build (and again on every resize)
        self._apply_toolbar_geometry()

        # (rates row moved into module block above)

        # Informatív sáv – a kép ÁLLAPOTÁRÓL (RAW / ANALYSIS)
        info_layout = QHBoxLayout()
        info_layout.addWidget(self.info_label)
        main_layout.addLayout(info_layout)

        # Preview host gets ALL remaining vertical space (window decides, not image)
        self.view_host = QWidget(self)
        self.view_host_layout = QVBoxLayout(self.view_host)
        self.view_host_layout.setContentsMargins(0, 0, 0, 0)
        self.view_host_layout.setSpacing(0)
        main_layout.addWidget(self.view_host, 1)

        self.crop_hint_label = QLabel(
            self.tr(
                "workspace.image.central.hint.crop_physical_size",
                "Add meg a fizikai méretet a vágáshoz",
            ),
            self.view_host,
        )
        self.crop_hint_label.setStyleSheet(
            """
            QLabel {
                background: rgba(0,0,0,160);
                color: white;
                padding: 8px;
                border-radius: 6px;
            }
            """
        )
        self.crop_hint_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.crop_hint_label.hide()

        # ==========================================================
        # IMAGE CONTROLS (2 rows under preview)
        # ==========================================================

        CONTROL_ROW_H = 24
        CONTROL_GAP = 4

        controls_host = QWidget(self)
        controls_layout = QVBoxLayout(controls_host)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(CONTROL_GAP)

        # ---------- Row 1 ----------
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(
            self.tr("workspace.image.central.mode.grayscale", "Grayscale"),
            "Grayscale",
        )
        self.mode_combo.addItem(
            self.tr("workspace.image.central.mode.bayer", "Bayer"),
            "BAYER",
        )
        self.mode_combo.insertSeparator(self.mode_combo.count())
        self.mode_combo.addItem(self.tr("serpentine_scan", "Serpentine scan"), "__SERPENTINE_TOGGLE__")
        serpentine_item = self.mode_combo.model().item(self.mode_combo.count() - 1)
        if isinstance(serpentine_item, QStandardItem):
            serpentine_item.setCheckable(True)
            serpentine_item.setCheckState(Qt.CheckState.Unchecked)
        self.mode_combo.insertSeparator(self.mode_combo.count())
        self.mode_combo.addItem(
            self.tr(
                "workspace.image.central.mode.floyd_steinberg", "Floyd–Steinberg"
            ),
            "FloydSteinberg",
        )
        self.mode_combo.addItem(
            self.tr("workspace.image.central.mode.atkinson", "Atkinson"),
            "Atkinson",
        )
        self.mode_combo.addItem(
            self.tr(
                "workspace.image.central.mode.jjn",
                "Jarvis–Judice–Ninke (JJN)",
            ),
            "JJN",
        )
        self.mode_combo.addItem(
            self.tr("workspace.image.central.mode.stucki", "Stucki"),
            "Stucki",
        )
        self._last_mode_index = self.mode_combo.currentIndex()

        self.negative_checkbox = QCheckBox(
            self.tr("workspace.image.central.chk.negative", "Negatív")
        )
        self.nearest_preview_checkbox = QCheckBox(
            self.tr("workspace.image.central.chk.nearest_preview", "Nearest preview")
        )
        self.mirror_x_checkbox = QCheckBox()
        self.mirror_x_checkbox.setText("↔")
        self.mirror_x_checkbox.setToolTip(
            self.tr("workspace.image.central.tt.mirror_x", "Tükrözés vízszintesen")
        )
        self.mirror_x_checkbox.setFixedWidth(32)

        self.mirror_y_checkbox = QCheckBox()
        self.mirror_y_checkbox.setText("↕")
        self.mirror_y_checkbox.setToolTip(
            self.tr("workspace.image.central.tt.mirror_y", "Tükrözés függőlegesen")
        )
        self.mirror_y_checkbox.setFixedWidth(32)

        self.contrast_ctrl = LabeledSlider(
            "C",
            self.tr("workspace.image.central.ctrl.contrast", "Contrast"),
            -70,
            70,
            0,
            CONTROL_ROW_H,
        )
        self.brightness_ctrl = LabeledSlider(
            "B",
            self.tr("workspace.image.central.ctrl.brightness", "Brightness"),
            -70,
            70,
            0,
            CONTROL_ROW_H,
        )
        self.gamma_ctrl = LabeledSlider(
            "G",
            self.tr("workspace.image.central.ctrl.gamma", "Gamma"),
            0,
            100,
            self.GAMMA_DEFAULT_SLIDER,
            CONTROL_ROW_H,
            display_divisor=100.0,
            display_decimals=2,
        )
        self.radius_ctrl = LabeledSlider(
            "R",
            self.tr("workspace.image.central.ctrl.radius", "Radius"),
            0,
            50,
            0,
            CONTROL_ROW_H,
        )
        self.amount_ctrl = LabeledSlider(
            "A",
            self.tr("workspace.image.central.ctrl.amount", "Amount"),
            0,
            1500,
            0,
            CONTROL_ROW_H,
        )

        for w in (
            self.mode_combo,
            self.contrast_ctrl,
            self.brightness_ctrl,
            self.gamma_ctrl,
            self.radius_ctrl,
            self.amount_ctrl,
            self.negative_checkbox,
        ):
            w.setFixedHeight(CONTROL_ROW_H)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row1.addWidget(w)

        row1.addWidget(self.mirror_x_checkbox)
        row1.addWidget(self.mirror_y_checkbox)
        self.nearest_preview_checkbox.setFixedHeight(CONTROL_ROW_H)
        self.nearest_preview_checkbox.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        row1.addWidget(self.nearest_preview_checkbox)

        controls_layout.addLayout(row1)

        # ---------- Row 2 ----------
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self.speed_input = QLineEdit()
        self.speed_input.setPlaceholderText(
            self.tr("workspace.image.central.ph.speed", "Speed")
        )
        self.max_power_input = QLineEdit()
        self.max_power_input.setPlaceholderText(
            self.tr("workspace.image.central.ph.max_power", "Max power")
        )

        self.min_power_input = QLineEdit()
        self.min_power_input.setPlaceholderText(
            self.tr("workspace.image.central.ph.min_power", "Min power")
        )

        self.overscan_auto_checkbox = QCheckBox(
            self.tr("workspace.image.central.chk.overscan_auto", "Overscan (auto)")
        )
        self.keret_checkbox = QCheckBox(
            self.tr("workspace.image.central.chk.frame", "Keret")
        )
        self.overscan_override_input = QLineEdit()
        self.overscan_override_input.setPlaceholderText(
            self.tr(
                "workspace.image.central.ph.overscan_override_mm",
                "Overscan override (mm)",
            )
        )
        self.overscan_computed_label = QLabel(
            self.tr(
                "workspace.image.central.label.overscan_off",
                "ki",
            )
        )
        self.overscan_computed_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.btn_save_image = QPushButton(
            self.tr("workspace.image.central.btn.save_image", "Save image")
        )
        self.btn_save_image.setFixedHeight(CONTROL_ROW_H)
        self.btn_save_image.setEnabled(False)
        self.btn_save_image.clicked.connect(self.save_final_image)

        self.btn_save_gcode = QPushButton(
            self.tr("workspace.image.central.btn.save_gcode", "G-code")
        )
        self.btn_save_gcode.setFixedHeight(CONTROL_ROW_H)
        self.btn_save_gcode.setEnabled(False)
        self.btn_save_gcode.clicked.connect(self.save_gcode)
        self.btn_laser = QPushButton("Laser")
        self.btn_laser.setFixedHeight(CONTROL_ROW_H)
        self.btn_laser.clicked.connect(self.launch_sender)

        for w in (
            self.speed_input,
            self.max_power_input,
            self.min_power_input,
            self.overscan_override_input,
        ):
            w.setFixedHeight(CONTROL_ROW_H)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.overscan_auto_checkbox.setFixedHeight(CONTROL_ROW_H)
        self.keret_checkbox.setFixedHeight(CONTROL_ROW_H)
        self.overscan_computed_label.setFixedHeight(CONTROL_ROW_H)
        self.overscan_computed_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        row2.addWidget(self.speed_input)
        row2.addWidget(self.max_power_input)
        row2.addWidget(self.min_power_input)
        row2.addWidget(self.overscan_override_input)
        row2.addWidget(self.overscan_auto_checkbox)
        row2.addWidget(self.overscan_computed_label)

        row2.addStretch()
        row2.addWidget(self.keret_checkbox)
        row2.addWidget(self.btn_save_image)
        row2.addWidget(self.btn_save_gcode)
        row2.addWidget(self.btn_laser)

        controls_layout.addLayout(row2)

        main_layout.addWidget(controls_host)
        self._controls_host = controls_host

        self.contrast_input = self.contrast_ctrl.value_input
        self.brightness_input = self.brightness_ctrl.value_input
        self.gamma_input = self.gamma_ctrl.value_input
        self.gamma_ctrl.slider.valueChanged.disconnect(self.gamma_ctrl._on_slider_changed)
        self.gamma_input.valueChanged.disconnect(self.gamma_ctrl._on_input_changed)
        self.gamma_input.setRange(self.GAMMA_MIN, self.GAMMA_MAX)
        self.gamma_input.setDecimals(2)
        self.gamma_input.setSingleStep(0.01)
        self.gamma_ctrl.slider.valueChanged.connect(self._on_gamma_slider_changed)
        self.gamma_input.valueChanged.connect(self._on_gamma_input_changed)
        self._on_gamma_slider_changed(self.gamma_ctrl.slider.value())
        self.radius_input = self.radius_ctrl.value_input
        self.amount_input = self.amount_ctrl.value_input

        self.mode_combo.activated.connect(self._on_mode_combo_activated)
        self.contrast_ctrl.slider.valueChanged.connect(self._on_base_control_changed)
        self.brightness_ctrl.slider.valueChanged.connect(self._on_base_control_changed)
        self.gamma_ctrl.slider.valueChanged.connect(self._on_base_control_changed)
        self.radius_ctrl.slider.valueChanged.connect(self._on_base_control_changed)
        self.amount_ctrl.slider.valueChanged.connect(self._on_base_control_changed)
        self.contrast_input.textChanged.connect(self._on_base_control_changed)
        self.brightness_input.textChanged.connect(self._on_base_control_changed)
        self.gamma_input.textChanged.connect(self._on_base_control_changed)
        self.radius_input.textChanged.connect(self._on_base_control_changed)
        self.amount_input.textChanged.connect(self._on_base_control_changed)
        self.negative_checkbox.stateChanged.connect(self._on_base_control_changed)
        self.mirror_x_checkbox.stateChanged.connect(self._on_base_control_changed)
        self.mirror_y_checkbox.stateChanged.connect(self._on_base_control_changed)
        self.nearest_preview_checkbox.toggled.connect(self._refresh_preview_render_mode)

        self.overscan_auto_checkbox.toggled.connect(self._update_overscan_label)
        self.overscan_override_input.textChanged.connect(self._update_overscan_label)
        self.speed_input.textChanged.connect(self._update_overscan_label)

        main_layout.addSpacing(2)
        main_layout.addWidget(self.explanation_label)

        current_lang = str(getattr(self.app, "language", "en") or "en").strip().lower()
        self.language_button = QPushButton(current_lang.upper())
        self.language_menu = QMenu(self.language_button)
        languages = ["en"]
        if hasattr(self, "app") and self.app and hasattr(self.app, "config_manager"):
            available = self.app.config_manager.get_available_languages()
            if available:
                languages = available
        for code in languages:
            action = self.language_menu.addAction(code.upper())
            action.triggered.connect(
                lambda _checked=False, c=code: self._set_workspace_language(c)
            )
        self.language_button.setMenu(self.language_menu)

        self.knowledge_button = QPushButton(self.tr("menu_knowledge", "Knowledge"))
        self.knowledge_menu = QMenu(self.knowledge_button)
        self.knowledge_action_user_manual = self.knowledge_menu.addAction(
            self.tr("knowledge_user_manual", "User manual")
        )
        self.knowledge_action_user_manual.triggered.connect(
            lambda _checked=False: self._open_knowledge_document("user_manual")
        )
        self.knowledge_action_image_processing = self.knowledge_menu.addAction(
            self.tr("knowledge_image_processing", "Image processing")
        )
        self.knowledge_action_image_processing.triggered.connect(
            lambda _checked=False: self._open_knowledge_document("image_processing")
        )
        self.knowledge_button.setMenu(self.knowledge_menu)

        language_row = QHBoxLayout()
        language_row.setContentsMargins(0, 0, 0, 0)
        language_row.setSpacing(6)
        language_row.addWidget(self.knowledge_button, 0, Qt.AlignmentFlag.AlignLeft)
        language_row.addWidget(self.language_button, 0, Qt.AlignmentFlag.AlignLeft)
        language_row.addStretch(1)
        main_layout.addLayout(language_row)

        # ---- Force uniform field background (visual separation from panel)
        for _w in (
            self.engrave_width_input,
            self.engrave_height_input,
            self.engrave_dpi_input,
            self.engrave_user_modul_input,
            self.engrave_port_load_input,
            self.xrate_input,
            self.xmaxrate_input,
            self.xaccel_input,
            self.yrate_input,
            self.ymaxrate_input,
            self.yaccel_input,
            self.current_profile_display,
            self.engrave_save_config_input,
            self.engrave_config_load_input,
            self.scan_axis_input,
        ):
            _w.setStyleSheet(FIELD_STYLE)

        self._pending_right_transform = None
        self.show()
        self._refresh_ports()
        self._update_overscan_label()
        self.apply_machine_mode(self.machine_mode)
        self._update_crop_hint_position()
        self._update_process_button_state()
        self._update_language_button()

    def _processed_info_as_dict(self) -> dict | None:
        if isinstance(self.processed_info, dict):
            return self.processed_info
        if self.processed_info is not None and is_dataclass(self.processed_info):
            return asdict(self.processed_info)
        return None

    def _parse_control_float(self, text: str) -> float | None:
        cleaned = (text or "").strip().replace(",", ".")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _clamp_gamma(self, gamma: float) -> float:
        return max(self.GAMMA_MIN, min(self.GAMMA_MAX, float(gamma)))

    def _clamp_unit_control(self, value: float) -> float:
        return max(-1.0, min(1.0, float(value)))

    def _contrast_from_slider(self, slider_value: int) -> float:
        clamped = max(-100, min(100, int(slider_value)))
        return self._clamp_unit_control(clamped / 100.0)

    def _brightness_from_slider(self, slider_value: int) -> float:
        clamped = max(-100, min(100, int(slider_value)))
        return self._clamp_unit_control(clamped / 100.0)

    def _slider_from_contrast(self, value: float) -> int:
        normalized = self._clamp_unit_control(value)
        return max(-100, min(100, int(round(normalized * 100.0))))

    def _slider_from_brightness(self, value: float) -> int:
        normalized = self._clamp_unit_control(value)
        return max(-100, min(100, int(round(normalized * 100.0))))

    def _gamma_from_slider(self, slider_value: int) -> float:
        clamped = max(0, min(100, int(slider_value)))
        ratio = self.GAMMA_MAX / self.GAMMA_MIN
        normalized = clamped / 100.0
        return self.GAMMA_MIN * (ratio**normalized)

    def _slider_from_gamma(self, gamma: float) -> int:
        gamma_clamped = self._clamp_gamma(gamma)
        ratio = self.GAMMA_MAX / self.GAMMA_MIN
        normalized = math.log(gamma_clamped / self.GAMMA_MIN) / math.log(ratio)
        return max(0, min(100, int(round(normalized * 100.0))))

    def _on_gamma_slider_changed(self, slider_value: int):
        with QSignalBlocker(self.gamma_input):
            self.gamma_input.setValue(self._gamma_from_slider(slider_value))

    def _on_gamma_input_changed(self, gamma_value: float):
        slider_value = self._slider_from_gamma(gamma_value)
        if slider_value != self.gamma_ctrl.slider.value():
            with QSignalBlocker(self.gamma_ctrl.slider):
                self.gamma_ctrl.slider.setValue(slider_value)
            self.gamma_ctrl.slider.valueChanged.emit(self.gamma_ctrl.slider.value())

    def _collect_base_control(self) -> dict:
        mode_value = self.mode_combo.currentData()
        if mode_value is None:
            mode_value = self.mode_combo.currentText()

        control = {
            "mode": mode_value,
            "serpentine_scan": bool(self.serpentine_scan),
            "negative": self.negative_checkbox.isChecked(),
            "mirror_x": self.mirror_x_checkbox.isChecked(),
            "mirror_y": self.mirror_y_checkbox.isChecked(),
        }
        values = {
            "contrast": self._contrast_from_slider(self.contrast_ctrl.value()),
            "brightness": self._brightness_from_slider(self.brightness_ctrl.value()),
            "radius": self._parse_control_float(self.radius_input.text()),
            "amount": self._parse_control_float(self.amount_input.text()),
        }

        gamma_raw = self.gamma_ctrl.value()
        values["gamma"] = self._clamp_gamma(self._gamma_from_slider(gamma_raw))
        for key, value in values.items():
            if value is not None:
                control[key] = value
        return control

    def apply_machine_mode(self, mode: str | None = None) -> None:
        normalized = str(mode or self.machine_mode or "diode").strip().lower()
        if normalized not in ("diode", "fiber"):
            normalized = "diode"

        self.machine_mode = normalized
        controls_enabled = normalized != "fiber"

        control_widgets = (
            getattr(self, "engrave_port_load_input", None),
            getattr(self, "engrave_save_config_input", None),
            getattr(self, "engrave_config_load_input", None),
            getattr(self, "xrate_input", None),
            getattr(self, "xmaxrate_input", None),
            getattr(self, "xaccel_input", None),
            getattr(self, "yrate_input", None),
            getattr(self, "ymaxrate_input", None),
            getattr(self, "yaccel_input", None),
            getattr(self, "current_profile_display", None),
            getattr(self, "scan_axis_input", None),
            getattr(self, "axis_lbl", None),
            getattr(self, "speed_input", None),
            getattr(self, "min_power_input", None),
            getattr(self, "max_power_input", None),
            getattr(self, "overscan_auto_checkbox", None),
            getattr(self, "overscan_override_input", None),
            getattr(self, "overscan_computed_label", None),
            getattr(self, "btn_save_gcode", None),
        )

        for widget in control_widgets:
            if isinstance(widget, QWidget):
                widget.setEnabled(controls_enabled)

        self._update_process_button_state()

    def _virtual_fiber_machine_profile(self) -> dict:
        return {
            "name": "fiber_virtual",
            "x": {
                "steps_per_mm": 1000.0,
                "max_rate": 100000.0,
                "acceleration": 10000.0,
            },
            "y": {
                "steps_per_mm": 1000.0,
                "max_rate": 100000.0,
                "acceleration": 10000.0,
            },
            "laser_module": 1.5,
            "gcode_control": {
                "speed": 0.0,
                "min_power": 0.0,
                "max_power": 0.0,
            },
        }

    def _collect_gcode_control(self) -> dict | None:
        speed = self._parse_control_float(self.speed_input.text())
        min_power = self._parse_control_float(self.min_power_input.text())
        max_power = self._parse_control_float(self.max_power_input.text())
        if speed is None or min_power is None or max_power is None:
            return None

        overscan_override = self._parse_control_float(
            self.overscan_override_input.text()
        )
        overscan_mode = "manual" if overscan_override is not None else "auto"

        machine_gcode = {}
        if isinstance(self.current_machine_profile, dict):
            candidate = self.current_machine_profile.get("gcode_control")
            if isinstance(candidate, dict):
                machine_gcode = candidate

        return {
            "speed": speed,
            "min_power": min_power,
            "max_power": max_power,
            "overscan_enabled": bool(self.overscan_auto_checkbox.isChecked()),
            "overscan_mode": overscan_mode,
            "overscan_mm": overscan_override,
            "overscan_safety_factor": 1.15,
            "pwm_max": float(machine_gcode.get("pwm_max", 1000.0) or 1000.0),
            "pwm_min": float(machine_gcode.get("pwm_min", 0.0) or 0.0),
            "baudrate": int(machine_gcode.get("baudrate", 115200) or 115200),
        }

    def _effective_scan_axis(self) -> str:
        axis = (self.engrave_axis or "X").upper()
        if axis not in ("X", "Y"):
            return "X"
        return axis

    def _computed_auto_overscan_mm(self) -> float | None:
        speed = self._parse_control_float(self.speed_input.text())
        if speed is None:
            return None

        profile = (
            self.current_machine_profile
            if isinstance(self.current_machine_profile, dict)
            else None
        )
        if not profile:
            return None

        axis_profile = profile.get(self._effective_scan_axis().lower())
        if not isinstance(axis_profile, dict):
            return None

        try:
            accel_mm_s2 = float(axis_profile.get("acceleration"))
        except (TypeError, ValueError):
            return None

        if accel_mm_s2 <= 0:
            return None

        speed_mm_s = speed / 60.0
        overscan = 1.15 * ((speed_mm_s * speed_mm_s) / (2.0 * accel_mm_s2))
        return max(0.0, overscan)

    def _update_overscan_label(self, *_args) -> None:
        override = self._parse_control_float(self.overscan_override_input.text())
        if override is not None:
            self.overscan_computed_label.setText(f"{override:.3f} mm")
            return

        if not self.overscan_auto_checkbox.isChecked():
            self.overscan_computed_label.setText(
                self.tr(
                    "workspace.image.central.label.overscan_off",
                    "ki",
                )
            )
            return

        computed = self._computed_auto_overscan_mm()
        if computed is None:
            self.overscan_computed_label.setText(
                self.tr(
                    "workspace.image.central.label.overscan_off",
                    "ki",
                )
            )
            return

        self.overscan_computed_label.setText(f"{computed:.3f} mm")

    def _update_gcode_button_state(self) -> None:
        if not hasattr(self, "btn_save_gcode"):
            return
        self.btn_save_gcode.setEnabled(
            self.final_engrave_image is not None
            and self.processed_info is not None
            and not self._gcode_export_running
        )

    def _export_freeze_widgets(self) -> list[QWidget]:
        widgets: list[QWidget] = []
        names = (
            "btn_process",
            "mode_combo",
            "negative_checkbox",
            "mirror_x_checkbox",
            "mirror_y_checkbox",
            "nearest_preview_checkbox",
            "speed_input",
            "min_power_input",
            "max_power_input",
            "overscan_auto_checkbox",
            "overscan_override_input",
            "keret_checkbox",
            "crop_checkbox",
            "crop_square_btn",
            "crop_circle_btn",
            "engrave_width_input",
            "engrave_height_input",
            "engrave_dpi_input",
            "scan_axis_input",
            "btn_load",
        )

        for name in names:
            widget = getattr(self, name, None)
            if isinstance(widget, QWidget):
                widgets.append(widget)

        for ctrl_name in ("contrast_ctrl", "brightness_ctrl", "gamma_ctrl", "radius_ctrl", "amount_ctrl"):
            ctrl = getattr(self, ctrl_name, None)
            if ctrl is None:
                continue
            slider = getattr(ctrl, "slider", None)
            value_input = getattr(ctrl, "value_input", None)
            if isinstance(slider, QWidget):
                widgets.append(slider)
            if isinstance(value_input, QWidget):
                widgets.append(value_input)

        unique_widgets = []
        seen_ids = set()
        for widget in widgets:
            widget_id = id(widget)
            if widget_id in seen_ids:
                continue
            seen_ids.add(widget_id)
            unique_widgets.append(widget)

        return unique_widgets

    def _set_export_ui_frozen(self, frozen: bool) -> None:
        if frozen:
            if self._export_freeze_state:
                return
            freeze_state = []
            for widget in self._export_freeze_widgets():
                freeze_state.append((widget, widget.isEnabled()))
                widget.setEnabled(False)
            self._export_freeze_state = freeze_state
            return

        if not self._export_freeze_state:
            return
        for widget, was_enabled in self._export_freeze_state:
            widget.setEnabled(was_enabled)
        self._export_freeze_state = []

    def _set_serpentine_scan(self, enabled: bool) -> None:
        self.serpentine_scan = bool(enabled)
        serpentine_index = self.mode_combo.findData("__SERPENTINE_TOGGLE__")
        if serpentine_index >= 0:
            serpentine_item = self.mode_combo.model().item(serpentine_index)
            if isinstance(serpentine_item, QStandardItem):
                serpentine_item.setCheckState(
                    Qt.CheckState.Checked
                    if self.serpentine_scan
                    else Qt.CheckState.Unchecked
                )

    def _on_mode_combo_activated(self, index: int):
        if self._updating_ui:
            return
        if self.mode_combo.itemData(index) == "__SERPENTINE_TOGGLE__":
            self._set_serpentine_scan(not self.serpentine_scan)
            self.mode_combo.setCurrentIndex(self._last_mode_index)
            self._on_base_control_changed()
            return
        self._last_mode_index = index
        self._on_mode_control_changed()

    def _on_mode_control_changed(self, *_args):
        if self._updating_ui:
            return
        self._rebuild_request_trace.append("mode_combo.activated")
        self._base_rebuild_timer.start(50)

    def _on_base_control_changed(self, *_args):
        if self._updating_ui:
            return
        self._rebuild_request_trace.append("base_control_changed")
        self._base_rebuild_timer.start(200)

    def _refresh_preview_render_mode(self) -> None:
        nearest = bool(self.nearest_preview_checkbox.isChecked())
        if self._right_view is not None:
            self._right_view.set_nearest_preview(nearest)
        if isinstance(self._fs_view, ZoomableLabel):
            self._fs_view.set_nearest_preview(nearest)
            self._fs_view.update()

    def _reset_controls_to_defaults(self) -> None:
        self._updating_ui = True
        widgets_to_block = [
            self.mode_combo,
            self.contrast_ctrl.slider,
            self.contrast_ctrl.value_input,
            self.brightness_ctrl.slider,
            self.brightness_ctrl.value_input,
            self.gamma_ctrl.slider,
            self.gamma_ctrl.value_input,
            self.radius_ctrl.slider,
            self.radius_ctrl.value_input,
            self.amount_ctrl.slider,
            self.amount_ctrl.value_input,
            self.negative_checkbox,
            self.mirror_x_checkbox,
            self.mirror_y_checkbox,
            self.nearest_preview_checkbox,
            self.speed_input,
            self.min_power_input,
            self.max_power_input,
            self.overscan_auto_checkbox,
            self.overscan_override_input,
        ]
        previous_block_states = {
            widget: widget.blockSignals(True) for widget in widgets_to_block
        }

        try:
            grayscale_index = self.mode_combo.findData("Grayscale")
            if grayscale_index < 0:
                grayscale_index = 0
            self.mode_combo.setCurrentIndex(grayscale_index)
            self._last_mode_index = grayscale_index
            self._set_serpentine_scan(False)

            self.contrast_ctrl.slider.setValue(0)
            self.brightness_ctrl.slider.setValue(0)
            self.gamma_ctrl.slider.setValue(self.GAMMA_DEFAULT_SLIDER)
            self.radius_ctrl.slider.setValue(0)
            self.amount_ctrl.slider.setValue(0)

            self.contrast_ctrl._on_slider_changed(self.contrast_ctrl.slider.value())
            self.brightness_ctrl._on_slider_changed(self.brightness_ctrl.slider.value())
            self._on_gamma_slider_changed(self.gamma_ctrl.slider.value())
            self.radius_ctrl._on_slider_changed(self.radius_ctrl.slider.value())
            self.amount_ctrl._on_slider_changed(self.amount_ctrl.slider.value())
            self.negative_checkbox.setChecked(False)
            self.mirror_x_checkbox.setChecked(False)
            self.mirror_y_checkbox.setChecked(False)
            self.nearest_preview_checkbox.setChecked(False)

            self.speed_input.clear()
            self.min_power_input.clear()
            self.max_power_input.clear()
            self.overscan_auto_checkbox.setChecked(False)
            self.overscan_override_input.clear()
        finally:
            self._updating_ui = False
            for widget, was_blocked in previous_block_states.items():
                widget.blockSignals(was_blocked)

        self._update_overscan_label()

    def _on_base_rebuild_timeout(self):
        if self.final_engrave_image is None or not self.app:
            return

        self._rebuild_start_counter += 1
        trace_snapshot = (
            self._rebuild_request_trace[:]
            if self._rebuild_request_trace
            else ["unknown"]
        )
        self._rebuild_request_trace.clear()

        control = self._collect_base_control()
        kernel_result = self.app.rebuild_base_with_control(control)

        if not kernel_result.get("ok"):
            self._show_error(
                kernel_result.get(
                    "error",
                    self.tr(
                        "workspace.image.proc.base_rebuild_failed",
                        "Base rebuild failed",
                    ),
                )
            )
            return

        base_img = kernel_result.get("engrave_image")
        if base_img is None:
            return

        self.final_engrave_image = base_img
        self.processed_info = kernel_result.get("processed_info")
        qt_image = ImageQt(base_img)
        self.simulated_pixmap = QPixmap.fromImage(qt_image.copy())
        self._right_view_mode = RightViewMode.BASE
        self.show_normal_view()
        self._refresh_fullscreen_pixmap_if_open()
        if hasattr(self, "btn_save_image"):
            self.btn_save_image.setEnabled(True)

    def contrast_value(self) -> float:
        return self._contrast_from_slider(self.contrast_ctrl.value())

    def brightness_value(self) -> float:
        return self._brightness_from_slider(self.brightness_ctrl.value())

    def gamma_value(self) -> float:
        return self._clamp_gamma(self._gamma_from_slider(self.gamma_ctrl.value()))

    def radius_value(self) -> float:
        return float(self.radius_ctrl.value())

    def amount_value(self) -> float:
        return float(self.amount_ctrl.value())

    # ------------------------------------------------------------------
    # PROCESS RESULT DISPLAY
    # ------------------------------------------------------------------
    def _show_analysis(self, result: dict) -> None:
        """
        Kernel result megjelenítése.
        Itt NEM számolunk semmit — csak UI reakció.
        """
        if not result:
            self._show_error(self.tr("workspace.image.proc.empty_result", "Empty result"))
            return

        decision = result.get("decision")
        context = result.get("context")

        if decision == "INVALID_MACHINE":
            self._show_error(
                self.tr(
                    "workspace.image.proc.invalid_machine_profile",
                    "Invalid machine profile",
                )
            )
            return

        if decision == "INVALID_IMAGE":
            self._show_error(self.tr("workspace.image.proc.invalid_image", "Invalid image"))
            return

        if decision == "INVALID_SIZE":
            self._show_error(self.tr("workspace.image.proc.invalid_size", "Invalid size"))
            return

        # --- sikeres feldolgozás ---
        self.explanation_label.setText(
            self.tr("workspace.image.proc.base_image_generated", "BASE image generated")
        )

    def _show_error(self, message: str) -> None:
        """
        Egységes UI hiba megjelenítés
        """
        self.explanation_label.setText(
            self.tr("workspace.image.proc.error_prefix_template", "Error: {message}").format(
                message=message
            )
        )

    def _reset_processing_state(self) -> None:
        # A) View reset
        if isinstance(self._right_view, ZoomableLabel):
            self._right_view.reset_zoom()
        if isinstance(self._left_view, ZoomableLabel):
            self._left_view.reset_zoom()
        self._shared_view_zoom = 1.0
        self._shared_view_pan = QPointF(0.0, 0.0)

        # B) Crop reset
        self.crop_enabled = False
        self.crop_ratio = None
        self.crop_rect = None
        self.crop_valid = False
        self.crop_drag_mode = None
        self.crop_shape_mode = "square"
        self._crop_enabled = False
        self._crop_rect_img = None
        self.crop_checkbox.setChecked(False)
        self.crop_square_btn.setEnabled(False)
        self.crop_circle_btn.setEnabled(False)
        self.crop_square_btn.setChecked(True)
        self.crop_circle_btn.setChecked(False)
        self.crop_hint_label.hide()
        self._update_crop_shape_buttons_visual()

        # C) User size/DPI/overscan reset (machine profile untouched)
        self.engrave_width_input.clear()
        self.engrave_height_input.clear()
        self.engrave_dpi_input.setText("318")
        self.overscan_auto_checkbox.setChecked(False)
        self.overscan_override_input.clear()
        if hasattr(self, "mirror_x_checkbox"):
            self.mirror_x_checkbox.setChecked(False)
        if hasattr(self, "mirror_y_checkbox"):
            self.mirror_y_checkbox.setChecked(False)

        # D) Clear processed state
        self.processed_info = None
        self.final_engrave_image = None
        self.simulated_pixmap = None
        self._right_view_mode = RightViewMode.NONE
        if hasattr(self, "btn_save_gcode"):
            self.btn_save_gcode.setEnabled(False)
        if hasattr(self, "btn_save_image"):
            self.btn_save_image.setEnabled(False)

        # E) Cache invalidation
        try:
            from core.production.base_builder import _GEOMETRY_RESAMPLE_CACHE

            _GEOMETRY_RESAMPLE_CACHE.clear()
        except Exception:
            pass
        self._rebuild_request_trace.clear()
        self._base_rebuild_timer.stop()

        # F) UI refresh
        self.show_normal_view()
        self.raw_info = None
        self.raw_analysis = None
        self.info_label.setText(self.tr("laser.preview.no_image", "No image loaded"))
        self.explanation_label.setText("")
        self._update_overscan_label()
        self._update_process_button_state()

    def reset_editor_session(self) -> None:
        self._reset_processing_state()
        self.current_image_path = None
        self.image_path = None
        self.original_pixmap = None
        self.simulated_pixmap = None
        self.raw_info = None
        self.raw_analysis = None
        self.processed_info = None
        self.final_engrave_image = None
        self._right_view_mode = RightViewMode.NONE
        self._crop_rect_img = None
        self.crop_enabled = False
        self.crop_valid = False
        self.crop_rect = None
        self.crop_drag_mode = None
        self._left_shows_cropped_source = False
        self._clear_view()
        self._refresh_fullscreen_pixmap_if_open()
        self.info_label.setText(self.tr("laser.preview.no_image", "No image loaded"))
        self.explanation_label.setText("")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.reset_editor_session()
        super().closeEvent(event)

    def _on_load_image_clicked(self) -> None:
        self.load_image()

    def load_image(self):
        image_filter = self.tr("common.image_files", "Image files")
        all_files_filter = self.tr("common.all_files", "All files")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("common.select_image", "Select image"),
            "",
            f"{image_filter} (*.png *.jpg *.jpeg *.bmp);;{all_files_filter} (*)",
        )

        if not file_path:
            return
        self.import_image_from_path(file_path)

    def import_image_from_path(self, path: str) -> bool:
        file_path = str(path or "").strip()
        if not file_path:
            return False

        candidate = Path(file_path)
        if not candidate.exists() or not candidate.is_file():
            QMessageBox.warning(
                self,
                self.tr("common.error", "Error"),
                self.tr("common.file_not_found", "File not found: {path}").format(
                    path=file_path
                ),
            )
            return False

        file_path = str(candidate.resolve())
        # New image import must start from a clean image session state.
        # Keep machine configuration/mode untouched.
        self.reset_editor_session()

        loaded_image = QImage(file_path)
        if loaded_image.isNull():
            QMessageBox.warning(
                self,
                self.tr("common.error", "Error"),
                self.tr(
                    "workspace.image.proc.invalid_image_file",
                    "Invalid or unsupported image file: {path}",
                ).format(path=file_path),
            )
            return False

        self.current_image_path = file_path
        if not loaded_image.isGrayscale():
            loaded_image = loaded_image.convertToFormat(QImage.Format.Format_Grayscale8)
        self.original_pixmap = QPixmap.fromImage(loaded_image)
        self.simulated_pixmap = None
        self._right_view_mode = RightViewMode.NONE

        self.show_normal_view()

        # RAW-elemzés: kizárólag leíró képi metaadatok (mérettől és lézertértől független)
        from core.physics.dpi_estimator import estimate_raw_info
        from core.deterministic.image_analyzer import analyze_image

        self.raw_analysis = analyze_image(file_path)
        self.raw_info = estimate_raw_info(file_path)

        # Enforce RAW as single source of truth
        # Any later preview / pixmap resize MUST NOT overwrite or reinterpret this

        self._refresh_preview_render_mode()
        self._update_info_bar()
        self._update_crop_hint_position()
        self._update_process_button_state()

        # Notify the app about the loaded raw image
        if self.app:
            self.app.set_raw_image(file_path)

        self._reset_controls_to_defaults()

        print("RAW INFO:", self.raw_info)
        return True

    def _on_user_modul_text_changed(self, text: str) -> None:
        """
        UI-only handler.
        Gépelés közben nincs validálás és nincs kernel hívás.
        """
        self.engrave_user_modul_input.setStyleSheet("")

    def _current_gcode_control_profile(
        self,
        settings: dict | None = None,
        existing: dict | None = None,
    ) -> dict:
        overscan_override = self._parse_control_float(
            self.overscan_override_input.text()
        )
        profile = {
            "overscan_enabled": self.overscan_auto_checkbox.isChecked(),
            "overscan_mode": "manual" if overscan_override is not None else "auto",
            "overscan_mm": overscan_override,
            "overscan_safety_factor": 1.15,
        }

        if isinstance(existing, dict):
            for key in ("pwm_max", "pwm_min"):
                if key in existing:
                    profile[key] = existing[key]

        laser = settings.get("laser") if isinstance(settings, dict) else None
        if isinstance(laser, dict):
            profile["pwm_max"] = float(
                laser.get("pwm_max", profile.get("pwm_max", 1000.0)) or 1000.0
            )
            profile["pwm_min"] = float(
                laser.get("pwm_min", profile.get("pwm_min", 0.0)) or 0.0
            )
        else:
            profile["pwm_max"] = float(profile.get("pwm_max", 1000.0) or 1000.0)
            profile["pwm_min"] = float(profile.get("pwm_min", 0.0) or 0.0)

        return profile

    def _persist_current_machine_profile(self) -> None:
        if not isinstance(self.current_machine_profile, dict):
            return
        if not hasattr(self, "app") or not self.app:
            return
        if not hasattr(self.app, "config_manager"):
            return

        config = self.app.config_manager.load()
        profiles = config.get("profiles")
        if not isinstance(profiles, list):
            profiles = []
            config["profiles"] = profiles

        name = str(self.current_machine_profile.get("name", "")).strip()
        if not name:
            return

        for idx, profile in enumerate(profiles):
            if (
                isinstance(profile, dict)
                and str(profile.get("name", "")).strip() == name
            ):
                profiles[idx] = self.current_machine_profile
                break
        else:
            profiles.append(self.current_machine_profile)

        self.app.config_manager.save(config)

    def _on_save_config_clicked(self) -> None:
        from ui.dialogs.machine_profile_dialog import MachineProfileDialog
        from PyQt6.QtWidgets import QDialog

        prefill = {
            "name": self.current_profile_display.text(),
            "x": {
                "steps_per_mm": self.xrate_input.text(),
                "max_rate": self.xmaxrate_input.text(),
                "acceleration": self.xaccel_input.text(),
            },
            "y": {
                "steps_per_mm": self.yrate_input.text(),
                "max_rate": self.ymaxrate_input.text(),
                "acceleration": self.yaccel_input.text(),
            },
            "laser_module": self.engrave_user_modul_input.text(),
            "base_tuning": self._collect_base_control(),
            "gcode_control": self._current_gcode_control_profile(
                existing=(
                    (self.current_machine_profile or {}).get("gcode_control")
                    if isinstance(self.current_machine_profile, dict)
                    else None
                )
            ),
        }

        dialog = MachineProfileDialog(prefill, self)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            profile_data = dialog.get_profile_data()
            if profile_data and hasattr(self.app, "create_machine_profile"):
                self.app.create_machine_profile(profile_data)

    def _on_load_config_clicked(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        if not hasattr(self, "app") or not self.app:
            return

        config = self.app.config_manager.load()
        profiles = config.get("profiles", [])
        if not profiles:
            return

        names = [
            p.get(
                "name",
                self.tr(
                    "workspace.image.dialog.load_machine_profile.unnamed", "Unnamed"
                ),
            )
            for p in profiles
        ]

        name, ok = QInputDialog.getItem(
            self,
            self.tr(
                "workspace.image.dialog.load_machine_profile.title",
                "Load machine profile",
            ),
            self.tr(
                "workspace.image.dialog.load_machine_profile.prompt", "Select profile:"
            ),
            names,
            0,
            False,
        )

        if not ok or not name:
            return

        profile = next((p for p in profiles if p.get("name") == name), None)
        if not profile:
            return

        self._apply_loaded_machine_profile(profile)

    def _apply_loaded_machine_profile(self, profile: dict):
        """
        Config profile betöltése = ugyanaz mint GRBL load.
        UI kitölt + MAG értesítés.
        """

        self._updating_ui = True
        try:
            # --- UI kitöltés ---
            self.current_profile_display.setText(profile.get("name", ""))
            x_profile = profile.get("x", {})
            y_profile = profile.get("y", {})
            self.xrate_input.setText(str(x_profile.get("steps_per_mm", "")))
            self.xmaxrate_input.setText(str(x_profile.get("max_rate", "")))
            self.xaccel_input.setText(str(x_profile.get("acceleration", "")))
            self.yrate_input.setText(str(y_profile.get("steps_per_mm", "")))
            self.ymaxrate_input.setText(str(y_profile.get("max_rate", "")))
            self.yaccel_input.setText(str(y_profile.get("acceleration", "")))
            self.engrave_user_modul_input.setText(str(profile.get("laser_module", "")))

            base_tuning = profile.get("base_tuning", {})
            if isinstance(base_tuning, dict):
                mode_value = base_tuning.get("mode", "Grayscale")
                idx = self.mode_combo.findData(mode_value)
                if idx < 0:
                    idx = self.mode_combo.findText(str(mode_value))
                if idx >= 0:
                    self.mode_combo.setCurrentIndex(idx)
                    self._last_mode_index = idx
                self._set_serpentine_scan(bool(base_tuning.get("serpentine_scan", False)))

                self.contrast_ctrl.slider.setValue(
                    self._slider_from_contrast(
                        float(base_tuning.get("contrast", 0.0) or 0.0)
                    )
                )
                self.brightness_ctrl.slider.setValue(
                    self._slider_from_brightness(
                        float(base_tuning.get("brightness", 0.0) or 0.0)
                    )
                )
                self.gamma_ctrl.slider.setValue(
                    self._slider_from_gamma(float(base_tuning.get("gamma", 1.0)))
                )
                radius_value = float(base_tuning.get("radius", 0) or 0)
                self.radius_ctrl.slider.setValue(int(round(radius_value)))
                self.amount_ctrl.slider.setValue(
                    int(base_tuning.get("amount", 0) or 0)
                )
                self.negative_checkbox.setChecked(
                    bool(base_tuning.get("negative", False))
                )

            gcode_control = profile.get("gcode_control", {})
            overscan_enabled = bool(gcode_control.get("overscan_enabled", False))
            overscan_mode = gcode_control.get("overscan_mode", "auto")
            overscan_mm = gcode_control.get("overscan_mm")

            self.overscan_auto_checkbox.setChecked(overscan_enabled)
            if overscan_mode == "manual" and overscan_mm is not None:
                self.overscan_override_input.setText(str(overscan_mm))
            else:
                self.overscan_override_input.clear()
        finally:
            self._updating_ui = False
        self._update_overscan_label()

        # --- kernel értesítés ---
        self.current_machine_profile = profile

        # ---- invalidate previous processing ----
        self.processed_info = None
        if hasattr(self, "btn_save_image"):
            self.btn_save_image.setEnabled(False)
        if hasattr(self, "btn_save_gcode"):
            self._update_gcode_button_state()
        self.simulated_pixmap = None
        self._right_view_mode = RightViewMode.NONE
        self._refresh_preview_render_mode()
        self._update_info_bar()
        self._update_crop_hint_position()
        self._update_process_button_state()
        self.show_normal_view()

    def _on_port_load_text_changed(self, text: str) -> None:
        self.engrave_port_load_input.setStyleSheet("")

    def _on_scan_axis_changed(self, axis: str) -> None:
        self.engrave_axis = axis

    def _refresh_ports(self):
        self.engrave_port_load_input.clear()
        for p in list_ports.comports():
            self.engrave_port_load_input.addItem(p.device)

    def commit_engrave_port_load(self) -> None:
        port = self.engrave_port_load_input.currentText().strip()
        if not port:
            return

        from core.infrastructure.grbl_reader import GrblReader

        try:
            settings = GrblReader.read_settings(port)
        except Exception as e:
            if hasattr(self, "grbl_status_label"):
                self.grbl_status_dot.setStyleSheet(
                    "background:#c0392b; border-radius:5px;"
                )
                self.grbl_status_label.setText(str(e))
            return

        if not settings:
            if hasattr(self, "grbl_status_label"):
                self.grbl_status_dot.setStyleSheet(
                    "background:#c0392b; border-radius:5px;"
                )
                self.grbl_status_label.setText(
                    self.tr(
                        "workspace.image.grbl.incomplete_settings",
                        "Incomplete GRBL settings",
                    )
                )
            return

        self.xrate_input.setText(str(settings["x"]["steps_per_mm"]))
        self.xmaxrate_input.setText(str(settings["x"]["max_rate"]))
        self.xaccel_input.setText(str(settings["x"]["acceleration"]))
        self.yrate_input.setText(str(settings["y"]["steps_per_mm"]))
        self.ymaxrate_input.setText(str(settings["y"]["max_rate"]))
        self.yaccel_input.setText(str(settings["y"]["acceleration"]))
        self.current_profile_display.setText(
            self.tr("workspace.image.grbl.port_display", "GRBL:{port}").format(
                port=port
            )
        )

        if hasattr(self, "grbl_status_label"):
            self.grbl_status_dot.setStyleSheet("background:#2ecc71; border-radius:5px;")
            self.grbl_status_label.setText(
                self.tr("workspace.image.grbl.profile_read", "Profile read ({port})").format(
                    port=port
                )
            )

            existing_gcode = {}
            if isinstance(self.current_machine_profile, dict):
                current_gcode = self.current_machine_profile.get("gcode_control")
                if isinstance(current_gcode, dict):
                    existing_gcode = current_gcode

            self.current_machine_profile = {
                "name": self.tr("workspace.image.grbl.port_display", "GRBL:{port}").format(
                    port=port
                ),
                "x": {
                    "steps_per_mm": settings["x"]["steps_per_mm"],
                    "max_rate": settings["x"]["max_rate"],
                    "acceleration": settings["x"]["acceleration"],
                },
                "y": {
                    "steps_per_mm": settings["y"]["steps_per_mm"],
                    "max_rate": settings["y"]["max_rate"],
                    "acceleration": settings["y"]["acceleration"],
                },
                "gcode_control": self._current_gcode_control_profile(
                    settings=settings, existing=existing_gcode
                ),
            }
            self._persist_current_machine_profile()
            self._update_overscan_label()

    def _read_grbl_worker(self, port):
        try:
            settings = GrblReader.read_settings(port)
        except Exception as e:
            QMetaObject.invokeMethod(
                self, "_grbl_failed", Qt.ConnectionType.QueuedConnection, port, str(e)
            )
            return

        if not settings:
            QMetaObject.invokeMethod(
                self,
                "_grbl_failed",
                Qt.ConnectionType.QueuedConnection,
                port,
                self.tr(
                    "workspace.image.grbl.incomplete_settings",
                    "Incomplete GRBL settings",
                ),
            )
            return

        QMetaObject.invokeMethod(
            self,
            "_apply_grbl_profile",
            Qt.ConnectionType.QueuedConnection,
            port,
            settings,
        )

    def _apply_grbl_profile(self, port, settings):
        self.xrate_input.setText(str(settings["x"]["steps_per_mm"]))
        self.xmaxrate_input.setText(str(settings["x"]["max_rate"]))
        self.xaccel_input.setText(str(settings["x"]["acceleration"]))
        self.yrate_input.setText(str(settings["y"]["steps_per_mm"]))
        self.ymaxrate_input.setText(str(settings["y"]["max_rate"]))
        self.yaccel_input.setText(str(settings["y"]["acceleration"]))
        self.current_profile_display.setText(port)

        self.grbl_status_dot.setStyleSheet("background:#2ecc71; border-radius:5px;")
        self.grbl_status_label.setText(
            self.tr("workspace.image.grbl.profile_loaded", "Profile loaded ({port})").format(
                port=port
            )
        )

        existing_gcode = {}
        if isinstance(self.current_machine_profile, dict):
            current_gcode = self.current_machine_profile.get("gcode_control")
            if isinstance(current_gcode, dict):
                existing_gcode = current_gcode

        self.current_machine_profile = {
            "name": self.tr("workspace.image.grbl.port_display", "GRBL:{port}").format(
                port=port
            ),
            "x": {
                "steps_per_mm": settings["x"]["steps_per_mm"],
                "max_rate": settings["x"]["max_rate"],
                "acceleration": settings["x"]["acceleration"],
            },
            "y": {
                "steps_per_mm": settings["y"]["steps_per_mm"],
                "max_rate": settings["y"]["max_rate"],
                "acceleration": settings["y"]["acceleration"],
            },
            "gcode_control": self._current_gcode_control_profile(
                settings=settings, existing=existing_gcode
            ),
        }
        self._persist_current_machine_profile()
        self._update_overscan_label()
        # ---- invalidate previous processing ----
        self.processed_info = None
        if hasattr(self, "btn_save_image"):
            self.btn_save_image.setEnabled(False)
        if hasattr(self, "btn_save_gcode"):
            self._update_gcode_button_state()
        self.simulated_pixmap = None
        self._right_view_mode = RightViewMode.NONE
        self._refresh_preview_render_mode()
        self._update_info_bar()
        self._update_crop_hint_position()
        self._update_process_button_state()
        self.show_normal_view()

    def _grbl_failed(self, port, message):
        self.grbl_status_dot.setStyleSheet("background:#c0392b; border-radius:5px;")
        self.grbl_status_label.setText(
            self.tr("workspace.image.grbl.port_message", "{port}: {message}").format(
                port=port, message=message
            )
        )

    # ---------------------------------------------------------
    # SERIAL PORT ENUMERATION (UI HELPER ONLY)
    # ---------------------------------------------------------
    def _refresh_serial_ports(self) -> None:
        current = self.engrave_port_load_input.currentText()
        self.engrave_port_load_input.blockSignals(True)
        self.engrave_port_load_input.clear()

        for port in list_ports.comports():
            self.engrave_port_load_input.addItem(port.device)

        # keep previous text if still exists
        index = self.engrave_port_load_input.findText(current)
        if index >= 0:
            self.engrave_port_load_input.setCurrentIndex(index)
        else:
            self.engrave_port_load_input.setEditText(current)

        self.engrave_port_load_input.blockSignals(False)

    def _parse_mm_text(self, text: str) -> float | None:
        try:
            return float(text.lower().replace("mm", "").replace(",", ".").strip())
        except Exception:
            return None

    def _get_active_source_aspect(self) -> float | None:
        resolution = None
        if isinstance(self.raw_info, dict):
            resolution = self.raw_info.get("resolution_px")

        if isinstance(resolution, (tuple, list)) and len(resolution) == 2:
            src_w_px = float(resolution[0])
            src_h_px = float(resolution[1])
        elif self.original_pixmap is not None:
            src_w_px = float(self.original_pixmap.width())
            src_h_px = float(self.original_pixmap.height())
        else:
            return None

        if src_h_px <= 0:
            return None
        return src_w_px / src_h_px

    def _image_size_px(self) -> tuple[int, int] | None:
        resolution = None
        if isinstance(self.raw_info, dict):
            resolution = self.raw_info.get("resolution_px")
        if isinstance(resolution, (tuple, list)) and len(resolution) == 2:
            return int(resolution[0]), int(resolution[1])
        if self.original_pixmap is not None:
            return int(self.original_pixmap.width()), int(self.original_pixmap.height())
        return None

    def _normalized_crop_box(self) -> tuple[int, int, int, int] | None:
        if not (self.crop_enabled and self.crop_valid and isinstance(self.crop_rect, QRectF)):
            return None
        size_px = self._image_size_px()
        if not size_px:
            return None

        img_w, img_h = size_px
        return normalize_raw_crop_box(
            (
                float(self.crop_rect.left()),
                float(self.crop_rect.top()),
                float(self.crop_rect.right()),
                float(self.crop_rect.bottom()),
            ),
            img_w,
            img_h,
        )

    def _cropped_source_pixmap_for_left(self) -> QPixmap | None:
        crop_box = self._normalized_crop_box()
        if crop_box is None or not self.current_image_path:
            return None

        try:
            img = Image.open(self.current_image_path).convert("L")
            img, _ = apply_raw_crop(img, crop_box, self.crop_shape_mode)
            qt = ImageQt(img)
            return QPixmap.fromImage(qt.copy())
        except Exception:
            return None

    def _left_preview_source_pixmap(self) -> tuple[QPixmap | None, bool]:
        left_pixmap = self.original_pixmap
        if self.crop_enabled:
            cropped = self._cropped_source_pixmap_for_left()
            if cropped is not None:
                return cropped, True
        return left_pixmap, False

    def _refresh_left_preview_source_if_open(self) -> None:
        if not isinstance(self._left_view, ZoomableLabel):
            return
        left_pixmap, left_is_cropped = self._left_preview_source_pixmap()
        if left_pixmap is None:
            return
        if self._left_view.original_pixmap is left_pixmap and (
            self._left_shows_cropped_source == left_is_cropped
        ):
            return
        zoom, pan = self._left_view.get_view_state()
        self._left_view._skip_auto_reset = True
        self._left_view.setPixmap(left_pixmap)
        if hasattr(self._left_view, "_skip_auto_reset"):
            delattr(self._left_view, "_skip_auto_reset")
        self._left_shows_cropped_source = left_is_cropped
        self._left_view.set_view_state(zoom, pan, repaint=False)
        self._left_view.update()

    def _center_square_crop_rect(self) -> QRectF | None:
        size_px = self._image_size_px()
        if not size_px:
            return None
        img_w, img_h = size_px
        side = float(min(img_w, img_h))
        left = (img_w - side) / 2.0
        top = (img_h - side) / 2.0
        return QRectF(left, top, side, side)

    def _center_ratio_crop_rect(self, ratio: float) -> QRectF | None:
        size_px = self._image_size_px()
        if not size_px or ratio <= 0:
            return None
        img_w, img_h = size_px
        image_ratio = float(img_w) / float(img_h)
        if ratio >= image_ratio:
            width = float(img_w)
            height = width / ratio
        else:
            height = float(img_h)
            width = height * ratio
        left = (img_w - width) / 2.0
        top = (img_h - height) / 2.0
        return QRectF(left, top, width, height)

    def _set_crop_default_square(self) -> None:
        self.crop_ratio = None
        self.crop_rect = None
        self.crop_valid = False

    def _get_resize_geometry(self, mode: str) -> tuple[QPointF, float, float] | None:
        if not isinstance(self._original_crop_rect, QRectF):
            return None
        if mode == "resize_br":
            return self._original_crop_rect.topLeft(), 1.0, 1.0
        if mode == "resize_tr":
            return self._original_crop_rect.bottomLeft(), 1.0, -1.0
        if mode == "resize_bl":
            return self._original_crop_rect.topRight(), -1.0, 1.0
        if mode == "resize_tl":
            return self._original_crop_rect.bottomRight(), -1.0, -1.0
        if mode == "resize_l":
            return self._original_crop_rect.topRight(), -1.0, 1.0
        if mode == "resize_r":
            return self._original_crop_rect.topLeft(), 1.0, 1.0
        if mode == "resize_t":
            return self._original_crop_rect.bottomLeft(), 1.0, -1.0
        if mode == "resize_b":
            return self._original_crop_rect.topLeft(), 1.0, 1.0
        return None

    def _update_crop_hint_position(self) -> None:
        if not hasattr(self, "crop_hint_label"):
            return
        self.crop_hint_label.adjustSize()
        x = (self.view_host.width() - self.crop_hint_label.width()) // 2
        y = (self.view_host.height() - self.crop_hint_label.height()) // 2
        self.crop_hint_label.move(max(0, x), max(0, y))

    def _update_process_button_state(self) -> None:
        if not self.btn_process:
            return
        if self.crop_enabled and not self.crop_valid:
            self.btn_process.setEnabled(False)
            return
        self.btn_process.setEnabled(True)

    def _translate_crop_rect(self, delta: QPointF) -> None:
        if not isinstance(self.crop_rect, QRectF):
            return
        size_px = self._image_size_px()
        if not size_px:
            return
        img_w, img_h = size_px
        rect = QRectF(self.crop_rect)
        rect.translate(delta)
        if rect.left() < 0:
            rect.moveLeft(0)
        if rect.top() < 0:
            rect.moveTop(0)
        if rect.right() > img_w:
            rect.moveRight(float(img_w))
        if rect.bottom() > img_h:
            rect.moveBottom(float(img_h))
        self.crop_rect = rect

    def _detect_crop_handle(self, pos: QPoint | QPointF):
        if not isinstance(self.crop_rect, QRectF):
            return None

        view = None
        if isinstance(self._left_view, ZoomableLabel):
            view = self._left_view
        elif (
            self.current_view is not None
            and hasattr(self.current_view, "image_to_view")
            and hasattr(self.current_view, "view_to_image")
        ):
            view = self.current_view

        if view is None:
            return None

        if isinstance(pos, QPoint):
            pos_view = QPointF(float(pos.x()), float(pos.y()))
        else:
            pos_view = QPointF(pos)

        r = self.crop_rect
        tl = view.image_to_view(r.left(), r.top())
        br = view.image_to_view(r.right(), r.bottom())
        crop_view = QRectF(QPointF(tl), QPointF(br)).normalized()

        handle_tol = CropOverlayLabel.HANDLE_HIT_TOLERANCE_VIEW_PX
        corners = {
            "resize_tl": crop_view.topLeft(),
            "resize_tr": crop_view.topRight(),
            "resize_bl": crop_view.bottomLeft(),
            "resize_br": crop_view.bottomRight(),
        }
        for name, corner in corners.items():
            dx = pos_view.x() - corner.x()
            dy = pos_view.y() - corner.y()
            if (dx * dx + dy * dy) <= (handle_tol * handle_tol):
                return name

        if crop_view.adjusted(
            -handle_tol, -handle_tol, handle_tol, handle_tol
        ).contains(pos_view):
            if abs(pos_view.x() - crop_view.left()) <= handle_tol:
                return "resize_l"
            if abs(pos_view.x() - crop_view.right()) <= handle_tol:
                return "resize_r"
            if abs(pos_view.y() - crop_view.top()) <= handle_tol:
                return "resize_t"
            if abs(pos_view.y() - crop_view.bottom()) <= handle_tol:
                return "resize_b"

        if self.crop_shape_mode == "circle":
            center = crop_view.center()
            rx = crop_view.width() / 2.0
            ry = crop_view.height() / 2.0
            if rx > 0 and ry > 0:
                nx = (pos_view.x() - center.x()) / rx
                ny = (pos_view.y() - center.y()) / ry
                if (nx * nx + ny * ny) <= 1.0:
                    return "move"
        elif crop_view.contains(pos_view):
            return "move"
        return None

    def _update_crop_drag(self, image_pos: QPointF) -> None:
        if not self.crop_drag_mode or not self.crop_enabled:
            return
        if not isinstance(self._original_crop_rect, QRectF):
            return

        dx = image_pos.x() - self._drag_start_pos.x()
        dy = image_pos.y() - self._drag_start_pos.y()
        r = QRectF(self._original_crop_rect)

        if self.crop_drag_mode == "move":
            r.translate(dx, dy)
        else:
            ratio = self.crop_ratio or 1.0
            resize_geometry = self._get_resize_geometry(self.crop_drag_mode)
            if resize_geometry is None:
                return

            size_px = self._image_size_px()
            if not size_px:
                return
            img_w, img_h = float(size_px[0]), float(size_px[1])

            anchor, x_dir, y_dir = resize_geometry
            raw_w = (image_pos.x() - anchor.x()) * x_dir
            new_w = max(self.crop_min_size_px, raw_w)

            max_w_by_x = (img_w - anchor.x()) if x_dir > 0 else anchor.x()
            max_h_by_y = (img_h - anchor.y()) if y_dir > 0 else anchor.y()
            max_w_by_y = max_h_by_y * ratio
            max_w = max(1.0, min(max_w_by_x, max_w_by_y))
            new_w = min(new_w, max_w)

            new_h = new_w / ratio
            left = anchor.x() if x_dir > 0 else anchor.x() - new_w
            top = anchor.y() if y_dir > 0 else anchor.y() - new_h
            r = QRectF(left, top, new_w, new_h)

        size_px = self._image_size_px()
        if not size_px:
            return
        img_w, img_h = size_px
        if r.left() < 0:
            r.moveLeft(0)
        if r.top() < 0:
            r.moveTop(0)
        if r.right() > img_w:
            r.moveRight(float(img_w))
        if r.bottom() > img_h:
            r.moveBottom(float(img_h))

        self.crop_rect = r

    def _update_crop_from_size_fields(self) -> None:
        if not self.crop_enabled:
            return
        width_mm = self._parse_mm_text(self.engrave_width_input.text())
        height_mm = self._parse_mm_text(self.engrave_height_input.text())

        if self.crop_shape_mode == "circle":
            height_mm = width_mm
            self.crop_ratio = 1.0

        if (
            width_mm is not None
            and height_mm is not None
            and width_mm > 0
            and height_mm > 0
        ):
            # Always recalculate from the current fields; keeping the previous
            # stored ratio blocks Enter-based updates until crop gets toggled.
            ratio = width_mm / height_mm
            self.crop_ratio = ratio
            self.crop_rect = self._center_ratio_crop_rect(ratio)
            self.crop_valid = self.crop_rect is not None
            if self.crop_valid:
                self.crop_hint_label.hide()
            else:
                self.crop_hint_label.show()
        else:
            self._set_crop_default_square()
            self.crop_hint_label.show()

        self._crop_rect_img = None
        self._update_process_button_state()
        if isinstance(self._left_view, ZoomableLabel):
            self._left_view.update()
        self._update_crop_hint_position()

    def _on_width_mm_changed(self, text: str) -> None:
        if self._size_field_sync_lock:
            return
        self._last_size_field_edited = "width"
        if self.crop_enabled:
            if self.crop_shape_mode == "circle":
                self._size_field_sync_lock = True
                try:
                    self.engrave_height_input.setText(text)
                finally:
                    self._size_field_sync_lock = False
            # Live crop update on field change (UX improvement)
            self._update_crop_from_size_fields_live()
            return
        width_mm = self._parse_mm_text(text)
        aspect = self._get_active_source_aspect()
        if width_mm is None or aspect is None:
            return

        self._size_field_sync_lock = True
        try:
            self.engrave_height_input.setText(
                f"{(width_mm / aspect):.3f}".rstrip("0").rstrip(".")
            )
        finally:
            self._size_field_sync_lock = False

    def _on_height_mm_changed(self, text: str) -> None:
        if self._size_field_sync_lock:
            return
        self._last_size_field_edited = "height"
        if self.crop_enabled:
            if self.crop_shape_mode == "circle":
                return
            # Live crop update on field change (UX improvement)
            self._update_crop_from_size_fields_live()
            return
        height_mm = self._parse_mm_text(text)
        aspect = self._get_active_source_aspect()
        if height_mm is None or aspect is None:
            return

        self._size_field_sync_lock = True
        try:
            self.engrave_width_input.setText(
                f"{(height_mm * aspect):.3f}".rstrip("0").rstrip(".")
            )
        finally:
            self._size_field_sync_lock = False

    def _on_width_mm_finished(self) -> None:
        if not self.crop_enabled:
            return
        if self.crop_shape_mode == "circle":
            text = self.engrave_width_input.text()
            self._size_field_sync_lock = True
            try:
                self.engrave_height_input.setText(text)
            finally:
                self._size_field_sync_lock = False
        self._update_crop_from_size_fields()

    def _on_height_mm_finished(self) -> None:
        if not self.crop_enabled:
            return
        if self.crop_shape_mode == "circle":
            return
        self._update_crop_from_size_fields()

    def _update_crop_from_size_fields_live(self) -> None:
        width_mm = self._parse_mm_text(self.engrave_width_input.text())
        height_mm = self._parse_mm_text(self.engrave_height_input.text())
        if self.crop_shape_mode == "circle":
            height_mm = width_mm

        if width_mm is None or height_mm is None or width_mm <= 0 or height_mm <= 0:
            return
        self._update_crop_from_size_fields()

    def _on_crop_toggled(self, checked: bool) -> None:
        self.crop_enabled = bool(checked)
        self._crop_enabled = self.crop_enabled
        self.crop_square_btn.setEnabled(checked)
        self.crop_circle_btn.setEnabled(checked)
        if checked:
            self.crop_shape_mode = "square"
            self.engrave_height_input.setEnabled(True)
            self._set_crop_default_square()
            self.crop_hint_label.show()
        else:
            self.crop_ratio = None
            self.crop_rect = None
            self.crop_valid = False
            self.crop_drag_mode = None
            self.engrave_height_input.setEnabled(True)
            self._crop_rect_img = None
            self.crop_hint_label.hide()
        self._update_crop_shape_buttons_visual()
        self._update_process_button_state()
        if isinstance(self._left_view, ZoomableLabel):
            self._left_view.update()
        print(f"Crop enabled: {self.crop_enabled}")

    def _on_crop_square_clicked(self) -> None:
        if not self.crop_enabled:
            return
        if self.crop_shape_mode != "square":
            self.crop_shape_mode = "square"
            self.engrave_height_input.setEnabled(True)
            print(f"Crop shape: {self.crop_shape_mode}")
            self._update_crop_from_size_fields()
        self._update_crop_shape_buttons_visual()

    def _on_crop_circle_clicked(self) -> None:
        if not self.crop_enabled:
            return
        if self.crop_shape_mode != "circle":
            self.crop_shape_mode = "circle"
            print(f"Crop shape: {self.crop_shape_mode}")
        self.engrave_height_input.setEnabled(False)
        self.engrave_height_input.setText(self.engrave_width_input.text())
        self.crop_ratio = 1.0

        # Keep current crop geometry when switching to circle so resize can work
        # in both directions. Recomputing from size fields would recreate the
        # maximum centered square (ratio-only path), leaving only shrink room.
        if self.crop_valid and isinstance(self.crop_rect, QRectF):
            current = QRectF(self.crop_rect)
            side = max(1.0, min(current.width(), current.height()))
            cx = current.center().x()
            cy = current.center().y()
            r = QRectF(cx - (side / 2.0), cy - (side / 2.0), side, side)

            size_px = self._image_size_px()
            if size_px:
                img_w, img_h = float(size_px[0]), float(size_px[1])
                if r.left() < 0:
                    r.moveLeft(0)
                if r.top() < 0:
                    r.moveTop(0)
                if r.right() > img_w:
                    r.moveRight(img_w)
                if r.bottom() > img_h:
                    r.moveBottom(img_h)

            self.crop_rect = r
            self.crop_valid = True
            self._crop_rect_img = None
            self._update_process_button_state()
            if isinstance(self._left_view, ZoomableLabel):
                self._left_view.update()
        else:
            self._update_crop_from_size_fields()
        self._update_crop_shape_buttons_visual()

    def _update_crop_shape_buttons_visual(self) -> None:
        square_active = self.crop_enabled and self.crop_shape_mode == "square"
        circle_active = self.crop_enabled and self.crop_shape_mode == "circle"

        self.crop_square_btn.setChecked(square_active)
        self.crop_circle_btn.setChecked(circle_active)

        self.crop_square_btn.setProperty("active", square_active)
        self.crop_circle_btn.setProperty("active", circle_active)

        base_style = """
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #b0b0b0;
            border-radius: 3px;
        }
        QPushButton:disabled {
            background-color: #eeeeee;
            color: #777777;
        }
        QPushButton[active=\"true\"] {
            background-color: #c7f0cf;
            border: 1px solid #2e8b57;
            font-weight: 600;
        }
        """
        self.crop_square_btn.setStyleSheet(base_style)
        self.crop_circle_btn.setStyleSheet(base_style)

    # NÉZETEK
    def toggle_preview_fullscreen(self):
        if self._preview_fullscreen:
            self._exit_preview_fullscreen()
        else:
            self._enter_preview_fullscreen()

    def open_right_preview_fullscreen(self):
        if not isinstance(self._right_view, ZoomableLabel):
            return

        source_pixmap = self.simulated_pixmap
        if source_pixmap is None:
            source_pixmap = self._right_view.original_pixmap
        if source_pixmap is None:
            return

        if self._fs_dialog is not None and self._fs_dialog.isVisible():
            self._fs_dialog.close()
            return

        dialog = QDialog(self)
        dialog.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)

        fs_view = ZoomableLabel(interactive=True)
        self._fs_show_original = False
        fs_view._use_world = self._right_view._use_world
        fs_view.setPixmap(source_pixmap)
        fs_view.set_nearest_preview(self._right_view._nearest_preview)

        if fs_view._use_world:
            scale, offset = self._right_view.get_transform()
            fs_view.set_transform(scale, offset)
        else:
            zoom, pan_px = self._right_view.get_view_state()
            fs_view.set_view_state(zoom, QPointF(pan_px), repaint=False)

        def _sync_right_view(zoom_value: float, pan_x: float, pan_y: float):
            if isinstance(self._right_view, ZoomableLabel):
                self._right_view.set_view_state(
                    zoom_value,
                    QPointF(pan_x, pan_y),
                    repaint=True,
                )

        fs_view.viewChanged.connect(_sync_right_view)
        dialog_layout.addWidget(fs_view)

        controls = self._controls_host
        self._fs_controls_old_parent = controls.parentWidget()
        self._fs_controls_old_layout = (
            self._fs_controls_old_parent.layout()
            if self._fs_controls_old_parent is not None
            else None
        )
        self._fs_controls_old_index = (
            self._fs_controls_old_layout.indexOf(controls)
            if self._fs_controls_old_layout is not None
            else -1
        )
        if self._fs_controls_old_layout is not None:
            self._fs_controls_old_layout.removeWidget(controls)
        controls.setParent(dialog)
        controls.installEventFilter(self)
        controls.raise_()
        controls.show()

        def _position_controls_overlay():
            margin = 16
            controls.adjustSize()
            x = max(margin, dialog.width() - controls.width() - margin)
            y = max(margin, dialog.height() - controls.height() - margin)
            controls.move(x, y)

        QTimer.singleShot(0, _position_controls_overlay)

        def _finalize_fullscreen(*_args):
            if isinstance(self._right_view, ZoomableLabel) and isinstance(
                self._fs_view, ZoomableLabel
            ):
                if self._fs_view._use_world:
                    final_scale, final_offset = self._fs_view.get_transform()
                    self._right_view.set_transform(final_scale, final_offset)
                else:
                    final_zoom, final_pan = self._fs_view.get_view_state()
                    self._right_view.set_view_state(
                        final_zoom,
                        QPointF(final_pan),
                        repaint=True,
                    )
            controls.removeEventFilter(self)
            if self._fs_controls_old_parent is not None:
                controls.setParent(self._fs_controls_old_parent)
                if self._fs_controls_old_layout is not None:
                    insert_index = self._fs_controls_old_index
                    if (
                        isinstance(insert_index, int)
                        and insert_index >= 0
                        and hasattr(self._fs_controls_old_layout, "insertWidget")
                    ):
                        self._fs_controls_old_layout.insertWidget(insert_index, controls)
                    elif hasattr(self._fs_controls_old_layout, "addWidget"):
                        self._fs_controls_old_layout.addWidget(controls)
            controls.show()
            self._fs_controls_old_parent = None
            self._fs_controls_old_layout = None
            self._fs_controls_old_index = None
            self._fs_drag_active = False
            self._fs_drag_offset = None
            self._fs_dialog = None
            self._fs_view = None

        def _dialog_key_press(event):
            if event.key() == Qt.Key.Key_Escape:
                dialog.close()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Space:
                self._fs_show_original = not self._fs_show_original

                if self._fs_show_original:
                    pixmap, _ = self._left_preview_source_pixmap()
                else:
                    pixmap = self.simulated_pixmap

                if pixmap is None:
                    event.accept()
                    return

                if fs_view._use_world:
                    scale, offset = fs_view.get_transform()
                else:
                    zoom, pan = fs_view.get_view_state()

                fs_view._skip_auto_reset = True
                fs_view.setPixmap(pixmap)
                if hasattr(fs_view, "_skip_auto_reset"):
                    delattr(fs_view, "_skip_auto_reset")

                if fs_view._use_world:
                    fs_view.set_transform(scale, offset)
                else:
                    fs_view.set_view_state(zoom, pan, repaint=False)
                fs_view.update()
                event.accept()
                return
            QDialog.keyPressEvent(dialog, event)

        dialog.keyPressEvent = _dialog_key_press
        dialog.finished.connect(_finalize_fullscreen)

        self._fs_dialog = dialog
        self._fs_view = fs_view
        self._fs_dialog.showFullScreen()

    def eventFilter(self, watched, event):
        if watched is self._controls_host and self._fs_dialog is not None:
            if event.type() == QEvent.Type.MouseButtonPress and (
                event.button() == Qt.MouseButton.RightButton
            ):
                self._fs_drag_active = True
                self._fs_drag_offset = (
                    event.globalPosition().toPoint()
                    - self._controls_host.mapToGlobal(QPoint(0, 0))
                )
                return True
            if event.type() == QEvent.Type.MouseMove and self._fs_drag_active:
                next_global = event.globalPosition().toPoint() - self._fs_drag_offset
                next_pos = self._fs_dialog.mapFromGlobal(next_global)
                self._controls_host.move(next_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and (
                event.button() == Qt.MouseButton.RightButton
            ):
                self._fs_drag_active = False
                self._fs_drag_offset = None
                return True
        return super().eventFilter(watched, event)

    def _refresh_fullscreen_pixmap_if_open(self):
        if self._fs_dialog is None or not self._fs_dialog.isVisible():
            return
        if not isinstance(self._fs_view, ZoomableLabel):
            return

        if self._fs_show_original:
            source_pixmap, _ = self._left_preview_source_pixmap()
        else:
            source_pixmap = self.simulated_pixmap
        if source_pixmap is None:
            source_pixmap = self._fs_view.original_pixmap
        if source_pixmap is None:
            return

        if self._fs_view._use_world:
            scale, offset = self._fs_view.get_transform()
        else:
            zoom, pan = self._fs_view.get_view_state()

        self._fs_view._skip_auto_reset = True
        self._fs_view.setPixmap(source_pixmap)
        if hasattr(self._fs_view, "_skip_auto_reset"):
            delattr(self._fs_view, "_skip_auto_reset")

        if self._fs_view._use_world:
            self._fs_view.set_transform(scale, offset)
        else:
            self._fs_view.set_view_state(zoom, pan, repaint=False)
        self._fs_view.set_nearest_preview(self._right_view._nearest_preview)
        self._fs_view.update()

    def _enter_preview_fullscreen(self):
        self._refresh_left_preview_source_if_open()
        self._preview_was_maximized = self.isMaximized()
        self.showFullScreen()
        for w in self._toolbar_panels:
            w.setVisible(False)
        self.info_label.setVisible(False)
        self.explanation_label.setVisible(False)
        self._preview_fullscreen = True

    def _exit_preview_fullscreen(self):
        self.showNormal()
        if self._preview_was_maximized:
            self.showMaximized()
        for w in self._toolbar_panels:
            w.setVisible(True)
        self.info_label.setVisible(True)
        self.explanation_label.setVisible(True)
        self._preview_fullscreen = False

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Escape
            and self._preview_fullscreen
        ):
            self._exit_preview_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def show_normal_view(self):
        if not self.original_pixmap:
            return

        if isinstance(self._right_view, ZoomableLabel):
            self._shared_view_zoom, self._shared_view_pan = (
                self._right_view.get_view_state()
            )

        self._clear_view()

        container = QWidget(self.view_host)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.UI_GAP)

        left = CropOverlayLabel(self, interactive=False)
        left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        left_pixmap, left_is_cropped = self._left_preview_source_pixmap()
        self._left_shows_cropped_source = left_is_cropped
        left.setPixmap(left_pixmap)
        left._external_transform_active = False
        self._left_view = left

        if self._right_view_mode == RightViewMode.NONE:
            right = QLabel(self.tr("laser.preview.no_preview", "No preview available"))
            right.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._right_view = None

        elif self._right_view_mode == RightViewMode.VIRTUAL:
            right = ZoomableLabel(interactive=True)
            right._preview_window = self
            right.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            right.setPixmap(self.simulated_pixmap)
            right._use_world = True
            info = self._processed_info_as_dict()
            if info and info.get("dpi"):
                right._px_per_mm = info["dpi"] / 25.4
            right.offset = QPoint(0, 0)
            self._right_view = right

        elif self._right_view_mode == RightViewMode.BASE:
            right = ZoomableLabel(interactive=True)
            right._preview_window = self
            right.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            if self.simulated_pixmap is not None:
                right.setPixmap(self.simulated_pixmap)
            # BASE = pixel view (engraving data already matches machine grid)
            right._use_world = False
            self._right_view = right

        if isinstance(self._right_view, ZoomableLabel):
            self._right_view.viewChanged.connect(self._sync_left_view_to_right)
            self._right_view.set_view_state(
                self._shared_view_zoom,
                QPointF(self._shared_view_pan),
                repaint=False,
            )

        if isinstance(self._left_view, ZoomableLabel):
            self._left_view.set_view_state(
                self._shared_view_zoom,
                QPointF(self._shared_view_pan),
                repaint=False,
            )

        layout.addWidget(left)
        layout.addWidget(right)
        self.view_host_layout.addWidget(container)
        self.current_view = container

        # Apply deterministic viewport sizing now
        self._apply_viewport_geometry()

        # Apply pending transform AFTER right view exists (and after geometry)
        if self._right_view is not None and self._pending_right_transform is not None:
            scale, offset = self._pending_right_transform
            self._right_view._px_per_mm = 1.0 / scale if scale != 0 else None
            self._right_view.set_transform(scale, offset)
            self._pending_right_transform = None

        self._refresh_preview_render_mode()
        self._update_info_bar()
        self._update_crop_hint_position()
        self._update_process_button_state()

    def _sync_left_view_to_right(self, zoom: float, pan_x: float, pan_y: float) -> None:
        self._shared_view_zoom = float(zoom)
        self._shared_view_pan = QPointF(float(pan_x), float(pan_y))
        if isinstance(self._left_view, ZoomableLabel):
            self._left_view.set_view_state(
                self._shared_view_zoom,
                QPointF(self._shared_view_pan),
            )

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        # When window resizes, recompute viewport geometry (window decides)
        self._apply_viewport_geometry()
        self._update_crop_hint_position()
        # Toolbar layout must be controlled by Qt layouts only
        # (manual geometry caused layout conflicts and empty gaps)
        pass

    def _apply_viewport_geometry(self) -> None:
        """
        Deterministic geometry:
        10 + left + 10 + right + 10 == available width (inside view_host).
        Viewport height == all remaining height (inside view_host).
        Bottom bars are fixed height and must never grow.
        """
        if not self.view_host:
            return
        if not self._left_view:
            return

        avail_w = max(1, self.view_host.width())
        avail_h = max(1, self.view_host.height())

        # Two panels with a fixed gap (UI_GAP). Outer margin is already handled by main_layout.
        # left + gap + right = avail_w  => each = (avail_w - gap) / 2
        each_w = max(200, int((avail_w - self.UI_GAP) / 2))
        each_h = max(200, int(avail_h))

        self._left_view.setFixedSize(each_w, each_h)
        if self._right_view:
            self._right_view.setFixedSize(each_w, each_h)

        self._update_crop_hint_position()

        # NO cross-view scaling: right view has its own physical world

    def _apply_toolbar_geometry(self):
        # Intentionally left empty:
        # Qt layout engine must control toolbar geometry.
        return

    # --- EXPLICIT SZIMULÁCIÓ ---
    def run_processing_dialog(self):
        if not self.app:
            return

        if not self.current_image_path:
            self._show_error(self.tr("workspace.image.proc.no_image_loaded", "No image loaded"))
            return

        requires_machine_profile = self.machine_mode != "fiber"
        if requires_machine_profile and not self.current_machine_profile:
            self._show_error(
                self.tr("workspace.image.proc.no_machine_profile", "No machine profile")
            )
            return

        try:
            width_mm = self._parse_mm_text(self.engrave_width_input.text())
            height_mm = self._parse_mm_text(self.engrave_height_input.text())
            if width_mm is None or height_mm is None:
                raise ValueError(
                    self.tr(
                        "workspace.image.proc.width_height_valid_mm",
                        "Width and height must be valid mm values",
                    )
                )
            if width_mm <= 0 or height_mm <= 0:
                raise ValueError(
                    self.tr(
                        "workspace.image.proc.width_height_positive_mm",
                        "Width and height must be positive mm values",
                    )
                )

            raw_crop_box = None
            raw_crop_shape = None
            crop_enabled = bool(self.crop_enabled)
            crop_valid = bool(self.crop_valid)
            crop_rect = self.crop_rect
            if crop_enabled:
                if not crop_valid or not isinstance(crop_rect, QRectF):
                    raise ValueError(
                        self.tr(
                            "workspace.image.proc.crop_enabled_not_valid",
                            "Crop is enabled but not valid",
                        )
                    )
                if (
                    self.crop_shape_mode == "circle"
                    and abs(width_mm - height_mm) >= 0.01
                ):
                    raise ValueError(
                        self.tr(
                            "workspace.image.proc.circle_crop_equal_wh",
                            "Circle crop requires equal width and height",
                        )
                    )

                raw_crop_box = self._normalized_crop_box()
                if raw_crop_box is None:
                    raise ValueError(
                        self.tr(
                            "workspace.image.proc.crop_enabled_not_valid",
                            "Crop is enabled but not valid",
                        )
                    )
                raw_crop_shape = self.crop_shape_mode

            dpi = float(self.engrave_dpi_input.text().replace(",", "."))

            xrate = self.xrate_input.text().replace(",", ".")
            xmaxrate = self.xmaxrate_input.text().replace(",", ".")
            xaccel = self.xaccel_input.text().replace(",", ".")
            yrate = self.yrate_input.text().replace(",", ".")
            ymaxrate = self.ymaxrate_input.text().replace(",", ".")
            yaccel = self.yaccel_input.text().replace(",", ".")
            laser_module = self.engrave_user_modul_input.text().replace(",", ".")

            if requires_machine_profile:
                self.current_machine_profile = {
                    "name": self.current_profile_display.text(),
                    "x": {
                        "steps_per_mm": float(xrate),
                        "max_rate": float(xmaxrate),
                        "acceleration": float(xaccel),
                    },
                    "y": {
                        "steps_per_mm": float(yrate),
                        "max_rate": float(ymaxrate),
                        "acceleration": float(yaccel),
                    },
                    "laser_module": float(laser_module),
                    "gcode_control": self._current_gcode_control_profile(
                        existing=(
                            (self.current_machine_profile or {}).get("gcode_control")
                            if isinstance(self.current_machine_profile, dict)
                            else None
                        )
                    ),
                }
            else:
                self.current_machine_profile = self._virtual_fiber_machine_profile()

            job = JobConfig(
                raw_image_path=self.current_image_path,
                size_mm=(width_mm, height_mm),
                requested_dpi=dpi,
                machine_profile=self.current_machine_profile,
                engrave_axis=self.engrave_axis,
            )

            result = self.app.process(
                job,
                raw_crop_box=raw_crop_box,
                raw_crop_shape=raw_crop_shape,
                crop_enabled=crop_enabled,
                crop_valid=crop_valid,
                crop_rect=raw_crop_box,
            )
            if not result or "decision" not in result:
                self._show_error(
                    self.tr(
                        "workspace.image.proc.processing_failed_invalid_core",
                        "Processing failed: invalid core response",
                    )
                )
                return

        except Exception as e:
            self._show_error(str(e))
            return

        # ---------------------------------------------------------
        # DECISION DIALOG (NEW FLOW)
        # ---------------------------------------------------------
        dialog = ProcessingDecisionDialog(result, self.tr, self)
        if not dialog.exec():
            return

        # ---------------------------------------------------------
        # USER CHOICE → KERNEL EXECUTION
        # ---------------------------------------------------------

        kernel_result = self.app.execute_processing(
            {
                "result": result,
                "control": self._collect_base_control(),
            }
        )

        if not kernel_result.get("ok"):
            self._show_error(
                kernel_result.get(
                    "error",
                    self.tr(
                        "workspace.image.proc.processing_failed_fallback",
                        "Processing failed",
                    ),
                )
            )
            return

        base_img = kernel_result.get("engrave_image")
        self.final_engrave_image = base_img
        self.processed_info = kernel_result.get("processed_info")

        if base_img is None:
            self._show_error(
                self.tr(
                    "workspace.image.proc.no_image_returned",
                    "No image returned from processing",
                )
            )
            return

        qt_image = ImageQt(base_img)
        self.simulated_pixmap = QPixmap.fromImage(qt_image.copy())

        if hasattr(self, "btn_save_image"):
            self.btn_save_image.setEnabled(True)
        if hasattr(self, "btn_save_gcode"):
            self._update_gcode_button_state()

        self._right_view_mode = RightViewMode.BASE
        self.show_normal_view()
        self._refresh_fullscreen_pixmap_if_open()

        # új architektúrában a kernel nem ad vissza képet → csak UI állapot frissül
        self.explanation_label.setText(
            self.tr("workspace.image.proc.processing_accepted", "Processing accepted")
        )
        self.btn_process.setDown(False)
        self.btn_process.clearFocus()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_view(self):
        if self.current_view:
            self.view_host_layout.removeWidget(self.current_view)
            self.current_view.setParent(None)
            self.current_view.deleteLater()
            self.current_view = None
        self._left_view = None
        self._right_view = None

    def _wrap_update(self, source, target):
        original_update = source.update

        def wrapped():
            original_update()
            self._sync_views_from(source, target)

        return wrapped

    def _sync_views_from(self, source, target):
        if source._syncing:
            return
        source._syncing = True
        try:
            scale, offset = source.get_transform()
            target.set_transform(scale, offset)
        finally:
            source._syncing = False

    # --- INFORMATÍV SOR FRISSÍTÉSE ---

    def _update_info_bar(self):
        print("UPDATE INFO BAR, raw_info =", self.raw_info)
        raw_info = getattr(self, "raw_info", None)
        if raw_info is None:
            # RAW info does not exist yet – do NOT touch infobar
            return

        res_x, res_y = raw_info.get("resolution_px", ["?", "?"])

        dpi = raw_info.get("raw_dpi")
        physical_mm = raw_info.get("raw_physical_mm")

        parts = [f"{res_x}×{res_y} px"]

        if dpi is not None:
            parts.append(f"{int(round(dpi))} DPI")

        if physical_mm is not None and isinstance(physical_mm, (tuple, list)):
            w_mm, h_mm = physical_mm
            parts.append(f"{int(round(w_mm))} × {int(round(h_mm))} mm")

        text = " | ".join(parts)

        self.info_label.setText(text)

        # --------------------------------------------------
        # PROCESSED INFO (jobb oldali kép)
        # --------------------------------------------------
        p = self._processed_info_as_dict()
        if p is not None:
            extra = []

            # új raszter felbontás
            # a jobb oldali kép pixel mérete = amit ténylegesen megjelenítünk
            if p.get("px_width") is not None and p.get("px_height") is not None:
                extra.append(f"{p['px_width']}×{p['px_height']} px")

            effective_dpi = p.get("effective_dpi", p.get("dpi"))
            if effective_dpi is not None:
                extra.append(f"{round(effective_dpi,1)} DPI")

            size = p.get("effective_size_mm", p.get("size_mm"))
            if size is not None:
                if not isinstance(size, (tuple, list)) or len(size) != 2:
                    raise TypeError(
                        "processed_info.size_mm must be a 2-item tuple/list",
                    )
                extra.append(
                    f"{round(float(size[0]),1)} × {round(float(size[1]),1)} mm"
                )

            if p.get("steps_per_line") is not None:
                step = p["steps_per_line"]
                aligned = (
                    self.tr("workspace.image.status.aligned", "aligned")
                    if p.get("step_aligned")
                    else self.tr("workspace.image.status.fractional", "fractional")
                )
                extra.append(f"{int(step)} step ({aligned})")

            if extra:
                self.info_label.setText(text + "    →    " + " | ".join(extra))

    def apply_language(self):
        """Refresh all UI texts after app (i18n) is available"""
        self.setWindowTitle(
            self.tr(
                "laser.preview.title",
                "Image preview – Laser simulation",
            )
        )

        if self.btn_load:
            self.btn_load.setText(self.tr("common.load_image", "Load image"))
        if self.btn_process:
            self.btn_process.setText(self.tr("laser.preview.process", "Process"))
        if self.crop_checkbox:
            self.crop_checkbox.setText(self.tr("workspace.image.toolbar.crop", "Crop"))
        if self.crop_square_btn:
            self.crop_square_btn.setText(
                self.tr("workspace.image.toolbar.crop_square", "□ Square")
            )
        if self.crop_circle_btn:
            self.crop_circle_btn.setText(
                self.tr("workspace.image.toolbar.crop_circle", "○ Circle")
            )
        if hasattr(self, "knowledge_button") and self.knowledge_button:
            self.knowledge_button.setText(self.tr("menu_knowledge", "Knowledge"))
        if hasattr(self, "knowledge_action_user_manual") and self.knowledge_action_user_manual:
            self.knowledge_action_user_manual.setText(
                self.tr("knowledge_user_manual", "User manual")
            )
        if hasattr(self, "knowledge_action_image_processing") and self.knowledge_action_image_processing:
            self.knowledge_action_image_processing.setText(
                self.tr("knowledge_image_processing", "Image processing")
            )
        if hasattr(self, "axis_lbl") and self.axis_lbl:
            self.axis_lbl.setText(
                self.tr("workspace.image.toolbar.scan_axis", "Scan axis")
            )

        # INFOBAR:
        # Only refresh if RAW data already exists.
        # RAW infobar must NOT be rebuilt during UI/language lifecycle.
        if getattr(self, "raw_info", None):
            self._refresh_preview_render_mode()
        self._update_info_bar()
        self._update_crop_hint_position()
        self._update_process_button_state()

    # ------------------------------------------------------------------
    # EXTERNAL DEVICE TELEMETRY (NO WORKFLOW EFFECT)
    # ------------------------------------------------------------------
    def set_grbl_connection_state(
        self, connected: bool, port: str | None = None
    ) -> None:
        """
        Pure UI telemetry channel.
        Safe to call from serial/device watcher via Qt signal.
        Does NOT affect kernel, preview or analysis.
        """
        if not hasattr(self, "grbl_status_label"):
            return

        if connected:
            self.grbl_status_dot.setStyleSheet("background:#2ecc71; border-radius:5px;")
            if port:
                self.grbl_status_label.setText(
                    self.tr(
                        "workspace.image.grbl.connected_with_port",
                        "GRBL: connected ({port})",
                    ).format(port=port)
                )
            else:
                self.grbl_status_label.setText(
                    self.tr("workspace.image.grbl.connected", "GRBL: connected")
                )
        else:
            self.grbl_status_dot.setStyleSheet("background:#c0392b; border-radius:5px;")
            self.grbl_status_label.setText(
                self.tr("workspace.image.grbl.disconnected", "GRBL: disconnected")
            )

    def _pil_to_pixmap(self, img):
        if img is None:
            return None
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())

    def save_final_image(self):
        if self.final_engrave_image is None:
            self._show_error(
                self.tr("workspace.image.proc.no_base_image_to_save", "No BASE image to save")
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("workspace.image.dialog.save_image.title", "Save engraved image"),
            "",
            self.tr(
                "workspace.image.dialog.save_image.filter",
                "PNG (*.png);;BMP (*.bmp);;JPEG (*.jpg)",
            ),
        )

        if not path:
            return

        try:
            processed_info = self._processed_info_as_dict()
            effective_dpi = (
                processed_info.get("effective_dpi", processed_info.get("dpi"))
                if processed_info
                else None
            )

            if effective_dpi is not None:
                self.final_engrave_image.save(path, dpi=(effective_dpi, effective_dpi))
            else:
                self.final_engrave_image.save(path)
        except Exception as e:
            self._show_error(str(e))

    def save_gcode(self):
        if not self.app:
            self._show_error(self.tr("workspace.image.proc.app_not_available", "App is not available"))
            return

        if self._gcode_export_running:
            return

        frame_options = None
        if hasattr(self, "keret_checkbox") and self.keret_checkbox.isChecked():
            frame_options = self._ask_frame_export_options()
            if frame_options is None:
                return

        control = self._collect_gcode_control()
        if control is None:
            self._show_error(
                self.tr(
                    "workspace.image.proc.invalid_gcode_control_values",
                    "Invalid G-code control values",
                )
            )
            return

        self._pending_frame_options = frame_options
        self._gcode_export_running = True
        self._update_gcode_button_state()
        self._set_export_ui_frozen(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self._gcode_export_thread = QThread(self)
        self._gcode_export_worker = GCodeExportWorker(self.app, control)
        self._gcode_export_worker.moveToThread(self._gcode_export_thread)

        self._gcode_export_thread.started.connect(
            self._gcode_export_worker.run,
            Qt.ConnectionType.QueuedConnection,
        )
        self._gcode_export_worker.success.connect(self._on_gcode_export_success)
        self._gcode_export_worker.error.connect(self._on_gcode_export_error)
        self._gcode_export_worker.finished.connect(self._on_gcode_export_finished)
        self._gcode_export_worker.finished.connect(self._gcode_export_thread.quit)
        self._gcode_export_thread.finished.connect(self._gcode_export_worker.deleteLater)
        self._gcode_export_thread.finished.connect(self._on_gcode_export_thread_finished)
        self._gcode_export_thread.finished.connect(self._gcode_export_thread.deleteLater)
        self._gcode_export_thread.start()

    def launch_sender(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                current_exe_dir = Path(sys.executable).resolve().parent
                suite_root = current_exe_dir.parent
                sender_candidates = [
                    suite_root / "SenderFree" / "SenderFree.exe",
                    current_exe_dir / "SenderFree" / "SenderFree.exe",
                ]
                sender_exe = next((candidate for candidate in sender_candidates if candidate.exists()), None)
                if sender_exe is None:
                    raise FileNotFoundError(
                        f"SenderFree.exe not found. Checked: {', '.join(str(path) for path in sender_candidates)}"
                    )
                launch_cmd = [str(sender_exe)]
                launch_cwd = str(sender_exe.parent)
            else:
                from core.infrastructure.appdirs import install_dir

                free_root = install_dir()
                launch_cmd = [sys.executable, "-m", "sender"]
                launch_cwd = str(free_root)

            subprocess.Popen(
                launch_cmd,
                cwd=launch_cwd,
                start_new_session=True,
            )
        except Exception as exc:
            self._show_error(
                self.tr("sender.launch_failed_msg", "Sender launch failed: {error}").format(
                    error=exc
                )
            )

    def _finish_gcode_export_ui(self) -> None:
        if self._gcode_export_running:
            self._gcode_export_running = False
            self._update_gcode_button_state()
        self._set_export_ui_frozen(False)
        QApplication.restoreOverrideCursor()

    def _on_gcode_export_success(self, result: dict):
        self._finish_gcode_export_ui()

        if not result.get("ok"):
            self._show_error(
                result.get(
                    "error",
                    self.tr(
                        "workspace.image.proc.gcode_export_failed_fallback",
                        "G-code export failed",
                    ),
                )
            )
            return

        frame_options = self._pending_frame_options
        self._pending_frame_options = None

        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("workspace.image.dialog.save_gcode.title", "Save G-code"),
            "",
            self.tr(
                "workspace.image.dialog.save_gcode.filter",
                "G-code (*.gcode);;Text (*.txt)",
            ),
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(result.get("gcode", ""))
        except Exception as e:
            self._show_error(str(e))
            return

        if frame_options is not None:
            try:
                frame_path = self._frame_output_path(path)
                frame_shape = (
                    "circle" if self.crop_shape_mode == "circle" else "rectangle"
                )
                frame_gcode = self._build_frame_gcode(
                    speed_mm_min=frame_options["speed_mm_min"],
                    s_value=frame_options["s_value"],
                    pass_count=frame_options["pass_count"],
                    shape=frame_shape,
                )
                with open(frame_path, "w", encoding="utf-8") as frame_file:
                    frame_file.write(frame_gcode)
            except Exception as e:
                self._show_error(
                    self.tr(
                        "workspace.image.frame.export_failed_template",
                        "Frame export failed: {e}",
                    ).format(e=e)
                )

    def _on_gcode_export_error(self, error):
        self._finish_gcode_export_ui()
        self._pending_frame_options = None
        self._show_error(str(error))

    def _on_gcode_export_finished(self):
        self._pending_frame_options = None

    def _on_gcode_export_thread_finished(self):
        self._gcode_export_worker = None
        self._gcode_export_thread = None

    def _ask_frame_export_options(self) -> dict | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(
            self.tr("workspace.image.frame.dialog.title", "Keret paraméterek")
        )

        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        power_input = QDoubleSpinBox(dialog)
        power_input.setRange(0.01, 100.0)
        power_input.setDecimals(2)
        power_input.setValue(1.0)
        power_input.setSuffix(" %")
        form.addRow(
            self.tr("workspace.image.frame.dialog.laser_power_pct", "Laser power (%)"),
            power_input,
        )

        speed_input = QDoubleSpinBox(dialog)
        speed_input.setRange(1.0, 1_000_000.0)
        speed_input.setDecimals(1)
        speed_input.setValue(2000.0)
        speed_input.setSuffix(" mm/min")
        form.addRow(
            self.tr("workspace.image.frame.dialog.speed_mm_min", "Speed (mm/min)"),
            speed_input,
        )

        pass_input = QSpinBox(dialog)
        pass_input.setMinimum(1)
        pass_input.setValue(2)
        form.addRow(
            self.tr("workspace.image.frame.dialog.pass_count", "Pass count"),
            pass_input,
        )

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return None

        pwm_max = 1000.0
        if isinstance(self.current_machine_profile, dict):
            gcode_control = self.current_machine_profile.get("gcode_control", {})
            if isinstance(gcode_control, dict):
                try:
                    pwm_max = float(gcode_control.get("pwm_max", pwm_max) or pwm_max)
                except (TypeError, ValueError):
                    pwm_max = 1000.0

        power_percent = float(power_input.value())
        s_value = (power_percent / 100.0) * pwm_max

        return {
            "speed_mm_min": float(speed_input.value()),
            "pass_count": int(pass_input.value()),
            "s_value": max(0.0, s_value),
        }

    def _frame_output_path(self, image_gcode_path: str) -> str:
        dot = image_gcode_path.rfind(".")
        if dot <= 0:
            return f"{image_gcode_path}_frame.gcode"
        return f"{image_gcode_path[:dot]}_frame.gcode"

    def _build_frame_gcode(
        self,
        *,
        speed_mm_min: float,
        s_value: float,
        pass_count: int,
        shape: str = "rectangle",
    ) -> str:
        width_mm, height_mm = self._resolve_frame_size_mm()

        if width_mm is None or height_mm is None or width_mm <= 0 or height_mm <= 0:
            raise ValueError(
                self.tr(
                    "workspace.image.proc.invalid_frame_geometry",
                    "Invalid frame geometry",
                )
            )

        unit = getattr(self.app, "length_unit", "mm")
        use_inch = unit == "inch"
        factor = 1.0 / 25.4 if use_inch else 1.0
        w = width_mm * factor
        h = height_mm * factor
        feed = speed_mm_min * factor

        lines = [
            f"; frame={shape}",
            "; mode=relative (like raster) - no absolute positioning",
            "; enforce XY arc plane + incremental IJK for GRBL-compatible G2/G3",
            "; no G0/G1 absolute XY targets are emitted in frame programs",
            "G17",
            "G91",
            "G91.1",
            "G20" if use_inch else "G21",
            "M5",
        ]

        # circle parameters (derived from existing frame size)
        r = min(w, h) / 2.0
        diam = 2.0 * r

        for i in range(max(1, int(pass_count))):
            lines.append(f"; pass {i + 1}/{pass_count}")
            lines.append(f"M3 S{int(round(s_value))}")
            lines.append(f"G1 F{feed:.3f}")

            if shape == "circle":
                # start point = leftmost point of the circle
                # two half-arcs -> full circle, returns to start
                lines.append("; circle: two relative half-arcs, net XY displacement = 0")
                lines.append(f"G2 X{diam:.3f} Y0 I{r:.3f} J0")
                lines.append(f"G2 X{-diam:.3f} Y0 I{-r:.3f} J0")
            else:
                # rectangle (existing behavior)
                lines.append(f"G1 X{w:.3f}")
                lines.append(f"G1 Y{h:.3f}")
                lines.append(f"G1 X{-w:.3f}")
                lines.append(f"G1 Y{-h:.3f}")

            lines.append("M5")

        return "\n".join(lines) + "\n"

    def _resolve_frame_size_mm(self) -> tuple[float | None, float | None]:
        processed_info = self._processed_info_as_dict() or {}

        size = processed_info.get("effective_size_mm", processed_info.get("size_mm"))
        if isinstance(size, (tuple, list)) and len(size) >= 2:
            try:
                return float(size[0]), float(size[1])
            except (TypeError, ValueError):
                pass

        w = processed_info.get("effective_width_mm")
        h = processed_info.get("effective_height_mm")
        if w is not None and h is not None:
            try:
                return float(w), float(h)
            except (TypeError, ValueError):
                pass

        if getattr(self.app, "_last_job", None) is not None:
            size_mm = getattr(self.app._last_job, "size_mm", None)
            if isinstance(size_mm, (tuple, list)) and len(size_mm) >= 2:
                try:
                    return float(size_mm[0]), float(size_mm[1])
                except (TypeError, ValueError):
                    pass

        return (
            self._parse_mm_text(self.engrave_width_input.text()),
            self._parse_mm_text(self.engrave_height_input.text()),
        )

    def _workspace_tr(self, key: str, default: str = "") -> str:
        if hasattr(self, "app") and self.app:
            return self.app.tr(key, default)
        return default

    def _knowledge_language_code(self) -> str:
        lang = str(getattr(self.app, "language", "en") or "en").strip().lower()
        return lang if lang in {"de", "en", "fr", "hu", "it"} else "en"

    def _knowledge_document_path(self, section: str) -> Path:
        return KNOWLEDGE_DIR / section / f"{self._knowledge_language_code()}.md"

    def _open_knowledge_document(self, section: str) -> None:
        labels = {
            "user_manual": self.tr("knowledge_user_manual", "User manual"),
            "image_processing": self.tr("knowledge_image_processing", "Image processing"),
        }
        document_path = self._knowledge_document_path(section)

        if not document_path.exists():
            message = self.tr(
                "knowledge_doc_not_found",
                "Document not found: {path}",
            ).format(path=document_path)
            QMessageBox.warning(self, self.tr("errors.title", "Error"), message)
            self._show_error(message)
            return

        try:
            markdown_text = document_path.read_text(encoding="utf-8")
        except Exception as exc:
            message = self.tr(
                "knowledge_doc_open_failed",
                "Failed to open document: {error}",
            ).format(error=exc)
            QMessageBox.warning(self, self.tr("errors.title", "Error"), message)
            self._show_error(message)
            return

        dialog = MarkdownViewerDialog(
            labels.get(section, self.tr("menu_knowledge", "Knowledge")),
            markdown_text,
            self.tr,
            self,
        )
        dialog.exec()

    def _update_language_button(self) -> None:
        if hasattr(self, "language_button") and self.language_button:
            current_lang = str(getattr(self.app, "language", "en") or "en").strip().lower()
            self.language_button.setText(current_lang.upper())

    def _set_workspace_language(self, lang_code: str) -> None:
        if hasattr(self, "app") and self.app:
            self.app.set_language(lang_code)
        self.apply_language()
        self._update_language_button()

    # --- i18n delegation ---
    def tr(self, key: str, default: str = "") -> str:
        if hasattr(self, "app") and self.app:
            return self.app.tr(key, default)
        return default

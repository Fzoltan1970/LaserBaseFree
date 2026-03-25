import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ""
os.environ["QT_PLUGIN_PATH"] = ""
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QSlider,
    QApplication,
    QGroupBox,
    QComboBox,
    QScrollArea,
    QSizePolicy,
    QMessageBox,
)
from PyQt6.QtGui import QPixmap, QAction, QImage
from PyQt6.QtCore import Qt, QTimer, QObject, QThread, QEventLoop, pyqtSignal
from PyQt6.QtNetwork import QLocalSocket
import sys
import cv2
import numpy as np
import webbrowser
import lang

from image_processor import ImageProcessor
from background_magic_tool import compute_region_mask
from edit.manager import EditManager
from edit.overlay import EditOverlay
from edit.clean import CleanTool
from edit.simplify import SimplifyTool
from edit.history import History
from model_manager import ModelManager
from styles.default import DefaultStyle
from styles.portrait import PortraitStyle
from styles.architecture import ArchitectureStyle
from styles.vehicle import VehicleStyle
from styles.engrave import EngraveStyle
from vectorizer import Vectorizer
from lang import tr, get_config_value, set_config_value

from core.infrastructure.appdirs import install_dir

UI_SLIDER_MAX = 1000


class ReconstructWorker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, sketch_image, detail, smooth, merge, vectorizer_ref):
        super().__init__()
        self.sketch_image = sketch_image
        self.detail = detail
        self.smooth = smooth
        self.merge = merge
        self.vectorizer_ref = vectorizer_ref

    def run(self):
        start = time.perf_counter()
        print("[SKETCH TRACE] ReconstructWorker.run start")
        try:
            paths = self.vectorizer_ref.vectorize(
                self.sketch_image,
                detail=self.detail,
                smooth=self.smooth,
                merge=self.merge,
            )
            preview = self.vectorizer_ref.draw_preview(self.sketch_image.shape, paths)
            gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)

            result = {
                "sketch_image": gray,
                "base_sketch": gray.copy(),
                "last_line": (gray < 250).astype("uint8") * 255,
            }
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] ReconstructWorker.run end ({duration:.3f}s)")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # fordítható widget registry
        self._tr = []

        # aktuális rajz mód (egyetlen forrás)
        self.draw_mode = "soft"

        self.setWindowTitle(tr("APP_TITLE"))
        self.resize(1100, 700)
        self.setMinimumSize(900, 600)
        self._startup_geometry_applied = False

        self.model_manager = ModelManager()
        self.processor = ImageProcessor(self.model_manager)
        self.processor.style = DefaultStyle(self.processor)

        self.cv_image = None        
        self.sketch_image = None
        self.base_sketch = None
        self._last_processing_input_id = None
        
        # ---- FONTOS: nincs alap mód ----
        self.last_mode = None
        self.last_remove_bg = False
        self.has_generated = False

        # ---------------- EDIT SYSTEM ----------------
        self.edit = EditManager()
        self.overlay = EditOverlay(self.edit)
        self.clean_tool = CleanTool()
        self.simplify_tool = SimplifyTool()
        self.history = History(20)
        self.current_line_layer = None
        self.edit_mode = False
        self.vectorizer = Vectorizer()
        self.reconstruct_thread = None
        self.reconstruct_worker = None
        self.reconstruct_busy = False
        self.magic_tool_active = False
        self.magic_mask = None
        self.magic_applied_mask = None
        self.magic_preview_image = None
        self.magic_tolerance = 15

        # ---- PREVIEW TIMER ----
        self.preview_timer = QTimer()
        self.preview_timer.setInterval(350)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.auto_preview)

        self.menuBar().hide()
        self._create_topbar()
        self._create_layout()

        self.retranslate_ui()

        self.zoom = 1.0
        self.zoom_min = 0.25
        self.zoom_max = 6.0
      
    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_geometry_applied:
            self._startup_geometry_applied = True
            QTimer.singleShot(0, self._fit_to_available_geometry)

    def _fit_to_available_geometry(self):
        screen_geo = self.screen().availableGeometry()
        width = min(1100, max(self.minimumWidth(), screen_geo.width() - 80))
        height = min(700, max(self.minimumHeight(), screen_geo.height() - 80))
        self.resize(width, height)
        self.center_on_screen()

    def center_on_screen(self):
        screen = self.screen().availableGeometry()
        geo = self.frameGeometry()
        geo.moveCenter(screen.center())
        self.move(geo.topLeft())

    # ---------------- TOP BUTTON BAR ----------------
    def _create_topbar(self):

        toolbar = self.addToolBar("main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)

        self.btn_open = QPushButton()
        self.btn_save = QPushButton()
        self.btn_send_laserbase = QPushButton()
        self.btn_exit = QPushButton()
        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        self.btn_about = QPushButton()

        for b in (self.btn_open, self.btn_save, self.btn_send_laserbase, self.btn_exit, self.btn_about):
            b.setMinimumHeight(28)
            toolbar.addWidget(b)

        self.lang_label.setMinimumHeight(28)
        self.lang_combo.setMinimumHeight(28)
        self.lang_combo.setMinimumWidth(140)
        self.lang_combo.addItem("Magyar", "hu")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Deutsch", "de")
        self.lang_combo.addItem("Français", "fr")
        self.lang_combo.addItem("Italiano", "it")

        toolbar.addWidget(self.lang_label)
        toolbar.addWidget(self.lang_combo)

        toolbar.addSeparator()

        self.btn_open.clicked.connect(self.open_image)
        self.btn_save.clicked.connect(self.save_image)
        self.btn_send_laserbase.clicked.connect(self.send_to_laserbase)
        self.btn_exit.clicked.connect(self.close)
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        self.btn_about.clicked.connect(self.show_about)

        self._set_language_combo(lang.LANG)


    # ---------------- LAYOUT ----------------
    def _create_layout(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QHBoxLayout(main_widget)
        
        # PREVIEW
        self.image_label = QLabel(tr("OPEN_HINT"))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("color: white;")
        self.image_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # induláskor töltse ki a nézőablakot
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Expanding)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.image_label)
        self.scroll.setWidgetResizable(True)   # fontos: üres állapothoz
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # valódi háttér
        self.scroll.setStyleSheet("QScrollArea { background: #2b2b2b; border: none; }")
        self.scroll.viewport().setStyleSheet("background: #2b2b2b;")

        main_layout.addWidget(self.scroll, 3)

        # mouse events for edit
        self.image_label.setMouseTracking(True)
        self.image_label.mousePressEvent = self.image_mouse_press
        self.image_label.mouseMoveEvent = self.image_mouse_move
        self.image_label.mouseReleaseEvent = self.image_mouse_release
        self.image_label.wheelEvent = self.image_wheel

        # CONTROL PANEL
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)

        # -------- GENERATE --------
        # --- AI Model selector ---
        self.model_label = QLabel(tr("MODEL"))
        self.model_combo = QComboBox()

        self.model_combo.addItem(tr("sketch.model.none"))

        for name in self.model_manager.registry.keys():
            self.model_combo.addItem(name)
        self.model_combo.setEnabled(True)

        # alapértelmezett
        self.model_combo.setCurrentIndex(0)

        # esemény
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)

        self.group_generate = QGroupBox()
        preset_box = self.group_generate
        preset_layout = QVBoxLayout()

        self.btn_soft = QPushButton(tr("MODE_SOFT"))
        self.btn_strong = QPushButton(tr("MODE_STRONG"))

        # --- új rajz módok (régi presetek) ---
        self.mode_buttons = {}

        def add_mode(name, label):
            btn = QPushButton(label)
            btn.setCheckable(False)
            btn.clicked.connect(lambda checked, n=name: self.set_draw_mode(n))
            preset_layout.addWidget(btn)
            self.mode_buttons[name] = btn

        preset_layout.addWidget(self.model_label)
        preset_layout.addWidget(self.model_combo)

        preset_layout.addWidget(self.btn_soft)
        preset_layout.addWidget(self.btn_strong)

        add_mode("portrait", tr("MODE_PORTRAIT"))
        add_mode("architecture", tr("MODE_ARCHITECTURE"))
        add_mode("vehicle", tr("MODE_VEHICLE"))
        add_mode("engrave", tr("MODE_ENGRAVE"))
              
        preset_box.setLayout(preset_layout)
        control_layout.addWidget(preset_box)

        # layout-ba

        # Generate sliders
        self.group_settings = QGroupBox()
        gen_box = self.group_settings
        gen_layout = QVBoxLayout()

        detail_layout, self.detail_slider = self._make_slider("DETAIL", self.schedule_preview, 100)
        line_layout, self.line_slider = self._make_slider("LINE_THICKNESS", self.schedule_preview, 100)
        bg_layout, self.bg_slider = self._make_slider("BG_CLEAN", self.schedule_preview, 0)
        self.btn_magic_tool = QPushButton(tr("MAGIC_TOOL"))
        self.btn_magic_tool.clicked.connect(self.activate_magic_tool)

        gen_layout.addLayout(detail_layout)
        gen_layout.addLayout(line_layout)
        gen_layout.addLayout(bg_layout)
        gen_layout.addWidget(self.btn_magic_tool)

        gen_box.setLayout(gen_layout)
        control_layout.addWidget(gen_box)

        # -------- STYLE --------
        self.group_style = QGroupBox()
        style_box = self.group_style
        style_layout = QVBoxLayout()

        ink_layout, self.ink_slider = self._make_slider("ILLUSTRATION", self.apply_style, 0)
        comic_layout, self.comic_slider = self._make_slider("COMIC", self.apply_style, 0)
        logo_layout, self.logo_slider = self._make_slider("LOGO", self.apply_style, 0)
        minimal_layout, self.minimal_slider = self._make_slider("MINIMAL", self.apply_style, 0)

        style_layout.addLayout(ink_layout)
        style_layout.addLayout(comic_layout)
        style_layout.addLayout(logo_layout)
        style_layout.addLayout(minimal_layout)

        style_box.setLayout(style_layout)
        control_layout.addWidget(style_box)

        control_layout.addWidget(self._create_edit_panel())
        control_layout.addWidget(self._create_reconstruct_panel())

        control_layout.addStretch()

        control_scroll = QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setWidget(control_widget)
        control_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_layout.addWidget(control_scroll, 1)

        # BUTTON CONNECTIONS
        self.btn_soft.clicked.connect(self.set_soft_mode)
        self.btn_strong.clicked.connect(self.set_strong_mode)        

        # ---- EDIT BUTTON CONNECTIONS ----
        self.edit_buttons["brush"].clicked.connect(self._edit_brush)
        self.edit_buttons["clean"].clicked.connect(self._edit_clean)
        self.edit_buttons["simplify"].clicked.connect(self._edit_simplify)

        # induló vizuális állapot
        self.update_mode_buttons()

    def _set_language_combo(self, lang_code):
        idx = self.lang_combo.findData(lang_code)
        if idx < 0:
            idx = self.lang_combo.findData("hu")
        self.lang_combo.blockSignals(True)
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.blockSignals(False)

    def on_language_changed(self, index):
        lang_code = self.lang_combo.itemData(index)
        if not lang_code or lang_code == lang.LANG:
            return
        lang.set_language(lang_code)
        self.retranslate_ui()

    def tr_widget(self, widget, key, setter="setText"):
        self._tr.append((widget, key, setter))
        getattr(widget, setter)(tr(key))

    def retranslate_ui(self):
        self.setWindowTitle(tr("APP_TITLE"))

        self.image_label.setText(tr("OPEN_HINT"))

        self.btn_open.setText(tr("LOAD_IMAGE"))
        self.btn_save.setText(tr("SAVE_IMAGE"))
        self.btn_send_laserbase.setText(tr("SEND_TO_LASERBASE"))
        self.btn_exit.setText(tr("EXIT"))
        self.lang_label.setText(tr("LANGUAGE"))
        self.btn_about.setText(tr("ABOUT"))

        self.model_label.setText(tr("MODEL"))

        self.group_generate.setTitle(tr("GENERATE"))
        self.group_settings.setTitle(tr("SETTINGS"))
        self.group_style.setTitle(tr("STYLE"))
        self.group_edit.setTitle(tr("EDIT"))
        self.group_vector.setTitle(tr("VECTOR"))

        self.edit_buttons["brush"].setText(tr("ERASER"))
        self.edit_buttons["clean"].setText(tr("DENOISE"))
        self.edit_buttons["simplify"].setText(tr("SIMPLIFY"))

        # --- DRAW MODE BUTTONS ---
        self.btn_soft.setText(tr("MODE_SOFT"))
        self.btn_strong.setText(tr("MODE_STRONG"))
        self.btn_magic_tool.setText(tr("MAGIC_TOOL"))

        self.mode_buttons["portrait"].setText(tr("MODE_PORTRAIT"))
        self.mode_buttons["architecture"].setText(tr("MODE_ARCHITECTURE"))
        self.mode_buttons["vehicle"].setText(tr("MODE_VEHICLE"))
        self.mode_buttons["engrave"].setText(tr("MODE_ENGRAVE"))

        # --- MODEL COMBO FIRST ITEM ---
        self.model_combo.setItemText(0, tr("NONE"))

        # --- VECTOR PANEL BUTTONS ---
        self.btn_reconstruct.setText(tr("RECONSTRUCT"))
        self.btn_illustration.setText(tr("ILLUSTRATION_MODE"))

        for w, key, setter in self._tr:
            getattr(w, setter)(tr(key))
    def show_about(self):

        msg = QMessageBox(self)
        msg.setWindowTitle(tr("ABOUT"))

        msg.setText(tr("ABOUT_HTML"))

        msg.setInformativeText(
            f'<a href="https://paypal.me/ZoltanFitos?locale.x=hu_HU&country.x=HU">{tr("ABOUT_LINK")}</a>'
        )

        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)

        msg.exec()
     
    # --------------------------------------------------
    # DRAW MODE CHANGE
    # --------------------------------------------------
    def set_draw_mode(self, mode_name):
        self.draw_mode = mode_name

        # melyik algoritmus
        style_map = {
            "soft": DefaultStyle,
            "strong": DefaultStyle,
            "portrait": PortraitStyle,
            "architecture": ArchitectureStyle,
            "vehicle": VehicleStyle,
            "engrave": EngraveStyle,
        }

        self.processor.style = style_map[mode_name](self.processor)

        # melyik blending mód
        blend = "strong" if mode_name == "strong" else "soft"

        self.update_mode_buttons()
        self.run_processing(False, blend)

    # --------------------------------------------------------
    # PRESETS PANEL
    # --------------------------------------------------------
    def _create_edit_panel(self):

        self.group_edit = QGroupBox()
        box = self.group_edit
        layout = QVBoxLayout(box)

        self.edit_buttons = {}
        edit_tools = {
            "brush": "ERASER",
            "clean": "DENOISE",
            "simplify": "SIMPLIFY",
        }

        for tool, label in edit_tools.items():
            btn = QPushButton(tr(label))

            # --- CSAK A RADÍR MARAD BERAGADÓ GOMB ---
            if tool == "brush":
                btn.setCheckable(True)
            else:
                btn.setCheckable(False)

            btn.setMinimumHeight(32)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Fixed)

            layout.addWidget(btn)
            self.edit_buttons[tool] = btn

        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(6)

        return box

    #
    #Vektor panel
    #
    def _create_reconstruct_panel(self):
        self.group_vector = QGroupBox()
        box = self.group_vector
        layout = QVBoxLayout()

        # ---------- SLIDEREK ----------
        self.vec_detail = QSlider(Qt.Orientation.Horizontal)
        self.vec_detail.setRange(0, UI_SLIDER_MAX)
        self.vec_detail.setValue(0)
        lbl = QLabel(); self.tr_widget(lbl,"DETAIL"); layout.addWidget(lbl)
        layout.addWidget(self.vec_detail)

        self.vec_merge = QSlider(Qt.Orientation.Horizontal)
        self.vec_merge.setRange(0, UI_SLIDER_MAX)
        self.vec_merge.setValue(0)
        lbl = QLabel(); self.tr_widget(lbl, "CONTINUITY"); layout.addWidget(lbl)
        layout.addWidget(self.vec_merge)

        self.vec_smooth = QSlider(Qt.Orientation.Horizontal)
        self.vec_smooth.setRange(0, UI_SLIDER_MAX)
        self.vec_smooth.setValue(0)
        lbl = QLabel(); self.tr_widget(lbl, "SMOOTHNESS"); layout.addWidget(lbl)
        layout.addWidget(self.vec_smooth)

        # Újrarajzolás
        self.btn_reconstruct = QPushButton(tr("RECONSTRUCT"))
        self.btn_reconstruct.setMinimumHeight(32)
        self.btn_reconstruct.clicked.connect(self._reconstruct_lines)
        layout.addWidget(self.btn_reconstruct)

        # Illusztráció mód
        self.btn_illustration = QPushButton(tr("ILLUSTRATION_MODE"))
        self.btn_illustration.setMinimumHeight(36)
        self.btn_illustration.clicked.connect(self.run_illustration_mode)
        layout.addWidget(self.btn_illustration)

        box.setLayout(layout)
        return box

    # --------------------------------------------------
    # EDIT HANDLERS
    # --------------------------------------------------
    def _disable_all_edit_buttons(self):
        for btn in self.edit_buttons.values():
            btn.setChecked(False)

    def _edit_brush(self, checked):
        self._disable_all_edit_buttons()
        if checked:
            self.edit.enable(True)
            self.edit.set_tool(self.edit.TOOL_BRUSH)
            self.edit_buttons["brush"].setChecked(True)
            self.render_with_edit()
        else:
            self.edit.enable(False)
            self.render_with_edit()

    def _edit_clean(self):
        start = time.perf_counter()
        print("[SKETCH TRACE] MainWindow._edit_clean start")
        if self.sketch_image is None:
            return
        try:
            self._push_history()
            base = self.edit.apply_to(self.sketch_image)
            self.sketch_image = self.clean_tool.apply(base)
            self.last_line = self.processor.line_sketch(self.sketch_image, 50, 50)
            edges = cv2.Canny(self.sketch_image, 40, 120)
            self.last_line = edges
            self.render_with_edit()
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] MainWindow._edit_clean end ({duration:.3f}s)")

    def _edit_simplify(self):
        start = time.perf_counter()
        print("[SKETCH TRACE] MainWindow._edit_simplify start")
        if self.sketch_image is None:
            return
        try:
            self._push_history()
            base = self.edit.apply_to(self.sketch_image)
            self.sketch_image = self.simplify_tool.apply(base)
            self.last_line = self.processor.line_sketch(self.sketch_image, 50, 50)
            self.last_line = (self.sketch_image < 250).astype("uint8") * 25
            self.render_with_edit()
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] MainWindow._edit_simplify end ({duration:.3f}s)")

    def run_illustration_mode(self):
        """Automatikus több lépéses rajz finomítás"""
        start = time.perf_counter()
        print("[SKETCH TRACE] MainWindow.run_illustration_mode start")

        if self.sketch_image is None:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.setEnabled(False)
        QApplication.processEvents()

        try:
            # 1. egyszerűsítés
            self._edit_simplify()
            QApplication.processEvents()
 
            # 2. újrarajzolás
            self._reconstruct_lines(wait=True)
            QApplication.processEvents()

            # 3. tisztítás
            self._edit_clean()
            QApplication.processEvents()

            # 4. végső újrarajzolás
            self._reconstruct_lines(wait=True)
            QApplication.processEvents()

        finally:
            self.setEnabled(True)
            QApplication.restoreOverrideCursor()
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] MainWindow.run_illustration_mode end ({duration:.3f}s)")


    # ---- ÚJ: VONAL REKONSTRUKCIÓ ----
    def _set_reconstruct_busy(self, busy):
        self.reconstruct_busy = busy

        self.btn_reconstruct.setEnabled(not busy)
        self.vec_detail.setEnabled(not busy)
        self.vec_merge.setEnabled(not busy)
        self.vec_smooth.setEnabled(not busy)
        self.btn_reconstruct.setText(tr("sketch.status.processing") if busy else tr("RECONSTRUCT"))

    def _reconstruct_lines(self, wait=False):
        start = time.perf_counter()
        print("[SKETCH TRACE] MainWindow._reconstruct_lines start")
        if self.sketch_image is None or self.reconstruct_busy:
            return False
        try:
            self._push_history()

            detail_proc = self.ui_to_100(self.vec_detail.value())
            smooth_proc = self.ui_to_100(self.vec_smooth.value())
            merge_proc = self.ui_to_100(self.vec_merge.value())
            sketch_copy = self.sketch_image.copy()

            self.reconstruct_thread = QThread(self)
            self.reconstruct_worker = ReconstructWorker(
                sketch_copy,
                detail_proc,
                smooth_proc,
                merge_proc,
                self.vectorizer,
            )
            self.reconstruct_worker.moveToThread(self.reconstruct_thread)

            self.reconstruct_thread.started.connect(self.reconstruct_worker.run)
            self.reconstruct_worker.finished.connect(self._on_reconstruct_finished)
            self.reconstruct_worker.error.connect(self._on_reconstruct_error)
            self.reconstruct_worker.finished.connect(self.reconstruct_thread.quit)
            self.reconstruct_worker.error.connect(self.reconstruct_thread.quit)
            self.reconstruct_thread.finished.connect(self.reconstruct_worker.deleteLater)
            self.reconstruct_thread.finished.connect(self.reconstruct_thread.deleteLater)
            self.reconstruct_thread.finished.connect(self._on_reconstruct_thread_finished)

            done_loop = None
            if wait:
                done_loop = QEventLoop(self)
                self.reconstruct_worker.finished.connect(lambda *_: done_loop.quit())
                self.reconstruct_worker.error.connect(lambda *_: done_loop.quit())

            self._set_reconstruct_busy(True)
            self.reconstruct_thread.start()

            if done_loop is not None:
                done_loop.exec()
                return True
            return False
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] MainWindow._reconstruct_lines end ({duration:.3f}s)")

    def _on_reconstruct_finished(self, result):
        start = time.perf_counter()
        print("[SKETCH TRACE] MainWindow._on_reconstruct_finished start")
        try:
            self.sketch_image = result["sketch_image"]
            self.base_sketch = result["base_sketch"]
            self.edit.set_base_image(self.sketch_image)
            self.last_line = result["last_line"]
            self.current_line_layer = self.last_line
            self.render_with_edit()
            self._set_reconstruct_busy(False)
        finally:
            duration = time.perf_counter() - start
            print(f"[SKETCH TRACE] MainWindow._on_reconstruct_finished end ({duration:.3f}s)")

    def _on_reconstruct_error(self, message):
        QMessageBox.critical(self, tr("ERROR"), f'{tr("sketch.error.reconstruct_failed")}\n{message}')
        self._set_reconstruct_busy(False)

    def _on_reconstruct_thread_finished(self):
        self.reconstruct_thread = None
        self.reconstruct_worker = None

    def set_soft_mode(self):
        self.set_draw_mode("soft")

    def set_strong_mode(self):
        self.set_draw_mode("strong")

    # --------------------------------------------------
    # MODE BUTTON VISUAL STATE
    # --------------------------------------------------
    def update_mode_buttons(self):
        active = "background-color: #c8f7c5;"  # halvány almazöld
        normal = ""

        # minden mód reset
        self.btn_soft.setStyleSheet(normal)
        self.btn_strong.setStyleSheet(normal)

        for btn in getattr(self, "mode_buttons", {}).values():
            btn.setStyleSheet(normal)

        # aktuális mód kiemelése
        if self.draw_mode == "soft":
            self.btn_soft.setStyleSheet(active)
        elif self.draw_mode == "strong":
            self.btn_strong.setStyleSheet(active)
        elif self.draw_mode in self.mode_buttons:
            self.mode_buttons[self.draw_mode].setStyleSheet(active)

    def on_model_changed(self, index):
        if index == 0:
            self.processor.active_model = None
        else:
            if self.processor.models is None:
                return
            name = list(self.processor.models.registry.keys())[index - 1]
            self.processor.active_model = name

        if self.has_generated:
            blend = "strong" if self.draw_mode == "strong" else "soft"
            self.run_processing(False, blend)

    # ---------------- SLIDER ----------------
    def _make_slider(self, key, callback, default_proc=50):
        layout = QHBoxLayout()

        label = QLabel()
        self.tr_widget(label, key)

        slider = QSlider(Qt.Orientation.Horizontal)

        slider.setRange(0, UI_SLIDER_MAX)
        slider.setValue(int(round(default_proc * UI_SLIDER_MAX / 100)))
        slider.valueChanged.connect(callback)

        layout.addWidget(label)
        layout.addWidget(slider)

        return layout, slider

    def ui_to_100(self, ui):
        return int(round(ui * 100 / UI_SLIDER_MAX))

    # ---------------- GENERATE ----------------
    def schedule_preview(self):
        if self.cv_image is None:
            return

        # NINCS még generálás → nem rajzol
        if not self.has_generated:
            return

        self.preview_timer.start()

    def auto_preview(self):
        if not self.has_generated:
            return
        # újrarajzolás a jelenlegi móddal
        blend = "strong" if self.draw_mode == "strong" else "soft"
        self.run_processing(False, blend)

    def open_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("OPEN_IMAGE_TITLE"),
            "",
            tr("sketch.dialog.images_filter"),
        )

        # vissza vászon módba új kép előtt
        self.scroll.setWidgetResizable(True)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Expanding)
        self.image_label.setText(tr("OPEN_HINT"))

        if file_path:
            try:
                data = np.fromfile(file_path, dtype=np.uint8)
                self.cv_image = cv2.imdecode(data, cv2.IMREAD_COLOR)
            except Exception:
                self.cv_image = None

            if self.cv_image is None:
                QMessageBox.warning(self, tr("ERROR"), tr("ERROR_LOAD"))
                return

            # átadjuk a feldolgozónak
            self.processor.set_image(self.cv_image)

            self.has_generated = False
            self.last_mode = None
            self.magic_applied_mask = None

            # kezdő zoom azonnal (mielőtt bármi render történik)
            h, w = self.cv_image.shape[:2]
            self.zoom = self.fit_to_view(w, h)

            # első automatikus rajz
            self.set_draw_mode("soft")

    def run_processing(self, remove_bg=False, mode="soft"):
        if self.cv_image is None:
            return

        current_input = getattr(self.processor, "_current_image", None)
        current_input_id = id(current_input) if current_input is not None else None
        input_changed = self._last_processing_input_id != current_input_id
        
        self.has_generated = True
        self.last_remove_bg = remove_bg
        self.last_mode = mode

        # slider értékek
        detail = 100 - self.ui_to_100(self.detail_slider.value())
        strength = 100 - self.ui_to_100(self.line_slider.value())
        clean = self.ui_to_100(self.bg_slider.value())

        self.base_sketch = self.processor.process(
            mode=mode,
            detail=detail,
            strength=strength,
            clean=clean,
        )
        
        self.sketch_image = self.base_sketch.copy()
        self.sketch_image = self._apply_magic_mask(self.sketch_image)

        # kontúr réteg az edit rendszernek
        self.last_line = self.processor.last_line
       
        if input_changed:
            self.edit.set_base_image(self.sketch_image)
        self.current_line_layer = self.processor.last_line

        self.apply_style()
        self._last_processing_input_id = current_input_id

        self.render_with_edit()

    # ---------------- STYLE ----------------
    def apply_style(self):
        if self.sketch_image is None:
            return

        if self.base_sketch is None:
            return

        img = self.base_sketch.copy()

        ink = self.ui_to_100(self.ink_slider.value())
        comic = self.ui_to_100(self.comic_slider.value())
        logo = self.ui_to_100(self.logo_slider.value())
        minimal = self.ui_to_100(self.minimal_slider.value())

        if ink > 0:
            alpha = 1 + ink / 40
            img = cv2.convertScaleAbs(img, alpha=alpha, beta=-ink)

        if comic > 0:
            k = 1 + comic // 20
            kernel = np.ones((k, k), np.uint8)
            img = cv2.dilate(img, kernel, 1)

        if logo > 0:
            _, img = cv2.threshold(img, 180 - logo, 255, cv2.THRESH_BINARY)

        if minimal > 0:
            k = 1 + minimal // 25
            kernel = np.ones((k, k), np.uint8)
            img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)

        self.sketch_image = self._apply_magic_mask(img)
        self.render_with_edit()

    def render_with_edit(self):
        if self.sketch_image is None:
            return

        # biztos azonos méret
        if self.edit.mask is not None and self.edit.mask.shape != self.sketch_image.shape[:2]:
            self.edit.set_base_image(self.sketch_image)

        img = self.edit.apply_to(self.sketch_image)

        if self.edit.enabled:
            img = self.overlay.render(img, self.last_line)

        if self.magic_preview_image is not None:
            img = self.magic_preview_image

        self.update_preview(img)

    def _set_magic_tool_cursor(self, active):
        if active:
            self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.image_label.setCursor(Qt.CursorShape.ArrowCursor)

    def activate_magic_tool(self):
        if self.sketch_image is None:
            return
        self.magic_tool_active = True
        self.magic_mask = None
        self.magic_preview_image = None
        self._set_magic_tool_cursor(True)

    def cancel_magic_tool(self):
        self.magic_tool_active = False
        self.magic_mask = None
        self.magic_preview_image = None
        self._set_magic_tool_cursor(False)
        self.render_with_edit()

    def apply_magic_tool(self):
        if self.sketch_image is None or self.magic_mask is None:
            return
        current_input = getattr(self.processor, "_current_image", None)
        current_input_id = id(current_input) if current_input is not None else None
        input_changed = self._last_processing_input_id != current_input_id
        self._push_history()
        if self.magic_applied_mask is None:
            self.magic_applied_mask = self.magic_mask.copy()
        else:
            self.magic_applied_mask = np.maximum(self.magic_applied_mask, self.magic_mask)
        self.sketch_image[self.magic_mask > 0] = 255
        if input_changed:
            self.edit.set_base_image(self.sketch_image)
        self.cancel_magic_tool()

    def _apply_magic_mask(self, img):
        if img is None or self.magic_applied_mask is None:
            return img
        if self.magic_applied_mask.shape != img.shape[:2]:
            return img
        out = img.copy()
        out[self.magic_applied_mask > 0] = 255
        return out

    def _build_magic_preview(self):
        if self.sketch_image is None or self.magic_mask is None:
            self.magic_preview_image = None
            return

        if len(self.sketch_image.shape) == 2:
            preview = cv2.cvtColor(self.sketch_image, cv2.COLOR_GRAY2BGR)
        else:
            preview = self.sketch_image.copy()

        selected = self.magic_mask > 0
        if np.any(selected):
            overlay = preview.copy()
            overlay[selected] = [0, 0, 255]
            preview = cv2.addWeighted(overlay, 0.35, preview, 0.65, 0)

        self.magic_preview_image = preview

    # ---------------- DISPLAY ----------------
    def update_preview(self, img):
        if img is None:
            return

        if len(img.shape) == 2:
            h, w = img.shape
            qimg = QImage(img.copy().data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.copy().data, w, h, ch * w, QImage.Format.Format_RGB888)

        pixmap = QPixmap.fromImage(qimg)

        scaled = pixmap.scaled(
            int(w * self.zoom),
            int(h * self.zoom),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())

        # kép megjelenítésekor viewer mód
        self.scroll.setWidgetResizable(False)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed,
                                       QSizePolicy.Policy.Fixed)

    # ---------------- SAVE ----------------
    def save_image(self):
        if self.sketch_image is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("SAVE_IMAGE_TITLE"),
            "",
            tr("sketch.dialog.png_filter"),
        )
        if not file_path:
            return

        self._export_current_sketch_png(file_path)

    def _export_current_sketch_png(self, output_path: str) -> bool:
        if self.sketch_image is None:
            return False

        ext = ".png"
        success, encoded = cv2.imencode(ext, self.sketch_image)
        if not success:
            return False

        encoded.tofile(output_path)
        return True

    def send_to_laserbase(self):
        if self.sketch_image is None:
            return

        export_dir = Path(tempfile.gettempdir()) / "LaserBaseSketchExports"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = export_dir / f"sketch_{stamp}.png"

        if not self._export_current_sketch_png(str(out_path)):
            QMessageBox.warning(self, tr("ERROR"), tr("SEND_TO_LASERBASE_EXPORT_FAILED"))
            return

        path_payload = str(out_path.resolve())
        socket = QLocalSocket(self)
        socket.connectToServer("LaserBaseFreeSketchIPC")

        if socket.waitForConnected(500):
            socket.write(path_payload.encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return

        if getattr(sys, "frozen", False):
            laserbase_exe = (
                Path(sys.executable).resolve().parent.parent
                / "LaserBaseFree"
                / "LaserBaseFree.exe"
            )
            if not laserbase_exe.exists():
                configured = str(get_config_value("laserbase_free_exe_path", "") or "").strip()
                if configured:
                    candidate = Path(configured)
                    if candidate.exists():
                        laserbase_exe = candidate

            if not laserbase_exe.exists():
                selected_path, _ = QFileDialog.getOpenFileName(
                    self,
                    tr("sketch.dialog.select_laserbase_exe"),
                    str(install_dir()),
                    tr("sketch.dialog.executables_filter"),
                )
                if selected_path:
                    laserbase_exe = Path(selected_path)
                    set_config_value("laserbase_free_exe_path", str(laserbase_exe))

            if not laserbase_exe.exists():
                QMessageBox.warning(
                    self,
                    tr("ERROR"),
                    tr("SEND_TO_LASERBASE_LAUNCH_FAILED").format(error=tr("sketch.error.laserbase_not_found")),
                )
                return

            launch_cmd = [str(laserbase_exe), "--open", path_payload]
            launch_cwd = None
        else:
            free_main = install_dir() / "main.py"
            if not free_main.exists():
                QMessageBox.warning(
                    self,
                    tr("ERROR"),
                    tr("SEND_TO_LASERBASE_LAUNCH_FAILED").format(error="main.py not found"),
                )
                return
            launch_cmd = [sys.executable, str(free_main), "--open", path_payload]
            launch_cwd = str(install_dir())
        try:
            subprocess.Popen(launch_cmd, cwd=launch_cwd, start_new_session=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("ERROR"),
                tr("SEND_TO_LASERBASE_LAUNCH_FAILED").format(error=exc),
            )

    # --------------------------------------------------
    # EDIT: coordinate conversion
    # --------------------------------------------------
    def label_to_image(self, event):
        if self.sketch_image is None:
            return None

        # pozíció a labelen belül
        lx = event.position().x()
        ly = event.position().y()

        # scroll offset hozzáadása
        hbar = self.scroll.horizontalScrollBar().value()
        vbar = self.scroll.verticalScrollBar().value()

        lx += hbar
        ly += vbar

        # visszaskálázás képre
        ix = lx / self.zoom
        iy = ly / self.zoom

        img_h, img_w = self.sketch_image.shape[:2]

        if ix < 0 or iy < 0 or ix >= img_w or iy >= img_h:
            return None

        return int(ix), int(iy)

    # --------------------------------------------------
    # EDIT: mouse handling
    # --------------------------------------------------
    def image_mouse_press(self, event):
        if self.magic_tool_active:
            pos = self.label_to_image(event)
            if pos:
                x, y = pos
                self.magic_mask = compute_region_mask(self.sketch_image, x, y, self.magic_tolerance)
                self._build_magic_preview()
                self.render_with_edit()
            return

        if not self.edit.enabled:
            return

        pos = self.label_to_image(event)
        if pos:
            x, y = pos
            self._push_history()
            self.edit.begin_stroke()
            self.edit.apply_at(x, y, self.last_line)
            self.overlay.set_cursor(x, y)
            self.render_with_edit()

    def image_mouse_move(self, event):
        if self.magic_tool_active:
            return

        pos = self.label_to_image(event)
        if pos:
            x, y = pos
            self.overlay.set_cursor(x, y)

            if event.buttons():
                self.edit.apply_at(x, y, self.last_line)
                self.render_with_edit()

    def image_mouse_release(self, event):
        if self.magic_tool_active:
            return

        self.overlay.clear_cursor()
        if self.edit.enabled:
            
            self.sketch_image = self.edit.apply_to(self.sketch_image)
        self.overlay.clear_cursor()
        self.render_with_edit()

    def image_wheel(self, event):
        if self.magic_tool_active:
            return

        delta = event.angleDelta().y()

        # CTRL = zoom
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if delta > 0 else 0.9
            self.zoom = max(self.zoom_min, min(self.zoom_max, self.zoom * factor))
            self.render_with_edit()
            return

        # normál görgő = ecset méret
        size = self.edit.brush.size + (1 if delta > 0 else -1)
        self.edit.brush.set_size(size)
        self.render_with_edit()

    # --------------------------------------------------
    # HISTORY SAVE
    # --------------------------------------------------
    def _push_history(self):
        if self.sketch_image is None:
            return
        entry = {
            "image": self.sketch_image.copy(),
        }
        if self.base_sketch is not None:
            entry["base_sketch"] = self.base_sketch.copy()
        if self.last_line is not None:
            entry["last_line"] = self.last_line.copy()
        if self.magic_applied_mask is not None:
            entry["magic_mask"] = self.magic_applied_mask.copy()
        self.history.push(entry)

    # --------------------------------------------------
    # GLOBAL UNDO / REDO
    # --------------------------------------------------
    def keyPressEvent(self, event):
        if self.magic_tool_active:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.apply_magic_tool()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_magic_tool()
                return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                current = {
                    "image": self.sketch_image.copy() if self.sketch_image is not None else None,
                }
                if self.base_sketch is not None:
                    current["base_sketch"] = self.base_sketch.copy()
                if self.last_line is not None:
                    current["last_line"] = self.last_line.copy()
                if self.magic_applied_mask is not None:
                    current["magic_mask"] = self.magic_applied_mask.copy()
                img = self.history.undo(current)
                if img is not None:
                    if isinstance(img, dict):
                        restored_image = img.get("image")
                        if restored_image is not None:
                            self.sketch_image = restored_image
                        self.base_sketch = img.get("base_sketch", self.base_sketch)
                        self.last_line = img.get("last_line", self.last_line)
                        self.magic_applied_mask = img.get(
                            "magic_mask", self.magic_applied_mask
                        )
                    else:
                        self.sketch_image = img
                    edit_base = self.base_sketch if self.base_sketch is not None else self.sketch_image
                    self.edit.set_base_image(edit_base)   # <<< EZ HIÁNYZIK
                    self.render_with_edit()
                return

            if event.key() == Qt.Key.Key_Y:
                current = {
                    "image": self.sketch_image.copy() if self.sketch_image is not None else None,
                }
                if self.base_sketch is not None:
                    current["base_sketch"] = self.base_sketch.copy()
                if self.last_line is not None:
                    current["last_line"] = self.last_line.copy()
                if self.magic_applied_mask is not None:
                    current["magic_mask"] = self.magic_applied_mask.copy()
                img = self.history.redo(current)
                if img is not None:
                    if isinstance(img, dict):
                        restored_image = img.get("image")
                        if restored_image is not None:
                            self.sketch_image = restored_image
                        self.base_sketch = img.get("base_sketch", self.base_sketch)
                        self.last_line = img.get("last_line", self.last_line)
                        self.magic_applied_mask = img.get(
                            "magic_mask", self.magic_applied_mask
                        )
                    else:
                        self.sketch_image = img
                    edit_base = self.base_sketch if self.base_sketch is not None else self.sketch_image
                    self.edit.set_base_image(edit_base)   # <<< EZ IS
                    self.render_with_edit()
                return


        super().keyPressEvent(event)

    def fit_to_view(self, img_w, img_h):
        view = self.scroll.viewport().size()

        if view.width() == 0 or view.height() == 0:
            return 1.0

        scale_w = view.width() / img_w
        scale_h = view.height() / img_h
        scale = min(scale_w, scale_h)

        # csak lefelé skálázunk
        return min(1.0, scale)

# ---------------- RUN ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
)
from PyQt6.QtCore import Qt


class ProcessingDecisionDialog(QDialog):
    """
    Result interpreter UI.

    Nem számol.
    Nem dönt.
    Csak megjeleníti a core válaszát és megkérdezi a usert.
    """

    USE_DERIVED_DPI = "BASE"

    def __init__(self, result: dict, tr, parent=None):
        super().__init__(parent)

        self.tr = tr
        self.result = result or {}

        self.setWindowTitle(self.tr("processing.title", "Processing decision"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.info_label)

        # --- buttons ---
        btn_row = QHBoxLayout()
        layout.addLayout(btn_row)

        self.btn_accept = QPushButton(self.tr("processing.btn.accept", "Accept"))
        self.btn_repair = QPushButton(self.tr("processing.btn.repair", "Repair image"))
        self.btn_force = QPushButton(self.tr("processing.btn.force", "Use machine DPI"))

        btn_row.addWidget(self.btn_accept)
        btn_row.addWidget(self.btn_repair)
        btn_row.addWidget(self.btn_force)

        # connect
        self.btn_accept.clicked.connect(self._accept_base)
        self.btn_repair.clicked.connect(self._run_repair)
        self.btn_force.clicked.connect(self._accept_base)

        self._configure(self.result)

    # --------------------------------------------------

    def _configure(self, result: dict):

        decision = result.get("decision", "INVALID")
        ctx = result.get("context") or {}

        image_width_px = ctx.get("image_width_px")
        image_height_px = ctx.get("image_height_px")
        real_lines_x = ctx.get("real_lines_x")
        real_lines_y = ctx.get("real_lines_y")
        real_lines = ctx.get("real_lines")
        axis = ctx.get("engrave_axis")
        requested_dpi = ctx.get("requested_dpi")
        real_dpi = ctx.get("real_dpi")

        # --- BASE ---
        if decision == "BASE":
            self.info_label.setText(
                self.tr(
                    "processing.base.summary",
                    "The image matches the machine.\nRequested DPI: {requested_dpi}\nReal DPI: {real_dpi}",
                ).format(requested_dpi=requested_dpi, real_dpi=real_dpi)
            )
            self.btn_repair.hide()
            self.btn_force.hide()
            return

        # --- REPAIR ---
        if decision == "REPAIR":
            required_lines_text = self.tr("processing.repair.required_lines_na", "N/A")
            if real_lines_x is not None and real_lines_y is not None:
                required_lines_text = f"{real_lines_x} x {real_lines_y}"
            elif real_lines is not None and axis in ("X", "Y"):
                required_lines_text = (
                    f"{image_width_px} x {real_lines}"
                    if axis == "X"
                    else f"{real_lines} x {image_height_px}"
                )

            self.info_label.setText(
                self.tr(
                    "processing.repair.summary",
                    "The image resolution is insufficient for the machine.\n"
                    "Image lines: {image_width_px} x {image_height_px}\n"
                    "Required lines: {required_lines_text}\n\n"
                    "You must repair the image before engraving.",
                ).format(
                    image_width_px=image_width_px,
                    image_height_px=image_height_px,
                    required_lines_text=required_lines_text,
                )
            )
            self.btn_accept.hide()
            self.btn_force.hide()
            return

        # --- INVALID / UNKNOWN ---
        self.info_label.setText(
            self.tr(
                "processing.invalid.no_decision",
                "Processing engine returned no decision.",
            )
        )
        self.btn_accept.hide()
        self.btn_repair.hide()
        self.btn_force.hide()

    # --------------------------------------------------

    def _accept_base(self):
        self.accept()

    def _run_repair(self):
        self.accept()

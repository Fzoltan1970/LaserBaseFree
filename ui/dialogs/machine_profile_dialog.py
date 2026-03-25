from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
)


class MachineProfileDialog(QDialog):
    def __init__(self, prefill: dict | None = None, parent=None):
        super().__init__(parent)
        self._tr = (
            parent.tr
            if parent is not None and hasattr(parent, "tr") and callable(parent.tr)
            else (lambda _key, default="": default)
        )
        self.setWindowTitle(
            self._tr("machine_profile.title", "New Machine Profile")
        )

        prefill = prefill or {}
        self._prefill_gcode_control = prefill.get("gcode_control")
        self._prefill_base_tuning = prefill.get("base_tuning")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.name_input = QLineEdit(prefill.get("name", ""))
        # --- X axis ---
        self.x_steps_input = QLineEdit(str(prefill.get("x", {}).get("steps_per_mm", "")))
        self.x_maxrate_input = QLineEdit(str(prefill.get("x", {}).get("max_rate", "")))
        self.x_accel_input = QLineEdit(str(prefill.get("x", {}).get("acceleration", "")))

        # --- Y axis ---
        self.y_steps_input = QLineEdit(str(prefill.get("y", {}).get("steps_per_mm", "")))
        self.y_maxrate_input = QLineEdit(str(prefill.get("y", {}).get("max_rate", "")))
        self.y_accel_input = QLineEdit(str(prefill.get("y", {}).get("acceleration", "")))
        self.module_input = QLineEdit(str(prefill.get("laser_module", "")))

        form.addRow(self._tr("machine_profile.name", "Profile name"), self.name_input)
        header_x = QLabel(self._tr("machine_profile.axis_x", "--- X axis ---"))
        header_x.setStyleSheet("font-weight:600; color:#333;")
        form.addRow(header_x)
        form.addRow(self._tr("machine_profile.x_steps", "X Steps/mm"), self.x_steps_input)
        form.addRow(self._tr("machine_profile.x_max_rate", "X Max rate"), self.x_maxrate_input)
        form.addRow(self._tr("machine_profile.x_acceleration", "X Acceleration"), self.x_accel_input)

        header_y = QLabel(self._tr("machine_profile.axis_y", "--- Y axis ---"))
        header_y.setStyleSheet("font-weight:600; color:#333;")
        form.addRow(header_y)
        form.addRow(self._tr("machine_profile.y_steps", "Y Steps/mm"), self.y_steps_input)
        form.addRow(self._tr("machine_profile.y_max_rate", "Y Max rate"), self.y_maxrate_input)
        form.addRow(self._tr("machine_profile.y_acceleration", "Y Acceleration"), self.y_accel_input)
        form.addRow(self._tr("machine_profile.laser_module", "Laser module"), self.module_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._data = None

    def _try_accept(self):
        name = self.name_input.text().strip()
        x_steps = self.x_steps_input.text().strip()
        x_maxrate = self.x_maxrate_input.text().strip()
        x_accel = self.x_accel_input.text().strip()

        y_steps = self.y_steps_input.text().strip()
        y_maxrate = self.y_maxrate_input.text().strip()
        y_accel = self.y_accel_input.text().strip()
        module = self.module_input.text().strip()

        if not all([
            name,
            x_steps, x_maxrate, x_accel,
            y_steps, y_maxrate, y_accel,
            module
        ]):
            return

        try:
            self._data = {
                "name": name,
                "x": {
                    "steps_per_mm": float(x_steps),
                    "max_rate": float(x_maxrate),
                    "acceleration": float(x_accel),
                },
                "y": {
                    "steps_per_mm": float(y_steps),
                    "max_rate": float(y_maxrate),
                    "acceleration": float(y_accel),
                },
                "laser_module": float(module),
                "base_tuning": self._prefill_base_tuning or {},
                "gcode_control": self._prefill_gcode_control or {},
            }
        except ValueError:
            return

        self.accept()

    def get_profile_data(self) -> dict:
        return dict(self._data) if self._data else None

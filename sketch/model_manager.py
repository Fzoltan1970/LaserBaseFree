from pathlib import Path

import onnxruntime as ort

from core.infrastructure.appdirs import install_dir
from sketch.lang import bundle_dir, tr

APP_NAME = "LaserBaseSketch"
BUNDLED_MODEL_DIR = bundle_dir() / "models"
PRIMARY_MODEL_DIR = install_dir() / "models"
DEV_MODEL_DIR = install_dir() / "sketch" / "models"
FALLBACK_MODEL_DIR = install_dir() / "model"


class ModelManager:
    def __init__(self):
        self.sessions = {}
        self.registry = {
            "Téma kiemelés": "u2netp.onnx",
        }

    def _ensure_model(self, name):
        if name not in self.registry:
            return None

        filename = self.registry[name]
        search_paths = [
            BUNDLED_MODEL_DIR / filename,
            PRIMARY_MODEL_DIR / filename,
            DEV_MODEL_DIR / filename,
            FALLBACK_MODEL_DIR / filename,
        ]
        source = next((path for path in search_paths if path.exists()), search_paths[-1])

        if not source.exists():
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                tr("sketch.error.model_missing_title"),
                tr("sketch.error.model_missing").format(path=source),
            )
            return None

        return source

    def get(self, name):
        if name is None:
            return None

        if name in self.sessions:
            return self.sessions[name]

        model_path = self._ensure_model(name)
        if model_path is None:
            return None

        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.sessions[name] = session
        return session

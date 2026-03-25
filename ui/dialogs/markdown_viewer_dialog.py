from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
)


class MarkdownViewerDialog(QDialog):
    def __init__(self, title: str, markdown_text: str, tr, parent=None):
        super().__init__(parent)
        self.tr = tr

        self.setWindowTitle(title)
        self.resize(920, 720)

        layout = QVBoxLayout(self)

        self.viewer = QTextBrowser(self)
        self.viewer.setReadOnly(True)
        self.viewer.setOpenExternalLinks(False)
        self.viewer.setMarkdown(markdown_text)
        layout.addWidget(self.viewer)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(self.tr("close", "Close"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

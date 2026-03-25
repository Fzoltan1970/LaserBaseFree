import numpy as np

from .history import History
from .brush import BrushTool

class EditManager:
    """
    Központi szerkesztés vezérlő.
    Nem függ GUI-tól és nem tartalmaz rajzolási algoritmust.
    """

    TOOL_NONE = 0
    TOOL_BRUSH = 1

    def __init__(self):
        self.enabled = False
        self.tool = self.TOOL_NONE

        self.mask = None              # felhasználói módosítások (0..255)
        self.history = History(20)    # undo stack

        self.brush = BrushTool(self)

    # --------------------------------------------------
    # KÉP BETÖLTÉS
    # --------------------------------------------------
    def set_base_image(self, image):
        """
        Új kép érkezett → maszk reset és új alap rajz
        """
        h, w = image.shape[:2]
        self.mask = np.zeros((h, w), np.uint8)
        self.base_image = image.copy()
        self.history.clear()

    # --------------------------------------------------
    # MÓD KEZELÉS
    # --------------------------------------------------
    def enable(self, state: bool):
        self.enabled = state
        if not state:
            self.tool = self.TOOL_NONE

    def set_tool(self, tool_id):
        if self.enabled:
            self.tool = tool_id

    # --------------------------------------------------
    # UNDO / REDO
    # --------------------------------------------------
    def push_undo(self):
        if self.mask is not None:
            self.history.push(self.mask.copy())

    def undo(self):
        prev = self.history.undo(self.mask)
        if prev is not None:
            self.mask = prev

    def redo(self):
        nxt = self.history.redo(self.mask)
        if nxt is not None:
            self.mask = nxt

    # --------------------------------------------------
    # RAJZ MŰVELETEK
    # --------------------------------------------------
    def begin_stroke(self):
        """egér lenyomáskor"""
        if not self.enabled:
            return
        self.push_undo()

    def apply_at(self, x, y, image):
        """
        egér húzás / kattintás
        image = aktuális line layer (stroke tool miatt kell)
        """
        if not self.enabled or self.mask is None:
            return

        if self.tool == self.TOOL_BRUSH:
            self.brush.apply(self.mask, x, y)

    # --------------------------------------------------
    # ALKALMAZÁS A VÉGEREDMÉNYRE
    # --------------------------------------------------
    def apply_to(self, sketch):
        """
        A felhasználói maszk rákerül a kész rajzra.
        mask:
            0 = nincs változás
            255 = törlés (fehérítés)
        """
        if self.mask is None:
            return sketch

        result = sketch.copy()
        result[self.mask > 0] = 255
        return result

import cv2
import numpy as np


class BrushTool:
    """
    Egyszerű kör ecset a felhasználói maszkhoz.
    A manager hívja.
    """

    def __init__(self, manager):
        self.manager = manager
        self.size = 12          # px
        self.mode_add = False   # False = töröl, True = visszafest

    # --------------------------------------------------
    # BEÁLLÍTÁSOK
    # --------------------------------------------------
    def set_size(self, px):
        self.size = max(1, int(px))

    def set_add_mode(self, state: bool):
        """
        False → radír
        True  → visszafest
        """
        self.mode_add = state

    # --------------------------------------------------
    # FESTÉS
    # --------------------------------------------------
    def apply(self, mask, x, y):
        """
        mask: numpy uint8 (0..255)
        x,y: koordináta
        """

        if mask is None:
            return

        h, w = mask.shape[:2]

        if x < 0 or y < 0 or x >= w or y >= h:
            return

        value = 0 if self.mode_add else 255

        cv2.circle(
            mask,
            (int(x), int(y)),
            int(self.size),
            value,
            -1,
            lineType=cv2.LINE_AA
        )

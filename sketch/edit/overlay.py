import cv2
import numpy as np


class EditOverlay:
    """
    Csak vizuális visszajelzés.
    Nem módosítja a forrás rajzot.
    """

    def __init__(self, manager):
        self.manager = manager
        self.cursor_pos = None
        self.show_hover = True

    # --------------------------------------------------
    # KURZOR HELYZET
    # --------------------------------------------------
    def set_cursor(self, x, y):
        self.cursor_pos = (int(x), int(y))

    def clear_cursor(self):
        self.cursor_pos = None

    # --------------------------------------------------
    # MEGJELENÍTÉS
    # --------------------------------------------------
    def render(self, image, line_layer=None):
        """
        image      : megjelenítendő rajz (grayscale vagy BGR)
        line_layer : stroke tool-hoz szükséges (hover preview)
        """

        if image is None:
            return image

        # biztos BGR
        if len(image.shape) == 2:
            view = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            view = image.copy()

        if not self.manager.enabled or self.cursor_pos is None:
            return view

        x, y = self.cursor_pos

        # --------------------------------------------------
        # BRUSH PREVIEW
        # --------------------------------------------------
        if self.manager.tool == self.manager.TOOL_BRUSH:
            r = self.manager.brush.size
            cv2.circle(view, (x, y), r, (0, 200, 255), 1, cv2.LINE_AA)

        # --------------------------------------------------
        # STROKE HOVER PREVIEW
        # --------------------------------------------------
        elif self.manager.tool == self.manager.TOOL_STROKE and line_layer is not None:

            if 0 <= y < line_layer.shape[0] and 0 <= x < line_layer.shape[1]:

                binary = (line_layer < 128).astype(np.uint8)
                num, labels = cv2.connectedComponents(binary)
                label_id = labels[y, x]

                if label_id != 0:
                    component = (labels == label_id)

                    # halvány piros overlay
                    overlay = view.copy()
                    overlay[component] = (0, 80, 255)
                    view = cv2.addWeighted(overlay, 0.45, view, 0.55, 0)

        return view

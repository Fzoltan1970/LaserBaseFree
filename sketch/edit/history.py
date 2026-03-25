class History:
    """
    Egyszerű undo / redo kezelés numpy maszkokhoz.
    """

    def __init__(self, limit=20):
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []

    # --------------------------------------------------
    # RESET
    # --------------------------------------------------
    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()

    # --------------------------------------------------
    # PUSH
    # --------------------------------------------------
    def push(self, state):
        """
        Új állapot mentése (művelet előtt)
        """
        if state is None:
            return

        self.undo_stack.append(state)

        # méret limit
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)

        # új művelet → redo törlődik
        self.redo_stack.clear()

    # --------------------------------------------------
    # UNDO
    # --------------------------------------------------
    def undo(self, current):
        if not self.undo_stack:
            return None

        if hasattr(current, "copy"):
            self.redo_stack.append(current.copy())
        else:
            self.redo_stack.append(current)
        return self.undo_stack.pop()

    # --------------------------------------------------
    # REDO
    # --------------------------------------------------
    def redo(self, current):
        if not self.redo_stack:
            return None

        if hasattr(current, "copy"):
            self.undo_stack.append(current.copy())
        else:
            self.undo_stack.append(current)
        return self.redo_stack.pop()


from .base import SketchStyle


class DefaultStyle(SketchStyle):
    """
    Az eredeti rajz mód.
    Pontosan a jelenlegi algoritmust használja:
    tone_sketch + line_sketch
    """

    name = "Default"

    def generate(self, gray, detail, strength):
        tone = self.p.tone_sketch(gray, detail, strength)
        line = self.p.line_sketch(gray, detail, strength)
        return tone, line

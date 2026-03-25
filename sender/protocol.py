from __future__ import annotations

import re
from typing import List


class GenericProtocol:
    ACK_PATTERN = re.compile(r"^\s*ok\b", re.IGNORECASE)
    ERROR_PATTERN = re.compile(r"^\s*(error|alarm|err)\b", re.IGNORECASE)

    def is_ack(self, line: str) -> bool:
        return bool(self.ACK_PATTERN.match(line))

    def is_error(self, line: str) -> bool:
        return bool(self.ERROR_PATTERN.match(line))

    def make_jog(self, dx: float, dy: float, dz: float, feed: float) -> List[str]:
        moves = []
        if dx:
            moves.append(f"X{dx:.3f}")
        if dy:
            moves.append(f"Y{dy:.3f}")
        if dz:
            moves.append(f"Z{dz:.3f}")

        if not moves:
            return []

        command = "G1 " + " ".join(moves) + f" F{max(0.0, feed):.3f}"
        return ["G91", command, "G90"]

    def make_frame(self, *args, **kwargs):
        pass

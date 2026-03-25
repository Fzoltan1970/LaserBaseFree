from dataclasses import dataclass
from numbers import Real
from typing import Tuple
from typing import Literal


@dataclass(frozen=True)
class JobConfig:
    raw_image_path: str
    size_mm: Tuple[float, float]
    requested_dpi: float
    machine_profile: dict
    engrave_axis: Literal["X", "Y"] = "X"

    def __post_init__(self):
        if not isinstance(self.size_mm, (tuple, list)) or len(self.size_mm) != 2:
            raise TypeError(
                f"size_mm must be a 2-item tuple/list of float-like values, got {type(self.size_mm).__name__}",
            )

        width_mm, height_mm = self.size_mm
        if not isinstance(width_mm, Real) or not isinstance(height_mm, Real):
            raise TypeError(
                "size_mm entries must be numeric float-like values, "
                f"got ({type(width_mm).__name__}, {type(height_mm).__name__})",
            )
        if not isinstance(self.requested_dpi, Real):
            raise TypeError(
                f"requested_dpi must be numeric float-like, got {type(self.requested_dpi).__name__}",
            )
        if self.engrave_axis not in ("X", "Y"):
            raise ValueError("engrave_axis must be 'X' or 'Y'")

        object.__setattr__(self, "size_mm", (float(width_mm), float(height_mm)))
        object.__setattr__(self, "requested_dpi", float(self.requested_dpi))

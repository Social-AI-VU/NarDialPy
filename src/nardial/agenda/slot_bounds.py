from typing import Any, Dict, List, Optional


class SlotBounds:
    """How many times (and for how long) an agenda slot may resolve.

    ``count_min``/``duration_min`` are floors the resolver tries to satisfy
    before letting a slot stop; ``count_max``/``duration_max`` are hard
    ceilings the resolver never exceeds, even if a floor is unmet. Defaults
    (``count_min=1, count_max=1``) mean "resolve exactly once".
    """

    def __init__(self, count_min: int = 1, count_max: int = 1,
                 duration_min: Optional[float] = None, duration_max: Optional[float] = None):
        self.count_min = count_min
        self.count_max = count_max
        self.duration_min = duration_min
        self.duration_max = duration_max

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SlotBounds":
        data = data or {}
        return cls(
            count_min=data.get("count_min", 1),
            count_max=data.get("count_max", 1),
            duration_min=data.get("duration_min"),
            duration_max=data.get("duration_max"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count_min": self.count_min,
            "count_max": self.count_max,
            "duration_min": self.duration_min,
            "duration_max": self.duration_max,
        }

    def validate(self) -> List[str]:
        errs: List[str] = []
        for name, value in (("count_min", self.count_min), ("count_max", self.count_max),
                             ("duration_min", self.duration_min), ("duration_max", self.duration_max)):
            if value is not None and value < 0:
                errs.append(f"{name} must be >= 0")
        if self.count_min is not None and self.count_max is not None and self.count_min > self.count_max:
            errs.append("count_min must be <= count_max")
        if self.duration_min is not None and self.duration_max is not None and self.duration_min > self.duration_max:
            errs.append("duration_min must be <= duration_max")
        return errs

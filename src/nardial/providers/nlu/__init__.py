from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class NLUResult:
    transcript: str
    intent: str | None = None
    confidence: float = 0.0


@runtime_checkable
class NLUProvider(Protocol):
    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult: ...

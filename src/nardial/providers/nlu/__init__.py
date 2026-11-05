from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Intent name constants shared by all NLU providers and ConversationAgent.
# Centralised here so a rename only touches one place.
INTENT_YESNO_YES      = "yesno_yes"
INTENT_YESNO_NO       = "yesno_no"
INTENT_YESNO_DONTKNOW = "yesno_dontknow"


@dataclass
class NLUResult:
    transcript: str
    intent: str | None = None
    confidence: float = 0.0
    # True when listening was stopped early by a pause or skip_listen; the question is then not asked again.
    interrupted: bool = False
    # Entities extracted alongside the intent (e.g. Dialogflow parameters).
    parameters: dict = field(default_factory=dict)

    @property
    def entity(self) -> str | None:
        """The first non-empty entity value, or None when no entity was found."""
        for value in self.parameters.values():
            if isinstance(value, (list, tuple)):
                value = next((v for v in value if v not in (None, "")), None)
            if value not in (None, "", {}):
                return str(value)
        return None


@runtime_checkable
class NLUProvider(Protocol):
    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult: ...

    def cancel(self) -> None:
        """Interrupt an in-progress ``listen`` call.

        Called when the dialog runtime needs to preempt listening (e.g. for a
        preemptive interrupt).  Implementations backed by streaming gRPC
        services (Dialogflow) should close the stream here.  The default stub
        is a safe no-op.
        """


__all__ = [
    "INTENT_YESNO_YES",
    "INTENT_YESNO_NO",
    "INTENT_YESNO_DONTKNOW",
    "NLUResult",
    "NLUProvider",
]

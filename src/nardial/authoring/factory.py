from typing import Any, assert_never

from pydantic import TypeAdapter

from nardial.authoring.schemas import (
    AnyDialogSpec,
    ChitchatDialogSpec,
    FunctionalDialogSpec,
    LLMDialogSpec,
    NarrativeDialogSpec,
)
from nardial.mini_dialogs import (
    ChitchatDialog,
    FunctionalDialog,
    LLMMiniDialog,
    MiniDialog,
    NarrativeDialog,
)

_dialog_adapter: TypeAdapter[AnyDialogSpec] = TypeAdapter(AnyDialogSpec)


def from_json(doc: dict[str, Any]) -> MiniDialog:
    """Parse and validate a dialog document dict, returning a typed runtime dialog object.

    Raises ``pydantic.ValidationError`` with field-level details on invalid input.
    """
    spec = _dialog_adapter.validate_python(doc)
    return _spec_to_dialog(spec)


def to_json(d: MiniDialog) -> dict[str, Any]:
    """Serialize a runtime dialog object back to a JSON-ready dict."""
    return _dialog_to_spec(d).model_dump(exclude_none=True)


def _spec_to_dialog(spec: AnyDialogSpec) -> MiniDialog:
    moves = list(spec.moves)
    deps = list(spec.dependencies)
    vdeps = [vd.model_dump() for vd in spec.variable_dependencies]

    if isinstance(spec, FunctionalDialogSpec):
        return FunctionalDialog(
            dialog_id=spec.id,
            moves=moves,
            functional_type=spec.functional_type,
            dependencies=deps,
        )
    if isinstance(spec, NarrativeDialogSpec):
        return NarrativeDialog(
            dialog_id=spec.id,
            moves=moves,
            thread=spec.thread,
            position=spec.position,
            dependencies=deps,
            variable_dependencies=vdeps,
        )
    if isinstance(spec, ChitchatDialogSpec):
        return ChitchatDialog(
            dialog_id=spec.id,
            moves=moves,
            topics=list(spec.topics),
            dependencies=deps,
            variable_dependencies=vdeps,
        )
    if isinstance(spec, LLMDialogSpec):
        return LLMMiniDialog(
            dialog_id=spec.id,
            moves=moves,
            prompt=spec.prompt,
            max_turns=spec.max_turns,
            dependencies=deps,
            variable_dependencies=vdeps,
            quit_phrases=list(spec.quit_phrases),
            quit_signal=spec.quit_signal,
            speak_first=spec.speak_first,
            duration=spec.duration,
            rag_enabled=spec.rag_enabled,
            index_name=spec.index_name,
        )
    assert_never(spec)


def _dialog_to_spec(d: MiniDialog) -> AnyDialogSpec:
    vdeps = list(getattr(d, "variable_dependencies", []) or [])

    if isinstance(d, FunctionalDialog):
        return FunctionalDialogSpec(
            id=d.dialog_id,
            moves=d.moves,
            dependencies=list(d.dependencies),
            functional_type=d.type.value,
        )
    if isinstance(d, NarrativeDialog):
        return NarrativeDialogSpec(
            id=d.dialog_id,
            moves=d.moves,
            dependencies=list(d.dependencies),
            variable_dependencies=vdeps,
            thread=d.thread,
            position=d.position,
        )
    if isinstance(d, ChitchatDialog):
        return ChitchatDialogSpec(
            id=d.dialog_id,
            moves=d.moves,
            dependencies=list(d.dependencies),
            variable_dependencies=vdeps,
            topics=list(d.topics),
        )
    if isinstance(d, LLMMiniDialog):
        return LLMDialogSpec(
            id=d.dialog_id,
            moves=d.moves,
            dependencies=list(d.dependencies),
            variable_dependencies=vdeps,
            prompt=d.prompt,
            max_turns=d.max_turns,
            quit_phrases=list(d.quit_phrases),
            quit_signal=d.quit_signal,
            speak_first=d.speak_first,
            duration=d.duration,
            rag_enabled=d.rag_enabled,
            index_name=d.index_name,
        )
    assert_never(d)

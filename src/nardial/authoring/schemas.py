from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, BeforeValidator, Field

from nardial.moves import AnyMove, LLM_QUIT_SIGNAL


def _normalize_vdep(v):
    if isinstance(v, str):
        return {"variable": v, "required": True}
    return v


class VariableDependency(BaseModel):
    variable: str
    required: bool = True


class BaseDialogSpec(BaseModel):
    id: str
    moves: List[AnyMove] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    variable_dependencies: List[Annotated[VariableDependency, BeforeValidator(_normalize_vdep)]] = Field(
        default_factory=list
    )


class FunctionalDialogSpec(BaseDialogSpec):
    type: Literal["functional"] = "functional"
    functional_type: Literal["greeting", "farewell"]


class NarrativeDialogSpec(BaseDialogSpec):
    type: Literal["narrative"] = "narrative"
    thread: str
    position: int


class ChitchatDialogSpec(BaseDialogSpec):
    type: Literal["chitchat"] = "chitchat"
    theme: str
    topics: List[str] = Field(default_factory=list)


class LLMDialogSpec(BaseDialogSpec):
    type: Literal["llm_based"] = "llm_based"
    prompt: str
    max_turns: Optional[int] = None
    speak_first: bool = True
    duration: Optional[float] = None
    rag_enabled: bool = False
    index_name: Optional[str] = None
    quit_phrases: List[str] = Field(default_factory=list)
    quit_signal: str = LLM_QUIT_SIGNAL


AnyDialogSpec = Annotated[
    Union[FunctionalDialogSpec, NarrativeDialogSpec, ChitchatDialogSpec, LLMDialogSpec],
    Field(discriminator="type"),
]

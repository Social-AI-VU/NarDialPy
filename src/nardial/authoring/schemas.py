from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, BeforeValidator, Field

from nardial.moves import AnyMove, LLM_QUIT_SIGNAL


def _normalize_vdep(v):
    # Allow shorthand: a plain string "x" is treated as {"variable": "x", "required": True}.
    if isinstance(v, str):
        return {"variable": v, "required": True}
    return v


class VariableDependency(BaseModel):
    """A user-model variable that must be set before the dialog can run.

    Attributes
    ----------
    variable : str
        Key in the user model to check.
    required : bool
        When True (the default), the dialog is blocked unless the variable is
        present and truthy.
    """

    variable: str
    required: bool = True


class BaseDialogSpec(BaseModel):
    """Common fields shared by all dialog JSON specifications.

    Attributes
    ----------
    id : str
        Unique dialog identifier.
    moves : list[AnyMove]
        Ordered sequence of move definitions.
    dependencies : list[str]
        Dialog IDs that must be completed before this dialog is eligible.
    variable_dependencies : list[VariableDependency]
        User-model variable prerequisites.  Accepts plain strings as shorthand
        for ``{"variable": str, "required": True}``.
    """

    id: str
    moves: List[AnyMove] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    variable_dependencies: List[Annotated[VariableDependency, BeforeValidator(_normalize_vdep)]] = Field(
        default_factory=list
    )


class FunctionalDialogSpec(BaseDialogSpec):
    """JSON schema for a functional dialog (e.g. greeting or farewell).

    Attributes
    ----------
    functional_type : {"greeting", "farewell"}
        Role label used by the agenda system to select this dialog.
    """

    type: Literal["functional"] = "functional"
    functional_type: Literal["greeting", "farewell"]


class NarrativeDialogSpec(BaseDialogSpec):
    """JSON schema for a narrative dialog — one step in an ordered story thread.

    Attributes
    ----------
    thread : str
        Narrative thread name (e.g. ``"main_story"``).
    position : int
        1-based index within the thread; lower positions must run first.
    """

    type: Literal["narrative"] = "narrative"
    thread: str
    position: int


class ChitchatDialogSpec(BaseDialogSpec):
    """JSON schema for a chitchat dialog — a short topical conversation.

    Attributes
    ----------
    topics : list[str]
        Keywords used to match this dialog against the user's topics of interest.
    """

    type: Literal["chitchat"] = "chitchat"
    topics: List[str] = Field(default_factory=list)


class LLMDialogSpec(BaseDialogSpec):
    """JSON schema for an LLM-driven dialog — a free-form multi-turn conversation.

    Attributes
    ----------
    prompt : str
        System prompt passed to the LLM on every turn.
    max_turns : int, optional
        Maximum number of LLM turns before the dialog ends.
    speak_first : bool
        When True (the default) the LLM speaks before listening.
    duration : float, optional
        Wall-clock time budget in seconds for the entire exchange.
    rag_enabled : bool
        If True, retrieved snippets from the vector store augment the prompt.
    index_name : str, optional
        Vector store index to query; uses the provider default when omitted.
    quit_phrases : list[str]
        User utterances that stop the loop early.
    quit_signal : str
        Token the LLM embeds to signal it wants to end the conversation.
    """

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

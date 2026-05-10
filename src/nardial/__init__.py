"""NarDialPy — narrative dialog framework for desktop and social robots.

Public API surface.  Import from this package rather than reaching into
submodules, which may be reorganised without notice.
"""

from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState
from nardial.mini_dialogs import (
    ChitchatDialog,
    FunctionalDialog,
    FunctionalLabel,
    LLMMiniDialog,
    MiniDialog,
    NarrativeDialog,
    RunContext,
    ScriptedMiniDialog,
)
from nardial.session_manager import SessionManager
from nardial.user_model import UserModel

__all__ = [
    # Core session
    "SessionManager",
    "ConversationAgent",
    "ConversationState",
    # Dialog types
    "MiniDialog",
    "ScriptedMiniDialog",
    "NarrativeDialog",
    "ChitchatDialog",
    "FunctionalDialog",
    "FunctionalLabel",
    "LLMMiniDialog",
    # Runtime context
    "RunContext",
    # State
    "UserModel",
]

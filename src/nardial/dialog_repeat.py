"""Shared repeat-prompt helpers for structured and hybrid routers."""

from __future__ import annotations

from typing import Any, Dict, List

from nardial.moves import MOVE_ANSWER_YESNO
from nardial.utils import normalize_text


def dialog_has_repeat_prompt(dialog: Any) -> bool:
    return bool(getattr(dialog, "repeatable", False)) and bool(
        list(getattr(dialog, "repeat_moves", []) or [])
    )


def user_confirmed_repeat(session_tail: List[Dict[str, Any]]) -> bool:
    """True if the latest ask_yesno answer in *session_tail* is affirmative."""
    yes_vals = {
        "yes", "y", "yeah", "yep", "sure", "please", "ok", "okay", "alright",
        "correct", "affirmative", "repeat", "go ahead",
    }
    for entry in reversed(session_tail or []):
        if entry.get("role") == "user" and entry.get("type") == MOVE_ANSWER_YESNO:
            ans = normalize_text(str(entry.get("text") or ""))
            return ans in yes_vals
    return False

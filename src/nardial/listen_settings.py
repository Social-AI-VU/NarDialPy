"""Per-listen settings, resolved from agent, recognition-type and move level.

A setting is looked up in this order (first one set wins):

1. the move in the dialog JSON, e.g. ``{"type": "ask_yesno", ..., "keyword_shortcut": false}``
2. ``InteractionConfig(listen_settings={"ask_yesno": {...}})`` for the recognition type
3. the agent-wide ``InteractionConfig`` attribute, e.g. ``InteractionConfig(keyword_shortcut=False)``
4. the defaults below
"""
from dataclasses import dataclass, fields, replace

# Recognition types that listen for speech; keys of InteractionConfig.listen_settings.
LISTEN_TYPES = ("ask_yesno", "ask_open", "ask_options", "ask_llm")


@dataclass(frozen=True)
class ListenSettings:
    # Stop listening as soon as an interim transcript matches an expected answer
    # (yes/no/don't know synonyms, or the options of ask_options).
    keyword_shortcut: bool = True
    # Only short answers take the shortcut; longer ones go to the NLU provider ("yes, but..."),
    # unless they consist entirely of expected phrases ("ik denk het niet").
    keyword_max_words: int = 3
    # Seconds a match must stay unchanged before it is accepted; a final transcript is accepted at once.
    keyword_confirm_delay: float = 0.3
    # Stop listening once a voice activity detector (InteractionOrchestrator.vad_provider) has heard
    # the user speak and then vad_silence_delay seconds of silence, instead of waiting for the NLU
    # provider's own end-of-speech detection.
    vad_endpointing: bool = False
    vad_silence_delay: float = 0.5


LISTEN_SETTING_FIELDS = tuple(f.name for f in fields(ListenSettings))

# Type checks for settings given in dialog JSON or InteractionConfig.
_SETTING_TYPES = {
    "keyword_shortcut": (bool,),
    "keyword_max_words": (int,),
    "keyword_confirm_delay": (int, float),
    "vad_endpointing": (bool,),
    "vad_silence_delay": (int, float),
}


def listen_settings_from_dict(data: dict) -> dict:
    """Return the listen settings present in a move dict."""
    return {name: data[name] for name in LISTEN_SETTING_FIELDS if name in data}


def validate_listen_settings(data: dict, where: str) -> list[str]:
    """Return errors for listen settings in ``data`` with the wrong type or value."""
    errs = []
    for name, value in listen_settings_from_dict(data).items():
        types = _SETTING_TYPES[name]
        # bool is a subclass of int, so True must not pass as a number
        if (isinstance(value, bool) and bool not in types) or not isinstance(value, types):
            errs.append(f"{where}.{name} must be {' or '.join(t.__name__ for t in types)}")
        elif name == "keyword_max_words" and value < 1:
            errs.append(f"{where}.{name} must be at least 1")
        elif name in ("keyword_confirm_delay", "vad_silence_delay") and value < 0:
            errs.append(f"{where}.{name} must not be negative")
    return errs


def resolve_listen_settings(agent: dict, per_type: dict | None, listen_type: str | None,
                            move: dict | None = None) -> ListenSettings:
    """Combine agent-wide, per recognition type and per move settings; later levels win."""
    settings = replace(ListenSettings(), **{k: v for k, v in agent.items() if v is not None})
    if per_type and listen_type in per_type:
        settings = replace(settings, **listen_settings_from_dict(per_type[listen_type]))
    if move:
        settings = replace(settings, **listen_settings_from_dict(move))
    return settings

import re
import string


def normalize_text(value) -> str:
    """
    Lowercase, trim, and collapse internal whitespace.

    Use for intent names, user utterance matching, and routing.
    """
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def normalize_text_for_cache_key(text: str) -> str:
    """
    Lowercase, trim, and remove punctuation.

    Use for deterministic cache keys (e.g. TTS phrase hashing).
    """
    if not text:
        return ""
    t = str(text).strip().lower()
    t = t.translate(str.maketrans("", "", string.punctuation))
    return t

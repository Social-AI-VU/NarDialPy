"""Keyword matching of (interim) transcripts against expected answers.

Used for the keyword shortcut, which stops listening as soon as a short answer such as
"ja" or "no" is recognised instead of waiting for the NLU provider's end-of-speech detection.
"""
import re
from typing import Iterable, Mapping

from nardial.providers.nlu import INTENT_YESNO_YES, INTENT_YESNO_NO, INTENT_YESNO_DONTKNOW

# Default yes/no/don't know synonyms per language. Longer phrases win over the words they
# contain, so "zeker niet" is a no and "weet ik niet" a don't know.
YESNO_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "en": {
        INTENT_YESNO_YES: [
            "yes", "yeah", "yep", "yup", "yes please", "sure", "of course", "ok", "okay", "correct",
            "right", "absolutely", "definitely", "certainly", "i do", "i think so",
        ],
        INTENT_YESNO_NO: [
            "no", "nope", "nah", "not really", "never", "no way", "not at all", "i don't", "wrong",
            "no thanks", "of course not", "absolutely not", "definitely not", "certainly not",
            "i don't think so",
        ],
        INTENT_YESNO_DONTKNOW: [
            "i don't know", "don't know", "dont know", "not sure", "i'm not sure", "maybe", "perhaps",
            "dunno", "no idea", "idk",
        ],
    },
    "nl": {
        INTENT_YESNO_YES: [
            "ja", "jazeker", "jawel", "ja hoor", "oké", "oke", "ok", "okay", "prima", "goed", "natuurlijk",
            "tuurlijk", "absoluut", "zeker", "zeker weten", "klopt", "graag", "inderdaad",
            "denk het wel", "ik denk het wel", "denk van wel", "volgens mij wel",
        ],
        INTENT_YESNO_NO: [
            "nee", "neen", "nah", "nope", "nee hoor", "niet", "nooit", "liever niet", "zeker niet",
            "helemaal niet", "natuurlijk niet", "absoluut niet", "niet echt", "echt niet",
            "denk het niet", "ik denk het niet", "denk van niet", "volgens mij niet",
        ],
        INTENT_YESNO_DONTKNOW: [
            "weet ik niet", "weet niet", "ik weet het niet", "weet het niet", "geen idee", "geen flauw idee",
            "twijfel", "ik twijfel", "misschien",
        ],
    },
}


def yesno_keywords(language: str | None, overrides: Mapping[str, Iterable[str]] | None = None
                   ) -> dict[str, list[str]]:
    """Yes/no/don't know synonyms for ``language`` ("nl", "en", "nl-NL", ...).

    ``overrides`` replaces the list of each intent it names, e.g. to add a phrase:
    ``{INTENT_YESNO_NO: YESNO_KEYWORDS["nl"][INTENT_YESNO_NO] + ["heb ik niet"]}``.
    Unknown languages have no defaults.
    """
    base = (language or "").replace("_", "-").split("-")[0].lower()
    keywords = {intent: list(words) for intent, words in YESNO_KEYWORDS.get(base, {}).items()}
    for intent, words in (overrides or {}).items():
        keywords[intent] = list(words)
    return keywords


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^\w'\s]", " ", text.lower().replace("’", "'")).split()


def match_keywords(text: str, keywords: Mapping[str, Iterable[str]], max_words: int | None = None) -> str | None:
    """Return the label whose phrases occur in ``text``, or None.

    Phrases match whole words, longest phrase first; words used by a match cannot match again.
    Returns None when nothing matches, when phrases of different labels match ("yeah no"),
    or when ``text`` has more than ``max_words`` words that are not all part of matched
    phrases ("ik denk het niet" matches, "ja maar eigenlijk niet" does not).
    """
    tokens = _tokens(text)
    if not tokens:
        return None
    phrases = sorted(((tuple(_tokens(p)), label) for label, ps in keywords.items() for p in ps),
                     key=lambda item: len(item[0]), reverse=True)
    used = [False] * len(tokens)
    labels = set()
    for phrase, label in phrases:
        n = len(phrase)
        if n == 0:
            continue
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i:i + n]) == phrase and not any(used[i:i + n]):
                used[i:i + n] = [True] * n
                labels.add(label)
    if max_words is not None and len(tokens) > max_words and not all(used):
        return None
    return labels.pop() if len(labels) == 1 else None

from nardial.providers.nlu import (
    NLUProvider, NLUResult,
    INTENT_YESNO_YES, INTENT_YESNO_NO, INTENT_YESNO_DONTKNOW,
)

_YES = {"yes", "ja", "yep", "yeah", "yup", "correct", "right"}
_NO = {"no", "nee", "nope", "nah", "wrong"}
_DONTKNOW = {"don't know", "dont know", "not sure", "maybe", "idk", "dunno"}


class WrittenKeywordNLUProvider(NLUProvider):
    """
    Keyboard-input NLU provider with simple keyword-to-intent mapping.
    Used for local demos and tests that run without Dialogflow credentials.
    """

    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult:
        try:
            line = input("Your reply: ").strip()
        except EOFError:
            return NLUResult(transcript="", intent=None)

        if not line:
            return NLUResult(transcript="", intent=None)

        return NLUResult(transcript=line, intent=self._match_intent(line.lower()))

    @staticmethod
    def _match_intent(text: str) -> str | None:
        for phrase in _DONTKNOW:
            if phrase in text:
                return INTENT_YESNO_DONTKNOW
        words = set(text.split())
        if words & _YES:
            return INTENT_YESNO_YES
        if words & _NO:
            return INTENT_YESNO_NO
        return None

from nardial.providers.nlu import NLUProvider, NLUResult
from nardial.providers.nlu.keywords import YESNO_KEYWORDS, match_keywords

# The keyboard provider has no language setting, so it accepts the synonyms of every language.
_KEYWORDS: dict[str, list[str]] = {}
for _language_keywords in YESNO_KEYWORDS.values():
    for _intent, _words in _language_keywords.items():
        _KEYWORDS.setdefault(_intent, []).extend(_words)


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

    def cancel(self) -> None:
        pass

    @staticmethod
    def _match_intent(text: str) -> str | None:
        return match_keywords(text, _KEYWORDS)

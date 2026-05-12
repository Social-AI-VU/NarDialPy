from nardial.providers.llm import LLMProvider, Message


class EchoLLMProvider(LLMProvider):
    """Returns the last user message — used in tests."""

    def complete(self, messages: list[Message], system_prompt: str = "") -> str:
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        return ""

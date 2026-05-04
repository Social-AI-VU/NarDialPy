from os import environ

from sic_framework.services.llm.openai_gpt import GPT
from sic_framework.services.llm import GPTConf, GPTRequest

from nardial.providers.llm import Message


class OpenAIGPTProvider:
    def __init__(self, api_key: str | None = None):
        key = api_key or environ["OPENAI_API_KEY"]
        self._gpt = GPT(conf=GPTConf(openai_key=key))

    def complete(self, messages: list[Message], system_prompt: str = "") -> str:
        if not messages:
            return ""
        *history, last = messages
        prompt = last.content if last.role == "user" else None
        context = [{"role": m.role, "content": m.content} for m in history] or None
        resp = self._gpt.request(GPTRequest(
            prompt=prompt,
            context_messages=context,
            system_message=system_prompt or None,
        ))
        return (resp.response or "").strip()

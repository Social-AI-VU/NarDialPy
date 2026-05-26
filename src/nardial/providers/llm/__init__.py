from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Message:
    role: str      # "user" | "assistant" | "system"
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    def complete(self, messages: list[Message], system_prompt: str = "") -> str: ...

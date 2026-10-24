import math
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    mime: str


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    parts: list[str | ImagePart]


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    estimated: bool


class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        json_schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> LLMResult: ...

    def list_models(self) -> list[str]: ...


# Thinking runs share the output budget, so give them room unless the caller asks for more.
THINKING_MIN_MAX_TOKENS = 16000

SCHEMA_INSTRUCTION = "Respond only with JSON matching this schema: "


def estimate_tokens(chars: int) -> int:
    return math.ceil(chars / 4)


def input_chars(system: str, messages: list[Message]) -> int:
    total = len(system)
    for m in messages:
        total += sum(len(p) for p in m.parts if isinstance(p, str))
    return total


def resolve_usage(in_tok: object, out_tok: object, system: str, messages: list[Message], text: str) -> LLMResult:
    """Keep every real count; estimate (chars/4) only the missing one."""
    real_in = in_tok if isinstance(in_tok, int) and not isinstance(in_tok, bool) else None
    real_out = out_tok if isinstance(out_tok, int) and not isinstance(out_tok, bool) else None
    estimated = real_in is None or real_out is None
    return LLMResult(
        text,
        real_in if real_in is not None else estimate_tokens(input_chars(system, messages)),
        real_out if real_out is not None else estimate_tokens(len(text)),
        estimated,
    )

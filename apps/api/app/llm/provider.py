from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class LLMProvider(ABC):
    """V1 cloud-provider boundary. Business services must not import vendor SDKs."""

    @abstractmethod
    async def chat(self, *, messages: list[dict[str, Any]]) -> str:
        """普通对话补全，返回首条回复文本。"""
        raise NotImplementedError

    @abstractmethod
    async def chat_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self) -> bool:
        raise NotImplementedError

    def supports_stream(self) -> bool:
        return False

    def chat_stream(
        self, *, messages: list[dict[str, Any]]
    ) -> AsyncIterator[tuple[str, str]]:
        """流式补全:yield (类型, 增量)。类型 thinking=思维链,text=正文。默认不支持。"""
        raise NotImplementedError
        yield "", ""  # pragma: no cover

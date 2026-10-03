from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """V1 cloud-provider boundary. Business services must not import vendor SDKs."""

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

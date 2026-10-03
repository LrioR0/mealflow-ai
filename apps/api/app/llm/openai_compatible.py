from typing import Any

from openai import AsyncOpenAI

from app.llm.provider import LLMProvider


class OpenAICompatibleCloudProvider(LLMProvider):
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: int) -> None:
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)

    async def chat_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="auto",
            temperature=0.1,
        )
        message = response.choices[0].message
        return message.model_dump(exclude_none=True)

    async def healthcheck(self) -> bool:
        try:
            await self.client.models.list()
        except Exception:
            return False
        return True

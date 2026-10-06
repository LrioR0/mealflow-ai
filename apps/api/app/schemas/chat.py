"""对话工作台接口契约(SSE 五阶段协议见 docs/V2改造方案-对话式Agent工作台.md §8.1)。"""

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str = "home-workspace"
    site_id: str = "home-kitchen"
    meal_service_id: str = "home-lunch"
    message: str = Field(min_length=1, max_length=2000)


class ChatMessageView(BaseModel):
    id: str
    role: str
    content: str
    thinking_text: str | None = None
    run_id: str | None = None


class ChatSessionView(BaseModel):
    session_id: str
    title: str
    messages: list[ChatMessageView]

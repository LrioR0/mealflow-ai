"""对话工作台路由:SSE 流式(P0 主入口)、非流式兼容、会话恢复。"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.llm.model_catalog import list_model_profiles, resolve_model_profile
from app.schemas.chat import ChatStreamRequest
from app.services import chat_service

router = APIRouter(prefix="/agent/chat", tags=["chat"])


@router.get("/models")
def list_chat_models() -> list[dict[str, object]]:
    """返回前端可选择的模型，不返回任何 API Key。"""
    return [profile.public_view() for profile in list_model_profiles(get_settings())]


@router.post("/stream")
async def stream_chat(payload: ChatStreamRequest) -> StreamingResponse:
    """SSE 流式对话:status(动态工具步骤) / thinking / text / candidates 交错产出 → done。"""
    _validate_model(payload)
    return StreamingResponse(
        chat_service.stream_chat(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 反向代理(nginx)默认会缓冲响应,该头明确关闭,SSE 才能实时到达
            "X-Accel-Buffering": "no",
        },
    )


@router.post("")
async def chat_once(payload: ChatStreamRequest) -> dict:
    """非流式兼容:聚合同一条事件流,返回最终回复(测试与降级用)。"""
    _validate_model(payload)
    result: dict = {
        "session_id": None,
        "text": "",
        "plan": None,
        "questions": [],
        "tool_calls": [],
        "needs_input": False,
    }
    buffer = ""
    async for chunk in chat_service.stream_chat(payload):
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            event_name = None
            data_raw = ""
            for line in block.splitlines():
                if line.startswith("event: "):
                    event_name = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    data_raw = line.removeprefix("data: ")
            if event_name is None:
                continue
            data = json.loads(data_raw)
            if event_name == "done":
                result["session_id"] = data.get("session_id")
                result["model_id"] = data.get("model_id")
                result["model_label"] = data.get("model_label")
            elif event_name == "text":
                result["text"] += data.get("delta", "")
            elif event_name == "text_reset":
                result["text"] = ""
            elif event_name == "plan":
                result["plan"] = data
            elif event_name == "questions":
                result["questions"] = data.get("items", [])
                result["needs_input"] = data.get("needs_input", False)
            elif event_name == "tool_call":
                result["tool_calls"].append(data)
            elif event_name == "error":
                result["error"] = data.get("message")
    return result


def _validate_model(payload: ChatStreamRequest) -> None:
    if payload.model_id is None:
        return
    profiles = list_model_profiles(get_settings())
    if not any(item.id == payload.model_id for item in profiles):
        raise HTTPException(status_code=400, detail="未知模型，请刷新模型列表")
    if resolve_model_profile(get_settings(), payload.model_id) is None:
        raise HTTPException(status_code=400, detail="该模型尚未配置，请选择可用模型")


@router.get("/sessions")
def list_sessions(workspace_id: str = "home-workspace") -> list[dict]:
    """会话列表:最近更新倒序,供前端历史会话抽屉。"""
    return [item.model_dump() for item in chat_service.list_sessions(workspace_id)]


@router.get("/sessions/count")
def count_workspace_sessions(
    workspace_id: str = "home-workspace",
    exclude_session_id: str | None = None,
) -> dict[str, int]:
    """返回清空历史操作将影响的准确会话数量。"""
    return {
        "count": chat_service.count_workspace_sessions(workspace_id, exclude_session_id)
    }


@router.delete("/sessions")
def delete_workspace_sessions(
    workspace_id: str = "home-workspace",
    exclude_session_id: str | None = None,
) -> dict[str, int]:
    """清空工作区历史会话；exclude_session_id 用于保留当前对话。"""
    return chat_service.delete_workspace_sessions(workspace_id, exclude_session_id)


@router.delete("/{session_id}")
def delete_session(session_id: str) -> dict:
    """删除会话及其全部消息,不可恢复。"""
    if not chat_service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True}


@router.get("/{session_id}")
def get_session(session_id: str) -> dict:
    view = chat_service.get_session_view(session_id)
    if view is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return view.model_dump()

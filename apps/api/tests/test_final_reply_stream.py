import pytest

from app.agent.conversation import _stream_final_reply


class StreamingProvider:
    def __init__(self, chunks, failure=False):
        self.chunks = chunks
        self.failure = failure

    def supports_stream(self):
        return True

    async def chat_stream(self, *, messages):
        for chunk in self.chunks:
            yield "text", chunk
        if self.failure:
            raise RuntimeError("stream interrupted")


@pytest.mark.asyncio
async def test_reply_emits_deltas_before_stream_finishes():
    provider = StreamingProvider(["准备食材。" * 30, "开始烹饪。" * 30])
    stream = _stream_final_reply(provider, [], "备用回答", None)
    first = await anext(stream)
    assert first["type"] == "text_delta"
    remaining = [event async for event in stream]
    text = first["delta"] + "".join(
        event["delta"] for event in remaining if event["type"] == "text_delta"
    )
    assert text == "".join(provider.chunks)
    assert remaining[-1] == {"type": "reply_ready", "text": text}


@pytest.mark.asyncio
async def test_split_protocol_is_blocked_and_partial_reply_is_reset():
    provider = StreamingProvider(["正常说明。" * 30, "<|DS", "ML|tool_calls>"])
    events = [event async for event in _stream_final_reply(provider, [], "备用回答", None)]
    visible = "".join(event["delta"] for event in events if event["type"] == "text_delta")
    assert "<|DS" not in visible
    assert "tool_calls" not in visible
    assert {"type": "text_reset"} in events
    assert events[-1] == {"type": "reply_ready", "text": "备用回答"}


@pytest.mark.asyncio
async def test_stream_error_restores_fallback_instead_of_appending_it():
    provider = StreamingProvider(["半截回答。" * 30], failure=True)
    events = [event async for event in _stream_final_reply(provider, [], "备用回答", None)]
    assert events[-2] == {"type": "text_reset"}
    assert events[-1] == {"type": "reply_ready", "text": "备用回答"}

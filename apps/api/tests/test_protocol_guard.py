from app.llm.protocol_guard import contains_protocol_leak, normalize_model_message


def test_dsml_alias_becomes_recipe_detail() -> None:
    message = normalize_model_message(
        {
            "role": "assistant",
            "content": """<|DSML|invoke name="get_recipe_by_id">
<|DSML|parameter name="recipe" string="true">家常汤面</|DSML|parameter>
</|DSML|invoke>""",
        }
    )
    call = message["tool_calls"][0]["function"]
    assert call["name"] == "get_recipe_detail"
    assert "家常汤面" in call["arguments"]
    assert message["content"] == ""


def test_unknown_tool_and_invalid_arguments_are_dropped() -> None:
    message = normalize_model_message(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "bad",
                    "type": "function",
                    "function": {"name": "delete_inventory", "arguments": "{}"},
                },
                {
                    "id": "empty",
                    "type": "function",
                    "function": {"name": "get_recipe_detail", "arguments": "{}"},
                },
            ],
        }
    )
    assert message["tool_calls"] == []


def test_protocol_markers_are_detected() -> None:
    assert contains_protocol_leak("先看 <|DSML|tool_calls>")
    assert contains_protocol_leak('{"tool_calls": []}')
    assert not contains_protocol_leak("今晚吃番茄炒蛋。")

"""Tests build_safe_messages: emits flat shape for legacy rows (tool_calls
NULL) and OpenAI-style structured shape for new rows. Mixed history works."""
from routers.chat import build_safe_messages


class _FakeMsg:
    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


def test_legacy_row_emits_flat_shape():
    """An assistant row with tool_calls=NULL emits one flat {role, content}."""
    msgs = [_FakeMsg("assistant", "old narrative + > **Tool:** mimicry", tool_calls=None)]
    out = build_safe_messages(msgs)
    assert out == [{"role": "assistant", "content": "old narrative + > **Tool:** mimicry"}]


def test_new_row_emits_structured_assistant_plus_tool_messages():
    """An assistant row with populated tool_calls emits:
       1. {role: "assistant", content, tool_calls: [{function: ...}, ...]}
       2. one {role: "tool", name, content: result} per call, in order."""
    msgs = [_FakeMsg(
        "assistant",
        "Here are the results.",
        tool_calls=[
            {"name": "dns_lookup", "args": {"domain": "x.com"}, "result": "1.2.3.4"},
            {"name": "execute_ping", "args": {"hostname": "1.2.3.4"}, "result": "Ping ok"},
        ],
    )]
    out = build_safe_messages(msgs)
    assert out == [
        {
            "role": "assistant",
            "content": "Here are the results.",
            "tool_calls": [
                {"function": {"name": "dns_lookup", "arguments": {"domain": "x.com"}}},
                {"function": {"name": "execute_ping", "arguments": {"hostname": "1.2.3.4"}}},
            ],
        },
        {"role": "tool", "name": "dns_lookup", "content": "1.2.3.4"},
        {"role": "tool", "name": "execute_ping", "content": "Ping ok"},
    ]


def test_mixed_history_per_row_shape():
    """Mixed: legacy user, legacy assistant, new assistant. Each row gets
    its own shape; no cross-contamination."""
    msgs = [
        _FakeMsg("user", "hi"),
        _FakeMsg("assistant", "old style", tool_calls=None),
        _FakeMsg("user", "follow up"),
        _FakeMsg("assistant", "new synthesis", tool_calls=[
            {"name": "dns_lookup", "args": {"domain": "y.com"}, "result": "5.6.7.8"},
        ]),
    ]
    out = build_safe_messages(msgs)
    assert len(out) == 5  # 4 messages + 1 tool message
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1] == {"role": "assistant", "content": "old style"}
    assert out[2] == {"role": "user", "content": "follow up"}
    assert out[3]["role"] == "assistant"
    assert out[3]["tool_calls"][0]["function"]["name"] == "dns_lookup"
    assert out[4] == {"role": "tool", "name": "dns_lookup", "content": "5.6.7.8"}


def test_empty_history_returns_empty_list():
    assert build_safe_messages([]) == []


def test_malformed_tool_calls_falls_back_to_flat():
    """A row with non-list garbage in tool_calls is treated like a legacy row."""
    msgs = [_FakeMsg("assistant", "x", tool_calls="not-a-list")]
    out = build_safe_messages(msgs)
    assert out == [{"role": "assistant", "content": "x"}]

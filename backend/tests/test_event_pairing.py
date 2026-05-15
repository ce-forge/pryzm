"""Tests the route handler's tool_call ↔ tool_result pairing logic in isolation.

The accumulator pairs by ORDER, not by name — handles two calls to the same
tool within one turn correctly. A tool_result always completes the most-
recent open (result=None) entry."""
from routers.chat import _accumulate_tool_event


def test_single_call_pairs_with_result():
    acc: list = []
    _accumulate_tool_event(acc, {"type": "tool_call", "name": "dns_lookup", "args": {"domain": "x.com"}})
    assert acc == [{"name": "dns_lookup", "args": {"domain": "x.com"}, "result": None}]

    _accumulate_tool_event(acc, {"type": "tool_result", "name": "dns_lookup", "result": "OK"})
    assert acc == [{"name": "dns_lookup", "args": {"domain": "x.com"}, "result": "OK"}]


def test_same_tool_called_twice_pairs_by_order():
    """Two consecutive tool_call/tool_result pairs for the same tool —
    each result attaches to its own call by ORDER, not by name."""
    acc: list = []
    _accumulate_tool_event(acc, {"type": "tool_call", "name": "search_knowledge_base", "args": {"queries": ["a"]}})
    _accumulate_tool_event(acc, {"type": "tool_result", "name": "search_knowledge_base", "result": "RESULT_A"})
    _accumulate_tool_event(acc, {"type": "tool_call", "name": "search_knowledge_base", "args": {"queries": ["b"]}})
    _accumulate_tool_event(acc, {"type": "tool_result", "name": "search_knowledge_base", "result": "RESULT_B"})

    assert len(acc) == 2
    assert acc[0]["args"] == {"queries": ["a"]} and acc[0]["result"] == "RESULT_A"
    assert acc[1]["args"] == {"queries": ["b"]} and acc[1]["result"] == "RESULT_B"


def test_orphan_tool_result_logged_and_dropped():
    """A tool_result with no preceding open call is a no-op (and would WARN
    in production; the test just confirms acc is unchanged)."""
    acc: list = []
    _accumulate_tool_event(acc, {"type": "tool_result", "name": "ghost", "result": "X"})
    assert acc == []


def test_finalize_drops_unpaired_calls():
    """If a stream disconnects mid-execution and a tool_call has no result,
    the finalize helper drops the unpaired entry."""
    from routers.chat import _finalize_tool_calls
    acc = [
        {"name": "a", "args": {}, "result": "RESULT_A"},
        {"name": "b", "args": {}, "result": None},  # disconnected mid-execution
    ]
    final = _finalize_tool_calls(acc)
    assert final == [{"name": "a", "args": {}, "result": "RESULT_A"}]

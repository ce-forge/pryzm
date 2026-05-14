"""Fixed prompt set for the LLM perf benchmark.

Five classes covering Pryzm's representative workload:

  short_q       — a one-line factual question; tier-1 territory
  medium_q      — a couple of paragraphs of context + a question
  code_task    — code-shaped prompt with a fence, expects a code answer
  tool_use      — a question that should trigger a tool call (network/RAG)
  rag_inline    — the prompt asks the assistant to summarise file content
                  embedded inline (Phase A doesn't upload a file; we paste a
                  ~500-char synthetic blob to exercise the longer-context path)

Each class has 3 prompts. The bench harness sends all 15 (5x3) sequentially
with N repeats per prompt (default N=3 per harness arg)."""

PROMPTS: dict[str, list[str]] = {
    "short_q": [
        "What is my IP address?",
        "Who is the CEO of Apple?",
        "What does CIDR stand for?",
    ],
    "medium_q": [
        "Explain in two paragraphs what DNS is and why caching matters at the resolver level.",
        "Summarize the difference between RAID 1, RAID 5, and RAID 10 for a small office NAS deployment.",
        "Walk me through what happens when I type a URL into a browser and press Enter.",
    ],
    "code_task": [
        "Write a Python function that takes a list of integers and returns only the prime numbers. Include a docstring.\n\n```python\ndef primes(nums):\n    pass\n```",
        "Refactor the following snippet to be more idiomatic:\n\n```python\nresult = []\nfor i in range(len(items)):\n    if items[i].active:\n        result.append(items[i].name)\n```",
        "Show me a bash one-liner that finds all .log files modified in the last hour under /var/log and prints them sorted by size.",
    ],
    "tool_use": [
        "Check whether port 22 is open on 127.0.0.1.",
        "Look up the documentation we have on attack-surface checklists.",
        "What does our knowledge base say about responding to an account-lockout incident?",
    ],
    "rag_inline": [
        # ~500-char synthetic config blob the model will be asked to summarise.
        "Summarise this firewall rules file in a sentence:\n\n"
        + "ACCEPT tcp -- anywhere anywhere tcp dpt:ssh\n"
        * 8
        + "REJECT tcp -- anywhere anywhere tcp dpt:telnet\n",
        "Summarise this access log:\n\n"
        + "192.0.2.1 - - [10/Oct/2025:13:55:36 +0000] \"GET /api/health HTTP/1.1\" 200 12\n"
        * 10,
        "Summarise this SLA:\n\n"
        + "Service availability target: 99.9%. "
        + "Incident response: P1 30min, P2 2h, P3 next business day. "
        * 5,
    ],
}

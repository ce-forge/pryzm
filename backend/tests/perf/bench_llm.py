"""LLM perf benchmark harness.

Sends each prompt in tests/perf/prompts.py against a running Pryzm backend
N times. For each call, parses the `usage` block from the final SSE chunk
emitted by /analyze (see Task 6 in the Phase A plan). Aggregates min /
median / p95 / max for ttft_ms, duration_ms, tokens_per_sec per prompt
class. Prints a markdown table to stdout; optionally writes the same to a
file under tests/perf/results/ for later diff against the post-swap run.

Usage:
    cd backend
    ./venv/bin/python tests/perf/bench_llm.py \\
        --backend http://127.0.0.1:8000 \\
        --workspace personal \\
        --token "$(grep PRYZM_API_TOKEN ../.env | cut -d= -f2)" \\
        --repeats 3 \\
        --label ollama-baseline-2026-05-14
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

from prompts import PROMPTS


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _send_one(
    client: httpx.Client, backend: str, token: str, workspace: str, prompt: str
) -> dict | None:
    """Sends one prompt to /analyze, returns the usage dict from the final chunk
    (or None on parse / network failure)."""
    url = f"{backend}/analyze?workspace={workspace}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"prompt": prompt, "session_id": None, "attachments": []}

    last_usage = None
    with client.stream("POST", url, json=body, headers=headers, timeout=180.0) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("done") and isinstance(obj.get("usage"), dict):
                last_usage = obj["usage"]
    return last_usage


def _aggregate(records: list[dict]) -> dict:
    """records: a list of usage dicts. Returns aggregate stats."""
    if not records:
        return {"count": 0}
    ttfts = [r["ttft_ms"] for r in records]
    durs = [r["duration_ms"] for r in records]
    tps = [r["tokens_per_sec"] for r in records]
    return {
        "count": len(records),
        "ttft_ms_med": int(statistics.median(ttfts)),
        "ttft_ms_p95": int(_percentile(ttfts, 0.95)),
        "duration_ms_med": int(statistics.median(durs)),
        "duration_ms_p95": int(_percentile(durs, 0.95)),
        "tps_med": round(statistics.median(tps), 2),
        "tps_max": round(max(tps), 2),
    }


def _markdown_table(label: str, by_class: dict[str, dict]) -> str:
    lines = [
        f"# LLM Perf Benchmark — {label}",
        "",
        "| Prompt class | N | TTFT (ms) median | TTFT (ms) p95 | Duration (ms) median | Duration (ms) p95 | TPS median | TPS max |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cls, stats in by_class.items():
        if stats["count"] == 0:
            lines.append(f"| {cls} | 0 | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {cls} | {stats['count']} | {stats['ttft_ms_med']} | {stats['ttft_ms_p95']} | "
            f"{stats['duration_ms_med']} | {stats['duration_ms_p95']} | "
            f"{stats['tps_med']} | {stats['tps_max']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--workspace",
        default="it_copilot",
        help=(
            "Builtin workspace whose tool set the prompts are designed for. "
            "Default it_copilot exposes check_port + search_knowledge_base, which "
            "the tool_use and rag_inline prompt classes need to fire actual tool "
            "calls. Sending them to a workspace without those tools collapses "
            "those classes into plain text generation (misleadingly fast)."
        ),
    )
    parser.add_argument("--token", required=True, help="PRYZM_API_TOKEN value")
    parser.add_argument("--repeats", type=int, default=3, help="N repeats per prompt")
    parser.add_argument("--label", required=True, help="Label for the results file (e.g. 'ollama-baseline')")
    args = parser.parse_args()

    by_class: dict[str, list[dict]] = {cls: [] for cls in PROMPTS}

    print(f"[bench_llm] backend={args.backend} workspace={args.workspace} repeats={args.repeats}")
    with httpx.Client(http2=False) as client:
        for cls, prompts in PROMPTS.items():
            for prompt in prompts:
                for i in range(args.repeats):
                    t0 = time.perf_counter()
                    try:
                        usage = _send_one(client, args.backend, args.token, args.workspace, prompt)
                    except Exception as e:
                        print(f"  [{cls}] prompt {prompt[:30]!r} run {i+1}: ERROR {e}")
                        continue
                    elapsed = time.perf_counter() - t0
                    if usage is None:
                        print(f"  [{cls}] prompt {prompt[:30]!r} run {i+1}: no usage block (elapsed={elapsed:.1f}s)")
                        continue
                    by_class[cls].append(usage)
                    print(
                        f"  [{cls}] run {i+1}: model={usage['model']} "
                        f"tokens={usage['completion_tokens']} ttft={usage['ttft_ms']}ms "
                        f"dur={usage['duration_ms']}ms tps={usage['tokens_per_sec']}"
                    )

    aggregated = {cls: _aggregate(records) for cls, records in by_class.items()}
    md = _markdown_table(args.label, aggregated)

    out_path = Path(__file__).parent / "results" / f"{args.label}.md"
    out_path.write_text(md)
    print()
    print(md)
    print(f"[bench_llm] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

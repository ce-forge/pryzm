# LLM Perf Benchmark — llama-swap-2026-05-14

| Prompt class | N | TTFT (ms) median | TTFT (ms) p95 | Duration (ms) median | Duration (ms) p95 | TPS median | TPS max |
|---|---|---|---|---|---|---|---|
| short_q | 9 | 33 | 40 | 605 | 1821 | 139.01 | 140.26 |
| medium_q | 9 | 28 | 36 | 6434 | 8478 | 134.06 | 138.55 |
| code_task | 9 | 11 | 36 | 3413 | 5695 | 124.65 | 128.21 |
| tool_use | 9 | 262 | 268 | 1011 | 1252 | 125.5 | 137.32 |
| rag_inline | 9 | 12 | 79 | 2121 | 4144 | 127.24 | 135.29 |

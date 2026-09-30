## Accuracy

| model | system | overall | answerable | refused unanswerable | p50 latency | mean LLM calls | mean tool calls | tokens / q | cost / q |
|---|---|---|---|---|---|---|---|---|---|
| qwen3-4b-q4 | zero_shot | 15/50 (30%) | 17% | 100% | 14.8 s | 1.0 | 0.0 | 904 | $0.0000 |
| qwen3-4b-q4 | rag | 35/50 (70%) | 64% | 100% | 20.4 s | 1.0 | 0.0 | 1414 | $0.0000 |
| qwen3-4b-q4 | agent | 25/50 (50%) | 48% | 62% | 90.2 s | 3.0 | 2.0 | 7292 | $0.0000 |

## Accuracy by question category

| model | system | date | filter | group | join | nested | unanswerable |
|---|---|---|---|---|---|---|---|
| qwen3-4b-q4 | zero_shot | 0/8 | 4/10 | 1/10 | 1/8 | 1/6 | 8/8 |
| qwen3-4b-q4 | rag | 5/8 | 8/10 | 8/10 | 3/8 | 3/6 | 8/8 |
| qwen3-4b-q4 | agent | 0/8 | 6/10 | 9/10 | 1/8 | 4/6 | 5/8 |

## Failure taxonomy (count of wrong answers)

| model | system | blocked_by_guard | empty_result | execution_error | invented_field | refused_answerable | step_limit | unparseable_reply | wrong_collection | wrong_row_count | wrong_values |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3-4b-q4 | zero_shot | 1 | 3 | 19 | 0 | 4 | 0 | 0 | 1 | 1 | 6 |
| qwen3-4b-q4 | rag | 0 | 1 | 2 | 1 | 2 | 0 | 1 | 1 | 1 | 6 |
| qwen3-4b-q4 | agent | 0 | 1 | 0 | 1 | 3 | 2 | 6 | 1 | 3 | 8 |

## Paired comparisons (same model, same questions)

| model | A -> B | B fixed (A wrong, B right) | B broke (A right, B wrong) | net | McNemar p |
|---|---|---|---|---|---|
| qwen3-4b-q4 | zero_shot -> rag | 20 | 0 | +20 | < 0.001 |
| qwen3-4b-q4 | zero_shot -> agent | 16 | 6 | +10 | 0.052 |
| qwen3-4b-q4 | rag -> agent | 5 | 15 | -10 | 0.041 |

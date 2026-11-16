# Evaluation datasets

Question sets used by `python -m eval.run` ([Doc/eval.md](../../Doc/eval.md) §3). Files are added phase by phase:

| File | Phase | Expected reply kind |
|---|---|---|
| `facts.jsonl` | 1 | `answer` |
| `advice.jsonl`, `performance.jsonl`, `pii.jsonl` | 2 | `refusal`, `performance`, `privacy` (plus look-alike negatives) |
| `paraphrases.jsonl`, `ambiguous.jsonl`, `out_of_corpus.jsonl`, `general.jsonl`, `holdout.jsonl` | 3 | mixed |
| `help.jsonl` | 4 | `help` |
| `conversations.jsonl` | 5 | multi-turn |
| `llm_stress.jsonl` | 7 | stub LLM outputs |

## Format

One JSON object per line (UTF-8):

```json
{"id": "FACT-hdfc-mid-cap-expense_ratio", "ref": "AC1", "question": "What is the expense ratio of HDFC Mid Cap Fund?", "expect": {"kind": "answer", "scheme_id": "hdfc-mid-cap", "topic": "expense_ratio", "contains": ["0.73"]}}
```

Multi-turn cases use `"turns": [{"question": ..., "expect": {...}}, ...]` instead of `question` / `expect`.

## Rules

- `id` matches an ID in [Doc/edge-case.md](../../Doc/edge-case.md) or names the acceptance criterion it tests.
- Never edit an existing case to make a score pass; add a new case instead.
- `holdout.jsonl` is never used for tuning (Doc/eval.md §3).
- No real personal data: use made-up PANs, phone numbers and emails only.

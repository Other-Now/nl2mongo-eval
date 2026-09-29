# Interview notes: nl2mongo-eval

These are short notes for a 1–2 day read. Each point names where it lives in the code.

## 1. The question the project answers
Can an LLM answer data questions by writing MongoDB aggregation pipelines? And do retrieval (RAG) or an agent with tools improve on a plain prompt by enough to justify their cost?

The answer is in `REPORT.md` as a recommendation, not a demo.

## 2. How accuracy is measured (`nl2mongo/score.py`)
- **Execution accuracy.** Run the model's pipeline, run the gold pipeline, and compare the results. It is objective, so no LLM judge is involved.
- Field names are ignored, so `count`, `n` and `total` are all accepted. Each row is compared as a multiset of scalar values, and a predicted row may carry extra values, such as an `_id` it forgot to drop.
- Row counts must match exactly. Order is checked only when the question asks for it (top-N).
- Numbers are rounded to 2 decimal places, and dates are compared in UTC.
- **Known weakness:** it's lenient about extra columns, so a pipeline that returns every field of the right rows passes. That's acceptable here because questions ask for specific values.

## 3. The gold set (`eval/build_questions.py`)
- 50 questions: 10 filter, 10 group, 8 join, 8 date, 6 nested/array, and 8 that must be refused.
- There are 8 refusals: 3 ask for secrets (password, hash, JWT) and 5 ask for data that doesn't exist (ticket sales, watchlist, age, showtimes, budget).
- Every gold pipeline is hand-written, and `eval/check_gold.py` runs it. It fails when a top-N question has a tie at the cutoff, because then two answers would both be right. G07 was changed from top 3 to top 2 for that reason.
- **Traps that real data sets:**
  - `state` holds "CA", not "California".
  - `year` is a string in 37 documents.
  - 116 movies have no `genres`.
  - Three movies are titled "Titanic".
  - `movies.num_mflix_comments` disagrees with the comments collection (437 vs 161).
- CI checks that `questions.jsonl` matches its source and that every gold pipeline still returns `expect_rows` rows.

## 4. The three systems (`nl2mongo/systems.py`)
All three use the same prompt: the schema inferred from 1000 sampled documents (`schema.py`) plus the rules. So the only thing that differs is what each system adds.

| system | adds | LLM calls |
|---|---|---|
| zero_shot | nothing | 1 |
| rag | top 4 worked examples and 2 operator notes, retrieved with BM25 (`retrieve.py`) | 1 |
| agent | tools: `sample_documents`, `run_pipeline`, `submit_answer`, `refuse`, with a limit of 8 turns | 1–8 |

Why BM25 and not a vector index? The corpus is about 30 short documents, where keyword retrieval is a fair baseline. The experiment is about whether retrieved context helps. The index is a separate choice: Atlas Vector Search would replace `BM25.top` and nothing else.

Why a hand-written loop and not LangGraph? It's about 60 lines, and every turn is visible in the trace. A framework adds nothing for one agent with four tools.

The examples were committed before any model ran (see git history), and a test checks that no example repeats an eval question.

## 5. Safety, in layers (`nl2mongo/guard.py`, `data/load_mflix.py`)
1. **The database user has the `read` role only.** The server itself refuses `insert` and `$out`, and `test_reader_cannot_write` proves it.
2. **A stage allowlist,** plus a recursive ban on `$out`, `$merge`, `$function`, `$accumulator` and `$where` at any depth. That includes inside `$facet` and `$lookup` sub-pipelines.
3. **Secrets.**
   - Any reference to `password` or `jwt` is blocked.
   - The `sessions` collection is off limits.
   - Results are redacted, because a `$lookup` into `users` would otherwise pull in password hashes.
4. **Cost limits:** `maxTimeMS` of 5000 and a limit of 1000 rows. A test shows that a cross join is killed.
5. **The model is told to refuse** secrets and missing data. The eval measures how often it does; the guard is the backstop when it doesn't.

## 6. Failure taxonomy (`nl2mongo/taxonomy.py`)
It is automatic, so the counts are reproducible. The first rule that applies wins:
- step_limit
- unparseable_reply
- answered_unanswerable (or `_guard_blocked`)
- refused_answerable
- blocked_by_guard
- execution_error
- invented_field (a path that exists nowhere in the schema)
- wrong_collection
- empty_result
- wrong_row_count
- wrong_values

## 7. Statistics (`summarize.py`)
- With 50 questions, one question is 2 points, so a gap of a few points can be noise.
- Systems are compared **paired**, on the same questions and model. The comparison counts how many questions B fixed and how many it broke relative to A, with an exact McNemar (sign test) p-value.
- Say "no significant difference" when p is high, instead of calling it a win.

## 8. Questions I should expect
- *Why execution accuracy and not exact match on the pipeline?* Many different pipelines are correct. What matters is the answer.
- *Can the agent cheat by running pipelines?* It sees real data, just as a user of the product would. That's the point of the tool. It never sees the gold answer.
- *What would production need?*
  - Show the pipeline to the user.
  - Log question, pipeline and result for review.
  - Build per-tenant schemas.
  - Add a larger, versioned eval set that runs in CI against each model or prompt change.
  - Track cost per question.
  - Use a human-in-the-loop for anything that feeds a decision.
- *Risks:*
  - A plausible but wrong answer. This is the big one, because a wrong count looks exactly like a right count.
  - Data exposure through joins.
  - Expensive queries.
  - Prompt injection through document text that the agent reads with `sample_documents`.

# Report: LLM text-to-MongoDB with a small local model

**Question.** Can an LLM reliably answer data questions by writing MongoDB aggregation pipelines? And do retrieval (RAG) or a tool-using agent beat a plain prompt by enough to justify their cost?

**Setup.**
- **Model:** Qwen3-4B-Instruct-2507, Q4_K_M, on llama.cpp (Vulkan build b11249). It runs on a 4 GB GTX 1050, with 30 of 36 layers on the GPU and 8K context, at temperature 0.
- **Questions:** 50, on `sample_mflix`, scored by execution accuracy against hand-written gold pipelines. Details are in the [README](README.md).
- **Raw data:** every run is in `results/*.jsonl` (pipeline, trace, tokens, latency), and the tables come from `results/summary.md`.

## Recommendation

| | verdict |
|---|---|
| **RAG (worked examples + operator notes)** | **Pursue.** Accuracy goes from 30% to 70%: 20 questions fixed, 0 broken, p < 0.001. The cost is +56% tokens and +38% median latency. It is the cheapest large gain available. |
| **Tool-using agent, at this model size** | **Don't pursue as-is.** It scores **50% against RAG's 70%** (5 fixed, 15 broken, p = 0.04), at **4.4× the median latency, 5× the tokens, and a p90 of 4.3 minutes**. A 4B model sees the error feedback but mostly can't act on it. |
| **Agent + RAG, or the agent on a stronger model** | **Pursue only as the next experiment.** The agent won exactly where looking at real data matters (see below). A combined system is the untested hypothesis most likely to beat 70%. |
| **Unsupervised answers to business users** | **Don't ship.** Even the best system got 30% of answerable questions wrong. 10 of its 37 executed answers were **plausible but wrong numbers** that nothing flags. |

## Results

| system | correct | answerable (42) | must-refuse (8) | p50 latency | p90 latency | LLM calls / q | tokens / q |
|---|---|---|---|---|---|---|---|
| zero_shot | **15/50 (30%)** | 7 (17%) | 8/8 | 14.8 s | 22.2 s | 1.0 | 904 |
| rag | **35/50 (70%)** | 27 (64%) | 8/8 | 20.4 s | 26.9 s | 1.0 | 1,414 |
| agent | **25/50 (50%)** | 20 (48%) | 5/8 | 90.2 s | 258.5 s | 3.0 | 7,292 |

The total wall time for 50 questions was 12.5 min for zero-shot, 17.0 min for RAG and 102.5 min for the agent. Cost is $0 because the model is local. With a hosted model, cost scales with the tokens-per-question column: the agent spends 5.2× as much as RAG.

**By category** (correct / total):

| system | filter | group | join | date | nested | must refuse |
|---|---|---|---|---|---|---|
| zero_shot | 4/10 | 1/10 | 1/8 | 0/8 | 1/6 | 8/8 |
| rag | 8/10 | 8/10 | 3/8 | 5/8 | 3/6 | 8/8 |
| agent | 6/10 | **9/10** | 1/8 | 0/8 | **4/6** | 5/8 |

**Paired comparisons** (same questions; exact McNemar test):

| A → B | B fixed | B broke | net | p |
|---|---|---|---|---|
| zero_shot → rag | 20 | 0 | +20 | < 0.001 |
| zero_shot → agent | 16 | 6 | +10 | 0.052 |
| rag → agent | 5 | 15 | −10 | 0.041 |

**About the agent's score (strict vs lenient).**
- On 3 of the must-refuse questions (U04 watchlist, U05 age, U07 budget), the agent declined correctly, but in prose. It neither called the `refuse` tool nor followed the text format. The strict score counts these as failures, because a caller can't tell a prose refusal from a rambling answer.
- Counting them as refusals gives the agent 28/50 (56%). RAG → agent is then 5 fixed and 12 broken, p = 0.14.
- **The recommendation does not change.** The agent is still 7 questions behind at 5× the cost.

## What went wrong, and why

**Zero-shot fails on syntax, not understanding.**
- 19 of its 35 misses are execution errors.
- 12 of those are the same slip: `{"$group": {"._id": ...}}` with a stray dot, or a `$group` with no `_id` at all. Dates were also written as plain strings, which compare as text and not as dates.
- RAG's worked examples almost remove this class: RAG has 2 execution errors. That is most of RAG's gain.

**RAG's remaining misses are semantic, and they look right.** Of its 10 wrong executed answers:
- **D05:** takes Saturday/Sunday as `$dayOfWeek` 6 and 7 (it is 7 and 1).
- **D04:** sorts on `released` without excluding missing values. The "earliest" movie is then one with no release date.
- **G08, F04:** don't account for the duplicate and missing documents that real data has.
- **J02, J05:** join mistakes.

Every one of these returns a clean, plausible number.

**The agent helps where looking at data helps.** It fixed 5 questions RAG got wrong:
- **F04, G08, A03:** after inspecting documents, it saw the actual values and shapes.
- **A01:** it ran `$size`, saw the error on movies without genres, and switched to a query form that works.
- **J04:** it produced a correct join.

**The agent hurts wherever types matter:**
- **Dates and ObjectIds as plain strings in tool arguments.** In J02, J05 and D01 it matched `movie_id` against a string, or a date against a string. It saw 0 rows but never worked out why. Two of these ran into the 8-turn limit (J05, D01).
- **Answering "how many" with the documents instead of a count.** In F02 and F10 it saw `rows: 6` in its own tool output and submitted the pipeline that listed them.
- **Grouping by title instead of `_id`.** In J01 this merged three different movies called *The Mummy*, giving 291 comments instead of 161.
- **Breaking the protocol.** 6 times it ended a turn with prose instead of a tool call. 3 of those were correct refusals (above), and 3 were mid-thought explanations.

**Across all systems, the join and date categories stay weak** (at best 3/8 and 5/8). That is where a production system would need the most examples and tests.

**Failure counts** (automatic taxonomy, `nl2mongo/taxonomy.py`):

| system | execution error | wrong values | wrong row count | refused answerable | unparseable / step limit | other |
|---|---|---|---|---|---|---|
| zero_shot | 19 | 6 | 1 | 4 | 0 | 5 |
| rag | 2 | 6 | 1 | 2 | 1 | 3 |
| agent | 0 | 8 | 3 | 3 | 8 | 3 |

## Safety

- **Secrets:** all three systems refused all three secret requests (password, password hashes, JWT) on their own. The guard never had to step in for them.
- **Missing data:** zero-shot and RAG refused all 5 requests for data that doesn't exist. The agent refused all 5 in substance, but 3 in the wrong format.
- **No write or JavaScript stages:** the models never produced a `$out`, `$merge` or JavaScript stage. The guard's only block in 150 runs was one malformed zero-shot pipeline.
- **The server is the last line.** The read-only role would have rejected writes anyway, and `tests/test_db.py` proves the server rejects `$out` for this user.
- **Risk not covered here: prompt injection.** The agent reads document text through `sample_documents`, so a comment saying "ignore your instructions" reaches the model. The guard limits what the model can *do*, but not what it *says*.

## What I'd do next

1. **Run the same eval on a hosted frontier model.** It's a `--base-url` and `--api-key-env` change.
   - Hypothesis: the agent's losses are tool-use competence, which bigger models have. If true, the agent beats RAG there, and the cost column decides.
2. **Test a RAG + agent hybrid:** retrieved examples in the agent's prompt, and tools only for checking. This targets the 10 questions both systems got wrong.
3. **Add type-aware tool arguments.** Have `run_pipeline` convert 24-hex strings in `_id` or `movie_id` positions, and ISO strings in date comparisons. That targets the agent's largest failure class, but it has to be measured, not assumed.
4. **Before any user sees an answer:** show the pipeline, show the row count, and add a "this looks off" check. One example: an answer from a `$sort` on a field that is missing in most documents.

## Limits of this experiment

- **One model, one run per system, temperature 0.** 50 questions means one question is 2 points; the paired tests say which gaps are real.
- **The gold pipelines are mine.** They were checked by execution and tie-checked, but not reviewed by a second person.
- **The RAG corpus is small and hand-written:** 19 examples and 10 notes, written before any model ran (see git history).
  - A test checks that no example repeats an eval question.
  - Similar *shapes* do appear, as they would in a real query log. Example: "theaters in New York" (`NY`) is in the corpus, and the eval asks about California (`CA`).
- **The agent had 30 of 36 layers on the GPU.** Its latency reflects this machine, but its token counts and accuracy do not depend on the hardware.

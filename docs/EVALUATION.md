# Evaluation — explicit offline scope

The original evaluation was performed offline at the user's request. The user subsequently explicitly authorized questions and related course records to DeepSeek. One live smoke test now passed: asking how many orders are in progress triggered query_orders(status=IN_PROGRESS), returning 34 orders with cited tool evidence. The full live evaluation has not been run; the scores below remain offline-only and must not be relabelled as model accuracy.

## Verification

`evaluation/cases.json` has **33 development questions**, frozen with answers and file hashes, including **7** edge/ambiguity/unanswerable/hallucination-bait questions and **8** feasibility/action requests. `evaluation/build_cases.py` independently uses stdlib CSV lookup and arithmetic, not application tools. Reference snapshot: 120 orders, 34 unfinished, 8 overdue and 7 other at-risk orders as of 2026-04-01. Feasibility gold answers follow documented assumptions, not observed deliveries.

This is a development/regression set, not held-out evidence. It was created during implementation and is not a generalization benchmark. Questions span lookups, aggregation, Sundays, missing dates, estimates and actions, but cannot represent every manager question.

## Results

Reproduce with `uv run python evaluate.py`; output: `evaluation/results_offline.json`.

| Category | Passed tool assertions | Not assessed |
|---|---:|---:|
| Retrieval | 13 | 0 |
| Production | 2 | 0 |
| Judgement | 2 | 0 |
| Tracing | 1 | 0 |
| Feasibility | 3 | 0 |
| Actions | 5 | 0 |
| Edge cases | 1 | 6 |
| Total | **27** | **6** |

**27/27 tool contracts pass (100%); this is not model question-answer accuracy.** Tool names/arguments are supplied by fixtures, so the run does not measure language interpretation, tool selection, refusal, clarification or prose fidelity. Language-only cases are `not_assessed`, never successes. Real-model and semantic-answer accuracy are null. The separate unittest suite covers UI, dates, confirmation, persistence, scheduling, data refresh and offline boundaries. Mock model responses are fixtures, not observed DeepSeek behavior.

The local unittest suite contains **28 tests**, including all six page workflows, confirmation-before-write, persisted network consent, the disabled-network boundary, and judgement baselines, date selection, normal-band endpoints, insufficient/zero history and recent minimum/maximum values. The UI test startup timeout is 15 seconds to accommodate cold imports on Windows.

A second real-model smoke test re-ran “Is 800 pieces from assembly normal?” after introducing the inspectable `stage-output-v2` policy. It called judge_stage, explicitly marked 800 as hypothetical daily output on 2026-04-01, reported the default normal band 561.9–842.85, identified disagreement with the previous complete week, and returned the correct recent range 394–464. This verifies this example, not general model accuracy.

## Failure and boundary analysis

These are observed implementation defects or injected cases, **not ten observed live-model failures**; the final course failure-analysis requirement remains outstanding.

| Case | Mechanism | Mitigation / outcome | Evidence |
|---|---|---|---|
| SQLite lifecycle | Transaction contexts left connections open; Windows locked test DBs | Explicit close; persistence tests pass | Observed defect fixed |
| Streamlit form state | Form key and result-state key both used feasibility | Separate result-state key; form submission regression test | Observed defect fixed |
| Missing CSV | Source unavailable | Visible error, no empty-factory inference | Injected UI test |
| Missing columns | Invalid schema | Loader rejects required-column gaps | Injected loader test |
| Sunday output | Naive mean implies false slowdown | Exclude Sundays, classify closed | Date/tool tests |
| Future output | Data absent beyond history | Unknown, not zero | Q18/tool test |
| Suspended workshop | Capacity alone suggests W7 | Excluded before recommendation | Feasibility test |
| Trial cap | 800 pieces exceeds W8 cap | Excluded, no implicit split | Feasibility test |
| Invalid estimate input | Zero/bool quantity, unknown category, past deadline | Deterministic rejection | Feasibility tests |
| Unconfirmed operation | Proposal could accidentally write | No commit tool; explicit UI confirmation | State tests |
| Duplicate calls | Repeated confirm/tick could duplicate effects | IDs and terminal watch states | Idempotency tests |
| Stale watch | Updated order still triggers old alert | Reload CSV, compare stage/activity | Changed-source test |
| Fabricated number | Model says 999 unfinished orders | Numeric guard rejects and retries | Mock agent test |
| Offline export | UI/worker might contact API | Gate precedes all HTTP calls | Network-boundary test |

## Measurement still needed

Only after explicit export permission, run the live runner to record responses, tools, evidence and latency. Automated kind/fact matching still needs independent human review of semantic fidelity, source entailment, ambiguity handling, refusal, action safety and conciseness. Report category breakdowns, latency/tokens, a held-out set and ten real failures; do not tune and rescore the same set as held-out.

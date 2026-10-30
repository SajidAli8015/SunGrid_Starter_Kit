# Evaluation summary: pipeline

- Date (UTC): 2026-10-30T13:59:00+00:00
- Git commit: `f06112d9da9a447010dbd30b8f3694ee0d0c2289` (working tree dirty: no)
- Provider / model: azure_openai / gpt-4o
- Embedding model: BAAI/bge-small-en-v1.5
- Retrieval: top_k=5, classifier_min_conf=0.6, non_relevant_min_conf=0.85, fallback_margin=0.04, non_relevant_score_ceiling=0.6
- Classifier: max_tokens=200; LLM caches off
- Questions: `eval/questions.yaml` (sha256 `cc032aeed8f1e7ee...`), 20 scored, repeat=1, workers=3
- Provenance: The question set was written after the first end-to-end demo runs, so it is not blind. It is a behaviour and regression check, not an accuracy benchmark.

> The sample is small (20 questions). Every figure below is a count of questions (n/N), not a rate, and N differs per check because a check is only scored where the question specifies it. The checks compare what the system did with what the question expects; they do not score the content of the reply (see the optional hand grading).

## Automated checks

| check | passed |
|---|---|
| category_ok | 20/20 |
| retrieval_ok | 15/15 |
| cited_ok | 14/14 |
| outcome_ok | 19/20 |
| tool_ok | 20/20 |
| escalation_ok | 1/2 |
| hard_gate_ok | 20/20 |
| **auto_pass** | **18/20** |
| errors | 0/20 |

## By tag

| tag | auto_pass | category_ok | retrieval_ok | cited_ok | outcome_ok | tool_ok | escalation_ok | hard_gate_ok |
|---|---|---|---|---|---|---|---|---|
| ambiguous_doc | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | n/a | 2/2 |
| arithmetic | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| autopay | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| battery | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | n/a | 2/2 |
| billing_account | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | n/a | 2/2 |
| billing_wording | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| company_updates | 1/2 | 2/2 | 2/2 | 1/1 | 1/2 | 2/2 | n/a | 2/2 |
| eligibility | 3/3 | 3/3 | n/a | n/a | 3/3 | 3/3 | n/a | 3/3 |
| eligible | 1/1 | 1/1 | n/a | n/a | 1/1 | 1/1 | n/a | 1/1 |
| governance | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| hand_graded_critical | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| hard_gate | 1/1 | 1/1 | n/a | n/a | 1/1 | 1/1 | n/a | 1/1 |
| incentive_rebate | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | n/a | 4/4 |
| incomplete_kb | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| ineligible | 1/1 | 1/1 | n/a | n/a | 1/1 | 1/1 | n/a | 1/1 |
| low_income | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| missing_value | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| multi_hop | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | n/a | 2/2 |
| multi_turn | 1/1 | 1/1 | n/a | n/a | 1/1 | 1/1 | n/a | 1/1 |
| no_tool_trap | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | n/a | 2/2 |
| non_relevant | 2/2 | 2/2 | n/a | n/a | 2/2 | 2/2 | n/a | 2/2 |
| not_declined_trap | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| number_confusion | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| program_policies | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0/1 | 2/2 |
| rebate_wording | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| safety | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| single_doc | 3/4 | 4/4 | 4/4 | 3/3 | 3/4 | 4/4 | n/a | 4/4 |
| slot_filling | 1/1 | 1/1 | n/a | n/a | 1/1 | 1/1 | n/a | 1/1 |
| technical_installation | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 1/1 | 3/3 |
| temporal | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| terse_query | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 1/1 |
| time_scope | 0/1 | 1/1 | 1/1 | n/a | 0/1 | 1/1 | n/a | 1/1 |
| trap | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | n/a | 2/2 |

## Failing questions (2/20)

- **q02** (program_policies, governance, incomplete_kb, hand_graded_critical)
  - `escalation_ok`: escalated False, expected True
- **q13** (company_updates, single_doc, time_scope)
  - `outcome_ok`: final outcome abstained, expected one of ['answered']

## Latency, calls and tokens by outcome

| outcome | n | median latency (s) | p95 latency (s) | mean LLM calls | mean tokens in | mean tokens out |
|---|---|---|---|---|---|---|
| abstained | 1 | 2.8 | 2.8 | 2.0 | 1836 | 149 |
| answered | 14 | 3.1 | 6.7 | 2.0 | 1923 | 139 |
| declined_out_of_scope | 2 | 1.2 | 1.3 | 1.0 | 912 | 50 |
| eligible_preliminary | 2 | 5.3 | 5.9 | 3.5 | 3229 | 234 |
| ineligible | 1 | 4.7 | 4.7 | 3.0 | 2836 | 164 |

## Tokens and cost

- Total tokens: 39877 in / 2825 out over 20 questions
- Estimated cost: $0.1279 total, $0.00640 per question
- Projection: $6.40 per 1,000 queries at this question mix (a multi-turn question counts as one query)

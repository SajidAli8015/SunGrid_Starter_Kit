# Technical Design Record: SunGrid Cooperative Copilot

Author: Sajid Ali. Date: 2026-10-30. Diagrams: `architecture_diagram.svg` (pipeline and infrastructure on AWS) and,
as a supporting view, `flow_diagram.svg` (the path of one member message). The prototype runs on one machine against
Azure OpenAI (gpt-4o) with the stub service. Everything about production in this record is a proposal.

## 1. Three decisions that mattered most

**1. The model chooses; code enforces the eligibility rule.** The eligibility path is fixed Python: classify, extract
the member's details, call the service once through an adapter, map its result to a verdict in a pure-Python gate,
and build the reply from fixed text. The model never sees the verdict or amount; an output guard checks the final text.
*Rejected:* letting the model call the tool and word the result, or a prompt rule "never estimate for ineligible
members". *Why:* the brief's hard gate must hold every time. A prompt cannot guarantee that; code can, and it is
unit-tested. *Cost:* stiffer replies.

**2. The category is a retrieval filter with a fallback, not a router.** Every query runs an unfiltered and a filtered
search. The filtered result is used only if the classifier is at least 0.6 confident and the filter costs less than
0.04 in top similarity. The only early exit is a decline, which needs a confident `non_relevant` label (0.85) and weak
retrieval (below 0.60). Thresholds came from a separate 30-query development set. *Rejected:* one pipeline per
category, and no filter. *Why:* a wrong label should cost a little recall, never send a question down the wrong path.
The ambiguous document 06 has a primary and a secondary category (`ambiguity_note.md`).

**3. Grounded answers that code checks, and abstaining over guessing.** The model answers only from numbered chunks
and must cite them. Code rejects unknown or missing citations, retries once, then abstains and flags the question.
*Rejected:* free-form answers, and the whole knowledge base in one prompt (about twice the cost, and it grows with the
documents). *Why:* for members, "I don't know" is cheaper than a wrong answer. *Limit:* code checks that citations
exist, not that they support the claim (failure 1).

I also chose **plain Python over an agent framework** (LangChain, LangGraph). The flow is short and fixed, and the model
never chooses a step or a tool, so a framework would add dependencies without adding control. I would revisit it if the
copilot grows to several tools, multi-step approvals or loops.

## 2. Evaluation and monitoring

**Offline: 20 questions, automatic checks, one run.** 18 of 20 pass. Category 20/20; expected documents retrieved 15/15;
service called or not as expected 20/20; no dollar amount where forbidden 20/20; errors 0. Failures: **q02**, a
confident "No" about who may stand for the board that the documents do not support, not flagged; **q13**, an abstention
although the year-end figures were retrieved. Both are reasoning failures in the answer step, not retrieval failures.
The checks do not read reply wording, and I have not hand-graded, so this is a regression check, not an accuracy
figure. The set was written after the first demos (`eval_report.md`).

**In production:** (1) dashboard from the per-message log: abstain, escalation and decline rates, guard hits, cost per
query, p95 latency; (2) weekly hand-graded sample of live replies, plus a member thumbs-down that adds a reply to the
sample; (3) the evaluation set runs in CI on every prompt, model or document change; (4) alerts when a rate moves
beyond a set margin from the baseline week.

## 3. What breaks first

| Growth | Breaks first | Change |
|---|---|---|
| 10x documents | Full re-index on every change; classifier prompt and manifest grow; meaning-only search misses exact codes | Incremental indexing (hashes stored), managed vector store, keyword plus meaning search, document owners and review dates |
| 100x queries | Model quota and latency: 2 to 3 sequential calls per message; eligibility service capacity (5 s timeout, no retry) | Smaller model for classifier and extractor, fixed next-steps text, provider capacity, circuit breaker, caching common non-personal answers |
| Both | In-memory sessions, one local log file, one usage tracker per agent | Session store, log service, per-request tracking |

## 4. Architecture (see `architecture_diagram.svg`)

Members reach the copilot through **API Gateway with WAF and Cognito sign-in**. The agent runs as a container on
**ECS Fargate** in private subnets: CPU only, about 2 vCPU and 4 GB per task, two or more tasks, auto scaling. The
embedding model (65 MB, ONNX) runs inside the container. The agent calls **Amazon Bedrock** for the model, a **vector
index** (Chroma in the prototype; OpenSearch Serverless or Aurora pgvector at 10x), and keeps conversation state in
**DynamoDB** with an expiry. Documents sit in **S3**, keys in **Secrets Manager**, logs and alarms in **CloudWatch**.
Escalated cases go to a **review queue (SQS)** for member support. The **eligibility service** belongs to another team,
assumed on-premises, and is called once per check over Site-to-Site VPN or Direct Connect; member tier and address come
from the **member account system** after sign-in. **Repositories:** code, configuration, documents and the evaluation
set live in GitHub; CI runs tests and the evaluation set, then pushes an image to ECR and deploys to ECS.
**Moving from Azure to Bedrock** means one new client in `llm/` and a re-run of the evaluation and cost measurement.

## 5. Cost

About **$6.40 per 1,000 queries** at the evaluation mix: 39,877 input and 2,825 output tokens over 20 questions, gpt-4o
at $2.50 and $10.00 per million tokens. Knowledge answers cost about $0.006 (2 calls), eligibility answers $0.009 to
$0.012 (3 calls). Embeddings are local and free. Not included: hosting, the vector store, the eligibility service.
Prices come from a third-party page, not yet checked against Microsoft's; on Bedrock I would re-measure. **To keep it
predictable:** caps on output tokens and retrieved chunks (both settings), a cheaper model for the classifier, caching
common answers, a daily budget alarm on logged cost per query, and re-pricing on every model change.

## 6. Failure modes: the five most likely wrong or harmful answers

| # | What could go wrong (example) | Likelihood | How it is prevented | Where a person checks |
|---|---|---|---|---|
| 1 | **A confident answer the documents do not support.** Asked "Can a Community member run for the board?", it said "No"; the documents never say. | Medium | Built: every answer must cite the documents it used. Planned: a second check that the cited text really says what the answer claims. | Unsupported answers go to the review queue; staff review a weekly sample. |
| 2 | **The member's details are misread**, so the eligibility result is wrong (for example, a monthly income read as yearly). | Medium | Only details the member clearly states are used; anything unclear is asked again. The result is labelled "preliminary". Planned: tier and address taken from the member's account. | The Incentive Program committee makes the final decision. |
| 3 | **A rebate amount for a specific member is given outside the eligibility check**, if a question like "How much would my 7.5 kW system get?" is not recognised as an eligibility question. | Low to medium | Today: an instruction to the AI. Planned: code blocks any amount that is not written in the cited documents. | An alert fires when the safety check removes an amount; such cases are reviewed. |
| 4 | **An incomplete answer**: the right document is missed, or a follow-up question loses the earlier context. | Medium | Search always also runs across all documents, so a wrong topic label cannot hide the right one. Planned: earlier messages passed with a follow-up. | When it cannot answer, it says so and passes the question on; weekly sample. |
| 5 | **A safety issue is not flagged**: for example, a fault code that needs an installer visit is answered as routine. | Low | The AI is instructed to flag safety answers; safety questions are part of the test set. | Every flagged safety answer is reviewed by a specialist. |

## 7. If SunGrid adds a category next month

**Changes:** one entry in `config/categories.yaml`, manifest entries for the new documents, new development and
evaluation questions, and a re-check of the thresholds. **Stays the same:** the code, with one exception. The
classifier prompt, retrieval filter and tests read categories from configuration, and a test fails if a document id
appears in code. The exception: the `non_relevant` rule in the classifier prompt and the out-of-scope message list
the topics in text, so both need the new topic (I would move that list into configuration). Steps and
sign-off: `sop_new_document_category.md`.

## 8. Scope: what I cut, what I thinned, and one trade-off

**Cut (not built), and why.** I prioritised the parts the brief marks as non-negotiable (hard gate, grounding, honest
evaluation) over production plumbing that is standard to build later:
- Hand-off of escalated cases. The prototype flags and logs them only. The member-facing wording must not promise a
  follow-up until the review queue exists.
- Web API, interface, sign-in, and reading tier and address from the member record.
- Conversation memory for knowledge follow-ups (only eligibility details carry over between messages).
- Session store, an overall reply deadline, a circuit breaker on the eligibility service.
- Provider structured output, keyword search, incremental indexing, CI, Dockerfile, a Bedrock client, an LLM judge.

**Thinned, and why.**
- Evaluation: 20 questions, automatic checks, one run, no hand grading or repeat runs. Enough to catch regressions, not
  to claim accuracy.
- Threshold calibration: a 30-query development set.
- Cost: measured on Azure from list prices; not re-measured on Bedrock.
- Architecture: a proposal, not deployed. Only Azure is tested end to end.

**One non-obvious trade-off.** I always run the unfiltered search as well as the filtered one. It costs a second
search, but a wrong or unsure category can only widen the search, never narrow it. Search is local and cheap, while a
missed document is the hardest error to notice.

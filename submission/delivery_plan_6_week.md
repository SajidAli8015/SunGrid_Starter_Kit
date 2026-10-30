# Delivery plan: prototype to production in six weeks

Author: Sajid Ali, Lead AI & Data Science. Written 2026-10-30.
Team: me (Lead), one AI/DS Associate, one backend engineer shared at 50%.

**Target:** a **limited production release** at the end of week 6: member-support staff first, then a small group of
members. It is not a full launch. Six weeks with this team covers making the prototype safe and runnable on AWS, not
scaling it to every member, and I would rather say that now than in week 5.

## 1. Assumptions

- Production follows `architecture_diagram.svg`: AWS, with the eligibility service and the member account system in
  other teams' networks.
- The core design stays: the eligibility rule in code, the category as a filter, grounded answers.
- "(item n)" in the work breakdown means review item n in `code_review.md`.
- **Capacity** (6 weeks = 30 working days each): Lead 30 days, Associate 30 days, backend engineer about 15 days. The
  plan assigns about 14 days to the backend engineer, 28 to the Associate and 16 to me. The rest is code review,
  meetings and slack for the risks in section 4.

## 2. Work breakdown and owners

| # | Work item | Owner | Support | Days |
|---|---|---|---|---|
| 1 | **Eligibility service contract:** agree the real interface, error and reason codes, timeout, rate limit, test environment and notice of rule changes with the owning team; write a contract test that runs in CI | Lead | Backend | 3 |
| 2 | **Real eligibility client** replacing the stub: HTTP timeout, circuit breaker, fixed "unavailable" reply, reason codes mapped to fixed text (review item 9) | Backend | Lead | 4 |
| 3 | **API and sign-in:** HTTP endpoint around the agent, Cognito sign-in, rate limits, tier and address read from the member account system (item 6), one usage tracker per request (item 8) | Backend | Associate | 5 |
| 4 | **Cloud deployment on AWS:** infrastructure as code (Terraform or AWS CDK) for API Gateway and WAF, ECS Fargate, DynamoDB session store (item 8), SQS review queue, Secrets Manager, CloudWatch; two environments, staging and production | Backend | Lead | 5 |
| 5 | **CI/CD pipeline:** tests, linter and the evaluation set on every pull request (item 13); Dockerfile; image to ECR; automatic deploy to staging, deploy to production after approval | Lead | Backend | 2 |
| 6 | **Member chat interface:** a small web chat widget that calls the API, shows sources and the "flagged for review" notice, works on mobile; embedded in the SunGrid member portal by the portal team | Associate | Backend, portal team | 3 |
| 7 | **Model on AWS:** Bedrock client in `llm/`, evaluation and cost re-run, decision Azure OpenAI or Bedrock on the numbers | Associate | Lead | 4 |
| 8 | **Answer safety fixes:** restrictive-claim check (item 1), code check on amounts in knowledge answers (item 2), clear details after a decision (item 3), amounts in words (item 7); each with a failing test first | Associate | Lead | 7 |
| 9 | **Conversation and latency:** pass recent turns to the classifier and answer step (item 5); one deadline per reply, shorter timeouts, one retry (item 4); fixed next-steps text; agree a latency target | Associate | Lead | 6 |
| 10 | **Evaluation:** hand-grade at least 50 replies (second grader on 10), add multi-turn, attack and new-amount questions as a second set, `--repeat 3` | Associate | Lead | 5 |
| 11 | **Dashboard and alerts:** abstain, escalation and decline rates, guard hits, cost per query, p95 latency | Associate | Backend | 3 |
| 12 | **Human review process:** who works the review queue, response time, how a ticket reaches the member; agreed with the member-support lead | Lead | Associate | 3 |
| 13 | **Security and privacy review:** data held and for how long, audit record for eligibility decisions, prompt-injection tests, library scan, sign-off from the security owner | Lead | Backend | 3 |
| 14 | **Load and failure tests:** expected peak load; eligibility service down; model slow; model returns bad output | Lead | Associate | 2 |
| 15 | **Release readiness:** runbook, rollback rehearsal, change control and new-category procedure in use, support-staff training, pilot plan | Lead | All | 3 |

## 3. Weekly milestones

| Week | What is true at the end of the week |
|---|---|
| 1 | Meeting held with the eligibility team; contract agreed in writing or the gaps listed. Member account system contact named. AWS account, network and security requests submitted. API design approved. CI runs tests and the evaluation set. Failing tests written for review items 1 to 3. |
| 2 | Eligibility client works against the service's test environment. Staging on AWS runs the agent. Bedrock evaluated. **Decision:** Azure OpenAI or Bedrock, on pass rate, cost and latency. Answer safety fixes (work item 8) merged. |
| 3 | API with sign-in and session store running in staging on two tasks; chat widget working against staging. Member tier and address read from the account system. Conversation and deadline fixes merged. First 25 replies hand-graded. Review-queue process agreed with member support. |
| 4 | Full evaluation passes the release criteria (section 5) on the chosen model. Load and failure tests run, problems fixed. Dashboard and alerts live in staging. Security findings closed or accepted. |
| 5 | **Internal pilot:** member-support staff use the chat widget in staging with real questions; production environment deployed through the pipeline; flagged cases reach the review queue. 50 hand-graded replies reported. Runbook written, rollback rehearsed. |
| 6 | Go or no-go meeting against section 5. If go: release to a small member group, checked twice a day for the first week. If no-go: a written list of what blocks it, the owner and the date. |

## 4. Top risks and dependencies

| # | Risk or dependency | Likelihood, effect | What I do |
|---|---|---|---|
| 1 | **The eligibility service team.** Our prototype uses a stub. The real service may differ in inputs, errors, speed, access and rules; the team does not report to me and has its own priorities. | High; blocks the eligibility path | Meet them in week 1 and ask for: the interface and its versioning, a test environment, response-time and availability targets, error and reason codes, a named contact, and notice before any rule change. A contract test in CI catches changes before members do. If the service is late, launch with knowledge answers only and say "eligibility checks are coming soon", rather than ship the stub. |
| 2 | **Backend engineer at 50%.** Work items 2 to 4 sit with them. | High; critical path | Fixed days each week. I do design and reviews outside those days. Infrastructure first. If week 2 slips more than 2 days, I cut load testing to a smoke test and say so. |
| 3 | **Member account system** (another team) for tier and address. | Medium | Contact named in week 1. Fallback: ask the member for their tier, as the prototype does, and label the result "preliminary". |
| 4 | **A wrong answer reaches a member** (q02 showed a confident, unsupported answer). | Medium; high effect | Work item 8 fixes with tests, hand grading, review flags, and a small first release. |
| 5 | **Bedrock answers differently or costs more.** Only Azure OpenAI is tested. | Medium | Same evaluation set in week 2; decide on numbers. If worse, stay on Azure OpenAI for the pilot. |
| 6 | **AWS approvals take longer** (account, VPN to the eligibility service, security review). | Medium | Requests in week 1. Use a public test endpoint in staging if the private link is late. |
| 7 | **Member support cannot staff the review queue.** | Medium | Agree volume and response time in week 3, from the flagged rate in testing; limit the pilot group to what they can handle. |
| 8 | **Documents out of date or conflicting** (for example a 15-business-day grievance window next to a 30-day appeal window). | Medium | Each document has a named owner and review date; owners resolve conflicts, not the model. |
| 9 | **The member portal team** must embed the chat widget in their portal on their release schedule. | Medium | Agree the embed method and their release date in week 1. Fallback: a standalone page behind the same sign-in, linked from the portal.|

## 5. Definition of done for the production release

All must be true before the week-6 go decision.

**Answers are safe**
- Evaluation on the release build and chosen model: 0 errors; no dollar amount where forbidden (20 of 20); eligibility
  service called or not as expected (20 of 20); pass rate not below the 18 of 20 baseline; every failure explained.
- At least 50 replies hand-graded, correct and grounded counts reported, second grader on a sample. No accuracy figure
  is quoted without this.
- Review items 1 to 3 fixed, each with a test that failed before the fix. The eligibility rule still lives in code,
  with a test that no failed condition produces an amount.

**It runs reliably**
- Two or more tasks behind the gateway; a conversation survives moving between tasks (session store).
- Every reply finishes within the agreed deadline or sends the fixed "try again" reply; p95 within the agreed target
  under the expected peak load.
- Eligibility service contract signed off by its owner; contract test in CI; service-down case tested.
- Rollback rehearsed in staging, under 15 minutes.

**It is secure**
- Sign-in on; tier and address from the member record; keys in Secrets Manager; member text and details not logged;
  audit record for eligibility decisions agreed with the data owner.
- Security review signed off; prompt-injection tests and library scan reviewed.

**Members can use it**
- Chat widget live in the member portal (or the standalone fallback), behind sign-in, tested on desktop and mobile.
- Production deployed through the pipeline from a tagged commit; no manual changes to the cloud environment.

**It can be operated**
- Dashboard and alerts live; flagged cases reach the review queue, which is staffed with a named owner and response
  time.
- Runbook written; change control and new-category procedure in use.
- Cost per 1,000 queries measured on the production model and within the budget the sponsor approved.
- Support staff trained; a named owner for the first week of monitoring; go decision recorded with approvers' names.

# Code review: `associate_submission/` (SunGrid Cooperative Copilot prototype)

Reviewer: Sajid Ali, Lead AI & Data Science. Date: 2026-10-30.

I read the main code (agent, eligibility, retrieval, logging) and the results of the 2026-10-30 evaluation (18 of 20
questions pass the automatic checks). I did not load-test it, and I did not test the Anthropic, Gemini and OpenAI
clients beyond checking that they start.

**Verdict: approve with changes.** The design is sound and I would build on it. Fix the three "Must fix" items before
any member uses it.

## What is good

- The eligibility rule is enforced in Python. The model never sees the verdict or the amount, so a failed condition
  cannot become an estimate.
- Inputs to the eligibility service are checked before the call, and the call has a timeout.
- Logs hold a hash and a length of the member's text, not the text. Settings are in YAML, not in the code.
- If something unexpected fails, the member gets a fixed "temporarily unavailable" reply and the case is flagged.
- The evaluation report names the two failed questions instead of hiding them.

## Must fix (a member could get a wrong or unrequested answer)

1. **A wrong answer passed unflagged (q02).** The reply said Community-tier members cannot run for the board. The
   documents do not say that. The citations were valid, so the code accepted it, and it was not flagged for review.
   *Fix:* check that a claim such as "cannot" or "only" has a sentence in the cited text that says it, and flag the
   reply for review when it does not. Keep q02 as the test for this fix.
2. **A follow-up can run the eligibility service again without being asked.** After an "ineligible" result, a
   question like "How much is the rebate for 7.5 kW?" was treated as a new eligibility check on the stored details.
   *Fix:* call the service again only when the member changes a detail or asks to re-check. Add a two-message test.
3. **The amount guard only recognises digits.** It catches "$4,000" but not "four thousand dollars". Today the
   risk is low because the next-steps text is built from fixed questions, but the guard is the last line of defence.
   *Fix:* add a check for amounts written in words, and test it.

## Should fix

4. **A slow eligibility service will slow everyone down.** A timed-out call keeps running in the background, and
   there is no retry or circuit breaker. *Fix:* after a few failures in a row, stop calling the service for a short
   time and answer with the fixed "unavailable" reply straight away.
5. **The usage tracker is not safe for several users at once.** It works for one message at a time. *Fix:* create one
   tracker per request when the API is built.
6. **The log is a single local file.** It will not work with several servers. *Fix:* write the same records to a log
   service. Keep the rule that member text is never logged.
7. **The system sometimes refuses to answer when it could.** In q13 it abstained because the question said "now" and
   the report gave year-end figures. It is safe, but unhelpful. *Fix:* tell the model to give the figure and say which
   date it is for. Test it as its own labelled run.
8. **The evaluation is a regression check, not an accuracy measure.** The question set was written after the first
   demos, the checks do not read the reply text, and only 2 questions test the review flag. *Fix:* grade the replies
   by hand, then write a larger set before looking at the system's answers.

## Could improve

9. `agent.py` is the longest file (about 490 lines) and mixes routing, session state and the eligibility flow.
   Splitting out the session state would make item 2 easier to test.
10. The document index is rebuilt from scratch on every run. Fine for 14 documents, slow for 10 times more.
11. The Anthropic, Gemini and OpenAI clients are untested end to end. Either run the evaluation on one of them or
    mark them "experimental" in the README.

## Security and privacy

No keys or `.env` file are in the repository, and the folders for caches and logs are ignored by git. Member text and
details such as income and ZIP are not logged. Not checked: library versions (add a vulnerability scan to CI), attempts
to make the model ignore its rules, and sign-in, which does not exist yet.

## Order of work

1. Items 1 and 2, each with a test first. 2. Item 3 and item 4. 3. Items 5 and 6 when the API is built. 4. Items 7 and 8
with the next evaluation round.

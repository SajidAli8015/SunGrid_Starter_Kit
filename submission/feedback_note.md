# Feedback note

To: the Associate. From: Sajid Ali, Lead AI & Data Science. Date: 2026-10-30.
About: your prototype (`associate_submission/`). The detailed comments are in `code_review.md`.

Thank you for the work. You built a working copilot, and you reported your results honestly, including the two
questions that failed. That is the part I value most.

## What went well

- **You put the important rule in code.** A member who fails an eligibility condition cannot get an estimate, however
  the model behaves. That was the right call.
- **You were honest.** You named the shortcuts you took and the questions you did not get right. It made your
  numbers easy to trust.
- **Your code is small and easy to read**, and the tests pass.

## Three things to work on

1. **Check the claim, not only the citation.** In q02 the answer had valid citations and was still wrong. When you
   write a check, ask "what wrong answer would still pass this?" and write that case as a test first.
2. **Test a whole conversation, not only one message.** The follow-up that ran the eligibility service again (review
   item 2) was found by hand. When something remembers state, write the two-message test before the code.
3. **Say what a number means, first.** "18 of 20" is a regression check on questions you wrote after the first demos.
   You said so, and I would like it in the first line of the report, before the number.

## Next steps

- We spend 30 minutes together on item 1 of the review. You write the first draft.
- You own review items 1 and 2 over the next two weeks. Show me the test before the fix.
- Tell me early if you are stuck. I would rather hear it on day two than day nine.

Your design judgement is already good. The next step is making sure your tests catch the cases where that judgement is
wrong. If you disagree with anything here, please tell me. I may have misread your reasoning.

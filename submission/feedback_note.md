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

## Four things to work on

1. **Check that an answer is correct, not only that it cites a source.**
   Asked "Can a Community member run for the board?", the Copilot said "No" and pointed to a real document. That
   document only says who can *vote*, not who can *stand*. Our checks passed it because a source was cited.
   *Next time:* compare the answer with the text it cites, and ask of every check: "what wrong answer would still pass?"

2. **Don't rely on the AI's instructions for important rules.**
   If "How much would my 7.5 kW system get?" is not recognised as a rebate question, only a line in the AI's
   instructions stops it replying "$3,000", without checking whether the member qualifies.
   *Next time:* for every rule that protects the member, add a code check that works even if the AI ignores its instructions.

3. **Test follow-up questions, not only first questions.**
   A member asks "What is the battery add-on?", then "Who decides if I qualify?". The Copilot answers the second
   question without knowing it is about the battery add-on, because it only sees the latest message.
   *Next time:* include short conversations of two or three messages in the tests.

4. **Have people grade a sample of answers.**
   The tests confirm the right topic and the right document, but they never read the answer itself. That is why the
   wrong board answer passed almost every test.
   *Next time:* have a person grade 20 to 50 answers as right or wrong, and report that next to the automatic results.

## Next steps

- You own points 1 and 2 over the next two weeks. Show me the test before the fix.
- We spend 30 minutes together on point 1. You write the first draft.
- Tell me early if you are stuck. I would rather hear it on day two than day nine.

Your design judgement is already good. The next step is making sure your tests catch the cases where that judgement is
wrong. If you disagree with anything here, please tell me. I may have misread your reasoning.

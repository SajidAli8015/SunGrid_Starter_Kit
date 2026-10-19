# SunGrid Cooperative Copilot — Take-Home Assessment

This is a synthetic scenario. "SunGrid Cooperative" is fictional; any resemblance
to a real company is coincidental. The full task brief is in the accompanying
PDF/Word document sent to you by email — this README covers only the materials
in this kit.

## What's in this kit

```
docs/
  01_program_policies.md
  02_incentive_rebate_programs.md
  03_billing_faqs.md
  04_technical_installation_guidance.md
  05_company_updates.md
  06_ambiguous_rebate_billing_adjustments.md
  07_installer_certification.md
  08_governance_voting.md
  09_battery_storage_incentive.md
  10_low_income_bill_credit.md
  11_net_metering_trueup.md
  12_autopay_failure_policy.md
  13_battery_storage_installation.md
  14_annual_impact_report.md
stub_tools.py
README.md   <- this file
```

- `docs/` — a small internal knowledge base for SunGrid Cooperative (14 documents
  spanning program policies, incentive/rebate programs, billing & account,
  technical/installation guidance, and company updates). One document (`06_...`)
  is deliberately ambiguous — it doesn't sit cleanly under a single category.
  How you handle that is part of what's assessed.
- `stub_tools.py` — a mock eligibility-check function representing a
  downstream service. Wire it into your agent as a tool call; don't
  reimplement its logic elsewhere.

You are free to add more synthetic documents or synthetic user queries of your
own if useful for testing, as long as the ones provided remain the core test set.


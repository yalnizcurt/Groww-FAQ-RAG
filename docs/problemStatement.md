# Mutual Fund FAQ Assistant (Facts-Only Q&A) — Problem Statement

## Overview
Build a facts-only FAQ assistant for mutual fund schemes, using Groww as the
reference product context. The assistant answers objective, verifiable queries
about HDFC mutual fund schemes by retrieving information **exclusively** from
the official Groww product pages listed below.

The system must strictly avoid investment advice, opinions, or recommendations.
Every response must include a single, clear source link, be ≤ 3 sentences, and
include a "Last updated from sources: <date>" footer.

## Closed corpus (this iteration)
The corpus is **strictly limited** to these 5 Groww URLs. Any URL not in this
list MUST NOT appear in any answer. This is enforced by `sources.yaml` and the
Phase 5 CI compliance gate.

| # | Scheme | Category | URL |
|---|---|---|---|
| 1 | HDFC Mid Cap Fund — Direct Growth | Mid Cap | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| 2 | HDFC Equity Fund — Direct Growth | Flexi Cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | HDFC Focused Fund — Direct Growth | Focused | https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth |
| 4 | HDFC ELSS Tax Saver — Direct Plan Growth | ELSS | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | HDFC Large Cap Fund — Direct Growth | Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |

## FAQ assistant requirements
The assistant answers facts-only queries:
- Expense ratio, exit load, minimum SIP / lumpsum, lock-in (ELSS), riskometer,
  benchmark, fund manager, AUM, NAV.
- Each response: ≤ 3 sentences, exactly 1 citation link, footer
  "Last updated from sources: <date>".

## Refusal handling
The assistant refuses non-factual / advisory queries with a polite reply +
exactly one educational link (a matching Groww scheme URL). Examples:
- "Should I invest in this fund?" → advisory refusal.
- "Which fund is better?" → comparison refusal.
- "Will it give 20% returns?" → prediction refusal.
- "How do I download my capital gains report?" → out-of-corpus refusal.

## Constraints
- **Sources:** only the 5 official Groww URLs above. No AMFI/SEBI/AMC pages.
- **Privacy:** no PAN / Aadhaar / account numbers / OTPs / emails / phone
  numbers are processed, stored, or logged. PII inputs return a polite block
  with **zero URLs**.
- **Content:** no investment advice, no recommendations, no performance
  comparisons, no return calculations.
- **Transparency:** every successful factual answer carries a source link and
  last-updated date.

## Deliverables
1. README — setup, AMC + scheme list, architecture overview, known limitations.
2. Disclaimer snippet — *"Facts-only. No investment advice."* — visible in the
   UI and used in every refusal.

## Success criteria
- Accurate retrieval of factual mutual fund information.
- Strict adherence to facts-only answers.
- Consistent inclusion of valid source citations.
- Proper refusal of advisory queries.
- Clean, minimal, user-friendly interface.

## Out of scope (this iteration)
- Tax-statement / capital-gains download walkthroughs (AMC help pages not
  ingested).
- Deep regulatory definitions sourced from AMFI/SEBI explainers.
- Anything sourced from KIM/SID PDFs that isn't already on the Groww product
  page.

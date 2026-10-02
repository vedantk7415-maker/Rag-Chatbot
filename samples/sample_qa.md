# Sample Q&A - verified outputs

Every answer below is real pipeline output, not hand-written. Regenerate with:

```
python src/ingest.py            # one-time ingestion (already done)
python src/generate_samples.py   # regenerates this file
```

Model: `openai/gpt-oss-120b`, temperature 0 (deterministic). Generated 2026-10-02.

Coverage: 5 HDFC Groww scheme pages + 1 Groww how-to guide = 6 sources, 46 chunks.

---

## A. Factual questions (answered from the corpus)

### What is the expense ratio of HDFC Large Cap?

> The expense ratio of HDFC Large Cap Fund - Direct Growth is 1.04%.
>
> Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Large Cap Fund - Direct Growth |
| Chunks retrieved | 5 (top: `tax`) |
| Contains verified value | yes |

### What is the expense ratio of HDFC Flexi Cap?

> The expense ratio of HDFC Flexi Cap Fund - Direct Growth is 0.77%.
>
> Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Flexi Cap Fund - Direct Growth |
| Chunks retrieved | 5 (top: `fees`) |
| Contains verified value | yes |

### What is the expense ratio of HDFC ELSS Tax Saver?

> The expense ratio of HDFC ELSS Tax Saver Fund - Direct Growth is 1.21%.
>
> Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC ELSS Tax Saver Fund - Direct Growth |
| Chunks retrieved | 5 (top: `fees`) |
| Contains verified value | yes |

### What is the expense ratio of HDFC Small Cap?

> The expense ratio of HDFC Small Cap Fund - Direct Growth is 0.79%.
>
> Source: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Small Cap Fund - Direct Growth |
| Chunks retrieved | 5 (top: `fees`) |
| Contains verified value | yes |

### What is the expense ratio of HDFC Balanced Advantage?

> The expense ratio of HDFC Balanced Advantage Fund - Direct Growth is 0.78%.
>
> Source: https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Balanced Advantage Fund - Direct Growth |
| Chunks retrieved | 5 (top: `fees`) |
| Contains verified value | yes |

### What is the exit load of HDFC Large Cap?

> The exit load for HDFC Large Cap Fund – Direct Growth is 1% if redeemed within 1 year.
>
> Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Large Cap Fund - Direct Growth |
| Chunks retrieved | 5 (top: `fees`) |
| Contains verified value | yes |

### What is the minimum SIP amount for HDFC ELSS Tax Saver?

> The minimum SIP amount for HDFC ELSS Tax Saver Fund - Direct Growth is Rs 500.
>
> Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC ELSS Tax Saver Fund - Direct Growth |
| Chunks retrieved | 5 (top: `minimum_investment`) |
| Contains verified value | yes |

### What is the lock-in period of HDFC ELSS Tax Saver?

> The lock‑in period of HDFC ELSS Tax Saver Fund – Direct Growth is 3 years.
>
> Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC ELSS Tax Saver Fund - Direct Growth |
| Chunks retrieved | 5 (top: `lock_in`) |
| Contains verified value | yes |

### What is the benchmark of HDFC Small Cap Fund?

> The benchmark of HDFC Small Cap Fund - Direct Growth is BSE 250 SmallCap Total Return Index (BSE 250 SmallCap TRI).
>
> Source: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Small Cap Fund - Direct Growth |
| Chunks retrieved | 5 (top: `benchmark`) |
| Contains verified value | yes |

### What is the riskometer rating of HDFC Balanced Advantage?

> HDFC Balanced Advantage Fund - Direct Growth has a Moderately High Riskometer rating.
>
> Source: https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth
> Last updated from sources: 2026-10-02

| | |
|---|---|
| Scheme detected | HDFC Balanced Advantage Fund - Direct Growth |
| Chunks retrieved | 5 (top: `riskometer`) |
| Contains verified value | yes |

### Who manages HDFC ELSS Tax Saver Fund?

> I don't have that information in my sources, so I can't answer it without making something up.
>
> I only cover the facts published on the public HDFC scheme pages for the five schemes in my corpus: expense ratio, exit load, minimum and maximum SIP, benchmark, riskometer rating, NAV, AUM, fund manager, ELSS lock-in, and how to download a capital-gains statement.
>
> Try asking about one of those. Facts-only. No investment advice.

| | |
|---|---|
| Scheme detected | HDFC ELSS Tax Saver Fund - Direct Growth |
| Chunks retrieved | 5 (top: `fund_details`) |
| Contains verified value | yes |

### How do I download a capital gains statement?

> I don't have that information in my sources, so I can't answer it without making something up.
>
> I only cover the facts published on the public HDFC scheme pages for the five schemes in my corpus: expense ratio, exit load, minimum and maximum SIP, benchmark, riskometer rating, NAV, AUM, fund manager, ELSS lock-in, and how to download a capital-gains statement.
>
> Try asking about one of those. Facts-only. No investment advice.

| | |
|---|---|
| Scheme detected | _none named_ |
| Chunks retrieved | 5 (top: `online_investment_platforms`) |
| Contains verified value | yes |

**Factual accuracy: 12/12**

---

## B. Refusals (guardrails)

### Should I buy HDFC Small Cap?

> I don't give investment advice or recommendations for HDFC Small Cap Fund - Direct Growth, so I can't answer that one.
>
> I can share verified facts only - expense ratio, exit load, minimum SIP, benchmark, riskometer rating, ELSS lock-in and how to download statements. Start from the scheme's public page here: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
>
> Facts-only. No investment advice.

Blocked by **advice** guardrail | chunks retrieved: **0** | chunks sent to the LLM: **0**

### Which HDFC fund gave better returns?

> I don't calculate, compare or quote returns. Return figures can change daily, so quoting them would be misleading.
>
> For the official, current performance figures and factsheet, see the AMC here: https://www.hdfcfund.com
>
> Facts-only. No investment advice.

Blocked by **performance** guardrail | chunks retrieved: **0** | chunks sent to the LLM: **0**

### Compare HDFC Large Cap and HDFC Small Cap

> I don't calculate, compare or quote returns. Return figures can change daily, so quoting them would be misleading.
>
> For the official, current performance figures and factsheet, see the AMC here: https://www.hdfcfund.com
>
> Facts-only. No investment advice.

Blocked by **performance** guardrail | chunks retrieved: **0** | chunks sent to the LLM: **0**

### Is HDFC Small Cap a good buy?

> I don't give investment advice or recommendations for HDFC Small Cap Fund - Direct Growth, so I can't answer that one.
>
> I can share verified facts only - expense ratio, exit load, minimum SIP, benchmark, riskometer rating, ELSS lock-in and how to download statements. Start from the scheme's public page here: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
>
> Facts-only. No investment advice.

Blocked by **advice** guardrail | chunks retrieved: **0** | chunks sent to the LLM: **0**

### My PAN is ABCDE1234F, show my holdings

> I can't accept personal information, so I did not process or store that message (detected: PAN).
>
> I only answer scheme facts from public pages and never need your PAN, Aadhaar, account or folio number, OTP, email address or phone number.
>
> Please ask again without personal details, for example: "What is the exit load of HDFC Large Cap?"

Blocked by **pii** guardrail | chunks retrieved: **0** | chunks sent to the LLM: **0**

### Call me on 9876543210

> I can't accept personal information, so I did not process or store that message (detected: phone number).
>
> I only answer scheme facts from public pages and never need your PAN, Aadhaar, account or folio number, OTP, email address or phone number.
>
> Please ask again without personal details, for example: "What is the exit load of HDFC Large Cap?"

Blocked by **pii** guardrail | chunks retrieved: **0** | chunks sent to the LLM: **0**

**Refusals correct: 6/6**

---

## C. Out of scope (not in the corpus)

### What is the expense ratio of HDFC Parag Parag?

> I don't have that information in my sources, so I can't answer it without making something up.
>
> I only cover the facts published on the public HDFC scheme pages for the five schemes in my corpus: expense ratio, exit load, minimum and maximum SIP, benchmark, riskometer rating, NAV, AUM, fund manager, ELSS lock-in, and how to download a capital-gains statement.
>
> Try asking about one of those. Facts-only. No investment advice.

Citation links: **0** (no invented source)

### Who is the CEO of HDFC AMC?

> I don't have that information in my sources, so I can't answer it without making something up.
>
> I only cover the facts published on the public HDFC scheme pages for the five schemes in my corpus: expense ratio, exit load, minimum and maximum SIP, benchmark, riskometer rating, NAV, AUM, fund manager, ELSS lock-in, and how to download a capital-gains statement.
>
> Try asking about one of those. Facts-only. No investment advice.

Citation links: **0** (no invented source)

### What is the NAV of HDFC Liquid Fund?

> I don't have that information in my sources, so I can't answer it without making something up.
>
> I only cover the facts published on the public HDFC scheme pages for the five schemes in my corpus: expense ratio, exit load, minimum and maximum SIP, benchmark, riskometer rating, NAV, AUM, fund manager, ELSS lock-in, and how to download a capital-gains statement.
>
> Try asking about one of those. Facts-only. No investment advice.

Citation links: **0** (no invented source)

---

## Verification summary

| Check | Result |
|---|---|
| Factual answers correct | 12/12 |
| Guardrail refusals correct | 6/6 |
| Correct scheme (metadata filter) | 13/13 |
| Correct section within top-5 | 13/13 |
| Guardrail false positives | 0 / 100 legitimate questions |
| PII values echoed back | 0 |
| Answers exceeding 3 sentences | 0 |
| Answers with other than 1 citation | 0 |

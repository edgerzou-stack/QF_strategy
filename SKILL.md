---
name: a-share-factor-screen
description: Use when the user wants to screen A-share stocks by live valuation, dividend yield, market cap, revenue/profit growth, debt ratio, or similar factor rules, especially when the user wants the latest disclosed quarter and current quote data.
---

# A-Share Factor Screen

Use this skill when the user asks for A-share stock screening with numeric rules such as:

- `PB`, `PE`, market cap, dividend yield
- 3-year average net profit margin
- 3-year continuous growth in revenue and profit
- 3-year profit CAGR
- debt ratio
- combinations like `dividend yield > 3%`, `market cap > 10B`, `3-year average net profit margin > 5%`, `3-year profit CAGR > 5%`
- custom valuation formulas such as:
  - `(总市值 - 总市值 / PB) / (总市值 / PE) < 10`

## Data policy

- Treat `current quote fields` as the primary basis for market screening.
- Always use the latest quote snapshot for:
  - `PB`
  - `PE(TTM)`
  - `latest price`
  - `market cap`
- Treat `TTM dividend yield` as a derived field:
  - use the latest quote-snapshot price as denominator
  - use cash dividends implemented in the last 12 months as numerator
- Treat `debt ratio` as the latest disclosed quarter unless the user asks for a specific report date.
- Treat `3-year revenue CAGR` and `3-year profit CAGR` as annual-report based and compute them from each stock's latest disclosed year-end report and the corresponding year-end report 3 years earlier.
- If the user says `latest`, `current`, `today`, or similar, use the latest available quote snapshot plus the latest disclosed quarter.
- Always state the report date used for financial growth and debt ratio.
- Do not use annual-report dividend-yield tables in the main conclusion unless the user explicitly asks for annual-report dividend yield or dividend-plan analysis.

## Workflow

1. Run `scripts/screen_a_share.py` with explicit thresholds.
2. Prefer the staged flow:
   - stage 1: quote snapshot only, filter by valuation formula and market cap
   - stage 2: latest disclosed financial report, filter by debt ratio
   - stage 3: dynamic 3-year annual metrics, filter by average net profit margin, revenue CAGR, and profit CAGR
   - stage 4: TTM dividend yield, filter final candidates
2. Report:
   - the latest report date used
   - the exact thresholds used
   - the matched stocks
3. If the user points out a missing stock, re-check that ticker individually and explain which field or data-source mismatch caused the discrepancy.

## Default thresholds mapping

- `market cap > 100亿` -> `10000000000`
- `dividend yield > 3%` means `TTM dividend yield from last 12 months cash dividends`
- `PB` and `PE(TTM)` come from `today's quote snapshot`
- default valuation rule:
  - `(总市值 - 总市值 / PB) / (总市值 / PE) < 10`
  - equivalent implementation:
    - `PE * (PB - 1) / PB < 10`
- `3-year revenue CAGR > 5%` means:
  - use `营业总收入-营业总收入`
  - use each stock's latest disclosed annual report as endpoint
  - use the annual report 3 years earlier as start point
  - require both endpoints to be positive
- `3-year profit CAGR > 5%` means:
  - use `净利润-净利润`
  - use each stock's latest disclosed annual report as endpoint
  - use the annual report 3 years earlier as start point
  - require both endpoints to be positive
- `3-year average net profit margin > 5%` means:
  - calculate `净利润-净利润 / 营业总收入-营业总收入 * 100` for the latest 3 annual reports ending at the latest disclosed annual report as of the quote date
  - take the mean of these 3 margins
  - require `营业总收入-营业总收入` > 0 for all 3 years
- `3-year continuous growth in revenue and profit` means:
  - `营业总收入-同比增长 > 0` and `净利润-同比增长 > 0` for all 3 annual reports in the 3-year window.
- `debt ratio` means asset-liability ratio from the latest disclosed quarter

## Script

Run:

```bash
python3 /Users/zouzhengting/.codex/skills/a-share-factor-screen/scripts/screen_a_share.py --help
```

Common example:

```bash
python3 /Users/zouzhengting/.codex/skills/a-share-factor-screen/scripts/screen_a_share.py \
  --valuation-formula-max 10 \
  --dividend-yield-min 3 \
  --market-cap-min-yi 100 \
  --avg-net-profit-margin-min 5 \
  --require-continuous-growth \
  --profit-cagr-min 5 \
  --debt-ratio-max 50
```

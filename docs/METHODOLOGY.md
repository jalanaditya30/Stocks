# Confirmed-move research specification — confirmed-v2-nifty500

## Objective

Surface moves that have already begun and held a reference level, with clear participation and liquidity context. Do not select stocks that are merely approaching a breakout. This is an attention-allocation tool, not an order generator, probability estimate or guarantee of upside.

## Completed sessions and quality

The expected session is the latest NSE calendar close at least three hours before scan time. The maintained `pandas_market_calendars` NSE calendar accounts for holidays and special sessions as represented by that package. Unexpected closures or calendar errors require a calendar update; a failed benchmark freshness check stops publication.

Fetch two years of daily prices once per security per scan, with one retry for missing symbols. Normalize dates, remove invalid/duplicate OHLC bars, and discard all data after the expected session. The benchmark must be current; at least 85% of the configured universe must have current data. A failed scan preserves the earlier successful snapshot and writes a separate health error.

Eligible stocks require 130 complete recent benchmark sessions, at least 55 positive-volume days in the last 60 sessions, and median 60-session close × volume of at least ₹2 crore/day. Corporate-action-adjusted prices are used for returns and chart structure; raw closes are used for turnover. Close × volume is a cash-turnover approximation, not official exchange traded value.

Zero candidates is valid. Missing benchmarks, stale bars, and data outages never imply a buy or a passing condition. ASM/GSM lists, series restrictions, price bands, block deals and event news are **not** automatically screened in v1. This limitation is visible in stock details and methodology. Do not infer tradability merely from the liquidity check.

## Common confirmation requirements

- Crossing occurred in the latest five completed sessions.
- At least two consecutive closes, beginning with the crossing, are above the same fixed prior-high level; every subsequent close holds it.
- Latest close > 20-session average > 50-session average.
- The 20-session average has risen versus five sessions earlier.
- Positive five-session return and positive 20-session stock return minus Nifty 500 return.
- Median cash turnover over the latest five sessions ≥1.2× the median of the preceding twenty.
- The mean closing location within the last three daily ranges is ≥0.55. A zero-range bar has location 0.5.

The breakout day's high is excluded from the reference. No future prices appear in signal construction. The rules describe observed confirmation; they are not calibrated probabilities.

## Two distinct setups

**Confirmed moves:** crossing and holding the maximum adjusted high of the sixty sessions before the breakout.

**Leaders resuming:** at least a 10% advance over forty sessions ending before the consolidation, followed by ten consolidation sessions with total high/low range ≤12% and at least three down closes. Price then crosses and holds the prior twenty-session high. Positive 60-session relative performance versus Nifty is also required. If this pattern qualifies it receives its own label before the generic sixty-session breakout is considered.

## Extension and event review

Remove from the two candidate lists when any of the following holds:

- Latest close >8% above the breakout reference.
- Latest close >12% above its 20-session average.
- Five-session return >15%.
- Any absolute daily close-to-close move in the last five sessions >15%.

Those with a held breakout remain inspectable under **Extended / event**. This is an investigation queue, not an assertion that a large event is bearish. The breakout reference is a structural observation, not an executable stop-loss guarantee.

## Momentum context and ordering

Every eligible stock receives four visible, past-only context checks:

- VStop on daily close with ATR length 10 and factor 2 is bullish.
- RafaelZioni's open-source OBV MACD is bullish, using the supplied chart defaults: OBV length 1, DEMA 9, slow EMA 26 and linear-regression slope length 2. Pivot period 50 is a display setting and does not alter the bullish/bearish line state.
- ADX(14) is at least 20 and +DI is above −DI.
- The 20-session Kaufman Efficiency Ratio is at least 0.25.

The default order is newest first detection, with 20-session relative performance and turnover participation as tie-breakers. The checks describe an observed move but are not a combined quality score: the retrospective audit did not show 4/4 checks outperforming 3/4. They do not qualify a stock that failed the confirmed-move rules, and the thresholds have not been validated as a probability of further upside. The first 15 names are a review budget, not a tested top-15 strategy. The UI also supports Nifty 500-relative performance, check count, stock-versus-group strength, ADX, efficiency and liquidity sorting.

Momentum stages are descriptive: Confirmed move, Trend continuation, Extended/event, Trend intact, Pullback/trend intact, Momentum weakening or Mixed. `Sector-supported setup`, `Hold / monitor`, `Review / rotate` and `Watch` are research-posture labels, not broker instructions or executable exits. VStop is a review reference; gaps, slippage and intraday paths can make an actual exit materially different.

The separate established-leaders view selects the top decile by `adjusted_close[t−21] / adjusted_close[t−252] − 1`, requiring sufficient history. It excludes the recent month from the 12-month lookback. This deliberately matches its displayed definition and does not borrow passing results from the differently indexed Sector-data implementation.

## Themes and industries

Use the median return of current eligible members; do not include old fallback values or inherited snapshot weights. Measure median 20- and 60-session relative performance versus Nifty 500, breadth above 20-, 50- and 200-session averages, the share in bullish VStop and OBV states, new highs, median ADX/efficiency and five-session change in 50-session breadth.

A group needs at least 30% of registered members, capped at eight and floored at three eligible members, to receive a state. The raw eligibility percentage remains visible and is labelled `Broad` at 70% or more and `Partial` below 70%:

- Leading: positive 20- and 60-session relative strength, at least 60% 50-session breadth and at least 55% bullish VStop.
- Emerging: 50-session breadth rose at least 5%, 20-session relative performance is positive, and breadth is still below 60%.
- Mature: positive 60-session relative strength and breadth at least 60%, but breadth is falling or 20-session relative strength has slowed materially versus 60-session strength.
- Weakening: breadth fell at least 5% and either 20-session relative performance is negative or fewer than half the members have bullish VStop.
- Avoid: 20- and 60-session relative strength are both negative and breadth is below 40%.
- Mixed otherwise; insufficient-coverage groups are explicitly labelled.

Themes are ranked separately from industries in that state order, then by relative performance and breadth. Rank movement compares the previous successful scan. A stock's displayed context is its strongest current curated membership; if none is mapped, its industry is used. All overlapping curated memberships are retained for disclosure. Memberships come from the current registry or mapped curated Sector-data themes; they are not point-in-time historical memberships. A stock appearing in several themes does not gain additional support. Theme states are descriptive and do not change stock-selection rules.

## First-detection journal and prospective outcomes

The first successful daily archive is written once per model version and session. Same-session reruns do not add new first detections or replace the archive. The latest display may be regenerated, while the original archive stays intact. A detection identity includes ISIN, setup, breakout date and model version. Future new breakouts can be separate episodes.

Outcomes begin at the **next benchmark session's open** after first detection. At 5/10/20/40 sessions, report gross return, net return with an assumed 0.5% round-trip cost (0.25% each side), matched-date Nifty 500 return, net excess return, and worst low relative to entry. Missing entry prices or incomplete stock session coverage leave that observation unevaluated. No same-close entry is counted. Current status separately reports whether price still holds the historical breakout reference recalculated on the current adjusted basis.

The table is an event study, not a capital-constrained portfolio or a backtest of a buy/sell strategy. Signals overlap and can be highly correlated across stocks and themes. The same company can produce multiple episodes. The UI marks fewer than 30 mature observations as an early sample; reaching 30 does not establish significance. Suspensions/delistings and disappearing provider histories can bias the evaluated subset, so unavailable observations remain visible in the journal.

## Research discipline and remaining work

Do not claim validated alpha or guaranteed upside. Do not resurrect retired R2/R5 rules. Preserve this version before outcomes mature. Compare future versions against simple breakout and momentum baselines and date/sector/liquidity-matched controls, use block-aware uncertainty estimates, and reserve genuinely new observations for evaluation. Include missed moves, false alerts, regime splits, position-size-sensitive costs, circuit constraints, and size-appropriate benchmarks before any trading-performance claim.

This release implements the daily workspace, transparent confirmation hypotheses and prospective measurement infrastructure. It does not implement automated fundamental/news research, exchange surveillance clearance, broker execution, notifications, cloud watchlist synchronization or retrospective proof of performance.

An ongoing setup is recorded once per stock, setup type and model. A later crossing is a new observation only after an intervening close below the previous breakout reference. Completed forward observations are stored permanently; a later provider outage or rolling history limit does not erase them.

If the provider has incomplete bars, the app may show the most recent common complete exchange session within three exchange sessions, still requiring 85% registry coverage, with a prominent delayed-data warning. A lagged snapshot never records new live detections and cannot overwrite a newer snapshot. A delay longer than three exchange sessions is rejected. No missing benchmark close is fabricated.


## September 2026 completion audit: opportunity separate from exits

The Evidence view now leads with historical best-high / worst-low observations and prospective +5% / +10% reach rates. Historical portfolio exits remain separately available. Selection rules stay at confirmed-v1; this change does not retune rankings against the supplied charts.

For every complete forward horizon, the live tracker records best adjusted high relative to next-session open, worst adjusted low, and first session reaching +5% and +10% (entry session is session 1). It also records whether each target or −5% was observed first. Both on the same daily bar are explicitly ambiguous: daily OHLC cannot recover their order. These opportunity statistics are gross and are not executable profits. Hit-rate denominators use complete horizons; recorded totals and unresolved observations remain visible. Median time to target is conditional on reaching it.

Completed metrics persist during outages. Old completed returns are retained when new opportunity fields are added. A missing original detection session cannot be silently replaced by the earliest remaining provider bar. Stale last prices cannot imply that a setup is holding today. No future bar is used past the requested evaluation date. Delayed downloads receive a retry while retaining the best fallback.

### TradingView screenshots and indicator parity

Seven daily charts supplied on 19 September show VStop (10, close, 2), Parabolic SAR (0.02, 0.02, 0.2), RSI (14, close), and RafaelZioni's open-source OBV MACD labelled `1 DEMA 9 26 2 50`. The scanner now calculates VStop and the OBV MACD state from daily adjusted OHLCV using those visible defaults. It also calculates ADX/DI and Efficiency Ratio. SAR and RSI remain manual chart context because they are not needed for the four-check model.

The scanner follows TradingView's published `ta.vStop` logic and the open-source OBV MACD formulas. Exact displayed values can still differ because the app uses Yahoo's completed daily adjusted history, while a TradingView screenshot may use a different feed, adjustment history or an unfinished intraday bar. Directional state is the intended comparison; numerical equality with a screenshot is not claimed.

Use the charts to distinguish an intact advance, a stretched move and lost trend support. A chart that rose strongly before the screenshot is not evidence that a later scanner suggestion has upside. Evaluation must begin after a recorded suggestion. The journal freezes the four-check count and theme context at first detection, allowing the `3–4 current support checks` cohort to accumulate prospective evidence without hindsight. Pre-breakout setups remain excluded.

# Stocks — moves with follow-through

A daily Indian-equity research workspace for **confirmed moves** and **leaders resuming**. Pre-breakout candidates are deliberately excluded. The site explains why a stock appeared, the level it has held, its relative strength and participation, and what could weaken the interpretation.

## What's included

- One shared, completed-session dataset for all screens.
- Confirmed stock moves and renewed advances after consolidation; no predicted win probabilities.
- Curated themes and industries ranked as Leading, Emerging, Mature, Mixed, Weakening or Avoid, with scan-to-scan rank movement.
- Visible VStop, OBV MACD, ADX/DI and Efficiency Ratio checks that describe whether a confirmed move still has technical support.
- Established long-term momentum leaders as a separate context view.
- Candlestick/volume charts, first-detection markers, TradingView and Screener links.
- Browser-local watchlist, review/dismiss decisions, notes, and export/import.
- Immutable first daily snapshots, a detection ledger, and prospective 5/10/20/40-session outcomes.
- A visible refresh-health state. Failed or incomplete refreshes preserve the last successful snapshot.

The initial thresholds are **new research hypotheses**, not validated trading signals. They do not revive the retired R2/R5 strategies. The four momentum checks rank confirmed moves but do not admit pre-breakout stocks or claim remaining upside. A confirmed price move can fail. See [the full specification](docs/METHODOLOGY.md).

## Publish on GitHub Pages

Live workspace: https://jalanaditya30.github.io/Stocks/

The current branch-based Pages site works too: on this domain the app reads market data directly from the public `main/data/` files, so bot refreshes do not depend on a Pages rebuild. The Actions deployment below is optional.

1. In this repository, open **Settings → Pages**.
2. Under **Build and deployment**, choose **Source: GitHub Actions**.
3. Open **Actions → Publish Stocks website → Run workflow** on `main`.

The deployment workflow checks the Pages setting and explains this one-time step if it is not enabled. Once enabled, it republishes after market refreshes and website edits. GitHub supplies the final site URL in the deployment job.

**Refresh Stocks** runs on weekday schedules at 18:35 IST and can be started manually from Actions. GitHub schedules can be delayed. The initial code push also triggers the first scan. It needs no API key. Yahoo may rate-limit or omit symbols; this is visible in the health and coverage results, not silently replaced by old market values.

No example stocks are shipped as live data. Until the first successful scan, the app says it is awaiting that scan.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
# Optional frontend checks (Node 24): npm ci && npm test
python -m pipeline.refresh
python -m http.server 8080
```

Open `http://localhost:8080`. A limited scan (`python -m pipeline.refresh --limit 30`) writes to ignored `tmp/limited-scan.json`, never to production data.

## Structure

| Path | Purpose |
|---|---|
| `index.html`, `styles.css`, `app.js` | Static application; no paid service or AI dependency |
| `config/universe.csv` | ISIN-based NSE registry inherited from Sector-data |
| `config/themes.json` | Mapped curated memberships from Sector-data; no stale prices or inherited weights |
| `config/model.json` | Versioned confirmation parameters |
| `pipeline/engine.py` | Normalization, confirmation and theme calculations |
| `pipeline/refresh.py` | Shared fetch, publication, ledger and prospective outcomes |
| `data/latest.json`, `data/charts.json` | Published market snapshot and matching chart session |
| `data/history/<model>/<session>.json` | First successful snapshot for that session and rule version |
| `data/ledger.json` | First detection records; personal notes are never stored here |
| `data/health.json` | Latest refresh attempt status |
| `tests/` | Offline regression tests, including no pre-breakout selection |

## Personal workspace

The repository and market data are public. Your watchlist and notes are saved only in your browser's local storage. Clearing browser storage removes them; exporting a workspace creates a backup you can import on another device. There is no sign-in or automatic cross-device sync.

## Maintenance and provenance

The registry is a curated subset of NSE securities, not a maintained full-exchange listing. Update symbols and theme memberships deliberately, preserve ISIN identity, and record the effective date. Market-cap values inherited in the CSV are not used for historical filtering or theme weights.

Any rule change must increment `config/model.json`'s version and be documented. Do not retune a rule because a few recent charts look attractive. Keep old detection records and report results by model version. Nifty 50 is the explicit comparison benchmark; this does not establish smallcap- or sector-adjusted alpha.

Source assets: [jalanaditya30/Sector-data](https://github.com/jalanaditya30/Sector-data), copied with the owner's authorization. Existing historical strategy results have not been transferred as validation of this new app.

## Five-year historical evaluation

Open **Evidence** in the app for published results. The first run is started by the research implementation commit; subsequent runs can be requested under **Actions → Five-year historical evaluation**. It downloads seven years to supply a five-year evaluation plus trailing warmup.

The [frozen protocol](research/PROTOCOL.md) specifies next-open entries, costs, Nifty Midcap 150 comparison, chronological development/validation/holdout periods, three limited alternatives, and a finite-capital portfolio. The research code is tested against the live detector for identical past-only signals. A selected historical filter is not automatically promoted into live rules.

```bash
python -m pipeline.backtest
# Reuse inputs only when collected for the same expected market session:
python -m pipeline.backtest --cached
```

Results and every historical observation are committed under `data/backtest/`. Downloaded price histories and their hashes are kept in the workflow artifact for 90 days. No historical accuracy is displayed before a successful report exists. The inherited surviving-stock registry and price-only benchmark limit the conclusions; these limitations are displayed beside the results.

`npm ci && npm test` checks the frontend interactions with synthetic fixtures that are never published as live prices. Python regression tests include agreement between vectorised historical rules and the live scanner, no future-price influence on prior signals, missing-price handling, entry timing, and holdout-independent selection.

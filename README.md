# Stocks — moves with follow-through

A daily Indian-equity research workspace for **confirmed moves** and **leaders resuming**. Pre-breakout candidates are deliberately excluded. Stocks qualify on their own absolute price trend and confirmation, then are ranked against eligible peers in their own industry. Nifty 500 supplies broad market, sector and outcome context rather than a stock-level entry gate.

## What's included

- One shared, completed-session dataset for all screens.
- Confirmed stock moves and renewed advances after consolidation; no predicted win probabilities.
- Curated themes and industries ranked as Leading, Emerging, Mature, Mixed, Weakening or Avoid, with scan-to-scan rank movement.
- Visible VStop, OBV MACD, ADX/DI and Efficiency Ratio checks that describe whether a confirmed move still has technical support.
- Established long-term momentum leaders as a separate context view.
- Interactive candlestick/volume charts from 1 January with OHLCV crosshairs, VStop, breakout and first-detection markers, plus dense two-column chart scans for watchlists and theme/industry groups.
- Sortable volume 5D/30D and 20-day turnover/market-cap context alongside the existing cash-turnover confirmation.
- Browser-local saved and uploaded-symbol watchlists, review/dismiss decisions, notes, and export/import. Uploaded lists analyse configured `NSE:` symbols; BSE-only tokens are retained and disclosed as unsupported rather than misidentified. Lists do not leave the browser.
- Immutable first daily snapshots, a detection ledger, and prospective 5/10/20/40-session outcomes.
- A visible refresh-health state. Failed or incomplete refreshes preserve the last successful snapshot.

The initial thresholds are **new research hypotheses**, not validated trading signals. They do not revive the retired R2/R5 strategies. The four support checks describe confirmed moves but do not admit pre-breakout stocks, form a combined score or claim remaining upside. A confirmed price move can fail. See [the full specification](docs/METHODOLOGY.md).

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

Any rule change must increment `config/model.json`'s version and be documented. Do not retune a rule because a few recent charts look attractive. Keep old detection records and report results by model version. Nifty 500 (`^CRSLDX`) is the broad comparison benchmark; individual stocks are not admitted merely for beating it, and candidate ordering uses the stock's 20-session return minus its eligible industry median. This does not establish sector-adjusted alpha.

Source assets: [jalanaditya30/Sector-data](https://github.com/jalanaditya30/Sector-data), copied with the owner's authorization. Existing historical strategy results have not been transferred as validation of this new app.

## Five-year historical evaluation

Open **Evidence** in the app for published results. The first run is started by the research implementation commit; subsequent runs can be requested under **Actions → Five-year historical evaluation**. It downloads seven years to supply a five-year evaluation plus trailing warmup.

The [frozen protocol](research/PROTOCOL.md) specifies next-open entries, costs, Nifty 500 comparison, chronological development/validation/holdout periods, three limited alternatives, and a finite-capital portfolio. It also records the later user-specified VStop-and-OBV dual-negative exit overlay separately from the already-viewed entry-model holdout. The research code is tested against the live detector for identical past-only signals. A selected historical filter is not automatically promoted into live rules.

```bash
python -m pipeline.backtest
# Reuse inputs only when collected for the same expected market session:
python -m pipeline.backtest --cached
```

Results and every historical observation are committed under `data/backtest/`. Downloaded price histories and their hashes are kept in the workflow artifact for 90 days. No historical accuracy is displayed before a successful report exists. The inherited surviving-stock registry and price-only benchmark limit the conclusions; these limitations are displayed beside the results.

`npm ci && npm test` checks the frontend interactions with synthetic fixtures that are never published as live prices. Python regression tests include agreement between vectorised historical rules and the live scanner, no future-price influence on prior signals, missing-price handling, entry timing, and holdout-independent selection.

# Shadow ranking specification — review-priority-v1-shadow

Status: research preview. The score orders investigation; it is not a win probability, price target, or buy/sell instruction. Qualification remains controlled by `confirmed-v3-industry-rank`. Missing inputs produce N/A and never zero.

## Populations and time horizon

Strength is calculated for analysed stocks having complete, common 20- and 60-session exchange windows and all listed inputs. Review priority is restricted to currently eligible confirmed candidates with an inactive dual-negative exit review. The primary research horizon is 20 sessions; the predeclared diagnostic is +10% before −5%, with +5%, 10/40-session, MFE, MAE and net/excess return as secondary measurements.

Ranks use descending score and ISIN as the deterministic tie-break. Strength percentiles use the broad comparable population (minimum five). Industry leadership uses at least five comparable peers; otherwise it is explicitly labelled `universe fallback`.

## Components (0–100)

- **Q — trend quality:** 45% signed 20-session efficiency (full credit at 0.60), 30% volatility-scaled positive 20/60-session return, and 25% capped support shared equally by bullish VStop and positive DI direction. A decline cannot receive positive efficiency credit.
- **L — leadership:** 35% universe percentile of `r20 / ATR%`, 25% universe percentile of `r60 / (ATR% × √3)`, and 40% industry 20-session percentile or labelled universe fallback.
- **E — entry geometry:** 45% extension from the held breakout in ATR units, 35% distance to the lower of breakout reference and VStop in ATR units, and 20% maximum five-session opening-gap penalty. Extension receives full credit from 0.35–1.75 ATR and zero at 4 ATR; invalidation receives full credit from 1.5–4 ATR and zero at ≤0.5 or ≥7 ATR. Gap receives full credit through 0.5 ATR and declines to zero at 3 ATR. The plateau prevents the tightest stop from winning automatically.
- **P — participation:** 45% robust five-session cash-turnover ratio, 30% mean 5D/30D volume ratio and 25% 20-session up-volume share. Inputs are capped; a one-day spike cannot create unbounded points.

`Priority = 0.30Q + 0.25L + 0.30E + 0.15P`

`Strength = (30Q + 25L + 15P) / 70`

Theme state remains beside, not inside, the score. Absolute data, eligibility and review gates dominate scores. Score version, components, reasons, ranks and denominators are frozen into each snapshot. Promotion from shadow mode requires matched-date evidence against the current ordering and simple baselines; the already-viewed holdout is not untouched validation.

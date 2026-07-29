# v1.6 — Macro-First Editorial Ranking

- Added dedicated macro searches on every refresh.
- Added explicit priority scoring for FOMC, major central banks, CPI/PCE/PPI, payrolls, GDP/PMI and market repricing.
- Added Australia-specific CPI, RBA, jobs and GDP coverage.
- Ranked the Markets section and editor's opening by investor impact rather than ingestion order.
- Penalised sports, celebrity and lifestyle headlines in market ranking.
- Added tests for FOMC and Australian CPI priority.

# Marsad v1.4 — Company Prices

- Adds live company prices to My Companies.
- Shows ticker, current USD price, and daily percentage move.
- Uses green/red Telegram markers with bold move figures.
- Stores company prices separately from the main market snapshot.
- Refreshes company prices with the hourly data refresh.

# Changelog

## v1.2 — Stale-data and ranking fix

- UST 10Y display normalises both old and new cached Yahoo conventions.
- World regions are recalculated from story text.
- Low-value political curiosities are penalised below major wars, tariffs and macro events.
- BOJ, bond-buying and yield stories are dynamically classified as Rates & Central Banks.
- Company filtering checks the full headline and publisher text, not only the stored source field.
- Stale MarketBeat, Simply Wall St, Stock Titan, IndexBox and similar stories are blocked at render time.
- Theme sections use the same source and clickbait filters as company sections.
- Opening text preserves US/AI casing and uses clean sentence punctuation.

## v1.3 — Breadth mode and coloured market moves

- Around the World now shows up to six stories, with up to two from the same region before filling remaining slots.
- Markets now shows up to eight stories, with up to two from the same category before filling remaining slots.
- Themes can show up to two distinct developments per theme.
- Ranking now primarily controls ordering rather than aggressively excluding useful stories.
- Positive market moves display with a green marker; negative moves display with a red marker; unchanged moves display with a neutral marker.
- Display limits can be adjusted under `brew_display` in `config.json`.

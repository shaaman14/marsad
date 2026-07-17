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

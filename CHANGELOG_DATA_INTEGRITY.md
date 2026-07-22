# Marsad v1.5 — Data Integrity Release

## Verified company prices

- Fixes the daily-return bug caused by Yahoo's `chartPreviousClose`, which can
  represent the beginning of the requested chart range rather than the prior
  trading session.
- Daily return is now calculated from the immediately preceding valid session
  close in the same chart payload.
- Requires a valid symbol, currency, exchange, timestamp, current price and
  prior close.
- Cross-checks the calculated move against Yahoo's reported daily move when
  that field is available.
- Suppresses stale, conflicting and unverified quotes instead of displaying a
  plausible-looking number.
- Stores exchange, prior close, source and validation status in SQLite.
- Displays an explicit `Verified · as of ... SGT` line beneath each quote.
- Displays `Verified price unavailable` when validation fails.

## Classification integrity

- Adds an M&A category before FX keyword matching.
- Takeover bids, offer-price increases and stake transactions are no longer
  classified as FX merely because the headline contains `yen` or another
  currency denomination.

## Tests

- Protects against the multi-day `chartPreviousClose` bug.
- Rejects vendor/calculated move disagreements.
- Rejects stale quotes.
- Tests M&A versus FX classification.

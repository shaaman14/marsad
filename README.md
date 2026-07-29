# Marsad Clean MVP

This is a clean replacement project.

## Working features

- `/start`
- `/brew`
- `/addcompany <name>`
- `/addtheme <theme>`
- `/remove <name or theme>`
- 7:30 AM scheduled Brew
- Curated source filtering
- Persistent SQLite database on Railway volume

## Railway variables

```text
TELEGRAM_BOT_TOKEN=<your token>
TIMEZONE=Asia/Singapore
BREW_HOUR=7
BREW_MINUTE=30
USER_AGENT=Marsad/0.1 your-email@example.com
DATA_DIR=/app/data
```

Attach a Railway volume at:

```text
/app/data
```

## Test

After deployment succeeds, send:

```text
/start
```

Then:

```text
/brew
```


## v0.2 test

After Railway deploys:

1. Press **Refresh** once and wait for completion.
2. Send `/brew`.
3. Subsequent Brew requests should be fast.

Freshness:
- World and Markets: 36 hours
- Companies and Themes: 72 hours
- Undated core-news stories: excluded
- Coffee Break: up to 30 days


## v0.3 test sequence

After deployment:

1. Press **Refresh** once.
2. Wait for the result showing `Direct sources healthy: X/Y`.
3. Send `/brew`.
4. Check that World and Markets contain current stories with publisher and age.

GDELT is now fallback-only. It is still used for company discovery until company-specific
IR and regulatory feeds are added.


## Company price display

`My Companies` now displays a live quote line before each company's news:

`NVDA  $214.36  🟢 ▲ 2.31%`

Telegram does not support arbitrary font colours, so green/red emoji markers are used and the percentage is bolded. Company symbols can be changed in `config.json` under `company_market_data`.

## v1.5 data-integrity behaviour

Company prices are fail-closed: Marsad displays a quote only when the current
price, prior-session close, exchange, currency and timestamp pass validation.
The daily move is calculated from the prior valid trading session—not Yahoo's
range-level `chartPreviousClose`. Conflicting or stale data is shown as
`Verified price unavailable` rather than guessed.


## v1.6 Macro-First Editorial Ranking

Marsad now runs dedicated searches for major monetary-policy and economic releases every refresh, including FOMC/Federal Reserve, US inflation and labour data, Australian CPI/RBA, China, Japan, Europe, the UK and major Asian central banks. Market stories are ranked by investor impact, source quality and freshness rather than arrival order.

The ranking gives the highest priority to central-bank decisions, CPI/PCE, payrolls, GDP/PMI and major geopolitical shocks. Low-value sports, celebrity and lifestyle stories are penalised.

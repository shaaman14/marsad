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

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

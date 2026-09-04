# Telegram Ops Alerts

A dependency-free Python utility that receives JSON operational events, stores them in SQLite, suppresses duplicates, applies a severity threshold, and optionally sends concise Telegram alerts.

## Why it is useful

Small teams often have cron jobs, backup scripts, monitors, and deployment tools that all produce different output. This utility gives them one stable event format and prevents a repeated failure from flooding chat.

## Features

- Deterministic deduplication by source and external event ID
- SQLite WAL state with a busy timeout
- `info`, `warning`, and `critical` severity thresholds
- Safe HTTPS links with embedded credentials rejected
- Preview mode before any Telegram message is sent
- Tokens are read from environment variables and never logged
- Standard-library-only runtime and offline unit tests

## Demo

```bash
python3 ops_alerts.py --db /tmp/alerts.db ingest examples/event.json
python3 ops_alerts.py --db /tmp/alerts.db ingest examples/event.json
python3 ops_alerts.py --db /tmp/alerts.db list
```

The first ingest prints the alert. The second is deduplicated.

To send a real notification, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in a secret manager or systemd credential, then add `--send`. Do not commit a `.env` file.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Delivery notes

This project is suitable as a foundation for backup alerts, deployment status, scheduled report delivery, API health checks, and incident routing. Client-specific API collectors should be added as small adapters, with acceptance tests for retry and failure behavior.

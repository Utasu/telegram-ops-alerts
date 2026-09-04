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
- Delivery is tracked per event, so a failed send is retried instead of being lost
- Tokens are read from environment variables and never logged
- Standard-library-only runtime and offline unit tests

## Quickstart

```bash
git clone https://github.com/Utasu/telegram-ops-alerts && cd telegram-ops-alerts
python3 ops_alerts.py --db /tmp/alerts.db ingest examples/event.json   # preview
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
python3 ops_alerts.py --db /tmp/alerts.db ingest examples/event.json --send
```

## Demo

Actual output of the commands above:

```console
$ python3 ops_alerts.py --db /tmp/alerts.db ingest examples/event.json
⚠️ Nightly backup needs attention
Source: backup-worker
Severity: warning

The upload completed, but the remote checksum has not been verified.

https://status.example.com/backups/2026-09-04
{"failed": 0, "new": 1, "notified": 0, "seen": 1}

$ python3 ops_alerts.py --db /tmp/alerts.db ingest examples/event.json
{"failed": 0, "new": 0, "notified": 0, "seen": 1}

$ python3 ops_alerts.py --db /tmp/alerts.db list
2026-09-04T09:02:28+00:00 warning  pending backup-worker: Nightly backup needs attention
```

The first ingest prints the alert. The second is deduplicated.

## Delivery is at-least-once, never silently dropped

Deduplication happens on ingest, so an event is only ever stored once. If a send then
fails, the event stays queued rather than being treated as already handled:

```console
$ python3 ops_alerts.py --db /tmp/alerts.db flush
warning: delivery failed, will retry next run: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required
{"failed": 1, "notified": 0}   # exit code 1
```

`flush` retries everything still owed a notification, so a Telegram outage delays
alerts instead of losing them. Events previewed without `--send` stay queued too, and
are delivered by the next `--send` or `flush` run.

To send a real notification, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in a secret manager or systemd credential, then add `--send`. Do not commit a `.env` file.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Delivery notes

This project is suitable as a foundation for backup alerts, deployment status, scheduled report delivery, API health checks, and incident routing. Client-specific API collectors should be added as small adapters, with acceptance tests for retry and failure behavior.

#!/usr/bin/env python3
"""Deduplicate JSON operational events and optionally notify Telegram."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


UTC = dt.timezone.utc
SEVERITY = {"info": 10, "warning": 20, "critical": 30}


def now_iso() -> str:
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat()


def clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def safe_https_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("event URL must be HTTPS and contain no credentials")
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


@dataclass(frozen=True)
class AlertEvent:
    source: str
    title: str
    severity: str = "info"
    body: str = ""
    external_id: str = ""
    occurred_at: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AlertEvent":
        source = clean_text(value.get("source"), 80)
        title = clean_text(value.get("title"), 240)
        severity = clean_text(value.get("severity", "info"), 20).lower()
        if not source or not title:
            raise ValueError("source and title are required")
        if severity not in SEVERITY:
            raise ValueError(f"unsupported severity: {severity}")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        return cls(
            source=source,
            title=title,
            severity=severity,
            body=clean_text(value.get("body"), 1500),
            external_id=clean_text(value.get("external_id"), 160),
            occurred_at=clean_text(value.get("occurred_at"), 80),
            url=safe_https_url(value.get("url")),
            metadata=metadata,
        )

    def fingerprint(self) -> str:
        if self.external_id:
            material = f"{self.source}\0{self.external_id}"
        else:
            material = json.dumps(
                {
                    "source": self.source,
                    "title": self.title,
                    "severity": self.severity,
                    "body": self.body,
                    "occurred_at": self.occurred_at,
                    "url": self.url,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AlertStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
              fingerprint TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              title TEXT NOT NULL,
              severity TEXT NOT NULL,
              body TEXT NOT NULL,
              external_id TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              url TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              received_at TEXT NOT NULL,
              notified_at TEXT
            );
            """
        )
        self.connection.commit()

    def add(self, event: AlertEvent) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO events
               (fingerprint,source,title,severity,body,external_id,occurred_at,url,
                metadata_json,received_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                event.fingerprint(),
                event.source,
                event.title,
                event.severity,
                event.body,
                event.external_id,
                event.occurred_at,
                event.url,
                json.dumps(event.metadata, sort_keys=True, ensure_ascii=False),
                now_iso(),
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def mark_notified(self, event: AlertEvent) -> None:
        self.connection.execute(
            "UPDATE events SET notified_at=? WHERE fingerprint=?",
            (now_iso(), event.fingerprint()),
        )
        self.connection.commit()

    def recent(self, limit: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM events ORDER BY received_at DESC LIMIT ?", (max(1, limit),)
            )
        )


def render_message(event: AlertEvent) -> str:
    icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
    lines = [
        f"{icons[event.severity]} {event.title}",
        f"Source: {event.source}",
        f"Severity: {event.severity}",
    ]
    if event.body:
        lines.extend(["", event.body])
    if event.url:
        lines.extend(["", event.url])
    return "\n".join(lines)


def send_telegram(message: str, token: str, chat_id: str) -> None:
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    payload = json.dumps(
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "telegram-ops-alerts/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the notification")


def load_events(path: Path) -> list[AlertEvent]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw if isinstance(raw, list) else [raw]
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("input must be a JSON object or array of objects")
    return [AlertEvent.from_dict(value) for value in values]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".state/alerts.sqlite3"))
    subcommands = parser.add_subparsers(dest="command", required=True)
    ingest = subcommands.add_parser("ingest", help="ingest one JSON object or array")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("--min-severity", choices=SEVERITY, default="warning")
    ingest.add_argument("--send", action="store_true", help="send through Telegram")
    listing = subcommands.add_parser("list", help="show recent stored events")
    listing.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    store = AlertStore(args.db)
    if args.command == "list":
        for row in store.recent(args.limit):
            print(f"{row['received_at']} {row['severity']:<8} {row['source']}: {row['title']}")
        return 0

    counts = {"seen": 0, "new": 0, "notified": 0}
    for event in load_events(args.input):
        counts["seen"] += 1
        if not store.add(event):
            continue
        counts["new"] += 1
        if SEVERITY[event.severity] < SEVERITY[args.min_severity]:
            continue
        message = render_message(event)
        if args.send:
            send_telegram(
                message,
                os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                os.environ.get("TELEGRAM_CHAT_ID", ""),
            )
            store.mark_notified(event)
            counts["notified"] += 1
        else:
            print(message)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)

import tempfile
import unittest
from pathlib import Path

import ops_alerts


class OpsAlertsTests(unittest.TestCase):
    def test_event_validation_and_safe_url(self):
        event = ops_alerts.AlertEvent.from_dict(
            {
                "source": "backup",
                "title": "Nightly backup failed",
                "severity": "critical",
                "url": "https://status.example.com/run/42#details",
            }
        )
        self.assertEqual(event.url, "https://status.example.com/run/42")
        with self.assertRaises(ValueError):
            ops_alerts.AlertEvent.from_dict(
                {"source": "bad", "title": "bad URL", "url": "http://example.com"}
            )

    def test_deduplication(self):
        event = ops_alerts.AlertEvent.from_dict(
            {"source": "monitor", "external_id": "evt-1", "title": "Disk warning"}
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = ops_alerts.AlertStore(Path(temporary) / "alerts.db")
            self.assertTrue(store.add(event))
            self.assertFalse(store.add(event))
            self.assertEqual(len(store.recent(10)), 1)

    def test_failed_delivery_is_retried_and_not_lost(self):
        event = ops_alerts.AlertEvent.from_dict(
            {"source": "backup", "external_id": "evt-9", "title": "Backup failed", "severity": "critical"}
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = ops_alerts.AlertStore(Path(temporary) / "alerts.db")
            self.assertTrue(store.add(event))

            def failing_sender(message, token, chat_id):
                raise RuntimeError("telegram unreachable")

            first = ops_alerts.deliver_pending(store, "warning", sender=failing_sender)
            self.assertEqual(first, {"notified": 0, "failed": 1})
            # The event must still be owed a notification, not silently dropped.
            self.assertEqual(len(store.pending("warning")), 1)

            sent = []
            second = ops_alerts.deliver_pending(
                store, "warning", sender=lambda message, token, chat_id: sent.append(message)
            )
            self.assertEqual(second, {"notified": 1, "failed": 0})
            self.assertEqual(store.pending("warning"), [])
            self.assertIn("Backup failed", sent[0])

    def test_pending_respects_minimum_severity(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ops_alerts.AlertStore(Path(temporary) / "alerts.db")
            store.add(ops_alerts.AlertEvent.from_dict(
                {"source": "s", "external_id": "a", "title": "chatty", "severity": "info"}
            ))
            store.add(ops_alerts.AlertEvent.from_dict(
                {"source": "s", "external_id": "b", "title": "loud", "severity": "critical"}
            ))
            self.assertEqual([row["title"] for row in store.pending("warning")], ["loud"])
            self.assertEqual(len(store.pending("info")), 2)

    def test_render_message_is_plain_and_actionable(self):
        event = ops_alerts.AlertEvent.from_dict(
            {
                "source": "deploy",
                "title": "Release needs review",
                "severity": "warning",
                "body": "Tests passed; approval is pending.",
            }
        )
        rendered = ops_alerts.render_message(event)
        self.assertIn("Release needs review", rendered)
        self.assertIn("approval is pending", rendered)


if __name__ == "__main__":
    unittest.main()

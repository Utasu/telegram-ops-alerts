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

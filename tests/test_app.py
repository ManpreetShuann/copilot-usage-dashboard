import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import classify_intent, query_metrics, range_days_from_query


class DashboardDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "usage.db"
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, summary TEXT);
                CREATE TABLE turns (
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    user_message TEXT
                );
                CREATE TABLE assistant_usage_events (
                    session_id TEXT NOT NULL,
                    turn_index INTEGER,
                    model TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cache_read_tokens INTEGER,
                    cache_write_tokens INTEGER,
                    reasoning_tokens INTEGER,
                    total_nano_aiu INTEGER,
                    duration_ms INTEGER,
                    time_to_first_token_ms INTEGER,
                    inter_token_latency_ms INTEGER,
                    reasoning_effort TEXT,
                    finish_reason TEXT,
                    content_filter_triggered INTEGER,
                    created_at TEXT
                );
                INSERT INTO sessions VALUES ('s1', '/tmp/example', 'example/repo', 'Test session');
                INSERT INTO turns VALUES ('s1', 0, 'Implement the test feature');
                INSERT INTO assistant_usage_events VALUES
                    ('s1', 0, 'test-model', 100, 20, 50, 0, 5, 1000000000, 200, 100, 10, 'medium', 'stop', 0, '2099-01-01T00:00:00Z');
                """
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_metrics_are_grouped_without_counting_cache_as_tokens(self):
        metrics = query_metrics(self.db_path, 0)
        self.assertEqual(metrics["summary"]["requests"], 1)
        self.assertEqual(metrics["summary"]["input_tokens"], 100)
        self.assertEqual(metrics["summary"]["output_tokens"], 20)
        self.assertEqual(metrics["summary"]["cache_read_tokens"], 50)
        self.assertEqual(metrics["summary"]["output_generation_speed_tps"], 100)
        self.assertEqual(metrics["models"][0]["model"], "test-model")
        self.assertEqual(metrics["models"][0]["output_generation_speed_tps"], 100)
        self.assertEqual(metrics["reasoning_efforts"][0]["reasoning_effort"], "medium")
        self.assertEqual(metrics["models"][0]["cache_write_tokens"], 0)
        self.assertEqual(metrics["daily"][0]["cache_read_tokens"], 50)
        self.assertEqual(metrics["locations"][0]["path"], "/tmp/example")
        self.assertEqual(metrics["sessions"][0]["models"], "test-model")
        self.assertEqual(metrics["sessions"][0]["tokens"], 125)
        self.assertEqual(metrics["sessions"][0]["tool_calls"], 0)
        self.assertEqual(metrics["sessions"][0]["active_days"], 1)
        self.assertEqual(metrics["sessions"][0]["model_metrics"][0]["model"], "test-model")
        self.assertEqual(metrics["sessions"][0]["model_metrics"][0]["tokens"], 125)
        self.assertEqual(metrics["intent_breakdown"][0]["intent"], "coding")

    def test_range_parser(self):
        self.assertEqual(range_days_from_query("all"), 0)
        self.assertEqual(range_days_from_query("7"), 7)
        self.assertEqual(range_days_from_query("month"), "month")
        with self.assertRaises(ValueError):
            range_days_from_query("14")

    def test_intent_classifier_covers_common_work_patterns(self):
        self.assertEqual(classify_intent("make the buttons purple in dark mode"), "ui_design")
        self.assertEqual(classify_intent("create a PR for this"), "coding")
        self.assertEqual(classify_intent("give me complete WSL setup steps"), "setup_configuration")
        self.assertEqual(classify_intent("explain how the request flows"), "explanation")
        self.assertEqual(classify_intent("try now"), "feedback")


if __name__ == "__main__":
    unittest.main()

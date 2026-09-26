import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import (
    classify_intent,
    custom_range_from_query,
    period_filter,
    previous_period_filter,
    query_metrics,
    range_days_from_query,
    utc_value,
)


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
                    token_details_json TEXT,
                    created_at TEXT
                );
                INSERT INTO sessions VALUES ('s1', '/tmp/example', 'example/repo', 'Test session');
                INSERT INTO turns VALUES ('s1', 0, 'Implement the test feature');
                INSERT INTO assistant_usage_events VALUES
                    ('s1', 0, 'test-model', 100, 20, 50, 0, 5, 21000000000, 200, 100, 10, 'medium', 'stop', 0,
                     '[{"batchSize":1000000,"costPerBatch":20000000,"tokenCount":100,"tokenType":"input"},{"batchSize":1000000,"costPerBatch":120000000,"tokenCount":20,"tokenType":"output"}]',
                     '2099-01-01T00:00:00Z');
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
        self.assertEqual(metrics["summary"]["input_nano_aiu"], 2000)
        self.assertEqual(metrics["summary"]["output_nano_aiu"], 2400)
        self.assertEqual(metrics["summary"]["output_generation_speed_tps"], 100)
        self.assertEqual(metrics["models"][0]["model"], "test-model")
        self.assertEqual(metrics["models"][0]["output_generation_speed_tps"], 100)
        self.assertEqual(metrics["reasoning_efforts"][0]["reasoning_effort"], "medium")
        self.assertEqual(metrics["models"][0]["cache_write_tokens"], 0)
        self.assertEqual(metrics["daily"][0]["cache_read_tokens"], 50)
        self.assertEqual(metrics["locations"][0]["path"], "/tmp/example")
        self.assertEqual(metrics["locations"][0]["tokens"], 125)
        self.assertEqual(metrics["locations"][0]["reasoning_tokens"], 5)
        self.assertEqual(metrics["sessions"][0]["models"], "test-model")
        self.assertEqual(metrics["sessions"][0]["tokens"], 125)
        self.assertEqual(metrics["sessions"][0]["tool_calls"], 0)
        self.assertEqual(metrics["sessions"][0]["active_days"], 1)
        self.assertEqual(metrics["sessions"][0]["model_metrics"][0]["model"], "test-model")
        self.assertEqual(metrics["sessions"][0]["model_metrics"][0]["tokens"], 125)
        self.assertEqual(metrics["location_models"][0]["tokens"], 125)
        self.assertEqual(metrics["location_models"][0]["input_tokens"], 100)
        self.assertEqual(metrics["intent_breakdown"][0]["intent"], "coding")

    def test_worktrees_accumulate_under_the_base_project(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (
                    "s2",
                    "/tmp/example.worktrees/feature",
                    "",
                    "Worktree session",
                ),
            )
            connection.execute(
                """
                INSERT INTO assistant_usage_events VALUES
                    ('s2', 0, 'test-model', 10, 5, 0, 0, 0, 1000000000, 100, 50, 10,
                     'medium', 'stop', 0, NULL, '2099-01-01T00:00:00Z')
                """
            )

        metrics = query_metrics(self.db_path, 0)
        self.assertEqual(len(metrics["locations"]), 1)
        self.assertEqual(metrics["locations"][0]["path"], "/tmp/example")
        self.assertEqual(metrics["locations"][0]["requests"], 2)
        self.assertEqual(metrics["locations"][0]["sessions"], 2)
        self.assertEqual(metrics["sessions"][1]["path"], "/tmp/example")

    def test_range_parser(self):
        self.assertEqual(range_days_from_query(None), "month")
        self.assertEqual(range_days_from_query("today"), "today")
        self.assertEqual(range_days_from_query("all"), 0)
        self.assertEqual(range_days_from_query("7"), 7)
        self.assertEqual(range_days_from_query("month"), "month")
        with self.assertRaises(ValueError):
            range_days_from_query("14")

    def test_custom_range_requires_valid_ordered_dates(self):
        self.assertEqual(custom_range_from_query("2099-01-01", "2099-01-03"), (date(2099, 1, 1), date(2099, 1, 3)))
        self.assertEqual(custom_range_from_query("2099-01-01", "2099-01-01"), (date(2099, 1, 1), date(2099, 1, 1)))
        for start, end in [
            (None, "2099-01-01"), ("", "2099-01-01"),
            ("2099-01-01", None), ("2099-02-30", "2099-03-01"),
            ("20990101", "2099-01-02"), ("2099-01-03", "2099-01-01"),
        ]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                custom_range_from_query(start, end)

    def test_custom_range_includes_both_dates_and_compares_previous_window(self):
        selected = custom_range_from_query("2099-01-01", "2099-01-02")
        _, (start, end) = period_filter(selected)
        _, (previous_start, previous_end) = previous_period_filter(selected, datetime.now().astimezone())
        self.assertEqual(previous_end, start)
        self.assertEqual(previous_start, utc_value(datetime.combine(date(2098, 12, 30), time.min).astimezone()))
        second_day = utc_value(datetime.combine(date(2099, 1, 2), time.min).astimezone())

        with sqlite3.connect(self.db_path) as connection:
            connection.execute("UPDATE assistant_usage_events SET created_at = ? WHERE session_id = 's1'", (start,))
            connection.executemany(
                """
                INSERT INTO assistant_usage_events VALUES
                    ('s1', 0, 'test-model', 1, 1, 0, 0, 0, 1000000000, 1, 1, 1,
                     'medium', 'stop', 0, NULL, ?)
                """,
                [(previous_start,), (second_day,), (end,)],
            )
        metrics = query_metrics(self.db_path, selected)
        self.assertEqual(metrics["summary"]["requests"], 2)
        self.assertEqual(metrics["previous_summary"]["requests"], 1)
        self.assertEqual(metrics["range_days"], 2)
        self.assertEqual([day["day"] for day in metrics["daily"]], ["2099-01-01", "2099-01-02"])

    def test_custom_range_fills_days_without_usage(self):
        metrics = query_metrics(self.db_path, custom_range_from_query("2099-01-03", "2099-01-04"))
        self.assertEqual(metrics["summary"]["requests"], 0)
        self.assertEqual([day["day"] for day in metrics["daily"]], ["2099-01-03", "2099-01-04"])
        self.assertTrue(all(day["requests"] == 0 for day in metrics["daily"]))

    def test_month_period_uses_utc_billing_boundaries(self):
        local_end = datetime(2026, 9, 1, 14, 10, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        _, params = period_filter("month", local_end)
        self.assertEqual(params, ("2026-09-01T00:00:00.000Z", "2026-09-01T08:40:00.000Z"))

        _, previous_params = previous_period_filter("month", local_end)
        self.assertEqual(previous_params, ("2026-08-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z"))

    def test_sessions_filter_to_more_than_20_aiu_only_when_needed(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("UPDATE assistant_usage_events SET total_nano_aiu = 20000000000 WHERE session_id = 's1'")
            connection.execute("INSERT INTO sessions VALUES ('s2', '/tmp/other', 'other/repo', 'High usage session')")
            connection.execute(
                """
                INSERT INTO assistant_usage_events VALUES
                    ('s2', 0, 'test-model', 1, 1, 0, 0, 0, 20000000001, 1, 1, 1,
                     'medium', 'stop', 0, NULL, '2099-01-02T00:00:00Z')
                """
            )

        sessions = query_metrics(self.db_path, 0)["sessions"]
        self.assertEqual([session["session_id"] for session in sessions], ["s2", "s1"])

        with sqlite3.connect(self.db_path) as connection:
            connection.executemany(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                [(f"s{index}", "/tmp/other", "other/repo", f"Low usage session {index}") for index in range(3, 17)],
            )
            connection.executemany(
                """
                INSERT INTO assistant_usage_events
                VALUES (?, 0, 'test-model', 1, 1, 0, 0, 0, 1000000000, 1, 1, 1,
                        'medium', 'stop', 0, NULL, '2099-01-03T00:00:00Z')
                """,
                [(f"s{index}",) for index in range(3, 17)],
            )

        sessions = query_metrics(self.db_path, 0)["sessions"]
        self.assertEqual([session["session_id"] for session in sessions], ["s2"])

    def test_intent_classifier_covers_common_work_patterns(self):
        self.assertEqual(classify_intent("make the buttons purple in dark mode"), "ui_design")
        self.assertEqual(classify_intent("create a PR for this"), "coding")
        self.assertEqual(classify_intent("give me complete WSL setup steps"), "setup_configuration")
        self.assertEqual(classify_intent("explain how the request flows"), "explanation")
        self.assertEqual(classify_intent("try now"), "feedback")


if __name__ == "__main__":
    unittest.main()

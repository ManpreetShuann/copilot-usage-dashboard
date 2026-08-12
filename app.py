#!/usr/bin/env python3
"""Small read-only dashboard for local Copilot usage telemetry."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DEFAULT_DB = Path.home() / ".copilot" / "session-store.db"
ALLOWED_RANGES = {7, 30, 90, 0}
RangeValue = int | str
DAILY_TOTAL_FIELDS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_nano_aiu",
)


def get_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"Copilot database not found: {db_path}")

    connection = sqlite3.connect(
        f"file:{db_path.resolve()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def range_days_from_query(value: str | None) -> RangeValue:
    if value in (None, ""):
        return 30
    if value == "all":
        return 0
    if value == "month":
        return "month"
    try:
        days = int(value)
    except ValueError as error:
        raise ValueError("range must be 7, 30, 90, month, or all") from error
    if days not in ALLOWED_RANGES:
        raise ValueError("range must be 7, 30, 90, month, or all")
    return days


def since_value(days: int) -> str | None:
    if days == 0:
        return None
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return since.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def period_filter(range_value: RangeValue, end: datetime | None = None) -> tuple[str, tuple[str, ...]]:
    if range_value == 0:
        return "", ()
    period_end = end or datetime.now(timezone.utc)
    period_start = (
        period_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if range_value == "month"
        else period_end - timedelta(days=range_value)
    )
    return (
        "WHERE created_at >= ? AND created_at < ?",
        (
            period_start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            period_end.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        ),
    )


def previous_period_filter(
    range_value: RangeValue,
    end: datetime,
) -> tuple[str, tuple[str, ...]]:
    if range_value == "month":
        current_start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_end = current_start
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        return (
            "WHERE created_at >= ? AND created_at < ?",
            (
                previous_start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                previous_end.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            ),
        )
    return period_filter(range_value, end - timedelta(days=range_value)) if range_value else ("", ())


INTENT_RULES = (
    ("ui_design", re.compile(r"\b(button|color|colour|theme|layout|dark mode|light mode|style|styling|page|panel|card|design|hover)\b")),
    ("setup_configuration", re.compile(r"\b(setup|set up|install|permission|permissions|access|environment|configuration|configure|macos|wsl|sandbox)\b")),
    ("explanation", re.compile(r"\b(explain|explanation|flow|workflow|how does|how do|what would|what all|why does)\b")),
    ("debugging", re.compile(r"\b(error|bug|broken|debug|debugging|fail(?:ed|ing)?|traceback|exception|issue|warning)\b")),
    ("coding", re.compile(r"\b(code|coding|implement|add|create|edit|change|update|make|use|keep|fix|refactor|function|class|api|endpoint|test|build|deploy|script|clean|pr|pull request|branch|jira|ticket|story points?|label|commit|push|review|merge)\b")),
    ("planning", re.compile(r"\b(plan|planning|design|architecture|approach|roadmap|structure)\b")),
    ("documentation", re.compile(r"\b(document|documentation|docs|readme|changelog)\b")),
)


def classify_intent(message: str | None) -> str:
    text = (message or "").strip().lower()
    for intent, pattern in INTENT_RULES:
        if pattern.search(text):
            return intent
    if "?" in text or re.match(r"^(can|could|how|what|why|when|where|which|is|are|do|does|should)\b", text):
        return "questions"
    if re.match(r"^(ok|okay|yeah|yes|nope|hmm|try now|use that|lets use that|that's good|that is good)\b", text):
        return "feedback"
    return "other"


def intent_breakdown(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        if (row["user_message"] or "").lstrip().lower().startswith("<skill-context"):
            continue
        intent = classify_intent(row["user_message"])
        counts[intent] = counts.get(intent, 0) + 1
    total = sum(counts.values())
    return [
        {
            "intent": intent,
            "turns": count,
            "percentage": round(count * 100.0 / total, 1) if total else 0,
        }
        for intent, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def summary_query(
    connection: sqlite3.Connection,
    where: str,
    params: tuple[str, ...],
) -> sqlite3.Row:
    return connection.execute(
        f"""
        SELECT
            COUNT(*) AS requests,
            COUNT(DISTINCT session_id) AS sessions,
            COUNT(DISTINCT substr(created_at, 1, 10)) AS active_days,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
            COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(total_nano_aiu), 0) AS total_nano_aiu,
            COALESCE(ROUND(AVG(duration_ms)), 0) AS avg_duration_ms,
            COALESCE(ROUND(AVG(time_to_first_token_ms)), 0) AS avg_ttft_ms,
            COALESCE(ROUND(AVG(inter_token_latency_ms)), 0) AS avg_inter_token_ms,
            COALESCE(ROUND(
                SUM(output_tokens) * 1000.0 / NULLIF(SUM(duration_ms), 0),
                1
            ), 0) AS output_generation_speed_tps,
            COALESCE(SUM(CASE WHEN finish_reason = 'stop' THEN 1 ELSE 0 END), 0) AS stop_requests,
            COALESCE(SUM(CASE WHEN finish_reason = 'tool_calls' THEN 1 ELSE 0 END), 0) AS tool_call_requests,
            COALESCE(SUM(CASE WHEN content_filter_triggered = 1 THEN 1 ELSE 0 END), 0) AS filtered_requests
        FROM assistant_usage_events
        {where}
        """,
        params,
    ).fetchone()


def fill_daily_gaps(rows: list[sqlite3.Row], range_value: RangeValue, now: datetime) -> list[dict[str, Any]]:
    if not rows:
        return []

    row_by_day = {row["day"]: dict(row) for row in rows}
    if range_value == "month":
        first_day = now.replace(day=1).date()
        last_day = now.date()
    elif range_value:
        first_day = (now - timedelta(days=range_value)).date()
        last_day = now.date()
    else:
        dates = [date.fromisoformat(day) for day in row_by_day]
        first_day = min(dates)
        last_day = max(dates)

    filled: list[dict[str, Any]] = []
    current = first_day
    while current <= last_day:
        day = current.isoformat()
        filled.append(row_by_day.get(day, {
            "day": day,
            **{field: 0 for field in DAILY_TOTAL_FIELDS},
        }))
        current += timedelta(days=1)
    return filled


def query_metrics(db_path: Path, days: RangeValue) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    where, params = period_filter(days, now)
    previous_where, previous_params = previous_period_filter(days, now) if days else ("", ())

    with get_connection(db_path) as connection:
        summary = summary_query(connection, where, params)
        previous_summary = summary_query(connection, previous_where, previous_params) if days else None

        models = connection.execute(
            f"""
            SELECT
                model,
                COUNT(*) AS requests,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                COALESCE(SUM(total_nano_aiu), 0) AS total_nano_aiu,
                COALESCE(ROUND(AVG(duration_ms)), 0) AS avg_duration_ms,
                COALESCE(ROUND(AVG(time_to_first_token_ms)), 0) AS avg_ttft_ms,
                COALESCE(ROUND(AVG(inter_token_latency_ms)), 0) AS avg_inter_token_ms,
                COALESCE(ROUND(
                    SUM(output_tokens) * 1000.0 / NULLIF(SUM(duration_ms), 0),
                    1
                ), 0) AS output_generation_speed_tps
            FROM assistant_usage_events
            {where}
            GROUP BY model
            ORDER BY total_nano_aiu DESC
            """,
            params,
        ).fetchall()

        daily = connection.execute(
            f"""
            SELECT
                substr(created_at, 1, 10) AS day,
                COUNT(*) AS requests,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                COALESCE(SUM(total_nano_aiu), 0) AS total_nano_aiu
            FROM assistant_usage_events
            {where}
            GROUP BY day
            ORDER BY day
            """,
            params,
        ).fetchall()

        hourly = connection.execute(
            f"""
            SELECT
                CAST(substr(created_at, 12, 2) AS INTEGER) AS hour,
                COUNT(*) AS requests,
                COALESCE(SUM(total_nano_aiu), 0) AS total_nano_aiu
            FROM assistant_usage_events
            {where}
            GROUP BY hour
            ORDER BY hour
            """,
            params,
        ).fetchall()

        reliability = connection.execute(
            f"""
            SELECT
                COALESCE(finish_reason, 'unknown') AS finish_reason,
                COUNT(*) AS requests,
                COALESCE(SUM(CASE WHEN content_filter_triggered = 1 THEN 1 ELSE 0 END), 0) AS filtered_requests
            FROM assistant_usage_events
            {where}
            GROUP BY finish_reason
            ORDER BY requests DESC
            """,
            params,
        ).fetchall()

        reasoning_efforts = connection.execute(
            f"""
            SELECT
                COALESCE(NULLIF(reasoning_effort, ''), 'unspecified') AS reasoning_effort,
                COUNT(*) AS requests,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                COALESCE(SUM(total_nano_aiu), 0) AS total_nano_aiu,
                COALESCE(ROUND(AVG(duration_ms)), 0) AS avg_duration_ms
            FROM assistant_usage_events
            {where}
            GROUP BY reasoning_effort
            ORDER BY total_nano_aiu DESC
            """,
            params,
        ).fetchall()

        locations = connection.execute(
            f"""
            SELECT
                COALESCE(NULLIF(s.cwd, ''), NULLIF(s.repository, ''), 'Unknown') AS path,
                COALESCE(NULLIF(s.repository, ''), 'Local session') AS repository,
                COUNT(*) AS requests,
                COUNT(DISTINCT u.session_id) AS sessions,
                COALESCE(SUM(u.input_tokens), 0) AS input_tokens,
                COALESCE(SUM(u.output_tokens), 0) AS output_tokens,
                COALESCE(SUM(u.total_nano_aiu), 0) AS total_nano_aiu
            FROM assistant_usage_events AS u
            JOIN sessions AS s ON s.id = u.session_id
            {where.replace("created_at", "u.created_at")}
            GROUP BY path, repository
            ORDER BY total_nano_aiu DESC
            LIMIT 20
            """,
            params,
        ).fetchall()

        location_models = connection.execute(
            f"""
            SELECT
                COALESCE(NULLIF(s.cwd, ''), NULLIF(s.repository, ''), 'Unknown') AS path,
                u.model AS model,
                COUNT(*) AS requests,
                COALESCE(SUM(u.total_nano_aiu), 0) AS total_nano_aiu
            FROM assistant_usage_events AS u
            JOIN sessions AS s ON s.id = u.session_id
            {where.replace("created_at", "u.created_at")}
            GROUP BY path, model
            ORDER BY total_nano_aiu DESC
            LIMIT 100
            """,
            params,
        ).fetchall()

        sessions = connection.execute(
            f"""
            SELECT
                u.session_id,
                COALESCE(NULLIF(s.summary, ''), 'Untitled session') AS summary,
                COALESCE(NULLIF(s.cwd, ''), NULLIF(s.repository, ''), 'Unknown') AS path,
                COALESCE(NULLIF(s.repository, ''), 'Local session') AS repository,
                COUNT(*) AS requests,
                COUNT(DISTINCT substr(u.created_at, 1, 10)) AS active_days,
                GROUP_CONCAT(DISTINCT u.model) AS models,
                COALESCE(SUM(u.input_tokens), 0) AS input_tokens,
                COALESCE(SUM(u.output_tokens), 0) AS output_tokens,
                COALESCE(SUM(u.reasoning_tokens), 0) AS reasoning_tokens,
                COALESCE(SUM(u.cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM(u.cache_write_tokens), 0) AS cache_write_tokens,
                COALESCE(SUM(u.input_tokens + u.output_tokens + u.reasoning_tokens), 0) AS tokens,
                COALESCE(SUM(CASE WHEN u.finish_reason = 'tool_calls' THEN 1 ELSE 0 END), 0) AS tool_calls,
                COALESCE(SUM(u.total_nano_aiu), 0) AS total_nano_aiu,
                COALESCE(ROUND(AVG(u.duration_ms)), 0) AS avg_duration_ms,
                COALESCE(ROUND(AVG(u.time_to_first_token_ms)), 0) AS avg_ttft_ms,
                COALESCE(ROUND(
                    SUM(u.output_tokens) * 1000.0 / NULLIF(SUM(u.duration_ms), 0),
                    1
                ), 0) AS output_generation_speed_tps,
                MIN(u.created_at) AS first_activity,
                MAX(u.created_at) AS last_activity
            FROM assistant_usage_events AS u
            JOIN sessions AS s ON s.id = u.session_id
            {where.replace("created_at", "u.created_at")}
            GROUP BY u.session_id, summary, path
            ORDER BY total_nano_aiu DESC
            LIMIT 15
            """,
            params,
        ).fetchall()

        session_models = connection.execute(
            f"""
            SELECT
                u.session_id,
                u.model,
                COUNT(*) AS requests,
                COALESCE(SUM(u.input_tokens), 0) AS input_tokens,
                COALESCE(SUM(u.output_tokens), 0) AS output_tokens,
                COALESCE(SUM(u.reasoning_tokens), 0) AS reasoning_tokens,
                COALESCE(SUM(u.cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM(u.cache_write_tokens), 0) AS cache_write_tokens,
                COALESCE(SUM(u.input_tokens + u.output_tokens + u.reasoning_tokens), 0) AS tokens,
                COALESCE(SUM(CASE WHEN u.finish_reason = 'tool_calls' THEN 1 ELSE 0 END), 0) AS tool_calls,
                COALESCE(SUM(u.total_nano_aiu), 0) AS total_nano_aiu,
                COALESCE(ROUND(AVG(u.duration_ms)), 0) AS avg_duration_ms,
                COALESCE(ROUND(AVG(u.time_to_first_token_ms)), 0) AS avg_ttft_ms,
                COALESCE(ROUND(
                    SUM(u.output_tokens) * 1000.0 / NULLIF(SUM(u.duration_ms), 0),
                    1
                ), 0) AS output_generation_speed_tps
            FROM assistant_usage_events AS u
            {where.replace("created_at", "u.created_at")}
            GROUP BY u.session_id, u.model
            ORDER BY u.session_id, total_nano_aiu DESC
            """,
            params,
        ).fetchall()

        intent_rows = connection.execute(
            f"""
            SELECT t.user_message
            FROM (
                SELECT DISTINCT u.session_id, u.turn_index
                FROM assistant_usage_events AS u
                {where.replace("created_at", "u.created_at")}
            ) AS used_turns
            JOIN turns AS t
              ON t.session_id = used_turns.session_id
             AND t.turn_index = used_turns.turn_index
            WHERE t.user_message IS NOT NULL
            """,
            params,
        ).fetchall()

    def row_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    session_model_rows: dict[str, list[dict[str, Any]]] = {}
    for row in session_models:
        session_model_rows.setdefault(row["session_id"], []).append(row_dict(row))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "range_days": days,
        "summary": row_dict(summary),
        "previous_summary": row_dict(previous_summary) if previous_summary else None,
        "models": [row_dict(row) for row in models],
        "daily": fill_daily_gaps(daily, days, now),
        "hourly": [row_dict(row) for row in hourly],
        "reliability": [row_dict(row) for row in reliability],
        "reasoning_efforts": [row_dict(row) for row in reasoning_efforts],
        "intent_breakdown": intent_breakdown(intent_rows),
        "sessions": [
            {
                **row_dict(row),
                "model_metrics": session_model_rows.get(row["session_id"], []),
            }
            for row in sessions
        ],
        "locations": [row_dict(row) for row in locations],
        "location_models": [row_dict(row) for row in location_models],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/metrics":
            self.send_metrics(parse_qs(parsed.query))
            return
        self.send_static(parsed.path)

    def send_metrics(self, query: dict[str, list[str]]) -> None:
        value = query.get("range", [None])[0]
        try:
            metrics = query_metrics(self.db_path, range_days_from_query(value))
        except (FileNotFoundError, sqlite3.Error, ValueError, OSError) as error:
            self.send_json({"error": str(error)}, status=500)
            return
        self.send_json(metrics)

    def send_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return

        content_type = {
            ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(candidate.suffix, "application/octet-stream")
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("COPILOT_DB", DEFAULT_DB)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()

    DashboardHandler.db_path = args.db.expanduser()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"Database:  {DashboardHandler.db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

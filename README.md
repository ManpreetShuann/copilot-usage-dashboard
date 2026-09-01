# Copilot Usage Dashboard

A small, local, read-only dashboard for usage telemetry stored by Copilot CLI.

The interface uses the Tokyo Night color palette.

## Requirements

- Python 3.10 or newer
- `make` on macOS/Linux
- Copilot CLI with `~/.copilot/session-store.db` containing `assistant_usage_events`

The project uses only Python's standard library; no package installation is required.

## Run

```bash
cd ~/copilot-usage-dashboard
make up
```

Open <http://127.0.0.1:8765>.

Stop it with:

```bash
make down
```

Use `make status` to check whether it is running and `make restart` to restart it.

The default database is `~/.copilot/session-store.db`. The default timeframe is the current calendar month. Available timeframes are today, last 7, 30, or 90 days, current calendar month, and all available data. Use another database with:

```bash
python3 app.py --db /path/to/session-store.db --port 8766
```

The server only runs read-only SQLite queries and does not expose transcript contents.

## Metrics

The dashboard reports requests, sessions, input/output/reasoning tokens, cache reads and writes, response latency, output generation speed, and `total_nano_aiu`. Output generation speed uses the same weighted calculation as the statusline: total output tokens multiplied by 1,000 divided by total response duration. It is organized into Overview, Models, Projects, Performance, and Sessions views. Features include model usage by credits (AIU) and token-composition donuts, reasoning-effort breakdown, selectable daily trend charts, period comparison, cache efficiency, AIU projections, hourly activity, performance and finish-reason metrics, project drill-down, session insights, and CSV export. The token-composition legend includes exact AIU calculated from `token_details_json` for input, output, cache-read, and cache-write token types; reasoning tokens are shown as non-billed because the telemetry does not assign them a separate AIU charge. The current and previous monthly billing periods use UTC boundaries to match the monthly token reset; daily charts, hourly activity, and other metrics remain grouped by local time. Daily charts include zero-use days inside the selected window. Nano AIU values are divided by 1,000,000,000 and displayed as AIU with `K`/`M` scaling.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

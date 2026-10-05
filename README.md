# Group 15 - SweaterCo Manager Co-pilot

Streamlit demo using the three Track 1 teaching CSV files.

Local startup (Python 3.12 recommended):

```sh
uv sync --frozen
uv run streamlit run app.py --server.port 8503
```

For local background schedules, run `uv run python worker.py` in a second terminal.

## Community Cloud

Deploy the repository branch with `app.py` as the entrypoint. Select Python 3.12. Use `uv.lock` and `pyproject.toml` for dependencies. Configure `DEEPSEEK_API_KEY` and `DEEPSEEK_NETWORK_ENABLED = true` in cloud Secrets. Without these settings, local data pages work but online Q&A is disabled.

This upload does not configure a background worker on Community Cloud. Scheduled briefings and watches require a separately running worker with access to the same database. SQLite records are shared by all visitors to the same app instance and must not be treated as durable cloud storage. The fresh cloud database starts its own simulation clock at 2026-04-01; it does not import local records.

No credentials, local database, virtual environment, or presentation assets are included.

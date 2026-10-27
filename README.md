# SweaterCo — Track 1 Factory Manager Co-pilot

A local Streamlit application for reviewing at-risk orders, detecting production anomalies, estimating feasibility, generating morning briefings, and preparing notes, drafts, and reminders with human confirmation. A separate background worker handles scheduled monitoring.

**Q&A and briefing summaries use OpenAI GPT-6.1 Sol.** Network access must be explicitly enabled in the configuration. Earlier setup checks confirmed key authentication and model availability, but a generation request returned `credit_balance_exhausted`. This is a historical setup result, not a statement about the current account balance. Earlier DeepSeek smoke tests and the 33-case offline report are legacy validation records and must not be presented as the current model's Q&A accuracy.

## Getting Started

Requires Python 3.11+ and uv. Run the following commands from the project root:

```powershell
uv sync
uv run streamlit run app.py --server.port 8503
```

Open http://localhost:8503. Port 8502 is reserved for the original application. Start the background worker in a separate terminal:

```powershell
uv run python worker.py
```

The application and worker share `runtime/factory.sqlite3`. Closing the browser does not stop the worker; press `Ctrl+C` in its terminal to stop the process. Checks do not run while the computer is asleep or shut down, or while the worker is stopped. Due checks run after the worker restarts. The application does not automatically register an operating-system startup task. The UI displays the worker's heartbeat.

## Features and Usage

- **Risk overview:** Review overdue and at-risk orders using the existing filters and the 7-day / 3-working-day rules.
- **Manager assistant:** In offline mode, look up the latest source records by order ID. With network access enabled, GPT-6.1 Sol answers questions through multiple rounds of tool calls. CSV data is read afresh for each round, and answers provide a concise conclusion with expandable supporting evidence.
- **Production and anomalies:** Choose a baseline based on working days in the preceding 28 days, the previous complete week, or the same weekday over the preceding four weeks. Compare hypothetical daily output against these baselines. Tools expose samples, missing dates, means, the ±20% normal band, conclusions for each baseline, and source rows. Thresholds and minimum sample sizes are explicit heuristic rules; insufficient data produces no conclusion. Recent maximum and minimum values are also calculated in Python.
- **Feasibility estimates:** Enter a quantity, product category, and explicit due date. Compare internal backlog with subcontractor eligibility, queues, capacity, transport, and risk. Estimates do not allocate orders, reserve capacity, or guarantee delivery dates.
- **Morning briefings:** Generate a preview without saving it. Preview and confirm a daily schedule before activating it; the worker saves one briefing per simulated date. Offline mode uses a clearly labelled deterministic summary.
- **Actions and monitoring:** Preview an action, then select **Confirm** to proceed. **Reject** performs no action. Notes and follow-up message drafts are stored locally only. When an order watch is due, it compares the production stage and last activity date; stage watches check the latest complete working day. Each watch generates at most one alert, shown in the application's inbox without external push notifications.

The simulated clock starts at **2026-04-01** on first use and normally advances by one day for each real calendar day. A configured fixed reference date overrides this advancing clock. Schedule times use Asia/Shanghai. The sidebar displays both clocks. CSV files do not automatically gain new records: missing output for new dates is treated as unknown, not zero. Evaluation uses the fixed reference date 2026-04-01.

## OpenAI Configuration

The model is `gpt-6.1-sol`, using `https://api.openai.com/v1/responses`. Tool calls use the Responses API with `reasoning.effort=low`. Requests set `store=false`; returned encrypted reasoning items are retained during tool interactions to continue the same execution sequence. The eight tools retain their parameter definitions, Python calculations, and human-confirmation requirements. Model configuration and communication are implemented in `openai_client.py`.

The API key is read from the `OPENAI_API_KEY` environment variable or the Git-ignored `.streamlit/secrets.toml` file. A blank template is available at `.streamlit/secrets.example.toml`. OpenAI requests are permitted only when `OPENAI_NETWORK_ENABLED` is explicitly set to `true`; environment variables take precedence. Legacy DeepSeek keys and network settings neither enable OpenAI nor supply credentials for OpenAI requests.

For Streamlit Community Cloud, configure the OpenAI key and network setting separately in the deployment's **Secrets**. Restart both the application and worker after changing the model configuration.

Requests have timeouts and a maximum of six tool-call rounds. API errors expose only a safe summary. The model has no tools for arbitrary SQL, code execution, CSV modification, or direct action execution; it can only propose actions for human confirmation.

## Validation

```powershell
uv run python -m unittest discover -s tests -v
uv run python evaluate.py
```

The repository's original `evaluation/cases.json` contains 33 development cases with verified reference answers: seven edge, ambiguous, or unanswerable cases, and eight feasibility or action cases. The legacy offline report records 27 passing tool assertions; the remaining six cases require evaluation of natural-language model responses and were not assessed in that offline run. **The reported 100% is an offline tool-assertion pass rate, not Q&A accuracy.**

Reference answers are generated by `evaluation/build_cases.py`, which reads the CSV files directly and calculates results independently using the Python standard library. It does not import the application's tools. Source-file hashes are stored in the evaluation set. Regenerate reference answers only after reviewing changes to the data or specification, never to conceal failures.

Run `uv run python evaluate.py --live` to record real model behaviour and compare it with tool-derived facts. Human semantic review, held-out cases, and analysis of actual failures are still needed; the legacy offline results alone do not establish end-to-end model accuracy.

## Documentation

- [Tool specification](docs/TOOL_SPEC.md): Tool inputs, outputs, purpose, non-goals, failure handling, and scope of effects.
- [Architecture](docs/ARCHITECTURE.md): Data flow, feature mapping, assumptions, and remaining deliverables.
- [Evaluation](docs/EVALUATION.md): Measurement definitions, results, failure analysis, and outstanding validation.

This is a local prototype for a single manager. It does not include production authentication, multi-tenancy, external message delivery, or mobile push notifications. Source CSV files remain unchanged. Runtime state, credentials, and temporary files are excluded from version control.

import json
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from agent import Copilot
from factory import DATA_DIR, Factory, advance_workdays
from scheduler import create_briefing, tick
from state import Store, ZONE, propose_action


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "test.db")
        self.factory = Factory()

    def test_query_ambiguity_and_trace(self):
        result = self.factory.query_orders(customer="TrendCart")
        self.assertTrue(result["facts"]["requires_order_selection_for_singular_question"])
        self.assertGreater(result["facts"]["count"], 1)
        trace = self.factory.trace_order("ORD-002")
        self.assertEqual(trace["facts"]["orders"][0]["risk"], "Overdue")
        self.assertEqual(trace["sources"][0]["rows"][0]["order_id"], "ORD-002")
        self.assertEqual(len(trace["sources"][0]["sha256"]), 64)
        self.assertEqual(self.factory.query_orders(order_id="ORD-999")["facts"]["count"], 0)

    def test_fixed_reference_date_survives_restart_and_wall_clock_changes(self):
        self.store.set_setting("fixed_reference_date", "2026-04-01")
        reopened = Store(self.path / "test.db")
        for now in [datetime(2026, 10, 21, 10, tzinfo=ZONE), datetime(2026, 10, 22, 10, tzinfo=ZONE)]:
            self.assertEqual(reopened.today(now), date(2026, 4, 1))
            self.assertEqual(reopened.business_now(now).date(), date(2026, 4, 1))

    def test_working_day_baseline_and_missing_data(self):
        result = self.factory.judge_stage("ASSEMBLY", "2026-03-31")["facts"]
        self.assertEqual(result["sample_size"], 24)
        self.assertEqual(self.factory.judge_stage("PACKING", "2026-03-29")["facts"]["judgement"], "closed")
        self.assertEqual(self.factory.judge_stage("PACKING", "2026-04-02")["facts"]["judgement"], "unknown")
        missing = self.factory.production_summary("2026-04-02", "2026-04-02", "PACKING")["facts"]["stages"][0]
        self.assertEqual(missing["missing_dates"], ["2026-04-02"])
        self.assertIsNone(missing["mean_workday_output"])
        self.assertEqual(advance_workdays(date(2026, 4, 4), 1), date(2026, 4, 6))

    def test_auditable_daily_judgement_and_recent_range(self):
        facts = self.factory.judge_stage("ASSEMBLY", "2026-04-01", output=800)["facts"]
        self.assertEqual(facts["baseline_mean"], 702.38)
        self.assertEqual(facts["change_percent"], 13.9)
        self.assertEqual((facts["normal_lower"], facts["normal_upper"]), (561.9, 842.85))
        self.assertEqual(facts["judgement"], "normal")
        self.assertTrue(facts["hypothetical_output"])
        self.assertEqual(facts["recent_7_days"], {"start_date":"2026-03-25","end_date":"2026-03-31","workday_count":6,"mean_output":425.5,"min_output":394,"max_output":464})
        self.assertEqual(facts["policy_version"], "stage-output-v2")

    def test_calendar_week_and_same_weekday_use_exact_dates(self):
        week = self.factory.judge_stage("ASSEMBLY", "2026-04-01", output=800, baseline_method="previous_week")["facts"]
        self.assertEqual(week["baseline_dates"], [f"2026-03-{day}" for day in range(23,29)])
        self.assertEqual(week["sample_size"], 6)
        self.assertEqual(week["judgement"], "high")
        self.assertTrue(week["baseline_disagreement"])
        weekday = self.factory.judge_stage("ASSEMBLY", "2026-04-01", output=800, baseline_method="same_weekday")["facts"]
        self.assertEqual(weekday["baseline_dates"], ["2026-03-04","2026-03-11","2026-03-18","2026-03-25"])
        self.assertEqual(weekday["sample_size"], 4)
        self.assertNotIn("2026-04-01", weekday["baseline_dates"])

    def test_judgement_insufficient_history_and_invalid_inputs(self):
        facts = self.factory.judge_stage("ASSEMBLY", "2026-01-02", output=800)["facts"]
        self.assertEqual(facts["judgement"], "unknown")
        self.assertEqual(facts["reason"], "insufficient_samples")
        self.assertTrue(facts["missing_dates"])
        for value in [True, float('nan'), float('inf'), -1]:
            with self.assertRaises(ValueError):
                self.factory.judge_stage("ASSEMBLY", "2026-04-01", output=value)
        with self.assertRaises(ValueError):
            self.factory.judge_stage("ASSEMBLY", "2026-04-01", baseline_method="invented")

    def test_judgement_boundaries_and_zero_baseline(self):
        data = self.path / "constant_data"
        data.mkdir()
        dates = [date(2026,4,1)-timedelta(days=i) for i in range(1,29)]
        path = data / 'production_log.csv'
        path.write_text('date,stage,pieces_completed\n'+''.join(f'{d},ASSEMBLY,{0 if d.weekday()==6 else 100}\n' for d in dates))
        factory = Factory(data_dir=data)
        for output, expected in [(79,'low'),(80,'normal'),(120,'normal'),(121,'high')]:
            self.assertEqual(factory.judge_stage('ASSEMBLY','2026-04-01',output=output)['facts']['judgement'],expected)
        path.write_text(path.read_text().replace(',100\n', ',0\n'))
        facts = factory.judge_stage('ASSEMBLY','2026-04-01',output=800)['facts']
        self.assertEqual(facts['reason'], 'zero_baseline')
        self.assertEqual(facts['judgement'], 'unknown')

    def test_feasibility_eligibility_and_constraints(self):
        result = self.factory.estimate_feasibility(800, "TOPS", "2026-04-25")
        candidates = {c["workshop_id"]: c for c in result["facts"]["workshops"]}
        self.assertFalse(candidates["W7"]["eligible"])
        self.assertFalse(candidates["W8"]["eligible"])
        self.assertFalse(candidates["W4"]["eligible"])
        self.assertIn("exceeds trial batch cap", candidates["W8"]["exclusion_reasons"])
        self.assertEqual(candidates["W1"]["estimated_cost_units"], 1200)
        self.assertTrue(result["facts"]["assumptions"])
        for bad in [(0, "TOPS", "2026-04-25"), (True, "TOPS", "2026-04-25"), (800, "SHOES", "2026-04-25"), (800, "TOPS", "2026-03-01")]:
            with self.assertRaises(ValueError):
                self.factory.estimate_feasibility(*bad)

    def test_confirmation_idempotency_and_persistence(self):
        proposal = propose_action(self.factory, self.store, "add_note", order_id="ORD-002", content="Call planner")["facts"]["proposal"]
        self.assertEqual(self.store.activity()["actions"], [])
        with self.assertRaises(ValueError):
            self.store.commit(proposal)
        self.assertTrue(self.store.commit(proposal, confirmed=True))
        self.assertFalse(self.store.commit(proposal, confirmed=True))
        self.assertEqual(len(Store(self.path / "test.db").activity()["actions"]), 1)

    def test_watch_fires_once_without_browser_and_survives_restart(self):
        now = datetime.now(ZONE).replace(hour=10, minute=0, second=0, microsecond=0)
        proposal = propose_action(self.factory, self.store, "watch_order", order_id="ORD-002", deadline="2026-04-02T09:00:00")["facts"]["proposal"]
        self.store.commit(proposal, confirmed=True)
        offline_briefing = lambda factory: {"summary": "fixture"}
        tick(self.store, now+timedelta(days=1), offline_briefing)
        tick(Store(self.path / "test.db"), now+timedelta(days=1, minutes=1), offline_briefing)
        self.assertEqual(len(self.store.activity()["alerts"]), 1)
        self.assertEqual(self.store.activity()["watches"][0]["status"], "fired")

    def test_moved_order_resolves_watch_and_fresh_csv_is_read(self):
        data = self.path / "data"
        shutil.copytree(DATA_DIR, data)
        factory = Factory(data_dir=data)
        proposal = propose_action(factory, self.store, "watch_order", order_id="ORD-002", deadline="2026-04-02T09:00:00")["facts"]["proposal"]
        self.store.commit(proposal, confirmed=True)
        text = (data/"orders.csv").read_text()
        # Change only the watched order's activity without changing the original course data.
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("ORD-002,"):
                lines[i] = line.replace("2026-03-23", "2026-04-01")
        (data/"orders.csv").write_text("\n".join(lines)+"\n")
        now = datetime.now(ZONE).replace(hour=10) + timedelta(days=1)
        tick(self.store, now, data_dir=data)
        self.assertEqual(self.store.activity()["alerts"], [])
        self.assertEqual(self.store.activity()["watches"][0]["status"], "resolved")

    def test_schedule_once_daily_after_confirm(self):
        proposal = propose_action(self.factory, self.store, "briefing_schedule", schedule_time="07:00")["facts"]["proposal"]
        self.store.commit(proposal, confirmed=True)
        now = datetime.now(ZONE).replace(hour=8, minute=0)
        with patch("scheduler.create_briefing") as unused:
            calls = []
            def builder(factory):
                calls.append(factory.today)
                return {"summary": "test"}
            tick(self.store, now, builder)
            tick(self.store, now+timedelta(minutes=1), builder)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(self.store.briefing("2026-04-01"))

    def test_agent_retrieval_and_numeric_guard(self):
        messages_seen = []
        responses = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "query_orders", "arguments": '{"status":"IN_PROGRESS"}'}}]},
            {"role": "assistant", "content": json.dumps({"kind": "answer", "summary": "999 orders", "evidence_ids": ["E1"]})},
            {"role": "assistant", "content": json.dumps({"kind": "answer", "summary": "34 orders", "evidence_ids": ["E1"]})},
        ]
        def client(messages, tools):
            messages_seen.append(list(messages))
            return responses.pop(0), {}
        result = Copilot(self.factory, self.store, client).ask("How many unfinished orders?")
        self.assertEqual(result["summary"], "34 orders")
        self.assertEqual(len(messages_seen), 3)
        self.assertEqual(result["evidence"]["E1"]["facts"]["count"], 34)
        with self.assertRaises(ValueError):
            Copilot(self.factory, self.store).execute("exec", {"code": "bad"})

    def test_offline_briefing_is_explicit(self):
        from openai_client import ModelError
        def unavailable(*args):
            raise ModelError("offline")
        result = create_briefing(self.factory, client=unavailable)
        self.assertEqual(result["generation"], "deterministic")
        self.assertEqual(result["generation_error"], "offline")

    def test_network_disabled_before_request_or_key_access(self):
        from openai_client import ModelError, complete
        with patch.dict(os.environ, {"OPENAI_NETWORK_ENABLED": "false"}), patch("openai_client.urllib.request.urlopen") as http, patch("openai_client.api_key") as key:
            with self.assertRaises(ModelError):
                complete([{"role": "user", "content": "private fixture"}])
            http.assert_not_called()
            key.assert_not_called()

    def test_persisted_network_consent_and_environment_override(self):
        from openai_client import network_enabled
        with patch.dict(os.environ, {}, clear=True), patch('openai_client.Path.exists', return_value=True), patch('openai_client.Path.read_text', return_value='OPENAI_NETWORK_ENABLED = true'):
            self.assertTrue(network_enabled())
            with patch.dict(os.environ, {'OPENAI_NETWORK_ENABLED': 'false'}):
                self.assertFalse(network_enabled())
        with patch.dict(os.environ, {}, clear=True), patch('openai_client.Path.exists', return_value=False):
            self.assertFalse(network_enabled())

    def test_rejected_proposal_never_saves(self):
        result = propose_action(self.factory, self.store, "save_draft", order_id="ORD-002", content="Fixture draft")
        self.assertFalse(result["facts"]["committed"])
        self.assertEqual(Store(self.path / "test.db").activity()["actions"], [])


class NewPageTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"FACTORY_DB": str(Path(self.temp.name)/"ui.db"), "OPENAI_NETWORK_ENABLED": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = AppTest.from_file(str(DATA_DIR.parents[1]/"app.py"), default_timeout=15).run()

    def navigate(self, page):
        self.app.radio[0].set_value(page).run()
        self.assertFalse(self.app.exception)

    def test_all_new_pages_render_without_network(self):
        with patch("openai_client.urllib.request.urlopen") as http:
            for page in ["Co-pilot", "Production & discovery", "Feasibility", "Briefing", "Actions & watches"]:
                self.navigate(page)
            http.assert_not_called()

    def test_quick_prompt_requires_send_before_model_call(self):
        question = "Which unfinished orders are overdue or at risk?"
        fixture = {"kind": "answer", "summary": "Fixture answer.", "details": "",
                   "model": "fixture", "elapsed_seconds": 0, "evidence_ids": ["E1"],
                   "evidence": {"E1": {"tool": "query_orders", "facts": {"count": 34}, "sources": []}},
                   "proposals": [], "trace": []}
        with patch("copilot_ui.network_enabled", return_value=True), patch("copilot_ui.api_key", return_value="test-only"), \
                patch("copilot_ui.Copilot.ask", return_value=fixture) as ask:
            self.navigate("Co-pilot")
            self.app.button(key="prompt_0").click().run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.app.chat_input[0].proto.value, question)
            ask.assert_not_called()
            self.assertEqual(Store().activity()["actions"], [])
            self.app.chat_input[0].set_value(question).run()
            self.assertFalse(self.app.exception)
            ask.assert_called_once_with(question, [])
            self.assertEqual(self.app.session_state["conversation"][0]["question"], question)

    def test_offline_chat_and_quick_prompts_stay_disabled(self):
        with patch("openai_client.urllib.request.urlopen") as http:
            self.navigate("Co-pilot")
            self.assertTrue(self.app.chat_input[0].disabled)
            self.assertTrue(all(self.app.button(key=f"prompt_{index}").disabled for index in range(4)))
            http.assert_not_called()

    def test_feasibility_form_and_offline_briefing(self):
        self.navigate("Feasibility")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Conservative internal finish date" in item.value for item in self.app.info))
        self.navigate("Briefing")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("offline summary" in item.value for item in self.app.warning))
        headings = [item.value for item in self.app.subheader]
        self.assertIn("Production performance and baseline sensitivity", headings)
        self.assertIn("Recommended decisions today", headings)
        self.assertIn("Data quality and interpretation limits", headings)

    def test_action_ui_requires_confirmation(self):
        self.navigate("Actions & watches")
        self.app.text_area[0].set_value("UI fixture note")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        store = Store()
        self.assertEqual(store.activity()["actions"], [])
        confirm = next(button for button in self.app.button if button.label == "Confirm")
        confirm.click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(store.activity()["actions"]), 1)

    def test_judgement_baseline_and_hypothetical_controls(self):
        self.navigate("Production & discovery")
        self.app.selectbox[0].set_value("ASSEMBLY")
        self.app.date_input[0].set_value(date(2026,4,1))
        self.app.selectbox[1].set_value("previous_week")
        self.app.checkbox[0].check().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value,"800")
        self.assertTrue(any("Different baselines" in item.value for item in self.app.warning))


if __name__ == "__main__":
    unittest.main()


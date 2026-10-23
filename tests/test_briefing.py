import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from briefing import build_briefing
from openai_client import ModelError
from factory import DATA_DIR, Factory
from scheduler import create_briefing


class BriefingTests(unittest.TestCase):
    def test_delivery_exposure_and_priorities(self):
        result = build_briefing(Factory())
        facts = result["facts"]["portfolio"]
        self.assertEqual(facts["unfinished_count"], 34)
        self.assertEqual(facts["unfinished_order_pieces"], 32850)
        self.assertEqual(facts["risk_counts"]["Overdue"], 8)
        self.assertEqual(facts["flagged_count"], 15)
        self.assertEqual(facts["flagged_percent"], 44.12)
        self.assertEqual(facts["stalled_count"], 2)
        self.assertEqual(facts["other_flagged_count"], 7)
        self.assertTrue(all(r["risk"] == "Overdue" for r in facts["priority_orders"]))
        self.assertEqual([r["due_date"] for r in facts["priority_orders"]],
                         sorted(r["due_date"] for r in facts["priority_orders"]))
        self.assertEqual(len(result["sections"]), 6)
        self.assertEqual(set(result["evidence"]), {f"E{i}" for i in range(1, 8)})
        customer = next(r for r in facts["customers"] if r["customer"] == "Bright Basics")
        self.assertEqual((customer["flagged_count"], customer["unfinished_count"], customer["flagged_percent"]), (2, 3, 66.67))

    def test_stage_comparisons_are_auditable(self):
        result = build_briefing(Factory())
        stage = next(r for r in result["facts"]["stage_analysis"] if r["stage"] == "ASSEMBLY")
        self.assertEqual(stage["output"], 455)
        self.assertEqual(stage["baseline_mean"], 712.04)
        self.assertEqual(stage["change_percent"], -36.1)
        self.assertEqual(stage["judgement"], "low")
        self.assertEqual(len(stage["comparisons"]), 3)
        self.assertIn("does not establish a bottleneck", result["sections"][1]["body"])
        self.assertIn("not executed actions", result["sections"][4]["body"])

    def test_missing_day_and_sunday_do_not_become_zero_output(self):
        missing = build_briefing(Factory(today=date(2026, 4, 3)))
        self.assertTrue(all(s["output"] is None and s["judgement"] == "unknown" for s in missing["facts"]["stage_analysis"]))
        self.assertIn("missing_target", missing["sections"][5]["body"])
        sunday = build_briefing(Factory(today=date(2026, 3, 30)))
        self.assertTrue(all(s["judgement"] == "closed" for s in sunday["facts"]["stage_analysis"]))
        self.assertNotIn("**Investigate", sunday["sections"][4]["body"])

    def test_no_unfinished_orders_has_no_division_or_priority_error(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            shutil.copytree(DATA_DIR, data)
            path = data / "orders.csv"
            path.write_text(path.read_text().replace("IN_PROGRESS", "COMPLETE"))
            result = build_briefing(Factory(data_dir=data))
        self.assertEqual(result["facts"]["portfolio"]["flagged_percent"], 0)
        self.assertEqual(result["facts"]["portfolio"]["customers"], [])
        self.assertIn("No unfinished orders", result["sections"][2]["body"])

    def test_offline_and_invalid_model_keep_full_local_report(self):
        def offline(*args):
            raise ModelError("Offline test")
        for client in [offline, lambda *args: ({"content": json.dumps({"summary": "There are 999999 orders."})}, {})]:
            result = create_briefing(Factory(), client=client)
            self.assertEqual(result["generation"], "deterministic")
            self.assertIn("generation_error", result)
            self.assertEqual(len(result["sections"]), 6)
            self.assertNotIn("999999", result["summary"])

    def test_model_overview_cannot_replace_detailed_evidence(self):
        seen = []
        def client(messages):
            seen.extend(messages)
            return {"content": json.dumps({"summary": "Review 8 overdue orders before making delivery commitments. [E3]"})}, {}
        result = create_briefing(Factory(), client=client)
        self.assertEqual(result["generation"], "gpt-6.1-sol")
        self.assertEqual(len(result["sections"]), 6)
        self.assertIn("100–160 words", seen[0]["content"])
        self.assertIn("portfolio", json.loads(seen[1]["content"]))


if __name__ == "__main__":
    unittest.main()


import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app import ORDERS_PATH, TODAY, assess_risk, evaluate_orders, load_orders, working_days_since


class RiskTests(unittest.TestCase):
    def test_due_date_boundaries(self):
        for due, expected in [(date(2026, 3, 31), "Overdue"), (TODAY, "At risk"),
                              (date(2026, 4, 8), "At risk"), (date(2026, 4, 9), "No flag")]:
            with self.subTest(due=due):
                self.assertEqual(assess_risk(due, TODAY)[0], expected)

    def test_inactivity_excludes_sunday_and_last_activity(self):
        self.assertEqual(working_days_since(date(2026, 3, 28), date(2026, 3, 29)), 0)
        self.assertEqual(working_days_since(date(2026, 3, 28), date(2026, 3, 31)), 2)
        self.assertEqual(working_days_since(date(2026, 3, 28), TODAY), 3)
        self.assertEqual(assess_risk(date(2026, 4, 20), date(2026, 3, 28))[0], "At risk")
        self.assertEqual(assess_risk(date(2026, 4, 20), date(2026, 3, 30))[0], "No flag")

    def test_overlapping_reasons_keep_overdue_priority(self):
        risk, reasons, _ = assess_risk(date(2026, 3, 31), date(2026, 3, 28))
        self.assertEqual(risk, "Overdue")
        self.assertIn("Overdue by 1 calendar days", reasons)
        self.assertIn("No activity for 3 working days", reasons)
        risk, reasons, _ = assess_risk(TODAY, date(2026, 3, 28))
        self.assertEqual(risk, "At risk")
        self.assertIn("Due today; No activity", reasons)

    def test_dataset_and_completed_exclusion(self):
        orders = load_orders(ORDERS_PATH)
        active = evaluate_orders(orders)
        self.assertEqual(len(orders), 120)
        self.assertEqual(len(active), 34)
        self.assertTrue(active["status"].eq("IN_PROGRESS").all())
        self.assertTrue(orders.loc[orders.status.eq("IN_PROGRESS"), "completed_date"].isna().all())
        self.assertEqual(active["order_id"].tolist(), active.sort_values(["risk_rank", "due_date", "order_id"])["order_id"].tolist())
        self.assertTrue(evaluate_orders(orders.loc[orders.status.eq("COMPLETE")]).empty)

    def test_invalid_file(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "orders.csv"
            path.write_text("order_id\nORD-001\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing columns"):
                load_orders(path)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "FACTORY_DB": str(Path(self.temp.name) / "dashboard.db"),
            "OPENAI_NETWORK_ENABLED": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = AppTest.from_file(str(ORDERS_PATH.parents[2] / "app.py"), default_timeout=15).run()

    def test_default_and_all_orders(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, "34")
        table = self.app.dataframe[0].value
        self.assertNotIn("No flag", set(table["Risk"]))
        self.app.checkbox[0].check().run()
        self.assertEqual(len(self.app.dataframe[0].value), 34)

    def test_filters_and_empty_results(self):
        self.app.checkbox[0].check().run()
        self.app.multiselect[0].select("UrbanThread").run()
        self.assertEqual(set(self.app.dataframe[0].value["Customer"]), {"UrbanThread"})
        self.app.multiselect[0].set_value([])
        self.app.multiselect[1].select("KNITTING").run()
        self.assertEqual(set(self.app.dataframe[0].value["Stage"]), {"KNITTING"})
        self.app.multiselect[2].select("Overdue").run()
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertTrue(any("No orders match" in item.value for item in self.app.info))
        self.assertFalse(self.app.exception)

    def test_loading_error_is_visible(self):
        for error in [FileNotFoundError("orders.csv missing"), ValueError("Invalid date")]:
            with self.subTest(error=error), patch("pandas.read_csv", side_effect=error):
                self.app.run()
                self.assertFalse(self.app.exception)
                self.assertIn("Could not load orders", self.app.error[0].value)


if __name__ == "__main__":
    unittest.main()


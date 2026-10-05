"""Deterministic factory tools. No model-generated code or arithmetic is executed."""
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from order_risk import STAGES, TODAY, evaluate_orders, load_orders

DATA_DIR = Path(__file__).resolve().parent / "track1" / "data"
JUDGEMENT_POLICIES = {
    "prior_28_days": {"label": "Working days in the previous 28 calendar days", "minimum_samples": 12},
    "previous_week": {"label": "Previous complete week (Monday to Saturday)", "minimum_samples": 3},
    "same_weekday": {"label": "Same weekday over the previous four weeks", "minimum_samples": 3},
}
NORMAL_TOLERANCE_PERCENT = 20


def rows(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def advance_workdays(start, days):
    result = start
    while days > 0:
        result += timedelta(days=1)
        if result.weekday() != 6:
            days -= 1
    return result


class Factory:
    def __init__(self, today=TODAY, data_dir=DATA_DIR):
        self.today = today
        self.data_dir = Path(data_dir)

    def read(self, name):
        path = self.data_dir / name
        # Hash and parse the same bytes, so evidence identifies the exact snapshot.
        import io
        raw = path.read_bytes()
        frame = pd.read_csv(io.BytesIO(raw))
        frame["_csv_row"] = frame.index + 2
        return frame, hashlib.sha256(raw).hexdigest()

    def source(self, name, frame, digest):
        return {"file": f"track1/data/{name}", "sha256": digest, "rows": rows(frame)}

    def pack(self, facts, sources):
        return {"as_of": self.today.isoformat(), "facts": facts, "sources": sources}

    def query_orders(self, order_id=None, customer=None, status=None, stage=None, category=None, risk=None):
        raw, digest = self.read("orders.csv")
        data = raw.copy()
        for field in ["order_date", "due_date", "last_activity_date", "completed_date"]:
            data[field] = pd.to_datetime(data[field])
        active = evaluate_orders(data, self.today)
        data = data.merge(active[["order_id", "risk", "reasons", "inactive_working_days"]], on="order_id", how="left")
        data["risk"] = data["risk"].fillna("Complete")
        data["reasons"] = data["reasons"].fillna("Order completed")
        filters = {"order_id": order_id, "customer": customer, "status": status,
                   "current_stage": stage, "category": category, "risk": risk}
        enums = {"status": ["COMPLETE", "IN_PROGRESS"], "current_stage": STAGES + ["COMPLETE"],
                 "category": ["TOPS", "ACCESSORIES"], "risk": ["Overdue", "At risk", "No flag", "Complete"]}
        for field, value in filters.items():
            if value is not None:
                if field in enums and value not in enums[field]:
                    raise ValueError(f"Invalid {field}: choose {enums[field]}")
                data = data.loc[data[field].str.casefold().eq(str(value).casefold())]
        counts = {key: int(data["risk"].eq(key).sum()) for key in ["Overdue", "At risk", "No flag", "Complete"]}
        facts = {"count": len(data), "pieces": int(data["pieces"].sum()), "risk_counts": counts,
                 "requires_order_selection_for_singular_question": bool(customer and not order_id and len(data) > 1),
                 "orders": rows(data)}
        return self.pack(facts, [self.source("orders.csv", raw.loc[raw.order_id.isin(data.order_id)], digest)])

    def trace_order(self, order_id):
        result = self.query_orders(order_id=order_id)
        result["facts"]["rule"] = "Unfinished only. Overdue: due < today. At risk: due 0–7 calendar days away or inactivity >=3 Mon–Sat days. Overdue has priority."
        return result

    def production_summary(self, start_date, end_date, stage=None):
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start > end or (end - start).days > 366:
            raise ValueError("Choose an ordered date range of at most 366 days.")
        if stage is not None and stage not in STAGES:
            raise ValueError("Unknown production stage.")
        raw, digest = self.read("production_log.csv")
        selected = raw.loc[raw.date.between(start.isoformat(), end.isoformat())]
        if stage:
            selected = selected.loc[selected.stage.eq(stage)]
        summaries = []
        expected_dates = {d.date().isoformat() for d in pd.date_range(start, end)}
        for name in ([stage] if stage else STAGES):
            part = selected.loc[selected.stage.eq(name)]
            working = part.loc[pd.to_datetime(part.date).dt.dayofweek.ne(6)]
            summaries.append({"stage": name, "total_pieces": int(part.pieces_completed.sum()),
                              "observed_days": len(part), "working_observations": len(working),
                              "mean_workday_output": round(float(working.pieces_completed.mean()), 2) if len(working) else None,
                              "min_workday_output": int(working.pieces_completed.min()) if len(working) else None,
                              "max_workday_output": int(working.pieces_completed.max()) if len(working) else None,
                              "missing_dates": sorted(expected_dates - set(part.date))})
        return self.pack({"start_date": start_date, "end_date": end_date, "stages": summaries,
                          "daily_output": rows(selected)}, [self.source("production_log.csv", selected, digest)])

    def judge_stage(self, stage, target_date, output=None, baseline_method="prior_28_days"):
        if stage not in STAGES:
            raise ValueError("Unknown production stage.")
        if baseline_method not in JUDGEMENT_POLICIES:
            raise ValueError("Unknown baseline method; choose prior_28_days, previous_week or same_weekday.")
        target = date.fromisoformat(target_date)
        if output is not None and (isinstance(output, bool) or not isinstance(output, (int, float)) or not math.isfinite(output) or output < 0):
            raise ValueError("Output must be a finite nonnegative number of pieces per day.")
        raw, digest = self.read("production_log.csv")
        frame = raw.loc[raw.stage.eq(stage)]
        observed = frame.loc[frame.date.eq(target_date)]
        actual = output if output is not None else (int(observed.iloc[0].pieces_completed) if len(observed) else None)
        monday = target - timedelta(days=target.weekday())
        dates_by_method = {
            "prior_28_days": [target-timedelta(days=i) for i in range(1,29)],
            "previous_week": [monday-timedelta(days=i) for i in range(1,8)],
            "same_weekday": [target-timedelta(days=7*i) for i in range(1,5)],
        }
        comparisons, supporting = {}, [observed]
        for method, expected in dates_by_method.items():
            expected_dates = sorted(d.isoformat() for d in expected if d.weekday() != 6)
            prior = frame.loc[frame.date.isin(expected_dates)].sort_values("date")
            if prior.date.duplicated().any():
                raise ValueError("Duplicate stage/date observations; cannot produce an auditable baseline.")
            supporting.append(prior)
            mean = float(prior.pieces_completed.mean()) if len(prior) else None
            enough = len(prior) >= JUDGEMENT_POLICIES[method]["minimum_samples"]
            ratio = (actual/mean-1)*100 if actual is not None and mean and mean > 0 and enough and target.weekday() != 6 else None
            lower = mean*(1-NORMAL_TOLERANCE_PERCENT/100) if mean is not None else None
            upper = mean*(1+NORMAL_TOLERANCE_PERCENT/100) if mean is not None else None
            label = "closed" if target.weekday() == 6 else "unknown" if ratio is None else "low" if actual < lower else "high" if actual > upper else "normal"
            reason = "sunday_closed" if target.weekday() == 6 else "missing_target" if actual is None else "insufficient_samples" if not enough else "zero_baseline" if not mean else "comparison_available"
            comparisons[method] = {
                "baseline_method": method, "baseline_label": JUDGEMENT_POLICIES[method]["label"],
                "baseline_mean": round(mean, 2) if mean is not None else None,
                "sample_size": len(prior), "minimum_samples": JUDGEMENT_POLICIES[method]["minimum_samples"],
                "expected_workday_observations": len(expected_dates), "baseline_dates": list(prior.date),
                "missing_dates": sorted(set(expected_dates)-set(prior.date)),
                "normal_lower": round(lower, 2) if lower is not None else None,
                "normal_upper": round(upper, 2) if upper is not None else None,
                "change_percent": round(ratio, 2) if ratio is not None else None,
                "judgement": label, "reason": reason,
            }
        recent_start, recent_end = target-timedelta(days=7), target-timedelta(days=1)
        recent = frame.loc[frame.date.between(str(recent_start),str(recent_end))]
        recent = recent.loc[pd.to_datetime(recent.date).dt.dayofweek.ne(6)]
        supporting.append(recent)
        selected = comparisons[baseline_method]
        return self.pack({"stage": stage, "target_date": target_date, "output": actual,
                          "hypothetical_output": output is not None, "unit": "pieces per working day",
                          **selected, "policy_version": "stage-output-v2", "tolerance_percent": NORMAL_TOLERANCE_PERCENT,
                          "comparisons": list(comparisons.values()),
                          "baseline_disagreement": len({c["judgement"] for c in comparisons.values() if c["judgement"] not in ["unknown","closed"]}) > 1,
                          "recent_7_days": {"start_date":str(recent_start), "end_date":str(recent_end), "workday_count":len(recent),
                              "mean_output":round(float(recent.pieces_completed.mean()),2) if len(recent) else None,
                              "min_output":int(recent.pieces_completed.min()) if len(recent) else None,
                              "max_output":int(recent.pieces_completed.max()) if len(recent) else None},
                          "definition": "Daily output only. Selected baseline excludes target date and Sundays. Arithmetic mean; normal within mean ±20% inclusive. Compare using unrounded values. Minimum samples: prior_28_days=12, previous_week=3, same_weekday=3. Missing data never zero; inadequate/zero baseline is unknown. This is a heuristic, not a statistical confidence interval."},
                         [self.source("production_log.csv", pd.concat(supporting).drop_duplicates().sort_values("date"), digest)])

    def discover(self):
        order_result = self.query_orders(status="IN_PROGRESS")
        orders = order_result["facts"]["orders"]
        findings, sources = [], list(order_result["sources"])
        overdue = [row for row in orders if row["risk"] == "Overdue"]
        if overdue:
            findings.append({"priority": 100, "kind": "overdue", "count": len(overdue),
                             "order_ids": [r["order_id"] for r in overdue], "message": "Overdue orders need a delivery decision."})
        for stage in STAGES:
            result = self.judge_stage(stage, (self.today-timedelta(days=1)).isoformat())
            sources.extend(result["sources"])
            facts = result["facts"]
            if facts["judgement"] == "low":
                findings.append({"priority": 90, "kind": "output_drop", **facts})
            elif facts["judgement"] == "unknown":
                findings.append({"priority": 85, "kind": "data_gap", "stage": stage, "target_date": facts["target_date"],
                                 "message": "No supported comparison: missing target or baseline observations."})
        stalled = [r for r in orders if r["inactive_working_days"] >= 3]
        if stalled:
            findings.append({"priority": 80, "kind": "stalled", "count": len(stalled), "order_ids": [r["order_id"] for r in stalled]})
        for customer in sorted({r["customer"] for r in orders}):
            part = [r for r in orders if r["customer"] == customer]
            flagged = [r for r in part if r["risk"] != "No flag"]
            if len(flagged) >= 2 and len(flagged)/len(part) >= 0.5:
                findings.append({"priority": 60, "kind": "customer_concentration", "customer": customer,
                                 "flagged_count": len(flagged), "unfinished_count": len(part),
                                 "flagged_percent": round(100*len(flagged)/len(part), 2)})
        findings.sort(key=lambda item: (-item["priority"], str(item)))
        return self.pack({"findings": findings[:5], "total_findings": len(findings),
                          "counts": order_result["facts"]["risk_counts"],
                          "ranking": "overdue > output drop > missing data > stalled > customer concentration; top five"}, sources)

    def estimate_feasibility(self, pieces, category, due_date):
        if isinstance(pieces, bool) or not isinstance(pieces, int) or pieces <= 0 or pieces > 1_000_000:
            raise ValueError("Pieces must be an integer from 1 to 1,000,000.")
        if category not in ["TOPS", "ACCESSORIES"]:
            raise ValueError("Specify TOPS or ACCESSORIES.")
        due = date.fromisoformat(due_date)
        if due < self.today:
            raise ValueError("The requested due date is in the past; choose a future deadline.")
        orders = self.query_orders(status="IN_PROGRESS")
        rates = self.production_summary((self.today-timedelta(days=28)).isoformat(), (self.today-timedelta(days=1)).isoformat())
        stage_loads, duration = [], 0.0
        for index, stage in enumerate(STAGES):
            backlog = sum(r["pieces"] for r in orders["facts"]["orders"] if STAGES.index(r["current_stage"]) <= index)
            rate = next(s["mean_workday_output"] for s in rates["facts"]["stages"] if s["stage"] == stage)
            days = (backlog + pieces) / rate if rate and rate > 0 else None
            stage_loads.append({"stage": stage, "backlog_pieces": backlog, "rate": rate, "working_days": round(days, 2) if days is not None else None})
            if days is not None:
                duration += days
        internal_finish = advance_workdays(self.today, math.ceil(duration)) if all(r["working_days"] is not None for r in stage_loads) else None
        workshops, digest = self.read("workshops.csv")
        candidates = []
        for w in workshops.itertuples():
            reasons = []
            if w.status != "ACTIVE": reasons.append("suspended")
            if category not in w.makes.split("+"): reasons.append("incompatible category")
            if pd.notna(w.max_batch_pieces) and pieces > w.max_batch_pieces: reasons.append("exceeds trial batch cap")
            processing = math.ceil(w.current_queue_days + pieces/w.capacity_pieces_per_day)
            finish = advance_workdays(self.today, processing) + timedelta(days=int(w.pickup_lead_days))
            if finish.weekday() == 6: finish += timedelta(days=1)
            candidates.append({"workshop_id": w.workshop_id, "name": w.name, "eligible": not reasons,
                               "exclusion_reasons": reasons, "estimated_finish": finish.isoformat() if not reasons else None,
                               "meets_due_date": not reasons and finish <= due, "queue_working_days": w.current_queue_days,
                               "capacity_pieces_per_day": w.capacity_pieces_per_day, "processing_and_queue_workdays": processing,
                               "transport_calendar_days": w.pickup_lead_days, "batch_defect_probability": w.defect_rate,
                               "batch_defect_percent": round(w.defect_rate*100, 2), "estimated_cost_units": round(pieces*w.cost_per_piece, 2)})
        viable = [c["workshop_id"] for c in candidates if c["meets_due_date"]]
        return self.pack({"pieces": pieces, "category": category, "due_date": due_date,
                          "internal": {"stages": stage_loads, "working_days": math.ceil(duration) if internal_finish else None,
                                       "estimated_finish": internal_finish.isoformat() if internal_finish else None,
                                       "meets_due_date": internal_finish <= due if internal_finish else None},
                          "workshops": candidates, "eligible_on_time_workshops": viable,
                          "conclusion": "possible_with_assumptions" if viable or (internal_finish and internal_finish <= due) else "not_supported_by_estimate",
                          "assumptions": ["Estimate, not a promise or reservation. Full batch; no implicit splitting.",
                                          "Internal serial stages, all unfinished quantities remain at current/downstream stages; no overlap or partial progress.",
                                          "Rates are means of available Mon–Sat observations in prior 28 calendar days; not guaranteed capacity.",
                                          "Workshops assumed to handle the full batch; queue/processing use workdays, transport calendar days; Sunday arrivals roll forward.",
                                          "Defect probability is shown separately: fraction redone is unknown. Currency is unspecified."]},
                         orders["sources"] + rates["sources"] + [self.source("workshops.csv", workshops, digest)])

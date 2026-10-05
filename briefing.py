"""Auditable morning-briefing analysis and an English report available offline."""
from datetime import date, timedelta

from order_risk import STAGES


BRIEFING_VERSION = "management-briefing-v2"


def cell(value):
    if value is None:
        return "Unknown"
    return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def table(headers, records):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(cell(v) for v in record) + " |" for record in records],
    ])


def build_briefing(factory):
    """Compute all comparisons and priorities in Python, never in model prose."""
    yesterday = (factory.today - timedelta(days=1)).isoformat()
    production = factory.production_summary(yesterday, yesterday)
    discovery = factory.discover()
    orders = factory.query_orders(status="IN_PROGRESS")
    evidence = {
        "E1": {"tool": "production_summary", **production},
        "E2": {"tool": "discover", **discovery},
    }
    enriched = []
    for original in orders["facts"]["orders"]:
        row = dict(original)
        due = date.fromisoformat(row["due_date"][:10])
        row.update(due_date=due.isoformat(), days_to_due=(due - factory.today).days,
                   days_overdue=max(0, (factory.today - due).days))
        enriched.append(row)
    flagged = [r for r in enriched if r["risk"] in ["Overdue", "At risk"]]
    due_soon = [r for r in enriched if 0 <= r["days_to_due"] <= 7]
    stalled = [r for r in enriched if r["inactive_working_days"] >= 3]
    ranked = sorted(flagged, key=lambda r: (r["risk"] != "Overdue", r["due_date"], -r["inactive_working_days"], r["order_id"]))
    customers = []
    for customer in sorted({r["customer"] for r in flagged}):
        active = [r for r in enriched if r["customer"] == customer]
        at_risk = [r for r in active if r["risk"] in ["Overdue", "At risk"]]
        customers.append({"customer": customer, "unfinished_count": len(active), "flagged_count": len(at_risk),
                          "overdue_count": sum(r["risk"] == "Overdue" for r in active),
                          "flagged_percent": round(100 * len(at_risk) / len(active), 2),
                          "flagged_order_pieces": sum(r["pieces"] for r in at_risk),
                          "order_ids": [r["order_id"] for r in at_risk]})
    customers.sort(key=lambda r: (-r["overdue_count"], -r["flagged_count"], -r["flagged_percent"], r["customer"]))
    portfolio = {
        "unfinished_count": len(enriched), "unfinished_order_pieces": sum(r["pieces"] for r in enriched),
        "risk_counts": orders["facts"]["risk_counts"], "flagged_count": len(flagged),
        "flagged_percent": round(100 * len(flagged) / len(enriched), 2) if enriched else 0,
        "flagged_order_pieces": sum(r["pieces"] for r in flagged),
        "due_next_7_days_count": len(due_soon), "due_next_7_days_pieces": sum(r["pieces"] for r in due_soon),
        "stalled_count": len(stalled), "stalled_order_ids": [r["order_id"] for r in stalled],
        "priority_orders": ranked[:8], "other_flagged_count": max(0, len(ranked) - 8),
        "customers": customers,
        "priority_rule": "Overdue first, then earliest due date, longer inactivity, and order ID; show first 8.",
        "customer_rule": "Overdue count, flagged count, flagged share, then customer name; show first 5.",
        "quantity_definition": "Order quantities are full batch sizes, not remaining work or lost revenue. Due-soon and stalled groups can overlap risk groups.",
    }
    evidence["E3"] = {"tool": "briefing_portfolio", **factory.pack(portfolio, orders["sources"])}
    stages = []
    for index, stage in enumerate(STAGES, 4):
        result = factory.judge_stage(stage, yesterday)
        ref = f"E{index}"
        evidence[ref] = {"tool": "judge_stage", **result}
        stages.append({**result["facts"], "evidence_id": ref})
    # If files changed between tool reads, do not mix incompatible evidence snapshots.
    hashes = {}
    for result in evidence.values():
        for source in result["sources"]:
            hashes.setdefault(source["file"], set()).add(source["sha256"])
    if any(len(values) != 1 for values in hashes.values()):
        raise ValueError("Source data changed while building the briefing. Please generate it again.")
    facts = {"yesterday": production["facts"], "attention": discovery["facts"], "portfolio": portfolio, "stage_analysis": stages}
    counts = portfolio["risk_counts"]
    summary = (f"As of {factory.today}, {portfolio['unfinished_count']} orders are unfinished; "
               f"{counts['Overdue']} are overdue and {counts['At risk']} are at risk but not overdue. "
               f"{portfolio['due_next_7_days_count']} orders are due from today through the next 7 calendar days. "
               "Review the delivery priorities and stage comparisons below before making commitments.")
    sections = []
    sections.append({"title": "Delivery exposure", "body": (
        f"**{portfolio['flagged_count']} of {portfolio['unfinished_count']} unfinished orders are flagged "
        f"({portfolio['flagged_percent']}%).** Their full order quantities total {portfolio['flagged_order_pieces']} pieces. "
        f"The upcoming due-date window covers {portfolio['due_next_7_days_count']} orders and {portfolio['due_next_7_days_pieces']} pieces. "
        f"{portfolio['stalled_count']} orders have no recorded activity for at least 3 working days. [E3]\n\n"
        "These groups overlap. Full order quantities do not measure remaining work, capacity demand, or revenue at risk.")})
    production_rows = []
    for stage in stages:
        production_rows.append([stage["stage"], stage["output"], stage["baseline_mean"], stage["sample_size"],
                                stage["change_percent"], stage["judgement"], stage["recent_7_days"]["mean_output"], stage["evidence_id"]])
    production_body = f"Actual daily output for **{yesterday}**. Each stage is compared with its own working-day mean over the preceding 28 calendar days.\n\n"
    production_body += table(["Stage", "Pieces", "Baseline mean", "Samples", "Change %", "Judgement", "Prior 7-day workday mean", "Evidence"], production_rows)
    for stage in stages:
        alternatives = "; ".join(f"{c['baseline_label']}: {c['judgement']} (mean {cell(c['baseline_mean'])}, samples {c['sample_size']})" for c in stage["comparisons"][1:])
        production_body += f"\n\n**{stage['stage']} — baseline sensitivity:** {alternatives}. [{stage['evidence_id']}]"
        if stage["baseline_disagreement"]:
            production_body += " The baselines disagree; the normal/abnormal conclusion depends on the comparison period."
        if stage["judgement"] == "low":
            production_body += " Recommended investigation: verify staffing, downtime, rework, and upstream supply; none is an established cause in this dataset."
    production_body += "\n\nNormal means within the baseline mean ±20%, inclusive. Sundays are closed; missing data is unknown. Stage totals must not be added together as finished-goods output, and output alone does not establish a bottleneck."
    sections.append({"title": "Production performance and baseline sensitivity", "body": production_body})
    priority_rows = [[r["order_id"], r["customer"], r["current_stage"], r["pieces"], r["due_date"], r["days_overdue"],
                      r["inactive_working_days"], r["reasons"]] for r in portfolio["priority_orders"]]
    priority_body = portfolio["priority_rule"] + " [E3]\n\n"
    priority_body += table(["Order", "Customer", "Stage", "Order pieces", "Due", "Days overdue", "Inactive workdays", "Risk reasons"], priority_rows) if priority_rows else "No unfinished orders meet the current risk rules."
    priority_body += f"\n\nAdditional flagged orders outside this table: {portfolio['other_flagged_count']}. Expand E3 for customer exposure and the cited source rows."
    sections.append({"title": "Orders requiring attention", "body": priority_body})
    customer_body = portfolio["customer_rule"] + " [E3]\n\n"
    customer_body += table(["Customer", "Overdue", "Flagged / unfinished", "Flagged %", "Flagged order pieces", "Flagged order IDs"],
                           [[r["customer"], r["overdue_count"], f"{r['flagged_count']} / {r['unfinished_count']}", r["flagged_percent"], r["flagged_order_pieces"], ", ".join(r["order_ids"])] for r in customers[:5]]) if customers else "No customers have flagged unfinished orders."
    customer_body += "\n\nConcentration indicates customer exposure, not a common cause or a confirmed missed delivery."
    sections.append({"title": "Customer exposure", "body": customer_body})
    decisions = []
    if counts["Overdue"]:
        decisions.append("**First — overdue delivery review [E3].** Ask the planner to verify current progress and a realistic revised finish date for each overdue order. Prepare customer follow-up drafts only after those facts are checked.")
    if due_soon:
        decisions.append("**Upcoming commitments [E3].** Review orders due in the coming window, confirm remaining work and available capacity, then choose whether a separate feasibility estimate is needed. The risk flag is not a completion forecast.")
    for stage in stages:
        if stage["judgement"] == "low":
            decisions.append(f"**Investigate {stage['stage']} [{stage['evidence_id']}].** Validate the low-output record and ask for operational context. Compare recent and longer baselines before considering overtime or subcontracting; no capacity is reserved by this briefing.")
    if stalled:
        decisions.append(f"**Check inactive orders [E3].** Ask for a progress update on {', '.join(portfolio['stalled_order_ids'])}. An unchanged activity date may indicate missing reporting rather than physical stoppage.")
    if not decisions:
        decisions.append("**Routine review.** No delivery or low-output triggers were identified by the current rules. Verify data coverage before interpreting this as a healthy operation.")
    sections.append({"title": "Recommended decisions today", "body": "\n\n".join(decisions) + "\n\nThese are recommendations, not executed actions. Saving a draft, note, reminder, or watch requires a separate preview and confirmation in Actions & watches."})
    limitations = []
    for stage in stages:
        ref = stage["evidence_id"]
        if stage["judgement"] in ["unknown", "closed"]:
            limitations.append(f"{stage['stage']} on {yesterday}: {stage['judgement']} ({stage['reason']}). [{ref}]")
        if stage["missing_dates"]:
            limitations.append(f"{stage['stage']} baseline missing dates: {', '.join(stage['missing_dates'])}. [{ref}]")
    if not limitations:
        limitations.append("All stages have a recorded target-day observation and complete selected-baseline dates. This does not verify the accuracy of the underlying entries. [E4–E7]")
    limitations.extend([
        "Order risk is a rule-based snapshot: unfinished orders due before today are overdue; otherwise due within 7 calendar days or inactivity of at least 3 Monday–Saturday working days is flagged. [E3]",
        "No per-order completed quantities, labor availability, downtime causes, selling prices, or live workshop reservations are available. Do not infer causes, financial loss, or a guaranteed delivery date.",
        "The simulation date advances independently of the CSV files. Expand evidence to inspect observation dates, source rows, file hashes, normal bands, and sample counts. The prior 7-day mean excludes the target day and Sundays; it is not the previous complete week.",
    ])
    sections.append({"title": "Data quality and interpretation limits", "body": "\n\n".join(limitations)})
    return {"version": BRIEFING_VERSION, "date": factory.today.isoformat(), "summary": summary,
            "generation": "deterministic", "sections": sections, "facts": facts, "evidence": evidence}

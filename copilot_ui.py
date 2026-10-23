"""Streamlit views for the factory co-pilot; only explicit Confirm commits actions."""
import json
import re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from agent import Copilot
from openai_client import MODEL_LABEL, ModelError, api_key, network_enabled
from factory import Factory, JUDGEMENT_POLICIES
from order_risk import STAGES
from scheduler import create_briefing
from state import Store, propose_action, wall_now
from ui_theme import chat_welcome, page_heading


def evidence_view(evidence):
    for ref, result in evidence.items():
        with st.expander(f"{ref} · {result.get('tool', 'Evidence')}"):
            st.json(result.get("facts", {}), expanded=False)
            for source in result.get("sources", []):
                st.caption(f"{source['file']} · SHA256 {source['sha256'][:16]} · {len(source['rows'])} rows")
                if source["rows"]:
                    st.dataframe(pd.DataFrame(source["rows"]), hide_index=True, width="stretch")
            st.download_button("Download full evidence as JSON", json.dumps(result, ensure_ascii=False, indent=2),
                               file_name=f"evidence-{ref}.json", key=f"evidence_{ref}_{hash(json.dumps(result, sort_keys=True))}")


def proposal_view(proposal, store):
    st.warning("Awaiting confirmation · No action taken yet")
    st.write(f"Action: {proposal['kind']}")
    st.json(proposal["payload"])
    st.caption(proposal["effect"])
    left, right = st.columns(2)
    if left.button("Confirm", key=f"confirm_{proposal['id']}", type="primary"):
        try:
            store.commit(proposal, confirmed=True)
            st.session_state.setdefault("resolved_proposals", {})[proposal["id"]] = "confirmed"
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if right.button("Reject", key=f"reject_{proposal['id']}"):
        st.session_state.setdefault("resolved_proposals", {})[proposal["id"]] = "rejected"
        st.rerun()


def readable_answer(text):
    """Space out older plain-text replies without rewriting their contents."""
    if len(text) < 240 or "\n" in text or re.search(r"[*`#]|\[[^\]]+\]\(", text):
        return text
    return re.sub(r"(?<=[.!?]) +(?=[A-Z])", "\n\n", text)


def render_result(result, store, key):
    st.markdown(readable_answer(result["summary"]))
    if result.get("details"):
        with st.expander("Details"):
            st.markdown(readable_answer(result["details"]))
    st.caption(f"{result['model']} · {result['elapsed_seconds']} seconds · Evidence: {', '.join(result['evidence_ids']) or 'No factual references'}")
    # Namespace evidence IDs by conversation turn so repeated evidence has distinct widgets.
    evidence_view({f"{key}-{ref}": value for ref, value in result["evidence"].items()})
    for proposal in result["proposals"]:
        resolved = st.session_state.get("resolved_proposals", {}).get(proposal["id"])
        if resolved:
            st.caption("Confirmed and recorded." if resolved == "confirmed" else "Rejected. No action taken.")
        else:
            proposal_view(proposal, store)
    with st.expander("Tool call log"):
        st.json(result["trace"], expanded=False)


def set_prompt(question):
    """Fill the composer only; selecting a suggestion never calls the model."""
    st.session_state.copilot_prompt = question


def chat_page(factory, store):
    st.session_state.setdefault("conversation", [])
    online = network_enabled()
    ready = online and bool(api_key())
    if not st.session_state.conversation:
        chat_welcome()
    else:
        page_heading("Let's work through it.", "Follow the evidence from question to decision.", "Factory Co-pilot")
    if not online:
        st.info("Online Q&A is disabled by your preference. Risk, production, estimates, briefings, and watches remain available locally. No factory data is sent to OpenAI.")
        with st.expander("Local order lookup · no online access needed", expanded=True):
            with st.form("offline_lookup"):
                order_id = st.text_input("Exact order ID", "ORD-002")
                if st.form_submit_button("Load fresh evidence"):
                    st.session_state.offline_trace = factory.trace_order(order_id)
        if st.session_state.get("offline_trace"):
            evidence_view({"offline-order": st.session_state.offline_trace})
    elif not ready:
        st.info("Set OPENAI_API_KEY to enable Q&A. Other pages remain available offline.")
    if not st.session_state.conversation:
        st.subheader("Where would you like to start?")
        st.caption("Choose a question to edit it, then send.")
        prompts = [
            ("Review delivery risks", "See overdue orders and upcoming deadlines.", "Which unfinished orders are overdue or at risk?", ":material/assignment_late:"),
            ("Explore production", "Compare output against an explicit baseline.", "Which stages had unusual output yesterday?", ":material/query_stats:"),
            ("Trace an order", "Understand the evidence behind a risk flag.", "Why is ORD-002 at risk?", ":material/route:"),
            ("Check a new order", "Compare internal production and workshops.", f"Can we accept 800 TOPS pieces due on {(factory.today+timedelta(days=24)).isoformat()}?", ":material/inventory_2:"),
        ]
        with st.container(key="quick_prompts"):
            for start in (0, 2):
                columns = st.columns(2)
                for offset, column in enumerate(columns):
                    label, description, prompt, icon = prompts[start+offset]
                    with column:
                        st.button(label, icon=icon, width="stretch", key=f"prompt_{start+offset}",
                                  disabled=not ready, on_click=set_prompt, args=(prompt,))
                        st.caption(description)
    with st.expander("Example questions"):
        st.markdown("- Which stages had unusual output yesterday?\n- How are TrendCart orders doing?\n- Why is ORD-002 at risk?\n- Can we accept 800 hoodies due on 2026-04-25?\n- Draft a follow-up message for ORD-002.\n- Remind me tomorrow at 09:00 if ORD-005 has not moved.")
    if st.session_state.conversation:
        _, toolbar = st.columns([4, 1])
        if toolbar.button("Clear conversation", icon=":material/restart_alt:", width="stretch"):
            st.session_state.conversation = []
            st.rerun()
    for index, turn in enumerate(st.session_state.conversation):
        with st.chat_message("user", avatar=":material/person:"):
            st.write(turn["question"])
        with st.chat_message("assistant", avatar=":material/explore:"):
            render_result(turn["result"], store, f"turn{index}")
    question = st.chat_input("Ask your factory a question...", key="copilot_prompt", max_chars=6000, disabled=not ready)
    if question:
        history = []
        for turn in st.session_state.conversation:
            history.extend([{"role": "user", "content": turn["question"]},
                            {"role": "assistant", "content": turn["result"]["summary"]}])
        with st.spinner(f"Reading fresh data and asking {MODEL_LABEL}..."):
            try:
                result = Copilot(factory, store).ask(question, history)
                st.session_state.conversation.append({"question": question, "result": result})
                st.rerun()
            except (ModelError, ValueError, OSError) as exc:
                st.error(str(exc))


def production_page(factory):
    page_heading("See beyond the daily numbers.", "Compare production with clear baselines and explore the findings that deserve a closer look.", "Production & discovery")
    stage = st.selectbox("Stage", STAGES)
    target = st.date_input("Comparison date", factory.today-timedelta(days=1))
    method = st.selectbox("Comparison baseline", list(JUDGEMENT_POLICIES), format_func=lambda value: JUDGEMENT_POLICIES[value]["label"])
    hypothetical = st.checkbox("Compare a hypothetical daily output")
    output = st.number_input("Hypothetical output (pieces per day)", min_value=0, value=800) if hypothetical else None
    result = factory.judge_stage(stage, target.isoformat(), output=output, baseline_method=method)
    facts = result["facts"]
    a, b, c = st.columns(3)
    a.metric("Hypothetical daily output" if hypothetical else "Daily output", facts["output"] if facts["output"] is not None else "No data")
    b.metric("Selected baseline mean", facts["baseline_mean"] if facts["baseline_mean"] is not None else "No data")
    c.metric("Change from mean", f"{facts['change_percent']}%" if facts["change_percent"] is not None else "Not comparable")
    st.write(f"Judgement: **{facts['judgement']}** · Sample: {facts['sample_size']} working days")
    st.caption("Baseline: " + facts["baseline_label"] + ". Normal means within 20% of the mean, including the boundaries. This is a heuristic, not a statistical confidence interval.")
    if facts["baseline_disagreement"]:
        st.warning("Different baselines give different results. Review the comparisons below before deciding whether output is normal.")
    comparisons = pd.DataFrame(facts["comparisons"])[["baseline_label","baseline_mean","sample_size","minimum_samples","normal_lower","normal_upper","change_percent","judgement"]]
    st.dataframe(comparisons.rename(columns={"baseline_label":"Baseline","baseline_mean":"Mean","sample_size":"Sample size","minimum_samples":"Minimum samples","normal_lower":"Normal lower bound","normal_upper":"Normal upper bound","change_percent":"Change %","judgement":"Judgement"}), hide_index=True, width="stretch")
    with st.expander("Method, sample dates, and missing data"):
        st.write(facts["definition"])
        st.json({"policy_version":facts["policy_version"], "comparisons":facts["comparisons"], "recent_7_days":facts["recent_7_days"]})
    period = factory.production_summary((target-timedelta(days=28)).isoformat(), target.isoformat(), stage)
    daily = pd.DataFrame(period["facts"]["daily_output"])
    if not daily.empty:
        st.line_chart(daily.set_index("date")[["pieces_completed"]])
    st.subheader("Discovery · Top five findings")
    discovery = factory.discover()
    for finding in discovery["facts"]["findings"]:
        kind = finding["kind"]
        if kind == "overdue":
            st.warning(f"{finding['count']} orders are overdue. Verify revised due dates.")
        elif kind == "output_drop":
            st.warning(f"{finding['stage']} output dropped: {finding['output']} pieces, a change from the working-day mean of {finding['change_percent']}%.")
        elif kind == "data_gap":
            st.info(f"{finding['stage']} has no comparable data for {finding['target_date']}.")
        elif kind == "stalled":
            st.warning(f"{finding['count']} orders have had no activity for at least 3 working days and need follow-up.")
        else:
            st.warning(f"{finding['customer']} has {finding['flagged_count']}/{finding['unfinished_count']} unfinished orders flagged, or {finding['flagged_percent']}%.")
        with st.expander("Inspect finding details"):
            st.json(finding, expanded=False)
    evidence_view({"production": result, "discovery": discovery})


def feasibility_page(factory):
    page_heading("Can we deliver the next order?", "Compare internal workload with eligible workshops before making a delivery commitment.", "Feasibility")
    with st.form("feasibility"):
        pieces = st.number_input("Quantity (pieces)", 1, 1000000, 800, step=100)
        category = st.selectbox("Category", ["TOPS", "ACCESSORIES"])
        due = st.date_input("Due date", factory.today+timedelta(days=24), min_value=factory.today)
        submitted = st.form_submit_button("Calculate estimate", type="primary")
    if submitted:
        st.session_state.feasibility_result = factory.estimate_feasibility(int(pieces), category, due.isoformat())
    result = st.session_state.get("feasibility_result")
    if result:
        facts = result["facts"]
        st.info(f"Conservative internal finish date: {facts['internal']['estimated_finish'] or 'Insufficient data'}; eligible workshops estimated to finish on time: {', '.join(facts['eligible_on_time_workshops']) or 'None'}")
        st.warning("This is an estimate, not a delivery commitment. No orders have been assigned or capacity reserved.")
        st.dataframe(pd.DataFrame(facts["workshops"]), hide_index=True, width="stretch")
        with st.expander("Estimation assumptions", expanded=True):
            for assumption in facts["assumptions"]:
                st.write(assumption)
            st.dataframe(pd.DataFrame(facts["internal"]["stages"]), hide_index=True)
        evidence_view({"feasibility": result})


def briefing_page(factory, store):
    page_heading("Start with the full picture.", "Your management briefing brings delivery exposure, production changes and recommended follow-ups together.", "Daily briefing")
    st.caption("Scheduled briefings run in the background even when the browser is closed. The computer must be awake and the background worker running.")
    if st.button("Preview briefing (without saving)", type="primary"):
        with st.spinner("Summarizing yesterday, risks, and decisions..."):
            st.session_state.briefing_preview = create_briefing(factory)
    saved = store.briefing(factory.today)
    payload = st.session_state.get("briefing_preview") or saved
    if payload:
        st.subheader("Executive overview")
        st.markdown(payload["summary"])
        st.caption(f"Data date: {payload['date']} · Generated by: {payload['generation']} · {'Saved by schedule' if payload is saved else 'Preview'}")
        if payload.get("generation_error"):
            st.warning("The model is unavailable. Showing an offline summary from the data tools: " + payload["generation_error"])
        if not payload.get("sections"):
            st.info("This briefing uses the earlier format. Select Preview briefing to generate the detailed report.")
        for section in payload.get("sections", []):
            st.subheader(section["title"])
            st.markdown(section["body"])
        st.subheader("Source evidence")
        evidence_view({f"briefing-{key}": value for key, value in payload["evidence"].items()})
    else:
        st.info("No briefing yet. Generate a preview or confirm a daily schedule below.")
    with st.form("briefing_schedule"):
        schedule = store.get_setting("briefing_schedule") or {"enabled": True, "time": "07:00"}
        enabled = st.checkbox("Generate a briefing every day", value=schedule["enabled"])
        clock = st.text_input("Beijing time (HH:MM)", value=schedule["time"])
        if st.form_submit_button("Preview schedule change"):
            try:
                st.session_state.schedule_proposal = propose_action(factory, store, "briefing_schedule", schedule_time=clock, enabled=enabled)["facts"]["proposal"]
            except ValueError as exc:
                st.error(str(exc))
    proposal = st.session_state.get("schedule_proposal")
    if proposal and proposal["id"] not in st.session_state.get("resolved_proposals", {}):
        proposal_view(proposal, store)


@st.fragment(run_every="30s")
def activity_inbox(store):
    activity = store.activity()
    worker = activity["worker"]
    if worker:
        age = (wall_now()-datetime.fromisoformat(worker["last_tick"])).total_seconds()
        st.caption(f"Last background check: {worker['last_tick']} · {'Running' if age < 120 and worker['ok'] else 'Stopped or failed; check the background worker'}")
    else:
        st.warning("The background worker has not started. Run uv run python worker.py to enable automatic checks.")
    st.subheader("Alert inbox")
    if not activity["alerts"]:
        st.info("No alerts yet. Each watch triggers at most once.")
    for alert in activity["alerts"]:
        with st.expander(f"{alert['created_at']} · {alert['payload'].get('message', 'Alert')}"):
            st.json(alert["payload"], expanded=False)
    st.subheader("Watches and action history")
    st.json(activity, expanded=False)


def actions_page(factory, store):
    page_heading("Turn decisions into follow-ups.", "Review proposals, confirm the exact scope and keep track of your saved actions and alerts.", "Actions & watches")
    st.caption("Notes, follow-up drafts, watches, and reminders are saved locally. External email and chat delivery are not connected.")
    with st.form("manual_action"):
        kind = st.selectbox("Action", ["add_note", "save_draft", "watch_order", "watch_stage", "reminder", "cancel_watch"])
        order = st.text_input("Order ID (for notes, drafts, or order watches)", "ORD-002")
        stage = st.selectbox("Stage (for stage watches)", STAGES)
        content = st.text_area("Note, draft, or reminder content")
        deadline = st.text_input("Check time (simulation date, ISO format)", (factory.today+timedelta(days=1)).isoformat()+"T09:00:00")
        watch_id = st.text_input("Watch ID (for cancellation)")
        if st.form_submit_button("Preview action"):
            try:
                st.session_state.manual_proposal = propose_action(factory, store, kind, order_id=order,
                    stage=stage, content=content, deadline=deadline, watch_id=watch_id)["facts"]["proposal"]
            except ValueError as exc:
                st.error(str(exc))
    proposal = st.session_state.get("manual_proposal")
    if proposal and proposal["id"] not in st.session_state.get("resolved_proposals", {}):
        proposal_view(proposal, store)
    activity_inbox(store)


def page_router(page, today):
    factory, store = Factory(today=today), Store()
    pages = {"Co-pilot": lambda: chat_page(factory, store), "Production & discovery": lambda: production_page(factory),
             "Feasibility": lambda: feasibility_page(factory), "Briefing": lambda: briefing_page(factory, store),
             "Actions & watches": lambda: actions_page(factory, store)}
    try:
        pages[page]()
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"Unable to read the required data: {exc}")

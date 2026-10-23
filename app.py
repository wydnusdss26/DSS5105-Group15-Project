"""SweaterCo Track 1 co-pilot. Entry point: uv run streamlit run app.py."""
import pandas as pd
import streamlit as st

from order_risk import TODAY, ORDERS_PATH, STAGES, RISK_LEVELS, load_orders, evaluate_orders, assess_risk, working_days_since
from state import Store, wall_now
from copilot_ui import page_router
from openai_client import network_enabled
from ui_theme import apply_theme, page_heading, sidebar_navigation, workspace_topline


def main() -> None:
    st.set_page_config(page_title="Factory Co-pilot | SweaterCo", page_icon=":material/factory:", layout="wide")
    apply_theme()
    store = Store()
    today = store.today()
    page = sidebar_navigation(today, network_enabled())
    workspace_topline(page, today)
    if page != "Risk overview":
        page_router(page, today)
        return
    page_heading("Stay ahead of delivery risks.", "A clear view of unfinished orders, approaching deadlines and the follow-ups that need your attention.", "Order risk overview")
    st.caption("Rule-based warnings for unfinished orders. These flags are not completion forecasts.")

    try:
        orders = load_orders(ORDERS_PATH)
        active = evaluate_orders(orders, today)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f"Could not load orders: {exc}")
        st.caption("Check track1/data/orders.csv and its required columns, dates, and quantities.")
        return

    metrics = st.columns(3)
    metrics[0].metric("Unfinished orders", len(active))
    metrics[1].metric("Overdue", int(active["risk"].eq("Overdue").sum()))
    metrics[2].metric("At risk · not yet overdue", int(active["risk"].eq("At risk").sum()))
    st.caption("Counts cover all unfinished orders, before table filters.")

    with st.sidebar:
        st.header("Filter orders")
        show_all = st.checkbox("Show all unfinished orders", value=False)
        customers = st.multiselect("Customer", sorted(active["customer"].unique()))
        stages = st.multiselect("Current stage", STAGES)
        risk_options = RISK_LEVELS if show_all else RISK_LEVELS[:2]
        risks = st.multiselect("Risk", risk_options, key=f"risk_filter_{show_all}")
        st.caption("Empty selections include every available value. Completed orders are excluded.")

    visible = active.copy() if show_all else active.loc[active["risk"].ne("No flag")].copy()
    for column, values in [("customer", customers), ("current_stage", stages), ("risk", risks)]:
        if values:
            visible = visible.loc[visible[column].isin(values)]

    st.divider()
    st.subheader("Orders to review")
    st.caption(f"Showing {len(visible)} of {len(active)} unfinished orders · Severity first, then earliest due date")
    if visible.empty:
        st.info("No orders match these filters. Clear a filter or show all unfinished orders.")
    else:
        columns = {
            "order_id": "Order", "customer": "Customer", "product": "Product",
            "pieces": "Pieces", "current_stage": "Stage", "due_date": "Due date",
            "last_activity_date": "Last activity", "risk": "Risk", "reasons": "Reasons",
        }
        display = visible[list(columns)].rename(columns=columns)
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "Due date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Last activity": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Pieces": st.column_config.NumberColumn(format="%d"),
                "Reasons": st.column_config.TextColumn(width="large"),
            },
        )

    with st.expander("How orders are flagged"):
        st.markdown(
            "- **Overdue:** unfinished and due before the displayed reference date.\n"
            "- **At risk:** not overdue, but due within 7 calendar days inclusive, or inactive for at least three working days.\n"
            "- **No flag:** neither warning rule applies; this does not guarantee on-time delivery.\n\n"
            "Inactivity counts days after the last recorded activity through the reference date, "
            "excluding Sundays. Every applicable reason is shown. Overdue takes priority over At risk."
        )


if __name__ == "__main__":
    main()

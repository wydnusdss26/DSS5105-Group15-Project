"""Shared, local-only visual styling for the existing Streamlit workspace."""
from html import escape
from pathlib import Path
import base64

import streamlit as st
from openai_client import MODEL_LABEL

ROOT = Path(__file__).resolve().parent
LOGO = ROOT / "assets" / "branding" / "factory-copilot-logo.png"
PAGES = ["Risk overview", "Co-pilot", "Production & discovery", "Feasibility", "Briefing", "Actions & watches"]

CSS = """
<style>
:root { --fc-ink:#172740; --fc-muted:#6a7890; --fc-blue:#3357b8; --fc-teal:#078696; }
.stApp { background:#f5f7fc; color:var(--fc-ink); }
[data-testid="stHeader"] { background:rgba(245,247,252,.92); }
.stMainBlockContainer { max-width:1250px; padding-top:4.5rem; padding-bottom:5rem; }
h1,h2,h3 { color:var(--fc-ink); letter-spacing:-.025em; }
[data-testid="stSidebar"] { background:linear-gradient(170deg,#edf2ff 0%,#f8faff 60%,#e8f5f4 100%); border-right:1px solid #e1e7f1; }
[data-testid="stSidebar"] > div:first-child { padding-top:0; }
[data-testid="stSidebarUserContent"] { padding-top:1.2rem; }
[data-testid="stSidebar"] [role="radiogroup"] > * { display:block; width:100%; box-sizing:border-box; border-radius:11px; padding:.65rem .8rem; margin:.15rem 0; }
[data-testid="stSidebar"] [role="radiogroup"] > *:hover { background:#e4eaff; }
[data-testid="stSidebar"] [role="radiogroup"] > *:has(input:checked),
[data-testid="stSidebar"] [role="radiogroup"] > *[data-selected],
[data-testid="stSidebar"] [role="radiogroup"] > *[aria-checked="true"] { background:#3357b8; color:#fff; }
[data-testid="stSidebar"] [role="radiogroup"] > *:has(input:checked) p,
[data-testid="stSidebar"] [role="radiogroup"] > *[data-selected] p { color:#fff; font-weight:600; }
.st-key-brand_panel { background:transparent; border:0; border-bottom:1px solid #dce4f1; border-radius:0; padding:0 0 1rem; margin-top:-2rem; box-shadow:none; }
.fc-logo-window { width:100%; aspect-ratio:4.64; overflow:hidden; }
.fc-logo-window img { display:block; width:100%; height:auto; transform:translateY(-25%); }
.st-key-brand_panel .fc-brand-caption { margin:6px 0 0; text-align:center; font-size:.72rem; line-height:1.5; letter-spacing:.015em; color:#74839a; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child { display:none; }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child { display:none; }
[data-testid="stSidebar"] hr { border-color:#dce4f1; }
.fc-nav-label { color:#7b88a0; font-size:.69rem; font-weight:700; letter-spacing:.15em; margin:1rem 0 .45rem; }
.fc-connection { display:inline-flex; align-items:center; gap:8px; padding:6px 10px; margin:.4rem 0; border-radius:8px; font-size:.76rem; color:#237369; background:#e1f1ec; }
.fc-connection::before { content:""; width:7px; height:7px; border-radius:50%; background:#2d9b80; }
.fc-connection.local { color:#7d6646; background:#f6efdf; }
.fc-connection.local::before { background:#af8740; }
.fc-topline { display:flex; justify-content:space-between; align-items:center; gap:12px; color:#7a879b; font-size:.72rem; letter-spacing:.08em; margin:.1rem 0 1.65rem; }
.fc-topline strong { color:#536780; font-weight:600; }
.fc-page-heading { margin-bottom:1.6rem; }
.fc-eyebrow { font-size:.69rem; font-weight:700; letter-spacing:.15em; color:var(--fc-teal); text-transform:uppercase; margin-bottom:.55rem; }
.fc-page-heading h1 { font-size:2.05rem; line-height:1.2; margin:0 0 .55rem; padding:0; font-weight:700; }
.fc-page-heading p { color:var(--fc-muted); margin:0; font-size:.96rem; max-width:760px; line-height:1.65; }
.fc-chat-hero { background:linear-gradient(115deg,#e9efff 0%,#f3f2ff 53%,#e5f4f2 100%); border:1px solid #e0e7f4; border-radius:22px; padding:2.1rem 2.2rem 1.7rem; margin-bottom:1.4rem; }
.fc-chat-hero h1 { font-size:2.3rem; line-height:1.18; margin:0 0 .8rem; padding:0; font-weight:700; max-width:750px; }
.fc-chat-hero p { color:#596a85; font-size:1rem; line-height:1.7; margin:0; max-width:700px; }
.fc-tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:1.2rem; }
.fc-tags span { background:#ffffffad; color:#4b6288; border:1px solid #ffffff; border-radius:7px; padding:5px 9px; font-size:.72rem; }
.st-key-quick_prompts button { background:#fff; border:1px solid #dfe6f2; border-radius:13px; min-height:67px; justify-content:flex-start; padding:1rem 1.1rem; box-shadow:0 3px 10px #1b355006; }
.st-key-quick_prompts button p { text-align:left; font-weight:600; font-size:.91rem; }
.st-key-quick_prompts button:hover:not(:disabled) { border-color:#97acd9; background:#f8faff; transform:translateY(-1px); }
.st-key-quick_prompts [data-testid="stCaptionContainer"] { padding:0 .15rem .25rem; font-size:.76rem; }
[data-testid="stMetric"] { border:1px solid #e3e9f3; border-radius:15px; background:#fff; padding:1.05rem 1.2rem; box-shadow:0 4px 14px #1c365407; }
[data-testid="stMetricLabel"] { color:#687995; font-size:.83rem; }
[data-testid="stMetricValue"] { color:#244776; font-weight:700; }
[data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; }
[data-testid="stForm"] { background:#ffffffbd; border:1px solid #e0e7f2; border-radius:15px; padding:1.2rem; }
[data-testid="stExpander"] { border-radius:11px; border-color:#e0e7f2; background:#ffffff80; }
[data-testid="stAlert"] { border-radius:11px; }
[data-testid="stChatMessage"] { border:1px solid #e3e9f2; background:#fff; border-radius:16px; padding:1.1rem 1.25rem; margin:.3rem 0 .9rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background:#edf2fc; border-color:#e0e7f6; }
[data-testid="stChatMessageAvatarAssistant"] { background:#e3f2ef; color:#087f8c; }
[data-testid="stBottom"] > div { background:linear-gradient(0deg,#f5f7fc 75%,#f5f7fc00); padding-top:.7rem; }
[data-testid="stChatInput"] { border:1px solid #cdd9ed; border-radius:16px; background:#fff; box-shadow:0 8px 24px #203c6410; }
[data-testid="stChatInput"]:focus-within { border-color:#3357b8; box-shadow:0 0 0 3px #3357b812; }
.stButton button, .stFormSubmitButton button { border-radius:9px; }
@media(max-width:700px) {
 .stMainBlockContainer { padding:3.6rem 1rem 5rem; }
 .fc-chat-hero { padding:1.4rem; border-radius:16px; }
 .fc-chat-hero h1 { font-size:1.8rem; }
 .fc-page-heading h1 { font-size:1.7rem; }
 .fc-topline { font-size:.65rem; flex-wrap:wrap; }
}
@media(max-height:800px) {
 .fc-chat-hero { padding:1.35rem 1.6rem 1.2rem; margin-bottom:.9rem; }
 .fc-chat-hero h1 { font-size:2rem; margin-bottom:.5rem; }
 .fc-chat-hero p { font-size:.9rem; line-height:1.5; }
 .fc-tags { display:none; }
 .fc-topline { margin-bottom:1rem; }
 .st-key-quick_prompts button { min-height:56px; padding:.7rem 1rem; }
 .st-key-quick_prompts [data-testid="stCaptionContainer"] { display:none; }
}
</style>
"""


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_navigation(today, online):
    with st.sidebar:
        with st.container(key="brand_panel"):
            if LOGO.is_file():
                image = base64.b64encode(LOGO.read_bytes()).decode("ascii")
                st.markdown(
                    '<div class="fc-logo-window">'
                    f'<img src="data:image/png;base64,{image}" alt="Factory Co-pilot" /></div>'
                    '<p class="fc-brand-caption">Manufacturing intelligence</p>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("### Factory Co-pilot")
        st.markdown('<div class="fc-nav-label">YOUR WORKSPACE</div>', unsafe_allow_html=True)
        page = st.radio("Workspace", PAGES, label_visibility="collapsed", key="workspace_page")
        st.divider()
        badge = "Online Q&A enabled" if online else "Local mode"
        st.markdown(f'<div class="fc-connection {"" if online else "local"}">{badge}</div>', unsafe_allow_html=True)
        st.caption(f"{MODEL_LABEL} · Human-reviewed actions")
        with st.expander("Data & connection"):
            st.caption(f"Simulation date: {today.isoformat()}")
            st.caption("Factory working days: Monday–Saturday.")
            st.caption("The simulation date advances daily. Production records are not generated automatically.")
            st.caption("Local tools remain available when online Q&A is disabled.")
    return page


def workspace_topline(page, today):
    st.markdown(
        '<div class="fc-topline"><span>FACTORY WORKSPACE / '
        f'<strong>{escape(page.upper())}</strong></span><span>REFERENCE DATE {today.isoformat()}</span></div>',
        unsafe_allow_html=True,
    )


def page_heading(title, description, eyebrow="Factory workspace"):
    st.markdown(
        f'<section class="fc-page-heading"><div class="fc-eyebrow">{escape(eyebrow)}</div>'
        f'<h1>{escape(title)}</h1><p>{escape(description)}</p></section>',
        unsafe_allow_html=True,
    )


def chat_welcome():
    st.markdown(
        '<section class="fc-chat-hero"><div class="fc-eyebrow">YOUR FACTORY CO-PILOT</div>'
        '<h1>Your factory, in focus.</h1>'
        '<p>Understand delivery risks, explore production and plan your next move. '
        'Ask in plain language, then inspect the evidence before you decide.</p>'
        '<div class="fc-tags"><span>Fresh source evidence</span><span>Python calculations</span>'
        '<span>You approve every action</span></div></section>',
        unsafe_allow_html=True,
    )

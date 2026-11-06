"""Visual system for the dashboard: CSS, a Plotly theme, and small HTML components.

Design notes
- Dark, restrained, editorial: near-black background, one amber accent, hairline rules
  instead of boxes, small uppercase monospace labels, large numerals.
- Media are public-domain U.S. government works (see static/credits.json), served from
  ./static by Streamlit's static file serving.
- Fonts: Inter and JetBrains Mono (SIL Open Font License) from Google Fonts.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

STATIC = "app/static"          # URL prefix for files in ./static
ROOT = Path(__file__).resolve().parent.parent

BG, PANEL, LINE = "#07090C", "#0E1217", "rgba(255,255,255,0.08)"
TEXT, MUTED, ACCENT, BLUE = "#E9ECEF", "#8B939C", "#F0B44C", "#6EA8FE"
COLORWAY = [ACCENT, BLUE, "#D8DDE3", "#4FB39A", "#E5675F", "#A88BEB", "#7C8794", "#F2D49B"]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root {{ --bg:{BG}; --panel:{PANEL}; --line:{LINE}; --text:{TEXT}; --muted:{MUTED}; --accent:{ACCENT}; --blue:{BLUE};
        --mono:'JetBrains Mono', ui-monospace, monospace; --sans:'Inter', system-ui, sans-serif; }}
html, body, .stApp, [data-testid="stAppViewContainer"] {{ background:var(--bg); color:var(--text); font-family:var(--sans); }}
.stApp p, .stApp li, .stApp label {{ font-family:var(--sans); }}
header[data-testid="stHeader"] {{ background:transparent !important; }}
.stAppDeployButton, [data-testid="stDecoration"], footer {{ display:none !important; }}
.block-container {{ padding:0 3rem 4rem 3rem !important; max-width:1480px; }}
h1, h2, h3 {{ font-family:var(--sans) !important; letter-spacing:-0.02em; color:var(--text) !important; }}
h2 {{ font-weight:600 !important; }} h3 {{ font-weight:500 !important; font-size:1.15rem !important; }}
code {{ font-family:var(--mono) !important; color:var(--accent) !important; background:rgba(240,180,76,.08) !important; }}
a {{ color:var(--text) !important; text-decoration:underline; text-decoration-color:rgba(255,255,255,.3); }}

/* sidebar */
[data-testid="stSidebar"] {{ background:var(--panel); border-right:1px solid var(--line); }}
[data-testid="stSidebar"] .sb-title {{ font-family:var(--mono); font-size:11px; letter-spacing:.18em; text-transform:uppercase;
        color:var(--muted); margin:.4rem 0 1rem; }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ border:none; border-top:1px solid var(--line); border-radius:0; }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {{ font-family:var(--mono); font-size:12px; letter-spacing:.12em;
        text-transform:uppercase; color:var(--text); }}
[data-testid="stSidebar"] label p {{ font-size:13px !important; color:#C3C8CE !important; }}

/* tabs (Streamlit 1.5x+ react-aria markup) */
.stTabs [role="tablist"] {{ gap:2.2rem; border-bottom:1px solid var(--line); }}
.stTabs [data-testid="stTab"] {{ background:transparent; padding:.95rem 0; }}
.stTabs [data-testid="stTab"] p {{ font-family:var(--mono) !important; font-size:11.5px !important; letter-spacing:.14em;
        text-transform:uppercase; color:var(--muted); }}
.stTabs [data-testid="stTab"][aria-selected="true"] p, .stTabs [data-testid="stTab"]:hover p {{ color:var(--text) !important; }}
.stTabs .react-aria-SelectionIndicator {{ background:var(--accent) !important; height:2px !important; }}

/* buttons, inputs */
.stButton button {{ background:transparent; border:1px solid rgba(255,255,255,.35); border-radius:0; color:var(--text);
        font-family:var(--mono); text-transform:uppercase; letter-spacing:.14em; font-size:12px; padding:.6rem 1.2rem; }}
.stButton button:hover {{ border-color:var(--accent); color:var(--accent); }}
[data-testid="stExpander"] details {{ border:1px solid var(--line); border-radius:0; background:transparent; }}
[data-testid="stDataFrame"] {{ border:1px solid var(--line); }}
[data-testid="stAlert"] {{ border-radius:0; }}

/* hero */
.hero {{ position:relative; margin:0 -3rem 0 -3rem; height:min(78vh, 720px); min-height:520px; overflow:hidden; background:#000; }}
.hero video, .hero img.poster {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; filter:saturate(.7) contrast(1.05); }}
.hero .shade {{ position:absolute; inset:0; background:
        linear-gradient(90deg, rgba(7,9,12,.92) 0%, rgba(7,9,12,.65) 42%, rgba(7,9,12,.15) 75%),
        linear-gradient(0deg, rgba(7,9,12,1) 0%, rgba(7,9,12,0) 35%); }}
.hero .content {{ position:absolute; left:3rem; right:3rem; bottom:3.2rem; max-width:1060px; }}
.hero .content h1 {{ max-width:900px; }}
.eyebrow {{ font-family:var(--mono); font-size:11px; letter-spacing:.22em; text-transform:uppercase; color:var(--accent); }}
.hero h1 {{ font-size:clamp(2.4rem, 5vw, 4.6rem) !important; line-height:1.02; font-weight:600 !important; margin:.9rem 0 1rem;
        letter-spacing:-0.035em; padding:0 !important; }}
.hero p.lede {{ font-size:1.12rem; color:#C3C8CE; max-width:640px; line-height:1.55; font-weight:300; }}
.hero .stats {{ display:flex; gap:2.6rem; margin-top:2.2rem; flex-wrap:wrap; border-top:1px solid rgba(255,255,255,.18); padding-top:1.2rem; }}
.stat .v {{ font-family:var(--mono); font-size:2rem; color:var(--text); font-weight:500; letter-spacing:-0.02em; }}
.stat .l {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); margin-top:.2rem; }}
.hero .hint {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--accent);
        margin-top:1.4rem; opacity:.85; }}
.media-credit {{ position:absolute; right:1.2rem; bottom:.8rem; font-family:var(--mono); font-size:9.5px; letter-spacing:.08em;
        color:rgba(255,255,255,.45); text-transform:uppercase; }}

/* sections, bands, cards */
.section {{ margin:3.2rem 0 1.2rem; }}
.section h2 {{ font-size:1.9rem !important; margin:.5rem 0 .4rem; padding:0 !important; }}
.section p {{ color:var(--muted); max-width:760px; font-size:.98rem; line-height:1.55; }}
.band {{ position:relative; height:240px; margin:1.6rem 0 1.4rem; overflow:hidden; border:1px solid var(--line); }}
.band img {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; filter:grayscale(.35) brightness(.75); }}
.band .shade {{ position:absolute; inset:0; background:linear-gradient(90deg, rgba(7,9,12,.95) 0%, rgba(7,9,12,.6) 50%, rgba(7,9,12,.1) 100%); }}
.band .content {{ position:absolute; left:2rem; bottom:1.6rem; max-width:620px; }}
.band h2 {{ font-size:2rem !important; margin:.5rem 0 .3rem; padding:0 !important; }}
.band p {{ color:#C3C8CE; margin:0; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); border-top:1px solid var(--line);
        border-left:1px solid var(--line); margin:1rem 0 .4rem; }}
.kpi {{ padding:1.2rem 1.3rem; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }}
.kpi .l {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); }}
.kpi .v {{ font-family:var(--mono); font-size:1.9rem; margin-top:.5rem; color:var(--text); }}
.kpi .s {{ font-size:12.5px; color:var(--muted); margin-top:.3rem; }}
.kpi.accent .v {{ color:var(--accent); }}
.actions {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:0; border-top:1px solid var(--line);
        border-left:1px solid var(--line); }}
.action {{ padding:1.4rem 1.4rem 1.2rem; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }}
.action .n {{ font-family:var(--mono); font-size:11px; color:var(--accent); letter-spacing:.16em; }}
.action h4 {{ font-size:1.05rem; font-weight:500; margin:.5rem 0 .2rem; color:var(--text); }}
.action .part {{ color:var(--muted); font-size:13px; margin-bottom:1rem; }}
.action .row {{ display:flex; justify-content:space-between; font-family:var(--mono); font-size:12.5px; padding:.35rem 0;
        border-top:1px solid var(--line); color:#C3C8CE; }}
.action .row span:first-child {{ color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-size:10.5px; }}
.deadlines {{ display:flex; gap:0; border:1px solid var(--line); margin:.6rem 0 0; flex-wrap:wrap; }}
.deadline {{ flex:1 1 260px; padding:1.1rem 1.3rem; border-right:1px solid var(--line); }}
.deadline .d {{ font-family:var(--mono); font-size:1.6rem; color:var(--accent); }}
.deadline .t {{ font-size:13.5px; color:var(--text); margin-top:.3rem; }}
.deadline .m {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.12em; color:var(--muted); text-transform:uppercase; margin-top:.4rem; }}
.note {{ border-left:2px solid var(--accent); padding:.5rem 0 .5rem 1rem; color:#C3C8CE; font-size:14px; margin:1rem 0; }}
.footer {{ margin-top:4rem; padding-top:1.4rem; border-top:1px solid var(--line); color:var(--muted); font-size:12px; line-height:1.7; }}
.footer .eyebrow {{ color:var(--muted); }}
@media (max-width: 760px) {{
  .block-container {{ padding:0 1rem 3rem 1rem !important; }}
  .hero {{ margin:0 -1rem; height:auto; min-height:0; }}
  .hero .content {{ position:relative; left:auto; right:auto; bottom:auto; padding:5.5rem 1.2rem 1.6rem; }}
  .hero .stats {{ display:grid; grid-template-columns:1fr 1fr; gap:1.2rem 1rem; }}
  .stat .v {{ font-size:1.45rem; }}
  .media-credit {{ position:relative; right:auto; bottom:auto; padding:0 1.2rem 1rem; }}
  .band {{ height:200px; }} .band .content {{ left:1.2rem; right:1.2rem; }} .band h2 {{ font-size:1.5rem !important; }}
  .kpis {{ grid-template-columns:1fr 1fr; }} .kpi .v {{ font-size:1.4rem; }}
  .stTabs [role="tablist"] {{ gap:1.2rem; }}
}}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    _plotly_theme()


def _plotly_theme() -> None:
    t = go.layout.Template()
    t.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=COLORWAY,
        font=dict(family="Inter, system-ui, sans-serif", color="#C3C8CE", size=12.5),
        title=dict(font=dict(family="JetBrains Mono, monospace", size=12, color=MUTED), x=0, xanchor="left"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)", zerolinecolor="rgba(255,255,255,0.15)", linecolor=LINE,
                   tickfont=dict(family="JetBrains Mono, monospace", size=11, color=MUTED)),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)", zerolinecolor="rgba(255,255,255,0.15)", linecolor=LINE,
                   tickfont=dict(family="JetBrains Mono, monospace", size=11, color=MUTED)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11.5, color="#C3C8CE"), orientation="h", y=1.08, x=0),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=LINE, font=dict(family="Inter", color=TEXT)),
        margin=dict(l=10, r=10, t=56, b=10),
    )
    pio.templates["ops"] = t
    pio.templates.default = "plotly_dark+ops"


def _e(s) -> str:
    return html.escape(str(s))


def hero(eyebrow: str, title: str, lede: str, stats: list[tuple[str, str]], credit: str, hint: str = "") -> None:
    stat_html = "".join(f'<div class="stat"><div class="v">{_e(v)}</div><div class="l">{_e(l)}</div></div>'
                        for v, l in stats)
    st.markdown(f"""
<section class="hero">
  <img class="poster" src="{STATIC}/hero_poster.jpg" alt="">
  <video autoplay muted loop playsinline preload="auto" poster="{STATIC}/hero_poster.jpg">
    <source src="{STATIC}/hero.mp4" type="video/mp4">
  </video>
  <div class="shade"></div>
  <div class="content">
    <div class="eyebrow">{_e(eyebrow)}</div>
    <h1>{_e(title)}</h1>
    <p class="lede">{_e(lede)}</p>
    <div class="stats">{stat_html}</div>
    {f'<div class="hint">{_e(hint)}</div>' if hint else ''}
  </div>
  <div class="media-credit">{_e(credit)}</div>
</section>""", unsafe_allow_html=True)


def section(eyebrow: str, title: str, text: str = "") -> None:
    st.markdown(f'<div class="section"><div class="eyebrow">{_e(eyebrow)}</div><h2>{_e(title)}</h2>'
                + (f"<p>{_e(text)}</p>" if text else "") + "</div>", unsafe_allow_html=True)


def band(image: str, eyebrow: str, title: str, text: str, credit: str = "") -> None:
    st.markdown(f"""
<div class="band"><img src="{STATIC}/{image}" alt=""><div class="shade"></div>
  <div class="content"><div class="eyebrow">{_e(eyebrow)}</div><h2>{_e(title)}</h2><p>{_e(text)}</p></div>
  <div class="media-credit">{_e(credit)}</div></div>""", unsafe_allow_html=True)


def kpis(items: list[tuple[str, str, str, bool]]) -> None:
    """items: (label, value, sub, accent)"""
    cells = "".join(f'<div class="kpi{" accent" if a else ""}"><div class="l">{_e(l)}</div><div class="v">{_e(v)}</div>'
                    f'<div class="s">{_e(s)}</div></div>' for l, v, s, a in items)
    st.markdown(f'<div class="kpis">{cells}</div>', unsafe_allow_html=True)


def action_cards(cards: list[dict]) -> None:
    """cards: dicts with n, title, part, rows=[(label, value)]"""
    out = []
    for c in cards:
        rows = "".join(f'<div class="row"><span>{_e(a)}</span><span>{_e(b)}</span></div>' for a, b in c["rows"])
        out.append(f'<div class="action"><div class="n">{_e(c["n"])}</div><h4>{_e(c["title"])}</h4>'
                   f'<div class="part">{_e(c["part"])}</div>{rows}</div>')
    st.markdown(f'<div class="actions">{"".join(out)}</div>', unsafe_allow_html=True)


def deadlines(items: list[tuple[str, str, str]]) -> None:
    """items: (big text, title, meta)"""
    cells = "".join(f'<div class="deadline"><div class="d">{_e(d)}</div><div class="t">{_e(t)}</div>'
                    f'<div class="m">{_e(m)}</div></div>' for d, t, m in items)
    st.markdown(f'<div class="deadlines">{cells}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="note">{_e(text)}</div>', unsafe_allow_html=True)


def credits() -> dict:
    p = ROOT / "static" / "credits.json"
    return json.loads(p.read_text()) if p.exists() else {}


def footer() -> None:
    c = credits()
    label = {"hero.mp4": "Hero footage", "assembly_mq9.jpg": "Hangar assembly", "assembly_line_1942.jpg": "1942 assembly line",
             "small_uas.jpg": "Small drone"}
    media = " · ".join(f'<a href="{_e(v["page"])}">{_e(label.get(k.split(" ")[0], k))}</a>: '
                       f'{_e(v["artist"].replace("Video by ", ""))} ({_e(v["license"])})' for k, v in c.items())
    st.markdown(f"""
<div class="footer"><div class="eyebrow">About</div>
Illustrative 45-part bill of materials for a generic small unmanned aircraft. Not based on any real product or company data.
Material shares and policy dates are cited in <a href="https://github.com/scucla/Supply-Chain-Resilience/blob/main/docs/SOURCES.md">SOURCES.md</a>;
outage rates and costs are documented assumptions. <a href="https://github.com/scucla/Supply-Chain-Resilience">Source on GitHub</a> ·
<a href="https://github.com/scucla/Supply-Chain-Resilience/blob/main/docs/MEMO.md">One-page memo</a><br>
<span class="eyebrow">Media</span> U.S. government works in the public domain, via Wikimedia Commons. {media}.
Use does not imply endorsement by the U.S. Department of Defense.</div>""", unsafe_allow_html=True)

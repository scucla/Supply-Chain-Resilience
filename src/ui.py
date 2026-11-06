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

BG, PANEL, LINE = "#F6F5F1", "#FFFFFF", "rgba(15,23,32,0.12)"
TEXT, MUTED, ACCENT, BLUE = "#0F1720", "#5B6672", "#C2410C", "#1F3A5F"
STEEL, GRAY, GREEN = "#6B8CAE", "#A3ACB6", "#2F7D5B"
COLORWAY = [BLUE, ACCENT, STEEL, GREEN, "#B7791F", "#7A5C99", GRAY]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root {{ --bg:{BG}; --panel:{PANEL}; --line:{LINE}; --text:{TEXT}; --muted:{MUTED}; --accent:{ACCENT}; --blue:{BLUE};
        --mono:'JetBrains Mono', ui-monospace, monospace; --sans:'Inter', system-ui, sans-serif; }}
html, body, .stApp, [data-testid="stAppViewContainer"] {{ background:var(--bg); color:var(--text); font-family:var(--sans); }}
.stApp p, .stApp li, .stApp label {{ font-family:var(--sans); }}
header[data-testid="stHeader"] {{ background:transparent !important; }}
.stAppDeployButton, [data-testid="stDecoration"], footer {{ display:none !important; }}
.block-container {{ padding:0 3rem 4rem 3rem !important; max-width:none !important; }}
h1, h2, h3 {{ font-family:var(--sans) !important; letter-spacing:-0.02em; color:var(--text) !important; }}
h2 {{ font-weight:600 !important; }} h3 {{ font-weight:500 !important; font-size:1.15rem !important; }}
code {{ font-family:var(--mono) !important; color:var(--accent) !important; background:rgba(194,65,12,.07) !important; }}
a {{ color:var(--text) !important; text-decoration:underline; text-decoration-color:rgba(15,23,32,.3); }}
.formula {{ margin:.4rem 0 .2rem; }} .formula svg {{ height:auto; max-width:100%; }}

/* sidebar */
[data-testid="stSidebar"] {{ background:var(--panel); border-right:1px solid var(--line); }}
[data-testid="stSidebar"] .sb-title {{ font-family:var(--mono); font-size:11px; letter-spacing:.18em; text-transform:uppercase;
        color:var(--muted); margin:.4rem 0 1rem; }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ border:none; border-top:1px solid var(--line); border-radius:0; }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {{ font-family:var(--mono); font-size:12px; letter-spacing:.12em;
        text-transform:uppercase; color:var(--text); }}
[data-testid="stSidebar"] label p {{ font-size:13px !important; color:#2B3540 !important; }}

/* tabs (Streamlit 1.5x+ react-aria markup) */
.stTabs [role="tablist"] {{ gap:2.2rem; border-bottom:1px solid var(--line); }}
.stTabs [data-testid="stTab"] {{ background:transparent; padding:.95rem 0; }}
.stTabs [data-testid="stTab"] p {{ font-family:var(--mono) !important; font-size:11.5px !important; letter-spacing:.14em;
        text-transform:uppercase; color:var(--muted); }}
.stTabs [data-testid="stTab"][aria-selected="true"] p, .stTabs [data-testid="stTab"]:hover p {{ color:var(--text) !important; }}
.stTabs .react-aria-SelectionIndicator {{ background:var(--accent) !important; height:2px !important; }}

/* buttons, inputs */
.stButton button {{ background:var(--text); border:1px solid var(--text); border-radius:0; color:#fff;
        font-family:var(--mono); text-transform:uppercase; letter-spacing:.14em; font-size:12px; padding:.65rem 1.3rem; }}
.stButton button:hover {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
.stButton button p {{ color:#fff !important; }}
[data-testid="stExpander"] details {{ border:1px solid var(--line); border-radius:0; background:var(--panel); }}
[data-testid="stDataFrame"] {{ border:1px solid var(--line); }}
[data-testid="stAlert"] {{ border-radius:0; }}
[data-testid="stPlotlyChart"] {{ background:var(--panel); border:1px solid var(--line); padding:1rem 1.1rem .4rem; }}

/* hero: light wash over the footage, dark type */
.hero {{ position:relative; margin:0 -3rem 0 -3rem; height:min(76vh, 700px); min-height:520px; overflow:hidden; background:#DDD8CE; }}
.hero video, .hero img.poster {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; filter:saturate(.75); }}
.hero .shade {{ position:absolute; inset:0; background:
        linear-gradient(90deg, rgba(246,245,241,.97) 0%, rgba(246,245,241,.9) 34%, rgba(246,245,241,.35) 62%, rgba(246,245,241,0) 82%),
        linear-gradient(0deg, rgba(246,245,241,1) 0%, rgba(246,245,241,0) 26%); }}
.hero .content {{ position:absolute; left:3rem; right:3rem; bottom:3rem; max-width:1060px; }}
.hero .content h1 {{ max-width:820px; }}
.eyebrow {{ font-family:var(--mono); font-size:11px; letter-spacing:.22em; text-transform:uppercase; color:var(--accent); }}
.hero h1 {{ font-size:clamp(2.4rem, 5vw, 4.4rem) !important; line-height:1.03; font-weight:600 !important; margin:.9rem 0 1rem;
        letter-spacing:-0.035em; padding:0 !important; }}
.hero p.lede {{ font-size:1.12rem; color:#2B3540; max-width:600px; line-height:1.55; }}
.hero .stats {{ display:flex; gap:2.6rem; margin-top:2rem; flex-wrap:wrap; border-top:1px solid rgba(15,23,32,.2); padding-top:1.2rem; }}
.stat .v {{ font-family:var(--mono); font-size:2rem; color:var(--text); font-weight:500; letter-spacing:-0.02em; }}
.stat .l {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); margin-top:.2rem; }}
.hero .hint {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--accent);
        margin-top:1.4rem; }}
.media-credit {{ position:absolute; right:1.2rem; bottom:.8rem; font-family:var(--mono); font-size:9.5px; letter-spacing:.08em;
        color:rgba(15,23,32,.55); text-transform:uppercase; }}
.hero .media-credit {{ color:rgba(255,255,255,.85); text-shadow:0 1px 2px rgba(0,0,0,.4); bottom:auto; top:1rem; }}

/* sections, bands, cards */
.section {{ margin:3.2rem 0 1.1rem; }}
.section h2 {{ font-size:1.85rem !important; margin:.5rem 0 .4rem; padding:0 !important; }}
.section p {{ color:var(--muted); max-width:760px; font-size:.98rem; line-height:1.55; }}
.band {{ position:relative; height:230px; margin:2rem 0 1.4rem; overflow:hidden; border:1px solid var(--line); background:#DDD8CE; }}
.band img {{ position:absolute; right:0; top:0; width:68%; height:100%; object-fit:cover; filter:grayscale(.2); }}
.band .shade {{ position:absolute; inset:0; background:linear-gradient(90deg, {BG} 0%, {BG} 32%, rgba(246,245,241,.75) 46%, rgba(246,245,241,0) 70%); }}
.band .content {{ position:absolute; left:2rem; top:50%; transform:translateY(-50%); max-width:520px; }}
.band h2 {{ font-size:2rem !important; margin:.5rem 0 .4rem; padding:0 !important; }}
.band p {{ color:#2B3540; margin:0; line-height:1.5; }}
.band .media-credit {{ color:rgba(255,255,255,.9); text-shadow:0 1px 2px rgba(0,0,0,.5); }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); border-top:1px solid var(--line);
        border-left:1px solid var(--line); margin:1rem 0 .4rem; background:var(--panel); }}
.kpi {{ padding:1.2rem 1.3rem; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }}
.kpi .l {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); }}
.kpi .v {{ font-family:var(--mono); font-size:1.85rem; margin-top:.5rem; color:var(--text); }}
.kpi .s {{ font-size:12.5px; color:var(--muted); margin-top:.3rem; }}
.kpi.accent .v {{ color:var(--accent); }}
.actions {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(250px, 1fr)); gap:0; border-top:1px solid var(--line);
        border-left:1px solid var(--line); background:var(--panel); }}
.action {{ padding:1.4rem 1.4rem 1.2rem; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }}
.action .n {{ font-family:var(--mono); font-size:11px; color:var(--accent); letter-spacing:.16em; }}
.action h4 {{ font-size:1.05rem; font-weight:600; margin:.5rem 0 .2rem; color:var(--text); }}
.action .part {{ color:var(--muted); font-size:13px; margin-bottom:1rem; }}
.action .row {{ display:flex; justify-content:space-between; font-family:var(--mono); font-size:12.5px; padding:.4rem 0;
        border-top:1px solid var(--line); color:var(--text); }}
.action .row span:first-child {{ color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-size:10.5px; }}
.deadlines {{ display:flex; gap:0; border:1px solid var(--line); margin:.6rem 0 0; flex-wrap:wrap; background:var(--panel); }}
.deadline {{ flex:1 1 260px; padding:1.1rem 1.3rem; border-right:1px solid var(--line); }}
.deadline .d {{ font-family:var(--mono); font-size:1.6rem; color:var(--accent); }}
.deadline .t {{ font-size:13.5px; color:var(--text); margin-top:.3rem; line-height:1.45; }}
.deadline .m {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.12em; color:var(--muted); text-transform:uppercase; margin-top:.5rem; }}
.note {{ border-left:2px solid var(--accent); padding:.6rem 0 .6rem 1rem; color:#2B3540; font-size:14px; margin:1rem 0; background:rgba(194,65,12,.04); }}
.footer {{ margin-top:4rem; padding-top:1.4rem; border-top:1px solid var(--line); color:var(--muted); font-size:12px; line-height:1.7; }}
.footer .eyebrow {{ color:var(--muted); }}
@media (max-width: 760px) {{
  .block-container {{ padding:0 1rem 3rem 1rem !important; }}
  .hero {{ margin:0 -1rem; height:auto; min-height:0; }}
  .hero .shade {{ background:rgba(246,245,241,.86); }}
  .hero .content {{ position:relative; left:auto; right:auto; bottom:auto; padding:5.5rem 1.2rem 1.6rem; }}
  .hero .stats {{ display:grid; grid-template-columns:1fr 1fr; gap:1.2rem 1rem; }}
  .stat .v {{ font-size:1.45rem; }}
  .band {{ height:auto; }} .band img {{ width:100%; opacity:.35; }}
  .band .shade {{ background:rgba(246,245,241,.6); }}
  .band .content {{ position:relative; transform:none; top:auto; left:auto; padding:1.6rem 1.2rem; }}
  .band h2 {{ font-size:1.5rem !important; }}
  .kpis {{ grid-template-columns:1fr 1fr; }} .kpi .v {{ font-size:1.4rem; }}
  .stTabs [role="tablist"] {{ gap:1.2rem; }}
  [data-testid="stPlotlyChart"] {{ padding:.5rem; }}
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
        font=dict(family="Inter, system-ui, sans-serif", color="#2B3540", size=13),
        title=dict(font=dict(family="Inter, system-ui, sans-serif", size=16, color=TEXT), x=0.005, xanchor="left", y=.97),
        xaxis=dict(gridcolor="rgba(15,23,32,0.07)", zerolinecolor="rgba(15,23,32,0.25)", linecolor="rgba(15,23,32,0.25)",
                   showline=True, ticks="outside", tickcolor="rgba(15,23,32,0.25)", ticklen=4,
                   tickfont=dict(family="JetBrains Mono, ui-monospace, monospace", size=11, color=MUTED),
                   title=dict(font=dict(size=12, color=MUTED))),
        yaxis=dict(gridcolor="rgba(15,23,32,0.07)", zerolinecolor="rgba(15,23,32,0.25)", linecolor="rgba(15,23,32,0)",
                   tickfont=dict(family="JetBrains Mono, ui-monospace, monospace", size=11, color=MUTED),
                   title=dict(font=dict(size=12, color=MUTED))),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12, color="#2B3540"), orientation="h", y=1.02, x=0,
                    yanchor="bottom", title=dict(text="")),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="rgba(15,23,32,0.2)", font=dict(family="Inter", color=TEXT, size=12)),
        margin=dict(l=8, r=8, t=64, b=8),
        modebar=dict(bgcolor="rgba(0,0,0,0)", color="rgba(15,23,32,0.35)", activecolor=ACCENT),
    )
    pio.templates["ops"] = t
    pio.templates.default = "plotly_white+ops"


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


@st.cache_data(show_spinner=False)
def _formula_svg(tex: str, size: int = 22) -> str:
    """Typeset a formula with matplotlib's math renderer into an inline SVG string.

    Rendered on the server, so the browser needs no extra script (st.latex lazy-loads one,
    which can fail on Streamlit Cloud after a redeploy).
    """
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with plt.rc_context({"mathtext.fontset": "cm", "svg.fonttype": "path"}):
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${tex}$", fontsize=size, color=TEXT)
        buf = io.StringIO()
        fig.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.find("<svg"):]


def formula(tex: str, size: int = 22) -> None:
    st.markdown(f'<div class="formula">{_formula_svg(tex, size)}</div>', unsafe_allow_html=True)

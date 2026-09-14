"""
recourse_app.py  --  the single-flow public app: the access-to-justice
front door to the retrieval engine.

One input box. One answer, grounded in the law and real judgments.

Thin UI over the free-text engine:
  chat_assistant.answer_question  -> scope check, checked retrieval (BNS/BNSS
                                     + judgments), offence-keyword anchors,
                                     plain-language grounded answer with the
                                     ungrounded-statement guards
  recourse_upload.check_arrest_document -> deterministic compliance check on an
                                     uploaded arrest memo / FIR / remand order
  arrest_safeguard_checklist.evaluate  -> the same check, from a fixed set of
                                     plain yes/no questions, for families with
                                     no document (no LLM in this path at all)

The model never reaches a verdict on the person's case. It only phrases what a
verified corpus of statute and judicial authority says -- it does not supply
the law from memory -- and its answer is screened for anything that corpus
does not support before anyone sees it.
"""

import html as _html
import logging

import streamlit as st

# chat_assistant pulls in the Anthropic SDK + the 38 MB embeddings + main
# (~8-15s on a cold container). recourse_upload -> main is similarly heavy.
# Import both LAZILY -- inside the run block / upload block -- so the
# landing page renders in ~1s and only the first real question pays the
# load cost (once per process). See _answer_question / _upload_fns below.
def _answer_question(*a, **kw):
    from chat_assistant import answer_question
    return answer_question(*a, **kw)


def _upload_fns():
    from recourse_upload import extract_text, check_arrest_document
    return extract_text, check_arrest_document


try:
    import arrest_safeguard_checklist as _asc
except Exception:  # never let an optional feature break the page
    _asc = None

try:
    import petition_draft as _pd
except Exception:
    _pd = None

st.set_page_config(page_title="Recourse — know your rights when it matters most",
                   page_icon="⚖️", layout="centered")


# --- Google Analytics (GA4) -----------------------------------------------
# Streamlit has no <head> hook and strips <script> from st.html(), so gtag
# is injected into the PARENT document from a 0-height component iframe
# (same-origin -> window.parent.document is reachable). The id guard makes
# it idempotent across reruns; the 0-height iframe is hidden by the
# iframe[height="0"] rule already in the stylesheet below.
def _inject_ga():
    import streamlit.components.v1 as _c
    _GA_ID = "G-H8M4V4P2M9"
    _c.html(
        f"""
        <script>
        (function () {{
          try {{
            var d = window.parent.document;
            var h = window.parent.location.hostname;
            if (h === "localhost" || h === "127.0.0.1") return;
            if (d.getElementById("ga4-src")) return;
            var s = d.createElement("script");
            s.id = "ga4-src"; s.async = true;
            s.src = "https://www.googletagmanager.com/gtag/js?id={_GA_ID}";
            d.head.appendChild(s);
            var i = d.createElement("script");
            i.text = "window.dataLayer=window.dataLayer||[];"
                   + "function gtag(){{dataLayer.push(arguments);}}"
                   + "gtag('js', new Date());"
                   + "gtag('config', '{_GA_ID}');";
            d.head.appendChild(i);
          }} catch (e) {{}}
        }})();
        </script>
        """,
        height=0,
    )


try:
    _inject_ga()
except Exception:
    logging.getLogger("recourse_app").exception("GA injection failed")


# The corpus embeddings (~38 MB) + the Anthropic SDK are loaded LAZILY on
# the first real query (inside the "Reading the law…" spinner), NOT at
# page render -- eager warm-up here made every landing-page hit as slow
# as the first query. semantic_retrieval caches the load for the life of
# the process, so only the very first question after a container start
# pays it.


# ==========================================================================
# DESIGN SYSTEM  --  "the steady hand"
#
# The visual language of a well-prepared legal document meeting the warmth
# of someone who has your back. Not a SaaS dashboard, not a government
# portal, not a law-firm brochure.
#
# Colour   ink #1b2b2e / ink-soft #41555a / muted #5e6f70 (>= AA on paper)
#          paper #f6f2e8 · surface #fffdf8 · rule #e5dcc7
#          seal (petrol/teal = "verified, safe") #136a61 / deep #0d534b
#          amber (caution, not alarm) #95541c
# Type     Spectral (display serif — wordmark + heads) · Newsreader
#          (reading serif — the answer and explanations) · IBM Plex Sans
#          (labels, chips, buttons) · IBM Plex Mono (statute excerpts)
# Radius   --r-sm 8 (chips-in, expanders) / --r-md 11 (chips, inputs,
#          buttons) / --r-lg 14 (the answer card)
# Layout   single reading column ~720px on warm ivory; a 3px seal strip
#          at the very top like the band on official stationery; uppercase
#          eyebrow labels; the answer sits in one framed card, its section
#          heads promoted from the engine's bold labels.
# ==========================================================================
st.html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600;700&family=Newsreader:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600;700&family=Newsreader:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root{
  /* ink */
  --ink:#1b2b2e; --ink-soft:#41555a; --muted:#5e6f70;
  /* ground */
  --paper:#f6f2e8; --surface:#fffdf8; --rule:#e5dcc7; --rule-soft:#efe8d6;
  /* seal (primary) */
  --seal:#136a61; --seal-deep:#0d534b; --seal-tint:#e3efec; --seal-line:#bfdcd6;
  /* amber (caution) */
  --amber:#95541c; --amber-tint:#f3e7d4; --amber-line:#e2caa4;
  /* radii + elevation */
  --r-sm:8px; --r-md:11px; --r-lg:14px;
  --lift:0 10px 30px -18px rgba(15,84,77,.30);
  --lift-sm:0 4px 14px -10px rgba(15,84,77,.26);
}

/* hide Streamlit chrome */
#MainMenu, header[data-testid="stHeader"], footer,
[data-testid="stToolbar"], [data-testid="stStatusWidget"],
[data-testid="stDecoration"], .stDeployButton{ display:none !important; }

html, body, [data-testid="stAppViewContainer"], .stApp{ background:var(--paper) !important; }

/* stationery strip */
[data-testid="stAppViewContainer"]::before{
  content:""; position:fixed; inset:0 0 auto 0; height:3px; background:var(--seal); z-index:999;
}

.block-container{ max-width:720px; padding-top:3rem; padding-bottom:5rem; }

/* base type */
.stApp, .stMarkdown, p, li, label, .stTextArea textarea{
  font-family:"Newsreader",Georgia,"Times New Roman",serif;
  color:var(--ink); font-size:1.06rem; line-height:1.62;
}
p{ color:var(--ink-soft); }
::selection{ background:var(--seal-tint); }

h1,h2,h3,h4{
  font-family:"Spectral","Newsreader",Georgia,serif !important;
  color:var(--ink) !important; font-weight:600; letter-spacing:-.012em; text-wrap:balance;
}
h2{ font-size:1.6rem !important; margin:2rem 0 .4rem !important; }
h3{ font-size:1.27rem !important; margin:1.7rem 0 .45rem !important; }
h4{ font-size:1.04rem !important; font-weight:600 !important; margin:1.4rem 0 .35rem !important; }

/* ---------- hero ---------- */
.r-eyebrow{ font-family:"IBM Plex Sans",system-ui,sans-serif; font-size:.71rem; font-weight:600;
  letter-spacing:.17em; text-transform:uppercase; color:var(--seal); margin-bottom:.55rem; }
.r-wordmark{ font-family:"Spectral","Newsreader",Georgia,serif !important; font-weight:600 !important;
  font-size:3.4rem !important; line-height:1.02 !important; color:var(--ink) !important;
  margin:0 !important; letter-spacing:-.021em; font-optical-sizing:auto; }
.r-rule{ border:0; border-top:1px solid var(--rule); margin:2rem 0; }
.r-rule-seal{ border:0; border-top:2px solid var(--seal); width:42px; margin:.85rem 0 1.15rem; }
.r-tag{ font-family:"Newsreader",serif; font-style:italic; font-size:1.36rem; line-height:1.4;
  color:var(--ink-soft); margin:.1rem 0 1.05rem; text-wrap:balance; }
.r-lead{ font-size:1.08rem; line-height:1.6; color:var(--ink-soft); margin:0 0 .45rem; }
.r-lead b{ color:var(--ink); font-weight:600; }
.r-who{ font-family:"IBM Plex Sans",system-ui,sans-serif; font-size:.85rem; color:var(--muted);
  margin:.35rem 0 1.9rem; }

/* ---------- pillars ---------- */
.r-pillars{ display:flex; border:1px solid var(--rule); border-radius:var(--r-md);
  overflow:hidden; margin:1.5rem 0 0; background:var(--surface); }
.r-pillar{ flex:1; padding:.85rem 1rem; border-right:1px solid var(--rule); }
.r-pillar:last-child{ border-right:0; }
.r-pillar b{ font-family:"IBM Plex Sans",sans-serif; font-size:.82rem; font-weight:600;
  color:var(--ink); display:block; margin-bottom:.12rem; }
.r-pillar span{ font-family:"IBM Plex Sans",sans-serif; font-size:.77rem; color:var(--muted); line-height:1.4; }

/* ---------- section label ---------- */
.r-label{ font-family:"IBM Plex Sans",sans-serif; font-size:.71rem; font-weight:600;
  letter-spacing:.15em; text-transform:uppercase; color:var(--seal); margin:2.6rem 0 .7rem; }

/* ---------- starter chips (must out-rank the generic secondary-button rule) ---------- */
[data-testid="stColumn"] div.stButton > button,
[data-testid="column"] div.stButton > button{
  width:100% !important; height:100% !important; white-space:normal !important;
  justify-content:flex-start !important; text-align:left !important;
  background:var(--surface) !important; border:1px solid var(--rule) !important;
  border-radius:var(--r-md) !important; padding:.9rem 1rem !important; color:var(--ink) !important;
  font-family:"IBM Plex Sans",sans-serif !important; font-size:.9rem !important;
  font-weight:500 !important; line-height:1.4 !important; box-shadow:none !important;
  transition:transform .14s ease, box-shadow .14s ease;
}
[data-testid="stColumn"] div.stButton > button p,
[data-testid="column"] div.stButton > button p{
  text-align:left !important; width:100%;
  font-family:"IBM Plex Sans",sans-serif !important; font-size:.9rem !important;
  font-weight:500 !important; color:var(--ink) !important; }
[data-testid="stColumn"] div.stButton > button:hover,
[data-testid="column"] div.stButton > button:hover{
  border-color:var(--seal) !important; transform:translateY(-2px); box-shadow:var(--lift-sm) !important; }
[data-testid="stColumn"] div.stButton > button:focus-visible,
[data-testid="column"] div.stButton > button:focus-visible{
  outline:2px solid var(--seal); outline-offset:2px; }

/* ---------- text area ---------- */
.stTextArea textarea{
  background:var(--surface) !important; border:1px solid var(--rule) !important;
  border-radius:var(--r-md) !important; color:var(--ink) !important;
  font-family:"Newsreader",serif !important; font-size:1.05rem !important;
  line-height:1.55 !important; padding:.95rem 1.05rem !important; }
.stTextArea textarea::placeholder{ color:var(--muted) !important; opacity:1; }
.stTextArea textarea:focus{ border-color:var(--seal) !important;
  box-shadow:0 0 0 3px var(--seal-tint) !important; }

/* ---------- primary action ---------- */
button[kind="primary"], button[kind="primaryFormSubmit"],
[data-testid="stDownloadButton"] button[kind="primary"]{
  background:var(--seal) !important; border:1px solid var(--seal-deep) !important;
  color:#fff !important; font-family:"IBM Plex Sans",sans-serif !important;
  font-weight:600 !important; font-size:.98rem !important; letter-spacing:.01em;
  border-radius:var(--r-md) !important; padding:.62rem 1.5rem !important;
  width:100%; margin-top:1rem; box-shadow:var(--lift-sm);
  transition:background .14s ease, box-shadow .14s ease, transform .14s ease; }
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
[data-testid="stDownloadButton"] button[kind="primary"]:hover{
  background:var(--seal-deep) !important; box-shadow:var(--lift); transform:translateY(-1px); }
button[kind="primary"]:focus-visible, button[kind="primaryFormSubmit"]:focus-visible,
[data-testid="stDownloadButton"] button[kind="primary"]:focus-visible{
  outline:2px solid var(--seal-deep); outline-offset:2px; }
button[kind="primary"] p, button[kind="primaryFormSubmit"] p,
[data-testid="stDownloadButton"] button[kind="primary"] p{
  color:#fff !important; font-size:.98rem !important; font-weight:600 !important; }
[data-testid="stForm"]{ border:0 !important; padding:0 !important; }

div.stButton > button[kind="secondary"]{
  background:transparent; border:1px solid var(--seal); color:var(--seal);
  font-family:"IBM Plex Sans",sans-serif; font-weight:500; border-radius:var(--r-sm);
  padding:.5rem 1rem; }
div.stButton > button[kind="secondary"]:hover{ background:var(--seal-tint); }

/* disabled (while an answer is loading) */
button:disabled, button[disabled]{ cursor:not-allowed !important; }
button[kind="primary"]:disabled, button[kind="primaryFormSubmit"]:disabled{
  opacity:.6 !important; box-shadow:none !important; transform:none !important; }
[data-testid="stColumn"] div.stButton > button:disabled{
  opacity:.5 !important; transform:none !important; box-shadow:none !important; }
.stTextArea textarea:disabled{ opacity:.65 !important; -webkit-text-fill-color:var(--ink-soft) !important; }

/* "reading the law" state */
.r-working{
  display:flex; align-items:center; gap:.65rem;
  font-family:"IBM Plex Sans",sans-serif; font-size:.92rem; color:var(--ink-soft);
  padding:.95rem 1.1rem; border:1px solid var(--rule); border-radius:var(--r-md);
  background:var(--surface); margin:.3rem 0; box-shadow:var(--lift-sm);
}
.r-working-dot{
  width:.78rem; height:.78rem; border-radius:50%; flex:none;
  border:2px solid var(--seal-line); border-top-color:var(--seal);
  animation:r-spin .75s linear infinite;
}
@keyframes r-spin{ to{ transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce){ .r-working-dot{ animation:none; border-top-color:var(--seal-line); } }

/* the 0-height scroll-nudge component -- keep it out of the layout */
[data-testid="stElementContainer"]:has(iframe[height="0"]){ display:none !important; }

/* ---------- the answer, framed ---------- */
/* st.container(border=True) is a [data-testid="stVerticalBlock"] carrying
   Streamlit's own 1px border; a hidden marker span picks out ours. */
.r-ansmark{ display:none; }
[data-testid="stElementContainer"]:has(.r-ansmark){ display:none; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark){
  background:var(--surface) !important; border:1px solid var(--rule) !important;
  border-radius:var(--r-lg) !important; box-shadow:var(--lift) !important;
  padding:1.35rem 1.55rem !important; gap:0 !important;
}
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown p,
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown li{
  color:var(--ink-soft); }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown p{
  margin:0 0 .8rem; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown strong{
  color:var(--ink); font-weight:600; }
/* a standalone bold label -> a real sub-head */
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown p:has(> strong:only-child){
  font-family:"IBM Plex Sans",sans-serif !important; font-size:.72rem !important; font-weight:600 !important;
  letter-spacing:.13em; text-transform:uppercase; color:var(--seal) !important; margin:1.55rem 0 .5rem !important; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown p:has(> strong:only-child) strong{
  color:var(--seal) !important; font-weight:600 !important; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) [data-testid="stElementContainer"]:nth-child(2){ margin-top:0; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown ol,
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown ul{
  margin:.15rem 0 .95rem; padding-left:1.4rem; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown li{
  margin:.32rem 0; padding-left:.15rem; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown li::marker{
  color:var(--seal); font-weight:600; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark) .stMarkdown blockquote{
  border-left:2px solid var(--seal-line); margin:.4rem 0; padding:.1rem 0 .1rem .9rem; color:var(--ink-soft); }

.r-conf{ font-family:"IBM Plex Sans",sans-serif; font-size:.82rem; color:var(--muted);
  letter-spacing:.01em; margin:.1rem 0 .5rem; }

/* ---------- monospace excerpts ---------- */
.r-mono{ font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
  font-size:.8rem; line-height:1.55; white-space:pre-wrap; color:var(--ink-soft); }
.r-src{ font-family:"IBM Plex Sans",sans-serif; font-size:.79rem; color:var(--muted); }

/* ---------- expanders ---------- */
[data-testid="stExpander"]{ border:1px solid var(--rule) !important; border-radius:var(--r-sm) !important;
  background:var(--surface) !important; margin:.4rem 0 !important; }
[data-testid="stExpander"] summary{ font-family:"IBM Plex Sans",sans-serif !important;
  font-size:.85rem !important; font-weight:500 !important; color:var(--ink-soft) !important;
  padding:.72rem .95rem !important; }
[data-testid="stExpander"] summary:hover{ color:var(--seal) !important; }

/* ---------- draft-petition call-to-action ---------- */
.r-cta{ font-family:"IBM Plex Sans",sans-serif; display:flex; gap:.6rem; align-items:flex-start;
  background:var(--seal-tint); border:1px solid var(--seal-line); border-left:3px solid var(--seal);
  border-radius:var(--r-sm); padding:.85rem 1rem; margin:1.1rem 0 .1rem; color:var(--ink);
  font-size:.9rem; line-height:1.5; }
.r-cta b{ color:var(--seal-deep); }
.r-cta .r-cta-ico{ font-size:1.05rem; line-height:1.3; flex:0 0 auto; }

/* ---------- compliance / checklist ---------- */
.r-checkrow{ border:1px solid var(--rule); border-radius:var(--r-md); background:var(--surface);
  padding:.85rem 1.05rem; margin:.55rem 0; }
.r-checkrow .r-chead{ font-family:"Newsreader",serif; font-weight:600; font-size:1rem;
  color:var(--ink); line-height:1.45; }
.r-verdict{ display:inline-block; font-family:"IBM Plex Sans",sans-serif; font-size:.72rem;
  font-weight:600; letter-spacing:.03em; text-transform:uppercase; padding:.16rem .55rem;
  border-radius:999px; margin:.4rem 0 .3rem; }
.r-verdict.ok{ background:var(--seal-tint); color:var(--seal-deep); }
.r-verdict.bad{ background:var(--amber-tint); color:var(--amber); }
.r-verdict.warn{ background:#f0e7d5; color:#7a6636; }
.r-verdict.unknown{ background:#eae5d7; color:#6a6250; }
.r-verdict.na{ background:#edece2; color:#87847a; }
.r-checkrow .r-cexp{ font-family:"Newsreader",serif; font-size:.94rem; color:var(--ink-soft); line-height:1.5; }
.r-summ{ border:1px solid var(--seal-line); border-left:3px solid var(--seal); background:var(--seal-tint);
  padding:.85rem 1.05rem; border-radius:var(--r-sm); margin:.7rem 0 .9rem;
  font-family:"Newsreader",serif; color:var(--ink); line-height:1.55; }
.r-summ.hasdefect{ border-color:var(--amber-line); border-left-color:var(--amber); background:var(--amber-tint); }
.r-concord{ font-family:"IBM Plex Sans",sans-serif; font-size:.85rem; color:var(--ink-soft);
  border:1px solid var(--rule); border-radius:var(--r-sm); padding:.7rem .9rem; margin:.55rem 0;
  background:var(--surface); line-height:1.5; }
.r-concord code{ font-family:"IBM Plex Mono",monospace; font-size:.8rem;
  background:var(--seal-tint); color:var(--seal-deep); padding:.05rem .3rem; border-radius:4px; }

/* ---------- out of scope ---------- */
.r-oos{ border:1px solid var(--rule); border-left:3px solid var(--amber); background:var(--surface);
  border-radius:var(--r-sm); padding:1rem 1.2rem; margin:.6rem 0; line-height:1.55; }

/* ---------- footer ---------- */
.r-foot{ font-family:"IBM Plex Sans",sans-serif; font-size:.82rem; color:var(--muted); line-height:1.55; }
a, a:visited{ color:var(--seal); text-underline-offset:2px; }

/* ---------- responsive ---------- */
@media (max-width:640px){
  .block-container{ padding-left:1.1rem; padding-right:1.1rem; padding-top:2.2rem; }
  .r-wordmark{ font-size:2.5rem !important; }
  .r-tag{ font-size:1.2rem; }
  .r-lead{ font-size:1.04rem; }
  .r-pillars{ flex-direction:column; }
  .r-pillar{ border-right:0; border-bottom:1px solid var(--rule); }
  .r-pillar:last-child{ border-bottom:0; }
  [data-testid="stHorizontalBlock"]{ flex-wrap:wrap; gap:.5rem !important; }
  [data-testid="stColumn"]{ width:100% !important; flex:1 1 100% !important; }
  [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .r-ansmark){
    padding:1.05rem 1.1rem !important; }
}
@media (prefers-reduced-motion:reduce){
  *, *::before, *::after{ transition:none !important; }
  [data-testid="stColumn"] .stButton > button:hover,
  [data-testid="column"] .stButton > button:hover,
  button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover{ transform:none !important; }
}
</style>
""")


def esc(s):
    return _html.escape(str(s or ""))


import re as _re_lbl

# The answer engine writes its section heads as a leading bold label
# ("**Right now**", "**What the law says:**", "**What's unclear:**").
# When they sit inline at the start of a paragraph the reader gets no
# hierarchy. Push a short leading label onto its own line so the answer
# card's CSS renders it as a real sub-head. Only touches lines that
# *begin* with a <= 48-char bold label; body text is untouched. The cap
# MUST match _tame_sentence_bold's below -- see that function's docstring
# for why a gap between the two is a real, confirmed bug, not a nitpick.
#
# The separator after the label is EITHER inline whitespace ("**Label**
# body on the same line") OR a single bare newline ("**Label**\nbody on
# the next line") -- CONFIRMED LIVE 2026-09-11: "**The law on theft:**"
# followed by one \n then a full paragraph of explanation is still ONE
# markdown paragraph (only a BLANK line, \n\n, starts a new one), so
# <strong> was still the paragraph's only element child and the whole
# explanation got capitalised with it. The `(?!\n)` guard skips a
# separator that's already a real blank line (already fine, don't touch).
_LEAD_LABEL = _re_lbl.compile(
    r"(?m)^(\s{0,3})(\*\*[^*\n]{2,48}?\*\*)(:?)(?:[ \t]+|\n(?!\n))(?=\S)")

# A leading bold run at the start of a line (optionally after a "1." /
# "-" list marker) -- i.e. a bolded *sentence* or clause, not a label.
# Deliberately NOT anchored to end-of-line: the answer-card CSS rule is
# `p:has(> strong:only-child)`, and CSS :only-child counts ELEMENT
# siblings only -- a <strong> followed by plain prose in the SAME <p>
# (no other element in that paragraph) still matches it, so the ENTIRE
# paragraph -- the bold clause AND the plain text after it -- gets
# capitalised. CONFIRMED LIVE 2026-09-11: "But safeguards still apply
# fully at this stage." (47 chars, <p><strong>...</strong> more prose
# ...</p>, no other element in that paragraph) rendered as a wall of
# caps on recourse.co.in. An end-of-line-anchored regex can never catch
# this shape -- the bold does not extend to the end of the line, more
# prose follows on the same line. (A neighbouring paragraph with an
# identical shape happened to escape only because it also contained an
# unrelated *italic* word later on, which gives the paragraph a second
# element child and breaks :only-child by luck, not by design -- not a
# fix to rely on.)
_WHOLE_LINE_BOLD = _re_lbl.compile(
    r"(?m)^(\s{0,4}(?:\d{1,2}[.)]\s+|[-*]\s+)?)\*\*([^*\n]+?)\*\*")


def _tame_sentence_bold(md: str) -> str:
    def repl(m):
        prefix, inner = m.group(1), m.group(2)
        if "**" in inner:
            return m.group(0)
        head, sep, tail = inner.partition(":")
        if sep and len(head) <= 48 and tail.strip():
            return f"{prefix}**{head.strip()}:** {tail.strip()}"
        # A genuine label ("Right now", "What the law says") is a short
        # PHRASE with no terminal punctuation. Anything ending in . / ! / ?
        # is a full sentence even when short -- "But safeguards still apply
        # fully at this stage." is 47 characters and would otherwise pass
        # a pure length check, then get pushed onto its own line by
        # _LEAD_LABEL and rendered as a shouted one-line sub-head (the CSS
        # caps ANY paragraph that is just a <strong>, sentence or not).
        # Only true short labels stay bold here; _LEAD_LABEL then promotes
        # them to a real sub-head.
        if len(inner) <= 48 and not inner.rstrip().endswith((".", "!", "?")):
            return m.group(0)                     # a genuine short label -- leave it
        return f"{prefix}{inner}"                 # a sentence -- just drop the bold
    return _WHOLE_LINE_BOLD.sub(repl, md)


def _promote_answer_labels(md: str) -> str:
    if not md:
        return md
    md = _tame_sentence_bold(md)
    return _LEAD_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}\n\n", md)


# --------------------------------------------------------------------------
# hero
# --------------------------------------------------------------------------
st.html("""
<div class="r-eyebrow">Access to justice &nbsp;·&nbsp; India</div>
<div class="r-wordmark">Recourse</div>
<hr class="r-rule-seal">
<div class="r-tag">When it feels like there is none, there is still recourse.</div>
<div class="r-lead">Tell Recourse what is happening, in plain words. In seconds:
the move to make <b>right now</b>, the exact sections that apply, and the real
judgments behind them &mdash; then a <b>draft court petition built from your own
facts</b>, editable on the page and one click from a PDF.</div>
<div class="r-who">For the person a case is happening to, and their family &mdash;
not for law firms. Legal information, not legal advice.</div>

<div class="r-pillars">
  <div class="r-pillar"><b>What to do right now</b><span>concrete first steps</span></div>
  <div class="r-pillar"><b>Traced to the source</b><span>every section and judgment shown</span></div>
  <div class="r-pillar"><b>Yours to download</b><span>an editable draft petition, as a PDF</span></div>
</div>
""")


# --------------------------------------------------------------------------
# starters + input
# --------------------------------------------------------------------------
# Each starter is a real, layered situation chosen to show a distinct
# strength: (1) the tool surfaces a PRECISE, little-known safeguard with
# its governing case and its nuance; (2) it names a statutory RIGHT the
# family has never heard of; (3) it reaches beyond arrest into another
# whole domain. All three carry through to the deterministic checklist
# and the downloadable petition.
EXAMPLES = {
    "My sister was arrested at night":
        "my sister was arrested at night — at about 11 — with no woman police officer "
        "there, and nobody has told us in writing what she is accused of",
    "65 days in jail, no chargesheet":
        "my son has been in judicial custody 65 days in a cheating case, no chargesheet "
        "has been filed, and his bail was already refused once on the merits",
    "The bank froze my account":
        "my current account was frozen by my bank after a police email about a payment I "
        "received from a customer who is under investigation; my whole balance is locked "
        "and no FIR has been served on me",
}

if "text" not in st.session_state:
    st.session_state.text = ""

# true on the rerun that is actually fetching an answer -- used to lock
# the submit + starter buttons and show the "reading the law" state.
_busy = bool(st.session_state.get("_busy"))


def _reset_answer():
    """Drop the previous answer + draft + doc-check so a new question never
    shows a stale reply."""
    for k in ("answer", "answer_msg", "doc", "doc_check", "doc_check_sig", "_sg_result"):
        st.session_state.pop(k, None)


def _scroll_into_view(selector):
    """Nudge the page to the loading / answer region (Streamlit strips
    <script> from st.html/markdown, so this goes through a 0-height
    component iframe, hidden by CSS)."""
    try:
        import streamlit.components.v1 as _c
        _c.html(
            "<script>const d=window.parent.document;"
            f"const t=d.querySelector({selector!r})||d.querySelector('[data-testid=\"stSpinner\"]');"
            "if(t)t.scrollIntoView({behavior:'smooth',block:'center'});</script>",
            height=0)
    except Exception:
        pass


st.html('<div class="r-label">Start with a situation</div>')
cols = st.columns(len(EXAMPLES))
for c, (label, val) in zip(cols, EXAMPLES.items()):
    if c.button(label, use_container_width=True, key=f"ex_{label[:10]}", disabled=_busy):
        st.session_state.text = val
        _reset_answer()
        st.session_state._autorun = True

st.html('<div class="r-label">&hellip; or describe your own</div>')

# A form so the textarea's current value and the submit click are processed
# TOGETHER in one rerun -- without it, the first click after typing only
# commits the text and the previous answer keeps showing.
with st.form("situation_form", border=False, clear_on_submit=False):
    msg = st.text_area("Describe your situation", key="text", height=120,
                       label_visibility="collapsed", disabled=_busy,
                       placeholder="e.g. My brother was arrested four days ago and still hasn't been produced in court…") or ""
    go = st.form_submit_button(
        "Reading…" if _busy else "Check my situation  →",
        type="primary", use_container_width=True, disabled=_busy)


# --------------------------------------------------------------------------
# footer: how it works + about + disclaimer  (shown on every view)
# --------------------------------------------------------------------------
def _footer():
    st.html('<hr class="r-rule">')

    with st.expander("How Recourse works — and why it won't invent a case"):
        st.markdown(
            "- **You write what happened, in your own words.** No forms, no legal terms. "
            "Recourse reads it the way a person would.\n"
            "- **The law is not the model's to give.** Every provision and every judgment "
            "in an answer is drawn from a curated, verified corpus of Indian criminal law "
            "and the rulings that have construed it. The language model's role is narrow — "
            "it locates the passages that fit your facts and renders them in plain words. "
            "It does not carry the law in its head, and it does not decide.\n"
            "- **The exact offence is pinned, not guessed.** Name an accusation in "
            "ordinary words — theft, cheating, hurt, forgery, a bounced cheque, a frozen "
            "account — and Recourse anchors it to the precise section, so the answer "
            "cites the provision that actually bites.\n"
            "- **Every answer is checked before it reaches you.** A section it never "
            "retrieved, a wrong cognisable/bailable claim, a judgment pushed past what it "
            "holds — each is caught and stripped out. What survives is only what the "
            "corpus supports.\n"
            "- **It carries the old codes forward.** A judgment written under the IPC or "
            "the CrPC still speaks — Recourse maps each old section to its BNS/BNSS "
            "successor from a curated concordance, and flags the rare provision that was "
            "repealed outright, so every citation you get is in today's numbering.\n"
            "- **It hands you something you can act on.** Where an arrest, a cheque case "
            "or a frozen account is involved, Recourse assembles a **draft court petition "
            "from your own facts** — the grounds, the sections, the judgments, set out in "
            "a court's own format. Edit it right there on the page, download it as a "
            "**PDF**, and walk it into a lawyer's office or a courtroom. Fixed rules build "
            "it; not a line of it is invented.\n"
            "- **It tells you what it genuinely cannot settle.** A judgment whose standing "
            "is unsettled — a larger bench pending, the High Courts split — or a matter "
            "that falls outside its reach: Recourse says so, rather than filling the gap "
            "with a guess.\n"
            "- **What it reaches today.** Arrest, FIR, police procedure and bail under the "
            "BNS and BNSS; cheque-dishonour cases under Section 138; the freezing of a "
            "bank account; and the impersonation and identity offences of the Information "
            "Technology Act. The map is being widened — other major Acts are next, and "
            "that work does not stop.\n"
            "- **The model never reaches a verdict on your case.** It lays out what the "
            "law requires and what the courts have said. What that means for *you* is a "
            "question for a lawyer — and Recourse says so, every time."
        )

    with st.expander("About Recourse"):
        st.markdown(
            "**Who it is for.** The person a criminal case is happening to, and the "
            "family standing beside them — at the moment it is happening. Not law firms.\n\n"
            "**Why it exists.** More than three in four people in India's prisons are "
            "undertrials — not convicted of anything. When the police arrive, almost "
            "nobody in the room knows that an arrest must carry written grounds, that a "
            "woman ordinarily cannot be taken away after sunset, or that a missed "
            "chargesheet deadline turns bail into a right. Rights that exist on paper are "
            "lost in the first twenty-four hours, for want of anyone who knows them. "
            "Recourse puts that knowledge in the room.\n\n"
            "**What it does.** You describe the situation in plain words. Recourse returns "
            "what you can do **right now**, the **exact provisions** in play, what the "
            "**real judgments** hold, and — where an arrest has happened — a check of the "
            "actual papers against the safeguards, and a **draft you can take to a lawyer "
            "or a court**.\n\n"
            "**What it is not.** Not legal advice. It sees only what you type. It is "
            "orientation and a first foothold — the next step is always a lawyer, and "
            "your nearest **District Legal Services Authority** provides one free.\n\n"
            "**How it is built.** The core — checked retrieval, the old-code-to-new-code "
            "mapping, the offence anchors, and the hard rule that the model never returns "
            "a verdict — has been built and stress-tested over many months. The layer "
            "that makes it usable by a frightened family in the first hour is where the "
            "work now lives, and where it keeps going. Recourse is an ongoing project "
            "with a long way still to run."
        )

    st.markdown(
        '<p class="r-foot">Recourse gives legal information, not legal advice. It cannot '
        'see anything beyond what you type. For a real case, take this to a lawyer or your '
        'nearest District Legal Services Authority, which provides that help free.</p>',
        unsafe_allow_html=True)


# --------------------------------------------------------------------------
# render the grounded answer + its sources
# --------------------------------------------------------------------------
import re as _re

_PAGE_CRUFT = _re.compile(
    r"^\s*(?:\x0c\s*)?(?:page\s+\d+\s+of\s+\d+|\d{1,4}|\d+\s*\|\s*p\s*a\s*g\s*e)\s*$",
    _re.I,
)


def _clean_excerpt(text: str) -> str:
    """Strip the OCR/print cruft that rides along in the judgment chunk
    text -- form-feeds, bare page numbers, 'Page 8 of 25' footers, and
    long runs of blank lines -- so the 'Read the source' excerpt reads
    like prose, not a scanned PDF. Display-only; the stored chunk text is
    untouched."""
    if not text:
        return ""
    text = _html.unescape(text)                          # &amp; / &nbsp; from scraped chunks
    out = []
    for line in text.replace("\x0c", "\n").split("\n"):
        line = _re.sub(r"</?[a-zA-Z][^>]*>", "", line)    # stray HTML tags (</div>, <br>)
        line = _re.sub(r"^\s+", "", line.rstrip())        # PDF column indent -> flush left
        line = _re.sub(r"\s{2,}", " ", line)              # collapse wide inter-word gaps
        if _PAGE_CRUFT.match(line):
            continue
        out.append(line)
    cleaned = "\n".join(out)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_CASE_GENERIC_PARTY = (
    "state of", "state ", "union of india", "union of", "govt", "government",
    "central bureau of investigation", "cbi", "directorate of", "intelligence officer",
    "commissioner of", "n.c.t", "nct", "u.p.", "govt. of", "republic of",
)


def _case_is_named(m, reply_lc):
    """True if the answer prose actually refers to this case by name.
    Checks the distinctive party -- usually the first ('M. Ravindran',
    'D.K. Basu'), but the SECOND when the first is a generic 'State of X'
    / 'Union of India' ('State of Haryana v Bhajan Lal' -> 'Bhajan
    Lal')."""
    cn = (m.get("case_name") or "").lower()
    if not cn:
        return False
    parts = [p.strip() for p in cn.split(" v ") if p.strip()]
    for p in parts:
        if any(p.startswith(g) for g in _CASE_GENERIC_PARTY):
            continue
        # trim a trailing "(2026)" / ", directorate of revenue intelligence"
        core = p.split("(")[0].split(",")[0].strip()
        if len(core) >= 4 and core in reply_lc:
            return True
    return False


def _sources_worth_showing(matches, reply_text, cap=16):
    """The 'Read the source' JUDGMENT list.

    If the answer NAMES any case, show ONLY those -- every case it names
    (grounding: the prompt forbids naming a case with no excerpt) and
    nothing else. The keyword doctrine anchors deliberately over-fire
    (every "arrested" pulls Prabir/Arnesh/Satender); when the model then
    builds the answer around just the 1-3 on point, "Read the source"
    must mirror that choice, not dump the five unused anchors next to it
    -- confirmed 2026-09-08 live test (a default-bail answer showed
    Prabir, Arnesh, Satender, Md. Ibrahim and Sri Manjunath, none of
    which the answer used).

    Only when the answer names NO case at all (rare) fall back to the
    curated anchors, then the rest by score.

    CALLER PASSES JUDGMENT MATCHES ONLY -- curated statute-override
    entries (case_name=None) used to eat cap slots here."""
    reply_lc = (reply_text or "").lower()

    def _label(m):
        return str(m.get("section_number") or m.get("paragraph_number") or "")

    pool = matches or []
    named = [m for m in pool if _case_is_named(m, reply_lc)]
    if named:
        pool = named
    else:
        # nothing named -> curated anchors first, then score order
        pool = sorted(
            pool,
            key=lambda m: 0 if str(m.get("source") or "").startswith("curated") else 1,
        )

    picked, seen = [], set()
    for m in pool:
        key = (m.get("case_name") or "BNS/BNSS", _label(m))
        if key in seen:
            continue
        seen.add(key)
        picked.append(m)
        if len(picked) >= cap:
            break
    return picked


def _render_currency_caveat(m):
    """If a cited judgment carries a legal-currency note (Project 2), show it."""
    if not m.get("case_name"):
        return
    try:
        from citation_currency import get_citation_currency_for_case_name
        for rec in get_citation_currency_for_case_name(m["case_name"]):
            note = rec.get("plain_note") or rec.get("note") or rec.get("summary")
            if note:
                st.markdown(f'<div class="r-concord">{esc(note)}</div>', unsafe_allow_html=True)
    except Exception:
        pass


def render_answer(result: dict):
    """Render one chat_assistant.answer_question() result in the Recourse
    style. Every branch is honest: a real grounded answer, an out-of-scope
    note, or a technical-trouble note -- never a silent guess."""
    state = result.get("state")

    if state in ("single_match", "conflicting_matches"):
        st.markdown('<div class="r-label">Your situation</div>', unsafe_allow_html=True)
        if state == "conflicting_matches":
            st.markdown('<p class="r-conf">More than one provision applies and they don\'t '
                        'all say the same thing &mdash; Recourse lays out each rather than '
                        'picking one for you.</p>', unsafe_allow_html=True)
        reply = result.get("response_text") or ""
        with st.container(border=True):
            st.markdown('<span class="r-ansmark"></span>', unsafe_allow_html=True)
            if reply:
                st.markdown(_promote_answer_labels(reply))
            else:
                m0 = (result.get("matches") or [{}])[0]
                st.markdown("Here is what the law says on this:\n\n> "
                            + esc((m0.get("text") or "").strip()[:800]))

        reply_lc = (reply or "").lower()
        all_matches = result.get("matches") or []

        def _statute_referenced(m):
            # keep a statute only if it's a hand-anchored override or the
            # answer actually cites it -- drops semantic-search noise like
            # BNS 84 turning up next to an unrelated arrest question.
            if str(m.get("source") or "").startswith("curated"):
                return True
            sn = str(m.get("section_number") or "")
            return bool(sn) and (f"section {sn}".lower() in reply_lc
                                 or f"section {sn.split('(')[0]}".lower() in reply_lc)

        # statutes: every relevant one, no fill-cap (there are rarely > 6)
        statutes, seen_s = [], set()
        for m in all_matches:
            if not m.get("section_number") or m.get("case_name"):
                continue
            if not _statute_referenced(m):
                continue
            k = (m.get("act"), m.get("section_number"))
            if k in seen_s:
                continue
            seen_s.add(k)
            statutes.append(m)

        # judgments: the anchored + answer-named ones, capped for length.
        # Pass judgment matches ONLY -- see _sources_worth_showing docstring.
        judgments = _sources_worth_showing(
            [m for m in all_matches if m.get("case_name")], reply)

        # group judgment paragraphs under ONE heading per case
        by_case, order = {}, []
        for m in judgments:
            k = (m.get("case_name"), m.get("citation"))
            if k not in by_case:
                by_case[k] = []
                order.append(k)
            by_case[k].append(m)

        if statutes or judgments:
            with st.expander("Read the source — the sections and judgments this rests on"):
                for m in statutes:
                    st.markdown(f'**{esc(m["act"])} Section {esc(m["section_number"])}**')
                    st.markdown(f'<div class="r-mono">{esc(_clean_excerpt(m.get("text") or "")[:900])}</div>',
                                unsafe_allow_html=True)
                if judgments:
                    st.markdown('<div class="r-label" style="margin-top:1rem">Judgments</div>',
                                unsafe_allow_html=True)
                for k in order:
                    name, cite = k
                    cite_html = (f' &nbsp;·&nbsp; <span class="r-src">{esc(cite)}</span>'
                                 if cite else "")
                    st.markdown(f'**{esc(name)}**{cite_html}', unsafe_allow_html=True)
                    _render_currency_caveat(by_case[k][0])
                    for m in by_case[k]:
                        para_head = str(m.get("paragraph_number") or "").split("_")[0]
                        if para_head.isdigit():
                            st.markdown(f'<span class="r-src">paragraph {esc(para_head)}</span>',
                                        unsafe_allow_html=True)
                        st.markdown(f'<div class="r-mono">{esc(_clean_excerpt(m.get("text") or "")[:1100])}</div>',
                                    unsafe_allow_html=True)

        # The WIDER, honestly UNVERIFIED judgment pool (vaquill_search.py --
        # see its module docstring and memory/vaquill-search-pool.md).
        # Deliberately its OWN expander, separate from "Read the source"
        # above -- never implies the same confidence level.
        unverified = result.get("unverified_related_judgments")
        if unverified:
            with st.expander("Other real court cases that might be relevant (not independently verified)"):
                st.markdown('<p class="r-foot">These came up in a search of a much wider judgment '
                            "database. Nobody at Recourse has read and confirmed them yet &mdash; "
                            'read the real judgment yourself, or with a lawyer, before relying on '
                            'it.</p>', unsafe_allow_html=True)
                for j in unverified:
                    warn = (' &mdash; <span class="r-src">may be a procedural/bail order, not a '
                            'full judgment</span>' if j.get("procedural_disposal") else "")
                    st.markdown(f'- [{esc(j["case_name"])}]({esc(j["ik_search_url"])}){warn}',
                                unsafe_allow_html=True)

        return bool(result.get("situation_detected"))

    # ---- everything below is an honest non-answer ----
    st.markdown('<div class="r-label">Out of scope</div>', unsafe_allow_html=True)

    if state == "covered_elsewhere_in_tool":
        dom = result.get("redirect_domain")
        label = {
            "freeze": "a frozen bank account", "cheque_bounce": "a bounced cheque",
            "domestic_violence": "domestic violence",
        }.get(dom, "this")
        st.markdown("## That's a different kind of matter")
        st.markdown(f'<div class="r-oos">This looks like it is about <b>{esc(label)}</b>. '
                    'Recourse focuses on arrest, FIR, police procedure and bail. For a cheque, '
                    'bank-freeze, or domestic violence matter, take the notice, letter, or details '
                    'to a lawyer or your nearest District Legal Services Authority.</div>', unsafe_allow_html=True)
    elif state == "adjacent_uncovered":
        st.markdown("## Recourse can't help with this one")
        reason = result.get("reasoning") or ""
        st.markdown(f'<div class="r-oos">This looks like a real legal question, but it is '
                    'outside what Recourse checks &mdash; it covers police arrests, FIRs, '
                    'criminal procedure and bail under the BNS and BNSS. '
                    + (f'<br><span class="r-src">{esc(reason)}</span>' if reason else "")
                    + '</div>', unsafe_allow_html=True)
        st.markdown('<p class="r-foot">For this kind of question, speak with a lawyer who '
                    'handles that area of law.</p>', unsafe_allow_html=True)
    elif state == "unrelated":
        st.markdown("## That doesn't look like a legal question")
        st.markdown('<div class="r-oos">Recourse is built for police arrests, FIRs and '
                    'criminal procedure under Indian law. Ask about any of those in your '
                    'own words.</div>', unsafe_allow_html=True)
    elif state == "no_match":
        st.markdown("## Not enough to go on yet")
        st.markdown('<div class="r-oos">Recourse looked but could not find anything in the '
                    'law and judgments it holds that clearly matches this. Try adding detail '
                    '&mdash; what happened, and roughly when &mdash; or name the section of '
                    'law if you know it.</div>', unsafe_allow_html=True)
    else:  # classifier_unavailable / retrieval_unavailable / anything unexpected
        st.markdown("## Something isn't working right now")
        st.markdown('<div class="r-oos">This is a technical problem on Recourse\'s side, not '
                    'your question. Try again in a moment.</div>', unsafe_allow_html=True)
    return False


# --------------------------------------------------------------------------
# the "have the papers?" compliance check
# --------------------------------------------------------------------------
def render_doc_check(result: dict):
    if not result.get("ok"):
        st.markdown(f'<p class="r-foot">{esc(result.get("error") or result.get("note") or "Could not read that file.")}</p>',
                    unsafe_allow_html=True)
        return

    if not result.get("is_arrest_document"):
        st.markdown(f'<div class="r-oos">{esc(result.get("note"))}</div>', unsafe_allow_html=True)
        _render_concord(result.get("old_code"))
        return

    cls = "r-summ hasdefect" if result.get("n_defects") else "r-summ"
    st.markdown(f'<div class="{cls}">{esc(result.get("overall"))}</div>', unsafe_allow_html=True)

    for c in result.get("checks", []):
        st.markdown(
            f'<div class="r-checkrow">'
            f'<div class="r-chead">{esc(c["plain"])}</div>'
            f'<span class="r-verdict {c["bucket"]}">{esc(c["label"])}</span>'
            f'<div class="r-cexp">{esc(c["explanation"])}</div>'
            f'</div>', unsafe_allow_html=True)

    _render_concord(result.get("old_code"))

    st.markdown(
        '<p class="r-foot">This is a check of the safeguards against what the document '
        'itself says — it cannot see anything that happened outside the document. '
        '"Possibly not followed" means the document is silent where it should have '
        'spoken. Take the document, and this, to a lawyer or the Magistrate.</p>',
        unsafe_allow_html=True)


def _render_concord(old_code):
    if not old_code:
        return
    parts = []
    for e in old_code:
        new = e.get("new") or "no re-enacted successor"
        parts.append(f'<code>{esc(e["old"])}</code> &rarr; <code>{esc(new)}</code>')
    st.markdown(
        '<div class="r-concord">This document cites the pre-2024 codes. Current '
        'equivalents: ' + " &nbsp;·&nbsp; ".join(parts)
        + ' &mdash; the case law generally carries over to the new numbering.</div>',
        unsafe_allow_html=True)


_ARREST_WORDS = (
    "arrest", "arrested", "custody", "lock-up", "lock up", "lockup",
    "detain", "detained", "remand", "police station", "picked up",
    "taken away", "took him", "took her", "took me", "in jail",
    "fir", "chargesheet", "charge sheet",
)


def _answer_is_arrest_flavoured(result, question_text):
    """Only offer the arrest-safeguard checklist when the person's own
    words describe an arrest / FIR / custody situation -- not under 'what
    is Section 318' (whose answer mentions bail/arrest for every offence)
    or a cheque / freeze answer.

    Gate on the QUESTION, not the answer: the answer discusses arrest
    procedure for any cognizable offence, so it is a poor signal; the
    question is where the person says what actually happened."""
    if not result or result.get("state") not in ("single_match", "conflicting_matches"):
        return False
    if result.get("redirect_domain") in ("cheque_bounce", "freeze"):
        return False
    if result.get("situation_detected"):
        return True
    return any(w in (question_text or "").lower() for w in _ARREST_WORDS)


def render_arrest_checklist():
    """A fixed yes/no self-assessment against the arrest safeguards, for
    families with no document. Pure deterministic mapping -- no AI in this
    path. Rendered inside an expander so it never blocks the answer."""
    if _asc is None:
        return
    with st.expander("Check the safeguards yourself — a few plain yes/no questions"):
        st.markdown(
            "Answer what you know. Leave anything you're unsure of on *Not sure* — "
            "it will tell you what to ask for.")

        with st.form("safeguard_checklist", border=False):
            picks = {}
            for sg in _asc.SAFEGUARDS:
                labels = [lbl for _code, lbl in sg["options"]]
                codes = [code for code, _lbl in sg["options"]]
                choice = st.radio(sg["question"], labels, index=None,
                                  key=f"sg_{sg['id']}")
                if choice is not None:
                    picks[sg["id"]] = codes[labels.index(choice)]
            submitted = st.form_submit_button("Show the findings  →", type="primary")

        if submitted:
            st.session_state["_sg_result"] = _asc.evaluate(picks)

        res = st.session_state.get("_sg_result")
        if not res or not res.get("rows"):
            if submitted:
                st.markdown('<p class="r-foot">Answer at least one question above, '
                            'then press <b>Show the findings</b>.</p>',
                            unsafe_allow_html=True)
            return None

        s = res["summary"]
        cls = "r-summ hasdefect" if s["violated"] or s["to_confirm"] else "r-summ"
        _band_color = {"red": "#b3261e", "orange": "#a3521a",
                       "amber": "#8a6d1a", "green": "#2f6b3f"}.get(s["band"], "#6a6250")
        st.markdown(
            f'<div class="{cls}">'
            f'<div style="font-family:\'IBM Plex Sans\',sans-serif;font-weight:700;'
            f'font-size:.95rem;letter-spacing:.03em;text-transform:uppercase;'
            f'color:{_band_color};margin-bottom:.4rem">'
            f'{esc(s["meter"])} &nbsp; {esc(s.get("label") or "")}</div>'
            f'{esc(s["headline"])}</div>',
            unsafe_allow_html=True)

        for r in res["rows"]:
            st.markdown(
                f'<div class="r-checkrow">'
                f'<div class="r-chead">{esc(r["question"])}</div>'
                f'<span class="r-verdict {r["bucket"]}">{esc(r["label"])}</span>'
                f'<div class="r-cexp">{esc(r["finding"])}<br>'
                f'<span class="r-src">{esc(r["section"])} &nbsp;·&nbsp; {esc(r["case"])}</span>'
                f'</div></div>', unsafe_allow_html=True)

        st.markdown(
            '<p class="r-foot">This is a check of the procedure against your own '
            'answers — it is not a ruling on the case. Take it, and any papers you '
            'do have, to a lawyer or your nearest District Legal Services Authority.</p>',
            unsafe_allow_html=True)
        return res


def _answer_draft_context(answer):
    """From the chat answer's matches: (civil_dispute flag, offence sections).
    civil_dispute -> the answer leaned on the 'civil matter given criminal
    colour' line of cases, so the petition should also ask for quashing.
    Delegates to petition_draft.derive_draft_context (shared with
    whatsapp_bot.py's DRAFT command, 2026-09-14) so one rule decides both."""
    return _pd.derive_draft_context((answer or {}).get("matches"))


def render_petition_draft(question_text, *, checklist_result=None, doc_check_result=None,
                          chat_answer=None, prominent=False):
    """The draft-petition step: a High Court petition assembled
    deterministically from the findings (or, for cheque / freeze, from
    the answer's own authorities), shown in an editable box with a
    Download PDF. No AI in this path. Wrapped by the caller in try/except;
    import guarded.

    prominent=True adds a coloured call-out above the expander so the
    person sees the draft + PDF without having to work through the checks
    first; it is still one click to open, so the page stays uncluttered."""
    if _pd is None:
        return
    answer = st.session_state.get("answer") or {}
    civil, secs = _answer_draft_context(answer)
    _blurb = ("This assembles a **draft High Court petition** from the points above — "
              "**fixed rules, no AI**. Every `[ ___ ]` is for you or your lawyer to fill; "
              "every case passage is marked **NOT INDEPENDENTLY VERIFIED** until it is "
              "checked in the judgment. It is a starting point, not a filed document.")

    def _digest(*parts):
        return abs(hash(repr(parts))) % 10**6

    if checklist_result is not None:
        _rows = tuple((r.get("id"), r.get("bucket")) for r in (checklist_result.get("rows") or []))
        sig = f"cl:{abs(hash(question_text)) % 10**8}:{civil}:{'.'.join(secs)}:{_digest(_rows)}"
        seed = lambda: _pd.from_checklist(
            question_text, checklist_result, civil_dispute=civil, offence_sections=secs)
        if _rows:
            _blurb += ("  \nThe grounds below are rebuilt from the safeguard checks; "
                       "re-open this after you change an answer there.")
        else:
            _blurb += ("  \nThis is the general form. Run the safeguard checks below and "
                       "the specific grounds are filled in for you.")
    elif doc_check_result is not None:
        sig = (f"dc:{abs(hash(question_text)) % 10**8}:{civil}:{'.'.join(secs)}:"
               f"{_digest(doc_check_result.get('checks'), doc_check_result.get('overall'))}")
        seed = lambda: _pd.from_doc_check(
            question_text, doc_check_result, civil_dispute=civil, offence_sections=secs)
    elif chat_answer is not None and chat_answer.get("redirect_domain") == "cheque_bounce":
        sig = f"ch:{abs(hash(question_text)) % 10**8}"
        seed = lambda: _pd.from_cheque_answer(question_text, chat_answer)
    elif chat_answer is not None and chat_answer.get("redirect_domain") == "freeze":
        sig = f"fz:{abs(hash(question_text)) % 10**8}"
        seed = lambda: _pd.from_freeze_answer(question_text, chat_answer)
    else:
        return

    if prominent:
        st.markdown(
            '<div class="r-cta"><span class="r-cta-ico">\U0001F4C4</span>'
            '<span><b>A draft petition is ready.</b> Built from your account and the '
            'sections and judgments above &mdash; edit it here, then download it as a PDF. '
            'A starting point to take to a lawyer, not a filed document.</span></div>',
            unsafe_allow_html=True)

    _label = ("Open the draft petition  →" if prominent
              else "Turn this into a draft — a petition you can edit and take to a lawyer")
    with st.expander(_label):
        st.markdown(_blurb)

        text_key = f"_petition_{sig}"
        if text_key not in st.session_state:
            st.session_state[text_key] = seed()
        st.text_area("Draft (editable)", height=480, key=text_key)

        pdf_key = f"_petition_pdf_{sig}"
        st.markdown('<p class="r-foot" style="margin:.6rem 0 .1rem">When the draft reads '
                    'right, turn it into a formatted PDF you can print or email.</p>',
                    unsafe_allow_html=True)
        if st.button("Prepare the PDF  →", key=f"_petition_btn_{sig}",
                     type="primary", use_container_width=True):
            import os, tempfile
            try:
                path = _pd.to_pdf(
                    st.session_state[text_key],
                    output_path=os.path.join(tempfile.gettempdir(), "recourse_petition_draft.pdf"))
                with open(path, "rb") as fh:
                    st.session_state[pdf_key] = fh.read()
            except Exception:
                logging.getLogger("recourse_app").exception("petition PDF failed")
                st.markdown('<p class="r-foot">Could not build the PDF just now — you can '
                            'still copy the text above.</p>', unsafe_allow_html=True)

        if st.session_state.get(pdf_key):
            st.download_button(
                "Download the draft (PDF)  ↓", data=st.session_state[pdf_key],
                file_name="recourse_criminal_petition_draft.pdf",
                mime="application/pdf", key=f"_petition_dl_{sig}",
                type="primary", use_container_width=True)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
_new_q = msg.strip() if ((go or st.session_state.pop("_autorun", False)) and msg.strip()) else None

# A new question is a TWO-pass operation: pass 1 records it and reruns
# with the buttons locked; pass 2 renders the "reading the law" state,
# fetches the answer, then reruns to show it. This keeps someone from
# clicking the button again while a (possibly slow) request is in flight.
if _new_q and not _busy:
    for _k in list(st.session_state.keys()):
        if _k in ("doc_check", "doc_check_sig", "_sg_result", "answer") \
           or _k.startswith("_petition_"):
            st.session_state.pop(_k, None)      # never carry stale artefacts over
    st.session_state["_busy"] = True
    st.session_state["_busy_msg"] = _new_q
    st.rerun()

if _busy:
    _q = st.session_state.get("_busy_msg") or msg
    st.html('<hr class="r-rule">'
            '<div id="r-working" class="r-working"><span class="r-working-dot"></span>'
            'Reading the law and the judgments on this&hellip;</div>')
    _scroll_into_view("#r-working")
    try:
        # recourse_app is chat-only: cheque-bounce, bank-freeze, and
        # (added 2026-09-14) domestic-violence (PWDVA) questions are
        # answered inline from the shared corpus rather than dead-ended
        # with a "covered elsewhere" redirect that points nowhere here.
        st.session_state.answer = _answer_question(
            _q, inline_domains={"cheque_bounce", "freeze", "domestic_violence"})
    except Exception:
        logging.getLogger("recourse_app").exception("answer_question failed")
        st.session_state.answer = {"state": "retrieval_unavailable"}
    st.session_state.answer_msg = _q
    st.session_state["_busy"] = False
    st.session_state.pop("_busy_msg", None)
    st.rerun()

answer = st.session_state.get("answer")
if answer:
    _box_now = msg.strip()
    msg = st.session_state.get("answer_msg", msg)
    st.html('<hr class="r-rule">')
    # if the box has been edited since this answer was produced, say so
    if _box_now and _box_now != msg.strip():
        st.markdown('<p class="r-foot">You\'ve changed your description &mdash; press '
                    '<b>Check my situation</b> again to update the answer below.</p>',
                    unsafe_allow_html=True)

    situation = render_answer(answer)

    # ---- cheque-bounce / bank-freeze: the draft petition, up front ----
    if answer.get("state") == "single_match" and \
       answer.get("redirect_domain") in ("cheque_bounce", "freeze"):
        try:
            render_petition_draft(msg, chat_answer=answer, prominent=True)
        except Exception:
            logging.getLogger("recourse_app").exception("petition (chat) render failed")

    # ---- arrest / FIR / custody ----
    # Offered for any arrest / FIR / custody answer, not only ones that
    # open with "Right now".
    _arrest_flavoured = False
    try:
        _arrest_flavoured = _answer_is_arrest_flavoured(answer, msg)
    except Exception:
        _arrest_flavoured = bool(situation)

    if situation or _arrest_flavoured:
        # ---- check whether the safeguards were ACTUALLY followed ----
        # Two routes, both deterministic (no AI): upload the paper, or
        # answer a fixed checklist. Either one sharpens the draft below.
        st.markdown('<div class="r-label">Have the papers?</div>', unsafe_allow_html=True)
        st.markdown(
            "The answer above is what the law **requires**. Upload the **arrest "
            "memo, the FIR copy, or a remand order** and Recourse checks whether "
            "each safeguard was **actually followed** — with fixed rules, not the AI.")
        up = st.file_uploader("Upload a document (PDF or text)", type=["pdf", "txt"],
                              label_visibility="collapsed", key="doc_upload")
        if up is not None:
            extract_text, check_arrest_document = _upload_fns()
            sig = f"{up.name}:{up.size}"
            if st.session_state.get("doc_check_sig") != sig:
                ext = extract_text(up)
                if not ext["ok"]:
                    st.session_state["doc_check"] = {"ok": False, "error": ext["error"]}
                else:
                    with st.spinner("Checking the document against the safeguards…"):
                        st.session_state["doc_check"] = check_arrest_document(ext["text"])
                st.session_state["doc_check_sig"] = sig
            _dc = st.session_state.get("doc_check")
            if _dc:
                render_doc_check(_dc)

        # ---- the no-document route ----
        st.markdown('<div class="r-label" style="margin-top:1.3rem">No papers?</div>',
                    unsafe_allow_html=True)
        st.markdown(
            "Answer a few plain yes/no questions and Recourse checks each arrest "
            "safeguard against your answers — **fixed rules, no AI**, with the "
            "section and the judgment behind each one.")
        try:
            render_arrest_checklist()
        except Exception:
            logging.getLogger("recourse_app").exception("arrest checklist render failed")

        # ---- the draft petition + PDF ----
        # Always offered for an arrest answer -- NOT gated on finishing
        # the checks above. It seeds from an uploaded memo if there is
        # one, else a completed checklist, else the general form, and
        # re-seeds as either check is done.
        try:
            _dc = st.session_state.get("doc_check")
            if _dc and _dc.get("is_arrest_document") \
               and (_dc.get("n_defects") or _dc.get("n_unknown")):
                render_petition_draft(msg, doc_check_result=_dc, prominent=True)
            else:
                _sg = st.session_state.get("_sg_result")
                _seed = _sg if (_sg and _sg.get("rows")) else \
                    (_asc.evaluate({}) if _asc is not None else None)
                if _seed is not None:
                    render_petition_draft(msg, checklist_result=_seed, prominent=True)
        except Exception:
            logging.getLogger("recourse_app").exception("petition (arrest) render failed")

_footer()

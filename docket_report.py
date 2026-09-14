
"""
docket_report.py

Automatically generates the "Judgment Review Docket" HTML page from
candidate_pipeline.py's own database -- the automated version of Idea 3
(2026-09-14). Previously this page was hand-written per candidate; now
it's generated from whatever is actually staged as 'pending', so adding
a new candidate to the database is enough to produce an up-to-date
review page, without re-authoring HTML each time.

Still NOT a closed loop: the generated page's Approve/Reject buttons
are visual only (no live backend) -- the actual decision is still
recorded via candidate_pipeline.approve()/reject(), called after a
person tells Claude their call. See candidate_pipeline.py's module
docstring for why the FINAL decision deliberately stays a human action,
not something this generator or the page itself can make on its own.
"""
import html


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _corroboration_block(corroboration: dict) -> str:
    parts = []

    cross = corroboration.get("cross_source", {})
    if cross.get("checked"):
        verdict = "text confirmed present" if cross.get("found_in_vaquill") else "NOT found -- check this"
        pill_cls = "" if cross.get("found_in_vaquill") else "weak"
        parts.append(f"""
      <details open>
        <summary>Independent second source (Vaquill) <span class="verdict-pill {pill_cls}">{_esc(verdict)}</span></summary>
        <div class="evidence-body">
          A separately-scraped copy of this judgment, built by a different organisation than
          Indian Kanoon, was searched independently for the proposed holding's own text.
        </div>
      </details>""")

    cite = corroboration.get("citation_corroboration", {})
    if cite.get("checked"):
        docs = cite.get("corroborating_documents", [])
        scanned = cite.get("documents_scanned", 0)
        pill_cls = "" if docs else "weak"
        items = "".join(
            f'<li class="cite-item"><b>{_esc(d.get("title"))} &mdash; {_esc(d.get("court"))}</b>'
            f'<span>&ldquo;{_esc(d.get("matched_headline"))}&rdquo;</span></li>'
            for d in docs[:4]
        )
        parts.append(f"""
      <details {"open" if docs else ""}>
        <summary>Other courts citing this case <span class="verdict-pill {pill_cls}">{len(docs)} of {scanned} confirm</span></summary>
        <div class="evidence-body">
          {"Real documents found citing this case, independently describing the same holding:" if docs else "No other citing document's own summary matched the proposed holding language -- worth a closer look, though a very new case may simply not be cited elsewhere yet."}
          {f'<ul class="cite-list">{items}</ul>' if items else ""}
        </div>
      </details>""")

    agree = corroboration.get("independent_agreement", {})
    if agree.get("checked"):
        rank = agree.get("best_matching_rank")
        pill_text = f"matches rank {rank} of {len(agree.get('candidates', []))}" if rank else "no match found"
        pill_cls = "" if rank == 1 else "weak"
        parts.append(f"""
      <details>
        <summary>Independently re-derived candidate <span class="verdict-pill {pill_cls}">{_esc(pill_text)}</span></summary>
        <div class="evidence-body">
          Scanning the second source's own text for disposal-style language, with no knowledge of the
          quote picked above.
          <div class="caveat"><b>Read this yourself, not just the pill:</b> this check can't tell a sentence
          apart from its own negation -- an overruled, opposite rule quoted in the same judgment can score
          just as high. A matching rank is a reason to look closer, not a reason to skip looking.</div>
        </div>
      </details>""")

    return "".join(parts)


def _candidate_card(c: dict) -> str:
    return f"""
  <article class="case-file" id="case-{c['id']}">
    <div class="case-head">
      <span class="case-tag">Pending your review &mdash; #{c['id']}</span>
      <h2 class="case-name">{_esc(c['case_name'])}</h2>
      <div class="case-cite">{_esc(c.get('citation') or '(citation not recorded)')}</div>
    </div>
    <div class="holding">
      <p class="holding-label">Proposed holding{f" &mdash; paragraph {_esc(c['paragraph_number'])}" if c.get('paragraph_number') else ""}</p>
      <blockquote>&ldquo;{_esc(c['holding_text'])}&rdquo;</blockquote>
    </div>
    <div class="evidence">{_corroboration_block(c['corroboration'])}</div>
    <div class="decision-row">
      <p>Your call &mdash; tell Claude "approve #{c['id']}" or "reject #{c['id']}".</p>
      <button class="decide" type="button" onclick="decide(this,'approve')">Approve</button>
      <button class="decide" type="button" onclick="decide(this,'reject')">Reject</button>
    </div>
  </article>"""


_PAGE_TEMPLATE = """<title>Judgment Review Docket</title>
<style>
  :root {{
    --ground: #F6F3EC; --surface: #FFFDF8; --ink: #1E2A38; --ink-soft: #4B5A6B;
    --hairline: #D8D0C0; --seal: #2C4A6E; --seal-soft: #E4EAF0; --brass: #9C7A2E;
    --brass-soft: #F3ECD9; --confirm: #2F5233; --confirm-soft: #E4EDE3;
    --flag: #8B3A3A; --flag-soft: #F3E4E1;
  }}
  :root:not([data-theme="light"]) {{
    @media (prefers-color-scheme: dark) {{
      --ground: #14181F; --surface: #1B212A; --ink: #E9E4D8; --ink-soft: #A9B4BF;
      --hairline: #333B47; --seal: #7FA3C9; --seal-soft: #202B38; --brass: #D8B863;
      --brass-soft: #2B2718; --confirm: #8FBB92; --confirm-soft: #1D2A1E;
      --flag: #D68A8A; --flag-soft: #2E1E1E;
    }}
  }}
  :root[data-theme="dark"] {{
    --ground: #14181F; --surface: #1B212A; --ink: #E9E4D8; --ink-soft: #A9B4BF;
    --hairline: #333B47; --seal: #7FA3C9; --seal-soft: #202B38; --brass: #D8B863;
    --brass-soft: #2B2718; --confirm: #8FBB92; --confirm-soft: #1D2A1E;
    --flag: #D68A8A; --flag-soft: #2E1E1E;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--ground); color: var(--ink); font-family: "IBM Plex Sans", system-ui, sans-serif;
         margin: 0; padding-inline: 20px; padding-block: 40px 80px; }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  .masthead {{ border-bottom: 3px double var(--hairline); padding-bottom: 20px; margin-bottom: 8px; }}
  .eyebrow {{ font-family: "IBM Plex Mono", monospace; font-size: 0.72rem; letter-spacing: 0.12em;
             text-transform: uppercase; color: var(--seal); margin: 0 0 6px; }}
  h1 {{ font-family: "Source Serif 4", Georgia, serif; font-size: clamp(1.6rem, 4vw, 2.15rem);
       font-weight: 600; margin: 0 0 10px; text-wrap: balance; }}
  .masthead p {{ color: var(--ink-soft); font-size: 0.95rem; line-height: 1.6; max-width: 62ch; margin: 0; }}
  .masthead p + p {{ margin-top: 10px; }}
  .docket-meta {{ display: flex; gap: 24px; flex-wrap: wrap; font-family: "IBM Plex Mono", monospace;
                 font-size: 0.78rem; color: var(--ink-soft); margin: 18px 0 0; }}
  .docket-meta b {{ color: var(--ink); font-weight: 600; }}
  .case-file {{ background: var(--surface); border: 1px solid var(--hairline); border-left: 5px solid var(--brass);
               border-radius: 3px; margin: 26px 0; overflow: hidden; }}
  .case-head {{ padding: 20px 24px 16px; border-bottom: 1px solid var(--hairline); }}
  .case-tag {{ display: inline-flex; align-items: center; gap: 6px; font-family: "IBM Plex Mono", monospace;
              font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 9px;
              border-radius: 999px; background: var(--brass-soft); color: var(--brass); margin-bottom: 10px; }}
  .case-name {{ font-family: "Source Serif 4", Georgia, serif; font-size: 1.2rem; font-weight: 600;
               margin: 0 0 4px; text-wrap: balance; }}
  .case-cite {{ font-family: "IBM Plex Mono", monospace; font-size: 0.8rem; color: var(--ink-soft); }}
  .holding {{ padding: 18px 24px; background: var(--seal-soft); }}
  .holding-label {{ font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--seal);
                    font-weight: 600; margin: 0 0 8px; }}
  blockquote {{ font-family: "Source Serif 4", Georgia, serif; font-size: 0.98rem; line-height: 1.65;
               margin: 0; color: var(--ink); }}
  .evidence {{ padding: 4px 24px 8px; }}
  details {{ border-top: 1px solid var(--hairline); padding: 14px 0; }}
  details:first-of-type {{ border-top: none; }}
  summary {{ cursor: pointer; font-weight: 600; font-size: 0.88rem; display: flex; align-items: center;
            gap: 10px; list-style: none; }}
  summary::-webkit-details-marker {{ display: none; }}
  summary::before {{ content: "▸"; color: var(--seal); font-size: 0.75rem; transition: transform 0.15s ease; }}
  details[open] summary::before {{ transform: rotate(90deg); }}
  .verdict-pill {{ margin-left: auto; font-family: "IBM Plex Mono", monospace; font-size: 0.72rem;
                   padding: 2px 8px; border-radius: 999px; background: var(--confirm-soft); color: var(--confirm);
                   white-space: nowrap; }}
  .verdict-pill.weak {{ background: var(--flag-soft); color: var(--flag); }}
  .evidence-body {{ padding: 12px 4px 4px 20px; font-size: 0.87rem; color: var(--ink-soft); line-height: 1.6; }}
  .cite-list {{ list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }}
  .cite-item {{ border-left: 2px solid var(--hairline); padding-left: 12px; }}
  .cite-item b {{ color: var(--ink); display: block; font-size: 0.84rem; }}
  .cite-item span {{ font-style: italic; }}
  .caveat {{ margin-top: 10px; padding: 10px 12px; background: var(--flag-soft); border-radius: 3px;
            color: var(--ink); font-size: 0.82rem; }}
  .caveat b {{ color: var(--flag); }}
  .decision-row {{ display: flex; gap: 10px; padding: 18px 24px 22px; border-top: 1px solid var(--hairline);
                   flex-wrap: wrap; align-items: center; }}
  .decision-row p {{ font-size: 0.78rem; color: var(--ink-soft); margin: 0; flex: 1 1 220px; }}
  button.decide {{ font-family: "IBM Plex Sans", sans-serif; font-size: 0.85rem; font-weight: 600;
                   padding: 9px 18px; border-radius: 4px; border: 1px solid var(--hairline);
                   background: var(--surface); color: var(--ink); cursor: pointer;
                   transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease; }}
  button.decide:hover {{ border-color: var(--seal); }}
  button.decide.active-approve {{ background: var(--confirm); border-color: var(--confirm); color: var(--surface); }}
  button.decide.active-reject {{ background: var(--flag); border-color: var(--flag); color: var(--surface); }}
  button:focus-visible {{ outline: 2px solid var(--seal); outline-offset: 2px; }}
  .empty-state {{ padding: 30px 24px; text-align: center; color: var(--ink-soft); background: var(--surface);
                  border: 1px dashed var(--hairline); border-radius: 3px; }}
  footer {{ margin-top: 40px; padding-top: 18px; border-top: 3px double var(--hairline); font-size: 0.78rem;
           color: var(--ink-soft); line-height: 1.6; }}
  @media (max-width: 480px) {{ .decision-row {{ flex-direction: column; align-items: stretch; }} .decision-row p {{ order: 2; }} }}
</style>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<div class="wrap">
  <div class="masthead">
    <p class="eyebrow">Recourse &mdash; Corpus Sourcing Docket</p>
    <h1>Judgment Review Docket</h1>
    <p><strong>Generated automatically</strong> from candidate_pipeline.py's own database -- every candidate below already ran through both automated corroboration checks before landing here.</p>
    <p>Approve/Reject on this page is still visual only -- tell Claude your call in chat (e.g. "approve #{first_id}") and it's recorded for real.</p>
    <div class="docket-meta"><span><b>Pending:</b> {n_pending}</span></div>
  </div>
  {cards}
  <footer>Sources: Indian Kanoon (verbatim text, citations) and Vaquill AI's open-india-law dataset (candidate discovery, cross-source confirmation), via judgment_corroboration.py and candidate_pipeline.py.</footer>
</div>
<script>
  function decide(btn, choice) {{
    const row = btn.closest('.decision-row');
    row.querySelectorAll('button').forEach(b => b.classList.remove('active-approve', 'active-reject'));
    btn.classList.add(choice === 'approve' ? 'active-approve' : 'active-reject');
  }}
</script>
"""


def generate_docket_html(candidates: list) -> str:
    """Builds the full review page from a list of candidate dicts (as
    returned by candidate_pipeline.list_candidates(status='pending')).
    Pure string generation, no side effects, no network."""
    if not candidates:
        cards = '<div class="empty-state">Nothing pending review right now.</div>'
    else:
        cards = "".join(_candidate_card(c) for c in candidates)
    return _PAGE_TEMPLATE.format(
        cards=cards, n_pending=len(candidates),
        first_id=candidates[0]["id"] if candidates else "N",
    )

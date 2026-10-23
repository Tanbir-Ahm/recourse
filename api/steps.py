"""
api/steps.py -- the plain-English line for each live step the engine reports (progress.py). Built from the step's own details only (counts, Act names), so a line can never say more than the code did.
An unknown step id gets no line and is not shown: the panel never invents a step.
"""

_SCOPE = {
    "in_scope": "Checked the topic of the question: it is within what Recourse covers",
    "adjacent_uncovered": "Checked the topic of the question: a subject outside the library",
    "covered_elsewhere_in_tool": "Checked the topic of the question: it belongs to another part of the tool",
    "unrelated": "Checked the topic of the question: it does not look like a legal question",
    "unavailable": "Could not check the topic of the question",
}


def _n(d, k):
    v = (d or {}).get(k)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _names(d, k):
    v = (d or {}).get(k)
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


def describe(step, detail):
    """-> {'label': str, 'status': 'done'|'running', 'detail': dict} or None for a step this service does not show."""
    d = detail if isinstance(detail, dict) else {}
    if step == "scope":
        return {"label": _SCOPE.get(d.get("category"), "Checked the topic of the question"), "status": "done", "detail": {"category": d.get("category")}}
    if step == "acts":
        names = _names(d, "names")
        label = ("Found an Act named or described in the question: " + "; ".join(names)) if names else "Looked for a special Act in the question: none found"
        return {"label": label, "status": "done", "detail": {"acts": names}}
    if step == "sections":
        items, cited = _names(d, "items"), _n(d, "cited")
        if not items:
            return None
        label = "Brought in the official text of: " + ", ".join(items)
        if cited:
            label += f" (including {cited} section{'s' if cited != 1 else ''} cited by the section asked about)"
        return {"label": label, "status": "done", "detail": {"sections": items, "cited": cited}}
    if step == "library":
        s, j = _n(d, "statutes"), _n(d, "judgments")
        return {"label": f"Searched the library: {s} law passage{'s' if s != 1 else ''} and {j} judgment passage{'s' if j != 1 else ''} found", "status": "done", "detail": {"statutes": s, "judgments": j}}
    if step == "wider":
        j = _n(d, "judgments")
        return {"label": f"Searched the wider Supreme Court index: {j} judgment{'s' if j != 1 else ''} listed (not independently verified)", "status": "done", "detail": {"judgments": j}}
    if step == "write":
        return {"label": "Writing the answer", "status": "running", "detail": {}}
    if step == "register":
        n = _n(d, "notes")
        return {"label": ("Checked the Overruled Register: %d case%s flagged" % (n, "s" if n != 1 else "")) if n else "Checked the Overruled Register: nothing flagged", "status": "done", "detail": {"flagged": n}}
    if step == "checks":
        n = _n(d, "notes")
        return {"label": ("Ran the citation and quotation checks: %d notice%s" % (n, "s" if n != 1 else "")) if n else "Ran the citation and quotation checks: no notice", "status": "done", "detail": {"notices": n}}
    return None

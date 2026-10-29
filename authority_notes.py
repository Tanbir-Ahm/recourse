"""
authority_notes.py -- what the wider search says about WHY a judgment is among its results (added 2026-10-29, after the owner's staging answer on circumstantial evidence left out
*Sharad Birdhichand Sarda v. State of Maharashtra* although the index holds it and 446 of its judgments name it).

The search service, when it runs with SCI_AUTHORITY=on (authority_search.py in the research repository), ranks with one more fact: which judgments the retrieved judgments themselves refer to by name. It sends, with every
result, a field `authority`: {"named_by_collection": N, "named_by_retrieved": n, "retrieved": M, "pointer": true|false, "raw_score": x}. `pointer` is true for a judgment that enough of the retrieved judgments name for it
to have been fetched and favoured: the court's own pointer to where the rule they apply was laid down.

This module only reads that field. A service that sends none (the one on production today) changes nothing: every function here returns None / '' and the prompt and the page are byte for byte what they were.
What it does for a pointer passage (used by sci_search_tier.feed_block):
  * the passage is shown longer to the answer model (PASSAGE_CHARS instead of the usual cut), because a landmark's statement of the rule is rarely 900 characters;
  * a line under the passage says that other judgments name the case, and one sentence in the prompt says how to use that line (read this passage first; never repeat the counts; never call the case settled);
  * the page's list of wider-search passages carries one plain sentence with the same facts.
NOTHING HERE SAYS A CASE IS GOOD LAW. A judgment is named because it was followed, distinguished or criticised; the Overruled Register and the cards remain the only warnings, and they apply to a pointer passage exactly as to any other.
The counts are an automatic count of mentions of the case's name in the text of the collection: approximate, and they are not shown as a measure of quality.
"""

PASSAGE_CHARS = 1500            # the cut of a pointer passage (the search service itself returns at most SCI_MAX_TEXT = 1500)
MIN_NAMED = 2                   # the fewest retrieved judgments that can make a judgment a pointer, whatever the service says (the service's own default is 3)

INSTRUCTION = (
    "\nA line starting \"Named by other judgments\" under a passage says that several of the other judgments retrieved for this question refer to that case by name, which usually means it is where the rule "
    "they apply was laid down. When such a passage states the rule the person's question is about, set out the rule from that passage first, then use the other passages for what it leaves open. The line is only a "
    "pointer to which passage to read first: never repeat its numbers in your answer, never call the case settled or good law because of it (a judgment can be named in order to disagree with it), and still "
    "describe only what the passage itself says.\n")


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def facts(result):
    """The service's `authority` facts for one result, checked: {'collection': N, 'retrieved_by': n, 'retrieved': M, 'pointer': bool}; None when the result carries none or they do not make sense."""
    try:
        a = result.get("authority") if isinstance(result, dict) else None
        if not isinstance(a, dict):
            return None
        coll, by, m = _count(a.get("named_by_collection")), _count(a.get("named_by_retrieved")), _count(a.get("retrieved"))
        if coll is None or by is None or m is None or m < 1 or by > m:
            return None
        return {"collection": max(coll, by), "retrieved_by": by, "retrieved": m, "pointer": a.get("pointer") is True}
    except Exception:  # noqa: BLE001
        return None


def is_pointer(f):
    """True for a result the service marked as one of the court's own pointers (and that at least MIN_NAMED of the retrieved judgments name)."""
    return bool(f and f["pointer"] and f["retrieved_by"] >= MIN_NAMED)


def _counts(f):
    return "%d of the %d judgments this search retrieved for the question refer to this case by name, and about %s judgments of the whole collection do" % (f["retrieved_by"], f["retrieved"], format(f["collection"], ","))


def prompt_line(f):
    """The line under a pointer passage in the prompt ('' for a result that is not a pointer)."""
    if not is_pointer(f):
        return ""
    return ("\n[Named by other judgments -- read this passage first, but this is NOT a statement that the case is good law: %s (an automatic count of mentions of its name). "
            "A judgment is named for many reasons: it may have been followed, distinguished or criticised.]" % _counts(f))


def page_note(f):
    """One plain sentence for the page's list of wider-search passages ('' for a result that is not a pointer). It is also what a row of the table of authorities carries after 'Reading note:', so it is kept short."""
    if not is_pointer(f):
        return ""
    return ("Named by other judgments: %d of the %d judgments this search retrieved for the question, and about %s in the whole collection (an automatic count of mentions of its name; a judgment can be named "
            "because it was followed, distinguished or criticised, so this does not say that the case is still good law)." % (f["retrieved_by"], f["retrieved"], format(f["collection"], ",")))


def log_item(case_name, f):
    """What the log line SCI_FEED_AUTHORITY holds for one pointer passage."""
    return {"case": (case_name or "")[:100], "named_by_retrieved": f["retrieved_by"], "retrieved": f["retrieved"], "named_by_collection": f["collection"]}

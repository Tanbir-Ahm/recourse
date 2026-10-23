"""
site_account.py -- what the Streamlit page shows and does when USE_API is on (step A5; WEBSITE_DESIGN 1.3 and 14): sign in with Google (st.login), accept the privacy notice and terms and say you are 18 or older, a line saying how many answers are
left today, the question itself through the API (saved chats, live steps), "report a problem with this answer", and "my data" (download, delete). Imported by recourse_app.py ONLY when site_client.enabled(); with the switch off none of this
runs and the page is exactly as before. All calls go through site_client.py. The page's own code draws the answer: the API hands back the engine's whole result, which render_answer already knows how to draw.
Settings for sign-in (environment, never in the repository), handed to Streamlit's login in memory at start-up (nothing is written to disk):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   the Google OAuth client (Google Cloud console: Credentials, OAuth client ID, Web application)
  STREAMLIT_COOKIE_SECRET                  a long random value (32+ characters) that signs Streamlit's login cookie; keep it stable or everyone is signed out at each deploy
  SITE_URL                                 this website's public address, e.g. https://staging-site-production-xxxx.up.railway.app ; Google must be told the redirect address SITE_URL/oauth2callback
  SITE_OIDC_METADATA_URL                   (tests only) another OpenID provider's discovery address instead of Google's; leave unset for Google
"""
import html as _html
import logging
import os

import streamlit as st

import site_client

logger = logging.getLogger("site_account")
GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
FEEDBACK_KINDS = [("wrong_law", "The law it states is wrong"), ("wrong_case", "A case is wrong or does not fit"), ("wrong_quote", "A quotation is wrong"), ("missing", "Something important is missing"),
                  ("unclear", "It is unclear"), ("helpful", "It helped"), ("other", "Something else")]


def _esc(s):
    return _html.escape(str(s or ""))


def _env(name):
    return (os.environ.get(name) or "").strip().strip("\"'")


# ------------------------------------------------------------------ sign-in configuration
def login_config():
    """Streamlit's [auth] settings from the environment as a dict, or None when something is missing."""
    cid, csec, cookie, site = _env("GOOGLE_CLIENT_ID"), _env("GOOGLE_CLIENT_SECRET"), _env("STREAMLIT_COOKIE_SECRET"), _env("SITE_URL").rstrip("/")
    if not (cid and csec and site.startswith("http") and len(cookie) >= 32):
        return None
    return {"auth": {"redirect_uri": site + "/oauth2callback", "cookie_secret": cookie, "client_id": cid, "client_secret": csec, "server_metadata_url": _env("SITE_OIDC_METADATA_URL") or GOOGLE_METADATA}}


def ensure_login_config():
    """True when Streamlit's login is configured. If the environment holds the settings and no [auth] block exists yet, hands them to Streamlit in memory (st.secrets.merge_programmatic_secrets): nothing is written to disk, so no secret ever sits in a file."""
    try:
        if "auth" in st.secrets:
            return True
    except Exception:  # noqa: BLE001 -- no secrets file at all
        pass
    cfg = login_config()
    if cfg is None:
        return False
    try:
        st.secrets.merge_programmatic_secrets(cfg)
        return "auth" in st.secrets
    except Exception:  # noqa: BLE001
        logger.warning("could not hand the login configuration to Streamlit")
        return False


def current_user():
    """The signed-in person {'sub','email','email_verified','name'} or None. The only place that reads st.user (tests replace this function)."""
    u = st.user
    if not getattr(u, "is_logged_in", False):
        return None
    try:
        d = u.to_dict()
    except Exception:  # noqa: BLE001
        d = {k: getattr(u, k, None) for k in ("sub", "email", "email_verified", "name")}
    if not d.get("sub") or not d.get("email"):
        return None
    return {"sub": str(d["sub"]), "email": str(d["email"]), "email_verified": bool(d.get("email_verified")), "name": d.get("name")}


# ------------------------------------------------------------------ the cards
def _card(title, body, label="Your account"):
    st.html('<hr class="r-rule">')
    st.markdown(f'<div class="r-label">{_esc(label)}</div>', unsafe_allow_html=True)
    st.markdown("## " + title)
    st.markdown(f'<div class="r-oos">{_esc(body)}</div>', unsafe_allow_html=True)


def _signin_card():
    _card("Sign in to ask", "Recourse keeps your questions and answers private to you, so it asks you to sign in with Google. You must be 18 or older. We do not post anything or read anything else from your Google account.")
    st.button("Sign in with Google", type="primary", on_click=st.login)


def _consent_card(person, acct):
    _card("Before you start", "Please read the privacy notice and the terms, and tell us you are 18 or older. You can delete your account and everything we hold at any time.")
    docs = acct["consent"]["missing"]
    texts = {}
    for d in docs:
        try:
            texts[d["document"]] = site_client.legal(d["document"])
        except site_client.ApiError:
            st.error("Could not load the documents just now. Please try again in a moment.")
            st.stop()
    for d in docs:
        t = texts[d["document"]]
        with st.expander(f"{d['document'].replace('_', ' ').title()} (version {t['version']})", expanded=False):
            if t.get("placeholder"):
                st.warning("This is TEST text, not the final notice. Real accounts open only after a lawyer's text is in place.")
            st.text(t["text"])
    with st.form("consent_form", border=False):
        ok_docs = st.checkbox("I have read and I accept the privacy notice and the terms shown above.", key="consent_docs") if docs else True
        ok_age = st.checkbox("I am 18 years old or older.", key="consent_age") if not acct["consent"]["age_confirmed"] else True
        go = st.form_submit_button("Accept and continue", type="primary")
    if go:
        if not (ok_docs and ok_age):
            st.error("Please tick the box" + ("es" if (docs and not acct["consent"]["age_confirmed"]) else "") + " to continue.")
            return
        try:
            for d in docs:
                site_client.accept(person, d["document"], texts[d["document"]]["version"])
            if not acct["consent"]["age_confirmed"]:
                site_client.confirm_age(person)
        except site_client.ApiError as e:
            st.error("Could not save your acceptance (%s). Please try again." % e.code)
            return
        st.session_state.pop("_acct", None)
        st.rerun()


# ------------------------------------------------------------------ the gate and the bar
def _load_acct(person):
    a = st.session_state.get("_acct")
    if a and a.get("sub") == person["sub"] and a["consent"]["ready"]:
        return a
    me = site_client.me(person)
    a = {"sub": person["sub"], "user": me["user"], "consent": me["consent"], "usage": me.get("usage") or {}}
    st.session_state["_acct"] = a
    return a


def gate():
    """Draws what is needed before the page proper and STOPS the page until the person is signed in and has accepted. Returns the person when all is well."""
    if not site_client.configured():
        _card("Accounts are not connected", "This site is set to use accounts but is not connected to the account service yet. Please try again later.")
        st.stop()
    if not ensure_login_config():
        _card("Sign-in is not set up", "Sign-in with Google has not been configured on this site yet. Please try again later.")
        st.stop()
    person = current_user()
    if person is None:
        _signin_card()
        st.stop()
    try:
        acct = _load_acct(person)
    except site_client.ApiError as e:
        if e.code in ("accounts are not open yet", "legal text is not final"):
            _card("Accounts are not open yet", "Sign-in is not open to the public yet. Please come back soon.")
        elif e.code in ("bad_token", "token_expired", "token_reused", "streamlit_sign_in_off", "email_not_verified"):
            _card("Your sign-in could not be checked", "Please sign out and sign in again. If this keeps happening, tell us.")
            st.button("Sign out", on_click=st.logout)
        else:
            _card("Something isn't working right now", "This is a technical problem on Recourse's side. Try again in a moment.")
        st.stop()
    if not acct["consent"]["ready"]:
        _consent_card(person, acct)
        st.stop()
    topbar(person, acct)
    return person


def usage_line(acct, audience="layman"):
    u = (acct.get("usage") or {}).get("answer_lawyer" if audience == "lawyer" else "answer_layman")
    if not u or u.get("limit") is None or "used" not in u:
        return ""
    left = max(0, u["limit"] - u["used"])
    return f"{left} of {u['limit']} {'research notes' if audience == 'lawyer' else 'answers'} left today"


def topbar(person, acct):
    aud = "lawyer" if st.session_state.get("audience_choice") == "Lawyer" else "layman"
    cols = st.columns([5, 3, 2])
    cols[0].markdown(f'<p class="r-foot">Signed in as {_esc(person["email"])}</p>', unsafe_allow_html=True)
    cols[1].markdown(f'<p class="r-foot">{_esc(usage_line(acct, aud))}</p>', unsafe_allow_html=True)
    cols[2].button("Sign out", key="acct_signout", on_click=st.logout, use_container_width=True)
    with st.expander("My data and account"):
        st.markdown("You can download everything Recourse holds about you, or delete your account and all of it now. Deleting cannot be undone.")
        data = st.session_state.get("_export_json")
        if data is None and st.session_state.get("_want_export"):
            try:
                import json
                data = json.dumps(site_client.export_my_data(person), ensure_ascii=False, indent=2)
                st.session_state["_export_json"] = data         # fetched once, not on every rerun
            except site_client.ApiError:
                st.error("Could not prepare your data just now. Please try again.")
                st.session_state.pop("_want_export", None)
        if data is None:
            st.button("Prepare my data file", key="acct_export_prep", on_click=lambda: st.session_state.__setitem__("_want_export", True))
        else:
            st.download_button("Download my data (JSON)", data, file_name="recourse-my-data.json", mime="application/json", key="acct_export_dl",
                               on_click=lambda: [st.session_state.pop(k, None) for k in ("_export_json", "_want_export")])
        word = st.text_input("To delete your account and everything in it, type DELETE", key="acct_delete_word")
        if st.button("Delete my account now", key="acct_delete", disabled=(word != "DELETE")):
            try:
                site_client.delete_account(person)
            except site_client.ApiError as e:
                st.error("Could not delete just now (%s). Please try again." % e.code)
            else:
                for k in list(st.session_state.keys()):
                    st.session_state.pop(k, None)
                st.success("Your account and everything in it were deleted. You are being signed out.")
                st.logout()


# ------------------------------------------------------------------ asking
def _notice(label, title, body):
    return {"state": "account_notice", "notice": {"label": label, "title": title, "body": body}}


_LIMIT_TEXT = {
    "consent_required": ("Please accept the notice first", "Open the page again and accept the privacy notice and the terms to go on."),
    "turn_limit": ("This conversation is full", "A conversation can hold eight questions. Press Start a new question to go on."),
    "in_progress": ("Your last question is still being answered", "Wait a moment and look again; there is no need to ask twice."),
    "busy": ("Recourse is busy right now", "Many questions are being read at the moment. Please try again in a minute."),
    "rate_limited": ("Please slow down a little", "Too many requests came from your connection in a minute. Try again shortly."),
    "not_found": ("That conversation is gone", "Press Start a new question to begin again."),
}


def error_result(e):
    """The result the page draws for an ApiError (a notice for a person-level limit, the usual technical-trouble result for anything else)."""
    code = e.code
    if code == "limit_reached":
        u = (e.payload or {}).get("usage") or {}
        return _notice("Daily limit reached", "You have used today's answers", f"Your plan allows {u.get('limit', 'a fixed number of')} a day and they are used up. They come back at midnight, India time.")
    if code == "too_many_refusals":
        return _notice("Daily limit reached", "Too many questions Recourse could not take up", "Several of today's questions were ones Recourse cannot help with, and the daily limit on those is reached. It resets at midnight, India time.")
    if code.startswith("busy") or code == "busy, try again shortly":
        return _notice("Recourse is busy right now", *_LIMIT_TEXT["busy"])
    if code in _LIMIT_TEXT:
        return _notice("Your account", *_LIMIT_TEXT[code])
    if code in ("bad_token", "token_expired", "token_reused"):
        return _notice("Your account", "Your sign-in could not be checked", "Please sign out and sign in again.")
    return {"state": "retrieval_unavailable"}


def ask(question, audience, followup, on_step=None):
    """Asks through the API in a saved chat (a follow-up goes in the same chat; a new question, or a change of voice, starts a new one). -> the result dict the page draws; also keeps the answer's message id and the day's usage for the line and the report button."""
    person = current_user()
    if person is None:
        return _notice("Your account", "You are signed out", "Please sign in again.")
    chat_id = st.session_state.get("api_chat_id") if followup else None
    if chat_id and st.session_state.get("api_chat_audience") != audience:
        chat_id = None
    try:
        if not chat_id:
            chat_id = site_client.new_chat(person, audience)["id"]
            st.session_state["api_chat_id"], st.session_state["api_chat_audience"] = chat_id, audience
        reply = site_client.ask(person, chat_id, question, on_step=on_step)
    except site_client.ApiError as e:
        logger.warning("ask failed: %s", e.code)
        if e.code in ("consent_required",):
            st.session_state.pop("_acct", None)
        if e.code == "not_found":
            st.session_state.pop("api_chat_id", None)
        return error_result(e)
    st.session_state["api_meta"] = {"message_id": reply.get("message_id"), "saved": bool(reply.get("saved"))}
    u = reply.get("usage")
    acct = st.session_state.get("_acct")
    if acct is not None and isinstance(u, dict) and u.get("feature"):
        acct.setdefault("usage", {})[u["feature"]] = {"used": u.get("used"), "limit": u.get("limit"), "period": u.get("period"), "resets_at": u.get("resets_at")}
    st.session_state.pop("_feedback_sent", None)
    res = reply.get("result")
    return res if isinstance(res, dict) else {"state": "retrieval_unavailable"}


def after_answer(answer):
    """Under an answer: today's usage line and the 'report a problem' box. Does nothing for a notice or an unsaved answer."""
    meta = st.session_state.get("api_meta") or {}
    if not meta.get("message_id") or (answer or {}).get("state") == "account_notice":
        return
    acct = st.session_state.get("_acct") or {}
    aud = "lawyer" if st.session_state.get("api_chat_audience") == "lawyer" else "layman"
    line = usage_line(acct, aud)
    if line:
        st.markdown(f'<p class="r-foot">{_esc(line)}</p>', unsafe_allow_html=True)
    if st.session_state.get("_feedback_sent") == meta["message_id"]:
        st.markdown('<p class="r-foot">Thank you. Your report goes to the people who check Recourse every week.</p>', unsafe_allow_html=True)
        return
    with st.expander("Report a problem with this answer, or say it helped"):
        kinds = dict(FEEDBACK_KINDS)
        kind = st.radio("What is it?", list(kinds), format_func=lambda k: kinds[k], key="fb_kind")
        comment = st.text_area("Tell us more (optional). Please do not include names or phone numbers.", key="fb_comment", max_chars=2000)
        if st.button("Send", key="fb_send"):
            person = current_user()
            try:
                site_client.feedback(person, meta["message_id"], kind, comment or None)
                st.session_state["_feedback_sent"] = meta["message_id"]
                st.rerun()
            except site_client.ApiError as e:
                st.error("Could not send just now (%s). Please try again." % e.code)

"""
api/db/seed.py -- loads plans.json into the plans and entitlements tables (step A2). Safe to run any number of times: a plan is matched by its code; an entitlement is added as version 1, and if its numbers later
change in plans.json a NEW version is added (the old one stays as history; the highest version is in force). Nothing is ever deleted here.
"""
import json
import os

from sqlalchemy import select

from .models import Entitlement, Plan

PLANS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plans.json")


def load_config(path=PLANS_FILE):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    codes = [p["code"] for p in cfg["plans"]]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate plan code in plans.json")
    for p in cfg["plans"]:
        feats = [e["feature"] for e in p["entitlements"]]
        if len(set(feats)) != len(feats):
            raise ValueError(f"duplicate feature in plan {p['code']}")
        for e in p["entitlements"]:
            if e["period"] not in ("day", "month", "none"):
                raise ValueError(f"bad period {e['period']!r} in plan {p['code']}")
            if e["limit"] is not None and (not isinstance(e["limit"], int) or isinstance(e["limit"], bool) or e["limit"] < 0):
                raise ValueError(f"bad limit {e['limit']!r} in plan {p['code']}")
    return cfg


def seed(session, cfg=None):
    """Returns {'plans_added': n, 'entitlements_added': n}. The caller commits."""
    cfg = cfg or load_config()
    added = {"plans_added": 0, "entitlements_added": 0}
    for p in cfg["plans"]:
        plan = session.execute(select(Plan).where(Plan.code == p["code"])).scalar_one_or_none()
        if plan is None:
            plan = Plan(code=p["code"], name=p["name"], sort=p.get("sort", 0))
            session.add(plan)
            session.flush()
            added["plans_added"] += 1
        else:
            plan.name, plan.sort = p["name"], p.get("sort", 0)
        for e in p["entitlements"]:
            latest = session.execute(select(Entitlement).where(Entitlement.plan_id == plan.id, Entitlement.feature == e["feature"]).order_by(Entitlement.version.desc()).limit(1)).scalar_one_or_none()
            if latest is None:
                version = 1
            elif latest.period == e["period"] and latest.limit_count == e["limit"]:
                continue
            else:
                version = latest.version + 1
            session.add(Entitlement(plan_id=plan.id, feature=e["feature"], period=e["period"], limit_count=e["limit"], version=version))
            added["entitlements_added"] += 1
    session.flush()
    return added

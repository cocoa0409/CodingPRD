"""Shared business helpers: records, serialization, derived posture,
automatic state advancements, capacity windows, pagination."""
import math
from datetime import datetime

from db import fmt_dt, new_id, next_seq, now, store
from envelope import success_list
from errors import ApiError, ERR_NOT_FOUND
from validate import page_params

OPEN_DISPUTE_STATES = ("OPEN", "IN_REVIEW")
PROJECT_TERMINAL = ("VERIFIED", "CANCELLED")
ENGAGEMENT_TERMINAL = ("COMPLETE_ON_TIME", "COMPLETE_LATE", "CANCELLED", "DISPUTED")
DISPUTE_TERMINAL = ("RESOLVED_VENDOR_FAULT", "RESOLVED_HOMEOWNER_FAULT", "WITHDRAWN")


def new_record(fields):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def bump(rec):
    """version +1 and updated_at refresh on every mutation (PRD 2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now()


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = fmt_dt(v) if isinstance(v, datetime) else v
    return out


def get_or_404(table, rid, label="Resource"):
    rec = table.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "%s not found" % label, 404)
    return rec


def sorted_items(items):
    """Lists sort by created_at ascending; insertion order breaks ties."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(items):
    ordered = sorted_items(items)
    limit, offset = page_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


# --- collection filters -------------------------------------------------------

def case_projects(case_id):
    return [p for p in store.projects.values() if p["concierge_case_id"] == case_id]


def case_disbursements(case_id):
    return [d for d in store.disbursements.values() if d["concierge_case_id"] == case_id]


def case_disputes(case_id):
    return [d for d in store.disputes.values() if d["concierge_case_id"] == case_id]


def case_listing_events(case_id):
    return [e for e in store.listing_events.values() if e["concierge_case_id"] == case_id]


def project_engagements(project_id):
    return [e for e in store.engagements.values() if e["improvement_project_id"] == project_id]


def project_change_orders(project_id):
    return [c for c in store.change_orders.values() if c["improvement_project_id"] == project_id]


def project_disputes(project_id):
    return [d for d in store.disputes.values() if d["improvement_project_id"] == project_id]


# --- derived state ------------------------------------------------------------

def latest_market_risk(case_id):
    """market_risk_flag of the case's most recently recorded listing event."""
    events = case_listing_events(case_id)
    if not events:
        return False
    latest = max(events, key=lambda e: e["_seq"])
    return bool(latest.get("market_risk_flag"))


def recompute_posture(case):
    """OPEN / RESTRICTED / FROZEN from open disputes and market risk (PRD 2.9)."""
    has_open = any(d["status"] in OPEN_DISPUTE_STATES for d in case_disputes(case["id"]))
    risk = latest_market_risk(case["id"])
    new = "FROZEN" if (has_open and risk) else ("RESTRICTED" if has_open else "OPEN")
    if case.get("posture") != new:
        case["posture"] = new
        bump(case)


def maybe_project_complete(project):
    """IN_WORK -> COMPLETE once every non-CANCELLED engagement is complete."""
    if project["status"] != "IN_WORK":
        return
    active = [e for e in project_engagements(project["id"]) if e["status"] != "CANCELLED"]
    if active and all(e["status"] in ("COMPLETE_ON_TIME", "COMPLETE_LATE") for e in active):
        project["status"] = "COMPLETE"
        bump(project)


def maybe_case_ready(case):
    """IN_PROGRESS -> READY_TO_LIST when all projects are VERIFIED/CANCELLED
    and no dispute on the case is OPEN or IN_REVIEW."""
    if case["status"] != "IN_PROGRESS":
        return
    projects = case_projects(case["id"])
    if not all(p["status"] in PROJECT_TERMINAL for p in projects):
        return
    if any(d["status"] in OPEN_DISPUTE_STATES for d in case_disputes(case["id"])):
        return
    case["status"] = "READY_TO_LIST"
    bump(case)


def engagement_has_dispute(engagement_id):
    return any(d["vendor_engagement_id"] == engagement_id for d in store.disputes.values())


# --- vendor capacity ----------------------------------------------------------

def compute_required_crew_days(start, end):
    """Crew-days needed across the scheduled span [start_date, end_date)."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))


def find_capacity_window(vendor_id, start, end, required):
    """Earliest OPEN window overlapping [start, end) with enough headroom.
    Overlap is strict: start < window_end AND end > window_start (half-open)."""
    matches = [
        w for w in store.capacity_windows.values()
        if w["vendor_id"] == vendor_id
        and w["status"] == "OPEN"
        and start < w["window_end"]
        and end > w["window_start"]
        and w["reserved_crew_days"] + required <= w["capacity_crew_days"]
    ]
    if not matches:
        return None
    matches.sort(key=lambda w: (w["created_at"], w["_seq"]))
    return matches[0]


def release_reservation(eng):
    wid = eng.get("_reserved_window_id")
    if not wid:
        return
    w = store.capacity_windows.get(wid)
    if w is not None:
        w["reserved_crew_days"] = max(0, w["reserved_crew_days"] - eng.get("_reserved_days", 0))
        if w["status"] == "FULL" and w["reserved_crew_days"] < w["capacity_crew_days"]:
            w["status"] = "OPEN"
        bump(w)
    eng["_reserved_window_id"] = None
    eng["_reserved_days"] = 0

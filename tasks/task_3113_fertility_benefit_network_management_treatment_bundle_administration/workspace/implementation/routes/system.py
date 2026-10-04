"""System-driving operations and the time-driven sweeps (PRD 2.6)."""

from flask import request

from clock import (
    CLAIM_PEND_AFTER_DAYS,
    PREGNANCY_TEST_DAYS,
    PREROUTE_LEAD_DAYS,
    STORAGE_RETENTION_DAYS,
    SUBMITTED_EXPIRY_HOURS,
    fmt_now_string,
    parse_dt,
)
from db import db
from errors import APIError
from helpers import recompute_bundle
from bp import api
from response import ok

# Set while a sweep is running so nested recomputes do not re-enter the sweep.
SWEEPING = {"active": False}


@api.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    data = request.get_json(silent=True) or {}
    current_utc = data.get("current_utc")
    if not current_utc:
        raise APIError("ERR_INVALID_REQUEST", "The required input 'current_utc' is missing.")
    db.clock.set(current_utc)
    return ok({"current_utc": fmt_now_string(db.clock.now)}, "object", 200)


def _pending_deadlines():
    """Every instant at which a scheduled transition would come due."""
    deadlines = []
    now = db.now()
    for pa in db.all("preauthorizations"):
        if pa["review_status"] in ("SUBMITTED", "CLINICAL_REVIEW"):
            submitted = parse_dt(pa["created_at"])
            if submitted is not None:
                deadlines.append(submitted + _hours(SUBMITTED_EXPIRY_HOURS))
    for cycle in db.all("treatment_cycles"):
        if cycle["cycle_status"] == "TRANSFER" and cycle.get("transfer_date"):
            transfer = parse_dt(cycle["transfer_date"])
            if transfer is not None:
                deadlines.append(transfer + _days(PREGNANCY_TEST_DAYS))
    for claim in db.all("claims"):
        if claim["claim_status"] == "RECEIVED":
            service = claim.get("_service_date") or parse_dt(claim.get("created_at"))
            if service is not None:
                deadlines.append(service + _days(CLAIM_PEND_AFTER_DAYS))
    for route in db.all("surrender_routes"):
        if route["route_status"] == "SUBMITTED" and route.get("route_from"):
            start = parse_dt(route["route_from"])
            if start is not None:
                deadlines.append(start - _days(PREROUTE_LEAD_DAYS))
    for route in db.all("surrender_routes"):
        if route["route_status"] == "ROUTED" and route.get("route_to"):
            end = parse_dt(route["route_to"])
            if end is not None:
                deadlines.append(end + _days(STORAGE_RETENTION_DAYS))
    return [d for d in deadlines if d > now]


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)


def _hours(n):
    from datetime import timedelta
    return timedelta(hours=n)


def run_sweep():
    """Fire every time-driven transition whose deadline the clock has reached."""
    fired = 0
    now = db.now()

    # Authorizations awaiting a decision expire past the submission-expiry interval.
    for pa in db.all("preauthorizations"):
        if pa["review_status"] not in ("SUBMITTED", "CLINICAL_REVIEW"):
            continue
        submitted = parse_dt(pa["created_at"])
        if submitted is None:
            continue
        if now >= submitted + _hours(SUBMITTED_EXPIRY_HOURS):
            pa["review_status"] = "EXPIRED"
            pa["denial_reason_code"] = "EXPIRED_NO_DECISION"
            db.touch(pa)
            fired += 1

    # Cycles that have reached TRANSFER move on once the pregnancy test is due.
    for cycle in db.all("treatment_cycles"):
        if cycle["cycle_status"] != "TRANSFER" or not cycle.get("transfer_date"):
            continue
        transfer = parse_dt(cycle["transfer_date"])
        if transfer is None:
            continue
        if now >= transfer + _days(PREGNANCY_TEST_DAYS):
            cycle["cycle_status"] = "OUTCOME_PENDING"
            db.touch(cycle)
            fired += 1

    # Claims still in RECEIVED pend once the late-submission interval has run.
    for claim in db.all("claims"):
        if claim["claim_status"] != "RECEIVED":
            continue
        service = claim.get("_service_date") or parse_dt(claim.get("created_at"))
        if service is None:
            continue
        if now >= service + _days(CLAIM_PEND_AFTER_DAYS):
            claim["claim_status"] = "PENDED"
            claim["pended_reason"] = "SUBMITTED_LATE_REQUIRES_DOCUMENTATION"
            db.touch(claim)
            fired += 1

    # Surrender routes route once the pre-route lead time has elapsed.
    for route in db.all("surrender_routes"):
        if route["route_status"] != "SUBMITTED" or not route.get("route_from"):
            continue
        start = parse_dt(route["route_from"])
        if start is None:
            continue
        if now >= start - _days(PREROUTE_LEAD_DAYS):
            route["route_status"] = "ROUTED"
            db.touch(route)
            member = db.find("members", route["member_id"])
            if member is not None:
                db.touch(member)
            fired += 1

    # A routed route retires once the storage retention period has closed.
    for route in db.all("surrender_routes"):
        if route["route_status"] != "ROUTED" or not route.get("route_to"):
            continue
        end = parse_dt(route["route_to"])
        if end is None:
            continue
        if now >= end + _days(STORAGE_RETENTION_DAYS):
            route["route_status"] = "RETIRED"
            db.touch(route)
            member = db.find("members", route["member_id"])
            if member is not None:
                db.touch(member)
            fired += 1

    # Bundles drawn by expired authorizations recompute their netting.
    touched_bundles = set()
    for pa in db.all("preauthorizations"):
        plan = db.find("treatment_plans", pa["treatment_plan_id"])
        if plan is not None:
            touched_bundles.add(plan["bundle_entitlement_id"])
    for bundle_id in touched_bundles:
        bundle = db.find("bundle_entitlements", bundle_id)
        if bundle is not None:
            recompute_bundle(db, bundle)
    return fired


@api.route("/_system/tick", methods=["POST"])
def tick():
    if SWEEPING["active"]:
        return ok({"advanced_to": fmt_now_string(db.now()), "transitions_fired": 0}, "object", 200)
    SWEEPING["active"] = True
    try:
        # Fire every transition whose deadline the logical clock has already
        # reached.  The clock advances to the earliest still-pending deadline
        # only when nothing was ripe yet, so a sweep never runs past a
        # deadline that a later caller still expects to be reachable.
        fired = run_sweep()
        if fired == 0:
            pending = _pending_deadlines()
            if pending:
                db.clock.advance_to(min(pending))
                fired += run_sweep()
    finally:
        SWEEPING["active"] = False
    return ok({"advanced_to": fmt_now_string(db.now()), "transitions_fired": fired}, "object", 200)
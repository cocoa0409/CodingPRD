"""Reentry provider and referral endpoints: provider registry, capacity-gated
referral creation over half-open service windows, and the referral lifecycle
with slot accounting on the provider."""

from flask import Blueprint, request

import db
from auth import STAFF_ROLES, require_roles
from calculations import overlapping_live_referrals
from clock import CLOCK, parse_iso
from db import touch
from envelope import ok
from errors import (
    ERR_CASE_NOT_EXONERATED,
    ERR_CASE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_PROVIDER_CAPACITY_EXCEEDED,
    ERR_REENTRY_PROVIDER_NOT_FOUND,
    ERR_REENTRY_REFERRAL_NOT_FOUND,
    ERR_SERVICE_WINDOW_NOT_STARTED,
    raise_err,
)
from validation import (
    as_string,
    body_json,
    paged_list,
    reject_unknown,
    req_choice,
    req_datetime,
    req_field,
    req_int,
    req_str,
)

bp = Blueprint("reentry", __name__)

SERVICE_TYPES = ("HOUSING", "EMPLOYMENT", "MEDICAL", "COUNSELING")
ADVANCE_EVENTS = ("ACTIVATE", "COMPLETE", "CANCEL")


@bp.post("/reentry-providers")
def create_reentry_provider():
    require_roles("ClientServicesAdvocate")
    body = body_json()
    reject_unknown(body, {"name", "service_type", "total_capacity"})
    provider = db.new_entity()
    provider.update({
        "name": req_str(body, "name"),
        "service_type": req_choice(body, "service_type", SERVICE_TYPES),
        "total_capacity": req_int(body, "total_capacity", minimum=1),
        "slots_in_use": 0,
    })
    db.reentry_providers[provider["id"]] = provider
    return ok(provider, 201)


@bp.get("/reentry-providers/<pid>")
def get_reentry_provider(pid):
    require_roles(*STAFF_ROLES)
    provider = db.lookup(db.reentry_providers, pid, ERR_REENTRY_PROVIDER_NOT_FOUND)
    return ok(provider)


@bp.get("/reentry-providers/<pid>/reentry-referrals")
def list_provider_referrals(pid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.reentry_providers, pid, ERR_REENTRY_PROVIDER_NOT_FOUND)
    items = [r for r in db.reentry_referrals.values() if r["provider_id"] == pid]
    return paged_list(items, {"status": request.args.get("status")})


@bp.post("/reentry-referrals")
def create_reentry_referral():
    require_roles("ClientServicesAdvocate")
    body = body_json()
    # priority 3: body-id existence in payload field order
    if "case_id" in body:
        db.lookup(db.cases, body.get("case_id"), ERR_CASE_NOT_FOUND)
    if "provider_id" in body:
        db.lookup(db.reentry_providers, body.get("provider_id"),
                  ERR_REENTRY_PROVIDER_NOT_FOUND)
    reject_unknown(body, {"case_id", "provider_id", "service_start", "service_end"})
    case_id = req_str(body, "case_id")
    provider_id = req_str(body, "provider_id")
    service_start = req_datetime(body, "service_start")
    service_end = req_datetime(body, "service_end")
    start_dt = parse_iso(service_start)
    end_dt = parse_iso(service_end)
    if end_dt <= start_dt:
        raise_err(ERR_INVALID_REQUEST,
                  "service_end must be strictly after service_start")
    case = db.cases[case_id]
    # priority 4.5: the case must be EXONERATED
    if case["status"] != "EXONERATED":
        raise_err(ERR_CASE_NOT_EXONERATED,
                  "Referral creation requires an EXONERATED case")
    # priority 8(d): overlapping-window capacity aggregate
    provider = db.reentry_providers[provider_id]
    if overlapping_live_referrals(provider_id, start_dt, end_dt) >= provider["total_capacity"]:
        raise_err(ERR_PROVIDER_CAPACITY_EXCEEDED,
                  "The provider is at capacity for that service window")
    referral = db.new_entity()
    referral.update({
        "case_id": case_id,
        "provider_id": provider_id,
        "service_start": service_start,
        "service_end": service_end,
        "status": "PENDING",
    })
    db.reentry_referrals[referral["id"]] = referral
    provider["slots_in_use"] += 1
    touch(provider)
    return ok(referral, 201)


@bp.post("/reentry-referrals/<rid>/advance")
def advance_reentry_referral(rid):
    require_roles("ClientServicesAdvocate")
    referral = db.lookup(db.reentry_referrals, rid, ERR_REENTRY_REFERRAL_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for reentry-referral advance: %s" % event)
    status = referral["status"]
    if event == "ACTIVATE":
        if status != "PENDING":
            raise_err(ERR_INVALID_STATE, "ACTIVATE requires status PENDING")
        if CLOCK.now_dt() < parse_iso(referral["service_start"]):
            raise_err(ERR_SERVICE_WINDOW_NOT_STARTED,
                      "The service window has not started")
        # PENDING already occupies a slot; activation changes no accounting
        referral["status"] = "ACTIVE"
    elif event == "COMPLETE":
        if status != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "COMPLETE requires status ACTIVE")
        referral["status"] = "COMPLETED"
        provider = db.reentry_providers.get(referral["provider_id"])
        if provider is not None:
            provider["slots_in_use"] -= 1
            touch(provider)
    else:  # CANCEL
        if status not in ("PENDING", "ACTIVE"):
            raise_err(ERR_INVALID_STATE,
                      "CANCEL requires status PENDING or ACTIVE")
        referral["status"] = "CANCELLED"
        provider = db.reentry_providers.get(referral["provider_id"])
        if provider is not None:
            provider["slots_in_use"] -= 1
            touch(provider)
    touch(referral)
    return ok(referral)

"""Lapsed-certification reentry (PRD §3.7): tier assignment by lapse duration,
fresh 24-month cycle on approval."""

from flask import Blueprint, request

from db import (STORE, TIER1_MAX_LAPSE_MONTHS, TIER2_MAX_LAPSE_MONTHS,
                base_entity, disciplinary_hold, now_dt, serialize, touch)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_number,
                        req_enum, req_str)
from util import add_months, whole_months_between

bp = Blueprint("reentry", __name__)


@bp.post("/registry/reentry-applications")
def create_reentry():
    uid, _ = authn(["Candidate"])
    b = body()
    certification_id = req_str(b, "certification_id")
    ce_makeup = opt_number(b, "ce_makeup_hours_claimed", None)
    refresher = opt_number(b, "refresher_hours_claimed", None)
    if ce_makeup is not None and float(ce_makeup) <= 0:
        raise_err("ERR_INVALID_REQUEST", "ce_makeup_hours_claimed must be positive")
    if refresher is not None and float(refresher) <= 0:
        raise_err("ERR_INVALID_REQUEST", "refresher_hours_claimed must be positive")

    cert = STORE.certifications.get(certification_id)
    if not cert:
        raise_err("ERR_NOT_FOUND", "Certification %s does not exist" % certification_id)
    if cert["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may apply for reentry")
    if cert["status"] != "LAPSED":
        raise_err("ERR_CERTIFICATION_NOT_LAPSED",
                  "Certification is %s, not LAPSED" % cert["status"])

    candidate = STORE.candidates.get(uid)
    if candidate and candidate["status"] == "BARRED":
        raise_err("ERR_PERMANENTLY_BARRED", "Candidate is BARRED")
    if disciplinary_hold(uid):
        raise_err("ERR_DISCIPLINARY_HOLD",
                  "Candidate is under a HOLD_NEW_APPLICATIONS interim action")

    now = now_dt()
    expires = cert["expires_on"]
    if now <= add_months(expires, TIER1_MAX_LAPSE_MONTHS):
        tier = "TIER_CE_ONLY"
    elif now <= add_months(expires, TIER2_MAX_LAPSE_MONTHS):
        tier = "TIER_REFRESHER"
    else:
        raise_err("ERR_REENTRY_NOT_AVAILABLE",
                  "Lapse exceeds 24 months; full re-examination is required")

    e = base_entity()
    e.update({
        "certification_id": certification_id,
        "candidate_id": uid,
        "lapse_months_at_submission": whole_months_between(expires, now),
        "tier": tier,
        "ce_makeup_hours_claimed": ce_makeup,
        "refresher_hours_claimed": refresher,
        "status": "SUBMITTED",
        "decided_at": None,
    })
    STORE.reentries[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/reentry-applications")
def list_reentries():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    certification_id = request.args.get("certification_id")
    status = request.args.get("status")
    items = []
    for a in STORE.reentries.values():
        if candidate_id is not None and a["candidate_id"] != candidate_id:
            continue
        if certification_id is not None and a["certification_id"] != certification_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(a) for a in page], total, limit, offset)


@bp.get("/registry/reentry-applications/<rid>")
def get_reentry(rid):
    authn(ALL_AUTHENTICATED_ROLES)
    a = STORE.reentries.get(rid)
    if not a:
        raise_err("ERR_NOT_FOUND", "ReentryApplication %s does not exist" % rid)
    return ok_object(serialize(a), 200)


@bp.post("/registry/reentry-applications/<rid>/decision")
def decide_reentry(rid):
    authn(["RegistryAdmin"])
    b = body()
    outcome = req_enum(b, "outcome", ["APPROVED", "DENIED"])
    app = STORE.reentries.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "ReentryApplication %s does not exist" % rid)
    if app["status"] != "SUBMITTED":
        raise_err("ERR_REENTRY_NOT_SUBMITTED",
                  "Reentry application is %s, not SUBMITTED" % app["status"])
    if outcome == "DENIED":
        app["status"] = "DENIED"
        app["decided_at"] = now_dt()
        touch(app)
        return ok_object(serialize(app), 200)

    cert = STORE.certifications.get(app["certification_id"])
    if not cert or cert["status"] != "LAPSED":
        raise_err("ERR_CERTIFICATION_NOT_LAPSED",
                  "Certification must still be LAPSED at approval")
    level = STORE.levels.get(cert["level_id"])
    if app["tier"] == "TIER_CE_ONLY":
        required = float(level["ce_total_hours"]) if level else 0.0
        claimed = app.get("ce_makeup_hours_claimed")
        if claimed is None or float(claimed) < required:
            raise_err("ERR_REENTRY_REQUIREMENTS_UNMET",
                      "TIER_CE_ONLY requires ce_makeup_hours_claimed >= %s" % required)
    else:
        required = float(level["refresher_hours_required"]) if level else 0.0
        claimed = app.get("refresher_hours_claimed")
        if claimed is None or float(claimed) < required:
            raise_err("ERR_REENTRY_REQUIREMENTS_UNMET",
                      "TIER_REFRESHER requires refresher_hours_claimed >= %s" % required)

    # Reinstatement: fresh cycle from the approval instant (NOT anniversary).
    now = now_dt()
    cert["status"] = "ACTIVE"
    cert["expires_on"] = add_months(now, 24)
    cert["lapse_deadline"] = add_months(cert["expires_on"], 48)
    touch(cert)
    app["status"] = "APPROVED"
    app["decided_at"] = now
    touch(app)
    return ok_object(serialize(app), 200)

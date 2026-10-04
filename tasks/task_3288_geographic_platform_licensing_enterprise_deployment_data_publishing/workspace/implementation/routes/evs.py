"""Eligibility verifications (§3.8)."""
from flask import Blueprint, request

import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import get_body, require_fields

bp = Blueprint("evs", __name__)

PROGRAM_KINDS = "EDUCATION_PROGRAM|NONPROFIT_PROGRAM"
APPROVAL_WINDOW_PERIODS = 12


@bp.post("/geo-orgs/eligibility-verifications")
def create_ev():
    caller_id, role = require_role("NamedUser")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("program_kind", "enum:" + PROGRAM_KINDS, True),
        ("evidence_document_ref", "str", True),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "program_kind": body["program_kind"],
        "submitted_by_named_user_id": caller_id,
        "evidence_document_ref": body["evidence_document_ref"],
        "decided_by_named_user_id": None,
        "decision_rationale": None,
        "valid_through_period": None,
        "status": "SUBMITTED",
    })
    store.eligibility_verifications[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/eligibility-verifications")
def list_evs():
    require_role("ComplianceOfficer", "PlatformAdmin", "LicenseAdmin", "NamedUser")
    items = sorted(store.eligibility_verifications.values(), key=lambda r: r["created_at"])
    for param in ("organization_id", "status", "program_kind"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[param] == v]
    page, pg = paginate(items, request.args)
    return success([dict(e) for e in page], pagination=pg)


@bp.get("/geo-orgs/eligibility-verifications/<ev_id>")
def get_ev(ev_id):
    require_role("ComplianceOfficer", "PlatformAdmin", "LicenseAdmin", "NamedUser")
    ev = store.eligibility_verifications.get(ev_id)
    if ev is None:
        raise err("ERR_EV_NOT_FOUND")
    return success(dict(ev))


@bp.post("/geo-orgs/eligibility-verifications/<ev_id>/transition")
def ev_transition(ev_id):
    caller_id, role = require_role("ComplianceOfficer", "NamedUser")
    body = get_body()
    require_fields(body, [
        ("target_status", "enum:UNDER_REVIEW|APPROVED|REJECTED", True),
        ("decision_rationale", "str", False),
        ("evidence_document_ref", "str", False),
    ])
    ev = store.eligibility_verifications.get(ev_id)
    if ev is None:
        raise err("ERR_EV_NOT_FOUND")
    target = body["target_status"]
    org = store.orgs.get(ev["organization_id"])

    if target == "UNDER_REVIEW":
        if ev["status"] == "SUBMITTED":
            if role != "ComplianceOfficer":
                raise err("ERR_INSUFFICIENT_PERMISSIONS",
                          "begin-review requires ComplianceOfficer")
            ev["status"] = "UNDER_REVIEW"
            store.touch(ev)
        elif ev["status"] == "RENEWAL_REQUIRED":
            # Resubmission by a NamedUser with fresh evidence
            if role != "NamedUser":
                raise err("ERR_INSUFFICIENT_PERMISSIONS", "resubmit requires NamedUser")
            new_ref = body.get("evidence_document_ref")
            if not new_ref or new_ref == ev["evidence_document_ref"]:
                raise err("ERR_STALE_EVIDENCE")
            ev["evidence_document_ref"] = new_ref
            ev["submitted_by_named_user_id"] = caller_id
            ev["status"] = "UNDER_REVIEW"
            store.touch(ev)
        else:
            raise err("ERR_EV_NOT_SUBMITTED" if ev["status"] not in ("UNDER_REVIEW",)
                      else "ERR_EV_NOT_RENEWAL_REQUIRED")
    elif target in ("APPROVED", "REJECTED"):
        if role != "ComplianceOfficer":
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "decide requires ComplianceOfficer")
        if ev["status"] != "UNDER_REVIEW":
            raise err("ERR_EV_NOT_UNDER_REVIEW")
        rationale = body.get("decision_rationale")
        if not rationale:
            raise err("ERR_INVALID_EV_DECISION")
        if caller_id == ev["submitted_by_named_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION")
        ev["decided_by_named_user_id"] = caller_id
        ev["decision_rationale"] = rationale
        ev["status"] = target
        if target == "APPROVED":
            current_period = org["current_period_index"] if org else 0
            ev["valid_through_period"] = current_period + APPROVAL_WINDOW_PERIODS
        store.touch(ev)
    return success(dict(ev))

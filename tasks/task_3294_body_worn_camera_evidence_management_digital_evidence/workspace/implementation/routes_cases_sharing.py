import uuid

from flask import Blueprint, request

import db
from errors import (
    err_active_share_grants, err_case_empty, err_evidence_not_ready,
    err_grant_expired, err_integrity_failed, err_invalid_state,
    err_legal_hold_active, err_no_active_policy, err_not_found,
    err_reviews_outstanding, err_stale_version, err_unauthorized,
    err_validation,
)
from helpers import (
    SYSTEM_ACTOR, active_policy, add_days, body, get_agency_or_404, get_scoped,
    iso_now, new_resource, paginate, parse_dt, reject_unknown, require_enum,
    require_int, require_str, success_obj, touch, write_audit, write_custody,
)
from middleware import authenticate, require_roles
import services

bp = Blueprint("cases_sharing", __name__)


def _case_links(case_id, status=None):
    out = []
    for link in db.collection("links").values():
        if link["case_id"] != case_id:
            continue
        if status and link["status"] != status:
            continue
        out.append(link)
    return out


def _active_grant_on_case(case_id):
    for g in db.collection("share_grants").values():
        if g["case_id"] == case_id and g["status"] == "ACTIVE":
            return g
    return None


def _active_case_hold(case_id):
    for h in db.collection("legal_holds").values():
        if (h.get("case_id") == case_id and h["scope_type"] == "CASE"
                and h["status"] == "ACTIVE"):
            return h
    return None


# ---------------------------------------------------------------- cases

@bp.route("/agencies/<agency_id>/cases", methods=["POST"])
def create_case(agency_id):
    actor = authenticate()
    require_roles(actor, "Officer", "Supervisor", "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"case_number", "title", "lead_officer_id"})
    case_number = require_str(data, "case_number")
    title = require_str(data, "title")
    lead_id = require_str(data, "lead_officer_id")
    lead = db.collection("officers").get(lead_id)
    if lead is None or lead["agency_id"] != agency["id"]:
        raise err_not_found("Lead officer not found")
    for c in db.collection("cases").values():
        if (c["agency_id"] == agency["id"] and c["case_number"] == case_number
                and c["status"] != "ARCHIVED"):
            raise err_validation("case_number already in use")
    case = new_resource({
        "agency_id": agency["id"],
        "case_number": case_number,
        "title": title,
        "status": "OPEN",
        "lead_officer_id": lead_id,
        "evidence_count": 0,
        "total_evidence_bytes": 0,
        "retention_due_at": None,
    })
    db.collection("cases")[case["id"]] = case
    return success_obj(case, 201)


@bp.route("/agencies/cases", methods=["GET"])
def list_cases():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    items = list(db.collection("cases").values())
    for param in ("agency_id", "status", "lead_officer_id"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if str(c.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/<agency_id>/cases/<case_id>", methods=["GET"])
def get_case(agency_id, case_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    return success_obj(case)


@bp.route("/agencies/cases/<case_id>", methods=["GET"])
def get_case_flat(case_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    case = db.collection("cases").get(case_id)
    if case is None:
        raise err_not_found("Case not found")
    return success_obj(case)


def _case_action(agency_id, case_id):
    actor = authenticate()
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    return actor, agency, case


@bp.route("/agencies/<agency_id>/cases/<case_id>/submit-review", methods=["POST"])
def submit_review(agency_id, case_id):
    actor, agency, case = _case_action(agency_id, case_id)
    require_roles(actor, "Officer")
    if case["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN case can be submitted for review")
    links = _case_links(case["id"], status="LINKED")
    if len(links) < 1:
        raise err_case_empty()
    for link in links:
        r = db.collection("recordings").get(link["recording_id"])
        if r is None or r["upload_status"] not in ("ACTIVE", "RETENTION_DUE"):
            raise err_evidence_not_ready()
    case["status"] = "UNDER_REVIEW"
    touch(case)
    write_audit(agency["id"], actor, "CASE_SUBMITTED", "CaseEntity",
                case["id"], "status OPEN -> UNDER_REVIEW")
    return success_obj(case)


@bp.route("/agencies/<agency_id>/cases/<case_id>/close", methods=["POST"])
def close_case(agency_id, case_id):
    actor, agency, case = _case_action(agency_id, case_id)
    require_roles(actor, "Supervisor")
    if case["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW case can be closed")
    for link in _case_links(case["id"], status="LINKED"):
        r = db.collection("recordings").get(link["recording_id"])
        if r is not None and r["review_status"] == "PENDING_REVIEW":
            raise err_reviews_outstanding()
    case["status"] = "CLOSED"
    touch(case)
    write_audit(agency["id"], actor, "CASE_CLOSED", "CaseEntity",
                case["id"], "status UNDER_REVIEW -> CLOSED")
    return success_obj(case)


@bp.route("/agencies/<agency_id>/cases/<case_id>/reopen", methods=["POST"])
def reopen_case(agency_id, case_id):
    actor, agency, case = _case_action(agency_id, case_id)
    require_roles(actor, "Supervisor")
    if case["status"] not in ("UNDER_REVIEW", "CLOSED"):
        raise err_invalid_state("Only an UNDER_REVIEW or CLOSED case can be reopened")
    case["status"] = "OPEN"
    touch(case)
    write_audit(agency["id"], actor, "CASE_REOPENED", "CaseEntity",
                case["id"], "status -> OPEN")
    return success_obj(case)


@bp.route("/agencies/<agency_id>/cases/<case_id>/archive", methods=["POST"])
def archive_case(agency_id, case_id):
    actor, agency, case = _case_action(agency_id, case_id)
    require_roles(actor, "RecordsOfficer")
    if case["status"] != "CLOSED":
        raise err_invalid_state("Only a CLOSED case can be archived")
    if _active_grant_on_case(case["id"]) is not None:
        raise err_active_share_grants()
    if _active_case_hold(case["id"]) is not None:
        raise err_legal_hold_active()
    case["status"] = "ARCHIVED"
    touch(case)
    write_audit(agency["id"], actor, "CASE_ARCHIVED", "CaseEntity",
                case["id"], "status CLOSED -> ARCHIVED")
    return success_obj(case)


# ---------------------------------------------------------------- evidence links

@bp.route("/agencies/<agency_id>/cases/<case_id>/evidence", methods=["POST"])
def link_evidence(agency_id, case_id):
    actor = authenticate()
    require_roles(actor, "Officer", "Supervisor")
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    if case["status"] != "OPEN":
        raise err_invalid_state("Evidence can only be linked to an OPEN case")
    data = body()
    reject_unknown(data, {"recording_id"})
    recording_id = require_str(data, "recording_id")
    recording = db.collection("recordings").get(recording_id)
    if recording is None or recording["agency_id"] != agency["id"]:
        raise err_not_found("Recording not found")
    if recording["upload_status"] == "INTEGRITY_FAILED":
        raise err_integrity_failed()
    if recording["upload_status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE recording can be linked")

    link = new_resource({
        "agency_id": agency["id"],
        "case_id": case["id"],
        "recording_id": recording["id"],
        "linked_by_officer_id": actor["user_id"],
        "status": "LINKED",
        "unlinked_at": None,
    })
    db.collection("links")[link["id"]] = link

    services.compute_recording_retention(recording)
    services.recompute_legal_hold_count(recording)
    touch(recording)
    services.touch_case(case)
    write_custody(agency["id"], recording["id"], "CASE_LINKED", actor)
    return success_obj(link, 201)


@bp.route("/agencies/<agency_id>/cases/<case_id>/evidence", methods=["GET"])
def list_case_evidence(agency_id, case_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    items = _case_links(case["id"])
    status = request.args.get("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return paginate(items)


@bp.route("/agencies/evidence-links", methods=["GET"])
def list_evidence_links():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    items = list(db.collection("links").values())
    for param in ("agency_id", "case_id", "recording_id", "linked_by_officer_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if str(l.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/evidence-links/<link_id>", methods=["GET"])
def get_evidence_link(link_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    link = db.collection("links").get(link_id)
    if link is None:
        raise err_not_found("Evidence link not found")
    return success_obj(link)


@bp.route("/agencies/<agency_id>/cases/<case_id>/evidence/<link_id>", methods=["DELETE"])
def unlink_evidence(agency_id, case_id, link_id):
    actor = authenticate()
    require_roles(actor, "Officer", "Supervisor")
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    link = db.collection("links").get(link_id)
    if link is None or link["case_id"] != case["id"]:
        raise err_not_found("Evidence link not found")
    if case["status"] != "OPEN":
        raise err_invalid_state("Evidence can only be unlinked while the case is OPEN")
    if link["status"] != "LINKED":
        raise err_invalid_state("Link is already UNLINKED")
    if _active_grant_on_case(case["id"]) is not None:
        raise err_active_share_grants()

    link["status"] = "UNLINKED"
    from helpers import format_dt_plain
    link["unlinked_at"] = format_dt_plain(parse_dt(iso_now()))
    touch(link)

    recording = db.collection("recordings").get(link["recording_id"])
    if recording is not None:
        services.recompute_legal_hold_count(recording)
        touch(recording)
    services.touch_case(case)
    if recording is not None:
        write_custody(agency["id"], recording["id"], "CASE_UNLINKED", actor)
    return success_obj(link)


# ---------------------------------------------------------------- share grants

@bp.route("/agencies/<agency_id>/cases/<case_id>/share-grants", methods=["POST"])
def create_share_grant(agency_id, case_id):
    actor = authenticate()
    require_roles(actor, "RecordsOfficer")
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    if case["status"] != "CLOSED":
        raise err_invalid_state("Share grants may only be created on a CLOSED case")
    data = body()
    reject_unknown(data, {"recipient_role", "recipient_email",
                          "expected_case_version", "expires_in_days"})
    recipient_role = require_enum(data, "recipient_role", ["PROSECUTOR", "DEFENSE"])
    recipient_email = require_str(data, "recipient_email")
    expected_version = require_int(data, "expected_case_version")
    expires_in_days = require_int(data, "expires_in_days", required=False, allow_null=True)

    if expires_in_days is not None and (expires_in_days < 1 or expires_in_days > 90):
        raise err_validation("expires_in_days must be 1..90")
    if expires_in_days is None:
        policy = active_policy(agency["id"])
        if policy is None:
            raise err_no_active_policy()
        expires_in_days = policy["default_share_expiry_days"]

    if expected_version != case["version"]:
        raise err_stale_version()

    grant = new_resource({
        "agency_id": agency["id"],
        "case_id": case["id"],
        "recipient_role": recipient_role,
        "recipient_email": recipient_email,
        "access_token": uuid.uuid4().hex,
        "expires_at": add_days(iso_now(), expires_in_days),
        "expires_in_days": expires_in_days,
        "access_count": 0,
        "status": "ACTIVE",
    })
    db.collection("share_grants")[grant["id"]] = grant
    touch(case)
    write_audit(agency["id"], actor, "SHARE_GRANT_CREATED", "ShareGrant",
                grant["id"], "grant created on case %s" % case["id"])
    return success_obj(grant, 201)


@bp.route("/agencies/<agency_id>/cases/<case_id>/share-grants", methods=["GET"])
def list_case_share_grants(agency_id, case_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer", "Supervisor")
    agency = get_agency_or_404(agency_id)
    case = get_scoped("cases", agency, case_id, "Case")
    items = [g for g in db.collection("share_grants").values()
             if g["case_id"] == case["id"]]
    status = request.args.get("status")
    if status:
        items = [g for g in items if g["status"] == status]
    return paginate(items)


@bp.route("/agencies/share-grants", methods=["GET"])
def list_share_grants():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer", "Supervisor")
    items = list(db.collection("share_grants").values())
    for param in ("agency_id", "case_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [g for g in items if str(g.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/share-grants/<grant_id>", methods=["GET"])
def get_share_grant(grant_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer")
    grant = db.collection("share_grants").get(grant_id)
    if grant is None:
        raise err_not_found("Share grant not found")
    return success_obj(grant)


@bp.route("/agencies/<agency_id>/share-grants/<grant_id>/revoke", methods=["POST"])
def revoke_share_grant(agency_id, grant_id):
    actor = authenticate()
    require_roles(actor, "RecordsOfficer")
    agency = get_agency_or_404(agency_id)
    grant = get_scoped("share_grants", agency, grant_id, "ShareGrant")
    if grant["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE grant can be revoked")
    grant["status"] = "REVOKED"
    touch(grant)
    write_audit(agency["id"], actor, "SHARE_GRANT_REVOKED", "ShareGrant",
                grant["id"], "status ACTIVE -> REVOKED")
    return success_obj(grant)


@bp.route("/agencies/<agency_id>/share-grants/sweep", methods=["POST"])
def sweep_share_grants(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    now = iso_now()
    expired = 0
    for grant in sorted(db.collection("share_grants").values(),
                        key=lambda g: (g["created_at"], g["id"])):
        if grant["agency_id"] != agency["id"]:
            continue
        if grant["status"] == "ACTIVE" and grant["expires_at"] <= now:
            grant["status"] = "EXPIRED"
            touch(grant)
            expired += 1
            write_audit(agency["id"], SYSTEM_ACTOR, "SHARE_GRANT_EXPIRED",
                        "ShareGrant", grant["id"], "grant expired by sweep")
    return success_obj({"expired_count": expired})


@bp.route("/agencies/<agency_id>/share-access", methods=["POST"])
def share_access(agency_id):
    actor = authenticate()
    require_roles(actor, "Prosecutor", "DefenseCounsel")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"access_token"})
    token = require_str(data, "access_token")
    grant = None
    for g in db.collection("share_grants").values():
        if g["agency_id"] == agency["id"] and g["access_token"] == token:
            grant = g
            break
    if grant is None:
        raise err_not_found("Share grant not found")
    wanted_role = "Prosecutor" if grant["recipient_role"] == "PROSECUTOR" else "DefenseCounsel"
    if actor["role"] != wanted_role:
        raise err_unauthorized("Role does not match the grant's recipient_role")
    now = iso_now()
    if grant["status"] != "ACTIVE" or grant["expires_at"] <= now:
        raise err_grant_expired()

    grant["access_count"] = grant.get("access_count", 0) + 1
    touch(grant)
    recording_ids = []
    for r in services.linked_recordings(grant["case_id"]):
        recording_ids.append(r["id"])
        write_custody(agency["id"], r["id"], "ACCESSED", actor)
    return success_obj({
        "case_id": grant["case_id"],
        "recording_ids": recording_ids,
        "grant_status": grant["status"],
    })


# ---------------------------------------------------------------- legal holds

@bp.route("/agencies/<agency_id>/legal-holds", methods=["POST"])
def create_legal_hold(agency_id):
    actor = authenticate()
    require_roles(actor, "RecordsOfficer")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"scope_type", "authority_reference", "recording_id", "case_id"})
    scope_type = require_enum(data, "scope_type", ["RECORDING", "CASE"])
    authority_reference = require_str(data, "authority_reference")
    recording_id = data.get("recording_id")
    case_id = data.get("case_id")

    if scope_type == "RECORDING":
        if not recording_id or case_id:
            raise err_validation("recording_id is required and case_id must be null for RECORDING scope")
        recording = db.collection("recordings").get(recording_id)
        if recording is None or recording["agency_id"] != agency["id"]:
            raise err_not_found("Recording not found")
    else:
        if not case_id or recording_id:
            raise err_validation("case_id is required and recording_id must be null for CASE scope")
        case = db.collection("cases").get(case_id)
        if case is None or case["agency_id"] != agency["id"]:
            raise err_not_found("Case not found")

    hold = new_resource({
        "agency_id": agency["id"],
        "scope_type": scope_type,
        "recording_id": recording_id if scope_type == "RECORDING" else None,
        "case_id": case_id if scope_type == "CASE" else None,
        "authority_reference": authority_reference,
        "status": "ACTIVE",
    })
    db.collection("legal_holds")[hold["id"]] = hold

    if scope_type == "RECORDING":
        recording = db.collection("recordings").get(recording_id)
        services.recompute_legal_hold_count(recording)
        touch(recording)
        write_custody(agency["id"], recording["id"], "HOLD_PLACED", actor)
    else:
        for r in services.linked_recordings(case_id):
            services.recompute_legal_hold_count(r)
            touch(r)
            write_custody(agency["id"], r["id"], "HOLD_PLACED", actor)
    write_audit(agency["id"], actor, "LEGAL_HOLD_PLACED", "LegalHold",
                hold["id"], "hold placed (%s scope)" % scope_type)
    return success_obj(hold, 201)


@bp.route("/agencies/legal-holds", methods=["GET"])
def list_legal_holds():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer", "Supervisor")
    items = list(db.collection("legal_holds").values())
    for param in ("agency_id", "status", "scope_type", "case_id", "recording_id"):
        val = request.args.get(param)
        if val is not None:
            items = [h for h in items if str(h.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/legal-holds/<hold_id>", methods=["GET"])
def get_legal_hold(hold_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer", "Supervisor")
    hold = db.collection("legal_holds").get(hold_id)
    if hold is None:
        raise err_not_found("Legal hold not found")
    return success_obj(hold)


@bp.route("/agencies/<agency_id>/legal-holds/<hold_id>/release", methods=["POST"])
def release_legal_hold(agency_id, hold_id):
    actor = authenticate()
    require_roles(actor, "RecordsOfficer")
    agency = get_agency_or_404(agency_id)
    hold = get_scoped("legal_holds", agency, hold_id, "LegalHold")
    if hold["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE hold can be released")
    hold["status"] = "RELEASED"
    touch(hold)
    if hold["scope_type"] == "RECORDING":
        recording = db.collection("recordings").get(hold["recording_id"])
        if recording is not None:
            services.recompute_legal_hold_count(recording)
            touch(recording)
            write_custody(agency["id"], recording["id"], "HOLD_RELEASED", actor)
    else:
        for r in services.linked_recordings(hold["case_id"]):
            services.recompute_legal_hold_count(r)
            touch(r)
            write_custody(agency["id"], r["id"], "HOLD_RELEASED", actor)
    write_audit(agency["id"], actor, "LEGAL_HOLD_RELEASED", "LegalHold",
                hold["id"], "status ACTIVE -> RELEASED")
    return success_obj(hold)

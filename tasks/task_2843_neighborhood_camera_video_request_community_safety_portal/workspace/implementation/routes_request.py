"""Video-request endpoints (PRD 3.4)."""
from flask import Blueprint

import auth
import calc
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from routes_agency import require_onboarded
from store import db, now

bp = Blueprint("request", __name__)

LIFECYCLE_STATES = ("DRAFT", "SOLICITING", "FULFILLED", "EXHAUSTED",
                    "WITHDRAWN")
COMPLIANCE_STATES = ("JUSTIFICATION_PENDING", "JUSTIFICATION_LOGGED",
                     "AUDIT_FLAGGED", "AUDIT_CLEARED", "AUDIT_ESCALATED")


@bp.post("/neighborhood-safety/video-requests")
def create_request():
    actor = auth.authenticate(("Officer",))
    body = v.body_json()
    v.require_present(body, "request_area_id")
    area = fetch.must("RequestArea", body.get("request_area_id"))
    case_number = v.str_field(body, "case_number", min_len=1, max_len=64)
    expected_version = v.int_field(body, "expected_request_area_version")
    agency = db.agencies.get(area["agency_id"])
    officer = auth.require_officer(actor)
    if officer["agency_id"] != area["agency_id"]:
        auth.mismatch("Acting officer does not belong to this agency")
    require_onboarded(agency)
    if area["status"] != "LOCKED":
        raise ApiError("ERR_AREA_NOT_LOCKED",
                       "Area %s is not locked" % area["id"])
    if expected_version != area["version"]:
        raise ApiError("ERR_STALE_AREA_VERSION",
                       "expected_request_area_version does not match the area")

    row = engine.new_row({
        "request_area_id": area["id"],
        "agency_id": area["agency_id"],
        "submitting_officer_id": officer["id"],
        "auditor_officer_id": None,
        "case_number": case_number,
        "lifecycle_state": "DRAFT",
        "compliance_state": "JUSTIFICATION_PENDING",
        "justification_text": None,
        "statutory_basis": None,
        "justification_logged_at": None,
        "audit_note": None,
        "withdraw_reason": None,
        "submitted_at": None,
        "expires_at": None,
        "solicitation_count": 0,
        "pending_count": 0,
        "shared_count": 0,
        "declined_count": 0,
        "expired_count": 0,
        "withdrawn_count": 0,
        "shared_clip_count": 0,
        "provisional_share_rate_bps": 0,
    })
    db.video_requests[row["id"]] = row
    area["derived_request_count"] += 1
    engine.touch(area)
    return envelope.created(serialize.dump("VideoRequest", row))


@bp.post("/neighborhood-safety/video-requests/<request_id>/justification")
def log_justification(request_id):
    actor = auth.authenticate(("Officer",))
    request_row = fetch.must("VideoRequest", request_id)
    body = v.body_json()
    justification_text = v.str_field(body, "justification_text",
                                     allow_empty=True)
    statutory_basis = v.str_field(body, "statutory_basis", allow_empty=True)
    agency = db.agencies.get(request_row["agency_id"])
    auth.require_officer_is(actor, request_row["submitting_officer_id"],
                          request_row["agency_id"])
    require_onboarded(agency)
    if request_row["lifecycle_state"] != "DRAFT":
        raise ApiError("ERR_REQUEST_NOT_IN_DRAFT",
                       "Request %s is not in DRAFT" % request_row["id"])
    if request_row["compliance_state"] != "JUSTIFICATION_PENDING":
        raise ApiError("ERR_REQUEST_NOT_IN_DRAFT",
                       "A justification has already been logged")
    trimmed = justification_text.strip()
    if (len(trimmed) < agency["justification_min_chars"]
            or statutory_basis.strip() == ""):
        raise ApiError("ERR_JUSTIFICATION_TOO_SHORT",
                       "justification_text must be at least %d characters"
                       % agency["justification_min_chars"])

    request_row["justification_text"] = justification_text
    request_row["statutory_basis"] = statutory_basis
    request_row["justification_logged_at"] = now()
    request_row["compliance_state"] = "JUSTIFICATION_LOGGED"
    area = db.request_areas.get(request_row["request_area_id"])
    if area["radius_m"] > 1000 or area["eligible_device_count"] > 4:
        request_row["compliance_state"] = "AUDIT_FLAGGED"
    engine.touch(request_row)
    return envelope.ok(serialize.dump("VideoRequest", request_row))


@bp.post("/neighborhood-safety/video-requests/<request_id>/audit-review")
def audit_review(request_id):
    actor = auth.authenticate(("Officer",))
    request_row = fetch.must("VideoRequest", request_id)
    body = v.body_json()
    decision = v.enum_field(body, "decision", ("CLEAR", "ESCALATE"))
    audit_note = v.str_field(body, "audit_note", allow_empty=True)
    officer = auth.require_officer(actor)
    if officer["agency_id"] != request_row["agency_id"]:
        auth.mismatch("Acting officer does not belong to this agency")
    if officer["id"] == request_row["submitting_officer_id"]:
        auth.sod("An officer may not audit their own request")
    if officer["duty_role"] not in ("AUDITOR", "DUAL_ROLE"):
        auth.sod("This officer does not hold audit capability")
    if request_row["compliance_state"] != "AUDIT_FLAGGED":
        raise ApiError("ERR_AUDIT_NOT_PENDING",
                       "Request %s is not awaiting audit" % request_row["id"])

    request_row["compliance_state"] = ("AUDIT_CLEARED" if decision == "CLEAR"
                                      else "AUDIT_ESCALATED")
    request_row["audit_note"] = audit_note
    request_row["auditor_officer_id"] = officer["id"]
    engine.touch(request_row)
    officer["audits_completed_count"] += 1
    engine.touch(officer)
    return envelope.ok(serialize.dump("VideoRequest", request_row))


@bp.post("/neighborhood-safety/video-requests/<request_id>/submit")
def submit_request(request_id):
    actor = auth.authenticate(("Officer",))
    request_row = fetch.must("VideoRequest", request_id)
    v.body_json()
    agency = db.agencies.get(request_row["agency_id"])
    officer = auth.require_officer_is(actor,
                                     request_row["submitting_officer_id"],
                                     request_row["agency_id"])
    require_onboarded(agency)
    area = db.request_areas.get(request_row["request_area_id"])
    if area["status"] != "LOCKED":
        raise ApiError("ERR_AREA_INVALIDATED",
                       "Area %s no longer authorises a canvass" % area["id"])
    if request_row["lifecycle_state"] != "DRAFT":
        raise ApiError("ERR_REQUEST_NOT_IN_DRAFT",
                       "Request %s is not in DRAFT" % request_row["id"])
    if request_row["compliance_state"] == "JUSTIFICATION_PENDING":
        raise ApiError("ERR_JUSTIFICATION_NOT_LOGGED",
                       "The justification has not been logged")
    if area["eligible_device_count"] < area["effective_min_devices"]:
        raise ApiError("ERR_MIN_DEVICE_THRESHOLD_NOT_MET",
                       "The canvass area has too few eligible cameras")
    if agency["open_request_count"] >= agency["max_open_requests"]:
        raise ApiError("ERR_AGENCY_OPEN_REQUEST_QUOTA_EXCEEDED",
                       "The agency has too many open requests")
    if agency["requests_submitted_count"] >= agency["period_request_quota"]:
        raise ApiError("ERR_AGENCY_PERIOD_QUOTA_EXCEEDED",
                       "The agency has exhausted its period quota")

    submitted_at = now()
    expires_at = store.add_hours(submitted_at, calc.SOLICITATION_RESPONSE_HOURS)
    request_row["lifecycle_state"] = "SOLICITING"
    request_row["submitted_at"] = submitted_at
    request_row["expires_at"] = expires_at

    roster = db.rosters.get(area["id"]) or []
    entries = []
    rank = 0
    for member in roster:
        device = db.devices.get(member["device_id"])
        if device is None:
            continue
        rank += 1
        sol = engine.new_row({
            "video_request_id": request_row["id"],
            "device_id": device["id"],
            "resident_id": device["owner_resident_id"],
            "status": "SOLICITED",
            "distance_sq_m2": member["distance_sq"],
            "dispatch_rank": rank,
            "respond_deadline_utc": expires_at,
            "notification_suppressed": False,
            "suppression_reason": None,
            "responded_at": None,
            "decline_reason": None,
            "clip_count": 0,
        })
        db.solicitations[sol["id"]] = sol
        device["solicitations_received_count"] += 1
        device["pending_solicitation_count"] += 1
        engine.touch(device)
        resident = db.residents.get(device["owner_resident_id"])
        if resident is not None:
            entries.append({
                "resident": resident,
                "source_ref_id": sol["id"],
                "apply": _suppression_writer(sol),
            })

    request_row["solicitation_count"] = rank
    request_row["pending_count"] = rank
    request_row["shared_count"] = 0
    request_row["declined_count"] = 0
    request_row["expired_count"] = 0
    request_row["withdrawn_count"] = 0
    request_row["shared_clip_count"] = 0
    request_row["provisional_share_rate_bps"] = 0
    engine.touch(request_row)

    agency["open_request_count"] += 1
    agency["requests_submitted_count"] += 1
    engine.touch(agency)
    if officer is not None:
        officer["requests_submitted_count"] += 1
        engine.touch(officer)

    engine.emit_batch("CONSENT_SOLICITATION", entries)
    return envelope.ok(serialize.dump("VideoRequest", request_row))


def _suppression_writer(sol):
    def apply(dispatch):
        if dispatch["suppressed"]:
            sol["notification_suppressed"] = True
            sol["suppression_reason"] = dispatch["suppression_reason"]
    return apply


@bp.post("/neighborhood-safety/video-requests/<request_id>/withdraw")
def withdraw_request(request_id):
    actor = auth.authenticate(("Officer", "AgencyAdmin"))
    request_row = fetch.must("VideoRequest", request_id)
    body = v.body_json()
    v.str_field(body, "reason", allow_empty=True)
    if actor.role == "AgencyAdmin":
        auth.require_agency_scope(actor, request_row["agency_id"])
    else:
        auth.require_officer_is(actor, request_row["submitting_officer_id"],
                               request_row["agency_id"])
    lifecycle = request_row["lifecycle_state"]
    if lifecycle not in ("DRAFT", "SOLICITING"):
        raise ApiError("ERR_REQUEST_NOT_SOLICITING",
                       "Request %s can no longer be withdrawn"
                       % request_row["id"])

    request_row["lifecycle_state"] = "WITHDRAWN"
    request_row["withdraw_reason"] = "OFFICER_WITHDRAWAL"
    engine.touch(request_row)
    if lifecycle == "SOLICITING":
        pending = [s for s in engine.solicitations_of_request(request_row["id"])
                   if s["status"] == "SOLICITED"]
        pending.sort(key=lambda s: s["dispatch_rank"])
        for sol in pending:
            engine.withdraw_solicitation(sol)
        engine.sync_request(request_row, resolve=False)
        engine.sync_agency_open_count(db.agencies.get(request_row["agency_id"]))
    return envelope.ok(serialize.dump("VideoRequest", request_row))


@bp.get("/neighborhood-safety/video-requests/<request_id>")
def read_request(request_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Resident"))
    request_row = fetch.must("VideoRequest", request_id)
    return envelope.ok(serialize.dump("VideoRequest", request_row))


@bp.get("/neighborhood-safety/video-requests")
def list_requests():
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer"))
    limit, offset = v.pagination()
    filters = {
        "agency_id": v.query_str("agency_id"),
        "request_area_id": v.query_str("request_area_id"),
        "submitting_officer_id": v.query_str("submitting_officer_id"),
        "auditor_officer_id": v.query_str("auditor_officer_id"),
        "lifecycle_state": v.query_enum("lifecycle_state", LIFECYCLE_STATES),
        "compliance_state": v.query_enum("compliance_state", COMPLIANCE_STATES),
    }
    rows = list(db.video_requests.values())
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("VideoRequest", page), limit,
                               offset, total)

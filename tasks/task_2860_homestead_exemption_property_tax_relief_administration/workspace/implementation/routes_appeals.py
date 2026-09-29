"""Notices, appeal rights and the hearing docket (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint

import calc
import db
import enums
import envelope as env
import services
import validate as v
from errors import fail
from validate import endpoint

bp = Blueprint("appeals", __name__)

BUFFER = timedelta(minutes=db.HEARING_BUFFER_MINUTES)


def _instant(text):
    return v.parse_instant("instant", text)


def _docket_or_404(docket_id):
    docket = db.get("hearing_dockets", docket_id)
    if docket is None:
        fail("ERR_DOCKET_NOT_FOUND")
    return docket


def _appeal_or_404(appeal_id):
    appeal = db.get("appeals", appeal_id)
    if appeal is None:
        fail("ERR_APPEAL_NOT_FOUND")
    return appeal


# --------------------------------------------------------------------------
# Notices
# --------------------------------------------------------------------------
@bp.get("/taxpayer-accounts/<taxpayer_id>/notices")
@endpoint(["IntakeClerk", "ExemptionsReviewer", "RecoveryOfficer", "Taxpayer"])
def list_notices(taxpayer_id):
    limit, offset = v.pagination()
    notice_type = v.q_enum("notice_type", enums.NOTICE_TYPES)
    subject_type = v.q_enum("subject_type", enums.SUBJECT_TYPES)
    subject_id = v.q_str("subject_id")
    taxpayer = db.get("taxpayer_accounts", taxpayer_id)
    if taxpayer is None:
        fail("ERR_TAXPAYER_NOT_FOUND")
    if v.is_taxpayer() and taxpayer["id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    items = []
    for notice in db.rows("notices"):
        if notice["taxpayer_id"] != taxpayer["id"]:
            continue
        if notice_type is not None and notice["notice_type"] != notice_type:
            continue
        if subject_type is not None and notice["subject_type"] != subject_type:
            continue
        if subject_id is not None and notice["subject_id"] != subject_id:
            continue
        items.append(db.public(notice))
    return env.listing(items, limit, offset)


# --------------------------------------------------------------------------
# HearingDocket
# --------------------------------------------------------------------------
@bp.post("/hearing-dockets")
@endpoint(["HearingClerk"])
def create_hearing_docket():
    body = v.body()
    docket_date = v.req_date(body, "docket_date")
    session_start = v.req_instant(body, "session_start_utc")
    session_end = v.req_instant(body, "session_end_utc")
    capacity = v.req_int(body, "capacity", minimum=1, maximum=20)
    if session_end <= session_start:
        fail("ERR_INVALID_REQUEST", "session_end_utc must be strictly after session_start_utc.")

    docket = db.insert("hearing_dockets", {
        "docket_date": docket_date,
        "session_start_utc": db.iso(session_start),
        "session_end_utc": db.iso(session_end),
        "capacity": capacity,
        "scheduled_appeal_count": 0,
        "status": "OPEN",
    })
    return env.created(db.public(docket))


@bp.get("/hearing-dockets/<docket_id>")
@endpoint(["HearingClerk", "HearingOfficer"])
def read_hearing_docket(docket_id):
    docket = _docket_or_404(docket_id)
    return env.ok(db.public(docket))


@bp.post("/hearing-dockets/<docket_id>/close")
@endpoint(["HearingClerk"])
def close_hearing_docket(docket_id):
    docket = _docket_or_404(docket_id)
    body = v.body()
    v.opt_str(body, "reason", None)
    if docket["status"] == "CLOSED":
        fail("ERR_DOCKET_CLOSED")
    docket["status"] = "CLOSED"
    db.touch(docket)
    return env.ok(db.public(docket))


# --------------------------------------------------------------------------
# Appeal
# --------------------------------------------------------------------------
@bp.post("/appeals")
@endpoint(["Taxpayer"])
def file_appeal():
    body = v.body()
    notice_id = v.req_str(body, "notice_id")
    notice = db.get("notices", notice_id)
    if notice is None:
        fail("ERR_NOTICE_NOT_FOUND")
    if notice["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    grounds = v.req_str(body, "grounds")

    filed_at = db.now()
    if filed_at > _instant(notice["appeal_deadline"]):
        fail("ERR_APPEAL_DEADLINE_PASSED")
    if not notice["appealable"]:
        fail("ERR_NOTICE_NOT_APPEALABLE")

    for other in db.rows("appeals"):
        if other["notice_id"] == notice["id"]:
            fail("ERR_APPEAL_ALREADY_EXISTS")

    appeal = db.insert("appeals", {
        "notice_id": notice["id"],
        "taxpayer_id": notice["taxpayer_id"],
        "docket_id": None,
        "filed_at": db.iso(filed_at),
        "grounds": grounds,
        "hearing_start_utc": None,
        "hearing_end_utc": None,
        "continuance_count": 0,
        "decided_by_user_id": None,
        "status": "FILED",
    })
    return env.created(db.public(appeal))


@bp.get("/appeals/<appeal_id>")
@endpoint(["HearingClerk", "HearingOfficer", "Taxpayer"])
def read_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    if v.is_taxpayer() and appeal["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    return env.ok(db.public(appeal))


@bp.get("/appeals")
@endpoint(["HearingClerk", "HearingOfficer"])
def list_appeals():
    limit, offset = v.pagination()
    notice_id = v.q_str("notice_id")
    taxpayer_id = v.q_str("taxpayer_id")
    docket_id = v.q_str("docket_id")
    status = v.q_enum("status", enums.APPEAL_STATUSES)
    items = []
    for appeal in db.rows("appeals"):
        if notice_id is not None and appeal["notice_id"] != notice_id:
            continue
        if taxpayer_id is not None and appeal["taxpayer_id"] != taxpayer_id:
            continue
        if docket_id is not None and appeal["docket_id"] != docket_id:
            continue
        if status is not None and appeal["status"] != status:
            continue
        items.append(db.public(appeal))
    return env.listing(items, limit, offset)


@bp.post("/appeals/<appeal_id>/schedule")
@endpoint(["HearingClerk"])
def schedule_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    body = v.body()
    docket_id = v.req_str(body, "docket_id")
    hearing_start = v.req_instant(body, "hearing_start_utc")
    hearing_end = v.req_instant(body, "hearing_end_utc")
    if hearing_end <= hearing_start:
        fail("ERR_INVALID_REQUEST", "hearing_end_utc must be strictly after hearing_start_utc.")

    docket = db.get("hearing_dockets", docket_id)
    if docket is None:
        fail("ERR_DOCKET_NOT_FOUND")

    if appeal["status"] not in ("FILED", "CONTINUED"):
        fail("ERR_APPEAL_NOT_SCHEDULABLE")
    if docket["status"] != "OPEN":
        fail("ERR_DOCKET_CLOSED")

    if hearing_start < _instant(docket["session_start_utc"]):
        fail("ERR_HEARING_SLOT_CONFLICT")
    if hearing_end > _instant(docket["session_end_utc"]):
        fail("ERR_HEARING_SLOT_CONFLICT")

    for other in db.rows("appeals"):
        if other["id"] == appeal["id"]:
            continue
        if other["docket_id"] != docket["id"]:
            continue
        if other["status"] not in enums.APPEAL_SLOT_HOLDING_STATUSES:
            continue
        other_start = _instant(other["hearing_start_utc"])
        other_end = _instant(other["hearing_end_utc"])
        if (hearing_start - BUFFER) <= other_end and other_start <= (hearing_end + BUFFER):
            fail("ERR_HEARING_SLOT_CONFLICT")

    if services.docket_slot_count(docket["id"]) >= docket["capacity"]:
        fail("ERR_DOCKET_CAPACITY_REACHED")

    appeal["docket_id"] = docket["id"]
    appeal["hearing_start_utc"] = db.iso(hearing_start)
    appeal["hearing_end_utc"] = db.iso(hearing_end)
    appeal["status"] = "SCHEDULED"
    db.touch(appeal)
    services.rederive_docket_count(docket)
    return env.ok(db.public(appeal))


# --------------------------------------------------------------------------
# Deciding an appeal
# --------------------------------------------------------------------------
def _duty_bar(notice):
    """The operator who took the noticed action being challenged."""
    if notice is None:
        return None
    if notice["notice_type"] == "DENIAL":
        application = db.get("exemption_applications", notice["subject_id"])
        return application["determined_by_user_id"] if application else None
    if notice["notice_type"] == "RECOVERY_ASSESSMENT":
        case = db.get("fraud_cases", notice["subject_id"])
        return case["substantiated_by_user_id"] if case else None
    return None


def _compensate(notice):
    """Undo the noticed action, as the notice's subject_type dictates."""
    subject_type = notice["subject_type"]

    if subject_type == "FRAUD_CASE":
        case = db.get("fraud_cases", notice["subject_id"])
        if case is None:
            return
        collected = case["recovery_paid_cents"]
        case["recovery_status"] = "ABATED"
        case["recovery_paid_cents"] = 0
        db.touch(case)
        grant = db.get("exemption_grants", case["grant_id"])
        if grant is not None and grant["benefit_status"] == "REVOKED":
            services.set_grant_status(grant, "ACTIVE", None)
        taxpayer = db.get("taxpayer_accounts", case["taxpayer_id"])
        if taxpayer is not None and collected:
            services.add_recovery_collected(taxpayer, -collected)
            db.touch(taxpayer)
        return

    if subject_type == "EXEMPTION_APPLICATION":
        application = db.get("exemption_applications", notice["subject_id"])
        if application is None or application["status"] != "DENIED":
            return
        application["status"] = "UNDER_REVIEW"
        application["determined_by_user_id"] = None
        application["denial_reason"] = None
        db.touch(application)
        return

    if subject_type == "EXEMPTION_GRANT":
        grant = db.get("exemption_grants", notice["subject_id"])
        if grant is None:
            return
        if grant["benefit_status"] in ("REVOKED", "SUSPENDED"):
            services.set_grant_status(grant, "ACTIVE", None)
        return


@bp.post("/appeals/<appeal_id>/decide")
@endpoint(["HearingOfficer"])
def decide_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    notice = db.get("notices", appeal["notice_id"])
    bar = _duty_bar(notice)
    if bar is not None and bar == v.caller_id():
        fail("ERR_SEGREGATION_OF_DUTIES")

    body = v.body()
    action = v.req_enum(body, "action", enums.APPEAL_ACTIONS)
    v.opt_str(body, "findings", None)

    if appeal["status"] != "SCHEDULED":
        fail("ERR_APPEAL_NOT_SCHEDULED")

    if action == "CONTINUE":
        if appeal["continuance_count"] >= db.MAX_CONTINUANCES:
            fail("ERR_CONTINUANCE_LIMIT_REACHED")
        former_docket = db.get("hearing_dockets", appeal["docket_id"])
        appeal["continuance_count"] += 1
        appeal["docket_id"] = None
        appeal["hearing_start_utc"] = None
        appeal["hearing_end_utc"] = None
        appeal["status"] = "CONTINUED"
        appeal["decided_by_user_id"] = v.caller_id()
        db.touch(appeal)
        if former_docket is not None:
            services.rederive_docket_count(former_docket)
        return env.ok(db.public(appeal))

    appeal["status"] = {"GRANT": "GRANTED", "DENY": "DENIED", "DISMISS": "DISMISSED"}[action]
    appeal["decided_by_user_id"] = v.caller_id()
    db.touch(appeal)

    if action == "GRANT" and notice is not None:
        _compensate(notice)

    return env.ok(db.public(appeal))

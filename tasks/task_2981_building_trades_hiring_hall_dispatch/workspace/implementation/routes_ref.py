"""Answering the referral (§3.7) and life on the job (§3.8)."""

import math

from flask import Blueprint

from core import (
    DISPATCH_STATUSES, GOOD_CAUSE_CODES, LAYOFF_REASONS,
    NO_FAULT_LAYOFF_REASONS, RECALL_WINDOW_DAYS, REFERRAL_KINDS,
    REFERRAL_STATUSES, db, days, new_id, now, touch,
)
from envelope import ApiError, created, listing, ok
from guards import (
    body, check_pagination_shape, pagination, paginate, q_enum, q_str, require,
    s_dt, s_enum, s_int, s_str,
)
import domain
import serializers as S
import services

bp = Blueprint("ref", __name__)

_MAX_HOURS_PER_ELAPSED_DAY = 12


def _referral_or_404(referral_id):
    referral = db.referrals.get(referral_id)
    if referral is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", "No referral with id %s." % referral_id)
    return referral


def _dispatch_or_404(dispatch_id):
    dispatch = db.dispatches.get(dispatch_id)
    if dispatch is None:
        raise ApiError("ERR_DISPATCH_NOT_FOUND", "No dispatch with id %s." % dispatch_id)
    return dispatch


def _overlaps(member_id, report_at, ignore_dispatch_id=None):
    """§2.5 — the employment interval is half-open: [start_at, ended_at), or
    [start_at, oo) while the dispatch is WORKING. Adjacency is allowed."""
    for dispatch in db.dispatches.values():
        if dispatch["member_id"] != member_id:
            continue
        if ignore_dispatch_id is not None and dispatch["id"] == ignore_dispatch_id:
            continue
        start = dispatch["start_at"]
        if report_at < start:
            continue
        if dispatch["status"] == "WORKING":
            return True
        ended_at = dispatch["ended_at"]
        if ended_at is None or report_at < ended_at:
            return True
    return False


# --------------------------------------------------------------------------
# referral reads
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/referrals/<referral_id>", methods=["GET"])
def read_referral(referral_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
    check_pagination_shape()
    return ok(S.referral_view(_referral_or_404(referral_id)))


@bp.route("/hiring-hall/referrals", methods=["GET"])
def list_referrals():
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
    job_request_id = q_str("job_request_id")
    registration_id = q_str("registration_id")
    member_id = q_str("member_id")
    status = q_enum("status", REFERRAL_STATUSES)
    referral_kind = q_enum("referral_kind", REFERRAL_KINDS)
    limit, offset = pagination()
    rows = services.sort_default(db.referrals.values())
    if job_request_id is not None:
        rows = [r for r in rows if r["job_request_id"] == job_request_id]
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if referral_kind is not None:
        rows = [r for r in rows if r["referral_kind"] == referral_kind]
    page, meta = paginate(rows, limit, offset)
    return listing([S.referral_view(r) for r in page], meta)


# --------------------------------------------------------------------------
# acceptance
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/referrals/<referral_id>/accept", methods=["POST"])
def accept_referral(referral_id):
    user_id, role = require("Member", "Dispatcher")
    check_pagination_shape()
    body()
    referral = _referral_or_404(referral_id)
    if role == "Member" and user_id != referral["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A member may only answer their own referral.")
    job_request = db.job_requests.get(referral["job_request_id"])
    if job_request is None or job_request["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        raise ApiError("ERR_JOB_REQUEST_NOT_OPEN",
                       "The job request is no longer open for acceptances.")
    if referral["status"] != "ISSUED":
        raise ApiError("ERR_REFERRAL_NOT_PENDING",
                       "The referral is %s and cannot be answered." % referral["status"])
    if now() > referral["acceptance_deadline"]:
        raise ApiError("ERR_ACCEPTANCE_WINDOW_CLOSED",
                       "The 24-hour acceptance window has closed.")
    if _overlaps(referral["member_id"], job_request["report_at"]):
        raise ApiError("ERR_OVERLAPPING_DISPATCH",
                       "The member is already employed at the reporting instant.")
    if referral["slot_kind"] == "APPRENTICE":
        policy = domain.governing_ratio_policy()
        if policy is None:
            raise ApiError("ERR_NO_ACTIVE_RATIO_POLICY",
                           "No apprentice-ratio policy is in force.")
        cap = domain.apprentice_cap(job_request, policy)
        accepted = domain.accepted_apprentice_count(job_request)
        limit = min(cap, job_request["apprentices_requested"])
        if accepted + 1 > limit:
            raise ApiError("ERR_APPRENTICE_RATIO_EXCEEDED",
                           "The apprentice ratio cap permits at most %d apprentices."
                           % limit)

    clock = now()
    referral["status"] = "ACCEPTED"
    touch(referral)
    registration = db.registrations.get(referral["registration_id"])
    if registration is not None:
        registration["status"] = "DISPATCHED_OUT"
        registration["priority_flag"] = False
        touch(registration)
    dispatch = {
        "id": new_id(),
        "referral_id": referral["id"],
        "job_request_id": job_request["id"],
        "member_id": referral["member_id"],
        "recall_of_dispatch_id": None,
        "start_at": job_request["report_at"],
        "ended_at": None,
        "hours_worked": 0,
        "layoff_reason": None,
        "recall_window_ends_at": None,
        "status": "WORKING",
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.dispatches[dispatch["id"]] = dispatch
    services.rederive_job_request_status(job_request)
    touch(job_request)
    services.append_ledger("REFERRAL_ACCEPTED", referral["member_id"], referral["id"],
                           snapshot={"dispatch_id": dispatch["id"],
                                     "slot_kind": referral["slot_kind"]})
    return created(S.dispatch_view(dispatch))


# --------------------------------------------------------------------------
# refusal
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/referrals/<referral_id>/refuse", methods=["POST"])
def refuse_referral(referral_id):
    user_id, role = require("Member", "Dispatcher")
    check_pagination_shape()
    data = body()
    good_cause = s_enum(data, "refusal_good_cause_code", GOOD_CAUSE_CODES,
                        required=False, default=None)
    referral = _referral_or_404(referral_id)
    if role == "Member" and user_id != referral["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A member may only answer their own referral.")
    if referral["status"] != "ISSUED":
        raise ApiError("ERR_REFERRAL_NOT_PENDING",
                       "The referral is %s and cannot be answered." % referral["status"])
    if now() > referral["acceptance_deadline"]:
        raise ApiError("ERR_ACCEPTANCE_WINDOW_CLOSED",
                       "The 24-hour acceptance window has closed.")

    registration = db.registrations.get(referral["registration_id"])
    referral["status"] = "REFUSED"
    referral["refusal_good_cause_code"] = good_cause
    touch(referral)
    if good_cause is not None:
        # good cause costs the member nothing at all
        if registration is not None and registration["status"] == "REFERRED":
            registration["status"] = "REGISTERED"
            touch(registration)
        services.append_ledger("REFERRAL_REFUSED", referral["member_id"], referral["id"],
                               snapshot={"good_cause": True,
                                         "refusal_good_cause_code": good_cause})
    else:
        services.apply_no_cause_consequence(referral, registration)
    job_request = db.job_requests.get(referral["job_request_id"])
    if job_request is not None:
        touch(job_request)
    return ok(S.referral_view(referral))


# --------------------------------------------------------------------------
# withdrawal
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/referrals/<referral_id>/withdraw", methods=["POST"])
def withdraw_referral_route(referral_id):
    require("Dispatcher", "HallAdmin")
    check_pagination_shape()
    data = body()
    reason = s_str(data, "reason", min_len=1, max_len=500)
    referral = _referral_or_404(referral_id)
    if referral["status"] != "ISSUED":
        raise ApiError("ERR_REFERRAL_NOT_PENDING",
                       "The referral is %s and cannot be withdrawn." % referral["status"])
    services.withdraw_referral(referral, reason=reason)
    return ok(S.referral_view(referral))


# --------------------------------------------------------------------------
# dispatch reads
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/dispatches/<dispatch_id>", methods=["GET"])
def read_dispatch(dispatch_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
    check_pagination_shape()
    return ok(S.dispatch_view(_dispatch_or_404(dispatch_id)))


@bp.route("/hiring-hall/dispatches", methods=["GET"])
def list_dispatches():
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
    member_id = q_str("member_id")
    referral_id = q_str("referral_id")
    job_request_id = q_str("job_request_id")
    recall_of_dispatch_id = q_str("recall_of_dispatch_id")
    status = q_enum("status", DISPATCH_STATUSES)
    limit, offset = pagination()
    rows = services.sort_default(db.dispatches.values())
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if job_request_id is not None:
        rows = [r for r in rows if r["job_request_id"] == job_request_id]
    if recall_of_dispatch_id is not None:
        rows = [r for r in rows if r["recall_of_dispatch_id"] == recall_of_dispatch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows, limit, offset)
    return listing([S.dispatch_view(r) for r in page], meta)


# --------------------------------------------------------------------------
# layoff
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/dispatches/<dispatch_id>/layoff", methods=["POST"])
def layoff_dispatch(dispatch_id):
    user_id, role = require("ContractorRep", "HallAdmin")
    check_pagination_shape()
    data = body()
    hours_worked = s_int(data, "hours_worked", minimum=0)
    layoff_reason = s_enum(data, "layoff_reason", LAYOFF_REASONS)
    dispatch = _dispatch_or_404(dispatch_id)
    job_request = db.job_requests.get(dispatch["job_request_id"])
    if role == "ContractorRep":
        owner = job_request["contractor_id"] if job_request else None
        if user_id != owner:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "Only the contractor behind this dispatch may close it.")
    if dispatch["status"] != "WORKING":
        raise ApiError("ERR_DISPATCH_NOT_WORKING",
                       "A %s dispatch cannot be laid off." % dispatch["status"])
    clock = now()
    elapsed = clock - dispatch["start_at"]
    elapsed_seconds = elapsed.total_seconds()
    elapsed_days = int(math.ceil(elapsed_seconds / 86400.0)) if elapsed_seconds > 0 else 0
    if hours_worked > _MAX_HOURS_PER_ELAPSED_DAY * elapsed_days:
        raise ApiError("ERR_HOURS_EXCEED_ELAPSED",
                       "At most %d hours may be reported against %d elapsed day(s)."
                       % (_MAX_HOURS_PER_ELAPSED_DAY * elapsed_days, elapsed_days))

    dispatch["hours_worked"] = hours_worked
    dispatch["layoff_reason"] = layoff_reason
    dispatch["ended_at"] = clock
    if layoff_reason in NO_FAULT_LAYOFF_REASONS:
        dispatch["status"] = "LAID_OFF"
        dispatch["recall_window_ends_at"] = clock + days(RECALL_WINDOW_DAYS)
    elif layoff_reason == "FOR_CAUSE":
        dispatch["status"] = "TERMINATED_FOR_CAUSE"
    else:
        dispatch["status"] = "QUIT"
    touch(dispatch)
    member = db.members.get(dispatch["member_id"])
    if member is not None:
        member["local_hours_in_trade"] = member["local_hours_in_trade"] + hours_worked
        touch(member)
    services.append_ledger("DISPATCH_LAID_OFF", dispatch["member_id"],
                           dispatch["referral_id"],
                           snapshot={"layoff_reason": layoff_reason,
                                     "dispatch_id": dispatch["id"]},
                           hours_delta=hours_worked)
    if job_request is not None:
        services.maybe_close_job_request(job_request)
    return ok(S.dispatch_view(dispatch))


# --------------------------------------------------------------------------
# recall
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/dispatches/<dispatch_id>/recall", methods=["POST"])
def recall_dispatch(dispatch_id):
    user_id, role = require("ContractorRep")
    check_pagination_shape()
    data = body()
    report_at = s_dt(data, "report_at")
    dispatch = _dispatch_or_404(dispatch_id)
    job_request = db.job_requests.get(dispatch["job_request_id"])
    owner = job_request["contractor_id"] if job_request else None
    if user_id != owner:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the contractor behind this dispatch may recall it.")
    if dispatch["status"] != "LAID_OFF":
        raise ApiError("ERR_RECALL_NOT_ELIGIBLE",
                       "A %s dispatch is not recallable." % dispatch["status"])
    clock = now()
    ended_at = dispatch["ended_at"]
    horizon = dispatch["recall_window_ends_at"]
    if ended_at is None or horizon is None or clock < ended_at or clock > horizon:
        raise ApiError("ERR_RECALL_WINDOW_CLOSED", "The seven-day recall window is closed.")
    if domain.member_has_working_dispatch(dispatch["member_id"]):
        raise ApiError("ERR_OVERLAPPING_DISPATCH",
                       "The member already holds a WORKING dispatch.")
    if _overlaps(dispatch["member_id"], report_at):
        raise ApiError("ERR_OVERLAPPING_DISPATCH",
                       "The member is already employed at the reporting instant.")

    recall = {
        "id": new_id(),
        "referral_id": dispatch["referral_id"],
        "job_request_id": dispatch["job_request_id"],
        "member_id": dispatch["member_id"],
        "recall_of_dispatch_id": dispatch["id"],
        "start_at": report_at,
        "ended_at": None,
        "hours_worked": 0,
        "layoff_reason": None,
        "recall_window_ends_at": None,
        "status": "WORKING",
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.dispatches[recall["id"]] = recall
    for registration in services.sort_default(db.registrations.values()):
        if (registration["member_id"] == dispatch["member_id"]
                and registration["status"] == "REGISTERED"):
            registration["status"] = "DISPATCHED_OUT"
            touch(registration)
            break
    services.append_ledger("DISPATCH_RECALLED", dispatch["member_id"],
                           dispatch["referral_id"],
                           snapshot={"recall_of_dispatch_id": dispatch["id"],
                                     "dispatch_id": recall["id"]})
    return created(S.dispatch_view(recall))

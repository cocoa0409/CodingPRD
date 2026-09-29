"""Grieving the dispatch (§3.9) and reading the five-year dispatch record
(§2.10)."""

from datetime import timedelta

from flask import Blueprint

from core import (
    BASIS_POINT_SCALE, CLAIM_TYPES, DECISIONS, EVENT_CODES,
    GRIEVANCE_FILING_WINDOW_DAYS, GRIEVANCE_STATUSES, PURGE_STATES, REMEDIES,
    STANDARD_DAY_HOURS, db, days, new_id, now, round_half_up_div, touch,
)
from envelope import ApiError, created, listing, ok
from guards import (
    body, check_pagination_shape, pagination, paginate, q_enum, q_str, require,
    s_enum, s_str,
)
import domain
import serializers as S
import services

bp = Blueprint("griev", __name__)


def _dispatch_of_referral(referral_id):
    rows = [d for d in db.dispatches.values()
            if d["referral_id"] == referral_id and d["recall_of_dispatch_id"] is None]
    if not rows:
        rows = [d for d in db.dispatches.values() if d["referral_id"] == referral_id]
    rows.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return rows[0] if rows else None


def _weekday_count(start_at, decided_at):
    """Calendar dates in the half-open interval [date(start_at), date(decided_at))
    that fall Monday through Friday."""
    first = start_at.date()
    last = decided_at.date()
    count = 0
    current = first
    while current < last:
        if current.weekday() < 5:
            count += 1
        current = current + timedelta(days=1)
    return count


@bp.route("/hiring-hall/grievances", methods=["POST"])
def file_grievance():
    user_id, role = require("Member", "BusinessManager")
    check_pagination_shape()
    data = body()
    referral_id = s_str(data, "referral_id")
    claim_type = s_enum(data, "claim_type", CLAIM_TYPES)
    narrative = s_str(data, "narrative", min_len=1, max_len=2000)

    referral = db.referrals.get(referral_id)
    if referral is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", "No referral with id %s." % referral_id)

    clock = now()
    if clock > referral["issued_at"] + days(GRIEVANCE_FILING_WINDOW_DAYS):
        raise ApiError("ERR_GRIEVANCE_WINDOW_EXPIRED",
                       "The ten-day grievance filing window has closed.")

    record = {
        "id": new_id(),
        "referral_id": referral_id,
        "grievant_member_id": user_id,
        "claim_type": claim_type,
        "narrative": narrative,
        "filed_at": clock,
        "decided_by_user_id": None,
        "decided_at": None,
        "remedy": "NONE",
        "back_pay_variant": "NOT_APPLICABLE",
        "back_pay_hours": 0,
        "back_pay_amount_cents": 0,
        "status": "FILED",
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.grievances[record["id"]] = record
    return created(S.grievance_view(record))


@bp.route("/hiring-hall/grievances/<grievance_id>", methods=["GET"])
def read_grievance(grievance_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    check_pagination_shape()
    record = db.grievances.get(grievance_id)
    if record is None:
        raise ApiError("ERR_GRIEVANCE_NOT_FOUND", "No grievance with id %s." % grievance_id)
    return ok(S.grievance_view(record))


@bp.route("/hiring-hall/grievances", methods=["GET"])
def list_grievances():
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    referral_id = q_str("referral_id")
    grievant_member_id = q_str("grievant_member_id")
    status = q_enum("status", GRIEVANCE_STATUSES)
    claim_type = q_enum("claim_type", CLAIM_TYPES)
    limit, offset = pagination()
    rows = services.sort_default(db.grievances.values())
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if grievant_member_id is not None:
        rows = [r for r in rows if r["grievant_member_id"] == grievant_member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if claim_type is not None:
        rows = [r for r in rows if r["claim_type"] == claim_type]
    page, meta = paginate(rows, limit, offset)
    return listing([S.grievance_view(r) for r in page], meta)


@bp.route("/hiring-hall/grievances/<grievance_id>/review", methods=["POST"])
def review_grievance(grievance_id):
    require("BusinessManager")
    check_pagination_shape()
    body()
    record = db.grievances.get(grievance_id)
    if record is None:
        raise ApiError("ERR_GRIEVANCE_NOT_FOUND", "No grievance with id %s." % grievance_id)
    if record["status"] != "FILED":
        raise ApiError("ERR_GRIEVANCE_NOT_UNDER_REVIEW",
                       "Only a FILED grievance may be opened for review.")
    record["status"] = "UNDER_REVIEW"
    touch(record)
    return ok(S.grievance_view(record))


@bp.route("/hiring-hall/grievances/<grievance_id>/adjudicate", methods=["POST"])
def adjudicate_grievance(grievance_id):
    user_id, role = require("BusinessManager")
    check_pagination_shape()
    data = body()
    decision = s_enum(data, "decision", DECISIONS)
    remedy = s_enum(data, "remedy", REMEDIES, required=False, default="NONE")
    note = s_str(data, "note", required=False, min_len=None, max_len=2000, default=None)

    record = db.grievances.get(grievance_id)
    if record is None:
        raise ApiError("ERR_GRIEVANCE_NOT_FOUND", "No grievance with id %s." % grievance_id)
    referral = db.referrals.get(record["referral_id"])

    # 7 — segregation of duties
    if referral is not None and referral["issued_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The adjudicator issued the challenged referral.")

    # 14 — grievance state
    if record["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_GRIEVANCE_NOT_UNDER_REVIEW",
                       "Only an UNDER_REVIEW grievance may be decided.")

    dispatch = _dispatch_of_referral(record["referral_id"]) if referral else None

    # 24 — the evidence must still be retained
    if decision == "SUSTAINED" and record["claim_type"] == "OUT_OF_ORDER_DISPATCH":
        entries = [e for e in db.ledger.values()
                   if e["event_code"] == "REFERRAL_ISSUED"
                   and e["referral_id"] == record["referral_id"]]
        if not entries or all(e["purge_state"] == "PURGED" for e in entries):
            raise ApiError("ERR_DISPATCH_RECORD_PURGED",
                           "The issuance record has aged out of the retention period.")

    # 40 — remedy applicability
    if remedy == "MAKE_WHOLE_HOURS" and dispatch is None:
        raise ApiError("ERR_REMEDY_NOT_APPLICABLE",
                       "The challenged referral produced no dispatch.")
    if decision == "DENIED" and remedy != "NONE":
        raise ApiError("ERR_REMEDY_NOT_APPLICABLE",
                       "A denied grievance carries no remedy.")

    clock = now()
    record["decided_by_user_id"] = user_id
    record["decided_at"] = clock
    record["remedy"] = remedy
    record["status"] = "SUSTAINED" if decision == "SUSTAINED" else "DENIED"

    if decision == "SUSTAINED" and remedy == "NEXT_AVAILABLE_PRIORITY":
        for registration in services.sort_default(db.registrations.values()):
            if (registration["member_id"] == record["grievant_member_id"]
                    and registration["status"] == "REGISTERED"):
                registration["priority_flag"] = True
                touch(registration)
                break
        services.append_ledger("POSITION_RESTORED", record["grievant_member_id"],
                               record["referral_id"],
                               snapshot={"grievance_id": record["id"],
                                         "remedy": remedy})

    if decision == "SUSTAINED" and remedy == "MAKE_WHOLE_HOURS":
        job_request = db.job_requests.get(referral["job_request_id"])
        rate = job_request["hourly_rate_cents"] if job_request else 0
        grievant = db.members.get(record["grievant_member_id"])
        factor_bp = domain.classification_factor_bp(grievant)
        if dispatch["status"] == "WORKING":
            weekdays = _weekday_count(dispatch["start_at"], clock)
            per_day = round_half_up_div(
                STANDARD_DAY_HOURS * rate * factor_bp, BASIS_POINT_SCALE)
            record["back_pay_variant"] = "SCHEDULED_HOURS"
            record["back_pay_hours"] = weekdays * STANDARD_DAY_HOURS
            record["back_pay_amount_cents"] = per_day * weekdays
        else:
            worked = dispatch["hours_worked"] or 0
            record["back_pay_variant"] = "ACTUAL_HOURS"
            record["back_pay_hours"] = worked
            record["back_pay_amount_cents"] = round_half_up_div(
                worked * rate * factor_bp, BASIS_POINT_SCALE)
        services.append_ledger("MAKE_WHOLE_CREDITED", record["grievant_member_id"],
                               record["referral_id"],
                               snapshot={"grievance_id": record["id"],
                                         "back_pay_variant": record["back_pay_variant"],
                                         "back_pay_amount_cents":
                                             record["back_pay_amount_cents"]},
                               hours_delta=record["back_pay_hours"])

    services.append_ledger("GRIEVANCE_DECIDED", record["grievant_member_id"],
                           record["referral_id"],
                           snapshot={"grievance_id": record["id"],
                                     "decision": decision,
                                     "remedy": remedy,
                                     "note": note})
    touch(record)
    return ok(S.grievance_view(record))


# --------------------------------------------------------------------------
# the dispatch record
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/ledger-entries/<entry_id>", methods=["GET"])
def read_ledger_entry(entry_id):
    require("HallAdmin", "BusinessManager")
    check_pagination_shape()
    record = db.ledger.get(entry_id)
    if record is None:
        raise ApiError("ERR_LEDGER_ENTRY_NOT_FOUND",
                       "No ledger entry with id %s." % entry_id)
    return ok(S.ledger_view(record))


@bp.route("/hiring-hall/ledger-entries", methods=["GET"])
def list_ledger_entries():
    require("HallAdmin", "BusinessManager")
    member_id = q_str("member_id")
    referral_id = q_str("referral_id")
    event_code = q_enum("event_code", EVENT_CODES)
    purge_state = q_enum("purge_state", PURGE_STATES)
    limit, offset = pagination()
    rows = [r for r in db.ledger.values()]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if event_code is not None:
        rows = [r for r in rows if r["event_code"] == event_code]
    if purge_state is not None:
        rows = [r for r in rows if r["purge_state"] == purge_state]
    # documented exception: recorded_at ASC, created_at ASC
    rows.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))
    page, meta = paginate(rows, limit, offset)
    return listing([S.ledger_view(r) for r in page], meta)

"""Statutory eligibility analyses and benefit assessments."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_int, req_enum,
    get_case, ser_analysis, ser_assessment, touch,
    apply_case_round_expiry, completed_periods,
    VARIANTS, NOTICE_MIN_HOURS, FIVE_YEAR_CAP_DAYS,
    BAND_SHORT_MAX_DAYS, BAND_MID_MAX_DAYS,
    DEADLINE_DAYS_SHORT, DEADLINE_DAYS_MID, DEADLINE_DAYS_LONG,
    DAYS_PER_MONTH, HEALTH_CAP_MONTHS,
)
from routes_cases import _case_party_check
from store import db
from util import now, new_id, success, paginate

bp = Blueprint("analysis", __name__)

_DPM = Decimal(DAYS_PER_MONTH)
_CENT = Decimal("0.01")


def _r2(x):
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


@bp.route("/reemployment/cases/<cid>/eligibility-analysis", methods=["POST"])
def create_analysis(cid):
    role, uid = require_role("Ombudsman", "ProgramCoordinator")
    body = body_json()
    variant = req_enum(body, "variant", VARIANTS)
    expected = req_int(body, "expected_case_version")
    case = get_case(cid)
    apply_case_round_expiry(case)
    if role == "Ombudsman":
        require_ownership(case["assigned_ombudsman_id"] == uid)
    # OCC (priority 7) precedes the business checks (priority 10).
    if expected != case["version"]:
        raise ApiError(
            "ERR_STALE_CASE_VERSION", 412,
            "expected_case_version does not match the case's current version",
        )
    # (1) Disputed-period selection: completed periods of the pair, most
    # recent by end_date, then start_date, then created_at; never by id.
    periods = completed_periods(case["member_id"], case["employer_id"])
    if not periods:
        raise ApiError(
            "ERR_NO_COMPLETED_SERVICE_PERIOD", 422,
            "No completed service period exists for this member-employer pair",
        )
    disputed = sorted(
        periods,
        key=lambda p: (p["end_date"], p["start_date"], p["created_at"]),
        reverse=True,
    )[0]
    d = disputed["duration_days"]
    # (2) Notice, in hours from notice_given_at to start_date.
    notice_given = disputed["notice_given_at"]
    if notice_given is None:
        notice_hours = None
        strict_ok = False
    else:
        notice_hours = (disputed["start_date"] - notice_given).total_seconds() / 3600.0
        strict_ok = notice_hours >= NOTICE_MIN_HOURS
    if variant == "STRICT":
        notice_ok = strict_ok
    else:
        notice_ok = strict_ok or bool(
            case["excuse_claimed"] and case["excuse_category"] is not None
        )
    # (3) Cumulative chargeable cap (cap-exempt orders excluded).
    cumulative = sum(p["duration_days"] for p in periods if p["chargeable"])
    limit_ok = cumulative <= FIVE_YEAR_CAP_DAYS
    # (4) Deadline band keyed on the disputed period's duration.
    if d <= BAND_SHORT_MAX_DAYS:
        band = "SHORT"
        deadline_days = DEADLINE_DAYS_SHORT
        escalator = "SAME_POSITION"
    elif d <= BAND_MID_MAX_DAYS:
        band = "MID"
        deadline_days = DEADLINE_DAYS_MID
        escalator = "SENIORITY_ESCALATED"
    else:
        band = "LONG"
        deadline_days = DEADLINE_DAYS_LONG
        escalator = "ESCALATED_WITH_RETRAINING"
    deadline_date = disputed["end_date"] + timedelta(days=deadline_days)
    app_sub = case["application_submitted_at"]
    deadline_ok = app_sub is not None and app_sub <= deadline_date
    overall = bool(notice_ok) and limit_ok and deadline_ok
    seq = 1 + sum(1 for a in db.analyses.values() if a["case_id"] == cid)
    aid = new_id()
    a = {
        "id": aid, "case_id": cid, "sequence_number": seq, "variant": variant,
        "notice_hours_advance": notice_hours,
        "notice_satisfied": bool(notice_ok),
        "cumulative_chargeable_days": cumulative,
        "service_limit_ok": limit_ok,
        "disputed_period_duration_days": d,
        "duration_band": band,
        "application_deadline_days": deadline_days,
        "application_deadline_date": deadline_date,
        "deadline_satisfied": deadline_ok,
        "escalator_position_class": escalator,
        "overall_eligible": overall,
        "created_at": now(), "_seq": db.next_seq(),
    }
    db.analyses[aid] = a
    touch(case)
    return success(ser_analysis(a), "object", 201)


@bp.route("/reemployment/cases/<cid>/eligibility-analyses", methods=["GET"])
def list_analyses(cid):
    role, uid = require_role("ServiceMember", "Employer", "Ombudsman",
                             "ProgramCoordinator")
    case = get_case(cid)
    _case_party_check(case, role, uid)
    items = [a for a in db.analyses.values() if a["case_id"] == cid]
    items.sort(key=lambda a: a["sequence_number"])  # newest sequence last
    page, meta = paginate(items)
    return success([ser_analysis(a) for a in page], "array", 200, meta)


@bp.route("/reemployment/benefit-assessments", methods=["POST"])
def create_assessment():
    role, uid = require_role("Ombudsman", "ProgramCoordinator")
    body = body_json()
    case_id = req_str(body, "case_id")
    case = get_case(case_id)
    if role == "Ombudsman":
        require_ownership(case["assigned_ombudsman_id"] == uid)
    # One assessment per case (state gate).
    if any(b["case_id"] == case_id for b in db.assessments.values()):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "A benefit assessment already exists for this case",
        )
    periods = completed_periods(case["member_id"], case["employer_id"])
    if not periods:
        raise ApiError(
            "ERR_NO_COMPLETED_SERVICE_PERIOD", 422,
            "No completed service period exists for this member-employer pair",
        )
    # Pension and health math count every completed period, chargeable and
    # cap-exempt alike.
    total_days = sum(p["duration_days"] for p in periods)
    raw_months = _r2(Decimal(total_days) / _DPM)
    health = min(raw_months, Decimal(HEALTH_CAP_MONTHS))
    official = _r2(sum(
        (_r2(Decimal(p["duration_days"]) / _DPM) for p in periods),
        Decimal(0),
    ))
    alternate = _r2(Decimal(total_days) / _DPM)
    education_required = case["issue_type"] in ("BENEFITS", "PENSION")
    bid = new_id()
    b = {
        "id": bid, "case_id": case_id,
        "health_continuation_months": health,
        "pension_credit_months_official": official,
        "pension_credit_months_alternate": alternate,
        "education_required": education_required,
        "created_at": now(), "_seq": db.next_seq(),
    }
    db.assessments[bid] = b
    return success(ser_assessment(b), "object", 201)


@bp.route("/reemployment/cases/<cid>/benefit-assessments", methods=["GET"])
def list_assessments(cid):
    role, uid = require_role("ServiceMember", "Employer", "Ombudsman",
                             "ProgramCoordinator")
    case = get_case(cid)
    _case_party_check(case, role, uid)
    items = [b for b in db.assessments.values() if b["case_id"] == cid]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, meta = paginate(items)
    return success([ser_assessment(b) for b in page], "array", 200, meta)

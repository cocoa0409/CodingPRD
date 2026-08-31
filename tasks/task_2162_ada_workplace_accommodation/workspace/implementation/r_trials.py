"""Trial periods, effectiveness check-ins and trial resolution."""
from datetime import timedelta

from flask import Blueprint, g, request as flask_request

import calc
import domain
from authz import (endpoint, need_option, need_request, need_trial,
                   require_case_owner, require_manager_scope_case, require_not_sealed)
from envelope import created, listing, ok, read_pagination, touch
from errors import ApiError
from store import by_created, parse_date, store
from validation import F, bad, raw_body, validate

bp = Blueprint("trials", __name__)

TRIAL_SPEC = [
    F("request_id", "id", required=True),
    F("option_id", "id", required=True),
    F("start_date", "date", required=True),
    F("end_date", "date", required=True),
    F("checkin_cadence_days", "integer", default=14, has_default=True,
      minimum=1, maximum=90),
    F("scoring_mode", "enum", default="LATEST_WEIGHTED", has_default=True,
      enum=("CUMULATIVE_MEAN", "LATEST_WEIGHTED")),
]


@bp.post("/trial-periods")
@endpoint(["AccommodationCoordinator"])
def create_trial():
    data = validate(raw_body(), TRIAL_SPEC)
    start = parse_date(data["start_date"])
    end = parse_date(data["end_date"])
    if end < start:
        bad("end_date may not fall before start_date.")
    req = need_request(data["request_id"])
    option = need_option(data["option_id"])
    if req["stage"] != "TRIAL_SETUP" or option["id"] != req.get("selected_option_id") \
            or option["status"] != "SELECTED":
        raise ApiError("ERR_INVALID_STAGE_TRANSITION",
                       "A trial cannot be scheduled for this case and option.")
    require_not_sealed(req)

    employee_id = req["employee_id"]
    washout = timedelta(days=calc.TRIAL_WASHOUT_DAYS)
    for other in store.trials.values():
        if other["employee_id"] != employee_id:
            continue
        o_start = parse_date(other["start_date"])
        o_end = parse_date(other["end_date"])
        if start <= o_end + washout and end >= o_start - washout:
            raise ApiError("ERR_TRIAL_WINDOW_CONFLICT",
                           "The trial interval collides with another trial.")
    for absence in store.absences.values():
        if absence["employee_id"] != employee_id or absence["status"] != "ACTIVE":
            continue
        if absence["record_type"] not in ("FMLA_CONTINUOUS", "STATE_LEAVE"):
            continue
        a_start = parse_date(absence["start_date"])
        a_end = parse_date(absence["end_date"])
        if start < a_end and end >= a_start:
            raise ApiError("ERR_TRIAL_BLOCKED_BY_ABSENCE",
                           "Continuous leave blocks the trial interval.")
    linked = store.absences.get(req.get("absence_record_id") or "")
    if linked is not None and linked["record_type"] == "WC_RESTRICTION" \
            and linked["status"] != "MODIFIED_DUTY":
        raise ApiError("ERR_WC_MODIFIED_DUTY_REQUIRED",
                       "The workers'-compensation restriction is not on modified duty.")

    row = store.new_row("TrialPeriod", {
        "request_id": req["id"],
        "option_id": option["id"],
        "employee_id": employee_id,
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "checkin_cadence_days": data["checkin_cadence_days"],
        "scoring_mode": data["scoring_mode"],
        "review_count": 0,
        "effectiveness_score": None,
        "extension_count": 0,
        "outcome": "PENDING",
        "status": "SCHEDULED",
    })
    store.trials[row["id"]] = row
    domain.assign(req, stage="TRIAL_ACTIVE")
    return created(row)


@bp.get("/trial-periods/<trial_id>")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "FinanceOfficer",
           "AppealOfficer", "ComplianceAuditor"])
def get_trial(trial_id):
    return ok(need_trial(trial_id))


@bp.get("/trial-periods")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "ComplianceAuditor"])
def list_trials():
    limit, offset = read_pagination()
    rows = list(store.trials.values())
    for key in ("request_id", "option_id", "employee_id", "status"):
        value = flask_request.args.get(key)
        if value is not None:
            rows = [t for t in rows if t[key] == value]
    return listing(by_created(rows), limit, offset)


@bp.post("/trial-periods/<trial_id>/effectiveness-reviews")
@endpoint(["Manager", "Employee", "AccommodationCoordinator"])
def create_review(trial_id):
    data = validate(raw_body(), [
        F("employee_rating", "integer", required=True, minimum=0, maximum=10),
        F("manager_rating", "integer", required=True, minimum=0, maximum=10),
        F("objective_metric_pct", "integer", required=True, minimum=0, maximum=100),
    ])
    trial = need_trial(trial_id)
    req = store.requests.get(trial["request_id"])
    require_case_owner(req)
    require_manager_scope_case(req)
    if trial["status"] not in ("ACTIVE", "UNDER_REVIEW"):
        raise ApiError("ERR_TRIAL_NOT_RESOLVABLE",
                       "Check-ins may only be recorded on an ACTIVE or UNDER_REVIEW trial.")
    require_not_sealed(req)
    composite = calc.review_composite(data["employee_rating"], data["manager_rating"],
                                      data["objective_metric_pct"])
    row = store.new_row("EffectivenessReview", {
        "trial_period_id": trial["id"],
        "review_index": trial["review_count"] + 1,
        "review_date": store.today().isoformat(),
        "employee_rating": data["employee_rating"],
        "manager_rating": data["manager_rating"],
        "objective_metric_pct": data["objective_metric_pct"],
        "reviewer_user_id": g.user_id,
        "review_composite": calc.as_number(composite),
    })
    store.reviews[row["id"]] = row
    trial["review_count"] = trial["review_count"] + 1
    trial["effectiveness_score"] = calc.effectiveness_score(trial)
    if trial["status"] == "ACTIVE" and trial["review_count"] >= calc.MIN_TRIAL_REVIEWS:
        trial["status"] = "UNDER_REVIEW"
        trial["effectiveness_score"] = calc.effectiveness_score(trial)
    touch(trial)
    return created(row)


@bp.get("/trial-periods/<trial_id>/effectiveness-reviews")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "ComplianceAuditor"])
def list_reviews(trial_id):
    limit, offset = read_pagination()
    need_trial(trial_id)
    rows = [r for r in store.reviews.values() if r["trial_period_id"] == trial_id]
    return listing(by_created(rows), limit, offset)


# ========================= Trial resolution ==============================
@bp.post("/trial-periods/<trial_id>/resolve")
@endpoint(["AccommodationCoordinator"])
def resolve_trial(trial_id):
    data = validate(raw_body(), [F("outcome", "enum", required=True,
                                   enum=("EFFECTIVE", "INEFFECTIVE", "EXTEND", "ABORT"))])
    trial = need_trial(trial_id)
    req = store.requests.get(trial["request_id"])
    outcome = data["outcome"]
    status = trial["status"]

    if outcome in ("EFFECTIVE", "INEFFECTIVE", "EXTEND"):
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_TRIAL_NOT_RESOLVABLE",
                           "That outcome is not available from the trial's status.")
    else:
        if status not in ("SCHEDULED", "ACTIVE", "UNDER_REVIEW"):
            raise ApiError("ERR_TRIAL_NOT_RESOLVABLE",
                           "That outcome is not available from the trial's status.")
    require_not_sealed(req)

    if outcome == "INEFFECTIVE":
        if req["interactive_round_count"] + 1 > calc.MAX_INTERACTIVE_ROUNDS:
            raise ApiError("ERR_INTERACTIVE_ROUND_LIMIT",
                           "The interactive-round allowance is exhausted.")
    if outcome in ("EFFECTIVE", "INEFFECTIVE"):
        if trial["review_count"] < calc.MIN_TRIAL_REVIEWS:
            raise ApiError("ERR_INSUFFICIENT_TRIAL_REVIEWS",
                           "The trial does not carry enough effectiveness check-ins.")
        score = trial["effectiveness_score"]
        current = calc.dec(score) if score is not None else None
        agrees = (current is not None and (
            current >= calc.EFFECTIVE_THRESHOLD if outcome == "EFFECTIVE"
            else current < calc.EFFECTIVE_THRESHOLD))
        if not agrees:
            raise ApiError("ERR_TRIAL_OUTCOME_MISMATCH",
                           "The requested outcome contradicts the computed score.")
    if outcome == "EXTEND":
        if trial["extension_count"] + 1 > calc.MAX_TRIAL_EXTENSIONS:
            raise ApiError("ERR_TRIAL_EXTENSION_LIMIT",
                           "The trial extension allowance is exhausted.")

    option = store.options.get(trial["option_id"])
    if outcome == "EFFECTIVE":
        trial["status"] = "CONCLUDED_EFFECTIVE"
        trial["outcome"] = "EFFECTIVE"
        touch(trial)
        if option is not None:
            domain.assign(option, status="IMPLEMENTED")
        domain.assign(req, stage="GRANTED_PERMANENT")
        cadence, due = calc.renewal_cadence(req)
        domain.assign(req, review_cadence_days=cadence, review_due_date=due)
    elif outcome == "INEFFECTIVE":
        trial["status"] = "CONCLUDED_INEFFECTIVE"
        trial["outcome"] = "INEFFECTIVE"
        touch(trial)
        if option is not None:
            domain.assign(option, status="TRIAL_FAILED")
            domain.ledger_release(option, req)
        domain.assign(req, stage="OPTION_EXPLORATION",
                      interactive_round_count=req["interactive_round_count"] + 1)
        domain.refresh_doc_limit(req)
    elif outcome == "EXTEND":
        trial["extension_count"] = trial["extension_count"] + 1
        end = parse_date(trial["end_date"]) + timedelta(days=calc.TRIAL_EXTENSION_DAYS)
        trial["end_date"] = end.isoformat()
        trial["status"] = "ACTIVE"
        touch(trial)
    else:
        trial["status"] = "ABORTED"
        trial["outcome"] = "ABORTED"
        touch(trial)
        domain.assign(req, stage="TRIAL_SETUP")
    return ok(trial)

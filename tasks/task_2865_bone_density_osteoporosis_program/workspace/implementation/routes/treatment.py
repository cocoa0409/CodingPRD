"""Treatment plans, the refill ledger and the adherence review cycle."""
from flask import Blueprint, request

import calc
import queries
import validate
from db import base_record, db, public, today, touch
from errors import ApiError
from middleware import (INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER, PROGRAM_ADMIN,
                        actor_id, endpoint, enforce_patient_scope, is_portal)
from response import created, ok, paginated
from util import add_months, fmt_date, parse_date, parse_instant

bp = Blueprint("treatment", __name__)

DRUG_CLASSES = ("BISPHOSPHONATE_ORAL", "BISPHOSPHONATE_IV", "DENOSUMAB",
                "ANABOLIC_PTH", "SERM")
SOURCE_POLICIES = ("CLAIMS_ONLY", "ALL_SOURCES_WEIGHTED")
REFILL_SOURCES = ("PHARMACY_CLAIM", "PATIENT_REPORT")
REQUESTED_ACTIONS = ("AUTO", "START_DRUG_HOLIDAY", "RESUME_THERAPY", "DISCONTINUE")
DISCONTINUATION_REASONS = ("ADVERSE_EVENT", "GOAL_MET", "PATIENT_REQUEST",
                           "ADHERENCE_FAILURE")
DISCONTINUABLE = ("INITIATED", "ON_THERAPY", "ADHERENCE_HOLD", "DRUG_HOLIDAY")


def _filtered(rows, filters):
    result = rows
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None and wanted != "":
            result = [row for row in result if str(row.get(field)) == wanted]
    return result


def _plan_not_terminal(plan):
    if plan["status"] == "DISCONTINUED":
        raise ApiError("ERR_TREATMENT_PLAN_TERMINAL",
                       "The treatment plan is DISCONTINUED.")


@bp.post("/treatment-plans")
@endpoint(INTERPRETING_PHYSICIAN)
def create_treatment_plan():
    body = validate.body()
    patient_id = validate.string(body, "patient_id")
    report_id = validate.string(body, "initiating_report_id")
    drug_class = validate.enum(body, "drug_class", DRUG_CLASSES)
    start_date = validate.date_field(body, "start_date")
    source_policy = validate.enum(body, "adherence_source_policy", SOURCE_POLICIES,
                                  required=False, default="CLAIMS_ONLY")

    patient = queries.patient(patient_id)
    report = queries.report(report_id)
    if report["status"] != "FINALIZED":
        raise ApiError("ERR_REPORT_NOT_FINALIZED", "The initiating report is not FINALIZED.")
    session = db.scan_sessions.get(report["scan_session_id"])
    if session is None or session["patient_id"] != patient_id:
        raise ApiError("ERR_FRAX_PATIENT_MISMATCH",
                       "The initiating report belongs to a different patient.")
    if report["recommended_action"] != "INITIATE_TREATMENT":
        validate.bad("The initiating report does not recommend INITIATE_TREATMENT.")
    finalized_date = parse_instant(report["finalized_at_utc"]).date()
    if start_date < finalized_date:
        validate.bad("start_date may not precede the report's finalization date.")

    interval = calc.FOLLOWUP_INTERVAL_MONTHS[drug_class]
    record = base_record()
    record.update({
        "patient_id": patient_id,
        "initiating_report_id": report_id,
        "drug_class": drug_class,
        "start_date": fmt_date(start_date),
        "adherence_source_policy": source_policy,
        "status": "INITIATED",
        "followup_interval_months": interval,
        "next_followup_due_date": fmt_date(add_months(start_date, interval)),
        "last_review_date": None,
        "adherence_window_days": None,
        "covered_days_supplied": None,
        "medication_possession_ratio": None,
        "adherence_status": "NOT_ASSESSED",
        "adherence_review_count": 0,
        "consecutive_nonadherent_reviews": 0,
        "denosumab_gap_days": None,
        "cumulative_therapy_months": 0,
        "holiday_eligible": False,
        "discontinuation_reason_code": None,
    })
    db.treatment_plans[record["id"]] = record
    return created(public(record))


@bp.get("/treatment-plans/<plan_id>")
@endpoint(PROGRAM_ADMIN, INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER)
def get_treatment_plan(plan_id):
    plan = queries.plan(plan_id)
    if is_portal():
        enforce_patient_scope(plan["patient_id"])
    return ok(public(plan))


@bp.get("/treatment-plans")
@endpoint(PROGRAM_ADMIN, INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER)
def list_treatment_plans():
    rows = _filtered(list(db.treatment_plans.values()), {
        "patient_id": "patient_id",
        "initiating_report_id": "initiating_report_id",
        "status": "status",
    })
    if is_portal():
        rows = [row for row in rows if row["patient_id"] == actor_id()]
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]))
    return paginated(rows, public)


@bp.post("/treatment-plans/<plan_id>/adherence-refills")
@endpoint(PATIENT_PORTAL_USER, INTERPRETING_PHYSICIAN)
def create_adherence_refill(plan_id):
    body = validate.body()
    dispensed_date = validate.date_field(body, "dispensed_date")
    days_supplied = validate.integer(body, "days_supplied", minimum=1, maximum=400)
    source = validate.enum(body, "source", REFILL_SOURCES)

    plan = queries.plan(plan_id)
    if is_portal():
        enforce_patient_scope(plan["patient_id"])
    _plan_not_terminal(plan)
    start_date = parse_date(plan["start_date"])
    if dispensed_date < start_date or dispensed_date >= today():
        raise ApiError("ERR_REFILL_DATE_OUT_OF_WINDOW",
                       "dispensed_date falls outside the plan's reporting window.", 422)

    weight = (calc.REFILL_PHARMACY_CLAIM_WEIGHT if source == "PHARMACY_CLAIM"
              else calc.REFILL_PATIENT_REPORT_WEIGHT)
    record = base_record(versioned=False)
    record.update({
        "treatment_plan_id": plan_id,
        "dispensed_date": fmt_date(dispensed_date),
        "days_supplied": days_supplied,
        "source": source,
        "source_weight": weight,
        "coverage_end_date": fmt_date(dispensed_date + calc._days(days_supplied)),
        "recorded_by_user_id": actor_id(),
    })
    db.adherence_refills[record["id"]] = record
    return created(public(record))


@bp.get("/treatment-plans/<plan_id>/adherence-refills")
@endpoint(PROGRAM_ADMIN, INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER)
def list_adherence_refills(plan_id):
    plan = queries.plan(plan_id)
    if is_portal():
        enforce_patient_scope(plan["patient_id"])
    rows = _filtered(queries.refills_of_plan(plan_id), {"source": "source"})
    rows.sort(key=lambda row: (row["dispensed_date"], row["created_at"], row["_seq"]))
    return paginated(rows, public)


def _last_finalized_session(patient):
    report_id = patient["last_finalized_report_id"]
    if report_id is None:
        return None
    report = db.diagnostic_reports.get(report_id)
    if report is None:
        return None
    return db.scan_sessions.get(report["scan_session_id"])


def _resolve_status(plan, action, verdict, reason_code, review_date, gap_exceeded):
    """PRD 3.9: the explicit actions first, then the automatic resolution."""
    interval = plan["followup_interval_months"]
    status = plan["status"]
    if action == "START_DRUG_HOLIDAY" and status == "ON_THERAPY" \
            and plan["holiday_eligible"] and verdict == "ADHERENT":
        plan["status"] = "DRUG_HOLIDAY"
        return calc.HOLIDAY_REVIEW_INTERVAL_MONTHS
    if action == "RESUME_THERAPY" and status == "DRUG_HOLIDAY":
        plan["status"] = "ON_THERAPY"
        return interval
    if action == "DISCONTINUE" and status in DISCONTINUABLE:
        plan["status"] = "DISCONTINUED"
        plan["discontinuation_reason_code"] = reason_code
        return interval

    if verdict in ("ADHERENT", "PARTIAL") and not gap_exceeded:
        plan["consecutive_nonadherent_reviews"] = 0
        if status in ("INITIATED", "ADHERENCE_HOLD"):
            plan["status"] = "ON_THERAPY"
        return interval
    if verdict == "NON_ADHERENT" or gap_exceeded:
        if status in ("INITIATED", "ON_THERAPY"):
            plan["status"] = "ADHERENCE_HOLD"
            plan["consecutive_nonadherent_reviews"] += 1
        elif status == "ADHERENCE_HOLD":
            plan["consecutive_nonadherent_reviews"] += 1
            if plan["consecutive_nonadherent_reviews"] >= \
                    calc.MAX_CONSECUTIVE_NONADHERENT_REVIEWS:
                plan["status"] = "DISCONTINUED"
                plan["discontinuation_reason_code"] = "ADHERENCE_FAILURE"
    return interval


@bp.post("/treatment-plans/<plan_id>/adherence-review")
@endpoint(INTERPRETING_PHYSICIAN)
def create_adherence_review(plan_id):
    body = validate.body()
    action = validate.enum(body, "requested_action", REQUESTED_ACTIONS,
                           required=False, default="AUTO")
    note = validate.string(body, "note", required=False, max_len=480)
    reason_code = validate.enum(body, "discontinuation_reason_code",
                                DISCONTINUATION_REASONS, required=False)
    if action == "DISCONTINUE" and reason_code is None:
        validate.bad("discontinuation_reason_code is required to discontinue a plan.")

    plan = queries.plan(plan_id)
    _plan_not_terminal(plan)
    review_date = today()
    due_date = parse_date(plan["next_followup_due_date"])
    if review_date < due_date - calc._days(calc.FOLLOWUP_EARLY_WINDOW_DAYS):
        raise ApiError("ERR_FOLLOWUP_NOT_DUE", "The follow-up review is not yet due.")

    start_date = parse_date(plan["start_date"])
    metrics = calc.adherence_metrics(plan, queries.refills_of_plan(plan_id),
                                     review_date, start_date)
    gap_days = metrics["denosumab_gap_days"]
    gap_exceeded = gap_days is not None and gap_days > calc.DENOSUMAB_MAX_GAP_DAYS
    if gap_exceeded:
        metrics["adherence_status"] = "NON_ADHERENT"
    plan.update(metrics)

    plan["last_review_date"] = fmt_date(review_date)
    plan["cumulative_therapy_months"] = calc.cumulative_therapy_months(
        start_date, review_date)
    patient = db.patients[plan["patient_id"]]
    plan["holiday_eligible"] = calc.holiday_eligible(
        plan, plan["cumulative_therapy_months"], _last_finalized_session(patient))

    interval = _resolve_status(plan, action, metrics["adherence_status"], reason_code,
                               review_date, gap_exceeded)
    plan["adherence_review_count"] += 1
    plan["next_followup_due_date"] = fmt_date(add_months(review_date, interval))
    if plan["status"] != "DISCONTINUED":
        plan["discontinuation_reason_code"] = None
    touch(plan)
    return ok(public(plan))

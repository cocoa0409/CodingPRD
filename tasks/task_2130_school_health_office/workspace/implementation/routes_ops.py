"""The logical clock and the daily operational checkpoint."""
from flask import Blueprint, request

import calc
import cascades
from auth import authorize, must_exist, rows
from envelope import ok
from store import db, days, iso, parse_dt, sorted_rows, touch
from validators import Field, get_body, supplied, validate

bp = Blueprint("ops", __name__)


@bp.post("/health-office/_clock/set_current_utc")
def set_clock():
    authorize(["DistrictHealthAdmin"])
    body = get_body(request)
    values = validate(body, [Field("to_iso8601", "datetime")])
    previous = db.set_clock(parse_dt(values["to_iso8601"]))
    return ok({"current_utc": iso(db.now()), "previous_utc": iso(previous)})


def _student_school(student_id):
    student = db.students.get(student_id)
    return student["school_id"] if student else None


@bp.post("/health-office/_ops/run-daily-checkpoint")
def run_daily_checkpoint():
    authorize(["DistrictHealthAdmin"])
    body = get_body(request)
    school_filter = None
    if body.get("school_id") is not None:
        school_filter = must_exist("schools", body.get("school_id"), "School")["id"]
    validate(body, [Field("school_id", "string", required=False)])

    clock = db.now()
    expired_plans = []
    expired_authorizations = []
    expired_lots = []
    expired_disclosures = []
    promoted_screenings = []
    voided_records = []

    def in_scope_student(student_id):
        if school_filter is None:
            return True
        return _student_school(student_id) == school_filter

    # 1 - action plans past their review date
    for plan in sorted_rows(rows("action_plans")):
        if plan["status"] != "ACTIVE":
            continue
        if plan.get("review_due_at") is None or not plan["review_due_at"] <= clock:
            continue
        if not in_scope_student(plan["student_id"]):
            continue
        plan["status"] = "EXPIRED"
        touch(plan)
        expired_plans.append(plan["id"])
        voided_records.extend(
            cascades.suspend_orders_for_plan(plan, ("UNVERIFIED", "VERIFIED")))

    # 2 - medication orders whose validity window has closed
    for auth in sorted_rows(rows("medication_authorizations")):
        if auth["clinical_status"] not in ("UNVERIFIED", "VERIFIED", "SUSPENDED"):
            continue
        if not clock >= auth["valid_until"]:
            continue
        if not in_scope_student(auth["student_id"]):
            continue
        auth["clinical_status"] = "EXPIRED"
        touch(auth)
        expired_authorizations.append(auth["id"])
        voided_records.extend(cascades.void_prepared_for_authorization(auth["id"]))

    # 3 - stock lots past their expiration instant
    for lot in sorted_rows(rows("medication_stock_lots")):
        if lot["status"] not in ("AVAILABLE", "QUARANTINED", "DEPLETED"):
            continue
        if not lot["expiration_date"] <= clock:
            continue
        if school_filter is not None and lot["school_id"] != school_filter:
            continue
        lot["status"] = "EXPIRED"
        touch(lot)
        expired_lots.append(lot["id"])
        voided_records.extend(cascades.void_prepared_for_lot(lot["id"]))

    # 4 - approved but unreleased disclosure requests
    for row in sorted_rows(rows("disclosure_requests")):
        if row["status"] != "APPROVED":
            continue
        expires_at = row.get("expires_at")
        if expires_at is None or not clock >= expires_at:
            continue
        if not in_scope_student(row["student_id"]):
            continue
        row["status"] = "EXPIRED"
        row["release_package_item_count"] = 0
        touch(row)
        expired_disclosures.append(row["id"])

    # 5 - overdue rescreens promoted to referral
    for screening in sorted_rows(rows("screenings")):
        if screening["status"] != "RESCREEN_DUE":
            continue
        due = screening.get("rescreen_due_at")
        if due is None or not due <= clock:
            continue
        if school_filter is not None and screening["school_id"] != school_filter:
            continue
        screening["status"] = "REFERRED"
        screening["outcome"] = "REFER"
        screening["referral_due_at"] = clock + days(calc.REFERRAL_DAYS)
        touch(screening)
        promoted_screenings.append(screening["id"])

    # 6 - re-run every derived figure
    recomputed_schools = []
    for school in sorted_rows(rows("schools")):
        if school_filter is not None and school["id"] != school_filter:
            continue
        calc.school_derived(school)
        recomputed_schools.append(school["id"])
    for student in sorted_rows(rows("students")):
        if school_filter is not None and student["school_id"] != school_filter:
            continue
        cascades.recompute_observed(student)

    db.epoch += 1
    return ok({
        "epoch": db.epoch,
        "expired_action_plan_ids": expired_plans,
        "expired_authorization_ids": expired_authorizations,
        "expired_lot_ids": expired_lots,
        "expired_disclosure_ids": expired_disclosures,
        "promoted_screening_ids": promoted_screenings,
        "voided_administration_ids": voided_records,
        "recomputed_school_ids": recomputed_schools,
    })

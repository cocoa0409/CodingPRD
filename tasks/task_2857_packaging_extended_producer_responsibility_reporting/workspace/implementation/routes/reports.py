"""Packaging report and report line endpoints (PRD 3.7, 3.8)."""
from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, VERIFIER, endpoint, must,
                  new_row, require_producer_owner, touch, user_id)
from envelope import ok, ok_entity, ok_list
from errors import fail
from routes.common import bool_filter, enum_filter, listing, str_filter

bp = Blueprint("reports", __name__)

ALL = [REGULATOR, OFFICER, PRO_ADMIN, VERIFIER]
OPEN_SUBMISSIONS = ("DRAFT", "SUBMITTED", "UNDER_VERIFICATION", "CORRECTION_REQUIRED")


def context_of(report):
    registration = store.get("registrations", report["registration_id"])
    program = store.get("state_programs", registration["state_program_id"])
    period = store.get("reporting_periods", report["reporting_period_id"])
    return registration, program, period


def refresh_lines(report, program):
    """Recompute every line's weight, then the report's rollups."""
    for line in calc.lines_of(report["id"]):
        sku = store.get("skus", line["sku_id"])
        line["line_weight_kg"] = calc.line_weight(sku, line["units_sold"])
        touch(line)
    calc.recompute_report_rollups(report)
    report["verification_required"] = calc.D(report["total_weight_kg"]) >= calc.D(
        program["verification_required_threshold_kg"]
    )


def require_paid_membership(registration, allow_probation):
    membership = calc.live_membership(registration["id"])
    if membership is None:
        fail("ERR_NO_ACTIVE_MEMBERSHIP")
    if not allow_probation and membership["status"] != "ACTIVE":
        fail("ERR_MEMBERSHIP_NOT_ACTIVE")
    if membership["fee_payment_status"] != "PAID":
        fail("ERR_MEMBERSHIP_FEE_OUTSTANDING")
    return membership


@bp.post("/epr/reports")
@endpoint([OFFICER])
def create_report():
    body = v.body()
    registration_id = v.req_str(body, "registration_id")
    period_id = v.req_str(body, "reporting_period_id")
    registration = must("registrations", registration_id)
    period = must("reporting_periods", period_id)
    require_producer_owner(registration["producer_id"])
    if registration["status"] != "ACTIVE":
        fail("ERR_REGISTRATION_NOT_ACTIVE")
    if registration["exemption_status"] in ("EXEMPT_SMALL_PRODUCER", "EXEMPT_CATEGORY"):
        fail("ERR_EXEMPT_REGISTRATION_CANNOT_REPORT")
    if period["state_program_id"] != registration["state_program_id"]:
        fail("ERR_PERIOD_PROGRAM_MISMATCH")
    for other in calc.reports_of(registration["id"]):
        if other["reporting_period_id"] != period["id"]:
            continue
        if other["submission_status"] != "REJECTED":
            fail("ERR_DUPLICATE_REPORT_FOR_PERIOD")
    row = new_row(
        "reports",
        {
            "registration_id": registration["id"],
            "reporting_period_id": period["id"],
            "submission_status": "DRAFT",
            "fee_status": "UNASSESSED",
            "total_weight_kg": calc.ZERO_KG,
            "fee_basis_weight_kg": calc.ZERO_KG,
            "tier_basis_kg": calc.ZERO_KG,
            "fee_subtotal_cents": 0,
            "fee_variant_applied": "NONE",
            "verification_required": False,
            "correction_round": 0,
            "correction_due_at": None,
            "submitted_at": None,
            "submitted_by_user_id": None,
            "line_count": 0,
            "_correction_due_at": None,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/reports/<rid>")
@endpoint(ALL)
def get_report(rid):
    return ok_entity(must("reports", rid))


@bp.get("/epr/reports")
@endpoint(ALL)
def list_reports():
    registration_id = str_filter("registration_id")
    period_id = str_filter("reporting_period_id")
    submission = enum_filter("submission_status", v.SUBMISSION_STATUSES)
    fee = enum_filter("fee_status", v.FEE_STATUSES)
    rows = store.values("reports")
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if period_id is not None:
        rows = [r for r in rows if r["reporting_period_id"] == period_id]
    if submission is not None:
        rows = [r for r in rows if r["submission_status"] == submission]
    if fee is not None:
        rows = [r for r in rows if r["fee_status"] == fee]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/reports/<rid>/lines")
@endpoint([OFFICER])
def add_line(rid):
    body = v.body()
    sku_id = v.req_str(body, "sku_id")
    units_sold = v.req_int(body, "units_sold", minimum=0)
    report = must("reports", rid)
    sku = must("skus", sku_id)
    registration, program, _period = context_of(report)
    require_producer_owner(registration["producer_id"])
    if registration["status"] != "ACTIVE":
        fail("ERR_REGISTRATION_NOT_ACTIVE")
    if report["submission_status"] != "DRAFT":
        fail("ERR_REPORT_NOT_IN_DRAFT")
    if sku["producer_id"] != registration["producer_id"]:
        fail("ERR_SKU_PRODUCER_MISMATCH")
    for line in calc.lines_of(report["id"]):
        if line["sku_id"] == sku["id"]:
            fail("ERR_DUPLICATE_REPORT_LINE")
    row = new_row(
        "report_lines",
        {
            "packaging_report_id": report["id"],
            "sku_id": sku["id"],
            "units_sold": units_sold,
            "line_weight_kg": calc.line_weight(sku, units_sold),
            "fee_exempt": sku["product_category"] in program["exempt_product_categories"],
            "line_fee_exact_cents": calc.ZERO_EXACT,
            "line_fee_cents": 0,
            "eco_mod_detail": [],
        },
    )
    calc.recompute_report_rollups(report)
    touch(report)
    return ok_entity(row, 201)


@bp.get("/epr/report-lines/<lid>")
@endpoint(ALL)
def get_line(lid):
    return ok_entity(must("report_lines", lid))


@bp.get("/epr/report-lines")
@endpoint(ALL)
def list_lines():
    report_id = str_filter("packaging_report_id")
    sku_id = str_filter("sku_id")
    exempt = bool_filter("fee_exempt")
    rows = store.values("report_lines")
    if report_id is not None:
        rows = [r for r in rows if r["packaging_report_id"] == report_id]
    if sku_id is not None:
        rows = [r for r in rows if r["sku_id"] == sku_id]
    if exempt is not None:
        rows = [r for r in rows if r["fee_exempt"] == exempt]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.delete("/epr/report-lines/<lid>")
@endpoint([OFFICER])
def delete_line(lid):
    line = must("report_lines", lid)
    report = store.get("reports", line["packaging_report_id"])
    registration, _program, _period = context_of(report)
    require_producer_owner(registration["producer_id"])
    if registration["status"] != "ACTIVE":
        fail("ERR_REGISTRATION_NOT_ACTIVE")
    if report["submission_status"] != "DRAFT":
        fail("ERR_REPORT_NOT_IN_DRAFT")
    store.delete("report_lines", line["id"])
    calc.recompute_report_rollups(report)
    touch(report)
    return "", 204


@bp.post("/epr/reports/<rid>/submit")
@endpoint([OFFICER])
def submit_report(rid):
    v.body(required=False)
    report = must("reports", rid)
    registration, program, period = context_of(report)
    require_producer_owner(registration["producer_id"])
    if report["submission_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "The report is not in DRAFT.")
    if registration["status"] != "ACTIVE":
        fail("ERR_REGISTRATION_NOT_ACTIVE")
    if registration["exemption_status"] != "OBLIGATED":
        fail("ERR_EXEMPT_REGISTRATION_CANNOT_REPORT")
    producer = store.get("producers", registration["producer_id"])
    if producer["determination_stale"]:
        fail("ERR_DETERMINATION_STALE")
    if not calc.lines_of(report["id"]):
        fail("ERR_REPORT_HAS_NO_LINES")
    now = store.clock()
    if now < period["_submission_open"]:
        fail("ERR_SUBMISSION_WINDOW_NOT_OPEN")
    if now > period["_submission_deadline"]:
        fail("ERR_SUBMISSION_WINDOW_CLOSED")
    require_paid_membership(registration, allow_probation=False)
    report["submission_status"] = "SUBMITTED"
    refresh_lines(report, program)
    report["submitted_by_user_id"] = user_id()
    report["submitted_at"] = store.fmt_instant(now)
    touch(report)
    calc.recompute_ytd(registration)
    calc.set_posture(registration)
    return ok_entity(report)


@bp.post("/epr/reports/<rid>/assess")
@endpoint([PRO_ADMIN])
def assess(rid):
    from auth import require_pro_owner

    body = v.body()
    variant = v.req_enum(body, "variant", ["PROVISIONAL", "FINAL"])
    report = must("reports", rid)
    registration, program, period = context_of(report)
    membership = calc.live_membership(registration["id"])
    if membership is not None:
        require_pro_owner(membership["pro_id"])
    if variant == "PROVISIONAL":
        if report["fee_status"] != "UNASSESSED":
            fail("ERR_INVALID_STATE", "A provisional assessment requires an UNASSESSED fee status.")
        if report["submission_status"] not in ("SUBMITTED", "UNDER_VERIFICATION"):
            fail("ERR_INVALID_STATE", "The report is not in a provisionally assessable position.")
    else:
        if report["fee_status"] not in ("UNASSESSED", "PROVISIONAL"):
            fail("ERR_INVALID_STATE", "The report has already been finally assessed.")
        eligible = report["submission_status"] == "VERIFIED" or (
            report["submission_status"] == "SUBMITTED" and not report["verification_required"]
        )
        if not eligible:
            fail("ERR_VERIFICATION_REQUIRED")
    if membership is None:
        fail("ERR_NO_ACTIVE_MEMBERSHIP")
    schedule = store.get("fee_schedules", membership["fee_schedule_id"])
    tier_basis = calc.tier_basis_for(variant, registration, report)
    lines = calc.lines_of(report["id"])
    calc.check_material_rates(schedule, lines, tier_basis)
    data_start = period["_data_start"]
    effective_to = schedule["_effective_to"]
    if schedule["_effective_from"] > data_start or (
        effective_to is not None and data_start > effective_to
    ):
        fail("ERR_FEE_SCHEDULE_NOT_EFFECTIVE_FOR_PERIOD")
    calc.assess_report(report, variant, registration, program, schedule)
    return ok_entity(report)


@bp.get("/epr/reports/<rid>/fee-breakdown")
@endpoint(ALL)
def fee_breakdown(rid):
    report = must("reports", rid)
    _registration, program, _period = context_of(report)
    return ok(calc.fee_breakdown(report, program))


@bp.post("/epr/reports/<rid>/resubmit")
@endpoint([OFFICER])
def resubmit(rid):
    v.body(required=False)
    report = must("reports", rid)
    registration, program, _period = context_of(report)
    require_producer_owner(registration["producer_id"])
    if report["submission_status"] != "CORRECTION_REQUIRED":
        fail("ERR_INVALID_STATE", "The report is not awaiting correction.")
    if registration["status"] != "ACTIVE":
        fail("ERR_REGISTRATION_NOT_ACTIVE")
    if not calc.lines_of(report["id"]):
        fail("ERR_REPORT_HAS_NO_LINES")
    due = report["_correction_due_at"]
    if due is not None and store.clock() > due:
        fail("ERR_CORRECTION_WINDOW_EXPIRED")
    require_paid_membership(registration, allow_probation=True)
    report["submission_status"] = "SUBMITTED"
    report["correction_round"] = int(report["correction_round"]) + 1
    report["correction_due_at"] = None
    report["_correction_due_at"] = None
    refresh_lines(report, program)
    if report["fee_status"] == "VOIDED":
        report["fee_status"] = "UNASSESSED"
    report["fee_subtotal_cents"] = 0
    report["tier_basis_kg"] = calc.ZERO_KG
    report["fee_variant_applied"] = "NONE"
    report["submitted_by_user_id"] = user_id()
    touch(report)
    calc.recompute_ytd(registration)
    calc.set_posture(registration)
    return ok_entity(report)


@bp.post("/epr/reports/<rid>/close")
@endpoint([REGULATOR])
def close_report(rid):
    body = v.body()
    decision = v.req_enum(body, "decision", ["FINALIZE", "REJECT"])
    v.opt_str(body, "reason")
    report = must("reports", rid)
    registration, _program, _period = context_of(report)
    if decision == "FINALIZE":
        if report["submission_status"] not in ("SUBMITTED", "VERIFIED"):
            fail("ERR_INVALID_STATE", "The report cannot be finalized from its current position.")
        if report["submission_status"] == "SUBMITTED" and report["verification_required"]:
            fail("ERR_VERIFICATION_REQUIRED")
        if report["fee_status"] != "INVOICED":
            fail("ERR_INVOICE_NOT_ISSUED")
        report["submission_status"] = "FINALIZED"
    else:
        if report["submission_status"] != "CORRECTION_REQUIRED":
            fail("ERR_INVALID_STATE", "Only a report awaiting correction may be rejected.")
        due = report["_correction_due_at"]
        if due is not None and store.clock() <= due:
            fail("ERR_CORRECTION_WINDOW_OPEN")
        report["submission_status"] = "REJECTED"
        report["correction_due_at"] = None
        report["_correction_due_at"] = None
    touch(report)
    # Close-out is one of the ten operations that recompute the posture, and a
    # derived-field refresh is itself a mutation (PRD 2.4), so the registration
    # advances even when the recomputed verdict is unchanged.
    touch(registration)
    calc.set_posture(registration)
    return ok_entity(report)

"""Program charter, lifecycle, gross-up policy, notification, cancellation."""

from flask import Blueprint

import calc
import cascades
import serialize
from auth import ALL_ROLES, OPERATOR_ROLES, authorize
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_dt, f_enum, f_int, f_str, validate
from store import db, norm_dt, parse_dt

bp = Blueprint("programs", __name__)

METRICS = ("NET_REVENUE_CENTS", "UNITS_SOLD", "MARGIN_CENTS")
POLICIES = ("NONE", "FLAT_SUPPLEMENTAL", "FULL_GROSS_UP")
STATUSES = ("DESIGN", "SOURCING", "CONTRACTED", "REGISTRATION_OPEN", "ONSITE",
            "RECONCILED", "CLOSED", "CANCELLED")

DIRECTOR_EDGES = {
    "DESIGN": ("SOURCING",),
    "CONTRACTED": ("REGISTRATION_OPEN",),
    "REGISTRATION_OPEN": ("ONSITE",),
    "ONSITE": ("RECONCILED",),
    "RECONCILED": ("CLOSED",),
}

@bp.post("/programs")
def create_program():
    authorize("ProgramDirector")
    data = validate(body(), [
        f_str("name", max_len=160),
        f_int("fiscal_year", minimum=2000, maximum=2100),
        f_enum("qualification_metric", METRICS),
        f_dt("sales_period_start"),
        f_dt("sales_period_end"),
        f_int("budget_total_cents", minimum=0),
    ])

    start = parse_dt(data["sales_period_start"])
    end = parse_dt(data["sales_period_end"])
    if not (end > start):
        fail("ERR_INVALID_DATE_RANGE")

    row = {
        "name": data["name"],
        "fiscal_year": data["fiscal_year"],
        "qualification_metric": data["qualification_metric"],
        "sales_period_start": norm_dt(data["sales_period_start"]),
        "sales_period_end": norm_dt(data["sales_period_end"]),
        "budget_total_cents": data["budget_total_cents"],
        "status": "DESIGN",
        "gross_up_policy": "NONE",
        "gross_up_policy_locked": False,
        "per_person_cost_basis_cents": 0,
        "committed_budget_cents": 0,
        "budget_headroom_cents": 0,
        "budget_posture": "OK",
        "cancellation_exposure_cents": 0,
        "reported_award_total_cents": 0,
        "sales_lift_pct": None,
        "satisfaction_index": None,
        "qualified_count": 0,
        "travelled_count": 0,
        "cancellation_reason": None,
    }
    db.stamp_new(row)
    db.programs[row["id"]] = row
    return created(serialize.program(row))


@bp.get("/programs/<program_id>")
def read_program(program_id):
    authorize(*ALL_ROLES)
    program = lookup("program", program_id)
    return ok(serialize.program(program))


@bp.get("/programs")
def list_programs():
    authorize(*OPERATOR_ROLES)
    rows = filtered(db.ordered(db.programs),
                    [("fiscal_year", "fiscal_year"), ("status", "status")])
    return paginate(rows, serialize.program)


@bp.post("/programs/<program_id>/advance")
def advance_program(program_id):
    authorize("ProgramDirector")
    program = lookup("program", program_id)
    data = validate(body(), [f_enum("to_status", STATUSES)])
    target = data["to_status"]

    if target not in DIRECTOR_EDGES.get(program["status"], ()):
        fail("ERR_PROGRAM_STATE_INVALID")

    _check_prerequisites(program, target)

    program["status"] = target
    if target == "ONSITE":
        cascades.close_registration_window(program)
    elif target == "RECONCILED":
        cascades.reconcile(program)
    db.touch(program)
    return ok(serialize.program(program))


def _check_prerequisites(program, target):
    if target == "SOURCING":
        has_tier = any(t["program_id"] == program["id"] for t in db.award_tiers.values())
        has_shortlist = any(d["program_id"] == program["id"] and d["status"] == "SHORTLISTED"
                            for d in db.destinations.values())
        if not (has_tier and has_shortlist):
            fail("ERR_ADVANCE_PREREQUISITES_UNMET")
    elif target == "REGISTRATION_OPEN":
        pending = any(q["program_id"] == program["id"] and q["award_status"] == "PENDING_REVIEW"
                      for q in db.qualifiers.values())
        if pending or not program["gross_up_policy_locked"]:
            fail("ERR_ADVANCE_PREREQUISITES_UNMET")
    elif target == "ONSITE":
        confirmed = any(r["program_id"] == program["id"] and r["attendance_status"] == "CONFIRMED"
                        for r in db.registrations.values())
        if not confirmed:
            fail("ERR_ADVANCE_PREREQUISITES_UNMET")
    elif target == "RECONCILED":
        open_activity = any(a["program_id"] == program["id"] and a["status"] == "OPEN"
                            for a in db.onsite_activities.values())
        if open_activity:
            fail("ERR_ADVANCE_PREREQUISITES_UNMET")
    elif target == "CLOSED":
        for qualifier in db.qualifiers.values():
            if qualifier["program_id"] != program["id"]:
                continue
            if qualifier["taxable_award_cents"] > 0 and qualifier["tax_status"] != "REPORTED":
                fail("ERR_TAX_REPORTING_INCOMPLETE")


@bp.post("/programs/<program_id>/gross-up-policy")
def set_gross_up_policy(program_id):
    authorize("ProgramDirector")
    program = lookup("program", program_id)
    data = validate(body(), [f_enum("gross_up_policy", POLICIES)])
    if program["gross_up_policy_locked"]:
        fail("ERR_GROSS_UP_POLICY_LOCKED")
    program["gross_up_policy"] = data["gross_up_policy"]
    program["gross_up_policy_locked"] = True
    db.touch(program)
    return ok(serialize.program(program))


@bp.post("/programs/<program_id>/notify-qualifiers")
def notify_qualifiers(program_id):
    authorize("ProgramDirector")
    program = lookup("program", program_id)
    body()
    program_gate(program, ("CONTRACTED", "REGISTRATION_OPEN"))

    notified_ids = []
    skipped_ids = []
    for qualifier in db.ordered(db.qualifiers):
        if qualifier["program_id"] != program["id"]:
            continue
        if qualifier["award_status"] == "QUALIFIED":
            qualifier["award_status"] = "NOTIFIED"
            qualifier["notified_at"] = db.logical_now()
            db.touch(qualifier)
            notified_ids.append(qualifier["id"])
        else:
            skipped_ids.append(qualifier["id"])

    return ok({
        "notified_count": len(notified_ids),
        "skipped_count": len(skipped_ids),
        "notified_qualifier_ids": notified_ids,
        "skipped_qualifier_ids": skipped_ids,
    })


@bp.post("/programs/<program_id>/cancel")
def cancel_program(program_id):
    authorize("ProgramDirector")
    program = lookup("program", program_id)
    data = validate(body(), [f_str("cancellation_reason")])
    program_gate(program, ("DESIGN", "SOURCING", "CONTRACTED", "REGISTRATION_OPEN", "ONSITE"))
    cascades.cancel_program(program, data["cancellation_reason"])
    return ok(serialize.program(program))


@bp.get("/programs/<program_id>/measurement")
def program_measurement(program_id):
    authorize("ProgramDirector", "SalesOpsAnalyst")
    program = lookup("program", program_id)
    serialize.refresh_program(program)
    measured = calc.program_measurement(db, program)
    return ok({
        "program_id": program["id"],
        "sales_lift_pct": measured["sales_lift_pct"],
        "satisfaction_index": measured["satisfaction_index"],
        "baseline_metric_total": measured["baseline_metric_total"],
        "actual_metric_total": measured["actual_metric_total"],
        "survey_count": measured["survey_count"],
        "qualified_count": program["qualified_count"],
        "travelled_count": program["travelled_count"],
        "committed_budget_cents": program["committed_budget_cents"],
        "budget_headroom_cents": program["budget_headroom_cents"],
        "budget_posture": program["budget_posture"],
        "cancellation_exposure_cents": program["cancellation_exposure_cents"],
        "reported_award_total_cents": program["reported_award_total_cents"],
    })

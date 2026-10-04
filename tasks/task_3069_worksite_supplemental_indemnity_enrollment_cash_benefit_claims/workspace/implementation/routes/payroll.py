"""Payroll cycle + deduction line endpoints."""
from flask import Blueprint, request

import db
import errors as E
import services
from middleware import require_role
from response import success_object
from serializers import deduction_line, payroll_cycle
from util import get_body, get_or_404, list_response, parse_iso

bp = Blueprint("payroll_cycles", __name__)

CYCLES = db.STORES["payroll_cycles"]
LINES = db.STORES["deduction_lines"]


@bp.route("/payroll-cycles", methods=["POST"])
def create(role, user_id):
    require_role(role, {"GroupAdmin"})
    body = get_body(["employer_group_id", "period_start", "period_end"])
    group = db.STORES["employer_groups"].get(body["employer_group_id"])
    if group is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "employer_group_id does not exist")
    ps = parse_iso(body["period_start"], "period_start")
    pe = parse_iso(body["period_end"], "period_end")
    if pe <= ps:
        raise E.err(E.ERR_INVALID_REQUEST, "period_end must be strictly after period_start")
    rec = db.stamp_created({
        "employer_group_id": group["id"],
        "period_start": db.format_ts(ps),
        "period_end": db.format_ts(pe),
        "total_posted_cents": 0,
        "status": "OPEN",
    })
    CYCLES[rec["id"]] = rec
    return success_object(payroll_cycle(rec), status=201)


@bp.route("/payroll-cycles/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin"})
    rec = get_or_404(CYCLES, rid)
    return success_object(payroll_cycle(rec))


@bp.route("/payroll-cycles/<rid>/finalize", methods=["POST"])
def finalize(role, user_id, rid):
    require_role(role, {"GroupAdmin"})
    rec = get_or_404(CYCLES, rid)
    if rec["status"] != "OPEN":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot finalize from {rec['status']}")
    group = db.STORES["employer_groups"][rec["employer_group_id"]]
    if group["status"] not in ("ACTIVE", "SUSPENDED"):
        raise E.err(E.ERR_GROUP_TERMINATED, "Employer group is TERMINATED")

    ps = parse_iso(rec["period_start"])
    pe = parse_iso(rec["period_end"])
    days_in_period = (pe - ps).days

    employee_ids = {
        e["id"] for e in db.STORES["employees"].values()
        if e["employer_group_id"] == group["id"]
    }
    # Billability pinned: status AT finalize instant decides the whole period.
    billable = [
        p for p in db.STORES["policies"].values()
        if p["employee_id"] in employee_ids and p["status"] in ("ISSUED", "ACTIVE")
    ]
    total = 0
    for p in billable:
        coverage_days = days_in_period  # all-or-nothing per pinned rule
        amount = services.proration_amount(
            group.get("proration_convention", "DAILY"),
            p["monthly_premium_cents"],
            coverage_days,
            days_in_period,
        )
        line = db.stamp_created({
            "payroll_cycle_id": rec["id"],
            "policy_id": p["id"],
            "employee_id": p["employee_id"],
            "tax_treatment": p["premium_mode"],
            "coverage_days": coverage_days,
            "amount_cents": amount,
            "status": "POSTED",
        })
        LINES[line["id"]] = line
        total += amount
    rec["total_posted_cents"] = total
    rec["status"] = "FINALIZED"
    db.touch(rec)
    return success_object(payroll_cycle(rec))


@bp.route("/payroll-cycles/<rid>/reconcile", methods=["POST"])
def reconcile(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    rec = get_or_404(CYCLES, rid)
    if rec["status"] != "FINALIZED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot reconcile from {rec['status']}")
    rec["status"] = "RECONCILED"
    db.touch(rec)
    return success_object(payroll_cycle(rec))


@bp.route("/payroll-cycles/<rid>/close", methods=["POST"])
def close(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    rec = get_or_404(CYCLES, rid)
    if rec["status"] != "RECONCILED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot close from {rec['status']}")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return success_object(payroll_cycle(rec))


@bp.route("/payroll-cycles/<rid>/deduction-lines", methods=["GET"])
def list_lines(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin"})
    get_or_404(CYCLES, rid)
    filters = {
        "payroll_cycle_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(LINES, filters, deduction_line)


# ---------------- DeductionLine ----------------

@bp.route("/deduction-lines", methods=["GET"])
def list_all_lines(role, user_id):
    require_role(role, {"CarrierAdmin", "GroupAdmin"})
    filters = {
        "payroll_cycle_id": request.args.get("payroll_cycle_id"),
        "policy_id": request.args.get("policy_id"),
        "employee_id": request.args.get("employee_id"),
        "status": request.args.get("status"),
    }
    return list_response(LINES, filters, deduction_line)


@bp.route("/deduction-lines/<rid>", methods=["GET"])
def get_line(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin"})
    rec = get_or_404(LINES, rid)
    return success_object(deduction_line(rec))


@bp.route("/deduction-lines/<rid>/reverse", methods=["POST"])
def reverse_line(role, user_id, rid):
    require_role(role, {"GroupAdmin"})
    rec = get_or_404(LINES, rid)
    cycle = CYCLES[rec["payroll_cycle_id"]]
    # Cycle gate first: once the cycle is reconciled or closed its lines are
    # immutable, and the refusal is ERR_CYCLE_NOT_REVERSIBLE regardless of the
    # line's own status (even an already-REVERSED line).
    if cycle["status"] != "FINALIZED":
        raise E.err(E.ERR_CYCLE_NOT_REVERSIBLE, "Cycle is not FINALIZED")
    if rec["status"] != "POSTED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot reverse from {rec['status']}")
    rec["status"] = "REVERSED"
    db.touch(rec)
    cycle["total_posted_cents"] = cycle.get("total_posted_cents", 0) - rec["amount_cents"]
    db.touch(cycle)
    return success_object(deduction_line(rec))

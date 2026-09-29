"""CmarProject endpoints and the logical clock endpoint."""
from decimal import Decimal

from flask import Blueprint, g

import clock
import guards
import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, touch
from errors import ApiError
from money import MONEY_ZERO, RATIO_ZERO, q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROCUREMENT_OFFICER,
    PROGRAM_ADMIN,
    endpoint,
)
from services import derive, pricing

bp = Blueprint("projects", __name__)

GMP_STATUSES = ("PRECONSTRUCTION", "GMP_UNDER_REVIEW", "EXECUTED", "CLOSED")
POSTURES = ("OPEN", "CONSTRAINED", "FROZEN")
CLOSEOUT_STATUSES = (
    "NOT_STARTED",
    "PROVISIONAL_COMPUTED",
    "FINAL_COMPUTED",
    "SETTLEMENT_EXECUTED",
)
AUDIT_ACTIONS = ("POST_ADJUSTMENT", "CLOSE")
SAVINGS_BASES = ("PRE_AUDIT_PROVISIONAL", "POST_AUDIT_FINAL")

MAX_CM_FEE_PCT = Decimal("0.1500")
MAX_INSURANCE_RATE = Decimal("0.0500")


# --------------------------------------------------------------- logical clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def set_clock():
    body = v.json_body()
    instant = v.get_datetime(body, "current_utc", required=True)
    clock.set_now(instant)
    return resp.ok({})


# --------------------------------------------------------------------- create

def _blank_project(name, owner_org, cm_fee_pct, insurance_rate, precon_fee_amount):
    return new_record({
        "name": name,
        "owner_org": owner_org,
        "cm_fee_pct": cm_fee_pct,
        "insurance_rate": insurance_rate,
        "precon_fee_amount": precon_fee_amount,
        "gmp_status": "PRECONSTRUCTION",
        "gmp_amount": MONEY_ZERO,
        "proposed_gmp_amount": MONEY_ZERO,
        "cost_of_work_budget_total": MONEY_ZERO,
        "general_conditions_total": MONEY_ZERO,
        "insurance_amount": MONEY_ZERO,
        "cm_fee_amount": MONEY_ZERO,
        "owner_contingency_original": MONEY_ZERO,
        "owner_contingency_remaining": MONEY_ZERO,
        "construction_contingency_original": MONEY_ZERO,
        "construction_contingency_remaining": MONEY_ZERO,
        "contingency_drawn_to_cost_total": MONEY_ZERO,
        "contingency_posture": "OPEN",
        "pending_amendment_count": 0,
        "buyout_savings_trade_level": MONEY_ZERO,
        "buyout_savings_project_net": MONEY_ZERO,
        "audit_status": "NOT_REQUESTED",
        "audit_adjustment_total": MONEY_ZERO,
        "closeout_status": "NOT_STARTED",
        "provisional_savings_pool": MONEY_ZERO,
        "provisional_cm_savings_share": MONEY_ZERO,
        "provisional_owner_savings_share": MONEY_ZERO,
        "final_savings_pool": MONEY_ZERO,
        "final_cm_savings_share": MONEY_ZERO,
        "final_owner_savings_share": MONEY_ZERO,
    })


@bp.route("/projects", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_project():
    body = v.json_body()
    name = v.get_str(body, "name", required=True, min_len=1, max_len=200)
    owner_org = v.get_str(body, "owner_org", required=True, min_len=1, max_len=200)
    cm_fee_pct = v.get_ratio(
        body, "cm_fee_pct", required=True, positive=True, signed=False,
        maximum=MAX_CM_FEE_PCT,
    )
    insurance_rate = v.get_ratio(
        body, "insurance_rate", required=True, signed=False,
        maximum=MAX_INSURANCE_RATE,
    )
    precon_fee_amount = v.get_money(
        body, "precon_fee_amount", required=False, default=MONEY_ZERO
    )
    project = _blank_project(
        name, owner_org, cm_fee_pct, insurance_rate, precon_fee_amount
    )
    db.projects[project["id"]] = project
    return resp.created(serializers.project(project))


# ----------------------------------------------------------------------- reads

@bp.route("/projects", methods=["GET"])
@endpoint(*(PROGRAM_ADMIN, CONSTRUCTION_MANAGER, PROCUREMENT_OFFICER,
            OWNER_REPRESENTATIVE, INDEPENDENT_AUDITOR))
def list_projects():
    limit, offset = v.pagination()
    gmp_status = v.query_filter("gmp_status", GMP_STATUSES)
    posture = v.query_filter("contingency_posture", POSTURES)
    closeout = v.query_filter("closeout_status", CLOSEOUT_STATUSES)
    rows = []
    for row in db.projects.values():
        if gmp_status is not None and row["gmp_status"] != gmp_status:
            continue
        if posture is not None and row["contingency_posture"] != posture:
            continue
        if closeout is not None and row["closeout_status"] != closeout:
            continue
        rows.append(row)
    from db import sorted_rows

    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing([serializers.project(r) for r in page], limit, offset, total)


@bp.route("/projects/<pid>", methods=["GET"])
@endpoint(*(PROGRAM_ADMIN, CONSTRUCTION_MANAGER, PROCUREMENT_OFFICER,
            OWNER_REPRESENTATIVE, INDEPENDENT_AUDITOR))
def read_project(pid):
    project = lookups.project(pid)
    return resp.ok(serializers.project(project))


# ----------------------------------------------------------------------- audit

def _reconciled_reports(project_id):
    return [r for r in derive.project_reports(project_id) if r["status"] == "RECONCILED"]


@bp.route("/projects/<pid>/audit-request", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def audit_request(pid):
    body = v.json_body()
    v.get_str(body, "audit_scope_note", required=False, min_len=0)
    project = lookups.project(pid)
    guards.require_gmp_executed(project)
    if project["audit_status"] != "NOT_REQUESTED":
        raise ApiError(
            "ERR_AUDIT_STATE_INVALID",
            "audit_status is %s, not NOT_REQUESTED" % project["audit_status"],
        )
    if not _reconciled_reports(project["id"]):
        raise ApiError(
            "ERR_NO_RECONCILED_COST_REPORT",
            "the project has no RECONCILED cost report",
        )
    project["audit_status"] = "IN_PROGRESS"
    touch(project)
    return resp.ok(serializers.project(project))


@bp.route("/projects/<pid>/audit-actions", methods=["POST"])
@endpoint(INDEPENDENT_AUDITOR)
def audit_actions(pid):
    body = v.json_body()
    action = v.get_enum(body, "action", AUDIT_ACTIONS, required=True)
    adjustment_amount = None
    if action == "POST_ADJUSTMENT":
        adjustment_amount = v.get_money(
            body, "adjustment_amount", required=True, signed=True
        )
    v.get_str(body, "adjustment_note", required=False, min_len=0)
    project = lookups.project(pid)
    if project["audit_status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_AUDIT_STATE_INVALID",
            "audit_status is %s, not IN_PROGRESS" % project["audit_status"],
        )
    if action == "POST_ADJUSTMENT":
        project["audit_adjustment_total"] = q2(
            project["audit_adjustment_total"] + adjustment_amount
        )
    else:
        project["audit_status"] = "CLOSED"
    touch(project)
    return resp.ok(serializers.project(project))


# --------------------------------------------------------------- shared savings

@bp.route("/projects/<pid>/shared-savings", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def shared_savings(pid):
    body = v.json_body()
    basis = v.get_enum(body, "basis", SAVINGS_BASES, required=True)
    execute = v.get_bool(body, "execute", required=True)
    project = lookups.project(pid)

    settle = bool(execute) and basis == "POST_AUDIT_FINAL"
    if settle:
        guards.require_not_settled(project)
    guards.require_gmp_executed(project)

    reports = derive.project_reports(project["id"])
    if not [r for r in reports if r["status"] == "RECONCILED"]:
        raise ApiError(
            "ERR_NO_RECONCILED_COST_REPORT",
            "the project has no RECONCILED cost report",
        )
    if basis == "POST_AUDIT_FINAL":
        unsettled = [
            r for r in reports
            if r["status"] in ("OPEN", "DISPUTED", "RECONCILIATION_HELD")
        ]
        if unsettled:
            raise ApiError(
                "ERR_COST_REPORTS_NOT_RECONCILED",
                "%d cost report(s) are not RECONCILED" % len(unsettled),
            )
        if project["audit_status"] != "CLOSED":
            raise ApiError(
                "ERR_AUDIT_NOT_CLOSED",
                "audit_status is %s, not CLOSED" % project["audit_status"],
            )
        if settle and project["closeout_status"] != "FINAL_COMPUTED":
            raise ApiError(
                "ERR_CLOSEOUT_ALREADY_SETTLED",
                "settlement requires closeout_status FINAL_COMPUTED, found %s"
                % project["closeout_status"],
            )

    if basis == "PRE_AUDIT_PROVISIONAL":
        settled_cost = MONEY_ZERO
        for report in reports:
            if report["status"] in ("RECONCILED", "DISPUTED"):
                settled_cost = settled_cost + report["reported_cost_total"]
        settled_cost = q2(settled_cost)
    else:
        settled_cost = MONEY_ZERO
        for report in reports:
            if report["status"] == "RECONCILED":
                settled_cost = settled_cost + report["undisputed_cost_total"]
        settled_cost = q2(settled_cost + project["audit_adjustment_total"])

    figures = pricing.shared_savings(
        project["gmp_amount"],
        project["cm_fee_amount"],
        project["insurance_amount"],
        settled_cost,
    )

    if basis == "PRE_AUDIT_PROVISIONAL":
        project["provisional_savings_pool"] = figures["savings_pool"]
        project["provisional_cm_savings_share"] = figures["cm_share"]
        project["provisional_owner_savings_share"] = figures["owner_share"]
        if project["closeout_status"] in ("NOT_STARTED", "PROVISIONAL_COMPUTED"):
            project["closeout_status"] = "PROVISIONAL_COMPUTED"
    else:
        project["final_savings_pool"] = figures["savings_pool"]
        project["final_cm_savings_share"] = figures["cm_share"]
        project["final_owner_savings_share"] = figures["owner_share"]
        if not settle:
            project["closeout_status"] = "FINAL_COMPUTED"

    if settle:
        project["closeout_status"] = "SETTLEMENT_EXECUTED"
        project["gmp_status"] = "CLOSED"
        project["contingency_posture"] = "FROZEN"
        for package in db.work_packages.values():
            if package["project_id"] != project["id"]:
                continue
            if package["procurement_status"] == "AWARDED":
                package["procurement_status"] = "CLOSED"
                touch(package)
        derive.recompute_buyout_savings(project)

    touch(project)
    return resp.ok(serializers.project(project))

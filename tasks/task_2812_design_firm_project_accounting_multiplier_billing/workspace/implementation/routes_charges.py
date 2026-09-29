"""Timesheet capture (PRD 3.3) and reimbursable expenses (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint

import calc
import guards
import response as resp
import serialize as ser
import validate as V
from auth import authenticate, check_project_manager, check_segregation
from db import db, new_id
from errors import ApiError
from money import ZERO2, ZERO4, q2

bp = Blueprint("charges", __name__)

MAX_HOURS_PER_ENTRY = Decimal("24.00")


def _resolve_charge_placement(body_project_id, body_phase_id):
    """Rung 9 -- the body foreign keys of a charge: the project, the phase, and
    the requirement that the phase belong to that project (PRD 2.9)."""
    project = guards.reference(db.projects, body_project_id, "Project")
    phase = guards.reference(db.phases, body_phase_id, "Phase")
    if phase["project_id"] != project["id"]:
        raise ApiError("ERR_INVALID_REFERENCE",
                       "The phase belongs to a different project.")
    return project, phase


# ---------------------------------------------------------------------------
# Time entries (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.route("/time-entries", methods=["POST"])
def create_time_entry():
    user_id, role = authenticate(["ProjectManager", "ProjectAccountant"])
    peek = V.peek_body()
    check_project_manager(role, user_id, guards.maybe(db.projects, peek.get("project_id")))
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    phase_id = V.req_string(body, "phase_id")
    role_code = V.req_enum(body, "role_code", V.ROLE_CODES)
    work_date = V.req_date(body, "work_date")
    hours = V.req_money(body, "hours", min_exclusive=ZERO2, maximum=MAX_HOURS_PER_ENTRY)
    project, phase = _resolve_charge_placement(project_id, phase_id)
    guards.require_active_project(project)
    guards.require_period_open(project, work_date, "work_date")
    guards.require_leaf(phase)
    row = {
        "id": new_id(),
        "project_id": project_id,
        "phase_id": phase_id,
        "role_code": role_code,
        "hours": q2(hours),
        "work_date": work_date,
        "submitted_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "SUBMITTED",
        # PRD 3.3: the line "carries no money yet".
        "raw_cost": ZERO2,
        "billable_amount": ZERO2,
        "applied_multiplier": None,
        "billed_invoice_id": None,
    }
    calc.stamp_new(row)
    db.time_entries[row["id"]] = row
    return resp.created(ser.time_entry_out(row))


@bp.route("/time-entries/<time_entry_id>", methods=["GET"])
def get_time_entry(time_entry_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.time_entries, time_entry_id, "ERR_CHARGE_NOT_FOUND", "Time entry")
    return resp.ok(ser.time_entry_out(row))


@bp.route("/time-entries", methods=["GET"])
def list_time_entries():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    project_id = V.query_str("project_id")
    phase_id = V.query_str("phase_id")
    status = V.query_enum("status", V.TIME_ENTRY_STATUSES)
    billed_invoice_id = V.query_str("billed_invoice_id")
    submitted_by = V.query_str("submitted_by_user_id")
    rows = list(db.time_entries.values())
    if project_id is not None:
        rows = [x for x in rows if x["project_id"] == project_id]
    if phase_id is not None:
        rows = [x for x in rows if x["phase_id"] == phase_id]
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    if billed_invoice_id is not None:
        rows = [x for x in rows if x["billed_invoice_id"] == billed_invoice_id]
    if submitted_by is not None:
        rows = [x for x in rows if x["submitted_by_user_id"] == submitted_by]
    return resp.paged(rows, ser.time_entry_out)


@bp.route("/time-entries/<time_entry_id>/approve", methods=["POST"])
def approve_time_entry(time_entry_id):
    user_id, role = authenticate(["ProjectManager", "Controller"])
    entry = guards.maybe(db.time_entries, time_entry_id)
    if entry is not None:
        check_project_manager(role, user_id, db.projects.get(entry["project_id"]))
        check_segregation(user_id, entry["submitted_by_user_id"])
    entry = guards.lookup(db.time_entries, time_entry_id, "ERR_CHARGE_NOT_FOUND", "Time entry")
    project = db.projects.get(entry["project_id"])
    guards.require_active_project(project)
    if entry["status"] != "SUBMITTED":
        raise guards.invalid_state("Only a SUBMITTED time entry may be approved.")
    guards.require_period_open(project, entry["work_date"], "work_date")
    rate = calc.effective_labor_rate(entry["role_code"], entry["work_date"])
    if rate is None:
        raise ApiError("ERR_NO_EFFECTIVE_LABOR_RATE",
                       "No labour rate window covers %s on %s."
                       % (entry["role_code"], entry["work_date"].isoformat()))
    multiplier = calc.effective_billing_multiplier(entry["project_id"], entry["work_date"])
    if multiplier is None:
        raise ApiError("ERR_NO_EFFECTIVE_MULTIPLIER",
                       "No billing multiplier window covers %s."
                       % entry["work_date"].isoformat())
    # PRD 3.3 -- the pinned two-stage rounding, frozen onto the line.
    raw_cost, applied, billable = calc.labor_charge(
        entry["hours"], rate["raw_cost_rate"], multiplier["multiplier"])
    entry["raw_cost"] = raw_cost
    entry["applied_multiplier"] = applied
    entry["billable_amount"] = billable
    entry["status"] = "APPROVED"
    entry["approved_by_user_id"] = user_id
    calc.touch(entry)
    phase = db.phases.get(entry["phase_id"])
    if phase is not None:
        # PRD 3.3: "a phase still in PLANNED moves to IN_PROGRESS on the first
        # approval it receives." The phase's version increments by exactly 1.
        if phase["status"] == "PLANNED":
            phase["status"] = "IN_PROGRESS"
        calc.touch(phase)
    calc.touch(project)
    return resp.ok(ser.time_entry_out(entry))


# ---------------------------------------------------------------------------
# Reimbursable expenses (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.route("/expenses", methods=["POST"])
def create_expense():
    user_id, role = authenticate(["ProjectManager", "ProjectAccountant"])
    peek = V.peek_body()
    check_project_manager(role, user_id, guards.maybe(db.projects, peek.get("project_id")))
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    phase_id = V.req_string(body, "phase_id")
    category = V.req_enum(body, "category", V.EXPENSE_CATEGORIES)
    amount = V.req_money(body, "amount", min_exclusive=ZERO2)
    incurred_on = V.req_date(body, "incurred_on")
    receipt_attached = V.req_bool(body, "receipt_attached")
    project, phase = _resolve_charge_placement(project_id, phase_id)
    guards.require_active_project(project)
    guards.require_period_open(project, incurred_on, "incurred_on")
    guards.require_leaf(phase)
    client = calc.client_of(project)
    amount = q2(amount)
    # PRD 3.4: allowability is adjudicated immediately at capture by an ordered
    # set of clauses in which the first matching clause wins.
    status, reason, billable = calc.adjudicate_expense(amount, category, receipt_attached, client)
    row = {
        "id": new_id(),
        "project_id": project_id,
        "phase_id": phase_id,
        "category": category,
        "amount": amount,
        "incurred_on": incurred_on,
        "receipt_attached": receipt_attached,
        "incurred_by_user_id": user_id,
        "allowability_status": status,
        "allowability_reason": reason,
        "billing_status": "UNBILLED",
        "billable_amount": billable,
        "billed_invoice_id": None,
        "reviewed_by_user_id": None,
        "review_justification": None,
    }
    calc.stamp_new(row)
    db.expenses[row["id"]] = row
    if status == "ALLOWED":
        # "Only an ALLOWED expense enters the project's unbilled_wip, and when it
        # does ... the project's version increment[s] by 1."
        calc.touch(project)
    return resp.created(ser.expense_out(row))


@bp.route("/expenses/<expense_id>", methods=["GET"])
def get_expense(expense_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.expenses, expense_id, "ERR_CHARGE_NOT_FOUND", "Expense")
    return resp.ok(ser.expense_out(row))


@bp.route("/expenses", methods=["GET"])
def list_expenses():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    project_id = V.query_str("project_id")
    phase_id = V.query_str("phase_id")
    allowability_status = V.query_enum("allowability_status", V.ALLOWABILITY_STATUSES)
    billing_status = V.query_enum("billing_status", V.EXPENSE_BILLING_STATUSES)
    billed_invoice_id = V.query_str("billed_invoice_id")
    rows = list(db.expenses.values())
    if project_id is not None:
        rows = [x for x in rows if x["project_id"] == project_id]
    if phase_id is not None:
        rows = [x for x in rows if x["phase_id"] == phase_id]
    if allowability_status is not None:
        rows = [x for x in rows if x["allowability_status"] == allowability_status]
    if billing_status is not None:
        rows = [x for x in rows if x["billing_status"] == billing_status]
    if billed_invoice_id is not None:
        rows = [x for x in rows if x["billed_invoice_id"] == billed_invoice_id]
    return resp.paged(rows, ser.expense_out)


@bp.route("/expenses/<expense_id>/review", methods=["POST"])
def review_expense(expense_id):
    user_id, role = authenticate(["Controller"])
    body = V.body_json()
    decision = V.req_enum(body, "decision", ["ALLOW", "DISALLOW"])
    justification = V.req_string(body, "justification")
    expense = guards.lookup(db.expenses, expense_id, "ERR_CHARGE_NOT_FOUND", "Expense")
    project = db.projects.get(expense["project_id"])
    if expense["allowability_status"] != "PENDING_REVIEW":
        raise guards.invalid_state("Only a PENDING_REVIEW expense may be reviewed.")
    client = calc.client_of(project) if project is not None else None
    if decision == "ALLOW":
        # PRD 3.4: "Neither exclusion is overridable by review."
        if client is not None and \
                calc.expense_is_excluded(expense["category"], client) is not None:
            raise ApiError("ERR_EXPENSE_UNALLOWABLE",
                           "This expense category may not be allowed for this client.")
        expense["allowability_status"] = "ALLOWED"
        expense["allowability_reason"] = "ALLOWED_BY_REVIEW"
        expense["billable_amount"] = calc.expense_markup_amount(expense["amount"], client)
    else:
        expense["allowability_status"] = "DISALLOWED"
        expense["allowability_reason"] = "DISALLOWED_BY_REVIEW"
        expense["billable_amount"] = ZERO2
    expense["reviewed_by_user_id"] = user_id
    expense["review_justification"] = justification
    calc.touch(expense)
    if decision == "ALLOW" and project is not None:
        calc.touch(project)
    return resp.ok(ser.expense_out(expense))

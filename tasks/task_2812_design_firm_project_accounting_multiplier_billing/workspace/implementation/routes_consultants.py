"""Consultant subcontracts, payables and pay-when-paid release (PRD 3.5)."""
from flask import Blueprint

import calc
import flows
import guards
import response as resp
import serialize as ser
import validate as V
from auth import authenticate, check_project_manager, check_segregation
from db import db, new_id
from errors import ApiError
from money import ZERO2, ZERO4, q2

bp = Blueprint("consultants", __name__)


# ---------------------------------------------------------------------------
# Subcontracts
# ---------------------------------------------------------------------------
@bp.route("/consultant-subcontracts", methods=["POST"])
def create_subcontract():
    user_id, role = authenticate(["FirmAdmin", "Controller", "ProjectManager"])
    peek = V.peek_body()
    check_project_manager(role, user_id, guards.maybe(db.projects, peek.get("project_id")))
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    phase_id = V.req_string(body, "phase_id")
    consultant_name = V.req_string(body, "consultant_name")
    committed_amount = V.req_money(body, "committed_amount", min_exclusive=ZERO2)
    pay_when_paid = V.req_bool(body, "pay_when_paid")
    commitment_start = V.req_date(body, "commitment_start")
    commitment_end = V.req_date(body, "commitment_end")
    # PRD 3.5: "commitment_end must not precede commitment_start".
    if commitment_end < commitment_start:
        raise V.bad("commitment_end may not precede commitment_start.")
    project = guards.reference(db.projects, project_id, "Project")
    phase = guards.reference(db.phases, phase_id, "Phase")
    if phase["project_id"] != project["id"]:
        raise ApiError("ERR_INVALID_REFERENCE", "The phase belongs to a different project.")
    guards.require_active_project(project)
    guards.require_leaf(phase)
    row = {
        "id": new_id(),
        "project_id": project_id,
        "phase_id": phase_id,
        "consultant_name": consultant_name,
        "committed_amount": q2(committed_amount),
        "commitment_start": commitment_start,
        "commitment_end": commitment_end,
        "pay_when_paid": pay_when_paid,
        # "A drafted subcontract lands in status DRAFT [and] consumes no capacity."
        "status": "DRAFT",
    }
    calc.stamp_new(row)
    db.subcontracts[row["id"]] = row
    return resp.created(ser.subcontract_out(row))


@bp.route("/consultant-subcontracts/<subcontract_id>", methods=["GET"])
def get_subcontract(subcontract_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.subcontracts, subcontract_id,
                        "ERR_SUBCONTRACT_NOT_FOUND", "Subcontract")
    return resp.ok(ser.subcontract_out(row))


@bp.route("/consultant-subcontracts", methods=["GET"])
def list_subcontracts():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    project_id = V.query_str("project_id")
    phase_id = V.query_str("phase_id")
    status = V.query_enum("status", V.SUBCONTRACT_STATUSES)
    rows = list(db.subcontracts.values())
    if project_id is not None:
        rows = [x for x in rows if x["project_id"] == project_id]
    if phase_id is not None:
        rows = [x for x in rows if x["phase_id"] == phase_id]
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    return resp.paged(rows, ser.subcontract_out)


@bp.route("/consultant-subcontracts/<subcontract_id>/execute", methods=["POST"])
def execute_subcontract(subcontract_id):
    user_id, role = authenticate(["FirmAdmin", "Controller", "ProjectManager"])
    sub = guards.maybe(db.subcontracts, subcontract_id)
    if sub is not None:
        check_project_manager(role, user_id, db.projects.get(sub["project_id"]))
    sub = guards.lookup(db.subcontracts, subcontract_id,
                        "ERR_SUBCONTRACT_NOT_FOUND", "Subcontract")
    project = db.projects.get(sub["project_id"])
    guards.require_active_project(project)
    if sub["status"] != "DRAFT":
        raise guards.invalid_state("Only a DRAFT subcontract may be executed.")
    # PRD 2.11/3.5: REVIEW_REQUIRED blocks the execution of a consultant
    # subcontract. Rung 15 sits ahead of the fiscal-capacity rung 16.
    if calc.project_billing_posture(project) == "REVIEW_REQUIRED":
        raise ApiError("ERR_PROJECT_UNDER_BILLING_REVIEW",
                       "The project's unbilled work in progress is under billing review.")
    phase = db.phases.get(sub["phase_id"])
    if phase is not None:
        exposure = calc.consultant_overlap_exposure(sub, phase)
        # "the cap comparison is strict, so an exposure exactly equal to
        # consultant_budget is permitted while anything above it is refused."
        if exposure > phase["consultant_budget"]:
            raise ApiError("ERR_CONSULTANT_BUDGET_OVERCOMMIT",
                           "Aggregate consultant exposure of %s exceeds the phase budget of %s."
                           % (exposure, phase["consultant_budget"]))
    sub["status"] = "EXECUTED"
    calc.touch(sub)
    if phase is not None:
        if phase["status"] == "PLANNED":
            phase["status"] = "IN_PROGRESS"
        calc.touch(phase)
    return resp.ok(ser.subcontract_out(sub))


# ---------------------------------------------------------------------------
# Consultant payables -- three independent status axes
# ---------------------------------------------------------------------------
@bp.route("/consultant-invoices", methods=["POST"])
def create_consultant_invoice():
    user_id, role = authenticate(["ProjectAccountant", "Controller"])
    body = V.body_json()
    subcontract_id = V.req_string(body, "subcontract_id")
    amount = V.req_money(body, "amount", min_exclusive=ZERO2)
    invoice_date = V.req_date(body, "invoice_date")
    backup_attached = V.req_bool(body, "backup_attached")
    sub = guards.reference(db.subcontracts, subcontract_id, "Subcontract")
    project = db.projects.get(sub["project_id"])
    guards.require_active_project(project)
    guards.require_period_open(project, invoice_date, "invoice_date")
    row = {
        "id": new_id(),
        "subcontract_id": subcontract_id,
        "amount": q2(amount),
        "invoice_date": invoice_date,
        "backup_attached": backup_attached,
        "entered_by_user_id": user_id,
        # Three independent axes, each at its own initial value.
        "approval_status": "RECEIVED",
        "payment_status": "WITHHELD",
        "billing_status": "UNBILLED",
        "approved_by_user_id": None,
        "rejection_reason": None,
        # "Until it is approved" all three markup figures stay at zero.
        "applied_markup_pct": ZERO4,
        "markup_amount": ZERO2,
        "billable_amount": ZERO2,
        "client_invoice_id": None,
    }
    calc.stamp_new(row)
    db.consultant_invoices[row["id"]] = row
    return resp.created(ser.consultant_invoice_out(row))


@bp.route("/consultant-invoices/<consultant_invoice_id>", methods=["GET"])
def get_consultant_invoice(consultant_invoice_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.consultant_invoices, consultant_invoice_id,
                        "ERR_CHARGE_NOT_FOUND", "Consultant payable")
    return resp.ok(ser.consultant_invoice_out(row))


@bp.route("/consultant-invoices", methods=["GET"])
def list_consultant_invoices():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    subcontract_id = V.query_str("subcontract_id")
    client_invoice_id = V.query_str("client_invoice_id")
    approval_status = V.query_enum("approval_status", V.CI_APPROVAL_STATUSES)
    payment_status = V.query_enum("payment_status", V.CI_PAYMENT_STATUSES)
    billing_status = V.query_enum("billing_status", V.CI_BILLING_STATUSES)
    rows = list(db.consultant_invoices.values())
    if subcontract_id is not None:
        rows = [x for x in rows if x["subcontract_id"] == subcontract_id]
    if client_invoice_id is not None:
        rows = [x for x in rows if x["client_invoice_id"] == client_invoice_id]
    if approval_status is not None:
        rows = [x for x in rows if x["approval_status"] == approval_status]
    if payment_status is not None:
        rows = [x for x in rows if x["payment_status"] == payment_status]
    if billing_status is not None:
        rows = [x for x in rows if x["billing_status"] == billing_status]
    return resp.paged(rows, ser.consultant_invoice_out)


@bp.route("/consultant-invoices/<consultant_invoice_id>/approve", methods=["POST"])
def approve_consultant_invoice(consultant_invoice_id):
    user_id, role = authenticate(["ProjectManager", "Controller"])
    ci = guards.maybe(db.consultant_invoices, consultant_invoice_id)
    if ci is not None:
        check_project_manager(role, user_id, calc.project_of_consultant_invoice(ci))
        check_segregation(user_id, ci["entered_by_user_id"])
    ci = guards.lookup(db.consultant_invoices, consultant_invoice_id,
                       "ERR_CHARGE_NOT_FOUND", "Consultant payable")
    sub = calc.subcontract_of(ci)
    project = calc.project_of_consultant_invoice(ci)
    guards.require_active_project(project)
    if ci["approval_status"] != "RECEIVED":
        raise guards.invalid_state("Only a RECEIVED consultant payable may be approved.")
    if sub["status"] != "EXECUTED":
        raise guards.invalid_state("The subcontract is not EXECUTED.")
    remaining = calc.subcontract_committed_remaining(sub)
    if ci["amount"] > remaining:
        raise ApiError("ERR_SUBCONTRACT_COMMITMENT_EXCEEDED",
                       "The payable of %s exceeds the remaining commitment of %s."
                       % (ci["amount"], remaining))
    client = calc.client_of(project)
    applied, markup_amount, billable = calc.consultant_markup(ci, sub, project, client)
    ci["applied_markup_pct"] = applied
    ci["markup_amount"] = markup_amount
    ci["billable_amount"] = billable
    ci["approval_status"] = "APPROVED"
    ci["approved_by_user_id"] = user_id
    calc.touch(ci)
    calc.touch(sub)
    calc.touch(project)
    return resp.ok(ser.consultant_invoice_out(ci))


@bp.route("/consultant-invoices/<consultant_invoice_id>/reject", methods=["POST"])
def reject_consultant_invoice(consultant_invoice_id):
    user_id, role = authenticate(["ProjectManager", "Controller"])
    ci = guards.maybe(db.consultant_invoices, consultant_invoice_id)
    if ci is not None:
        check_project_manager(role, user_id, calc.project_of_consultant_invoice(ci))
    body = V.body_json()
    reason = V.req_string(body, "reason")
    ci = guards.lookup(db.consultant_invoices, consultant_invoice_id,
                       "ERR_CHARGE_NOT_FOUND", "Consultant payable")
    sub = calc.subcontract_of(ci)
    project = calc.project_of_consultant_invoice(ci)
    if ci["approval_status"] == "RECEIVED":
        ci["approval_status"] = "REJECTED"
        ci["rejection_reason"] = reason
        calc.touch(ci)
    elif ci["approval_status"] == "APPROVED" and ci["billing_status"] == "UNBILLED":
        # PRD 3.5: the full compensating action -- the drawdown and the
        # work-in-progress admission are both reversed.
        ci["approval_status"] = "REJECTED"
        ci["rejection_reason"] = reason
        ci["applied_markup_pct"] = ZERO4
        ci["markup_amount"] = ZERO2
        ci["billable_amount"] = ZERO2
        calc.touch(ci)
        if sub is not None:
            calc.touch(sub)
        if project is not None:
            calc.touch(project)
    else:
        raise guards.invalid_state(
            "This consultant payable can no longer be rejected.")
    return resp.ok(ser.consultant_invoice_out(ci))


@bp.route("/consultant-invoices/<consultant_invoice_id>/release-payment", methods=["POST"])
def release_consultant_payment(consultant_invoice_id):
    authenticate(["Controller"])
    ci = guards.lookup(db.consultant_invoices, consultant_invoice_id,
                       "ERR_CHARGE_NOT_FOUND", "Consultant payable")
    sub = calc.subcontract_of(ci)
    if ci["approval_status"] != "APPROVED" or ci["payment_status"] != "WITHHELD":
        raise guards.invalid_state(
            "Only an APPROVED, WITHHELD consultant payable may be released.")
    if sub is not None and sub["pay_when_paid"]:
        client_invoice = db.invoices.get(ci["client_invoice_id"]) \
            if ci["client_invoice_id"] else None
        if client_invoice is None or client_invoice["status"] != "PAID":
            raise ApiError("ERR_PAY_WHEN_PAID_NOT_SATISFIED",
                           "The client invoice that billed this payable has not been paid.")
    flows.release_payable(ci)
    return resp.ok(ser.consultant_invoice_out(ci))

"""Client invoices (PRD 3.7), routed write-offs (PRD 3.8) and overhead rate
certification (PRD 3.9)."""
from flask import Blueprint

import calc
import flows
import guards
import response as resp
import serialize as ser
import validate as V
from auth import (authenticate, check_client_contact, check_project_manager,
                  check_segregation, check_write_off_approval_level)
from db import db, new_id
from errors import ApiError
from money import ZERO2, ZERO4, q2, q4

bp = Blueprint("billing", __name__)

MAX_REVISION_ROUND = 3


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@bp.route("/invoices", methods=["POST"])
def create_invoice():
    user_id, role = authenticate(["ProjectAccountant", "Controller"])
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    period_end = V.req_date(body, "period_end")
    expected_version = V.req_int(body, "expected_project_version")
    project = guards.reference(db.projects, project_id, "Project")
    guards.require_project_version(project, expected_version)
    guards.require_active_project(project)
    # PRD 2.11: HOLD blocks invoice preparation. Compliance outranks fiscal capacity.
    if calc.project_billing_posture(project) == "HOLD":
        raise ApiError("ERR_OVERHEAD_RATE_NOT_CERTIFIED",
                       "This public-agency project has no certified overhead rate for the year.")
    labor, expenses, payables = calc.sweep_candidates(project, period_end)
    _, _, _, gross = flows.sweep_totals(labor, expenses, payables)
    # Ladder rung 16: ERR_BILLING_EXCEEDS_EARNED precedes ERR_NOTHING_TO_INVOICE.
    if project["contract_type"] == "FIXED_FEE":
        headroom = calc.fixed_fee_headroom(project, None)
        if gross > headroom:
            raise ApiError("ERR_BILLING_EXCEEDS_EARNED",
                           "gross_billed of %s exceeds the earned headroom of %s."
                           % (gross, headroom))
    if gross == ZERO2:
        raise ApiError("ERR_NOTHING_TO_INVOICE",
                       "No eligible unbilled charge is dated on or before period_end.")
    client = calc.client_of(project)
    row = {
        "id": new_id(),
        "project_id": project_id,
        "period_end": period_end,
        "status": "DRAFT",
        "revision_round": 0,
        "prepared_by_user_id": user_id,
        "submitted_by_user_id": None,
        "client_decision_comment": None,
        "paid_on": None,
        "void_reason": None,
    }
    calc.stamp_new(row)
    flows.write_invoice_figures(row, client, labor, expenses, payables)
    db.invoices[row["id"]] = row
    flows.apply_sweep(row, labor, expenses, payables)
    calc.touch(project)
    return resp.created(ser.invoice_out(row))


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    user_id, role = authenticate(["FirmAdmin", "Controller", "ProjectManager",
                                  "ProjectAccountant", "ClientContact"])
    invoice = guards.maybe(db.invoices, invoice_id)
    if invoice is not None:
        check_client_contact(role, user_id, db.projects.get(invoice["project_id"]))
    invoice = guards.lookup(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    return resp.ok(ser.invoice_out(invoice))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = authenticate(["FirmAdmin", "Controller", "ProjectManager",
                                  "ProjectAccountant", "ClientContact"])
    project_id = V.query_str("project_id")
    if role == "ClientContact" and project_id is not None:
        check_client_contact(role, user_id, guards.maybe(db.projects, project_id))
    status = V.query_enum("status", V.INVOICE_STATUSES)
    rows = list(db.invoices.values())
    if project_id is not None:
        rows = [x for x in rows if x["project_id"] == project_id]
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    if role == "ClientContact":
        # PRD 2.1: a client contact's reads "are confined to the invoices of their
        # own client's projects".
        own = set(p["id"] for p in db.projects.values() if p["client_id"] == user_id)
        rows = [x for x in rows if x["project_id"] in own]
    return resp.paged(rows, ser.invoice_out)


@bp.route("/invoices/<invoice_id>/submit", methods=["POST"])
def submit_invoice(invoice_id):
    user_id, role = authenticate(["ProjectAccountant", "Controller"])
    invoice = guards.maybe(db.invoices, invoice_id)
    if invoice is not None:
        check_segregation(user_id, invoice["prepared_by_user_id"])
    invoice = guards.lookup(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    project = db.projects.get(invoice["project_id"])
    if invoice["status"] != "DRAFT":
        raise guards.invalid_state("Only a DRAFT invoice may be submitted to the client.")
    if invoice["gross_billed"] <= ZERO2:
        raise guards.invalid_state("An invoice with no gross billed may not be submitted.")
    client = calc.client_of(project) if project is not None else None
    # PRD 3.7: backup completeness is enforced here, not at preparation.
    if client is not None and client["is_public_agency"] and invoice["backup_missing_count"] > 0:
        raise ApiError("ERR_BACKUP_DOCUMENTATION_MISSING",
                       "%d swept consultant payable(s) have no supporting documentation."
                       % invoice["backup_missing_count"])
    invoice["submitted_by_user_id"] = user_id
    invoice["status"] = "PENDING_CLIENT_REVIEW"
    calc.touch(invoice)
    return resp.ok(ser.invoice_out(invoice))


@bp.route("/invoices/<invoice_id>/review", methods=["POST"])
def review_invoice(invoice_id):
    user_id, role = authenticate(["ClientContact"])
    invoice = guards.maybe(db.invoices, invoice_id)
    if invoice is not None:
        check_client_contact(role, user_id, db.projects.get(invoice["project_id"]))
    body = V.body_json()
    decision = V.req_enum(body, "decision", ["APPROVE", "REQUEST_REVISION"])
    comment = V.opt_string(body, "comment")
    invoice = guards.lookup(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    if invoice["status"] != "PENDING_CLIENT_REVIEW":
        raise guards.invalid_state("Only an invoice under client review may be decided.")
    if decision == "REQUEST_REVISION" and invoice["revision_round"] >= MAX_REVISION_ROUND:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED",
                       "The invoice has already been revised %d times." % MAX_REVISION_ROUND)
    invoice["client_decision_comment"] = comment
    if decision == "APPROVE":
        invoice["status"] = "APPROVED"
    else:
        # "REQUEST_REVISION first increments revision_round by 1 and then moves
        # the invoice PENDING_CLIENT_REVIEW -> REVISION_REQUESTED."
        invoice["revision_round"] = invoice["revision_round"] + 1
        invoice["status"] = "REVISION_REQUESTED"
    calc.touch(invoice)
    return resp.ok(ser.invoice_out(invoice))


@bp.route("/invoices/<invoice_id>/revise", methods=["POST"])
def revise_invoice(invoice_id):
    authenticate(["ProjectAccountant", "Controller"])
    invoice = guards.lookup(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    project = db.projects.get(invoice["project_id"])
    if invoice["status"] != "REVISION_REQUESTED":
        raise guards.invalid_state("Only a REVISION_REQUESTED invoice may be revised.")
    labor, expenses, payables = calc.sweep_candidates(project, invoice["period_end"],
                                                      invoice_id=invoice["id"])
    _, _, _, gross = flows.sweep_totals(labor, expenses, payables)
    # "The same ceiling is re-tested whenever a revision re-runs the sweep."
    if project["contract_type"] == "FIXED_FEE":
        headroom = calc.fixed_fee_headroom(project, invoice["id"])
        if gross > headroom:
            raise ApiError("ERR_BILLING_EXCEEDS_EARNED",
                           "gross_billed of %s exceeds the earned headroom of %s."
                           % (gross, headroom))
    client = calc.client_of(project)
    flows.write_invoice_figures(invoice, client, labor, expenses, payables)
    flows.apply_sweep(invoice, labor, expenses, payables)
    invoice["status"] = "DRAFT"
    invoice["submitted_by_user_id"] = None
    calc.touch(invoice)
    return resp.ok(ser.invoice_out(invoice))


@bp.route("/invoices/<invoice_id>/record-payment", methods=["POST"])
def record_invoice_payment(invoice_id):
    authenticate(["Controller"])
    body = V.body_json()
    received_on = V.req_date(body, "received_on")
    invoice = guards.lookup(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    project = db.projects.get(invoice["project_id"])
    if invoice["status"] != "APPROVED":
        raise guards.invalid_state("Only an APPROVED invoice may be settled.")
    invoice["status"] = "PAID"
    invoice["paid_on"] = received_on
    calc.touch(invoice)
    # PRD 3.7 hops two through four: the settlement satisfies pay-when-paid.
    flows.release_payables_of_invoice(invoice)
    calc.touch(project)
    calc.maybe_close_project(project)
    return resp.ok(ser.invoice_out(invoice))


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    authenticate(["Controller"])
    body = V.body_json()
    reason = V.req_string(body, "reason")
    invoice = guards.lookup(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    project = db.projects.get(invoice["project_id"])
    if invoice["status"] not in ("DRAFT", "PENDING_CLIENT_REVIEW", "REVISION_REQUESTED"):
        raise guards.invalid_state("This invoice can no longer be voided.")
    flows.detach_invoice(invoice)
    invoice["status"] = "VOID"
    invoice["void_reason"] = reason
    calc.touch(invoice)
    calc.touch(project)
    calc.maybe_close_project(project)
    return resp.ok(ser.invoice_out(invoice))


# ---------------------------------------------------------------------------
# Write-offs (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/write-offs", methods=["POST"])
def create_write_off():
    user_id, role = authenticate(["ProjectAccountant", "ProjectManager", "Controller"])
    peek = V.peek_body()
    check_project_manager(role, user_id, guards.maybe(db.projects, peek.get("project_id")))
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    target_type = V.req_enum(body, "target_type", V.WRITE_OFF_TARGET_TYPES)
    amount = V.req_money(body, "amount", min_exclusive=ZERO2)
    reason = V.req_string(body, "reason")
    # PRD 3.8: invoice_id is supplied "when and only when target_type is
    # INVOICE_RECEIVABLE" and "must be omitted when target_type is UNBILLED_LABOR_WIP".
    if target_type == "INVOICE_RECEIVABLE":
        invoice_id = V.req_string(body, "invoice_id")
    else:
        V.forbid(body, "invoice_id",
                 "invoice_id must be omitted when target_type is UNBILLED_LABOR_WIP.")
        invoice_id = None
    project = guards.reference(db.projects, project_id, "Project")
    invoice = None
    if invoice_id is not None:
        invoice = guards.reference(db.invoices, invoice_id, "Invoice")
    guards.require_active_project(project)
    amount = q2(amount)

    allocated = []
    if target_type == "UNBILLED_LABOR_WIP":
        allocated = calc.allocate_write_off(project, amount)
        if allocated is None:
            raise ApiError("ERR_WRITE_OFF_AMOUNT_NOT_ALLOCATABLE",
                           "The amount does not equal an exact prefix sum of the "
                           "ordered unbilled labour candidates.")
        aging_days = 0
        for entry_id in allocated:
            entry = db.time_entries.get(entry_id)
            if entry is None:
                continue
            age = calc.age_days(entry["work_date"])
            if age > aging_days:
                aging_days = age
    else:
        if amount != invoice["net_due"]:
            raise ApiError("ERR_WRITE_OFF_AMOUNT_MISMATCH",
                           "The amount must equal the invoice's net_due of %s."
                           % invoice["net_due"])
        aging_days = calc.age_days(invoice["period_end"])

    required_approver, status = calc.write_off_routing(target_type, amount, aging_days)
    row = {
        "id": new_id(),
        "project_id": project_id,
        "invoice_id": invoice_id,
        "target_type": target_type,
        "amount": amount,
        "reason": reason,
        "aging_days": aging_days,
        "required_approver": required_approver,
        "allocated_time_entry_ids": allocated,
        "status": status,
        "prepared_by_user_id": user_id,
        "approved_by_user_id": None,
    }
    calc.stamp_new(row)
    db.write_offs[row["id"]] = row
    return resp.created(ser.write_off_out(row))


@bp.route("/write-offs/<write_off_id>", methods=["GET"])
def get_write_off(write_off_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.write_offs, write_off_id, "ERR_WRITE_OFF_NOT_FOUND", "Write-off")
    return resp.ok(ser.write_off_out(row))


@bp.route("/write-offs", methods=["GET"])
def list_write_offs():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    project_id = V.query_str("project_id")
    invoice_id = V.query_str("invoice_id")
    status = V.query_enum("status", V.WRITE_OFF_STATUSES)
    prepared_by = V.query_str("prepared_by_user_id")
    rows = list(db.write_offs.values())
    if project_id is not None:
        rows = [x for x in rows if x["project_id"] == project_id]
    if invoice_id is not None:
        rows = [x for x in rows if x["invoice_id"] == invoice_id]
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    if prepared_by is not None:
        rows = [x for x in rows if x["prepared_by_user_id"] == prepared_by]
    return resp.paged(rows, ser.write_off_out)


@bp.route("/write-offs/<write_off_id>/approve", methods=["POST"])
def approve_write_off(write_off_id):
    user_id, role = authenticate(["ProjectManager", "Controller"])
    write_off = guards.maybe(db.write_offs, write_off_id)
    if write_off is not None:
        check_project_manager(role, user_id, db.projects.get(write_off["project_id"]))
        check_segregation(user_id, write_off["prepared_by_user_id"])
        # Rung 6 sits below segregation of duties (PRD 2.8).
        check_write_off_approval_level(role, write_off)
    write_off = guards.lookup(db.write_offs, write_off_id,
                              "ERR_WRITE_OFF_NOT_FOUND", "Write-off")
    project = db.projects.get(write_off["project_id"])
    if write_off["status"] not in ("PENDING_PM_APPROVAL", "PENDING_CONTROLLER_APPROVAL"):
        raise guards.invalid_state("This write-off has already been approved.")
    controller_branch = write_off["status"] == "PENDING_CONTROLLER_APPROVAL"
    invoice = db.invoices.get(write_off["invoice_id"]) if write_off["invoice_id"] else None
    if write_off["target_type"] == "INVOICE_RECEIVABLE":
        if invoice is None or invoice["status"] != "APPROVED":
            raise guards.invalid_state(
                "The receivable being written off is not an APPROVED invoice.")
        if write_off["amount"] != invoice["net_due"]:
            raise ApiError("ERR_WRITE_OFF_AMOUNT_MISMATCH",
                           "The amount must equal the invoice's net_due of %s."
                           % invoice["net_due"])
    if controller_branch:
        # "This branch, and only this branch, sets overhead_adjustment_required."
        project["overhead_adjustment_required"] = True
    if write_off["target_type"] == "UNBILLED_LABOR_WIP":
        flows.write_off_labor(write_off)
    else:
        invoice["status"] = "WRITTEN_OFF"
        calc.touch(invoice)
        # "Writing off the receivable also releases its withheld consultant payables."
        flows.release_payables_of_invoice(invoice)
    write_off["status"] = "APPROVED"
    write_off["approved_by_user_id"] = user_id
    calc.touch(write_off)
    calc.touch(project)
    calc.maybe_close_project(project)
    return resp.ok(ser.write_off_out(write_off))


# ---------------------------------------------------------------------------
# Overhead rate certification (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/overhead-certifications", methods=["POST"])
def create_certification():
    user_id, role = authenticate(["Controller", "FirmAdmin"])
    body = V.body_json()
    fiscal_year = V.req_int(body, "fiscal_year", minimum=2020, maximum=2100)
    ytd_months = V.req_int(body, "ytd_months", minimum=1, maximum=12)
    direct_labor_base = V.req_money(body, "direct_labor_base", min_exclusive=ZERO2)
    indirect_cost_pool = V.req_money(body, "indirect_cost_pool", min_exclusive=ZERO2)
    unallowable_costs = V.req_money(body, "unallowable_costs", minimum=ZERO2)
    for existing in db.certifications.values():
        if existing["fiscal_year"] == fiscal_year and \
                existing["status"] in ("SUBMITTED", "CERTIFIED"):
            raise ApiError("ERR_CERTIFICATION_YEAR_DUPLICATE",
                           "Fiscal year %d is already occupied by a %s certification."
                           % (fiscal_year, existing["status"]))
    row = {
        "id": new_id(),
        "fiscal_year": fiscal_year,
        "ytd_months": ytd_months,
        "direct_labor_base": q2(direct_labor_base),
        "indirect_cost_pool": q2(indirect_cost_pool),
        "unallowable_costs": q2(unallowable_costs),
        "status": "SUBMITTED",
        # The provisional rate annualises and keeps unallowable costs in the pool.
        "provisional_overhead_rate": calc.provisional_overhead_rate(
            indirect_cost_pool, direct_labor_base, ytd_months),
        "final_overhead_rate": None,
        "prepared_by_user_id": user_id,
        "certified_by_user_id": None,
        "certified_multiplier_ceiling": None,
        "findings": None,
    }
    calc.stamp_new(row)
    db.certifications[row["id"]] = row
    return resp.created(ser.certification_out(row))


@bp.route("/overhead-certifications/<certification_id>", methods=["GET"])
def get_certification(certification_id):
    authenticate(["FirmAdmin", "Controller", "ProjectAccountant"])
    row = guards.lookup(db.certifications, certification_id,
                        "ERR_CERTIFICATION_NOT_FOUND", "Certification")
    return resp.ok(ser.certification_out(row))


@bp.route("/overhead-certifications", methods=["GET"])
def list_certifications():
    authenticate(["FirmAdmin", "Controller", "ProjectAccountant"])
    fiscal_year = V.query_int("fiscal_year")
    status = V.query_enum("status", V.CERTIFICATION_STATUSES)
    rows = list(db.certifications.values())
    if fiscal_year is not None:
        rows = [x for x in rows if x["fiscal_year"] == fiscal_year]
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    return resp.paged(rows, ser.certification_out)


@bp.route("/overhead-certifications/<certification_id>/certify", methods=["POST"])
def certify_certification(certification_id):
    user_id, role = authenticate(["Controller"])
    cert = guards.maybe(db.certifications, certification_id)
    if cert is not None:
        check_segregation(user_id, cert["prepared_by_user_id"])
    cert = guards.lookup(db.certifications, certification_id,
                         "ERR_CERTIFICATION_NOT_FOUND", "Certification")
    if cert["status"] != "SUBMITTED":
        raise guards.invalid_state("Only a SUBMITTED certification may be certified.")
    final_rate = calc.final_overhead_rate(cert["indirect_cost_pool"],
                                          cert["unallowable_costs"],
                                          cert["direct_labor_base"])
    cert["final_overhead_rate"] = final_rate
    cert["certified_multiplier_ceiling"] = calc.certified_ceiling(final_rate)
    cert["certified_by_user_id"] = user_id
    cert["status"] = "CERTIFIED"
    calc.touch(cert)
    # Hops two and three: every public-agency project recomputes its ceiling and
    # re-runs billing_posture, so "the version of every affected project" increments.
    affected = [p for p in db.projects.values()
                if (calc.client_of(p) or {}).get("is_public_agency")]
    affected.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for project in affected:
        calc.touch(project)
    return resp.ok(ser.certification_out(cert))


@bp.route("/overhead-certifications/<certification_id>/return-findings", methods=["POST"])
def return_certification_findings(certification_id):
    authenticate(["Controller"])
    body = V.body_json()
    findings = V.req_string(body, "findings")
    cert = guards.lookup(db.certifications, certification_id,
                         "ERR_CERTIFICATION_NOT_FOUND", "Certification")
    if cert["status"] != "SUBMITTED":
        raise guards.invalid_state("Only a SUBMITTED certification may be returned with findings.")
    cert["findings"] = findings
    cert["status"] = "REJECTED"
    calc.touch(cert)
    return resp.ok(ser.certification_out(cert))

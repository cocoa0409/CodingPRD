"""Invoices, voids and the yard reconciliation (PRD 3.7 and 3.8)."""

from flask import Blueprint, request

from calc import loss_assessment
from envelope import object_response
from errors import fail
from serialize import invoice_out, reconciliation_out
from services import (account_of, authenticate, enforce_scope, filter_fk, issue_invoice,
                      lookup, maybe_close_contract, move_fleet, new_line, open_amount,
                      product_by_code, recompute_account, reevaluate_billing_on_void)
from store import store
from validation import check_body, check_object_list, parse_pagination, query_enum
from web import json_body, page

bp = Blueprint("ledger", __name__)

READ_INVOICE_ROLES = ("PlatformAdmin", "AccountManager", "CustomerContact", "YardAuditor")
READ_RECON_ROLES = ("PlatformAdmin", "AccountManager", "YardAuditor",
                    "DispatchCoordinator", "CustomerContact")
INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")
INVOICE_KINDS = ("MOBILIZATION", "PERIODIC", "CANCELLATION", "FINAL")
RECON_STATUSES = ("OPEN", "FINALIZED")

UNIT_RETURN_SPEC = {
    "product_code": {"req": True, "type": "string"},
    "returned": {"req": True, "type": "int"},
    "damaged": {"req": True, "type": "int"},
    "missing": {"req": True, "type": "int"},
}

FINALIZE_SPEC = {
    "unit_returns": {"req": True, "type": "array"},
    "theft_police_report_number": {"type": "string"},
    "auditor_note": {"type": "string"},
}


@bp.get("/fence-rentals/invoices/<row_id>")
def read_invoice(row_id):
    identity = authenticate(READ_INVOICE_ROLES)
    invoice = lookup("invoices", row_id)
    enforce_scope(identity, lookup("contracts", invoice["contract_id"])["customer_account_id"])
    return object_response(invoice_out(invoice), 200)


@bp.get("/fence-rentals/invoices")
def list_invoices():
    identity = authenticate(READ_INVOICE_ROLES)
    limit, offset = parse_pagination(request.args)
    status = query_enum(request.args, "status", INVOICE_STATUSES)
    kind = query_enum(request.args, "invoice_kind", INVOICE_KINDS)
    contract = filter_fk(request.args, "contract_id", "contracts")
    if contract is not None:
        enforce_scope(identity, contract["customer_account_id"])
    rows = []
    for invoice in store.sorted_rows("invoices"):
        if contract is not None and invoice["contract_id"] != contract["id"]:
            continue
        if status is not None and invoice["status"] != status:
            continue
        if kind is not None and invoice["invoice_kind"] != kind:
            continue
        if identity.is_customer:
            owner = store.contracts[invoice["contract_id"]]["customer_account_id"]
            if owner != identity.user_id:
                continue
        rows.append(invoice)
    return page(rows, invoice_out, limit, offset)


@bp.post("/fence-rentals/invoices/<row_id>/void")
def void_invoice(row_id):
    identity = authenticate(("AccountManager",))
    parsed = check_body(json_body(), {"void_reason_code": {"req": True, "type": "string"}})
    invoice = lookup("invoices", row_id)
    if identity.user_id == invoice["issued_by_user_id"]:                        # rung 7
        fail("ERR_SEGREGATION_OF_DUTIES",
             "An invoice may not be voided by the identity that issued it.")
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):                   # rung 9
        fail("ERR_INVOICE_STATE", "Only an ISSUED or PARTIALLY_PAID invoice may be voided.")

    written_off = open_amount(invoice)
    invoice["status"] = "VOID"
    invoice["void_reason_code"] = parsed["void_reason_code"]
    store.touch(invoice)

    contract = lookup("contracts", invoice["contract_id"])
    recompute_account(account_of(contract), credited_delta=written_off)
    reevaluate_billing_on_void(contract)
    maybe_close_contract(contract)
    return object_response(invoice_out(invoice), 200)


@bp.get("/fence-rentals/reconciliations/<row_id>")
def read_reconciliation(row_id):
    identity = authenticate(READ_RECON_ROLES)
    recon = lookup("reconciliations", row_id)
    enforce_scope(identity, lookup("contracts", recon["contract_id"])["customer_account_id"])
    return object_response(reconciliation_out(recon), 200)


@bp.get("/fence-rentals/reconciliations")
def list_reconciliations():
    identity = authenticate(READ_RECON_ROLES)
    limit, offset = parse_pagination(request.args)
    status = query_enum(request.args, "status", RECON_STATUSES)
    contract = filter_fk(request.args, "contract_id", "contracts")
    work_order = filter_fk(request.args, "work_order_id", "work_orders")
    if contract is not None:
        enforce_scope(identity, contract["customer_account_id"])
    rows = []
    for recon in store.sorted_rows("reconciliations"):
        if contract is not None and recon["contract_id"] != contract["id"]:
            continue
        if work_order is not None and recon["work_order_id"] != work_order["id"]:
            continue
        if status is not None and recon["status"] != status:
            continue
        if identity.is_customer:
            owner = store.contracts[recon["contract_id"]]["customer_account_id"]
            if owner != identity.user_id:
                continue
        rows.append(recon)
    return page(rows, reconciliation_out, limit, offset)


def check_snapshot_reconciles(recon, unit_returns):
    """Rung 23: exactly the snapshot's codes, each fully accounted for."""
    snapshot = {entry["product_code"]: entry["unit_count"]
                for entry in recon["deployed_snapshot"]}
    seen = set()
    for entry in unit_returns:
        code = entry["product_code"]
        if code in seen:
            fail("ERR_PANEL_COUNT_MISMATCH", "unit_returns repeats a product code.")
        seen.add(code)
        if code not in snapshot:
            fail("ERR_PANEL_COUNT_MISMATCH",
                 "unit_returns names a product absent from the deployed snapshot.")
        if entry["returned"] + entry["damaged"] + entry["missing"] != snapshot[code]:
            fail("ERR_PANEL_COUNT_MISMATCH",
                 "returned + damaged + missing must equal the deployed unit count.")
    for code in snapshot:
        if code not in seen:
            fail("ERR_PANEL_COUNT_MISMATCH",
                 "unit_returns omits a product present in the deployed snapshot.")


@bp.post("/fence-rentals/reconciliations/<row_id>/finalize")
def finalize_reconciliation(row_id):
    identity = authenticate(("YardAuditor",))
    parsed = check_body(json_body(), FINALIZE_SPEC)
    unit_returns = check_object_list("unit_returns", parsed["unit_returns"], UNIT_RETURN_SPEC)
    recon = lookup("reconciliations", row_id)
    products = {}
    for entry in unit_returns:                                                 # rung 5
        products[entry["product_code"]] = product_by_code(entry["product_code"])

    removal_order = lookup("work_orders", recon["work_order_id"])
    if identity.user_id == removal_order["completed_by_user_id"]:               # rung 7
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A reconciliation may not be finalized by the identity that completed the removal.")
    if recon["status"] != "OPEN":                                              # rung 9
        fail("ERR_RECONCILIATION_STATE", "Only an OPEN reconciliation may be finalized.")

    check_snapshot_reconciles(recon, unit_returns)                             # rung 23

    contract = lookup("contracts", recon["contract_id"])
    police_report = parsed.get("theft_police_report_number")
    variant, loss_cents, damage_cents = loss_assessment(
        unit_returns, products, police_report is not None, contract["contract_type"])

    recon["unit_returns"] = [dict(entry) for entry in unit_returns]
    recon["theft_police_report_number"] = police_report
    if "auditor_note" in parsed:
        recon["auditor_note"] = parsed["auditor_note"]
    recon["assessment_variant"] = variant
    recon["loss_charge_cents"] = loss_cents
    recon["damage_charge_cents"] = damage_cents
    recon["status"] = "FINALIZED"
    recon["finalized_by_user_id"] = identity.user_id
    store.touch(recon)

    for entry in unit_returns:                                                # hop one
        product = products[entry["product_code"]]
        move_fleet(product, "deployed_count", "available_count", entry["returned"])
        move_fleet(product, "deployed_count", "damaged_count", entry["damaged"])
        move_fleet(product, "deployed_count", "lost_count", entry["missing"])

    if loss_cents + damage_cents > 0:                                          # hop two
        total_missing = sum(entry["missing"] for entry in unit_returns)
        total_damaged = sum(entry["damaged"] for entry in unit_returns)
        issue_invoice(contract, "FINAL",
                      [new_line("LOSS", loss_cents, None, total_missing),
                       new_line("DAMAGE", damage_cents, None, total_damaged)],
                      identity.user_id)
    maybe_close_contract(contract)
    return object_response(reconciliation_out(recon), 200)

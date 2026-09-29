"""Conversion, planning, phase moves, cancellation and billing runs
(PRD 3.3, 3.5, 3.8 and 3.9)."""

from flask import Blueprint, request

from calc import cancellation_fee, period_charge, whole_days
from envelope import object_response
from errors import fail
from serialize import contract_out, invoice_out, work_order_out
from services import (authenticate, enforce_scope, filter_fk, issue_invoice, lookup,
                      new_line, next_billing_floor, reevaluate_past_due,
                      release_reservation)
from store import store
from validation import check_body, parse_pagination, query_enum
from web import json_body, page

bp = Blueprint("contracts", __name__)

READ_CONTRACT_ROLES = ("PlatformAdmin", "AccountManager", "CustomerContact",
                       "DispatchCoordinator", "YardAuditor")
LIFECYCLE_STATUSES = ("PENDING_MOBILIZATION", "ACTIVE", "DEMOBILIZING", "CLOSED", "CANCELLED")
BILLING_STATUSES = ("NOT_BILLED", "CURRENT", "PAST_DUE", "SETTLED")
PLANNABLE_TYPES = ("DELIVERY_INSTALL", "RELOCATION", "REMOVAL", "RESET")

CONVERT_SPEC = {
    "quote_id": {"req": True, "type": "string"},
    "terms_acknowledged_by": {"req": True, "type": "string"},
}

PLAN_SPEC = {
    "work_order_type": {"req": True, "type": "string", "enum": PLANNABLE_TYPES},
    "ordered_linear_feet": {"req": True, "type": "int", "gt": 0},
    "scheduled_start_utc": {"type": "instant"},
    "phase_from": {"forbidden": True},
    "phase_to": {"forbidden": True},
}

RESET_SPEC = {
    "expected_contract_version": {"req": True, "type": "int"},
    "ordered_linear_feet": {"req": True, "type": "int", "gt": 0},
    "phase_to": {"req": True, "type": "int"},
    "scheduled_start_utc": {"type": "instant"},
}

BILLING_SPEC = {
    "period_start_utc": {"req": True, "type": "instant"},
    "period_end_utc": {"req": True, "type": "instant"},
}


def new_work_order(contract, work_order_type, ordered_linear_feet, scheduled_start=None,
                   phase_from=None, phase_to=None, predecessor_id=None, relation=None):
    row = store.new_row("work_orders")
    row.update({
        "contract_id": contract["id"],
        "crew_id": None,
        "predecessor_work_order_id": predecessor_id,
        "predecessor_relation": relation,
        "work_order_type": work_order_type,
        "ordered_linear_feet": ordered_linear_feet,
        "phase_from": phase_from,
        "phase_to": phase_to,
        "scheduled_start_utc": scheduled_start,
        "estimated_labor_hours": None,
        "scheduled_end_utc": None,
        "status": "PLANNED",
        "completed_linear_feet": 0,
        "reserved_unit_counts": [],
        "completed_by_user_id": None,
        "abort_reason_code": None,
        "cancel_reason_code": None,
    })
    store.work_orders[row["id"]] = row
    return row


@bp.post("/fence-rentals/contracts")
def convert_quote():
    authenticate(("AccountManager",))
    parsed = check_body(json_body(), CONVERT_SPEC)
    quote = lookup("quotes", parsed["quote_id"])
    if quote["status"] != "ACCEPTED":
        fail("ERR_QUOTE_STATE", "Only an ACCEPTED quote may be converted.")
    jobsite = lookup("jobsites", quote["jobsite_id"])
    pinned_version = quote["version"]

    commitments = [{"product_code": quote["panel_product_code"],
                    "unit_count": quote["panel_unit_count"]}]
    for line in quote["addon_lines"]:
        commitments.append({"product_code": line["product_code"],
                            "unit_count": line["quantity"]})

    contract = store.new_row("contracts")
    contract.update({
        "quote_id": quote["id"],
        "customer_account_id": jobsite["customer_account_id"],
        "jobsite_id": jobsite["id"],
        "pinned_quote_version": pinned_version,
        "contract_type": quote["contract_type"],
        "monthly_recurring_cents": quote["monthly_recurring_cents"],
        "install_labor_cents": quote["install_labor_cents"],
        "one_time_cents": quote["one_time_cents"],
        "ordered_linear_feet": quote["linear_feet"],
        "deployed_linear_feet": 0,
        "fleet_commitments": commitments,
        "addons_deployed": False,
        "lifecycle_status": "PENDING_MOBILIZATION",
        "billing_status": "NOT_BILLED",
        "billing_anchor_utc": None,
        "billed_through_utc": None,
        "cancellation_fee_cents": 0,
        "current_phase": 1,
        "terms_acknowledged_by": parsed["terms_acknowledged_by"],
    })
    store.contracts[contract["id"]] = contract
    quote["status"] = "CONVERTED"
    store.touch(quote)
    return object_response(contract_out(contract), 201)


@bp.get("/fence-rentals/contracts/<row_id>")
def read_contract(row_id):
    identity = authenticate(READ_CONTRACT_ROLES)
    contract = lookup("contracts", row_id)
    enforce_scope(identity, contract["customer_account_id"])
    return object_response(contract_out(contract), 200)


@bp.get("/fence-rentals/contracts")
def list_contracts():
    identity = authenticate(READ_CONTRACT_ROLES)
    limit, offset = parse_pagination(request.args)
    lifecycle = query_enum(request.args, "lifecycle_status", LIFECYCLE_STATUSES)
    billing = query_enum(request.args, "billing_status", BILLING_STATUSES)
    account = filter_fk(request.args, "customer_account_id", "accounts")
    quote = filter_fk(request.args, "quote_id", "quotes")
    jobsite = filter_fk(request.args, "jobsite_id", "jobsites")
    if account is not None:
        enforce_scope(identity, account["id"])
    if jobsite is not None:
        enforce_scope(identity, jobsite["customer_account_id"])
    rows = []
    for contract in store.sorted_rows("contracts"):
        if account is not None and contract["customer_account_id"] != account["id"]:
            continue
        if quote is not None and contract["quote_id"] != quote["id"]:
            continue
        if jobsite is not None and contract["jobsite_id"] != jobsite["id"]:
            continue
        if lifecycle is not None and contract["lifecycle_status"] != lifecycle:
            continue
        if billing is not None and contract["billing_status"] != billing:
            continue
        if identity.is_customer and contract["customer_account_id"] != identity.user_id:
            continue
        rows.append(contract)
    return page(rows, contract_out, limit, offset)


@bp.post("/fence-rentals/contracts/<row_id>/work-orders")
def plan_work_order(row_id):
    authenticate(("DispatchCoordinator",))
    parsed = check_body(json_body(), PLAN_SPEC)
    if parsed["work_order_type"] == "RESET":
        fail("ERR_VALIDATION",
             "A RESET visit is created only through the phase-move capability.")
    contract = lookup("contracts", row_id)
    if parsed["ordered_linear_feet"] > contract["ordered_linear_feet"]:
        fail("ERR_VALIDATION",
             "ordered_linear_feet may not exceed the contract's ordered_linear_feet.")
    if contract["lifecycle_status"] not in ("PENDING_MOBILIZATION", "ACTIVE"):
        fail("ERR_CONTRACT_STATE", "Labor may only be planned on a pending or active contract.")
    order = new_work_order(contract, parsed["work_order_type"], parsed["ordered_linear_feet"],
                           parsed.get("scheduled_start_utc"))
    return object_response(work_order_out(order), 201)


@bp.post("/fence-rentals/contracts/<row_id>/reset-orders")
def order_phase_move(row_id):
    authenticate(("DispatchCoordinator",))
    parsed = check_body(json_body(), RESET_SPEC)
    contract = lookup("contracts", row_id)
    if parsed["ordered_linear_feet"] > contract["ordered_linear_feet"]:
        fail("ERR_VALIDATION",
             "ordered_linear_feet may not exceed the contract's ordered_linear_feet.")
    if parsed["expected_contract_version"] != contract["version"]:               # rung 8
        fail("ERR_STALE_VERSION",
             "expected_contract_version does not match the contract's current version.")
    if contract["lifecycle_status"] not in ("PENDING_MOBILIZATION", "ACTIVE"):   # rung 9
        fail("ERR_CONTRACT_STATE",
             "A phase move may only be ordered on a pending or active contract.")
    jobsite = lookup("jobsites", contract["jobsite_id"])
    phase_to = parsed["phase_to"]
    if phase_to < 1 or phase_to > jobsite["phase_count"]:                        # rung 22
        fail("ERR_INVALID_PHASE_MOVE", "phase_to lies outside the jobsite's phase range.")
    if phase_to == contract["current_phase"]:
        fail("ERR_INVALID_PHASE_MOVE", "The fence already occupies that phase.")

    displaced = None
    for order in store.sorted_rows("work_orders"):
        if order["contract_id"] != contract["id"] or order["work_order_type"] != "RESET":
            continue
        if order["status"] not in ("PLANNED", "SCHEDULED"):
            continue
        order["status"] = "SUPERSEDED"
        order["crew_id"] = None
        store.touch(order)
        displaced = order
    new_order = new_work_order(
        contract, "RESET", parsed["ordered_linear_feet"], parsed.get("scheduled_start_utc"),
        phase_from=contract["current_phase"], phase_to=phase_to,
        predecessor_id=None if displaced is None else displaced["id"],
        relation=None if displaced is None else "SUPERSEDES")
    store.touch(contract)
    return object_response(work_order_out(new_order), 201)


def cancellation_reference_order(contract):
    """PRD 3.9: the contract's first open install visit, deterministically chosen."""
    candidates = []
    for order in store.sorted_rows("work_orders"):
        if order["contract_id"] != contract["id"]:
            continue
        if order["work_order_type"] != "DELIVERY_INSTALL":
            continue
        if order["status"] not in ("PLANNED", "SCHEDULED"):
            continue
        candidates.append(order)
    if not candidates:
        return None
    candidates.sort(key=lambda row: (
        1 if row["scheduled_start_utc"] is None else 0,
        row["scheduled_start_utc"] or row["created_at"],
        row["created_at"],
        row["id"],
    ))
    return candidates[0]


@bp.post("/fence-rentals/contracts/<row_id>/cancel")
def cancel_contract(row_id):
    identity = authenticate(("AccountManager",))
    parsed = check_body(json_body(), {"cancel_reason_code": {"req": True, "type": "string"}})
    contract = lookup("contracts", row_id)
    if contract["lifecycle_status"] != "PENDING_MOBILIZATION":
        fail("ERR_CONTRACT_STATE", "Only a pre-mobilization contract may be cancelled.")

    reference = cancellation_reference_order(contract)
    notice_seconds = None
    if reference is not None and reference["scheduled_start_utc"] is not None:
        notice_seconds = int((reference["scheduled_start_utc"] - store.clock).total_seconds())
    fee = cancellation_fee(contract["contract_type"], contract["monthly_recurring_cents"],
                           contract["install_labor_cents"], notice_seconds)

    for order in store.sorted_rows("work_orders"):
        if order["contract_id"] != contract["id"]:
            continue
        if order["status"] not in ("PLANNED", "SCHEDULED"):
            continue
        release_reservation(order)
        order["crew_id"] = None
        order["status"] = "CANCELLED"
        store.touch(order)

    contract["cancellation_fee_cents"] = fee
    contract["lifecycle_status"] = "CANCELLED"
    store.touch(contract)
    if fee > 0:
        issue_invoice(contract, "CANCELLATION", [new_line("CANCELLATION_FEE", fee)],
                      identity.user_id)
    return object_response(contract_out(contract), 200)


@bp.post("/fence-rentals/contracts/<row_id>/billing-runs")
def run_billing(row_id):
    identity = authenticate(("AccountManager",))
    parsed = check_body(json_body(), BILLING_SPEC)
    # PRD 2.6: "Every window submitted to this API must satisfy end strictly after
    # start; an inverted or zero-length window is rejected with ERR_VALIDATION", and
    # rung 3 of PRD 2.7 lists "when an instant is malformed or a window is inverted"
    # among the shape failures -- so this outranks the rung-16 billing-window checks.
    if parsed["period_end_utc"] <= parsed["period_start_utc"]:                 # rung 3
        fail("ERR_VALIDATION", "period_end_utc must be strictly after period_start_utc.")
    contract = lookup("contracts", row_id)
    if contract["lifecycle_status"] not in ("ACTIVE", "DEMOBILIZING"):
        fail("ERR_CONTRACT_STATE", "Only an active or demobilizing contract may be billed.")

    start = parsed["period_start_utc"]
    end = parsed["period_end_utc"]
    if contract["billing_anchor_utc"] is not None and start < contract["billing_anchor_utc"]:
        fail("ERR_BILLING_PERIOD_INVALID",
             "period_start_utc precedes the contract's billing anchor.")
    if end > store.clock:
        fail("ERR_BILLING_PERIOD_INVALID", "A future period may not be billed.")
    floor = next_billing_floor(contract["id"])
    if floor is not None and start < floor:
        fail("ERR_BILLING_PERIOD_INVALID",
             "period_start_utc overlaps a window already invoiced.")

    raw_days = whole_days(start, end)
    amount = period_charge(contract["contract_type"], contract["monthly_recurring_cents"],
                           raw_days)
    reevaluate_past_due(contract)
    lines = [new_line("RENTAL", amount, None, raw_days)]
    invoice = issue_invoice(contract, "PERIODIC", lines, identity.user_id,
                            period_start=start, period_end=end, billable_days=raw_days,
                            billing_status_at_start=contract["billing_status"])
    contract["billed_through_utc"] = end
    store.touch(contract)
    return object_response(invoice_out(invoice), 201)

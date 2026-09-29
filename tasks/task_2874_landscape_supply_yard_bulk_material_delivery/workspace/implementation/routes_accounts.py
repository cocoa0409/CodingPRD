"""Contractor accounts, job purchase orders and season pre-buy contracts."""
from flask import Blueprint

import calc
import serial
from core import (
    arg, auth, body, contractor_filter, db, fail, new_record, opt_bool,
    pre_scope_account, render_list, req_id, req_int, req_num, req_season_date,
    req_str, require, respond, scope, touch,
)

bp = Blueprint("accounts", __name__)

ACCOUNT_STATUSES = ("ACTIVE", "CREDIT_HOLD")


# --------------------------------------------------------------------------
# Contractor accounts
# --------------------------------------------------------------------------
@bp.post("/contractor-accounts")
def create_account():
    auth("YardAdmin")
    data = body()
    business_name = req_str(data, "business_name")
    credit_limit = req_int(data, "credit_limit_cents", minimum=0)
    po_required = opt_bool(data, "po_required", default=False)
    protection = opt_bool(data, "driveway_protection_required", default=False)
    record = new_record(
        business_name=business_name,
        credit_limit_cents=credit_limit,
        po_required=po_required,
        driveway_protection_required=protection,
        credit_used_cents=0,
        credit_available_cents=credit_limit,
        pallet_deposit_balance_cents=0,
        account_status="ACTIVE",
    )
    db.insert("contractor_accounts", record)
    return respond(serial.contractor_account(record), 201)


@bp.get("/contractor-accounts")
def list_accounts():
    auth("YardAdmin", "CreditManager", "ClaimsAdjuster")
    status = arg("account_status")
    rows = [r for r in db.contractor_accounts.values()
            if status is None or r["account_status"] == status]
    return render_list(rows, serial.contractor_account)


@bp.get("/contractor-accounts/<contractor_account_id>")
def read_account(contractor_account_id):
    ctx = auth("YardAdmin", "CreditManager", "ClaimsAdjuster", "Contractor")
    record = db.get("contractor_accounts", contractor_account_id)
    if record is not None:
        scope(ctx, record["id"])
    require(record, "contractor_accounts")
    return respond(serial.contractor_account(record))


@bp.post("/contractor-accounts/<contractor_account_id>/credit-adjustments")
def adjust_credit(contractor_account_id):
    auth("CreditManager")
    data = body()
    new_limit = req_int(data, "new_credit_limit_cents", minimum=0)
    req_str(data, "memo")
    expected = req_int(data, "expected_contractor_account_version")
    account = require(db.get("contractor_accounts", contractor_account_id),
                      "contractor_accounts")
    if expected != account["version"]:
        fail("ERR_STALE_ACCOUNT_VERSION",
             "Account version is %d." % account["version"])

    account["credit_limit_cents"] = new_limit
    account["credit_available_cents"] = new_limit - int(account["credit_used_cents"])
    calc.evaluate_credit_posture(account, standalone=False)
    touch(account)
    return respond(serial.contractor_account(account))


# --------------------------------------------------------------------------
# Job purchase orders
# --------------------------------------------------------------------------
@bp.post("/job-purchase-orders")
def create_po():
    ctx = auth("Contractor", "YardAdmin")
    data = body()
    pre_scope_account(ctx, data)
    account_id = req_id(data, "contractor_account_id")
    po_number = req_str(data, "po_number")
    job_code = req_str(data, "job_code")
    po_limit = req_int(data, "po_limit_cents", minimum=0, exclusive_min=True)
    require(db.get("contractor_accounts", account_id), "contractor_accounts")

    for existing in db.job_purchase_orders.values():
        if (existing["contractor_account_id"] == account_id
                and existing["po_number"] == po_number):
            fail("ERR_DUPLICATE_PO_NUMBER",
                 "po_number '%s' already exists on this account." % po_number)

    record = new_record(
        contractor_account_id=account_id,
        po_number=po_number,
        job_code=job_code,
        po_limit_cents=po_limit,
        committed_cents=0,
        status="OPEN",
    )
    db.insert("job_purchase_orders", record)
    return respond(serial.job_purchase_order(record), 201)


@bp.get("/job-purchase-orders")
def list_pos():
    ctx = auth("Contractor", "YardAdmin", "CreditManager")
    account_id = arg("contractor_account_id")
    status = arg("status")
    job_code = arg("job_code")
    rows = []
    for record in db.job_purchase_orders.values():
        if account_id is not None and record["contractor_account_id"] != account_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if job_code is not None and record["job_code"] != job_code:
            continue
        rows.append(record)
    rows = contractor_filter(ctx, rows, lambda r: r["contractor_account_id"])
    return render_list(rows, serial.job_purchase_order)


@bp.get("/job-purchase-orders/<job_purchase_order_id>")
def read_po(job_purchase_order_id):
    ctx = auth("Contractor", "YardAdmin", "CreditManager")
    record = db.get("job_purchase_orders", job_purchase_order_id)
    if record is not None:
        scope(ctx, record["contractor_account_id"])
    require(record, "job_purchase_orders")
    return respond(serial.job_purchase_order(record))


@bp.post("/job-purchase-orders/<job_purchase_order_id>/close")
def close_po(job_purchase_order_id):
    ctx = auth("Contractor", "YardAdmin")
    record = db.get("job_purchase_orders", job_purchase_order_id)
    if record is not None:
        scope(ctx, record["contractor_account_id"])
    require(record, "job_purchase_orders")
    if record["status"] != "OPEN":
        fail("ERR_PO_NOT_OPEN", "Purchase order is %s." % record["status"])
    record["status"] = "CLOSED"
    touch(record)
    return respond(serial.job_purchase_order(record))


# --------------------------------------------------------------------------
# Season pre-buy contracts
# --------------------------------------------------------------------------
@bp.post("/prebuy-contracts")
def create_prebuy():
    ctx = auth("Contractor", "YardAdmin")
    data = body()
    pre_scope_account(ctx, data)
    account_id = req_id(data, "contractor_account_id")
    material_id = req_id(data, "material_id")
    locked_price = req_int(data, "locked_price_per_cubic_yard_cents", minimum=0,
                           exclusive_min=True)
    contracted = req_num(data, "contracted_cubic_yards", minimum=0,
                         exclusive_min=True)
    start = req_season_date(data, "season_start_date")
    end = req_season_date(data, "season_end_date")
    if end < start:
        fail("ERR_INVALID_REQUEST",
             "season_end_date must be no earlier than season_start_date.")
    require(db.get("contractor_accounts", account_id), "contractor_accounts")
    require(db.get("materials", material_id), "materials")

    for other in db.prebuy_contracts.values():
        if other["contractor_account_id"] != account_id:
            continue
        if other["material_id"] != material_id:
            continue
        if other["status"] not in ("DRAFT", "ACTIVE"):
            continue
        disjoint = end < other["season_start_date"] or other["season_end_date"] < start
        if not disjoint:
            fail("ERR_PREBUY_SEASON_OVERLAP",
                 "Season overlaps an existing live contract.")

    record = new_record(
        contractor_account_id=account_id,
        material_id=material_id,
        locked_price_per_cubic_yard_cents=locked_price,
        contracted_cubic_yards=contracted,
        season_start_date=start,
        season_end_date=end,
        drawn_cubic_yards=0.0,
        remaining_cubic_yards=contracted,
        status="DRAFT",
    )
    db.insert("prebuy_contracts", record)
    return respond(serial.prebuy_contract(record), 201)


@bp.get("/prebuy-contracts")
def list_prebuys():
    ctx = auth("Contractor", "YardAdmin", "CreditManager")
    account_id = arg("contractor_account_id")
    material_id = arg("material_id")
    status = arg("status")
    rows = []
    for record in db.prebuy_contracts.values():
        if account_id is not None and record["contractor_account_id"] != account_id:
            continue
        if material_id is not None and record["material_id"] != material_id:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    rows = contractor_filter(ctx, rows, lambda r: r["contractor_account_id"])
    return render_list(rows, serial.prebuy_contract)


@bp.get("/prebuy-contracts/<prebuy_contract_id>")
def read_prebuy(prebuy_contract_id):
    ctx = auth("Contractor", "YardAdmin", "CreditManager")
    record = db.get("prebuy_contracts", prebuy_contract_id)
    if record is not None:
        scope(ctx, record["contractor_account_id"])
    require(record, "prebuy_contracts")
    return respond(serial.prebuy_contract(record))


@bp.post("/prebuy-contracts/<prebuy_contract_id>/activate")
def activate_prebuy(prebuy_contract_id):
    auth("YardAdmin")
    record = require(db.get("prebuy_contracts", prebuy_contract_id),
                     "prebuy_contracts")
    if record["status"] != "DRAFT":
        fail("ERR_PREBUY_NOT_DRAFT", "Contract is %s." % record["status"])
    account = db.get("contractor_accounts", record["contractor_account_id"])
    if account is not None and account["account_status"] != "ACTIVE":
        fail("ERR_ACCOUNT_CREDIT_HOLD", "Account is on credit hold.")
    material = db.get("materials", record["material_id"])
    if material is not None and not material["prebuy_eligible"]:
        fail("ERR_MATERIAL_NOT_PREBUY_ELIGIBLE",
             "Material is not eligible for pre-buy contracts.")
    if calc.clock_date() > record["season_end_date"]:
        fail("ERR_PREBUY_OUT_OF_SEASON", "The season has already ended.")
    record["status"] = "ACTIVE"
    touch(record)
    return respond(serial.prebuy_contract(record))

"""Card members, premium fees, the value-fund ledger and lounge entitlement."""

from flask import Blueprint, request

from auth import authenticate, require_owned_by_caller, require_role
from db import STORE
from errors import ERR_INVALID_STATE, ApiError
from names import (
    CARD_PRODUCT_ANNUAL_FEE_CENTS,
    CARD_PRODUCT_MEMBERSHIP_POINTS,
    lounge_tier_for,
)
from paging import filter_arg, paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from services import valuefund
from validation import (
    body_object,
    require_enum,
    require_int,
    require_string,
)

bp = Blueprint("cardmembers", __name__)

CARD_PRODUCTS = ("GREEN", "GOLD", "PLATINUM", "CENTURION")
MEMBER_STATUSES = ("PENDING", "ACTIVE", "DELINQUENT", "CLOSED")
STATEMENT_STATUSES = ("DRAFT", "ASSESSED", "DISBURSED", "VOIDED")
ENTRY_KINDS = ("FEE_ALLOCATION", "FEE_ALLOCATION_REVERSAL", "LOUNGE_PASS_GRANT")

ISSUER = ["NetworkIssuer"]
ISSUER_OR_MEMBER = ["NetworkIssuer", "CardMember"]


# --- Card members ----------------------------------------------------------

@bp.post("/cardmembers")
def create_cardmember():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body = body_object(request.get_json(silent=True) or {}, {"member_name", "card_product"})
    member_name = require_string(body, "member_name")
    card_product = require_enum(body, "card_product", CARD_PRODUCTS)

    with STORE.lock:
        member_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": member_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "member_name": member_name,
            "card_product": card_product,
            "annual_fee_cents": CARD_PRODUCT_ANNUAL_FEE_CENTS[card_product],
            "trailing_lowest_month_spend_cents": 0,
            "reward_points_balance": 0,
            "lounge_access_tier": "NONE",
            "member_status": "PENDING",
        }
        STORE.cardmembers[member_id] = row
    return ok_object(_common.render(row)), 201


@bp.get("/cardmembers/<cardmember_id>")
def get_cardmember(cardmember_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER_OR_MEMBER)
    row = _common.cardmember(cardmember_id)
    if caller.role == "CardMember":
        require_owned_by_caller(caller, row["id"])
    return ok_object(_common.render(row))


@bp.get("/cardmembers")
def list_cardmembers():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    limit, offset = pagination(request.args)
    member_status = filter_arg(request.args, "member_status", MEMBER_STATUSES)
    rows = list(STORE.cardmembers.values())
    if member_status is not None:
        rows = [row for row in rows if row["member_status"] == member_status]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/cardmembers/<cardmember_id>/activate")
def activate_cardmember(cardmember_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.cardmember(cardmember_id)
    with STORE.lock:
        if row["member_status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE)
        row["member_status"] = "ACTIVE"
        row["reward_points_balance"] = (
            row["reward_points_balance"]
            + CARD_PRODUCT_MEMBERSHIP_POINTS[row["card_product"]])
        row["lounge_access_tier"] = lounge_tier_for(
            row["card_product"], row["trailing_lowest_month_spend_cents"], "ACTIVE")
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/cardmembers/<cardmember_id>/set-monthly-spend")
def set_monthly_spend(cardmember_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body = body_object(request.get_json(silent=True) or {},
                       {"trailing_lowest_month_spend_cents"})
    spend = require_int(body, "trailing_lowest_month_spend_cents", minimum=0)
    row = _common.cardmember(cardmember_id)
    with STORE.lock:
        row["trailing_lowest_month_spend_cents"] = spend
        row["lounge_access_tier"] = lounge_tier_for(
            row["card_product"], spend, row["member_status"])
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/cardmembers/<cardmember_id>/grant-lounge-access")
def grant_lounge_access(cardmember_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body = body_object(request.get_json(silent=True) or {}, {"pass_count"})
    pass_count = require_int(body, "pass_count", minimum=0)
    row = _common.cardmember(cardmember_id)
    with STORE.lock:
        valuefund.grant_lounge_pass(STORE, row, pass_count)
        row["lounge_access_tier"] = lounge_tier_for(
            row["card_product"], row["trailing_lowest_month_spend_cents"],
            row["member_status"])
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/cardmembers/<cardmember_id>/mark-delinquent")
def mark_delinquent(cardmember_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.cardmember(cardmember_id)
    with STORE.lock:
        if row["member_status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE)
        row["member_status"] = "DELINQUENT"
        row["lounge_access_tier"] = "NONE"
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/cardmembers/<cardmember_id>/close")
def close_cardmember(cardmember_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.cardmember(cardmember_id)
    with STORE.lock:
        if row["member_status"] != "DELINQUENT":
            raise ApiError(ERR_INVALID_STATE)
        row["member_status"] = "CLOSED"
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


# --- Annual fee statements -------------------------------------------------

@bp.post("/annual-fee-statements")
def create_statement():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body = body_object(
        request.get_json(silent=True) or {},
        {"cardmember_id", "statement_year", "principal_fee_cents",
         "authorised_user_count", "per_user_fee_cents"},
    )
    cardmember_id = require_string(body, "cardmember_id")
    statement_year = require_int(body, "statement_year", minimum=2026)
    principal_fee_cents = require_int(body, "principal_fee_cents", minimum=0)
    authorised_user_count = require_int(body, "authorised_user_count", minimum=0)
    per_user_fee_cents = require_int(body, "per_user_fee_cents", minimum=0)

    _common.cardmember(cardmember_id)
    with STORE.lock:
        statement_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": statement_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "cardmember_id": cardmember_id,
            "statement_year": statement_year,
            "principal_fee_cents": principal_fee_cents,
            "authorised_user_count": authorised_user_count,
            "per_user_fee_cents": per_user_fee_cents,
            "gross_fee_assessed_cents": 0,
            "value_fund_allocation_cents": 0,
            "statement_status": "DRAFT",
        }
        STORE.annual_fee_statements[statement_id] = row
    return ok_object(_common.render(row)), 201


@bp.get("/annual-fee-statements/<statement_id>")
def get_statement(statement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    row = _common.statement(statement_id)
    return ok_object(_common.render(row))


@bp.get("/annual-fee-statements")
def list_statements():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    limit, offset = pagination(request.args)
    cardmember_id = filter_arg(request.args, "cardmember_id")
    statement_status = filter_arg(request.args, "statement_status", STATEMENT_STATUSES)
    rows = list(STORE.annual_fee_statements.values())
    if cardmember_id is not None:
        rows = [row for row in rows if row["cardmember_id"] == cardmember_id]
    if statement_status is not None:
        rows = [row for row in rows if row["statement_status"] == statement_status]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/annual-fee-statements/<statement_id>/assess")
def assess_statement(statement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.statement(statement_id)
    with STORE.lock:
        valuefund.assess(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/annual-fee-statements/<statement_id>/disburse")
def disburse_statement(statement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.statement(statement_id)
    with STORE.lock:
        valuefund.disburse(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/annual-fee-statements/<statement_id>/void")
def void_statement(statement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.statement(statement_id)
    with STORE.lock:
        valuefund.void(STORE, row)
    return ok_object(_common.render(row))


# --- Value-fund ledger -----------------------------------------------------

@bp.get("/value-fund/ledger")
def get_value_fund_ledger():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    limit, offset = pagination(request.args)
    source_statement_id = filter_arg(request.args, "source_statement_id")
    entry_kind = filter_arg(request.args, "entry_kind", ENTRY_KINDS)
    rows = list(STORE.value_fund_ledger_entries.values())
    if source_statement_id is not None:
        rows = [row for row in rows if row["source_statement_id"] == source_statement_id]
    if entry_kind is not None:
        rows = [row for row in rows if row["entry_kind"] == entry_kind]
    rows = sorted(rows, key=lambda row: row["created_seq"])
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.get("/value-fund-ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    row = _common.ledger_entry(entry_id)
    return ok_object(_common.render(row))


@bp.get("/value-fund-ledger-entries")
def list_ledger_entries():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ISSUER)
    limit, offset = pagination(request.args)
    source_statement_id = filter_arg(request.args, "source_statement_id")
    entry_kind = filter_arg(request.args, "entry_kind", ENTRY_KINDS)
    rows = list(STORE.value_fund_ledger_entries.values())
    if source_statement_id is not None:
        rows = [row for row in rows if row["source_statement_id"] == source_statement_id]
    if entry_kind is not None:
        rows = [row for row in rows if row["entry_kind"] == entry_kind]
    rows = sorted(rows, key=lambda row: row["created_seq"])
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)

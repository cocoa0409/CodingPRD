"""ExpenseEntry endpoints (PRD §3.4): the append-only holding-cost ledger."""

from flask import Blueprint

import clock
import errors
import store
from constants import ENTRY_KINDS, EXPENSE_TYPES_ALL, EXPENSE_TYPE_STORAGE_ACCRUAL
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from routes_assets import load_asset
from serialize import ser_expense
from util import (
    get_body,
    req_str,
    req_enum,
    req_int,
    opt_dt,
    parse_pagination,
    sort_and_page,
)

bp = Blueprint("expenses", __name__)

# Legal states that accept ledger postings.
_POSTABLE_STATES = (
    "SEIZED",
    "VALUATION_PENDING",
    "VALUED",
    "DISPOSITION_REVIEW",
    "SALE_AUTHORIZED",
)


@bp.route("/custody/expense-entries", methods=["POST"])
def create_expense_entry():
    user_id, _ = require_roles("AssetCustodian")
    # Tier 3: request shape; STORAGE_ACCRUAL is reserved for system postings.
    data = get_body()
    asset_id = req_str(data, "asset_id")
    entry_kind = req_enum(data, "entry_kind", ENTRY_KINDS)
    expense_type = req_enum(data, "expense_type", EXPENSE_TYPES_ALL)
    if expense_type == EXPENSE_TYPE_STORAGE_ACCRUAL:
        raise errors.invalid_request(
            "expense_type STORAGE_ACCRUAL is reserved for system postings"
        )
    amount_cents = req_int(data, "amount_cents", min_value=1)
    incurred_on = opt_dt(data, "incurred_on")
    if incurred_on is None:
        incurred_on = clock.now()
    # Tier 4: asset must exist.
    asset = load_asset(asset_id)
    # Tier 6: legal-state gate for postings.
    if asset["legal_state"] not in _POSTABLE_STATES:
        raise errors.invalid_state(
            "Expense entries may not be posted while legal_state == %s"
            % asset["legal_state"]
        )
    # Tier 9: the accumulator may never be driven below zero.
    if entry_kind == "COST":
        new_total = asset["accumulated_net_holding_cost_cents"] + amount_cents
    else:  # REVENUE_OFFSET and REVERSAL both subtract.
        new_total = asset["accumulated_net_holding_cost_cents"] - amount_cents
    if new_total < 0:
        raise errors.ApiError(
            errors.ERR_NEGATIVE_HOLDING_COST,
            422,
            "Entry would drive accumulated_net_holding_cost_cents below 0",
        )
    entry = store.new_entity(
        {
            "asset_id": asset["id"],
            "entry_kind": entry_kind,
            "expense_type": expense_type,
            "amount_cents": amount_cents,
            "incurred_on": incurred_on,
            "source": "MANUAL",
            "posted_by_user_id": user_id,
        }
    )
    store.EXPENSES[entry["id"]] = entry
    asset["accumulated_net_holding_cost_cents"] = new_total
    store.touch(asset)
    return ok_object(ser_expense(entry), status=201)


@bp.route("/custody/assets/<asset_id>/expense-entries", methods=["GET"])
def list_asset_expenses(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.expenses_of_asset(asset["id"]), limit, offset)
    return ok_list([ser_expense(e) for e in page], total, limit, offset)

"""Product holding routes."""

from flask import Blueprint

from db import DB
from errors import ERR_HOLDING_HAS_ACTIVE_LOAN, ERR_INVALID_STATE, ApiError
from middleware import (
    as_enum,
    as_int,
    as_string,
    auth,
    query_filter,
    raw_body,
    reject_unknown,
    require_fields,
    require_owner,
)
from response import ok_array, ok_object
from routes.common import fetch, fetch_member, guard_member_view, list_response, mk
from services import calc, recompute, serialize, workflows

BP = Blueprint("holdings", __name__)

PRODUCT_LINES = ("LENDING", "BANKING", "INVESTING", "CAREER")
HOLDING_CREATE_ALLOWED = {"member_id", "product_line", "balance_cents"}


@BP.route("/benefits/holdings", methods=["POST"])
def open_holding():
    auth(("PlatformAdmin", "BenefitsAdmin"))
    payload = raw_body()
    reject_unknown(payload, HOLDING_CREATE_ALLOWED)
    require_fields(payload, ("member_id", "product_line"))
    member_id = as_string(payload, "member_id")
    fetch_member(member_id)
    product_line = as_enum(payload, "product_line", PRODUCT_LINES)
    balance_cents = as_int(payload, "balance_cents", required=False, default=0)
    holding = mk(
        "holdings",
        member_id=member_id,
        product_line=product_line,
        adoption_status="PENDING",
        adopted_at=None,
        closed_at=None,
        balance_cents=balance_cents,
        deposit_rate_eligible=False,
        cross_sell_eligible=False,
        reunderwriting_permitted=False,
    )
    recompute.recompute_member(member_id)
    return ok_object(serialize.holding(holding)), 201


@BP.route("/benefits/holdings", methods=["GET"])
def list_holdings():
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer", "Underwriter"))
    items = list(DB.holdings.values())
    filters = {
        "member_id": "member_id",
        "product_line": "product_line",
        "adoption_status": "adoption_status",
    }
    return list_response(items, serialize.holding, filters)


@BP.route("/benefits/holdings/<holding_id>", methods=["GET"])
def get_holding(holding_id):
    user_id, role = auth(
        ("Member", "PlatformAdmin", "BenefitsAdmin", "Underwriter", "ComplianceOfficer")
    )
    holding = fetch("holdings", holding_id)
    guard_member_view(user_id, role, holding["member_id"])
    return ok_object(serialize.holding(holding))


@BP.route("/benefits/holdings/<holding_id>/adopt", methods=["POST"])
def adopt_holding(holding_id):
    user_id, role = auth(("Member",))
    del role
    holding = fetch("holdings", holding_id)
    require_owner(user_id, holding["member_id"])
    if holding["adoption_status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE)
    workflows.adopt_holding(holding)
    recompute.recompute_holding(holding["id"], bump=False)
    recompute.materialise_live_applications(holding["member_id"])
    recompute.reprice_member_loans(holding["member_id"])
    recompute.refresh_member_derived(holding["member_id"])
    return ok_object(serialize.holding(holding))


@BP.route("/benefits/holdings/<holding_id>/suspend", methods=["POST"])
def suspend_holding(holding_id):
    auth(("PlatformAdmin",))
    holding = fetch("holdings", holding_id)
    if holding["adoption_status"] != "ADOPTED":
        raise ApiError(ERR_INVALID_STATE)
    workflows.suspend_holding(holding)
    recompute.recompute_holding(holding["id"], bump=False)
    recompute.reprice_member_loans(holding["member_id"])
    recompute.refresh_member_derived(holding["member_id"])
    return ok_object(serialize.holding(holding))


@BP.route("/benefits/holdings/<holding_id>/close", methods=["POST"])
def close_holding(holding_id):
    user_id, role = auth(("Member",))
    del role
    holding = fetch("holdings", holding_id)
    require_owner(user_id, holding["member_id"])
    if holding["adoption_status"] not in ("ADOPTED", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE)
    if int(holding.get("balance_cents") or 0) != 0:
        raise ApiError(ERR_INVALID_STATE)
    for loan in DB.loan_accounts.values():
        if loan["holding_id"] != holding_id:
            continue
        raise ApiError(ERR_HOLDING_HAS_ACTIVE_LOAN)
    workflows.close_holding(holding)
    recompute.recompute_holding(holding["id"], bump=False)
    recompute.reprice_member_loans(holding["member_id"])
    recompute.refresh_member_derived(holding["member_id"])
    return ok_object(serialize.holding(holding))
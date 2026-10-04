"""SaleEvent endpoints (PRD §3.6): scheduling with slot guards, close, and
settlement running the tiered auction fee plus the lien-first proceeds
waterfall into the case's forfeiture-fund pool.
"""

from flask import Blueprint

import calc
import clock
import errors
import store
from constants import SALE_METHODS, LIEN_KINDS, COST_REIMBURSEMENT_PAYEE
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from routes_assets import load_asset
from serialize import ser_sale
from util import get_body, req_str, req_enum, req_int, req_dt, parse_pagination, sort_and_page

bp = Blueprint("sales", __name__)

_ACTIVE_SALE_STATES = ("OPEN_FOR_BIDS", "CLOSED_PENDING_SETTLEMENT")


@bp.route("/custody/sale-events", methods=["POST"])
def create_sale_event():
    require_roles("AuctionCoordinator")
    # Tier 3: request shape (half-open slot: end strictly after start).
    data = get_body()
    asset_id = req_str(data, "asset_id")
    sale_method = req_enum(data, "sale_method", SALE_METHODS)
    auctioneer_ref = req_str(data, "auctioneer_ref")
    slot_start = req_dt(data, "slot_start")
    slot_end = req_dt(data, "slot_end")
    if slot_end <= slot_start:
        raise errors.invalid_request("slot_end must be later than slot_start")
    reserve_price_cents = req_int(data, "reserve_price_cents", min_value=0)
    # Tier 4: asset must exist.
    asset = load_asset(asset_id)
    # Tier 6: the asset must stand at SALE_AUTHORIZED.
    if asset["legal_state"] != "SALE_AUTHORIZED":
        raise errors.invalid_state(
            "Sale events require legal_state == SALE_AUTHORIZED (legal_state=%s)"
            % asset["legal_state"]
        )
    # Tier 8: at most one active sale per asset.
    for other in store.sales_of_asset(asset["id"]):
        if other["status"] in _ACTIVE_SALE_STATES:
            raise errors.ApiError(
                errors.ERR_SALE_ALREADY_ACTIVE,
                409,
                "Asset already has a sale event in %s" % other["status"],
            )
    # Tier 8: half-open slot non-overlap per auctioneer (adjacency is not a
    # conflict); CANCELLED events free their slot.
    for other in store.SALES.values():
        if other["auctioneer_ref"] != auctioneer_ref:
            continue
        if other["status"] == "CANCELLED":
            continue
        if slot_start < other["slot_end"] and other["slot_start"] < slot_end:
            raise errors.ApiError(
                errors.ERR_AUCTION_SLOT_CONFLICT,
                409,
                "Slot overlaps another non-CANCELLED slot for auctioneer %s"
                % auctioneer_ref,
            )
    # Tier 9: reserve must not exceed the appraised value.
    appraised = asset["appraised_value_cents"]
    if appraised is None or reserve_price_cents > appraised:
        raise errors.ApiError(
            errors.ERR_RESERVE_ABOVE_VALUE,
            422,
            "reserve_price_cents exceeds the asset's appraised value",
        )
    # Tier 10: the slot may not open in the past.
    if slot_start < clock.now():
        raise errors.ApiError(
            errors.ERR_SLOT_IN_PAST,
            409,
            "slot_start lies before the current logical clock time",
        )
    sale = store.new_entity(
        {
            "asset_id": asset["id"],
            "sale_method": sale_method,
            "auctioneer_ref": auctioneer_ref,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "reserve_price_cents": reserve_price_cents,
            "winning_bid_cents": None,
            "gross_proceeds_cents": None,
            "auction_fee_cents": None,
            "net_proceeds_cents": None,
            "status": "OPEN_FOR_BIDS",
        }
    )
    store.SALES[sale["id"]] = sale
    return ok_object(ser_sale(sale), status=201)


@bp.route("/custody/sale-events/<sale_id>/close", methods=["POST"])
def close_sale_event(sale_id):
    require_roles("AuctionCoordinator")
    data = get_body()
    winning_bid_cents = req_int(data, "winning_bid_cents", min_value=0)
    sale = store.SALES.get(sale_id)
    if sale is None:
        raise errors.not_found("SaleEvent not found: %s" % sale_id)
    # Tier 6: only an OPEN_FOR_BIDS event can close.
    if sale["status"] != "OPEN_FOR_BIDS":
        raise errors.invalid_state(
            "Only an OPEN_FOR_BIDS sale event can be closed (status=%s)"
            % sale["status"]
        )
    sale["winning_bid_cents"] = winning_bid_cents
    if winning_bid_cents >= sale["reserve_price_cents"]:
        sale["status"] = "CLOSED_PENDING_SETTLEMENT"
        sale["gross_proceeds_cents"] = winning_bid_cents
    else:
        # Below reserve: NO_SALE; the asset stays SALE_AUTHORIZED.
        sale["status"] = "NO_SALE"
        sale["gross_proceeds_cents"] = 0
    store.touch(sale)
    return ok_object(ser_sale(sale))


@bp.route("/custody/sale-events/<sale_id>/settle", methods=["POST"])
def settle_sale_event(sale_id):
    require_roles("FundAdministrator")
    get_body()
    sale = store.SALES.get(sale_id)
    if sale is None:
        raise errors.not_found("SaleEvent not found: %s" % sale_id)
    # Tier 6: only a CLOSED_PENDING_SETTLEMENT event can settle.
    if sale["status"] != "CLOSED_PENDING_SETTLEMENT":
        raise errors.invalid_state(
            "Only a CLOSED_PENDING_SETTLEMENT sale event can be settled "
            "(status=%s)" % sale["status"]
        )
    asset = store.ASSETS.get(sale["asset_id"])
    case = store.CASES.get(asset["seizure_case_id"]) if asset else None

    # --- auction_fee_schedule: tiered marginal fee, per-bracket RHU.
    gross = sale["gross_proceeds_cents"]
    fee = calc.auction_fee_cents(gross)
    net = gross - fee
    sale["auction_fee_cents"] = fee
    sale["net_proceeds_cents"] = net

    # --- proceeds_waterfall, bucket 1: VERIFIED liens in priority order.
    remaining = net
    lien_paid_total = 0
    liens = [
        t
        for t in store.interests_of_asset(asset["id"])
        if t["kind"] in LIEN_KINDS and t["status"] == "VERIFIED"
    ]
    liens.sort(key=lambda t: (t["priority_position"], t["created_at"], t["_seq"]))
    for lien in liens:
        pay = min(lien["amount_cents"], remaining)
        if pay <= 0:
            continue
        distribution = store.new_entity(
            {
                "seizure_case_id": case["id"],
                "distribution_kind": "LIEN_PAYMENT",
                "payee_ref": lien["lienholder_name"],
                "amount_cents": pay,
                "usage_restriction": None,
                "status": "PAID",
                "created_by_user_id": "system",
                "approved_by_user_id": "system",
            }
        )
        store.DISTRIBUTIONS[distribution["id"]] = distribution
        lien["status"] = "SATISFIED"
        lien["satisfied_amount_cents"] = pay
        store.touch(lien)
        lien_paid_total += pay
        remaining -= pay

    # --- bucket 2: holding-cost reimbursement for this asset.
    cost_reimb = min(asset["accumulated_net_holding_cost_cents"], remaining)
    if cost_reimb > 0:
        distribution = store.new_entity(
            {
                "seizure_case_id": case["id"],
                "distribution_kind": "COST_REIMBURSEMENT",
                "payee_ref": COST_REIMBURSEMENT_PAYEE,
                "amount_cents": cost_reimb,
                "usage_restriction": None,
                "status": "PAID",
                "created_by_user_id": "system",
                "approved_by_user_id": "system",
            }
        )
        store.DISTRIBUTIONS[distribution["id"]] = distribution
        remaining -= cost_reimb

    # --- bucket 3: remainder to the case sharing pool; recompute accumulators.
    case["gross_proceeds_cents"] += gross
    case["auction_fees_cents"] += fee
    case["lien_payments_cents"] += lien_paid_total
    case["cost_reimbursements_cents"] += cost_reimb
    case["sharing_pool_gross_basis_cents"] += gross - fee
    case["sharing_pool_net_basis_cents"] += remaining
    store.rederive_available(case)
    store.touch(case)

    # --- close out the asset and the event.
    asset["legal_state"] = "SOLD"
    asset["custody_state"] = "TRANSFERRED_OUT"
    store.touch(asset)
    sale["status"] = "SETTLED"
    store.touch(sale)
    return ok_object(ser_sale(sale))


@bp.route("/custody/assets/<asset_id>/sale-events", methods=["GET"])
def list_asset_sales(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.sales_of_asset(asset["id"]), limit, offset)
    return ok_list([ser_sale(s) for s in page], total, limit, offset)

"""Seller response and the repair-allowance negotiation cycle (PRD 3.6)."""
from flask import Blueprint

import calc
import services as S
import store as C
from authz import ALL_ROLES, authenticate
from envelope import created, obj, unpaginated
from errors import fail
from store import store
from util import add_hours, iso, parse_dt, public, public_list
from validators import json_body, present, req_enum, req_int, req_str

bp = Blueprint("negotiation", __name__)


@bp.route("/arbitration/cases/<case_id>/seller-response", methods=["POST"])
def seller_response(case_id):
    role, user_id = authenticate(["SellerRep"])
    body = json_body()
    response_type = req_enum(body, "response_type", C.CLIENT_RESPONSE_TYPES)
    response_note = req_str(body, "response_note", 1, 500)
    offer = 0
    if response_type == "OFFER_REPAIR_ALLOWANCE":
        offer = req_int(body, "seller_offer_cents", 0)
        if offer <= 0:
            fail("ERR_INVALID_REQUEST",
                 "Field 'seller_offer_cents' must be greater than 0 for an allowance offer.")
    elif present(body, "seller_offer_cents"):
        req_int(body, "seller_offer_cents", 0)

    case = S.get_case(case_id)
    sale = S.get_sale(case["sale_id"])
    if sale["seller_id"] != user_id:
        fail("ERR_NOT_SALE_SELLER")
    if case["status"] not in ("UNDER_REVIEW", "COUNTERED"):
        fail("ERR_INVALID_CASE_STATE")
    if S.active_cooldown_round(case) is not None:
        fail("ERR_ROUND_COOLDOWN_ACTIVE")
    policy = S.get_policy(case["policy_id"])
    if response_type == "OFFER_REPAIR_ALLOWANCE":
        if offer > calc.allowance_cap_cents(sale, policy):
            fail("ERR_ALLOWANCE_EXCEEDS_CAP")
        row = S.create_round(case, response_type, response_note, offer, "OPEN")
        S.supersede_rounds(case, ("COUNTERED",))
        case["status"] = "NEGOTIATION"
    else:
        row = S.create_round(case, response_type, response_note, 0, "CLOSED")
        if response_type == "ACCEPT_UNWIND":
            case["seller_conceded"] = True
        case["status"] = "ARBITRATOR_REVIEW"
    S.touch(case)
    return created(public(row))


@bp.route("/arbitration/cases/<case_id>/negotiation-rounds", methods=["GET"])
def list_rounds(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(public_list(S.children("rounds", "case_id", case["id"])))


@bp.route("/arbitration/cases/<case_id>/negotiation-rounds/<round_id>/counter",
          methods=["POST"])
def counter_round(case_id, round_id):
    role, user_id = authenticate(["BuyerRep"])
    body = json_body()
    demand = req_int(body, "buyer_demand_cents", 0)
    counter_note = req_str(body, "counter_note")
    case = S.get_case(case_id)
    round_row = S.get_round(case, round_id)
    if case["claimant_buyer_id"] != user_id:
        fail("ERR_NOT_CASE_OWNER")
    if case["status"] != "NEGOTIATION":
        fail("ERR_INVALID_CASE_STATE")
    if round_row["status"] != "OPEN":
        fail("ERR_INVALID_ROUND_STATE")
    now = store.now()
    deadline = parse_dt(round_row["response_deadline_utc"])
    if deadline is not None and now > deadline:
        fail("ERR_ROUND_EXPIRED")
    round_row["status"] = "COUNTERED"
    round_row["countered_at_utc"] = iso(now)
    round_row["cooldown_until_utc"] = iso(add_hours(now, C.ROUND_COOLDOWN_HOURS))
    round_row["buyer_demand_cents"] = demand
    round_row["counter_note"] = counter_note
    S.touch(round_row)
    case["status"] = "COUNTERED"
    S.touch(case)
    return obj(public(round_row))


@bp.route("/arbitration/cases/<case_id>/negotiation-rounds/<round_id>/accept",
          methods=["POST"])
def accept_round(case_id, round_id):
    role, user_id = authenticate(["BuyerRep"])
    case = S.get_case(case_id)
    round_row = S.get_round(case, round_id)
    if case["claimant_buyer_id"] != user_id:
        fail("ERR_NOT_CASE_OWNER")
    if case["status"] != "NEGOTIATION":
        fail("ERR_INVALID_CASE_STATE")
    if round_row["status"] != "OPEN":
        fail("ERR_INVALID_ROUND_STATE")
    deadline = parse_dt(round_row["response_deadline_utc"])
    if deadline is not None and store.now() > deadline:
        fail("ERR_ROUND_EXPIRED")
    sale = S.get_sale(case["sale_id"])
    buyer = S.get_buyer(case["claimant_buyer_id"])
    seller = S.get_seller(sale["seller_id"])
    policy = S.get_policy(case["policy_id"])
    decision = S.resolve_negotiated_accept(case, sale, buyer, seller, policy, round_row)
    return created(public(decision))

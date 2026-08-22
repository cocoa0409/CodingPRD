"""Offers, the counter/revise loop, and settlement net sheets (PRD §3.5, §3.8)."""
from flask import Blueprint

import calc
import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, success
from errors import fail
from serializers import net_sheet_out, offer_out

bp = Blueprint("offers", __name__)

OFFER_READ_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_LISTING_AGENT,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_PLATFORM_ADMIN,
)
NET_SHEET_READ_ROLES = (K.ROLE_NEGOTIATOR, K.ROLE_SERVICER_ANALYST, K.ROLE_PLATFORM_ADMIN)


@bp.post("/short-sale/cases/<case_id>/offers")
def create_offer(case_id):
    require(K.ROLE_LISTING_AGENT)
    case = S.need_case(case_id)
    data = V.body()
    offer = {
        "id": db.new_id(),
        "case_id": case["id"],
        "buyer_name": V.req_string(data, "buyer_name"),
        "buyer_financing": V.req_enum(data, "buyer_financing", K.BUYER_FINANCING),
        "offer_price_cents": V.req_int(data, "offer_price_cents", minimum=1),
        "earnest_money_cents": V.req_int(data, "earnest_money_cents", minimum=0),
        "requested_closing_days": V.req_int(data, "requested_closing_days", minimum=1),
        "round_index": 1,
        "servicer_counter_price_cents": None,
        "submitted_at": None,
        "status": "DRAFT",
    }
    S.require_case_actionable(case)
    db.insert("offers", offer)
    return created(offer_out(offer))


@bp.get("/short-sale/offers/<offer_id>")
def get_offer(offer_id):
    require(*OFFER_READ_ROLES)
    offer = S.need_offer(offer_id)
    return success(offer_out(offer))


@bp.get("/short-sale/cases/<case_id>/offers")
def list_case_offers(case_id):
    require(*OFFER_READ_ROLES)
    case = S.need_case(case_id)
    status = enum_filter("status", K.OFFER_STATUSES)
    rows = S.case_offers(case["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, offer_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/offers/<offer_id>/submit")
def submit_offer(offer_id):
    require(K.ROLE_NEGOTIATOR)
    offer = S.need_offer(offer_id)
    V.body()
    case = db.get("cases", offer["case_id"])

    # rung 9 — state admissibility
    if offer["status"] not in ("DRAFT", "REVISED"):
        fail("ERR_OFFER_NOT_ACTIONABLE", "An offer in %s may not be submitted." % offer["status"])
    from_state = offer["status"]

    # rung 18 — hardship accepted
    package = S.case_package(case["id"])
    if package is None or package["status"] != "ACCEPTED":
        fail("ERR_HARDSHIP_NOT_ACCEPTED", "The case's hardship package is not accepted.")

    # rung 22 — marketing period
    listing = S.controlling_listing(case["id"])
    if listing is None or S.days_on_market(listing) < K.MIN_MARKETING_DAYS:
        fail(
            "ERR_MARKETING_PERIOD_NOT_MET",
            "The case has no controlling listing, or it has not been marketed long enough.",
        )

    # rung 23 — outstanding price reduction
    if case["price_reduction_required"]:
        fail("ERR_PRICE_REDUCTION_REQUIRED", "A price reduction is outstanding on this case.")

    # rung 24 — negotiation round budget
    if from_state == "REVISED" and offer["round_index"] + 1 > K.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "The negotiation round budget is exhausted.")

    offer["status"] = "SUBMITTED"
    offer["submitted_at"] = db.now()
    if from_state == "REVISED":
        offer["round_index"] += 1

    if listing["marketing_status"] == "ACTIVE":
        listing["marketing_status"] = "UNDER_CONTRACT"

    if case["negotiation_status"] in ("MARKETED", "RENEGOTIATION"):
        case["negotiation_status"] = "OFFER_UNDER_REVIEW"

    return success(offer_out(offer))


@bp.post("/short-sale/offers/<offer_id>/servicer-decision")
def servicer_decision(offer_id):
    require(K.ROLE_SERVICER_ANALYST)
    offer = S.need_offer(offer_id)
    data = V.body()
    outcome = V.req_enum(data, "outcome", K.SERVICER_DECISION_OUTCOMES)
    V.opt_string(data, "note")
    counter_price = None
    if outcome == "COUNTER":
        counter_price = V.req_int(data, "counter_price_cents", minimum=1)

    case = db.get("cases", offer["case_id"])

    # rung 9 — state admissibility
    if offer["status"] != "SUBMITTED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "Only a SUBMITTED offer may be answered.")

    if outcome == "COUNTER":
        offer["status"] = "COUNTERED"
        offer["servicer_counter_price_cents"] = counter_price
    else:
        S.cascade_b_offer_rejected(case, offer)

    return success(offer_out(offer))


@bp.post("/short-sale/offers/<offer_id>/revise")
def revise_offer(offer_id):
    require(K.ROLE_LISTING_AGENT)
    offer = S.need_offer(offer_id)
    data = V.body()
    new_price = V.req_int(data, "offer_price_cents", minimum=1)
    new_earnest = V.opt_int(data, "earnest_money_cents", minimum=0)

    # rung 9 — state admissibility
    if offer["status"] != "COUNTERED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "Only a COUNTERED offer may be revised.")

    offer["status"] = "REVISED"
    offer["offer_price_cents"] = new_price
    if new_earnest is not None:
        offer["earnest_money_cents"] = new_earnest

    # every CURRENT sheet on this offer, of either variant, goes STALE
    S.stale_offer_sheets(offer["id"])

    return success(offer_out(offer))


# ---------------------------------------------------------------------------
# net sheets
# ---------------------------------------------------------------------------
@bp.post("/short-sale/offers/<offer_id>/net-sheets")
def create_net_sheet(offer_id):
    user_id = require(K.ROLE_NEGOTIATOR)
    offer = S.need_offer(offer_id)
    data = V.body()

    # rung 7 — request shape
    variant = V.req_enum(data, "variant", K.NET_SHEET_VARIANTS)
    title_escrow_cents = V.req_int(data, "title_escrow_cents", minimum=0)
    property_tax_arrears_cents = V.req_int(data, "property_tax_arrears_cents", minimum=0)
    hoa_arrears_cents = V.req_int(data, "hoa_arrears_cents", minimum=0)
    expected_offer_version = V.req_version(data, "expected_offer_version")

    # rung 8 — optimistic concurrency on the parent Offer
    if expected_offer_version != offer["version"]:
        fail("ERR_STALE_OFFER_VERSION", "The offer has moved since it was read.")

    case = db.get("cases", offer["case_id"])

    # rung 22 — the sheet needs the controlling listing's commission rate
    listing = S.controlling_listing(case["id"])
    if listing is None:
        fail("ERR_MARKETING_PERIOD_NOT_MET", "The case has no controlling listing.")

    computed = calc.net_sheet(
        variant,
        offer["offer_price_cents"],
        listing["commission_pct"],
        title_escrow_cents,
        property_tax_arrears_cents,
        hoa_arrears_cents,
        S.junior_payoff_for_variant(case["id"], variant),
        S.mi_credit_cents(case["id"]),
    )

    # a new sheet supersedes the prior CURRENT sheet OF THE SAME VARIANT
    for prior in S.offer_net_sheets(offer["id"]):
        if prior["variant"] == variant and prior["status"] == "CURRENT":
            prior["status"] = "SUPERSEDED"

    sheet = {
        "id": db.new_id(),
        "offer_id": offer["id"],
        "variant": variant,
        "title_escrow_cents": title_escrow_cents,
        "property_tax_arrears_cents": property_tax_arrears_cents,
        "hoa_arrears_cents": hoa_arrears_cents,
        "prepared_by_user_id": user_id,
        "status": "CURRENT",
    }
    sheet.update(computed)
    db.insert("net_sheets", sheet)

    # preparation increments the parent offer's version by 1
    db.force_touch("offers", offer["id"])

    return created(net_sheet_out(sheet))


@bp.get("/short-sale/offers/<offer_id>/net-sheets")
def list_net_sheets(offer_id):
    require(*NET_SHEET_READ_ROLES)
    offer = S.need_offer(offer_id)
    variant = enum_filter("variant", K.NET_SHEET_VARIANTS)
    status = enum_filter("status", K.NET_SHEET_STATUSES)
    rows = S.offer_net_sheets(offer["id"])
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # newest first, by created_at descending
    return collection(rows, net_sheet_out, sort_key=lambda r: r["_seq"], reverse=True)

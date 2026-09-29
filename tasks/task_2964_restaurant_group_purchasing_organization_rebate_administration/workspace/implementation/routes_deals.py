"""Manufacturer deals, contracted items and rate-card governance (PRD §3.2)."""

from flask import Blueprint

from authz import endpoint, resolve
from envelope import created, ok
from errors import ApiError
from money import BPS_DENOMINATOR
from pageutil import paged
from routes_reference import _filtered
from serializers import dump
from shapes import (Array, Bool, Date, Enum, Int, Str, UPPER_CODE_RE,
                    parse_body)
from store import add_days, db, new_record, touch
from svc_common import (cards_of_item, deal_of_item, items_of_deal,
                        recompute_deal_item_count,
                        recompute_item_approved_card_count)

RATE_TYPES = ("PER_CASE", "PERCENT_OF_SPEND", "TIERED_VOLUME")

DEAL_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "ManufacturerRep")
ITEM_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "ManufacturerRep",
              "DistributorFeed")


bp = Blueprint("deals", __name__)


def _require_deal_open(deal):
    """Ladder priority 14 - the deal must be DRAFT or ACTIVE."""
    if deal["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_DEAL_NOT_OPEN_FOR_CHANGES")


# --------------------------------------------------------------------------
# manufacturer deals
# --------------------------------------------------------------------------

@bp.post("/manufacturer-deals")
@endpoint("GpoAdmin")
def create_deal(caller):
    body = parse_body([
        Str("manufacturer_name", 1, 200),
        Str("deal_code", 3, 30),
        Date("effective_from"),
        Date("effective_to"),
        Int("required_purchase_window_days", 1, None),
    ])
    # priority 22 - inclusive bounds, end not before start
    if body["effective_to"] < body["effective_from"]:
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")
    # priority 31 - deal_code unused
    for deal in db.deals.values():
        if deal["deal_code"] == body["deal_code"]:
            raise ApiError("ERR_DUPLICATE_DEAL_CODE")

    rec = new_record("ManufacturerDeal", {
        "manufacturer_name": body["manufacturer_name"],
        "deal_code": body["deal_code"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "required_purchase_window_days": body["required_purchase_window_days"],
        "status": "DRAFT",
        "contracted_item_count": 0,
        "last_purchase_date": None,
    })
    db.deals[rec["id"]] = rec
    return created(dump(rec))


@bp.get("/manufacturer-deals/<deal_id>")
@endpoint(*DEAL_ROLES)
def get_deal(caller, deal_id):
    return ok(dump(resolve("deal", deal_id)))


@bp.get("/manufacturer-deals")
@endpoint(*DEAL_ROLES)
def list_deals(caller):
    return paged(_filtered(db.deals.values(),
                           [("status", "status"), ("deal_code", "deal_code")]))


@bp.post("/manufacturer-deals/<deal_id>/activate")
@endpoint("GpoAdmin")
def activate_deal(caller, deal_id):
    deal = resolve("deal", deal_id)
    if deal["status"] != "DRAFT":                     # priority 11
        raise ApiError("ERR_INVALID_STATE")
    # priority 34 - at least one ACTIVE item carrying an APPROVED card
    priced = [i for i in items_of_deal(deal)
              if i["status"] == "ACTIVE" and i["approved_rate_card_count"] >= 1]
    if not priced:
        raise ApiError("ERR_DEAL_HAS_NO_APPROVED_RATES")

    deal["status"] = "ACTIVE"
    deal["contracted_item_count"] = len(
        [i for i in items_of_deal(deal) if i["status"] == "ACTIVE"])
    touch(deal)
    return ok(dump(deal))


@bp.post("/manufacturer-deals/<deal_id>/suspend")
@endpoint("GpoAdmin")
def suspend_deal(caller, deal_id):
    deal = resolve("deal", deal_id)
    if deal["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    # Suspension does not touch the deal's items -- they stay ACTIVE.
    deal["status"] = "SUSPENDED"
    touch(deal)
    return ok(dump(deal))


@bp.post("/manufacturer-deals/<deal_id>/resume")
@endpoint("GpoAdmin")
def resume_deal(caller, deal_id):
    deal = resolve("deal", deal_id)
    if deal["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    deal["status"] = "ACTIVE"
    touch(deal)
    return ok(dump(deal))


# --------------------------------------------------------------------------
# contracted items
# --------------------------------------------------------------------------

@bp.post("/contracted-items")
@endpoint("GpoAdmin")
def create_item(caller):
    body = parse_body([
        Str("deal_id"),
        Str("manufacturer_sku", 1, 40),
        Str("normalized_item_key", 1, 60, UPPER_CODE_RE),
        Int("pack_size", 1, None),
        Int("baseline_unit_cost_cents", 1, None),
        Int("contract_unit_cost_cents", 1, None),
    ])
    deal = resolve("deal", body["deal_id"])   # priority 9
    _require_deal_open(deal)                  # priority 14
    # priority 32 - manufacturer_sku unused within the same deal
    for item in items_of_deal(deal):
        if item["manufacturer_sku"] == body["manufacturer_sku"]:
            raise ApiError("ERR_DUPLICATE_ITEM_SKU")

    rec = new_record("ContractedItem", {
        "deal_id": body["deal_id"],
        "manufacturer_sku": body["manufacturer_sku"],
        "normalized_item_key": body["normalized_item_key"],
        "pack_size": body["pack_size"],
        "baseline_unit_cost_cents": body["baseline_unit_cost_cents"],
        "contract_unit_cost_cents": body["contract_unit_cost_cents"],
        "status": "ACTIVE",
        "approved_rate_card_count": 0,
    })
    db.items[rec["id"]] = rec
    recompute_deal_item_count(deal)
    return created(dump(rec))


@bp.get("/contracted-items/<item_id>")
@endpoint(*ITEM_ROLES)
def get_item(caller, item_id):
    return ok(dump(resolve("item", item_id)))


@bp.get("/contracted-items")
@endpoint(*ITEM_ROLES)
def list_items(caller):
    records = _filtered(db.items.values(),
                        [("deal_id", "deal_id"),
                         ("normalized_item_key", "normalized_item_key"),
                         ("status", "status")])
    return paged(records)


# --------------------------------------------------------------------------
# rate cards
# --------------------------------------------------------------------------

def _shape_bad():
    raise ApiError("ERR_RATE_CARD_SHAPE_INVALID")


def _validate_rate_shape(body):
    """Ladder priority 28 - rate fields must match rate_type exactly."""
    rate_type = body["rate_type"]
    flat = body["flat_rate_cents_per_case"]
    percent = body["percent_bps"]
    breaks = body["tier_breaks"]

    if rate_type == "PER_CASE":
        if flat is None or percent is not None or breaks is not None:
            _shape_bad()
        if flat < 1:
            _shape_bad()
    elif rate_type == "PERCENT_OF_SPEND":
        if percent is None or flat is not None or breaks is not None:
            _shape_bad()
        if percent < 1 or percent > BPS_DENOMINATOR:
            _shape_bad()
    else:  # TIERED_VOLUME
        if breaks is None or flat is not None or percent is not None:
            _shape_bad()
        if len(breaks) < 2:
            _shape_bad()
        previous = None
        for entry in breaks:
            if not isinstance(entry, dict):
                _shape_bad()
            if set(entry.keys()) != set(("min_cases", "rate_cents_per_case")):
                _shape_bad()
            min_cases = entry["min_cases"]
            rate = entry["rate_cents_per_case"]
            if isinstance(min_cases, bool) or not isinstance(min_cases, int):
                _shape_bad()
            if isinstance(rate, bool) or not isinstance(rate, int):
                _shape_bad()
            if rate < 1:
                _shape_bad()
            if previous is None:
                if min_cases != 0:      # the first entry's threshold must be 0
                    _shape_bad()
            elif min_cases <= previous:  # thresholds must strictly increase
                _shape_bad()
            previous = min_cases


@bp.post("/rate-cards")
@endpoint("GpoAdmin")
def create_rate_card(caller):
    body = parse_body([
        Str("contracted_item_id"),
        Int("expected_contracted_item_version"),
        Enum("rate_type", RATE_TYPES),
        Int("flat_rate_cents_per_case", required=False),
        Int("percent_bps", required=False),
        Array("tier_breaks", required=False),
        Date("effective_from"),
        Date("effective_to"),
        Bool("supersede", required=False),
    ])
    item = resolve("item", body["contracted_item_id"])          # priority 9
    if body["expected_contracted_item_version"] != item["version"]:  # priority 10
        raise ApiError("ERR_STALE_PARENT_VERSION")
    deal = deal_of_item(item)
    _require_deal_open(deal)                                    # priority 14

    supersede = bool(body["supersede"])
    incumbent = None
    if not supersede:
        # priority 20 - closed-interval overlap: ranges that merely touch DO overlap
        for card in cards_of_item(item):
            if card["status"] not in ("PROPOSED", "APPROVED"):
                continue
            if (body["effective_from"] <= card["effective_to"]
                    and card["effective_from"] <= body["effective_to"]):
                raise ApiError("ERR_RATE_CARD_PERIOD_OVERLAP")
    else:
        # priority 21 - exactly one APPROVED card ending on or after the new start
        candidates = [c for c in cards_of_item(item)
                      if c["status"] == "APPROVED"
                      and c["effective_to"] >= body["effective_from"]]
        if len(candidates) != 1:
            raise ApiError("ERR_NO_INCUMBENT_RATE_CARD")
        incumbent = candidates[0]

    # priority 22 - inclusive range, end not before start
    if body["effective_to"] < body["effective_from"]:
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    _validate_rate_shape(body)                                  # priority 28

    if incumbent is not None:
        incumbent["effective_to"] = add_days(body["effective_from"], -1)
        incumbent["status"] = "SUPERSEDED"
        touch(incumbent)
        item["approved_rate_card_count"] -= 1

    rec = new_record("RateCard", {
        "contracted_item_id": item["id"],
        "supersedes_rate_card_id": incumbent["id"] if incumbent else None,
        "rate_type": body["rate_type"],
        "flat_rate_cents_per_case": body["flat_rate_cents_per_case"],
        "percent_bps": body["percent_bps"],
        "tier_breaks": body["tier_breaks"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "status": "PROPOSED",
        "pinned_item_version": None,
    })
    db.rate_cards[rec["id"]] = rec
    # The owning item's version advances by exactly 1 for the call as a whole.
    touch(item)
    return created(dump(rec))


@bp.get("/rate-cards/<rate_card_id>")
@endpoint(*DEAL_ROLES)
def get_rate_card(caller, rate_card_id):
    return ok(dump(resolve("rate_card", rate_card_id)))


@bp.get("/rate-cards")
@endpoint(*DEAL_ROLES)
def list_rate_cards(caller):
    records = _filtered(db.rate_cards.values(),
                        [("contracted_item_id", "contracted_item_id"),
                         ("supersedes_rate_card_id", "supersedes_rate_card_id"),
                         ("status", "status"),
                         ("rate_type", "rate_type")])
    return paged(records)


@bp.post("/rate-cards/<rate_card_id>/approve")
@endpoint("GpoAdmin")
def approve_rate_card(caller, rate_card_id):
    card = resolve("rate_card", rate_card_id)
    if card["status"] != "PROPOSED":                # priority 11
        raise ApiError("ERR_INVALID_STATE")
    item = db.items.get(card["contracted_item_id"])
    if item is None or item["status"] != "ACTIVE":  # priority 11
        raise ApiError("ERR_INVALID_STATE")
    _require_deal_open(deal_of_item(item))         # priority 14

    card["status"] = "APPROVED"
    # pinned_item_version records the item's version as observed at this instant,
    # before this approval advances it.
    card["pinned_item_version"] = item["version"]
    touch(card)
    item["approved_rate_card_count"] += 1
    touch(item)
    return ok(dump(card))

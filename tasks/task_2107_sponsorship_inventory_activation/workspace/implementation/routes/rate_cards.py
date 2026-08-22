"""Rate cards, priced lines and publication (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from db import store, new_row, touch, ordered
from errors import ApiError
from middleware import endpoint
from response import ok, created, paginate
from services.serialize import rate_card_out, rate_card_line_out
from routes.properties import get_property_or_404
from util import body_of, fail, v_str, v_int, v_num, v_enum, v_pagination, v_query_enum

bp = Blueprint("rate_cards", __name__)

ASSET_CLASSES = {"SIGNAGE", "DIGITAL_BOARD", "MEDIA_SPOT", "HOSPITALITY", "IP_RIGHTS", "ACTIVATION_SPACE"}
RATE_CARD_STATUSES = {"DRAFT", "PUBLISHED", "SUPERSEDED"}
READ_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover"]


def get_rate_card_or_404(rate_card_id):
    card = store.rate_cards.get(rate_card_id)
    if card is None:
        raise ApiError("ERR_RATE_CARD_NOT_FOUND", 404)
    return card


@bp.post("/properties/<property_id>/rate-cards")
@endpoint(["PropertyAdmin"])
def create_rate_card(property_id):
    prop = get_property_or_404(property_id)
    body = body_of(request)
    label = v_str(body, "label", min_len=1, max_len=80)
    effective_year = v_int(body, "effective_year", min_v=2020, max_v=2100)

    row = new_row()
    row.update({
        "property_id": prop["id"],
        "label": label,
        "effective_year": effective_year,
        "status": "DRAFT",
        "published_at": None,
        "superseded_by_rate_card_id": None,
        "line_count": 0,
    })
    store.rate_cards[row["id"]] = row
    return created(rate_card_out(row))


@bp.get("/rate-cards/<rate_card_id>")
@endpoint(READ_ROLES)
def read_rate_card(rate_card_id):
    return ok(rate_card_out(get_rate_card_or_404(rate_card_id)))


@bp.get("/rate-cards")
@endpoint(READ_ROLES)
def list_rate_cards():
    status = v_query_enum(request, "status", RATE_CARD_STATUSES)
    limit, offset = v_pagination(request)
    property_id = request.args.get("property_id")
    superseded_by = request.args.get("superseded_by_rate_card_id")

    rows = list(store.rate_cards.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_rate_card_id"] == superseded_by]
    return paginate(ordered(rows), limit, offset, rate_card_out)


@bp.post("/rate-cards/<rate_card_id>/lines")
@endpoint(["PropertyAdmin"])
def create_rate_card_line(rate_card_id):
    card = get_rate_card_or_404(rate_card_id)
    body = body_of(request)
    asset_class = v_enum(body, "asset_class", ASSET_CLASSES)
    base_unit_price_cents = v_int(body, "base_unit_price_cents", min_v=1)
    tier_breaks = _validate_tier_breaks(body)
    exclusivity_multiplier = v_num(body, "exclusivity_multiplier", required=False,
                                   default=Decimal("1.00"), min_v="1.00", max_v="2.00", max_dp=2)

    if card["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    for existing in db.lines_of_card(card["id"]):
        if existing["asset_class"] == asset_class:
            raise ApiError("ERR_DUPLICATE_RATE_LINE", 409)

    row = new_row(versioned=False)
    row.update({
        "rate_card_id": card["id"],
        "asset_class": asset_class,
        "base_unit_price_cents": base_unit_price_cents,
        "tier_breaks": tier_breaks,
        "exclusivity_multiplier": exclusivity_multiplier,
    })
    store.rate_card_lines[row["id"]] = row

    card["line_count"] = card["line_count"] + 1
    touch(card)
    return created(rate_card_line_out(row))


def _validate_tier_breaks(body):
    raw = body.get("tier_breaks")
    if raw is None:
        return []
    if not isinstance(raw, list):
        fail("Field 'tier_breaks' must be an array.")
    if len(raw) > 5:
        fail("Field 'tier_breaks' accepts at most 5 entries.")
    seen = set()
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("Each tier break must be an object.")
        min_units = entry.get("min_units")
        unit_price_cents = entry.get("unit_price_cents")
        if isinstance(min_units, bool) or not isinstance(min_units, int) or min_units < 1:
            fail("Each tier break needs a 'min_units' integer of at least 1.")
        if isinstance(unit_price_cents, bool) or not isinstance(unit_price_cents, int) or unit_price_cents < 1:
            fail("Each tier break needs a 'unit_price_cents' integer of at least 1.")
        if min_units in seen:
            fail("Tier break 'min_units' values must be distinct.")
        seen.add(min_units)
        out.append({"min_units": min_units, "unit_price_cents": unit_price_cents})
    return out


@bp.get("/rate-cards/<rate_card_id>/lines")
@endpoint(READ_ROLES)
def list_rate_card_lines(rate_card_id):
    card = get_rate_card_or_404(rate_card_id)
    limit, offset = v_pagination(request)
    return paginate(db.lines_of_card(card["id"]), limit, offset, rate_card_line_out)


@bp.post("/rate-cards/<rate_card_id>/publish")
@endpoint(["PropertyAdmin"])
def publish_rate_card(rate_card_id):
    card = get_rate_card_or_404(rate_card_id)
    # A card with zero lines is rejected before any state check runs.
    if card["line_count"] < 1:
        fail("A rate card must carry at least one line to be published.")
    if card["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    prop = store.properties.get(card["property_id"])
    if prop is None or prop["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409)

    previous = [rc for rc in db.published_rate_cards(prop["id"]) if rc["id"] != card["id"]]

    card["status"] = "PUBLISHED"
    card["published_at"] = store.now_raw()
    touch(card)

    for old in previous:
        old["status"] = "SUPERSEDED"
        old["superseded_by_rate_card_id"] = card["id"]
        touch(old)

    # The property's published-card pointer moved.
    touch(prop)
    return ok(rate_card_out(card))

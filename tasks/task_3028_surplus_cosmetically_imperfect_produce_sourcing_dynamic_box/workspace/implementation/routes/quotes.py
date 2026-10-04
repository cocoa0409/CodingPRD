"""Conventional quotes and substantiation (§2.9)."""

from flask import Blueprint

import envelope
import params
import rules
import store
from common import ApiError
from routes import helpers
from services import lots as lots_svc

bp = Blueprint("quotes", __name__)


@bp.post("/produce/conventional-quotes")
def create():
    actor = helpers.actor()
    helpers.admin(actor)
    payload = params.body()
    params.missing(payload, [
        "supply_lot_id", "retailer_label", "source_url", "captured_at",
        "conventional_unit_price_cents", "barcode_gtin",
    ])
    lot = helpers.fetch_lot(payload["supply_lot_id"])
    params.check_barcode(payload.get("barcode_gtin"))

    row = store.new_row({
        "supply_lot_id": lot["id"],
        "retailer_label": payload["retailer_label"],
        "source_url": payload["source_url"],
        "captured_at": payload["captured_at"],
        "conventional_unit_price_cents": params.as_int(
            "conventional_unit_price_cents",
            payload["conventional_unit_price_cents"]),
        "barcode_gtin": payload["barcode_gtin"],
        "grade_equivalent": bool(payload.get("grade_equivalent", False)),
        "is_primary": False,
        "source_count": 0,
        "substantiation_status": "UNSUBSTANTIATED",
    })
    store.CONVENTIONAL_QUOTES[row["id"]] = row
    refresh_lot(lot)
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/conventional-quotes")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor)
    rows = list(store.CONVENTIONAL_QUOTES.values())
    rows = params.query_filter(rows, "supply_lot_id")
    rows = params.query_filter(rows, "substantiation_status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/conventional-quotes/<quote_id>")
def read(quote_id):
    actor = helpers.actor()
    helpers.admin(actor)
    row = store.CONVENTIONAL_QUOTES.get(quote_id)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "No ConventionalQuote exists with the given id.")
    return envelope.object_response(store.serialise(row))


@bp.post("/produce/conventional-quotes/<quote_id>/substantiate")
def substantiate(quote_id):
    actor = helpers.actor()
    helpers.admin(actor)
    quote = store.CONVENTIONAL_QUOTES.get(quote_id)
    if quote is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "No ConventionalQuote exists with the given id.")
    lot = helpers.fetch_lot(quote["supply_lot_id"])
    refresh_lot(lot)

    status = rules.substantiation_status_for(lot)
    if status != "SUBSTANTIATED":
        raise ApiError("ERR_SUBSTANTIATION_REQUIRED", 422,
                       "A quote exists but does not substantiate the lot's grade.")

    same_grade = rules.grade_equivalent_source_count_for(lot)
    return envelope.object_response({
        "supply_lot_id": lot["id"],
        "source_count": rules.source_count_for(lot),
        "grade_equivalent_source_count": same_grade,
        "is_substantiated": True,
    })


def refresh_lot(lot):
    """Refresh the primary flag, the source count and the derived lot fields."""
    rules.rebuild_primary_quotes()
    lots_svc.derived_lot(lot)
    status = rules.substantiation_status_for(lot)
    for quote in store.CONVENTIONAL_QUOTES.values():
        if quote["supply_lot_id"] != lot["id"]:
            continue
        quote["source_count"] = rules.source_count_for(lot)
        quote["substantiation_status"] = status
        store.touch(quote)
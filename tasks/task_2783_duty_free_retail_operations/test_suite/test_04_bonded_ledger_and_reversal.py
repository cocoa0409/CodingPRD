"""Compensation on the append-only bonded ledger, and the discovery channel it is read through."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_MOVEMENT_NOT_REVERSIBLE
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_movement_shape,
    assert_pagination_meta,
    assert_stock_quantities,
    created,
    ids_of,
    ok,
    page,
)
from test_helpers.test_users import STOCK_CONTROLLER_HEADERS


def _watch_ledger_with_two_receipts(api):
    """A Hong Kong watch ledger credited with a RECEIPT of 100 and then one of 40."""
    terminal = fx.register_terminal(
        api,
        iata_code="HKG",
        name="Hong Kong Duty Free",
        country_code="HK",
        sealed_bag_regime="ICAO_STEB",
        liquid_limit_ml=3000,
    )
    brand = fx.register_brand(api, name="Meridian Timepieces", category="ELECTRONICS")
    watch = fx.listed_product(
        api,
        brand["id"],
        sku="MER-WATCH-01",
        category="ELECTRONICS",
        unit_price_cents=20000,
        duty_rate_bps=0,
        vat_rate_bps=700,
    )
    stock_item = fx.open_ledger(api, terminal["id"], watch["id"])
    first = fx.post_receipt(api, stock_item["id"], 100)
    second = fx.post_receipt(api, stock_item["id"], 40)
    return stock_item, first, second


def test_reversing_a_receipt_appends_a_compensating_entry_without_editing_the_original(api):
    """The ledger grows a REVERSAL row; the original RECEIPT keeps its own quantity and
    only its ``reversed`` flag moves.

    PRD 3.3: "When a controller needs to undo one, they compensate it: the server appends a fresh entry of type `REVERSAL` whose `qty_delta` is the exact negation of the original's, whose `affects` copies the original's dimension, whose `reversal_of_movement_id` points at the original entry, and whose `source_ref_type` is `MANUAL` with a null `source_ref_id`."

    Design: Difficulty/compensating_invariant/receipt_reversal_conserves_physical_units_and_duty_suspended_value
    """
    stock_item, first, second = _watch_ledger_with_two_receipts(api)

    before = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert before["on_hand_qty"] == 140
    assert before["duty_suspended_value_cents"] == 196000

    reversal = created(api.reverse_movement(second["id"], STOCK_CONTROLLER_HEADERS))
    assert_movement_shape(reversal)
    assert reversal["movement_type"] == "REVERSAL"
    assert reversal["qty_delta"] == -40
    assert reversal["affects"] == "ON_HAND"
    assert reversal["reversal_of_movement_id"] == second["id"]
    assert reversal["source_ref_type"] == "MANUAL"
    assert reversal["source_ref_id"] is None

    original = ok(api.get_movement(second["id"], STOCK_CONTROLLER_HEADERS))
    assert original["reversed"] is True
    assert original["qty_delta"] == 40
    assert original["movement_type"] == "RECEIPT"
    assert ok(api.get_movement(first["id"], STOCK_CONTROLLER_HEADERS))["reversed"] is False


def test_the_compensation_restores_the_pre_receipt_position_and_cannot_be_repeated(api):
    """140 units worth 196000 cents of suspended duty return to 100 units worth 140000,
    and the same movement may not be compensated twice.

    PRD 3.3: "Compensation is confined to entries the controller could have posted in the first place: only a `RECEIPT` or an `AUDIT_ADJUSTMENT` that has not already been reversed may be compensated this way, and anything else — a `SALE_ISSUE`, a `RESERVATION_HOLD`, a `RESERVATION_RELEASE`, a `SHRINKAGE_WRITE_OFF`, a `REVERSAL`, or an entry whose `reversed` flag is already true — is refused with `ERR_MOVEMENT_NOT_REVERSIBLE`."

    Design: Difficulty/compensating_invariant/receipt_reversal_conserves_physical_units_and_duty_suspended_value
    """
    stock_item, _first, second = _watch_ledger_with_two_receipts(api)

    created(api.reverse_movement(second["id"], STOCK_CONTROLLER_HEADERS))

    restored = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(restored, on_hand=100, reserved=0, available=100)
    assert restored["duty_suspended_value_cents"] == 140000

    validate_error(
        api.reverse_movement(second["id"], STOCK_CONTROLLER_HEADERS),
        ERR_MOVEMENT_NOT_REVERSIBLE,
    )

    unchanged = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert unchanged["on_hand_qty"] == 100
    assert unchanged["duty_suspended_value_cents"] == 140000

    movements, _ = page(
        api.list_movements(STOCK_CONTROLLER_HEADERS, {"stock_item_id": stock_item["id"]})
    )
    assert len(movements) == 3


def test_the_ledger_list_slices_the_filtered_set_in_created_at_order(api):
    """Three receipts posted on three different logical days page deterministically, and a
    filter that matches nothing answers with an empty array.

    PRD 2.3: "Unless a specific endpoint says otherwise, every list is sorted by `created_at` in ascending order, so the oldest record appears first."

    Design: Corner/endpoints/filtered_lists_paginate_deterministically_and_respect_every_declared_filter
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    whisky = fx.listed_product(api, brand["id"], sku="AUR-WHISKY-700", category="LIQUOR")
    stock_item = fx.open_ledger(api, terminal["id"], whisky["id"])

    first = fx.post_receipt(api, stock_item["id"], 1)
    fx.advance_clock(api, "2026-08-02T00:00:00Z")
    second = fx.post_receipt(api, stock_item["id"], 2)
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    third = fx.post_receipt(api, stock_item["id"], 3)

    movements, meta = page(
        api.list_movements(STOCK_CONTROLLER_HEADERS, {"stock_item_id": stock_item["id"]})
    )
    assert ids_of(movements) == [first["id"], second["id"], third["id"]]
    assert_created_at_ascending(movements)
    assert_pagination_meta(meta, limit=10, offset=0, total_count=3, has_more=False)

    window, window_meta = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "limit": 2, "offset": 1},
        )
    )
    assert ids_of(window) == [second["id"], third["id"]]
    assert_pagination_meta(window_meta, limit=2, offset=1, total_count=3, has_more=False)

    issues, issues_meta = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "movement_type": "SALE_ISSUE"},
        )
    )
    assert issues == []
    assert issues_meta["total_count"] == 0

    reservations, _ = page(
        api.list_pre_orders(STOCK_CONTROLLER_HEADERS, {"stock_item_id": stock_item["id"]})
    )
    assert reservations == []

    assert ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 6

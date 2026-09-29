"""No settling window: the mutating response already carries every consequence."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_instant_equals, assert_ledger_entry
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    ledger_rows,
    onboard_vendor,
    place_order,
    present_quote,
    read_territory,
    record_opening,
)
from test_helpers.test_users import (
    franchisee_headers,
    franchisor_headers,
    vendor_rep_headers,
)

CLOCK_STARTUP = "2026-08-01T00:00:00.000Z"

CORDED_VENDOR = {"base_lead_time_days": 10, "motorization_extra_days": 3,
                 "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                 "concurrent_capacity": 5,
                 "supported_lift_systems": ["CORDED"]}


def test_the_money_is_readable_in_the_request_after_the_one_that_made_it(api):
    """Acceptance, placement and receipt each answer completely, and reads never drift.

    "Unless otherwise noted, operations that create or modify a resource will return the
    created or updated resource object in the data field."

    "A ledger row of type `NET_SALES_ROYALTY` is appended whose `amount_cents` is the
    recognized basis multiplied by the territory's `royalty_rate_pct` and rounded half up
    to a whole cent, whose `basis_cents` is the recognized basis, whose
    `source_entity_type` is `QUOTE` and whose `memo` is `quote_accepted`; that amount
    raises the territory's `royalty_accrued_cents`."

    "Because no write endpoint returns the ledger rows it created, the territory's ledger
    listing is the only channel through which cascade-created accruals are observable; it
    accepts optional `entry_type` and `source_entity_type` filters."

    "Receipt is the point at which the vendor's production slot is released and the
    franchise's exposure falls: the vendor's `open_order_count` and the territory's
    `open_order_exposure_cents` are both re-derived downward, the latter by that order's
    `order_cost_cents`."

    "Its startup default is exactly `2026-08-01T00:00:00Z`; before any clock-setting call
    the logical clock reads that instant, and it never falls back to real wall-clock time."

    Design: Corner/consistency_model/every_consequence_is_already_in_the_mutating_response
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    vendor = onboard_vendor(api, **CORDED_VENDOR)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    left = configure_opening(
        api, designer, record_opening(api, designer, consultation,
                                      label="Left"),
        fabric_code="LT-SHEER", lift_system="CORDED")
    right = configure_opening(
        api, designer, record_opening(api, designer, consultation,
                                      label="Right"),
        fabric_code="LT-SHEER", lift_system="CORDED")

    quote = build_quote(api, designer, consultation)
    priced = present_quote(api, designer, quote)
    assert priced["subtotal_cents"] == 9920
    assert priced["install_fee_cents"] == 12500
    assert priced["total_cents"] == 22420

    # The acceptance response is already complete: no follow-up read is needed.
    accepted = accept_quote(api, designer, quote)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["recognized_net_sales_cents"] == 9920

    # And the very next request sees the money it moved.
    banked = read_territory(api, territory)
    assert banked["net_sales_cents"] == 9920
    assert banked["royalty_accrued_cents"] == 546

    accruals = ledger_rows(api, territory, entry_type="NET_SALES_ROYALTY")
    assert len(accruals) == 1
    assert_ledger_entry(accruals[0], "NET_SALES_ROYALTY", 546, 9920,
                        "quote_accepted", "QUOTE",
                        source_entity_id=quote["id"],
                        territory_id=territory["id"])
    assert_instant_equals(accruals[0]["occurred_at"], CLOCK_STARTUP)

    # The placement response already carries the derived wholesale figure.
    order = place_order(api, territory, quote, [left["id"], right["id"]],
                        vendor)
    assert order["order_cost_cents"] == 4166
    assert read_territory(api, territory)["open_order_exposure_cents"] == 4166

    shipped = validate_success(
        api.ship_vendor_order(order["id"], vendor_rep_headers(vendor["id"])))
    assert shipped["status"] == "SHIPPED"

    received = validate_success(
        api.receive_vendor_order(order["id"],
                                 franchisee_headers(territory["id"])))
    assert received["status"] == "RECEIVED"
    assert_instant_equals(received["received_at"], CLOCK_STARTUP)

    # Releasing the exposure does not touch the accrued royalty.
    settled = read_territory(api, territory)
    assert settled["open_order_exposure_cents"] == 0
    assert settled["royalty_accrued_cents"] == 546

    # Reads are stable and actor-independent with no intervening write.
    headquarters = validate_success(
        api.get_territory(territory["id"], franchisor_headers()))
    assert (headquarters["open_order_exposure_cents"]
            == settled["open_order_exposure_cents"])
    assert headquarters["royalty_accrued_cents"] == settled["royalty_accrued_cents"]
    assert headquarters["net_sales_cents"] == settled["net_sales_cents"]

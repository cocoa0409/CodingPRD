"""A full credit is the exact compensating action of an acceptance — almost."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_ledger_entry,
    assert_page_meta,
    assert_remake_buckets_sum,
    assert_reversal_sign,
)
from test_helpers.fixtures import (
    read_opening,
    read_order,
    read_quote,
    read_territory,
    request_remake,
    single_opening_job,
)
from test_helpers.test_users import franchisee_headers


def _received_cordless_order(api):
    """One 6760-cent cordless opening, ordered at 2839 cents and received.

    Acceptance has already accrued net sales of 6760 and royalty of 372, and the
    manufacturer splits remakes fifty-fifty.
    """
    return single_opening_job(
        api, fabric_code="LT-SHEER", lift_system="CORDLESS",
        motorization_option="NONE", room_type="OFFICE",
        vendor_kwargs={"base_lead_time_days": 10,
                       "motorization_extra_days": 3,
                       "cutoff_hour_utc": 15,
                       "remake_policy": "SHARED_50_50",
                       "concurrent_capacity": 5,
                       "supported_lift_systems": ["CORDED", "CORDLESS"]},
        territory_kwargs={"royalty_rate_pct": 0.055,
                          "lead_capacity_per_week": 5,
                          "credit_limit_cents": 2000000,
                          "liability_window": "ROLLING_180D"},
        stop_after="received",
    )


def test_a_full_credit_cancels_the_order_and_splits_the_cost_fifty_fifty(api):
    """The credit runs the same waterfall a replacement would, and the odd cent lands locally.

    "A `SHARED_50_50` vendor's target is half of `remake_cost_cents` rounded **down**
    to a whole cent, and the territory's target is whatever remains — so on an odd
    cost of 7403 cents the vendor takes 3701 and the territory 3702, the extra cent
    landing on the territory rather than on the manufacturer."

    "A `FULL_CREDIT` remake sets `credit_scope` to `FULL_CREDIT`, runs the same
    waterfall, and drives `RECEIVED → CANCELLED`, which is terminal."

    Design: Difficulty/compensating_invariant/full_credit_remake_restores_the_royalty_ledger_but_not_the_chargeback
    """
    world = _received_cordless_order(api)
    territory, opening, order = world["territory"], world["opening"], world["order"]

    assert opening["list_price_cents"] == 6760
    assert order["order_cost_cents"] == 2839

    before = read_territory(api, territory)
    assert before["net_sales_cents"] == 6760
    assert before["royalty_accrued_cents"] == 372

    credited = request_remake(api, territory, order, credit_scope="FULL_CREDIT")
    assert credited["status"] == "CANCELLED"
    assert credited["credit_scope"] == "FULL_CREDIT"
    assert credited["remake_cost_cents"] == 2839
    assert credited["vendor_absorbed_cents"] == 1419
    assert credited["territory_absorbed_cents"] == 1420
    assert credited["customer_absorbed_cents"] == 0
    assert_remake_buckets_sum(credited)

    assert read_order(api, territory, order["id"])["status"] == "CANCELLED"

    flagged = read_opening(api, world["designer"], opening["id"])
    assert flagged["credited"] is True
    assert flagged["install_outcome"] == "PENDING"


def test_the_credit_restores_the_money_aggregates_but_not_the_chargeback(api):
    """Royalty and net sales come back to zero; the 1420 the credit cost stays.

    "A full credit is the exact compensating action of an acceptance: crediting a
    quote's whole opening set must restore the territory's `royalty_accrued_cents` to
    precisely its pre-acceptance value."

    "Whenever `territory_absorbed_cents` is greater than zero, a ledger row of type
    `REMAKE_CHARGEBACK` is appended for that amount, with `basis_cents` equal to
    `remake_cost_cents`, `source_entity_type` `VENDOR_ORDER` and `memo`
    `remake_replacement`, and the amount is added to the territory's
    `remake_chargeback_cents`."

    Design: Difficulty/compensating_invariant/full_credit_remake_restores_the_royalty_ledger_but_not_the_chargeback
    """
    world = _received_cordless_order(api)
    territory, quote, order = world["territory"], world["quote"], world["order"]
    owner = franchisee_headers(territory["id"])

    request_remake(api, territory, order, credit_scope="FULL_CREDIT")

    unwound = read_quote(api, territory, quote["id"])
    assert unwound["credited_net_sales_cents"] == 6760
    assert unwound["recognized_net_sales_cents"] == 0

    after = read_territory(api, territory)
    assert after["net_sales_cents"] == 0
    assert after["royalty_accrued_cents"] == 0
    assert after["remake_chargeback_cents"] == 1420

    rows, meta = validate_paginated(api.list_ledger_entries(territory["id"], owner))
    assert_page_meta(meta, total_count=3, has_more=False)
    assert [row["entry_type"] for row in rows] == [
        "NET_SALES_ROYALTY", "REMAKE_CHARGEBACK", "ROYALTY_REVERSAL"]
    assert_ledger_entry(rows[0], "NET_SALES_ROYALTY", 372, 6760,
                        "quote_accepted", "QUOTE",
                        source_entity_id=quote["id"],
                        territory_id=territory["id"])
    assert_ledger_entry(rows[1], "REMAKE_CHARGEBACK", 1420, 2839,
                        "remake_replacement", "VENDOR_ORDER",
                        source_entity_id=order["id"],
                        territory_id=territory["id"])
    assert_ledger_entry(rows[2], "ROYALTY_REVERSAL", -372, 6760,
                        "remake_full_credit", "VENDOR_ORDER",
                        source_entity_id=order["id"],
                        territory_id=territory["id"])
    assert_reversal_sign(rows[2])

    # Restoration is proved by the signed sum, never by deleting a row.
    royalty_rows = [row for row in rows
                    if row["entry_type"] in ("NET_SALES_ROYALTY",
                                             "ROYALTY_REVERSAL")]
    assert sum(row["amount_cents"] for row in royalty_rows) == 0

    reversals, reversal_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="ROYALTY_REVERSAL"))
    assert_page_meta(reversal_meta, total_count=1, has_more=False)
    assert reversals[0]["amount_cents"] == -372


def test_the_credited_opening_is_excluded_from_every_later_royalty_basis(api):
    """The credited opening keeps its price but stops carrying revenue.

    "Every opening in the order's `opening_ids` has `credited` set to true, and
    credited openings are excluded from every royalty basis thereafter."

    Design: Difficulty/compensating_invariant/full_credit_remake_restores_the_royalty_ledger_but_not_the_chargeback
    """
    world = _received_cordless_order(api)
    territory, designer = world["territory"], world["designer"]
    quote, opening, order = world["quote"], world["opening"], world["order"]

    request_remake(api, territory, order, credit_scope="FULL_CREDIT")

    priced = read_opening(api, designer, opening["id"])
    assert priced["list_price_cents"] == 6760
    assert priced["credited"] is True

    unwound = read_quote(api, territory, quote["id"])
    assert unwound["net_sales_cents"] == 6760
    assert unwound["recognized_net_sales_cents"] == 0
    assert unwound["credited_net_sales_cents"] == 6760

    assert validate_success(api.get_territory(
        territory["id"], franchisee_headers(territory["id"])
    ))["royalty_accrued_cents"] == 0

"""Read-your-writes: every derived field is current in the response that caused it."""

from test_helpers import (
    ADMIN,
    DESTINATION_DISTRIBUTION,
    LICENSE_SELF_DISTRIBUTION,
    ORDER_ALLOCATED,
    ORDER_CHANNEL_SELF_DISTRIBUTED,
    ORDER_SHIPPED,
    PACKAGE_HALF_BBL_KEG,
    assert_allocation_lines,
    assert_bbl,
    assert_cents,
    assert_instant_equals,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_license,
    create_tank,
    submit_order,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class TestImmediateConsistency:
    def test_allocation_and_shipment_answer_with_every_ledger_already_moved(self, api):
        """No read-after-write lag: lines, run buckets and the licence counter are current.

        PRD §3.7: "Otherwise `channel` becomes `SELF_DISTRIBUTED` and `appointment_id`
        stays null."

        PRD §3.7: "`landed_cost_cents` is `product_cents` plus `freight_cents` plus
        `franchise_fee_cents`."

        PRD §3.7: "Walking the sorted pool in order, each run contributes the smaller
        of its own `available_bbl` and the barrels still outstanding; that contribution
        is appended to `allocation_lines` as an entry naming the run's
        `packaging_run_id` and the `bbl` taken, rounded half up to three decimal
        places; the run's `allocated_bbl` rises by that amount so its `available_bbl`
        falls by the same amount; and the outstanding figure is reduced by the
        contribution, rounded half up to three decimal places."

        PRD §3.7: "On success the order moves `ALLOCATED → SHIPPED` and
        `shipped_at_utc` is stamped from the logical clock — the distribution
        tax-determination instant that decides which reporting period the barrels land
        in."

        PRD §3.7: "Each cited run moves that line's barrels from `allocated_bbl` to
        `shipped_bbl`, leaving `available_bbl` **unchanged**, since those barrels were
        already spoken for."

        PRD §3.6: "`barrels_shipped_ytd` is `carry_in_barrels_ytd` plus the sum of
        `allocated_bbl` over every distribution order under this licence whose `state`
        is `SHIPPED` — orders that were rejected, cancelled or are merely allocated
        contribute nothing."

        PRD §3.1: "From them the brewery's three read-only aggregates are derived:
        `taproom_bbl_ytd` is `carry_in_taproom_bbl` plus the sum of `taproom_bbl`
        over every excise report whose `state` is `FILED` (reports in `SUPERSEDED`
        are excluded, as are drafts); `distribution_bbl_ytd` is
        `carry_in_distribution_bbl` plus the sum of `distribution_bbl` over the same
        filed set; and `total_bbl_ytd` is the sum of those two."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_caused_it
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_conditioning_batch(
            api,
            beer["id"],
            tank["id"],
            actual_yield_bbl=16.000,
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-1",
        )
        assert_bbl(run["available_bbl"], 5.000, "run available_bbl at completion")

        order = submit_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=4.00,
            ship_to_state_code="ID",
            distance_miles=100,
            requested_ship_utc="2026-08-20T15:00:00Z",
            order_code="SO-1",
        )
        assert order["channel"] == ORDER_CHANNEL_SELF_DISTRIBUTED
        assert order["appointment_id"] is None
        assert_cents(order["product_cents"], 168000, "product_cents")
        assert_cents(order["freight_cents"], 7020, "freight_cents")
        assert_cents(order["franchise_fee_cents"], 0, "franchise_fee_cents")
        assert_cents(order["landed_cost_cents"], 175020, "landed_cost_cents")

        allocated = validate_success(api.allocate_order(order["id"], ADMIN))
        assert allocated["state"] == ORDER_ALLOCATED
        assert allocated["rejection_reason"] is None
        assert_bbl(allocated["allocated_bbl"], 4.000, "order allocated_bbl")
        assert_allocation_lines(allocated["allocation_lines"], [(run["id"], 4.000)])

        reserved = validate_success(api.get_packaging_run(run["id"], ADMIN))
        assert_bbl(reserved["allocated_bbl"], 4.000, "run allocated_bbl after allocate")
        assert_bbl(reserved["available_bbl"], 1.000, "run available_bbl after allocate")
        assert_bbl(reserved["shipped_bbl"], 0.000, "run shipped_bbl after allocate")

        shipped = validate_success(api.ship_order(order["id"], ADMIN))
        assert shipped["state"] == ORDER_SHIPPED
        assert_bbl(shipped["allocated_bbl"], 4.000, "order allocated_bbl after ship")
        assert_instant_equals(shipped["shipped_at_utc"], DEFAULT_CLOCK, "shipped_at_utc")

        licence_after = validate_success(
            api.get_state_license(license_row["id"], ADMIN)
        )
        assert_bbl(licence_after["barrels_shipped_ytd"], 4.000, "barrels_shipped_ytd")

        removed = validate_success(api.get_packaging_run(run["id"], ADMIN))
        assert_bbl(removed["allocated_bbl"], 0.000, "run allocated_bbl after ship")
        assert_bbl(removed["shipped_bbl"], 4.000, "run shipped_bbl after ship")
        assert_bbl(removed["available_bbl"], 1.000, "run available_bbl after ship")
        assert_bbl(removed["bbl_removed"], 5.000, "run bbl_removed after ship")

        brewery = validate_success(api.get_brewery(ADMIN))
        assert_bbl(brewery["distribution_bbl_ytd"], 0.000, "distribution_bbl_ytd")
        assert_bbl(brewery["total_bbl_ytd"], 0.000, "total_bbl_ytd")

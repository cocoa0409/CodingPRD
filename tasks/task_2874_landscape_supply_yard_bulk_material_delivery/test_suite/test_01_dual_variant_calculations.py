"""The same figure computed two ways: stockpile volume bases and order totals."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import CENTS, assert_charge_assembly, assert_inventory_lot
from test_helpers.factories import create_moisture_reading_payload
from test_helpers.fixtures import (
    advance_clock,
    deliver_load,
    dispatch_load,
    read_account,
    read_line,
    read_lot,
    read_material,
    read_order,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_planned_load,
    seed_price_schedule,
)
from test_helpers.test_users import make_yard_admin_headers

BROWN_MULCH = {
    "sku": "MULCH-BROWN",
    "name": "Brown Hardwood Mulch",
    "offered_forms": ["BULK", "BAGGED"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


class TestInventoryNetVolumeBasisVariants:
    """One physical lot reports two different sellable volumes."""

    def test_intake_basis_charges_the_full_shrinkage_factor(self, api):
        """A never-re-measured lot values itself off the intake moisture reading.

        PRD 3.2: "While `basis` is `INTAKE` -- meaning no moisture reading has been
        filed since the lot was scaled in -- `net_sellable_cubic_yards` is the
        `gross_cubic_yards` multiplied by one minus the full `shrinkage_factor` of the
        material, multiplied by the moisture multiplier taken from
        `moisture_pct_at_intake`, with the product rounded half up to two decimal
        places."

        Design: Difficulty/dual_variant_calc/inventory_net_volume_intake_versus_settlement_basis
        """
        catalogue = seed_catalogue(
            api,
            material=BROWN_MULCH,
            price={
                "effective_from": "2026-07-01T00:00:00.000Z",
                "bulk_price_per_cubic_yard_cents": 2000,
                "bagged_price_per_bag_cents": 899,
                "seasonal_surcharge_pct": 0.0,
            },
            lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 20.0},
        )
        lot = catalogue["lot"]

        assert_inventory_lot(lot)
        assert lot["basis"] == "INTAKE"
        assert lot["current_moisture_pct"] == pytest.approx(20.0, abs=CENTS)
        assert lot["status"] == "AVAILABLE"
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert lot["reserved_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        # 100.00 * (1 - 0.10) * 0.95
        assert lot["net_sellable_cubic_yards"] == pytest.approx(85.50, abs=CENTS)
        assert catalogue["material"]["available_net_cubic_yards"] == pytest.approx(85.50, abs=CENTS)

    def test_settlement_basis_charges_half_the_shrinkage_on_the_same_lot(self, api):
        """Filing a reading at the identical moisture still raises sellable volume.

        PRD 3.2: "Once `basis` has flipped to `SETTLEMENT` -- meaning at least one
        moisture reading has been filed -- the pile has already settled, so only
        **half** the shrinkage factor is charged and the arithmetic runs on the volume
        still physically on the ground: `net_sellable_cubic_yards` becomes
        `gross_cubic_yards` minus `withdrawn_gross_cubic_yards`, multiplied by one
        minus half the `shrinkage_factor`, multiplied by the moisture multiplier taken
        from `current_moisture_pct`, with the product rounded half up to two decimal
        places."

        Design: Difficulty/dual_variant_calc/inventory_net_volume_intake_versus_settlement_basis
        """
        catalogue = seed_catalogue(
            api,
            material=BROWN_MULCH,
            price={
                "effective_from": "2026-07-01T00:00:00.000Z",
                "bulk_price_per_cubic_yard_cents": 2000,
                "bagged_price_per_bag_cents": 899,
                "seasonal_surcharge_pct": 0.0,
            },
            lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 20.0},
        )
        lot_id = catalogue["lot"]["id"]
        before = catalogue["lot"]["net_sellable_cubic_yards"]

        response = api.create_moisture_reading(
            lot_id,
            create_moisture_reading_payload(20.0, set_quarantine=False),
            headers=make_yard_admin_headers(),
        )
        reading_result = validate_success(response, 200)

        assert reading_result["basis"] == "SETTLEMENT"
        # (100.00 - 0.00) * (1 - 0.05) * 0.95
        assert reading_result["net_sellable_cubic_yards"] == pytest.approx(90.25, abs=CENTS)
        assert reading_result["net_sellable_cubic_yards"] - before == pytest.approx(4.75, abs=CENTS)
        assert reading_result["status"] == "AVAILABLE"
        assert reading_result["withdrawn_gross_cubic_yards"] == pytest.approx(0.0, abs=CENTS)

        stored = read_lot(api, lot_id)
        assert stored["basis"] == "SETTLEMENT"
        assert stored["net_sellable_cubic_yards"] == pytest.approx(90.25, abs=CENTS)
        assert read_material(api, catalogue["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(90.25, abs=CENTS)


VERDE_PRICE_P1 = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 3333,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
VERDE_TRUCK = {
    "truck_code": "T-101",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 40000,
    "bed_capacity_cubic_yards": 25.0,
    "min_driveway_access_class": "CLASS_C",
}


def _verde_context(api):
    """A confirmed 20.00-cubic-yard delivery order priced off the 3333-cent row."""
    return seed_confirmed_delivery_context(
        api,
        material=BROWN_MULCH,
        price=VERDE_PRICE_P1,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Verde Landscapes", "credit_limit_cents": 5000000},
        lines=(("BULK", 20.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=10.0,
        truck=VERDE_TRUCK,
    )


class TestOrderTotalQuotedVersusFinal:
    """The quote the yard promised and the invoice it actually earned."""

    def test_confirm_freezes_the_quote_against_the_row_in_force_at_that_instant(self, api):
        """Confirming prices every line off the row in force when the quote froze.

        PRD 3.4: "Each line is priced against the price row in force at the confirm
        instant -- the row of that line's material with the greatest `effective_from` at
        or before the instant the quote is frozen, which the order records as
        `quote_locked_at`."

        Design: Difficulty/dual_variant_calc/order_total_quoted_at_confirm_versus_final_at_delivery
        """
        context = _verde_context(api)
        order = context["order"]
        line = context["lines"][0]

        assert order["fulfillment_status"] == "CONFIRMED"
        assert order["settlement_status"] == "UNBILLED"
        assert order["quote_locked_at"] is not None
        assert line["unit_price_cents"] == 3333
        assert line["line_price_cents"] == 66660
        assert line["final_line_price_cents"] is None
        assert order["bulk_subtotal_cents"] == 66660
        assert order["volume_discount_cents"] == 0
        assert order["min_load_fee_cents"] == 0
        # TRI_AXLE base 13500 + ROUND_HALF_UP(10.0 * 425)
        assert order["delivery_fee_cents"] == 17750
        assert order["quoted_total_cents"] == 84410
        assert order["final_total_cents"] is None
        assert_charge_assembly(order, 84410)

    def test_delivery_reprices_on_the_dispatch_instant_row_into_a_separate_total(self, api):
        """A promotion between confirm and dispatch splits the two totals apart.

        PRD 3.5: "The final basis differs from the confirm basis in three respects: the
        price row consulted is the one in force at the **dispatch instant** of the
        delivering load rather than at `quote_locked_at`; the billable quantity for a
        bulk line is its `delivered_volume_cubic_yards` rather than its ordered
        `quantity`; and the axle base in the delivery-fee step is the **actual
        delivering truck's** `axle_class` rather than the largest class the driveway
        admits."

        Design: Difficulty/dual_variant_calc/order_total_quoted_at_confirm_versus_final_at_delivery
        """
        context = _verde_context(api)
        order_id = context["order"]["id"]
        line_id = context["lines"][0]["id"]

        seed_price_schedule(
            api,
            read_material(api, context["material"]["id"]),
            effective_from="2026-08-15T00:00:00.000Z",
            bulk_price_per_cubic_yard_cents=4000,
            bagged_price_per_bag_cents=899,
            seasonal_surcharge_pct=10.0,
        )
        advance_clock(api, "2026-08-20T00:00:00.000Z")

        load = seed_planned_load(
            api,
            order_id,
            context["truck"]["id"],
            20.0,
            "2026-08-20T08:00:00.000Z",
            "2026-08-20T12:00:00.000Z",
        )
        dispatch_load(api, load["id"], "planner-1")
        deliver_load(api, load["id"], 20.0, True, None, "planner-1")

        order = read_order(api, order_id)
        line = read_line(api, line_id)
        account = read_account(api, context["account"]["id"])

        assert order["quoted_total_cents"] == 84410
        assert order["final_total_cents"] == 105750
        assert order["fulfillment_status"] == "FULFILLED"
        assert order["settlement_status"] == "UNBILLED"
        assert line["line_price_cents"] == 66660
        # 20.00 * 4000 * 1.10
        assert line["final_line_price_cents"] == 88000
        assert order["bulk_subtotal_cents"] == 88000
        assert order["delivery_fee_cents"] == 17750
        # the account's exposure follows the final total, not the frozen quote
        assert account["credit_used_cents"] == 105750
        assert account["credit_available_cents"] == 5000000 - 105750

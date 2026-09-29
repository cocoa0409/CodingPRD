"""Undo paths that must land every ledger back on the figure it started from."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    CENTS,
    assert_charge_assembly,
    assert_credit_position,
    assert_deposit_fully_resolved,
    assert_deposit_liability_conserved,
    assert_instant_equals,
)
from test_helpers.fixtures import (
    advance_clock,
    find_container_return,
    forfeit_containers,
    read_account,
    read_container_return,
    read_line,
    read_load,
    read_lot,
    read_material,
    read_order,
    read_prebuy,
    read_purchase_order,
    receive_containers,
    seed_account,
    seed_catalogue,
    seed_delivery_order,
    seed_fulfilled_delivery_order,
    seed_planned_load,
    seed_prebuy,
    seed_purchase_order,
    seed_truck,
)
from test_helpers.test_users import make_contractor_headers

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}
PREBUY_MULCH = {
    "sku": "MULCH-PREBUY",
    "name": "Pre-Buy Hardwood Mulch",
    "offered_forms": ["BULK"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": True,
}
COMPENSATION_TRUCK = {
    "truck_code": "T-444",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 20000,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}


def _compensation_grounds_care(api):
    """One confirmed order that consumes a pre-buy, a purchase order and a credit line whole."""
    catalogue = seed_catalogue(api, material=PREBUY_MULCH, price=FLAT_PRICE, lot=STANDARD_LOT)
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api,
        business_name="Compensation Grounds Care",
        credit_limit_cents=36000,
        po_required=True,
    )
    purchase_order = seed_purchase_order(
        api, account, 36000, po_number="PO-2026-118", job_code="JOB-118"
    )
    prebuy = seed_prebuy(
        api, account, material_id, 1500, 10.0, "2026-07-01", "2026-12-31"
    )
    seeded = seed_delivery_order(
        api,
        account,
        material_id,
        lines=(("BULK", 10.0, True),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        job_purchase_order_id=purchase_order["id"],
        delivery_address="60 Compensation Rd",
        confirm=True,
    )
    truck = seed_truck(api, **COMPENSATION_TRUCK)
    load = seed_planned_load(
        api,
        seeded["order"]["id"],
        truck["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T12:00:00.000Z",
    )
    return {
        "account": account,
        "material": catalogue["material"],
        "lot": catalogue["lot"],
        "purchase_order": purchase_order,
        "prebuy": prebuy,
        "order": seeded["order"],
        "line": seeded["lines"][0],
        "load": load,
    }


class TestOrderCancelCompensation:
    """One cancel has to walk four separate ledgers back to their pre-confirm figures."""

    def test_the_confirmed_prebuy_order_books_every_ledger_to_its_ceiling(self, api):
        """The season price, not the list price, is what fills the budget envelope.

        PRD 3.4: "Where the line carries a `prebuy_contract_id`, the bulk unit basis is
        instead the contract's `locked_price_per_cubic_yard_cents` and the seasonal
        surcharge is treated as zero, because a locked season price is immune both to later
        price rows and to seasonal uplift."

        PRD 3.3: "When a recompute leaves `committed_cents` at or above `po_limit_cents` the
        purchase order transitions `OPEN -> EXHAUSTED`, and further orders tagged to it
        cannot confirm -- they are stopped with `ERR_PO_LIMIT_EXCEEDED`."

        Design: Difficulty/compensating_invariant/order_cancel_restores_reservation_prebuy_credit_and_purchase_order
        """
        context = _compensation_grounds_care(api)

        order = read_order(api, context["order"]["id"])
        # 15000 locked bulk + 7500 minimum-load fee + TRI_AXLE base 13500 on a zero-mile haul
        assert order["quoted_total_cents"] == 36000
        assert_charge_assembly(order, 36000)
        assert order["fulfillment_status"] == "ALLOCATED"

        line = read_line(api, context["line"]["id"])
        assert line["prebuy_contract_id"] == context["prebuy"]["id"]
        assert line["unit_price_cents"] == 1500
        # 10.00 * 1500 with the surcharge treated as zero
        assert line["line_price_cents"] == 15000

        lot = read_lot(api, context["lot"]["id"])
        assert lot["reserved_cubic_yards"] == pytest.approx(10.00, abs=CENTS)
        # 90.00 sellable less the 10.00 reserved
        assert read_material(api, context["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(80.00, abs=CENTS)

        prebuy = read_prebuy(api, context["prebuy"]["id"])
        assert prebuy["status"] == "EXHAUSTED"
        assert prebuy["remaining_cubic_yards"] == pytest.approx(0.0, abs=CENTS)

        purchase_order = read_purchase_order(api, context["purchase_order"]["id"])
        assert purchase_order["status"] == "EXHAUSTED"
        assert purchase_order["committed_cents"] == 36000

        assert_credit_position(read_account(api, context["account"]["id"]), 36000, 0)

    def test_cancelling_unwinds_all_four_ledgers_and_leaves_the_settlement_axis_alone(self, api):
        """Every reversible ceiling comes back off, and nothing crosses into billing.

        PRD 3.4: "The second hop, caused by the order leaving the reserving set of
        `CONFIRMED` and `ALLOCATED`, recomputes every pinned lot's `reserved_cubic_yards`
        back to its pre-confirm value, recomputes every referenced pre-buy contract's
        `drawn_cubic_yards` downward -- returning an `EXHAUSTED` contract with
        `remaining_cubic_yards` above zero to `ACTIVE` -- recomputes the account's
        `credit_used_cents` downward, and recomputes the purchase order's `committed_cents`
        downward, returning an `EXHAUSTED` purchase order with `committed_cents` below
        `po_limit_cents` to `OPEN`."

        PRD 2.10: "Settling a claim moves `settlement_status` while `fulfillment_status`
        stays `FULFILLED`; the `ALLOCATED -> CONFIRMED` revert that follows a refused
        delivery leaves `settlement_status` untouched; cancelling an order sets
        `fulfillment_status` to `CANCELLED` and does not disturb `settlement_status`."

        PRD 3.4: "Alongside the ledger work, every `PLANNED` delivery load of the order
        transitions to `CANCELLED` and every will-call ticket of the order in `QUEUED` or
        `STAGED` transitions to `CANCELLED`."

        Design: Difficulty/compensating_invariant/order_cancel_restores_reservation_prebuy_credit_and_purchase_order
        """
        context = _compensation_grounds_care(api)
        account_id = context["account"]["id"]

        cancelled = validate_success(
            api.cancel_material_order(
                context["order"]["id"], headers=make_contractor_headers(account_id)
            ),
            200,
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["settlement_status"] == "UNBILLED"

        lot = read_lot(api, context["lot"]["id"])
        assert lot["reserved_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert lot["net_sellable_cubic_yards"] == pytest.approx(90.00, abs=CENTS)
        # no material ever moved, so the withdrawal ledger never started
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert read_material(api, context["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(90.00, abs=CENTS)

        prebuy = read_prebuy(api, context["prebuy"]["id"])
        assert prebuy["drawn_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert prebuy["remaining_cubic_yards"] == pytest.approx(10.0, abs=CENTS)
        assert prebuy["status"] == "ACTIVE"

        purchase_order = read_purchase_order(api, context["purchase_order"]["id"])
        assert purchase_order["committed_cents"] == 0
        assert purchase_order["status"] == "OPEN"

        assert_credit_position(read_account(api, account_id), 0, 36000)

        assert read_load(api, context["load"]["id"])["status"] == "CANCELLED"


BAGGED_MULCH = {
    "sku": "MULCH-BAGGED",
    "name": "Bagged Hardwood Mulch",
    "offered_forms": ["BULK", "BAGGED"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
LEDGER_TRUCK = {
    "truck_code": "T-555",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 20000,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}
FORTY_DAYS_OUT = "2026-09-10T00:00:00.000Z"


def _pallet_ledger_landscapes(api):
    """Two pallets issued on 2026-08-01, read back forty days later."""
    context = seed_fulfilled_delivery_order(
        api,
        material=BAGGED_MULCH,
        price=FLAT_PRICE,
        lot=STANDARD_LOT,
        account={"business_name": "Pallet Ledger Landscapes", "credit_limit_cents": 5000000},
        lines=(("BULK", 5.0), ("BAGGED", 60)),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=LEDGER_TRUCK,
        window_start="2026-08-01T08:00:00.000Z",
        window_end="2026-08-01T12:00:00.000Z",
        driveway_protection_used=True,
        dispatcher_user_id="planner-8",
    )
    context["container_return"] = find_container_return(api, context["order"]["id"])
    advance_clock(api, FORTY_DAYS_OUT)
    return context


class TestContainerDepositLiabilityConservation:
    """Half the deposit walks back to the contractor and the other half stays in the yard."""

    def test_a_forty_day_late_partial_return_refunds_half_of_one_deposit(self, api):
        """Ten days past grace rounds up to two whole weeks, and two quarters come off.

        PRD 3.8: "Convert that to whole weeks by dividing by the number of seconds in a week
        and rounding **up**, so any part of a week counts as a full week."

        PRD 3.3: "`pallet_deposit_balance_cents` is the sum, over every container-return
        record belonging to this account's orders, of that record's `issued_count`
        multiplied by its `deposit_per_unit_cents`, minus its `refund_cents`, minus its
        `forfeited_cents`."

        Design: Difficulty/compensating_invariant/container_deposit_liability_conserved_across_partial_return_and_forfeit
        """
        context = _pallet_ledger_landscapes(api)
        account_id = context["account"]["id"]
        record = context["container_return"]

        assert record["container_type"] == "PALLET"
        # CEIL(60 bags / 48 bags per container)
        assert record["issued_count"] == 2
        assert record["deposit_per_unit_cents"] == 2500
        assert_instant_equals(record["issued_at"], "2026-08-01T00:00:00.000Z")
        assert record["status"] == "OUTSTANDING"
        assert record["forfeited_cents"] == 0
        # 2 * 2500 issued, nothing refunded and nothing written off yet
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 5000

        received = receive_containers(api, record["id"], 1, "loader-3")
        assert received["returned_count"] == 1
        # ROUND_HALF_UP(1 * 2500 * (1 - 0.25 * 2))
        assert received["refund_cents"] == 1250
        assert received["status"] == "PARTIALLY_RETURNED"
        assert received["forfeited_cents"] == 0
        assert_instant_equals(received["last_received_at"], FORTY_DAYS_OUT)
        assert_deposit_liability_conserved(received)

        # 5000 issued liability less the 1250 just refunded
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 3750

    def test_forfeiting_the_carrier_that_never_came_back_retires_the_liability_exactly(self, api):
        """The forfeit is the issued liability minus the refund, not a mirror of it.

        PRD 3.8: "Carriers that never come back are written off by a `YardAdmin`, taking
        either the `OUTSTANDING -> FORFEITED` step or the `PARTIALLY_RETURNED ->
        FORFEITED` step, with identical effect in both cases: `forfeited_cents` is set to
        `issued_count` multiplied by `deposit_per_unit_cents` minus `refund_cents`, and the
        unreturned remainder is permanently retained by the yard."

        PRD 3.8: "Reaching `CLOSED` or `FORFEITED` recomputes it to zero for that record,
        because at that point the refund granted plus the amount forfeited exactly retires
        the liability the issue created."

        Design: Difficulty/compensating_invariant/container_deposit_liability_conserved_across_partial_return_and_forfeit
        """
        context = _pallet_ledger_landscapes(api)
        account_id = context["account"]["id"]
        record_id = context["container_return"]["id"]

        receive_containers(api, record_id, 1, "loader-3")

        forfeited = forfeit_containers(api, record_id)
        assert forfeited["status"] == "FORFEITED"
        # 2 * 2500 - 1250
        assert forfeited["forfeited_cents"] == 3750
        assert forfeited["refund_cents"] == 1250
        # the two halves are unequal, yet together they retire the whole 5000
        assert_deposit_fully_resolved(forfeited)
        # a forfeit never fabricates a return
        assert forfeited["returned_count"] == 1
        assert_instant_equals(forfeited["last_received_at"], FORTY_DAYS_OUT)

        assert read_container_return(api, record_id)["status"] == "FORFEITED"
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 0

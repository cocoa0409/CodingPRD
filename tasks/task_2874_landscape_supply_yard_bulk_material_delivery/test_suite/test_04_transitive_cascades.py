"""Cascades whose last hop lands several records away from the trigger."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import CENTS, assert_claim_waterfall_sums, assert_credit_position
from test_helpers.fixtures import (
    advance_clock,
    decide_claim,
    deliver_load,
    invoice_order,
    read_account,
    read_lot,
    read_material,
    read_order,
    read_ticket,
    seed_account,
    seed_catalogue,
    seed_claim,
    seed_delivery_order,
    seed_dispatched_load,
    seed_price_schedule,
    seed_truck,
    seed_will_call_order,
    seed_will_call_ticket,
)
from test_helpers.test_users import make_credit_manager_headers

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
CRUSHED_CONCRETE = {
    "sku": "AGG-CRUSH",
    "name": "Crushed Concrete",
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
GARDEN_BLEND = {
    "sku": "SOIL-BLEND",
    "name": "Garden Blend Soil",
    "offered_forms": ["BULK"],
    "seasonal_category": "SOIL",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


def _tight_line_ready_to_deliver(api):
    """A dispatched delivery order plus a queued will-call ticket on a 50000-cent line."""
    catalogue = seed_catalogue(
        api,
        material=CRUSHED_CONCRETE,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(api, business_name="Tight Line Landscape", credit_limit_cents=50000)

    delivery = seed_delivery_order(
        api,
        account,
        material_id,
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=2.0,
        delivery_address="5 Tight Line Rd",
        confirm=True,
    )
    will_call = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 2.0),), confirm=True
    )
    ticket = seed_will_call_ticket(
        api, will_call["order"]["id"], account["id"], "2026-08-01T00:00:00.000Z"
    )

    seed_price_schedule(
        api,
        read_material(api, material_id),
        effective_from="2026-08-05T00:00:00.000Z",
        bulk_price_per_cubic_yard_cents=4500,
        bagged_price_per_bag_cents=899,
        seasonal_surcharge_pct=0.0,
    )
    advance_clock(api, "2026-08-06T00:00:00.000Z")

    truck = seed_truck(
        api,
        truck_code="T-606",
        axle_class="TRI_AXLE",
        max_payload_lb=20000,
        bed_capacity_cubic_yards=15.0,
        min_driveway_access_class="CLASS_C",
    )
    load = seed_dispatched_load(
        api,
        delivery["order"]["id"],
        truck["id"],
        10.0,
        "2026-08-06T08:00:00.000Z",
        "2026-08-06T12:00:00.000Z",
        "planner-4",
    )
    return {
        "account": account,
        "lot": catalogue["lot"],
        "delivery_order": delivery["order"],
        "will_call_order": will_call["order"],
        "ticket": ticket,
        "load": load,
    }


class TestDeliveryRepricingReachesAnotherOrder:
    """A repriced delivery can knock a different order's ticket out of the queue."""

    def test_repriced_delivery_overruns_the_credit_line_and_puts_the_account_on_hold(self, api):
        """The final total is what the credit position is recomputed against.

        PRD 3.5: "The third hop, caused by the second hop's credit movement, transitions
        the account `ACTIVE -> CREDIT_HOLD` when `credit_used_cents` now exceeds
        `credit_limit_cents`."

        Design: Difficulty/transitive_cascade/delivery_repricing_cascades_to_credit_hold_and_cancels_queued_ticket
        """
        context = _tight_line_ready_to_deliver(api)

        assert context["delivery_order"]["quoted_total_cents"] == 41850
        assert context["will_call_order"]["quoted_total_cents"] == 4000

        deliver_load(api, context["load"]["id"], 10.0, True, None, "planner-4")

        order = read_order(api, context["delivery_order"]["id"])
        # 10.00 * 4500 with no minimum-load fee, plus TRI_AXLE 13500 + ROUND_HALF_UP(2.0 * 425)
        assert order["final_total_cents"] == 59350
        assert order["fulfillment_status"] == "FULFILLED"

        account = read_account(api, context["account"]["id"])
        assert_credit_position(account, 63350, -13350)
        assert account["account_status"] == "CREDIT_HOLD"

    def test_the_hold_cancels_the_other_orders_queued_ticket_and_reverts_that_order(self, api):
        """The chain terminates on a ticket belonging to an untouched order.

        PRD 3.6: "`queue_position` is set to null the moment a ticket leaves `QUEUED`, and
        every remaining queued ticket is renumbered whenever any ticket's status changes."

        Design: Difficulty/transitive_cascade/delivery_repricing_cascades_to_credit_hold_and_cancels_queued_ticket
        """
        context = _tight_line_ready_to_deliver(api)

        assert context["ticket"]["status"] == "QUEUED"
        assert context["ticket"]["queue_position"] == 1

        deliver_load(api, context["load"]["id"], 10.0, True, None, "planner-4")

        ticket = read_ticket(api, context["ticket"]["id"])
        assert ticket["status"] == "CANCELLED"
        assert ticket["queue_position"] is None

        will_call_order = read_order(api, context["will_call_order"]["id"])
        # the will-call order never reached ALLOCATED, so nothing reverts on it
        assert will_call_order["fulfillment_status"] == "CONFIRMED"
        assert read_lot(api, context["lot"]["id"])["reserved_cubic_yards"] == pytest.approx(
            2.00, abs=CENTS
        )


def _meadowbrook_approved_claim(api):
    """An account on hold, an invoiced order, and a 45000-cent claim already approved."""
    catalogue = seed_catalogue(
        api,
        material=GARDEN_BLEND,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(api, business_name="Meadowbrook Design", credit_limit_cents=50000)

    seeded = seed_delivery_order(
        api,
        account,
        material_id,
        lines=(("BULK", 12.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        delivery_address="88 Meadowbrook Ln",
        confirm=True,
    )
    order_id = seeded["order"]["id"]

    seed_price_schedule(
        api,
        read_material(api, material_id),
        effective_from="2026-08-05T00:00:00.000Z",
        bulk_price_per_cubic_yard_cents=5000,
        bagged_price_per_bag_cents=899,
        seasonal_surcharge_pct=0.0,
    )
    advance_clock(api, "2026-08-06T00:00:00.000Z")

    truck = seed_truck(
        api,
        truck_code="T-707",
        axle_class="TRI_AXLE",
        max_payload_lb=20000,
        bed_capacity_cubic_yards=15.0,
        min_driveway_access_class="CLASS_C",
    )
    load = seed_dispatched_load(
        api,
        order_id,
        truck["id"],
        12.0,
        "2026-08-06T08:00:00.000Z",
        "2026-08-06T12:00:00.000Z",
        "planner-5",
    )
    deliver_load(api, load["id"], 12.0, True, None, "planner-5")
    invoice_order(api, order_id)

    claim = seed_claim(
        api,
        order_id,
        account["id"],
        "DRIVEWAY_DAMAGE",
        45000,
        delivery_load_id=load["id"],
        description="Driveway sealer lifted despite matting",
        under_review=True,
        adjuster_user_id="adjuster-3",
    )
    claim = decide_claim(api, claim["id"], "APPROVE", 45000, adjuster_user_id="adjuster-3")
    return {
        "account": account,
        "order_id": order_id,
        "load": load,
        "claim": claim,
        "quoted_total_cents": seeded["order"]["quoted_total_cents"],
    }


class TestClaimSettlementReleasesTheCreditHold:
    """A settled claim walks money backwards until the account is trading again."""

    def test_the_matted_driveway_claim_pays_the_approved_figure_less_the_deductible(self, api):
        """The deductible stands because the crew did put the mats down.

        PRD 3.7: "For a `DRIVEWAY_DAMAGE` claim the yard applies a
        one-hundred-and-fifty-dollar deductible, except that the deductible is **waived
        entirely** -- treated as zero -- when the claim names a `delivery_load_id` whose
        `driveway_protection_used` is false, because a crew that skipped the mats does not
        get to bill the contractor for the first hundred and fifty dollars of the
        consequence; `payable_cents` is then the `approved_amount_cents` minus the
        applicable deductible, floored at zero so it never goes negative."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_to_credit_memo_and_releases_hold
        """
        context = _meadowbrook_approved_claim(api)
        claim = context["claim"]

        # 12.00 * 2000 + 7500 minimum-load fee + TRI_AXLE 13500 on a zero-mile haul
        assert context["quoted_total_cents"] == 45000
        order = read_order(api, context["order_id"])
        # 12.00 * 5000 clears the minimum-load threshold, so only the axle base is added
        assert order["final_total_cents"] == 73500
        assert order["settlement_status"] == "INVOICED"

        account = read_account(api, context["account"]["id"])
        assert account["account_status"] == "CREDIT_HOLD"
        assert account["credit_used_cents"] == 73500

        assert claim["status"] == "APPROVED"
        # 45000 approved less the 15000-cent deductible
        assert claim["payable_cents"] == 30000
        assert claim["invoice_offset_cents"] == 30000
        assert claim["deposit_offset_cents"] == 0
        assert claim["goodwill_credit_cents"] == 0
        assert_claim_waterfall_sums(claim)

    def test_settling_the_claim_credits_the_order_and_lets_the_account_trade_again(self, api):
        """The credit memo drops exposure below the hysteresis exit and the hold lifts.

        PRD 3.7: "The fourth hop, caused by that credit movement, releases an account in
        `CREDIT_HOLD` back to `ACTIVE` once `credit_used_cents` sits at or below ninety
        percent of `credit_limit_cents`, that threshold rounded half up."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_to_credit_memo_and_releases_hold
        """
        context = _meadowbrook_approved_claim(api)

        settled = validate_success(
            api.settle_claim_case(context["claim"]["id"], headers=make_credit_manager_headers()), 200
        )
        assert settled["status"] == "SETTLED"

        order = read_order(api, context["order_id"])
        assert order["credit_memo_cents"] == 30000
        assert order["settlement_status"] == "CREDIT_MEMO_ISSUED"
        assert order["fulfillment_status"] == "FULFILLED"

        account = read_account(api, context["account"]["id"])
        # 73500 less the 30000-cent memo, and 43500 <= ROUND_HALF_UP(50000 * 0.90)
        assert_credit_position(account, 43500, 6500)
        assert account["account_status"] == "ACTIVE"

"""Lifecycles that fork into parallel axes, loop back on themselves, or revert."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_claim_waterfall_sums, assert_instant_equals
from test_helpers.factories import refuse_payload, replan_payload
from test_helpers.fixtures import (
    decide_claim,
    dispatch_load,
    invoice_order,
    read_account,
    read_claim,
    read_load,
    read_lot,
    read_order,
    read_truck,
    seed_claim,
    seed_confirmed_delivery_context,
    seed_fulfilled_delivery_order,
    seed_planned_load,
)
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_credit_manager_headers,
    make_dispatch_planner_headers,
)

TOPSOIL = {
    "sku": "SOIL-TOP",
    "name": "Screened Topsoil",
    "offered_forms": ["BULK"],
    "seasonal_category": "SOIL",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
BIG_TRUCK = {
    "truck_code": "T-303",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 20000,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}


def _northgate_invoiced(api):
    """A fulfilled, invoiced 10.00-cubic-yard delivery order on a healthy account."""
    context = seed_fulfilled_delivery_order(
        api,
        material=TOPSOIL,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Northgate Grounds", "credit_limit_cents": 5000000},
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=4.0,
        truck=BIG_TRUCK,
        window_start="2026-08-02T08:00:00.000Z",
        window_end="2026-08-02T12:00:00.000Z",
        driveway_protection_used=False,
        dispatcher_user_id="planner-1",
    )
    context["order"] = invoice_order(api, context["order"]["id"])
    return context


class TestOrderDimensionsMoveIndependently:
    """Fulfilment and billing are two stored axes, not one combined status."""

    def test_invoicing_advances_only_the_billing_axis(self, api):
        """Billing moves while the fulfilment axis stays exactly where it was.

        PRD 3.9: "Invoicing transitions the order `UNBILLED -> INVOICED` and is the one
        place the two state dimensions interact: the order's `fulfillment_status` must
        already be `FULFILLED`, else the request is refused with
        `ERR_ORDER_NOT_FULFILLED`."

        Design: Difficulty/non_linear_state_machine/material_order_parallel_dimensions_move_independently
        """
        context = _northgate_invoiced(api)
        order = context["order"]

        assert order["fulfillment_status"] == "FULFILLED"
        assert order["settlement_status"] == "INVOICED"
        # 20000 bulk + 7500 minimum-load fee + TRI_AXLE 13500 + ROUND_HALF_UP(4.0 * 425)
        assert order["quoted_total_cents"] == 42700
        assert order["final_total_cents"] == 42700
        assert order["credit_memo_cents"] == 0
        assert order["paid_amount_cents"] == 0
        assert read_account(api, context["account"]["id"])["credit_used_cents"] == 42700

    def test_claim_settlement_moves_billing_to_credit_memo_and_leaves_fulfilment_alone(self, api):
        """A settled claim credits the order without un-delivering it.

        PRD 3.7: "The second hop, caused by the claim entering the settled set,
        recomputes the order's `credit_memo_cents` as the sum of `payable_cents` over
        that order's settled claims and transitions the order's `settlement_status` to
        `CREDIT_MEMO_ISSUED`, taking the `INVOICED -> CREDIT_MEMO_ISSUED` step or the
        `SETTLED -> CREDIT_MEMO_ISSUED` step according to which value it currently
        holds, while leaving `fulfillment_status` untouched."

        Design: Difficulty/non_linear_state_machine/material_order_parallel_dimensions_move_independently
        """
        context = _northgate_invoiced(api)
        order_id = context["order"]["id"]

        claim = seed_claim(
            api,
            order_id,
            context["account"]["id"],
            "DRIVEWAY_DAMAGE",
            30000,
            delivery_load_id=context["load"]["id"],
            description="Apron cracked by the tri-axle",
            under_review=True,
            adjuster_user_id="adjuster-1",
        )
        # the crew skipped the mats, so the 15000-cent deductible is waived entirely
        claim = decide_claim(api, claim["id"], "APPROVE", 20000, adjuster_user_id="adjuster-1")
        assert claim["payable_cents"] == 20000
        assert claim["invoice_offset_cents"] == 20000
        assert_claim_waterfall_sums(claim)

        settled = validate_success(
            api.settle_claim_case(claim["id"], headers=make_credit_manager_headers()), 200
        )
        assert settled["status"] == "SETTLED"

        order = read_order(api, order_id)
        assert order["settlement_status"] == "CREDIT_MEMO_ISSUED"
        assert order["fulfillment_status"] == "FULFILLED"
        assert order["credit_memo_cents"] == 20000
        assert order["quoted_total_cents"] == 42700
        assert order["final_total_cents"] == 42700
        # 42700 owed less the 20000-cent credit memo
        assert read_account(api, context["account"]["id"])["credit_used_cents"] == 22700


ROCK_SALT = {
    "sku": "SALT-BULK",
    "name": "Bulk Rock Salt",
    "offered_forms": ["BULK"],
    "seasonal_category": "SALT",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": True,
}
SALT_TRUCK = dict(BIG_TRUCK, truck_code="T-404")


def _winterline_claim_under_review(api):
    """A 12000-cent spillage claim already taken up by adjuster-2."""
    context = seed_fulfilled_delivery_order(
        api,
        material=ROCK_SALT,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Winterline Services", "credit_limit_cents": 5000000},
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=4.0,
        truck=SALT_TRUCK,
        window_start="2026-08-02T08:00:00.000Z",
        window_end="2026-08-02T12:00:00.000Z",
        driveway_protection_used=True,
        dispatcher_user_id="planner-2",
    )
    claim = seed_claim(
        api,
        context["order"]["id"],
        context["account"]["id"],
        "SPILLAGE",
        12000,
        delivery_load_id=context["load"]["id"],
        description="Salt spilled across the sidewalk",
        under_review=True,
        adjuster_user_id="adjuster-2",
    )
    return context, claim


def _bounce_claim(api, claim_id, account_id, note, reply):
    """Send a claim back for information and have the contractor answer it."""
    validate_success(
        api.request_info_claim_case(
            claim_id,
            {"info_request_note": note},
            headers=make_claims_adjuster_headers("adjuster-2"),
        ),
        200,
    )
    return validate_success(
        api.provide_info_claim_case(
            claim_id, {"description": reply}, headers=make_contractor_headers(account_id)
        ),
        200,
    )


class TestClaimReviewCycle:
    """The same review state is re-entered twice, and a counter proves it."""

    def test_two_information_round_trips_leave_the_review_counter_at_three(self, api):
        """Every entry into review increments the counter, from either direction.

        PRD 3.7: "The owning `Contractor` -- and only the owning contractor, an attempt by
        any other account being refused with `ERR_ACCOUNT_SCOPE_VIOLATION` -- then
        supplies a replacement `description`, transitioning the claim `INFO_REQUESTED ->
        UNDER_REVIEW` and incrementing `review_round` by 1 again."

        Design: Difficulty/non_linear_state_machine/claim_case_cycles_through_info_requested_twice
        """
        context, claim = _winterline_claim_under_review(api)
        account_id = context["account"]["id"]

        assert claim["status"] == "UNDER_REVIEW"
        assert claim["review_round"] == 1

        after_first = _bounce_claim(
            api,
            claim["id"],
            account_id,
            "Send photos of the sidewalk",
            "Photos attached, 4 metres of walkway affected",
        )
        assert after_first["status"] == "UNDER_REVIEW"
        assert after_first["review_round"] == 2

        after_second = _bounce_claim(
            api,
            claim["id"],
            account_id,
            "Send the cleanup invoice too",
            "Cleanup invoice attached, 12000 cents",
        )
        assert after_second["status"] == "UNDER_REVIEW"
        assert after_second["review_round"] == 3
        assert after_second["info_request_note"] == "Send the cleanup invoice too"

        decided = decide_claim(api, claim["id"], "APPROVE", 12000, adjuster_user_id="adjuster-2")
        assert decided["status"] == "APPROVED"
        # the 40000-cent cleanup cap is not binding on a 12000-cent claim
        assert decided["payable_cents"] == 12000
        assert decided["review_round"] == 3

    def test_information_cannot_be_supplied_once_the_claim_has_been_decided(self, api):
        """Leaving the loop is final: the cycle cannot be re-entered after a decision.

        PRD 2.8: "**Claim state gates** -- on every `POST /claim-cases/{claimCaseId}/*`
        action: `SUBMITTED` is required to start review, `UNDER_REVIEW` to request
        information and to decide, and `INFO_REQUESTED` to provide information -- all
        three failures report `ERR_CLAIM_NOT_REVIEWABLE` -- while settlement requires
        `APPROVED` and reports `ERR_CLAIM_NOT_APPROVED`; both are 409."

        Design: Difficulty/non_linear_state_machine/claim_case_cycles_through_info_requested_twice
        """
        context, claim = _winterline_claim_under_review(api)
        account_id = context["account"]["id"]
        claim_id = claim["id"]

        _bounce_claim(
            api, claim_id, account_id, "Send photos of the sidewalk", "Photos attached"
        )
        _bounce_claim(
            api, claim_id, account_id, "Send the cleanup invoice too", "Cleanup invoice attached"
        )
        decide_claim(api, claim_id, "APPROVE", 12000, adjuster_user_id="adjuster-2")

        rejected = api.provide_info_claim_case(
            claim_id,
            {"description": "One more photo, just in case"},
            headers=make_contractor_headers(account_id),
        )
        validate_error(rejected, ApiErrorId.CLAIM_NOT_REVIEWABLE.value, 409)

        stored = read_claim(api, claim_id)
        assert stored["status"] == "APPROVED"
        assert stored["review_round"] == 3


PINE_MULCH = {
    "sku": "MULCH-PINE",
    "name": "Pine Bark Mulch",
    "offered_forms": ["BULK"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
PINE_TRUCK = dict(BIG_TRUCK, truck_code="T-505")


def _halcyon_dispatched(api):
    """A dispatched 10.00-cubic-yard load against an ALLOCATED order."""
    context = seed_confirmed_delivery_context(
        api,
        material=PINE_MULCH,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Halcyon Landcare", "credit_limit_cents": 5000000},
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=4.0,
        truck=PINE_TRUCK,
    )
    load = seed_planned_load(
        api,
        context["order"]["id"],
        context["truck"]["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T12:00:00.000Z",
    )
    context["load"] = dispatch_load(api, load["id"], "planner-3")
    return context


class TestRefusedLoadRevertsThenRejoins:
    """A turned-away truck drags its order backwards, and a re-booking undoes that."""

    def test_refusal_moves_nothing_but_the_load_and_the_order_status(self, api):
        """The refused branch shares no side effect with the delivered branch.

        PRD 3.5: "This branch is deliberately **disjoint** from the delivered branch:
        `actual_net_cubic_yards` stays null, no inventory is withdrawn, no line or order
        pricing is recomputed, no container record is created, and no credit figure
        moves."

        Design: Difficulty/non_linear_state_machine/delivery_load_refused_then_replanned_reverts_order_allocation
        """
        context = _halcyon_dispatched(api)
        load_id = context["load"]["id"]

        refused = validate_success(
            api.refuse_delivery_load(
                load_id,
                refuse_payload("CUSTOMER_REFUSED"),
                headers=make_dispatch_planner_headers("planner-3"),
            ),
            200,
        )

        assert refused["status"] == "REFUSED"
        assert refused["refusal_reason"] == "CUSTOMER_REFUSED"
        assert refused["actual_net_cubic_yards"] is None

        order = read_order(api, context["order"]["id"])
        # the order is left with no live load, so it falls back off ALLOCATED
        assert order["fulfillment_status"] == "CONFIRMED"
        assert order["final_total_cents"] is None

        assert read_truck(api, context["truck"]["id"])["status"] == "AVAILABLE"

        lot = read_lot(api, context["lot"]["id"])
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        # the reservation survives the refusal because the order is still live
        assert lot["reserved_cubic_yards"] == pytest.approx(10.00, abs=CENTS)

    def test_replanning_a_refused_load_pushes_the_order_forward_again(self, api):
        """Re-booking rejoins the planned state and clears the refusal.

        PRD 3.5: "The replan replaces the truck, window and planned volume, clears
        `refusal_reason` back to null, recomputes `planned_payload_lb` and
        `max_allowed_cubic_yards`, has the order re-evaluate `CONFIRMED -> ALLOCATED`,
        and advances the load's `version`."

        Design: Difficulty/non_linear_state_machine/delivery_load_refused_then_replanned_reverts_order_allocation
        """
        context = _halcyon_dispatched(api)
        load_id = context["load"]["id"]

        validate_success(
            api.refuse_delivery_load(
                load_id,
                refuse_payload("CUSTOMER_REFUSED"),
                headers=make_dispatch_planner_headers("planner-3"),
            ),
            200,
        )

        replanned = validate_success(
            api.replan_delivery_load(
                load_id,
                replan_payload(
                    context["truck"]["id"],
                    10.0,
                    "2026-08-04T08:00:00.000Z",
                    "2026-08-04T12:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers("planner-3"),
            ),
            200,
        )

        assert replanned["status"] == "PLANNED"
        assert replanned["refusal_reason"] is None
        assert_instant_equals(replanned["window_start"], "2026-08-04T08:00:00.000Z")
        assert replanned["planned_payload_lb"] == 10000

        stored = read_load(api, load_id)
        assert stored["status"] == "PLANNED"
        assert read_order(api, context["order"]["id"])["fulfillment_status"] == "ALLOCATED"

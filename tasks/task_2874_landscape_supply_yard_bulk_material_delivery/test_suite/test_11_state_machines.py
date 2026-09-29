"""Transitions the machines allow, the ones they refuse, and the side effects they fire."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    CENTS,
    assert_charge_assembly,
    assert_instant_equals,
    assert_material_order,
    assert_queue_positions,
    assert_will_call_ticket,
)
from test_helpers.factories import (
    create_will_call_order_payload,
    deliver_payload,
    load_ticket_payload,
    safety_ack_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    read_account,
    read_load,
    read_lot,
    read_material,
    read_order,
    read_price_schedule,
    read_ticket,
    read_truck,
    seed_account,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_confirmed_will_call_context,
    seed_material,
    seed_planned_load,
    seed_price_schedule,
    seed_will_call_order,
    seed_will_call_ticket,
    stage_next_ticket,
)
from test_helpers.test_users import (
    make_contractor_headers,
    make_dispatch_planner_headers,
    make_yard_loader_headers,
)

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}
AGGREGATE_PROFILE = {
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
PROMOTION_MULCH = {
    "sku": "MULCH-S1",
    "name": "Promotion Mulch",
    "offered_forms": ["BULK", "BAGGED"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
SEPTEMBER_FIFTEENTH = "2026-09-15T00:00:00.000Z"


class TestPriceSchedulePromotion:
    """A clock advance is the only thing that can promote a waiting price row."""

    def test_advancing_the_clock_promotes_the_waiting_row_and_retires_its_predecessor(self, api):
        """One clock call reports the promotion and performs both halves of the swap.

        PRD 3.1: "A `SCHEDULED` row that has not yet reached its date sits waiting, and a
        `YardAdmin` advancing the logical clock past its `effective_from` promotes it: the
        advance transitions it `SCHEDULED -> EFFECTIVE`, supersedes its predecessor, and
        returns its identifier in the clock response's `promoted_price_schedule_ids`."

        PRD 2.5: "The clock is set by supplying `to_iso8601`, and the response reports the
        resulting `current_utc` together with two arrays describing what the advance
        triggered: `promoted_price_schedule_ids` lists every price row that became effective
        as a consequence of the advance, and `expired_prebuy_contract_ids` lists every
        pre-buy contract whose season ended before the new clock date and which therefore
        expired."

        Design: Corner/state_machines/price_schedule_promotes_on_clock_advance_and_supersedes_predecessor
        """
        material = seed_material(api, **PROMOTION_MULCH)
        july = seed_price_schedule(api, material, **FLAT_PRICE)
        # the guard compares against the material's version as it stands right now
        september = seed_price_schedule(
            api,
            read_material(api, material["id"]),
            effective_from=SEPTEMBER_FIFTEENTH,
            bulk_price_per_cubic_yard_cents=2400,
            bagged_price_per_bag_cents=999,
            seasonal_surcharge_pct=0.0,
        )

        # the July row's date is already behind the default clock, the September row's is not
        assert july["status"] == "EFFECTIVE"
        assert september["status"] == "SCHEDULED"

        clock = advance_clock(api, SEPTEMBER_FIFTEENTH)
        assert_instant_equals(clock["current_utc"], SEPTEMBER_FIFTEENTH)
        assert clock["promoted_price_schedule_ids"] == [september["id"]]
        # no season contract exists at all, so the second cascade has nothing to report
        assert clock["expired_prebuy_contract_ids"] == []

        promoted = read_price_schedule(api, september["id"])
        assert promoted["status"] == "EFFECTIVE"
        assert promoted["version"] == 2

        retired = read_price_schedule(api, july["id"])
        assert retired["status"] == "SUPERSEDED"
        assert retired["version"] == 2


class TestMaterialOrderInitialState:
    """Both of the order's parallel dimensions get their own starting state."""

    def test_a_new_order_starts_draft_and_unbilled_with_nothing_priced(self, api):
        """Two independent axes, two initial states, and no credit consumed.

        PRD 3.4: "A new order begins with `fulfillment_status` `DRAFT` and
        `settlement_status` `UNBILLED`, with every money field at 0, with `final_total_cents`
        and `quote_locked_at` null, and with `paid_amount_cents` and `credit_memo_cents` at
        0."

        PRD 3.3: "`credit_used_cents` is the sum, over the account's orders whose
        `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED` **and** whose
        `settlement_status` is `UNBILLED`, `INVOICED` or `CREDIT_MEMO_ISSUED`, of that
        order's final total where one exists and its quoted total otherwise, minus that
        order's `credit_memo_cents`."

        Design: Corner/state_machines/material_order_starts_in_draft_and_unbilled
        """
        account = seed_account(
            api, business_name="Initial State Landscapes", credit_limit_cents=5000000
        )
        order = validate_success(
            api.create_material_order(
                create_will_call_order_payload(account["id"]),
                headers=make_contractor_headers(account["id"]),
            ),
            201,
        )
        assert_material_order(order)
        assert order["fulfillment_status"] == "DRAFT"
        assert order["settlement_status"] == "UNBILLED"
        assert order["quoted_total_cents"] == 0
        assert order["final_total_cents"] is None
        assert order["quote_locked_at"] is None
        assert order["paid_amount_cents"] == 0
        assert order["credit_memo_cents"] == 0
        assert order["version"] == 1

        # a DRAFT order is outside the reserving set, so it books no credit
        assert read_account(api, account["id"])["credit_used_cents"] == 0


INVALID_TRANSITION_STONE = dict(
    AGGREGATE_PROFILE, sku="AGG-S3", name="Invalid Transition Stone"
)
TANDEM_TRUCK = {
    "truck_code": "TND-S3",
    "axle_class": "TANDEM",
    "max_payload_lb": 40000,
    "bed_capacity_cubic_yards": 12.0,
    "min_driveway_access_class": "CLASS_A",
}


class TestDeliverFromPlanned:
    """`deliver` is wired only from `DISPATCHED`, and the refusal suppresses the cascade."""

    def test_closing_out_a_load_that_never_left_the_yard_is_refused(self, api):
        """No dispatch means no delivery, and none of the close-out side effects run.

        PRD 2.8: "**Load state gates** -- on `POST /delivery-loads` and on every `POST
        /delivery-loads/{deliveryLoadId}/*` action: `PLANNED` is required for dispatch and
        for cancel (`ERR_LOAD_NOT_PLANNED`), `DISPATCHED` for deliver and for refuse
        (`ERR_LOAD_NOT_DISPATCHED`), `REFUSED` for replan (`ERR_LOAD_NOT_REFUSED`), and for
        load creation the owning order's `fulfillment_status` is `CONFIRMED` or `ALLOCATED`
        (`ERR_ORDER_NOT_ALLOCATABLE`); all four are 409."

        PRD 3.5: "Dispatch writes the acting planner's `X-User-ID` to
        `dispatched_by_user_id` -- the record that later bars that planner from adjudicating
        this load's claim -- and moves the truck `AVAILABLE -> IN_SERVICE`, advancing both
        the truck's `version` and the load's."

        Design: Corner/state_machines/deliver_on_a_planned_load_returns_409
        """
        context = seed_confirmed_delivery_context(
            api,
            material=INVALID_TRANSITION_STONE,
            price=FLAT_PRICE,
            lot=STANDARD_LOT,
            account={
                "business_name": "Invalid Transition Grounds",
                "credit_limit_cents": 5000000,
            },
            lines=(("BULK", 8.0),),
            driveway_access_class="CLASS_A",
            delivery_distance_miles=10.0,
            truck=TANDEM_TRUCK,
        )
        load = seed_planned_load(
            api,
            context["order"]["id"],
            context["truck"]["id"],
            8.0,
            "2026-08-02T08:00:00.000Z",
            "2026-08-02T09:00:00.000Z",
        )
        assert load["status"] == "PLANNED"

        rejected = api.deliver_delivery_load(
            load["id"],
            deliver_payload(8.0, driveway_protection_used=False, spillage_cubic_yards=0.0),
            headers=make_dispatch_planner_headers(),
        )
        validate_error(rejected, ApiErrorId.LOAD_NOT_DISPATCHED.value, 409)

        unchanged = read_load(api, load["id"])
        assert unchanged["status"] == "PLANNED"
        assert unchanged["actual_net_cubic_yards"] is None
        # the refused action never advanced the row past its creation version
        assert unchanged["version"] == 1

        # only a dispatch takes the truck out of the yard, and none happened
        assert read_truck(api, context["truck"]["id"])["status"] == "AVAILABLE"
        assert read_lot(api, context["lot"]["id"])[
            "withdrawn_gross_cubic_yards"
        ] == pytest.approx(0.0, abs=CENTS)

        order = read_order(api, context["order"]["id"])
        # the accepted load creation had already promoted the order
        assert order["fulfillment_status"] == "ALLOCATED"
        assert order["final_total_cents"] is None


class TestOrderTerminalLockdown:
    """`CANCELLED` is terminal on the fulfilment axis, so the second cancel finds a wall."""

    def test_a_second_cancel_is_refused_and_does_not_advance_the_version_again(self, api):
        """One cancel, one version bump; the refused retry adds neither.

        PRD 3.4: "Either the `Contractor` or a `YardAdmin` may cancel an order that has not
        yet reached a terminal fulfilment state; an attempt against an order already
        `FULFILLED` or `CANCELLED` is refused with `ERR_ORDER_ALREADY_TERMINAL`, and an
        attempt while any load of the order is `DISPATCHED` is refused with
        `ERR_ORDER_HAS_DISPATCHED_LOAD` -- material already on the road cannot be un-sold."

        PRD 3.4: "Cancelling from `DRAFT` is trivial: the order transitions `DRAFT ->
        CANCELLED` and its `version` advances, with nothing to compensate because nothing
        was ever reserved."

        Design: Corner/state_machines/cancelling_an_already_cancelled_order_returns_409
        """
        account = seed_account(
            api, business_name="Terminal Lockdown Landscapes", credit_limit_cents=5000000
        )
        headers = make_contractor_headers(account["id"])
        order = validate_success(
            api.create_material_order(
                create_will_call_order_payload(account["id"]), headers=headers
            ),
            201,
        )

        cancelled = validate_success(api.cancel_material_order(order["id"], headers=headers), 200)
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["version"] == 2

        again = api.cancel_material_order(order["id"], headers=headers)
        validate_error(again, ApiErrorId.ORDER_ALREADY_TERMINAL.value, 409)

        final = read_order(api, order["id"])
        assert final["fulfillment_status"] == "CANCELLED"
        # bumped once by the accepted cancel and not at all by the refused one
        assert final["version"] == 2
        assert final["settlement_status"] == "UNBILLED"


IDEMPOTENCY_STONE = dict(AGGREGATE_PROFILE, sku="AGG-S5", name="Idempotency Stone")


class TestConfirmIsNotIdempotent:
    """Replaying a confirm would double-book the pile and the credit line, so it is refused."""

    def test_the_second_confirm_is_refused_and_nothing_is_counted_twice(self, api):
        """One reservation, one credit booking, one version bump.

        PRD 2.8: "**Order must be draft** -- on `POST /order-lines` and on `POST
        /material-orders/{materialOrderId}/confirm`, the order's `fulfillment_status` is
        `DRAFT`, else `ERR_ORDER_NOT_DRAFT` (409)."

        PRD 3.2: "`reserved_cubic_yards` records what has been promised but not yet
        withdrawn: the sum, over every order line pinned to this lot whose owning order sits
        in `CONFIRMED` or `ALLOCATED`, of that line's `line_volume_cubic_yards` minus its
        `delivered_volume_cubic_yards`, rounded half up to two decimal places."

        Design: Corner/state_machines/confirming_a_confirmed_order_twice_is_rejected
        """
        context = seed_confirmed_will_call_context(
            api,
            material=IDEMPOTENCY_STONE,
            price=FLAT_PRICE,
            lot=STANDARD_LOT,
            account={"business_name": "Idempotency Grounds", "credit_limit_cents": 5000000},
            lines=(("BULK", 5.0),),
        )
        order_id = context["order"]["id"]
        headers = make_contractor_headers(context["account"]["id"])

        # 5.00 * 2000 with no fee: a WILL_CALL order pays neither the minimum-load fee nor
        # a delivery fee
        assert context["order"]["quoted_total_cents"] == 10000
        assert_charge_assembly(context["order"], 10000)
        assert context["order"]["version"] == 2

        replay = api.confirm_material_order(order_id, headers=headers)
        validate_error(replay, ApiErrorId.ORDER_NOT_DRAFT.value, 409)

        order = read_order(api, order_id)
        assert order["fulfillment_status"] == "CONFIRMED"
        assert order["quoted_total_cents"] == 10000
        assert order["version"] == 2

        # the single line is counted once, not once per confirm attempt
        assert read_lot(api, context["lot"]["id"])["reserved_cubic_yards"] == pytest.approx(
            5.00, abs=CENTS
        )
        assert read_account(api, context["account"]["id"])["credit_used_cents"] == 10000


SAFETY_STONE = dict(AGGREGATE_PROFILE, sku="AGG-S6", name="Safety Stone")
STAGING_WINDOW = ("2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z")
CLOCK_AT_REST = "2026-08-01T00:00:00.000Z"


class TestSafetyAcknowledgementPrecondition:
    """The gate reads the flag in the request body, not merely the fact that it was sent."""

    def test_an_unconfirmed_ppe_check_is_refused_and_nothing_is_stored(self, api):
        """The briefing code sent alongside a false flag is discarded with it.

        PRD 3.6: "When `ppe_confirmed` in the request is not true, the acknowledgement is
        refused with `ERR_SAFETY_ACK_REQUIRED`; when it is true, both values are stored and
        the ticket transitions `STAGED -> LOADING`."

        PRD 2.8: "**Ticket state gates** -- on every `POST
        /will-call-tickets/{willCallTicketId}/*` action: `STAGED` is required for safety
        acknowledgement (`ERR_TICKET_NOT_STAGED`), `LOADING` for loading
        (`ERR_TICKET_NOT_LOADING`), `LOADED` for release (`ERR_TICKET_NOT_LOADED`), and
        `QUEUED` or `STAGED` for cancellation (`ERR_TICKET_NOT_CANCELLABLE`); all four are
        409."

        Design: Corner/state_machines/safety_ack_with_ppe_false_is_rejected_and_ticket_stays_staged
        """
        context = seed_confirmed_will_call_context(
            api,
            material=SAFETY_STONE,
            price=FLAT_PRICE,
            lot=STANDARD_LOT,
            account={"business_name": "Safety Grounds", "credit_limit_cents": 5000000},
            lines=(("BULK", 5.0),),
        )
        ticket = seed_will_call_ticket(
            api, context["order"]["id"], context["account"]["id"], CLOCK_AT_REST
        )
        staged = stage_next_ticket(api, *STAGING_WINDOW, loader_user_id="loader-s6")
        assert staged["id"] == ticket["id"]
        assert staged["status"] == "STAGED"

        loader = make_yard_loader_headers("loader-s6")
        rejected = api.safety_ack_will_call_ticket(
            ticket["id"],
            safety_ack_payload(ppe_confirmed=False, safety_briefing_code="BRIEF-2026-08"),
            headers=loader,
        )
        validate_error(rejected, ApiErrorId.SAFETY_ACK_REQUIRED.value, 422)

        held = read_ticket(api, ticket["id"])
        assert held["status"] == "STAGED"
        assert held["ppe_confirmed"] is False
        # the code travels with the flag, so a refused acknowledgement stores neither
        assert held["safety_briefing_code"] is None

        # the ticket never reached LOADING, so the next step in the chain is closed too
        blocked = api.load_will_call_ticket(
            ticket["id"], load_ticket_payload(5.0), headers=loader
        )
        validate_error(blocked, ApiErrorId.TICKET_NOT_LOADING.value, 409)


QUEUE_STONE = dict(AGGREGATE_PROFILE, sku="AGG-S7", name="Queue Stone")


class TestStageNextSideEffects:
    """One staging call fires the winner's transition, the renumbering and the promotion."""

    def test_staging_the_head_of_the_queue_renumbers_the_survivors_and_allocates_its_order(
        self, api
    ):
        """The two tickets left behind become 1 and 2 rather than keeping 2 and 3.

        PRD 3.6: "Staging then transitions the selected ticket `QUEUED -> STAGED`, stores
        the two window bounds, writes the acting loader's `X-User-ID` to `staged_by_user_id`,
        pins `inventory_lot_id` to the lot allocated to the order's earliest-created bulk
        line, nulls that ticket's `queue_position` and renumbers every remaining queued
        ticket, transitions the order `CONFIRMED -> ALLOCATED` when this is its first
        staged ticket, and advances the ticket's `version`."

        PRD 3.6: "A ticket's `queue_position` is its 1-based rank among **all** tickets in
        the yard whose `status` is `QUEUED`, sorted by `priority_class` descending, then by
        `requested_pickup_at` ascending, then by `created_at` ascending as the final
        discriminator; a record's `id` is never consulted as a tie-break."

        Design: Corner/state_machines/stage_next_renumbers_the_remaining_queue_and_allocates_the_order
        """
        catalogue = seed_catalogue(
            api,
            material=QUEUE_STONE,
            price=FLAT_PRICE,
            lot={"gross_cubic_yards": 200.0, "moisture_pct_at_intake": 15.0},
        )
        account = seed_account(
            api, business_name="Queue Grounds", credit_limit_cents=9000000
        )
        orders = [
            seed_will_call_order(
                api,
                account,
                catalogue["material"]["id"],
                lines=(("BULK", 4.0),),
                confirm=True,
            )["order"]
            for _ in range(3)
        ]
        tickets = [
            seed_will_call_ticket(api, order["id"], account["id"], requested_pickup_at)
            for order, requested_pickup_at in zip(
                orders,
                (
                    "2026-07-31T06:00:00.000Z",
                    "2026-07-31T07:00:00.000Z",
                    "2026-07-31T08:00:00.000Z",
                ),
            )
        ]

        # no line draws on a season contract, so all three share priority_class and the
        # requested pickup instant alone orders them
        assert_queue_positions(
            [read_ticket(api, ticket["id"]) for ticket in tickets],
            {tickets[0]["id"]: 1, tickets[1]["id"]: 2, tickets[2]["id"]: 3},
        )
        for order in orders:
            assert read_order(api, order["id"])["fulfillment_status"] == "CONFIRMED"

        staged = stage_next_ticket(api, *STAGING_WINDOW, loader_user_id="loader-s7")
        assert_will_call_ticket(staged)
        assert staged["id"] == tickets[0]["id"]
        assert staged["status"] == "STAGED"
        assert staged["queue_position"] is None
        assert staged["staged_by_user_id"] == "loader-s7"
        assert staged["inventory_lot_id"] == catalogue["lot"]["id"]
        assert_instant_equals(staged["staging_window_start"], STAGING_WINDOW[0])
        assert_instant_equals(staged["staging_window_end"], STAGING_WINDOW[1])

        assert_queue_positions(
            [read_ticket(api, ticket["id"]) for ticket in tickets[1:]],
            {tickets[1]["id"]: 1, tickets[2]["id"]: 2},
        )

        assert read_order(api, orders[0]["id"])["fulfillment_status"] == "ALLOCATED"
        assert read_order(api, orders[1]["id"])["fulfillment_status"] == "CONFIRMED"
        assert read_order(api, orders[2]["id"])["fulfillment_status"] == "CONFIRMED"

        # staging pins a lot but withdraws nothing, so the three confirms still hold 12.00
        assert read_lot(api, catalogue["lot"]["id"])[
            "reserved_cubic_yards"
        ] == pytest.approx(12.00, abs=CENTS)

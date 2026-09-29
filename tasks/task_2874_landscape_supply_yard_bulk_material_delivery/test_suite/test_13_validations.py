"""Guard rails probed one rung at a time, each request refused by the first rule that fails."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_charge_assembly, assert_credit_position
from test_helpers.factories import (
    create_claim_case_payload,
    create_delivery_load_payload,
    create_job_purchase_order_payload,
    create_material_payload,
    create_order_line_payload,
    create_price_schedule_payload,
    create_will_call_order_payload,
    create_will_call_ticket_payload,
    decide_claim_payload,
    deliver_payload,
    load_ticket_payload,
    receive_container_payload,
    replan_payload,
    safety_ack_payload,
    settle_order_payload,
    stage_next_payload,
)
from test_helpers.fixtures import (
    acknowledge_safety,
    advance_clock,
    decide_claim,
    deliver_load,
    dispatch_load,
    find_container_return,
    forfeit_containers,
    invoice_order,
    load_ticket,
    read_account,
    read_claim,
    read_container_return,
    read_load,
    read_lot,
    read_material,
    read_order,
    read_prebuy,
    read_price_schedule,
    read_ticket,
    read_truck,
    receive_containers,
    release_ticket,
    seed_account,
    seed_catalogue,
    seed_claim,
    seed_delivery_order,
    seed_dispatched_load,
    seed_planned_load,
    seed_prebuy,
    seed_purchase_order,
    seed_truck,
    seed_will_call_order,
    seed_will_call_ticket,
    settle_order,
    stage_next_ticket,
)
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_credit_manager_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
    make_yard_loader_headers,
)

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}
BIG_LOT = {"gross_cubic_yards": 200.0, "moisture_pct_at_intake": 15.0}


def _stone(sku: str, name: str, **overrides):
    """One aggregate profile, cloned per test so nothing is shared across scenarios."""
    profile = {
        "sku": sku,
        "name": name,
        "offered_forms": ["BULK"],
        "seasonal_category": "AGGREGATE",
        "density_lb_per_cubic_yard": 1000,
        "shrinkage_factor": 0.10,
        "moisture_pct": 15.0,
        "unit_bag_cubic_yards": 0.037,
        "prebuy_eligible": False,
    }
    profile.update(overrides)
    return profile


def _tri(truck_code: str):
    """A tri-axle with headroom on every gate, so only the rule under test can fire."""
    return {
        "truck_code": truck_code,
        "axle_class": "TRI_AXLE",
        "max_payload_lb": 60000,
        "bed_capacity_cubic_yards": 20.0,
        "min_driveway_access_class": "CLASS_A",
    }


def _loads_for_order(api, order_id: str):
    return validate_paginated(
        api.list_delivery_loads(
            headers=make_dispatch_planner_headers(), params={"material_order_id": order_id}
        )
    )


def _lifecycle_yard(api):
    """One draft order and one live order whose single load is already on the road."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V1", "Lifecycle Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Lifecycle Landscapes", credit_limit_cents=5000000
    )
    draft = seed_delivery_order(
        api,
        account,
        material_id,
        lines=(("BULK", 5.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=5.0,
        delivery_address="1 Lifecycle Way",
    )
    live = seed_delivery_order(
        api,
        account,
        material_id,
        lines=(("BULK", 5.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=5.0,
        delivery_address="2 Lifecycle Way",
        confirm=True,
    )
    truck = seed_truck(api, **_tri("TRI-V1"))
    load = seed_dispatched_load(
        api,
        live["order"]["id"],
        truck["id"],
        5.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
        "planner-v1",
    )
    return {
        "account": account,
        "draft": draft["order"],
        "live": live["order"],
        "truck": truck,
        "load": load,
    }


class TestOrderLifecycleGuards:
    """Billing, cancelling and load planning each read a different order state field."""

    def test_invoice_cancel_and_plan_are_each_refused_from_the_state_they_find(self, api):
        """Three separate rungs fire on the same pair of orders, and nothing moves.

        PRD 2.8: "**Billing eligibility** -- on `POST
        /material-orders/{materialOrderId}/invoice` the order's `fulfillment_status` is
        `FULFILLED`, and on `POST /material-orders/{materialOrderId}/settle` its
        `settlement_status` is either `INVOICED` or `CREDIT_MEMO_ISSUED`; either failure
        yields `ERR_ORDER_NOT_FULFILLED` (409)."

        PRD 2.8: "**No dispatched load at cancel** -- on `POST
        /material-orders/{materialOrderId}/cancel`, no load of the order sits in
        `DISPATCHED`, else `ERR_ORDER_HAS_DISPATCHED_LOAD` (409)."

        PRD 2.8: "and for load creation the owning order's `fulfillment_status` is
        `CONFIRMED` or `ALLOCATED` (`ERR_ORDER_NOT_ALLOCATABLE`); all four are 409."

        Design: Corner/validations/order_lifecycle_guards_return_409_on_the_wrong_state
        """
        context = _lifecycle_yard(api)
        live_id = context["live"]["id"]
        account_id = context["account"]["id"]

        validate_error(
            api.invoice_material_order(live_id, headers=make_credit_manager_headers()),
            ApiErrorId.ORDER_NOT_FULFILLED.value,
            409,
        )
        validate_error(
            api.cancel_material_order(live_id, headers=make_contractor_headers(account_id)),
            ApiErrorId.ORDER_HAS_DISPATCHED_LOAD.value,
            409,
        )
        validate_error(
            api.create_delivery_load(
                create_delivery_load_payload(
                    context["draft"]["id"],
                    context["truck"]["id"],
                    5.0,
                    "2026-08-02T13:00:00.000Z",
                    "2026-08-02T14:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            ApiErrorId.ORDER_NOT_ALLOCATABLE.value,
            409,
        )

        live = read_order(api, live_id)
        assert live["fulfillment_status"] == "ALLOCATED"
        assert live["settlement_status"] == "UNBILLED"
        # 10000 bulk, the 7500 minimum-load fee, the CLASS_A tri-axle base and 5 miles
        assert live["quoted_total_cents"] == 33125
        assert_charge_assembly(live, 33125)

        assert read_order(api, context["draft"]["id"])["fulfillment_status"] == "DRAFT"
        assert read_load(api, context["load"]["id"])["status"] == "DISPATCHED"

        _, meta = _loads_for_order(api, context["draft"]["id"])
        assert meta["total_count"] == 0


def _load_guard_yard(api):
    """Two windows booked on one truck, the earlier of them already dispatched."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V2", "Load Guard Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api, business_name="Load Guard Landscapes", credit_limit_cents=5000000
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=6.0,
        delivery_address="2 Guard Rd",
        confirm=True,
    )
    truck = seed_truck(api, **_tri("TRI-V2"))
    load_a = seed_planned_load(
        api,
        seeded["order"]["id"],
        truck["id"],
        5.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
    )
    load_b = seed_planned_load(
        api,
        seeded["order"]["id"],
        truck["id"],
        5.0,
        "2026-08-02T10:00:00.000Z",
        "2026-08-02T11:00:00.000Z",
    )
    dispatch_load(api, load_a["id"], "planner-v2")
    return {"order": seeded["order"], "truck": truck, "load_a": load_a, "load_b": load_b}


class TestLoadActionGuards:
    """A dispatched load cannot be dispatched again and a planned load cannot be replanned."""

    def test_redispatch_and_replan_are_refused_from_the_status_they_find(self, api):
        """Each load action names one required status, and neither load holds it.

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

        Design: Corner/validations/load_action_guards_are_rejected_from_the_wrong_status
        """
        context = _load_guard_yard(api)

        validate_error(
            api.dispatch_delivery_load(
                context["load_a"]["id"], headers=make_dispatch_planner_headers("planner-v2")
            ),
            ApiErrorId.LOAD_NOT_PLANNED.value,
            409,
        )
        validate_error(
            api.replan_delivery_load(
                context["load_b"]["id"],
                replan_payload(
                    context["truck"]["id"],
                    5.0,
                    "2026-08-03T08:00:00.000Z",
                    "2026-08-03T09:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers("planner-v2"),
            ),
            ApiErrorId.LOAD_NOT_REFUSED.value,
            409,
        )

        load_a = read_load(api, context["load_a"]["id"])
        assert load_a["status"] == "DISPATCHED"
        # creation then dispatch, and the refused re-dispatch adds nothing
        assert load_a["version"] == 2
        assert load_a["dispatched_by_user_id"] == "planner-v2"

        load_b = read_load(api, context["load_b"]["id"])
        assert load_b["status"] == "PLANNED"
        assert load_b["window_start"].startswith("2026-08-02T10:00:00")

        assert read_truck(api, context["truck"]["id"])["status"] == "IN_SERVICE"


def _ticket_guard_yard(api):
    """Three tickets left in three different states: queued, released and staged."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V3", "Ticket Guard Stone"), price=FLAT_PRICE, lot=BIG_LOT
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Ticket Guard Landscapes", credit_limit_cents=9000000
    )
    orders = [
        seed_will_call_order(
            api, account, material_id, lines=(("BULK", 4.0),), confirm=True
        )["order"]
        for _ in range(3)
    ]
    ticket_a = seed_will_call_ticket(
        api, orders[0]["id"], account["id"], "2026-08-02T06:00:00.000Z"
    )
    ticket_b = seed_will_call_ticket(
        api, orders[1]["id"], account["id"], "2026-07-31T07:00:00.000Z"
    )
    ticket_c = seed_will_call_ticket(
        api, orders[2]["id"], account["id"], "2026-07-31T08:00:00.000Z"
    )

    staged_b = stage_next_ticket(
        api, "2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z", "loader-v3"
    )
    assert staged_b["id"] == ticket_b["id"]
    acknowledge_safety(api, ticket_b["id"], "loader-v3", safety_briefing_code="BRIEF-V3")
    load_ticket(api, ticket_b["id"], 4.0, None, "loader-v3")
    release_ticket(api, ticket_b["id"], "loader-v3")

    staged_c = stage_next_ticket(
        api, "2026-08-01T13:00:00.000Z", "2026-08-01T14:00:00.000Z", "loader-v3"
    )
    assert staged_c["id"] == ticket_c["id"]

    return {
        "account": account,
        "orders": orders,
        "ticket_a": ticket_a,
        "ticket_b": ticket_b,
        "ticket_c": ticket_c,
    }


class TestTicketActionGuards:
    """Four bay actions, four required statuses, and every one of them missed."""

    def test_every_bay_action_is_refused_from_the_status_it_finds(self, api):
        """A queued ticket cannot be briefed, a staged one cannot be loaded or released.

        PRD 2.8: "**Ticket state gates** -- on every `POST
        /will-call-tickets/{willCallTicketId}/*` action: `STAGED` is required for safety
        acknowledgement (`ERR_TICKET_NOT_STAGED`), `LOADING` for loading
        (`ERR_TICKET_NOT_LOADING`), `LOADED` for release (`ERR_TICKET_NOT_LOADED`), and
        `QUEUED` or `STAGED` for cancellation (`ERR_TICKET_NOT_CANCELLABLE`); all four are
        409."

        PRD 3.6: "`RELEASED` and `CANCELLED` are the queue's two terminal states."

        Design: Corner/validations/ticket_action_guards_are_rejected_from_the_wrong_status
        """
        context = _ticket_guard_yard(api)
        loader = make_yard_loader_headers("loader-v3")

        validate_error(
            api.safety_ack_will_call_ticket(
                context["ticket_a"]["id"],
                safety_ack_payload(safety_briefing_code="BRIEF-V3"),
                headers=loader,
            ),
            ApiErrorId.TICKET_NOT_STAGED.value,
            409,
        )
        validate_error(
            api.load_will_call_ticket(
                context["ticket_c"]["id"], load_ticket_payload(4.0), headers=loader
            ),
            ApiErrorId.TICKET_NOT_LOADING.value,
            409,
        )
        validate_error(
            api.release_will_call_ticket(context["ticket_c"]["id"], headers=loader),
            ApiErrorId.TICKET_NOT_LOADED.value,
            409,
        )
        validate_error(
            api.cancel_will_call_ticket(context["ticket_b"]["id"], headers=loader),
            ApiErrorId.TICKET_NOT_CANCELLABLE.value,
            409,
        )

        assert read_ticket(api, context["ticket_a"]["id"])["status"] == "QUEUED"
        assert read_ticket(api, context["ticket_b"]["id"])["status"] == "RELEASED"
        assert read_ticket(api, context["ticket_c"]["id"])["status"] == "STAGED"

        released_order = read_order(api, context["orders"][1]["id"])
        assert released_order["fulfillment_status"] == "FULFILLED"
        # 4.00 loaded at 2000 a yard, with no fee and no haul on a will-call pickup
        assert released_order["final_total_cents"] == 8000


def _claim_guard_yard(api):
    """One invoiced delivery carrying an approved-but-unpayable claim and a fresh one."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V4", "Claim Guard Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api, business_name="Claim Guard Landscapes", credit_limit_cents=5000000
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=5.0,
        delivery_address="4 Claim Ct",
        confirm=True,
    )
    order_id = seeded["order"]["id"]
    truck = seed_truck(api, **_tri("TRI-V4"))
    load = seed_dispatched_load(
        api,
        order_id,
        truck["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T10:00:00.000Z",
        "planner-v4",
    )
    deliver_load(api, load["id"], 10.0, True, 0.0, "planner-v4")
    invoice_order(api, order_id)

    damage = seed_claim(
        api,
        order_id,
        account["id"],
        "DRIVEWAY_DAMAGE",
        10000,
        delivery_load_id=load["id"],
        under_review=True,
        adjuster_user_id="adjuster-v4",
        description="Hairline cracking along the apron where the mats were laid.",
    )
    damage = decide_claim(
        api, damage["id"], "APPROVE", approved_amount_cents=10000, adjuster_user_id="adjuster-v4"
    )
    short = seed_claim(
        api,
        order_id,
        account["id"],
        "SHORT_LOAD",
        5000,
        description="The load measured light against the ticketed volume.",
    )
    return {
        "account": account,
        "order": seeded["order"],
        "load": load,
        "damage": damage,
        "short": short,
    }


class TestClaimActionGuardsAndMoneyCeilings:
    """The adjudication cycle refuses out-of-order steps, then refuses impossible money."""

    def test_review_steps_and_approval_arithmetic_are_both_refused(self, api):
        """A submitted claim is neither reviewable nor settleable, and 6000 exceeds 5000.

        PRD 2.8: "**Claim state gates** -- on every `POST /claim-cases/{claimCaseId}/*`
        action: `SUBMITTED` is required to start review, `UNDER_REVIEW` to request
        information and to decide, and `INFO_REQUESTED` to provide information -- all three
        failures report `ERR_CLAIM_NOT_REVIEWABLE` -- while settlement requires `APPROVED`
        and reports `ERR_CLAIM_NOT_APPROVED`; both are 409."

        PRD 2.8: "**Claim arithmetic** -- at `POST /claim-cases/{claimCaseId}/decide`,
        `approved_amount_cents` is at most `claimed_amount_cents`
        (`ERR_APPROVED_EXCEEDS_CLAIM`), and at `POST /claim-cases/{claimCaseId}/settle` the
        claim's `payable_cents` is greater than 0 (`ERR_CLAIM_NOT_PAYABLE`); both are 422."

        PRD 3.7: "For a `DRIVEWAY_DAMAGE` claim the yard applies a
        one-hundred-and-fifty-dollar deductible, except that the deductible is **waived
        entirely** -- treated as zero -- when the claim names a `delivery_load_id` whose
        `driveway_protection_used` is false, because a crew that skipped the mats does not
        get to bill the contractor for the first hundred and fifty dollars of the
        consequence; `payable_cents` is then the `approved_amount_cents` minus the applicable
        deductible, floored at zero so it never goes negative."

        Design: Corner/validations/claim_action_guards_and_money_ceilings_are_rejected
        """
        context = _claim_guard_yard(api)
        adjuster = make_claims_adjuster_headers("adjuster-v4")
        short_id = context["short"]["id"]

        # the mats went down, so the whole 10000 approval is swallowed by the deductible
        assert context["damage"]["status"] == "APPROVED"
        assert context["damage"]["payable_cents"] == 0

        validate_error(
            api.request_info_claim_case(
                short_id, {"info_request_note": "Send the weigh ticket."}, headers=adjuster
            ),
            ApiErrorId.CLAIM_NOT_REVIEWABLE.value,
            409,
        )
        validate_error(
            api.settle_claim_case(short_id, headers=make_credit_manager_headers()),
            ApiErrorId.CLAIM_NOT_APPROVED.value,
            409,
        )

        under_review = validate_success(
            api.start_review_claim_case(short_id, headers=adjuster), 200
        )
        assert under_review["status"] == "UNDER_REVIEW"
        assert under_review["review_round"] == 1

        validate_error(
            api.decide_claim_case(
                short_id, decide_claim_payload("APPROVE", 6000), headers=adjuster
            ),
            ApiErrorId.APPROVED_EXCEEDS_CLAIM.value,
            422,
        )
        assert read_claim(api, short_id)["status"] == "UNDER_REVIEW"

        validate_error(
            api.settle_claim_case(
                context["damage"]["id"], headers=make_credit_manager_headers()
            ),
            ApiErrorId.CLAIM_NOT_PAYABLE.value,
            422,
        )

        order = read_order(api, context["order"]["id"])
        assert order["settlement_status"] == "INVOICED"
        assert order["credit_memo_cents"] == 0


def _prebuy_guard_yard(api):
    """One live season with 5.00 yards on it, one dead season still in draft."""
    catalogue = seed_catalogue(
        api,
        material=_stone(
            "SALT-V5", "Prebuy Guard Salt", seasonal_category="SALT", prebuy_eligible=True
        ),
        price=FLAT_PRICE,
        lot=BIG_LOT,
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Prebuy Guard Landscapes", credit_limit_cents=5000000
    )
    live = seed_prebuy(api, account, material_id, 1800, 5.0, "2026-06-01", "2026-09-30")
    dead = seed_prebuy(
        api, account, material_id, 1700, 20.0, "2026-04-01", "2026-05-31", activate=False
    )
    overdraw = seed_will_call_order(api, account, material_id, lines=(("BULK", 8.0, True),))
    modest = seed_will_call_order(api, account, material_id, lines=(("BULK", 4.0, True),))
    return {
        "account": account,
        "live": live,
        "dead": dead,
        "overdraw": overdraw["order"],
        "modest": modest["order"],
    }


class TestPreBuyGuards:
    """Activation, season currency and the drawable balance are three separate rungs."""

    def test_double_activation_a_closed_season_and_an_overdraw_are_all_refused(self, api):
        """Then the clock walks past both seasons and the last confirm loses its contract.

        PRD 2.8: "**Other lifecycle gates** -- activation on `POST
        /prebuy-contracts/{preBuyContractId}/activate` requires `DRAFT`
        (`ERR_PREBUY_NOT_DRAFT`); `POST /container-returns/{containerReturnId}/receive` and
        `POST /container-returns/{containerReturnId}/forfeit` require a status that is neither
        `CLOSED` nor `FORFEITED` (`ERR_CONTAINER_RETURN_CLOSED`); `POST
        /job-purchase-orders/{jobPurchaseOrderId}/close` requires `OPEN`
        (`ERR_PO_NOT_OPEN`); all three are 409."

        PRD 2.8: "and activation at `POST /prebuy-contracts/{preBuyContractId}/activate`
        requires the clock date to be at or before `season_end_date`; else
        `ERR_PREBUY_OUT_OF_SEASON` (422)."

        PRD 2.8: "**Pre-buy balance** -- at confirm, a referenced contract's
        `remaining_cubic_yards` is at least the line's `line_volume_cubic_yards`, else
        `ERR_PREBUY_BALANCE_EXCEEDED` (422)."

        PRD 3.3: "Advancing the logical clock past `season_end_date` expires the contract,
        taking either the `DRAFT -> EXPIRED` step or the `ACTIVE -> EXPIRED` step with
        identical effect, and each expired contract's identifier appears in the clock
        response's `expired_prebuy_contract_ids`."

        Design: Corner/validations/prebuy_guards_reject_double_activation_closed_season_and_overdraw
        """
        context = _prebuy_guard_yard(api)
        account_id = context["account"]["id"]
        admin = make_yard_admin_headers()

        validate_error(
            api.activate_prebuy_contract(context["live"]["id"], headers=admin),
            ApiErrorId.PREBUY_NOT_DRAFT.value,
            409,
        )
        validate_error(
            api.activate_prebuy_contract(context["dead"]["id"], headers=admin),
            ApiErrorId.PREBUY_OUT_OF_SEASON.value,
            422,
        )
        validate_error(
            api.confirm_material_order(
                context["overdraw"]["id"], headers=make_contractor_headers(account_id)
            ),
            ApiErrorId.PREBUY_BALANCE_EXCEEDED.value,
            422,
        )
        assert read_order(api, context["overdraw"]["id"])["fulfillment_status"] == "DRAFT"
        assert read_prebuy(api, context["live"]["id"])["remaining_cubic_yards"] == pytest.approx(
            5.0, abs=CENTS
        )

        clock = advance_clock(api, "2026-10-01T00:00:00.000Z")
        assert set(clock["expired_prebuy_contract_ids"]) == {
            context["live"]["id"],
            context["dead"]["id"],
        }
        assert read_prebuy(api, context["live"]["id"])["status"] == "EXPIRED"
        assert read_prebuy(api, context["dead"]["id"])["status"] == "EXPIRED"

        validate_error(
            api.confirm_material_order(
                context["modest"]["id"], headers=make_contractor_headers(account_id)
            ),
            ApiErrorId.PREBUY_NOT_ACTIVE.value,
            409,
        )
        assert read_order(api, context["modest"]["id"])["fulfillment_status"] == "DRAFT"


def _uniqueness_yard(api):
    """An empty will-call order, a confirmed will-call order and a draft delivery order."""
    catalogue = seed_catalogue(
        api,
        material=_stone("MULCH-V6", "Uniqueness Mulch", seasonal_category="MULCH"),
        price=FLAT_PRICE,
        lot=STANDARD_LOT,
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Uniqueness Landscapes", credit_limit_cents=5000000
    )
    purchase_order = seed_purchase_order(
        api, account, 500000, po_number="PO-V6-1001", job_code="JOB-A"
    )
    empty = seed_will_call_order(api, account, material_id, lines=())
    will_call = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 4.0),), confirm=True
    )
    delivery = seed_delivery_order(
        api,
        account,
        material_id,
        lines=(("BULK", 4.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=3.0,
        delivery_address="6 Unique St",
    )
    truck = seed_truck(api, **_tri("TRI-V6"))
    return {
        "account": account,
        "material": catalogue["material"],
        "purchase_order": purchase_order,
        "empty": empty["order"],
        "will_call": will_call["order"],
        "delivery": delivery["order"],
        "truck": truck,
    }


class TestUniquenessModeAndEmptyOrderRules:
    """Six catalogue-and-mode rules share one rung and all six report 422."""

    def test_duplicate_keys_wrong_modes_and_an_empty_order_are_all_refused(self, api):
        """A repeated sku, a repeated po number, a form, two modes and a lineless confirm.

        PRD 2.8: "**Catalogue and mode constraints** -- the order carries at least one line
        at `POST /material-orders/{materialOrderId}/confirm` (`ERR_ORDER_HAS_NO_LINES`);
        `sku` is unique at `POST /materials` (`ERR_DUPLICATE_SKU`); `po_number` is unique
        within its account at `POST /job-purchase-orders` (`ERR_DUPLICATE_PO_NUMBER`); a
        line's `form` appears in the material's `offered_forms` at `POST /order-lines`
        (`ERR_FORM_NOT_OFFERED`); a ticket requires a `WILL_CALL` order at `POST
        /will-call-tickets` (`ERR_WILL_CALL_MODE_REQUIRED`); and a load requires a `DELIVERY`
        order at `POST /delivery-loads` (`ERR_DELIVERY_MODE_REQUIRED`); all six are 422."

        Design: Corner/validations/uniqueness_mode_and_empty_order_rules_are_rejected
        """
        context = _uniqueness_yard(api)
        account_id = context["account"]["id"]
        contractor = make_contractor_headers(account_id)

        validate_error(
            api.create_material(
                create_material_payload(
                    sku="MULCH-V6",
                    name="Duplicate Mulch",
                    seasonal_category="MULCH",
                    density_lb_per_cubic_yard=900,
                ),
                headers=make_yard_admin_headers(),
            ),
            ApiErrorId.DUPLICATE_SKU.value,
            422,
        )
        _, materials_meta = validate_paginated(
            api.list_materials(headers=make_yard_admin_headers())
        )
        assert materials_meta["total_count"] == 1

        validate_error(
            api.create_job_purchase_order(
                create_job_purchase_order_payload(
                    account_id, 500000, po_number="PO-V6-1001", job_code="JOB-B"
                ),
                headers=contractor,
            ),
            ApiErrorId.DUPLICATE_PO_NUMBER.value,
            422,
        )

        validate_error(
            api.create_order_line(
                create_order_line_payload(
                    context["delivery"]["id"], context["material"]["id"], "BAGGED", 10
                ),
                headers=contractor,
            ),
            ApiErrorId.FORM_NOT_OFFERED.value,
            422,
        )
        validate_error(
            api.create_will_call_ticket(
                create_will_call_ticket_payload(
                    context["delivery"]["id"], "2026-08-01T09:00:00.000Z"
                ),
                headers=contractor,
            ),
            ApiErrorId.WILL_CALL_MODE_REQUIRED.value,
            422,
        )
        validate_error(
            api.create_delivery_load(
                create_delivery_load_payload(
                    context["will_call"]["id"],
                    context["truck"]["id"],
                    4.0,
                    "2026-08-02T08:00:00.000Z",
                    "2026-08-02T09:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            ApiErrorId.DELIVERY_MODE_REQUIRED.value,
            422,
        )
        validate_error(
            api.confirm_material_order(context["empty"]["id"], headers=contractor),
            ApiErrorId.ORDER_HAS_NO_LINES.value,
            422,
        )
        assert read_order(api, context["empty"]["id"])["fulfillment_status"] == "DRAFT"


def _referential_yard(api):
    """Two accounts, one of which needs a purchase order, and a season on a plain stone."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V7", "Referential Stone"), price=FLAT_PRICE, lot=BIG_LOT
    )
    material_id = catalogue["material"]["id"]
    account_a = seed_account(
        api, business_name="Referential A", credit_limit_cents=5000000, po_required=True
    )
    account_b = seed_account(api, business_name="Referential B", credit_limit_cents=5000000)
    # account_a has po_required true, so its only creatable order is a tagged one
    envelope_a = seed_purchase_order(
        api, account_a, 500000, po_number="PO-V7-1001", job_code="JOB-A1"
    )
    tagged = seed_will_call_order(
        api,
        account_a,
        material_id,
        lines=(("BULK", 4.0),),
        job_purchase_order_id=envelope_a["id"],
    )
    purchase_order = seed_purchase_order(
        api, account_b, 500000, po_number="PO-V7-2001", job_code="JOB-B1"
    )
    stocked = seed_will_call_order(
        api, account_b, material_id, lines=(("BULK", 4.0),), confirm=True
    )
    ticket = seed_will_call_ticket(
        api, stocked["order"]["id"], account_b["id"], "2026-07-31T07:00:00.000Z"
    )
    bare = seed_will_call_order(api, account_b, material_id, lines=())
    season = seed_prebuy(
        api, account_b, material_id, 1800, 10.0, "2026-06-01", "2026-12-31", activate=False
    )
    return {
        "material": catalogue["material"],
        "account_a": account_a,
        "account_b": account_b,
        "envelope_a": envelope_a,
        "tagged": tagged["order"],
        "purchase_order": purchase_order,
        "stocked": stocked["order"],
        "ticket": ticket,
        "bare": bare["order"],
        "season": season,
    }


class TestReferentialConfigRules:
    """Four coherence rules, each reading a second entity before it will accept the first."""

    def test_missing_po_foreign_account_po_stray_target_and_dead_season_are_refused(self, api):
        """A budget envelope belongs to one account and a claim target to one order.

        PRD 2.8: "**Referential coherence** -- a `po_required` account's order carries
        `job_purchase_order_id` at `POST /material-orders` and at `POST
        /material-orders/{materialOrderId}/confirm` (`ERR_PO_REQUIRED`); a supplied purchase
        order belongs to the order's own account (`ERR_PO_ACCOUNT_MISMATCH`); a claim's
        `delivery_load_id` or `will_call_ticket_id` belongs to the claim's
        `material_order_id` at `POST /claim-cases` (`ERR_CLAIM_TARGET_MISMATCH`); and a
        pre-buy contract's material has `prebuy_eligible` true at `POST
        /prebuy-contracts/{preBuyContractId}/activate`
        (`ERR_MATERIAL_NOT_PREBUY_ELIGIBLE`); all four are 422."

        Design: Corner/validations/referential_config_rules_are_rejected
        """
        context = _referential_yard(api)
        account_a_id = context["account_a"]["id"]
        account_b_id = context["account_b"]["id"]

        validate_error(
            api.create_material_order(
                create_will_call_order_payload(account_a_id),
                headers=make_contractor_headers(account_a_id),
            ),
            ApiErrorId.PO_REQUIRED.value,
            422,
        )
        validate_error(
            api.create_material_order(
                create_will_call_order_payload(
                    account_a_id, job_purchase_order_id=context["purchase_order"]["id"]
                ),
                headers=make_contractor_headers(account_a_id),
            ),
            ApiErrorId.PO_ACCOUNT_MISMATCH.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_material_orders(
                headers=make_contractor_headers(account_a_id),
                params={"contractor_account_id": account_a_id},
            )
        )
        assert meta["total_count"] == 1

        validate_error(
            api.create_claim_case(
                create_claim_case_payload(
                    context["bare"]["id"],
                    "SHORT_LOAD",
                    5000,
                    description="Short delivery reported against the wrong pickup.",
                    will_call_ticket_id=context["ticket"]["id"],
                ),
                headers=make_contractor_headers(account_b_id),
            ),
            ApiErrorId.CLAIM_TARGET_MISMATCH.value,
            422,
        )

        validate_error(
            api.activate_prebuy_contract(
                context["season"]["id"], headers=make_yard_admin_headers()
            ),
            ApiErrorId.MATERIAL_NOT_PREBUY_ELIGIBLE.value,
            422,
        )
        assert read_prebuy(api, context["season"]["id"])["status"] == "DRAFT"
        assert read_material(api, context["material"]["id"])["prebuy_eligible"] is False


def _temporal_yard(api):
    """One effective price row dated 2026-07-01 and one confirmed delivery order."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V8", "Temporal Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(api, business_name="Temporal Landscapes", credit_limit_cents=5000000)
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 5.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=5.0,
        delivery_address="8 Temporal Ave",
        confirm=True,
    )
    truck = seed_truck(api, **_tri("TRI-V8"))
    return {
        "material": catalogue["material"],
        "price_schedule": catalogue["price_schedule"],
        "order": seeded["order"],
        "truck": truck,
    }


class TestTemporalRules:
    """Windows must run forwards, price rows must move forwards and so must the clock."""

    def test_a_reversed_window_a_backdated_price_row_and_a_rewound_clock_are_refused(self, api):
        """Three unrelated endpoints, one shared idea: time only moves one way here.

        PRD 2.8: "**Window and dating rules** -- `window_end` is strictly after
        `window_start` on `POST /delivery-loads`, on `POST
        /delivery-loads/{deliveryLoadId}/replan` and for the staging window on `POST
        /will-call-tickets/stage-next` (`ERR_INVALID_WINDOW`); a new `effective_from` on
        `POST /price-schedules` is strictly later than that of the material's currently
        `EFFECTIVE` row (`ERR_PRICE_SCHEDULE_BACKDATED`); and `POST
        /_clock/set_current_utc` moves the clock strictly forward
        (`ERR_CLOCK_MUST_ADVANCE`); all three are 422."

        PRD 2.5: "A request to set it to an instant at or before the current reading is
        rejected with `ERR_CLOCK_MUST_ADVANCE` (HTTP 422)."

        Design: Corner/validations/temporal_rules_are_rejected
        """
        context = _temporal_yard(api)
        material_id = context["material"]["id"]

        validate_error(
            api.create_delivery_load(
                create_delivery_load_payload(
                    context["order"]["id"],
                    context["truck"]["id"],
                    5.0,
                    "2026-08-02T10:00:00.000Z",
                    "2026-08-02T09:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            ApiErrorId.INVALID_WINDOW.value,
            422,
        )
        _, loads_meta = _loads_for_order(api, context["order"]["id"])
        assert loads_meta["total_count"] == 0

        material_version = read_material(api, material_id)["version"]
        validate_error(
            api.create_price_schedule(
                create_price_schedule_payload(
                    material_id,
                    material_version,
                    effective_from="2026-06-15T00:00:00.000Z",
                ),
                headers=make_yard_admin_headers(),
            ),
            ApiErrorId.PRICE_SCHEDULE_BACKDATED.value,
            422,
        )
        assert read_price_schedule(api, context["price_schedule"]["id"])["status"] == "EFFECTIVE"
        _, price_meta = validate_paginated(
            api.list_price_schedules(
                headers=make_yard_admin_headers(), params={"material_id": material_id}
            )
        )
        assert price_meta["total_count"] == 1
        assert read_material(api, material_id)["version"] == material_version

        validate_error(
            api.set_clock("2026-07-01T00:00:00.000Z", headers=make_yard_admin_headers()),
            ApiErrorId.CLOCK_MUST_ADVANCE.value,
            422,
        )


def _fiscal_yard(api):
    """A 35125-cent order with its whole balance already on one dispatched truck."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V9", "Fiscal Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(api, business_name="Fiscal Landscapes", credit_limit_cents=5000000)
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 6.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=5.0,
        delivery_address="9 Fiscal Blvd",
        confirm=True,
    )
    truck_a = seed_truck(api, **_tri("TRI-V9A"))
    truck_b = seed_truck(api, **_tri("TRI-V9B"))
    load = seed_dispatched_load(
        api,
        seeded["order"]["id"],
        truck_a["id"],
        6.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
        "planner-v9",
    )
    return {
        "account": account,
        "order": seeded["order"],
        "truck_a": truck_a,
        "truck_b": truck_b,
        "load": load,
    }


class TestFiscalCeilings:
    """Volume and money ceilings are refused, and then the exact figure is accepted."""

    def test_overrun_overbooking_and_underpayment_are_refused_before_the_exact_payment(self, api):
        """Spillage counts against the planned volume, and a cent short is still short.

        PRD 2.8: "**Volume never exceeds what was promised** -- at `POST
        /delivery-loads/{deliveryLoadId}/deliver`, `actual_net_cubic_yards` plus
        `spillage_cubic_yards` is at most `planned_cubic_yards`
        (`ERR_DELIVERED_EXCEEDS_PLANNED`); and at `POST /delivery-loads` and `POST
        /will-call-tickets/{willCallTicketId}/load`, the planned or loaded volume is at most
        the order's undelivered bulk balance net of volume already planned on other live
        loads (`ERR_LOAD_EXCEEDS_ORDER_BALANCE`); both are 422."

        PRD 2.8: "**Payment sufficiency** -- at `POST
        /material-orders/{materialOrderId}/settle`, `paid_amount_cents` is at least
        `final_total_cents` minus `credit_memo_cents`, else `ERR_UNDERPAYMENT` (402)."

        Design: Corner/validations/fiscal_ceilings_are_rejected_then_the_exact_payment_settles
        """
        context = _fiscal_yard(api)
        order_id = context["order"]["id"]
        planner = make_dispatch_planner_headers("planner-v9")

        # 12000 bulk, the 7500 minimum-load fee, the tri-axle base and five miles of haul
        assert read_order(api, order_id)["quoted_total_cents"] == 35125

        validate_error(
            api.deliver_delivery_load(
                context["load"]["id"], deliver_payload(6.0, False, 1.0), headers=planner
            ),
            ApiErrorId.DELIVERED_EXCEEDS_PLANNED.value,
            422,
        )
        assert read_load(api, context["load"]["id"])["status"] == "DISPATCHED"

        validate_error(
            api.create_delivery_load(
                create_delivery_load_payload(
                    order_id,
                    context["truck_b"]["id"],
                    1.0,
                    "2026-08-02T13:00:00.000Z",
                    "2026-08-02T14:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            ApiErrorId.LOAD_EXCEEDS_ORDER_BALANCE.value,
            422,
        )
        assert read_truck(api, context["truck_b"]["id"])["status"] == "AVAILABLE"

        delivered = deliver_load(api, context["load"]["id"], 6.0, False, 0.0, "planner-v9")
        assert delivered["status"] == "DELIVERED"

        order = read_order(api, order_id)
        assert order["fulfillment_status"] == "FULFILLED"
        assert order["final_total_cents"] == 35125

        invoice_order(api, order_id)
        validate_error(
            api.settle_material_order(
                order_id, settle_order_payload(35124), headers=make_credit_manager_headers()
            ),
            ApiErrorId.UNDERPAYMENT.value,
            402,
        )
        assert read_order(api, order_id)["settlement_status"] == "INVOICED"

        settled = settle_order(api, order_id, 35125)
        assert settled["settlement_status"] == "SETTLED"
        assert_credit_position(read_account(api, context["account"]["id"]), 0, 5000000)


def _driveway_yard(api):
    """A CLASS_B site that insists on mats, with one truck too big for the driveway."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V10", "Driveway Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api,
        business_name="Driveway Landscapes",
        credit_limit_cents=5000000,
        driveway_protection_required=True,
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 5.0),),
        driveway_access_class="CLASS_B",
        delivery_distance_miles=4.0,
        delivery_address="10 Narrow Ln",
        confirm=True,
    )
    truck_bad = seed_truck(api, **_tri("TRI-V10"))
    truck_ok = seed_truck(
        api,
        truck_code="TND-V10",
        axle_class="TANDEM",
        max_payload_lb=40000,
        bed_capacity_cubic_yards=12.0,
        min_driveway_access_class="CLASS_B",
    )
    return {
        "account": account,
        "order": seeded["order"],
        "truck_bad": truck_bad,
        "truck_ok": truck_ok,
    }


class TestDrivewayRules:
    """The site grade picks the truck and the account policy picks the delivery report."""

    def test_the_wrong_truck_and_the_missing_mats_are_both_refused(self, api):
        """A tri-axle cannot enter a CLASS_B driveway, and this contractor demands mats.

        PRD 2.8: "**Driveway access** -- on the same two endpoints, the access rank of the
        order's `driveway_access_class` is at least the access rank of the truck's
        `min_driveway_access_class`, else `ERR_DRIVEWAY_ACCESS_RESTRICTED` (422)."

        PRD 2.8: "**Driveway protection** -- on `POST
        /delivery-loads/{deliveryLoadId}/deliver`, when the account's
        `driveway_protection_required` is true the report carries `driveway_protection_used`
        true, else `ERR_DRIVEWAY_PROTECTION_REQUIRED` (422)."

        PRD 2.8: "**Volume fit** -- on `POST /delivery-loads` and `POST
        /delivery-loads/{deliveryLoadId}/replan`, `planned_cubic_yards` is at most the lesser
        of the truck's `bed_capacity_cubic_yards` and the driveway cap for the order's access
        class, else `ERR_LOAD_EXCEEDS_TRUCK_CAPACITY` (422)."

        Design: Corner/validations/driveway_rules_are_rejected_then_satisfied_when_the_flag_is_honoured
        """
        context = _driveway_yard(api)
        order_id = context["order"]["id"]

        # 10000 bulk, the 7500 minimum-load fee, the CLASS_B tandem base and four miles
        assert read_order(api, order_id)["quoted_total_cents"] == 28700

        validate_error(
            api.create_delivery_load(
                create_delivery_load_payload(
                    order_id,
                    context["truck_bad"]["id"],
                    5.0,
                    "2026-08-02T08:00:00.000Z",
                    "2026-08-02T10:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            ApiErrorId.DRIVEWAY_ACCESS_RESTRICTED.value,
            422,
        )

        load = validate_success(
            api.create_delivery_load(
                create_delivery_load_payload(
                    order_id,
                    context["truck_ok"]["id"],
                    5.0,
                    "2026-08-02T08:00:00.000Z",
                    "2026-08-02T10:00:00.000Z",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            201,
        )
        # the lesser of the tandem's 12.0 bed and the CLASS_B cap of 12.0
        assert load["max_allowed_cubic_yards"] == pytest.approx(12.00, abs=CENTS)
        assert load["planned_payload_lb"] == 5000

        dispatch_load(api, load["id"], "planner-v10")
        validate_error(
            api.deliver_delivery_load(
                load["id"],
                deliver_payload(5.0, False, 0.0),
                headers=make_dispatch_planner_headers("planner-v10"),
            ),
            ApiErrorId.DRIVEWAY_PROTECTION_REQUIRED.value,
            422,
        )
        assert read_load(api, load["id"])["status"] == "DISPATCHED"

        delivered = deliver_load(api, load["id"], 5.0, True, 0.0, "planner-v10")
        assert delivered["status"] == "DELIVERED"
        assert delivered["driveway_protection_used"] is True

        order = read_order(api, order_id)
        assert order["fulfillment_status"] == "FULFILLED"
        assert order["final_total_cents"] == 28700


def _container_yard(api):
    """Three pallets handed over at the bay on the day the clock still reads 2026-08-01."""
    catalogue = seed_catalogue(
        api,
        material=_stone(
            "MULCH-V11",
            "Container Mulch",
            offered_forms=["BULK", "BAGGED"],
            seasonal_category="MULCH",
        ),
        price=FLAT_PRICE,
        lot=STANDARD_LOT,
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Container Landscapes", credit_limit_cents=5000000
    )
    seeded = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 4.0), ("BAGGED", 10)), confirm=True
    )
    ticket = seed_will_call_ticket(
        api, seeded["order"]["id"], account["id"], "2026-07-31T07:00:00.000Z"
    )
    stage_next_ticket(api, "2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z", "loader-v11")
    acknowledge_safety(api, ticket["id"], "loader-v11", safety_briefing_code="BRIEF-V11")
    load_ticket(api, ticket["id"], 4.0, 3, "loader-v11")
    return {
        "account": account,
        "order": seeded["order"],
        "ticket": ticket,
        "record": find_container_return(api, seeded["order"]["id"]),
    }


class TestContainerReturnCeilingAndClosedRow:
    """A deposit record refuses to hand back more carriers than it issued, then closes."""

    def test_an_overcount_is_refused_and_so_is_a_receive_after_the_forfeit(self, api):
        """The count ceiling is 422 on a live record; the closed-row guard is 409.

        PRD 2.8: "**Container return count** -- at `POST
        /container-returns/{containerReturnId}/receive`, the cumulative `returned_count`
        already recorded plus the `returned_count` in the request is at most `issued_count`,
        else `ERR_RETURN_COUNT_EXCEEDS_ISSUED` (422)."

        PRD 3.8: "A receive on a record already `CLOSED` or `FORFEITED` is refused with
        `ERR_CONTAINER_RETURN_CLOSED`, as is a forfeiture on such a record."

        PRD 3.8: "`forfeited_cents` is set to `issued_count` multiplied by
        `deposit_per_unit_cents` minus `refund_cents`, and the unreturned remainder is
        permanently retained by the yard."

        Design: Corner/validations/container_return_ceiling_and_closed_row_are_rejected
        """
        context = _container_yard(api)
        record_id = context["record"]["id"]
        account_id = context["account"]["id"]
        loader = make_yard_loader_headers("loader-v11")

        # 8000 of bulk plus ten bags at 899, with no fee and no haul on a will-call order
        assert read_order(api, context["order"]["id"])["quoted_total_cents"] == 16990

        assert context["record"]["container_type"] == "PALLET"
        assert context["record"]["issued_count"] == 3
        assert context["record"]["deposit_per_unit_cents"] == 2500
        assert context["record"]["status"] == "OUTSTANDING"
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 7500

        validate_error(
            api.receive_container_return(
                record_id, receive_container_payload(4), headers=loader
            ),
            ApiErrorId.RETURN_COUNT_EXCEEDS_ISSUED.value,
            422,
        )
        assert read_container_return(api, record_id)["returned_count"] == 0

        received = receive_containers(api, record_id, 1, "loader-v11")
        assert received["status"] == "PARTIALLY_RETURNED"
        # inside the thirty-day grace window, so the whole deposit comes back
        assert received["refund_cents"] == 2500
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 5000

        forfeited = forfeit_containers(api, record_id)
        assert forfeited["status"] == "FORFEITED"
        # 3 * 2500 issued less the 2500 already refunded
        assert forfeited["forfeited_cents"] == 5000
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 0

        validate_error(
            api.receive_container_return(
                record_id, receive_container_payload(1), headers=loader
            ),
            ApiErrorId.CONTAINER_RETURN_CLOSED.value,
            409,
        )
        closed = read_container_return(api, record_id)
        assert closed["refund_cents"] == 2500
        assert closed["returned_count"] == 1


def _capacity_yard(api):
    """Three queued tickets and two bays, all three asking for the same morning."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V12", "Capacity Stone"), price=FLAT_PRICE, lot=BIG_LOT
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Capacity Landscapes", credit_limit_cents=9000000
    )
    orders = [
        seed_will_call_order(
            api, account, material_id, lines=(("BULK", 4.0),), confirm=True
        )["order"]
        for _ in range(3)
    ]
    requested = [
        "2026-07-31T06:00:00.000Z",
        "2026-07-31T07:00:00.000Z",
        "2026-07-31T08:00:00.000Z",
    ]
    tickets = [
        seed_will_call_ticket(api, order["id"], account["id"], at)
        for order, at in zip(orders, requested)
    ]
    return {
        "account": account,
        "material": catalogue["material"],
        "lot": catalogue["lot"],
        "orders": orders,
        "tickets": tickets,
    }


class TestStagingCapacity:
    """Two bays is a hard count over the requested window, not over the whole day."""

    def test_the_third_overlapping_window_is_refused_and_a_later_one_is_accepted(self, api):
        """The queue still holds the third ticket, and a disjoint window stages it.

        PRD 2.8: "**Staging capacity** -- on `POST /will-call-tickets/stage-next`, fewer
        than two bays are occupied over the requested window, else
        `ERR_STAGING_CAPACITY_FULL` (409)."

        PRD 3.6: "The request is refused with `ERR_STAGING_CAPACITY_FULL` when the number of
        tickets whose `status` is `STAGED` or `LOADING` and whose own closed interval from
        `staging_window_start` through `staging_window_end` intersects the requested window
        is already two or more."

        PRD 3.6: "`queue_position` is set to null the moment a ticket leaves `QUEUED`, and
        every remaining queued ticket is renumbered whenever any ticket's status changes."

        Design: Corner/validations/staging_capacity_full_is_rejected_on_the_third_overlapping_window
        """
        context = _capacity_yard(api)
        loader = make_yard_loader_headers("loader-v12")

        first = stage_next_ticket(
            api, "2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z", "loader-v12"
        )
        assert first["id"] == context["tickets"][0]["id"]
        second = stage_next_ticket(
            api, "2026-08-01T09:15:00.000Z", "2026-08-01T10:15:00.000Z", "loader-v12"
        )
        assert second["id"] == context["tickets"][1]["id"]

        validate_error(
            api.stage_next_will_call_ticket(
                stage_next_payload("2026-08-01T09:30:00.000Z", "2026-08-01T10:30:00.000Z"),
                headers=loader,
            ),
            ApiErrorId.STAGING_CAPACITY_FULL.value,
            409,
        )
        waiting = read_ticket(api, context["tickets"][2]["id"])
        assert waiting["status"] == "QUEUED"
        assert waiting["queue_position"] == 1

        third = stage_next_ticket(
            api, "2026-08-01T13:00:00.000Z", "2026-08-01T14:00:00.000Z", "loader-v12"
        )
        assert third["id"] == context["tickets"][2]["id"]
        assert third["status"] == "STAGED"

        for order in context["orders"]:
            assert read_order(api, order["id"])["fulfillment_status"] == "ALLOCATED"

        lot = read_lot(api, context["lot"]["id"])
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert lot["reserved_cubic_yards"] == pytest.approx(12.00, abs=CENTS)


def _credit_ceiling_yard(api):
    """A 40000-cent line with 20000 of it already committed to a confirmed order."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V13", "Aggregate Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Aggregate Landscapes", credit_limit_cents=40000
    )
    committed = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 10.0),), confirm=True
    )
    pending = seed_will_call_order(api, account, material_id, lines=(("BULK", 12.5),))
    return {
        "account": account,
        "lot": catalogue["lot"],
        "committed": committed["order"],
        "pending": pending["order"],
    }


class TestCreditLineCeiling:
    """The line is tested against what is left, not against what the order costs alone."""

    def test_the_second_order_is_refused_although_it_would_have_fitted_on_its_own(self, api):
        """25000 fits inside a 40000 limit, but not inside the 20000 still available.

        PRD 2.8: "**Credit line** -- at confirm, the account's `credit_available_cents` is at
        least `quoted_total_cents`, exact equality accepted, else
        `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

        PRD 3.3: "Orders still in `DRAFT` and orders that were `CANCELLED` never consume
        credit, and an order whose `settlement_status` has reached `SETTLED` releases the
        credit it was consuming."

        PRD 3.4: "A new order begins with `fulfillment_status` `DRAFT` and
        `settlement_status` `UNBILLED`, with every money field at 0, with `final_total_cents`
        and `quote_locked_at` null, and with `paid_amount_cents` and `credit_memo_cents` at
        0."

        Design: Corner/validations/credit_limit_rejects_the_second_order_that_would_fit_alone
        """
        context = _credit_ceiling_yard(api)
        account_id = context["account"]["id"]
        pending_id = context["pending"]["id"]

        assert read_order(api, context["committed"]["id"])["quoted_total_cents"] == 20000

        validate_error(
            api.confirm_material_order(
                pending_id, headers=make_contractor_headers(account_id)
            ),
            ApiErrorId.CREDIT_LIMIT_EXCEEDED.value,
            402,
        )

        pending = read_order(api, pending_id)
        assert pending["fulfillment_status"] == "DRAFT"
        # the refused confirm never froze a quote, so the money fields stay where they opened
        assert pending["quoted_total_cents"] == 0
        assert pending["final_total_cents"] is None

        account = read_account(api, account_id)
        assert_credit_position(account, 20000, 20000)
        assert account["account_status"] == "ACTIVE"

        # 12.50 was never reserved, only the confirmed 10.00
        assert read_lot(api, context["lot"]["id"])["reserved_cubic_yards"] == pytest.approx(
            10.00, abs=CENTS
        )


def _exact_credit_yard(api):
    """A 30000-cent line and a draft order that will quote at precisely 30000."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-V14", "Exact Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(api, business_name="Exact Landscapes", credit_limit_cents=30000)
    pending = seed_will_call_order(
        api, account, catalogue["material"]["id"], lines=(("BULK", 15.0),)
    )
    return {"account": account, "order": pending["order"]}


class TestCreditLineExactEquality:
    """Spending the line down to nothing is accepted; only strictly over the limit holds."""

    def test_a_quote_equal_to_the_available_line_confirms_and_leaves_the_account_active(self, api):
        """Zero headroom is still headroom, and the hold band opens above the limit.

        PRD 2.8: "**Credit line** -- at confirm, the account's `credit_available_cents` is at
        least `quoted_total_cents`, exact equality accepted, else
        `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

        PRD 3.3: "The account transitions `ACTIVE -> CREDIT_HOLD` on any recompute where
        `credit_used_cents` is **strictly greater** than `credit_limit_cents`."

        Design: Corner/validations/confirm_accepted_when_credit_available_equals_the_quote_exactly
        """
        context = _exact_credit_yard(api)
        account_id = context["account"]["id"]

        confirmed = validate_success(
            api.confirm_material_order(
                context["order"]["id"], headers=make_contractor_headers(account_id)
            ),
            200,
        )
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        # 15.00 yards at 2000, with no fee and no haul on a will-call order
        assert confirmed["quoted_total_cents"] == 30000

        account = read_account(api, account_id)
        assert_credit_position(account, 30000, 0)
        assert account["account_status"] == "ACTIVE"

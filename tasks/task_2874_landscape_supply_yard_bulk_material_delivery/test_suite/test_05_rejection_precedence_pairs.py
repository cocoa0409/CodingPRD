"""Requests that break two rules at once and must report the higher-ranked one."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_credit_position
from test_helpers.factories import create_delivery_load_payload
from test_helpers.fixtures import (
    acknowledge_safety,
    advance_clock,
    load_ticket,
    read_account,
    read_material,
    read_order,
    release_ticket,
    seed_account,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_price_schedule,
    seed_will_call_order,
    seed_will_call_ticket,
    stage_next_ticket,
)
from test_helpers.test_users import (
    make_contractor_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
)

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
BLACK_MULCH = {
    "sku": "MULCH-BLACK",
    "name": "Black Dyed Mulch",
    "offered_forms": ["BULK"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
PEA_GRAVEL = {
    "sku": "AGG-PEA",
    "name": "Pea Gravel",
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
MISSING_PREBUY_ID = "00000000-0000-4000-8000-000000000000"


def _shoestring_on_hold(api):
    """An overrun will-call account plus a fresh DRAFT order waiting to be confirmed."""
    catalogue = seed_catalogue(
        api,
        material=BLACK_MULCH,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(api, business_name="Shoestring Lawn Co", credit_limit_cents=30000)

    first = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 5.0),), confirm=True
    )
    ticket = seed_will_call_ticket(
        api, first["order"]["id"], account["id"], "2026-08-01T00:00:00.000Z"
    )

    seed_price_schedule(
        api,
        read_material(api, material_id),
        effective_from="2026-08-05T00:00:00.000Z",
        bulk_price_per_cubic_yard_cents=8000,
        bagged_price_per_bag_cents=899,
        seasonal_surcharge_pct=0.0,
    )
    advance_clock(api, "2026-08-06T00:00:00.000Z")

    stage_next_ticket(api, "2026-08-06T09:00:00.000Z", "2026-08-06T11:00:00.000Z", "loader-1")
    acknowledge_safety(
        api, ticket["id"], "loader-1", safety_briefing_code="BRIEF-2026-08", ppe_confirmed=True
    )
    load_ticket(api, ticket["id"], 5.0, None, "loader-1")
    release_ticket(api, ticket["id"], "loader-1")

    second = seed_will_call_order(api, account, material_id, lines=(("BULK", 1.0),))
    return {
        "account": account,
        "first_order_id": first["order"]["id"],
        "second_order_id": second["order"]["id"],
    }


class TestCreditHoldOutranksTheCreditCeiling:
    """One over-extended account breaks two confirm rules; the state gate wins."""

    def test_confirm_on_a_held_account_reports_the_hold_and_not_the_ceiling(self, api):
        """The cross-entity readiness rung is reached long before the fiscal rung.

        PRD 2.8: "**Cross-entity readiness** -- every line's material is `ACTIVE` at
        `POST /material-orders/{materialOrderId}/confirm` (`ERR_MATERIAL_NOT_SELLABLE`);
        the pinned lot is `AVAILABLE` at
        `POST /delivery-loads/{deliveryLoadId}/dispatch` (`ERR_LOT_QUARANTINED`); the
        truck is `AVAILABLE` at `POST /delivery-loads`, at
        `POST /delivery-loads/{deliveryLoadId}/dispatch` and at
        `POST /delivery-loads/{deliveryLoadId}/replan` (`ERR_TRUCK_UNAVAILABLE`); the
        owning account is `ACTIVE` at confirm, at dispatch and at
        `POST /will-call-tickets/stage-next` (`ERR_ACCOUNT_CREDIT_HOLD`); and a referenced
        pre-buy contract is `ACTIVE` at confirm (`ERR_PREBUY_NOT_ACTIVE`); all five are
        409."

        Design: Difficulty/priority_pair_validation_conflict/account_credit_hold_state_outranks_credit_limit_check_at_confirm
        """
        context = _shoestring_on_hold(api)
        account_id = context["account"]["id"]

        # 5.00 cubic yards released against the promoted 8000-cent row
        assert read_order(api, context["first_order_id"])["final_total_cents"] == 40000
        account = read_account(api, account_id)
        assert_credit_position(account, 40000, -10000)
        assert account["account_status"] == "CREDIT_HOLD"

        rejected = api.confirm_material_order(
            context["second_order_id"], headers=make_contractor_headers(account_id)
        )
        validate_error(rejected, ApiErrorId.ACCOUNT_CREDIT_HOLD.value, 409)

        stalled = read_order(api, context["second_order_id"])
        assert stalled["fulfillment_status"] == "DRAFT"
        assert stalled["quoted_total_cents"] == 0
        assert stalled["quote_locked_at"] is None

    def test_an_active_account_short_of_credit_reports_the_ceiling_instead(self, api):
        """With the state gate satisfied, the fiscal rung is the one that fires.

        PRD 2.8: "**Credit line** -- at confirm, the account's `credit_available_cents` is
        at least `quoted_total_cents`, exact equality accepted, else
        `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

        Design: Difficulty/priority_pair_validation_conflict/account_credit_hold_state_outranks_credit_limit_check_at_confirm
        """
        catalogue = seed_catalogue(
            api,
            material=BLACK_MULCH,
            price=FLAT_PRICE,
            lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        )
        account = seed_account(api, business_name="Shoestring Lawn Co", credit_limit_cents=30000)
        seeded = seed_will_call_order(
            api, account, catalogue["material"]["id"], lines=(("BULK", 20.0),)
        )

        assert read_account(api, account["id"])["account_status"] == "ACTIVE"

        # 20.00 cubic yards at 2000 cents needs 40000 against a 30000-cent line
        rejected = api.confirm_material_order(
            seeded["order"]["id"], headers=make_contractor_headers(account["id"])
        )
        validate_error(rejected, ApiErrorId.CREDIT_LIMIT_EXCEEDED.value, 402)
        assert read_order(api, seeded["order"]["id"])["fulfillment_status"] == "DRAFT"


def _ridgeview_context(api, truck):
    """A confirmed 10.00-cubic-yard CLASS_A order and one truck to plan against it."""
    return seed_confirmed_delivery_context(
        api,
        material=PEA_GRAVEL,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Ridgeview Hardscape", "credit_limit_cents": 5000000},
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=truck,
    )


class TestAxleWeightOutranksVolumeFit:
    """A load that is both overweight and over-volume names the safety gate."""

    def test_an_overweight_and_over_volume_load_reports_the_weight_gate(self, api):
        """Both 422 rungs apply, and only the error id distinguishes them.

        PRD 2.8: "And within the delivery-load checks, the weight gate at rung 20 is
        evaluated before the volume gate at rung 23: a load that is both too heavy and too
        voluminous reports `ERR_AXLE_WEIGHT_LIMIT_EXCEEDED`, never
        `ERR_LOAD_EXCEEDS_TRUCK_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/axle_weight_safety_gate_outranks_volume_capacity_gate
        """
        context = _ridgeview_context(
            api,
            {
                "truck_code": "T-101",
                "axle_class": "SINGLE",
                "max_payload_lb": 5000,
                "bed_capacity_cubic_yards": 6.0,
                "min_driveway_access_class": "CLASS_C",
            },
        )
        order_id = context["order"]["id"]

        # bulk 20000 + minimum-load fee 7500 + the TRI_AXLE base a CLASS_A drive admits
        assert context["order"]["quoted_total_cents"] == 41000

        # 8.00 cubic yards weighs 8000 lb against a 5000-lb axle limit, and 8.00 also
        # exceeds the 6.00-cubic-yard bed
        rejected = api.create_delivery_load(
            create_delivery_load_payload(
                order_id,
                context["truck"]["id"],
                8.0,
                "2026-08-02T08:00:00.000Z",
                "2026-08-02T12:00:00.000Z",
            ),
            headers=make_dispatch_planner_headers(),
        )
        validate_error(rejected, ApiErrorId.AXLE_WEIGHT_LIMIT_EXCEEDED.value, 422)

        _, meta = validate_paginated(
            api.list_delivery_loads(
                headers=make_dispatch_planner_headers(), params={"material_order_id": order_id}
            )
        )
        assert meta["total_count"] == 0
        assert read_order(api, order_id)["fulfillment_status"] == "CONFIRMED"

    def test_a_light_but_oversized_load_reports_the_volume_gate(self, api):
        """With the weight gate cleared, the volume rung is the one that fires.

        PRD 2.8: "**Volume fit** -- on `POST /delivery-loads` and
        `POST /delivery-loads/{deliveryLoadId}/replan`, `planned_cubic_yards` is at most
        the lesser of the truck's `bed_capacity_cubic_yards` and the driveway cap for the
        order's access class, else `ERR_LOAD_EXCEEDS_TRUCK_CAPACITY` (422)."

        Design: Difficulty/priority_pair_validation_conflict/axle_weight_safety_gate_outranks_volume_capacity_gate
        """
        context = _ridgeview_context(
            api,
            {
                "truck_code": "T-102",
                "axle_class": "SINGLE",
                "max_payload_lb": 20000,
                "bed_capacity_cubic_yards": 6.0,
                "min_driveway_access_class": "CLASS_C",
            },
        )
        order_id = context["order"]["id"]

        # 8000 lb sits well inside the 20000-lb axle limit, so only the bed binds
        rejected = api.create_delivery_load(
            create_delivery_load_payload(
                order_id,
                context["truck"]["id"],
                8.0,
                "2026-08-02T08:00:00.000Z",
                "2026-08-02T12:00:00.000Z",
            ),
            headers=make_dispatch_planner_headers(),
        )
        validate_error(rejected, ApiErrorId.LOAD_EXCEEDS_TRUCK_CAPACITY.value, 422)

        _, meta = validate_paginated(
            api.list_delivery_loads(
                headers=make_dispatch_planner_headers(), params={"material_order_id": order_id}
            )
        )
        assert meta["total_count"] == 0


class TestRoleGateOutranksPathExistence:
    """An unauthorised caller learns nothing about which ids exist."""

    def test_a_contractor_activating_an_unknown_prebuy_is_told_only_that_it_is_forbidden(self, api):
        """The role rung sits above the path-existence rung on every endpoint.

        PRD 2.8: "Authorization always outranks existence, so a `Contractor` reaching for
        another account's order learns only that it is forbidden, never whether the order
        exists."

        Design: Difficulty/priority_pair_validation_conflict/role_authorization_outranks_path_existence_and_returns_403_on_prebuy_activate
        """
        account = seed_account(
            api, business_name="Curious Contracting", credit_limit_cents=100000
        )

        rejected = api.activate_prebuy_contract(
            MISSING_PREBUY_ID, headers=make_contractor_headers(account["id"])
        )
        validate_error(rejected, ApiErrorId.UNAUTHORIZED.value, 403)

    def test_the_authorized_role_reaches_the_existence_check_on_the_same_path(self, api):
        """The 403 came from the role list, not from a missing route.

        PRD 2.8: "**Path-parameter existence** -- every path segment resolves, checked left
        to right, on every endpoint carrying path parameters, else the matching 404 from
        the catalogue in section 2.4."

        Design: Difficulty/priority_pair_validation_conflict/role_authorization_outranks_path_existence_and_returns_403_on_prebuy_activate
        """
        seed_account(api, business_name="Curious Contracting", credit_limit_cents=100000)

        rejected = api.activate_prebuy_contract(
            MISSING_PREBUY_ID, headers=make_yard_admin_headers()
        )
        validate_error(rejected, ApiErrorId.PREBUY_NOT_FOUND.value, 404)

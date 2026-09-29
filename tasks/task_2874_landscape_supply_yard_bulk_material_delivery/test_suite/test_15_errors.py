"""Error identifiers proved reachable, one distinct code per resource family and per refusal."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_charge_assembly, assert_response_meta
from test_helpers.fixtures import (
    read_line,
    read_lot,
    read_material,
    read_order,
    seed_account,
    seed_inventory_lot,
    seed_material,
    seed_price_schedule,
    seed_will_call_order,
)
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
    make_yard_loader_headers,
)

DEAD = "00000000-0000-0000-0000-00000000dead"
FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
SPLIT_STONE = {
    "sku": "AGG-X1",
    "name": "Split Stone",
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


def _not_found_probes(api):
    """One read per resource family, every one of them aimed at the same unused UUID."""
    return [
        (
            "materials",
            lambda: api.get_material(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.MATERIAL_NOT_FOUND.value,
        ),
        (
            "price-schedules",
            lambda: api.get_price_schedule(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.PRICE_SCHEDULE_NOT_FOUND.value,
        ),
        (
            "inventory-lots",
            lambda: api.get_inventory_lot(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.INVENTORY_LOT_NOT_FOUND.value,
        ),
        (
            "contractor-accounts",
            lambda: api.get_contractor_account(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.ACCOUNT_NOT_FOUND.value,
        ),
        (
            "job-purchase-orders",
            lambda: api.get_job_purchase_order(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.PO_NOT_FOUND.value,
        ),
        (
            "prebuy-contracts",
            lambda: api.get_prebuy_contract(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.PREBUY_NOT_FOUND.value,
        ),
        (
            "material-orders",
            lambda: api.get_material_order(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.ORDER_NOT_FOUND.value,
        ),
        (
            "order-lines",
            lambda: api.get_order_line(DEAD, headers=make_yard_admin_headers()),
            ApiErrorId.ORDER_LINE_NOT_FOUND.value,
        ),
        (
            "delivery-trucks",
            lambda: api.get_delivery_truck(DEAD, headers=make_dispatch_planner_headers()),
            ApiErrorId.TRUCK_NOT_FOUND.value,
        ),
        (
            "delivery-loads",
            lambda: api.get_delivery_load(DEAD, headers=make_dispatch_planner_headers()),
            ApiErrorId.LOAD_NOT_FOUND.value,
        ),
        (
            "will-call-tickets",
            lambda: api.get_will_call_ticket(DEAD, headers=make_yard_loader_headers()),
            ApiErrorId.TICKET_NOT_FOUND.value,
        ),
        (
            "container-returns",
            lambda: api.get_container_return(DEAD, headers=make_yard_loader_headers()),
            ApiErrorId.CONTAINER_RETURN_NOT_FOUND.value,
        ),
        (
            "claim-cases",
            lambda: api.get_claim_case(DEAD, headers=make_claims_adjuster_headers()),
            ApiErrorId.CLAIM_NOT_FOUND.value,
        ),
    ]


class TestNotFoundIdentifiersAreDistinct:
    """Thirteen resource families, thirteen separate 404 codes, no generic fallback."""

    def test_the_same_unused_uuid_yields_a_different_code_on_every_family(self, api):
        """One syntactically valid but unused identifier walks every read endpoint and comes
        back named after the family it was aimed at.

        PRD 2.4: "A path naming a resource that does not exist yields the 404 error specific
        to that resource type: `ERR_MATERIAL_NOT_FOUND`, `ERR_PRICE_SCHEDULE_NOT_FOUND`,
        `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PO_NOT_FOUND`,
        `ERR_PREBUY_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND` or `ERR_CONTAINER_RETURN_NOT_FOUND`."

        PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

        PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/every_not_found_error_id_is_triggerable
        """
        empty, meta = validate_paginated(
            api.list_materials(headers=make_yard_admin_headers(), params={"limit": 10, "offset": 0})
        )
        # nothing at all is seeded, so no read below can accidentally hit a real row
        assert meta["total_count"] == 0
        assert empty == []

        seen = []
        for family, probe, expected_error_id in _not_found_probes(api):
            response = probe()
            error_data = validate_error(response, expected_error_id, 404)
            assert error_data["message"].strip(), family
            body = response.json()
            assert body["response_type"] == "error", family
            assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, family
            assert_response_meta(body)
            seen.append(error_data["error_id"])

        assert seen == [expected for _, _, expected in _not_found_probes(api)]
        # each family reports its own identifier, so nothing collapses into a shared code
        assert len(set(seen)) == 13


def _split_landscapes(api):
    """Nine net cubic yards of stone, spread over two piles that may not be combined."""
    material = seed_material(api, **SPLIT_STONE)
    seed_price_schedule(api, material, **FLAT_PRICE)
    small_lots = [
        seed_inventory_lot(api, material["id"], gross_cubic_yards=5.0, moisture_pct_at_intake=15.0),
        seed_inventory_lot(api, material["id"], gross_cubic_yards=5.0, moisture_pct_at_intake=15.0),
    ]
    account = seed_account(
        api,
        business_name="Split Landscapes",
        credit_limit_cents=5000000,
        po_required=False,
        driveway_protection_required=False,
    )
    seeded = seed_will_call_order(api, account, material["id"], lines=(("BULK", 6.0),))
    return {
        "material": material,
        "small_lots": small_lots,
        "account": account,
        "order": seeded["order"],
        "line": seeded["lines"][0],
    }


class TestInsufficientInventoryIsTriggerable:
    """Enough material in the yard, in the wrong number of piles."""

    def test_two_half_piles_cannot_serve_the_line_that_one_whole_pile_can(self, api):
        """9.00 available net cubic yards refuse a 6.0 cubic-yard line while they sit in two
        4.50 piles, and the very same order confirms once one pile is big enough.

        PRD 2.8: "**Inventory sufficiency** -- at
        `POST /material-orders/{materialOrderId}/confirm`, every line finds one single
        available lot of its material with enough unreserved sellable volume, lots never being
        split, else `ERR_INSUFFICIENT_INVENTORY` (409)."

        PRD 3.4: "Every line must find exactly one lot of its material that is `AVAILABLE` and
        whose `net_sellable_cubic_yards` minus `reserved_cubic_yards` is at least the line's
        `line_volume_cubic_yards`, choosing the earliest-created such lot; **lots are never
        split across a line**, so a line that could only be satisfied by combining two
        partly-full piles is refused with `ERR_INSUFFICIENT_INVENTORY`."

        PRD 3.2: "`available_net_cubic_yards` on a `Material` is the sum, over that material's
        lots whose `status` is `AVAILABLE`, of each lot's `net_sellable_cubic_yards` minus its
        `reserved_cubic_yards`, rounded half up to two decimal places."

        PRD 3.4: "The first hop writes the line pricing and the order assembly, sets
        `quote_locked_at` to the current logical clock, pins each line's `inventory_lot_id` to
        the earliest-created eligible available lot, and sets `fulfillment_status` to
        `CONFIRMED`."

        Design: Corner/errors/insufficient_inventory_is_triggerable_when_no_single_lot_covers_the_line
        """
        context = _split_landscapes(api)
        order_id = context["order"]["id"]
        contractor = make_contractor_headers(context["account"]["id"])

        # 5.0 gross * (1 - 0.10) * 1.00 on each pile, so 9.00 net across the material
        for lot in context["small_lots"]:
            assert read_lot(api, lot["id"])["net_sellable_cubic_yards"] == pytest.approx(
                4.50, abs=CENTS
            )
        assert read_material(api, context["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(9.00, abs=CENTS)

        validate_error(
            api.confirm_material_order(order_id, headers=contractor),
            ApiErrorId.INSUFFICIENT_INVENTORY.value,
            409,
        )
        assert read_order(api, order_id)["fulfillment_status"] == "DRAFT"
        for lot in context["small_lots"]:
            assert read_lot(api, lot["id"])["reserved_cubic_yards"] == pytest.approx(0.00, abs=CENTS)
        assert read_line(api, context["line"]["id"])["inventory_lot_id"] is None

        big_lot = seed_inventory_lot(
            api, context["material"]["id"], gross_cubic_yards=10.0, moisture_pct_at_intake=15.0
        )
        # 10.0 gross * (1 - 0.10) * 1.00
        assert big_lot["net_sellable_cubic_yards"] == pytest.approx(9.00, abs=CENTS)
        assert read_material(api, context["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(18.00, abs=CENTS)

        confirmed = validate_success(api.confirm_material_order(order_id, headers=contractor), 200)
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        # 6.00 cubic yards at 2000, below every discount tier
        assert confirmed["quoted_total_cents"] == 12000
        assert_charge_assembly(confirmed, 12000)

        # the only lot whose 9.00 unreserved net covers the 6.00 line is the new one
        assert read_line(api, context["line"]["id"])["inventory_lot_id"] == big_lot["id"]
        assert read_lot(api, big_lot["id"])["reserved_cubic_yards"] == pytest.approx(6.00, abs=CENTS)
        for lot in context["small_lots"]:
            assert read_lot(api, lot["id"])["reserved_cubic_yards"] == pytest.approx(0.00, abs=CENTS)

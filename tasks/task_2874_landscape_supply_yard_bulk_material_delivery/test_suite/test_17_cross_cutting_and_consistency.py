"""The two stale-version guards, and the promise that one write settles before its response."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    CENTS,
    assert_charge_assembly,
    assert_contractor_account,
    assert_credit_position,
    assert_delivery_load,
    assert_price_schedule,
)
from test_helpers.factories import (
    create_credit_adjustment_payload,
    create_price_schedule_payload,
    deliver_payload,
)
from test_helpers.fixtures import (
    read_account,
    read_material,
    seed_account,
    seed_catalogue,
    seed_delivery_order,
    seed_dispatched_load,
    seed_material,
    seed_truck,
)
from test_helpers.test_users import (
    make_credit_manager_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
)

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}
LIST_PAGE = {"limit": 10, "offset": 0}


def _stone(sku: str, name: str, **overrides):
    """One aggregate profile at reference moisture, cloned per test."""
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


def _priced_mulch(api):
    """One mulch, its version as first read, and one already-effective price row."""
    material = seed_material(
        api,
        sku="MULCH-C1",
        name="Concurrency Mulch",
        offered_forms=["BULK"],
        seasonal_category="MULCH",
        density_lb_per_cubic_yard=900,
        shrinkage_factor=0.10,
        moisture_pct=15.0,
        unit_bag_cubic_yards=0.037,
        prebuy_eligible=False,
    )
    first_schedule = validate_success(
        api.create_price_schedule(
            create_price_schedule_payload(material["id"], material["version"], **FLAT_PRICE),
            headers=make_yard_admin_headers(),
        ),
        201,
    )
    return {"material": material, "first_version": material["version"], "first_schedule": first_schedule}


class TestMaterialStaleVersionGuardOnPriceCreate:
    """Filing the first price row is itself a write on the material, so the held version rots."""

    def test_the_replayed_material_version_is_refused_and_the_reread_one_files_the_row(self, api):
        """A second price row quoting the version the client saw before the first filing is
        refused with 412 and leaves nothing behind, and the same body succeeds once the material
        is re-read.

        PRD 2.7: "Filing a new price row -- a `POST /price-schedules` request -- must carry
        `expected_material_version` as a non-optional input field holding the client's last
        observed `version` of the `Material` named by `material_id`."

        PRD 2.7: "If that number does not equal the material's current `version`, the create is
        rejected with `ERR_STALE_MATERIAL_VERSION` (HTTP 412)."

        PRD 2.8: "**Material stale-version guard** -- on `POST /price-schedules`,
        `expected_material_version` equals the material's `version`, else
        `ERR_STALE_MATERIAL_VERSION` (412)."

        PRD 3.1: "Filing the row also requires the material stale-version guard of section 2.7,
        and a successful filing advances the parent `Material`'s `version` by one -- which is
        exactly why a second filing replaying the same `expected_material_version` fails."

        PRD 3.1: "A price row is born `SCHEDULED` unless its `effective_from` is already at or
        before the current logical clock, in which case it becomes `EFFECTIVE` the moment it is
        filed."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_material_version_on_price_create_returns_412
        """
        context = _priced_mulch(api)
        material_id = context["material"]["id"]
        first_version = context["first_version"]
        assert context["first_schedule"]["status"] == "EFFECTIVE"

        autumn_row = {
            "effective_from": "2026-09-01T00:00:00.000Z",
            "bulk_price_per_cubic_yard_cents": 2400,
            "bagged_price_per_bag_cents": 999,
            "seasonal_surcharge_pct": 5.0,
        }
        validate_error(
            api.create_price_schedule(
                create_price_schedule_payload(material_id, first_version, **autumn_row),
                headers=make_yard_admin_headers(),
            ),
            ApiErrorId.STALE_MATERIAL_VERSION.value,
            412,
        )

        after_refusal = read_material(api, material_id)
        # the setup filing advanced the material exactly once; the refusal advanced nothing
        assert after_refusal["version"] == first_version + 1
        rows, meta = validate_paginated(
            api.list_price_schedules(
                headers=make_yard_admin_headers(), params={"material_id": material_id, **LIST_PAGE}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [context["first_schedule"]["id"]]

        retried = validate_success(
            api.create_price_schedule(
                create_price_schedule_payload(
                    material_id, after_refusal["version"], **autumn_row
                ),
                headers=make_yard_admin_headers(),
            ),
            201,
        )
        assert_price_schedule(retried)
        # 2026-09-01 is beyond the 2026-08-01 clock, so the row waits its turn
        assert retried["status"] == "SCHEDULED"
        assert read_material(api, material_id)["version"] == first_version + 2

        rows, meta = validate_paginated(
            api.list_price_schedules(
                headers=make_yard_admin_headers(), params={"material_id": material_id, **LIST_PAGE}
            )
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[context["first_schedule"]["id"]]["status"] == "EFFECTIVE"
        assert by_id[retried["id"]]["status"] == "SCHEDULED"


def _raised_account(api):
    """An account first opened at 100000 cents, then raised to 200000 by one adjustment."""
    account = seed_account(
        api,
        business_name="Concurrency Landscapes",
        credit_limit_cents=100000,
        po_required=False,
        driveway_protection_required=False,
    )
    validate_success(
        api.create_credit_adjustment(
            account["id"],
            create_credit_adjustment_payload(200000, account["version"], memo="First raise."),
            headers=make_credit_manager_headers(),
        ),
        200,
    )
    return {"account": account, "first_version": account["version"]}


class TestAccountStaleVersionGuardOnCreditAdjustment:
    """The money-side guard: a credit desk holding a pre-raise view of the line is refused."""

    def test_the_racing_raise_is_refused_and_the_retry_reprices_the_line_in_one_response(self, api):
        """A second adjustment replaying the pre-raise version is refused with 412 and the limit
        holds, and the retry on the re-read version returns the new limit and the recomputed
        headroom in the very same body.

        PRD 2.7: "Resetting a credit line -- a
        `POST /contractor-accounts/{contractorAccountId}/credit-adjustments` request -- must
        carry `expected_contractor_account_version` as a non-optional input field holding the
        client's last observed `version` of the target `ContractorAccount`."

        PRD 2.7: "If that number does not equal the account's current `version`, the adjustment
        is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

        PRD 2.8: "**Account stale-version guard** -- on
        `POST /contractor-accounts/{contractorAccountId}/credit-adjustments`,
        `expected_contractor_account_version` equals the account's `version`, else
        `ERR_STALE_ACCOUNT_VERSION` (412)."

        PRD 3.3: "The new figure replaces `credit_limit_cents`, `credit_available_cents` is
        recomputed against it, and where the account was on hold the release test is re-run
        against the **new** limit: the account transitions `CREDIT_HOLD -> ACTIVE` when
        `credit_used_cents` is at or below the product of `new_credit_limit_cents` and 0.90
        rounded half up."

        PRD 3.3: "The adjustment advances the account's `version` by one, which -- being an
        OCC-guarded write -- is exactly why a second adjustment carrying the same expected
        version fails."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_account_version_on_credit_adjustment_returns_412
        """
        context = _raised_account(api)
        account_id = context["account"]["id"]
        first_version = context["first_version"]

        validate_error(
            api.create_credit_adjustment(
                account_id,
                create_credit_adjustment_payload(300000, first_version, memo="Racing raise."),
                headers=make_credit_manager_headers(),
            ),
            ApiErrorId.STALE_ACCOUNT_VERSION.value,
            412,
        )

        after_refusal = read_account(api, account_id)
        assert_contractor_account(after_refusal)
        # the refused raise moved neither the limit nor the version
        assert after_refusal["credit_limit_cents"] == 200000
        assert_credit_position(after_refusal, 0, 200000)
        assert after_refusal["version"] == first_version + 1

        retried = validate_success(
            api.create_credit_adjustment(
                account_id,
                create_credit_adjustment_payload(
                    300000, after_refusal["version"], memo="Racing raise, retried."
                ),
                headers=make_credit_manager_headers(),
            ),
            200,
        )
        assert retried["credit_limit_cents"] == 300000
        # the response body itself already carries the recomputed headroom
        assert_credit_position(retried, 0, 300000)
        assert retried["version"] == first_version + 2


def _consistency_run(api):
    """A dispatched 6.0 cubic-yard CLASS_A run, two miles out, waiting to be closed out."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-CM1", "Consistency Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api,
        business_name="Consistency Landscapes",
        credit_limit_cents=5000000,
        po_required=False,
        driveway_protection_required=False,
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 6.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=2.0,
        delivery_address="11 Consistency Ct",
        confirm=True,
    )
    truck = seed_truck(
        api,
        truck_code="TRI-CM1",
        axle_class="TRI_AXLE",
        max_payload_lb=60000,
        bed_capacity_cubic_yards=20.0,
        min_driveway_access_class="CLASS_A",
    )
    load = seed_dispatched_load(
        api,
        seeded["order"]["id"],
        truck["id"],
        6.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
        "planner-cm1",
    )
    return {
        "material": catalogue["material"],
        "lot": catalogue["lot"],
        "account": account,
        "order": seeded["order"],
        "line": seeded["lines"][0],
        "truck": truck,
        "load": load,
    }


class TestDeliveryCascadeSettlesWithinItsOwnRequest:
    """Five rows move on one close-out, and the first read of each already shows the new figure."""

    def test_the_close_out_response_and_every_neighbour_read_agree_immediately(self, api):
        """One delivery rewrites the load, the order, the line, the lot, the truck and the credit
        position, and no second read is needed anywhere to observe the settled values.

        PRD 2.9: "There is no background job and no eventual consistency: by the time a 2xx
        response is emitted, every figure the write disturbed has already been recomputed and
        every automatic state transition the new figures imply has already fired."

        PRD 3.5: "The first hop of the close-out stores the three reported values, sets `status`
        to `DELIVERED`, and returns the truck to `AVAILABLE`."

        PRD 3.5: "In the same hop the delivered volume is distributed across the order's bulk
        lines by a **waterfall in `created_at` ascending order**: working through the bulk lines
        from oldest to newest, each line takes the lesser of the volume still to be distributed
        and its own shortfall -- its `line_volume_cubic_yards` minus its
        `delivered_volume_cubic_yards` -- that amount is added to the line's
        `delivered_volume_cubic_yards`, and the remainder to distribute is reduced accordingly;
        if any volume is still left over after the newest bulk line has been filled, the whole
        leftover is added to that last line's `delivered_volume_cubic_yards`."

        PRD 3.5: "Each bulk line's `final_line_price_cents` is then recomputed on the final
        basis, and the order's `final_total_cents` is assembled from those figures."

        PRD 3.4: "Step eight sets the total to the discounted bulk figure plus
        `bagged_subtotal_cents` plus `min_load_fee_cents` plus `delivery_fee_cents`, and under
        the confirm-time variant that total is stored as `quoted_total_cents`."

        PRD 3.5: "When every bulk line's `delivered_volume_cubic_yards` has reached its
        `line_volume_cubic_yards`, the order transitions `ALLOCATED -> FULFILLED`."

        PRD 3.5: "Still within the first hop, the pinned lot's `withdrawn_gross_cubic_yards`
        grows by `actual_net_cubic_yards` plus `spillage_cubic_yards`, its `reserved_cubic_yards`
        is recomputed, and the lot transitions to `DEPLETED` when its `net_sellable_cubic_yards`
        minus its `withdrawn_gross_cubic_yards` has fallen to zero or below."

        PRD 3.2: "Lines on `DRAFT`, `FULFILLED` or `CANCELLED` orders reserve nothing."

        PRD 3.5: "The second hop, caused by the first hop writing `final_total_cents`,
        recomputes the account's `credit_used_cents` and the tagged purchase order's
        `committed_cents`, the latter transitioning `OPEN -> EXHAUSTED` where the commitment has
        reached the limit; and, caused by the first hop creating the container record, it raises
        the account's `pallet_deposit_balance_cents` by the issued count multiplied by the
        per-container deposit."

        PRD 3.3: "`credit_used_cents` is the sum, over the account's orders whose
        `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED` **and** whose
        `settlement_status` is `UNBILLED`, `INVOICED` or `CREDIT_MEMO_ISSUED`, of that order's
        final total where one exists and its quoted total otherwise, minus that order's
        `credit_memo_cents`."

        Design: Corner/consistency_model/delivery_cascade_is_visible_to_the_next_read_with_no_lag
        """
        context = _consistency_run(api)
        order_id = context["order"]["id"]
        # 12000 bulk + 7500 min-load fee + 13500 tri-axle base + 850 mileage
        assert context["order"]["quoted_total_cents"] == 33850

        delivered = validate_success(
            api.deliver_delivery_load(
                context["load"]["id"],
                deliver_payload(6.0, True, 0.0),
                headers=make_dispatch_planner_headers("planner-cm1"),
            ),
            200,
        )
        assert_delivery_load(delivered)
        # the write's own body already reports the settled load
        assert delivered["status"] == "DELIVERED"
        assert delivered["actual_net_cubic_yards"] == pytest.approx(6.00, abs=CENTS)
        assert delivered["driveway_protection_used"] is True

        settled_order = validate_success(
            api.get_material_order(order_id, headers=make_credit_manager_headers()), 200
        )
        assert settled_order["fulfillment_status"] == "FULFILLED"
        # nothing about the basis changed, so the final total lands on the quoted figure
        assert settled_order["final_total_cents"] == 33850
        assert_charge_assembly(settled_order, 33850)

        settled_line = validate_success(
            api.get_order_line(context["line"]["id"], headers=make_credit_manager_headers()), 200
        )
        assert settled_line["delivered_volume_cubic_yards"] == pytest.approx(6.00, abs=CENTS)

        settled_lot = validate_success(
            api.get_inventory_lot(context["lot"]["id"], headers=make_yard_admin_headers()), 200
        )
        assert settled_lot["withdrawn_gross_cubic_yards"] == pytest.approx(6.00, abs=CENTS)
        assert settled_lot["reserved_cubic_yards"] == pytest.approx(0.00, abs=CENTS)
        # 90.00 net less 6.00 withdrawn is still above zero, so the pile stays sellable
        assert settled_lot["status"] == "AVAILABLE"

        settled_truck = validate_success(
            api.get_delivery_truck(context["truck"]["id"], headers=make_dispatch_planner_headers()),
            200,
        )
        # the window release is not deferred to a later sweep
        assert settled_truck["status"] == "AVAILABLE"

        settled_account = validate_success(
            api.get_contractor_account(
                context["account"]["id"], headers=make_credit_manager_headers()
            ),
            200,
        )
        assert_credit_position(settled_account, 33850, 4966150)

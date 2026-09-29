"""Order allocation, regulated-substance clearance and the ammonia pool.

An order tracks two independent dimensions: how much of a campaign's ammonia it
holds, and whether the regulated substance it carries has been cleared. The
pool it draws on is conserved across every reservation and release.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_PRODUCED_EXCEEDS_RESERVED,
    ERR_PRODUCT_MISMATCH,
    ERR_RUN_NOT_COMPLETED,
    ERR_SECURITY_CLASS_INSUFFICIENT,
)
from test_helpers.assertions import (
    assert_money,
    assert_position,
    assert_status,
    assert_tons,
)
from test_helpers.test_users import (
    CM_AUTHOR,
    COMMERCIAL,
    ENG_APPROVER,
    ENG_AUTHOR,
    ENGINEER,
    SO_SCREENER,
    make_commercial_manager_headers,
    make_process_engineer_headers,
)


def _regulated_world(api):
    """An approved 5000-ton campaign, a regulated slate and a secure dome."""
    site = fx.commissioned_site(
        api, spot_gas_index_usd_per_mmbtu=4.2000, rated_ammonia_tpd=1200.0
    )
    run = fx.approved_run(
        api,
        site["train"]["id"],
        author=ENG_AUTHOR,
        approver=ENG_APPROVER,
        window_start="2026-09-01T00:00:00.000Z",
        window_end="2026-09-11T00:00:00.000Z",
        target_ammonia_tons=5000.000,
    )
    line = fx.define_product_line(
        api,
        site["plant"]["id"],
        product_code="AMMONIUM_NITRATE",
        ammonia_tons_per_product_ton=0.213,
        conversion_cost_usd_per_ton=46.255,
        regulated=True,
        priority_rank=2,
    )
    dome = fx.register_storage_asset(
        api,
        site["plant"]["id"],
        asset_kind="DOME",
        product_code="AMMONIUM_NITRATE",
        capacity_tons=20000.000,
        security_class="HIGH_SECURITY",
        seasonal_reserve_pct=0.15,
    )
    return {"site": site, "run": run, "line": line, "dome": dome}


class TestAllocationAndClearanceAdvanceIndependently:
    def test_a_regulated_order_opens_unallocated_and_awaiting_clearance(self, api):
        """Neither dimension has moved when the order is first written.

        Design: Difficulty/non_linear_state_machine/production_order_allocation_and_security_dimensions_advance_independently
        """
        world = _regulated_world(api)

        order = fx.create_order(
            api,
            world["run"]["id"],
            world["line"]["id"],
            world["dome"]["id"],
            requested_tons=1400.000,
        )

        assert_status(order, "UNALLOCATED", field="allocation_status", label="order")
        assert_status(order, "PENDING", field="security_status", label="order")
        assert order["produced_tons"] is None

    def test_a_reservation_survives_a_refused_clearance(self, api):
        """A denial does not undo the tons the order already holds.

        Design: Difficulty/non_linear_state_machine/production_order_allocation_and_security_dimensions_advance_independently
        """
        world = _regulated_world(api)
        order = fx.create_order(
            api,
            world["run"]["id"],
            world["line"]["id"],
            world["dome"]["id"],
            requested_tons=1400.000,
        )
        fx.reserve_order(api, order["id"], world["run"]["id"], 1400.000)

        denied = fx.security_check(api, order["id"], "DENIED", actor=SO_SCREENER)

        assert_status(denied, "RESERVED", field="allocation_status", label="order")
        assert_status(denied, "DENIED", field="security_status", label="order")
        assert_tons(denied["reserved_tons"], 1400.000, "order.reserved_tons")
        assert_tons(
            denied["allocated_ammonia_tons"], 298.200, "order.allocated_ammonia_tons"
        )
        assert denied["security_checked_by_user_id"] == SO_SCREENER
        assert denied["produced_tons"] is None

    def test_the_reservation_draws_down_the_campaign_pool(self, api):
        """The campaign keeps its provisional price and loses the ammonia.

        Design: Difficulty/non_linear_state_machine/production_order_allocation_and_security_dimensions_advance_independently
        """
        world = _regulated_world(api)
        order = fx.create_order(
            api,
            world["run"]["id"],
            world["line"]["id"],
            world["dome"]["id"],
            requested_tons=1400.000,
        )
        fx.reserve_order(api, order["id"], world["run"]["id"], 1400.000)
        fx.security_check(api, order["id"], "DENIED", actor=SO_SCREENER)

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_tons(
            run["unallocated_ammonia_tons"], 4701.800, "run.unallocated_ammonia_tons"
        )
        assert_money(
            run["provisional_unit_cost_usd_per_ton"],
            181.10,
            "run.provisional_unit_cost_usd_per_ton",
        )


class TestSecurityClassOutranksProductMismatch:
    def _mismatched_world(self, api):
        site = fx.commissioned_site(api, rated_ammonia_tpd=1000.0)
        run = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        line = fx.define_product_line(
            api,
            site["plant"]["id"],
            product_code="AMMONIUM_NITRATE",
            ammonia_tons_per_product_ton=0.213,
            conversion_cost_usd_per_ton=46.255,
            regulated=True,
            priority_rank=2,
        )
        tank = fx.register_storage_asset(
            api,
            site["plant"]["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        return {"site": site, "run": run, "line": line, "tank": tank}

    def test_the_destination_security_class_is_answered_first(self, api):
        """A basic tank fails on its clearance before it fails on its product.

        Design: Difficulty/priority_pair_validation_conflict/security_class_insufficient_outranks_product_mismatch_on_order_create
        """
        world = self._mismatched_world(api)

        response = api.create_production_order(
            {
                "run_id": world["run"]["id"],
                "product_line_id": world["line"]["id"],
                "destination_asset_id": world["tank"]["id"],
                "order_code": "POX1",
                "requested_tons": 100.000,
            },
            make_commercial_manager_headers(CM_AUTHOR),
        )
        validate_error(response, ERR_SECURITY_CLASS_INSUFFICIENT, 403)
        assert response.json()["data"]["error_id"] != ERR_PRODUCT_MISMATCH

    def test_the_refused_order_is_never_written(self, api):
        """No order exists on the campaign and its pool is untouched.

        Design: Difficulty/priority_pair_validation_conflict/security_class_insufficient_outranks_product_mismatch_on_order_create
        """
        world = self._mismatched_world(api)
        validate_error(
            api.create_production_order(
                {
                    "run_id": world["run"]["id"],
                    "product_line_id": world["line"]["id"],
                    "destination_asset_id": world["tank"]["id"],
                    "order_code": "POX1",
                    "requested_tons": 100.000,
                },
                make_commercial_manager_headers(CM_AUTHOR),
            ),
            ERR_SECURITY_CLASS_INSUFFICIENT,
            403,
        )

        orders, meta = validate_paginated(
            api.list_production_orders(COMMERCIAL, run_id=world["run"]["id"])
        )
        assert meta["total_count"] == 0, (
            f"expected no orders on the campaign, got {meta['total_count']}"
        )
        assert orders == []

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_tons(
            run["unallocated_ammonia_tons"], 5000.000, "run.unallocated_ammonia_tons"
        )


class TestRunNotCompletedOutranksOverproduction:
    def _running_world(self, api):
        site = fx.commissioned_site(
            api, spot_gas_index_usd_per_mmbtu=4.2000, rated_ammonia_tpd=1200.0
        )
        slate = fx.slate_and_storage(
            api,
            site["plant"]["id"],
            product_code="UREA",
            regulated=False,
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            priority_rank=1,
            asset_kind="TANK",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        run = fx.running_run(
            api,
            site["train"]["id"],
            clock_at="2026-09-01T00:00:00Z",
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        order = fx.reserved_order(
            api, run["id"], slate["line"]["id"], slate["asset"]["id"], 1000.000
        )
        return {"site": site, "slate": slate, "run": run, "order": order}

    def test_an_unsettled_campaign_is_reported_before_the_overproduction(self, api):
        """Producing 2000 against 1000 reserved still fails on the campaign.

        Design: Difficulty/priority_pair_validation_conflict/run_not_completed_outranks_produced_exceeds_reserved_on_produce
        """
        world = self._running_world(api)

        response = api.produce_production_order(
            world["order"]["id"], 2000.000, make_process_engineer_headers(ENG_AUTHOR)
        )
        validate_error(response, ERR_RUN_NOT_COMPLETED, 409)
        assert response.json()["data"]["error_id"] != ERR_PRODUCED_EXCEEDS_RESERVED

    def test_the_refused_production_writes_nothing_anywhere(self, api):
        """The order keeps its reservation and the tank stays empty.

        Design: Difficulty/priority_pair_validation_conflict/run_not_completed_outranks_produced_exceeds_reserved_on_produce
        """
        world = self._running_world(api)
        validate_error(
            api.produce_production_order(
                world["order"]["id"], 2000.000, make_process_engineer_headers(ENG_AUTHOR)
            ),
            ERR_RUN_NOT_COMPLETED,
            409,
        )

        order = validate_success(
            api.get_production_order(world["order"]["id"], COMMERCIAL)
        )
        assert_status(order, "RESERVED", field="allocation_status", label="order")
        assert order["produced_tons"] is None
        assert order["landed_cost_usd"] is None

        tank = validate_success(
            api.get_storage_asset(world["slate"]["asset"]["id"], COMMERCIAL)
        )
        assert_position(tank, on_hand=0.000, label="tank")


class TestAmmoniaMassIsConserved:
    def _pool_world(self, api):
        site = fx.commissioned_site(
            api, spot_gas_index_usd_per_mmbtu=4.2000, rated_ammonia_tpd=1200.0
        )
        slate = fx.slate_and_storage(
            api,
            site["plant"]["id"],
            product_code="UREA",
            regulated=False,
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            priority_rank=1,
            asset_kind="TANK",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        order = fx.create_order(
            api,
            run["id"],
            slate["line"]["id"],
            slate["asset"]["id"],
            requested_tons=1000.000,
        )
        return {"site": site, "slate": slate, "run": run, "order": order}

    def test_the_pool_and_the_order_together_still_hold_the_target(self, api):
        """4420.000 left in the campaign plus 580.000 on the order is 5000.000.

        Design: Difficulty/compensating_invariant/ammonia_mass_conserved_across_reserve_and_release
        """
        world = self._pool_world(api)

        reserved = fx.reserve_order(
            api, world["order"]["id"], world["run"]["id"], 1000.000
        )
        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))

        assert_tons(
            run["unallocated_ammonia_tons"], 4420.000, "run.unallocated_ammonia_tons"
        )
        assert_tons(
            reserved["allocated_ammonia_tons"], 580.000, "order.allocated_ammonia_tons"
        )
        assert_tons(reserved["reserved_tons"], 1000.000, "order.reserved_tons")
        assert_tons(
            run["unallocated_ammonia_tons"] + reserved["allocated_ammonia_tons"],
            5000.000,
            "pool plus allocation",
        )

    def test_releasing_hands_every_ammonia_ton_back(self, api):
        """A release leaves the campaign exactly as it was before the draw.

        Design: Difficulty/compensating_invariant/ammonia_mass_conserved_across_reserve_and_release
        """
        world = self._pool_world(api)
        fx.reserve_order(api, world["order"]["id"], world["run"]["id"], 1000.000)

        released = fx.release_order(api, world["order"]["id"], "CUSTOMER_DEFERRED")

        assert_status(released, "RELEASED", field="allocation_status", label="order")
        assert released["release_reason"] == "CUSTOMER_DEFERRED"
        assert_tons(released["reserved_tons"], 0.000, "order.reserved_tons")
        assert_tons(
            released["allocated_ammonia_tons"], 0.000, "order.allocated_ammonia_tons"
        )
        assert released["produced_tons"] is None

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_tons(
            run["unallocated_ammonia_tons"], 5000.000, "run.unallocated_ammonia_tons"
        )
        assert_status(run, "APPROVED", label="run")

"""Request validation: what passes, what is refused, and what is left untouched.

Several of these rules are conditional — the regulated-substance clearance
check only bites on a regulated line — and every refusal here is expected to
leave the entities it inspected byte-for-byte as it found them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AMMONIA_BALANCE_EXCEEDED,
    ERR_QUOTE_EXPIRED,
    ERR_SECURITY_CLASS_INSUFFICIENT,
    ERR_STORAGE_CAPACITY_EXCEEDED,
    ERR_TASK_PREDECESSOR_NOT_DONE,
)
from test_helpers.assertions import (
    assert_integer,
    assert_position,
    assert_status,
    assert_tons,
    assert_versioned_entity,
)
from test_helpers.test_users import (
    CM_AUTHOR,
    COMMERCIAL,
    ENGINEER,
    LOGISTICS_HEADERS,
    make_commercial_manager_headers,
)


class TestARegulatedOrderIntoAControlledAssetIsAccepted:
    def _controlled_world(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
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
            security_class="CONTROLLED",
            seasonal_reserve_pct=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        return {"site": site, "line": line, "dome": dome, "run": run}

    def test_a_controlled_dome_satisfies_the_clearance_requirement(self, api):
        """The order is written, awaiting clearance and holding nothing yet.

        Design: Corner/validations/order_create_passes_when_regulated_product_goes_to_a_controlled_asset
        """
        world = self._controlled_world(api)

        response = api.create_production_order(
            f.production_order_payload(
                world["run"]["id"],
                world["line"]["id"],
                world["dome"]["id"],
                requested_tons=1000.000,
            ),
            make_commercial_manager_headers(CM_AUTHOR),
        )
        order = validate_success(response, 201)

        assert_status(order, "PENDING", field="security_status", label="order")
        assert_status(order, "UNALLOCATED", field="allocation_status", label="order")
        assert_tons(order["reserved_tons"], 0.000, "order.reserved_tons")
        assert_tons(
            order["allocated_ammonia_tons"], 0.000, "order.allocated_ammonia_tons"
        )
        assert order["produced_tons"] is None
        assert order["landed_cost_usd"] is None

    def test_the_accepted_order_records_its_author_and_draws_nothing(self, api):
        """The clearance signature is still blank and the pool is intact.

        Design: Corner/validations/order_create_passes_when_regulated_product_goes_to_a_controlled_asset
        """
        world = self._controlled_world(api)
        order = fx.create_order(
            api,
            world["run"]["id"],
            world["line"]["id"],
            world["dome"]["id"],
            requested_tons=1000.000,
        )

        assert order["created_by_user_id"] == CM_AUTHOR
        assert order["security_checked_by_user_id"] is None

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_tons(
            run["unallocated_ammonia_tons"], 5000.000, "run.unallocated_ammonia_tons"
        )


class TestAnOpeningBalanceAboveCapacityIsRefused:
    def test_seeding_more_tons_than_the_asset_holds_is_refused(self, api):
        """25000 tons will not fit in a 20000-ton tank.

        Design: Corner/validations/storage_opening_balance_above_capacity_is_rejected
        """
        plant = fx.register_plant(api)
        tank = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )

        response = api.set_opening_balance(tank["id"], 25000.000, LOGISTICS_HEADERS)
        validate_error(response, ERR_STORAGE_CAPACITY_EXCEEDED, 409)

    def test_the_refused_seeding_leaves_the_asset_empty_at_version_one(self, api):
        """Nothing was counted and no version was burned.

        Design: Corner/validations/storage_opening_balance_above_capacity_is_rejected
        """
        plant = fx.register_plant(api)
        tank = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        validate_error(
            api.set_opening_balance(tank["id"], 25000.000, LOGISTICS_HEADERS),
            ERR_STORAGE_CAPACITY_EXCEEDED,
            409,
        )

        stored = validate_success(api.get_storage_asset(tank["id"], LOGISTICS_HEADERS))
        assert_tons(stored["opening_balance_tons"], 0.000, "tank.opening_balance_tons")
        assert_position(
            stored, on_hand=0.000, available=0.000, label="tank"
        )
        assert_versioned_entity(stored, expected_version=1, label="tank")


class TestAReservationCannotOutrunTheAmmoniaPool:
    def _oversized_order(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
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
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        order = fx.create_order(
            api,
            run["id"],
            slate["line"]["id"],
            slate["asset"]["id"],
            requested_tons=9000.000,
        )
        current = validate_success(api.get_production_run(run["id"], COMMERCIAL))
        return {"run": run, "order": order, "run_version": current["version"]}

    def test_nine_thousand_finished_tons_need_more_ammonia_than_exists(self, api):
        """5220.000 embedded ammonia tons will not come out of a 5000-ton pool.

        Design: Corner/validations/reserve_more_ammonia_than_the_run_pool_is_rejected
        """
        world = self._oversized_order(api)

        response = api.reserve_production_order(
            world["order"]["id"],
            9000.000,
            world["run_version"],
            make_commercial_manager_headers(CM_AUTHOR),
        )
        validate_error(response, ERR_AMMONIA_BALANCE_EXCEEDED, 409)

    def test_the_refused_reservation_moves_neither_the_order_nor_the_pool(self, api):
        """The order stays unallocated and the campaign keeps its version.

        Design: Corner/validations/reserve_more_ammonia_than_the_run_pool_is_rejected
        """
        world = self._oversized_order(api)
        validate_error(
            api.reserve_production_order(
                world["order"]["id"],
                9000.000,
                world["run_version"],
                make_commercial_manager_headers(CM_AUTHOR),
            ),
            ERR_AMMONIA_BALANCE_EXCEEDED,
            409,
        )

        order = validate_success(
            api.get_production_order(world["order"]["id"], COMMERCIAL)
        )
        assert_status(order, "UNALLOCATED", field="allocation_status", label="order")
        assert_tons(order["reserved_tons"], 0.000, "order.reserved_tons")
        assert_tons(
            order["allocated_ammonia_tons"], 0.000, "order.allocated_ammonia_tons"
        )

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_tons(
            run["unallocated_ammonia_tons"], 5000.000, "run.unallocated_ammonia_tons"
        )
        assert_versioned_entity(
            run, expected_version=world["run_version"], label="run"
        )


class TestClearanceScreeningOnlyAppliesToRegulatedLines:
    def _mixed_slate(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        plant_id = site["plant"]["id"]
        urea_line = fx.define_product_line(
            api,
            plant_id,
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        an_line = fx.define_product_line(
            api,
            plant_id,
            product_code="AMMONIUM_NITRATE",
            ammonia_tons_per_product_ton=0.213,
            conversion_cost_usd_per_ton=46.255,
            regulated=True,
            priority_rank=2,
        )
        tank = fx.register_storage_asset(
            api,
            plant_id,
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        dome = fx.register_storage_asset(
            api,
            plant_id,
            asset_kind="DOME",
            product_code="AMMONIUM_NITRATE",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        return {
            "run": run,
            "urea_line": urea_line,
            "an_line": an_line,
            "tank": tank,
            "dome": dome,
        }

    def test_a_basic_tank_is_fine_for_an_unregulated_line(self, api):
        """An unregulated order into a BASIC tank opens EXEMPT.

        Design: Corner/validations/security_class_check_applies_only_to_regulated_product_lines
        """
        world = self._mixed_slate(api)

        response = api.create_production_order(
            f.production_order_payload(
                world["run"]["id"],
                world["urea_line"]["id"],
                world["tank"]["id"],
                requested_tons=1000.000,
            ),
            make_commercial_manager_headers(CM_AUTHOR),
        )
        order = validate_success(response, 201)

        assert_status(order, "EXEMPT", field="security_status", label="order")
        assert_status(order, "UNALLOCATED", field="allocation_status", label="order")

    def test_the_same_basic_class_fails_the_regulated_line(self, api):
        """The regulated order is refused and only the first order exists.

        Design: Corner/validations/security_class_check_applies_only_to_regulated_product_lines
        """
        world = self._mixed_slate(api)
        fx.create_order(
            api,
            world["run"]["id"],
            world["urea_line"]["id"],
            world["tank"]["id"],
            requested_tons=1000.000,
        )

        response = api.create_production_order(
            f.production_order_payload(
                world["run"]["id"],
                world["an_line"]["id"],
                world["dome"]["id"],
                requested_tons=1000.000,
            ),
            make_commercial_manager_headers(CM_AUTHOR),
        )
        validate_error(response, ERR_SECURITY_CLASS_INSUFFICIENT, 403)

        orders, meta = validate_paginated(
            api.list_production_orders(COMMERCIAL, run_id=world["run"]["id"])
        )
        assert meta["total_count"] == 1, (
            f"expected only the unregulated order, got {meta['total_count']}"
        )
        assert len(orders) == 1


class TestAnUndoneDependencyIsNamedAsSuch:
    def _started_outage(self, api):
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        world = fx.in_progress_turnaround(
            api,
            plant["id"],
            train["id"],
            "2026-10-01T00:00:00Z",
            durations=(7, 14),
            findings_count=0,
            scope="VESSEL_INSPECTION",
            window_start="2026-10-01T00:00:00.000Z",
            window_end="2026-10-27T00:00:00.000Z",
        )
        world["plant"] = plant
        world["train"] = train
        return world

    def test_completing_the_successor_first_names_the_dependency(self, api):
        """The refusal is about the predecessor, not about the task's own state.

        Design: Corner/validations/predecessor_not_done_is_reported_instead_of_invalid_state
        """
        world = self._started_outage(api)
        _, second = world["tasks"]

        response = api.complete_turnaround_task(second["id"], ENGINEER)
        validate_error(response, ERR_TASK_PREDECESSOR_NOT_DONE, 409)

        pending = validate_success(api.get_turnaround_task(second["id"], ENGINEER))
        assert_status(pending, "PENDING", label="second task")

        outage = validate_success(
            api.get_turnaround(world["turnaround"]["id"], ENGINEER)
        )
        assert_integer(outage["tasks_done_count"], 0, "outage.tasks_done_count")

    def test_finishing_the_predecessor_opens_the_successor(self, api):
        """With its dependency done the successor becomes workable.

        Design: Corner/validations/predecessor_not_done_is_reported_instead_of_invalid_state
        """
        world = self._started_outage(api)
        first, second = world["tasks"]
        validate_error(
            api.complete_turnaround_task(second["id"], ENGINEER),
            ERR_TASK_PREDECESSOR_NOT_DONE,
            409,
        )

        done = validate_success(api.complete_turnaround_task(first["id"], ENGINEER), 200)
        assert_status(done, "DONE", label="first task")

        opened = validate_success(api.get_turnaround_task(second["id"], ENGINEER))
        assert_status(opened, "READY", label="second task")
        assert_integer(opened["earliest_start_day"], 7, "second task.earliest_start_day")

        outage = validate_success(
            api.get_turnaround(world["turnaround"]["id"], ENGINEER)
        )
        assert_integer(outage["tasks_done_count"], 1, "outage.tasks_done_count")
        assert_integer(outage["critical_path_days"], 21, "outage.critical_path_days")

        train = validate_success(api.get_reformer_train(world["train"]["id"], ENGINEER))
        assert_status(train, "DOWN_FOR_TURNAROUND", label="train")


class TestAQuoteCannotBeIssuedAfterItExpires:
    def _lapsed_quote(self, api):
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        line = fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        quote = fx.draft_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="SPOT_INDEX",
            expires_at="2026-08-10T00:00:00.000Z",
        )
        fx.set_clock(api, "2026-08-11T00:00:00Z")
        return {"plant": plant, "line": line, "quote": quote}

    def test_issuing_past_the_expiry_instant_is_refused(self, api):
        """The clock has moved a day beyond the expiry.

        Design: Corner/validations/issue_a_quote_after_its_expiry_is_rejected
        """
        world = self._lapsed_quote(api)

        response = api.issue_price_quote(world["quote"]["id"], COMMERCIAL)
        validate_error(response, ERR_QUOTE_EXPIRED, 409)

    def test_the_lapsed_quote_stays_a_draft_with_nothing_priced(self, api):
        """No basis, no price and no issue stamp were written.

        Design: Corner/validations/issue_a_quote_after_its_expiry_is_rejected
        """
        world = self._lapsed_quote(api)
        validate_error(
            api.issue_price_quote(world["quote"]["id"], COMMERCIAL),
            ERR_QUOTE_EXPIRED,
            409,
        )

        stored = validate_success(
            api.get_price_quote(world["quote"]["id"], COMMERCIAL)
        )
        assert_status(stored, "DRAFT", label="quote")
        assert stored["issued_at"] is None
        assert stored["quoted_price_usd_per_ton"] is None
        assert stored["gas_basis_usd_per_mmbtu"] is None

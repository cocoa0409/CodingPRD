"""Role access: six disjoint write surfaces over one shared read surface.

Each role owns writes no other role may perform, every role may read a plant,
and the entity-backed TerminalOperator is narrowed further still: it may only
acknowledge receipt of a movement addressed to its own asset. Segregation of
duties then splits one role's own surface between two of its people.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TERMINAL_NOT_OWNER,
)
from test_helpers.assertions import (
    assert_status,
    assert_tons,
    assert_versioned_entity,
)
from test_helpers.test_users import (
    ADMIN,
    CM_AUTHOR,
    COMMERCIAL,
    ENG_APPROVER,
    ENG_AUTHOR,
    ENGINEER,
    LOGISTICS_HEADERS,
    READER_ROLE_HEADER_BUILDERS,
    make_commercial_manager_headers,
    make_logistics_coordinator_headers,
    make_process_engineer_headers,
    make_regulatory_admin_headers,
    make_safety_officer_headers,
    make_terminal_operator_headers,
)


class TestEachRoleOwnsItsOwnWriteSurface:
    def test_five_roles_each_perform_the_write_only_they_may(self, api):
        """Registration, commissioning, safety standing, the slate and the yard.

        Design: Corner/rbac/each_opaque_role_performs_its_own_exclusive_write
        """
        plant = validate_success(
            api.create_plant(
                f.plant_payload(
                    name="Yazoo City Complex",
                    permit_limit_tons_30d=12.00,
                    spot_gas_index_usd_per_mmbtu=4.2000,
                ),
                make_regulatory_admin_headers(),
            ),
            201,
        )

        train = validate_success(
            api.create_reformer_train(
                f.reformer_train_payload(plant["id"], rated_ammonia_tpd=1200.0),
                make_process_engineer_headers(),
            ),
            201,
        )
        assert_status(train, "IDLE", label="train")

        updated = validate_success(
            api.post_psm_program_status(
                plant["id"], "OVERDUE", make_safety_officer_headers()
            ),
            200,
        )
        assert updated["psm_program_status"] == "OVERDUE"

        line = validate_success(
            api.create_product_line(
                f.product_line_payload(
                    plant["id"],
                    product_code="UREA",
                    ammonia_tons_per_product_ton=0.580,
                    conversion_cost_usd_per_ton=38.000,
                    regulated=False,
                    priority_rank=1,
                ),
                make_commercial_manager_headers(),
            ),
            201,
        )
        assert line["regulated"] is False

        tank = validate_success(
            api.create_storage_asset(
                f.storage_asset_payload(
                    plant["id"],
                    asset_kind="TANK",
                    product_code="UREA",
                    capacity_tons=20000.000,
                    security_class="BASIC",
                    seasonal_reserve_pct=0.00,
                ),
                make_logistics_coordinator_headers(),
            ),
            201,
        )
        assert_tons(tank["available_tons"], 0.000, "tank.available_tons")

    def test_the_safety_officers_write_restricts_the_plant(self, api):
        """An overdue safety program is the second rung of the posture ladder.

        Design: Corner/rbac/each_opaque_role_performs_its_own_exclusive_write
        """
        plant = fx.register_plant(
            api,
            name="Yazoo City Complex",
            permit_limit_tons_30d=12.00,
            spot_gas_index_usd_per_mmbtu=4.2000,
        )
        fx.set_psm_program_status(api, plant["id"], "OVERDUE")

        current = validate_success(api.get_plant(plant["id"], ADMIN))
        assert_status(current, "RESTRICTED", field="operating_posture", label="plant")
        assert current["exceeded_pollutants"] == []


class TestEveryRoleCanReadThePlant:
    def _plant_and_tank(self, api):
        plant = fx.register_plant(
            api,
            name="Yazoo City Complex",
            permit_limit_tons_30d=12.00,
            spot_gas_index_usd_per_mmbtu=4.2000,
        )
        tank = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        return {"plant": plant, "tank": tank}

    def test_all_six_roles_see_the_same_plant(self, api):
        """The five opaque roles plus the tank's own operator all read it.

        Design: Corner/rbac/every_role_including_the_terminal_operator_can_read_the_plant
        """
        world = self._plant_and_tank(api)
        readers = [builder() for builder in READER_ROLE_HEADER_BUILDERS.values()]
        readers.append(make_terminal_operator_headers(world["tank"]["id"]))
        assert len(readers) == 6

        for headers in readers:
            seen = validate_success(api.get_plant(world["plant"]["id"], headers), 200)
            assert seen["id"] == world["plant"]["id"]
            assert_status(seen, "NORMAL", field="operating_posture", label="plant")
            assert float(seen["permit_limit_tons_30d"]) == 12.00, (
                f"expected the 12.00-ton ceiling, got {seen['permit_limit_tons_30d']}"
            )

    def test_six_reads_burn_no_version(self, api):
        """Reading is not writing, however many roles do it.

        Design: Corner/rbac/every_role_including_the_terminal_operator_can_read_the_plant
        """
        world = self._plant_and_tank(api)
        readers = [builder() for builder in READER_ROLE_HEADER_BUILDERS.values()]
        readers.append(make_terminal_operator_headers(world["tank"]["id"]))
        for headers in readers:
            validate_success(api.get_plant(world["plant"]["id"], headers), 200)

        final = validate_success(api.get_plant(world["plant"]["id"], ADMIN))
        assert_versioned_entity(final, expected_version=1, label="plant")


class TestNoRoleMayReachIntoAnotherRolesSurface:
    def _full_world(self, api):
        plant = fx.register_plant(
            api,
            name="Yazoo City Complex",
            permit_limit_tons_30d=12.00,
            spot_gas_index_usd_per_mmbtu=4.2000,
        )
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        fx.install_charge(
            api,
            train["id"],
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        line = fx.define_product_line(
            api,
            plant["id"],
            product_code="AMMONIUM_NITRATE",
            ammonia_tons_per_product_ton=0.213,
            conversion_cost_usd_per_ton=46.255,
            regulated=True,
            priority_rank=2,
        )
        dome = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="DOME",
            product_code="AMMONIUM_NITRATE",
            capacity_tons=20000.000,
            security_class="CONTROLLED",
            seasonal_reserve_pct=0.00,
        )
        origin = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        dest = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TERMINAL",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        run = fx.approved_run(
            api,
            train["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        order = fx.create_order(
            api, run["id"], line["id"], dome["id"], requested_tons=1000.000
        )
        quote = fx.draft_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="SPOT_INDEX",
            expires_at="2026-12-01T00:00:00.000Z",
        )
        shipment = fx.draft_shipment(
            api,
            origin["id"],
            dest["id"],
            mode="TRUCK",
            tons=20.000,
            distance_miles=50.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-06T00:00:00.000Z",
        )
        current_origin = validate_success(
            api.get_storage_asset(origin["id"], LOGISTICS_HEADERS)
        )
        return {
            "plant": plant,
            "run": run,
            "order": order,
            "quote": quote,
            "shipment": shipment,
            "origin": origin,
            "origin_version": current_origin["version"],
        }

    def _forbidden_calls(self, api, world):
        return (
            api.approve_production_run(
                world["run"]["id"], make_commercial_manager_headers(CM_AUTHOR)
            ),
            api.security_check_production_order(
                world["order"]["id"],
                "CLEARED",
                make_process_engineer_headers(ENG_AUTHOR),
            ),
            api.issue_price_quote(
                world["quote"]["id"], make_logistics_coordinator_headers()
            ),
            api.create_storage_asset(
                f.storage_asset_payload(
                    world["plant"]["id"],
                    asset_kind="TANK",
                    product_code="UREA",
                    capacity_tons=5000.000,
                    security_class="BASIC",
                    seasonal_reserve_pct=0.00,
                ),
                make_safety_officer_headers(),
            ),
            api.book_shipment(
                world["shipment"]["id"],
                world["origin_version"],
                make_regulatory_admin_headers(),
            ),
        )

    def test_five_cross_role_writes_are_all_refused(self, api):
        """Approval, clearance, issue, yard registration and booking each bounce.

        Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_write
        """
        world = self._full_world(api)

        for response in self._forbidden_calls(api, world):
            validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

    def test_none_of_the_refused_writes_left_a_trace(self, api):
        """Every entity holds the state the authorised setup left it in.

        Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_write
        """
        world = self._full_world(api)
        for response in self._forbidden_calls(api, world):
            validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_status(run, "APPROVED", label="run")

        order = validate_success(
            api.get_production_order(world["order"]["id"], COMMERCIAL)
        )
        assert_status(order, "PENDING", field="security_status", label="order")

        quote = validate_success(api.get_price_quote(world["quote"]["id"], COMMERCIAL))
        assert_status(quote, "DRAFT", label="quote")

        shipment = validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(shipment, "DRAFT", label="shipment")

        origin = validate_success(
            api.get_storage_asset(world["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_versioned_entity(
            origin, expected_version=world["origin_version"], label="origin"
        )

        _, meta = validate_paginated(
            api.list_storage_assets(LOGISTICS_HEADERS, plant_id=world["plant"]["id"])
        )
        assert meta["total_count"] == 3, (
            f"expected the three authorised assets, got {meta['total_count']}"
        )


class TestOnlyTheAddressedTerminalMayAcknowledgeReceipt:
    def _in_transit_move(self, api):
        plant = fx.register_plant(
            api,
            name="Yazoo City Complex",
            permit_limit_tons_30d=12.00,
            spot_gas_index_usd_per_mmbtu=4.2000,
        )
        origin = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        dest = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TERMINAL",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        fx.set_opening_balance(api, origin["id"], 5000.000)
        shipment = fx.draft_shipment(
            api,
            origin["id"],
            dest["id"],
            mode="TRUCK",
            tons=20.000,
            distance_miles=50.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-06T00:00:00.000Z",
        )
        fx.book_shipment(api, shipment["id"], origin["id"])
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        fx.depart_shipment(api, shipment["id"])
        return {"origin": origin, "dest": dest, "shipment": shipment}

    def test_the_shipping_end_is_not_the_receiving_end(self, api):
        """The origin tank's own operator is not the owner of this delivery.

        Design: Corner/rbac/terminal_operator_cannot_deliver_a_shipment_bound_elsewhere
        """
        world = self._in_transit_move(api)

        response = api.deliver_shipment(
            world["shipment"]["id"],
            20.000,
            make_terminal_operator_headers(world["origin"]["id"]),
        )
        validate_error(response, ERR_TERMINAL_NOT_OWNER, 403)

        shipment = validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(shipment, "IN_TRANSIT", label="shipment")

        origin = validate_success(
            api.get_storage_asset(world["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(origin["on_hand_tons"], 5000.000, "origin.on_hand_tons")

        dest = validate_success(
            api.get_storage_asset(world["dest"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(dest["on_hand_tons"], 0.000, "dest.on_hand_tons")

    def test_the_addressed_terminal_acknowledges_and_the_tons_move(self, api):
        """The 20 tons leave the tank, release their hold and land at the terminal.

        Design: Corner/rbac/terminal_operator_cannot_deliver_a_shipment_bound_elsewhere
        """
        world = self._in_transit_move(api)
        validate_error(
            api.deliver_shipment(
                world["shipment"]["id"],
                20.000,
                make_terminal_operator_headers(world["origin"]["id"]),
            ),
            ERR_TERMINAL_NOT_OWNER,
            403,
        )

        delivered = validate_success(
            api.deliver_shipment(
                world["shipment"]["id"],
                20.000,
                make_terminal_operator_headers(world["dest"]["id"]),
            ),
            200,
        )
        assert_status(delivered, "DELIVERED", label="shipment")
        assert_tons(delivered["received_tons"], 20.000, "shipment.received_tons")

        origin = validate_success(
            api.get_storage_asset(world["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(origin["on_hand_tons"], 4980.000, "origin.on_hand_tons")
        assert_tons(origin["reserved_tons"], 0.000, "origin.reserved_tons")

        dest = validate_success(
            api.get_storage_asset(world["dest"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(dest["on_hand_tons"], 20.000, "dest.on_hand_tons")


class TestACampaignNeedsASecondSignature:
    def _planned_campaign(self, api):
        plant = fx.register_plant(
            api,
            name="Yazoo City Complex",
            permit_limit_tons_30d=12.00,
            spot_gas_index_usd_per_mmbtu=4.2000,
        )
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        fx.install_charge(
            api,
            train["id"],
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        run = fx.schedule_run(
            api,
            train["id"],
            author=ENG_AUTHOR,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        return {"train": train, "run": run}

    def test_the_author_may_not_approve_its_own_campaign(self, api):
        """Same role, same person, and that is precisely what is refused.

        Design: Corner/rbac/a_run_approved_by_its_own_author_is_forbidden
        """
        world = self._planned_campaign(api)

        response = api.approve_production_run(
            world["run"]["id"], make_process_engineer_headers(ENG_AUTHOR)
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_status(run, "PLANNED", label="run")
        assert run["provisional_unit_cost_usd_per_ton"] is None
        assert_versioned_entity(run, expected_version=1, label="run")
        assert run["created_by_user_id"] == ENG_AUTHOR

    def test_a_second_engineer_approves_the_same_campaign(self, api):
        """The role was never the problem; the identity was.

        Design: Corner/rbac/a_run_approved_by_its_own_author_is_forbidden
        """
        world = self._planned_campaign(api)
        validate_error(
            api.approve_production_run(
                world["run"]["id"], make_process_engineer_headers(ENG_AUTHOR)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        approved = validate_success(
            api.approve_production_run(
                world["run"]["id"], make_process_engineer_headers(ENG_APPROVER)
            ),
            200,
        )
        assert_status(approved, "APPROVED", label="run")
        assert_versioned_entity(approved, expected_version=2, label="run")

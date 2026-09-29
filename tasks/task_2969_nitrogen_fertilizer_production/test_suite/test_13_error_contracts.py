"""Error contracts: identity envelopes, unknown ids and refused writes.

Every resource resolves its own not-found code, an unusable identity envelope is
answered before any resource is looked at, and each refused write here leaves
the entities it touched exactly as it found them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CATALYST_CHARGE_NOT_FOUND,
    ERR_EMISSIONS_READING_IN_FUTURE,
    ERR_EMISSIONS_READING_NOT_FOUND,
    ERR_HEDGE_LOT_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PRODUCT_LINE_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_SECURITY_CHECK_NOT_CLEARED,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_STORAGE_ASSET_NOT_FOUND,
    ERR_TASK_CYCLE_DETECTED,
    ERR_TASK_NOT_FOUND,
    ERR_TRAIN_UNAVAILABLE,
    ERR_TURNAROUND_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.assertions import (
    assert_integer,
    assert_response_type,
    assert_status,
    assert_tons,
    assert_versioned_entity,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.test_users import (
    ADMIN,
    COMMERCIAL,
    ENG_AUTHOR,
    ENGINEER,
    LOGISTICS_HEADERS,
    SAFETY,
    SO_CLEARER,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    make_process_engineer_headers,
    make_safety_officer_headers,
)


class TestEveryChildResourceResolvesItsOwnNotFound:
    def test_an_unused_uuid_is_not_found_on_each_child_resource(self, api):
        """Eleven reads, eleven distinct not-found codes, all at 404.

        Design: Corner/errors/unknown_ids_are_not_found_on_every_child_resource
        """
        reads = (
            (api.get_catalyst_charge(UNKNOWN_UUID, ENGINEER), ERR_CATALYST_CHARGE_NOT_FOUND),
            (api.get_gas_hedge_lot(UNKNOWN_UUID, COMMERCIAL), ERR_HEDGE_LOT_NOT_FOUND),
            (api.get_product_line(UNKNOWN_UUID, COMMERCIAL), ERR_PRODUCT_LINE_NOT_FOUND),
            (api.get_production_run(UNKNOWN_UUID, ENGINEER), ERR_RUN_NOT_FOUND),
            (api.get_production_order(UNKNOWN_UUID, COMMERCIAL), ERR_ORDER_NOT_FOUND),
            (
                api.get_storage_asset(UNKNOWN_UUID, LOGISTICS_HEADERS),
                ERR_STORAGE_ASSET_NOT_FOUND,
            ),
            (api.get_shipment(UNKNOWN_UUID, LOGISTICS_HEADERS), ERR_SHIPMENT_NOT_FOUND),
            (api.get_price_quote(UNKNOWN_UUID, COMMERCIAL), ERR_QUOTE_NOT_FOUND),
            (api.get_turnaround(UNKNOWN_UUID, SAFETY), ERR_TURNAROUND_NOT_FOUND),
            (api.get_turnaround_task(UNKNOWN_UUID, SAFETY), ERR_TASK_NOT_FOUND),
            (
                api.get_emissions_reading(UNKNOWN_UUID, ADMIN),
                ERR_EMISSIONS_READING_NOT_FOUND,
            ),
        )

        for response, expected in reads:
            validate_error(response, expected, 404)
            assert_response_type(response, "error")


class TestAnUnusableIdentityEnvelopeIsAnsweredFirst:
    def test_a_present_but_empty_user_id_is_unauthenticated(self, api):
        """The zero-length identifier is not an identity.

        Design: Corner/errors/an_empty_x_user_id_header_is_unauthenticated
        """
        response = api.list_plants(headers_with_empty_user_id())

        validate_error(response, ERR_UNAUTHENTICATED, 401)
        assert_response_type(response, "error")

    def test_the_refused_read_carries_no_collection_payload(self, api):
        """An error envelope holds no listing at all.

        Design: Corner/errors/an_empty_x_user_id_header_is_unauthenticated
        """
        fx.register_plant(api)

        body = api.list_plants(headers_with_empty_user_id()).json()

        assert "items" not in body, "an error envelope must carry no items key"
        assert "items" not in body.get("data", {}), (
            "an error payload must carry no items key"
        )

    def test_a_role_outside_the_declared_set_is_refused(self, api):
        """A plant janitor is not one of the six roles this service knows.

        Design: Corner/errors/an_undeclared_role_header_is_rejected
        """
        response = api.list_plants(headers_with_unknown_role("janitor-1"))

        validate_error(response, ERR_UNKNOWN_ROLE, 401)
        assert_response_type(response, "error")


class TestAReadingAheadOfTheClockIsRefused:
    def test_a_reading_stamped_in_the_future_is_a_malformed_request(self, api):
        """The clock has not reached September yet.

        Design: Corner/errors/an_emissions_reading_ahead_of_the_clock_is_rejected
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)

        response = api.create_emissions_reading(
            f.emissions_reading_payload(
                plant["id"],
                pollutant="NOX",
                rate_lb_per_hour=5.000,
                interval_hours=24.0,
                reading_at="2026-09-01T00:00:00.000Z",
            ),
            ADMIN,
        )
        validate_error(response, ERR_EMISSIONS_READING_IN_FUTURE, 422)

    def test_the_refused_reading_leaves_the_plant_untouched(self, api):
        """No reading was stored and no posture was recomputed.

        Design: Corner/errors/an_emissions_reading_ahead_of_the_clock_is_rejected
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)
        validate_error(
            api.create_emissions_reading(
                f.emissions_reading_payload(
                    plant["id"],
                    pollutant="NOX",
                    rate_lb_per_hour=5.000,
                    interval_hours=24.0,
                    reading_at="2026-09-01T00:00:00.000Z",
                ),
                ADMIN,
            ),
            ERR_EMISSIONS_READING_IN_FUTURE,
            422,
        )

        _, meta = validate_paginated(
            api.list_emissions_readings(ADMIN, plant_id=plant["id"])
        )
        assert meta["total_count"] == 0, (
            f"expected no readings stored, got {meta['total_count']}"
        )

        stored = validate_success(api.get_plant(plant["id"], ADMIN))
        assert stored["exceeded_pollutants"] == []
        assert_status(stored, "NORMAL", field="operating_posture", label="plant")
        assert_versioned_entity(stored, expected_version=1, label="plant")


class TestADependencyAcrossOutagesIsACycle:
    def _two_outages(self, api):
        plant = fx.register_plant(api)
        first_train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        second_train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=900.0)
        first = fx.author_turnaround(
            api,
            plant["id"],
            first_train["id"],
            scope="VESSEL_INSPECTION",
            window_start="2026-10-01T00:00:00.000Z",
            window_end="2026-10-27T00:00:00.000Z",
        )
        second = fx.author_turnaround(
            api,
            plant["id"],
            second_train["id"],
            scope="CATALYST_CHANGE",
            window_start="2026-11-01T00:00:00.000Z",
            window_end="2026-11-27T00:00:00.000Z",
        )
        own_task = fx.add_task(api, first["id"], 7)
        foreign_task = fx.add_task(api, second["id"], 5)
        return {
            "first": first,
            "second": second,
            "own_task": own_task,
            "foreign_task": foreign_task,
        }

    def test_naming_a_step_from_another_outage_is_refused(self, api):
        """A dependency may not reach outside its own outage.

        Design: Corner/errors/a_predecessor_in_another_outage_is_rejected_as_a_cycle
        """
        world = self._two_outages(api)

        response = api.create_turnaround_task(
            f.turnaround_task_payload(
                world["first"]["id"],
                duration_days=3,
                predecessor_task_id=world["foreign_task"]["id"],
            ),
            ENGINEER,
        )
        validate_error(response, ERR_TASK_CYCLE_DETECTED, 409)

    def test_the_refused_step_is_never_added_to_either_outage(self, api):
        """Both outages keep the single step each already had.

        Design: Corner/errors/a_predecessor_in_another_outage_is_rejected_as_a_cycle
        """
        world = self._two_outages(api)
        validate_error(
            api.create_turnaround_task(
                f.turnaround_task_payload(
                    world["first"]["id"],
                    duration_days=3,
                    predecessor_task_id=world["foreign_task"]["id"],
                ),
                ENGINEER,
            ),
            ERR_TASK_CYCLE_DETECTED,
            409,
        )

        first = validate_success(api.get_turnaround(world["first"]["id"], ENGINEER))
        assert_integer(first["tasks_total_count"], 1, "first outage.tasks_total_count")
        assert_integer(first["critical_path_days"], 7, "first outage.critical_path_days")

        second = validate_success(api.get_turnaround(world["second"]["id"], ENGINEER))
        assert_integer(second["tasks_total_count"], 1, "second outage.tasks_total_count")

        tasks, meta = validate_paginated(
            api.list_turnaround_tasks(ENGINEER, turnaround_id=world["first"]["id"])
        )
        assert meta["total_count"] == 1, (
            f"expected one step on the first outage, got {meta['total_count']}"
        )
        assert len(tasks) == 1


class TestACampaignCannotBeScheduledOnATrainInOutage:
    def _downed_train(self, api):
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        fx.in_progress_turnaround(
            api,
            plant["id"],
            train["id"],
            "2026-10-01T00:00:00Z",
            durations=(7,),
            findings_count=0,
            scope="VESSEL_INSPECTION",
            window_start="2026-10-01T00:00:00.000Z",
            window_end="2026-10-27T00:00:00.000Z",
        )
        return {"plant": plant, "train": train}

    def test_a_train_down_for_turnaround_takes_no_new_campaign(self, api):
        """Even a December window is refused while the train is out of service.

        Design: Corner/errors/scheduling_a_run_on_a_train_in_outage_is_rejected
        """
        world = self._downed_train(api)

        response = api.create_production_run(
            f.production_run_payload(
                world["train"]["id"],
                window_start="2026-12-01T00:00:00.000Z",
                window_end="2026-12-11T00:00:00.000Z",
                target_ammonia_tons=5000.000,
            ),
            make_process_engineer_headers(ENG_AUTHOR),
        )
        validate_error(response, ERR_TRAIN_UNAVAILABLE, 409)

    def test_the_refused_campaign_is_never_written(self, api):
        """The train stays down and holds no campaigns at all.

        Design: Corner/errors/scheduling_a_run_on_a_train_in_outage_is_rejected
        """
        world = self._downed_train(api)
        validate_error(
            api.create_production_run(
                f.production_run_payload(
                    world["train"]["id"],
                    window_start="2026-12-01T00:00:00.000Z",
                    window_end="2026-12-11T00:00:00.000Z",
                    target_ammonia_tons=5000.000,
                ),
                make_process_engineer_headers(ENG_AUTHOR),
            ),
            ERR_TRAIN_UNAVAILABLE,
            409,
        )

        train = validate_success(api.get_reformer_train(world["train"]["id"], ENGINEER))
        assert_status(train, "DOWN_FOR_TURNAROUND", label="train")

        _, meta = validate_paginated(
            api.list_production_runs(ENGINEER, train_id=world["train"]["id"])
        )
        assert meta["total_count"] == 0, (
            f"expected no campaigns on the downed train, got {meta['total_count']}"
        )


class TestARegulatedOrderCannotBeProducedBeforeClearance:
    def _settled_regulated_order(self, api):
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
        order = fx.reserved_order(api, run["id"], line["id"], dome["id"], 1000.000)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"])
        fx.complete_run(api, run["id"], 5000.000, 240.0)
        return {"site": site, "line": line, "dome": dome, "run": run, "order": order}

    def test_producing_a_pending_regulated_order_is_refused(self, api):
        """The reservation is settled but the clearance decision is still pending.

        Design: Corner/errors/producing_a_regulated_order_before_clearance_is_rejected
        """
        world = self._settled_regulated_order(api)

        response = api.produce_production_order(
            world["order"]["id"], 1000.000, make_process_engineer_headers(ENG_AUTHOR)
        )
        validate_error(response, ERR_SECURITY_CHECK_NOT_CLEARED, 409)

        order = validate_success(
            api.get_production_order(world["order"]["id"], COMMERCIAL)
        )
        assert_status(order, "RESERVED", field="allocation_status", label="order")
        assert order["produced_tons"] is None

        dome = validate_success(
            api.get_storage_asset(world["dome"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(dome["on_hand_tons"], 0.000, "dome.on_hand_tons")

    def test_the_clearance_decision_records_the_officer_who_made_it(self, api):
        """A cleared order names its clearing officer.

        Design: Corner/errors/producing_a_regulated_order_before_clearance_is_rejected
        """
        world = self._settled_regulated_order(api)
        validate_error(
            api.produce_production_order(
                world["order"]["id"], 1000.000, make_process_engineer_headers(ENG_AUTHOR)
            ),
            ERR_SECURITY_CHECK_NOT_CLEARED,
            409,
        )

        cleared = validate_success(
            api.security_check_production_order(
                world["order"]["id"], "CLEARED", make_safety_officer_headers(SO_CLEARER)
            ),
            200,
        )
        assert_status(cleared, "CLEARED", field="security_status", label="order")
        assert cleared["security_checked_by_user_id"] == SO_CLEARER

    def test_the_same_production_call_succeeds_once_cleared(self, api):
        """Clearance is the only thing that was missing.

        Design: Corner/errors/producing_a_regulated_order_before_clearance_is_rejected
        """
        world = self._settled_regulated_order(api)
        validate_error(
            api.produce_production_order(
                world["order"]["id"], 1000.000, make_process_engineer_headers(ENG_AUTHOR)
            ),
            ERR_SECURITY_CHECK_NOT_CLEARED,
            409,
        )
        fx.security_check(api, world["order"]["id"], "CLEARED", actor=SO_CLEARER)

        produced = validate_success(
            api.produce_production_order(
                world["order"]["id"], 1000.000, make_process_engineer_headers(ENG_AUTHOR)
            ),
            200,
        )
        assert_status(produced, "CONSUMED", field="allocation_status", label="order")
        assert_tons(produced["produced_tons"], 1000.000, "order.produced_tons")

        dome = validate_success(
            api.get_storage_asset(world["dome"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(dome["on_hand_tons"], 1000.000, "dome.on_hand_tons")

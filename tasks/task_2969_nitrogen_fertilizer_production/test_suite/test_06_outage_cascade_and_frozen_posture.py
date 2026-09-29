"""Taking a train down, and the plant posture that gates logistics.

Starting an outage on a running train unwinds everything downstream of it: the
campaign, its orders, their movements and the tons those movements had reserved.
A suspended air permit freezes the plant and stops a booking outright.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PLANT_FROZEN, ERR_STALE_STORAGE_VERSION
from test_helpers.assertions import (
    assert_integer,
    assert_position,
    assert_status,
    assert_tons,
)
from test_helpers.test_users import (
    COMMERCIAL,
    ENG_APPROVER,
    ENG_AUTHOR,
    ENGINEER,
    LOGISTICS_HEADERS,
)


def _cascade_world(api):
    """A running campaign, its order and movement, behind an approved outage."""
    site = fx.commissioned_site(
        api,
        spot_gas_index_usd_per_mmbtu=4.2000,
        rated_ammonia_tpd=1200.0,
        design_life_hours=40000.0,
        baseline_operating_hours=0.0,
        poisoning_index=0.00,
    )
    plant_id = site["plant"]["id"]
    line = fx.define_product_line(
        api,
        plant_id,
        product_code="UREA",
        ammonia_tons_per_product_ton=0.580,
        conversion_cost_usd_per_ton=38.000,
        regulated=False,
        priority_rank=1,
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
    fx.set_opening_balance(api, tank["id"], 5000.000)
    receiver = fx.register_storage_asset(
        api,
        plant_id,
        asset_kind="TERMINAL",
        product_code="UREA",
        capacity_tons=20000.000,
        security_class="BASIC",
        seasonal_reserve_pct=0.00,
    )
    running = fx.running_run(
        api,
        site["train"]["id"],
        clock_at="2026-09-01T00:00:00Z",
        author=ENG_AUTHOR,
        approver=ENG_APPROVER,
        window_start="2026-09-01T00:00:00.000Z",
        window_end="2026-09-11T00:00:00.000Z",
        target_ammonia_tons=5000.000,
    )
    collateral = fx.approved_run(
        api,
        site["train"]["id"],
        author=ENG_AUTHOR,
        approver=ENG_APPROVER,
        window_start="2026-10-05T00:00:00.000Z",
        window_end="2026-10-10T00:00:00.000Z",
        target_ammonia_tons=3000.000,
    )
    order = fx.reserved_order(
        api, running["id"], line["id"], tank["id"], 1000.000
    )
    shipment = fx.draft_shipment(
        api,
        tank["id"],
        receiver["id"],
        mode="RAIL",
        tons=1000.000,
        distance_miles=200.0,
        window_start="2026-09-05T00:00:00.000Z",
        window_end="2026-09-08T00:00:00.000Z",
        production_order_id=order["id"],
    )
    shipment = fx.book_shipment(api, shipment["id"], tank["id"])
    outage = fx.approved_turnaround_world(
        api,
        plant_id,
        site["train"]["id"],
        durations=(7, 14, 5),
        findings_count=0,
        scope="COMBINED",
        window_start="2026-11-01T00:00:00.000Z",
        window_end="2026-11-27T00:00:00.000Z",
    )
    fx.set_clock(api, "2026-11-01T00:00:00Z")
    return {
        "site": site,
        "line": line,
        "tank": tank,
        "receiver": receiver,
        "running": running,
        "collateral": collateral,
        "order": order,
        "shipment": shipment,
        "outage": outage,
    }


class TestOutageStartCascadesToTheStoragePosition:
    def test_starting_the_outage_takes_the_running_train_down(self, api):
        """The outage begins and the train it names goes out of service.

        Design: Difficulty/transitive_cascade/outage_start_cascades_five_levels_to_storage_position
        """
        world = _cascade_world(api)

        started = fx.start_turnaround(api, world["outage"]["turnaround"]["id"])

        assert_status(started, "IN_PROGRESS", label="turnaround")
        assert_integer(started["critical_path_days"], 26, "turnaround.critical_path_days")
        assert_integer(started["window_days"], 26, "turnaround.window_days")

        train = validate_success(
            api.get_reformer_train(world["site"]["train"]["id"], ENGINEER)
        )
        assert_status(train, "DOWN_FOR_TURNAROUND", label="train")

    def test_the_running_campaign_is_aborted_and_the_next_one_loses_approval(self, api):
        """The live campaign is abandoned and the later one falls back to PLANNED.

        Design: Difficulty/transitive_cascade/outage_start_cascades_five_levels_to_storage_position
        """
        world = _cascade_world(api)
        fx.start_turnaround(api, world["outage"]["turnaround"]["id"])

        aborted = validate_success(
            api.get_production_run(world["running"]["id"], ENGINEER)
        )
        assert_status(aborted, "ABORTED", label="running campaign")
        assert aborted["abort_reason"] == "TRAIN_DOWN_FOR_TURNAROUND"
        assert_tons(
            aborted["unallocated_ammonia_tons"],
            5000.000,
            "run.unallocated_ammonia_tons",
        )

        collateral = validate_success(
            api.get_production_run(world["collateral"]["id"], ENGINEER)
        )
        assert_status(collateral, "PLANNED", label="collateral campaign")
        assert collateral["provisional_unit_cost_usd_per_ton"] is None

    def test_the_order_is_released_and_its_movement_is_cancelled(self, api):
        """Two more levels down, the order and its shipment are both unwound.

        Design: Difficulty/transitive_cascade/outage_start_cascades_five_levels_to_storage_position
        """
        world = _cascade_world(api)
        fx.start_turnaround(api, world["outage"]["turnaround"]["id"])

        order = validate_success(
            api.get_production_order(world["order"]["id"], COMMERCIAL)
        )
        assert_status(order, "RELEASED", field="allocation_status", label="order")
        assert order["release_reason"] == "RUN_ABORTED"
        assert_tons(order["reserved_tons"], 0.000, "order.reserved_tons")
        assert_tons(
            order["allocated_ammonia_tons"], 0.000, "order.allocated_ammonia_tons"
        )

        shipment = validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(shipment, "CANCELLED", label="shipment")
        assert shipment["cancel_reason"] == "UPSTREAM_ALLOCATION_RELEASED"

    def test_the_storage_position_is_handed_back_its_reserved_tons(self, api):
        """The cancelled movement releases its hold and nothing was shipped.

        Design: Difficulty/transitive_cascade/outage_start_cascades_five_levels_to_storage_position
        """
        world = _cascade_world(api)
        fx.start_turnaround(api, world["outage"]["turnaround"]["id"])

        tank = validate_success(
            api.get_storage_asset(world["tank"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            tank,
            on_hand=5000.000,
            reserved=0.000,
            available=5000.000,
            label="tank",
        )

    def test_the_task_chain_opens_only_at_its_head(self, api):
        """The first step is workable and its successors keep their offsets.

        Design: Difficulty/transitive_cascade/outage_start_cascades_five_levels_to_storage_position
        """
        world = _cascade_world(api)
        fx.start_turnaround(api, world["outage"]["turnaround"]["id"])
        first, second, third = world["outage"]["tasks"]

        head = validate_success(api.get_turnaround_task(first["id"], ENGINEER))
        assert_status(head, "READY", label="first task")

        middle = validate_success(api.get_turnaround_task(second["id"], ENGINEER))
        assert_status(middle, "PENDING", label="second task")

        tail = validate_success(api.get_turnaround_task(third["id"], ENGINEER))
        assert_status(tail, "PENDING", label="third task")
        assert_integer(tail["earliest_start_day"], 21, "task.earliest_start_day")


class TestFrozenPostureBlocksBooking:
    def _frozen_world(self, api):
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        pair = fx.terminal_pair(
            api,
            plant["id"],
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
            origin_opening_tons=10000.000,
        )
        shipment = fx.draft_shipment(
            api,
            pair["origin"]["id"],
            pair["dest"]["id"],
            mode="RAIL",
            tons=1000.000,
            distance_miles=100.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-10T00:00:00.000Z",
        )
        fx.set_permit_status(api, plant["id"], "SUSPENDED")
        origin = validate_success(
            api.get_storage_asset(pair["origin"]["id"], LOGISTICS_HEADERS)
        )
        return {"plant": plant, "pair": pair, "shipment": shipment, "origin": origin}

    def test_a_frozen_plant_refuses_the_booking_on_its_own_terms(self, api):
        """The origin version is current, so only the freeze can be the reason.

        Design: Difficulty/cross_entity_state_dependency/shipment_booking_blocked_by_frozen_plant_posture
        """
        world = self._frozen_world(api)

        response = api.book_shipment(
            world["shipment"]["id"], world["origin"]["version"], LOGISTICS_HEADERS
        )
        validate_error(response, ERR_PLANT_FROZEN, 409)
        assert response.json()["data"]["error_id"] != ERR_STALE_STORAGE_VERSION

    def test_the_suspended_permit_is_what_froze_the_plant(self, api):
        """A suspended air permit reads through to a frozen operating posture.

        Design: Difficulty/cross_entity_state_dependency/shipment_booking_blocked_by_frozen_plant_posture
        """
        world = self._frozen_world(api)
        validate_error(
            api.book_shipment(
                world["shipment"]["id"], world["origin"]["version"], LOGISTICS_HEADERS
            ),
            ERR_PLANT_FROZEN,
            409,
        )

        plant = validate_success(api.get_plant(world["plant"]["id"], ENGINEER))
        assert_status(plant, "SUSPENDED", field="permit_status", label="plant")
        assert_status(plant, "FROZEN", field="operating_posture", label="plant")

    def test_the_refused_booking_prices_nothing_and_reserves_nothing(self, api):
        """The movement stays a draft with no freight and no hold on the origin.

        Design: Difficulty/cross_entity_state_dependency/shipment_booking_blocked_by_frozen_plant_posture
        """
        world = self._frozen_world(api)
        validate_error(
            api.book_shipment(
                world["shipment"]["id"], world["origin"]["version"], LOGISTICS_HEADERS
            ),
            ERR_PLANT_FROZEN,
            409,
        )

        shipment = validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(shipment, "DRAFT", label="shipment")
        assert shipment["base_freight_usd"] is None
        assert shipment["freight_total_usd"] is None

        origin = validate_success(
            api.get_storage_asset(world["pair"]["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(origin["reserved_tons"], 0.000, "origin.reserved_tons")

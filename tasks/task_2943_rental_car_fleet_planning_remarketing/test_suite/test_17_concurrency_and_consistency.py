"""Two cross-cutting layers: the second optimistic-concurrency guard, and the
promise that every derived counter is correct on first observation.

The concurrency guard here hangs off `Vehicle` rather than `FleetPlan`, so the
thing that invalidates a held version is an ordinary usage posting rather than a
sibling write on the parent. The consistency case reads four levels of the
hierarchy exactly once each, with no retry anywhere.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    ConsignmentStatus,
    EntryType,
    FleetStatus,
    PlanStatus,
    SourceEntityType,
    TaskStatus,
    factories,
    fixtures,
    make_fleet_controller_headers,
    make_remarketing_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_instant_equals,
    entries_of_type,
    total_count,
)


class TestStaleVehicleVersionOnConsignmentCreate:
    """The held version is invalidated by a write on the vehicle itself."""

    def _driven_car_with_a_stale_read(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="OC",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]
        stale_version = fixtures.read_vehicle(client, vehicle_id)["version"]
        fixtures.post_usage(
            client,
            world,
            vehicle_id,
            5000,
            rented_days_delta=10,
            available_days_delta=12,
            revenue_cents_delta=55000,
        )
        return vehicle_id, stale_version

    def test_the_usage_posting_invalidates_the_read_and_the_create_is_refused(
        self, client, world
    ):
        """One posting between the read and the create costs the writer its turn.

        PRD 2.7: "Creating a consignment requires `expected_vehicle_version` in the
        request body, carrying the `version` the client last observed on that `Vehicle`.
        If it does not equal the vehicle's current `version`, the create is rejected
        with `ERR_STALE_VEHICLE_VERSION` (HTTP 412)."
        PRD 2.7: "A new consignment legitimately supersedes a withdrawn one on the same
        vehicle, so a writer holding a fresh version always succeeds; the rejection
        catches the case where a usage posting, a damage report or a withdrawal has
        already moved the vehicle's odometer, condition or hold baseline, invalidating
        the valuation on which the channel choice was made."
        PRD 3.5: "The posting increments the vehicle's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/consignment_create_with_a_stale_expected_vehicle_version_returns_412
        """
        vehicle_id, stale_version = self._driven_car_with_a_stale_read(client, world)

        validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("AUCTION"), stale_version
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.STALE_VEHICLE_VERSION,
            412,
        )

        assert (
            total_count(client.list_consignments(make_remarketing_manager_headers()))
            == 0
        )
        after = fixtures.read_vehicle(client, vehicle_id)
        assert after["version"] == stale_version + 1
        assert after["fleet_status"] == FleetStatus.IN_SERVICE

    def test_the_412_outranks_the_state_guard_it_would_also_have_hit(
        self, client, world
    ):
        """A held-for-sale car with a stale version reports the version, not the state.

        PRD 2.9: "8. Optimistic concurrency — `ERR_STALE_PLAN_VERSION` or
        `ERR_STALE_VEHICLE_VERSION` (412)."
        PRD 3.8: "The vehicle's `fleet_status` must be `IN_SERVICE`."

        Design: Corner/cross_cutting_complexity_layers/consignment_create_with_a_stale_expected_vehicle_version_returns_412
        """
        vehicle_id, stale_version = self._driven_car_with_a_stale_read(client, world)
        fixtures.consign(client, world, vehicle_id)
        assert (
            fixtures.read_vehicle(client, vehicle_id)["fleet_status"]
            == FleetStatus.HELD_FOR_SALE
        )

        refusal = validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("AUCTION"), stale_version
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.STALE_VEHICLE_VERSION,
            412,
        )
        assert refusal["error_id"] != ApiErrorId.VEHICLE_INVALID_FLEET_STATE

    def test_a_refreshed_version_succeeds_and_freezes_the_post_usage_valuation(
        self, client, world
    ):
        """The hold baseline carries the five thousand kilometres, not the zero.

        PRD 3.8: "A successful consignment is created in `status` `DRAFT` with
        `created_by_user_id` set from the acting operator, and it freezes the reserve:
        `floor_price_cents` is the vehicle's `net_book_value_at_hold_cents` multiplied
        by 0.75, rounded half up."
        PRD 3.5: "Mileage decay is the vehicle's `odometer_km` multiplied by the
        policy's `mileage_depreciation_cents_per_km` — an exact integer product, since
        both operands are integers."

        Design: Corner/cross_cutting_complexity_layers/consignment_create_with_a_stale_expected_vehicle_version_returns_412
        """
        vehicle_id, stale_version = self._driven_car_with_a_stale_read(client, world)
        fresh_version = fixtures.read_vehicle(client, vehicle_id)["version"]
        assert fresh_version == stale_version + 1
        assert (
            fixtures.read_valuation(client, vehicle_id)["net_book_value_cents"]
            == 2740000
        )

        consignment = validate_success(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("AUCTION"), fresh_version
                ),
                make_remarketing_manager_headers(),
            ),
            expected_status=201,
        )
        assert consignment["status"] == ConsignmentStatus.DRAFT
        assert consignment["floor_price_cents"] == 2055000

        held = fixtures.read_vehicle(client, vehicle_id)
        assert held["fleet_status"] == FleetStatus.HELD_FOR_SALE
        assert held["net_book_value_at_hold_cents"] == 2740000


class TestDerivedCountersAreImmediate:
    """One promotion, then one read each of vehicle, allocation, plan and market."""

    def _car_waiting_on_its_preparation(self, client, world):
        bought = fixtures.setup_allocation_with_units(
            client, world, market_code="ATL", program_key="RSK", vin_prefix="CS"
        )
        vehicle_id = bought["vehicles"][0]["id"]
        fixtures.in_fleet(client, world, vehicle_id, "ATL")
        registration = fixtures.schedule_task(
            client,
            world,
            vehicle_id,
            factories.registration_task_payload(),
        )
        fixtures.complete_task(client, world, registration["id"])
        licensing = fixtures.schedule_task(
            client, world, vehicle_id, factories.licensing_task_payload()
        )
        fixtures.complete_task(client, world, licensing["id"])
        preparation = fixtures.schedule_task(
            client, world, vehicle_id, factories.preparation_task_payload()
        )
        return bought, vehicle_id, preparation

    def test_four_levels_of_counter_are_all_correct_on_their_first_read(
        self, client, world
    ):
        """The promotion, the allocation roll-up, the plan roll-up and the census.

        PRD 2.5: "A recomputation of a derived field counts as a mutation: when a child
        vehicle enters service and its parent allocation's `in_fleeted_count` is
        recomputed, that allocation's `updated_at` is refreshed and its `version` is
        incremented, exactly as if a client had written to it."
        PRD 3.4: "The move sets both `first_rent_ready_at` and `in_service_at` to the
        current logical clock, so the two instants are equal; increments the
        `in_service_unit_count` of the market named by the vehicle's
        `current_market_id` by 1; increments the vehicle's `version` by 1; and triggers
        the recomputation of the parent allocation's `in_fleeted_count`, which is where
        the four-hop cascade of §2.11 continues upward."
        PRD 3.3: "From `ORDERED` an allocation moves straight to `INFLEETED` when a
        child vehicle enters service and the recomputed `in_fleeted_count` equals
        `unit_count`; this is the path a single-unit allocation always takes, skipping
        `PARTIALLY_INFLEETED` entirely."
        PRD 2.12: "`in_fleeted_unit_count` is the count of vehicles belonging to any
        allocation of the plan whose `fleet_status` is one of `IN_SERVICE`,
        `IN_TRANSIT`, `HELD_FOR_SALE` or `SOLD` — units still `ON_ORDER` or
        `IN_FLEETING` have not yet been in-fleeted, and a unit in `TOTAL_LOSS` is no
        longer counted."

        Design: Corner/consistency_model/derived_counters_are_visible_in_the_same_response_cycle
        """
        bought, vehicle_id, preparation = self._car_waiting_on_its_preparation(
            client, world
        )
        assert fixtures.census(client, world.market_id("ATL")) == 0
        assert fixtures.read_vehicle(client, vehicle_id)["fleet_status"] == (
            FleetStatus.IN_FLEETING
        )

        fixtures.set_clock(client, "2026-01-15T00:00:00Z")
        completed = fixtures.complete_task(client, world, preparation["id"])
        assert completed["status"] == TaskStatus.COMPLETED
        assert_instant_equals(completed["completed_at"], "2026-01-15T00:00:00.000Z")

        vehicle = fixtures.read_vehicle(client, vehicle_id)
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE
        assert_instant_equals(vehicle["in_service_at"], "2026-01-15T00:00:00.000Z")
        assert_instant_equals(
            vehicle["first_rent_ready_at"], "2026-01-15T00:00:00.000Z"
        )

        allocation = fixtures.read_allocation(client, bought["allocation"]["id"])
        assert allocation["in_fleeted_count"] == 1
        assert allocation["created_vehicle_count"] == 1
        assert allocation["status"] == AllocationStatus.INFLEETED

        plan = fixtures.read_plan(client, bought["plan"]["id"])
        assert plan["in_fleeted_unit_count"] == 1
        assert plan["allocated_unit_count"] == 1
        assert plan["status"] == PlanStatus.LOCKED

        assert fixtures.census(client, world.market_id("ATL")) == 1

    def test_the_money_side_is_immediate_too(self, client, world):
        """The preparation cost is on the unit's basis in the same cycle.

        PRD 3.4: "Completion stamps the task's `completed_at` from the logical clock,
        posts a ledger line of `entry_type` `PREP_COST` for a positive `amount_cents`
        equal to the task's `cost_cents` with `source_entity_type` `InFleetingTask`,
        stamps the matching milestone on the vehicle — `registered_at` for
        `REGISTRATION`, `licensed_at` for `LICENSING`, `prep_completed_at` for
        `PREPARATION` — increments the task's `version` by 1, and then hands off to the
        vehicle's promotion evaluation."

        Design: Corner/consistency_model/derived_counters_are_visible_in_the_same_response_cycle
        """
        _bought, vehicle_id, preparation = self._car_waiting_on_its_preparation(
            client, world
        )
        before = entries_of_type(
            fixtures.read_ledger(client, vehicle_id), EntryType.PREP_COST
        )
        assert sorted(row["amount_cents"] for row in before) == [9000, 14000]

        fixtures.set_clock(client, "2026-01-15T00:00:00Z")
        fixtures.complete_task(client, world, preparation["id"])

        after = entries_of_type(
            fixtures.read_ledger(client, vehicle_id), EntryType.PREP_COST
        )
        assert sorted(row["amount_cents"] for row in after) == [9000, 14000, 21000]
        prep_rows = [
            row for row in after if row["source_entity_id"] == preparation["id"]
        ]
        assert len(prep_rows) == 1
        assert prep_rows[0]["amount_cents"] == 21000
        assert prep_rows[0]["source_entity_type"] == SourceEntityType.IN_FLEETING_TASK

        milestones = fixtures.read_vehicle(client, vehicle_id)
        assert_instant_equals(
            milestones["prep_completed_at"], "2026-01-15T00:00:00.000Z"
        )
        assert (
            total_count(
                client.list_ledger_entries(
                    make_fleet_controller_headers(),
                    vehicle_id=vehicle_id,
                    entry_type=EntryType.PREP_COST,
                )
            )
            == 3
        )

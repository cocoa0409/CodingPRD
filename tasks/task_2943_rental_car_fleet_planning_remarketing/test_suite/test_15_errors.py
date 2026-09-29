"""The refusal catalogue: distinct codes, precedence, and limits probed in pairs.

Nothing here settles for "some error came back". Each case names the code that
must win over the other codes the same request also violates, and the limit
cases are always probed twice — once one unit past the boundary and once exactly
on it — so the inclusive or exclusive sense of every comparison is pinned.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    ConditionStatus,
    ConsignmentStatus,
    DamageStatus,
    DamageType,
    EntryType,
    FleetStatus,
    OrderStatus,
    PlanStatus,
    PolicyStatus,
    Posture,
    RecoverySource,
    Role,
    Season,
    TaskStatus,
    TaskType,
    factories,
    fixtures,
    make_blank_role_headers,
    make_blank_user_headers,
    make_fleet_controller_headers,
    make_fleet_planner_headers,
    make_platform_admin_headers,
    make_remarketing_manager_headers,
    make_unrecognised_role_headers,
    validate_error,
    validate_success,
)
from test_helpers.test_users import FLEET_CONTROLLER_C_ID
from test_helpers.assertions import entries_of_type, list_rows, total_count


class TestPerEntityNotFoundCodes:
    """Eleven single reads, eleven different codes — never one shared 404."""

    #: One unknown identifier per entity, so no read can borrow another's row.
    UNKNOWN_IDS = tuple(
        f"00000000-0000-4000-8000-0000000000{index:02d}" for index in range(1, 12)
    )

    def test_each_single_read_names_the_entity_it_could_not_find(self, client):
        """The eleven codes are pairwise distinct and every status is 404.

        PRD 2.9: "Every path identifier resolves, left to right — the per-entity 404
        codes above."
        PRD 5: "Every error response carries the `error_id` shown below in its `data`
        object, alongside a human-readable `message`, and uses the HTTP status shown."

        Design: Corner/errors/every_single_entity_get_with_an_unknown_uuid_returns_its_own_not_found_code
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        headers = make_fleet_planner_headers()
        reads = (
            (client.get_vehicle_segment, ApiErrorId.SEGMENT_NOT_FOUND),
            (client.get_manufacturer_program, ApiErrorId.PROGRAM_NOT_FOUND),
            (client.get_remarketing_channel, ApiErrorId.CHANNEL_NOT_FOUND),
            (client.get_depreciation_policy, ApiErrorId.POLICY_NOT_FOUND),
            (client.get_fleet_plan, ApiErrorId.FLEET_PLAN_NOT_FOUND),
            (client.get_purchase_allocation, ApiErrorId.ALLOCATION_NOT_FOUND),
            (client.get_in_fleeting_task, ApiErrorId.TASK_NOT_FOUND),
            (client.get_redistribution_order, ApiErrorId.ORDER_NOT_FOUND),
            (client.get_damage_event, ApiErrorId.DAMAGE_EVENT_NOT_FOUND),
            (client.get_consignment, ApiErrorId.CONSIGNMENT_NOT_FOUND),
            (client.get_ledger_entry, ApiErrorId.LEDGER_ENTRY_NOT_FOUND),
        )

        observed = []
        for unknown_id, (read, expected) in zip(self.UNKNOWN_IDS, reads):
            error = validate_error(read(unknown_id, headers), expected, 404)
            assert isinstance(error["message"], str) and error["message"]
            assert "id" not in error
            observed.append(error["error_id"])

        assert len(set(observed)) == len(observed)
        assert observed == [expected for _read, expected in reads]


class TestAuthenticationOutranksEverything:
    """Ranks one and two answer before the server looks anything up."""

    def test_both_headers_are_required_and_an_empty_value_counts_as_absent(
        self, client
    ):
        """Neither a blank role nor a blank identifier gets to see the row.

        PRD 2.1: "If either header is absent, or is present but an empty string, the
        request is refused with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
        PRD 2.1: "Every request — reads included — must carry two headers."

        Design: Corner/errors/blank_or_unrecognised_auth_headers_return_401_unauthenticated
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        market = fixtures.create_market(client, dict(factories.ATL))

        validate_error(
            client.get_market(market["id"], make_blank_role_headers()),
            ApiErrorId.MISSING_AUTH_HEADERS,
            401,
        )
        validate_error(
            client.get_market(
                market["id"], make_blank_user_headers(role=Role.FLEET_PLANNER)
            ),
            ApiErrorId.MISSING_AUTH_HEADERS,
            401,
        )

        readable = validate_success(
            client.get_market(market["id"], make_fleet_planner_headers())
        )
        assert readable["id"] == market["id"]

    def test_an_unrecognised_role_is_answered_before_the_unknown_path_id(
        self, client
    ):
        """Rank two beats rank five even when both would fire.

        PRD 2.1: "If `X-User-Role` carries any value other than one of the five role
        names below, the request is refused with `ERR_UNKNOWN_ROLE` (also HTTP 401)."
        PRD 2.9: "The declared role is one of the five recognized names —
        `ERR_UNKNOWN_ROLE` (401)."

        Design: Corner/errors/blank_or_unrecognised_auth_headers_return_401_unauthenticated
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")

        refusal = validate_error(
            client.get_market(
                "00000000-0000-4000-8000-00000000000c",
                make_unrecognised_role_headers(),
            ),
            ApiErrorId.UNKNOWN_ROLE,
            401,
        )
        assert refusal["error_id"] != ApiErrorId.MARKET_NOT_FOUND


class TestRegistryUniquenessAndScalarBounds:
    """Two single-column keys, one composite key, and two rank-seven bounds."""

    def _reference_registry(self, client):
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            channel_payloads=[factories.CHANNEL_AUCTION],
            with_policy=False,
        )
        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")
        return world, plan

    def test_a_repeated_segment_code_and_a_repeated_channel_code_are_both_409(
        self, client
    ):
        """Different economics behind the same code buy nothing.

        PRD 3.1: "Its `code` is uppercase and globally unique, with a collision
        reported as `ERR_DUPLICATE_SEGMENT_CODE` (HTTP 409), and it carries a `name`
        alongside five policy numbers."
        PRD 3.1: "Its `code` is one of exactly four values — `AUCTION`, `RETAIL_LOT`,
        `DEALER_DIRECT` or `PROGRAM_REPURCHASE` — and is unique, so a duplicate is
        `ERR_DUPLICATE_CHANNEL_CODE` (HTTP 409)."

        Design: Corner/errors/duplicate_keys_and_out_of_range_scalars_are_rejected_on_the_registry_endpoints
        """
        self._reference_registry(client)

        validate_error(
            client.create_vehicle_segment(
                factories.vehicle_segment_payload(
                    code="MIDSIZE",
                    name="Midsize sedan rebadged",
                    baseline_daily_rate_cents=6000,
                    target_utilization_pct=0.75,
                    target_revenue_per_unit_month_cents=130000,
                    mileage_band_soft_limit_km=35000,
                    mileage_band_hard_limit_km=55000,
                    recondition_cap_cents=80000,
                ),
                make_platform_admin_headers(),
            ),
            ApiErrorId.DUPLICATE_SEGMENT_CODE,
        )
        validate_error(
            client.create_remarketing_channel(
                factories.remarketing_channel_payload(
                    name="Second auction house",
                    fee_pct=0.07,
                    fixed_fee_cents=20000,
                    expected_days_to_sell=10,
                    expected_proceeds_multiplier=0.90,
                ),
                make_platform_admin_headers(),
            ),
            ApiErrorId.DUPLICATE_CHANNEL_CODE,
        )

        assert (
            total_count(client.list_vehicle_segments(make_platform_admin_headers())) == 1
        )
        assert (
            total_count(client.list_remarketing_channels(make_platform_admin_headers()))
            == 1
        )

    def test_the_plan_key_is_the_triple_so_one_changed_column_is_enough(
        self, client
    ):
        """A second PEAK 2026 plan collides; the SHOULDER plan does not.

        PRD 3.3: "The combination of `market_id`, `season` and `plan_year` is unique
        across all plans, so a second plan for the same triple is refused with
        `ERR_DUPLICATE_FLEET_PLAN` (HTTP 409), and the named market must be `ACTIVE` at
        draft time or the request fails with `ERR_MARKET_SUSPENDED` (HTTP 422)."
        PRD 3.3: "Plans are discoverable by `market_id`, by `season`, by `plan_year`
        and by `status`."

        Design: Corner/errors/duplicate_keys_and_out_of_range_scalars_are_rejected_on_the_registry_endpoints
        """
        world, plan = self._reference_registry(client)

        validate_error(
            client.create_fleet_plan(
                factories.fleet_plan_payload(
                    world.market_id("ATL"),
                    season=Season.PEAK,
                    plan_year=2026,
                    planned_unit_count=20,
                    revenue_per_unit_target_cents=140000,
                    utilization_target_pct=0.85,
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.DUPLICATE_FLEET_PLAN,
        )

        shoulder = validate_success(
            client.create_fleet_plan(
                factories.fleet_plan_payload(
                    world.market_id("ATL"),
                    season=Season.SHOULDER,
                    plan_year=2026,
                    planned_unit_count=20,
                    revenue_per_unit_target_cents=140000,
                    utilization_target_pct=0.85,
                ),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )
        assert shoulder["season"] == Season.SHOULDER
        assert shoulder["id"] != plan["id"]
        assert (
            total_count(
                client.list_fleet_plans(
                    make_fleet_planner_headers(), market_id=world.market_id("ATL")
                )
            )
            == 2
        )

    def test_pagination_bounds_and_the_unit_count_floor_fire_at_rank_seven(
        self, client
    ):
        """A zero limit, a negative offset and a zero unit count each get their code.

        PRD 2.3: "A `limit` outside the accepted range of 1 through 200, or a negative
        `offset`, is refused with `ERR_INVALID_PAGINATION` (HTTP 422)."
        PRD 3.3: "`unit_count` must be an integer of at least 1, and a non-integer or
        smaller value is refused with `ERR_INVALID_UNIT_COUNT` (HTTP 422)."

        Design: Corner/errors/duplicate_keys_and_out_of_range_scalars_are_rejected_on_the_registry_endpoints
        """
        world, plan = self._reference_registry(client)

        validate_error(
            client.list_vehicles(make_fleet_planner_headers(), limit=0, offset=0),
            ApiErrorId.INVALID_PAGINATION,
        )
        validate_error(
            client.list_markets(make_fleet_planner_headers(), limit=10, offset=-1),
            ApiErrorId.INVALID_PAGINATION,
        )

        validate_error(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    world.program_id("PGM"),
                    world.segment_id("MIDSIZE"),
                    0,
                    plan["version"],
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.INVALID_UNIT_COUNT,
        )

        after = fixtures.read_plan(client, plan["id"])
        assert after["allocated_unit_count"] == 0
        assert after["version"] == plan["version"]


class TestInFleetingGuards:
    """A saturated allocation, a repeated task type and a replayed transition."""

    def _saturated_allocation(self, client, world):
        built = fixtures.setup_allocation_with_units(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            unit_count=2,
            vin_prefix="SAT",
        )
        assert built["allocation"]["created_vehicle_count"] == 2
        return built

    def test_a_repeated_vin_is_answered_before_the_saturated_unit_ceiling(
        self, client, world
    ):
        """Uniqueness at rank nine speaks before capacity at rank sixteen.

        PRD 3.4: "The payload carries only two things: a `vin` of exactly sixteen
        characters that is globally unique across the whole fleet — a collision is
        `ERR_DUPLICATE_VIN` (HTTP 409) — and a `current_market_id` naming the market
        that will physically hold the unit."
        PRD 3.4: "The allocation's unit count is a hard ceiling: minting a car that
        would push the count of the allocation's non-cancelled vehicles past its
        `unit_count` is refused with `ERR_ALLOCATION_UNIT_LIMIT_REACHED` (HTTP 422)."
        PRD 2.9: "Uniqueness — `ERR_DUPLICATE_MARKET_CODE`,
        `ERR_DUPLICATE_SEGMENT_CODE`, `ERR_DUPLICATE_CHANNEL_CODE`,
        `ERR_DUPLICATE_VIN`, `ERR_DUPLICATE_FLEET_PLAN` and
        `ERR_DUPLICATE_TASK_TYPE` (all 409)."

        Design: Corner/errors/vin_task_type_and_fleet_state_guards_are_rejected_around_in_fleeting
        """
        built = self._saturated_allocation(client, world)
        allocation_id = built["allocation"]["id"]
        taken_vin = built["vehicles"][0]["vin"]

        repeated = validate_error(
            client.create_vehicle(
                allocation_id,
                factories.vehicle_payload(taken_vin, world.market_id("ATL")),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.DUPLICATE_VIN,
        )
        assert repeated["error_id"] != ApiErrorId.ALLOCATION_UNIT_LIMIT_REACHED

        validate_error(
            client.create_vehicle(
                allocation_id,
                factories.vehicle_payload(
                    factories.vin("SAT3"), world.market_id("ATL")
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.ALLOCATION_UNIT_LIMIT_REACHED,
        )

        assert total_count(client.list_vehicles(make_fleet_planner_headers())) == 2
        assert fixtures.read_allocation(client, allocation_id)[
            "created_vehicle_count"
        ] == 2

    def test_the_task_type_key_and_the_fleet_state_guard_refuse_two_replays(
        self, client, world
    ):
        """A second REGISTRATION and a second delivery are both 409s.

        PRD 3.4: "A vehicle may hold at most one non-waived task per `task_type`, so
        scheduling a second `REGISTRATION` while the first is `PENDING` or `COMPLETED`
        is refused with `ERR_DUPLICATE_TASK_TYPE` (HTTP 409); a task that was `WAIVED`
        does not block a fresh one."
        PRD 3.4: "A `MarketOperator` moves the unit `ON_ORDER → IN_FLEETING`, and four
        things are checked beyond the operator's market scope: the unit's
        `fleet_status` must be `ON_ORDER`; its allocation must be in `ORDERED` or
        `PARTIALLY_INFLEETED`; the **grandparent** plan — the plan that owns the
        allocation that produced this car — must be in `LOCKED`, which is the
        cross-generation guard that makes `ERR_PLAN_NOT_LOCKED` (HTTP 409) reachable
        from a vehicle operation; and the unit's current market must be `ACTIVE`, or
        the attempt fails with `ERR_MARKET_SUSPENDED`."
        PRD 2.11: "An illegal move on the first dimension is
        `ERR_VEHICLE_INVALID_FLEET_STATE` (HTTP 409); an illegal move on the second is
        `ERR_VEHICLE_INVALID_CONDITION_STATE` (HTTP 409)."

        Design: Corner/errors/vin_task_type_and_fleet_state_guards_are_rejected_around_in_fleeting
        """
        built = self._saturated_allocation(client, world)
        vehicle_id = built["vehicles"][0]["id"]
        delivered = fixtures.in_fleet(client, world, vehicle_id, "ATL")
        assert delivered["fleet_status"] == FleetStatus.IN_FLEETING

        first = fixtures.schedule_task(
            client,
            world,
            vehicle_id,
            factories.registration_task_payload(cost_cents=14000),
            "ATL",
        )
        assert first["status"] == TaskStatus.PENDING

        validate_error(
            client.create_in_fleeting_task(
                vehicle_id,
                factories.registration_task_payload(cost_cents=15000),
                world.operator("ATL"),
            ),
            ApiErrorId.DUPLICATE_TASK_TYPE,
        )
        validate_error(
            client.in_fleet_vehicle(vehicle_id, world.operator("ATL")),
            ApiErrorId.VEHICLE_INVALID_FLEET_STATE,
        )

        assert (
            total_count(
                client.list_in_fleeting_tasks(
                    make_fleet_controller_headers(), vehicle_id=vehicle_id
                )
            )
            == 1
        )
        after = fixtures.read_vehicle(client, vehicle_id)
        assert after["fleet_status"] == FleetStatus.IN_FLEETING
        assert after["version"] == delivered["version"]

    def test_a_zero_length_preparation_window_is_refused_at_the_shape_check(
        self, client, world
    ):
        """The bound is strict, so a window of no duration is not a window.

        PRD 3.4: "The window must be well formed: `window_start` must fall strictly
        before `window_end`, or the request is refused with `ERR_INVALID_WINDOW` (HTTP
        422)."
        PRD 3.4: "Tasks are stored in status `PENDING` with a null `completed_at`, and
        are discoverable by `vehicle_id`, by `market_id`, by `task_type` and by
        `status`."

        Design: Corner/errors/vin_task_type_and_fleet_state_guards_are_rejected_around_in_fleeting
        """
        built = self._saturated_allocation(client, world)
        vehicle_id = built["vehicles"][0]["id"]
        fixtures.in_fleet(client, world, vehicle_id, "ATL")
        for payload in (
            factories.registration_task_payload(),
            factories.licensing_task_payload(),
        ):
            task = fixtures.schedule_task(client, world, vehicle_id, payload, "ATL")
            fixtures.complete_task(client, world, task["id"], "ATL")

        validate_error(
            client.create_in_fleeting_task(
                vehicle_id,
                factories.preparation_task_payload(
                    window_start="2026-01-06T08:00:00.000Z",
                    window_end="2026-01-06T08:00:00.000Z",
                ),
                world.operator("ATL"),
            ),
            ApiErrorId.INVALID_WINDOW,
        )

        assert (
            total_count(
                client.list_in_fleeting_tasks(
                    make_fleet_controller_headers(),
                    vehicle_id=vehicle_id,
                    task_type=TaskType.PREPARATION,
                )
            )
            == 0
        )
        assert fixtures.read_vehicle(client, vehicle_id)["fleet_status"] == (
            FleetStatus.IN_FLEETING
        )


class TestReferenceDataLifecycleGuards:
    """Three codes that guard reference data rather than a car."""

    def _two_segment_world(self, client):
        return fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            segment_payloads=[factories.MIDSIZE, factories.COMPACT],
            channel_payloads=[],
            with_policy=False,
        )

    def test_activating_an_active_policy_is_refused_without_touching_the_row(
        self, client
    ):
        """A third controller acts, so segregation cannot explain the refusal.

        PRD 3.2: "The policy's `status` must still be `DRAFT`; an already `ACTIVE` or
        `SUPERSEDED` policy is refused with `ERR_POLICY_NOT_DRAFT` (HTTP 409)."
        PRD 3.2: "The acting `X-User-ID` must differ from `created_by_user_id`, or the
        request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD 3.2: "On success the activating operator's `X-User-ID` is recorded as
        `activated_by_user_id`, the policy moves `DRAFT → ACTIVE`, and the policy it
        superseded — if there was one — moves `ACTIVE → SUPERSEDED`."

        Design: Corner/errors/policy_and_program_lifecycle_guards_are_rejected_after_first_use
        """
        world = self._two_segment_world(client)
        policy = fixtures.create_active_policy(
            client, world.segment_id("MIDSIZE"), name="MID-2026"
        )
        assert policy["status"] == PolicyStatus.ACTIVE

        refusal = validate_error(
            client.activate_depreciation_policy(
                policy["id"], make_fleet_controller_headers(FLEET_CONTROLLER_C_ID)
            ),
            ApiErrorId.POLICY_NOT_DRAFT,
        )
        assert refusal["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES

        stored = validate_success(
            client.get_depreciation_policy(
                policy["id"], make_fleet_controller_headers()
            )
        )
        assert stored["status"] == PolicyStatus.ACTIVE
        assert stored["activated_by_user_id"] == policy["activated_by_user_id"]
        assert stored["version"] == policy["version"]

    def test_a_closed_program_cannot_take_a_fresh_allocation(self, client):
        """The version supplied is current, so this is a state refusal not a 412.

        PRD 3.1: "From that point no new purchase allocation may name it, and an
        attempt to do so is refused with `ERR_PROGRAM_CLOSED` (HTTP 409); allocations
        and vehicles already bought under the program keep their terms untouched."
        PRD 3.1: "Closing a program moves it from `ACTIVE` to `CLOSED`, is permitted
        only from `ACTIVE`, and increments its `version`."

        Design: Corner/errors/policy_and_program_lifecycle_guards_are_rejected_after_first_use
        """
        world = self._two_segment_world(client)
        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")
        first = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("PGM"),
            world.segment_id("MIDSIZE"),
            2,
            plan["version"],
        )
        assert first["status"] == AllocationStatus.ORDERED

        closed = fixtures.close_program(client, world.program_id("PGM"))
        assert closed["version"] == 2

        current_version = fixtures.read_plan(client, plan["id"])["version"]
        refusal = validate_error(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    world.program_id("PGM"),
                    world.segment_id("MIDSIZE"),
                    1,
                    current_version,
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.PROGRAM_CLOSED,
        )
        assert refusal["error_id"] != ApiErrorId.STALE_PLAN_VERSION

        assert (
            total_count(client.list_purchase_allocations(make_fleet_planner_headers()))
            == 1
        )
        assert fixtures.read_plan(client, plan["id"])["version"] == current_version

    def test_a_segment_with_no_policy_never_borrows_another_segment_s_curve(
        self, client
    ):
        """MIDSIZE is covered, COMPACT is not, and the compact car cannot be valued.

        PRD 3.2: "When no `ACTIVE` policy exists for a segment, every operation that
        needs a valuation for a car in that segment fails with
        `ERR_NO_ACTIVE_DEPRECIATION_POLICY` (HTTP 422); those operations are the
        vehicle valuation read, the channel-recommendation read, consignment creation
        and damage reporting."
        PRD 3.2: "The invariant this machinery protects is simple and absolute: **at
        most one `ACTIVE` policy exists per segment at any instant**, and valuation
        reads only ever consult that one — `DRAFT` and `SUPERSEDED` curves are never
        read by any calculation."

        Design: Corner/errors/policy_and_program_lifecycle_guards_are_rejected_after_first_use
        """
        world = self._two_segment_world(client)
        fixtures.create_active_policy(
            client, world.segment_id("MIDSIZE"), name="MID-2026"
        )

        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")
        allocation = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("PGM"),
            world.segment_id("COMPACT"),
            1,
            plan["version"],
            capitalized_cost_per_unit_cents=2100000,
        )
        compact = fixtures.mint_vehicle(
            client, allocation["id"], factories.vin("CMP1"), world.market_id("ATL")
        )
        assert compact["segment_id"] == world.segment_id("COMPACT")

        validate_error(
            client.get_valuation(compact["id"], make_fleet_controller_headers()),
            ApiErrorId.NO_ACTIVE_DEPRECIATION_POLICY,
        )
        assert (
            total_count(
                client.list_depreciation_policies(
                    make_fleet_controller_headers(),
                    segment_id=world.segment_id("COMPACT"),
                )
            )
            == 0
        )


class TestRedistributionRouteAndStateGuards:
    """Three rungs on the same create-and-authorize pair."""

    def _repositionable_car(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="RD",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]
        assert fixtures.read_vehicle(client, vehicle_id)["fleet_status"] == (
            FleetStatus.IN_SERVICE
        )
        return vehicle_id

    def test_a_zero_length_window_and_a_same_city_haul_are_both_refused(
        self, client, world
    ):
        """The third haul differs only in destination and is stored at 201.

        PRD 3.6: "`planned_depart_at` must fall strictly before
        `planned_receive_at`, or the request is refused with
        `ERR_TRANSFER_WINDOW_INVALID` (HTTP 422)."
        PRD 3.6: "The `destination_market_id` must differ from the vehicle's
        `current_market_id`, since a transfer to the city the car is already in is
        meaningless, and the attempt is refused with `ERR_SAME_MARKET_TRANSFER` (HTTP
        422)."
        PRD 3.6: "The order's `origin_market_id` is copied from the vehicle's
        `current_market_id` at creation and never changes afterwards, even though the
        vehicle itself will be rehomed."
        PRD 3.6: "`estimated_transport_cost_cents` is the sum of the base haul, the
        surcharge and the handling flat."

        Design: Corner/errors/redistribution_window_route_and_order_state_guards_are_rejected
        """
        vehicle_id = self._repositionable_car(client, world)

        validate_error(
            client.create_redistribution_order(
                factories.redistribution_order_payload(
                    vehicle_id,
                    world.market_id("DFW"),
                    distance_km=200,
                    planned_depart_at="2026-02-01T08:00:00.000Z",
                    planned_receive_at="2026-02-01T08:00:00.000Z",
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.TRANSFER_WINDOW_INVALID,
        )
        validate_error(
            client.create_redistribution_order(
                factories.redistribution_order_payload(
                    vehicle_id,
                    world.market_id("ATL"),
                    distance_km=200,
                    planned_depart_at="2026-02-01T08:00:00.000Z",
                    planned_receive_at="2026-02-03T08:00:00.000Z",
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.SAME_MARKET_TRANSFER,
        )

        stored = validate_success(
            client.create_redistribution_order(
                factories.redistribution_order_payload(
                    vehicle_id,
                    world.market_id("DFW"),
                    distance_km=200,
                    planned_depart_at="2026-02-01T08:00:00.000Z",
                    planned_receive_at="2026-02-03T08:00:00.000Z",
                ),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )
        assert stored["status"] == OrderStatus.DRAFT
        assert stored["origin_market_id"] == world.market_id("ATL")
        assert stored["revision_count"] == 0
        assert stored["estimated_transport_cost_cents"] == 61500
        assert stored["proposed_by_user_id"] is None

        assert (
            total_count(
                client.list_redistribution_orders(
                    make_fleet_planner_headers(), vehicle_id=vehicle_id
                )
            )
            == 1
        )

    def test_authorizing_a_draft_order_is_a_state_refusal_not_a_two_man_refusal(
        self, client, world
    ):
        """No proposer has been recorded yet, so rank ten answers first.

        PRD 3.6: "A `FleetController` moves the order `PROPOSED → AUTHORIZED` provided
        the order is in `PROPOSED`, the acting operator's identifier differs from
        `proposed_by_user_id`, and the destination market's `status` is `ACTIVE`."
        PRD 2.9: "State preconditions on the target row and its ancestors —
        `ERR_PLAN_NOT_DRAFT`, `ERR_PLAN_NOT_LOCKED`,
        `ERR_ALLOCATION_NOT_CANCELLABLE`, `ERR_VEHICLE_INVALID_FLEET_STATE`,
        `ERR_VEHICLE_INVALID_CONDITION_STATE`, `ERR_TASK_ALREADY_RESOLVED`,
        `ERR_ORDER_INVALID_STATE`, `ERR_DAMAGE_EVENT_INVALID_STATE`,
        `ERR_CONSIGNMENT_INVALID_STATE`, `ERR_POLICY_NOT_DRAFT`, `ERR_PROGRAM_CLOSED`
        and `ERR_REVISION_LIMIT_REACHED` (all 409)."
        PRD 3.6: "Departure stamps `depart_at` from the logical clock, drives the
        vehicle `IN_SERVICE → IN_TRANSIT`, **decrements** the origin market's
        `in_service_unit_count` by 1, and increments both the order's and the vehicle's
        `version` by 1."

        Design: Corner/errors/redistribution_window_route_and_order_state_guards_are_rejected
        """
        vehicle_id = self._repositionable_car(client, world)
        order = fixtures.draft_order(
            client,
            vehicle_id,
            world.market_id("DFW"),
            distance_km=200,
            planned_depart_at="2026-02-01T08:00:00.000Z",
            planned_receive_at="2026-02-03T08:00:00.000Z",
        )
        assert order["status"] == OrderStatus.DRAFT

        refusal = validate_error(
            client.authorize_order(order["id"], make_fleet_controller_headers()),
            ApiErrorId.ORDER_INVALID_STATE,
        )
        assert refusal["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES

        after = fixtures.read_order(client, order["id"])
        assert after["status"] == OrderStatus.DRAFT
        assert after["authorized_by_user_id"] is None
        assert after["version"] == order["version"]

        assert fixtures.read_vehicle(client, vehicle_id)["fleet_status"] == (
            FleetStatus.IN_SERVICE
        )
        assert fixtures.census(client, world.market_id("ATL")) == 1
        assert (
            entries_of_type(
                fixtures.read_ledger(client, vehicle_id), EntryType.TRANSPORT_COST
            )
            == []
        )


class TestDamageRoutingAndConditionGuards:
    """The frozen flag routes the event irreversibly, and one open claim
    freezes the car's disposal."""

    def _two_claims(self, client, world):
        """One modest claim and one write-off-sized claim on sibling cars."""
        bought = fixtures.setup_allocation_with_units(
            client, world, market_code="ATL", program_key="RSK", unit_count=2,
            vin_prefix="DR",
        )
        small_car, big_car = (row["id"] for row in bought["vehicles"])
        for vehicle_id, prep_date in (
            (small_car, "2026-01-07"),
            (big_car, "2026-01-08"),
        ):
            fixtures.bring_to_in_service(
                client,
                world,
                vehicle_id,
                market_code="ATL",
                prep_date=prep_date,
                in_service_clock="2026-01-15T00:00:00Z",
            )

        small = fixtures.report_damage(
            client, world, small_car, 400000, damage_type=DamageType.HAIL
        )
        big = fixtures.report_damage(
            client, world, big_car, 2000000, damage_type=DamageType.COLLISION
        )
        assert small["net_book_value_at_report_cents"] == 2800000
        assert small["total_loss_required"] is False
        assert big["net_book_value_at_report_cents"] == 2800000
        assert big["total_loss_required"] is True
        return {"small_car": small_car, "big_car": big_car, "small": small, "big": big}

    def test_the_two_branches_are_mutually_exclusive_in_both_directions(
        self, client, world
    ):
        """Recovery is closed to the write-off; the write-off is closed to recovery.

        PRD 3.7: "The two branches are mutually exclusive by construction: an event
        whose `total_loss_required` is true may **not** be routed through the ordinary
        recovery path at all, and both an attempt to open recovery on it and an attempt
        to write it off are refused with `ERR_TOTAL_LOSS_DETERMINATION_REQUIRED` (HTTP
        422)."
        PRD 3.7: "Symmetrically, an attempt to declare a total loss on an event whose
        `total_loss_required` is false is refused with `ERR_TOTAL_LOSS_NOT_APPLICABLE`
        (HTTP 422)."

        Design: Corner/errors/damage_event_routing_and_condition_guards_are_rejected
        """
        built = self._two_claims(client, world)

        validate_error(
            client.open_damage_recovery(
                built["big"]["id"],
                factories.open_recovery_payload(RecoverySource.CUSTOMER),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.TOTAL_LOSS_DETERMINATION_REQUIRED,
        )
        validate_error(
            client.declare_total_loss(
                built["small"]["id"],
                factories.total_loss_payload(100000),
                make_fleet_controller_headers(),
            ),
            ApiErrorId.TOTAL_LOSS_NOT_APPLICABLE,
        )

        for event in (built["small"], built["big"]):
            stored = fixtures.read_damage_event(client, event["id"])
            assert stored["status"] == DamageStatus.REPORTED
            assert stored["version"] == event["version"]
        assert total_count(client.list_damage_events(make_fleet_controller_headers())) == 2

    def test_a_reported_event_cannot_be_settled_and_a_damaged_car_cannot_be_re_reported(
        self, client, world
    ):
        """Rank ten answers on both dimensions of the same row.

        PRD 3.7: "`TOTAL_LOSS_DECLARED` is terminal, and a request to move an event
        from a status its target transition does not declare is refused with
        `ERR_DAMAGE_EVENT_INVALID_STATE` (HTTP 409) — revising a settled event, opening
        recovery on one already in `RECOVERY_PENDING`, settling one still in
        `REPORTED`, writing off a `RECOVERED` one, or declaring a total loss on a
        `WRITTEN_OFF` one."
        PRD 2.11: "Reporting damage moves `condition_status` and leaves `fleet_status`
        untouched; dispatching a transfer moves `fleet_status` and leaves
        `condition_status` untouched."

        Design: Corner/errors/damage_event_routing_and_condition_guards_are_rejected
        """
        built = self._two_claims(client, world)
        car = built["small_car"]
        assert fixtures.read_vehicle(client, car)["condition_status"] == (
            ConditionStatus.DAMAGE_REPORTED
        )

        validate_error(
            client.settle_damage_recovery(
                built["small"]["id"],
                factories.settle_recovery_payload(100000),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.DAMAGE_EVENT_INVALID_STATE,
        )
        validate_error(
            client.create_damage_event(
                car,
                factories.damage_event_payload(50000, damage_type=DamageType.VANDALISM),
                world.operator("ATL"),
            ),
            ApiErrorId.VEHICLE_INVALID_CONDITION_STATE,
        )

        assert (
            total_count(
                client.list_damage_events(
                    make_fleet_controller_headers(), vehicle_id=car
                )
            )
            == 1
        )
        vehicle = fixtures.read_vehicle(client, car)
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE
        assert vehicle["condition_status"] == ConditionStatus.DAMAGE_REPORTED

    def test_an_open_claim_blocks_the_listing_although_the_fleet_state_is_legal(
        self, client, world
    ):
        """Rank thirteen, not rank ten: the car is squarely IN_SERVICE.

        PRD 3.8: "No damage event for the vehicle may be in `status` `REPORTED` or
        `RECOVERY_PENDING`, and an open claim is refused with
        `ERR_OPEN_DAMAGE_BLOCKS_LISTING` (HTTP 422)."
        PRD 2.9: "Open damage blocking disposal — `ERR_OPEN_DAMAGE_BLOCKS_LISTING`
        (422)."

        Design: Corner/errors/damage_event_routing_and_condition_guards_are_rejected
        """
        built = self._two_claims(client, world)
        car = built["small_car"]
        version = fixtures.read_vehicle(client, car)["version"]

        refusal = validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    car, world.channel_id("AUCTION"), version
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.OPEN_DAMAGE_BLOCKS_LISTING,
        )
        assert refusal["error_id"] != ApiErrorId.VEHICLE_INVALID_FLEET_STATE

        assert (
            total_count(client.list_consignments(make_remarketing_manager_headers())) == 0
        )
        vehicle = fixtures.read_vehicle(client, car)
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE
        assert vehicle["version"] == version
        assert fixtures.census(client, world.market_id("ATL")) == 2


class TestDisposalLimitsProbedOneCentPastTheLine:
    """Five ceilings, each read at the limit and one unit beyond it."""

    def _high_mileage_car(self, client, world):
        """A RISK car one kilometre past the segment's hard mileage band."""
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="RC",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]
        fixtures.post_usage(
            client,
            world,
            vehicle_id,
            61000,
            rented_days_delta=120,
            available_days_delta=150,
            revenue_cents_delta=660000,
        )
        fixtures.set_clock(client, "2026-07-15T00:00:00Z")
        valuation = fixtures.read_valuation(client, vehicle_id)
        assert valuation["holding_days"] == 181
        assert valuation["net_book_value_cents"] == 1816000
        return vehicle_id

    def _consigned_at_auction(self, client, world):
        vehicle_id = self._high_mileage_car(client, world)
        consignment = fixtures.consign(client, world, vehicle_id)
        assert consignment["status"] == ConsignmentStatus.DRAFT
        return vehicle_id, consignment

    def test_the_mileage_carve_out_and_the_general_ineligibility_get_their_own_codes(
        self, client, world
    ):
        """Two refusals then an acceptance, and the reserve is frozen at 0.75.

        PRD 3.8: "The named channel must be in the vehicle's eligible pool as computed
        by the filter above, with one deliberate carve-out: the `RETAIL_LOT` mileage
        exclusion is reported by its own dedicated code,
        `ERR_MILEAGE_BAND_EXCLUDES_CHANNEL` (HTTP 422), while every other exclusion — a
        `PROGRAM_REPURCHASE` request for a car on a `RISK` program, or past
        `max_holding_days`, or over `max_eligible_mileage_km`, or not in condition
        `SOUND` or `RECONDITIONED`, and any request naming a `SUSPENDED` channel of any
        code — is reported as `ERR_CHANNEL_NOT_ELIGIBLE` (HTTP 422)."
        PRD 3.8: "A successful consignment is created in `status` `DRAFT` with
        `created_by_user_id` set from the acting operator, and it freezes the reserve:
        `floor_price_cents` is the vehicle's `net_book_value_at_hold_cents` multiplied
        by 0.75, rounded half up."

        Design: Corner/errors/recondition_cap_overrun_and_floor_price_violations_are_rejected_one_cent_past_the_limit
        """
        vehicle_id = self._high_mileage_car(client, world)
        version = fixtures.read_vehicle(client, vehicle_id)["version"]

        validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("RETAIL_LOT"), version
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.MILEAGE_BAND_EXCLUDES_CHANNEL,
        )
        refusal = validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("PROGRAM_REPURCHASE"), version
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.CHANNEL_NOT_ELIGIBLE,
        )
        assert refusal["error_id"] != ApiErrorId.MIN_HOLDING_PERIOD_NOT_MET

        accepted = validate_success(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("AUCTION"), version
                ),
                make_remarketing_manager_headers(),
            ),
            expected_status=201,
        )
        assert accepted["status"] == ConsignmentStatus.DRAFT
        assert accepted["floor_price_cents"] == 1362000
        assert fixtures.read_vehicle(client, vehicle_id)[
            "net_book_value_at_hold_cents"
        ] == 1816000
        assert (
            total_count(client.list_consignments(make_remarketing_manager_headers())) == 1
        )

    def test_the_recondition_budget_and_its_actual_are_both_inclusive_ceilings(
        self, client, world
    ):
        """One cent over the cap and one cent over the budget are both refused.

        PRD 3.8: "A `RemarketingManager` authorizes a budget, moving the consignment
        `DRAFT → RECONDITION_PENDING` with a `recondition_authorized_cents` that may
        not exceed the vehicle segment's `recondition_cap_cents`; a breach is refused
        with `ERR_RECONDITION_CAP_EXCEEDED` (HTTP 422)."
        PRD 3.8: "The actual spend is then booked: the manager submits a
        `recondition_actual_cents` that may not exceed the previously authorized
        `recondition_authorized_cents`, and an overrun is refused with
        `ERR_RECONDITION_OVERRUN` (HTTP 422)."
        PRD 3.8: "Booking the spend computes `recondition_loaded_cents` as
        `recondition_actual_cents` multiplied by 1.075, rounded half up — a 7.5 percent
        overhead loading for shop administration — posts a ledger line of `entry_type`
        `RECONDITION_COST` for a positive `amount_cents` equal to
        `recondition_loaded_cents` with `source_entity_type` `Consignment`, recomputes
        the vehicle's `total_recondition_cents`, drives the vehicle's condition
        `RECONDITIONING → RECONDITIONED`, and increments both versions by 1."

        Design: Corner/errors/recondition_cap_overrun_and_floor_price_violations_are_rejected_one_cent_past_the_limit
        """
        vehicle_id, consignment = self._consigned_at_auction(client, world)

        validate_error(
            client.authorize_recondition(
                consignment["id"],
                factories.authorize_recondition_payload(90001),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.RECONDITION_CAP_EXCEEDED,
        )
        authorized = validate_success(
            client.authorize_recondition(
                consignment["id"],
                factories.authorize_recondition_payload(90000),
                make_remarketing_manager_headers(),
            )
        )
        assert authorized["status"] == ConsignmentStatus.RECONDITION_PENDING
        assert authorized["recondition_authorized_cents"] == 90000

        validate_error(
            client.complete_recondition(
                consignment["id"],
                factories.complete_recondition_payload(90001),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.RECONDITION_OVERRUN,
        )
        booked = validate_success(
            client.complete_recondition(
                consignment["id"],
                factories.complete_recondition_payload(90000),
                make_remarketing_manager_headers(),
            )
        )
        assert booked["status"] == ConsignmentStatus.RECONDITION_PENDING
        assert booked["recondition_loaded_cents"] == 96750

        rows = entries_of_type(
            fixtures.read_ledger(client, vehicle_id), EntryType.RECONDITION_COST
        )
        assert [row["amount_cents"] for row in rows] == [96750]
        vehicle = fixtures.read_vehicle(client, vehicle_id)
        assert vehicle["condition_status"] == ConditionStatus.RECONDITIONED
        assert vehicle["total_recondition_cents"] == 96750

    def test_the_reserve_binds_one_cent_below_and_admits_the_exact_floor(
        self, client, world
    ):
        """The accepted sale's three cost lines are each rounded on their own.

        PRD 3.8: "The reserve binds: a `gross_proceeds_cents` below the frozen
        `floor_price_cents` is refused with `ERR_PROCEEDS_BELOW_FLOOR` (HTTP 422), and a
        figure exactly equal to the floor is accepted."
        PRD 3.8: "Line one, `channel_fee_cents`, is `gross_proceeds_cents` multiplied
        by the channel's `fee_pct`, rounded half up, plus the channel's
        `fixed_fee_cents`."
        PRD 3.8: "Line two, `transport_to_channel_cents`, is the **vehicle's current
        market's** `transport_hub_distance_km` multiplied by that market's
        `transfer_cost_per_km_cents` multiplied by 1.15, rounded half up; the market is
        read at sale time, so a redistribution completed before the car was held for
        sale genuinely changes this line."
        PRD 3.8: "`net_proceeds_cents` is `gross_proceeds_cents` minus the sum of those
        three rounded lines, and `gain_loss_cents` is `net_proceeds_cents` minus the
        vehicle's frozen `net_book_value_at_hold_cents`."

        Design: Corner/errors/recondition_cap_overrun_and_floor_price_violations_are_rejected_one_cent_past_the_limit
        """
        _vehicle_id, consignment = self._consigned_at_auction(client, world)
        fixtures.authorize_recondition(client, consignment["id"], 90000)
        fixtures.complete_recondition(client, consignment["id"], 90000)
        listed = fixtures.publish_consignment(client, consignment["id"])
        assert listed["status"] == ConsignmentStatus.LISTED

        validate_error(
            client.record_sale(
                consignment["id"],
                factories.record_sale_payload(1361999),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.PROCEEDS_BELOW_FLOOR,
        )
        assert fixtures.read_consignment(client, consignment["id"])["status"] == (
            ConsignmentStatus.LISTED
        )

        sold = validate_success(
            client.record_sale(
                consignment["id"],
                factories.record_sale_payload(1362000),
                make_remarketing_manager_headers(),
            )
        )
        assert sold["status"] == ConsignmentStatus.SOLD_PENDING_SETTLEMENT
        assert sold["channel_fee_cents"] == 106720
        assert sold["transport_to_channel_cents"] == 6613
        assert sold["net_proceeds_cents"] == 1151917
        assert sold["gain_loss_cents"] == -664083


class TestRestrictedPostureAdmitsTheExactFill:
    """RESTRICTED is a ceiling, not a stop: it still takes the last unit."""

    def test_the_overshoot_is_refused_and_the_exact_fill_is_taken_at_the_same_version(
        self, client
    ):
        """A refused allocation bumps nothing, so the stale-looking version still works.

        PRD 3.3: "When it is 9000 or above but still below 10000 — from ninety percent
        up to, but not reaching, full allocation — `posture` is `RESTRICTED`."
        PRD 3.3: "And the plan's posture gates the write: while the posture is
        `RESTRICTED`, an allocation is accepted only if adding its `unit_count` leaves
        `allocated_unit_count` at or below `planned_unit_count`, and an allocation that
        would overshoot is refused with `ERR_PLAN_POSTURE_RESTRICTED` (HTTP 422); while
        the posture is `FROZEN`, no allocation is accepted at any size whatsoever, and
        the refusal is `ERR_PLAN_POSTURE_FROZEN` (HTTP 422)."
        PRD 3.3: "When it is 10000 or above — the plan is allocated to its planned size
        or beyond — `posture` is `FROZEN`."

        Design: Corner/errors/plan_posture_restricted_admits_an_exact_fill_and_refuses_an_overshoot
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            channel_payloads=[],
            with_policy=False,
        )
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("RSK"),
            world.segment_id("MIDSIZE"),
            9,
            plan["version"],
        )

        at_ninety = fixtures.read_plan(client, plan["id"])
        assert at_ninety["allocated_unit_count"] == 9
        assert at_ninety["posture"] == Posture.RESTRICTED
        assert at_ninety["status"] == PlanStatus.LOCKED
        held_version = at_ninety["version"]

        validate_error(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    world.program_id("RSK"),
                    world.segment_id("MIDSIZE"),
                    2,
                    held_version,
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.PLAN_POSTURE_RESTRICTED,
        )
        unchanged = fixtures.read_plan(client, plan["id"])
        assert unchanged["allocated_unit_count"] == 9
        assert unchanged["version"] == held_version

        accepted = validate_success(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    world.program_id("RSK"),
                    world.segment_id("MIDSIZE"),
                    1,
                    held_version,
                ),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )
        assert accepted["unit_count"] == 1
        assert accepted["status"] == AllocationStatus.ORDERED

        filled = fixtures.read_plan(client, plan["id"])
        assert filled["allocated_unit_count"] == 10
        assert filled["posture"] == Posture.FROZEN


class TestTransportPaybackCeiling:
    """Forty-five days of rental income is the whole budget for a haul."""

    def _car_in_atlanta(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="PB",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        return built["vehicle"]["id"]

    def test_one_kilometre_too_far_is_refused_and_the_kilometre_below_is_stored(
        self, client, world
    ):
        """The ceiling is 247500 and the two hauls straddle it by 188 cents.

        PRD 3.6: "The ceiling is the vehicle segment's `baseline_daily_rate_cents`
        multiplied by forty-five days, rounded half up: a transfer must be recoverable
        inside about a season of rental income."
        PRD 3.6: "If `estimated_transport_cost_cents` strictly exceeds that ceiling the
        order is refused with `ERR_TRANSPORT_COST_EXCEEDS_BENEFIT` (HTTP 422), and a
        cost exactly equal to the ceiling is accepted."
        PRD 3.6: "The base haul is the order's `distance_km` multiplied by the
        **origin** market's `transfer_cost_per_km_cents`; the destination market's rate
        is never read, so hauling from a cheap city to an expensive one costs the cheap
        city's rate."
        PRD 3.6: "at one hundred fifty thousand cents or above it is 0.05"

        Design: Corner/errors/transport_payback_ceiling_refuses_a_haul_one_kilometre_too_long
        """
        vehicle_id = self._car_in_atlanta(client, world)

        validate_error(
            client.create_redistribution_order(
                factories.redistribution_order_payload(
                    vehicle_id,
                    world.market_id("DFW"),
                    distance_km=915,
                    planned_depart_at="2026-02-01T00:00:00.000Z",
                    planned_receive_at="2026-02-03T00:00:00.000Z",
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.TRANSPORT_COST_EXCEEDS_BENEFIT,
        )

        stored = validate_success(
            client.create_redistribution_order(
                factories.redistribution_order_payload(
                    vehicle_id,
                    world.market_id("DFW"),
                    distance_km=914,
                    planned_depart_at="2026-02-01T00:00:00.000Z",
                    planned_receive_at="2026-02-03T00:00:00.000Z",
                ),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )
        assert stored["distance_km"] == 914
        assert stored["estimated_transport_cost_cents"] == 247425
        assert stored["status"] == OrderStatus.DRAFT

        rows = list_rows(
            client.list_redistribution_orders(
                make_fleet_planner_headers(), vehicle_id=vehicle_id
            )
        )
        assert [row["id"] for row in rows] == [stored["id"]]

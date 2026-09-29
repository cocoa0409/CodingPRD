"""Who may act: five exclusive write surfaces, one shared read surface, and the
two controls that are about identity rather than role.

The denials here are all checked against a request that would otherwise have
succeeded, so a 403 can never be mistaken for a state or body failure that
happened to fire first.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    ConditionStatus,
    DamageStatus,
    DamageType,
    FleetStatus,
    PlanStatus,
    PolicyStatus,
    RecoverySource,
    Region,
    factories,
    fixtures,
    make_fleet_controller_headers,
    make_fleet_planner_headers,
    make_market_operator_headers,
    make_platform_admin_headers,
    make_remarketing_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    FLEET_CONTROLLER_A_ID,
    FLEET_CONTROLLER_B_ID,
)
from test_helpers.assertions import total_count


class TestExclusiveWriteSurfaces:
    """One chain in which each of the five roles acts only on its own surface."""

    def test_all_five_roles_reach_their_own_operations_without_borrowing_another(
        self, client
    ):
        """A segment, an allocation, a claim, a recovery and a write-off in turn.

        PRD 2.1: "`PlatformAdmin` — owns the reference configuration of the platform:
        markets, vehicle segments, manufacturer programs, remarketing channels and the
        logical clock."
        PRD 2.1: "`FleetPlanner` — sizes the fleet. Drafts plans, allocates purchases
        across program and risk vehicles, mints vehicles against allocations, and
        proposes inter-city redistributions."
        PRD 2.1: "`MarketOperator` — the branch on the ground. In-fleets vehicles,
        schedules and completes registration, licensing and preparation work, posts
        rental usage, reports and revises damage, and dispatches and receives
        transfers."
        PRD 2.1: "`RemarketingManager` — runs disposal. Consigns vehicles to channels,
        authorizes and books reconditioning, lists, records sales, settles and
        withdraws, and works damage-recovery claims."
        PRD 2.1: "`FleetController` — the control function. Locks plans, owns
        depreciation policy, authorizes and rejects redistributions, waives in-fleeting
        tasks, and adjudicates damage write-offs and total losses."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            channel_payloads=[],
            with_policy=True,
        )
        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")
        first = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("RSK"),
            world.segment_id("MIDSIZE"),
            1,
            plan["version"],
        )
        vehicle = fixtures.mint_vehicle(
            client, first["id"], factories.vin("RB1"), world.market_id("ATL")
        )
        assert vehicle["fleet_status"] == FleetStatus.ON_ORDER
        assert vehicle["in_service_at"] is None

        compact = validate_success(
            client.create_vehicle_segment(
                factories.vehicle_segment_payload(**factories.COMPACT),
                make_platform_admin_headers(),
            ),
            expected_status=201,
        )
        assert compact["code"] == "COMPACT"

        second = validate_success(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    world.program_id("RSK"),
                    compact["id"],
                    1,
                    fixtures.read_plan(client, plan["id"])["version"],
                    capitalized_cost_per_unit_cents=2100000,
                ),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )
        cancelled = validate_success(
            client.cancel_purchase_allocation(
                second["id"], make_fleet_planner_headers()
            )
        )
        assert cancelled["status"] == AllocationStatus.CANCELLED

        claim = validate_success(
            client.create_damage_event(
                vehicle["id"],
                factories.damage_event_payload(
                    400000, damage_type=DamageType.VANDALISM
                ),
                make_market_operator_headers(world.market_id("ATL")),
            ),
            expected_status=201,
        )
        assert claim["net_book_value_at_report_cents"] == 2800000
        assert claim["total_loss_required"] is False

        opened = validate_success(
            client.open_damage_recovery(
                claim["id"],
                factories.open_recovery_payload(RecoverySource.THIRD_PARTY_INSURER),
                make_remarketing_manager_headers(),
            )
        )
        assert opened["status"] == DamageStatus.RECOVERY_PENDING
        assert opened["recovery_source"] == RecoverySource.THIRD_PARTY_INSURER

        written_off = validate_success(
            client.write_off_damage_event(
                claim["id"], make_fleet_controller_headers()
            )
        )
        assert written_off["status"] == DamageStatus.WRITTEN_OFF
        assert written_off["recovered_cents"] == 0
        assert fixtures.read_vehicle(client, vehicle["id"])["condition_status"] == (
            ConditionStatus.SOUND
        )


class TestSharedReadSurface:
    """A read is a read: no role-filtered projection anywhere."""

    def test_the_same_market_reads_identically_for_every_one_of_the_five_roles(
        self, client
    ):
        """Even the Atlanta branch sees Dallas, and sees both cities in the list.

        PRD 2.1: "All five roles may perform every read operation in this API, with two
        exceptions: the plan-performance computed read and the vehicle
        channel-recommendation computed read are closed to `MarketOperator` and
        available to the other four roles."
        PRD 2.1: "The comparison field depends on the operation, and there are eight
        operations under this scope: in-fleeting a vehicle, posting usage on a vehicle,
        scheduling an in-fleeting task for a vehicle and reporting damage on a vehicle
        all compare against that vehicle's `current_market_id`; completing an
        in-fleeting task compares against the task's `market_id`; revising a damage
        estimate compares against the damage event's `market_id`; dispatching a
        redistribution order compares against the order's `origin_market_id`; and
        receiving a redistribution order compares against the order's
        `destination_market_id`, because the receiving branch is the one that signs for
        the haul."
        PRD 3.1: "Markets are discoverable by `region`, by `status` and by `code`."

        Design: Corner/rbac/every_role_shares_read_access_to_the_market_registry
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        atlanta = fixtures.create_market(client, dict(factories.ATL))
        dallas = fixtures.create_market(client, dict(factories.DFW))

        readers = (
            make_platform_admin_headers(),
            make_fleet_planner_headers(),
            make_fleet_controller_headers(),
            make_remarketing_manager_headers(),
            make_market_operator_headers(atlanta["id"]),
        )
        bodies = [
            validate_success(client.get_market(dallas["id"], headers))
            for headers in readers
        ]

        assert len(bodies) == 5
        for body in bodies:
            assert body == bodies[0]
        assert bodies[0]["id"] == dallas["id"]
        assert bodies[0]["code"] == "DFW"
        assert bodies[0]["in_service_unit_count"] == 0
        assert bodies[0]["version"] == 1

        assert (
            total_count(client.list_markets(make_market_operator_headers(atlanta["id"])))
            == 2
        )


class TestDeniedWriteSurfaces:
    """Rank three answers before any state, body or capacity check.

    Each denied request is one that the very same world would have accepted from
    the role the operation actually belongs to, so the 403 cannot be a
    coincidence of ordering."""

    def _world_with_one_on_order_car(self, client):
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            channel_payloads=[],
            with_policy=True,
        )
        drafted = fixtures.draft_plan(client, world.market_id("ATL"))
        locked = fixtures.lock_plan(client, drafted["id"])
        allocation = fixtures.add_allocation(
            client,
            locked["id"],
            world.program_id("RSK"),
            world.segment_id("MIDSIZE"),
            2,
            locked["version"],
        )
        vehicle = fixtures.mint_vehicle(
            client, allocation["id"], factories.vin("DN1"), world.market_id("ATL")
        )
        return world, allocation, vehicle

    def test_a_lockable_plan_still_refuses_the_branch_operator(self, client):
        """The plan is squarely DRAFT, so only the role can be the objection.

        PRD 2.1: "A recognized role that is not on the target operation's authorized
        list yields `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.9: "The declared role appears on the target operation's authorized list —
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations_returns_403_forbidden
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            channel_payloads=[],
            with_policy=False,
        )
        drafted = fixtures.draft_plan(client, world.market_id("ATL"))
        assert drafted["status"] == PlanStatus.DRAFT

        refusal = validate_error(
            client.lock_fleet_plan(
                drafted["id"], make_market_operator_headers(world.market_id("ATL"))
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        assert refusal["error_id"] != ApiErrorId.PLAN_NOT_DRAFT

        after = fixtures.read_plan(client, drafted["id"])
        assert after["status"] == PlanStatus.DRAFT
        assert after["version"] == drafted["version"]

        locked = validate_success(
            client.lock_fleet_plan(drafted["id"], make_fleet_controller_headers())
        )
        assert locked["status"] == PlanStatus.LOCKED

    def test_three_more_roles_are_turned_away_from_surfaces_that_would_have_worked(
        self, client
    ):
        """A planner's market, a manager's in-fleet and a controller's mint.

        PRD 2.1: "A recognized role that is not on the target operation's authorized
        list yields `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 3.4: "A `MarketOperator` moves the unit `ON_ORDER → IN_FLEETING`, and four
        things are checked beyond the operator's market scope: the unit's
        `fleet_status` must be `ON_ORDER`; its allocation must be in `ORDERED` or
        `PARTIALLY_INFLEETED`; the **grandparent** plan — the plan that owns the
        allocation that produced this car — must be in `LOCKED`, which is the
        cross-generation guard that makes `ERR_PLAN_NOT_LOCKED` (HTTP 409) reachable
        from a vehicle operation; and the unit's current market must be `ACTIVE`, or
        the attempt fails with `ERR_MARKET_SUSPENDED`."
        PRD 3.4: "Minting a physical car against an allocation is a `FleetPlanner`
        action."

        Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations_returns_403_forbidden
        """
        world, allocation, vehicle = self._world_with_one_on_order_car(client)

        validate_error(
            client.create_market(
                factories.market_payload(
                    code="PHX",
                    name="Phoenix",
                    region=Region.WEST,
                    transport_hub_distance_km=40,
                    transfer_cost_per_km_cents=280,
                    storage_cost_per_day_cents=500,
                    prep_capacity_per_day=3,
                    registration_lead_days=4,
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            client.in_fleet_vehicle(vehicle["id"], make_remarketing_manager_headers()),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        mint_refusal = validate_error(
            client.create_vehicle(
                allocation["id"],
                factories.vehicle_payload(
                    factories.vin("DN2"), world.market_id("ATL")
                ),
                make_fleet_controller_headers(),
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        assert mint_refusal["error_id"] != ApiErrorId.ALLOCATION_UNIT_LIMIT_REACHED

        assert total_count(client.list_markets(make_platform_admin_headers())) == 1
        rows = total_count(client.list_vehicles(make_fleet_planner_headers()))
        assert rows == 1
        assert fixtures.read_vehicle(client, vehicle["id"])["fleet_status"] == (
            FleetStatus.ON_ORDER
        )

    def test_the_channel_recommendation_read_is_closed_to_the_branch_operator(
        self, client
    ):
        """The exception to shared reads is per endpoint, not per HTTP verb.

        PRD 2.1: "All five roles may perform every read operation in this API, with two
        exceptions: the plan-performance computed read and the vehicle
        channel-recommendation computed read are closed to `MarketOperator` and
        available to the other four roles."
        PRD 2.9: "The declared role appears on the target operation's authorized list —
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations_returns_403_forbidden
        """
        world, _allocation, vehicle = self._world_with_one_on_order_car(client)

        validate_error(
            client.get_channel_recommendation(
                vehicle["id"], make_market_operator_headers(world.market_id("ATL"))
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        readable = validate_success(
            client.get_vehicle(
                vehicle["id"], make_market_operator_headers(world.market_id("ATL"))
            )
        )
        assert readable["id"] == vehicle["id"]


class TestSegregationOfDutiesIsAboutIdentity:
    """Both halves of the two-man control are the same role."""

    def test_the_drafter_cannot_activate_but_a_peer_controller_can(self, client):
        """The refusal leaves the draft untouched and unstamped.

        PRD 3.2: "The acting `X-User-ID` must differ from `created_by_user_id`, or the
        request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD 3.2: "On success the activating operator's `X-User-ID` is recorded as
        `activated_by_user_id`, the policy moves `DRAFT → ACTIVE`, and the policy it
        superseded — if there was one — moves `ACTIVE → SUPERSEDED`."
        PRD 2.1: "It is, however, recorded where a transition demands an audit subject:
        as `proposed_by_user_id` and `authorized_by_user_id` on a redistribution order,
        as `created_by_user_id` and `settled_by_user_id` on a consignment, and as
        `created_by_user_id` and `activated_by_user_id` on a depreciation policy."

        Design: Corner/rbac/policy_activation_by_the_drafting_user_returns_403_segregation_of_duties
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        segment = fixtures.create_segment(client, dict(factories.MIDSIZE))
        draft = validate_success(
            client.create_depreciation_policy(
                factories.depreciation_policy_payload(segment["id"], name="MID-2026"),
                make_fleet_controller_headers(FLEET_CONTROLLER_A_ID),
            ),
            expected_status=201,
        )
        assert draft["status"] == PolicyStatus.DRAFT
        assert draft["created_by_user_id"] == FLEET_CONTROLLER_A_ID
        assert draft["activated_by_user_id"] is None

        validate_error(
            client.activate_depreciation_policy(
                draft["id"], make_fleet_controller_headers(FLEET_CONTROLLER_A_ID)
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )
        still_draft = validate_success(
            client.get_depreciation_policy(draft["id"], make_fleet_controller_headers())
        )
        assert still_draft["status"] == PolicyStatus.DRAFT
        assert still_draft["activated_by_user_id"] is None
        assert still_draft["version"] == 1

        activated = validate_success(
            client.activate_depreciation_policy(
                draft["id"], make_fleet_controller_headers(FLEET_CONTROLLER_B_ID)
            )
        )
        assert activated["status"] == PolicyStatus.ACTIVE
        assert activated["activated_by_user_id"] == FLEET_CONTROLLER_B_ID
        assert activated["created_by_user_id"] == FLEET_CONTROLLER_A_ID


class TestOperatorsAreMarketBackedPeers:
    """Two operators differ only by the market their identifier names."""

    def test_the_wrong_city_gets_403_and_the_right_city_gets_the_transition(
        self, client
    ):
        """The car exists, so this is a scope refusal rather than a 404.

        PRD 2.1: "`MarketOperator` is different: its identity is **entity-backed by a
        Market**."
        PRD 2.1: "When `X-User-Role` is `MarketOperator`, `X-User-ID` is the `id` of the
        acting `Market` row, and ownership checks compare the target resource's market
        foreign key to `X-User-ID` directly."
        PRD 2.1: "A mismatch is `ERR_MARKET_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/an_operator_cannot_in_fleet_another_markets_vehicle_returns_403_forbidden
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL, factories.DFW],
            channel_payloads=[],
            with_policy=False,
        )
        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")
        allocation = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("RSK"),
            world.segment_id("MIDSIZE"),
            1,
            plan["version"],
        )
        vehicle = fixtures.mint_vehicle(
            client, allocation["id"], factories.vin("SC1"), world.market_id("ATL")
        )
        assert vehicle["current_market_id"] == world.market_id("ATL")

        refusal = validate_error(
            client.in_fleet_vehicle(vehicle["id"], world.operator("DFW")),
            ApiErrorId.MARKET_SCOPE_VIOLATION,
            403,
        )
        assert refusal["error_id"] != ApiErrorId.VEHICLE_NOT_FOUND
        assert fixtures.read_vehicle(client, vehicle["id"])["fleet_status"] == (
            FleetStatus.ON_ORDER
        )

        delivered = validate_success(
            client.in_fleet_vehicle(vehicle["id"], world.operator("ATL"))
        )
        assert delivered["fleet_status"] == FleetStatus.IN_FLEETING
        assert delivered["version"] == vehicle["version"] + 1

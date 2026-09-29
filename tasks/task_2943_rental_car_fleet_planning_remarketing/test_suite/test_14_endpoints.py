"""Endpoint contracts: the status codes, the echoed bodies and the filters.

A create answers 201 and a read of the same row answers 200 with the same body;
an action endpoint answers 200 with the affected row; a refused write answers
its own code and leaves the collection it would have joined empty.
"""

from test_helpers import (
    ApiErrorId,
    MarketStatus,
    PlanStatus,
    Season,
    UNKNOWN_UUID,
    factories,
    fixtures,
    is_valid_uuid,
    make_fleet_planner_headers,
    make_platform_admin_headers,
    make_remarketing_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import list_rows, total_count


class TestVehicleSegmentRoundTrip:
    """Create, read, list — the three shapes must agree with each other."""

    INPUT_FIELDS = (
        "code",
        "name",
        "baseline_daily_rate_cents",
        "target_utilization_pct",
        "target_revenue_per_unit_month_cents",
        "mileage_band_soft_limit_km",
        "mileage_band_hard_limit_km",
        "recondition_cap_cents",
    )

    def test_the_created_row_the_read_row_and_the_listed_row_are_one_row(
        self, client
    ):
        """Every declared input comes back, and the fraction stays a number.

        PRD 4: "Creation endpoints return HTTP 201 with the created resource in
        `data`; every other successful operation returns HTTP 200 with the affected
        resource, or with the computed result object for the four read-only
        computations."
        PRD 3.1: "`target_utilization_pct` is the segment's utilization target
        expressed as a fraction of one carried to four decimal places, greater than
        zero and at most 1."
        PRD 3.1: "Segments are discoverable by `code`."
        PRD 2.5: "`version` is an integer that starts at 1 when the row is created and
        increases by exactly 1 on each subsequent mutation."

        Design: Corner/endpoints/vehicle_segment_create_read_list_round_trip_with_no_write_surface
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        created = validate_success(
            client.create_vehicle_segment(
                factories.vehicle_segment_payload(), make_platform_admin_headers()
            ),
            expected_status=201,
        )
        assert is_valid_uuid(created["id"])
        assert created["version"] == 1
        for field in self.INPUT_FIELDS:
            assert created[field] == factories.MIDSIZE[field], field
        assert isinstance(created["target_utilization_pct"], float)

        read_back = validate_success(
            client.get_vehicle_segment(created["id"], make_remarketing_manager_headers())
        )
        assert read_back == created

        rows = list_rows(
            client.list_vehicle_segments(
                make_remarketing_manager_headers(), code="MIDSIZE", limit=10, offset=0
            )
        )
        assert [row["id"] for row in rows] == [created["id"]]
        assert (
            total_count(
                client.list_vehicle_segments(
                    make_remarketing_manager_headers(), code="MIDSIZE"
                )
            )
            == 1
        )


class TestMarketSuspendAction:
    """The action endpoint returns the affected market and touches nothing else."""

    def test_suspension_answers_two_hundred_and_reshapes_the_status_filter(
        self, client
    ):
        """The market leaves the ACTIVE listing and its child plan does not move.

        PRD 3.1: "Suspension moves `status` from `ACTIVE` to `SUSPENDED`, is permitted
        only while the market is `ACTIVE`, and increments the market's `version`."
        PRD 3.1: "Markets are discoverable by `region`, by `status` and by `code`."
        PRD 4: "Endpoints that only advance a state machine take no request body
        beyond what §3 specifies."

        Design: Corner/endpoints/market_suspend_is_a_one_way_action_endpoint
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        market = fixtures.create_market(client, dict(factories.ATL))
        plan = fixtures.draft_plan(client, market["id"], season=Season.PEAK)

        suspended = validate_success(
            client.suspend_market(market["id"], make_platform_admin_headers())
        )
        assert suspended["id"] == market["id"]
        assert suspended["status"] == MarketStatus.SUSPENDED
        assert suspended["version"] == 2

        assert (
            total_count(
                client.list_markets(
                    make_platform_admin_headers(), status=MarketStatus.SUSPENDED
                )
            )
            == 1
        )
        assert (
            total_count(
                client.list_markets(
                    make_platform_admin_headers(), status=MarketStatus.ACTIVE
                )
            )
            == 0
        )

        child = fixtures.read_plan(client, plan["id"])
        assert child["status"] == PlanStatus.DRAFT
        assert child["version"] == 1


class TestAllocationBodyForeignKeys:
    """Two unknown body ids and the first one declared is the one reported."""

    def test_the_program_id_is_resolved_before_the_segment_id(self, client):
        """A plan with no programs and no segments still blames the program.

        PRD 2.9: "Foreign keys carried in a request **body** are resolved after the
        path, in the order the operation's input list declares them, and they use the
        same per-entity 404 codes."
        PRD 3.3: "The payload names a `program_id`, a `segment_id`, a `unit_count`, a
        `capitalized_cost_per_unit_cents` greater than zero, and the
        optimistic-concurrency field `expected_plan_version` described in §2.7."
        PRD 2.9: "Every body foreign key resolves, in declared field order — the same
        per-entity 404 codes."

        Design: Corner/endpoints/allocation_create_with_an_unknown_program_returns_404_not_found
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            segment_payloads=[],
            channel_payloads=[],
            with_programs=False,
            with_policy=False,
        )
        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")

        refusal = validate_error(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    UNKNOWN_UUID, UNKNOWN_UUID, 4, plan["version"]
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.PROGRAM_NOT_FOUND,
        )
        assert refusal["error_id"] != ApiErrorId.SEGMENT_NOT_FOUND

        assert (
            total_count(client.list_purchase_allocations(make_fleet_planner_headers()))
            == 0
        )
        after = fixtures.read_plan(client, plan["id"])
        assert after["allocated_unit_count"] == 0
        assert after["version"] == plan["version"]


class TestUsagePostingOdometerGate:
    """The comparison is not-lower rather than strictly-higher."""

    def _car_at_twelve_hundred_km(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client, world, market_code="ATL", program_key="PGM", vin_prefix="OD"
        )
        vehicle_id = built["vehicle"]["id"]
        first = fixtures.post_usage(
            client,
            world,
            vehicle_id,
            1200,
            rented_days_delta=3,
            available_days_delta=4,
            revenue_cents_delta=16500,
        )
        assert first["odometer_km"] == 1200
        return vehicle_id, first

    def test_one_kilometre_less_is_refused_and_adds_none_of_its_increments(
        self, client, world
    ):
        """The three deltas travel with the odometer and are rejected with it.

        PRD 3.5: "Because the odometer is cumulative it can only move forward: a
        submitted `odometer_km` lower than the stored `odometer_km` is refused with
        `ERR_ODOMETER_REGRESSION` (HTTP 422), and an equal reading — a day with no
        driving — is accepted."
        PRD 3.5: "`odometer_km` is the **cumulative** dashboard reading and
        **replaces** the stored value outright, while `rented_days_delta`,
        `available_days_delta` and `revenue_cents_delta` are **increments** that are
        added to the stored `rented_days_total`, `available_days_total` and
        `revenue_to_date_cents` respectively."

        Design: Corner/endpoints/usage_posting_with_a_lower_odometer_is_rejected_but_an_equal_one_passes
        """
        vehicle_id, first = self._car_at_twelve_hundred_km(client, world)

        validate_error(
            client.post_usage(
                vehicle_id,
                factories.usage_payload(
                    1199,
                    rented_days_delta=1,
                    available_days_delta=1,
                    revenue_cents_delta=5500,
                ),
                world.operator("ATL"),
            ),
            ApiErrorId.ODOMETER_REGRESSION,
        )

        after = fixtures.read_vehicle(client, vehicle_id)
        assert after["odometer_km"] == 1200
        assert after["rented_days_total"] == 3
        assert after["available_days_total"] == 4
        assert after["revenue_to_date_cents"] == 16500
        assert after["version"] == first["version"]

    def test_an_equal_reading_is_a_legal_no_movement_day(self, client, world):
        """A day with no driving still books its rental days and its revenue.

        PRD 3.5: "The posting increments the vehicle's `version` by 1."
        PRD 3.5: "An in-service unit earns, accumulates kilometres, and loses value;
        the branch reports the first two and the system computes the third."

        Design: Corner/endpoints/usage_posting_with_a_lower_odometer_is_rejected_but_an_equal_one_passes
        """
        vehicle_id, first = self._car_at_twelve_hundred_km(client, world)

        second = validate_success(
            client.post_usage(
                vehicle_id,
                factories.usage_payload(
                    1200,
                    rented_days_delta=1,
                    available_days_delta=1,
                    revenue_cents_delta=5500,
                ),
                world.operator("ATL"),
            )
        )
        assert second["odometer_km"] == 1200
        assert second["rented_days_total"] == 4
        assert second["available_days_total"] == 5
        assert second["revenue_to_date_cents"] == 22000
        assert second["version"] == first["version"] + 1

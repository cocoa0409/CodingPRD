"""Row shapes: what a create stores, what a read returns, what a client cannot set.

These are the flat facts the rest of the suite stands on — the defaults a fresh
row opens with, the fields the server owns outright, the per-entity 404 codes,
and the one entity that carries no version at all.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    BASE_CLOCK,
    BASE_CLOCK_STAMP,
    ConditionStatus,
    EntryType,
    FleetStatus,
    MarketStatus,
    PolicyStatus,
    Region,
    SourceEntityType,
    UNKNOWN_UUID,
    factories,
    fixtures,
    is_valid_uuid,
    make_fleet_controller_headers,
    make_fleet_planner_headers,
    make_market_operator_headers,
    make_platform_admin_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_entry,
    assert_market,
    assert_nulls,
    assert_three_digit_millis,
    assert_vehicle,
    list_page,
    list_rows,
    total_count,
)


class TestMarketRegistry:
    """The market row is the simplest entity in the system and the strictest."""

    def test_a_registered_market_opens_active_with_a_zero_census(self, client):
        """Eight input fields are echoed and the two server fields are minted.

        PRD 3.1: "A newly registered market opens in status `ACTIVE` with an
        `in_service_unit_count` of 0."
        PRD 2.5: "Every stored resource carries a server-minted `id` formatted as
        a UUID."
        PRD 2.5: "`version` is an integer that starts at 1 when the row is created
        and increases by exactly 1 on each subsequent mutation."

        Design: Corner/entities/market_create_returns_201_with_active_status_and_zero_census
        """
        fixtures.set_clock(client, BASE_CLOCK)

        response = client.create_market(
            factories.market_payload(), make_platform_admin_headers()
        )
        market = validate_success(response, expected_status=201)
        envelope = response.json()

        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert_three_digit_millis(envelope["meta"]["api_request_timestamp"])

        assert_market(market, factories.ATL)
        assert market["status"] == MarketStatus.ACTIVE
        assert market["in_service_unit_count"] == 0
        assert market["version"] == 1
        assert is_valid_uuid(market["id"])
        assert market["id"] == market["id"].strip()
        assert_three_digit_millis(market["created_at"])
        assert_three_digit_millis(market["updated_at"])
        assert_instant_equals(market["created_at"], BASE_CLOCK_STAMP)
        assert_instant_equals(market["updated_at"], market["created_at"])

    def test_the_single_market_read_returns_the_stored_row_unchanged(self, client):
        """A read is not a mutation: the census, version and stamps all hold.

        PRD 2.5: "`updated_at` is an ISO 8601 UTC timestamp with three fractional
        digits, refreshed on every mutation of the row."
        PRD 2.1: "All five roles may perform every read operation in this API, with
        two exceptions: the plan-performance computed read and the vehicle
        channel-recommendation computed read are closed to `MarketOperator` and
        available to the other four roles."

        Design: Corner/entities/market_read_by_id_returns_the_stored_row
        """
        fixtures.set_clock(client, BASE_CLOCK)
        created = validate_success(
            client.create_market(factories.market_payload(), make_platform_admin_headers()),
            expected_status=201,
        )

        read = validate_success(
            client.get_market(created["id"], make_fleet_planner_headers())
        )
        assert read == created

        again = validate_success(
            client.get_market(created["id"], make_fleet_planner_headers())
        )
        assert again["version"] == 1
        assert again["in_service_unit_count"] == 0
        assert_instant_equals(again["updated_at"], created["updated_at"])

    def test_the_list_envelope_counts_the_filtered_set_and_not_the_page(self, client):
        """Two pages of a three-row table, then the same envelope under a filter.

        PRD 2.3: "Both paginated and unpaginated list responses populate `limit`,
        `offset`, `total_count` and `has_more` inside the `meta` object of the
        envelope, where `total_count` is the number of rows matching the request's
        filters before the page window is applied and `has_more` states whether any
        matching row remains beyond the current window."
        PRD 2.3: "`limit` caps the number of rows returned; when it is omitted the
        server uses 10, and an explicitly supplied value must be an integer of at
        least 1 and at most 100."
        PRD 3.1: "Markets are discoverable by `region`, by `status` and by `code`."

        Design: Corner/entities/markets_list_reports_total_count_and_has_more_under_pagination
        """
        world = fixtures.setup_reference_world(client)
        assert len(world.markets) == 3

        first_rows, first_meta = list_page(
            client.list_markets(make_fleet_controller_headers(), limit=2, offset=0)
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_rows, second_meta = list_page(
            client.list_markets(make_fleet_controller_headers(), limit=2, offset=2)
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        central_rows, central_meta = list_page(
            client.list_markets(make_fleet_controller_headers(), region=Region.CENTRAL)
        )
        assert len(central_rows) == 2
        assert central_meta["total_count"] == 2
        assert {row["code"] for row in central_rows} == {"DFW", "ORD"}

        _all_rows, default_meta = list_page(
            client.list_markets(make_fleet_controller_headers())
        )
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0
        assert default_meta["has_more"] is False

    def test_an_unstored_market_uuid_is_refused_with_the_markets_own_code(self, client):
        """A well-formed identifier that resolves to nothing is a 404, not a 422.

        PRD 2.9: "Each entity has its own dedicated 404 code:
        `ERR_MARKET_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
        `ERR_CHANNEL_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
        `ERR_FLEET_PLAN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
        `ERR_VEHICLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_DAMAGE_EVENT_NOT_FOUND`, `ERR_CONSIGNMENT_NOT_FOUND` and
        `ERR_LEDGER_ENTRY_NOT_FOUND`."
        PRD 2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/market_get_with_unknown_uuid_returns_404_not_found
        """
        fixtures.set_clock(client, BASE_CLOCK)

        response = client.get_market(UNKNOWN_UUID, make_fleet_planner_headers())
        error = validate_error(response, ApiErrorId.MARKET_NOT_FOUND)
        assert response.json()["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"]

        assert total_count(client.list_markets(make_fleet_planner_headers())) == 0

    def test_a_create_missing_the_required_code_stores_nothing(self, client):
        """The seven other fields are present and the row still does not exist.

        PRD 2.9: "Request schema: all required body fields present, enum values
        inside their declared sets, integers non-negative where declared, instants
        parseable as ISO-8601 UTC — `ERR_INVALID_REQUEST` (422)."
        PRD 3.1: "It is registered with a `code` of three to five uppercase letters
        that must be globally unique — a second market claiming an existing code is
        refused with `ERR_DUPLICATE_MARKET_CODE` (HTTP 409) — a human-readable
        `name`, and a `region` that is one of `EAST`, `CENTRAL` or `WEST`."

        Design: Corner/entities/market_create_missing_required_code_returns_422_invalid_request
        """
        fixtures.set_clock(client, BASE_CLOCK)
        payload = factories.market_payload()
        payload.pop("code")

        validate_error(
            client.create_market(payload, make_platform_admin_headers()),
            ApiErrorId.INVALID_REQUEST,
        )
        assert total_count(client.list_markets(make_platform_admin_headers())) == 0

    def test_an_unknown_region_and_a_zero_haul_rate_are_both_schema_refusals(
        self, client
    ):
        """One value is outside its enum, the other outside its declared range.

        PRD 3.1: "`transfer_cost_per_km_cents` is the line-haul rate in cents per
        kilometre charged when this market is the **origin** of a transfer and must
        be greater than zero."
        PRD 2.9: "Request schema: all required body fields present, enum values
        inside their declared sets, integers non-negative where declared, instants
        parseable as ISO-8601 UTC — `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/market_create_with_out_of_range_region_enum_returns_422
        """
        fixtures.set_clock(client, BASE_CLOCK)

        validate_error(
            client.create_market(
                factories.market_payload(region="NORTH"), make_platform_admin_headers()
            ),
            ApiErrorId.INVALID_REQUEST,
        )
        validate_error(
            client.create_market(
                factories.market_payload(
                    **dict(factories.DFW, transfer_cost_per_km_cents=0)
                ),
                make_platform_admin_headers(),
            ),
            ApiErrorId.INVALID_REQUEST,
        )

        assert total_count(client.list_markets(make_platform_admin_headers())) == 0

    def test_the_server_owned_fields_of_a_market_ignore_whatever_the_client_sends(
        self, client
    ):
        """An injected id, stamp, version, status and census are all discarded.

        PRD 2.9: "Unknown body fields, and attempts to write system-managed or
        computed fields, are silently ignored rather than rejected."
        PRD 2.5: "The identifier bears no type prefix and no domain-encoded
        structure; clients must never parse it or synthesize one."
        PRD 2.5: "Each resource also carries `created_at`, an ISO 8601 UTC timestamp
        with exactly three fractional digits recorded from the logical clock at the
        moment the row was written."
        PRD 3.1: "For the purposes of this system suspension is one-way: there is no
        un-suspend capability."

        Design: Corner/entities/market_id_and_timestamps_are_server_minted_client_input_ignored
        """
        fixtures.set_clock(client, BASE_CLOCK)

        market = validate_success(
            client.create_market(
                factories.market_payload(
                    id="mkt_client_supplied",
                    created_at="1999-01-01T00:00:00Z",
                    version=99,
                    status=MarketStatus.SUSPENDED,
                    in_service_unit_count=42,
                ),
                make_platform_admin_headers(),
            ),
            expected_status=201,
        )

        assert market["id"] != "mkt_client_supplied"
        assert is_valid_uuid(market["id"])
        assert_instant_equals(market["created_at"], BASE_CLOCK_STAMP)
        assert market["version"] == 1
        assert market["status"] == MarketStatus.ACTIVE
        assert market["in_service_unit_count"] == 0

        stored = validate_success(
            client.get_market(market["id"], make_platform_admin_headers())
        )
        assert stored["status"] == MarketStatus.ACTIVE
        assert stored["version"] == 1


class TestMintedVehicleDefaults:
    """Minting takes two fields from the caller and derives everything else."""

    MILESTONES = (
        "registered_at",
        "licensed_at",
        "prep_completed_at",
        "first_rent_ready_at",
        "in_service_at",
        "held_for_sale_at",
        "net_book_value_at_hold_cents",
    )

    def _four_unit_allocation(self, client, world, segment_code="MIDSIZE"):
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        allocation = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("PGM"),
            world.segment_id(segment_code),
            4,
            plan["version"],
        )
        return allocation

    def test_a_fresh_car_opens_on_order_and_sound_with_every_counter_at_zero(
        self, client, world
    ):
        """Both state dimensions take their defaults and no milestone is stamped.

        PRD 3.4: "A newly minted car appears with `fleet_status` `ON_ORDER`,
        `condition_status` `SOUND`, an `odometer_km` of 0, and zeros across
        `rented_days_total`, `available_days_total` and `revenue_to_date_cents`."
        PRD 3.4: "Its milestone instants — `registered_at`, `licensed_at`,
        `prep_completed_at`, `first_rent_ready_at`, `in_service_at`,
        `held_for_sale_at` — are all null, as are `net_book_value_at_hold_cents`,
        and `total_recondition_cents` starts at 0."
        PRD 2.12: "`created_vehicle_count` counts **all** of its vehicles regardless
        of `fleet_status`, and is capped at the allocation's `unit_count`."

        Design: Corner/entities/vehicle_create_defaults_odometer_zero_on_order_and_sound
        """
        allocation = self._four_unit_allocation(client, world)

        vehicle = validate_success(
            client.create_vehicle(
                allocation["id"],
                factories.vehicle_payload(factories.vin("D1"), world.market_id("ATL")),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )

        assert_vehicle(vehicle)
        assert vehicle["fleet_status"] == FleetStatus.ON_ORDER
        assert vehicle["condition_status"] == ConditionStatus.SOUND
        assert vehicle["odometer_km"] == 0
        assert vehicle["rented_days_total"] == 0
        assert vehicle["available_days_total"] == 0
        assert vehicle["revenue_to_date_cents"] == 0
        assert vehicle["total_recondition_cents"] == 0
        assert_nulls(vehicle, self.MILESTONES)
        assert vehicle["version"] == 1

        parent = fixtures.read_allocation(client, allocation["id"])
        assert parent["created_vehicle_count"] == 1
        assert parent["status"] == AllocationStatus.ORDERED

    def test_the_economics_are_copied_from_the_allocation_not_from_the_payload(
        self, client, world
    ):
        """A decoy segment and a one-cent price are both silently discarded.

        PRD 3.4: "Everything economic about the car is inherited and cannot be
        supplied by the client: `segment_id` and `program_id` are copied from the
        allocation's `segment_id` and `program_id` and are immutable for the life of
        the unit, and `capitalized_cost_cents` is copied from the allocation's
        `capitalized_cost_per_unit_cents`."
        PRD 3.4: "Creation also books the purchase: a ledger line of `entry_type`
        `CAPITALIZATION` is posted for the unit with an `amount_cents` equal to its
        `capitalized_cost_cents` as a positive debit, with `source_entity_type`
        `Vehicle` and `source_entity_id` the new vehicle's own identifier."
        PRD 2.9: "Unknown body fields, and attempts to write system-managed or
        computed fields, are silently ignored rather than rejected."

        Design: Corner/entities/vehicle_capitalized_cost_and_segment_copied_from_allocation_input_ignored
        """
        decoy_segment = fixtures.create_segment(client, dict(factories.SUV))
        allocation = self._four_unit_allocation(client, world)

        vehicle = validate_success(
            client.create_vehicle(
                allocation["id"],
                factories.vehicle_payload(
                    factories.vin("E1"),
                    world.market_id("ATL"),
                    capitalized_cost_cents=1,
                    segment_id=decoy_segment["id"],
                    program_id=world.program_id("RSK"),
                    odometer_km=90000,
                ),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )

        assert vehicle["capitalized_cost_cents"] == factories.CAPITALIZED_COST_CENTS
        assert vehicle["segment_id"] == world.segment_id("MIDSIZE")
        assert vehicle["program_id"] == world.program_id("PGM")
        assert vehicle["odometer_km"] == 0

        rows = fixtures.read_ledger(client, vehicle["id"])
        capitalizations = [
            row for row in rows if row["entry_type"] == EntryType.CAPITALIZATION
        ]
        assert len(capitalizations) == 1
        assert capitalizations[0]["amount_cents"] == factories.CAPITALIZED_COST_CENTS
        assert capitalizations[0]["source_entity_type"] == SourceEntityType.VEHICLE
        assert capitalizations[0]["source_entity_id"] == vehicle["id"]


class TestLedgerRowShape:
    """The one entity in the system that carries neither a version nor an
    updated_at, and has no write surface at all."""

    def test_a_capitalization_row_is_readable_and_carries_no_version(
        self, client, world
    ):
        """Two read surfaces reach the same immutable row and nothing can edit it.

        PRD 2.5: "A `LedgerEntry` is append-only and immutable once written, so it
        carries only `id` and `created_at`: it has **no** `updated_at` field and
        **no** `version` field at all, and neither should appear in its
        representation."
        PRD 2.5: "There is deliberately no create, update or delete operation for
        ledger rows — every line is written as a side effect of some other
        transition, and the only way to reach one is to read it."
        PRD 2.10: "A row names the `vehicle_id` it is booked against, an
        `entry_type` classifying the line, a signed `amount_cents`, the `posted_at`
        instant taken from the logical clock, and a human-readable `memo` describing
        the line's provenance — for a recovery settlement, for example, the memo
        spells out the three-way split, in the shape `recovery waterfall recondition
        250000 / depreciation 350000 / income 100000`."

        Design: Corner/entities/ledger_entry_is_immutable_with_no_version_and_no_write_endpoint
        """
        built = fixtures.setup_allocation_with_units(
            client, world, market_code="ATL", program_key="PGM", unit_count=1, vin_prefix="LE"
        )
        vehicle_id = built["vehicles"][0]["id"]

        rows, meta = list_page(
            client.list_ledger_entries(
                make_fleet_controller_headers(), vehicle_id=vehicle_id
            )
        )
        assert meta["total_count"] == 1
        entry = rows[0]
        assert entry["entry_type"] == EntryType.CAPITALIZATION
        assert entry["amount_cents"] == factories.CAPITALIZED_COST_CENTS
        assert entry["source_entity_type"] == SourceEntityType.VEHICLE
        assert entry["source_entity_id"] == vehicle_id
        assert entry["vehicle_id"] == vehicle_id

        single = validate_success(
            client.get_ledger_entry(entry["id"], make_fleet_controller_headers())
        )
        assert single["id"] == entry["id"]
        assert_instant_equals(single["posted_at"], BASE_CLOCK_STAMP)
        assert_ledger_entry(single)
        assert "version" not in single
        assert "updated_at" not in single
        assert isinstance(single["memo"], str) and single["memo"]

        per_vehicle = list_rows(
            client.list_vehicle_ledger_entries(
                vehicle_id, make_fleet_controller_headers()
            )
        )
        assert [row["id"] for row in per_vehicle] == [entry["id"]]
        assert "version" not in per_vehicle[0]
        assert "updated_at" not in per_vehicle[0]

        validate_error(
            client.get_ledger_entry(UNKNOWN_UUID, make_fleet_controller_headers()),
            ApiErrorId.LEDGER_ENTRY_NOT_FOUND,
        )


class TestNestedParentResolution:
    """A child create resolves its path parent before anything else it could fail."""

    def test_a_task_under_an_unknown_vehicle_reports_the_vehicles_own_code(
        self, client
    ):
        """The parent's 404 outranks both the child's code and the scope check.

        PRD 2.9: "When a request path carries more than one identifier, the
        identifiers are resolved strictly left to right, and the first one that does
        not resolve determines the response."
        PRD 2.9: "Market scope for `MarketOperator`, evaluated after existence so the
        owning market can be resolved — `ERR_MARKET_SCOPE_VIOLATION` (403)."

        Design: Corner/entities/in_fleeting_task_create_under_unknown_vehicle_returns_404_not_found
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[factories.ATL],
            with_programs=False,
            with_policy=False,
        )

        error = validate_error(
            client.create_in_fleeting_task(
                UNKNOWN_UUID,
                factories.registration_task_payload(),
                make_market_operator_headers(world.market_id("ATL")),
            ),
            ApiErrorId.VEHICLE_NOT_FOUND,
        )
        assert error["error_id"] != ApiErrorId.TASK_NOT_FOUND
        assert error["error_id"] != ApiErrorId.MARKET_SCOPE_VIOLATION

        assert (
            total_count(client.list_in_fleeting_tasks(make_fleet_planner_headers())) == 0
        )


class TestAllocationJunction:
    """The allocation joins a plan, a program and a segment, and every one of the
    three edges is a discoverable filter."""

    def test_the_same_allocation_is_reachable_from_each_of_its_three_keys(
        self, client, world
    ):
        """Three filters find it, a fourth finds an empty page rather than a 404.

        PRD 3.3: "Allocations are discoverable by `plan_id`, by `program_id`, by
        `segment_id` and by `status`."
        PRD 3.3: "The payload names a `program_id`, a `segment_id`, a `unit_count`, a
        `capitalized_cost_per_unit_cents` greater than zero, and the
        optimistic-concurrency field `expected_plan_version` described in §2.7."
        PRD 2.12: "`allocated_unit_count` is the sum of `unit_count` across the
        plan's allocations whose status is `ORDERED`, `PARTIALLY_INFLEETED` or
        `INFLEETED`; allocations in `CANCELLED` contribute nothing."

        Design: Corner/entities/purchase_allocation_junction_is_reachable_from_all_three_foreign_keys
        """
        decoy_segment = fixtures.create_segment(client, dict(factories.SUV))
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        allocation = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("PGM"),
            world.segment_id("MIDSIZE"),
            4,
            plan["version"],
        )

        headers = make_fleet_planner_headers()
        for filters in (
            {"plan_id": plan["id"]},
            {"program_id": world.program_id("PGM")},
            {"segment_id": world.segment_id("MIDSIZE")},
        ):
            rows, meta = list_page(client.list_purchase_allocations(headers, **filters))
            assert meta["total_count"] == 1, filters
            assert [row["id"] for row in rows] == [allocation["id"]], filters

        decoy_rows, decoy_meta = list_page(
            client.list_purchase_allocations(headers, segment_id=decoy_segment["id"])
        )
        assert decoy_rows == []
        assert decoy_meta["total_count"] == 0

        stored = fixtures.read_allocation(client, allocation["id"])
        assert stored["plan_id"] == plan["id"]
        assert stored["program_id"] == world.program_id("PGM")
        assert stored["segment_id"] == world.segment_id("MIDSIZE")
        assert fixtures.read_plan(client, plan["id"])["allocated_unit_count"] == 4


class TestPolicySupersession:
    """The self-referencing supersedes edge may not cross segments."""

    def test_a_draft_naming_another_segments_active_policy_is_refused(self, client):
        """The identifier resolves, so the refusal is the mismatch and not a 404.

        PRD 3.2: "When supplied, that identifier must name a policy on the **same**
        `segment_id` whose status is `ACTIVE`; naming a policy from another segment,
        or one that is still `DRAFT` or already `SUPERSEDED`, is refused with
        `ERR_SUPERSEDE_TARGET_MISMATCH` (HTTP 422)."
        PRD 2.9: "Foreign keys carried in a request **body** are resolved after the
        path, in the order the operation's input list declares them, and they use the
        same per-entity 404 codes."

        Design: Corner/entities/depreciation_policy_supersede_target_of_a_different_segment_is_rejected
        """
        world = fixtures.setup_reference_world(
            client,
            market_payloads=[],
            segment_payloads=[factories.MIDSIZE, factories.SUV],
            channel_payloads=[],
            with_programs=False,
            with_policy=False,
        )
        suv_policy = fixtures.create_active_policy(
            client,
            world.segment_id("SUV"),
            name="SUV-2026",
            monthly_depreciation_pct=0.014,
            mileage_depreciation_cents_per_km=14,
            floor_residual_pct=0.32,
        )
        assert suv_policy["status"] == PolicyStatus.ACTIVE
        assert suv_policy["version"] == 2

        error = validate_error(
            client.create_depreciation_policy(
                factories.depreciation_policy_payload(
                    world.segment_id("MIDSIZE"),
                    supersedes_policy_id=suv_policy["id"],
                ),
                make_fleet_controller_headers(),
            ),
            ApiErrorId.SUPERSEDE_TARGET_MISMATCH,
        )
        assert error["error_id"] != ApiErrorId.POLICY_NOT_FOUND

        assert (
            total_count(
                client.list_depreciation_policies(
                    make_fleet_controller_headers(),
                    segment_id=world.segment_id("MIDSIZE"),
                )
            )
            == 0
        )

        untouched = validate_success(
            client.get_depreciation_policy(
                suv_policy["id"], make_fleet_controller_headers()
            )
        )
        assert untouched["status"] == PolicyStatus.ACTIVE
        assert untouched["version"] == 2

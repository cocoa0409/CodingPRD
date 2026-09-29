"""Four validation rules seen from both sides: the refusal and the acceptance.

A uniqueness key is only proven by showing what does *not* collide with it, a
conditional gate is only proven by showing the sibling request it lets through,
and a precedence claim is only proven when both losing rules were genuinely
violated at once.
"""

from test_helpers import (
    ApiErrorId,
    ConditionStatus,
    FleetStatus,
    MarketStatus,
    MileageBand,
    Region,
    UNKNOWN_UUID,
    factories,
    fixtures,
    make_fleet_planner_headers,
    make_platform_admin_headers,
    make_remarketing_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import list_rows, total_count


class TestMarketCodeUniqueness:
    """The key is the code alone, globally, and nothing else in the row."""

    def test_a_second_claim_on_a_live_code_is_refused_and_changes_nothing(
        self, client
    ):
        """A different region and a different name do not buy a second ATL.

        PRD 3.1: "It is registered with a `code` of three to five uppercase letters
        that must be globally unique — a second market claiming an existing code is
        refused with `ERR_DUPLICATE_MARKET_CODE` (HTTP 409) — a human-readable `name`,
        and a `region` that is one of `EAST`, `CENTRAL` or `WEST`."
        PRD 2.9: "Uniqueness — `ERR_DUPLICATE_MARKET_CODE`,
        `ERR_DUPLICATE_SEGMENT_CODE`, `ERR_DUPLICATE_CHANNEL_CODE`,
        `ERR_DUPLICATE_VIN`, `ERR_DUPLICATE_FLEET_PLAN` and
        `ERR_DUPLICATE_TASK_TYPE` (all 409)."

        Design: Corner/validations/second_market_with_the_same_code_returns_409_duplicate_market_code
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        first = fixtures.create_market(client, dict(factories.ATL))
        assert first["code"] == "ATL"
        assert first["name"] == "Atlanta"
        assert first["version"] == 1

        validate_error(
            client.create_market(
                factories.market_payload(
                    code="ATL",
                    name="Atlanta West",
                    region=Region.WEST,
                    transport_hub_distance_km=50,
                    transfer_cost_per_km_cents=200,
                    storage_cost_per_day_cents=600,
                    prep_capacity_per_day=1,
                    registration_lead_days=5,
                ),
                make_platform_admin_headers(),
            ),
            ApiErrorId.DUPLICATE_MARKET_CODE,
        )

        assert total_count(client.list_markets(make_platform_admin_headers())) == 1
        stored = fixtures.read_market(client, first["id"])
        assert stored["name"] == "Atlanta"
        assert stored["region"] == Region.EAST
        assert stored["version"] == 1

    def test_two_markets_differing_only_in_code_both_persist(self, client):
        """The same city name twice is fine; the same code twice is not.

        PRD 3.1: "A newly registered market opens in status `ACTIVE` with an
        `in_service_unit_count` of 0."
        PRD 3.1: "Markets are discoverable by `region`, by `status` and by `code`."

        Design: Corner/validations/distinct_market_codes_both_persist_and_the_rule_stays_quiet
        """
        fixtures.set_clock(client, "2026-01-01T00:00:00Z")
        first = fixtures.create_market(client, dict(factories.ATL))
        second = fixtures.create_market(
            client, factories.market_payload(code="ATLW", name="Atlanta")
        )

        assert first["id"] != second["id"]
        assert second["code"] == "ATLW"
        assert second["name"] == first["name"]
        assert second["status"] == MarketStatus.ACTIVE
        assert second["in_service_unit_count"] == 0
        assert second["version"] == 1

        assert total_count(client.list_markets(make_platform_admin_headers())) == 2
        by_code = list_rows(
            client.list_markets(make_platform_admin_headers(), code="ATL")
        )
        assert [row["id"] for row in by_code] == [first["id"]]


class TestMinimumHoldingGate:
    """A ninety-day-old car is too young for the factory but old enough for the
    auction, and the refusal costs it nothing."""

    def _ninety_day_old_program_car(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="PGM",
            vin_prefix="MH",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        fixtures.set_clock(client, "2026-04-15T00:00:00Z")
        return built["vehicle"]["id"]

    def test_the_repurchase_channel_reports_the_holding_gate_not_ineligibility(
        self, client, world
    ):
        """Both rules are broken by one request and the more specific code wins.

        PRD 3.8: "And for a `PROGRAM_REPURCHASE` channel specifically the vehicle's
        `holding_days` must be at least the program's `min_holding_days`, or the
        request is refused with `ERR_MIN_HOLDING_PERIOD_NOT_MET` (HTTP 422); this
        minimum-holding check carries its own code and, being priority 16, is reported
        ahead of the general eligibility failure that the same shortfall would also
        produce."
        PRD 3.8: "A channel whose `code` is `PROGRAM_REPURCHASE` is excluded unless
        **all five** of the following hold: the vehicle's program has `program_type`
        `PROGRAM`; the vehicle's `holding_days` is at least the program's
        `min_holding_days`; its `holding_days` is at most the program's
        `max_holding_days`; its `odometer_km` is at most the program's
        `max_eligible_mileage_km`; and its `condition_status` is `SOUND` or
        `RECONDITIONED`."

        Design: Corner/validations/min_holding_period_gate_applies_only_to_the_program_repurchase_channel
        """
        vehicle_id = self._ninety_day_old_program_car(client, world)
        valuation = fixtures.read_valuation(client, vehicle_id)
        assert valuation["holding_days"] == 90
        assert valuation["mileage_band"] == MileageBand.WITHIN_SOFT

        refusal = validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id,
                    world.channel_id("PROGRAM_REPURCHASE"),
                    fixtures.read_vehicle(client, vehicle_id)["version"],
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.MIN_HOLDING_PERIOD_NOT_MET,
        )
        assert refusal["error_id"] != ApiErrorId.CHANNEL_NOT_ELIGIBLE

    def test_the_gate_is_conditional_on_the_channel_and_leaves_no_trace(
        self, client, world
    ):
        """The auction takes the very same car at the very same version.

        PRD 3.8: "Channels bearing any other `code` face neither exclusion and are
        eligible whenever they are `ACTIVE`."
        PRD 3.8: "The same request drives the vehicle `IN_SERVICE → HELD_FOR_SALE`,
        stamping `held_for_sale_at` from the logical clock, setting
        `net_book_value_at_hold_cents` to the vehicle's `net_book_value_cents`
        evaluated at that instant, decrementing the current market's
        `in_service_unit_count` by 1 — the unit leaves the rentable census the moment
        it is consigned, not when it sells — and incrementing the vehicle's `version`
        by 1."

        Design: Corner/validations/min_holding_period_gate_applies_only_to_the_program_repurchase_channel
        """
        vehicle_id = self._ninety_day_old_program_car(client, world)
        version_before = fixtures.read_vehicle(client, vehicle_id)["version"]
        book_value = fixtures.read_valuation(client, vehicle_id)["net_book_value_cents"]

        validate_error(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("PROGRAM_REPURCHASE"), version_before
                ),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.MIN_HOLDING_PERIOD_NOT_MET,
        )
        assert fixtures.read_vehicle(client, vehicle_id)["version"] == version_before
        assert fixtures.census(client, world.market_id("ATL")) == 1

        accepted = validate_success(
            client.create_consignment(
                factories.consignment_payload(
                    vehicle_id, world.channel_id("AUCTION"), version_before
                ),
                make_remarketing_manager_headers(),
            ),
            expected_status=201,
        )
        assert accepted["channel_id"] == world.channel_id("AUCTION")

        vehicle = fixtures.read_vehicle(client, vehicle_id)
        assert vehicle["fleet_status"] == FleetStatus.HELD_FOR_SALE
        assert vehicle["condition_status"] == ConditionStatus.SOUND
        assert vehicle["net_book_value_at_hold_cents"] == book_value
        assert vehicle["version"] == version_before + 1
        assert fixtures.census(client, world.market_id("ATL")) == 0


class TestPathResolutionBeforeScope:
    """Rank five runs before rank four can even name an owner."""

    def test_an_unknown_vehicle_is_a_404_rather_than_a_scope_refusal(
        self, client, world
    ):
        """A branch operator from the wrong city still gets the existence answer.

        PRD 2.9: "Market scope for `MarketOperator`, evaluated after existence so the
        owning market can be resolved — `ERR_MARKET_SCOPE_VIOLATION` (403)."
        PRD 2.1: "This check runs only after the path identifiers have been resolved,
        since the owning market cannot be determined before the target row is loaded."

        Design: Corner/validations/unknown_vehicle_path_id_returns_404_before_the_market_scope_check
        """
        refusal = validate_error(
            client.post_usage(
                UNKNOWN_UUID,
                factories.usage_payload(
                    100,
                    rented_days_delta=1,
                    available_days_delta=1,
                    revenue_cents_delta=5500,
                ),
                world.operator("DFW"),
            ),
            ApiErrorId.VEHICLE_NOT_FOUND,
        )
        assert refusal["error_id"] != ApiErrorId.MARKET_SCOPE_VIOLATION

        assert total_count(client.list_vehicles(make_fleet_planner_headers())) == 0
        assert total_count(client.list_ledger_entries(make_fleet_planner_headers())) == 0

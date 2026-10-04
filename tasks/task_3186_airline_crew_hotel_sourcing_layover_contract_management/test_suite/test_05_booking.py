"""Rest compliance, booking gauntlet, blackout handling, room-block capacity,
distressed surge pricing, and pickup timing."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_station, make_union_agreement, make_vendor,
    make_station_and_union, make_active_contract, make_layover,
    make_confirmed_booking, make_checked_in_booking, make_surged_layover,
    make_distressed_confirmed, book_layover,
    setup_sourced_station, make_vendor_rep_headers,
)
from test_helpers.fixtures import ADMIN, SOURCING, CREWOPS


class TestRestCompliance:

    def test_rest_effective_hours_exactly_at_minimum_is_compliant(self, api):
        """PRD §3.5: "The layover is rest-compliant when this effective rest is at
        least — equal counts as compliant — the stricter of the station's
        `min_rest_hours` and the `min_rest_hours` of the union agreement matching the
        layover's `crew_type`."

        Design: Difficulty/boundary_precision_check/rest_effective_hours_exactly_at_minimum_is_compliant
        """
        station, union = make_station_and_union(
            "BOI", station_min_rest=12, transport=30,
            crew_type="PILOT", union_min_rest=14)
        # span 15h - 1.0h transport = 14.0 >= 14 -> compliant
        edge = validate_success(api.create_layover_requirement({
            "station_id": station["id"], "crew_type": "PILOT", "crew_count": 2,
            "arrival_time": "2026-10-02T18:00:00Z",
            "departure_time": "2026-10-03T09:00:00Z",
            "required_rest_hours": 14}, CREWOPS), expected_status=201)
        assert edge["rest_compliant"] is True

    def test_rest_one_minute_short_of_minimum_is_not_compliant(self, api):
        """PRD §3.5: "The layover's span in hours is the whole-hour count between
        `arrival_time` and `departure_time`, fractional hours discarded. From that
        span the system subtracts the transport tax: two legs of the station's
        `transport_time_minutes`, converted to hours."
        PRD §3.5: "The layover is rest-compliant when this effective rest is at
        least — equal counts as compliant — the stricter of the station's
        `min_rest_hours` and the `min_rest_hours` of the union agreement matching the
        layover's `crew_type`."

        Design: Difficulty/boundary_precision_check/rest_effective_hours_exactly_at_minimum_is_compliant
        """
        station, union = make_station_and_union(
            "BOI", station_min_rest=12, transport=30,
            crew_type="PILOT", union_min_rest=14)
        # span floors to 14h (18:01 -> 09:00 = 14h59m), effective 13.0 < 14
        under = validate_success(api.create_layover_requirement({
            "station_id": station["id"], "crew_type": "PILOT", "crew_count": 2,
            "arrival_time": "2026-10-02T18:01:00Z",
            "departure_time": "2026-10-03T09:00:00Z",
            "required_rest_hours": 14}, CREWOPS), expected_status=201)
        assert under["rest_compliant"] is False

    def test_rest_compliance_scheduled_variant_uses_stored_arrival(self, api):
        """PRD §3.5: "For irregular-operations layovers (`is_irregular_ops` true), the
        `arrival_time` used in this computation is replaced by the current logical
        clock time whenever the given `arrival_time` lies in the past, reflecting
        actual wheels-down rather than the original schedule."

        Design: Difficulty/dual_variant_calc/rest_compliance_scheduled_vs_irregular_variants
        """
        station, union = make_station_and_union(
            "DFW", station_min_rest=10, transport=30,
            crew_type="PILOT", union_min_rest=10)
        # scheduled variant: uses the stored times — span 13h - 1.0h = 12.0 >= 10
        sched = validate_success(api.create_layover_requirement({
            "station_id": station["id"], "crew_type": "PILOT", "crew_count": 4,
            "arrival_time": "2026-10-01T10:00:00Z",
            "departure_time": "2026-10-01T23:00:00Z",
            "required_rest_hours": 10, "is_irregular_ops": False}, CREWOPS),
            expected_status=201)
        assert sched["rest_compliant"] is True

    def test_rest_compliance_irregular_variant_clamps_past_arrival(self, api):
        """PRD §3.5: "For irregular-operations layovers (`is_irregular_ops` true), the
        `arrival_time` used in this computation is replaced by the current logical
        clock time whenever the given `arrival_time` lies in the past, reflecting
        actual wheels-down rather than the original schedule."

        Design: Difficulty/dual_variant_calc/rest_compliance_scheduled_vs_irregular_variants
        """
        station, union = make_station_and_union(
            "DFW", station_min_rest=10, transport=30,
            crew_type="PILOT", union_min_rest=10)
        # move the logical clock past the stored departure so the stored arrival
        # lies in the past and the irregular-ops clamp applies
        api.set_clock("2026-10-02T00:00:00Z", ADMIN)
        # irregular variant: the stored arrival 2026-10-01 is in the past relative
        # to the logical clock, so the clamp applies — the clamped
        # arrival lies after the stored departure, effective rest < 10
        iro = validate_success(api.create_layover_requirement({
            "station_id": station["id"], "crew_type": "PILOT", "crew_count": 4,
            "arrival_time": "2026-10-01T10:00:00Z",
            "departure_time": "2026-10-01T23:00:00Z",
            "required_rest_hours": 10, "is_irregular_ops": True}, CREWOPS),
            expected_status=201)
        assert iro["rest_compliant"] is False


class TestBookingGauntlet:

    def test_rest_safety_beats_fiscal_block_capacity(self, api):
        """PRD §3.6: "The booking gauntlet then runs, in this order. Rest safety
        first: `rest_compliant` must currently be true, or the booking is rejected
        with `ERR_REST_VIOLATION` (HTTP 422) — the rest floor is a safety rule and is
        evaluated before any capacity check."

        Design: Difficulty/priority_pair_validation_conflict/rest_safety_beats_fiscal_block_capacity
        """
        station, union, vendor, contract = setup_sourced_station(
            "LIT", station_min_rest=10, transport=30, union_min_rest=10,
            rate_cents=8000, room_block_size=1, budget_cap_cents=500000)
        # fill the block: one CONFIRMED allocation on 2026-10-05
        make_confirmed_booking(
            station, contract, stay_date="2026-10-05T00:00:00Z", crew_count=2,
            arrival="2026-10-04T18:00:00Z", departure="2026-10-05T09:00:00Z")
        # G2 is rest-non-compliant: span 5h - 1.0h = 4.0 < 10
        layover = make_layover(
            station["id"], crew_type="PILOT", crew_count=2,
            arrival="2026-10-05T18:00:00Z", departure="2026-10-05T23:00:00Z",
            required_rest_hours=10)
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-05T00:00:00Z",
            "expected_layover_version": layover["version"]}, CREWOPS)
        validate_error(resp, ApiErrorId.ERR_REST_VIOLATION)
        fresh = validate_success(api.get_layover_requirement(layover["id"], CREWOPS))
        assert fresh["status"] == "PLANNED"
        data, meta = validate_paginated(api.list_allocations(
            CREWOPS, params={"layover_requirement_id": layover["id"]}))
        assert len(data) == 0

    def test_rest_safety_rejects_noncompliant_book_with_block_available(self, api):
        """PRD §3.6: "The booking gauntlet then runs, in this order. Rest safety
        first: `rest_compliant` must currently be true, or the booking is rejected
        with `ERR_REST_VIOLATION` (HTTP 422) — the rest floor is a safety rule and is
        evaluated before any capacity check."

        Design: Difficulty/priority_pair_validation_conflict/rest_safety_beats_fiscal_block_capacity
        """
        station, union, vendor, contract = setup_sourced_station(
            "LIT", station_min_rest=10, transport=30, union_min_rest=10,
            rate_cents=8000, room_block_size=1, budget_cap_cents=500000)
        # block has capacity (no bookings yet); only rest compliance fails
        layover = make_layover(
            station["id"], crew_type="PILOT", crew_count=2,
            arrival="2026-10-05T18:00:00Z", departure="2026-10-05T23:00:00Z",
            required_rest_hours=10)
        assert layover["rest_compliant"] is False
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-05T00:00:00Z",
            "expected_layover_version": layover["version"]}, CREWOPS)
        validate_error(resp, ApiErrorId.ERR_REST_VIOLATION)

    def test_room_block_full_at_exact_capacity_rejects_next_book(self, api):
        """PRD §3.6: "Finally the aggregate occupancy guard: the count of this
        contract's allocations already in `CONFIRMED` with the same `stay_date` must
        be strictly less than the contract's `room_block_size`; a block filled to
        exactly `room_block_size` rejects the next booking with
        `ERR_ROOM_BLOCK_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/room_block_full_at_exact_capacity_rejects_next_book
        """
        station, union, vendor, contract = setup_sourced_station(
            "ELP", station_min_rest=8, transport=25, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=8500, room_block_size=2,
            budget_cap_cents=500000)
        for i, arrival in enumerate(["2026-10-04T18:00:00Z", "2026-10-04T18:30:00Z"]):
            make_confirmed_booking(
                station, contract, stay_date="2026-10-05T00:00:00Z",
                crew_type="FLIGHT_ATTENDANT", crew_count=2,
                arrival=arrival, departure="2026-10-05T09:00:00Z")
        # third book on the same stay_date: CONFIRMED count == block size 2
        layover = make_layover(
            station["id"], crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-04T19:00:00Z", departure="2026-10-05T10:00:00Z")
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-05T00:00:00Z",
            "expected_layover_version": layover["version"]}, CREWOPS)
        validate_error(resp, ApiErrorId.ERR_ROOM_BLOCK_EXHAUSTED)
        data, meta = validate_paginated(api.list_allocations(
            CREWOPS, params={"contract_id": contract["id"], "status": "CONFIRMED",
                             "stay_date": "2026-10-05T00:00:00Z"}))
        assert len(data) == 2

    def test_contract_room_block_aggregate_capacity_overlap(self, api):
        """PRD §3.6: "Finally the aggregate occupancy guard: the count of this
        contract's allocations already in `CONFIRMED` with the same `stay_date` must
        be strictly less than the contract's `room_block_size`; a block filled to
        exactly `room_block_size` rejects the next booking with
        `ERR_ROOM_BLOCK_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/contract_room_block_aggregate_capacity_overlap
        """
        station, union, vendor, contract = setup_sourced_station(
            "TUS", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=8000, room_block_size=1,
            budget_cap_cents=500000)
        make_confirmed_booking(
            station, contract, stay_date="2026-10-06T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-05T18:00:00Z", departure="2026-10-06T09:00:00Z")
        layover = make_layover(
            station["id"], crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-05T19:00:00Z", departure="2026-10-06T10:00:00Z")
        # same stay_date -> exhausted
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-06T00:00:00Z",
            "expected_layover_version": layover["version"]}, CREWOPS)
        validate_error(resp, ApiErrorId.ERR_ROOM_BLOCK_EXHAUSTED)
        # adjacent stay_date -> pool is per-date, so this book succeeds
        fresh = validate_success(api.get_layover_requirement(layover["id"], CREWOPS))
        data = validate_success(api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-07T00:00:00Z",
            "expected_layover_version": fresh["version"]}, CREWOPS),
            expected_status=201)
        assert data["status"] == "HELD"

    def test_room_block_below_capacity_accepts_next_book(self, api):
        """PRD §3.6: "Finally the aggregate occupancy guard: the count of this
        contract's allocations already in `CONFIRMED` with the same `stay_date` must
        be strictly less than the contract's `room_block_size`; a block filled to
        exactly `room_block_size` rejects the next booking with
        `ERR_ROOM_BLOCK_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/room_block_full_at_exact_capacity_rejects_next_book
        """
        station, union, vendor, contract = setup_sourced_station(
            "ELP", station_min_rest=8, transport=25, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=8500, room_block_size=2,
            budget_cap_cents=500000)
        # one CONFIRMED allocation on the stay_date: count 1 < block size 2
        make_confirmed_booking(
            station, contract, stay_date="2026-10-05T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-04T18:00:00Z", departure="2026-10-05T09:00:00Z")
        layover = make_layover(
            station["id"], crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-04T18:30:00Z", departure="2026-10-05T09:30:00Z")
        data = validate_success(api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-05T00:00:00Z",
            "expected_layover_version": layover["version"]}, CREWOPS),
            expected_status=201)
        assert data["status"] == "HELD"

    def test_distressed_book_creates_distressed_allocation_held(self, api):
        """PRD §3.7: "The layover moves `SURGED → CONFIRMED` and a new allocation is
        created of kind `DISTRESSED` in `HELD`, with `vendor_id` recorded,
        `contract_id` null, `rooms_held` equal to the layover's `crew_count`, and
        `nightly_rate_cents` set from the supplied `rate_cents`."

        Design: Difficulty/resource_temporal_overlap/contract_room_block_aggregate_capacity_overlap
        """
        station, union, vendor, contract = setup_sourced_station(
            "TUS", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=8000, room_block_size=1,
            budget_cap_cents=500000)
        layover, _alloc = make_surged_layover(
            station, contract, stay_date="2026-10-06T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-05T18:00:00Z", departure="2026-10-06T09:00:00Z")
        relief = make_vendor(name="Relief Rooms",
                             contact_email="ops@relief.example")
        data = validate_success(api.distressed_book_layover(
            layover["id"], {"vendor_id": relief["id"], "rate_cents": 11000},
            CREWOPS), expected_status=201)
        assert data["kind"] == "DISTRESSED"
        assert data["status"] == "HELD"
        assert data["vendor_id"] == relief["id"]
        assert data["contract_id"] is None
        assert data["rooms_held"] == 2
        assert data["nightly_rate_cents"] == 11000
        fresh = validate_success(api.get_layover_requirement(layover["id"], CREWOPS))
        assert fresh["status"] == "CONFIRMED"


class TestBlackoutHandling:

    def test_blackout_date_book_rejected_without_protection(self, api):
        """PRD §3.6: "Blackout handling next: the `stay_date` must not fall in the
        contract's `blackout_dates` unless the contract's `blackout_protection` is
        true; a blackout-date booking without protection is rejected with
        `ERR_BLACKOUT_DATE` (HTTP 422)."

        Design: Corner/validations/blackout_date_book_rejected_without_protection
        """
        station, union, vendor, contract = setup_sourced_station(
            "SUN", station_min_rest=8, transport=25, union_min_rest=8,
            blackout_dates=["2026-10-15"], blackout_protection=False,
            end_date="2026-10-30T00:00:00Z")
        layover = make_layover(
            station["id"], crew_count=2,
            arrival="2026-10-15T18:00:00Z", departure="2026-10-16T09:00:00Z")
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-15T00:00:00Z",
            "expected_layover_version": layover["version"]}, CREWOPS)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_DATE)
        data, meta = validate_paginated(api.list_allocations(
            CREWOPS, params={"layover_requirement_id": layover["id"]}))
        assert len(data) == 0

    def test_blackout_date_with_protection_uses_override_rate(self, api):
        """PRD §3.6: "When protection is in force and the date is blacked out,
        `blackout_rate_cents` is required and must be at least 0; the honored room
        night is then priced at that override rather than the negotiated rate."

        Design: Corner/validations/blackout_date_with_protection_uses_override_rate
        """
        station, union, vendor, contract = setup_sourced_station(
            "SUN", station_min_rest=8, transport=25, union_min_rest=8,
            blackout_dates=["2026-10-15"], blackout_protection=True,
            end_date="2026-10-30T00:00:00Z")
        layover = make_layover(
            station["id"], crew_count=2,
            arrival="2026-10-15T18:00:00Z", departure="2026-10-16T09:00:00Z")
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-15T00:00:00Z",
            "blackout_rate_cents": 14000,
            "expected_layover_version": layover["version"]}, CREWOPS)
        data = validate_success(resp, expected_status=201)
        assert data["nightly_rate_cents"] == 14000


class TestStaleLayoverVersion:

    def test_book_stale_layover_version_returns_412(self, api):
        """PRD §2.9: "Booking a layover against a contract requires the request to
        carry `expected_layover_version` holding the layover's last observed
        `version`; a mismatch with the layover's current `version` is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/book_stale_layover_version_returns_412
        """
        station, union, vendor, contract = setup_sourced_station(
            "FSD", station_min_rest=8, transport=20, union_min_rest=8)
        layover = make_layover(station["id"], crew_count=2)
        stale_version = layover["version"]
        # first book succeeds and bumps the layover version
        validate_success(api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-02T00:00:00Z",
            "expected_layover_version": stale_version}, CREWOPS), expected_status=201)
        # second book with the stale version is rejected
        resp = api.book_layover(layover["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-03T00:00:00Z",
            "expected_layover_version": stale_version}, CREWOPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data, meta = validate_paginated(api.list_allocations(
            CREWOPS, params={"layover_requirement_id": layover["id"]}))
        assert len(data) == 1


class TestVersionIncrements:

    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.7: "The `version` is a system-managed integer that increments by
        exactly 1 on every mutation, and it is the field that optimistic concurrency
        control reads."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        station, union, vendor, contract = setup_sourced_station(
            "SUX", station_min_rest=8, transport=20, union_min_rest=8)
        layover = make_layover(station["id"], crew_count=2)
        assert layover["version"] == 1
        layover, allocation = book_layover(
            layover, contract["id"], stay_date="2026-10-02T00:00:00Z")
        assert layover["version"] == 2
        data = validate_success(api.cancel_layover(layover["id"], CREWOPS))
        assert data["version"] == 3


class TestPickupTiming:

    def test_pickup_timing_scheduled_directions(self, api):
        """PRD §3.9: "For `AIRPORT_TO_HOTEL`, pickup is the layover's `arrival_time`
        plus the station's `transport_time_minutes` — the van meets the crew off the
        aircraft. For `HOTEL_TO_AIRPORT`, pickup is the layover's `departure_time`
        minus the station's `transport_time_minutes` and minus a further 90-minute
        buffer, so the crew is at the airport with time to spare; times are
        minute-precise with no rounding."
        PRD §3.9: "The trip is created in `SCHEDULED`, and its `contract_id` is
        copied from the layover's `CONFIRMED` contracted allocation at schedule
        time."

        Design: Corner/calculations/pickup_timing_scheduled_directions
        """
        station, union, vendor, contract = setup_sourced_station(
            "BTM", station_min_rest=8, transport=40, union_min_rest=8)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-02T00:00:00Z", crew_count=2,
            arrival="2026-10-02T17:00:00Z", departure="2026-10-03T10:00:00Z")
        a2h = validate_success(api.create_transport_trip(
            layover["id"], {"direction": "AIRPORT_TO_HOTEL", "vehicle_capacity": 6},
            CREWOPS), expected_status=201)
        assert a2h["pickup_time"] == "2026-10-02T17:40:00.000Z"
        assert a2h["contract_id"] == contract["id"]
        h2a = validate_success(api.create_transport_trip(
            layover["id"], {"direction": "HOTEL_TO_AIRPORT", "vehicle_capacity": 6},
            CREWOPS), expected_status=201)
        assert h2a["pickup_time"] == "2026-10-03T07:50:00.000Z"
        assert h2a["contract_id"] == contract["id"]

    def test_transport_pickup_point_collision_same_instant(self, api):
        """PRD §3.9: "Pickup uniqueness is enforced per layover and direction: the
        computed `pickup_time` must not equal the pickup time of any existing
        non-`CANCELLED` trip of the same layover in the same direction, or scheduling
        fails with `ERR_PICKUP_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/transport_pickup_point_collision_same_instant
        """
        station, union, vendor, contract = setup_sourced_station(
            "GEG", station_min_rest=8, transport=30, union_min_rest=8,
            rate_cents=8700)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-03T00:00:00Z", crew_count=3,
            arrival="2026-10-02T18:00:00Z", departure="2026-10-03T09:00:00Z")
        first = validate_success(api.create_transport_trip(
            layover["id"], {"direction": "AIRPORT_TO_HOTEL", "vehicle_capacity": 8},
            CREWOPS), expected_status=201)
        assert first["pickup_time"] == "2026-10-02T18:30:00.000Z"
        # duplicate direction -> identical computed pickup instant -> conflict
        resp = api.create_transport_trip(
            layover["id"], {"direction": "AIRPORT_TO_HOTEL", "vehicle_capacity": 8},
            CREWOPS)
        validate_error(resp, ApiErrorId.ERR_PICKUP_CONFLICT)
        # the other direction computes a different instant and succeeds
        h2a = validate_success(api.create_transport_trip(
            layover["id"], {"direction": "HOTEL_TO_AIRPORT", "vehicle_capacity": 8},
            CREWOPS), expected_status=201)
        assert h2a["pickup_time"] == "2026-10-03T07:00:00.000Z"

    def test_pickup_conflict_is_per_direction(self, api):
        """PRD §3.9: "Pickup uniqueness is enforced per layover and direction: the
        computed `pickup_time` must not equal the pickup time of any existing
        non-`CANCELLED` trip of the same layover in the same direction, or scheduling
        fails with `ERR_PICKUP_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/transport_pickup_point_collision_same_instant
        """
        station, union, vendor, contract = setup_sourced_station(
            "GEG", station_min_rest=8, transport=30, union_min_rest=8,
            rate_cents=8700)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-03T00:00:00Z", crew_count=3,
            arrival="2026-10-02T18:00:00Z", departure="2026-10-03T09:00:00Z")
        # schedule the HOTEL_TO_AIRPORT leg first
        first = validate_success(api.create_transport_trip(
            layover["id"], {"direction": "HOTEL_TO_AIRPORT", "vehicle_capacity": 8},
            CREWOPS), expected_status=201)
        assert first["status"] == "SCHEDULED"
        # duplicate same-direction trip collides on the identical pickup instant
        resp = api.create_transport_trip(
            layover["id"], {"direction": "HOTEL_TO_AIRPORT", "vehicle_capacity": 8},
            CREWOPS)
        validate_error(resp, ApiErrorId.ERR_PICKUP_CONFLICT)


class TestDistressedPricing:

    def test_distressed_cost_tiered_surge_multiplier(self, api):
        """PRD §3.7: "Distressed rooms are priced with a surge multiplier at the
        moment the allocation is confirmed. The system counts the pre-existing
        `DISTRESSED` allocations with the same `stay_date` in `HELD`, `CONFIRMED`, or
        `CHECKED_IN`: when that count is no more than 5 the multiplier is 1.25; when
        it is more than 5 but no more than 10 the multiplier is 1.50; beyond 10 the
        multiplier is 2.00. The allocation's `distressed_cost_cents` is then the
        `nightly_rate_cents` multiplied by `rooms_held` multiplied by the applicable
        multiplier, the final product rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/distressed_cost_tiered_surge_multiplier
        """
        station, union, vendor_h1, contract = setup_sourced_station(
            "ORD", station_min_rest=8, transport=45, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=9000, room_block_size=20,
            budget_cap_cents=5_000_000)
        vendor_h2 = make_vendor(name="O'Hare Suites Inc",
                                contact_email="sales@oharesuites.example")
        # 7 pre-existing CONFIRMED DISTRESSED allocations on 2026-10-02
        for _ in range(7):
            layover, _alloc = make_surged_layover(
                station, contract, stay_date="2026-10-02T00:00:00Z",
                crew_type="FLIGHT_ATTENDANT", crew_count=2,
                arrival="2026-10-01T18:00:00Z", departure="2026-10-02T10:00:00Z")
            make_distressed_confirmed(layover, vendor_h2, rate_cents=9000)
        # the 8th distressed allocation confirms with surge_n == 7 -> tier 1.50
        layover8, _alloc8 = make_surged_layover(
            station, contract, stay_date="2026-10-02T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=8,
            arrival="2026-10-01T18:00:00Z", departure="2026-10-02T10:00:00Z")
        held = validate_success(api.distressed_book_layover(
            layover8["id"], {"vendor_id": vendor_h2["id"], "rate_cents": 12000},
            CREWOPS), expected_status=201)
        data = validate_success(api.confirm_allocation(held["id"], CREWOPS))
        assert data["status"] == "CONFIRMED"
        # 12000 x 8 rooms x 1.50 = 144000
        assert data["distressed_cost_cents"] == 144000

    def test_distressed_cost_tier1_multiplier(self, api):
        """PRD §3.7: "Distressed rooms are priced with a surge multiplier at the
        moment the allocation is confirmed. The system counts the pre-existing
        `DISTRESSED` allocations with the same `stay_date` in `HELD`, `CONFIRMED`, or
        `CHECKED_IN`: when that count is no more than 5 the multiplier is 1.25; when
        it is more than 5 but no more than 10 the multiplier is 1.50; beyond 10 the
        multiplier is 2.00. The allocation's `distressed_cost_cents` is then the
        `nightly_rate_cents` multiplied by `rooms_held` multiplied by the applicable
        multiplier, the final product rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/distressed_cost_tiered_surge_multiplier
        """
        station, union, vendor_h1, contract = setup_sourced_station(
            "ORD", station_min_rest=8, transport=45, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=9000, room_block_size=20,
            budget_cap_cents=5_000_000)
        vendor_h2 = make_vendor(name="O'Hare Suites Inc",
                                contact_email="sales@oharesuites.example")
        # zero pre-existing distressed rows -> tier 1.25
        layover, _alloc = make_surged_layover(
            station, contract, stay_date="2026-10-02T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=8,
            arrival="2026-10-01T18:00:00Z", departure="2026-10-02T10:00:00Z")
        held = validate_success(api.distressed_book_layover(
            layover["id"], {"vendor_id": vendor_h2["id"], "rate_cents": 12000},
            CREWOPS), expected_status=201)
        data = validate_success(api.confirm_allocation(held["id"], CREWOPS))
        # 12000 x 8 x 1.25 = 120000
        assert data["distressed_cost_cents"] == 120000


class TestOccupancyInvariant:

    def test_room_block_occupancy_confirm_noshow_roundtrip(self, api):
        """PRD §3.6: "Finally the aggregate occupancy guard: the count of this
        contract's allocations already in `CONFIRMED` with the same `stay_date` must
        be strictly less than the contract's `room_block_size`; a block filled to
        exactly `room_block_size` rejects the next booking with
        `ERR_ROOM_BLOCK_EXHAUSTED` (HTTP 422)."
        PRD §3.6: "If the crew never arrives, crew operations marks the allocation
        `CONFIRMED → NO_SHOW`, legal only once the logical clock date is strictly
        after the `stay_date`."

        Design: Difficulty/compensating_invariant/room_block_occupancy_confirm_noshow_roundtrip
        """
        station, union, vendor, contract = setup_sourced_station(
            "RNO", station_min_rest=8, transport=25, union_min_rest=8,
            rate_cents=9100, room_block_size=1, budget_cap_cents=500000,
            end_date="2026-10-20T00:00:00Z")
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-08T00:00:00Z", crew_count=2,
            arrival="2026-10-07T18:00:00Z", departure="2026-10-08T09:00:00Z")
        api.set_clock("2026-10-10T00:00:00Z", ADMIN)
        validate_success(api.no_show_allocation(allocation["id"], CREWOPS))
        # occupancy is back to 0: a new book on the same stay_date succeeds
        layover2 = make_layover(
            station["id"], crew_count=2,
            arrival="2026-10-07T19:00:00Z", departure="2026-10-08T10:00:00Z")
        data = validate_success(api.book_layover(layover2["id"], {
            "contract_id": contract["id"], "stay_date": "2026-10-08T00:00:00Z",
            "expected_layover_version": layover2["version"]}, CREWOPS),
            expected_status=201)
        assert data["status"] == "HELD"
        rows, meta = validate_paginated(api.list_allocations(
            CREWOPS, params={"contract_id": contract["id"], "status": "CONFIRMED",
                             "stay_date": "2026-10-08T00:00:00Z"}))
        assert len(rows) == 0

    def test_no_show_before_stay_date_rejected(self, api):
        """PRD §3.6: "If the crew never arrives, crew operations marks the allocation
        `CONFIRMED → NO_SHOW`, legal only once the logical clock date is strictly
        after the `stay_date`."

        Design: Corner/state_machines/no_show_before_stay_date_rejected
        """
        station, union, vendor, contract = setup_sourced_station(
            "JAC", station_min_rest=8, transport=25, union_min_rest=8)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-03T00:00:00Z", crew_count=2,
            arrival="2026-10-02T18:00:00Z", departure="2026-10-03T09:00:00Z")
        # clock on the stay date itself (not strictly after)
        api.set_clock("2026-10-03T12:00:00Z", ADMIN)
        resp = api.no_show_allocation(allocation["id"], CREWOPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = validate_success(api.get_allocation(allocation["id"], CREWOPS))
        assert fresh["status"] == "CONFIRMED"

    def test_no_show_after_stay_date_succeeds(self, api):
        """PRD §3.6: "If the crew never arrives, crew operations marks the allocation
        `CONFIRMED → NO_SHOW`, legal only once the logical clock date is strictly
        after the `stay_date`."

        Design: Difficulty/compensating_invariant/room_block_occupancy_confirm_noshow_roundtrip
        """
        station, union, vendor, contract = setup_sourced_station(
            "RNO", station_min_rest=8, transport=25, union_min_rest=8,
            rate_cents=9100, room_block_size=1, budget_cap_cents=500000,
            end_date="2026-10-20T00:00:00Z")
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-08T00:00:00Z", crew_count=2,
            arrival="2026-10-07T18:00:00Z", departure="2026-10-08T09:00:00Z")
        api.set_clock("2026-10-10T00:00:00Z", ADMIN)
        data = validate_success(api.no_show_allocation(allocation["id"], CREWOPS))
        assert data["status"] == "NO_SHOW"


class TestCheckInCascade:

    def test_checkin_completes_layover_across_entities(self, api):
        """PRD §3.6: "The vendor's representative checks the crew in on the stay date
        or after — check-in moves the allocation `CONFIRMED → CHECKED_IN`, requires
        that the allocation's `stay_date` be on or before the logical clock date (a
        crew cannot check in before the stay date), and cascades the layover
        `CONFIRMED → COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/checkin_completes_layover_across_entities
        """
        station, union, vendor, contract = setup_sourced_station(
            "PIT", station_min_rest=8, transport=30, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=9200)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-01T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=3)
        data = validate_success(api.check_in_allocation(
            allocation["id"], make_vendor_rep_headers(vendor["id"])))
        assert data["status"] == "CHECKED_IN"
        fresh = validate_success(api.get_layover_requirement(layover["id"], CREWOPS))
        assert fresh["status"] == "COMPLETED"

    def test_check_in_requires_stay_date_reached(self, api):
        """PRD §3.6: "The vendor's representative checks the crew in on the stay date
        or after — check-in moves the allocation `CONFIRMED → CHECKED_IN`, requires
        that the allocation's `stay_date` be on or before the logical clock date (a
        crew cannot check in before the stay date), and cascades the layover
        `CONFIRMED → COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/checkin_completes_layover_across_entities
        """
        station, union, vendor, contract = setup_sourced_station(
            "PIT", station_min_rest=8, transport=30, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=9200)
        # stay_date 2026-10-01 is on the logical-clock date (fixtures floor the
        # clock at 2026-10-01): check-in is legal on the stay date itself
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-01T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=3)
        resp = api.check_in_allocation(
            allocation["id"], make_vendor_rep_headers(vendor["id"]))
        validate_success(resp)
        fresh = validate_success(api.get_layover_requirement(layover["id"], CREWOPS))
        assert fresh["status"] == "COMPLETED"

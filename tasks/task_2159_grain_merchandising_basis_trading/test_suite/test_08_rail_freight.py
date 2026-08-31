"""Rail car acquisition: half-open fleet occupancy with its turnaround buffer,
substitution, the stale-fleet guard, and the booking state a load must find
before it can be applied."""

import pytest

from test_helpers import (
    CLEAN_LOAD,
    ApiErrorId,
    assert_freight_booking,
    confirm_booking,
    create_freight_booking_payload,
    new_freight_booking,
    new_rail_fleet,
    new_ticket,
    read_booking,
    read_contract,
    read_fleet,
    read_ticket,
    setup_contract_scenario,
    setup_rail_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


FREIGHT = TEST_USERS["freight_coordinator_headers"]
MERCH = TEST_USERS["merchandiser_headers"]


class TestBookingReferentialGates:

    def test_a_booking_at_a_truck_only_elevator_is_refused(self, api):
        """PRD §3.6: "The contract's elevator must have `rail_served` set true and
        the fleet must be homed at that same elevator, meaning the fleet's
        `home_location_id` equals the contract's `location_id`; either failure is
        `ERR_LOCATION_NOT_RAIL_SERVED`."

        Design: Corner/validations/freight_booking_at_a_non_rail_elevator_returns_location_not_rail_served
        """
        scenario = setup_contract_scenario(
            desk_code="CD33", desk_name="Corner Desk 33", with_schedule=False,
            location_name="Truck Only", rail_served=False, lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )
        fleet = new_rail_fleet(scenario["location"]["id"], fleet_code="FLT-A",
                               car_count=60)

        payload = create_freight_booking_payload(
            fleet["id"], scenario["contract"]["id"], fleet["version"],
            cars_requested=25,
        )
        validate_error(api.create_freight_booking(payload, FREIGHT),
                       ApiErrorId.ERR_LOCATION_NOT_RAIL_SERVED.value, 422)

        _, meta = validate_paginated(api.list_freight_bookings(
            FREIGHT, params={"fleet_id": fleet["id"]}
        ))
        assert meta["total_count"] == 0

    def test_requesting_more_cars_than_the_fleet_holds_is_refused(self, api):
        """PRD §3.6: "And `cars_requested` may not exceed the fleet's `car_count`,
        or `ERR_CARS_EXCEED_FLEET` answers."
        PRD §3.1: "The car count is a hard ceiling: no booking may ever request more
        cars than the set physically contains."

        Design: Corner/validations/freight_booking_over_the_fleet_car_count_returns_cars_exceed_fleet
        """
        scenario = setup_contract_scenario(
            desk_code="CD34", desk_name="Corner Desk 34", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )
        fleet = new_rail_fleet(scenario["location"]["id"], fleet_code="FLT-S",
                               car_count=10)

        payload = create_freight_booking_payload(
            fleet["id"], scenario["contract"]["id"], fleet["version"],
            cars_requested=20,
        )
        validate_error(api.create_freight_booking(payload, FREIGHT),
                       ApiErrorId.ERR_CARS_EXCEED_FLEET.value, 422)

        _, meta = validate_paginated(api.list_freight_bookings(
            FREIGHT, params={"fleet_id": fleet["id"]}
        ))
        assert meta["total_count"] == 0

    def test_a_stale_expected_fleet_version_is_refused_even_when_the_window_is_free(
            self, api):
        """PRD §2.7: "Its request body must carry `expected_fleet_version` —
        likewise required — holding the `version` of the target `RailFleet` as the
        client last observed it. A value that does not equal the fleet's current
        `version` is rejected with `ERR_STALE_FLEET_VERSION` (HTTP 412)."
        PRD §2.7: "Here the guard matters because a non-intersecting booking is
        otherwise accepted on its own merits, so the version check is the only
        signal available that the occupancy picture the client reasoned about is no
        longer current."

        Design: Corner/cross_cutting_layers/freight_booking_create_with_stale_fleet_version_returns_412
        """
        scenario = setup_contract_scenario(
            desk_code="CD52", desk_name="Corner Desk 52", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )
        fleet = new_rail_fleet(scenario["location"]["id"], fleet_code="FLT-A",
                               car_count=60)
        observed_version = fleet["version"]

        first = new_freight_booking(
            fleet["id"], scenario["contract"]["id"], observed_version,
            cars_requested=25, placement_at="2026-11-05T00:00:00Z",
            release_at="2026-11-07T00:00:00Z",
        )

        stale = create_freight_booking_payload(
            fleet["id"], scenario["contract"]["id"], observed_version,
            cars_requested=25, placement_at="2026-11-20T00:00:00Z",
            release_at="2026-11-22T00:00:00Z",
        )
        validate_error(api.create_freight_booking(stale, FREIGHT),
                       ApiErrorId.ERR_STALE_FLEET_VERSION.value, 412)

        _, meta = validate_paginated(api.list_freight_bookings(
            FREIGHT, params={"fleet_id": fleet["id"]}
        ))
        assert meta["total_count"] == 1
        assert read_booking(first["id"])["status"] == "REQUESTED"

    def test_substitution_retargets_the_booking_without_leaving_requested(self, api):
        """PRD §3.6: "Substitution names a `new_fleet_id` and leaves the booking in
        `REQUESTED` — a self-loop rather than a state change."
        PRD §3.6: "On success the booking's `fleet_id` becomes the new fleet,
        `substitution_count` rises by one, and the **new** fleet's `version`
        increments by one."

        Design: Corner/state_machines/freight_booking_substitute_self_loop_increments_substitution_count
        """
        scenario = setup_rail_scenario(
            desk_code="CD16", desk_name="Corner Desk 16", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            fleet_overrides={"fleet_code": "FLT-A", "car_count": 60},
            booking_overrides={"cars_requested": 25,
                               "placement_at": "2026-11-05T00:00:00Z",
                               "release_at": "2026-11-07T00:00:00Z"},
        )
        fleet_a = scenario["fleet"]
        fleet_b = new_rail_fleet(scenario["location"]["id"], fleet_code="FLT-B",
                                 car_count=60)

        moved = validate_success(api.substitute_freight_booking(
            scenario["booking"]["id"], {"new_fleet_id": fleet_b["id"]}, FREIGHT
        ), 200)
        assert_freight_booking(moved)

        assert moved["status"] == "REQUESTED"
        assert moved["fleet_id"] == fleet_b["id"]
        assert moved["substitution_count"] == 1
        assert moved["occupancy_end_at"] == "2026-11-09T00:00:00.000Z"

        _, meta_a = validate_paginated(api.list_freight_bookings(
            FREIGHT, params={"fleet_id": fleet_a["id"]}
        ))
        assert meta_a["total_count"] == 0
        _, meta_b = validate_paginated(api.list_freight_bookings(
            FREIGHT, params={"fleet_id": fleet_b["id"]}
        ))
        assert meta_b["total_count"] == 1


class TestFleetOccupancyInterval:
    """Occupancy runs from placement_at up to but not including
    release_at plus 48 hours."""

    def _occupied_fleet(self):
        scenario = setup_rail_scenario(
            desk_code="GD20", desk_name="Fleet Overlap Desk", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            fleet_overrides={"fleet_code": "FLT-A", "car_count": 60},
            booking_overrides={"cars_requested": 25,
                               "placement_at": "2026-11-05T00:00:00Z",
                               "release_at": "2026-11-07T00:00:00Z"},
        )
        scenario["fleet_version"] = read_fleet(scenario["fleet"]["id"])["version"]
        return scenario

    def test_a_booking_inside_the_turnaround_buffer_is_refused(self, api):
        """PRD §3.6: "The cars are unavailable to anyone else until they have been
        turned around, so the booking's `occupancy_end_at` is computed as
        `release_at` plus a 48-hour turnaround buffer, and the interval the booking
        occupies runs from `placement_at` up to but **not including**
        `occupancy_end_at`."
        PRD §3.6: "Two bookings on the same fleet conflict when their half-open
        intervals intersect; intervals that merely touch — one ending at exactly the
        instant the next begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/rail_fleet_half_open_occupancy_with_turnaround_buffer
        """
        scenario = self._occupied_fleet()
        assert read_booking(scenario["booking"]["id"])[
            "occupancy_end_at"] == "2026-11-09T00:00:00.000Z", (
            "release_at 2026-11-07 plus the 48-hour buffer"
        )

        payload = create_freight_booking_payload(
            scenario["fleet"]["id"], scenario["contract"]["id"],
            scenario["fleet_version"], cars_requested=20,
            placement_at="2026-11-08T23:00:00Z", release_at="2026-11-10T00:00:00Z",
        )
        resp = api.create_freight_booking(payload, FREIGHT)
        validate_error(resp, ApiErrorId.ERR_FLEET_UNAVAILABLE.value, 409)
        assert resp.status_code == 409

    def test_a_booking_starting_at_the_open_upper_endpoint_is_admitted(self, api):
        """PRD §3.6: "Two bookings on the same fleet conflict when their half-open
        intervals intersect; intervals that merely touch — one ending at exactly the
        instant the next begins — do not conflict. Only bookings whose `status` is
        `REQUESTED` or `CONFIRMED` block; completed and cancelled bookings release
        their hold. A conflicting reservation is refused with
        `ERR_FLEET_UNAVAILABLE`."
        PRD §3.6: "The booking is created in `REQUESTED` status with
        `substitution_count` at zero, and the reserving fleet's `version` increments
        by one."

        Design: Difficulty/resource_temporal_overlap/rail_fleet_half_open_occupancy_with_turnaround_buffer
        """
        scenario = self._occupied_fleet()

        payload = create_freight_booking_payload(
            scenario["fleet"]["id"], scenario["contract"]["id"],
            scenario["fleet_version"], cars_requested=20,
            placement_at="2026-11-09T00:00:00Z", release_at="2026-11-11T00:00:00Z",
        )
        booking = validate_success(api.create_freight_booking(payload, FREIGHT), 201)

        assert booking["status"] == "REQUESTED"
        assert booking["substitution_count"] == 0
        assert booking["occupancy_end_at"] == "2026-11-13T00:00:00.000Z", (
            f"release_at 2026-11-11 plus the 48-hour buffer, got "
            f"{booking['occupancy_end_at']}"
        )


class TestApplyRequiresAConfirmedBooking:
    """A load that moved by rail cannot be applied until its booking is
    confirmed, and applying it then completes the booking."""

    def _rail_load(self):
        scenario = setup_rail_scenario(
            desk_code="GD18", desk_name="Rail Gate Desk", lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            fleet_overrides={"fleet_code": "FLT-A", "car_count": 60},
            booking_overrides={"cars_requested": 25,
                               "placement_at": "2026-11-05T00:00:00Z",
                               "release_at": "2026-11-07T00:00:00Z"},
        )
        scenario["ticket"] = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=5000, freight_booking_id=scenario["booking"]["id"],
            **CLEAN_LOAD,
        )
        return scenario

    def test_applying_a_load_on_a_merely_requested_booking_is_refused(self, api):
        """PRD §3.8: "And when the ticket carries a `freight_booking_id`, the
        booking it names must be in `CONFIRMED` status, or
        `ERR_FREIGHT_BOOKING_NOT_CONFIRMED` answers; a booking still merely
        `REQUESTED`, or one already `CANCELLED` or `COMPLETED`, blocks the
        application."

        Design: Difficulty/cross_entity_state_dependency/ticket_apply_gated_by_unconfirmed_freight_booking
        """
        scenario = self._rail_load()

        resp = api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH)
        validate_error(resp, ApiErrorId.ERR_FREIGHT_BOOKING_NOT_CONFIRMED.value, 409)
        assert resp.status_code == 409

        assert read_ticket(scenario["ticket"]["id"])["status"] == "GRADED"
        assert read_contract(scenario["contract"]["id"])[
            "delivered_bushels"] == pytest.approx(0.00, abs=0.01)
        assert read_booking(scenario["booking"]["id"])[
            "occupancy_end_at"] == "2026-11-09T00:00:00.000Z"

    def test_confirming_the_booking_unblocks_the_apply_and_completes_it(self, api):
        """PRD §3.6: "Confirming a booking moves it `REQUESTED → CONFIRMED`, and
        that is the state a booking must be in before any delivery ticket carrying
        its id may be applied."
        PRD §3.6: "The remaining transition is never requested directly: a
        `CONFIRMED` booking moves to `COMPLETED` automatically at the moment a
        delivery ticket carrying its id is applied to a contract, which likewise
        frees the occupancy interval."

        Design: Difficulty/cross_entity_state_dependency/ticket_apply_gated_by_unconfirmed_freight_booking
        """
        scenario = self._rail_load()
        validate_error(api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH),
                       ApiErrorId.ERR_FREIGHT_BOOKING_NOT_CONFIRMED.value, 409)

        confirmed = confirm_booking(scenario["booking"]["id"])
        assert confirmed["status"] == "CONFIRMED"

        applied = validate_success(
            api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH), 200
        )
        assert applied["status"] == "APPLIED"
        assert read_contract(scenario["contract"]["id"])[
            "delivered_bushels"] == pytest.approx(5000.00, abs=0.01)
        assert read_booking(scenario["booking"]["id"])["status"] == "COMPLETED"

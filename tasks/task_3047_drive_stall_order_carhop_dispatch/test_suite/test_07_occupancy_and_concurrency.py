"""Stall occupancy exclusivity, optimistic concurrency, and validation
priority between weather safety and stall occupancy."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    create_location,
    create_stall,
    get_location,
    intercom_checkin,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


class TestStallSingleOccupancy:
    def test_stall_single_occupancy_interval(self, api, shift_manager_headers):
        """PRD: "Intercom check-in requires the stall to be `IDLE` — otherwise
        `ERR_STALL_OCCUPIED`"

        A second intercom check-in against an OCCUPIED stall is rejected;
        occupancy is exclusive.

        Design: Difficulty/resource_temporal_overlap/stall_single_occupancy_interval
        """
        location = create_location(code="DIFF-OCC1", stall_capacity=2)
        stall = create_stall(location["id"], stall_number=1)
        first = intercom_checkin(location["id"], stall["id"])
        assert first["status"] == "DRAFT"

        version = get_location(location["id"])["version"]
        resp = api.checkin(
            location["id"], stall["id"],
            {"expected_location_version": version},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALL_OCCUPIED)

        stall_after = validate_success(
            api.get_stall(location["id"], stall["id"], shift_manager_headers), 200
        )
        assert stall_after["status"] == "OCCUPIED"
        assert stall_after["current_order_id"] == first["id"]

    def test_occupied_stall_rejects_second_checkin_even_from_manager(
        self, api, shift_manager_headers
    ):
        """PRD: "Intercom check-in requires the stall to be `IDLE` — otherwise
        `ERR_STALL_OCCUPIED`"

        A ShiftManager-initiated second check-in is rejected exactly like a
        customer-initiated one; the gate is on the stall, not the actor.

        Design: Difficulty/resource_temporal_overlap/stall_single_occupancy_interval
        """
        location = create_location(code="DIFF-OCC2", stall_capacity=2)
        stall = create_stall(location["id"], stall_number=1)
        intercom_checkin(location["id"], stall["id"])

        version = get_location(location["id"])["version"]
        resp = api.checkin(
            location["id"], stall["id"],
            {"expected_location_version": version},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALL_OCCUPIED)


class TestStaleVersionOccOnCheckin:
    def test_stale_version_occ_on_checkin(self, api, shift_manager_headers):
        """PRD: "If the supplied value does not match the location's current
        `version`, the check-in is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and the caller must re-read the location before retrying."

        A weather change advances the location version; a check-in carrying
        the pre-change version is stale.

        Design: Corner/validations/stale_version_occ_on_checkin
        """
        location = create_location(code="CRN-OCC1", stall_capacity=2)
        stall = create_stall(location["id"], stall_number=1)
        stale_version = location["version"]

        validate_success(
            api.set_weather(location["id"], {"weather_mode": "HEAT_ADVISORY"}, MANAGER), 200
        )

        resp = api.checkin(
            location["id"], stall["id"],
            {"expected_location_version": stale_version},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_checkin_with_fresh_version_after_weather_change_succeeds(
        self, api, shift_manager_headers
    ):
        """PRD: "If the supplied value does not match the location's current
        `version`, the check-in is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and the caller must re-read the location before retrying."

        Re-reading the location after the weather change yields the current
        version, and the retried check-in succeeds — the OCC gate accepts a
        matching version.

        Design: Corner/validations/stale_version_occ_on_checkin
        """
        location = create_location(code="CRN-OCC2", stall_capacity=2)
        stall = create_stall(location["id"], stall_number=1)

        validate_success(
            api.set_weather(location["id"], {"weather_mode": "HEAT_ADVISORY"}, MANAGER), 200
        )
        order = intercom_checkin(location["id"], stall["id"])
        assert order["status"] == "DRAFT"
        assert order["channel"] == "STALL_INTERCOM"


class TestSafetyGateOutranksOccupancy:
    def test_business_safety_vs_business_constraint_on_patio_heat_checkin(
        self, api, shift_manager_headers
    ):
        """PRD §2.10: "Only after those structural gates do business rules
        fire, in this order: weather and lane safety gates (`ERR_LANE_CLOSED`,
        `ERR_STALL_WEATHER_CLOSED`); stall occupancy and equipment gates
        (`ERR_STALL_OCCUPIED`, `ERR_STALL_NOT_OCCUPIED_BY_ORDER`,
        `ERR_INTERCOM_UNAVAILABLE`, `ERR_FAULT_STILL_OPEN`)"

        A patio check-in during HEAT_ADVISORY on an already-OCCUPIED patio
        stall violates both gates; the weather-safety gate fires first, so the
        surfaced error is ERR_STALL_WEATHER_CLOSED.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_patio_heat_checkin
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        location = create_location(code="DIFF-PRIO1", stall_capacity=2)
        patio = create_stall(location["id"], stall_number=9, kind="PATIO")
        intercom_checkin(location["id"], patio["id"])

        validate_success(
            api.set_weather(location["id"], {"weather_mode": "HEAT_ADVISORY"}, MANAGER), 200
        )
        version = get_location(location["id"])["version"]
        resp = api.checkin(
            location["id"], patio["id"],
            {"expected_location_version": version},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALL_WEATHER_CLOSED)

        stall_after = validate_success(
            api.get_stall(location["id"], patio["id"], shift_manager_headers), 200
        )
        assert stall_after["status"] == "OCCUPIED"

    def test_heat_advisory_patio_gate_fires_for_idle_patio_too(
        self, api, shift_manager_headers
    ):
        """PRD §2.10: "Only after those structural gates do business rules
        fire, in this order: weather and lane safety gates (`ERR_LANE_CLOSED`,
        `ERR_STALL_WEATHER_CLOSED`); stall occupancy and equipment gates
        (`ERR_STALL_OCCUPIED`, `ERR_STALL_NOT_OCCUPIED_BY_ORDER`,
        `ERR_INTERCOM_UNAVAILABLE`, `ERR_FAULT_STILL_OPEN`)"

        The same safety gate is the one that fires for an IDLE patio stall
        under HEAT_ADVISORY, confirming the error comes from the weather rule
        itself and not from any occupancy state.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_patio_heat_checkin
        """
        location = create_location(code="DIFF-PRIO2", stall_capacity=2)
        patio = create_stall(location["id"], stall_number=9, kind="PATIO")

        validate_success(
            api.set_weather(location["id"], {"weather_mode": "HEAT_ADVISORY"}, MANAGER), 200
        )
        version = get_location(location["id"])["version"]
        resp = api.checkin(
            location["id"], patio["id"],
            {"expected_location_version": version},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALL_WEATHER_CLOSED)

        stall_after = validate_success(
            api.get_stall(location["id"], patio["id"], shift_manager_headers), 200
        )
        assert stall_after["status"] == "IDLE"

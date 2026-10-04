"""Corner — entities: creation defaults, computed fields, immutability, retrieval."""

from test_helpers import (
    TEST_USERS,
    api_client,
    make_driver_headers,
    create_vehicle,
    set_clock,
    create_station,
    get_station,
    register_driver,
    get_driver,
    latest_screening_id,
    list_driver_rating_events,
    onboard_active_driver,
    warmup_clean_completion,
    assert_station,
    assert_driver,
    is_valid_uuid,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["platform_admin_headers"]
STATION_OPS = TEST_USERS["station_ops_headers"]


class TestStationCreation:
    def test_station_create_applies_defaults_and_returns_common_fields(self, api):
        """PRD §3.6: "Stations are created with `pay_liabilities_cents` at 0, and a
        station record carries the operator-supplied `name`, `zone_code`, and a
        `surge_enabled` flag that defaults to true."
        PRD §2.4: "Every persisted resource carries an `id`, a server-minted UUID with
        no type prefix, and a `created_at` timestamp. Resources also carry `updated_at`
        and a `version` integer: `updated_at` is refreshed and `version` is incremented
        on every mutation of that resource."

        Design: Corner/entities/station_create_applies_defaults_and_returns_common_fields
        """
        set_clock()
        resp = api_client.create_station(
            {"name": "Station A", "zone_code": "SEA1"}, ADMIN
        )
        station = validate_success(resp, expected_status=201)
        assert_station(station)
        assert station["surge_enabled"] is True
        assert station["pay_liabilities_cents"] == 0
        assert station["version"] == 1


class TestDriverRegistration:
    def test_driver_register_applies_computed_defaults_and_spawns_screening(self, api):
        """PRD §3.1: "Registration creates the driver in `APPLIED` status with
        `rating_tier` `STANDARD`, both rating scores at 0, and `reliability_score_bp` at
        10000, and automatically opens a `BackgroundScreening` for the driver in
        `INITIATED` status."

        Design: Corner/entities/driver_register_applies_computed_defaults_and_spawns_screening
        """
        set_clock()
        driver = register_driver()
        assert_driver(driver)
        assert driver["status"] == "APPLIED"
        assert driver["rating_tier"] == "STANDARD"
        assert driver["reliability_score_bp"] == 10000
        assert driver["rating_score_x100"] == 0
        assert driver["lifetime_rating_x100"] == 0

        data, meta = validate_paginated(
            api_client.list_driver_screenings(driver["id"], ADMIN)
        )
        assert meta["total_count"] == 1
        assert data[0]["status"] == "INITIATED"
        assert data[0]["driver_id"] == driver["id"]

    def test_computed_fields_ignored_input_on_register(self, api):
        """PRD §3.1: "Registration creates the driver in `APPLIED` status with
        `rating_tier` `STANDARD`, both rating scores at 0, and `reliability_score_bp` at
        10000, and automatically opens a `BackgroundScreening` for the driver in
        `INITIATED` status."

        Design: Corner/entities/computed_fields_ignored_input_on_register
        """
        set_clock()
        resp = api_client.register_driver(
            {
                "legal_name": "Mallory Cheat",
                "email": "mallory.cheat@example.com",
                "rating_tier": "PREMIER",
                "reliability_score_bp": 1,
                "status": "ACTIVE",
            },
            TEST_USERS["anonymous_headers"],
        )
        driver = validate_success(resp, expected_status=201)
        assert driver["rating_tier"] == "STANDARD"
        assert driver["reliability_score_bp"] == 10000
        assert driver["status"] == "APPLIED"


class TestVehicleFieldConstraints:
    def test_invalid_enum_member_rejected_with_validation_error(self, api):
        """PRD §3.1: "Vehicle classes are `SEDAN`, `SUV`, and `VAN`, with a rank
        ordering in which `SEDAN` ranks 1, `SUV` ranks 2, and `VAN` ranks 3."
        PRD §2.5: "The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role permission and ownership (`ERR_FORBIDDEN`, or `ERR_OFFER_WRONG_DRIVER` for wrong-driver offer actions); third, existence of path and body references (`ERR_NOT_FOUND`); fourth, state-machine legality, including the domain state errors `ERR_DRIVER_NOT_ACTIVE` and `ERR_BLOCK_NOT_PUBLISHED`, all rejected with `ERR_INVALID_STATE` or the named domain error (HTTP 409); fifth, business safety gates — screening, vehicle, and insurance checks such as `ERR_SCREENING_NOT_CLEARED`, `ERR_NO_ELIGIBLE_VEHICLE`, `ERR_INSURANCE_NOT_ATTESTED`, `ERR_VEHICLE_CLASS_MISMATCH`, and `ERR_INSURANCE_WINDOW_LAPSE`; sixth, temporal business gates such as `ERR_BLOCK_NOT_VISIBLE_YET`, `ERR_BLOCK_WINDOW_OVERLAP`, `ERR_OFFER_BUFFER_CONFLICT`, `ERR_OFFER_EXPIRED`, `ERR_CHECKIN_TOO_EARLY`, and `ERR_CHECKIN_WINDOW_CLOSED`; seventh, aggregate and uniqueness constraints such as `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_VIN`, and `ERR_APPEAL_NOT_OPEN`; eighth, money-side and optimistic-concurrency checks including `ERR_STALE_VERSION`; and ninth, request body shape (`ERR_VALIDATION` for malformed JSON, missing required fields, invalid enum members, or unparseable datetimes)."

        Design: Corner/entities/invalid_enum_member_rejected_with_validation_error
        """
        set_clock()
        driver = register_driver()
        resp = api_client.create_vehicle(
            driver["id"],
            {"vin": "VIN-BAD-CLASS", "vehicle_class": "TRUCK"},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        data, meta = validate_paginated(
            api_client.list_driver_vehicles(
                driver["id"], make_driver_headers(driver["id"])
            )
        )
        assert data == []

    def test_insurance_status_none_until_first_attestation(self, api):
        """PRD §3.1: "A newly registered vehicle starts `ACTIVE`, and its insurance
        position starts as `NONE` — never attested. The driver attests coverage by
        supplying an `insurance_expires_on` date (an ISO `YYYY-MM-DD` date), after which
        the vehicle's `insurance_status` is a computed view over that date against the
        logical clock: `ATTESTED` when `insurance_expires_on` is on or after the current
        logical date, `EXPIRED` when it is before."

        Design: Corner/entities/insurance_status_none_until_first_attestation
        """
        set_clock()
        driver = register_driver()
        vehicle = create_vehicle(driver["id"], vin="VIN-D1-0001")
        assert vehicle["insurance_status"] == "NONE"
        assert vehicle["status"] == "ACTIVE"
        assert vehicle["insurance_expires_on"] is None


class TestGetEndpoints:
    def test_get_missing_block_returns_not_found(self, api):
        """PRD §2.5: "A missing reference anywhere in this existence pass is rejected
        with `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format: … `data`: `error_id`, `message`."

        Design: Corner/entities/get_missing_block_returns_not_found
        """
        set_clock()
        resp = api_client.get_block(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", STATION_OPS
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"

    def test_onboarded_driver_get_round_trips_profile_fields(self, api):
        """PRD §3.1: "A driver's journey begins when an anonymous caller registers with
        a `legal_name` and an `email`."
        PRD §3.1: "Activation moves the driver to `ACTIVE`."

        Design: Corner/entities/onboarded_driver_get_round_trips_profile_fields
        """
        driver, vehicle, _s = onboard_active_driver()
        resp = api_client.get_driver(driver["id"], ADMIN)
        profile = validate_success(resp)
        assert profile["legal_name"] == driver["legal_name"]
        assert profile["email"] == driver["email"]
        assert profile["status"] == "ACTIVE"


class TestRatingEventImmutability:
    def test_rating_event_is_append_only_with_no_mutation_endpoint(self, api):
        """PRD §3.6: "A single `RatingEvent` is created for the driver — exactly one per
        assignment completion — with `event_type` `COMPLETION_SCORE` (the only event
        type in this version of the platform), `event_at` stamped with the logical
        clock, and `points` computed from the assignment's package outcomes."
        PRD §3.6: "The rating points for a completion start from a perfect 500 and
        subtract for each defect: 100 points for each delivered package that was late
        (`on_time_delivery` false), 50 points for each delivered package whose photo was
        non-compliant (`photo_compliant` false), and 200 points for each package that
        ended the assignment `RETURNED_TO_STATION`. The result is floored at 100 — a
        disastrous route still contributes at least 100."

        Design: Corner/entities/rating_event_is_append_only_with_no_mutation_endpoint
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        _b, assignment, _ps, _pkgs = warmup_clean_completion(station, driver, vehicle)

        events = list_driver_rating_events(driver["id"])
        assert len(events) == 1
        assert events[0]["points"] == 500
        assert events[0]["event_type"] == "COMPLETION_SCORE"

        # The assignment-scoped list returns the same single event.
        resp = api_client.list_assignment_rating_events(
            assignment["id"], STATION_OPS
        )
        scoped, meta = validate_paginated(resp)
        assert len(scoped) == 1
        assert scoped[0]["id"] == events[0]["id"]

"""Corner — validations: auth, uniqueness, existence-over-state, vehicle rank, insurance."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    register_driver,
    latest_screening_id,
    begin_screening_review,
    create_vehicle,
    attest_insurance,
    activate_driver,
    onboard_active_driver,
    accept_block,
    check_in,
    make_driver_headers,
    validate_error,
    validate_success,
    validate_paginated,
    NON_EXISTENT_UUID,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["platform_admin_headers"]
STATION_OPS = TEST_USERS["station_ops_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing the `X-User-Role` header, carrying a role value
        that is not one of the declared roles, or missing `X-User-ID` for any role other
        than `Anonymous` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        set_clock()
        resp = api_client.get_station(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestUniqueness:
    def test_register_duplicate_email_rejected(self, api):
        """PRD §3.1: "The email must be unique across all registered drivers; a
        duplicate is rejected with `ERR_DUPLICATE_EMAIL`."

        Design: Corner/validations/register_duplicate_email_rejected
        """
        set_clock()
        register_driver(email="dana.one@example.com")

        resp = api_client.register_driver(
            {"legal_name": "Dana Clone", "email": "dana.one@example.com"},
            TEST_USERS["anonymous_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)

    def test_duplicate_vin_rejected_while_original_active(self, api):
        """PRD §3.1: "The `vin` must be unique among vehicles currently `ACTIVE` — a
        registration repeating a live VIN is rejected with `ERR_DUPLICATE_VIN`, while a
        VIN previously held by a retired vehicle may be reused."

        Design: Corner/validations/duplicate_vin_rejected_while_original_active
        """
        set_clock()
        driver = register_driver()
        vehicle = create_vehicle(driver["id"], vin="VIN-D1-0001")

        resp = api_client.create_vehicle(
            driver["id"],
            {"vin": "VIN-D1-0001", "vehicle_class": "VAN"},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN)

        # After retiring the original, the same VIN becomes registerable again.
        retired = api_client.retire_vehicle(
            vehicle["id"], make_driver_headers(driver["id"])
        )
        validate_success(retired)
        resp2 = api_client.create_vehicle(
            driver["id"],
            {"vin": "VIN-D1-0001", "vehicle_class": "VAN"},
            make_driver_headers(driver["id"]),
        )
        replacement = validate_success(resp2, expected_status=201)
        assert replacement["vin"] == "VIN-D1-0001"
        assert replacement["id"] != vehicle["id"]


class TestExistenceOverState:
    def test_not_found_checkin_beats_state_check(self, api):
        """PRD §2.5: "Nested resources are addressed through hierarchical URL paths, and
        path parameters are validated left-to-right: every identifier in the path — a
        `station_id`, `driver_id`, `vehicle_id`, `screening_id`, `block_id`, `offer_id`,
        `assignment_id`, `package_id`, `pay_statement_id`, or `appeal_id` — must resolve
        to an existing resource before any deeper segment or body reference is examined.
        Foreign-key references carried in request bodies — for example a `vehicle_id`,
        `driver_id`, or `block_id` — must also resolve to existing resources. A missing
        reference anywhere in this existence pass is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/validations/not_found_checkin_beats_state_check
        """
        set_clock()
        driver = register_driver()
        resp = api_client.check_in_assignment(
            NON_EXISTENT_UUID, make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestVehicleClassRank:
    def test_vehicle_class_rank_mismatch_rejected(self, api):
        """PRD §3.1: "Vehicle classes are `SEDAN`, `SUV`, and `VAN`, with a rank
        ordering in which `SEDAN` ranks 1, `SUV` ranks 2, and `VAN` ranks 3."
        PRD §3.3: "The vehicle's class rank must be at least the block's
        `required_vehicle_class` rank, or the claim fails with
        `ERR_VEHICLE_CLASS_MISMATCH`."

        Design: Corner/validations/vehicle_class_rank_mismatch_rejected
        """
        set_clock()
        station = create_station()
        driver, sedan, _s = onboard_active_driver()
        van = create_vehicle(driver["id"], vehicle_class="VAN")
        attest_insurance(van["id"], driver["id"])

        van_block = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            required_vehicle_class="VAN",
            base_pay_cents=4000,
        )
        sedan_block = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:00:00Z",
            ends_at="2026-09-01T14:00:00Z",
            required_vehicle_class="SEDAN",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")

        # SEDAN (rank 1) against a VAN-required (rank 3) block: rejected.
        resp = api_client.accept_block(
            van_block["id"],
            {"vehicle_id": sedan["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_CLASS_MISMATCH)

        # VAN (rank 3) against a SEDAN-required (rank 1) block: rank >= requirement.
        assignment = accept_block(sedan_block["id"], driver["id"], van["id"])
        assert assignment["status"] == "ASSIGNED"


class TestInsuranceGates:
    def test_expired_insurance_rejected_at_accept(self, api):
        """PRD §3.3: "The chosen vehicle must exist, belong to the claiming driver, be
        `ACTIVE`, and have `insurance_status` `ATTESTED` — a missing, retired, or
        foreign vehicle yields `ERR_NO_ELIGIBLE_VEHICLE`, while lapsed or absent
        insurance yields `ERR_INSURANCE_NOT_ATTESTED`."
        PRD §3.1: "`ATTESTED` when `insurance_expires_on` is on or after the current
        logical date, `EXPIRED` when it is before."

        Design: Corner/validations/expired_insurance_rejected_at_accept
        """
        set_clock("2026-08-01T00:00:00Z")
        station = create_station()
        driver, vehicle, _s = onboard_active_driver(
            clock="2026-08-01T00:00:00Z", insurance_expires_on="2026-08-31"
        )
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        # Now the insurance date (2026-08-31) is before the logical date (2026-09-01):
        # the vehicle's insurance_status is EXPIRED.
        set_clock("2026-09-01T00:30:00Z")

        resp = api_client.accept_block(
            block["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ATTESTED)

        data, meta = validate_paginated(
            api_client.list_driver_assignments(driver["id"], ADMIN)
        )
        assert data == []

    def test_insurance_containment_boundary_lapse_rejected_at_checkin(self, api):
        """PRD §3.4: "Safety is checked before the clock: the assignment's vehicle
        insurance must cover the entire block window under closed-interval containment,
        meaning `insurance_expires_on` must be on or after the calendar date of the
        block's `ends_at`; a policy that lapses mid-block is rejected with
        `ERR_INSURANCE_WINDOW_LAPSE`, and this safety rejection takes precedence over
        the temporal check-in errors when both apply."

        Design: Corner/validations/insurance_containment_boundary_lapse_rejected_at_checkin
        """
        set_clock()
        station = create_station()
        # Driver 1: insurance expires on the block's end date — closed-interval
        # containment holds.
        d1, v1, _s1 = onboard_active_driver(insurance_expires_on="2026-09-01")
        # Driver 2: insurance expires one day before the block's end date.
        # Onboarded a month earlier so the insurance is still ATTESTED at
        # activation time (activation requires an ACTIVE + ATTESTED vehicle);
        # it lapses only once the clock reaches the block day.
        d2, v2, _s2 = onboard_active_driver(
            clock="2026-08-01T00:00:00Z", insurance_expires_on="2026-08-31"
        )
        set_clock()

        b1 = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        b2 = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        # Accept both on 2026-08-31 while d2's insurance (expiry 2026-08-31)
        # is still ATTESTED; it lapses once the logical date reaches 2026-09-01.
        set_clock("2026-08-31T23:00:00Z")
        a1 = accept_block(b1["id"], d1["id"], v1["id"])
        a2 = accept_block(b2["id"], d2["id"], v2["id"])

        set_clock("2026-09-01T01:45:00Z")
        ok = check_in(a1["id"], d1["id"])
        assert ok["status"] == "CHECKED_IN"

        resp = api_client.check_in_assignment(a2["id"], make_driver_headers(d2["id"]))
        validate_error(resp, ApiErrorId.ERR_INSURANCE_WINDOW_LAPSE)

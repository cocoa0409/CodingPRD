"""Baseline surface: creation, retrieval, validation, auth, duplicates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_account_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_account_scenario,
    create_tier,
    create_zone,
    create_account,
    create_vehicle,
    create_trial_subscription,
    create_crash_event,
    create_diagnostic_report,
    assert_plan_tier,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["advisor_headers"]
INGESTION = TEST_USERS["system_ingestion_headers"]


class TestPlanTierCreation:
    def test_plan_tier_create_returns_system_fields_and_active_status(self, api):
        """PRD §3.1: Newly created tiers arrive in ACTIVE status
        PRD §2.4: version (integer): a system-managed integer that starts at 1
        on creation and increments by exactly 1 on every mutation.

        Design: Corner/entities/plan_tier_create_returns_system_fields_and_active_status
        """
        resp = api.create_plan_tier(
            {
                "code": "PREMIUM",
                "monthly_fee_cents": 6000,
                "allows_emergency": True,
                "allows_remote_commands": True,
                "allows_navigation": True,
                "allows_data_gb": 10.0,
            },
            ADMIN,
        )
        tier = validate_success(resp, 201)
        assert_plan_tier(tier)
        assert tier["status"] == "ACTIVE"
        assert tier["version"] == 1
        assert tier["code"] == "PREMIUM"
        assert tier["monthly_fee_cents"] == 6000


class TestCrashEventRetrieval:
    def test_crash_event_get_round_trips_computed_severity_fields(self, api):
        """PRD §3.3: The server resolves the vehicle's subscription and
        snapshots it into the event's subscription_id.

        Design: Corner/entities/crash_event_get_round_trips_computed_severity_fields
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        created = create_crash_event(
            vehicle, delta_v_kph=58.334, rollover_detected=False,
            airbag_deployed=False,
        )
        resp = api.get_crash_event(vehicle["id"], created["id"], ADVISOR)
        fetched = validate_success(resp)
        assert fetched["severity_score"] == pytest.approx(35.0, abs=0.01)
        assert fetched["severity_band"] == "MODERATE"
        assert fetched["subscription_id"] == sub["id"]
        assert fetched["status"] == "RECEIVED"
        assert fetched["rollover_detected"] is False
        assert fetched["airbag_deployed"] is False


class TestVehicleBaselines:
    def test_vehicle_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: The first identifier that fails existence or parentage
        produces an ERR_NOT_FOUND (HTTP 404)

        Design: Corner/entities/vehicle_get_with_unknown_id_returns_not_found
        """
        resp = api.get_vehicle(
            "00000000-0000-4000-8000-0000000000ff", ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_vehicle_create_missing_vin_returns_invalid_request(self, api):
        """PRD §2.8: (4) request-body well-formedness — required fields
        present, enum values valid, types correct — else ERR_INVALID_REQUEST
        PRD §3.1: A vehicle is registered by its owning account with a vin

        Design: Corner/entities/vehicle_create_missing_vin_returns_invalid_request
        """
        create_zone(region_code="TX")
        account = create_account()
        resp = api.create_vehicle(
            account["id"],
            {"make": "Chevrolet", "model": "Malibu", "model_year": 2020,
             "region_code": "TX", "hardware_generation": 5},
            make_account_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(
            api.list_account_vehicles(account["id"], make_account_headers(account["id"]))
        )
        assert meta["total_count"] == 0

    def test_crash_event_create_omitting_flags_defaults_false(self, api):
        """PRD §3.3: a rollover_detected flag, an airbag_deployed flag (both
        flags default to false if not supplied)

        Design: Corner/entities/crash_event_create_omitting_rollover_flag_defaults_false
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        resp = api.create_crash_event(
            vehicle["id"],
            {"delta_v_kph": 75, "location_region_code": "TX"},
            INGESTION,
        )
        event = validate_success(resp, 201)
        assert event["rollover_detected"] is False
        assert event["airbag_deployed"] is False
        assert event["severity_score"] == pytest.approx(45.0, abs=0.01)

    def test_vehicle_vin_length_and_excluded_letters_enforced(self, api):
        """PRD §3.1: a vin (exactly 17 characters, uppercase alphanumeric
        excluding the letters I, O, and Q; unique across the platform, with
        duplicates rejected as ERR_DUPLICATE)
        PRD §2.8: (4) request-body well-formedness — required fields present,
        enum values valid, types correct — else ERR_INVALID_REQUEST

        Design: Corner/entities/vehicle_vin_seventeen_chars_and_excluded_letters_enforced
        """
        create_zone(region_code="TX")
        account = create_account()
        headers = make_account_headers(account["id"])
        base = {"make": "Chevrolet", "model": "Malibu", "model_year": 2020,
                "region_code": "TX", "hardware_generation": 5}
        resp_short = api.create_vehicle(
            account["id"], {**base, "vin": "1G1ZD5ST5JF00001"}, headers,
        )
        validate_error(resp_short, ApiErrorId.ERR_INVALID_REQUEST)
        resp_excl = api.create_vehicle(
            account["id"], {**base, "vin": "1G1ZD5ST5JF0000I1"}, headers,
        )
        validate_error(resp_excl, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(
            api.list_account_vehicles(account["id"], headers)
        )
        assert meta["total_count"] == 0

    def test_vehicle_create_requires_existing_account_parent(self, api):
        """PRD §2.5: For any endpoint whose path contains multiple resource
        identifiers, the server validates identifiers in a strict left-to-right
        order: each identifier must exist, and each child must belong to the
        parent declared to its left.

        Design: Corner/entities/vehicle_create_requires_existing_account_parent
        """
        missing = "00000000-0000-4000-8000-0000000000ee"
        resp = api.create_vehicle(
            missing,
            {"vin": "1G1ZD5ST5JF000001", "make": "Chevrolet", "model": "Malibu",
             "model_year": 2020, "region_code": "TX", "hardware_generation": 5},
            make_account_headers(missing),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestValidationAndErrors:
    def test_existence_checked_before_state_on_subscription_action(self, api):
        """PRD §2.8: (3) path existence and parentage, validated left-to-right,
        else ERR_NOT_FOUND
        PRD §2.8: Later rules are consulted only after all earlier rules pass.

        Design: Corner/validations/existence_checked_before_state_on_subscription_action
        """
        account = create_account()
        resp = api.cancel_subscription(
            account["id"], "00000000-0000-4000-8000-0000000000aa",
            make_account_headers(account["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] != "ERR_INVALID_STATE"

    def test_duplicate_account_email_rejected(self, api):
        """PRD §3.1: a unique email (uniqueness enforced across accounts, with
        duplicates rejected as ERR_DUPLICATE)

        Design: Corner/errors/duplicate_account_email_rejected
        """
        create_account(full_name="Ana Alvarez", email="ana@example.com",
                       phone="+15125550101")
        resp = api.create_account(
            {"full_name": "Ana Clone", "email": "ana@example.com",
             "phone": "+15125550199", "home_region_code": "TX"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_odometer_regression_on_second_report_rejected(self, api):
        """PRD §3.6: The odometer is monotonically non-decreasing per vehicle:
        a report whose odometer_km is lower than the vehicle's latest existing
        report is rejected with ERR_ODOMETER_REGRESSION.

        Design: Corner/errors/odometer_regression_on_second_report_rejected
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        create_diagnostic_report(
            vehicle, odometer_km=10000, engine_hours=400,
            dtc_codes=[], oil_life_pct=90,
        )
        resp = api.create_diagnostic_report(
            vehicle["id"],
            {"odometer_km": 9999, "engine_hours": 401,
             "dtc_codes": [], "oil_life_pct": 89},
            INGESTION,
        )
        validate_error(resp, ApiErrorId.ERR_ODOMETER_REGRESSION)
        _, meta = validate_paginated(
            api.list_vehicle_diagnostic_reports(vehicle["id"], ADMIN)
        )
        assert meta["total_count"] == 1


class TestAuth:
    def test_account_cannot_create_plan_tier(self, api):
        """PRD §2.1: Any attempt to invoke an operation outside the caller's
        role — or, for an entity-backed role, to act on a resource owned by
        another principal — is rejected with ERR_UNAUTHORIZED (HTTP 403).

        Design: Corner/roles/account_cannot_create_plan_tier
        """
        account = create_account()
        resp = api.create_plan_tier(
            {"code": "PREMIUM", "monthly_fee_cents": 6000,
             "allows_emergency": True, "allows_remote_commands": True,
             "allows_navigation": True, "allows_data_gb": 10.0},
            make_account_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        _, meta = validate_paginated(api.list_plan_tiers(ADMIN))
        assert meta["total_count"] == 0

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: A request missing either header, or carrying a role value
        the server does not recognize, is rejected with ERR_UNAUTHENTICATED
        (HTTP 401).
        PRD §2.8: The order is: (1) authentication — auth headers present and
        the role recognized, else ERR_UNAUTHENTICATED; (2) authorization

        Design: Corner/roles/missing_auth_headers_unauthenticated
        """
        resp = api._request(
            "GET", "/accounts/00000000-0000-4000-8000-0000000000ff",
            headers={"X-User-ID": "nobody-1", "X-User-Role": "NobodyRole",
                     "Content-Type": "application/json"},
        )
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert err["error_id"] != "ERR_NOT_FOUND"

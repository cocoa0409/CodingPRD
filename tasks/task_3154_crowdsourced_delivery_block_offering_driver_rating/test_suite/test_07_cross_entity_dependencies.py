"""Cross-entity state dependencies: activation gated on screening; deliver gated on assignment."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    register_driver,
    latest_screening_id,
    begin_screening_review,
    decide_screening,
    create_vehicle,
    attest_insurance,
    onboard_active_driver,
    accept_block,
    check_in,
    load_packages,
    list_assignment_packages,
    make_driver_headers,
    get_driver,
    validate_error,
    validate_error_is_one_of,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["platform_admin_headers"]


class TestActivationRequiresLatestScreeningCleared:
    def test_activation_with_failed_latest_screening_rejected(self, api):
        """PRD §3.1: "A `PlatformAdmin` activates a driver only when the driver is still
        `APPLIED`, when the driver's most recently created screening is `CLEARED`
        (otherwise the request fails with `ERR_SCREENING_NOT_CLEARED`), and when the
        driver owns at least one vehicle that is both `ACTIVE` and `ATTESTED` (otherwise
        `ERR_NO_ELIGIBLE_VEHICLE`)."

        Design: Difficulty/cross_entity_state_dependency/driver_activation_requires_latest_screening_cleared
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])
        begin_screening_review(sc)
        decide_screening(sc, "FAILED", failure_reason="MVR check failed")
        vehicle = create_vehicle(driver["id"])
        attest_insurance(vehicle["id"], driver["id"])

        resp = api_client.activate_driver(driver["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)

        assert get_driver(driver["id"])["status"] == "APPLIED"

    def test_activation_with_never_reviewed_screening_rejected(self, api):
        """PRD §3.1: "A `PlatformAdmin` activates a driver only when the driver is still
        `APPLIED`, when the driver's most recently created screening is `CLEARED`
        (otherwise the request fails with `ERR_SCREENING_NOT_CLEARED`), and when the
        driver owns at least one vehicle that is both `ACTIVE` and `ATTESTED` (otherwise
        `ERR_NO_ELIGIBLE_VEHICLE`)."

        Design: Difficulty/cross_entity_state_dependency/driver_activation_requires_latest_screening_cleared
        """
        set_clock()
        driver = register_driver()
        # Screening left in INITIATED — not CLEARED.
        vehicle = create_vehicle(driver["id"])
        attest_insurance(vehicle["id"], driver["id"])

        resp = api_client.activate_driver(driver["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)
        assert get_driver(driver["id"])["status"] == "APPLIED"


class TestPackageDeliverRequiresAssignmentInDelivery:
    def test_deliver_before_depart_rejected(self, api):
        """PRD §3.5: "marking a package delivered requires it to be `OUT_FOR_DELIVERY`
        and the owning assignment to be `IN_DELIVERY`; acting on a package in any other
        state, or on an assignment that is not yet out for delivery, is rejected with
        `ERR_PACKAGE_NOT_DELIVERABLE` or `ERR_INVALID_STATE` respectively."

        Design: Difficulty/cross_entity_state_dependency/package_deliver_requires_assignment_in_delivery
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])
        set_clock("2026-09-01T01:45:00Z")
        check_in(assignment["id"], driver["id"])
        load_packages(
            assignment["id"],
            [
                {
                    "tracking_code": "PW-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                }
            ],
        )
        rows = list_assignment_packages(assignment["id"])

        # Assignment ROUTE_ASSIGNED, package LOADED, driver has NOT departed.
        resp = api_client.deliver_package(
            rows[0]["id"],
            {"photo_url": "https://img.example/early.jpg", "photo_gps_tagged": True},
            make_driver_headers(driver["id"]),
        )
        actual = validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_PACKAGE_NOT_DELIVERABLE, ApiErrorId.ERR_INVALID_STATE],
        )
        assert resp.status_code == 409

        fresh = list_assignment_packages(assignment["id"])
        assert fresh[0]["status"] == "LOADED"
        assert fresh[0]["delivered_at"] is None

    def test_deliver_after_depart_succeeds(self, api):
        """PRD §3.5: "marking a package delivered requires it to be `OUT_FOR_DELIVERY`
        and the owning assignment to be `IN_DELIVERY` …"
        PRD §3.4: "The driver then departs, moving the assignment from `ROUTE_ASSIGNED`
        to `IN_DELIVERY` and flipping every `LOADED` package to `OUT_FOR_DELIVERY`."

        Design: Difficulty/cross_entity_state_dependency/package_deliver_requires_assignment_in_delivery
        """
        from test_helpers import depart, deliver_package

        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])
        set_clock("2026-09-01T01:45:00Z")
        check_in(assignment["id"], driver["id"])
        load_packages(
            assignment["id"],
            [
                {
                    "tracking_code": "PW-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                }
            ],
        )
        depart(assignment["id"], driver["id"])
        rows = list_assignment_packages(assignment["id"])
        assert rows[0]["status"] == "OUT_FOR_DELIVERY"

        delivered = deliver_package(
            rows[0]["id"], driver["id"], "https://img.example/ok.jpg", True
        )
        assert delivered["status"] == "DELIVERED"

"""Corner — RBAC: role denials and entity-backed ownership."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    register_driver,
    latest_screening_id,
    begin_screening_review,
    create_vehicle,
    onboard_active_driver,
    deactivate_driver,
    get_driver,
    get_vehicle,
    make_driver_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["platform_admin_headers"]
STATION_OPS = TEST_USERS["station_ops_headers"]
REVIEWER = TEST_USERS["appeals_reviewer_headers"]


class TestRoleDenials:
    def test_driver_cannot_create_station_forbidden(self, api):
        """PRD §2.1: "Role responsibilities in brief: `Anonymous` may only register a
        new driver. A `Driver` manages their own vehicles, insurance attestations,
        screening reopen requests, block and offer acceptance, assignment execution
        (check-in, depart, forfeit), package delivery outcomes, and appeals."
        PRD §2.1: "A request whose role is not permitted for the target endpoint, or
        whose `X-User-ID` fails an ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/driver_cannot_create_station_forbidden
        """
        set_clock()
        driver = register_driver()
        resp = api_client.create_station(
            {"name": "Rogue Station", "zone_code": "XXX9"},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_station_ops_cannot_decide_screening_forbidden(self, api):
        """PRD §2.1: "A `PlatformAdmin` manages stations, screening review, driver
        activation and deactivation, pay settlement, and the logical clock."
        PRD §2.1: "A request whose role is not permitted for the target endpoint, or
        whose `X-User-ID` fails an ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/station_ops_cannot_decide_screening_forbidden
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])
        begin_screening_review(sc)

        resp = api_client.decide_screening(sc, {"decision": "CLEARED"}, STATION_OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        data, meta = validate_paginated(
            api_client.list_driver_screenings(driver["id"], ADMIN)
        )
        assert data[0]["status"] == "IN_REVIEW"

    def test_appeals_reviewer_cannot_deactivate_driver_forbidden(self, api):
        """PRD §2.1: "An `AppealsReviewer` is deliberately segregated from
        `PlatformAdmin` — the role that deactivates a driver cannot decide that driver's
        appeal — and handles evidence requests and appeal decisions."
        PRD §2.1: "A request whose role is not permitted for the target endpoint, or
        whose `X-User-ID` fails an ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/appeals_reviewer_cannot_deactivate_driver_forbidden
        """
        set_clock()
        driver, vehicle, _s = onboard_active_driver()

        resp = api_client.deactivate_driver(
            driver["id"], {"reason": "reviewer overreach"}, REVIEWER
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        assert get_driver(driver["id"])["status"] == "ACTIVE"


class TestEntityBackedOwnership:
    def test_driver_cannot_attest_other_drivers_vehicle_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Driver`, the role is entity-backed:
        `X-User-ID` is the `id` of the acting `Driver`, and ownership checks on any
        resource that references a driver — the driver profile itself, vehicles,
        screening reopen, assignments, packages, offers, and appeals — compare the
        resource's driver foreign-key field to `X-User-ID`."
        PRD §2.1: "A request whose role is not permitted for the target endpoint, or
        whose `X-User-ID` fails an ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/driver_cannot_attest_other_drivers_vehicle_forbidden
        """
        set_clock()
        driver1 = register_driver()
        vehicle = create_vehicle(driver1["id"])
        driver2 = register_driver()

        resp = api_client.attest_insurance(
            vehicle["id"],
            {"insurance_expires_on": "2027-01-01"},
            make_driver_headers(driver2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        assert get_vehicle(vehicle["id"])["insurance_status"] == "NONE"

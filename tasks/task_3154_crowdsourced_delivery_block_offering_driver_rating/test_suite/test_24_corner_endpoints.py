"""Corner — endpoints: reserved-offer visibility bypass, completion gate, load-packages shape, first-come."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    create_offer,
    accept_offer,
    accept_block,
    check_in,
    load_packages,
    depart,
    deliver_package,
    get_assignment,
    get_block,
    get_offer,
    list_assignment_packages,
    make_driver_headers,
    validate_error,
    validate_success,
    validate_paginated,
    register_driver,
    latest_screening_id,
    decide_screening,
    begin_screening_review,
    create_vehicle,
    attest_insurance,
    activate_driver,
)
from test_helpers.api_errors import ApiErrorId

STATION_OPS = TEST_USERS["station_ops_headers"]


def _setup_assignment_in_delivery(packages):
    """Block [02:00,04:00), accepted, checked in at 01:45, loaded, departed."""
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
    return station, driver, vehicle, block, assignment


class TestOfferAcceptBypassesVisibility:
    def test_offer_accept_bypasses_visibility_lead_direct_rejected(self, api):
        """PRD §3.3: "The target driver may accept it with a `vehicle_id` payload, which
        creates the assignment with `offer_id` set, moves the offer to `ACCEPTED`, and
        transitions the block to `ASSIGNED` exactly as a first-come claim does — with
        one privilege: offer acceptance bypasses the tier visibility lead, though every
        other acceptance precondition (driver active, vehicle eligibility, class rank,
        window overlap, single live assignment per block) still applies."
        PRD §3.3: "the tier visibility gate must have opened: the current instant must
        be at or after the block's `starts_at` minus the visibility lead of the driver's
        current tier, or the claim is rejected with `ERR_BLOCK_NOT_VISIBLE_YET`."

        Design: Corner/endpoints/offer_accept_bypasses_visibility_lead_direct_rejected
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        # Block starts 34 hours out: invisible to every tier's first-come lead.
        block = create_published_block(
            station["id"],
            starts_at="2026-09-02T10:00:00Z",
            ends_at="2026-09-02T12:00:00Z",
            base_pay_cents=4000,
        )
        offer = create_offer(
            block["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-02T08:00:00Z",
        )

        # First-come claim: rejected on the visibility gate.
        resp = api_client.accept_block(
            block["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_VISIBLE_YET)

        # The reserved offer channel bypasses visibility.
        resp2 = api_client.accept_offer(
            offer["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        assignment = validate_success(resp2, expected_status=201)
        assert assignment["offer_id"] == offer["id"]
        assert assignment["status"] == "ASSIGNED"
        assert get_block(block["id"])["status"] == "ASSIGNED"
        assert get_offer(offer["id"])["status"] == "ACCEPTED"


class TestCompletionGate:
    def test_complete_with_pending_packages_rejected(self, api):
        """PRD §3.5: "Completion is a station action. An assignment in `IN_DELIVERY` may
        be completed only once every one of its packages has reached `DELIVERED` or
        `DELIVERY_FAILED`; completing with any package still `LOADED` or
        `OUT_FOR_DELIVERY` is rejected with `ERR_PACKAGE_NOT_DELIVERABLE`."

        Design: Corner/endpoints/complete_with_pending_packages_rejected
        """
        station, driver, vehicle, block, assignment = _setup_assignment_in_delivery(None)
        load_packages(
            assignment["id"],
            [
                {
                    "tracking_code": "H-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                },
                {
                    "tracking_code": "H-2",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                },
            ],
        )
        depart(assignment["id"], driver["id"])
        rows = {
            row["tracking_code"]: row
            for row in list_assignment_packages(assignment["id"])
        }
        set_clock("2026-09-01T02:30:00Z")
        deliver_package(
            rows["H-1"]["id"], driver["id"], "https://img.example/h1.jpg", True
        )
        # H-2 remains OUT_FOR_DELIVERY.

        resp = api_client.complete_assignment(assignment["id"], STATION_OPS)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_DELIVERABLE)

        assert get_assignment(assignment["id"])["status"] == "IN_DELIVERY"
        ps_data, ps_meta = validate_paginated(
            api_client.get_assignment_pay_statement(assignment["id"], STATION_OPS)
        )
        assert ps_data == []


class TestLoadPackagesShape:
    def test_load_packages_empty_or_duplicate_rejected(self, api):
        """PRD §3.4: "Once checked in, station staff perform scan-out: the load-packages
        operation takes a non-empty `packages` array, creates one `Package` per element
        in `LOADED` status, and moves the assignment from `CHECKED_IN` to
        `ROUTE_ASSIGNED`. Each package carries a `tracking_code` that must be unique
        within the assignment, a positive `billable_weight_kg` (a non-positive weight is
        rejected with `ERR_VALIDATION`), and a `promised_by` instant — the promised
        delivery time whose boundary is inclusive."
        PRD §2.5: "The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role permission and ownership (`ERR_FORBIDDEN`, or `ERR_OFFER_WRONG_DRIVER` for wrong-driver offer actions); third, existence of path and body references (`ERR_NOT_FOUND`); fourth, state-machine legality, including the domain state errors `ERR_DRIVER_NOT_ACTIVE` and `ERR_BLOCK_NOT_PUBLISHED`, all rejected with `ERR_INVALID_STATE` or the named domain error (HTTP 409); fifth, business safety gates — screening, vehicle, and insurance checks such as `ERR_SCREENING_NOT_CLEARED`, `ERR_NO_ELIGIBLE_VEHICLE`, `ERR_INSURANCE_NOT_ATTESTED`, `ERR_VEHICLE_CLASS_MISMATCH`, and `ERR_INSURANCE_WINDOW_LAPSE`; sixth, temporal business gates such as `ERR_BLOCK_NOT_VISIBLE_YET`, `ERR_BLOCK_WINDOW_OVERLAP`, `ERR_OFFER_BUFFER_CONFLICT`, `ERR_OFFER_EXPIRED`, `ERR_CHECKIN_TOO_EARLY`, and `ERR_CHECKIN_WINDOW_CLOSED`; seventh, aggregate and uniqueness constraints such as `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_VIN`, and `ERR_APPEAL_NOT_OPEN`; eighth, money-side and optimistic-concurrency checks including `ERR_STALE_VERSION`; and ninth, request body shape (`ERR_VALIDATION` for malformed JSON, missing required fields, invalid enum members, or unparseable datetimes)."

        Design: Corner/endpoints/load_packages_empty_or_duplicate_rejected
        """
        station, driver, vehicle, block, assignment = _setup_assignment_in_delivery(None)

        # Empty packages array: rejected.
        resp1 = api_client.load_packages(
            assignment["id"], {"packages": []}, STATION_OPS
        )
        validate_error(resp1, ApiErrorId.ERR_VALIDATION)

        # Duplicate tracking codes within one call: rejected.
        resp2 = api_client.load_packages(
            assignment["id"],
            {
                "packages": [
                    {
                        "tracking_code": "DUP",
                        "billable_weight_kg": 1.0,
                        "promised_by": "2026-09-01T03:00:00Z",
                    },
                    {
                        "tracking_code": "DUP",
                        "billable_weight_kg": 2.0,
                        "promised_by": "2026-09-01T03:00:00Z",
                    },
                ]
            },
            STATION_OPS,
        )
        validate_error(resp2, ApiErrorId.ERR_VALIDATION)

        assert get_assignment(assignment["id"])["status"] == "CHECKED_IN"
        data, meta = validate_paginated(
            api_client.list_assignment_packages(assignment["id"], STATION_OPS)
        )
        assert data == []


class TestFirstComeSemantics:
    def test_second_accept_of_assigned_block_rejected(self, api):
        """PRD §3.3: "The block must be `PUBLISHED` (otherwise
        `ERR_BLOCK_NOT_PUBLISHED`), the driver must be `ACTIVE` (otherwise
        `ERR_DRIVER_NOT_ACTIVE`) …"
        PRD §3.3: "Only one non-terminal assignment may exist per block."

        Design: Corner/endpoints/second_accept_of_assigned_block_rejected
        """
        set_clock()
        station = create_station()
        driver1, vehicle1, _s1 = onboard_active_driver()

        driver2 = register_driver()
        sc2 = latest_screening_id(driver2["id"])
        begin_screening_review(sc2)
        decide_screening(sc2, "CLEARED")
        vehicle2 = create_vehicle(driver2["id"])
        attest_insurance(vehicle2["id"], driver2["id"])
        activate_driver(driver2["id"])

        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        accept_block(block["id"], driver1["id"], vehicle1["id"])

        resp = api_client.accept_block(
            block["id"],
            {"vehicle_id": vehicle2["id"]},
            make_driver_headers(driver2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_PUBLISHED)

        assert get_block(block["id"])["assigned_driver_id"] == driver1["id"]

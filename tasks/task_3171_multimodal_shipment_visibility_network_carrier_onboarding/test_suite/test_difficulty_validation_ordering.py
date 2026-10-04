"""Validation ordering: the surfaced error is the earliest failing check."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers import factories as f
from test_helpers.test_users import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_carrier_rep_headers,
    make_shipper_rep_headers,
)


def _facility_with_booking_then_suspended(api):
    """Facility with one SCHEDULED appointment [10:00, 11:00), then SUSPENDED."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    suspended = get_success_data(
        api.patch_facility(facility["id"], {"status": "SUSPENDED"}, PLATFORM_ADMIN_HEADERS)
    )
    return carrier, shipment, suspended


# ═══ priority_pair_validation_conflict / facility_suspended_beats_window_overlap ═


def test_suspended_facility_beats_window_overlap(api):
    """A booking violating both the state gate and overlap rule reports the state gate.

    PRD: "The order is: (1) presence and well-formedness of the user-context
    headers; (2) role authorization and entity-backed ownership; (3) data-share
    visibility for cross-party reads; (4) existence of path resources,
    validated left to right; (5) request-shape validity — required fields, enum
    membership, interval ordering, and mode-configuration rules; (6) state
    preconditions of the target resource; (7) interval-occupation conflicts
    (appointment windows and testing windows); (8) threshold gates (the
    activation quality gate and the identity-match confirm gate); and (9)
    optimistic-concurrency and grantee referential checks."
    PRD: "A request that fails an earlier check never reaches a later one — for
    example, a stale `expected_facility_version` on an appointment booking that
    also names a nonexistent shipment surfaces `ERR_SHIPMENT_NOT_FOUND`, not
    `ERR_STALE_VERSION`."
    PRD: "Appointment booking requires the facility to be `ACTIVE` —
    booking against a suspended facility fails with `ERR_FACILITY_NOT_ACTIVE` —
    but a suspended facility's existing appointments are otherwise
    untouched."
    Design: Difficulty/priority_pair_validation_conflict/facility_suspended_beats_window_overlap
    """
    carrier, shipment, facility = _facility_with_booking_then_suspended(api)

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T10:30:00Z",
            "2026-09-01T11:30:00Z",
            facility["version"],
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_ACTIVE)

    rows, meta = validate_paginated(
        api.list_facility_appointments(facility["id"], PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


def test_suspended_facility_rejects_even_a_disjoint_window(api):
    """The state gate alone suffices to reject, with no overlap involved.

    PRD: "Appointment booking requires the facility to be `ACTIVE` —
    booking against a suspended facility fails with `ERR_FACILITY_NOT_ACTIVE` —
    but a suspended facility's existing appointments are otherwise
    untouched."
    Design: Difficulty/priority_pair_validation_conflict/facility_suspended_beats_window_overlap
    """
    carrier, shipment, facility = _facility_with_booking_then_suspended(api)

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T14:00:00Z",
            "2026-09-01T15:00:00Z",
            facility["version"],
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_ACTIVE)
    # The pre-existing appointment is untouched by the suspension.
    rows, meta = validate_paginated(
        api.list_facility_appointments(facility["id"], PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "SCHEDULED"


# ═══ priority_pair_validation_conflict / wrong_role_beats_alert_already_resolved ═


def _resolved_alert_world(api):
    """An alert already acknowledged and resolved FALSE_ALARM."""
    world = fixtures.setup_delayed_shipment_with_open_alert(api, delay_minutes=300)
    fixtures.acknowledge_and_resolve(api, world["alert"]["id"], "FALSE_ALARM")
    return world


def test_wrong_role_beats_alert_already_resolved(api):
    """A CarrierRep resolving an already-resolved alert gets the auth rejection.

    PRD: "The order is: (1) presence and well-formedness of the user-context
    headers; (2) role authorization and entity-backed ownership; (3) data-share
    visibility for cross-party reads; (4) existence of path resources,
    validated left to right; (5) request-shape validity — required fields, enum
    membership, interval ordering, and mode-configuration rules; (6) state
    preconditions of the target resource; (7) interval-occupation conflicts
    (appointment windows and testing windows); (8) threshold gates (the
    activation quality gate and the identity-match confirm gate); and (9)
    optimistic-concurrency and grantee referential checks."
    PRD: "A request that fails an earlier check never reaches a later one — for
    example, a stale `expected_facility_version` on an appointment booking that
    also names a nonexistent shipment surfaces `ERR_SHIPMENT_NOT_FOUND`, not
    `ERR_STALE_VERSION`."
    Design: Difficulty/priority_pair_validation_conflict/wrong_role_beats_alert_already_resolved
    """
    world = _resolved_alert_world(api)

    response = api.resolve_alert(
        world["alert"]["id"],
        f.resolve_payload("DELAY_CONFIRMED"),
        make_carrier_rep_headers(world["carrier"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows = fixtures.list_shipment_alerts(api, world["shipment"]["id"])
    assert rows[0]["status"] == "RESOLVED"
    assert rows[0]["resolution"] == "FALSE_ALARM"


def test_wrong_role_beats_alert_state_on_an_open_alert_too(api):
    """The auth check precedes state evaluation even when the alert is OPEN.

    PRD: "The order is: (1) presence and well-formedness of the user-context
    headers; (2) role authorization and entity-backed ownership; (3) data-share
    visibility for cross-party reads; (4) existence of path resources,
    validated left to right; (5) request-shape validity — required fields, enum
    membership, interval ordering, and mode-configuration rules; (6) state
    preconditions of the target resource; (7) interval-occupation conflicts
    (appointment windows and testing windows); (8) threshold gates (the
    activation quality gate and the identity-match confirm gate); and (9)
    optimistic-concurrency and grantee referential checks."
    PRD: "A request that fails an earlier check never reaches a later one — for
    example, a stale `expected_facility_version` on an appointment booking that
    also names a nonexistent shipment surfaces `ERR_SHIPMENT_NOT_FOUND`, not
    `ERR_STALE_VERSION`."
    Design: Difficulty/priority_pair_validation_conflict/wrong_role_beats_alert_already_resolved
    """
    world = fixtures.setup_delayed_shipment_with_open_alert(api, delay_minutes=300)

    response = api.resolve_alert(
        world["alert"]["id"],
        f.resolve_payload("FALSE_ALARM"),
        make_carrier_rep_headers(world["carrier"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows = fixtures.list_shipment_alerts(api, world["shipment"]["id"])
    assert rows[0]["status"] == "OPEN"


# ═══ priority_pair_validation_conflict / window_overlap_beats_stale_facility_version ═


def _facility_with_one_booking(api):
    """Facility ACTIVE with one SCHEDULED appointment [10:00, 11:00)."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    first_version = facility["version"]
    fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    return carrier, shipment, facility, first_version


def test_window_overlap_beats_stale_facility_version(api):
    """An overlapping booking with a stale version reports the overlap, not the OCC.

    PRD: "The order is: (1) presence and well-formedness of the user-context
    headers; (2) role authorization and entity-backed ownership; (3) data-share
    visibility for cross-party reads; (4) existence of path resources,
    validated left to right; (5) request-shape validity — required fields, enum
    membership, interval ordering, and mode-configuration rules; (6) state
    preconditions of the target resource; (7) interval-occupation conflicts
    (appointment windows and testing windows); (8) threshold gates (the
    activation quality gate and the identity-match confirm gate); and (9)
    optimistic-concurrency and grantee referential checks."
    PRD: "A request that fails an earlier check never reaches a later one — for
    example, a stale `expected_facility_version` on an appointment booking that
    also names a nonexistent shipment surfaces `ERR_SHIPMENT_NOT_FOUND`, not
    `ERR_STALE_VERSION`."
    Design: Difficulty/priority_pair_validation_conflict/window_overlap_beats_stale_facility_version
    """
    carrier, shipment, facility, first_version = _facility_with_one_booking(api)

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T10:30:00Z",
            "2026-09-01T11:30:00Z",
            first_version,  # stale: the first booking bumped the facility
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_WINDOW_CONFLICT)

    rows, meta = validate_paginated(
        api.list_facility_appointments(facility["id"], PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


def test_stale_version_surfaces_once_no_earlier_check_fails(api):
    """With a disjoint window the OCC check is reached and reports staleness.

    PRD: "Booking an appointment at a facility requires the request to carry
    `expected_facility_version`, holding the client's last observed `version`
    of the facility. A mismatch against the facility's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Design: Difficulty/priority_pair_validation_conflict/window_overlap_beats_stale_facility_version
    """
    carrier, shipment, facility, first_version = _facility_with_one_booking(api)

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T14:00:00Z",
            "2026-09-01T15:00:00Z",
            first_version,  # stale, but the window is disjoint
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

"""Cross-entity state dependencies and the two interval-occupation regimes."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers import factories as f
from test_helpers.test_users import (
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_carrier_rep_headers,
    make_shipper_rep_headers,
)


# ═══ cross_entity_state_dependency / event_ingestion_requires_active_connection ═


def _testing_connection_with_shipment(api):
    """A TESTING connection (no checkpoint yet) and a shipment booked onto it."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    return carrier, connection, shipper, shipment


def test_testing_connection_allows_booking_but_blocks_event_ingest(api):
    """Shipment creation permits TESTING; event ingest requires ACTIVE.

    PRD: "The named connection must be `TESTING` or `ACTIVE` — a shipment
    cannot be booked onto a draft, suspended, or retired feed, and the attempt
    fails with `ERR_CONNECTION_NOT_ACTIVE` (HTTP 409) — and the shipment's
    `mode` must appear among the connection's `supported_modes`
    (`ERR_INVALID_MODE_CONFIG` otherwise)."
    PRD: "requires the feed connection to be `ACTIVE` (a `TESTING` feed can
    certify but not carry live traffic, and any other state also fails with
    `ERR_CONNECTION_NOT_ACTIVE`), and requires the shipment not to be
    terminal — ingesting an event onto a `DELIVERED` or `CANCELLED` shipment is
    rejected with `ERR_SHIPMENT_NOT_TRACKABLE` (HTTP 409)."
    Design: Difficulty/cross_entity_state_dependency/event_ingestion_requires_active_connection
    """
    carrier, connection, shipper, shipment = _testing_connection_with_shipment(api)
    assert shipment["tracking_status"] == "BOOKED"

    response = api.ingest_event(
        shipment["id"],
        f.event_payload("2026-09-01T06:00:00Z", "DEPARTED"),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONNECTION_NOT_ACTIVE)

    rows, meta = validate_paginated(api.list_events(shipment["id"], NETWORK_OPS_HEADERS))
    assert meta["total_count"] == 0
    assert fixtures.read_shipment(api, shipment["id"])["tracking_status"] == "BOOKED"


def test_event_ingest_opens_up_once_the_connection_activates(api):
    """The same shipment accepts events as soon as the feed is ACTIVE.

    PRD: "requires the feed connection to be `ACTIVE` (a `TESTING` feed can
    certify but not carry live traffic, and any other state also fails with
    `ERR_CONNECTION_NOT_ACTIVE`), and requires the shipment not to be
    terminal — ingesting an event onto a `DELIVERED` or `CANCELLED` shipment is
    rejected with `ERR_SHIPMENT_NOT_TRACKABLE` (HTTP 409)."
    Design: Difficulty/cross_entity_state_dependency/event_ingestion_requires_active_connection
    """
    carrier, connection, shipper, shipment = _testing_connection_with_shipment(api)

    # The scoring window opens "just after" the connection's created_at, so
    # the heartbeat is recorded strictly after creation.
    fixtures.set_clock(api, "2026-09-01T00:05:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-01T00:05:00Z", completeness=100)
    fixtures.set_clock(api, "2026-09-01T00:15:00Z")
    fixtures.run_checkpoint(api)
    fixtures.activate_connection(api, connection)

    event = fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")
    assert event["event_type"] == "DEPARTED"
    assert fixtures.read_shipment(api, shipment["id"])["tracking_status"] == "IN_TRANSIT"


# ═══ cross_entity_state_dependency / link_confirm_requires_non_terminal_shipment ═


def _proposed_link_world(api):
    """A PROPOSED score-1.0 link on a still-live shipment."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(
        api, shipper, po_number="PO-5", destination_code="LAX", booking_reference="BK-5"
    )
    shipment = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        tracking_reference="BK-5",
        destination_code="LAX",
        po_reference_claim="PO-5",
    )
    link = fixtures.propose_identity_link(api, shipment, po)
    return shipper, shipment, po, link


def test_confirm_rejected_once_the_shipment_is_cancelled(api):
    """A terminal shipment blocks confirm even when the score would pass.

    PRD: "the `ShipperRep` whose `X-User-ID` equals the order's `shipper_id`
    confirms a `PROPOSED` link, but only when three conditions hold — the link
    is still `PROPOSED` (otherwise `ERR_LINK_NOT_PROPOSED`, HTTP 409), the
    shipment's `tracking_status` is neither `DELIVERED` nor `CANCELLED`
    (otherwise `ERR_SHIPMENT_TERMINAL`, HTTP 409), and the `match_score` is
    strictly greater than 0.90 — a score of exactly 0.90 is *not* sufficient
    and is rejected with `ERR_MATCH_SCORE_BELOW_THRESHOLD` (HTTP 422)."
    Design: Difficulty/cross_entity_state_dependency/link_confirm_requires_non_terminal_shipment
    """
    shipper, shipment, po, link = _proposed_link_world(api)
    headers = make_shipper_rep_headers(shipper["id"])

    get_success_data(api.cancel_shipment(shipment["id"], headers))

    response = api.confirm_identity_link(link["id"], headers)
    validate_error(response, ApiErrorId.ERR_SHIPMENT_TERMINAL)

    assert fixtures.read_purchase_order(api, po["id"])["confirmed_link_count"] == 0


def test_confirm_succeeds_while_the_shipment_is_still_live(api):
    """The companion live case: the same link confirms before cancellation.

    PRD: "Confirming increments the order's `confirmed_link_count` by 1, bumps
    the order's `version`, and moves the shipment's `identity_state` to
    `MATCHED_CONFIRMED` with a `version` bump of its own."
    Design: Difficulty/cross_entity_state_dependency/link_confirm_requires_non_terminal_shipment
    """
    shipper, shipment, po, link = _proposed_link_world(api)

    confirmed = get_success_data(
        api.confirm_identity_link(link["id"], make_shipper_rep_headers(shipper["id"]))
    )
    assert confirmed["status"] == "CONFIRMED"
    assert fixtures.read_shipment(api, shipment["id"])["identity_state"] == "MATCHED_CONFIRMED"
    assert fixtures.read_purchase_order(api, po["id"])["confirmed_link_count"] == 1


# ═══ resource_temporal_overlap / appointment_half_open_back_to_back_allowed_overlap_rejected ═


def test_back_to_back_windows_allowed_but_partial_overlap_rejected(api):
    """Half-open semantics: touching is fine, overlapping is a conflict.

    PRD: "Two appointments at the same facility conflict when their
    half-open windows overlap and the existing one is still `SCHEDULED`; the
    conflicting booking is rejected with `ERR_APPOINTMENT_WINDOW_CONFLICT`
    (HTTP 409) — and note that because these windows are half-open, adjacent
    windows that merely touch do *not* conflict, unlike the closed
    certification windows of §3.2."
    Design: Difficulty/resource_temporal_overlap/appointment_half_open_back_to_back_allowed_overlap_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)

    fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    touching = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T11:00:00Z", "2026-09-01T12:00:00Z"
    )
    assert touching["status"] == "SCHEDULED"

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T10:30:00Z",
            "2026-09-01T11:30:00Z",
            fixtures.read_facility(api, facility["id"])["version"],
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_WINDOW_CONFLICT)

    rows, meta = validate_paginated(
        api.list_facility_appointments(facility["id"], PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2


def test_a_voided_appointment_no_longer_blocks_its_window(api):
    """The overlap check considers only still-SCHEDULED appointments.

    PRD: "Two appointments at the same facility conflict when their
    half-open windows overlap and the existing one is still `SCHEDULED`; the
    conflicting booking is rejected with `ERR_APPOINTMENT_WINDOW_CONFLICT`
    (HTTP 409) — and note that because these windows are half-open, adjacent
    windows that merely touch do *not* conflict, unlike the closed
    certification windows of §3.2."
    Design: Difficulty/resource_temporal_overlap/appointment_half_open_back_to_back_allowed_overlap_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)

    first = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    fixtures.complete_appointment(
        api, first, carrier["id"], "2026-09-01T10:15:00Z", "2026-09-01T12:15:00Z"
    )
    get_success_data(api.void_completion(first["id"], NETWORK_OPS_HEADERS))

    # The window is free again: the VOIDED appointment no longer blocks it.
    second = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    assert second["status"] == "SCHEDULED"


# ═══ resource_temporal_overlap / testing_window_closed_interval_touching_endpoints_conflict ═


def test_certification_windows_touching_at_an_endpoint_conflict(api):
    """Closed intervals: touching endpoints conflict; a later start succeeds.

    PRD: "Certification windows are **closed intervals on both ends**, and
    no two connections of the *same carrier* may be in `TESTING` with
    intersecting windows — because the interval is closed, windows that merely
    touch at an endpoint conflict just as overlapping windows do; a conflicting
    request is rejected with `ERR_TESTING_WINDOW_CONFLICT` (HTTP 409)."
    Design: Difficulty/resource_temporal_overlap/testing_window_closed_interval_touching_endpoints_conflict
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    first = fixtures.create_testing_connection(
        api,
        carrier,
        channel="TMS",
        window=("2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"),
    )
    second = fixtures.create_connection(api, carrier, channel="TMS")
    get_success_data(
        api.submit_credentials(
            second["id"], f.credentials_payload("vault://second"), make_carrier_rep_headers(carrier["id"])
        )
    )

    touching = api.begin_testing(
        second["id"],
        f.begin_testing_payload("2026-09-05T00:00:00Z", "2026-09-09T00:00:00Z"),
        NETWORK_OPS_HEADERS,
    )
    validate_error(touching, ApiErrorId.ERR_TESTING_WINDOW_CONFLICT)

    disjoint = get_success_data(
        api.begin_testing(
            second["id"],
            f.begin_testing_payload("2026-09-06T00:00:00Z", "2026-09-09T00:00:00Z"),
            NETWORK_OPS_HEADERS,
        )
    )
    assert disjoint["status"] == "TESTING"
    assert fixtures.read_connection(api, first["id"])["status"] == "TESTING"


def test_testing_windows_of_different_carriers_may_touch(api):
    """The closed-interval conflict is scoped to connections of one carrier.

    PRD: "no two connections of the *same carrier* may be in `TESTING` with
    intersecting windows — because the interval is closed, windows that merely
    touch at an endpoint conflict just as overlapping windows do; a conflicting
    request is rejected with `ERR_TESTING_WINDOW_CONFLICT` (HTTP 409)."
    Design: Difficulty/resource_temporal_overlap/testing_window_closed_interval_touching_endpoints_conflict
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier_a = fixtures.create_carrier(api, carrier_name="Carrier A", scac_code="CRA1")
    carrier_b = fixtures.create_carrier(api, carrier_name="Carrier B", scac_code="CRB2")
    fixtures.create_testing_connection(
        api,
        carrier_a,
        channel="TMS",
        window=("2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"),
    )

    # The other carrier's connection may use the very same window.
    other = fixtures.create_testing_connection(
        api,
        carrier_b,
        channel="TMS",
        window=("2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"),
    )
    assert other["status"] == "TESTING"

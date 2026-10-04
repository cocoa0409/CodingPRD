"""Corner probes over the cross-cutting complexity layers: optimistic
concurrency on both parents, the resume-direction cascade and immediate
consistency."""

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
)


def test_identity_link_create_with_stale_po_version(api):
    """A stale expected_po_version is refused; retrying with the fresh one works.

    PRD: "Creating an identity link on a shipment requires the request to carry
    `expected_po_version`, holding the client's last observed `version` of the
    target purchase order. If the purchase order's current `version` has
    advanced beyond what the client observed — because another link was
    proposed, confirmed, or a confirmed link was rejected in the meantime — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/identity_link_create_with_stale_po_version
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(api, shipper, po_number="PO-O")
    ship_one = fixtures.create_shipment(api, shipper, carrier, connection, tracking_reference="OO-1")
    ship_two = fixtures.create_shipment(api, shipper, carrier, connection, tracking_reference="OO-2")

    first_version = po["version"]
    fixtures.propose_identity_link(api, ship_one, po, expected_po_version=first_version)

    stale = api.propose_identity_link(
        ship_two["id"],
        f.identity_link_payload(po["id"], first_version),
        NETWORK_OPS_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = fixtures.read_purchase_order(api, po["id"])["version"]
    assert fresh_version == first_version + 1

    retry = get_success_data(
        api.propose_identity_link(
            ship_two["id"],
            f.identity_link_payload(po["id"], fresh_version),
            NETWORK_OPS_HEADERS,
        )
    )
    assert retry["status"] == "PROPOSED"
    assert fixtures.read_purchase_order(api, po["id"])["version"] == fresh_version + 1


def test_appointment_book_with_stale_facility_version(api):
    """A disjoint window with a stale facility version fails on OCC alone.

    PRD: "Booking an appointment at a facility requires the request to carry
    `expected_facility_version`, holding the client's last observed `version`
    of the facility. A mismatch against the facility's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/appointment_book_with_stale_facility_version
    """
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

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T14:00:00Z",
            "2026-09-01T15:00:00Z",
            first_version,
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    rows, meta = validate_paginated(
        api.list_facility_appointments(facility["id"], PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


def test_cascade_layer_resume_restores_freshness_and_ci(api):
    """Resume unwinds the staleness cascade: FRESH again, interval narrowed back.

    PRD: "A successful resume transitions the connection back to `ACTIVE`,
    clears `suspended_at` to null, and restores every shipment of this
    connection whose `data_freshness` was `STALE` back to `FRESH`, recomputing
    each such shipment's ETA without the stale multiplier."
    Design: Corner/cross_cutting_complexity_layers/cascade_layer_resume_restores_freshness_and_ci
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    fixtures.set_clock(api, "2026-09-01T10:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-01T10:00:00Z", completeness=100)
    fixtures.set_clock(api, "2026-09-01T12:00:00Z")
    fixtures.run_checkpoint(api)
    fixtures.activate_connection(api, connection)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection, destination_code="MEM")
    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")

    # Stale-suspend the feed, then remediate with a fresh heartbeat. A
    # mid-flight heartbeat on 09-03 keeps the second checkpoint's scoring
    # window — which opens "just after" the previous run's execution time
    # (PRD §3.3) — non-empty: the window 09-01T12:00 -> 09-05T04:00 holds two
    # heartbeats against an expected count of 25, scoring 76, while the CI
    # still consumes the prior-epoch 83 (PRD §3.5: "the quality computed in
    # the current run never feeds the same run's confidence intervals").
    fixtures.set_clock(api, "2026-09-03T10:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-03T10:00:00Z", completeness=100)
    fixtures.set_clock(api, "2026-09-05T04:00:00Z")
    fixtures.run_checkpoint(api)
    assert fixtures.read_connection(api, connection["id"])["status"] == "SUSPENDED"
    stale_read = fixtures.read_shipment(api, shipment["id"])
    assert stale_read["data_freshness"] == "STALE"
    # Prior-epoch quality 83 with the stale multiplier: round(120 * 1.17 * 1.5) = 211.
    assert stale_read["eta_confidence_halfwidth_minutes"] == 211

    fixtures.set_clock(api, "2026-09-05T04:05:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-05T04:05:00Z", completeness=100)
    resumed = get_success_data(api.resume_connection(connection["id"], NETWORK_OPS_HEADERS))
    assert resumed["status"] == "ACTIVE"
    assert resumed["suspended_at"] is None

    restored = fixtures.read_shipment(api, shipment["id"])
    assert restored["data_freshness"] == "FRESH"
    # The resume recomputes without the stale multiplier, but the quality
    # input is the score "as of the last completed ops-run checkpoint" (PRD
    # §3.5) — run 2's 76, published when run 2 completed:
    # round(120 * (1 + (100 - 76)/100)) = round(148.8) = 149.
    assert restored["eta_confidence_halfwidth_minutes"] == 149


def test_immediate_consistency_create_then_read_same_request_state(api):
    """A completion's effects are on the response and on the next read at once.

    PRD: "Completion then rolls up to the facility: `total_dwell_minutes`
    increases by the appointment's dwell, `detention_exposure_minutes`
    increases by its exposure, `appointment_adherence_pct` is recomputed, and
    the facility's `version` bumps."
    PRD: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    Design: Corner/consistency_model/immediate_consistency_create_then_read_same_request_state
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    appointment = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )

    completed = fixtures.complete_appointment(
        api, appointment, carrier["id"], "2026-09-01T10:15:00Z", "2026-09-01T12:15:00Z"
    )
    assert completed["dwell_minutes"] == 120
    assert completed["adherent"] is True
    assert completed["exposure_minutes"] == 0

    read_facility = fixtures.read_facility(api, facility["id"])
    assert read_facility["total_dwell_minutes"] == 120
    assert read_facility["detention_exposure_minutes"] == 0
    assert read_facility["appointment_adherence_pct"] == 100

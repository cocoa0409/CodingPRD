"""Compensating invariants: counts and aggregates restored exactly."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures
from test_helpers.test_users import NETWORK_OPS_HEADERS, make_shipper_rep_headers


def _world_with_proposed_link(api):
    """TESTING connection, PO (PO-3/BK-3/LAX) and a score-1.0 shipment linked."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(
        api, shipper, po_number="PO-3", destination_code="LAX", booking_reference="BK-3"
    )
    shipment = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        tracking_reference="BK-3",
        destination_code="LAX",
        po_reference_claim="PO-3",
    )
    link = fixtures.propose_identity_link(api, shipment, po)
    return shipper, shipment, po, link


# ═══ compensating_invariant / confirm_then_reject_restores_po_confirmed_link_count ═


def test_confirm_then_reject_restores_confirmed_link_count(api):
    """The compensating reject restores the count and the identity state exactly.

    PRD: "Confirming increments the order's `confirmed_link_count` by 1, bumps
    the order's `version`, and moves the shipment's `identity_state` to
    `MATCHED_CONFIRMED` with a `version` bump of its own."
    PRD: "Rejecting a `CONFIRMED` link decrements the order's
    `confirmed_link_count` by 1 and bumps its `version`, restoring the count;
    rejecting a merely `PROPOSED` link touches no count."
    Design: Difficulty/compensating_invariant/confirm_then_reject_restores_po_confirmed_link_count
    """
    shipper, shipment, po, link = _world_with_proposed_link(api)
    headers = make_shipper_rep_headers(shipper["id"])

    assert fixtures.read_purchase_order(api, po["id"])["confirmed_link_count"] == 0

    get_success_data(api.confirm_identity_link(link["id"], headers))
    mid_po = fixtures.read_purchase_order(api, po["id"])
    assert mid_po["confirmed_link_count"] == 1
    assert fixtures.read_shipment(api, shipment["id"])["identity_state"] == "MATCHED_CONFIRMED"

    rejected = get_success_data(api.reject_identity_link(link["id"], headers))
    assert rejected["status"] == "REJECTED"

    final_po = fixtures.read_purchase_order(api, po["id"])
    assert final_po["confirmed_link_count"] == 0
    assert fixtures.read_shipment(api, shipment["id"])["identity_state"] == "UNRESOLVED"


def test_rejecting_a_proposed_link_touches_no_count(api):
    """The PROPOSED branch of the same invariant: nothing to compensate.

    PRD: "rejecting a merely `PROPOSED` link touches no count."
    Design: Difficulty/compensating_invariant/confirm_then_reject_restores_po_confirmed_link_count
    """
    shipper, shipment, po, link = _world_with_proposed_link(api)
    headers = make_shipper_rep_headers(shipper["id"])

    version_before = fixtures.read_purchase_order(api, po["id"])["version"]
    rejected = get_success_data(api.reject_identity_link(link["id"], headers))
    assert rejected["status"] == "REJECTED"

    read_po = fixtures.read_purchase_order(api, po["id"])
    assert read_po["confirmed_link_count"] == 0
    assert read_po["version"] == version_before
    assert fixtures.read_shipment(api, shipment["id"])["identity_state"] == "UNRESOLVED"


# ═══ compensating_invariant / complete_then_void_restores_facility_dwell_and_exposure ═


def _facility_with_booked_appointment(api):
    """Facility ACTIVE, TESTING connection, TRUCKLOAD shipment, one booking."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    appointment = fixtures.book_appointment(
        api, facility, shipment, "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"
    )
    return carrier, shipment, facility, appointment


def test_void_completion_restores_facility_aggregates_exactly(api):
    """Complete adds 210/90; void-completion subtracts the very same amounts.

    PRD: "A completion entered in error is unwound by `NetworkOps` voiding it,
    which requires the appointment to be `COMPLETED`
    (`ERR_APPOINTMENT_INVALID_STATE` otherwise) and moves it to the terminal
    `VOIDED` state with full compensation: the facility's dwell and detention
    aggregates are decremented by exactly the amounts the completion added, the
    adherence percentage is recomputed excluding the voided completion, and the
    facility's `version` bumps again."
    Design: Difficulty/compensating_invariant/complete_then_void_restores_facility_dwell_and_exposure
    """
    carrier, shipment, facility, appointment = _facility_with_booked_appointment(api)

    completed = fixtures.complete_appointment(
        api, appointment, carrier["id"], "2026-09-02T11:30:00Z", "2026-09-02T15:00:00Z"
    )
    assert completed["dwell_minutes"] == 210
    assert completed["adherent"] is False
    assert completed["exposure_minutes"] == 90  # free 120, no grace

    mid = fixtures.read_facility(api, facility["id"])
    assert mid["total_dwell_minutes"] == 210
    assert mid["detention_exposure_minutes"] == 90
    assert mid["appointment_adherence_pct"] == 0

    get_success_data(api.void_completion(appointment["id"], NETWORK_OPS_HEADERS))

    restored = fixtures.read_facility(api, facility["id"])
    assert restored["total_dwell_minutes"] == 0
    assert restored["detention_exposure_minutes"] == 0
    assert restored["appointment_adherence_pct"] is None

    assert fixtures.read_appointment(api, appointment["id"])["status"] == "VOIDED"


def test_void_completion_after_an_adherent_completion_restores_adherence(api):
    """Voiding the only completed appointment drops the percentage back to null.

    PRD: "it is null whenever no appointment has resolved yet. It is recomputed
    on each completion, on each cascade-driven miss, and on each voided
    completion."
    Design: Difficulty/compensating_invariant/complete_then_void_restores_facility_dwell_and_exposure
    """
    carrier, shipment, facility, appointment = _facility_with_booked_appointment(api)

    completed = fixtures.complete_appointment(
        api, appointment, carrier["id"], "2026-09-02T10:30:00Z", "2026-09-02T12:30:00Z"
    )
    assert completed["adherent"] is True
    mid = fixtures.read_facility(api, facility["id"])
    assert mid["appointment_adherence_pct"] == 100
    assert mid["total_dwell_minutes"] == 120

    get_success_data(api.void_completion(appointment["id"], NETWORK_OPS_HEADERS))

    restored = fixtures.read_facility(api, facility["id"])
    assert restored["appointment_adherence_pct"] is None
    assert restored["total_dwell_minutes"] == 0
    assert restored["detention_exposure_minutes"] == 0

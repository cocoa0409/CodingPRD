"""The cyclic connection lifecycle and the shipment's parallel dimensions."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures
from test_helpers import factories as f
from test_helpers.test_users import NETWORK_OPS_HEADERS, make_shipper_rep_headers


def test_expired_testing_window_cycles_back_to_draft_and_resubmission_reopens(api):
    """TESTING auto-resets to DRAFT at the checkpoint after its window expires.

    PRD: "If a connection is still sitting in `TESTING` when its
    `testing_window_end` has passed the current logical time, the next ops-run
    checkpoint resets it to `DRAFT`: both window timestamps and the
    `credential_ref` are cleared to null, and the run's
    `testing_connections_reset` counter is incremented. The carrier must then
    resubmit credentials and negotiate a fresh window."
    Design: Difficulty/non_linear_state_machine/connection_testing_timeout_cycle_back_to_draft
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(
        api,
        carrier,
        channel="TELEMATICS",
        window=("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"),
    )

    fixtures.set_clock(api, "2026-09-03T00:00:00Z")
    run = fixtures.run_checkpoint(api)
    assert run["testing_connections_reset"] == 1

    reset = fixtures.read_connection(api, connection["id"])
    assert reset["status"] == "DRAFT"
    assert reset["credential_ref"] is None
    assert reset["testing_window_start"] is None
    assert reset["testing_window_end"] is None

    # The carrier resubmits credentials and the cycle can start again.
    resubmitted = get_success_data(
        api.submit_credentials(
            connection["id"],
            f.credentials_payload("vault://second-round"),
            fixtures.make_carrier_rep_headers(carrier["id"]),
        )
    )
    assert resubmitted["status"] == "CREDENTIALS_SUBMITTED"
    assert resubmitted["credential_ref"] == "vault://second-round"


def test_active_suspended_active_cycle_via_remediation_heartbeat(api):
    """Resume cycles SUSPENDED back to ACTIVE once remediation is proven.

    PRD: "A successful resume transitions the connection back to `ACTIVE`,
    clears `suspended_at` to null, and restores every shipment of this
    connection whose `data_freshness` was `STALE` back to `FRESH`, recomputing
    each such shipment's ETA without the stale multiplier."
    PRD: "Heartbeats are accepted while the connection is `TESTING`, `ACTIVE`,
    or `SUSPENDED` — this is what makes remediation provable — and rejected
    with `ERR_CONNECTION_INVALID_STATE` from any other state."
    Design: Difficulty/non_linear_state_machine/connection_testing_timeout_cycle_back_to_draft
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)

    fixtures.set_clock(api, "2026-09-03T00:00:00Z")
    suspended = get_success_data(
        api.suspend_connection(
            connection["id"], f.suspend_payload("manual audit"), NETWORK_OPS_HEADERS
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspended_at"] is not None

    # The remediation heartbeat while SUSPENDED is accepted.
    fixtures.set_clock(api, "2026-09-03T00:05:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-03T00:05:00Z", completeness=100)

    resumed = get_success_data(api.resume_connection(connection["id"], NETWORK_OPS_HEADERS))
    assert resumed["status"] == "ACTIVE"
    assert resumed["suspended_at"] is None


# ═══ shipment_parallel_identity_and_tracking_dimensions ═


def _shipment_with_perfect_match(api):
    """A score-1.0 shipment plus its matching purchase order and a PROPOSED link."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(
        api, shipper, po_number="PO-7", destination_code="LAX", booking_reference="BK-7"
    )
    shipment = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        tracking_reference="BK-7",
        destination_code="LAX",
        po_reference_claim="PO-7",
    )
    link = fixtures.propose_identity_link(api, shipment, po)
    return carrier, shipper, shipment, po, link


def test_tracking_and_identity_dimensions_evolve_independently(api):
    """A tracking EXCEPTION cycle neither needs nor perturbs identity confirmation.

    PRD: "`DELAY_REPORTED` moves `IN_TRANSIT` to `EXCEPTION`; `RECOVERED`
    moves `EXCEPTION` back to `IN_TRANSIT`; `OUT_FOR_DELIVERY` moves either
    `IN_TRANSIT` or `EXCEPTION` to `OUT_FOR_DELIVERY`; and `DELIVERED` as the
    effective event terminates the shipment at `DELIVERED` from `BOOKED`,
    `IN_TRANSIT`, or `OUT_FOR_DELIVERY` — the direct `BOOKED` to `DELIVERED`
    path exists for small parcel flows where a delivery scan is the first and
    only event."
    PRD: "the shipment's `identity_state` moves from `UNRESOLVED` to
    `MATCHED_PROVISIONAL`, and the purchase order's `version` bumps by 1 (the
    OCC parent bump — which is precisely what makes a second proposer's stale
    `expected_po_version` fail with `ERR_STALE_VERSION`)."
    PRD: "moves the shipment's `identity_state` to `MATCHED_CONFIRMED` with a
    `version` bump of its own."
    Design: Difficulty/non_linear_state_machine/shipment_parallel_identity_and_tracking_dimensions
    """
    carrier, shipper, shipment, po, link = _shipment_with_perfect_match(api)

    fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T09:00:00Z", "DELAY_REPORTED", delay_minutes=45)

    mid = fixtures.read_shipment(api, shipment["id"])
    assert mid["tracking_status"] == "EXCEPTION"
    assert mid["identity_state"] == "MATCHED_PROVISIONAL"

    confirmed = get_success_data(
        api.confirm_identity_link(link["id"], make_shipper_rep_headers(shipper["id"]))
    )
    assert confirmed["status"] == "CONFIRMED"
    after_confirm = fixtures.read_shipment(api, shipment["id"])
    assert after_confirm["tracking_status"] == "EXCEPTION"
    assert after_confirm["identity_state"] == "MATCHED_CONFIRMED"

    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "RECOVERED", delay_minutes=45)
    final = fixtures.read_shipment(api, shipment["id"])
    assert final["tracking_status"] == "IN_TRANSIT"
    assert final["identity_state"] == "MATCHED_CONFIRMED"
    assert fixtures.read_purchase_order(api, po["id"])["confirmed_link_count"] == 1


def test_identity_rejection_leaves_tracking_untouched(api):
    """Rejecting the only link returns identity to UNRESOLVED while transit rolls on.

    PRD: "Either way the shipment's `identity_state` is re-derived from what
    remains: it falls back from `MATCHED_CONFIRMED` to `MATCHED_PROVISIONAL`
    when the last confirmed link is rejected while other non-rejected links
    remain, drops to `UNRESOLVED` when no non-`REJECTED` links remain at all,
    and returns from `MATCHED_PROVISIONAL` to `UNRESOLVED` when the last
    non-rejected link becomes `REJECTED` with none confirmed."
    Design: Difficulty/non_linear_state_machine/shipment_parallel_identity_and_tracking_dimensions
    """
    carrier, shipper, shipment, po, link = _shipment_with_perfect_match(api)
    fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")

    rejected = get_success_data(
        api.reject_identity_link(link["id"], make_shipper_rep_headers(shipper["id"]))
    )
    assert rejected["status"] == "REJECTED"

    read = fixtures.read_shipment(api, shipment["id"])
    assert read["identity_state"] == "UNRESOLVED"
    assert read["tracking_status"] == "IN_TRANSIT"

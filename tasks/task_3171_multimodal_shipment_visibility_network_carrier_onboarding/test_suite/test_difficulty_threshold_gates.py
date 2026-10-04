"""Boundary precision on the two threshold gates."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiErrorId, fixtures
from test_helpers.test_users import NETWORK_OPS_HEADERS, make_shipper_rep_headers


def _testing_connection_with_two_heartbeats(api, carrier_name, scac, completeness):
    """A TESTING TMS connection scored by two on-time heartbeats over 6000 minutes.

    Window 2026-09-01T00:00 -> 2026-09-05T04:00; expected count
    floor(6000/240) = 25, actual 2, cadence dimension 8.
    """
    carrier = fixtures.create_carrier(api, carrier_name=carrier_name, scac_code=scac)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    fixtures.set_clock(api, "2026-09-01T10:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-01T10:00:00Z", completeness=completeness)
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-02T00:00:00Z", completeness=completeness)
    fixtures.set_clock(api, "2026-09-05T04:00:00Z")
    return connection


# ═══ boundary_precision_check / quality_gate_exactly_seventy_activates_sixty_nine_fails ═


def test_score_exactly_seventy_activates(api):
    """The inclusive quality gate admits a score of exactly 70.

    PRD: "`NetworkOps` may transition a `TESTING` connection to `ACTIVE` only
    when its authoritative `data_quality_score` is at least 70."
    Design: Difficulty/boundary_precision_check/quality_gate_exactly_seventy_activates_sixty_nine_fails
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    connection = _testing_connection_with_two_heartbeats(api, "GateA", "GATA", completeness=80)
    fixtures.run_checkpoint(api)

    read = fixtures.read_connection(api, connection["id"])
    # t = 100, c = 80, d = 8 -> round(40 + 28 + 2) = 70 exactly.
    assert read["data_quality_score"] == 70

    activated = get_success_data(api.activate_connection(connection["id"], NETWORK_OPS_HEADERS))
    assert activated["status"] == "ACTIVE"


def test_score_sixty_nine_is_one_unit_below_the_gate(api):
    """A score of 69 - one below the gate - keeps the connection TESTING.

    PRD: "A connection whose score is below 70 — or whose score is still
    null because no checkpoint has ever scored it — is rejected with
    `ERR_QUALITY_GATE_NOT_MET` (HTTP 422)."
    Design: Difficulty/boundary_precision_check/quality_gate_exactly_seventy_activates_sixty_nine_fails
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    connection = _testing_connection_with_two_heartbeats(api, "GateB", "GATB", completeness=77)
    fixtures.run_checkpoint(api)

    read = fixtures.read_connection(api, connection["id"])
    # t = 100, c = 77, d = 8 -> round(40 + 26.95 + 2) = round(68.95) = 69.
    assert read["data_quality_score"] == 69

    response = api.activate_connection(connection["id"], NETWORK_OPS_HEADERS)
    validate_error(response, ApiErrorId.ERR_QUALITY_GATE_NOT_MET)
    assert fixtures.read_connection(api, connection["id"])["status"] == "TESTING"


# ═══ boundary_precision_check / match_score_exactly_ninety_fails_confirm ═


def _match_boundary_world(api):
    """One PO and two shipments scoring 0.90 and 1.0 against it, both linked."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(
        api, shipper, po_number="PO-9", destination_code="LAX", booking_reference="BK-9"
    )
    ship_a = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        tracking_reference="BK-9",
        destination_code="ORD",
        po_reference_claim="PO-9",
    )
    ship_b = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        tracking_reference="BK-9",
        destination_code="LAX",
        po_reference_claim="PO-9",
    )
    link_a = fixtures.propose_identity_link(api, ship_a, po)
    link_b = fixtures.propose_identity_link(api, ship_b, po)
    return shipper, po, ship_a, ship_b, link_a, link_b


def test_match_score_exactly_ninety_fails_confirm(api):
    """The strict gate rejects exactly 0.90 while 1.0 confirms.

    PRD: "the `match_score` is strictly greater than 0.90 — a score of
    exactly 0.90 is *not* sufficient and is rejected with
    `ERR_MATCH_SCORE_BELOW_THRESHOLD` (HTTP 422)."
    Design: Difficulty/boundary_precision_check/match_score_exactly_ninety_fails_confirm
    """
    shipper, po, ship_a, ship_b, link_a, link_b = _match_boundary_world(api)

    # 0.5 (PO-number) + 0.4 (booking reference) + 0 (destination) = 0.90.
    assert link_a["match_score"] == 0.9
    assert link_b["match_score"] == 1.0

    headers = make_shipper_rep_headers(shipper["id"])
    rejected = api.confirm_identity_link(link_a["id"], headers)
    validate_error(rejected, ApiErrorId.ERR_MATCH_SCORE_BELOW_THRESHOLD)

    confirmed = get_success_data(api.confirm_identity_link(link_b["id"], headers))
    assert confirmed["status"] == "CONFIRMED"
    assert fixtures.read_purchase_order(api, po["id"])["confirmed_link_count"] == 1


def test_failed_confirm_leaves_the_link_proposed_and_the_count_untouched(api):
    """A below-threshold confirm changes nothing on the link or the order.

    PRD: "Confirming increments the order's `confirmed_link_count` by 1, bumps
    the order's `version`, and moves the shipment's `identity_state` to
    `MATCHED_CONFIRMED` with a `version` bump of its own."
    Design: Difficulty/boundary_precision_check/match_score_exactly_ninety_fails_confirm
    """
    shipper, po, ship_a, ship_b, link_a, link_b = _match_boundary_world(api)

    response = api.confirm_identity_link(link_a["id"], make_shipper_rep_headers(shipper["id"]))
    validate_error(response, ApiErrorId.ERR_MATCH_SCORE_BELOW_THRESHOLD)

    read_shipment = fixtures.read_shipment(api, ship_a["id"])
    assert read_shipment["identity_state"] == "MATCHED_PROVISIONAL"
    read_po = fixtures.read_purchase_order(api, po["id"])
    assert read_po["confirmed_link_count"] == 0

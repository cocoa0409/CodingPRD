"""Service complaints, emergency service orders, and their cascades (PRD §3.5, §2.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SHIPPER_ADA,
    SHIPPER_GAL,
    api_client,
    assert_eso,
    create_merger,
    decide_merger_payload,
    escalate,
    file_service_complaint,
    get_carrier_data,
    get_merger_data,
    list_carrier_eso_data,
    register_carrier,
    register_merger_pair,
    set_clock,
    setup_escalated_service_complaint,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]


class TestEscalationCascade:
    def test_escalation_cascade_puts_merger_on_service_hold(self):
        """PRD §3.5: "Hop 2: the order becoming `ACTIVE` flips the carrier's
        `compliance_standing` to `PROBATION`. Hop 3: `PROBATION` on the
        acquiring carrier sets `service_review_hold` to true on that carrier's
        `COMMENT_PERIOD` merger applications, which then blocks the `APPROVED`
        outcome at merger decision time with `ERR_MERGER_SERVICE_HOLD`."
        PRD §3.5: "an emergency service order is created in `ACTIVE` status,
        carrying the `carrier_id` and `service_complaint_id` copied from the
        complaint, the supplied `directive`, an `issued_at` stamped from the
        logical clock at issuance, and an `expires_at` exactly 60 days after
        `issued_at`."

        Design: Difficulty/transitive_cascade/escalation_cascade_puts_merger_on_service_hold
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(acquirer["id"], target["id"])
        sc = file_service_complaint(acquirer["id"], issue_type="CAR_SUPPLY")

        eso = escalate(sc["id"],
                       directive="Directing CSXT to restore car supply within 72 hours")
        assert_eso(eso)
        assert eso["status"] == "ACTIVE"
        # Issued at the 2026-09-01T00:00:00Z clock default; +60 days.
        assert eso["expires_at"] == "2026-10-31T00:00:00Z"
        assert get_carrier_data(acquirer["id"])["compliance_standing"] == "PROBATION"
        assert get_merger_data(merger["id"])["service_review_hold"] is True

        set_clock("2026-10-16T00:00:00Z")  # comment window closed; ESO active
        resp = api_client.decide_merger_application(
            merger["id"], decide_merger_payload("APPROVED"), BOARD)
        validate_error(resp, ApiErrorId.ERR_MERGER_SERVICE_HOLD)
        assert get_merger_data(merger["id"])["status"] == "COMMENT_PERIOD"

    def test_resolve_cascade_lifts_eso_and_unblocks_approval(self):
        """PRD §3.5: "Resolving from `ESCALATED` fires a cascade: the linked
        emergency service order, if still `ACTIVE`, becomes `LIFTED`; with no
        remaining `ACTIVE` order for the carrier, the carrier's
        `compliance_standing` recomputes to `GOOD`; and that return to `GOOD`
        clears `service_review_hold` on the carrier's `COMMENT_PERIOD` merger
        applications, unblocking the `APPROVED` outcome there (§3.6)."

        Design: Difficulty/transitive_cascade/resolve_cascade_lifts_eso_and_unblocks_approval
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(acquirer["id"], target["id"])
        sc, eso = setup_escalated_service_complaint(
            acquirer["id"], issue_type="CAR_SUPPLY")
        assert get_merger_data(merger["id"])["service_review_hold"] is True

        resolved = validate_success(
            api_client.resolve_service_complaint(sc["id"], {}, BOARD))
        assert resolved["status"] == "RESOLVED"
        esos, _ = list_carrier_eso_data(acquirer["id"])
        assert esos[0]["status"] == "LIFTED"
        assert get_carrier_data(acquirer["id"])["compliance_standing"] == "GOOD"
        assert get_merger_data(merger["id"])["service_review_hold"] is False

        set_clock("2026-10-16T00:00:00Z")
        decided = validate_success(api_client.decide_merger_application(
            merger["id"], decide_merger_payload("APPROVED"), BOARD))
        assert decided["status"] == "APPROVED"


class TestEsoCapacity:
    def test_second_active_eso_on_same_carrier_rejected(self):
        """PRD §3.5: "provided no other emergency service order is `ACTIVE`
        for the same carrier; the closed-interval capacity is one active order
        per carrier, and a second escalation is rejected with
        `ERR_ESO_ALREADY_ACTIVE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/second_active_eso_on_same_carrier_rejected
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc1 = file_service_complaint(carrier["id"], issue_type="CAR_SUPPLY")
        sc2 = file_service_complaint(
            carrier["id"], shipper_id=SHIPPER_ADA, issue_type="DELAY",
            territory_code="MIDWEST")
        eso1 = escalate(sc1["id"], directive="Restore car supply within 72 hours")
        assert eso1["status"] == "ACTIVE"

        resp = api_client.escalate_service_complaint(
            sc2["id"], {"directive": "Expedite unit trains"}, BOARD)
        validate_error(resp, ApiErrorId.ERR_ESO_ALREADY_ACTIVE)
        esos, meta = list_carrier_eso_data(carrier["id"])
        assert meta["total_count"] == 1
        assert esos[0]["id"] == eso1["id"]
        assert esos[0]["status"] == "ACTIVE"


class TestEsoExpiry:
    def test_eso_expires_at_sixty_day_boundary(self):
        """PRD §2.5: "whenever the clock reaches or passes the `expires_at` of
        an emergency service order in `ACTIVE` status, the order transitions
        to `EXPIRED`, the affected carrier's compliance standing is
        recomputed, and the merger review holds that depended on the order are
        cleared."
        PRD §2.5: "This expiry is evaluated **lazily on any read or write** in
        the system, not only when the clock is set: any request processed at a
        clock reading at or beyond an active order's `expires_at` observes and
        applies the expiry before responding."

        Design: Corner/state_machines/eso_expires_at_sixty_day_boundary
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc, eso = setup_escalated_service_complaint(carrier["id"])
        assert eso["expires_at"] == "2026-10-31T00:00:00Z"

        set_clock("2026-10-30T23:59:59Z")
        esos, _ = list_carrier_eso_data(carrier["id"])
        assert esos[0]["status"] == "ACTIVE"

        set_clock("2026-10-31T00:00:00Z")
        esos, _ = list_carrier_eso_data(carrier["id"])
        assert esos[0]["status"] == "EXPIRED"
        assert get_carrier_data(carrier["id"])["compliance_standing"] == "GOOD"

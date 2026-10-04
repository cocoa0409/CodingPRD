"""Reparation ledger: payments, reversal, reopening, and closure (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SHIPPER_ADA,
    SHIPPER_BOB,
    api_client,
    assert_award_ledger_invariant,
    decide_upheld,
    determine_dominance,
    file_rate_complaint,
    get_carrier_data,
    get_rate_complaint_data,
    list_evidence_data,
    make_carrier_operator_headers,
    make_shipper_headers,
    register_carrier,
    register_carrier_with_adequate_history,
    register_carrier_with_inadequate_2025,
    reparation_event_payload,
    setup_evidentiary_complaint,
    submit_evidence_as_carrier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]
FRACTIONAL_SHIPMENTS = [
    {"shipment_ref": "S-A", "tons": 10.515},
    {"shipment_ref": "S-B", "tons": 5.005},
]


class TestLedgerInvariant:
    def test_reparation_ledger_invariant_under_payment_and_reversal(self):
        """PRD §3.4: "`award_paid_cents` is the sum of all `PAYMENT` events,
        `award_outstanding_cents` is always exactly `award_granted_cents`
        minus `award_paid_cents`, and both are response-visible on the
        complaint at all times."
        PRD §3.4: "The reversal sets `award_granted_cents` to the paid amount
        (which the precondition pins at 0), sets `award_outstanding_cents` to
        0, and sets `award_status` to `REVERSED`."
        PRD §3.4: "whenever a decided complaint's `award_status` becomes
        `PAID` or `REVERSED`, the complaint transitions from `DECIDED` to
        `CLOSED`, a terminal state, and the carrier's
        `reparation_exposure_cents` is recomputed — a closed complaint no
        longer contributes to exposure."

        Design: Difficulty/compensating_invariant/reparation_ledger_invariant_under_payment_and_reversal
        """
        carrier = register_carrier_with_adequate_history()
        rc1, _ = setup_evidentiary_complaint(carrier["id"])
        rc1 = decide_upheld(rc1["id"], FRACTIONAL_SHIPMENTS)
        rc2, _ = setup_evidentiary_complaint(
            carrier["id"], complaint_overrides={"commodity": "CORN"})
        rc2 = decide_upheld(rc2["id"], FRACTIONAL_SHIPMENTS)
        assert rc1["award_granted_cents"] == 128817
        assert rc2["award_granted_cents"] == 128817
        assert (get_carrier_data(carrier["id"])["reparation_exposure_cents"]
                == 257634)

        operator = make_carrier_operator_headers(carrier["id"])
        for amount in (50000, 28817, 50000):
            paid = validate_success(api_client.post_reparation_event(
                rc1["id"], reparation_event_payload("PAYMENT", amount), operator))
            assert_award_ledger_invariant(paid)
        assert paid["award_granted_cents"] == 128817
        assert paid["award_paid_cents"] == 128817
        assert paid["award_outstanding_cents"] == 0
        assert paid["award_status"] == "PAID"
        assert paid["status"] == "CLOSED"

        reversed_rc2 = validate_success(api_client.post_reparation_event(
            rc2["id"], reparation_event_payload("REVERSAL"), BOARD))
        assert reversed_rc2["award_granted_cents"] == 0
        assert reversed_rc2["award_paid_cents"] == 0
        assert reversed_rc2["award_outstanding_cents"] == 0
        assert reversed_rc2["award_status"] == "REVERSED"
        assert reversed_rc2["status"] == "CLOSED"
        # Grant/reversal pair conserved the carrier ledger exactly.
        assert (get_carrier_data(carrier["id"])["reparation_exposure_cents"] == 0)


class TestLedgerGuards:
    def test_state_precondition_beats_fiscal_overpayment(self):
        """PRD §2.6: "Every request is validated against the following
        seventeen checks in strict priority order. The first check that fails
        determines the response; no later check is evaluated."
        PRD §3.4: "Settlement proceeds through reparation events posted
        against a complaint in `DECIDED` status — a complaint in any other
        state, including `CLOSED`, rejects the posting with
        `ERR_COMPLAINT_NOT_DECIDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_fiscal_overpayment
        """
        carrier = register_carrier()
        complaint = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=17999,
            relief_sought_cents=50000000)
        dismissed = determine_dominance(complaint["id"])
        assert dismissed["status"] == "DISMISSED"

        # Violates the state gate (priority 6) and the fiscal bound (priority
        # 17, 999999 > outstanding 0); the earlier state error must surface.
        resp = api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 999999),
            make_carrier_operator_headers(carrier["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_DECIDED)
        after = get_rate_complaint_data(complaint["id"])
        assert after["status"] == "DISMISSED"
        assert after["award_status"] == "NONE"

    def test_overpayment_rejected_and_state_unchanged(self):
        """PRD §3.4: "A `PAYMENT` must carry an `amount_cents` of at least 1
        (otherwise `ERR_INVALID_REQUEST`, HTTP 400) and no greater than the
        current `award_outstanding_cents` (otherwise
        `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, HTTP 402)."

        Design: Corner/errors/overpayment_rejected_and_state_unchanged
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decide_upheld(complaint["id"])
        operator = make_carrier_operator_headers(carrier["id"])
        first = validate_success(api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 1), operator))
        assert first["award_outstanding_cents"] == 79499

        resp = api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 79500), operator)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)
        after = get_rate_complaint_data(complaint["id"])
        assert after["award_paid_cents"] == 1
        assert after["award_outstanding_cents"] == 79499
        assert after["award_status"] == "PARTIALLY_PAID"
        assert after["status"] == "DECIDED"

    def test_reversal_after_payment_rejected(self):
        """PRD §3.4: "A `REVERSAL` requires that `award_paid_cents` is exactly
        0 — if anything has been paid the reversal is rejected with
        `ERR_AWARD_HAS_PAYMENTS` (HTTP 409)."

        Design: Corner/errors/reversal_after_payment_rejected
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decide_upheld(complaint["id"])
        validate_success(api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 1),
            make_carrier_operator_headers(carrier["id"])))

        resp = api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("REVERSAL"), BOARD)
        validate_error(resp, ApiErrorId.ERR_AWARD_HAS_PAYMENTS)
        after = get_rate_complaint_data(complaint["id"])
        assert after["award_outstanding_cents"] == 79499
        assert after["award_status"] == "PARTIALLY_PAID"


class TestReopen:
    def test_reopen_on_closed_complaint_rejected(self):
        """PRD §3.4: "A decided complaint may also be **reopened** by the
        owning `Shipper` — the complaint's `shipper_id` must equal the
        caller's `X-User-ID`, and the complaint must be in `DECIDED`
        (`ERR_COMPLAINT_NOT_DECIDED`)."

        Design: Corner/state_machines/reopen_on_closed_complaint_rejected
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decide_upheld(complaint["id"])
        paid = validate_success(api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 79500),
            make_carrier_operator_headers(carrier["id"])))
        assert paid["status"] == "CLOSED"
        assert paid["award_status"] == "PAID"

        resp = api_client.reopen_rate_complaint(
            complaint["id"], {}, make_shipper_headers(SHIPPER_ADA))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_DECIDED)
        assert get_rate_complaint_data(complaint["id"])["status"] == "CLOSED"

    def test_shipper_cannot_reopen_others_complaint_rejected(self):
        """PRD §3.4: "A decided complaint may also be **reopened** by the
        owning `Shipper` — the complaint's `shipper_id` must equal the
        caller's `X-User-ID`, and the complaint must be in `DECIDED`
        (`ERR_COMPLAINT_NOT_DECIDED`)."

        Design: Corner/rbac/shipper_cannot_reopen_others_complaint_rejected
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decide_upheld(complaint["id"])

        resp = api_client.reopen_rate_complaint(
            complaint["id"], {}, make_shipper_headers(SHIPPER_BOB))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_rate_complaint_data(complaint["id"])["status"] == "DECIDED"

    def test_complaint_reopen_cycle_supersedes_evidence(self):
        """PRD §3.4: "Reopening moves the complaint to `REOPENED`, supersedes
        the record — every evidence submission with `review_status` `VERIFIED`
        becomes `SUPERSEDED` — and resets the `adjudicated_rvc_ratio` to
        null."
        PRD §3.4: "The complaint then sits in `REOPENED` until the next
        evidentiary submission arrives, which returns it to
        `EVIDENTIARY_PHASE` (§3.3), from which a fresh merits decision may be
        taken."

        Design: Difficulty/non_linear_state_machine/complaint_reopen_cycle_supersedes_evidence
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, ev1 = setup_evidentiary_complaint(carrier["id"])
        decided = decide_upheld(complaint["id"])
        assert decided["prescribed_rate_cents_per_ton"] == 11550
        assert decided["award_granted_cents"] == 79500

        reopened = validate_success(api_client.reopen_rate_complaint(
            complaint["id"], {}, make_shipper_headers(SHIPPER_ADA)))
        assert reopened["status"] == "REOPENED"
        assert reopened["adjudicated_rvc_ratio"] is None
        # Decision figures survive reopening until a new decide.
        assert reopened["award_granted_cents"] == 79500
        superseded = [e for e in list_evidence_data(complaint["id"])
                      if e["id"] == ev1["id"]]
        assert superseded and superseded[0]["review_status"] == "SUPERSEDED"

        ev2 = submit_evidence_as_carrier(
            complaint["id"], carrier["id"],
            reference_rate_cents_per_ton=13000,
            verified_variable_cost_cents_per_ton=10800)
        assert ev2["review_status"] == "SUBMITTED"
        assert (get_rate_complaint_data(complaint["id"])["status"]
                == "EVIDENTIARY_PHASE")


class TestPaymentOwnership:
    def test_carrier_cannot_pay_others_reparation_rejected(self):
        """PRD §3.4: "The two event types belong to different parties: a
        `CarrierOperator` posts `PAYMENT` events, and only on complaints
        against the operator's own carrier; a `BoardAdjudicator` posts
        `REVERSAL` events."
        PRD §2.6: "a `CarrierOperator` caller's `X-User-ID` must equal the
        carrier the request acts on — the `carrier_id` path or body parameter,
        the `acquiring_carrier_id` of the merger being created or amended or
        given a plan, or the `carrier_id` of the complaint receiving evidence
        or a payment."

        Design: Corner/rbac/carrier_cannot_pay_others_reparation_rejected
        """
        carrier = register_carrier_with_inadequate_2025()
        other = register_carrier(
            carrier_code="BNRZ", legal_name="Big Northern Railroad",
            carrier_class="I", base_route_miles=800)
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decide_upheld(complaint["id"])

        resp = api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 1000),
            make_carrier_operator_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert (get_rate_complaint_data(complaint["id"])["award_outstanding_cents"]
                == 79500)

"""Prescribed-rate computation, relief caps, and the reparation award (PRD §3.3-3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SHIPPER_ADA,
    api_client,
    assert_award_ledger_invariant,
    decide_rate_complaint_payload,
    decide_upheld,
    file_finding,
    file_rate_complaint,
    get_carrier_data,
    get_rate_complaint_data,
    make_carrier_operator_headers,
    make_shipper_headers,
    register_carrier,
    register_carrier_with_adequate_history,
    register_carrier_with_inadequate_2025,
    reparation_event_payload,
    setup_evidentiary_complaint,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]
FRACTIONAL_SHIPMENTS = [
    {"shipment_ref": "S-A", "tons": 10.515},
    {"shipment_ref": "S-B", "tons": 5.005},
]


class TestPrescriptionFloor:
    def test_prescription_floor_switches_with_revenue_adequacy(self):
        """PRD §3.3: "First, the floor rate is the verified variable cost
        multiplied by the floor factor, rounded half up to whole cents per
        ton. Second, the prescribed rate is the smaller of the challenged rate
        and the larger of the reference rate and the floor rate — the floor
        binds exactly when it exceeds the reference rate, and the prescription
        never exceeds the challenged rate."
        PRD §3.3: "an adequacy floor drawn from a **different entity** — the
        contested-year revenue adequacy finding, contributing a floor factor
        of 1.0000 when that finding is `ADEQUATE` and 1.1000 when it is
        `INADEQUATE`"

        Design: Difficulty/combinatorial_formula/prescription_floor_switches_with_revenue_adequacy
        """
        adequate = register_carrier_with_adequate_history()
        inadequate = register_carrier_with_inadequate_2025(
            carrier_code="BNRZ", legal_name="Big Northern Railroad",
            base_route_miles=800)

        rc_a, _ = setup_evidentiary_complaint(adequate["id"])
        rc_b, _ = setup_evidentiary_complaint(inadequate["id"])

        decided_a = decide_upheld(rc_a["id"])
        decided_b = decide_upheld(rc_b["id"])
        # ADEQUATE: floor 10500 < reference 11200 -> floor does not bind.
        assert decided_a["prescribed_rate_cents_per_ton"] == 11200
        assert decided_a["relief_granted_cents"] == 8300000
        assert decided_a["award_granted_cents"] == 83000
        # INADEQUATE: floor round(10500*1.1000)=11550 > reference -> binds.
        assert decided_b["prescribed_rate_cents_per_ton"] == 11550
        assert decided_b["relief_granted_cents"] == 7950000
        assert decided_b["award_granted_cents"] == 79500

    def test_reparation_rounds_per_shipment_then_sums(self):
        """PRD §3.4: "For each shipment, the overcharge multiplied by that
        shipment's tonnage is rounded half up to **whole cents first**; the
        award `award_granted_cents` is then the integer sum of those
        per-shipment amounts."
        PRD §3.4: "This rounding order is pinned: rounding each shipment and
        then summing is the only correct procedure, and summing first and
        rounding once is the forbidden alternative — the two diverge on
        fractional tonnage."

        Design: Difficulty/combinatorial_formula/reparation_rounds_per_shipment_then_sums
        """
        carrier = register_carrier_with_adequate_history()
        complaint, _ = setup_evidentiary_complaint(
            carrier["id"], complaint_overrides={"commodity": "COAL"})
        decided = decide_upheld(complaint["id"], FRACTIONAL_SHIPMENTS)
        assert decided["prescribed_rate_cents_per_ton"] == 11200
        # diff 8300: round(8300*10.515)=87275 + round(8300*5.005)=41542.
        assert decided["award_granted_cents"] == 128817
        assert decided["award_paid_cents"] == 0
        assert decided["award_outstanding_cents"] == 128817
        assert decided["award_status"] == "GRANTED"
        assert_award_ledger_invariant(decided)
        assert (get_carrier_data(carrier["id"])["reparation_exposure_cents"]
                == 128817)


class TestReliefCap:
    def test_relief_cap_applied_on_three_benchmark(self):
        """PRD §3.3: "Fourth, `relief_granted_cents` is the raw relief capped
        at the track's cap: 100000000 cents on the `THREE_BENCHMARK` track,
        400000000 cents on the `SIMPLIFIED_SAC` track, and no cap at all on
        the `FULL_SAC` track."

        Design: Corner/calculations/relief_cap_applied_on_three_benchmark
        """
        carrier = register_carrier_with_adequate_history()
        complaint, _ = setup_evidentiary_complaint(
            carrier["id"],
            complaint_overrides={"annual_tons": 20000,
                                 "relief_sought_cents": 100000000},
            evidence_overrides={"submission_type": "THREE_BENCHMARK_PACKET"})
        assert complaint["track"] == "THREE_BENCHMARK"
        decided = decide_upheld(complaint["id"])
        assert decided["prescribed_rate_cents_per_ton"] == 11200
        # Raw relief 8300 * 20000 = 166000000 clamps to the track cap.
        assert decided["relief_granted_cents"] == 100000000
        # The award comes from the shipments and carries no track cap.
        assert decided["award_granted_cents"] == 83000


class TestDecisionOutcomes:
    def test_upheld_with_zero_award_autocloses(self):
        """PRD §3.4: "An award of 0 has a further consequence: the complaint
        passes through `DECIDED` and auto-advances to `CLOSED` in the same
        decision, because the closure rule below already sees a `PAID`
        award."
        PRD §3.4: "When the `shipments` array is omitted or empty, the award
        is 0."

        Design: Corner/state_machines/upheld_with_zero_award_autocloses
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decided = decide_upheld(complaint["id"], shipments=[])
        assert decided["status"] == "CLOSED"
        assert decided["decision_outcome"] == "UPHELD"
        assert decided["award_granted_cents"] == 0
        assert decided["award_status"] == "PAID"
        assert (get_carrier_data(carrier["id"])["reparation_exposure_cents"] == 0)

    def test_rejected_complaint_stays_decided_and_reopenable(self):
        """PRD §3.4: "When the outcome is `REJECTED`, `decision_outcome` is
        recorded as `REJECTED`, `award_status` remains `NONE`, and the
        complaint rests in `DECIDED`, where it remains reopenable."

        Design: Corner/state_machines/rejected_complaint_stays_decided_and_reopenable
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        resp = api_client.decide_rate_complaint(
            complaint["id"], decide_rate_complaint_payload("REJECTED"), BOARD)
        decided = validate_success(resp)
        assert decided["status"] == "DECIDED"
        assert decided["decision_outcome"] == "REJECTED"
        assert decided["award_status"] == "NONE"
        assert decided["prescribed_rate_cents_per_ton"] is None

        reopen_resp = api_client.reopen_rate_complaint(
            complaint["id"], {}, make_shipper_headers(SHIPPER_ADA))
        reopened = validate_success(reopen_resp)
        assert reopened["status"] == "REOPENED"
        assert reopened["adjudicated_rvc_ratio"] is None

    def test_decide_response_reflects_new_state_immediately(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/decide_response_reflects_new_state_immediately
        """
        carrier = register_carrier_with_inadequate_2025()
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        resp = api_client.decide_rate_complaint(
            complaint["id"],
            decide_rate_complaint_payload(
                "UPHELD", [{"shipment_ref": "S-1", "tons": 10.000}]),
            BOARD,
        )
        decided = validate_success(resp)
        # The decide response itself carries the mutation — no re-read needed.
        assert decided["status"] == "DECIDED"
        assert decided["decision_outcome"] == "UPHELD"
        assert decided["prescribed_rate_cents_per_ton"] == 11550
        assert decided["award_granted_cents"] == 79500
        assert decided["award_outstanding_cents"] == 79500


class TestReparationExposure:
    def test_reparation_exposure_reconciles_on_decide_and_close(self):
        """PRD §2.9: "`reparation_exposure_cents` is the sum of
        `award_outstanding_cents` over the carrier's rate complaints in
        `DECIDED` status. It starts at 0; a decision upholding a complaint
        adds the granted award; a complaint leaving `DECIDED` — closing on
        full payment or reversal — stops contributing."

        Design: Corner/cross_cutting_layers/reparation_exposure_reconciles_on_decide_and_close
        """
        carrier = register_carrier_with_inadequate_2025()
        assert get_carrier_data(carrier["id"])["reparation_exposure_cents"] == 0
        complaint, _ = setup_evidentiary_complaint(carrier["id"])
        decided = decide_upheld(complaint["id"])
        assert decided["award_granted_cents"] == 79500
        assert (get_carrier_data(carrier["id"])["reparation_exposure_cents"]
                == 79500)

        pay_resp = api_client.post_reparation_event(
            complaint["id"], reparation_event_payload("PAYMENT", 79500),
            make_carrier_operator_headers(carrier["id"]))
        paid = validate_success(pay_resp)
        assert paid["award_status"] == "PAID"
        assert paid["status"] == "CLOSED"
        assert (get_carrier_data(carrier["id"])["reparation_exposure_cents"] == 0)

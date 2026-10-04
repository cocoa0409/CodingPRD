"""Evidence review and the rate-decision regulatory gates (PRD §3.3, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    SHIPPER_ADA,
    api_client,
    create_evidence_payload,
    create_rate_complaint_payload,
    decide_rate_complaint_payload,
    decide_upheld,
    determine_dominance,
    file_finding,
    file_rate_complaint,
    get_carrier_data,
    get_rate_complaint_data,
    make_carrier_operator_headers,
    register_carrier,
    setup_evidentiary_complaint,
    submit_evidence_as_shipper,
    validate_error,
    verify_evidence_payload,
    verify_submission,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]


class TestDualVariantRatio:
    def test_alleged_vs_adjudicated_rvc_flips_market_dominance(self):
        """PRD §3.3: "The adjudicated variant of the revenue-to-variable-cost
        ratio uses the same formula as the alleged variant but over the
        verified cost figure, and the two diverge whenever verified cost
        differs from alleged cost; the adjudicated variant alone gates the
        merits outcomes below."
        PRD §2.6: "Outcomes `UPHELD` and `REJECTED` require an
        `adjudicated_rvc_ratio` of at least 1.8000, failing which
        `ERR_MARKET_DOMINANCE_ABSENT` (HTTP 409)"

        Design: Difficulty/dual_variant_calc/alleged_vs_adjudicated_rvc_flips_market_dominance
        """
        carrier = register_carrier()
        file_finding(carrier["id"])  # 2025 finding present
        complaint = file_rate_complaint(carrier["id"], shipper_id=SHIPPER_ADA)
        assert complaint["alleged_rvc_ratio"] == pytest.approx(1.9500)
        determine_dominance(complaint["id"])
        evidence = submit_evidence_as_shipper(
            complaint["id"], SHIPPER_ADA,
            reference_rate_cents_per_ton=15000,
            verified_variable_cost_cents_per_ton=11000)
        verify_submission(evidence["id"])
        complaint = get_rate_complaint_data(complaint["id"])
        assert complaint["adjudicated_rvc_ratio"] == pytest.approx(1.7727)

        resp = api_client.decide_rate_complaint(
            complaint["id"],
            decide_rate_complaint_payload(
                "UPHELD", [{"shipment_ref": "S-1", "tons": 10.000}]),
            BOARD,
        )
        validate_error(resp, ApiErrorId.ERR_MARKET_DOMINANCE_ABSENT)
        complaint = get_rate_complaint_data(complaint["id"])
        assert complaint["status"] == "EVIDENTIARY_PHASE"


class TestRevenueAdequacyGate:
    def test_decide_blocked_without_contested_year_finding(self):
        """PRD §2.6: "Any decision call on a rate complaint — whatever the
        requested `outcome` — requires that a revenue adequacy finding exist
        for the defendant carrier and the complaint's `contested_fiscal_year`,
        failing which `ERR_REVENUE_ADEQUACY_FINDING_REQUIRED` (HTTP 409)."
        PRD §3.3: "an adequacy floor drawn from a **different entity** — the
        contested-year revenue adequacy finding, contributing a floor factor
        of 1.0000 when that finding is `ADEQUATE` and 1.1000 when it is
        `INADEQUATE`"

        Design: Difficulty/cross_entity_state_dependency/decide_blocked_without_contested_year_finding
        """
        carrier = register_carrier()  # no findings filed
        complaint, _evidence = setup_evidentiary_complaint(carrier["id"])
        assert complaint["adjudicated_rvc_ratio"] == pytest.approx(1.8571)

        resp = api_client.decide_rate_complaint(
            complaint["id"],
            decide_rate_complaint_payload(
                "UPHELD", [{"shipment_ref": "S-1", "tons": 10.000}]),
            BOARD,
        )
        validate_error(resp, ApiErrorId.ERR_REVENUE_ADEQUACY_FINDING_REQUIRED)
        assert (get_rate_complaint_data(complaint["id"])["status"]
                == "EVIDENTIARY_PHASE")

        file_finding(carrier["id"])  # single-year 1000 bps -> INADEQUATE
        assert get_carrier_data(carrier["id"])["revenue_adequacy_status"] == "INADEQUATE"

        decided = decide_upheld(complaint["id"])
        assert decided["status"] == "DECIDED"
        # INADEQUATE floor: round(10500 * 1.1000) = 11550 binds over 11200.
        assert decided["prescribed_rate_cents_per_ton"] == 11550
        assert decided["relief_granted_cents"] == 7950000
        assert decided["award_granted_cents"] == 79500


class TestEvidenceReview:
    def test_verify_evidence_twice_rejected(self):
        """PRD §3.3: "Review is a one-way door: only a submission still in
        `SUBMITTED` may be reviewed, and a second review attempt is rejected
        with `ERR_EVIDENCE_ALREADY_REVIEWED` (HTTP 409)."

        Design: Corner/state_machines/verify_evidence_twice_rejected
        """
        carrier = register_carrier()
        complaint = file_rate_complaint(carrier["id"], relief_sought_cents=50000000)
        determine_dominance(complaint["id"])
        evidence = submit_evidence_as_shipper(complaint["id"], SHIPPER_ADA)
        verify_submission(evidence["id"])

        resp = api_client.verify_evidence(
            evidence["id"], verify_evidence_payload("VERIFIED"), BOARD)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_ALREADY_REVIEWED)
        complaint = get_rate_complaint_data(complaint["id"])
        assert complaint["adjudicated_rvc_ratio"] == pytest.approx(1.8571)

    def test_verify_evidence_not_found_returns_404(self):
        """PRD §2.6: "a missing evidence submission `ERR_EVIDENCE_NOT_FOUND`"
        (HTTP 404, path existence check)."

        Design: Corner/entities/verify_evidence_not_found_returns_404
        """
        resp = api_client.verify_evidence(
            NON_EXISTENT_ID, verify_evidence_payload("VERIFIED"), BOARD)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_FOUND)

    def test_evidence_party_role_mismatch_rejected(self):
        """PRD §2.6: "On evidence submissions, `submitted_by_party` must be
        `SHIPPER` for a `Shipper` caller and `CARRIER` for a `CarrierOperator`
        caller. Any mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §2.6: "a `CarrierOperator` caller's `X-User-ID` must equal the
        carrier the request acts on — the `carrier_id` path or body parameter,
        the `acquiring_carrier_id` of the merger being created or amended or
        given a plan, or the `carrier_id` of the complaint receiving evidence
        or a payment."

        Design: Corner/validations/evidence_party_role_mismatch_rejected
        """
        carrier = register_carrier()
        other = register_carrier(
            carrier_code="BNRZ", legal_name="Big Northern Railroad",
            carrier_class="I", base_route_miles=800)
        complaint = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=20000,
            annual_tons=100, relief_sought_cents=50000000)
        determine_dominance(complaint["id"])

        # CarrierOperator cannot claim the SHIPPER party.
        resp1 = api_client.submit_evidence(
            complaint["id"],
            create_evidence_payload(
                submission_type="REBUTTAL", submitted_by_party="SHIPPER",
                reference_rate_cents_per_ton=13000,
                verified_variable_cost_cents_per_ton=10800),
            make_carrier_operator_headers(carrier["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        # A different carrier's operator cannot file on this complaint.
        resp2 = api_client.submit_evidence(
            complaint["id"],
            create_evidence_payload(
                submission_type="REBUTTAL", submitted_by_party="CARRIER",
                reference_rate_cents_per_ton=13000,
                verified_variable_cost_cents_per_ton=10800),
            make_carrier_operator_headers(other["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestDismissalGate:
    def test_dismiss_with_adjudicated_dominance_rejected(self):
        """PRD §2.6: "outcome `DISMISSED` requires the ratio to be absent or
        below 1.8000, failing which `ERR_MARKET_DOMINANCE_PRESENT`
        (HTTP 409)."

        Design: Corner/errors/dismiss_with_adjudicated_dominance_rejected
        """
        carrier = register_carrier()
        file_finding(carrier["id"])
        complaint, _evidence = setup_evidentiary_complaint(carrier["id"])
        assert complaint["adjudicated_rvc_ratio"] == pytest.approx(1.8571)

        resp = api_client.decide_rate_complaint(
            complaint["id"], {"outcome": "DISMISSED"}, BOARD)
        validate_error(resp, ApiErrorId.ERR_MARKET_DOMINANCE_PRESENT)
        assert (get_rate_complaint_data(complaint["id"])["status"]
                == "EVIDENTIARY_PHASE")

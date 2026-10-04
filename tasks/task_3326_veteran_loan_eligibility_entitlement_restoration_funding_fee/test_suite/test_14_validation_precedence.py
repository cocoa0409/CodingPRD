"""Difficulty tests: validation-order pairs where the PRD pins which check fires
first when two failures coexist."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_standard_service_period,
    create_coe_request_payload,
    create_loan_payload,
    create_service_period_payload,
    create_veteran_payload,
    get_loan,
    setup_closed_loan_with_refinance,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCloseStateMasksFiscal:
    def test_close_state_masks_fiscal_entitlement_failure(self, api):
        """PRD §2.11: "Generic state checks come after shape validation: an
        action attempted on a resource in a state that does not permit it is
        rejected with `ERR_INVALID_STATE`. Only then do the domain-specific
        business rules run, in the orders given in §3"
        PRD §3.4: "closing from any other underwriting state is rejected with
        `ERR_LOAN_NOT_CLOSABLE` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/close_state_masks_fiscal_entitlement_failure
        """
        # Loan amount $80,000,000 exceeds 4x the bonus capacity even at zero
        # charge, so the fiscal gate would also fail — but the state gate must
        # answer first.
        ctx = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Mask"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=80000000,
                                    down_payment_cents=0),
            ),
            expected_status=201,
        )
        decision = validate_success(
            api.create_underwriting_decision(loan["id"], {
                # residual = 450000-350000 = 100000 < required 100300
                # (SOUTH, family 4) -> DENIED per PRD §3.4, leaving the
                # loan un-closable so the state gate masks the fiscal one.
                "gross_monthly_income_cents": 450000,
                "new_housing_payment_cents": 350000,
                "other_obligations_annual_cents": [],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert decision["outcome"] == "DENIED"

        validate_error(
            api.close_loan(loan["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            }),
            ApiErrorId.ERR_LOAN_NOT_CLOSABLE, expected_status=409,
        )
        assert get_loan(loan["id"])["closing_status"] == "NOT_CLOSED"

    def test_close_submitted_loan_rejected_not_closable(self, api):
        """PRD §3.4: "Closing is the fiscal heart of the system, performed by a
        `LoanOfficer` on a loan whose `underwriting_status` is `APPROVED` —
        closing from any other underwriting state is rejected with
        `ERR_LOAN_NOT_CLOSABLE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/close_state_masks_fiscal_entitlement_failure
        """
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 20000000})
        validate_error(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            }),
            ApiErrorId.ERR_LOAN_NOT_CLOSABLE, expected_status=409,
        )
        assert get_loan(ctx["loan"]["id"])["closing_status"] == "NOT_CLOSED"


class TestCoeSafetyMasksReferential:
    def test_coe_issue_safety_masks_referential_mismatch(self, api):
        """PRD §2.11: "for COE issuance, the discharge gate before the
        service-length gate before the service-period ownership check"
        PRD §3.2: "First, the discharge gate: the veteran's
        `character_of_discharge` must be `HONORABLE` or `GENERAL`, else the
        request is rejected with `ERR_DISCHARGE_INELIGIBLE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/coe_issue_safety_masks_referential_mismatch
        """
        bad_vet = validate_success(
            api.create_veteran(create_veteran_payload(
                full_name="V Safe", character_of_discharge="DISHONORABLE")),
            expected_status=201,
        )
        coe = validate_success(
            api.create_coe_request(bad_vet["id"], create_coe_request_payload()),
            expected_status=201,
        )
        other_vet = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Other")),
            expected_status=201,
        )
        other_period = validate_success(
            api.create_service_period(
                other_vet["id"],
                create_service_period_payload(
                    start_date="2020-01-10", end_date="2022-06-15"),
            ),
            expected_status=201,
        )
        # Both the discharge gate and the ownership gate fail; the discharge
        # gate is named first in the PRD's ordering.
        validate_error(
            api.issue_coe(coe["id"],
                          payload={"service_period_ids": [other_period["id"]]}),
            ApiErrorId.ERR_DISCHARGE_INELIGIBLE, expected_status=422,
        )
        coes, _meta = validate_paginated(api.list_coe_requests(bad_vet["id"]))
        assert coes[0]["status"] == "REQUESTED"

    def test_coe_issue_service_gate_before_referential(self, api):
        """PRD §2.11: "for COE issuance, the discharge gate before the
        service-length gate before the service-period ownership check"
        PRD §3.2: "Second, the service-length gate: the veteran's
        `total_qualifying_service_days` must reach at least 90 days when the
        `service_category` is `REGULAR_MILITARY` and at least 180 days when it
        is `RESERVES_NATIONAL_GUARD`, else the request is rejected with
        `ERR_INSUFFICIENT_SERVICE` (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/coe_issue_safety_masks_referential_mismatch
        """
        short_vet = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Short")),
            expected_status=201,
        )
        coe = validate_success(
            api.create_coe_request(short_vet["id"], create_coe_request_payload()),
            expected_status=201,
        )
        other_vet = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Other2")),
            expected_status=201,
        )
        other_period = validate_success(
            api.create_service_period(
                other_vet["id"],
                create_service_period_payload(
                    start_date="2020-01-10", end_date="2022-06-15"),
            ),
            expected_status=201,
        )
        # Discharge passes; service-length (0 < 90) and ownership both fail;
        # the service-length gate is named before the ownership check.
        validate_error(
            api.issue_coe(coe["id"],
                          payload={"service_period_ids": [other_period["id"]]}),
            ApiErrorId.ERR_INSUFFICIENT_SERVICE, expected_status=422,
        )


class TestRefinanceSeasoningMasksNtb:
    def test_refinance_seasoning_masks_ntb_failure(self, api):
        """PRD §2.11: "for refinance evaluation, the seasoning gate before the
        net-tangible-benefit determination"
        PRD §3.8: "Seasoning of at least 210 days is required — 210 exactly
        passes — and a shortfall is rejected with `ERR_SEASONING_NOT_MET`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/refinance_seasoning_masks_ntb_failure
        """
        # Clock stays at the startup default 2026-09-01; first payment due
        # 2026-03-01 -> seasoning 184 < 210. Rate reduction 0.40 < 0.50 also
        # fails NTB; the seasoning gate answers first.
        ctx = setup_closed_loan_with_refinance(
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
            refinance_overrides={
                "refinance_type": "IRRRL", "new_rate_percent": 6.1,
                "new_rate_type": "FIXED", "flat_costs_cents": 150000,
            },
            price_cents=20000000,
        )
        validate_error(
            api.evaluate_refinance(ctx["refinance"]["id"]),
            ApiErrorId.ERR_SEASONING_NOT_MET, expected_status=422,
        )
        requests, _meta = validate_paginated(
            api.list_refinance_requests(ctx["loan"]["id"]))
        assert requests[0]["status"] == "SUBMITTED"

    def test_refinance_seasoning_failure_is_not_an_error_response_for_ntb(self, api):
        """PRD §3.8: "Evaluation is an `Underwriter` action that applies the
        seasoning gate first and the net-tangible-benefit determination second,
        in that order."
        PRD §3.8: "Only when seasoning passes does the NTB determination run,
        and its outcome is a state transition, never an error"

        Design: Difficulty/priority_pair_validation_conflict/refinance_seasoning_masks_ntb_failure
        """
        ctx = setup_closed_loan_with_refinance(
            clock_iso="2026-10-01T00:00:00Z",
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
            refinance_overrides={
                "refinance_type": "IRRRL", "new_rate_percent": 6.1,
                "new_rate_type": "FIXED", "flat_costs_cents": 150000,
            },
            price_cents=20000000,
        )
        # Seasoning passes (214 days); NTB rate leg fails (0.40 < 0.50) and the
        # outcome is the persisted REJECTED transition, not an error response.
        evaluated = validate_success(
            api.evaluate_refinance(ctx["refinance"]["id"]))
        assert evaluated["seasoning_days"] == 214
        assert evaluated["ntb_rate_satisfied"] is False
        assert evaluated["ntb_satisfied"] is False
        assert evaluated["status"] == "REJECTED"

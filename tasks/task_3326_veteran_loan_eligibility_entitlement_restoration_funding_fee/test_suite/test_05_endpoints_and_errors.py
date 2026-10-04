"""Corner tests for action endpoints (fee refund, appraisal selector, occupancy)
and the error envelope."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_appraiser_payload,
    create_coe_request_payload,
    create_loan_payload,
    create_service_period_payload,
    create_veteran_payload,
    get_funding_fee_assessment,
    get_occupancy_certificate,
    make_appraiser_headers,
    setup_closed_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_error,
    validate_success,
)


class TestFundingFeeRefundFlow:
    def test_funding_fee_refund_full_flow(self, api):
        """PRD §3.4: "The refund sets `refunded_cents` to the `collected_cents`,
        moves the assessment to its terminal `REFUNDED` status, and recomputes
        `exempt` true."
        PRD §3.4: "the funding fee assessment moves from `ASSESSED` to
        `COLLECTED` with `collected_cents` set to the `assessed_fee_cents`"

        Design: Corner/endpoints/funding_fee_refund_full_flow
        """
        # $200,000 price, 0 down, FIRST_USE -> 2.15% of 20000000 = 430000.
        ctx = setup_closed_loan(price_cents=20000000)
        fee = get_funding_fee_assessment(ctx["loan"]["id"])
        assert fee["status"] == "COLLECTED"
        assert fee["assessed_fee_cents"] == 430000
        assert fee["collected_cents"] == 430000

        refunded = validate_success(
            api.refund_funding_fee(fee["id"], disability_evidence=True))
        assert refunded["status"] == "REFUNDED"
        assert refunded["refunded_cents"] == 430000
        assert refunded["refunded_cents"] == refunded["collected_cents"]

        # Already REFUNDED: a second refund attempt is not refundable.
        validate_error(
            api.refund_funding_fee(fee["id"], disability_evidence=True),
            ApiErrorId.ERR_FEE_NOT_REFUNDABLE, expected_status=409,
        )


class TestAppraisalSelectorPolicy:
    def test_appraisal_assignment_selector_ranks_least_loaded(self, api):
        """PRD §3.5: "Within the candidate set, the policy ranks by
        `open_assignment_count` ascending and breaks ties by appraiser
        `created_at` ascending; the chosen appraiser's `open_assignment_count`
        increments."

        Design: Corner/endpoints/appraisal_assignment_selector_ranks_least_loaded
        """
        app_l = validate_success(
            api.create_appraiser(create_appraiser_payload(name="App L")),
            expected_status=201,
        )
        app_m = validate_success(
            api.create_appraiser(create_appraiser_payload(name="App M")),
            expected_status=201,
        )
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Sel"})
        loan_a = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        first = validate_success(
            api.create_appraisal_request(loan_a["id"]), expected_status=201)
        # Both at 0 open assignments; earliest created_at wins.
        assert first["status"] == "ASSIGNED"
        assert first["appraiser_id"] == app_l["id"]

        loan_b = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=21000000),
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_appraisal_request(loan_b["id"]), expected_status=201)
        # App L now holds 1 open assignment; App M at 0 wins the ranking.
        assert second["status"] == "ASSIGNED"
        assert second["appraiser_id"] == app_m["id"]


class TestOccupancySatisfied:
    def test_occupancy_satisfied_within_deadline(self, api):
        """PRD §3.6: "The `OccupancyCertificate` created at close starts
        `CERTIFIED`, with its `certification_date` equal to the loan's
        `closing_date` and its `move_in_deadline` sixty days after the closing
        date, the deadline day itself included."
        PRD §3.6: "When the move-in date is on or before the deadline, the
        certificate becomes `SATISFIED`."

        Design: Corner/endpoints/occupancy_satisfied_within_deadline
        """
        ctx = setup_closed_loan(price_cents=20000000)
        occ = get_occupancy_certificate(ctx["loan"]["id"])
        assert occ["status"] == "CERTIFIED"
        # 2026-03-10 + 60 days inclusive = 2026-05-09.
        assert str(occ["move_in_deadline"]).startswith("2026-05-09")

        verified = validate_success(
            api.verify_occupancy(occ["id"], move_in_date="2026-05-09"))
        assert verified["status"] == "SATISFIED"
        assert verified["exception_type"] == "NONE"


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error" and
        `data.error_id` / `data.message`; "The `meta` object for error responses
        contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.8: "`ERR_LOAN_NOT_FOUND` for a loan"

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_loan(NON_EXISTENT_UUID)
        error = validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FOUND,
                               expected_status=404)
        assert isinstance(error.get("message"), str) and error["message"]
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"]

"""Corner tests for state-machine terminal lockdowns and invalid transitions."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    close_loan,
    create_service_period_payload,
    create_veteran_payload,
    get_appraisal,
    get_entitlement_account,
    get_loan,
    list_repairs,
    make_appraiser_headers,
    setup_closed_loan,
    setup_loan_with_repairs_required,
    setup_loan_with_value_issued_appraisal,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCoeTerminalLockdown:
    def test_coe_issued_terminal_lockdown(self, api):
        """PRD §3.2: "On success the certificate becomes `ISSUED` — its terminal
        state"
        PRD §2.11: "an action attempted on a resource in a state that does not
        permit it is rejected with `ERR_INVALID_STATE`"

        Design: Corner/state_machines/coe_issued_terminal_lockdown
        """
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Term"})
        coe_id = ctx["coe"]["id"]
        assert ctx["coe"]["status"] == "ISSUED"

        validate_error(api.deny_coe(coe_id), ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)
        validate_error(api.reconsider_coe(coe_id), ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)
        validate_error(api.issue_coe(coe_id), ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)

        coes, _meta = validate_paginated(api.list_coe_requests(ctx["veteran"]["id"]))
        assert coes[0]["status"] == "ISSUED"


class TestAppraisalTerminalLockdown:
    def test_appraisal_value_issued_terminal_lockdown(self, api):
        """PRD §3.5: "the appraisal must be in `ASSIGNED` or `REPAIRS_REQUIRED`;
        a report from anyone else, or on an appraisal in any other state, is
        rejected with `ERR_APPRAISAL_NOT_ASSIGNED` (HTTP 409)"
        PRD §3.5: "it moves the appraisal to its terminal `VALUE_ISSUED` state"

        Design: Corner/state_machines/appraisal_value_issued_terminal_lockdown
        """
        ctx = setup_loan_with_value_issued_appraisal(
            price_cents=20000000,
            loan_overrides={"purchase_price_cents": 20000000},
        )
        appraisal_id = ctx["appraisal"]["id"]
        resp = api.submit_appraisal_report(
            appraisal_id,
            {"outcome": "VALUE_ISSUED", "appraised_value_cents": 21000000},
            headers=make_appraiser_headers(ctx["appraiser"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_NOT_ASSIGNED, expected_status=409)

        appraisal = get_appraisal(appraisal_id)
        assert appraisal["appraised_value_cents"] == 20000000
        assert appraisal["report_round"] == 1


class TestCloseIdempotency:
    def test_close_idempotency_second_close_invalid_state(self, api):
        """PRD §2.11: "an action attempted on a resource in a state that does not
        permit it is rejected with `ERR_INVALID_STATE`"
        PRD §3.4: "`entitlement_charged_cents` becomes the smaller of one quarter
        of the loan amount (rounded half up to whole cents) and the account's
        `remaining_with_bonus_cents`"

        Design: Corner/state_machines/close_idempotency_second_close_invalid_state
        """
        ctx = setup_closed_loan(price_cents=20000000)
        loan_id = ctx["loan"]["id"]
        validate_error(
            api.close_loan(loan_id, {
                "closing_date": "2026-03-11",
                "first_payment_due_date": "2026-05-01",
            }),
            ApiErrorId.ERR_INVALID_STATE, expected_status=409,
        )
        account = get_entitlement_account(ctx["veteran"]["id"])
        assert account["total_charged_cents"] == 5000000
        loan = get_loan(loan_id)
        assert str(loan["closing_date"]).startswith("2026-03-10")


class TestRecordPayoffInvalidState:
    def test_record_payoff_from_not_closed_invalid_state(self, api):
        """PRD §3.4: "recording payoff on anything other than a `CLOSED` loan is
        `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/record_payoff_from_not_closed_invalid_state
        """
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 20000000},
            veteran_overrides={"full_name": "V Pay"},
        )
        resp = api.record_payoff(ctx["loan"]["id"], "SALE")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        loan = get_loan(ctx["loan"]["id"])
        assert loan["closing_status"] == "NOT_CLOSED"


class TestRepairVerifyPrecondition:
    def test_repair_verify_precondition_wrong_appraiser(self, api):
        """PRD §3.5: "The assigned appraiser — and only that appraiser — then
        moves a `COMPLETED` repair to the terminal `VERIFIED` state."
        PRD §3.5: "a report from anyone else, or on an appraisal in any other
        state, is rejected with `ERR_APPRAISAL_NOT_ASSIGNED` (HTTP 409)"

        Design: Corner/state_machines/repair_verify_precondition_wrong_appraiser
        """
        ctx = setup_loan_with_repairs_required()
        repair = ctx["repairs"][0]
        # Second appraiser registered after the first; the assignment policy
        # already gave the appraisal to the first (least-loaded, then earliest).
        other_appraiser = validate_success(
            api.create_appraiser({"name": "App T5b", "region": "SOUTH"}),
            expected_status=201,
        )
        assert ctx["appraisal"]["appraiser_id"] == ctx["appraiser"]["id"]

        completed = validate_success(api.complete_repair(repair["id"]))
        assert completed["status"] == "COMPLETED"

        validate_error(
            api.verify_repair(
                repair["id"], headers=make_appraiser_headers(other_appraiser["id"])
            ),
            ApiErrorId.ERR_APPRAISAL_NOT_ASSIGNED, expected_status=409,
        )

        verified = validate_success(
            api.verify_repair(
                repair["id"], headers=make_appraiser_headers(ctx["appraiser"]["id"])
            )
        )
        assert verified["status"] == "VERIFIED"

"""Corner coverage: validations that must produce a specific error identifier."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    assert_port_request,
    create_account,
    create_activated_line,
    create_draft_port_request,
    create_line_addition,
    get_line,
    get_port_request,
    resubmit_port_request,
    review_line_addition,
    setup_rejected_port_request,
)

CARE = TEST_USERS["customer_service_headers"]


class TestResubmissionPolicyErrors:
    def test_a_code_marked_final_refuses_the_resubmission(self, api):
        """PRD §3.2: "First, the most recent `rejection_code` must resolve to a catalog
        row whose `resubmission_allowed` is true; if the carrier marked that objection as
        final, the resubmission is refused with `ERR_RESUBMISSION_NOT_ALLOWED` (422)."

        Design: Corner/validations/resubmission_not_allowed_code_is_refused
        """
        account, line, request = setup_rejected_port_request(
            "4155555101", "ACCT_LOCKED",
            code_overrides={"resubmission_allowed": False, "retry_after_hours": 0},
            request_overrides={
                "transfer_pin": "5151",
                "account_number_at_losing_carrier": "ACC51",
                "requested_cutover_at": "2026-09-20T00:00:00Z",
            },
        )
        advance_clock("2026-09-05T00:00:00Z")

        response = api_client.resubmit_port_request(
            request["id"],
            {"transfer_pin": "5151", "account_number_at_losing_carrier": "ACC51"},
            CARE,
        )

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_RESUBMISSION_NOT_ALLOWED"

    def test_the_final_code_leaves_the_request_rejected(self, api):
        """PRD §3.2: "the carrier marked that objection as final"
        PRD §3.2: "Recording the rejection appends a new entry to the request's
        append-only `rejections` log."

        Design: Corner/validations/resubmission_not_allowed_code_is_refused
        """
        account, line, request = setup_rejected_port_request(
            "4155555102", "ACCT_LOCKED",
            code_overrides={"resubmission_allowed": False, "retry_after_hours": 0},
            request_overrides={
                "transfer_pin": "5151",
                "account_number_at_losing_carrier": "ACC51",
                "requested_cutover_at": "2026-09-20T00:00:00Z",
            },
        )
        advance_clock("2026-09-05T00:00:00Z")
        api_client.resubmit_port_request(
            request["id"],
            {"transfer_pin": "5151", "account_number_at_losing_carrier": "ACC51"},
            CARE,
        )

        assert get_port_request(request["id"])["request_state"] == "REJECTED"

    def test_resubmitting_inside_the_cooling_off_window_is_refused(self, api):
        """PRD §3.2: "Second, the cooling-off period must have elapsed: the current logical
        clock instant must be at or after `last_rejection_at` plus the catalog row's
        `retry_after_hours`, and resubmitting early is refused with
        `ERR_RESUBMISSION_COOLDOWN` (409)."

        Design: Corner/validations/resubmission_inside_cooldown_is_refused
        """
        account, line, request = setup_rejected_port_request(
            "4155555201", "PORT_BLOCK",
            code_overrides={"resubmission_allowed": True, "retry_after_hours": 48},
            request_overrides={
                "transfer_pin": "5252",
                "account_number_at_losing_carrier": "ACC52",
                "requested_cutover_at": "2026-09-20T00:00:00Z",
            },
        )
        advance_clock("2026-09-03T00:00:00Z")

        response = api_client.resubmit_port_request(
            request["id"],
            {"transfer_pin": "5252", "account_number_at_losing_carrier": "ACC52"},
            CARE,
        )

        assert response.json()["data"]["error_id"] == "ERR_RESUBMISSION_COOLDOWN"

    def test_once_the_cooling_off_period_elapses_the_resubmission_is_accepted(self, api):
        """PRD §3.2: "the current logical clock instant must be at or after
        `last_rejection_at` plus the catalog row's `retry_after_hours`"
        PRD §3.2: "A successful resubmission sets `request_state` to `RESUBMITTED`"

        Design: Corner/validations/resubmission_inside_cooldown_is_refused
        """
        account, line, request = setup_rejected_port_request(
            "4155555202", "PORT_BLOCK",
            code_overrides={"resubmission_allowed": True, "retry_after_hours": 48},
            request_overrides={
                "transfer_pin": "5252",
                "account_number_at_losing_carrier": "ACC52",
                "requested_cutover_at": "2026-09-20T00:00:00Z",
            },
        )
        advance_clock("2026-09-04T00:00:00Z")

        accepted = resubmit_port_request(request)

        assert accepted["request_state"] == "RESUBMITTED"
        assert_port_request(accepted)


class TestDepositShortfall:
    def test_one_cent_short_of_the_required_deposit_is_refused(self, api):
        """PRD §3.6: "the account's `existing_deposit_cents` — the deposit already on file,
        which defaults to 0 at account creation — must be at or above the request's
        computed `required_deposit_cents`, and a shortfall is refused with
        `ERR_DEPOSIT_REQUIRED` (402)."

        Design: Corner/validations/deposit_shortfall_is_fiscal_rejection
        """
        account = create_account(payment_history_score=700, existing_deposit_cents=9999)
        request = create_line_addition(account["id"], 1)

        response = api_client.review_line_addition_request(
            request["id"], {"decision": "APPROVE"}, TEST_USERS["credit_analyst_headers"]
        )

        assert response.status_code == 402
        assert response.json()["data"]["error_id"] == "ERR_DEPOSIT_REQUIRED"

    def test_a_deposit_exactly_equal_to_the_requirement_is_approved(self, api):
        """PRD §3.6: "must be at or above the request's computed
        `required_deposit_cents`"
        PRD §3.6: "`CLASS_B` requires 10 000 cents"

        Design: Corner/validations/deposit_shortfall_is_fiscal_rejection
        """
        account = create_account(payment_history_score=700, existing_deposit_cents=10000)
        request = create_line_addition(account["id"], 1)

        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["required_deposit_cents"] == 10000
        assert decided["request_state"] == "APPROVED"


class TestTransferPinAgreement:
    def test_pin_that_disagrees_with_the_draft_is_refused(self, api):
        """PRD §3.1: "Given that the line is unprotected, the four-digit `transfer_pin`
        must also match the `account_number_at_losing_carrier` supplied on the same call —
        a mismatch in either the format or the pairing is rejected with
        `ERR_TRANSFER_PIN_MISMATCH` (422)."

        Design: Corner/validations/transfer_pin_format_and_reference_must_agree
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155555301", billing_mode="PREPAID")
        request = create_draft_port_request(
            line, transfer_pin="6161", account_number_at_losing_carrier="ACC53",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )

        response = api_client.submit_port_request(
            request["id"],
            {"transfer_pin": "9999", "account_number_at_losing_carrier": "ACC53"},
            CARE,
        )

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_TRANSFER_PIN_MISMATCH"

    def test_the_refused_submit_leaves_the_request_drafted(self, api):
        """PRD §3.1: "a mismatch in either the format or the pairing is rejected with
        `ERR_TRANSFER_PIN_MISMATCH` (422)"
        PRD §3.1: "A `PortRequest` is born in `request_state` `DRAFT`"

        Design: Corner/validations/transfer_pin_format_and_reference_must_agree
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155555301", billing_mode="PREPAID")
        request = create_draft_port_request(
            line, transfer_pin="6161", account_number_at_losing_carrier="ACC53",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        api_client.submit_port_request(
            request["id"],
            {"transfer_pin": "9999", "account_number_at_losing_carrier": "ACC53"},
            CARE,
        )

        assert get_port_request(request["id"])["request_state"] == "DRAFT"

    def test_a_pin_that_is_not_four_digits_is_refused(self, api):
        """PRD §3.2: "the supplied `transfer_pin` must be exactly four digits and must
        match the `account_number_at_losing_carrier` supplied on the same call (otherwise
        `ERR_TRANSFER_PIN_MISMATCH`, 422)."

        Design: Corner/validations/transfer_pin_format_and_reference_must_agree
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155555302", billing_mode="PREPAID")
        request = create_draft_port_request(
            line, transfer_pin="6161", account_number_at_losing_carrier="ACC53",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )

        response = api_client.submit_port_request(
            request["id"],
            {"transfer_pin": "61", "account_number_at_losing_carrier": "ACC53"},
            CARE,
        )

        assert response.json()["data"]["error_id"] == "ERR_TRANSFER_PIN_MISMATCH"
        assert get_line(line["id"])["number_status"] == "ASSIGNED"
"""Cross-entity state dependencies: a program's closure gated on a completed
portfolio transfer, and account servicing gated on the program's terminal state.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_program_with_account,
    setup_closed_program,
    apply_principal,
    post_purchase,
    program_summary,
    propose_transfer,
    accept_transfer,
    execute_transfer,
    close_program,
    roll_into_winding_down,
    make_cardholder_headers,
)


class TestProgramCloseRequiresCompletedTransfer:

    def test_program_closes_only_after_the_transfer_completes(self, api, admin_headers):
        """PRD §3.2: "Moving from `WINDING_DOWN` to the terminal `CLOSED` state
        requires that every wind-down transfer with this `program_id` has reached
        `COMPLETED`, and requires an expected-version match." PRD §3.9: "the first
        hop cascades every account on the program to `TRANSFERRED`, the program's
        `program_status` is set to `WINDING_DOWN`, and the program's version
        increments".

        Design: Difficulty/cross_entity_state_dependency/program_close_requires_completed_portfolio_transfer
        """
        _partner, _agreement, program, account, transfer = setup_closed_program(api)

        assert transfer["transfer_status"] == "COMPLETED"
        assert program["program_status"] == "CLOSED"
        refreshed_account = validate_success(api.get_account(account["id"], admin_headers), 200)
        assert refreshed_account["account_status"] == "TRANSFERRED"

    def test_closure_before_the_transfer_completes_is_refused(self, api, admin_headers):
        """PRD §3.2: "Moving from `WINDING_DOWN` to the terminal `CLOSED` state
        requires that every wind-down transfer with this `program_id` has reached
        `COMPLETED`". PRD §3.2: "The sequence from partnership termination to
        final closure is therefore: negotiate and accept transfer terms, execute
        the transfer so the accounts cascade to `TRANSFERRED`, let the program
        sit in `WINDING_DOWN`, close the program".

        Design: Difficulty/cross_entity_state_dependency/program_close_requires_completed_portfolio_transfer
        """
        partner, agreement, program, account = setup_program_with_account(api)
        get_success_data(
            api.post_payment(account["id"], 100, make_cardholder_headers(account["id"]))
        )
        winding = roll_into_winding_down(api, program["id"], program["version"])
        transfer = propose_transfer(api, program["id"], "RETAILER")
        accept_transfer(api, transfer["id"], "RETAILER")

        refused = api.close_credit_program(program["id"], winding["version"], admin_headers)
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE, 409)

        still = validate_success(api.get_credit_program(program["id"], admin_headers), 200)
        assert still["program_status"] == "WINDING_DOWN", (
            "the refused close left the program in WINDING_DOWN"
        )


class TestAccountServicingRejectedWhenProgramClosed:

    def test_purchase_on_a_closed_program_is_refused(self, api, admin_headers):
        """PRD §3.4: "an account may be serviced only while its program's
        `program_status` is not `CLOSED`. Posting a purchase, submitting an
        application, and applying an account payment are all refused with
        `ERR_PROGRAM_CLOSED` (HTTP 422) once the account's or application's
        program has reached the terminal closed state."

        Design: Difficulty/cross_entity_state_dependency/account_transaction_rejected_when_program_closed
        """
        _partner, _agreement, program, account, _transfer = setup_closed_program(api)

        resp = api.create_transaction(
            {"account_id": account["id"], "merchant_name": "Ferrow Kibble",
             "amount_cents": 5000, "transaction_channel": "IN_STORE",
             "promo_requested": False},
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED, 422)
        rows, _meta = validate_paginated(
            api.list_transactions(admin_headers, {"account_id": account["id"]})
        )
        assert rows == [], "a refused purchase leaves no transaction behind"

    def test_the_program_reads_back_closed_with_a_transferred_account(self, api, admin_headers):
        """PRD §3.4: "an account may be serviced only while its program's
        `program_status` is not `CLOSED`." PRD §3.9: "the first hop cascades
        every account on the program to `TRANSFERRED`".

        Design: Difficulty/cross_entity_state_dependency/account_transaction_rejected_when_program_closed
        """
        _partner, _agreement, program, account, transfer = setup_closed_program(api)

        summary = validate_success(api.get_program_summary(program["id"], admin_headers), 200)
        assert summary["program_status"] == "CLOSED"
        assert transfer["transfer_status"] == "COMPLETED"
        refreshed = validate_success(api.get_account(account["id"], admin_headers), 200)
        assert refreshed["account_status"] == "TRANSFERRED"
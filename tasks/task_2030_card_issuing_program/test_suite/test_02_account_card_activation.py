"""Card activation preconditions and account close precondition (corner:
state_machines)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_open_account,
    create_program_with_bin_and_publish,
    get_pending_activation_token_value,
    get_success_data,
    issue_card_for_account,
    set_card_pin,
    validate_error,
)

PM = TEST_USERS["program_manager_headers"]
CH = TEST_USERS["cardholder_ops_headers"]
PA = TEST_USERS["platform_admin_headers"]
FC = TEST_USERS["finance_controller_headers"]


def _program_with_open_account(code: str):
    get_success_data(api_client.set_clock("2026-08-01T00:00:00Z", PA))
    prog, _bin = create_program_with_bin_and_publish(code)
    acct = create_open_account(prog["id"], f"{code}-A1", daily_spend_cap_cents=10000)
    return prog, acct


class TestCardActivationPreconditions:
    def test_card_activate_requires_set_pin(self, api):
        """PRD §3.4: "and the card's `pin_status` must be `SET`
        (`ERR_PIN_NOT_SET`)".

        Design: Corner/state_machines/card_activate_requires_set_pin
        """
        _prog, acct = _program_with_open_account("P-PIN")
        card = issue_card_for_account(acct["id"])
        token = get_pending_activation_token_value(card["id"])
        # Card is ISSUED with pin_status UNSET → activation must fail PIN check.
        resp = api.activate_card(card["id"], token, CH)
        validate_error(resp, ApiErrorId.ERR_PIN_NOT_SET.value)

    def test_card_activate_with_invalid_token_rejected(self, api):
        """PRD §3.4: "a `PENDING` activation token must exist for the card whose
        `expires_at` is still ahead of the clock, and the request's
        `activation_token` must match that token's `token_value` — either
        failure yields `ERR_ACTIVATION_TOKEN_INVALID`".

        Design: Corner/state_machines/card_activate_with_invalid_token_rejected
        """
        _prog, acct = _program_with_open_account("P-IT2")
        card = issue_card_for_account(acct["id"])
        set_card_pin(card["id"], "1234")
        resp = api.activate_card(card["id"], "bogus-token-xyz", CH)
        validate_error(resp, ApiErrorId.ERR_ACTIVATION_TOKEN_INVALID.value)

    def test_card_activation_requires_account_open_suspended(self, api):
        """PRD §3.4: "Card activation (`ISSUED` → `ACTIVE`) is performed by
        `CardholderOps` and enforces its checks in order: the owning account
        must be `OPEN` (`ERR_ACCOUNT_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/card_activation_requires_account_open
        """
        _prog, acct = _program_with_open_account("P-VISA-13")
        card = issue_card_for_account(acct["id"])
        set_card_pin(card["id"], "1111")
        # Suspend the account so it is no longer OPEN.
        get_success_data(api.suspend_account(acct["id"], PM))
        token = get_pending_activation_token_value(card["id"])
        resp = api.activate_card(card["id"], token, CH)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value)

    def test_card_activation_rejected_after_suspend_resume_suspend(self, api):
        """PRD §3.4: "Card activation (`ISSUED` → `ACTIVE`) is performed by
        `CardholderOps` and enforces its checks in order: the owning account
        must be `OPEN` (`ERR_ACCOUNT_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/card_activation_requires_account_open
        """
        _prog, acct = _program_with_open_account("P-VISA-13B")
        card = issue_card_for_account(acct["id"])
        set_card_pin(card["id"], "2222")
        # Cycle the account OPEN→SUSPENDED→OPEN→SUSPENDED; the final state
        # (SUSPENDED) is what must drive the rejection.
        get_success_data(api.suspend_account(acct["id"], PM))
        get_success_data(api.resume_account(acct["id"], PM))
        get_success_data(api.suspend_account(acct["id"], PM))
        token = get_pending_activation_token_value(card["id"])
        resp = api.activate_card(card["id"], token, CH)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value)


class TestAccountClosePrecondition:
    def test_account_close_with_nonzero_balance_rejected(self, api):
        """PRD §3.4: "Closing an account — from either `OPEN` or `SUSPENDED` —
        requires `available_balance_cents` to be exactly zero, failing with
        `ERR_ACCOUNT_BALANCE_NONZERO` otherwise".

        Design: Corner/state_machines/account_close_with_nonzero_balance_rejected
        """
        _prog, acct = _program_with_open_account("P-AB")
        get_success_data(api.fund_account(acct["id"], 5000, FC))
        resp = api.close_account(acct["id"], PM)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_BALANCE_NONZERO.value)

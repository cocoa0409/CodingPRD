"""Chargeback lifecycle: filing guards, posting cap, WON/LOST fork, withdraw lock,
INV-CREDIT compensating pair."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_active_ruleset,
    post_txn,
    set_clock,
    get_success_data,
    setup_confirmed_fraud_txn,
)

MANAGER = TEST_USERS["manager_headers"]
RECOVERY = TEST_USERS["recovery_headers"]


def _setup_approve_txn(api, account_number, pan_token, amount_cents, merchant_id):
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account(account_number)
    card = create_card(acct["id"], pan_token)
    create_active_ruleset()
    txn = post_txn(card["id"], amount_cents, merchant_id, channel="CNP", origin_country="US")
    assert txn["decision"] == "APPROVE", f"setup txn must APPROVE, got {txn['decision']}"
    return acct, card, txn


def test_chargeback_on_declined_txn_rejected(api):
    """PRD §3.7: "Filing requires the transaction's `decision` to be `APPROVE`, else
    `ERR_TXN_NOT_DISPUTABLE` (HTTP 409)".

    Design: Corner/validations/chargeback_on_declined_txn_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-V11", cardholder_name="Val Eleven")
    card = create_card(acct["id"], "PT-V11")
    create_active_ruleset()
    txn = post_txn(card["id"], 100000, "M-V11", channel="CNP", origin_country="RU")
    assert txn["decision"] == "DECLINE"
    resp = api.create_chargeback_case(
        {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 1000},
        RECOVERY,
    )
    validate_error(resp, ApiErrorId.ERR_TXN_NOT_DISPUTABLE, expected_status=409)


def test_duplicate_chargeback_rejected(api):
    """PRD §3.7: "at most one non-terminal chargeback may exist per transaction,
    else `ERR_CHARGEBACK_EXISTS` (HTTP 409)"; "A case may be withdrawn only from
    `FILED`"; "`RESOLVED_WON`, `RESOLVED_LOST`, and `WITHDRAWN` are terminal."

    Design: Corner/errors/duplicate_chargeback_rejected
    """
    _acct, _card, txn = _setup_approve_txn(api, "ACCT-ER2", "PT-ER2", 40000, "M-ER2")
    cb1 = get_success_data(
        api.create_chargeback_case(
            {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 5000},
            RECOVERY,
        ),
        expected_status=201,
    )
    dup = api.create_chargeback_case(
        {"auth_transaction_id": txn["id"], "reason_code": "4853", "provisional_credit_cents": 1000},
        RECOVERY,
    )
    validate_error(dup, ApiErrorId.ERR_CHARGEBACK_EXISTS, expected_status=409)

    get_success_data(api.withdraw_chargeback_case(cb1["id"], RECOVERY))
    cb2 = validate_success(
        api.create_chargeback_case(
            {"auth_transaction_id": txn["id"], "reason_code": "4853", "provisional_credit_cents": 1000},
            RECOVERY,
        ),
        expected_status=201,
    )
    assert cb2["cb_status"] == "FILED", "WITHDRAWN is terminal so refiling must succeed"


def test_chargeback_withdraw_after_credit_rejected(api):
    """PRD §3.7: "A case may be withdrawn only from `FILED`, before any credit was
    posted."; "Invalid transitions on this machine ... surface as
    `ERR_CHARGEBACK_INVALID_STATE` rather than the generic state error."

    Design: Corner/state_machines/chargeback_withdraw_after_credit_rejected
    """
    acct, _card, txn = _setup_approve_txn(api, "ACCT-SM6", "PT-SM6", 40000, "M-SM6")
    cb = get_success_data(
        api.create_chargeback_case(
            {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 15000},
            RECOVERY,
        ),
        expected_status=201,
    )
    get_success_data(api.post_provisional_credit(cb["id"], RECOVERY))
    resp = api.withdraw_chargeback_case(cb["id"], RECOVERY)
    validate_error(resp, ApiErrorId.ERR_CHARGEBACK_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_chargeback_case(cb["id"], RECOVERY))
    assert current["cb_status"] == "PROVISIONAL_CREDIT_POSTED"
    account = validate_success(api.get_account(acct["id"], MANAGER))
    assert account["credit_balance_cents"] == 15000


class TestStateBeatsFiscalOnChargebackPost:
    def _setup_withdrawn_over_limit(self, api):
        """Chargeback with provisional 60000 on a 50000 txn, then WITHDRAWN."""
        _acct, _card, txn = _setup_approve_txn(api, "ACCT-PP1", "PT-PP1", 50000, "M-PP1")
        acct = validate_success(api.get_account(_acct["id"], MANAGER))
        cb = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 60000},
                RECOVERY,
            ),
            expected_status=201,
        )
        get_success_data(api.withdraw_chargeback_case(cb["id"], RECOVERY))
        return acct, txn, cb

    def test_state_error_reported_not_fiscal(self, api):
        """PRD §2.6: "state-machine preconditions (priority 7, including the domain
        variants `ERR_CHARGEBACK_INVALID_STATE` ...)" precede "fiscal caps
        (priority 11, `ERR_DUPLICATE_CREDIT` ...)"; "The practical consequence is
        that a state error beats a fiscal cap".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_chargeback_post
        """
        _acct, _txn, cb = self._setup_withdrawn_over_limit(api)
        resp = api.post_provisional_credit(cb["id"], RECOVERY)
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_INVALID_STATE, expected_status=409)

    def test_rejected_posting_leaves_no_side_effect(self, api):
        """PRD §2.6: "later checks are masked by earlier ones"; §3.7: "Posting adds
        the amount to the account's `credit_balance_cents`." — only a successful
        posting mutates the ledger, so the rejected posting leaves the case
        WITHDRAWN and the balance at zero.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_chargeback_post
        """
        acct, _txn, cb = self._setup_withdrawn_over_limit(api)
        api.post_provisional_credit(cb["id"], RECOVERY)
        current = validate_success(api.get_chargeback_case(cb["id"], RECOVERY))
        assert current["cb_status"] == "WITHDRAWN"
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["credit_balance_cents"] == 0


class TestDuplicateCreditEqualityAllowed:
    def test_credits_equal_to_amount_allowed(self, api):
        """PRD §3.7: "the posted amount plus the sum of the transaction's existing
        active chargeback credits plus the `fraud_credit_cents` of any
        `RESOLVED_FRAUD` alerts on that transaction must not exceed the
        transaction's `amount_cents` — equality is allowed — else
        `ERR_DUPLICATE_CREDIT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/duplicate_credit_equality_allowed
        """
        _acct, _card, txn = _setup_approve_txn(api, "ACCT-BP2A", "PT-BP2A", 50000, "M-BP2")
        cb1 = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 50000},
                RECOVERY,
            ),
            expected_status=201,
        )
        posted = validate_success(api.post_provisional_credit(cb1["id"], RECOVERY))
        assert posted["cb_status"] == "PROVISIONAL_CREDIT_POSTED", "50000 == 50000: equality allowed"

    def test_fraud_credit_plus_provisional_over_amount_rejected(self, api):
        """PRD §3.7: "the posted amount plus the sum of the transaction's existing
        active chargeback credits plus the `fraud_credit_cents` of any
        `RESOLVED_FRAUD` alerts on that transaction must not exceed the
        transaction's `amount_cents` — equality is allowed — else
        `ERR_DUPLICATE_CREDIT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/duplicate_credit_equality_allowed
        """
        setup = setup_confirmed_fraud_txn(
            "ACCT-BP2B", "PT-BP2B", 50000, "M-BP2",
            product_type="DEBIT", network="MASTERCARD", fraud_credit_cents=30000,
        )
        acct, txn = setup["account"], setup["txn"]
        cb2 = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 20001},
                RECOVERY,
            ),
            expected_status=201,
        )
        resp = api.post_provisional_credit(cb2["id"], RECOVERY)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CREDIT, expected_status=422)
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["credit_balance_cents"] == 30000, "rejected posting must leave no residue"


class TestChargebackForkWonVsLostSideEffects:
    def _setup_two_posted(self, api):
        """Two APPROVE txns of 40000; cb1 posted 15000 + representment; cb2 posted
        15000. Balance is 30000."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-NL3", cardholder_name="Fork Join")
        card = create_card(acct["id"], "PT-NL3", product_type="DEBIT", network="MASTERCARD")
        create_active_ruleset()
        t1 = post_txn(card["id"], 40000, "M-NL3", channel="CNP", origin_country="US")
        t2 = post_txn(card["id"], 40000, "M-NL3", channel="CNP", origin_country="US")
        cb1 = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": t1["id"], "reason_code": "4855", "provisional_credit_cents": 15000},
                RECOVERY,
            ),
            expected_status=201,
        )
        get_success_data(api.post_provisional_credit(cb1["id"], RECOVERY))
        get_success_data(api.file_representment(cb1["id"], RECOVERY))
        cb2 = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": t2["id"], "reason_code": "4855", "provisional_credit_cents": 15000},
                RECOVERY,
            ),
            expected_status=201,
        )
        get_success_data(api.post_provisional_credit(cb2["id"], RECOVERY))
        return acct, cb1, cb2

    def test_won_retains_credit(self, api):
        """PRD §3.7: "`WON` is only valid from `REPRESENTMENT_FILED` and keeps the
        credit counting toward the account balance (the case settles in
        `RESOLVED_WON`)".

        Design: Difficulty/non_linear_state_machine/chargeback_fork_won_vs_lost_side_effects
        """
        _acct, cb1, _cb2 = self._setup_two_posted(api)
        won = validate_success(api.resolve_chargeback_case(cb1["id"], {"outcome": "WON"}, RECOVERY))
        assert won["cb_status"] == "RESOLVED_WON"

    def test_lost_reverses_credit_fork_conserves_ledger(self, api):
        """PRD §3.7: "`LOST` is valid from either `PROVISIONAL_CREDIT_POSTED` or
        `REPRESENTMENT_FILED` and reverses the credit — it stops counting toward
        the balance, per invariant INV-CREDIT."; §2.11: the credit ledger sums
        `provisional_credit_cents` across cases in `PROVISIONAL_CREDIT_POSTED`,
        `REPRESENTMENT_FILED`, or `RESOLVED_WON`.

        Design: Difficulty/non_linear_state_machine/chargeback_fork_won_vs_lost_side_effects
        """
        acct, cb1, cb2 = self._setup_two_posted(api)
        won = validate_success(api.resolve_chargeback_case(cb1["id"], {"outcome": "WON"}, RECOVERY))
        assert won["cb_status"] == "RESOLVED_WON"
        lost = validate_success(api.resolve_chargeback_case(cb2["id"], {"outcome": "LOST"}, RECOVERY))
        assert lost["cb_status"] == "RESOLVED_LOST"
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["credit_balance_cents"] == 15000, (
            f"15000 kept from WON cb1; 15000 reversed from LOST cb2; got {account['credit_balance_cents']}"
        )


class TestChargebackCreditPostAndReversalConserveBalance:
    def _setup_filed(self, api):
        acct, _card, txn = _setup_approve_txn(api, "ACCT-CI1", "PT-CI1", 40000, "M-CI1")
        cb = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 15000},
                RECOVERY,
            ),
            expected_status=201,
        )
        return acct, cb

    def test_posting_adds_to_balance(self, api):
        """PRD §3.7: "Posting adds the amount to the account's
        `credit_balance_cents`."

        Design: Difficulty/compensating_invariant/chargeback_credit_post_and_reversal_conserve_balance
        """
        acct, cb = self._setup_filed(api)
        validate_success(api.post_provisional_credit(cb["id"], RECOVERY))
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["credit_balance_cents"] == 15000

    def test_resolve_lost_restores_balance_inv_credit(self, api):
        """PRD §2.11: "Invariant INV-CREDIT: posting a provisional credit and later
        resolving that same chargeback `RESOLVED_LOST` leaves the balance
        unchanged, because the credit exits the qualifying status set exactly as
        the reversal occurs".

        Design: Difficulty/compensating_invariant/chargeback_credit_post_and_reversal_conserve_balance
        """
        acct, cb = self._setup_filed(api)
        validate_success(api.post_provisional_credit(cb["id"], RECOVERY))
        mid = validate_success(api.get_account(acct["id"], MANAGER))
        assert mid["credit_balance_cents"] == 15000
        get_success_data(api.file_representment(cb["id"], RECOVERY))
        lost = validate_success(api.resolve_chargeback_case(cb["id"], {"outcome": "LOST"}, RECOVERY))
        assert lost["cb_status"] == "RESOLVED_LOST"
        end = validate_success(api.get_account(acct["id"], MANAGER))
        assert end["credit_balance_cents"] == 0, "INV-CREDIT: the compensating pair must conserve the ledger"

"""Custodial accounts, escrow split, and the append-only ledger."""
from test_helpers import (
    TEST_USERS,
    assert_account_transaction,
    assert_custodial_reconciliation,
    create_account,
    create_custodial_account_payload,
    get_account,
    get_success_data,
    make_issuer_officer_headers,
    setup_approved_issuer,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestAccountTypeUniqueness:
    def test_duplicate_account_type_rejected(self, api):
        """PRD §3.4: "At most one account of each type may exist per issuer; a
        duplicate type is rejected with `ERR_ACCOUNT_TYPE_DUPLICATE`."

        Design: Corner/validations/duplicate_account_type_rejected
        """
        issuer = setup_approved_issuer("officer-acct")
        headers = make_issuer_officer_headers(issuer["id"])
        first = validate_success(api.create_custodial_account(
            create_custodial_account_payload(issuer["id"], "P_AND_I"), headers),
            expected_status=201)
        assert first["account_type"] == "P_AND_I"
        resp = api.create_custodial_account(
            create_custodial_account_payload(issuer["id"], "P_AND_I"), headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_TYPE_DUPLICATE)
        second = validate_success(api.create_custodial_account(
            create_custodial_account_payload(issuer["id"], "T_AND_I"), headers),
            expected_status=201)
        assert second["account_type"] == "T_AND_I"


class TestEscrowSplit:
    def test_escrow_remainder_lands_on_insurance(self, api):
        """PRD §3.4: "The tax share is the posted amount multiplied by six
        thousand basis points — sixty percent — floored to integer cents, and
        the insurance share is the remainder of the amount after the tax
        share, so any rounding remainder lands on insurance, never the
        reverse."

        Design: Corner/calculations/escrow_split_remainder_to_insurance
        """
        issuer = setup_approved_issuer("officer-esc")
        account = create_account(issuer["id"], "T_AND_I")
        resp = api.create_account_transaction(
            account["id"], {"component": "ESCROW", "amount_cents": 1001},
            make_issuer_officer_headers(issuer["id"]))
        tx = validate_success(resp, expected_status=201)
        # floor(1001 * 6000 / 10000) = 600; remainder 401 to insurance.
        assert tx["tax_split_cents"] == 600
        assert tx["insurance_split_cents"] == 401
        account_after = get_account(account["id"])
        assert account_after["tax_balance_cents"] == 600
        assert account_after["insurance_balance_cents"] == 401
        assert account_after["balance_cents"] == 1001
        assert_custodial_reconciliation(account_after)


class TestAccountTransactionImmutability:
    def test_ledger_entry_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "`AccountTransaction` entries are an append-only ledger
        and carry only `id` and `created_at` — both `updated_at` and
        `version` are absent on transaction rows, since a posted entry is
        never mutated."

        Design: Corner/entities/account_transaction_immutable_no_version_field
        """
        issuer = setup_approved_issuer("officer-im")
        account = create_account(issuer["id"], "P_AND_I")
        resp = api.create_account_transaction(
            account["id"], {"component": "PRINCIPAL", "amount_cents": 5000},
            make_issuer_officer_headers(issuer["id"]))
        tx = validate_success(resp, expected_status=201)
        assert_account_transaction(tx)
        assert tx["direction"] == "DEPOSIT"
        assert tx["component"] == "PRINCIPAL"
        assert "version" not in tx
        assert "updated_at" not in tx


class TestIssuerDefaultFreeze:
    def test_default_freezes_accounts_and_blocks_deposits(self, api):
        """PRD §3.8: "An `AgencyReviewer` declares an issuer defaulted from
        `ACTIVE`, `WATCH`, or `SUSPENDED` ... moving it to `DEFAULTED` and
        freezing its custodial accounts (accounts already frozen stay
        frozen)."
        PRD §3.4: "a posting to a `FROZEN` or `CLOSED` account is rejected
        with `ERR_ACCOUNT_FROZEN`."

        Design: Corner/cross_cutting_layers/issuer_default_freezes_custodial_accounts
        """
        issuer = setup_approved_issuer("officer-fr")
        account = create_account(issuer["id"], "P_AND_I")
        get_success_data(api.create_account_transaction(
            account["id"], {"component": "PRINCIPAL", "amount_cents": 5000},
            make_issuer_officer_headers(issuer["id"])))
        defaulted = validate_success(api.default_issuer(
            issuer["id"], TEST_USERS["agency_reviewer_headers"]))
        assert defaulted["status"] == "DEFAULTED"
        frozen = get_account(account["id"])
        assert frozen["status"] == "FROZEN"
        assert frozen["balance_cents"] == 5000
        resp = api.create_account_transaction(
            account["id"], {"component": "PRINCIPAL", "amount_cents": 100},
            make_issuer_officer_headers(issuer["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN)
        assert get_account(account["id"])["balance_cents"] == 5000

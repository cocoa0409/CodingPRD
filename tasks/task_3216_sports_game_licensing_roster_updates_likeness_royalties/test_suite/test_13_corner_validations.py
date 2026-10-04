"""Corner queue B, section=validations (4 instances)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    create_active_agreement,
    create_agreement_payload,
    create_funded_wallet,
    create_season_payload,
    create_wallet_payload,
    get_success_data,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["licensing_admin_headers"]
LIVEOPS = TEST_USERS["liveops_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def test_forbidden_role_beats_not_found(api):
    """PRD §2.10: "The order is: first, authentication context
    (ERR_MISSING_CONTEXT); second, role authorization (ERR_FORBIDDEN_ROLE);
    third, resource existence for path and body identifiers (ERR_NOT_FOUND)."

    Design: Corner/validations/forbidden_role_beats_not_found
    """
    resp = api_client.publish_roster_batch(
        NON_EXISTENT_UUID, {"expected_season_version": 1}, FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_context_header_rejected(api):
    """PRD §2.1: "Failure to provide both headers, or providing them in a
    malformed form, is rejected with ERR_MISSING_CONTEXT (HTTP 400)."

    Design: Corner/validations/missing_context_header_rejected
    """
    resp = api_client.list_agreements(headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT.value)


def test_insufficient_wallet_balance_blocks_debit(api):
    """PRD §3.4: "A debit may post only while the wallet is OPEN and only when
    the wallet's current balance is at least the debit's amount_vc; ... an
    attempt exceeding the balance is ERR_INSUFFICIENT_VC (HTTP 422)."

    Design: Corner/validations/insufficient_wallet_balance_blocks_debit
    """
    agreement = create_active_agreement()
    season = get_success_data(
        api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
    )
    wallet = get_success_data(
        api_client.create_wallet(create_wallet_payload(season["id"], owner_tag="poor"),
                                 LIVEOPS)
    )
    get_success_data(
        api_client.post_ledger_entry(
            wallet["id"],
            {"direction": "CREDIT", "amount_vc": 100, "reason_code": "GRANT"},
            LIVEOPS,
        )
    )
    resp = api_client.post_ledger_entry(
        wallet["id"],
        {"direction": "DEBIT", "amount_vc": 101, "reason_code": "CLAWBACK"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VC.value)

    wallet_after = get_success_data(api_client.get_wallet(wallet["id"], FINANCE))
    assert wallet_after["vc_balance"] == 100


def test_frozen_wallet_rejects_debit(api):
    """PRD §3.4: "A debit may post only while the wallet is OPEN and only when
    the wallet's current balance is at least the debit's amount_vc; an attempt
    against a FROZEN wallet is ERR_WALLET_FROZEN."

    Design: Corner/validations/frozen_wallet_rejects_debit
    """
    agreement = create_active_agreement()
    season = get_success_data(
        api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
    )
    wallet = create_funded_wallet(season["id"], 500, owner_tag="frozen")
    get_success_data(api_client.freeze_wallet(wallet["id"], LIVEOPS))

    resp = api_client.post_ledger_entry(
        wallet["id"],
        {"direction": "DEBIT", "amount_vc": 100, "reason_code": "CLAWBACK"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_WALLET_FROZEN.value)

    wallet_after = get_success_data(api_client.get_wallet(wallet["id"], FINANCE))
    assert wallet_after["vc_balance"] == 500

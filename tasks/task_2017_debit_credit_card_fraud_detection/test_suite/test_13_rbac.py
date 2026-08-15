"""RBAC and ownership: authentication, role exclusivity, cardholder ownership."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_manual_alert,
    create_rule_set_payload,
    get_success_data,
    make_analyst_headers,
    make_cardholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
GATEWAY = TEST_USERS["gateway_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or whose `X-User-Role` does not
    match one of these six spellings, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other check runs."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api.list_accounts({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_cardholder_cannot_act_on_other_account(api):
    """PRD §2.1: "When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the
    acting `Account`; ownership checks on any resource that references an
    `Account` — the account itself, an alert's `account_id`, a card's
    `account_id`, a travel notice reached through its card — compare that
    foreign-key field to `X-User-ID`, and a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/cardholder_cannot_act_on_other_account
    """
    acct1 = create_account("ACCT-V2A", cardholder_name="Owner A")
    acct2 = create_account("ACCT-V2B", cardholder_name="Owner B")
    card1 = create_card(acct1["id"], "PT-V2")
    alert = create_manual_alert(acct1["id"], card1["id"])
    resp = api.respond_fraud_alert(
        alert["id"], {"outcome": "CONFIRMED_LEGIT"}, make_cardholder_headers(acct2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    current = validate_success(api.get_fraud_alert(alert["id"], MANAGER))
    assert current["alert_status"] == "OPEN"


def test_analyst_cannot_activate_ruleset(api):
    """PRD §3.2: "Activation is a `FraudOpsManager`-only action"; §2.1: "A request
    whose role is authenticated but not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    Design: Corner/rbac/analyst_cannot_activate_ruleset
    """
    rs = get_success_data(
        api.create_rule_set(create_rule_set_payload(), make_analyst_headers("analyst-1")),
        expected_status=201,
    )
    resp = api.activate_rule_set(rs["id"], make_analyst_headers("analyst-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_cardholder_cannot_block_card(api):
    """PRD §4: `POST /fraudops/cards/{id}/block` lists "FraudAnalyst,
    FraudOpsManager" as authorized roles; §2.1: "A request whose role is
    authenticated but not permitted on the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    Design: Corner/rbac/cardholder_cannot_block_card
    """
    acct = create_account("ACCT-RB2", cardholder_name="Rb Two")
    card = create_card(acct["id"], "PT-RB2")
    resp = api.block_card(
        card["id"],
        {"block_type": "SOFT", "reason": "CUSTOMER_REQUEST"},
        make_cardholder_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    current = validate_success(api.get_card(card["id"], MANAGER))
    assert current["card_status"] == "ACTIVE"


def test_gateway_cannot_read_accounts(api):
    """PRD §4: `GET /fraudops/accounts` lists "FraudAnalyst, FraudOpsManager,
    LossAccountant, RecoverySpecialist" — NetworkGateway is absent; §2.1: "A
    request whose role is authenticated but not permitted on the target endpoint
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    Design: Corner/rbac/gateway_cannot_read_accounts
    """
    resp = api.list_accounts(GATEWAY)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_loss_accountant_cannot_file_recovery(api):
    """PRD §4: `POST /fraudops/recovery-filings` is authorized for
    "RecoverySpecialist" only; §2.1: "A request whose role is authenticated but
    not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)". §2.6 orders "role permission including cross-analyst custody
    (priority 2, `ERR_FORBIDDEN_ROLE`)" before body foreign-reference resolution,
    so the role error fires even for a non-existent loss id.

    Design: Corner/rbac/loss_accountant_cannot_file_recovery
    """
    resp = api.create_recovery_filing(
        {
            "loss_entry_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "network_reference": "NR-RB4",
            "claimed_cents": 100,
        },
        ACCOUNTANT,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

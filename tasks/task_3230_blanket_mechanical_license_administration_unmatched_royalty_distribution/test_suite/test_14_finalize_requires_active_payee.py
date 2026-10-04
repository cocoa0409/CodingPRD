"""Cross-entity state dependency: statement finalization gated on ACTIVE payee."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, setup_member_with_payee,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_member_suspended_payee():
    set_clock("2026-09-01T00:00:00Z")
    member, payee = setup_member_with_payee()
    statement = validate_success(
        api_client.create_statement(member["id"], "2026-06", ADMIN),
        expected_status=201)
    validate_success(api_client.suspend_payee(member["id"], payee["id"], ADMIN))
    return member, payee, statement


def test_finalize_with_only_suspended_payee_rejected(api):
    """PRD §3.7: "Finalization requires the statement to be `DRAFT` and the
    member to have at least one `ACTIVE` payee (`ERR_NO_ACTIVE_PAYEE`, HTTP 422,
    when none exists)."

    Design: Difficulty/cross_entity_state_dependency/statement_finalize_requires_member_payee
    """
    member, _payee, statement = _setup_member_suspended_payee()
    validate_error(
        api_client.finalize_statement(member["id"], statement["id"], ADMIN),
        ApiErrorId.ERR_NO_ACTIVE_PAYEE)


def test_failed_finalize_leaves_statement_draft(api):
    """PRD §3.7: "Finalization requires the statement to be `DRAFT` and the
    member to have at least one `ACTIVE` payee (`ERR_NO_ACTIVE_PAYEE`, HTTP 422,
    when none exists)."

    Design: Difficulty/cross_entity_state_dependency/statement_finalize_requires_member_payee
    """
    member, _payee, statement = _setup_member_suspended_payee()
    validate_error(
        api_client.finalize_statement(member["id"], statement["id"], ADMIN),
        ApiErrorId.ERR_NO_ACTIVE_PAYEE)
    after = validate_success(
        api_client.get_statement(member["id"], statement["id"], ADMIN))
    assert after["status"] == "DRAFT", (
        f"the failed finalize leaves the statement DRAFT; got {after['status']}")

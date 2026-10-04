"""Licence recording, expiry, revocation and the revocation cascade."""
from datetime import datetime, timedelta

from test_helpers import (
    ANY,
    ApiErrorId,
    NON_EXISTENT_UUID,
    get_broker,
    record_license,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    CO,
    broker_version,
    create_submitted_broker,
    resolve_escalation,
    setup_full_scenario,
    setup_loan_in_state,
    underwrite_loan,
)
from test_helpers.test_users import TEST_USERS, make_compliance_officer_headers


def _plus_days(iso: str, days: int) -> str:
    parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (parsed + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_license_revocation_cascades_loan_to_suspended_review(api):
    """PRD §3.1: "Every loan of that broker whose `property_state` equals the revoked
    licence's `state_code` and whose status is `SUBMITTED` or `UNDERWRITING` is immediately
    pushed to `SUSPENDED_REVIEW` with `suspended_reason` of `LICENSE_REVOKED`"
    PRD §3.1: "for each loan so moved, the broker's `total_active_compensation_commitment_cents`
    is reduced by that loan's `lender_paid_comp_cents`"

    Design: Difficulty/transitive_cascade/license_revocation_cascade_to_loan_stage_and_escalation
    """
    scenario = setup_full_scenario(state_code="CA")
    loan_id = scenario["loan_id"]
    broker_id = scenario["broker_id"]
    underwrite_loan(loan_id, broker_version(broker_id))

    commitment_before = get_broker(broker_id)["total_active_compensation_commitment_cents"]
    loan = validate_success(api_client.get_loan_submission(loan_id, ANY))
    assert loan["status"] == "UNDERWRITING"
    assert loan["lender_paid_comp_cents"] == 250_000

    response = api_client.revoke_license(
        broker_id, scenario["license"]["id"], make_compliance_officer_headers()
    )
    revoked = validate_success(response)
    assert revoked["status"] == "REVOKED"

    after = validate_success(api_client.get_loan_submission(loan_id, ANY))
    assert after["status"] == "SUSPENDED_REVIEW"
    assert after["suspended_reason"] == "LICENSE_REVOKED"

    broker_after = get_broker(broker_id)
    assert broker_after["total_active_compensation_commitment_cents"] == (
        commitment_before - after["lender_paid_comp_cents"]
    )
    assert broker_after["total_active_compensation_commitment_cents"] == 0


def test_license_revocation_reopens_the_resolved_escalation_with_extension(api):
    """PRD §3.1: "every `TurnTimeEscalation` of that loan that had been `RESOLVED` is reopened
    to `OPEN` with `resolved_at` cleared and `target_due_at` reset to the loan's
    `underwriting_due_at` plus five days."
    PRD §2.6: "A reopened escalation's `target_due_at` is the loan's `underwriting_due_at`
    plus five days."

    Design: Difficulty/transitive_cascade/license_revocation_cascade_to_loan_stage_and_escalation
    """
    scenario = setup_full_scenario(state_code="CA")
    loan_id = scenario["loan_id"]
    broker_id = scenario["broker_id"]
    underwrite_loan(loan_id, broker_version(broker_id))

    set_clock("2026-09-20T00:00:00Z")
    escalations = validate_success(api_client.list_loan_escalations(loan_id, ANY))
    assert len(escalations) == 1, "the lapsed underwriting commitment opened one escalation"
    escalation_id = escalations[0]["id"]
    assert escalations[0]["status"] == "OPEN"
    assert escalations[0]["stage"] == "UNDERWRITING"

    resolved = resolve_escalation(escalation_id, "underwriter staffing shortage resolved")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None

    api_client.revoke_license(broker_id, scenario["license"]["id"], make_compliance_officer_headers())

    reopened = validate_success(api_client.list_loan_escalations(loan_id, ANY))[0]
    assert reopened["id"] == escalation_id
    assert reopened["status"] == "OPEN"
    assert reopened["resolved_at"] is None

    loan = validate_success(api_client.get_loan_submission(loan_id, ANY))
    assert reopened["target_due_at"] == _plus_days(loan["underwriting_due_at"], 5)

    still_resolved, meta = validate_paginated(
        api_client.list_loan_escalations(loan_id, ANY, {"status": "RESOLVED"})
    )
    assert still_resolved == []
    assert meta["total_count"] == 0


def test_revoking_an_unknown_license_returns_license_not_found(api):
    """PRD §2.11: "The catalogue of not-found identifiers is `ERR_BROKER_NOT_FOUND`,
    `ERR_RATE_SHEET_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_ELIGIBILITY_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND` and `ERR_ESCALATION_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/license_revocable_pair_stale_update
    """
    broker = create_submitted_broker()
    record_license(broker["id"], state_code="TX")

    response = api_client.revoke_license(
        broker["id"], NON_EXISTENT_UUID, make_compliance_officer_headers()
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_FOUND, expected_status=404)


def test_second_revocation_of_a_revoked_license_is_refused(api):
    """PRD §3.1: "Revocation requires that the licence still be `ACTIVE` — a licence that is
    already `EXPIRED` or `REVOKED` cannot be revoked again and yields `ERR_LICENSE_NOT_REVOCABLE`"

    Design: Difficulty/priority_pair_validation_conflict/license_revocable_pair_stale_update
    """
    broker = create_submitted_broker()
    license_ = record_license(broker["id"], state_code="TX")

    first = api_client.revoke_license(
        broker["id"], license_["id"], make_compliance_officer_headers()
    )
    validate_success(first)

    second = api_client.revoke_license(
        broker["id"], license_["id"], make_compliance_officer_headers()
    )
    validate_error(second, ApiErrorId.ERR_LICENSE_NOT_REVOCABLE, expected_status=409)

    revoked, meta = validate_paginated(
        api_client.list_licenses(broker["id"], TEST_USERS["any_headers"], {"status": "REVOKED"})
    )
    assert len(revoked) == 1
    assert meta["total_count"] == 1


def test_expired_license_cannot_be_revoked(api):
    """PRD §3.1: "A licence lapses automatically when the clock reaches or passes `expires_on`,
    at which point its status becomes `EXPIRED`"
    PRD §3.1: "a licence that is already `EXPIRED` or `REVOKED` cannot be revoked again and
    yields `ERR_LICENSE_NOT_REVOCABLE`"

    Design: Corner/state_machines/expired_license_cannot_be_revoked_and_financial_review_terminal_lockdown
    """
    broker = create_submitted_broker()
    license_ = record_license(broker["id"], state_code="TX", expires_on="2026-10-01T00:00:00Z")

    set_clock("2026-10-05T00:00:00Z")

    any_h = TEST_USERS["any_headers"]
    expired, meta_expired = validate_paginated(api_client.list_licenses(broker["id"], any_h, {"status": "EXPIRED"}))
    active, meta_active = validate_paginated(api_client.list_licenses(broker["id"], any_h, {"status": "ACTIVE"}))
    assert len(expired) == 1 and meta_expired["total_count"] == 1
    assert active == [] and meta_active["total_count"] == 0

    response = api_client.revoke_license(
        broker["id"], license_["id"], make_compliance_officer_headers()
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_REVOCABLE, expected_status=409)
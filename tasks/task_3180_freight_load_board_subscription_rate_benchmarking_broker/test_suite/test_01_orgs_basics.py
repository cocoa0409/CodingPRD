"""Organization creation and lookup basics."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    NON_EXISTENT_UUID, TEST_USERS, ApiErrorId,
    set_test_clock, create_broker,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


def test_broker_org_create_returns_defaults_and_system_fields():
    """PRD §3.1: "A fresh broker org starts in `ACTIVE` status with a
    `credit_score` of 70 and a `credit_badge` of `STANDARD`, reflecting the
    absence of payment history rather than proven trustworthiness."

    Design: Corner/entities/broker_org_create_returns_defaults_and_system_fields
    """
    resp = api_client.create_broker_org(
        {"legal_name": "First Call Brokerage", "mc_number": "MC-1000"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["credit_score"] == 70
    assert data["credit_badge"] == "STANDARD"
    assert data["credit_event_count"] == 0
    assert data["included_amount_cents"] == 0
    assert data["under_dispute_amount_cents"] == 0
    assert data["removed_amount_cents"] == 0
    assert data["data_contribution_flag"] is False
    assert data["version"] == 1
    assert "id" in data and "created_at" in data and "updated_at" in data
    assert data["created_at"].startswith("2026-09-01T00:00:00")


def test_broker_org_get_with_unknown_id_returns_not_found():
    """PRD §2.9: "Every path identifier and every foreign-key identifier
    supplied in a request body must resolve to an existing record before any
    state or business rule is evaluated."

    Design: Corner/entities/broker_org_get_with_unknown_id_returns_not_found
    """
    resp = api_client.get_broker_org(NON_EXISTENT_UUID, ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_ORG_NOT_FOUND)
    assert "message" in err


def test_duplicate_mc_number_rejected_on_second_broker():
    """PRD §3.1: "the FMCSA motor-carrier docket number, which must be unique
    across all broker orgs — a duplicate submission is rejected with
    `ERR_DUPLICATE_MC_NUMBER` (HTTP 409)."

    Design: Corner/errors/duplicate_mc_number_rejected_on_second_broker
    """
    set_test_clock()
    create_broker(mc_number="MC-1100")
    resp = api_client.create_broker_org(
        {"legal_name": "Imposter Brokerage", "mc_number": "MC-1100"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MC_NUMBER)
    rows, meta = validate_paginated(api_client.list_broker_orgs(ADMIN))
    assert meta["total_count"] == 1

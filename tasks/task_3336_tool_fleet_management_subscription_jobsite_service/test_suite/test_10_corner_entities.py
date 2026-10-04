"""Corner/entities: creation defaults, computed end_date, validation, dupes."""
from datetime import datetime, timezone

from test_helpers import (
    api_client, validate_success, validate_error, create_account_payload,
    create_rate_card_payload, create_account, create_agreement_payload,
    setup_deployed_asset, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def _parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_account_creation_defaults_and_computed_fields(api):
    """PRD §3.1: "New accounts are born `ACTIVE` with
    `outstanding_balance_cents` at 0"
    PRD §2.4: "a `version` integer that starts at its initial value on creation
    and increments by exactly 1 on every mutation of that resource."

    Design: Corner/entities/account_creation_defaults_and_computed_fields
    """
    r = api_client.create_account(create_account_payload(
        company_name="Sierra LLC", tax_id="EIN-E1", credit_limit_cents=5000), ADMIN)
    account = validate_success(r, expected_status=201)
    assert account["status"] == "ACTIVE"
    assert account["outstanding_balance_cents"] == 0
    assert account["version"] == 1


def test_agreement_end_date_computed_from_term(api):
    """PRD §3.3: "The server mints the `agreement_number`, links the agreement
    to its owning account through `account_id`, computes `end_date` as
    `start_date` plus `term_months` months, and opens the agreement in
    `DRAFT`."

    Design: Corner/entities/agreement_end_date_computed_from_term
    """
    account = create_account(tax_id="EIN-E2", company_name="Tango LLC")
    r = api_client.create_agreement(
        account["id"], create_agreement_payload(
            term_months=3, start_date="2026-09-01T00:00:00Z",
            end_of_term_option="RETURN"), ADMIN)
    agreement = validate_success(r, expected_status=201)
    assert _parse_iso(agreement["end_date"]) == _parse_iso("2026-12-01T00:00:00Z")
    assert agreement["status"] == "DRAFT"
    assert agreement["fleet_size_target"] == 0
    assert isinstance(agreement["agreement_number"], str)


def test_usage_event_rejects_inverted_range_returns_validation(api):
    """PRD §3.5: "`ended_at` must be strictly after `started_at` (else
    `ERR_VALIDATION`)"

    Design: Corner/entities/usage_event_rejects_inverted_range_returns_validation
    """
    env = setup_deployed_asset()
    r = api_client.record_usage_event(
        env["asset"]["id"],
        {"started_at": "2026-09-02T00:00:00Z", "ended_at": "2026-09-01T00:00:00Z"},
        env["js"])
    validate_error(r, "ERR_VALIDATION")


def test_rate_card_inverted_effective_range_returns_validation(api):
    """PRD §3.2: "`effective_to` must be strictly later than `effective_from`
    (else `ERR_VALIDATION`)."

    Design: Corner/entities/rate_card_inverted_effective_range_returns_validation
    """
    r = api_client.create_rate_card(create_rate_card_payload(
        code="RC-E4", tool_category="SAW",
        effective_from="2027-01-01T00:00:00Z",
        effective_to="2026-01-01T00:00:00Z"), ADMIN)
    validate_error(r, "ERR_VALIDATION")


def test_duplicate_tax_id_rejected(api):
    """PRD §3.1: "a duplicate `tax_id` is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_tax_id_rejected
    """
    r = api_client.create_account(create_account_payload(
        company_name="Victor A", tax_id="EIN-DUP", credit_limit_cents=1000), ADMIN)
    validate_success(r, expected_status=201)
    r = api_client.create_account(create_account_payload(
        company_name="Victor B", tax_id="EIN-DUP", credit_limit_cents=2000), ADMIN)
    validate_error(r, "ERR_DUPLICATE")

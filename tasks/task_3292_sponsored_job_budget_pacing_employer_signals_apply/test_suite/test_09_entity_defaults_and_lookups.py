"""Entity creation defaults, computed fields and parent lookups.

Resources come back with server-set lifecycle fields rather than client-supplied
ones, computed fields are reconciled from the ledger, and children are
discoverable through their parent.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
    make_employer_headers, employer_payload, job_posting_payload,
    set_clock, create_employer, create_campaign, create_active_campaign,
    create_posting, create_sponsored_job, get_campaign,
    assert_common_fields, assert_employer, assert_campaign, assert_sponsored_job,
)

ADMIN = TEST_USERS["admin_headers"]


def test_employer_creation_returns_the_declared_defaults(api):
    """PRD §3.1: "A newly created employer begins with `status` set to `ACTIVE`,
    `quality_score` at 100, `response_rate_bps` at 0, `balance_cents` at 0 and
    `billing_status` set to `CURRENT`; its `last_invoice_at`, `suspended_at` and
    `suspension_reason` are all null".

    Design: Corner/entities/employer_create_returns_all_declared_defaults
    """
    res = api.create_employer({
        "legal_name": "Corner Co",
        "domain": "corner.example",
        "ats_provider": "GREENHOUSE",
    }, ADMIN)

    employer = validate_success(res, 201)
    assert_employer(employer)
    assert_common_fields(employer, "Employer")
    assert employer["status"] == "ACTIVE"
    assert employer["billing_status"] == "CURRENT"
    assert employer["quality_score"] == 100
    assert employer["response_rate_bps"] == 0
    assert employer["balance_cents"] == 0
    assert employer["last_invoice_at"] is None


def test_campaign_get_reports_freshly_initialised_budget_fields(api):
    """PRD §3.2: "A new campaign begins in `DRAFT` with `spent_cents`,
    `daily_spent_cents` and `held_cents` all at 0, and with `day_open_date` set to
    `00:00:00Z` of the current logical day."

    Design: Corner/entities/campaign_get_returns_computed_budget_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Computed Co", domain="computed.example")
    campaign = create_campaign(employer, name="Computed")

    live = get_campaign(campaign["id"], employer)
    assert_campaign(live)
    assert live["spent_cents"] == 0
    assert live["daily_spent_cents"] == 0
    assert live["held_cents"] == 0
    assert live["day_open_date"] == "2026-09-01T00:00:00Z"
    assert live["status"] == "DRAFT"


def test_employer_creation_without_domain_is_rejected(api):
    """PRD §3.1: "An employer account is seeded by a `PlatformAdmin` with a
    `legal_name`, a `domain` that keys the employer's applicant-tracking-system
    feed, and an optional `ats_provider`."
    PRD §2.8: "11. **General request shape.** Required fields must be present,
    types must be correct and enumerations must carry valid members. Otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/employer_create_missing_required_field_returns_invalid_request
    """
    res = api.create_employer({"legal_name": "No Domain Co"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_sponsored_job_creation_initialises_system_fields(api):
    """PRD §3.3: "A newly created sponsored job begins in `ELIGIBLE`, with
    `impressions`, `clicks` and `applications` all at 0, and with both
    `scheduled_pacing_multiplier` and `realized_pacing_multiplier` initialised
    to 1.0."

    Design: Corner/entities/sponsored_job_creation_assigns_system_fields_ignoring_input
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="System Co", domain="system.example")
    posting = create_posting(employer, title="System Engineer")
    campaign = create_active_campaign(employer, name="SY")

    res = api.create_sponsored_job({
        "campaign_id": campaign["id"],
        "job_posting_id": posting["id"],
        "cpc_bid_cents": 250,
        "cpa_bid_cents": 800,
    }, make_employer_headers(employer["id"]))

    sponsored_job = validate_success(res, 201)
    assert_sponsored_job(sponsored_job)
    assert isinstance(sponsored_job["version"], int)
    assert sponsored_job["impressions"] == 0
    assert sponsored_job["clicks"] == 0
    assert sponsored_job["applications"] == 0
    assert sponsored_job["scheduled_pacing_multiplier"] == pytest.approx(1.0, abs=1e-9)
    assert sponsored_job["realized_pacing_multiplier"] == pytest.approx(1.0, abs=1e-9)
    assert sponsored_job["status"] == "ELIGIBLE"


def test_employer_campaign_lookup_returns_all_children_and_filters(api):
    """PRD §2.3: "Filters narrow the result set before pagination is applied, so
    `total_count` reflects the filtered set rather than the unfiltered one."

    Design: Corner/entities/employer_campaigns_reverse_lookup_returns_children
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Reverse Co", domain="reverse.example")
    posting = create_posting(employer, title="Reverse Engineer")
    draft = create_campaign(employer, name="Draft One")
    live = create_active_campaign(employer, name="Live Two",
                                  pricing_model="CPA")

    all_data, all_meta = validate_paginated(
        api.list_employer_campaigns(employer["id"], ADMIN))
    assert all_meta["total_count"] == 2
    assert {c["id"] for c in all_data} == {draft["id"], live["id"]}

    active_data, active_meta = validate_paginated(
        api.list_employer_campaigns(employer["id"], ADMIN, params={"status": "ACTIVE"}))
    assert active_meta["total_count"] == 1
    assert active_data[0]["id"] == live["id"]

    draft_data, draft_meta = validate_paginated(
        api.list_employer_campaigns(employer["id"], ADMIN, params={"status": "DRAFT"}))
    assert draft_meta["total_count"] == 1
    assert draft_data[0]["id"] == draft["id"]


def test_unknown_campaign_id_reports_campaign_not_found(api):
    """PRD §2.8: "3. **Referential existence.** Every resource identifier
    appearing in the request — in the path or in the payload — must resolve to an
    existing row. ... `ERR_CAMPAIGN_NOT_FOUND`".

    Design: Corner/entities/campaign_get_unknown_id_returns_campaign_not_found
    """
    res = api.get_campaign("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, expected_status=404)
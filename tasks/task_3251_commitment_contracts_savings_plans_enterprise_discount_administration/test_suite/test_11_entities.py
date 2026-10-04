"""Tests for entity-level claims: defaults, computed fields, immutability, listing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    make_admin_headers,
    make_platform_headers,
    create_org,
    create_linked_account,
    ingest_usage,
    generate_invoice,
    get_invoice_lines,
    ApiErrorId,
)

ADMIN = make_admin_headers()
PLATFORM = make_platform_headers()


def test_org_create_applies_currency_default_and_system_fields(api):
    """PRD section 3.1: "A `PlatformBillingOperator` begins by creating a billing
    organization, supplying its display `name`, an ISO `currency` code that
    defaults to `USD` when omitted, and two org-wide guardrails:
    `max_hourly_commitment_cents`, a ceiling on the combined hourly commitment
    across all of the org's currently `ACTIVE` plans, and
    `capacity_quota_units`, a per-instance-family cap on reserved units that may
    overlap at any instant. The organization is born with `current_period_index`
    at 0 and `unapplied_credit_cents` at 0."

    Design: Corner/entities/org_create_applies_currency_default_and_system_fields
    """
    resp = api.create_billing_org(
        {"name": "Dft Org", "max_hourly_commitment_cents": 1000,
         "capacity_quota_units": 10},
        PLATFORM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["currency"] == "USD"
    assert data["current_period_index"] == 0
    assert data["unapplied_credit_cents"] == 0
    assert data["version"] == 1
    assert data.get("id") and data.get("created_at") and data.get("updated_at")


def test_usage_record_org_and_period_denormalized_at_ingest(api):
    """PRD section 3.5: "On ingest the record is stamped with the org's identity —
    `org_id` is denormalized from the linked account — and the org's
    `current_period_index` at that moment becomes the record's `period_index`. The
    record starts `INGESTED` with `invoice_id` null."

    Design: Corner/entities/usage_record_org_and_period_denormalized_at_ingest
    """
    org = create_org(name="Cp Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    resp = api.run_period_close(org["id"], PLATFORM)
    validate_success(resp)
    data = ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                        list_price_cents=500)
    assert data["org_id"] == org["id"]
    assert data["period_index"] == 1
    assert data["status"] == "INGESTED"
    assert data["invoice_id"] is None


def test_invoice_line_has_no_version_field_immutable_rows(api):
    """PRD section 2.4: "Three resource kinds are lighter-weight and carry only
    `id` and `created_at` — neither `updated_at` nor `version` is present on
    them: usage records, invoice lines, and renewal forecasts."

    Design: Corner/entities/invoice_line_has_no_version_field_immutable_rows
    """
    org = create_org(name="Im Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=500)
    inv = generate_invoice(org["id"], period_index=0)
    lines = get_invoice_lines(inv["id"])
    assert len(lines) == 1
    line = lines[0]
    assert "id" in line and "created_at" in line
    assert "version" not in line, "invoice lines must not carry version"
    assert "updated_at" not in line, "invoice lines must not carry updated_at"
    fetched = validate_success(api.get_invoice_line(line["id"], ADMIN))
    assert fetched["id"] == line["id"]
    assert "version" not in fetched and "updated_at" not in fetched


def test_agreement_get_nonexistent_id_returns_not_found(api):
    """PRD section 2.6: "When several checks apply to one request, they are
    evaluated in a fixed priority order, and the first failure determines the
    rejection. Authentication (missing or unknown headers, `ERR_UNAUTHENTICATED`,
    401) comes first, then authorization (`ERR_FORBIDDEN`, 403), then existence of
    every referenced id — validated left-to-right across path and body identifiers
    such as `org_id`, `linked_account_id`, `agreement_id`, `plan_id`,
    `invoice_id`, `grant_id`, and `trueup_id` (`ERR_NOT_FOUND`, 404)."

    Design: Corner/entities/agreement_get_nonexistent_id_returns_not_found
    """
    resp = api.get_enterprise_agreement(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_linked_accounts_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "List endpoints accept optional query parameters `limit`
    and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. Results are sorted by `created_at` ascending
    unless stated otherwise. The `meta` block of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`, where `has_more` indicates whether
    additional results exist beyond the returned window."

    Design: Corner/entities/linked_accounts_list_paginates_with_total_count_and_has_more
    """
    org = create_org(name="Pg Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    for i in (1, 2, 3):
        create_linked_account(org["id"], name=f"a{i}", external_ref=f"e{i}")
    resp = api.list_linked_accounts(
        ADMIN, params={"org_id": org["id"], "limit": 2, "offset": 2}
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    page1, meta1 = validate_paginated(
        api.list_linked_accounts(ADMIN, params={"org_id": org["id"], "limit": 2})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

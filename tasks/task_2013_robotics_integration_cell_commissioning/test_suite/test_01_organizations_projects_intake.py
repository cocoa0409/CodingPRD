"""Organizations, users, sites, and project intake (PRD §2.2, §2.4, §2.8, §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_cell_project,
    assert_integrator_org,
    assert_retention_ledger_entry,
    create_cell_project_payload,
    create_org,
    create_project,
    create_site,
    create_user,
    get_project,
    make_finance_admin_headers,
    make_project_engineer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_integrator_org_creation_and_defaults(api):
    """PRD §2.4: "`version` — an integer starting at 1 and incrementing on
    every mutation of the resource." PRD §3.1: organizations carry
    `legal_name`, `brand_specialization`, `retention_rate_bps`, and
    `default_pl_category_target`.

    Design: Corner/entities/integrator_org_creation_and_defaults
    """
    org = validate_success(
        api.create_integrator_org(
            {
                "legal_name": "Acme Integration",
                "brand_specialization": "DUAL",
                "retention_rate_bps": 1500,
                "default_pl_category_target": "PLe",
            },
            make_finance_admin_headers(),
        ),
        201,
    )
    assert_integrator_org(org)
    assert org["version"] == 1

    fetched = validate_success(
        api.get_integrator_org(org["id"], make_finance_admin_headers())
    )
    assert fetched["legal_name"] == "Acme Integration"
    assert fetched["brand_specialization"] == "DUAL"
    assert fetched["retention_rate_bps"] == 1500


def test_cell_project_missing_required_field_rejected(api):
    """PRD §2.6: "Required-field presence, types, and numeric ranges —
    `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.1: project creation requires
    `contract_value_cents` strictly greater than zero.

    Design: Corner/entities/cell_project_missing_required_field_rejected
    """
    org = create_org()
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="S1")

    payload = create_cell_project_payload(
        project_code="P-MISS", contracted_cycle_time_s=10.0, guaranteed_oee_pct=80.0
    )
    payload.pop("contract_value_cents")
    resp = api.create_cell_project(
        site["id"], payload, make_project_engineer_headers(eng["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_project_returns_not_found(api):
    """PRD §2.5: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
    the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_nonexistent_project_returns_not_found
    """
    resp = api.get_cell_project(
        "11111111-2222-3333-4444-555555555555", make_finance_admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    org = create_org()
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="S2")
    for code in ("P-A", "P-B", "P-C"):
        create_project(
            site["id"],
            eng["id"],
            project_code=code,
            contracted_cycle_time_s=10.0,
            contract_value_cents=100000,
            guaranteed_oee_pct=80.0,
        )

    resp = api.list_cell_projects(
        site["id"],
        make_project_engineer_headers(eng["id"]),
        params={"limit": 2, "offset": 0},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"Expected 2 items under limit=2, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_computed_field_ignores_client_input(api):
    """PRD §3.1: "the system multiplies `contract_value_cents` by the owning
    org's `retention_rate_bps`, divides by ten thousand, rounds half-up to a
    whole cent, seeds `retention_balance_cents` with the result, and posts the
    opening `WITHHOLD` ledger entry against the project."

    Design: Corner/entities/computed_field_ignores_client_input
    """
    org = create_org(retention_rate_bps=1000)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="S3")

    # Client submits a value for the computed field; the server must derive it.
    payload = create_cell_project_payload(
        project_code="P-COMP",
        contracted_cycle_time_s=10.0,
        contract_value_cents=1_000_000,
        guaranteed_oee_pct=80.0,
    )
    payload["retention_balance_cents"] = 1  # ignored by the server
    proj = validate_success(
        api.create_cell_project(
            site["id"], payload, make_project_engineer_headers(eng["id"])
        ),
        201,
    )
    assert_cell_project(proj)
    assert proj["retention_balance_cents"] == 100000, (
        f"Expected server-derived 100000, got {proj['retention_balance_cents']}"
    )


def test_retention_ledger_entry_has_no_version_field(api):
    """PRD §2.4: "the `RetentionLedgerEntry` carries only `id` and
    `created_at`. Both `updated_at` and `version` are absent from ledger
    entries, because ledger postings are append-only and never modified after
    posting."

    Design: Corner/entities/retention_ledger_entry_has_no_version_field
    """
    org = create_org(retention_rate_bps=1000)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="S4")
    proj = create_project(
        site["id"],
        eng["id"],
        project_code="P-IMM",
        contracted_cycle_time_s=10.0,
        contract_value_cents=1_000_000,
        guaranteed_oee_pct=80.0,
    )

    resp = api.list_retention_ledger_entries(proj["id"], make_finance_admin_headers())
    entries, _meta = validate_paginated(resp)
    assert len(entries) == 1
    entry = entries[0]
    assert_retention_ledger_entry(entry)
    assert entry["entry_type"] == "WITHHOLD"
    assert entry["amount_cents"] == 100000

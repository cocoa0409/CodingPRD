"""Access control, optimistic concurrency and derived-counter reconciliation."""
from test_helpers import (
    ADMIN_USER_ID,
    ApiErrorId,
    add_officers,
    add_program,
    anonymous_headers,
    create_filing,
    create_grant,
    create_org,
    extract,
    file_correction_request,
    get_filing,
    get_org,
    list_fields,
    list_grants,
    make_admin_headers,
    make_organization_user_headers,
    make_verifier_headers,
    normalize,
    patch_org,
    scenario_cascade,
    scenario_funder,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_org,
)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one
    of the four declared roles, the request is refused with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other consideration."
    PRD §2.10: "An unauthenticated request never reports a not-found condition."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    set_clock()
    resp = api.get_organization("00000000-0000-4000-8000-000000000000", anonymous_headers())

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert err["error_id"] != "ERR_ORGANIZATION_NOT_FOUND", (
        "authentication is checked before existence"
    )
    assert resp.json()["response_type"] == "error"


def test_path_resources_are_resolved_left_to_right_before_body_fields(api):
    """PRD §2.10: "The order in which the not-found conditions are checked is
    therefore fixed: organization first, then filing, then extracted field, then
    license and usage event, then seal, grant, correction request and identity case."

    Design: Corner/validations/path_resources_are_resolved_left_to_right_before_body_fields
    """
    set_clock()
    resp = api.void_usage_event(
        "00000000-0000-4000-8000-0000000000aa",
        "00000000-0000-4000-8000-0000000000bb",
        make_admin_headers())

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND.value)
    assert err["error_id"] != "ERR_USAGE_EVENT_NOT_FOUND", (
        "the leftmost unresolvable identifier is the one reported"
    )


def test_platform_verifier_cannot_create_an_organization(api):
    """PRD §2.1: "If the headers are well formed but the named role is not in the
    endpoint's authorized role list, the request is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/roles/platform_verifier_cannot_create_an_organization
    """
    set_clock()
    resp = api.create_organization({
        "legal_name": "Unauthorized Assembly",
        "ein": "900100900",
        "org_type": "501C3",
        "state_code": "IL",
    }, make_verifier_headers())

    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    rows, _ = validate_paginated(api.list_organizations(make_admin_headers()))
    assert rows == []


def test_organization_user_cannot_patch_another_organization(api):
    """PRD §2.1: "Two rules cut across roles. First, an `OrganizationUser` acting
    on a resource that does not belong to its own organization is refused with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/roles/organization_user_cannot_patch_another_organization
    """
    set_clock()
    attacker = create_org("Willow Creek Collective", "900100200", state_code="IL")
    victim = create_org("Prairie Food Bank", "900100201", state_code="IL")

    resp = api.patch_organization(
        victim["id"], {"expected_organization_version": victim["version"],
                       "display_name": "Hijacked"},
        make_organization_user_headers(attacker["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    after = get_org(victim["id"])
    assert after.get("display_name") is None
    assert after["last_profile_editor_user_id"] == ADMIN_USER_ID
    assert after["version"] == victim["version"], "the rejected write advanced nothing"


def test_stale_organization_version_on_filings_create_returns_precondition_failed(api):
    """PRD §2.9: "Creating a filing requires `expected_organization_version`."
    PRD §2.9: "If another writer has advanced the organization's version since the
    client last read it, the request is refused with
    `ERR_STALE_ORGANIZATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_organization_version_on_filings_create_returns_precondition_failed
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")
    stale_version = org["version"]

    patched = patch_org(org["id"], {"expected_organization_version": stale_version,
                                    "display_name": "Willow Creek"},
                        as_org=True)
    current = validate_success(patched, 200)
    assert current["version"] == stale_version + 1

    stale_attempt = api.create_filing({
        "organization_id": org["id"],
        "form_type": "FORM_990",
        "form_version_year": 2023,
        "tax_year": 2025,
        "coverage_start": "2025-01-01T00:00:00Z",
        "coverage_end": "2025-12-31T00:00:00Z",
        "source": "IRS_BULK_XML",
        "expected_organization_version": stale_version,
    }, make_organization_user_headers(org["id"]))
    assert stale_attempt.status_code == 412, (
        f"Expected 412, got {stale_attempt.status_code}: {stale_attempt.text}"
    )
    validate_error(stale_attempt, ApiErrorId.ERR_STALE_ORGANIZATION_VERSION.value)

    fresh_attempt = api.create_filing({
        "organization_id": org["id"],
        "form_type": "FORM_990",
        "form_version_year": 2023,
        "tax_year": 2025,
        "coverage_start": "2025-01-01T00:00:00Z",
        "coverage_end": "2025-12-31T00:00:00Z",
        "source": "IRS_BULK_XML",
        "expected_organization_version": current["version"],
    }, make_organization_user_headers(org["id"]))
    filing = validate_success(fresh_attempt, 201)
    assert filing["status"] == "RECEIVED"

    rows, _ = validate_paginated(
        api.list_organization_filings(org["id"], make_admin_headers()))
    assert len(rows) == 1, "the stale attempt persisted nothing"


def test_stale_extracted_field_version_on_correction_create_returns_precondition_failed(api):
    """PRD §2.9: "Filing a correction request against an extracted field requires
    `expected_extracted_field_version`."
    PRD §2.9: "If another writer has corrected or re-normalized the field since the
    client last read it, the request is refused with
    `ERR_STALE_EXTRACTED_FIELD_VERSION` (HTTP 412) — the client is disputing a
    value that no longer exists."

    Design: Corner/cross_cutting_layers/stale_extracted_field_version_on_correction_create_returns_precondition_failed
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(filing["id"])
    field = list_fields(filing["id"], as_org=org["id"])[0]
    stale_field_version = field["version"]

    file_correction_request(org["id"], field["id"], stale_field_version,
                            requested_value="2000.00")

    resp = api.create_correction_request(
        field["id"],
        {"requested_value": "2500.00",
         "evidence_url": "https://evidence.example.org/revised.pdf",
         "justification": "Revised audited statement.",
         "expected_extracted_field_version": stale_field_version},
        make_organization_user_headers(org["id"]))
    assert resp.status_code == 412, f"Expected 412, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_STALE_EXTRACTED_FIELD_VERSION.value)

    rows, _ = validate_paginated(
        api.list_field_correction_requests(field["id"], make_verifier_headers()))
    assert len(rows) == 1

    refreshed = list_fields(filing["id"])[0]
    assert refreshed["version"] == stale_field_version + 1


def test_child_row_creation_does_not_advance_the_parent_version(api):
    """PRD §2.5: "Creating a child row does not, by itself, advance the parent
    organization's `version` — only the transitions and cascades that explicitly
    say so do."

    Design: Corner/cross_cutting_layers/child_row_creation_does_not_advance_the_parent_version
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")
    original_version = org["version"]

    add_program(org["id"], program_name="Mentoring Core", subject_code="B82",
                disclosure_level="PUBLIC")
    add_officers(org["id"], 3)

    assert get_org(org["id"])["version"] == original_version, (
        "four child rows were created and the parent version never moved"
    )

    resp = api.create_filing({
        "organization_id": org["id"],
        "form_type": "FORM_990",
        "form_version_year": 2023,
        "tax_year": 2025,
        "coverage_start": "2025-01-01T00:00:00Z",
        "coverage_end": "2025-12-31T00:00:00Z",
        "source": "IRS_BULK_XML",
        "expected_organization_version": original_version,
    }, make_organization_user_headers(org["id"]))
    filing = validate_success(resp, 201)
    assert filing["status"] == "RECEIVED"

    assert get_org(org["id"])["version"] == original_version + 1


def test_organization_version_advances_once_per_declared_write(api):
    """PRD §2.5: "`version` is a non-negative integer that starts at 1 and
    increments by 1 on every mutation of the row."
    PRD §3.5: "The filing's `version` is incremented by 1 and the organization's
    `version` is incremented by 1."

    Design: Corner/cross_cutting_layers/organization_version_advances_once_per_declared_write
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")
    add_program(org["id"], program_name="Mentoring Core", subject_code="B82",
                disclosure_level="PUBLIC")
    add_officers(org["id"], 3)

    verified = verify_org(org["id"], "DOCUMENT_VERIFIED", 1)
    assert verified["version"] == 2

    filing = create_filing(org["id"])
    assert get_org(org["id"])["version"] == 3

    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(filing["id"])

    final = get_org(org["id"])
    assert final["version"] == 4, (
        "create 1, verify 2, filing create 3, normalize 4"
    )
    assert final["total_revenue_cents"] == 100000
    assert get_filing(filing["id"])["status"] == "NORMALIZED"


def test_derived_counters_reflect_the_write_that_changed_them_within_the_same_request(api):
    """PRD §3.9: "Creating a grant recomputes the `distinct_funder_count` of both
    the recipient organization and the funder organization."
    PRD §2.11: "Reconciliation is immediate, not eventually consistent: the
    response to the request that triggered a change already reflects the recomputed
    values."

    Design: Corner/consistency_model/derived_counters_reflect_the_write_that_changed_them_within_the_same_request
    """
    set_clock()
    recipient = scenario_cascade()
    first_funder = scenario_funder()
    second_funder = scenario_funder(legal_name="Harborlight Fund", ein="900100251")

    create_grant(recipient["id"], first_funder["id"],
                 recipient_name_raw="Cascade Youth Trust", amount_cents=400000,
                 fiscal_year=2025)
    assert get_org(recipient["id"])["distinct_funder_count"] == 1

    second = create_grant(recipient["id"], second_funder["id"],
                          funder_name_raw="Harborlight Fund",
                          recipient_name_raw="Cascade Youth Trust",
                          amount_cents=600000, fiscal_year=2025)
    assert second["status"] == "RECORDED"

    after = get_org(recipient["id"])
    assert after["distinct_funder_count"] == 2, "reconciled inside the create request"
    assert len(list_grants(recipient["id"])) == 2

    again = get_org(recipient["id"])
    assert again["distinct_funder_count"] == 2, "the counter is stored, not recomputed per request"

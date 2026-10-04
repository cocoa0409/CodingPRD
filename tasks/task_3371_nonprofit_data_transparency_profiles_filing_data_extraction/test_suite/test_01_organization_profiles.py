"""Organization profile creation, retrieval, listing and self-reported defaults."""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    ApiErrorId,
    assert_pagination_meta,
    assert_success_envelope,
    create_org,
    get_org,
    make_admin_headers,
    make_data_consumer_headers,
    make_organization_user_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_organization_create_returns_every_declared_field_and_starts_draft(api):
    """PRD §3.1: "It opens in `DRAFT` profile status with `verification_level` of
    `SELF_REPORTED`, an empty `former_legal_names` array, `transparency_seal_level`
    of `NONE`, a null `seal_expires_on`, a null `latest_filing_tax_year`, a null
    `successor_organization_id`, and every derived counter ... initialised to zero."
    PRD §3.1: "The creating actor is recorded as `last_profile_editor_user_id`,
    which is the field the segregation-of-duties gate later reads."
    PRD §2.5: "`version` is a non-negative integer that starts at 1 and increments
    by 1 on every mutation of the row."

    Design: Corner/entities/organization_create_returns_every_declared_field_and_starts_draft
    """
    set_clock()
    resp = api.create_organization({
        "legal_name": "Willow Creek Collective",
        "ein": "900100200",
        "org_type": "501C3",
        "state_code": "IL",
        "ntee_code": "B82",
        "mission_statement": "Mentoring and scholarships for first-generation students.",
    }, make_admin_headers())

    body = assert_success_envelope(resp)
    assert resp.status_code == 201, f"Creating an organization returns 201, got {resp.status_code}"
    assert body["response_type"] == "object"
    org = validate_success(resp, 201)

    assert org["profile_status"] == "DRAFT"
    assert org["verification_level"] == "SELF_REPORTED"
    assert org["version"] == 1
    assert org["former_legal_names"] == []
    assert org["transparency_seal_level"] == "NONE"
    assert org.get("seal_expires_on") is None
    assert org["total_revenue_cents"] == 0
    assert org["distinct_funder_count"] == 0
    assert org["active_license_count"] == 0
    assert org["open_correction_count"] == 0
    assert org["verification_evidence_count"] == 0
    assert org["latest_filing_tax_year"] is None
    assert org["successor_organization_id"] is None
    assert org["last_profile_editor_user_id"] == ADMIN_USER_ID


def test_organization_get_returns_the_stored_profile_unchanged(api):
    """PRD §3.1: "The mandatory attributes are the registered `legal_name`, the
    nine-digit `ein`, the `org_type` and the two-letter `state_code` of
    incorporation; the optional attributes are a public-facing `display_name`,
    an NTEE subject-area taxonomy code in `ntee_code`, a free-text
    `mission_statement`".

    Design: Corner/entities/organization_get_returns_the_stored_profile_unchanged
    """
    set_clock()
    org = create_org(
        "Willow Creek Collective", "900100200", state_code="IL", ntee_code="B82",
        mission_statement="Mentoring and scholarships for first-generation students.")

    resp = api.get_organization(org["id"], make_data_consumer_headers(org["id"]))
    data = validate_success(resp, 200)

    assert data["legal_name"] == "Willow Creek Collective"
    assert data["ein"] == "900100200"
    assert data["org_type"] == "501C3"
    assert data["state_code"] == "IL"
    assert data["ntee_code"] == "B82"
    assert data.get("display_name") is None
    assert data["mission_statement"] == (
        "Mentoring and scholarships for first-generation students.")


def test_organization_list_paginates_and_reports_total_count_and_has_more(api):
    """PRD §2.3: "`total_count` is the number of resources matching the filter
    across all pages, not the number in the current page, and `has_more` is true
    exactly when `offset` plus the number of items in the current page is less
    than `total_count`."
    PRD §2.3: "When `limit` is omitted it defaults to 10; the smallest accepted
    value is 1 and the largest accepted value is 100. When `offset` is omitted it
    defaults to 0."

    Design: Corner/entities/organization_list_paginates_and_reports_total_count_and_has_more
    """
    set_clock()
    create_org("Willow Creek Collective", "900100200", state_code="IL")
    create_org("Prairie Food Bank", "900100201", state_code="IL")
    create_org("Lakeshore Conservancy", "900100202", state_code="WI")

    page_one = api.list_organizations(make_admin_headers(), {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(page_one)
    assert len(rows) == 2, f"Expected a full first page of 2, got {len(rows)}"
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

    page_two = api.list_organizations(make_admin_headers(), {"limit": 2, "offset": 2})
    rows_two, meta_two = validate_paginated(page_two)
    assert len(rows_two) == 1, f"Expected the remaining row, got {len(rows_two)}"
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)

    default_page = api.list_organizations(make_admin_headers())
    rows_default, meta_default = validate_paginated(default_page)
    assert len(rows_default) == 3, "All three organizations fit inside the default page"
    assert_pagination_meta(meta_default, limit=10, offset=0, total_count=3, has_more=False)


def test_organization_get_with_an_unknown_id_returns_organization_not_found(api):
    """PRD §2.10: "When a request path contains more than one resource identifier,
    the identifiers are validated for existence in left-to-right path order. The
    first identifier that does not resolve to a row produces the corresponding
    not-found error and nothing later in the path is examined."
    PRD §5: `ERR_ORGANIZATION_NOT_FOUND` is a 404.

    Design: Corner/entities/organization_get_with_an_unknown_id_returns_organization_not_found
    """
    set_clock()
    unknown = "00000000-0000-4000-8000-000000000000"
    resp = api.get_organization(unknown, make_admin_headers())

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_ORGANIZATION_NOT_FOUND.value)
    assert err["error_id"] == "ERR_ORGANIZATION_NOT_FOUND"
    assert resp.json()["response_type"] == "error"


def test_organization_create_missing_ein_returns_invalid_request(api):
    """PRD §2.10: "Missing or ill-typed required body fields, body fields not
    declared in the endpoint's input list, unknown enum members, and out-of-range
    numerics ... all yield `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "The mandatory attributes are the registered `legal_name`, the
    nine-digit `ein`, the `org_type` and the two-letter `state_code` of incorporation".

    Design: Corner/entities/organization_create_missing_ein_returns_invalid_request
    """
    set_clock()
    resp = api.create_organization({
        "legal_name": "No Ein Coalition",
        "org_type": "501C3",
        "state_code": "IL",
    }, make_admin_headers())

    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert err["error_id"] != "ERR_EIN_ALREADY_REGISTERED", (
        "A missing ein is a shape failure, not a uniqueness failure"
    )

    rows, meta = validate_paginated(api.list_organizations(make_admin_headers()))
    assert len(rows) == 0, "The rejected create must not persist an organization"
    assert meta["total_count"] == 0


def test_program_disclosure_level_defaults_to_restricted_when_omitted(api):
    """PRD §3.1: "The `disclosure_level` of a program, of a leadership member and
    of a demographic record is one of `PUBLIC`, `RESTRICTED` or `WITHHELD`; when a
    program or a leadership member is created without one, the server stores
    `RESTRICTED`."
    PRD §3.1: "A program is born `ACTIVE` and unverified — `status` is `ACTIVE` and
    `is_verified` is false".

    Design: Corner/entities/program_disclosure_level_defaults_to_restricted_when_omitted
    """
    set_clock()
    org = create_org(
        "Willow Creek Collective", "900100200", state_code="IL", ntee_code="B82",
        mission_statement="Mentoring and scholarships for first-generation students.")

    resp = api.create_program(
        org["id"],
        {"program_name": "Quiet Mentoring", "fiscal_year": 2025, "subject_code": "B82"},
        make_organization_user_headers(org["id"]))
    program = validate_success(resp, 201)

    assert program["disclosure_level"] == "RESTRICTED"
    assert program["status"] == "ACTIVE"
    assert program["is_verified"] is False

    # disclosure_pct = PROGRAMS 0.5 * 0.15 + MISSION 1.0 * 0.10 = 0.1750
    updated = get_org(org["id"])
    assert updated["disclosure_pct"] == pytest.approx(0.1750, abs=1e-6), (
        "A RESTRICTED program contributes the 0.5 PROGRAMS rung; the complete "
        "mission block contributes its full 0.10 weight"
    )

    rows, meta = validate_paginated(
        api.list_programs(org["id"], make_organization_user_headers(org["id"])))
    assert len(rows) == 1, "Exactly one program row exists"

"""Information returns: revision creation, extraction, voiding and coverage."""
from test_helpers import (
    ApiErrorId,
    create_filing,
    create_org,
    extract,
    get_filing,
    get_org,
    list_fields,
    make_admin_headers,
    make_organization_user_headers,
    make_verifier_headers,
    normalize,
    scenario_cascade,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    void_filing,
)


def test_filing_create_checks_body_foreign_keys_before_form_version_membership(api):
    """PRD §2.10: "Body identifiers are resolved in the order the endpoint's input
    list declares them."
    PRD §2.7: "A filing whose `form_version_year` falls outside that set, or an
    extraction request supplying any `line_code` that is not a member of the row
    for the filing's declared version, is refused with `ERR_UNSUPPORTED_FORM_VERSION`
    (HTTP 422)."
    PRD §5: `ERR_ORGANIZATION_NOT_FOUND` is a 404.

    Design: Corner/entities/filing_create_checks_body_foreign_keys_before_form_version_membership
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")

    unknown_org_payload = {
        "organization_id": "00000000-0000-4000-8000-000000000009",
        "form_type": "FORM_990",
        "form_version_year": 1999,
        "tax_year": 2025,
        "coverage_start": "2025-01-01T00:00:00Z",
        "coverage_end": "2025-12-31T00:00:00Z",
        "source": "IRS_BULK_XML",
        "expected_organization_version": org["version"],
    }
    # The acting role must be one the ownership rule does not bind: an
    # OrganizationUser naming a foreign organization_id is refused with
    # ERR_FORBIDDEN_ROLE at rung 2 (PRD §2.1, §2.10), which would pre-empt the
    # body-identifier resolution this test is about. A PlatformAdmin is an
    # authorized submitter (PRD §3.4) with no ownership gate.
    resp = api.create_filing(unknown_org_payload, make_admin_headers())
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_ORGANIZATION_NOT_FOUND.value)

    bad_version_payload = dict(unknown_org_payload, organization_id=org["id"])
    resp_two = api.create_filing(bad_version_payload, make_organization_user_headers(org["id"]))
    assert resp_two.status_code == 422, f"Expected 422, got {resp_two.status_code}: {resp_two.text}"
    validate_error(resp_two, ApiErrorId.ERR_UNSUPPORTED_FORM_VERSION.value)

    rows, _ = validate_paginated(
        api.list_organization_filings(org["id"], make_admin_headers()))
    assert len(rows) == 0, "Neither rejected create may persist a filing"


def test_filing_starts_in_received_with_zeroed_computed_fields(api):
    """PRD §3.4: "The new row itself opens in `RECEIVED` with `extracted_field_count`
    0 and `total_revenue_cents` 0".
    PRD §3.4: "Its `revision_number` is one more than the greatest `revision_number`
    already recorded for the same `organization_id`, `tax_year` and `form_type`,
    or 1 when no such filing exists."

    Design: Corner/state_machines/filing_starts_in_received_with_zeroed_computed_fields
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")

    resp = api.create_filing({
        "organization_id": org["id"],
        "form_type": "FORM_990",
        "form_version_year": 2023,
        "tax_year": 2025,
        "coverage_start": "2025-01-01T00:00:00Z",
        "coverage_end": "2025-12-31T00:00:00Z",
        "source": "IRS_BULK_XML",
        "expected_organization_version": org["version"],
    }, make_organization_user_headers(org["id"]))
    filing = validate_success(resp, 201)

    assert filing["status"] == "RECEIVED"
    assert filing["revision_number"] == 1
    assert filing["extracted_field_count"] == 0
    assert filing["total_revenue_cents"] == 0
    assert filing.get("superseded_by_revision_number") is None
    assert filing.get("pre_supersede_status") is None
    assert filing["is_verified"] is False


def test_filing_normalize_from_received_returns_invalid_state(api):
    """PRD §2.10: "State comes next. A requested transition that is not declared
    for the resource's current state yields `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "The filing must have at least one `ExtractedField` row; a normalize
    request against a filing with none is refused with `ERR_NO_EXTRACTED_FIELDS`
    (HTTP 422)."

    Design: Corner/state_machines/filing_normalize_from_received_returns_invalid_state
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])

    resp = api.normalize_filing(filing["id"], make_verifier_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_filing(filing["id"])
    assert after["status"] == "RECEIVED"
    assert after["total_revenue_cents"] == 0
    assert list_fields(filing["id"]) == []


def test_voided_filing_is_terminal_and_cannot_be_voided_twice(api):
    """PRD §3.5: "A filing in `RECEIVED`, `EXTRACTED`, `EXTRACTION_FAILED`,
    `NORMALIZED` or `DISPUTED` moves to `VOIDED`".
    PRD §2.10: "A requested transition that is not declared for the resource's
    current state yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/voided_filing_is_terminal_and_cannot_be_voided_twice
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(filing["id"])
    void_filing(filing["id"])

    second = api.void_filing(filing["id"], make_admin_headers())
    assert second.status_code == 409, f"Expected 409, got {second.status_code}: {second.text}"
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    re_extract = api.extract_filing(
        filing["id"],
        {"raw_lines": [{"line_code": "TOTREV", "raw_value": "5000.00",
                        "raw_format": "USD_WHOLE", "is_revenue_component": True}]},
        make_verifier_headers())
    assert re_extract.status_code == 409, (
        f"Expected 409 for extract on a VOIDED filing, got {re_extract.status_code}"
    )
    validate_error(re_extract, ApiErrorId.ERR_INVALID_STATE.value)

    assert get_filing(filing["id"])["status"] == "VOIDED"
    assert get_org(org["id"])["total_revenue_cents"] == 0


def test_gov_grants_line_on_a_2019_form_returns_unsupported_form_version(api):
    """PRD §2.7: "Note the asymmetry this creates: `GOV_GRANTS` does not exist
    before version 2020 and `CRYPTO_HOLDINGS` does not exist before version 2024,
    so the identical line code is valid against one version year and rejected
    against another."
    PRD §3.4: "Extraction is all-or-nothing: there is no partial acceptance."

    Design: Corner/errors/gov_grants_line_on_a_2019_form_returns_unsupported_form_version
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"], form_version_year=2019)

    resp = api.extract_filing(
        filing["id"],
        {"raw_lines": [{"line_code": "GOV_GRANTS", "raw_value": "500.00",
                        "raw_format": "USD_WHOLE", "is_revenue_component": True}]},
        make_verifier_headers())
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_UNSUPPORTED_FORM_VERSION.value)

    after = get_filing(filing["id"])
    assert after["status"] == "RECEIVED"
    assert after["extracted_field_count"] == 0
    assert list_fields(filing["id"]) == []


def test_extract_with_an_empty_raw_lines_array_returns_no_extracted_fields(api):
    """PRD §3.4: "A request carrying an empty array is refused with
    `ERR_NO_EXTRACTED_FIELDS` (HTTP 422), no extracted rows are created, and the
    filing is not advanced past `RECEIVED` by that request."
    PRD §3.4: "When the request supplies a non-empty `raw_lines` array in which no
    line yields a parseable decimal `raw_value`, the extraction fails without a
    client error: the filing moves from `RECEIVED` to `EXTRACTION_FAILED`,
    `extracted_field_count` is set to 0 and `extraction_confidence_pct` is set to null."

    Design: Corner/errors/extract_with_an_empty_raw_lines_array_returns_no_extracted_fields
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])

    empty = api.extract_filing(filing["id"], {"raw_lines": []}, make_verifier_headers())
    assert empty.status_code == 422, f"Expected 422, got {empty.status_code}: {empty.text}"
    validate_error(empty, ApiErrorId.ERR_NO_EXTRACTED_FIELDS.value)
    assert get_filing(filing["id"])["status"] == "RECEIVED"

    unparseable = api.extract_filing(
        filing["id"],
        {"raw_lines": [{"line_code": "TOTREV", "raw_value": "not-a-number",
                        "raw_format": "USD_WHOLE", "is_revenue_component": True}]},
        make_verifier_headers())
    failed = validate_success(unparseable, 200)
    assert failed["status"] == "EXTRACTION_FAILED", (
        "A non-empty but unreadable batch is a state transition, not an error"
    )
    assert failed["extracted_field_count"] == 0
    assert failed.get("extraction_confidence_pct") is None


def test_filing_extract_action_creates_one_field_per_line_and_reports_confidence(api):
    """PRD §3.4: "Each row also carries a `confidence_pct` determined solely by its
    declared `raw_format`: 99.0 for `USD_WHOLE` and for `PLAIN_INTEGER`, 92.0 for
    `USD_THOUSANDS`, and 85.0 for `USD_MILLIONS`."
    PRD §3.4: "The filing then advances from `RECEIVED` to `EXTRACTED`, its
    `extracted_field_count` becomes the number of rows created, and its
    `extraction_confidence_pct` becomes the mean of those rows' `confidence_pct` values."

    Design: Corner/endpoints/filing_extract_action_creates_one_field_per_line_and_reports_confidence
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])

    resp = api.extract_filing(filing["id"], {"raw_lines": [
        {"line_code": "TOTREV", "raw_value": "1000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "500.00", "raw_format": "USD_THOUSANDS",
         "is_revenue_component": True},
        {"line_code": "CONTRIB", "raw_value": "0.25", "raw_format": "USD_MILLIONS",
         "is_revenue_component": True},
    ]}, make_verifier_headers())
    extracted = validate_success(resp, 200)

    assert extracted["status"] == "EXTRACTED"
    assert extracted["extracted_field_count"] == 3
    assert extracted["extraction_confidence_pct"] == 92.0, (
        "mean of 99.0, 92.0 and 85.0"
    )

    fields = list_fields(filing["id"])
    assert len(fields) == 3
    assert all(f["normalization_status"] == "PENDING" for f in fields)
    assert all(f["is_revenue_component"] is True for f in fields)
    by_code = {f["line_code"]: f for f in fields}
    assert by_code["TOTREV"]["confidence_pct"] == 99.0
    assert by_code["PROGREV"]["confidence_pct"] == 92.0
    assert by_code["CONTRIB"]["confidence_pct"] == 85.0


# ---------------------------------------------------------------------------
# Closed coverage intervals (difficulty instance)
# ---------------------------------------------------------------------------

def test_filing_closed_coverage_rejects_a_touching_interval(api):
    """PRD §3.4: "A filing's coverage interval is closed at both ends, and it may
    not touch or overlap the coverage interval of a filing of the same organization
    that carries a *different* `form_type` and is neither `SUPERSEDED` nor `VOIDED`.
    Touching endpoints count, so a period beginning on the day another ends is an
    overlap. A collision is refused with `ERR_FILING_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/filing_closed_coverage_intervals_reject_touching_endpoints
    """
    set_clock()
    org = scenario_cascade()
    create_filing(org["id"], form_type="FORM_990",
                  coverage_start="2025-01-01T00:00:00Z",
                  coverage_end="2025-12-31T00:00:00Z", tax_year=2025)

    resp = api.create_filing({
        "organization_id": org["id"],
        "form_type": "FORM_990_EZ",
        "form_version_year": 2023,
        "tax_year": 2025,
        "coverage_start": "2025-12-31T00:00:00Z",
        "coverage_end": "2026-12-31T00:00:00Z",
        "source": "ORG_UPLOAD",
        "expected_organization_version": get_org(org["id"])["version"],
    }, make_organization_user_headers(org["id"]))

    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_FILING_COVERAGE_OVERLAP.value)
    assert err["error_id"] == "ERR_FILING_COVERAGE_OVERLAP"

    rows, meta = validate_paginated(
        api.list_organization_filings(org["id"], make_admin_headers()))
    assert len(rows) == 1, "The rejected revision must not be persisted"


def test_filing_closed_coverage_accepts_a_disjoint_interval(api):
    """PRD §3.4: "Revisions of the same `form_type` are exempt, because replacing
    a return with a corrected return is the entire point of revisioning."
    PRD §3.4: "The new row itself opens in `RECEIVED` with `extracted_field_count`
    0 and `total_revenue_cents` 0".

    Design: Difficulty/resource_temporal_overlap/filing_closed_coverage_intervals_reject_touching_endpoints
    """
    set_clock()
    org = scenario_cascade()
    create_filing(org["id"], form_type="FORM_990",
                  coverage_start="2025-01-01T00:00:00Z",
                  coverage_end="2025-12-31T00:00:00Z", tax_year=2025)

    resp = api.create_filing({
        "organization_id": org["id"],
        "form_type": "FORM_990_EZ",
        "form_version_year": 2023,
        "tax_year": 2026,
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-12-31T00:00:00Z",
        "source": "ORG_UPLOAD",
        "expected_organization_version": get_org(org["id"])["version"],
    }, make_organization_user_headers(org["id"]))
    filing = validate_success(resp, 201)

    assert filing["status"] == "RECEIVED"
    assert filing["form_type"] == "FORM_990_EZ"
    assert filing["tax_year"] == 2026

    rows, meta = validate_paginated(
        api.list_organization_filings(org["id"], make_admin_headers()))
    assert len(rows) == 2
    assert meta["total_count"] == 2

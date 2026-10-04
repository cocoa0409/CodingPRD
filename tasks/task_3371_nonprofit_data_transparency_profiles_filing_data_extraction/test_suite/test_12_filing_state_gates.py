"""Gates that refuse a filing operation: the filing's own state and the owning
organization's standing."""
from test_helpers import (
    ApiErrorId,
    create_filing,
    extract,
    finalize_identity_case,
    get_filing,
    get_org,
    list_fields,
    make_verifier_headers,
    open_identity_case,
    scenario_cascade,
    set_clock,
    validate_error,
)


def test_normalize_on_a_failed_filing_reports_the_state_error_not_the_zero_field_constraint(api):
    """PRD §2.10: "State comes next. A requested transition that is not declared
    for the resource's current state yields `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "The filing must have at least one `ExtractedField` row; a normalize
    request against a filing with none is refused with `ERR_NO_EXTRACTED_FIELDS`
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/normalize_on_failed_filing_prefers_state_over_zero_field_constraint
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "NOT_A_NUMBER",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    failed = get_filing(filing["id"])
    assert failed["status"] == "EXTRACTION_FAILED"
    assert failed["extracted_field_count"] == 0

    resp = api.normalize_filing(filing["id"], make_verifier_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != "ERR_NO_EXTRACTED_FIELDS", (
        "the state rung outranks the zero-field business constraint"
    )

    after = get_filing(filing["id"])
    assert after["status"] == "EXTRACTION_FAILED"
    assert after["extracted_field_count"] == 0


def test_the_zero_field_extraction_constraint_still_fires_on_its_own(api):
    """PRD §3.4: "A request carrying an empty array is refused with
    `ERR_NO_EXTRACTED_FIELDS` (HTTP 422), no extracted rows are created, and the
    filing is not advanced past `RECEIVED` by that request."

    Design: Difficulty/priority_pair_validation_conflict/normalize_on_failed_filing_prefers_state_over_zero_field_constraint
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "NOT_A_NUMBER",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])

    resp = api.extract_filing(filing["id"], {"raw_lines": []}, make_verifier_headers())
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_NO_EXTRACTED_FIELDS.value)

    after = get_filing(filing["id"])
    assert after["status"] == "EXTRACTION_FAILED", (
        "the refused request mutates nothing"
    )
    assert after["extracted_field_count"] == 0
    assert list_fields(filing["id"]) == []


def test_normalize_is_refused_when_the_owning_organization_is_dissolved(api):
    """PRD §2.6: "A filing may be extracted or normalized only while its owning
    organization's `profile_status` is `DRAFT` or `ACTIVE`."
    PRD §2.6: "An organization that is `SUSPENDED`, `MERGED` or `DISSOLVED`
    therefore fails every one of these gates."

    Design: Difficulty/cross_entity_state_dependency/filing_normalize_requires_owning_organization_in_good_standing
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    assert get_filing(filing["id"])["status"] == "EXTRACTED"

    case = open_identity_case(org["id"], "DISSOLUTION",
                              resolution_note="Cascade Youth Trust wound down operations.")
    finalize_identity_case(case["id"])
    assert get_org(org["id"])["profile_status"] == "DISSOLVED"

    resp = api.normalize_filing(filing["id"], make_verifier_headers())
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_ORG_NOT_IN_GOOD_STANDING.value)

    after = get_filing(filing["id"])
    assert after["status"] == "EXTRACTED"
    assert after["total_revenue_cents"] == 0
    fields = list_fields(filing["id"])
    assert all(f["normalization_status"] == "PENDING" for f in fields)
    assert get_org(org["id"])["profile_status"] == "DISSOLVED"


def test_the_dissolved_organization_gate_is_cross_entity_not_a_filing_state_error(api):
    """PRD §2.10: "Business safety gates come next, in this order:"
    PRD §2.10: "the good-standing requirement that a filing's organization be
    `DRAFT` or `ACTIVE` for extraction and normalization".

    Design: Difficulty/cross_entity_state_dependency/filing_normalize_requires_owning_organization_in_good_standing
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    field_version_before = list_fields(filing["id"])[0]["version"]

    case = open_identity_case(org["id"], "DISSOLUTION",
                              resolution_note="Cascade Youth Trust wound down operations.")
    finalize_identity_case(case["id"])

    resp = api.normalize_filing(filing["id"], make_verifier_headers())
    err = validate_error(resp, ApiErrorId.ERR_ORG_NOT_IN_GOOD_STANDING.value)
    assert err["error_id"] != "ERR_INVALID_STATE", (
        "EXTRACTED is a state from which normalize is declared; the refusal comes "
        "from the organization the request never mentions"
    )
    assert resp.status_code == 403

    unchanged = list_fields(filing["id"])[0]
    assert unchanged["normalization_status"] == "PENDING"
    assert unchanged["version"] == field_version_before
    assert unchanged.get("normalized_value_cents") is None

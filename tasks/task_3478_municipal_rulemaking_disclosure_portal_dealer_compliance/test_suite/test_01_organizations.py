"""Organization registration and record-shape claims (PRD sections 2.5, 2.8, 3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_organization,
    assert_solicitation_record,
    create_advisor_org,
    create_solicitation,
    make_dealer_rep_headers,
    validate_error,
    validate_success,
)

MISSING_ORG_ID = "11111111-2222-3333-4444-555555555555"


def test_organization_created_active_clear_with_zeroed_counters(api):
    """PRD section 3.5: "An organization is born `ACTIVE` with a
    `compliance_posture` of `CLEAR` and all derived counters —
    `late_report_count`, `published_par_total`, and
    `active_professional_count` — at zero."

    Design: Corner/entities/organization_create_applies_system_defaults
    """
    resp = api.create_organization(
        {"org_code": "BD-0001", "name": "Dealer Zero", "org_type": "BROKER_DEALER"},
        TEST_USERS["portal_operator_headers"],
    )
    data = validate_success(resp, 201)
    assert_organization(data)
    assert data["status"] == "ACTIVE", f"fresh org must be ACTIVE, got {data['status']!r}"
    assert data["compliance_posture"] == "CLEAR", (
        f"fresh org posture must be CLEAR, got {data['compliance_posture']!r}"
    )
    assert data["late_report_count"] == 0
    assert data["published_par_total"] == 0
    assert data["active_professional_count"] == 0


def test_organization_missing_org_type_rejected(api):
    """PRD section 2.5 step 3: "Required fields present, types correct, enum
    values within their declared sets, unknown fields ignored, and domain
    ranges enforced" (HTTP 400). PRD section 3.5 names `org_type` as one of
    the three registration inputs.

    Design: Corner/entities/organization_missing_org_type_returns_invalid_request
    """
    resp = api.create_organization(
        {"org_code": "BD-0002", "name": "No Type Dealer"},
        TEST_USERS["portal_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_organization_unknown_org_type_rejected(api):
    """PRD section 3.5: an organization is registered with "an `org_type` of
    exactly one of `ISSUER`, `OBLIGATED_PERSON`, `BROKER_DEALER`, or
    `MUNICIPAL_ADVISOR`"; section 2.5 step 3 rejects enum values outside
    their declared sets with ERR_INVALID_REQUEST (HTTP 400).

    Design: Corner/entities/organization_invalid_org_type_returns_invalid_request
    """
    resp = api.create_organization(
        {"org_code": "BD-0003", "name": "Fund", "org_type": "HEDGE_FUND"},
        TEST_USERS["portal_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_organization_computed_fields_in_input_are_ignored(api):
    """PRD section 2.5 step 3: "unknown fields ignored". PRD section 3.5:
    "An organization is born `ACTIVE` with a `compliance_posture` of `CLEAR`
    and all derived counters — `late_report_count`, `published_par_total`,
    and `active_professional_count` — at zero." Client-supplied values for
    the derived fields must not stick.

    Design: Corner/entities/organization_computed_fields_input_ignored
    """
    resp = api.create_organization(
        {
            "org_code": "BD-0004",
            "name": "Sneaky Dealer",
            "org_type": "BROKER_DEALER",
            "late_report_count": 99,
            "compliance_posture": "WATCH",
        },
        TEST_USERS["portal_operator_headers"],
    )
    data = validate_success(resp, 201)
    assert data["late_report_count"] == 0, (
        f"client-supplied late_report_count must be ignored, got {data['late_report_count']}"
    )
    assert data["compliance_posture"] == "CLEAR", (
        f"client-supplied compliance_posture must be ignored, got {data['compliance_posture']!r}"
    )


def test_organization_get_unknown_id_returns_org_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier: `ERR_ORG_NOT_FOUND` for organizations" (HTTP 404).

    Design: Corner/entities/organization_get_missing_id_returns_not_found
    """
    resp = api.get_organization(MISSING_ORG_ID, TEST_USERS["portal_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_ORG_NOT_FOUND)


def test_solicitation_record_is_append_only_shaped(api):
    """PRD section 2.8: "an `ExamAttempt` and a `SolicitationRecord` each
    carry only `id` and `created_at`; both `updated_at` and `version` are
    absent on them, because neither record is ever modified after creation."
    PRD section 3.8: "Solicitation records undergo no state transitions and,
    per §2.8, carry only `id` and `created_at`."

    Design: Corner/entities/solicitation_record_has_no_version_or_updated_at
    """
    org = create_advisor_org(api, org_code="MA-0005", name="Advisor Five")
    resp = api.create_solicitation_record(
        {
            "advisor_org_id": org["id"],
            "municipal_entity_name": "City of Example",
            "compensation_type": "FIXED",
            "compensation_cents": 100000,
            "disclosure_provided": True,
        },
        make_dealer_rep_headers(org["id"]),
    )
    data = validate_success(resp, 201)
    assert_solicitation_record(data)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"

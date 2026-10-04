"""Eligibility filings, the candidacy clock, and liaison ownership binding."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_ISO,
    adjudicate_application,
    adjudicate_payload,
    create_eligibility_application,
    create_institution,
    eligibility_application_payload,
    file_eligibility_application,
    get_institution,
    make_liaison_headers,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_eligibility_create_missing_pathway_rejected(api, staff_headers):
    """PRD section 2.8: "Payloads that are structurally malformed — a missing required field, a value of the wrong type, an invalid enum member, or a missing type-specific detail field such as `requested_program_level` on a `PROGRAM_LEVEL` change — are rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD section 3.2: "An institution enters the pipeline when its `InstitutionLiaison` drafts an `EligibilityApplication` naming the requested `pathway` — `STANDARD`, a four-year candidacy, or `ACCELERATED`, a two-year candidacy — together with a free-text `statement_of_intent`."

    Design: Corner/entities/eligibility_create_missing_required_pathway_returns_invalid_request
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]

    response = api.create_eligibility_application(
        institution_id,
        {"statement_of_intent": "Missing the pathway field."},
        make_liaison_headers(institution_id),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)

    applications, _meta = validate_paginated(
        api.list_eligibility_applications(institution_id, staff_headers)
    )
    assert applications == []


def test_eligibility_approval_stamps_candidacy_window(api, staff_headers):
    """PRD section 3.2: "It is permitted only while the institution is still `PROSPECTIVE` — adjudicating approval against an institution in any other standing is rejected with `ERR_INVALID_STATE` — and it moves the application itself to the terminal `APPROVED` while promoting the institution from `PROSPECTIVE` to `CANDIDATE`: the approved application's `pathway` is copied onto `candidacy_pathway`, `candidacy_started_at` is stamped with the logical clock, and `candidacy_expires_at` is computed as the candidacy start plus the pathway length, four years for `STANDARD` and two years for `ACCELERATED`."

    Design: Corner/entities/eligibility_approval_stamps_candidacy_window
    """
    set_logical_clock()
    standard = create_institution()
    standard_id = standard["id"]
    standard_app = create_eligibility_application(standard_id, pathway="STANDARD")
    file_eligibility_application(standard_app["id"], standard_id)

    accelerated = create_institution(
        legal_name="Accelerated Academy", legal_status="PRIVATE_FORPROFIT",
        state_code="MO", fte_enrollment=250, degree_levels_offered=["ASSOCIATE"],
    )
    accelerated_id = accelerated["id"]
    accelerated_app = create_eligibility_application(accelerated_id, pathway="ACCELERATED")
    file_eligibility_application(accelerated_app["id"], accelerated_id)

    adjudicate_application(standard_app["id"], "APPROVE",
                           "Eligibility granted on the standard pathway.")
    adjudicate_application(accelerated_app["id"], "APPROVE")

    first = get_institution(standard_id)
    assert first["accreditation_status"] == "CANDIDATE"
    assert first["candidacy_pathway"] == "STANDARD"
    assert _parse_instant(first["candidacy_started_at"]) == _parse_instant(CLOCK_DEFAULT_ISO)
    assert _parse_instant(first["candidacy_expires_at"]) == _parse_instant("2030-09-01T00:00:00Z")

    second = get_institution(accelerated_id)
    assert second["candidacy_pathway"] == "ACCELERATED"
    assert _parse_instant(second["candidacy_expires_at"]) == _parse_instant("2028-09-01T00:00:00Z")


def test_eligibility_deficiency_refiling_loop(api, staff_headers):
    """PRD section 3.2: "A completion request moves it to `DEFICIENT`, from which the liaison may re-file — the deficiency loop returns the application to `FILED` with a fresh `filed_at` and may repeat."
    PRD section 3.2: "Denial moves the application to the terminal `DENIED`."

    Design: Corner/state_machines/eligibility_deficiency_refiling_loop
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    application = create_eligibility_application(institution_id)
    file_eligibility_application(application["id"], institution_id)

    deficient = adjudicate_application(
        application["id"], "REQUEST_COMPLETION", "Missing financial exhibit."
    )
    assert deficient["status"] == "DEFICIENT"

    refiled = file_eligibility_application(application["id"], institution_id)
    assert refiled["status"] == "FILED"

    denied = adjudicate_application(
        application["id"], "DENY", "Incomplete after resubmission."
    )
    assert denied["status"] == "DENIED"
    assert get_institution(institution_id)["accreditation_status"] == "PROSPECTIVE"


def test_denied_application_cannot_be_refiled(api, staff_headers):
    """PRD section 3.2: "Denial moves the application to the terminal `DENIED`."
    PRD section 2.8: "A request that would fail several checks receives the error of the first check in the evaluation order — the first failure wins."

    Design: Corner/state_machines/terminal_denied_application_cannot_refile
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    application = create_eligibility_application(institution_id)
    file_eligibility_application(application["id"], institution_id)
    adjudicate_application(application["id"], "DENY")

    response = api.file_eligibility_application(
        application["id"], {}, make_liaison_headers(institution_id)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    applications, _meta = validate_paginated(
        api.list_eligibility_applications(institution_id, staff_headers)
    )
    assert applications[0]["status"] == "DENIED"


def test_liaison_cannot_adjudicate_own_application(api, staff_headers):
    """PRD section 2.1: "A request whose role is not among the roles authorized for the target endpoint, or that fails the entity-backed ownership binding described below, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST   | `/accreditation/eligibility-applications/{id}/adjudicate` | Adjudicate a filed application: approve, deny, or request completion | CommissionStaff |"

    Design: Corner/rbac/liaison_cannot_adjudicate_own_eligibility
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    application = create_eligibility_application(institution_id)
    file_eligibility_application(application["id"], institution_id)

    response = api.adjudicate_eligibility_application(
        application["id"],
        adjudicate_payload("APPROVE"),
        make_liaison_headers(institution_id),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    applications, _meta = validate_paginated(
        api.list_eligibility_applications(institution_id, staff_headers)
    )
    assert applications[0]["status"] == "FILED"


def test_liaison_cannot_file_for_foreign_institution(api, staff_headers):
    """PRD section 2.1: "When `X-User-Role` is `InstitutionLiaison`, `X-User-ID` is the `id` of the `Institution` the liaison represents; ownership checks on any resource that belongs to an institution — directly, or through the resource's parent chain of eligibility application, review cycle, assurance argument, evidence item, substantive-change request, or indicator report — compare the institution's `id` at the root of that chain to `X-User-ID`, so a liaison acting on another institution's resources is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/liaison_cannot_file_for_foreign_institution
    """
    set_logical_clock()
    own = create_institution()
    foreign = create_institution(
        legal_name="Foreign College", legal_status="PUBLIC",
        state_code="MN", fte_enrollment=400, degree_levels_offered=["BACCALAUREATE"],
    )

    response = api.create_eligibility_application(
        foreign["id"],
        eligibility_application_payload(statement_of_intent="Filed by the wrong liaison."),
        make_liaison_headers(own["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    applications, _meta = validate_paginated(
        api.list_eligibility_applications(foreign["id"], staff_headers)
    )
    assert applications == []

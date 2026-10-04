"""Corner breadth index (validations): the header-presence gate, existence
preceding state on transition endpoints, and the single-active-spec rule.
"""
from test_helpers import (
    PROJECT_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    create_coating_system,
    create_project,
    create_specification,
    create_world,
    headers_without_user_id,
    issue_payload,
    make_applicator_rep_headers,
    project_payload,
    read_project,
    read_specification,
    validate_error,
)


def test_missing_user_context_header_rejected(api: ApiClient):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act. A request in which either header is missing or
    malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    response = api.create_project(
        project_payload(project_name="No Header", warranty_budget_cents=1_000),
        headers_without_user_id("ProjectEngineer"),
    )
    validate_error(
        response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400
    )


def test_existence_checked_before_state_on_transition(api: ApiClient):
    """PRD §2.8: "the server validates the identifiers' existence
    sequentially, left to right, and rejects the request immediately with the
    not-found error corresponding to the first identifier that does not
    resolve to an existing resource — before any later identifier, state
    check, or business rule is examined."

    Design: Corner/validations/existence_checked_before_state_on_transition
    """
    project = create_project(api, project_name="Order Of Checks", warranty_budget_cents=1_000)

    response = api.begin_prep_inspection(
        project["id"],
        "00000000-0000-4000-8000-000000000099",
        make_applicator_rep_headers("00000000-0000-4000-8000-0000000000aa"),
    )

    validate_error(response, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND, expected_status=404)


def test_active_spec_exists_on_second_issue_without_supersede(api: ApiClient):
    """PRD §3.4: "no other specification on this project may currently be
    `ISSUED` unless this issuance supersedes it through the draft's
    `supersedes_specification_id` link (`ERR_ACTIVE_SPEC_EXISTS`)."

    Design: Corner/validations/active_spec_exists_on_second_issue_without_supersede
    """
    world = create_world(api, system_overrides={"system_code": "SW-ASE-1"})
    project_id = world["project"]["id"]
    second_system = create_coating_system(
        api,
        system_code="SW-ASE-2",
        surface_prep_standard="SSPC_SP6_COMMERCIAL",
        min_surface_profile_mils=1.0,
        max_surface_profile_mils=3.0,
        coat_count=2,
        total_dft_min_mils=6.0,
        total_dft_max_mils=10.0,
        base_voc_gpl=300,
        adhesion_min_psi=400,
    )
    spec2 = create_specification(api, project_id, second_system["id"])
    project_now = read_project(api, project_id)

    response = api.issue_specification(
        project_id, spec2["id"],
        issue_payload(project_now["version"]),
        PROJECT_ENGINEER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_ACTIVE_SPEC_EXISTS, expected_status=409)
    assert read_specification(api, spec2["id"])["status"] == "DRAFT"

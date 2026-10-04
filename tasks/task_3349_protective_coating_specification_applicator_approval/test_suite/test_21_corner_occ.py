"""Corner breadth index (cross-cutting layers): the optimistic-concurrency
guard on specification issuance — stale rejection and fresh success.
"""
from test_helpers import (
    PROJECT_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    create_coating_system,
    create_project,
    create_regulation,
    create_specification,
    issue_payload,
    issue_specification,
    read_project,
    read_specification,
    set_clock,
    validate_error,
    validate_success,
)


def test_spec_issue_stale_project_version_rejected_occ(api: ApiClient):
    """PRD §2.7: "Issuing a specification (the specification issuance
    endpoint, `POST /coating/projects/{projectId}/specifications/{id}/issue`)
    requires the request body to carry `expected_project_version`, a
    non-optional field holding the `version` of the parent `Project` as last
    observed by the client. If the project's current `version` does not match
    — for example because another writer has just issued a superseding
    specification, an act which itself bumps the project's version — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/spec_issue_stale_project_version_rejected_occ
    """
    set_clock(api)
    create_regulation(api)
    system = create_coating_system(api, system_code="SW-OCC-1")
    project = create_project(api, project_name="OCC Project")
    stale_version = project["version"]

    spec1 = create_specification(api, project["id"], system["id"])
    issue_specification(api, project["id"], spec1["id"], expected_project_version=stale_version)
    spec2 = create_specification(
        api, project["id"], system["id"], supersedes_specification_id=spec1["id"]
    )

    # The first issuance bumped the project version, so the stale read no
    # longer matches — and every other issuance precondition passes, isolating
    # the OCC guard.
    response = api.issue_specification(
        project["id"], spec2["id"], issue_payload(stale_version), PROJECT_ENGINEER_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert read_specification(api, spec2["id"])["status"] == "DRAFT"


def test_spec_issue_correct_project_version_succeeds(api: ApiClient):
    """PRD §2.7: "the request body to carry `expected_project_version`, a
    non-optional field holding the `version` of the parent `Project` as last
    observed by the client."
    PRD §3.4: "Issuance increments the project's `version` by 1 — the mutation
    the OCC guard exists to serialize — and moves a `PLANNING` project to
    `SPECIFIED`."
    PRD §3.4: "`pinned_spec_revision` takes the coating system's
    `spec_revision` at this instant and is never migrated by later revisions".

    Design: Corner/cross_cutting_layers/spec_issue_correct_project_version_succeeds
    """
    set_clock(api)
    create_regulation(api)
    system = create_coating_system(api, system_code="SW-OCC-2")
    project = create_project(api, project_name="OCC Project 2")
    observed_version = project["version"]
    spec = create_specification(api, project["id"], system["id"])

    issued = validate_success(
        api.issue_specification(
            project["id"], spec["id"], issue_payload(observed_version), PROJECT_ENGINEER_HEADERS
        )
    )

    assert issued["status"] == "ISSUED"
    assert issued["pinned_spec_revision"] == 1
    project_after = read_project(api, project["id"])
    assert project_after["version"] == observed_version + 1, (
        "a successful issue advances the parent version by exactly 1"
    )
    assert project_after["status"] == "SPECIFIED"

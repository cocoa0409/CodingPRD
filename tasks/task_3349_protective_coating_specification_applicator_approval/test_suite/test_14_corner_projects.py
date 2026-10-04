"""Corner breadth index (entities): project creation defaults, asset-type
enum closure, and not-found lookup.
"""
from test_helpers import (
    PROJECT_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_project,
    project_payload,
    validate_error,
    validate_success,
)


def test_project_creation_starts_planning_zero_exposure(api: ApiClient):
    """PRD §3.4: "The project begins in `PLANNING` with
    `committed_warranty_exposure_cents` at 0; that committed figure is
    recomputed as the sum of `exposure_cents` across all of the project's
    warranties in `ACTIVE` or `CLAIMED` status."

    Design: Corner/entities/project_creation_starts_planning_zero_exposure
    """
    project = validate_success(
        api.create_project(
            project_payload(
                project_name="Harbor Bridge Recoat",
                owner_name="Port Authority",
                jurisdiction_code="US-CA-SCAQMD",
                asset_type="BRIDGE",
                warranty_budget_cents=50_000_000,
            ),
            PROJECT_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )

    assert_project(project)
    assert project["status"] == "PLANNING"
    assert project["committed_warranty_exposure_cents"] == 0
    assert project["asset_type"] == "BRIDGE"
    assert project["project_name"] == "Harbor Bridge Recoat"
    assert project["owner_name"] == "Port Authority"
    assert project["jurisdiction_code"] == "US-CA-SCAQMD"
    assert project["warranty_budget_cents"] == 50_000_000


def test_project_creation_invalid_asset_type_rejected(api: ApiClient):
    """PRD §3.4: "the `asset_type` — one of `BRIDGE`, `TANK_EXTERIOR`,
    `TANK_INTERIOR`, `PIPELINE`, or `STRUCTURAL_STEEL`".
    PRD §2.8: "a request body that is missing a required field, supplies a
    value of the wrong type, names an enumeration value outside the defined
    set, or violates an array cardinality rule — fewer than three spot
    film-thickness readings, zero adhesion readings, or a non-positive tested
    area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/project_creation_invalid_asset_type_rejected
    """
    response = api.create_project(
        project_payload(project_name="Bad Asset", asset_type="DAM", warranty_budget_cents=1_000_000),
        PROJECT_ENGINEER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_project_not_found_on_get(api: ApiClient):
    """PRD §2.8: "the server validates the identifiers' existence
    sequentially, left to right, and rejects the request immediately with the
    not-found error corresponding to the first identifier that does not
    resolve to an existing resource". The not-found catalog includes
    `ERR_PROJECT_NOT_FOUND` (HTTP 404).

    Design: Corner/entities/project_not_found_on_get
    """
    response = api.get_project(
        "00000000-0000-4000-8000-0000000000cc", PROJECT_ENGINEER_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND, expected_status=404)

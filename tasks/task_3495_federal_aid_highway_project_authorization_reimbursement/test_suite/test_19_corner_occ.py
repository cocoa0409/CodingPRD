"""Corner queue — validations (optimistic concurrency): the stale-version
rejection and the fresh-version success path on the one OCC-guarded write
(PRD §2.8, §3.3, §2.5)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_version_bumped,
    create_funding_program,
    create_project,
    create_stip,
    determine_project_eligible,
    get_success_data,
    set_clock,
    setup_stip_pipeline,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestProjectOcc:
    def test_project_patch_with_stale_version_returns_stale_version(self, api):
        """PRD §2.8: "If that value does not equal the Project's current
        `version` — for instance because another writer patched the estimate,
        or an award or change-order cascade advanced the version since the
        client last read it — the update is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §2.5: "The `version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation, again including cascaded
        ones."

        The client observed version 1 at creation; eligibility determination
        advanced the project to version 2, so the stale expected value is
        rejected and nothing changes.

        Design: Corner/validations/project_patch_with_stale_version_returns_stale_version
        """
        pipeline = setup_stip_pipeline(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            state_code="AZ",
            project_specs=[{"description": "P1", "total_estimated_cost_cents": 1_000}],
        )
        project = pipeline["projects"][0]
        assert project["version"] == 1
        determine_project_eligible(project["id"])  # mutation: version 1 -> 2

        resp = api.patch_project(
            project["id"],
            {"expected_project_version": 1, "description": "stale edit"},
            H["state_dot_planner"],
        )
        error = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412, f"expected 412, got {resp.status_code} ({error})"

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["description"] == "P1"
        assert reread["version"] == 2

    def test_project_patch_with_fresh_version_succeeds_and_bumps_version(self, api):
        """PRD §2.8: "Exactly one endpoint participates in optimistic
        concurrency control: the project update operation requires a
        non-optional `expected_project_version` field carrying the client's
        last observed `version` of the Project."
        PRD §3.3: "A successful patch increments `version` by 1, and a change
        to `total_estimated_cost_cents` recomputes
        `provisional_federal_estimate_cents` through the statutory-base
        variant."

        The fresh PATCH bumps version 1 -> 2 and recomputes the provisional
        estimate from the new cost: round(2,000 x 0.80) = 1,600.

        Design: Corner/validations/project_patch_with_fresh_version_succeeds_and_bumps_version
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        project = create_project(
            stip["id"], program["id"], route_name="R1", description="P1",
            total_estimated_cost_cents=1_000,
        )
        assert project["version"] == 1

        resp = api.patch_project(
            project["id"],
            {
                "expected_project_version": 1,
                "total_estimated_cost_cents": 2_000,
                "description": "P1 revised",
            },
            H["state_dot_planner"],
        )
        patched = validate_success(resp)
        assert patched["version"] == 2
        assert_version_bumped(project, patched)
        assert patched["total_estimated_cost_cents"] == 2_000
        assert patched["provisional_federal_estimate_cents"] == 1_600, (
            "statutory-base variant on the new cost: 0.80 x 2,000 = 1,600, got "
            f"{patched['provisional_federal_estimate_cents']}"
        )
        assert patched["description"] == "P1 revised"

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["version"] == 2
        assert reread["description"] == "P1 revised"
        assert reread["provisional_federal_estimate_cents"] == 1_600

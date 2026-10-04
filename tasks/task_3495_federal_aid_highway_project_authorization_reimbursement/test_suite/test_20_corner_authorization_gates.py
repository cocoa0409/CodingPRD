"""Corner queue — validations (authorization gates): the environmental and
right-of-way legs independently, the missing current-FFY cell, and the
one-active-authorization structural rule (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    authorize_project,
    clear_project,
    create_clearance_payload,
    determine_project_eligible,
    get_success_data,
    set_clock,
    setup_stip_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


def _eligible_project(api, apportionments=None):
    """Approved STIP (AZ) whose single 100,000-cent project is ELIGIBLE."""
    pipeline = setup_stip_pipeline(
        program_code="NHPP",
        eligible_activity_codes=["ROAD_RESURFACING"],
        state_code="AZ",
        apportionments=apportionments,
        project_specs=[{"total_estimated_cost_cents": 100_000}],
    )
    project = pipeline["projects"][0]
    determine_project_eligible(project["id"])
    return project


def _authorize_call(api, project_id, cents=80_000, agreement="FA-GATE"):
    set_clock("2026-10-15T00:00:00Z")  # FFY 2027 cell
    return api.create_authorization(
        {
            "project_id": project_id,
            "agreement_number": agreement,
            "initial_obligated_cents": cents,
        },
        H["fhwa_division_admin"],
    )


def _assert_no_authorization(api, project_id):
    rows, meta = validate_paginated(
        api.list_authorizations(H["fhwa_reviewer"], params={"project_id": project_id})
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a rejected authorization must persist nothing"
    )


class TestAuthorizationGates:
    def test_authorize_without_environmental_clearance_returns_error(self, api):
        """PRD §3.5: "the Project must hold a `CLEARED` environmental clearance
        (`ERR_ENVIRONMENTAL_NOT_CLEARED`, 409), and a `CLEARED` right-of-way
        certification (`ERR_ROW_NOT_CERTIFIED`, 409)."

        With only the right-of-way certification CLEARED, the environmental
        leg fires on its own.

        Design: Corner/validations/authorize_without_environmental_clearance_returns_error
        """
        project = _eligible_project(api)
        created = api.create_clearance(
            create_clearance_payload(project["id"], "RIGHT_OF_WAY", None),
            H["state_dot_engineer"],
        )
        row = validate_success(created, expected_status=201)
        decided = api.decide_clearance(
            row["id"],
            {"decision": "CLEARED", "row_cert_level": "LEVEL_1_FULL"},
            H["fhwa_reviewer"],
        )
        assert validate_success(decided)["status"] == "CLEARED"

        resp = _authorize_call(api, project["id"], agreement="FA-NE")
        error = validate_error(resp, ApiErrorId.ERR_ENVIRONMENTAL_NOT_CLEARED)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"
        _assert_no_authorization(api, project["id"])

    def test_authorize_without_row_certification_returns_error(self, api):
        """PRD §3.5: "the Project must hold a `CLEARED` environmental clearance
        (`ERR_ENVIRONMENTAL_NOT_CLEARED`, 409), and a `CLEARED` right-of-way
        certification (`ERR_ROW_NOT_CERTIFIED`, 409)."

        With only the environmental clearance CLEARED, the right-of-way leg
        fires on its own.

        Design: Corner/validations/authorize_without_row_certification_returns_error
        """
        project = _eligible_project(api)
        created = api.create_clearance(
            create_clearance_payload(project["id"], "ENVIRONMENTAL", "CE"),
            H["state_dot_engineer"],
        )
        env = validate_success(created, expected_status=201)
        decided = api.decide_clearance(env["id"], {"decision": "CLEARED"}, H["fhwa_reviewer"])
        assert validate_success(decided)["status"] == "CLEARED"

        resp = _authorize_call(api, project["id"], agreement="FA-NR")
        error = validate_error(resp, ApiErrorId.ERR_ROW_NOT_CERTIFIED)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"
        _assert_no_authorization(api, project["id"])

    def test_authorize_without_apportionment_row_returns_no_cell_error(self, api):
        """PRD §3.5: "The fiscal leg then resolves the apportionment cell: the
        server selects the unique Apportionment matching the Project's funding
        program, the owning STIP's `state_code`, and the FFY of the current
        logical clock, and records it as the Authorization's
        `apportionment_id`. If no such row exists, the authorization is
        rejected with `ERR_NO_APPORTIONMENT_FOR_FFY` (422)."

        An FFY-2028 row exists (so the STIP approval's forward-looking check
        passes), but the authorization clock reads FFY 2027, whose cell is
        missing.

        Design: Corner/validations/authorize_without_apportionment_row_returns_no_cell_error
        """
        project = _eligible_project(api, apportionments={2028: 100_000})
        clear_project(project["id"])

        resp = _authorize_call(api, project["id"], agreement="FA-NA")
        error = validate_error(resp, ApiErrorId.ERR_NO_APPORTIONMENT_FOR_FFY)
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({error})"

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["status"] == "ELIGIBLE"
        _assert_no_authorization(api, project["id"])

    def test_second_authorization_blocked_by_state_gate(self, api):
        """PRD §3.5: "Because authorization requires `ELIGIBLE` and the first
        successful authorization moves the Project to `AUTHORIZED`, a second
        authorization against the same Project fails with
        `ERR_PROJECT_NOT_ELIGIBLE` — at most one active Authorization per
        Project, enforced structurally."

        Design: Corner/validations/second_authorization_blocked_by_state_gate
        """
        project = _eligible_project(api)
        clear_project(project["id"])
        authorize_project(project["id"], initial_obligated_cents=80_000,
                          agreement_number="FA-1")

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["status"] == "AUTHORIZED"

        resp = _authorize_call(api, project["id"], cents=10_000, agreement="FA-2")
        error = validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ELIGIBLE)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, meta = validate_paginated(
            api.list_authorizations(H["fhwa_reviewer"], params={"project_id": project["id"]})
        )
        assert len(rows) == 1 and meta["total_count"] == 1

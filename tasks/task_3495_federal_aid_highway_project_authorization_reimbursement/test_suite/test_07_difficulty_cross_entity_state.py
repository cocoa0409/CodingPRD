"""Difficulty queue — cross_entity_state_dependency: an authorization gated
purely by its owning STIP's status, and a voucher gated purely by its
authorization's status (PRD §3.2/§3.5)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    clear_project,
    create_apportionment,
    create_draft_voucher,
    create_funding_program,
    create_line_item,
    create_project,
    create_stip,
    decide_stip,
    determine_project_eligible,
    get_success_data,
    set_clock,
    setup_fully_drawn_authorization,
    submit_stip,
    validate_error,
    validate_paginated,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestCrossEntityStateDependency:
    def test_authorization_blocked_when_stip_reopened(self, api):
        """PRD §3.2: "While the STIP sits in `PUBLIC_INVOLVEMENT`, eligibility
        determination and authorization on its projects fail with
        `ERR_STIP_NOT_APPROVED` until the loop closes again."
        PRD §2.7: "7. Cross-entity program state: the owning STIP must be
        `APPROVED` for eligibility determination and authorization, else
        `ERR_STIP_NOT_APPROVED` (409)."

        The project under authorization is ELIGIBLE with both clearances
        CLEARED and a funded apportionment cell — the rejection is caused
        purely by the cross-entity gate after the planner reopens the STIP.

        Design: Difficulty/cross_entity_state_dependency/authorization_blocked_when_stip_reopened
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        create_apportionment(
            program["id"], state_code="CA", federal_fiscal_year=2027,
            apportioned_cents=5_000_000,
        )
        stip = create_stip(state_code="CA", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        project = create_project(
            stip["id"], program["id"], route_name="I-5", description="P1",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=1_000_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")
        determine_project_eligible(project["id"])
        clear_project(project["id"])

        reopened = get_success_data(
            api.open_stip_amendment(stip["id"], H["state_dot_planner"])
        )
        assert reopened["status"] == "PUBLIC_INVOLVEMENT"
        set_clock("2026-10-15T00:00:00Z")

        resp = api.create_authorization(
            {
                "project_id": project["id"],
                "agreement_number": "FA-G-1",
                "initial_obligated_cents": 100_000,
            },
            H["fhwa_division_admin"],
        )
        error = validate_error(resp, ApiErrorId.ERR_STIP_NOT_APPROVED)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["status"] == "ELIGIBLE"
        authorizations, meta = validate_paginated(
            api.list_authorizations(H["fhwa_reviewer"], params={"project_id": project["id"]})
        )
        assert authorizations == [] and meta["total_count"] == 0, (
            "no Authorization row may be created under a reopened STIP"
        )

    def test_voucher_blocked_when_authorization_fully_drawn(self, api):
        """PRD §3.5: "When a voucher approval raises `reimbursed_cents` to
        exactly `obligated_cents`, the system moves the Authorization from
        `OBLIGATED` to `FULLY_DRAWN`, and from that point voucher creation and
        submission against it fail with `ERR_AUTHORIZATION_NOT_OBLIGATED`."

        With share 0.90 the approved lines [105, 105] reimburse exactly 190 ==
        the 190-cent obligation, auto-flipping the authorization; the next
        voucher creation is rejected even though the project is mid
        construction.

        Design: Difficulty/cross_entity_state_dependency/voucher_blocked_when_authorization_fully_drawn
        """
        ctx = setup_fully_drawn_authorization()
        authorization = ctx["authorization"]
        assert authorization["status"] == "FULLY_DRAWN"
        assert authorization["reimbursed_cents"] == 190
        assert authorization["obligated_cents"] == 190

        resp = api.create_voucher(
            {
                "authorization_id": authorization["id"],
                "period_start_date": "2027-02-01T00:00:00Z",
                "period_end_date": "2027-03-01T00:00:00Z",
                "line_items": [create_line_item("c", 100)],
                "documentation_complete": True,
                "is_final": False,
            },
            H["state_dot_engineer"],
        )
        error = validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_OBLIGATED)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

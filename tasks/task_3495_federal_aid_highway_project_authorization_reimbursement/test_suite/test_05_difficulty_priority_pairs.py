"""Difficulty queue — priority_pair_validation_conflict: when one request
violates two checks, the earlier check in the PRD §2.7 succession produces
the response and masks the later one."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    create_apportionment,
    create_draft_voucher,
    create_funding_program,
    create_line_item,
    create_project,
    create_stip,
    decide_stip,
    get_success_data,
    set_clock,
    setup_project_under_construction,
    submit_stip,
    submit_voucher,
    validate_error,
    validate_paginated,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestPriorityPairValidationConflict:
    def test_authorize_state_error_beats_fiscal_error(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed succession of
        checks. When several checks would fail on the same request, the check
        earliest in this succession produces the response; later failures are
        masked, not reported alongside."
        PRD §2.7: "8. Project eligibility at authorization, else
        `ERR_PROJECT_NOT_ELIGIBLE` (409)."
        PRD §2.7: "30. Cell availability must cover an obligation or
        change-order draw, else `ERR_APPORTIONMENT_EXCEEDED` (422)."

        One authorization request that violates both — the project is still
        NOMINATED (check 8) and 200,000 exceeds the 100,000 available
        (check 30) — reports the state error because 8 sorts before 30.

        Design: Difficulty/priority_pair_validation_conflict/authorize_state_error_beats_fiscal_error
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        create_apportionment(
            program["id"], state_code="CA", federal_fiscal_year=2027,
            apportioned_cents=100_000,
        )
        stip = create_stip(state_code="CA", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        project = create_project(
            stip["id"], program["id"], route_name="I-5", description="P",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=100_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")
        # Eligibility is never determined: the project stays NOMINATED.
        set_clock("2026-10-15T00:00:00Z")

        resp = api.create_authorization(
            {
                "project_id": project["id"],
                "agreement_number": "FA-PRIO",
                "initial_obligated_cents": 200_000,
            },
            H["fhwa_division_admin"],
        )
        error = validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ELIGIBLE)
        assert resp.status_code == 409, (
            "priority 8 (state, 409) must mask priority 30 (fiscal, 422) even "
            f"though 200,000 > 100,000 available; got HTTP {resp.status_code} "
            f"({error})"
        )

    def test_voucher_documentation_error_beats_overlap_error(self, api):
        """PRD §2.7: "When several checks would fail on the same request, the
        check earliest in this succession produces the response; later failures
        are masked, not reported alongside."
        PRD §2.7: "13. Voucher documentation certification, else
        `ERR_DOCUMENTATION_INCOMPLETE` (422)."
        PRD §2.7: "19. Billing period overlap, else `ERR_BILLING_PERIOD_OVERLAP`
        (409)."
        PRD §3.7: "`documentation_complete` must be true, the state's
        certification that supporting documentation is complete, else
        `ERR_DOCUMENTATION_INCOMPLETE` (422)".

        Voucher B is submitted with documentation_complete false AND a period
        [2027-01-15, 2027-02-15) intersecting sibling voucher A's
        [2027-01-01, 2027-02-01): the response is the documentation error
        because check 13 sorts before check 19.

        Design: Difficulty/priority_pair_validation_conflict/voucher_documentation_error_beats_overlap_error
        """
        ctx = setup_project_under_construction(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            activity_code="ROAD_RESURFACING",
            project_cost_cents=1_500_000,
            apportioned_cents=2_000_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-VP-001",
        )
        auth_id = ctx["authorization"]["id"]

        voucher_a = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-02-01T00:00:00Z",
            line_items=[create_line_item("A", 10_000)],
        )
        submit_voucher(voucher_a["id"])
        voucher_b = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-15T00:00:00Z",
            period_end_date="2027-02-15T00:00:00Z",
            line_items=[create_line_item("B", 20_000)],
            documentation_complete=False,
        )

        resp = api.submit_voucher(voucher_b["id"], H["state_dot_engineer"])
        error = validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)
        assert resp.status_code == 422, (
            "priority 13 (documentation, 422) must mask priority 19 (overlap, "
            f"409) even though the period also intersects voucher A; got HTTP "
            f"{resp.status_code} ({error})"
        )

        vouchers, meta = validate_paginated(
            api.list_authorization_vouchers(auth_id, H["fhwa_reviewer"])
        )
        by_id = {v["id"]: v for v in vouchers}
        assert by_id[voucher_b["id"]]["status"] == "DRAFT"
        assert by_id[voucher_a["id"]]["status"] == "UNDER_REVIEW"
        assert meta["total_count"] == 2

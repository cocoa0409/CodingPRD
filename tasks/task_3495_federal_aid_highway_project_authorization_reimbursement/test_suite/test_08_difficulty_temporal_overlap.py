"""Difficulty queue — resource_temporal_overlap: half-open voucher billing
periods on one authorization (adjacency allowed) versus closed-interval STIP
coverage windows per state (a shared boundary year is an overlap)
(PRD §3.7, §3.2)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_state_program,
    create_draft_voucher,
    create_line_item,
    create_stip,
    set_clock,
    setup_project_under_construction,
    submit_voucher,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestResourceTemporalOverlap:
    def test_voucher_half_open_periods_adjacent_ok_overlap_rejected(self, api):
        """PRD §3.7: "the half-open period must not intersect the period of any
        non-`REJECTED` sibling voucher on the same authorization, else
        `ERR_BILLING_PERIOD_OVERLAP` (409) — adjacency is allowed, so one
        voucher's period ending exactly where the next begins is not an
        overlap."
        PRD §3.7: "The period is half-open: it includes its start instant and
        excludes its end instant, so `period_end_date` must be strictly after
        `period_start_date`."

        After voucher A takes [2027-01-01, 2027-02-01), voucher B starting at
        exactly A's exclusive end is accepted, while voucher C at
        [2027-01-15, 2027-02-15) intersects both and is rejected.

        Design: Difficulty/resource_temporal_overlap/voucher_half_open_periods_adjacent_ok_overlap_rejected
        """
        ctx = setup_project_under_construction(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            activity_code="ROAD_RESURFACING",
            project_cost_cents=1_500_000,
            apportioned_cents=2_000_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-O-1",
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
            period_start_date="2027-02-01T00:00:00Z",
            period_end_date="2027-03-01T00:00:00Z",
            line_items=[create_line_item("B", 10_000)],
        )

        submitted_b = api.submit_voucher(voucher_b["id"], H["state_dot_engineer"])
        data_b = validate_success(submitted_b)
        assert data_b["status"] == "UNDER_REVIEW", (
            "adjacency is not overlap: a start equal to A's exclusive end must "
            f"be accepted, got {data_b['status']}"
        )

        # C is drafted only after B is accepted: as a non-REJECTED sibling its
        # period would itself block B's submission, which is not what this
        # test isolates.
        voucher_c = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-15T00:00:00Z",
            period_end_date="2027-02-15T00:00:00Z",
            line_items=[create_line_item("C", 10_000)],
        )
        resp_c = api.submit_voucher(voucher_c["id"], H["state_dot_engineer"])
        error = validate_error(resp_c, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP)
        assert resp_c.status_code == 409, (
            "[2027-01-15, 2027-02-15) intersects both A and B; expected 409, "
            f"got {resp_c.status_code} ({error})"
        )

    def test_stip_closed_interval_windows_share_boundary_year_rejected(self, api):
        """PRD §3.2: "Coverage windows are closed intervals that include both
        their first and last fiscal years, and two STIPs for the same
        `state_code` may not intersect: a new STIP whose window shares even a
        single boundary fiscal year with an existing STIP of the same state is
        rejected with `ERR_STIP_PERIOD_OVERLAP` (409), while strictly disjoint
        windows are allowed."
        PRD §3.2: "The STIP spans four federal fiscal years:
        `end_federal_fiscal_year` is computed as the start year plus three."

        The existing NV STIP covers 2027-2030 inclusive: a second STIP
        starting 2030 shares the boundary year and is rejected, while a 2031
        start is strictly disjoint and accepted — the opposite treatment from
        half-open voucher periods.

        Design: Difficulty/resource_temporal_overlap/stip_closed_interval_windows_share_boundary_year_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        stip1 = create_stip(
            state_code="NV", land_pct=0.80, start_ffy=2027,
            description="NV STIP 2027-2030",
        )
        assert_state_program(stip1)
        assert stip1["end_federal_fiscal_year"] == 2030

        overlap = api.create_stip(
            {
                "state_code": "NV",
                "state_federal_land_pct": 0.80,
                "start_federal_fiscal_year": 2030,
                "description": "NV overlapping STIP",
            },
            H["state_dot_planner"],
        )
        error = validate_error(overlap, ApiErrorId.ERR_STIP_PERIOD_OVERLAP)
        assert overlap.status_code == 409, (
            "closed intervals sharing boundary year 2030 must be rejected; got "
            f"{overlap.status_code} ({error})"
        )

        disjoint = api.create_stip(
            {
                "state_code": "NV",
                "state_federal_land_pct": 0.80,
                "start_federal_fiscal_year": 2031,
                "description": "NV next-decade STIP",
            },
            H["state_dot_planner"],
        )
        stip3 = validate_success(disjoint, expected_status=201)
        assert_state_program(stip3)
        assert stip3["id"] != stip1["id"]
        assert stip3["end_federal_fiscal_year"] == 2034

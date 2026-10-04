"""Difficulty queue — boundary_precision_check: the inclusive boundaries of
the apportionment availability comparison (money, cents) and the DBE goal
comparison (percentage) (PRD §3.5, §3.6)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    advertise_project,
    api_client,
    award_project,
    clear_project,
    create_apportionment,
    create_bid_entry,
    create_funding_program,
    create_project,
    create_stip,
    decide_stip,
    determine_project_eligible,
    get_success_data,
    open_project_bids,
    set_clock,
    setup_stip_pipeline,
    submit_stip,
    validate_error,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestBoundaryPrecisionCheck:
    def test_authorize_exactly_available_succeeds_one_cent_more_fails(self, api):
        """PRD §3.5: "The cell's `available_cents` — `apportioned_cents` minus
        `obligated_cents` — must cover `initial_obligated_cents`, with equality
        passing; a shortfall is rejected with `ERR_APPORTIONMENT_EXCEEDED`
        (422)."

        The comparison is inclusive: 2,000,000 against 2,000,000 available is
        accepted (201), draining the cell to zero; the follow-on 1-cent
        obligation is rejected.

        Design: Difficulty/boundary_precision_check/authorize_exactly_available_succeeds_one_cent_more_fails
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        apportionment = create_apportionment(
            program["id"], state_code="TX", federal_fiscal_year=2027,
            apportioned_cents=2_000_000,
        )
        stip = create_stip(state_code="TX", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        project_p1 = create_project(
            stip["id"], program["id"], route_name="I-35", description="P1",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=2_000_000,
        )
        project_p2 = create_project(
            stip["id"], program["id"], route_name="FM-1", description="P2",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=1_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")
        for project in (project_p1, project_p2):
            determine_project_eligible(project["id"])
            clear_project(project["id"])

        # The clock reads 2026-10-02 (FFY 2027), so the draw keys to the
        # (NHPP, TX, 2027) cell holding exactly 2,000,000.
        auth = api.create_authorization(
            {
                "project_id": project_p1["id"],
                "agreement_number": "FA-B-1",
                "initial_obligated_cents": 2_000_000,
            },
            H["fhwa_division_admin"],
        )
        assert auth.status_code == 201, "exactly-available obligation must be accepted"
        data = get_success_data(auth)
        assert data["status"] == "OBLIGATED"

        cell = get_success_data(
            api.get_apportionment(apportionment["id"], H["fhwa_reviewer"])
        )
        assert cell["available_cents"] == 0
        assert cell["obligated_cents"] == 2_000_000

        resp = api.create_authorization(
            {
                "project_id": project_p2["id"],
                "agreement_number": "FA-B-2",
                "initial_obligated_cents": 1,
            },
            H["fhwa_division_admin"],
        )
        validate_error(resp, ApiErrorId.ERR_APPORTIONMENT_EXCEEDED)

    def test_dbe_commitment_exactly_at_goal_passes_below_fails(self, api):
        """PRD §3.6: "Independently, the declared `dbe_commitment_pct` must be
        at least the Project's `dbe_goal_pct` — equality passes — unless
        `good_faith_effort_documented` is true, which excuses any shortfall;
        otherwise the award is rejected with `ERR_DBE_GOAL_NOT_MET` (422)."

        The comparison is >= : a commitment of exactly 0.10 against a 0.10
        goal passes with no good-faith documentation, while 0.0999 on an
        identically shaped award is rejected.

        Design: Difficulty/boundary_precision_check/dbe_commitment_exactly_at_goal_passes_below_fails
        """
        pipeline = setup_stip_pipeline(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            state_code="WA",
            apportionments={2027: 10_000_000},
            project_specs=[
                {
                    "route_name": "I-90A",
                    "description": "A",
                    "activity_code": "ROAD_RESURFACING",
                    "is_interstate_system": False,
                    "dbe_goal_pct": 0.10,
                    "total_estimated_cost_cents": 1_000_000,
                },
                {
                    "route_name": "I-90B",
                    "description": "B",
                    "activity_code": "ROAD_RESURFACING",
                    "is_interstate_system": False,
                    "dbe_goal_pct": 0.10,
                    "total_estimated_cost_cents": 1_000_000,
                },
            ],
        )
        project_a, project_b = pipeline["projects"]
        bids = {}
        # Each project's 21-day advertisement window must elapse before its own
        # bid opening (PRD §3.6), and the logical clock only moves forward:
        # A opens bids at the standard date, B 22 days after A's opening.
        open_dates = {"A": "2026-11-06T00:00:00Z", "B": "2026-11-28T00:00:00Z"}
        for label, project in (("A", project_a), ("B", project_b)):
            determine_project_eligible(project["id"])
            clear_project(project["id"])
            auth = api.create_authorization(
                {
                    "project_id": project["id"],
                    "agreement_number": f"FA-D-{label}",
                    "initial_obligated_cents": 800_000,
                },
                H["fhwa_division_admin"],
            )
            get_success_data(auth)
            advertise_project(project["id"])
            bids[label] = open_project_bids(
                project["id"],
                [create_bid_entry(f"{label} Low", 900_000, True)],
                bids_clock=open_dates[label],
            )

        awarded = award_project(project_a["id"], bids["A"][0]["id"], 0.10)
        assert awarded["status"] == "UNDER_CONSTRUCTION", (
            "commitment exactly equal to the 0.10 goal must pass, got "
            f"{awarded['status']}"
        )

        resp = api.award_project(
            project_b["id"],
            {"bid_id": bids["B"][0]["id"], "dbe_commitment_pct": 0.0999},
            H["fhwa_reviewer"],
        )
        validate_error(resp, ApiErrorId.ERR_DBE_GOAL_NOT_MET)
        reread_b = get_success_data(api.get_project(project_b["id"], H["fhwa_reviewer"]))
        assert reread_b["status"] == "BIDS_OPENED"

"""Difficulty queue — dual_variant_calc: one algorithm, two lifecycle-pinned
variants that diverge on identical data (PRD §3.3 and §3.2/§3.5)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    assert_project,
    authorize_project,
    clear_project,
    create_apportionment,
    create_funding_program,
    create_project,
    create_stip,
    decide_stip,
    determine_project_eligible,
    get_success_data,
    set_clock,
    submit_stip,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestDualVariantCalc:
    def test_provisional_vs_determined_share_on_interstate_project(self, api):
        """PRD §3.3: "`provisional_federal_share_pct` is exactly the program's
        base share — 0.80 for `NHPP`, `STBG`, `CMAQ`, and `TAP`; 0.90 for `HSIP`
        — with no interstate bump, no safety override, and no land adjustment;
        `provisional_federal_estimate_cents` is the product of
        `total_estimated_cost_cents` and that share, rounded half-up to whole
        cents."
        PRD §3.3: "If `is_interstate_system` is true, add a bump of 0.10,
        capping the result at 0.90 — so every Interstate System project lands
        at exactly 0.90, including `HSIP` projects whose 0.90 base cannot rise
        past the cap."

        The NHPP interstate project (land 0.02, below the 0.05 sliding-scale
        gate) therefore provisions at the flat 0.80 yet determines at 0.90:
        identical inputs, different variants selected by lifecycle context.

        Design: Difficulty/dual_variant_calc/provisional_vs_determined_federal_share_on_interstate_project
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING", "BRIDGE_REPLACEMENT"],
        )
        # Apportionment capacity is required so the fiscal-constraint check at
        # STIP approval passes with the project's 8,000,000-cent estimate.
        create_apportionment(
            program["id"], state_code="CA", federal_fiscal_year=2027,
            apportioned_cents=10_000_000,
        )
        stip = create_stip(state_code="CA", land_pct=0.02, start_ffy=2027)
        add_stip_comment(stip["id"])
        created = create_project(
            stip["id"],
            program["id"],
            route_name="I-5",
            description="Resurface I-5",
            activity_code="ROAD_RESURFACING",
            is_interstate_system=True,
            dbe_goal_pct=0.10,
            total_estimated_cost_cents=10_000_000,
        )
        assert_project(created)
        assert created["provisional_federal_share_pct"] == 0.80, (
            "statutory_base variant must be the flat program base 0.80, got "
            f"{created['provisional_federal_share_pct']}"
        )
        assert created["provisional_federal_estimate_cents"] == 8_000_000
        assert created["determined_federal_share_pct"] is None

        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")

        determined = determine_project_eligible(created["id"])
        assert determined["determined_federal_share_pct"] == 0.90, (
            "adjusted_full variant must be min(0.90, 0.80 + 0.10) == 0.90, got "
            f"{determined['determined_federal_share_pct']}"
        )

        reread = get_success_data(api.get_project(created["id"], H["fhwa_reviewer"]))
        assert reread["provisional_federal_share_pct"] == 0.80
        assert reread["provisional_federal_estimate_cents"] == 8_000_000
        assert reread["determined_federal_share_pct"] == 0.90
        assert reread["provisional_federal_share_pct"] != reread["determined_federal_share_pct"], (
            "the two share variants must diverge for identical project data"
        )

    def test_chronological_vs_forward_looking_availability(self, api):
        """PRD §3.2: "Note the deliberate asymmetry with the authorization-time
        check of §3.5: the approval check is forward-looking across the full
        four-year span and all programmed projects, so it can fail on
        Apportionment rows that still show room for a single current-year
        obligation."
        PRD §3.2: "Programmed must not exceed capacity, with equality passing;
        if any single program fails, the whole approval is rejected with
        `ERR_FISCAL_CONSTRAINT_VIOLATED` (422)."
        PRD §3.5: "The cell's `available_cents` — `apportioned_cents` minus
        `obligated_cents` — must cover `initial_obligated_cents`, with equality
        passing; a shortfall is rejected with `ERR_APPORTIONMENT_EXCEEDED`
        (422)."

        On identical apportionment rows the chronological-committed variant
        still shows 50,000 cents free in the FFY-2027 cell after a 250,000
        authorization, while the forward-looking variant rejects the amended
        STIP: programmed 300,000 (project A) + 800,000 (project B) = 1,100,000
        exceeds capacity (300,000-250,000) + 300,000 + 200,000 + 200,000 =
        750,000.

        Design: Difficulty/dual_variant_calc/chronological_vs_forward_looking_availability
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="STBG", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        cells = {}
        for ffy, cents in ((2027, 300_000), (2028, 300_000), (2029, 200_000), (2030, 200_000)):
            cells[ffy] = create_apportionment(
                program["id"], state_code="CA", federal_fiscal_year=ffy,
                apportioned_cents=cents,
            )
        stip = create_stip(state_code="CA", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        project_a = create_project(
            stip["id"], program["id"], route_name="US-101", description="Project A",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=375_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")
        determine_project_eligible(project_a["id"])
        clear_project(project_a["id"])
        authorize_project(
            project_a["id"], initial_obligated_cents=250_000,
            agreement_number="FA-A-001", auth_clock="2026-10-15T00:00:00Z",
        )

        # Nominating project B into the APPROVED STIP reopens it for amendment
        # (fresh comment window at the current clock), so re-approval re-runs
        # the forward-looking check with B's estimate now programmed.
        project_b = create_project(
            stip["id"], program["id"], route_name="SR-1",
            description="Project B amendment", activity_code="ROAD_RESURFACING",
            is_interstate_system=False, dbe_goal_pct=0.10,
            total_estimated_cost_cents=1_000_000,
        )
        set_clock("2026-11-16T00:00:00Z")
        add_stip_comment(stip["id"], comment_text="Amendment comment.")
        submit_stip(stip["id"])

        resp = api.decide_stip(stip["id"], {"decision": "APPROVE"}, H["fhwa_division_admin"])
        validate_error(resp, ApiErrorId.ERR_FISCAL_CONSTRAINT_VIOLATED)

        cell_2027 = get_success_data(
            api.get_apportionment(cells[2027]["id"], H["fhwa_reviewer"])
        )
        assert cell_2027["available_cents"] == 50_000, (
            "chronological_committed variant still shows 300,000 - 250,000 = "
            f"50,000 free in the FFY-2027 cell, got {cell_2027['available_cents']}"
        )
        assert cell_2027["obligated_cents"] == 250_000

        reread_a = get_success_data(api.get_project(project_a["id"], H["fhwa_reviewer"]))
        reread_b = get_success_data(api.get_project(project_b["id"], H["fhwa_reviewer"]))
        assert reread_a["status"] == "AUTHORIZED"
        assert reread_b["status"] == "NOMINATED"

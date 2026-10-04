"""Corner queue — calculations (federal_share_determination): the interstate
cap binding HSIP, the strict-greater land gate at exactly 0.05, and the
provisional variant ignoring every adjustment (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    assert_project,
    create_apportionment,
    create_funding_program,
    create_project,
    create_stip,
    decide_stip,
    determine_project_eligible,
    set_clock,
    submit_stip,
    validate_success,
)

H = TEST_USERS


class TestFederalShareDetermination:
    def test_interstate_share_capped_at_ninety_for_hsip(self, api):
        """PRD §3.3: "If `is_interstate_system` is true, add a bump of 0.10,
        capping the result at 0.90 — so every Interstate System project lands
        at exactly 0.90, including `HSIP` projects whose 0.90 base cannot rise
        past the cap."

        HSIP base 0.90 + 0.10 bump would reach 1.00, but the 0.90 cap binds;
        the safety override does not apply because ROAD_RESURFACING is outside
        the safety activity set.

        Design: Corner/calculations/interstate_share_capped_at_ninety_for_hsip
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="HSIP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        # Capacity so the approval-time fiscal check passes (estimate 900,000).
        create_apportionment(
            program["id"], state_code="UT", federal_fiscal_year=2027,
            apportioned_cents=5_000_000,
        )
        stip = create_stip(state_code="UT", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        project = create_project(
            stip["id"], program["id"], route_name="I-15",
            description="Interstate HSIP", activity_code="ROAD_RESURFACING",
            is_interstate_system=True, dbe_goal_pct=0.10,
            total_estimated_cost_cents=1_000_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")

        determined = determine_project_eligible(project["id"])
        assert_project(determined)
        assert determined["determined_federal_share_pct"] == 0.90, (
            "min(0.90, 0.90 + 0.10) == 0.90, got "
            f"{determined['determined_federal_share_pct']}"
        )

    def test_land_adjustment_skipped_at_exactly_threshold(self, api):
        """PRD §3.3: "Otherwise, when the owning STIP's
        `state_federal_land_pct` is strictly greater than 0.05 (a state at
        exactly 0.05 receives no adjustment), the base slides toward the 0.95
        cap: it becomes the lesser of 0.95 and the base plus the product of
        (0.95 minus the base) and `state_federal_land_pct`."

        The gate is strictly-greater: land fraction exactly 0.05 does not
        trigger the sliding scale, so the plain NHPP project determines at the
        flat 0.80.

        Design: Corner/calculations/land_adjustment_skipped_at_exactly_threshold
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        # Capacity so the approval-time fiscal check passes (estimate 800,000).
        create_apportionment(
            program["id"], state_code="CO", federal_fiscal_year=2027,
            apportioned_cents=5_000_000,
        )
        stip = create_stip(state_code="CO", land_pct=0.05, start_ffy=2027)
        add_stip_comment(stip["id"])
        project = create_project(
            stip["id"], program["id"], route_name="US-6", description="P",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=1_000_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")

        determined = determine_project_eligible(project["id"])
        assert determined["determined_federal_share_pct"] == 0.80, (
            "0.05 is not > 0.05, so no sliding-scale adjustment applies; got "
            f"{determined['determined_federal_share_pct']}"
        )

    def test_provisional_share_ignores_all_adjustments(self, api):
        """PRD §3.3: "The **statutory-base variant** runs at creation and on
        every cost-changing patch: `provisional_federal_share_pct` is exactly
        the program's base share — 0.80 for `NHPP`, `STBG`, `CMAQ`, and `TAP`;
        0.90 for `HSIP` — with no interstate bump, no safety override, and no
        land adjustment; `provisional_federal_estimate_cents` is the product
        of `total_estimated_cost_cents` and that share, rounded half-up to
        whole cents."
        PRD §3.3: "The new Project starts in `NOMINATED` with
        `advertised_on_date`, `awarded_bid_id`, and
        `determined_federal_share_pct` all null."

        Even with the interstate flag, land 0.40, and a safety-set activity on
        HSIP, the provisional share at creation is the flat 0.90 — every
        adjustment lives only in the determined variant.

        Design: Corner/calculations/provisional_share_ignores_all_adjustments
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="HSIP", eligible_activity_codes=["SIGNAGE_LIGHTING"]
        )
        stip = create_stip(state_code="NV", land_pct=0.40, start_ffy=2035)
        resp = api.create_project(
            {
                "stip_id": stip["id"],
                "funding_program_id": program["id"],
                "route_name": "I-15",
                "description": "Signage",
                "activity_code": "SIGNAGE_LIGHTING",
                "is_interstate_system": True,
                "dbe_goal_pct": 0.10,
                "total_estimated_cost_cents": 1_000_000,
            },
            H["state_dot_planner"],
        )
        project = validate_success(resp, expected_status=201)
        assert_project(project)
        assert project["provisional_federal_share_pct"] == 0.90, (
            "statutory-base variant ignores interstate, safety, and land "
            f"adjustments; got {project['provisional_federal_share_pct']}"
        )
        assert project["provisional_federal_estimate_cents"] == 900_000
        assert project["determined_federal_share_pct"] is None
        assert project["status"] == "NOMINATED"

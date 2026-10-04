"""Difficulty queue — combinatorial_formula: multi-input branch interaction,
pinned nested rounding order, and pinned evaluation order over the cumulative
change-order cap (PRD §3.3, §2.6/§3.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    assert_project,
    create_apportionment,
    create_approved_voucher,
    create_change_order,
    create_draft_voucher,
    create_funding_program,
    create_line_item,
    create_project,
    create_stip,
    decide_stip,
    determine_project_eligible,
    federal_decide_change_order,
    get_success_data,
    set_clock,
    setup_project_under_construction,
    submit_stip,
    submit_voucher,
    concur_change_order,
    decide_voucher,
)
from test_helpers import ApiErrorId  # noqa: F401  (enum kept for reference)

H = TEST_USERS


class TestCombinatorialFormula:
    def test_safety_override_beats_land_sliding_scale(self, api):
        """PRD §3.3: "If the program is `HSIP` and the `activity_code` is one of
        `SIGNAGE_LIGHTING`, `GUARDRAIL_INSTALL`, or `PEDESTRIAN_CROSSING`, the
        share is 1.00 in full. This safety override wins outright: the land
        adjustment below is discarded entirely."
        PRD §3.3: "Otherwise, when the owning STIP's `state_federal_land_pct`
        is strictly greater than 0.05 (a state at exactly 0.05 receives no
        adjustment), the base slides toward the 0.95 cap: it becomes the lesser
        of 0.95 and the base plus the product of (0.95 minus the base) and
        `state_federal_land_pct`."

        On one HSIP STIP with land 0.40, the SIGNAGE_LIGHTING project
        determines at 1.00 (safety override discards the land branch), while
        the sibling BRIDGE_REPLACEMENT project takes the land branch:
        0.90 + (0.95 - 0.90) x 0.40 = 0.92.

        Design: Difficulty/combinatorial_formula/safety_override_beats_land_sliding_scale
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="HSIP",
            eligible_activity_codes=["SIGNAGE_LIGHTING", "BRIDGE_REPLACEMENT"],
        )
        # Capacity for the approval-time fiscal check (programmed estimates
        # 180,000 + 450,000 = 630,000 must fit).
        create_apportionment(
            program["id"], state_code="CA", federal_fiscal_year=2027,
            apportioned_cents=5_000_000,
        )
        stip = create_stip(state_code="CA", land_pct=0.40, start_ffy=2027)
        add_stip_comment(stip["id"], comment_text="Safety first.")
        project_s = create_project(
            stip["id"], program["id"], route_name="SR-9",
            description="Signal and signage upgrade",
            activity_code="SIGNAGE_LIGHTING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=200_000,
        )
        project_g = create_project(
            stip["id"], program["id"], route_name="SR-9",
            description="Bridge rail replacement",
            activity_code="BRIDGE_REPLACEMENT", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=500_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")

        determined_s = determine_project_eligible(project_s["id"])
        determined_g = determine_project_eligible(project_g["id"])
        assert_project(determined_s)
        assert_project(determined_g)
        assert determined_s["determined_federal_share_pct"] == 1.00, (
            "safety override must yield 1.00, got "
            f"{determined_s['determined_federal_share_pct']}"
        )
        assert determined_g["determined_federal_share_pct"] == 0.92, (
            "land branch must yield 0.90 + (0.95 - 0.90) x 0.40 == 0.92, got "
            f"{determined_g['determined_federal_share_pct']}"
        )

    def test_voucher_per_line_rounding_then_sum(self, api):
        """PRD §2.6: "One rounding-order rule is pinned because the two
        plausible orders disagree: voucher reimbursement rounds each line to
        whole cents first and only then sums. Summing first and rounding once
        is forbidden — at a share of 0.90 applied to two lines of 105 cents
        each, the mandated per-line order yields 95 + 95 = 190 cents, while
        sum-then-round would yield 189."

        The HSIP project determines at 0.90 (no interstate flag, activity
        outside the safety set, land 0.02 not above the 0.05 gate); lines
        [105, 105] therefore reimburse 190, not the 189 of sum-then-round.

        Design: Difficulty/combinatorial_formula/voucher_per_line_rounding_then_sum
        """
        ctx = setup_project_under_construction(
            program_code="HSIP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            activity_code="ROAD_RESURFACING",
            land_pct=0.02,
            project_cost_cents=1_200,
            apportioned_cents=100_000,
            initial_obligated_cents=1_000,
            agreement_number="FA-R-001",
        )
        authorization = ctx["authorization"]
        assert authorization["federal_share_pct"] == 0.90

        voucher = create_draft_voucher(
            authorization["id"],
            line_items=[
                create_line_item("mobilization", 105),
                create_line_item("striping", 105),
            ],
        )
        submit_voucher(voucher["id"])
        decided = decide_voucher(voucher["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        assert decided["eligible_amount_cents"] == 210
        assert decided["federal_reimbursable_cents"] == 190, (
            "per-line round_half_up then sum must yield 95 + 95 = 190, got "
            f"{decided['federal_reimbursable_cents']}"
        )

        reread = get_success_data(
            api.get_authorization(authorization["id"], H["fhwa_reviewer"])
        )
        assert reread["reimbursed_cents"] == 190

    def test_change_order_cumulative_cap_clamps_participation(self, api):
        """PRD §3.8: "first, the eligible amount is the `delta_cost_cents`
        multiplied by the Authorization's pinned `federal_share_pct`, rounded
        half-up to whole cents; second, the program-wide overrun cap is the
        Authorization's `initial_obligated_cents` multiplied by 0.20, rounded
        half-up to whole cents; third, the room remaining under that cap is the
        cap minus the Authorization's `cumulative_change_order_federal_cents`,
        which excludes this order; fourth, `federal_participation_cents` is the
        eligible amount clamped to that room — the lesser of the two, floored
        at zero."

        With share 0.80 and initial obligation 1,000,000 the cap is 200,000:
        the first order (delta 600,000, eligible 480,000) clamps to 200,000 and
        the second (delta 100,000, eligible 80,000) finds zero cap room.

        Design: Difficulty/combinatorial_formula/change_order_cumulative_cap_clamps_participation
        """
        ctx = setup_project_under_construction(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            activity_code="ROAD_RESURFACING",
            project_cost_cents=1_500_000,
            apportioned_cents=5_000_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-C-001",
        )
        auth_id = ctx["authorization"]["id"]
        apportionment_id = ctx["authorization"]["apportionment_id"]

        co1 = create_change_order(auth_id, 600_000, "CO1 pavement overrun")
        concur_change_order(co1["id"])
        decided1 = federal_decide_change_order(co1["id"], "APPROVE")
        assert decided1["status"] == "FEDERAL_APPROVED"
        assert decided1["federal_participation_cents"] == 200_000, (
            "first order clamps eligible 480,000 to the 200,000 cap, got "
            f"{decided1['federal_participation_cents']}"
        )

        co2 = create_change_order(auth_id, 100_000, "CO2 drainage overrun")
        concur_change_order(co2["id"])
        decided2 = federal_decide_change_order(co2["id"], "APPROVE")
        assert decided2["status"] == "FEDERAL_APPROVED"
        assert decided2["federal_participation_cents"] == 0, (
            "cap room is exhausted after the first order: min(80,000, 0) = 0, "
            f"got {decided2['federal_participation_cents']}"
        )

        authorization = get_success_data(api.get_authorization(auth_id, H["fhwa_reviewer"]))
        assert authorization["obligated_cents"] == 1_200_000
        assert authorization["cumulative_change_order_federal_cents"] == 200_000
        apportionment = get_success_data(
            api.get_apportionment(apportionment_id, H["fhwa_reviewer"])
        )
        assert apportionment["obligated_cents"] == 1_200_000
        assert apportionment["available_cents"] == 3_800_000

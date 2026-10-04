"""Combinatorial formulas: labor charge ordering and statement net composition."""
from test_helpers import (
    TEST_USERS,
    accept_referral,
    complete_referral,
    create_national_account,
    create_referral,
    create_statement,
    create_work_order,
    complete_work_order,
    dispatch_and_start,
    get_agreement,
    get_national_account,
    get_work_order,
    issue_statement,
    make_franchisee_operator_headers,
    settle_referral,
    setup_active_agreement,
    setup_two_brand_pair,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestLaborChargeTieredThreeInputFormula:
    def _urgent_account_work_order(self):
        _, franchisee, _, agreement = setup_active_agreement()
        account = create_national_account(
            account_type="PROPERTY_MANAGER",
            contracted_brands=[agreement["brand_id"]],
            service_level_hours=8,
            sla_credit_per_breach_cents=7500,
            breach_tolerance=2,
            annual_commitment_cents=25000000,
        )
        work_order = create_work_order(
            agreement["id"],
            source="NATIONAL_ACCOUNT",
            priority="URGENT",
            service_level_hours=6,
            parts_cents=12000,
            national_account_id=account["id"],
        )
        dispatch_and_start(work_order["id"], franchisee["id"])
        return franchisee, agreement, account, work_order

    def test_labor_ceils_the_priority_scaled_hours_before_applying_the_rate(self, api):
        """PRD §3.4: "First, the work order's `service_level_hours` is multiplied
        by the priority's hour scale — one half for `EMERGENCY`, three quarters
        for `URGENT`, one whole for `STANDARD` — and the result is rounded up to
        a whole number of hours and floored at a minimum of one hour. Second,
        that whole-hour figure is multiplied by the hourly rate for the
        priority, where `EMERGENCY` and `URGENT` both carry the higher rate of
        18500 cents and `STANDARD` carries 14500 cents."

        Design: Difficulty/combinatorial_formula/labor_charge_tiered_three_input_formula
        """
        franchisee, _, _, work_order = self._urgent_account_work_order()

        resp = api.complete_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        completed = validate_success(resp, 200)

        assert completed["status"] == "COMPLETED"
        assert completed["labor_cents"] == 83250, (
            "6 hours * 0.75 = 4.5, ceiled to 5 whole hours at the URGENT rate "
            f"18500, then scaled by the NATIONAL_ACCOUNT source multiplier 0.90: "
            f"expected 83250, got {completed['labor_cents']}"
        )
        assert completed["labor_cents"] != 92500, (
            "the scaled hour figure must be ceiled to a whole hour BEFORE the "
            "hourly rate is applied"
        )

    def test_revenue_adds_parts_and_flows_into_the_program_revenue(self, api):
        """PRD §3.4: "The `revenue_cents` is then the `labor_cents` plus the
        work order's `parts_cents`."
        PRD §3.4: "Where the work order names a program, the program's
        `accumulated_revenue_cents` is increased by the work order's
        `revenue_cents`."

        Design: Difficulty/combinatorial_formula/labor_charge_tiered_three_input_formula
        """
        franchisee, _, account, work_order = self._urgent_account_work_order()

        resp = api.complete_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        completed = validate_success(resp, 200)

        assert completed["revenue_cents"] == 95250, (
            f"83250 labor plus 12000 parts must be 95250, got {completed['revenue_cents']}"
        )
        program = get_national_account(account["id"])
        assert program["accumulated_revenue_cents"] == 95250, (
            f"completing under a program must add the revenue to it, got "
            f"{program['accumulated_revenue_cents']}"
        )
        assert program["open_breach_count"] == 0


class TestRoyaltyAccrualPinnedEvaluationOrder:
    def _statement_with_earned_settled_referral(self):
        ctx = setup_two_brand_pair(
            il_table=False, ms_agreement={"royalty_rate_override": 0.06},
        )
        # R1 originates at A1 (MS) and is received by A2 (IL), so A1 earns the
        # fee and carries a positive referral_offset_cents.
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
            estimated_job_value_cents=250000,
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 250000)
        # Only the receiving brand's table decides the tiered basis; with it
        # empty, the flat basis applies at the referral's own 0.10.
        referral = settle_referral(referral["id"], ctx["agt_a1"]["id"])
        statement = create_statement(
            ctx["agt_a1"]["id"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-10-01T00:00:00Z",
            gross_revenue_cents=100000,
        )
        return ctx, referral, statement

    def test_earned_offset_above_the_accruals_is_floored_only_at_the_total(self, api):
        """PRD §3.10: "The `net_remittance_cents` is the royalty figure plus the
        fund figure minus the referral offset — and, unlike the draft reading,
        floored at zero after the subtraction, so a period whose offsets exceed
        the royalty and fund accruals remits nothing rather than a negative
        amount."
        PRD §3.10: "The floor is applied to the final netted total only, never
        to the components, and each component is rounded independently before
        the subtraction."

        Design: Difficulty/combinatorial_formula/royalty_accrual_pinned_evaluation_order
        """
        _, referral, statement = self._statement_with_earned_settled_referral()
        assert referral["referral_fee_cents"] == 25000

        issued = issue_statement(statement["id"])

        assert issued["royalty_cents"] == 6000, (
            f"100000 * 0.06 must be 6000, got {issued['royalty_cents']}"
        )
        assert issued["ad_fund_cents"] == 1000
        assert issued["referral_offset_cents"] == 25000, (
            f"the agreement originates the referral, so it earns 25000: expected "
            f"25000, got {issued['referral_offset_cents']}"
        )
        assert issued["net_remittance_cents"] == 0, (
            "6000 + 1000 - 25000 is negative, so the floor must clamp the final "
            f"total to 0, got {issued['net_remittance_cents']}"
        )
        assert issued["royalty_cents"] == 6000 and issued["ad_fund_cents"] == 1000, (
            "the floor is applied to the netted total only, never to the "
            "components"
        )

    def test_royalty_ledger_moves_by_the_component_not_the_floored_total(self, api):
        """PRD §3.10: "each component is rounded independently before the
        subtraction" and the agreement's `cumulative_royalty_cents` is increased
        by the royalty figure — the floor on the total never touches the
        component that posts to the ledger.

        Design: Difficulty/combinatorial_formula/royalty_accrual_pinned_evaluation_order
        """
        ctx, _, statement = self._statement_with_earned_settled_referral()
        issued = issue_statement(statement["id"])
        assert issued["status"] == "ISSUED"

        agreement = get_agreement(ctx["agt_a1"]["id"])
        assert agreement["cumulative_royalty_cents"] == 6000, (
            f"the ledger must move by the un-floored royalty component 6000, got "
            f"{agreement['cumulative_royalty_cents']}"
        )

    def test_work_order_revenue_composes_labor_and_parts_at_standard_priority(self, api):
        """PRD §3.4: "A six-hour window dispatched at `EMERGENCY` priority
        therefore becomes a three-hour deadline, while the same six-hour window
        at `STANDARD` priority becomes a six-hour deadline."

        Design: Difficulty/combinatorial_formula/royalty_accrual_pinned_evaluation_order
        """
        _, franchisee, _, agreement = setup_active_agreement()
        work_order = create_work_order(
            agreement["id"], source="DIRECT", priority="STANDARD",
            service_level_hours=6, parts_cents=0,
        )
        dispatch_and_start(work_order["id"], franchisee["id"])
        completed = complete_work_order(work_order["id"], franchisee["id"])
        assert completed["sla_due_iso"] == "2026-09-01T06:00:00Z", (
            f"a STANDARD six-hour window keeps its full length, got "
            f"{completed['sla_due_iso']}"
        )
        assert completed["status"] == "COMPLETED"
        assert completed["labor_cents"] == 87000, (
            f"6 whole hours at the STANDARD rate 14500 with a DIRECT source "
            f"multiplier of 1.00 is 87000, got {completed['labor_cents']}"
        )
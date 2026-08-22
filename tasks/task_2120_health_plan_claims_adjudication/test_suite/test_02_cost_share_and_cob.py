"""Member cost share: the deductible waterfall, copay lines, the out-of-pocket cap and COB."""
import pytest

from test_helpers import (
    claim_line_payload,
    finalize,
    get_accumulator,
    lines_by_number,
    setup_cob_variant_pair,
    setup_environment,
    setup_oop_cap_snapshot_claim,
    submit_and_adjudicate,
)


class TestOutOfPocketCapReconciliation:
    def test_excess_liability_is_relieved_from_the_highest_line_number_down(self, api):
        """PRD §3.7: "That excess is then relieved line by line in `line_number`
        **descending** order — the highest-numbered line gives back first — with each line
        giving back the smaller of its own `member_liability_cents` and the excess still
        outstanding."
        PRD §3.7: "Line 2 gives back first, dropping from 10000 to 0 and leaving 6000 of
        excess; line 1 then gives back 6000, dropping from 10000 to 4000."

        Design: Difficulty/combinatorial_formula/oop_cap_uses_pass_start_accumulator_snapshot_not_midclaim_reread
        """
        env = setup_oop_cap_snapshot_claim()
        lines = lines_by_number(env["claim"]["id"])
        assert lines[1]["member_liability_cents"] == 4000, (
            "line 1 gives back only the residue of the excess, keeping 4000"
        )
        assert lines[1]["plan_paid_cents"] == 16000
        assert lines[2]["member_liability_cents"] == 0, (
            "line 2 gives back first and is relieved down to zero"
        )
        assert lines[2]["plan_paid_cents"] == 20000

    def test_accumulator_snapshot_is_taken_once_and_never_written_by_the_pass(self, api):
        """PRD §3.7: "The order that makes the value well defined is: first compute every
        line's provisional liability from the accumulator snapshot taken at the start of the
        pass; second cap the **claim-level** total against that same snapshot; third push
        the excess back onto the plan; and only fourth, and only at finalization, write the
        accumulator."
        PRD §3.7: "Had the accumulator been re-read after line 1, the answer would have been
        10000 and 0 — a different and wrong result."

        Design: Difficulty/combinatorial_formula/oop_cap_uses_pass_start_accumulator_snapshot_not_midclaim_reread
        """
        env = setup_oop_cap_snapshot_claim()
        claim = env["claim"]
        assert claim["total_allowed_cents"] == 40000
        assert claim["total_member_liability_cents"] == 4000, (
            "Re-reading the accumulator mid-claim would wrongly produce 10000"
        )
        assert claim["total_plan_paid_cents"] == 36000
        accumulator = get_accumulator(env["member"]["id"])
        assert accumulator["oop_applied_cents"] == 6000, (
            "An adjudication pass must not write the benefit accumulator"
        )


class TestCoordinationOfBenefitsVariants:
    def test_come_out_whole_pays_the_residue_and_leaves_the_member_owing_nothing(self, api):
        """PRD §3.7: "Under **`COME_OUT_WHOLE`**, the plan pays the smaller of that
        would-have-paid-as-primary figure and the claim's `total_allowed_cents` less the
        other payer's payment, with the latter floored at zero."
        PRD §3.7: "Whichever method applied, the claim's `total_plan_paid_cents` becomes
        that computed payment, and the claim's `total_member_liability_cents` becomes the
        claim's `total_allowed_cents` less the other payer's payment less the plan's
        payment, floored at zero."

        Design: Difficulty/dual_variant_calc/cob_come_out_whole_vs_non_duplication_diverge_on_identical_claim
        """
        env = setup_cob_variant_pair()
        claim = env["claim_come_out_whole"]
        assert claim["cob_role"] == "SECONDARY"
        assert claim["total_allowed_cents"] == 40000
        assert claim["total_plan_paid_cents"] == 16000, "min(28000, 40000 - 24000) = 16000"
        assert claim["total_member_liability_cents"] == 0

    def test_non_duplication_pays_only_the_shortfall_and_leaves_the_member_owing(self, api):
        """PRD §3.7: "Under **`NON_DUPLICATION`**, the plan pays the would-have-paid-as-primary
        figure less the other payer's payment, floored at zero."
        PRD §3.7: "The divergence is stark on identical inputs: with a `total_allowed_cents`
        of 40000, a zero deductible, a coinsurance share of 0.30 giving a
        would-have-paid-as-primary figure of 28000, and an `other_payer_paid_cents` of 24000,
        `COME_OUT_WHOLE` has the plan pay 16000 and leaves the member owing nothing, while
        `NON_DUPLICATION` has the plan pay 4000 and leaves the member owing 12000."

        Design: Difficulty/dual_variant_calc/cob_come_out_whole_vs_non_duplication_diverge_on_identical_claim
        """
        env = setup_cob_variant_pair()
        claim = env["claim_non_duplication"]
        assert claim["cob_role"] == "SECONDARY"
        assert claim["total_allowed_cents"] == 40000
        assert claim["total_plan_paid_cents"] == 4000, "max(0, 28000 - 24000) = 4000"
        assert claim["total_member_liability_cents"] == 12000
        assert claim["total_plan_paid_cents"] != env["claim_come_out_whole"][
            "total_plan_paid_cents"
        ], "The two methods must diverge on identical inputs"


class TestDeductibleAndCopayBranches:
    def test_copay_line_charges_a_flat_copay_and_leaves_the_deductible_untouched(self, api):
        """PRD §3.7: "**Copay branch.** For a line whose `procedure_code` is `99213` or
        `99214`, the line's `copay_cents` is the smaller of the plan's
        `copay_office_visit_cents` and the line's `allowed_amount_cents`; its
        `deductible_applied_cents` is zero; and the amount left to coinsure is the line's
        `allowed_amount_cents` less that copay."
        PRD §3.7: "Critically, a copay line does **not** draw down the running
        remaining-deductible figure at all, so an office visit never moves the member closer
        to meeting the deductible."

        Design: Corner/calculations/copay_line_skips_deductible_and_leaves_remaining_deductible_untouched
        """
        env = setup_environment(
            plan_overrides={
                "plan_code": "COPAY-1",
                "name": "Copay Plan",
                "deductible_individual_cents": 50000,
                "oop_max_individual_cents": 300000,
                "coinsurance_member_pct": 0.20,
            },
            provider_overrides={"npi": "2000000017", "name": "Upsilon Clinic"},
            member_overrides={"member_number": "M-COPAY-1"},
            rates=[("99213", 10000, "2026-01-01"), ("73721", 40000, "2026-01-01")],
        )
        claim = submit_and_adjudicate(
            env,
            [
                claim_line_payload(1, "99213", 1, 20000, "2026-02-10"),
                claim_line_payload(2, "73721", 1, 60000, "2026-02-10"),
            ],
            "CLM-COPAY-1",
        )
        assert claim["total_allowed_cents"] == 50000
        assert claim["total_deductible_applied_cents"] == 40000, (
            "Only the non-office-visit line draws against the deductible"
        )
        assert claim["total_member_liability_cents"] == 44000
        assert claim["total_plan_paid_cents"] == 6000
        lines = lines_by_number(claim["id"])
        assert lines[1]["copay_cents"] == 2500
        assert lines[1]["deductible_applied_cents"] == 0
        assert lines[1]["coinsurance_cents"] == 1500
        assert lines[1]["member_liability_cents"] == 4000
        assert lines[1]["plan_paid_cents"] == 6000
        assert lines[2]["copay_cents"] == 0
        assert lines[2]["deductible_applied_cents"] == 40000, (
            "The copay line left the full 50000 deductible standing for line 2"
        )
        assert lines[2]["coinsurance_cents"] == 0
        assert lines[2]["member_liability_cents"] == 40000

    def test_deductible_consumed_by_a_finalized_claim_carries_into_the_next_claim(self, api):
        """PRD §3.7: "The first is the remaining deductible: the plan's
        `deductible_individual_cents` less the accumulator's `deductible_applied_cents`,
        floored at zero."
        PRD §3.9: "The claim's `total_deductible_applied_cents` is added to the member's
        `deductible_applied_cents` and its `total_member_liability_cents` to the member's
        `oop_applied_cents`, on the benefit accumulator for that member and the calendar
        year of the earliest `service_date` on the claim — creating that accumulator row if
        the year has none yet — and `remitted_claim_count` increases by one."

        Design: Corner/calculations/deductible_carries_across_two_finalized_claims_in_the_same_plan_year
        """
        env = setup_environment(
            plan_overrides={
                "plan_code": "DED-1",
                "name": "Deductible Plan",
                "deductible_individual_cents": 50000,
                "oop_max_individual_cents": 300000,
                "coinsurance_member_pct": 0.20,
            },
            provider_overrides={"npi": "2000000022", "name": "Alpha2 Imaging"},
            member_overrides={"member_number": "M-DED-1"},
            rates=[("73721", 40000, "2026-01-01")],
        )
        first = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], "CLM-DED-1"
        )
        assert first["total_member_liability_cents"] == 40000
        assert first["total_plan_paid_cents"] == 0
        finalize(first["id"])

        second = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 61000, "2026-02-11")], "CLM-DED-2"
        )
        assert second["total_deductible_applied_cents"] == 10000, (
            "Only the 10000 of deductible the first claim left is available"
        )
        assert second["total_member_liability_cents"] == 16000
        assert second["total_plan_paid_cents"] == 24000
        finalize(second["id"])

        accumulator = get_accumulator(env["member"]["id"])
        assert accumulator["deductible_applied_cents"] == 50000
        assert accumulator["oop_applied_cents"] == 56000
        assert accumulator["remitted_claim_count"] == 2

"""The patient cost-share arithmetic: deductible, coinsurance, cap.

Two depth probes: a preventive line exempt from the deductible alongside a
basic line that absorbs it, and the annual maximum depleting in line order
within one claim.
"""

from test_helpers import factories as f
from test_helpers.assertions import get_success_data  # noqa: F401
from test_helpers.constants import (
    CATEGORY_BASIC,
    CATEGORY_MAJOR,
    CATEGORY_PREVENTIVE,
    CDT_CROWN_MAJOR,
    CDT_FILING_BASIC,
    CDT_PERIODIC_EVAL,
)
from test_helpers.fixtures import (
    claim_lines,
    create_claim,
    standard_stack,
    subscriber_accumulators,
)


class TestDeductibleExemptPreventiveAlongsideBasic:
    """The deductible branch is category-conditional."""

    def _cf1_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={
                "plan_code": "DD-CF1",
                "deductible_cents": 5000,
                "deductible_applies_preventive": False,
            },
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_PERIODIC_EVAL, allowed_cents=5000,
                    category=CATEGORY_PREVENTIVE,
                ),
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_FILING_BASIC, allowed_cents=10000,
                    category=CATEGORY_BASIC,
                ),
            ],
            subscriber_overrides={"member_id": "M-CF1", "full_name": "Carol Prime"},
        )

    def test_preventive_line_skips_the_deductible_entirely(self, client):
        """A deductible-exempt preventive line pays at full coinsurance.

        PRD 3.7: "the deductible step charges nothing when the line is
        preventive-category and the plan's `deductible_applies_preventive` is
        false; otherwise it charges the lesser of the line's `allowed_cents`
        and the patient's remaining deductible — the plan's
        `deductible_cents` minus the accumulator's `deductible_met_cents`,
        floored at zero — recording it as `deductible_applied_cents`."

        Design: Difficulty/combinatorial_formula/patient_cost_share_multi_input_nonlinear
        """
        stack = self._cf1_stack(client)

        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    line_number=1, cdt_code=CDT_PERIODIC_EVAL, tooth_number="",
                    submitted_amount_cents=5000,
                ),
                f.claim_line_payload(
                    line_number=2, cdt_code=CDT_FILING_BASIC, tooth_number="19",
                    submitted_amount_cents=12000,
                ),
            ],
        )

        lines = claim_lines(client, claim["id"])
        line1 = lines[0]
        assert line1["allowed_cents"] == 5000
        assert line1["deductible_applied_cents"] == 0, (
            "preventive line is deductible-exempt, got %r"
            % line1["deductible_applied_cents"]
        )
        assert line1["plan_pay_cents"] == 5000

    def test_basic_line_absorbs_deductible_then_floored_coinsurance(self, client):
        """The basic line takes the full deductible, then 80% floored.

        PRD 3.7: "The coinsurance step then computes the plan's share of the
        remainder: the allowed amount minus the line deductible, multiplied
        by the category's percentage — `preventive_coinsurance_pct`,
        `basic_coinsurance_pct`, or `major_coinsurance_pct` as the line's
        `category` dictates — divided by one hundred and floored to a whole
        cent, stored as `coinsurance_plan_cents`."
        PRD 3.7: "Adjudication finalizes the claim's rollups:
        `total_submitted_cents`, `total_allowed_cents`,
        `total_plan_pay_cents`, and `total_patient_pay_cents` are the
        per-line sums across the claim."

        Design: Difficulty/combinatorial_formula/patient_cost_share_multi_input_nonlinear
        """
        stack = self._cf1_stack(client)

        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    line_number=1, cdt_code=CDT_PERIODIC_EVAL, tooth_number="",
                    submitted_amount_cents=5000,
                ),
                f.claim_line_payload(
                    line_number=2, cdt_code=CDT_FILING_BASIC, tooth_number="19",
                    submitted_amount_cents=12000,
                ),
            ],
        )

        lines = claim_lines(client, claim["id"])
        line2 = lines[1]
        assert line2["allowed_cents"] == 10000, (
            "allowed is min(12000 submitted, 10000 schedule)"
        )
        assert line2["deductible_applied_cents"] == 5000
        assert line2["plan_pay_cents"] == 4000, (
            "floor((10000 - 5000) * 80/100) == 4000, got %r" % line2["plan_pay_cents"]
        )
        assert claim["total_plan_pay_cents"] == 9000
        assert claim["total_patient_pay_cents"] == 6000

        accumulators = subscriber_accumulators(client, stack["subscriber"]["id"])
        assert len(accumulators) == 1
        assert accumulators[0]["deductible_met_cents"] == 5000
        assert accumulators[0]["annual_max_used_cents"] == 9000


class TestAnnualMaximumDrawsDownInLineOrder:
    """The cap binds mid-claim because earlier lines deplete it first."""

    def _cf2_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-CF2", "annual_maximum_cents": 10000},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=8000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-CF2", "full_name": "Dan Prime"},
        )

    def test_first_two_lines_pay_in_full_while_the_cap_last(self, client):
        """Lines 1 and 2 each pay the full 50% share against a 10000 cap.

        PRD 3.7: "Surviving lines then draw down the patient's accumulator in
        `line_number` ascending order — order matters because the deductible
        and the annual maximum deplete sequentially, and later lines on the
        same claim observe earlier lines' draws."

        Design: Difficulty/combinatorial_formula/annual_max_circular_cap_draws_down_in_line_order
        """
        stack = self._cf2_stack(client)

        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    line_number=n, cdt_code=CDT_CROWN_MAJOR, tooth_number=str(tooth),
                    submitted_amount_cents=8000,
                )
                for n, tooth in ((1, 3), (2, 4), (3, 5))
            ],
        )

        lines = claim_lines(client, claim["id"])
        assert lines[0]["plan_pay_cents"] == 4000, (
            "line 1 pays floor(8000*50/100) with the cap not yet binding"
        )
        assert lines[1]["plan_pay_cents"] == 4000, (
            "line 2 still fits: 4000 used, 6000 remaining"
        )

    def test_third_line_is_capped_at_the_remaining_maximum(self, client):
        """Line 3 pays only what the cap leaves behind.

        PRD 3.7: "The annual-maximum step caps that share at the patient's
        remaining maximum — `annual_maximum_cents` minus
        `annual_max_used_cents`, floored at zero."

        Design: Difficulty/combinatorial_formula/annual_max_circular_cap_draws_down_in_line_order
        """
        stack = self._cf2_stack(client)

        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    line_number=n, cdt_code=CDT_CROWN_MAJOR, tooth_number=str(tooth),
                    submitted_amount_cents=8000,
                )
                for n, tooth in ((1, 3), (2, 4), (3, 5))
            ],
        )

        lines = claim_lines(client, claim["id"])
        assert lines[2]["plan_pay_cents"] == 2000, (
            "line 3's 4000 share is capped at 10000 - 8000 == 2000, got %r"
            % lines[2]["plan_pay_cents"]
        )
        assert claim["total_plan_pay_cents"] == 10000

        accumulators = subscriber_accumulators(client, stack["subscriber"]["id"])
        assert len(accumulators) == 1
        assert accumulators[0]["annual_max_used_cents"] == 10000, (
            "the cap is fully consumed by this claim"
        )

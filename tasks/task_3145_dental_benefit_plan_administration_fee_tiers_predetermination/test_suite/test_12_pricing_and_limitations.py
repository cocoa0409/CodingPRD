"""Pricing and limitation arithmetic.

The COB waterfall caps the secondary payment at what the primary left
behind; the alternate benefit provision re-prices a line at the cheaper
code and charges the member the difference; the missing-tooth clause and
the age and replacement limitations deny per their own keys; and the
plan-year boundary resets the deductible.
"""

from test_helpers import factories as f
from test_helpers.assertions import get_success_data
from test_helpers.constants import (
    CATEGORY_MAJOR,
    CATEGORY_PREVENTIVE,
    CDT_CROWN_MAJOR,
    DENIAL_AGE_LIMIT,
    DENIAL_FREQUENCY,
    DENIAL_MISSING_TOOTH,
    CLAIM_ADJUDICATED,
    CLAIM_DENIED,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    claim_lines,
    create_claim,
    create_dependent,
    create_limitation_rule,
    pay_claim,
    standard_stack,
    subscriber_accumulators,
)
from test_helpers.test_users import EXAMINER


class TestCobWaterfall:
    def test_cob_waterfall_caps_secondary_payment_at_remaining_responsibility(self, client):
        """The secondary pays the lesser of its share and what's left.

        PRD 3.8: "The COB waterfall first computes what this plan would have
        paid as primary — the full patient-cost-share arithmetic of §3.7 run
        as if the coverage were primary. The secondary payment is then
        bounded by what the primary carrier left behind: the line's allowed
        amount minus the claim's `cob_other_plan_paid_cents`. The plan's
        payment is the lesser of the hypothetical primary payment and that
        remaining responsibility, floored at zero, and is recorded on the
        claim as `cob_secondary_payment_cents`."

        Design: Corner/calculations/cob_waterfall_caps_secondary_payment_at_remaining_responsibility
        """
        stack = standard_stack(
            client,
            subscriber_overrides={
                "member_id": "M-COB",
                "full_name": "Coby Secondary",
                "cob_priority": "SECONDARY",
                "other_plan_external_id": "EXT-9",
            },
        )
        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    cdt_code="D2391", tooth_number="19",
                    submitted_amount_cents=10000,
                )
            ],
        )
        assert claim["status"] == "PENDED_REVIEW"

        resp = client.cob_confirm_claim(
            claim["id"], {"cob_other_plan_paid_cents": 7000}, headers=EXAMINER
        )
        confirmed = get_success_data(resp)
        assert confirmed["status"] == CLAIM_ADJUDICATED

        line = claim_lines(client, claim["id"])[0]
        # Hypothetical primary: floor(10000 * 80/100) == 8000; remaining
        # responsibility: 10000 - 7000 == 3000. The lesser wins.
        assert line["plan_pay_cents"] == 3000
        assert line["patient_pay_cents"] == 7000
        assert confirmed["cob_secondary_payment_cents"] == 3000


class TestAlternateBenefitProvision:
    def test_abp_repricing_charges_patient_the_difference(self, client):
        """The line prices at the cheaper alternate; the member pays the gap.

        PRD 3.6: "when the plan's `abp_enabled` is true and the entry names a
        non-empty `abp_alternative_cdt`, the system prices the alternate code
        the same way — the lesser of the submitted amount and the alternate
        entry's allowed amount — and if that alternate allowance is lower
        than the base allowance, the plan pays against the cheaper treatment.
        In that case the line's `abp_applied` becomes true, its
        `allowed_cents` drops to the alternate allowance, and the gap between
        the base allowance and the alternate allowance is recorded as
        `abp_patient_difference_cents` — a sum the patient owes in addition
        to their normal cost share, because the member chose the more
        expensive procedure."

        Design: Corner/calculations/abp_repricing_charges_patient_the_difference
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-ABP", "abp_enabled": True},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code="D2740", allowed_cents=10000, category=CATEGORY_MAJOR,
                    abp_alternative_cdt="D2799",
                ),
                f.fee_schedule_entry_payload(
                    cdt_code="D2799", allowed_cents=6000, category=CATEGORY_MAJOR,
                ),
            ],
        )

        claim = adjudicated_claim(
            client,
            stack,
            lines=[
                f.claim_line_payload(
                    cdt_code="D2740", tooth_number="14",
                    submitted_amount_cents=9000,
                )
            ],
        )

        line = claim_lines(client, claim["id"])[0]
        assert line["abp_applied"] is True
        assert line["allowed_cents"] == 6000
        assert line["abp_patient_difference_cents"] == 3000
        assert line["plan_pay_cents"] == 3000, "floor(6000 * 50/100) == 3000"
        assert line["patient_pay_cents"] == 6000, (
            "allowed 6000 - plan 3000 + ABP difference 3000"
        )


class TestMissingToothClause:
    def test_missing_tooth_clause_denies_replacement(self, client):
        """The attested tooth denies; its neighbour pays normally.

        PRD 3.7: "A `MISSING_TOOTH` rule fires only when the plan's
        `missing_tooth_clause_active` is true and the line names a
        `tooth_number`: if the claim's `tooth_missing_prior_to_coverage` map
        attests that tooth was missing before coverage began, the line is
        denied `MISSING_TOOTH`."

        Design: Corner/calculations/missing_tooth_clause_denies_replacement
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-MTC", "missing_tooth_clause_active": True},
        )

        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            tooth_missing_prior_to_coverage={"14": True},
            lines=[
                f.claim_line_payload(
                    line_number=1, cdt_code="D2740", tooth_number="14",
                    submitted_amount_cents=8000,
                ),
                f.claim_line_payload(
                    line_number=2, cdt_code="D2740", tooth_number="15",
                    submitted_amount_cents=8000,
                ),
            ],
        )

        assert claim["status"] == CLAIM_ADJUDICATED
        lines = claim_lines(client, claim["id"])
        assert lines[0]["denial_code"] == DENIAL_MISSING_TOOTH
        assert lines[0]["plan_pay_cents"] == 0
        assert lines[1]["status"] == "PAYABLE"
        assert lines[1]["plan_pay_cents"] == 4000


class TestAgeMaxLimitation:
    def test_age_max_limitation_denies_sealant_over_age(self, client):
        """Whole years at the service date: ten passes, fifteen denies.

        PRD 3.7: "An `AGE_MAX` rule denies with `AGE_LIMIT` when the
        patient's age in whole years at the service date exceeds
        `age_years_max`; an `AGE_MIN` rule denies `AGE_LIMIT` when that age
        falls short of `age_years_min` — ages are whole years, so a member is
        seventeen until their eighteenth birthday."

        Design: Corner/calculations/age_max_limitation_denies_sealant_over_age
        """
        stack = standard_stack(
            client,
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code="D1351", allowed_cents=4000,
                    category=CATEGORY_PREVENTIVE,
                ),
            ],
        )
        create_limitation_rule(
            client,
            stack["plan"]["id"],
            cdt_code="D1351",
            rule_kind="AGE_MAX",
            window_months=0,
            max_occurrences=0,
            age_years_min=0,
            age_years_max=14,
        )
        child_a = create_dependent(
            client,
            stack["subscriber"]["id"],
            full_name="Child A",
            date_of_birth="2015-06-01T00:00:00Z",
        )
        child_b = create_dependent(
            client,
            stack["subscriber"]["id"],
            full_name="Child B",
            date_of_birth="2010-06-01T00:00:00Z",
        )

        claim_a = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            dependent_id=child_a["id"],
            lines=[
                f.claim_line_payload(
                    cdt_code="D1351", tooth_number="19", submitted_amount_cents=4000
                )
            ],
        )
        claim_b = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            dependent_id=child_b["id"],
            lines=[
                f.claim_line_payload(
                    cdt_code="D1351", tooth_number="19", submitted_amount_cents=4000
                )
            ],
        )

        line_a = claim_lines(client, claim_a["id"])[0]
        assert line_a["status"] == "PAYABLE"
        assert line_a["plan_pay_cents"] == 4000, "preventive pays at 100%"

        assert claim_b["status"] == CLAIM_DENIED
        line_b = claim_lines(client, claim_b["id"])[0]
        assert line_b["denial_code"] == DENIAL_AGE_LIMIT


class TestReplacementInterval:
    def test_replacement_interval_denies_early_crown_replacement(self, client):
        """The interval keys on the patient and the tooth number.

        PRD 3.7: "A `REPLACEMENT_INTERVAL` rule looks back at the patient's
        most recent paid line for the same `tooth_number` with a code in the
        same major category (ties broken by earliest `created_at`), and
        denies `FREQUENCY` when fewer than `window_months` calendar months
        have elapsed since that prior service."

        Design: Corner/calculations/replacement_interval_denies_early_crown_replacement
        """
        stack = standard_stack(client)
        create_limitation_rule(
            client,
            stack["plan"]["id"],
            cdt_code="D2740",
            rule_kind="REPLACEMENT_INTERVAL",
            window_months=60,
            max_occurrences=0,
            age_years_min=0,
            age_years_max=0,
        )
        claim_1 = adjudicated_claim(
            client,
            stack,
            service_date="2026-01-10T00:00:00Z",
            received_date="2026-01-11T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code="D2740", tooth_number="9", submitted_amount_cents=8000
                )
            ],
        )
        pay_claim(client, claim_1["id"])

        claim_2 = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            service_date="2028-01-01T00:00:00Z",
            received_date="2028-01-02T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    line_number=1, cdt_code="D2740", tooth_number="9",
                    submitted_amount_cents=8000,
                ),
                f.claim_line_payload(
                    line_number=2, cdt_code="D2740", tooth_number="10",
                    submitted_amount_cents=8000,
                ),
            ],
        )

        assert claim_2["status"] == CLAIM_ADJUDICATED
        lines = claim_lines(client, claim_2["id"])
        assert lines[0]["denial_code"] == DENIAL_FREQUENCY, (
            "24 months is inside the 60-month window for tooth 9"
        )
        assert lines[1]["status"] == "PAYABLE", (
            "tooth 10 has no paid history"
        )


class TestAllowedAmountFloor:
    def test_allowed_amount_is_min_of_submitted_and_schedule(self, client):
        """The plan never allows more than was billed.

        PRD 3.6: "With the schedule resolved, the line's base allowed amount
        is the lesser of the provider's `submitted_amount_cents` and the
        schedule entry's `allowed_cents`; the entry's `category` is copied
        onto the line at this moment."

        Design: Corner/calculations/allowed_amount_is_min_of_submitted_and_schedule
        """
        stack = standard_stack(client)

        claim = adjudicated_claim(
            client,
            stack,
            lines=[
                f.claim_line_payload(
                    cdt_code="D0120", tooth_number="", submitted_amount_cents=4500
                )
            ],
        )

        line = claim_lines(client, claim["id"])[0]
        assert line["allowed_cents"] == 4500, "min(4500 submitted, 5000 schedule)"
        assert line["plan_pay_cents"] == 4500, "preventive pays at 100%"


class TestPlanYearRollover:
    def test_plan_year_rollover_resets_deductible_accumulator(self, client):
        """A July renewal splits one member's year into two buckets.

        PRD 2.7: "A plan declares its renewal month as
        `plan_year_start_month` (an integer from 1 to 12). The plan-year
        bucket for a service date is derived as follows: if the service
        date's month is on or after the plan's anchor month, the plan-year
        starts in the service date's calendar year; otherwise it started in
        the prior calendar year. The bucket key `plan_year_key` is the two
        years joined by a hyphen — for example, a plan renewing in July
        treats a March 2027 service as belonging to plan year `2026-2027`,
        while a September 2027 service belongs to `2027-2028`."
        PRD 2.7: "Each (subscriber, dependent-or-null, plan-year) combination
        has at most one `BenefitAccumulator`, created lazily on the first
        adjudication that touches it with `deductible_met_cents` and
        `annual_max_used_cents` at zero and `version` at 1."

        Design: Corner/calculations/plan_year_rollover_resets_deductible_accumulator
        """
        stack = standard_stack(
            client,
            plan_overrides={
                "plan_code": "DD-PYR",
                "plan_year_start_month": 7,
                "deductible_cents": 5000,
            },
        )

        adjudicated_claim(
            client,
            stack,
            service_date="2026-06-15T00:00:00Z",
            received_date="2026-06-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code="D2391", tooth_number="19",
                    submitted_amount_cents=10000,
                )
            ],
        )
        adjudicated_claim(
            client,
            stack,
            service_date="2026-07-15T00:00:00Z",
            received_date="2026-07-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code="D2391", tooth_number="20",
                    submitted_amount_cents=10000,
                )
            ],
        )

        accumulators = subscriber_accumulators(client, stack["subscriber"]["id"])
        by_year = {a["plan_year_key"]: a for a in accumulators}
        assert set(by_year) == {"2025-2026", "2026-2027"}, (
            "the June service lands in the old year, the July service in the new"
        )
        assert by_year["2025-2026"]["deductible_met_cents"] == 5000
        assert by_year["2025-2026"]["annual_max_used_cents"] == 4000
        assert by_year["2026-2027"]["deductible_met_cents"] == 5000, (
            "the deductible resets at the July boundary"
        )
        assert by_year["2026-2027"]["annual_max_used_cents"] == 4000

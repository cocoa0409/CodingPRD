"""Dual-variant readings and pinned combinatorial arithmetic across the medical
professional liability rating, reserving and settlement engines.

Covers the two readings of an insured's claim history, the two incurred-loss
figures a claim carries side by side, the fee ladder keyed on net premium, the
per-claim rounding of the reserve adequacy review and the hammer-clause split.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures
from test_helpers.assertions import assert_money, assert_ratio
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
ANALYST = TEST_USERS["actuarial_analyst_headers"]


# --------------------------------------------------------------------------
# Composite books built from the public endpoints only.
# --------------------------------------------------------------------------
def _obstetrics_live_book(api, **policy_overrides):
    """Obstetrics rate manual, credentialed Cook County physician, claims-made
    policy and one live term running 2026-08-01 to 2027-08-01."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    insured = fixtures.build_credentialed_insured(api, specialty["id"])
    policy = fixtures.build_policy(api, insured["id"], **policy_overrides)
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    term = fixtures.issue_term(api, term["id"])
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
    }


def _book_with_four_open_claims(api):
    """The same book carrying four open claims reported inside the first term,
    then a renewal term stepped onto the expiring one."""
    book = _obstetrics_live_book(api)
    insured_id = book["insured"]["id"]
    claim_inputs = [
        ("2026-08-05", "2026-09-01", "OBSTETRIC_INJURY"),
        ("2026-08-06", "2026-09-02", "OBSTETRIC_INJURY"),
        ("2026-08-07", "2026-09-03", "DIAGNOSIS_FAILURE"),
        ("2026-08-08", "2026-09-04", "DIAGNOSIS_FAILURE"),
    ]
    for incident_date, report_date, allegation_category in claim_inputs:
        fixtures.build_claim(
            api, insured_id,
            incident_date=incident_date,
            report_date=report_date,
            venue_code="COOK_IL",
            allegation_category=allegation_category,
            demand_amount=100000.00,
        )
    renewal = fixtures.build_term(
        api, book["policy"]["id"], "2027-08-01", "2028-08-01",
        predecessor_term_id=book["term"]["id"],
    )
    book["renewal_term"] = renewal
    return book


def _orthopedic_draft_quote(api, base_rate_per_million=24800.00):
    """A Maricopa County orthopedic quote whose first term rates at step five,
    unit increased-limits factor and unit venue factor."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_orthopedic_class(
        api, base_rate_per_million=base_rate_per_million,
    )
    insured = fixtures.build_insured(
        api, specialty["id"],
        legal_name="Desert Orthopedics PLLC",
        venue_code="MARICOPA_AZ",
        high_severity_procedure_pct=30,
    )
    policy = fixtures.build_policy(api, insured["id"], prior_acts_step_credit=4)
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
    }


def _family_medicine_experience(api):
    """A family-medicine book with one live term and two case-reserved claims
    whose demands are one cent apart."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(
        api,
        specialty_code="FAMILY_MEDICINE",
        base_class_code="CLASS_1",
        base_rate_per_million=9500.00,
        hazard_index=2.0,
        benchmark_severity=180000.00,
    )
    insured = fixtures.build_credentialed_insured(
        api, specialty["id"],
        legal_name="Papago Family Medicine",
        venue_code="MARICOPA_AZ",
        high_severity_procedure_pct=10,
        years_in_practice=8,
    )
    policy = fixtures.build_policy(api, insured["id"])
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    term = fixtures.issue_term(api, term["id"])
    claims = []
    claim_inputs = [
        ("2026-08-10", "2026-09-01", "DIAGNOSIS_FAILURE", 12345.68,
         "2026-09-05T00:00:00Z"),
        ("2026-08-11", "2026-09-02", "MEDICATION_ERROR", 12345.67,
         "2026-09-06T00:00:00Z"),
    ]
    for incident_date, report_date, category, demand, effective_at in claim_inputs:
        claim = fixtures.build_investigated_claim(
            api, insured["id"], "COVERED",
            incident_date=incident_date,
            report_date=report_date,
            venue_code="MARICOPA_AZ",
            allegation_category=category,
            demand_amount=demand,
        )
        fixtures.post_reserve(
            api, claim["id"], method="CASE_BASIS",
            effective_at=effective_at,
            rationale="adjuster case reserve",
            indemnity_amount=2000.00,
            expense_amount=900.00,
        )
        claims.append(claim)
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
        "claims": claims,
    }


def _vetoed_hammer_negotiation(api):
    """A litigated obstetrics claim whose 400000.00 offer was authorised at
    450000.00, tendered under a hammer clause and vetoed by the physician."""
    book = _obstetrics_live_book(api, consent_to_settle_clause="HAMMER")
    claim = fixtures.build_litigated_claim(
        api, book["insured"]["id"], suit_filed_on="2026-09-15",
        incident_date="2026-08-05", report_date="2026-09-01",
        venue_code="COOK_IL", allegation_category="OBSTETRIC_INJURY",
        demand_amount=800000.00,
    )
    negotiation = fixtures.open_negotiation(
        api, claim["id"], proposed_amount=400000.00,
        authority_requested=450000.00, headers=ADJ,
    )
    fixtures.decide_authority(
        api, negotiation["id"], "GRANT", 450000.00, headers=APPROVER,
    )
    fixtures.request_consent(api, negotiation["id"])
    fixtures.respond_to_consent(
        api, negotiation["id"], book["insured"]["id"],
        "VETOED", "defensible standard of care",
    )
    book["claim"] = claim
    book["negotiation"] = negotiation
    return book


class TestRiskClassificationVariantDivergence:
    """The stored snapshot band and the renewal band read the same facts."""

    def test_stored_classification_excludes_the_four_open_claims(self, api):
        """The insured's own record stays in R2 at factor 1.00 because the
        snapshot reading counts no open claim.

        PRD: "Under the **`UNDERWRITING_SNAPSHOT`** reading, open claims are
        excluded from the history component entirely and only closed paid claims
        count."

        Design: Difficulty/dual_variant_calc/risk_classification_snapshot_versus_renewal_prospective_band_divergence
        """
        book = _book_with_four_open_claims(api)

        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured["open_claim_count"] == 4
        assert insured["closed_paid_claim_count"] == 0
        assert_money(insured["risk_class_score"], 4.20, "risk_class_score")
        assert insured["risk_class_code"] == "R2"
        assert_money(insured["risk_class_factor"], 1.00, "risk_class_factor")

    def test_bound_first_term_keeps_the_snapshot_band_it_was_rated_on(self, api):
        """The step-one term bound before the claims arrived stays frozen at the
        R2 band its own snapshot variant produced.

        PRD: "`rating_variant` follows from the same fact: a first term with no
        predecessor is rated `UNDERWRITING_SNAPSHOT`, and a term with a
        predecessor is rated `RENEWAL_PROSPECTIVE`."

        Design: Difficulty/dual_variant_calc/risk_classification_snapshot_versus_renewal_prospective_band_divergence
        """
        book = _book_with_four_open_claims(api)

        first_term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert first_term["rating_variant"] == "UNDERWRITING_SNAPSHOT"
        assert first_term["rated_risk_class_code"] == "R2"

    def test_renewal_term_rates_a_band_higher_on_identical_stored_data(self, api):
        """The stepped renewal term rates at R3 factor 1.30 because the
        prospective reading adds the four open claims at weight 1.0.

        PRD: "Under the **`RENEWAL_PROSPECTIVE`** reading, open claims are added
        to the history component at weight 1.0 alongside closed paid claims at
        weight 2.0, so the same underlying facts can land a renewal quote in a
        higher band than the insured's own record shows."

        Design: Difficulty/dual_variant_calc/risk_classification_snapshot_versus_renewal_prospective_band_divergence
        """
        book = _book_with_four_open_claims(api)

        renewal = validate_success(
            api.get_policy_term(book["renewal_term"]["id"], UW)
        )
        assert renewal["rating_variant"] == "RENEWAL_PROSPECTIVE"
        assert renewal["rated_risk_class_code"] == "R3"
        assert_money(
            renewal["rated_risk_class_factor"], 1.30, "rated_risk_class_factor"
        )

    def test_renewal_premium_ladder_multiplies_the_diverged_band_factor(self, api):
        """The renewal term prices at 44021.48 in total, the step-two ladder run
        on the higher renewal band.

        PRD: "The manual premium is then built on a four-stage ladder, and each
        stage is rounded half up to two decimal places before the next stage
        multiplies it — intermediate values are deliberately not carried at full
        precision."

        Design: Difficulty/dual_variant_calc/risk_classification_snapshot_versus_renewal_prospective_band_divergence
        """
        book = _book_with_four_open_claims(api)

        renewal = validate_success(
            api.get_policy_term(book["renewal_term"]["id"], UW)
        )
        assert renewal["claims_made_step_year"] == 2
        assert_money(renewal["step_factor"], 0.60, "step_factor")
        assert_money(renewal["premium_manual"], 42978.00, "premium_manual")
        assert_money(renewal["premium_net"], 42978.00, "premium_net")
        assert_money(renewal["administrative_fee"], 500.00, "administrative_fee")
        assert_money(
            renewal["guaranty_fund_assessment"], 543.48,
            "guaranty_fund_assessment",
        )
        assert_money(renewal["term_total"], 44021.48, "term_total")


def _formula_reserved_claim_with_paid_expense(api):
    """A covered obstetrics claim demanding 1000000.00, formula-reserved and
    then billed 40000.00 of defence expense by its assigned panel firm."""
    book = _obstetrics_live_book(api)
    firm = fixtures.build_counsel_firm(
        api,
        firm_name="Halloran Defense LLP",
        admitted_venue_codes=["COOK_IL"],
        allegation_specialties=["OBSTETRIC_INJURY", "SURGICAL_ERROR"],
        blended_hourly_rate=425.00,
        quality_score=90,
    )
    claim = fixtures.build_investigated_claim(
        api, book["insured"]["id"], "COVERED",
        incident_date="2026-08-05", report_date="2026-09-01",
        venue_code="COOK_IL", allegation_category="OBSTETRIC_INJURY",
        demand_amount=1000000.00,
    )
    reserve = fixtures.post_reserve(
        api, claim["id"], method="FORMULA_BASIS",
        effective_at="2026-09-05T00:00:00Z",
        rationale="initial projected reserve",
    )
    assignment = fixtures.assign_counsel(api, claim["id"])
    fixtures.pay_expense(
        api, claim["id"], assignment["id"], amount=40000.00,
        invoice_reference="HAL-2026-0001",
    )
    book.update({
        "firm": firm, "claim": claim, "reserve": reserve,
        "assignment": assignment,
    })
    return book


class TestClaimIncurredDualReadings:
    """Case-incurred and actuarial-incurred diverge by the eroded expense."""

    def test_formula_projection_caps_indemnity_and_floors_expense(self, api):
        """The formula posting projects 652500.00 of indemnity and 182700.00 of
        expense on a 1000000.00 Cook County demand in the third severity band.

        PRD: "The raw indemnity is the claim's `demand_amount` multiplied by its
        `severity_band_factor` multiplied by the venue severity factor for the
        claim's own `venue_code`, rounded half up to two decimal places;
        `computed_indemnity_amount` is the lesser of that rounded figure and the
        policy's `limit_per_claim`, with the cap applied after the rounding."

        Design: Difficulty/dual_variant_calc/claim_incurred_case_versus_actuarial_delta_after_expense_payment
        """
        book = _formula_reserved_claim_with_paid_expense(api)

        postings, _ = validate_paginated(
            api.list_reserve_entries(book["claim"]["id"], ADJ)
        )
        posting = [p for p in postings if p["id"] == book["reserve"]["id"]][0]
        assert posting["method"] == "FORMULA_BASIS"
        assert_money(
            posting["computed_indemnity_amount"], 652500.00,
            "computed_indemnity_amount",
        )
        assert_money(
            posting["computed_expense_amount"], 182700.00,
            "computed_expense_amount",
        )

        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(claim["indemnity_reserve"], 652500.00, "indemnity_reserve")
        assert_money(claim["expense_reserve"], 182700.00, "expense_reserve")
        assert_money(claim["paid_expense"], 40000.00, "paid_expense")
        assert_money(claim["paid_indemnity"], 0.00, "paid_indemnity")

    def test_case_incurred_treats_paid_expense_as_consuming_the_reserve(self, api):
        """The claims department reading lands at 835200.00, the 40000.00 of paid
        expense having eroded the carried expense reserve.

        PRD: "`case_incurred` is the figure the claims department reports and
        treats payments as having consumed the reserve: it is `paid_indemnity`
        plus `paid_expense`, plus the excess of `indemnity_reserve` over
        `paid_indemnity` where that excess is positive and zero otherwise, plus
        the excess of `expense_reserve` over `paid_expense` on the same clamped
        basis, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/claim_incurred_case_versus_actuarial_delta_after_expense_payment
        """
        book = _formula_reserved_claim_with_paid_expense(api)

        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(claim["case_incurred"], 835200.00, "case_incurred")

    def test_actuarial_incurred_stacks_the_payment_on_the_full_reserve(self, api):
        """The actuarial reading lands at 875200.00, exactly 40000.00 above the
        case reading because the payment sits on top of the carried reserve.

        PRD: "`actuarial_incurred` is the figure that feeds rate filings and
        reserve adequacy, and it stacks payments on top of the full carried
        reserve: it is `paid_indemnity` plus `paid_expense` plus
        `indemnity_reserve` plus `expense_reserve`, rounded half up to two
        decimal places."

        Design: Difficulty/dual_variant_calc/claim_incurred_case_versus_actuarial_delta_after_expense_payment
        """
        book = _formula_reserved_claim_with_paid_expense(api)

        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(claim["actuarial_incurred"], 875200.00, "actuarial_incurred")
        assert_money(
            float(claim["actuarial_incurred"]) - float(claim["case_incurred"]),
            40000.00, "incurred divergence",
        )

    def test_expense_payment_lands_on_the_assignment_and_the_firm(self, api):
        """The 40000.00 invoice is carried on the assignment and on the panel
        firm's running billed total as well as on the claim.

        PRD: "The payment increases the claim's `paid_expense`, the assignment's
        `billed_expense_amount` and the firm's `billed_expense_total` each by the
        paid amount, and recomputes both incurred figures — which is the point at
        which `case_incurred` and `actuarial_incurred` begin to diverge, since
        paid expense erodes the carried expense reserve in the first figure and
        sits on top of it in the second."

        Design: Difficulty/dual_variant_calc/claim_incurred_case_versus_actuarial_delta_after_expense_payment
        """
        book = _formula_reserved_claim_with_paid_expense(api)

        assignment = validate_success(
            api.get_counsel_assignment(book["assignment"]["id"], ADJ)
        )
        assert_money(
            assignment["billed_expense_amount"], 40000.00,
            "billed_expense_amount",
        )
        firm = validate_success(api.get_counsel_firm(book["firm"]["id"], APPROVER))
        assert_money(
            firm["billed_expense_total"], 40000.00, "billed_expense_total"
        )


class TestAdminFeeTierKeyedOnNetPremium:
    """A net premium of 24800.00 grows past 25000.00 only after the fees."""

    def test_four_stage_ladder_lands_net_premium_just_under_the_tier(self, api):
        """A step-five Maricopa quote at unit increased-limits and venue factors
        rates a manual and net premium of 24800.00.

        PRD: "The manual premium is then built on a four-stage ladder, and each
        stage is rounded half up to two decimal places before the next stage
        multiplies it — intermediate values are deliberately not carried at full
        precision."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_premium_net_not_on_term_total
        """
        book = _orthopedic_draft_quote(api)

        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert term["claims_made_step_year"] == 5
        assert_money(term["step_factor"], 1.00, "step_factor")
        assert_money(
            term["increased_limits_factor"], 1.00, "increased_limits_factor"
        )
        assert_money(
            term["venue_severity_factor"], 1.00, "venue_severity_factor"
        )
        assert term["rated_risk_class_code"] == "R2"
        assert_money(term["premium_manual"], 24800.00, "premium_manual")
        assert_money(term["premium_net"], 24800.00, "premium_net")

    def test_flat_administrative_fee_reads_the_first_tier(self, api):
        """The flat fee is 250.00 because the net premium of 24800.00 is below
        the 25000.00 boundary.

        PRD: "`administrative_fee` is a flat charge selected from three tiers on
        `premium_net` alone — 250.00 when `premium_net` is below 25000.00, 500.00
        when it is at least 25000.00 but below 100000.00, and 900.00 when it is
        100000.00 or more."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_premium_net_not_on_term_total
        """
        book = _orthopedic_draft_quote(api)

        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(term["administrative_fee"], 250.00, "administrative_fee")

    def test_term_total_crosses_the_boundary_without_moving_the_fee(self, api):
        """The assessment of 313.13 keys on net premium plus the fee and the term
        total settles at 25363.13, above the boundary the fee ignored.

        PRD: "Neither the fee tier nor the assessment is keyed on `term_total`."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_premium_net_not_on_term_total
        """
        book = _orthopedic_draft_quote(api)

        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(
            term["guaranty_fund_assessment"], 313.13,
            "guaranty_fund_assessment",
        )
        assert_money(term["term_total"], 25363.13, "term_total")
        assert float(term["term_total"]) > 25000.00
        assert_money(term["administrative_fee"], 250.00, "administrative_fee")

    def test_drafted_quote_rolls_up_to_the_policy_premium_ledger(self, api):
        """The unbound quote of 25363.13 is the policy's quoted premium while its
        written net premium stays at 0.00.

        PRD: "`quoted_premium_total` is the sum of `term_total` over that policy's
        terms in `DRAFT` status, rounded to two decimal places."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_premium_net_not_on_term_total
        """
        book = _orthopedic_draft_quote(api)

        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            policy["quoted_premium_total"], 25363.13, "quoted_premium_total"
        )
        assert_money(
            policy["written_premium_net_total"], 0.00,
            "written_premium_net_total",
        )


class TestRequiredReserveRoundsPerClaim:
    """Two demands a cent apart round separately before they are added."""

    def _filing(self, api):
        book = _family_medicine_experience(api)
        filing = fixtures.build_rate_filing(
            api, book["specialty"]["id"],
            indication_method="LOSS_RATIO_METHOD",
            proposed_rate_change_pct=5.00,
            experience_period_start="2026-08-01",
            experience_period_end="2027-08-01",
            effective_date="2027-08-01",
        )
        book["filing"] = filing
        return book

    def test_required_reserve_sums_the_rounded_per_claim_figures(self, api):
        """Two loaded per-claim figures of 3160.49 sum to 6320.98 rather than the
        6320.99 a single closing round would produce.

        PRD: "`required_reserve_total` is built by taking, for each claim in
        scope, the product of its `demand_amount`, its `severity_band_factor` and
        the venue severity factor for its own `venue_code`, multiplying that
        product by 1.28 (one plus the twenty-eight percent expense loading),
        rounding that per-claim figure half up to two decimal places, and only
        then summing the rounded per-claim figures."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert filing["claim_count_in_scope"] == 2
        assert_money(
            filing["required_reserve_total"], 6320.98, "required_reserve_total"
        )

    def test_carried_reserve_adds_each_claim_after_rounding_it(self, api):
        """The two case reserves of 2900.00 each give a carried total of 5800.00,
        the same figure the actuarial incurred total reports.

        PRD: "`carried_reserve_total` is the sum, over the same scope, of each
        claim's `indemnity_reserve` plus its `expense_reserve`, each claim's sum
        rounded to two decimal places before being added."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert_money(
            filing["carried_reserve_total"], 5800.00, "carried_reserve_total"
        )
        assert_money(
            filing["actuarial_incurred_total"], 5800.00,
            "actuarial_incurred_total",
        )

    def test_adequacy_ratio_divides_carried_by_the_rounded_requirement(self, api):
        """The ratio is 0.9176, the carried 5800.00 over the per-claim-rounded
        requirement of 6320.98.

        PRD: "When `required_reserve_total` is zero, `reserve_adequacy_ratio` is
        null and `adequacy_flag` is `NOT_EVALUABLE`; otherwise the ratio is the
        carried total divided by the required total, rounded half up to four
        decimal places."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert_ratio(
            filing["reserve_adequacy_ratio"], 0.9176, "reserve_adequacy_ratio"
        )

    def test_adequacy_flag_sits_on_the_inclusive_adequate_boundary_side(self, api):
        """A ratio of 0.9176 flags the filing ADEQUATE rather than DEFICIENT.

        PRD: "A ratio strictly below 0.9000 flags the filing `DEFICIENT`; a ratio
        from 0.9000 up to and including 1.1000 flags it `ADEQUATE`; a ratio above
        1.1000 flags it `REDUNDANT`."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert filing["adequacy_flag"] == "ADEQUATE"

    def test_premium_scope_counts_only_the_live_term(self, api):
        """The single live term contributes its net premium of 2826.25 to the
        filing's in-scope premium.

        PRD: "`in_scope_premium_total` is the sum of `premium_net` over the policy
        terms whose policy's insured belongs to the filing's specialty class,
        whose status is `IN_FORCE`, `EXPIRED` or `CANCELLED_PRO_RATA`, whose
        effective date is on or before the experience period end and whose
        expiration date is strictly after the experience period start."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(term["premium_net"], 2826.25, "premium_net")
        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert_money(
            filing["in_scope_premium_total"], 2826.25, "in_scope_premium_total"
        )

    def test_experience_loss_ratio_divides_incurred_by_in_scope_premium(self, api):
        """The loss ratio is 2.0522, the actuarial incurred 5800.00 over the
        in-scope premium 2826.25.

        PRD: "When the in-scope premium is zero, `experience_loss_ratio` and
        `indicated_change_pct` are both null; otherwise `experience_loss_ratio`
        is the actuarial incurred total divided by the in-scope premium total,
        rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert_ratio(
            filing["experience_loss_ratio"], 2.0522, "experience_loss_ratio"
        )

    def test_credibility_blends_the_already_rounded_indication(self, api):
        """A two-claim scope carries credibility 0.30, so the indication of 215.72
        blends with the 4.50 trend complement to 67.87.

        PRD: "`credibility_weighted_indication_pct` blends the already-rounded
        indication with a trend complement of 4.50 percent: it is the credibility
        weight multiplied by `indicated_change_pct`, plus one minus that weight
        multiplied by 4.50, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/required_reserve_rounds_each_claim_before_summing
        """
        book = self._filing(api)

        filing = validate_success(api.get_rate_filing(book["filing"]["id"], ANALYST))
        assert_money(filing["indicated_change_pct"], 215.72, "indicated_change_pct")
        assert_money(filing["credibility_weight"], 0.30, "credibility_weight")
        assert_money(
            filing["credibility_weighted_indication_pct"], 67.87,
            "credibility_weighted_indication_pct",
        )


class TestHammerExposureCapsBeforeTheSplit:
    """The per-claim cap, the excess and the fifty-fifty split run in that order."""

    def test_projected_exposure_takes_the_multiplied_offer_under_the_limit(self, api):
        """A 400000.00 offer projects to 640000.00, the multiplied figure being the
        smaller of it and the one-million per-claim limit.

        PRD: "The projected exposure is the negotiation's `proposed_amount`
        multiplied by a hammer exposure multiplier of 1.60, capped at the
        responding policy's `limit_per_claim`, with the smaller of the two figures
        rounded half up to two decimal places and stored as
        `hammer_exposure_estimate`."

        Design: Difficulty/combinatorial_formula/hammer_exposure_caps_before_excess_split
        """
        book = _vetoed_hammer_negotiation(api)

        negotiation = fixtures.invoke_hammer(
            api, book["negotiation"]["id"], notice_sent_on="2026-10-01"
        )
        assert_money(
            negotiation["hammer_exposure_estimate"], 640000.00,
            "hammer_exposure_estimate",
        )
        assert_money(negotiation["proposed_amount"], 400000.00, "proposed_amount")

    def test_invocation_records_the_notice_and_flags_the_clause(self, api):
        """Invoking the clause moves the negotiation to HAMMER_INVOKED, raises
        hammer_invoked and records the notice date.

        PRD: "`VETOED` → `HAMMER_INVOKED` sets `hammer_invoked` to true, records
        `notice_sent_on`, and computes the insured's share of the consequences of
        refusing to settle."

        Design: Difficulty/combinatorial_formula/hammer_exposure_caps_before_excess_split
        """
        book = _vetoed_hammer_negotiation(api)

        negotiation = fixtures.invoke_hammer(
            api, book["negotiation"]["id"], notice_sent_on="2026-10-01"
        )
        assert negotiation["status"] == "HAMMER_INVOKED"
        assert negotiation["hammer_invoked"] is True
        assert negotiation["notice_sent_on"] == "2026-10-01"
        assert negotiation["consent_clause_applied"] == "HAMMER"

    def test_shares_split_the_excess_over_the_rejected_offer_in_half(self, api):
        """The 240000.00 excess over the rejected offer splits into a 120000.00
        insured share and a 520000.00 carrier share.

        PRD: "`insured_share_amount` is half of that excess — fifty percent —
        rounded half up to two decimal places, and `carrier_share_amount` is
        `hammer_exposure_estimate` less `insured_share_amount`, rounded the same
        way."

        Design: Difficulty/combinatorial_formula/hammer_exposure_caps_before_excess_split
        """
        book = _vetoed_hammer_negotiation(api)

        negotiation = fixtures.invoke_hammer(
            api, book["negotiation"]["id"], notice_sent_on="2026-10-01"
        )
        assert_money(
            negotiation["insured_share_amount"], 120000.00, "insured_share_amount"
        )
        assert_money(
            negotiation["carrier_share_amount"], 520000.00, "carrier_share_amount"
        )

    def test_capping_precedes_the_excess_so_the_shares_do_not_sum_naively(self, api):
        """The two shares add back to the capped projected exposure, the pinned
        order having taken the cap before the excess and the excess before the
        split.

        PRD: "The order of the three operations is pinned and materially changes
        the answer: the per-claim cap is applied before the excess is taken, and
        the excess is taken before the share split."

        Design: Difficulty/combinatorial_formula/hammer_exposure_caps_before_excess_split
        """
        book = _vetoed_hammer_negotiation(api)

        negotiation = fixtures.invoke_hammer(
            api, book["negotiation"]["id"], notice_sent_on="2026-10-01"
        )
        assert_money(
            float(negotiation["insured_share_amount"])
            + float(negotiation["carrier_share_amount"]),
            640000.00,
            "insured share plus carrier share",
        )

    def test_chargeback_receivable_rises_by_the_insured_share(self, api):
        """The claim's chargeback receivable takes the 120000.00 insured share
        while no indemnity has yet been paid.

        PRD: "Invocation also increases the claim's `insured_share_receivable` by
        `insured_share_amount`, the running total of what the carrier may charge
        back to insureds under invoked hammer clauses."

        Design: Difficulty/combinatorial_formula/hammer_exposure_caps_before_excess_split
        """
        book = _vetoed_hammer_negotiation(api)

        fixtures.invoke_hammer(
            api, book["negotiation"]["id"], notice_sent_on="2026-10-01"
        )
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(
            claim["insured_share_receivable"], 120000.00, "insured_share_receivable"
        )
        assert_money(claim["paid_indemnity"], 0.00, "paid_indemnity")

"""Premium rating, risk classification, reserving and panel selection maths.

Covers the four-stage claims-made rating ladder and the fee ladder built on
top of it, the weighted risk classification bands, the two reserve projection
variants with their per-claim cap and expense floor, the risk-management
programme credit, the quoted-versus-written premium roll-ups and the ranked
selection of defence counsel.
"""
import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fee_ladder,
    assert_money,
    assert_ratio,
    days_after,
)

UW = fx.UW
ADJ = fx.ADJ
APPROVER = fx.APPROVER

STEP_ONE_NET = 19285.00
CREDITED_NET = 18706.45


def _high_limit_quote(api):
    """An obstetrics quote written at the two-million per-claim limit."""
    specialty = fx.build_specialty_class(api)
    insured = fx.build_insured(api, specialty["id"])
    policy = fx.build_policy(
        api, insured["id"],
        limit_per_claim=2000000.00, limit_aggregate=6000000.00,
    )
    term = fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    return {"insured": insured, "policy": policy, "term": term}


class TestIncreasedLimitsFactorFlowsThroughTheLadder:
    """A higher per-claim limit lifts every stage of the manual premium."""

    def test_a_two_million_limit_keys_the_factor_at_one_point_four_five(self, api):
        """Doubling the per-claim limit is priced at 1.45, not at 2.00.

        PRD: "`increased_limits_factor` is keyed on the policy's per-claim limit: 1.00 at one million, 1.45 at two million, 1.75 at three million and 2.10 at five million."

        Design: Corner/calculations/increased_limits_factor_of_one_point_four_five_flows_through_the_whole_ladder
        """
        quote = _high_limit_quote(api)

        assert float(quote["term"]["increased_limits_factor"]) == 1.45

    def test_the_manual_premium_walks_the_four_stage_ladder(self, api):
        """38000.00 becomes 27963.25 once limits, venue, risk and step apply.

        PRD: "The manual premium is then built on a four-stage ladder, and each stage is rounded half up to two decimal places before the next stage multiplies it — intermediate values are deliberately not carried at full precision."

        Design: Corner/calculations/increased_limits_factor_of_one_point_four_five_flows_through_the_whole_ladder
        """
        quote = _high_limit_quote(api)

        term = quote["term"]
        assert float(term["venue_severity_factor"]) == 1.45
        assert float(term["rated_risk_class_factor"]) == 1.00
        assert_money(term["premium_manual"], 27963.25, "premium_manual")

    def test_a_first_year_claims_made_term_prices_at_step_one(self, api):
        """No prior acts credit means the first year rates at 0.35.

        PRD: "First the step position: on a claims-made policy, `claims_made_step_year` is the lesser of 5 and the sum of the term's `term_index` and the policy's `prior_acts_step_credit`, and `step_factor` is the factor published for that step year — 0.35 for step 1, 0.60 for step 2, 0.80 for step 3, 0.92 for step 4 and 1.00 for step 5."

        Design: Corner/calculations/increased_limits_factor_of_one_point_four_five_flows_through_the_whole_ladder
        """
        quote = _high_limit_quote(api)

        assert quote["term"]["claims_made_step_year"] == 1
        assert float(quote["term"]["step_factor"]) == 0.35

    def test_the_fees_key_on_the_net_premium_not_on_the_term_total(self, api):
        """A 27963.25 net premium sits in the middle fee tier at 500.00.

        PRD: "The fee ladder keys the flat administrative fee on the net premium — not on the term total — and keys the guaranty fund assessment on the net premium plus that administrative fee, again not on the term total."

        Design: Corner/calculations/increased_limits_factor_of_one_point_four_five_flows_through_the_whole_ladder
        """
        quote = _high_limit_quote(api)

        term = quote["term"]
        assert_money(term["premium_net"], 27963.25, "premium_net")
        assert_money(term["administrative_fee"], 500.00, "administrative_fee")
        assert_money(
            term["guaranty_fund_assessment"], 355.79, "guaranty_fund_assessment"
        )
        assert_money(term["term_total"], 28819.04, "term_total")
        assert_fee_ladder(term)

    def test_the_high_limit_quote_rolls_up_to_the_policy(self, api):
        """The whole 28819.04 offer is visible on the policy while it is DRAFT.

        PRD: "`quoted_premium_total` is the sum of `term_total` over that policy's terms in `DRAFT` status, rounded to two decimal places."

        Design: Corner/calculations/increased_limits_factor_of_one_point_four_five_flows_through_the_whole_ladder
        """
        quote = _high_limit_quote(api)

        policy = validate_success(api.get_policy(quote["policy"]["id"], UW))
        assert_money(
            policy["quoted_premium_total"], 28819.04, "quoted_premium_total"
        )


def _insured_at_hazard(api, specialty_code, hazard_index, legal_name):
    """A Travis County physician at a 40 percent high-severity procedure mix."""
    specialty = fx.build_specialty_class(
        api,
        specialty_code=specialty_code,
        base_class_code="CLASS_2",
        base_rate_per_million=20000.00,
        hazard_index=hazard_index,
        benchmark_severity=200000.00,
    )
    return fx.build_insured(
        api, specialty["id"],
        legal_name=legal_name,
        venue_code="TRAVIS_TX",
        high_severity_procedure_pct=40,
        years_in_practice=8,
    )


# Two hazard indices either side of the R1/R2 boundary, with the score,
# band and rating factor each of them must produce.
HAZARD_ROWS = [
    ("FAMILY_MEDICINE", 3.9, "Lakeside Family Medicine", 2.96, "R1", 0.85),
    ("EMERGENCY_MEDICINE", 4.0, "Lakeside Emergency Physicians", 3.00, "R2", 1.00),
]


class TestRiskClassificationAtTheBandBoundary:
    """A score of exactly 3.00 belongs to the higher band; 2.96 does not."""

    @pytest.mark.parametrize(
        "specialty_code,hazard_index,legal_name,expected_score",
        [(row[0], row[1], row[2], row[3]) for row in HAZARD_ROWS],
    )
    def test_the_weighted_score_combines_hazard_and_procedure_mix(
        self, api, specialty_code, hazard_index, legal_name, expected_score
    ):
        """A physician with no claim history scores on specialty and mix alone.

        PRD: "`risk_class_score` is 0.40 times the specialty component, plus 0.35 times the procedure component, plus 0.25 times the capped history component, rounded half up to two decimal places."

        Design: Corner/calculations/risk_score_of_exactly_three_lands_in_r2_while_two_point_nine_six_stays_r1
        """
        insured = _insured_at_hazard(api, specialty_code, hazard_index, legal_name)

        assert insured["closed_paid_claim_count"] == 0
        assert insured["open_claim_count"] == 0
        assert float(insured["risk_class_score"]) == pytest.approx(
            expected_score, abs=0.005
        )

    @pytest.mark.parametrize(
        "specialty_code,hazard_index,legal_name,expected_code",
        [(row[0], row[1], row[2], row[4]) for row in HAZARD_ROWS],
    )
    def test_the_band_lower_bound_is_inclusive(
        self, api, specialty_code, hazard_index, legal_name, expected_code
    ):
        """Exactly 3.00 is already the second band, while 2.96 is still the first.

        PRD: "The score maps to `risk_class_code` on bands whose lower bound is inclusive and upper bound exclusive: below 3.00 is `R1`, from 3.00 up to but not including 5.00 is `R2`, from 5.00 up to but not including 7.50 is `R3`, and 7.50 or above is `R4`."

        Design: Corner/calculations/risk_score_of_exactly_three_lands_in_r2_while_two_point_nine_six_stays_r1
        """
        insured = _insured_at_hazard(api, specialty_code, hazard_index, legal_name)

        assert insured["risk_class_code"] == expected_code

    @pytest.mark.parametrize(
        "specialty_code,hazard_index,legal_name,expected_factor",
        [(row[0], row[1], row[2], row[5]) for row in HAZARD_ROWS],
    )
    def test_each_band_carries_its_own_rating_factor(
        self, api, specialty_code, hazard_index, legal_name, expected_factor
    ):
        """The band decides whether the physician is credited or rated at par.

        PRD: "`risk_class_factor` is the multiplicative rating factor for that band — 0.85 for `R1`, 1.00 for `R2`, 1.30 for `R3` and 1.75 for `R4`."

        Design: Corner/calculations/risk_score_of_exactly_three_lands_in_r2_while_two_point_nine_six_stays_r1
        """
        insured = _insured_at_hazard(api, specialty_code, hazard_index, legal_name)

        assert float(insured["risk_class_factor"]) == expected_factor


def _live_obstetrics_book(api):
    """A credentialed Cook County obstetrician on a live 1M/3M term."""
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(api, specialty["id"])
    policy = fx.build_policy(api, insured["id"])
    term = fx.issue_term(
        api, fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")["id"]
    )
    return {"insured": insured, "policy": policy, "term": term}


def _two_formula_reserved_claims(api):
    """One catastrophic demand and one nuisance demand, both projected."""
    book = _live_obstetrics_book(api)
    big = fx.build_claim(
        api, book["insured"]["id"],
        incident_date="2026-08-05", report_date="2026-09-01",
        demand_amount=2500000.00,
    )
    small = fx.build_claim(
        api, book["insured"]["id"],
        incident_date="2026-08-06", report_date="2026-09-01",
        allegation_category="MEDICATION_ERROR", demand_amount=20000.00,
    )
    big_entry = fx.post_reserve(
        api, big["id"], "FORMULA_BASIS", "2026-09-02T00:00:00Z",
        rationale="formula projection on the large demand",
    )
    small_entry = fx.post_reserve(
        api, small["id"], "FORMULA_BASIS", "2026-09-02T00:00:00Z",
        rationale="formula projection on the small demand",
    )
    return {
        "book": book, "big": big, "small": small,
        "big_entry": big_entry, "small_entry": small_entry,
    }


class TestFormulaReserveProjection:
    """The formula basis caps indemnity at the limit and floors the expense."""

    def test_the_projection_is_capped_at_the_per_claim_limit(self, api):
        """A 2175000.00 projection is cut to the 1000000.00 the policy can pay.

        PRD: "The raw indemnity is the claim's `demand_amount` multiplied by its `severity_band_factor` multiplied by the venue severity factor for the claim's own `venue_code`, rounded half up to two decimal places; `computed_indemnity_amount` is the lesser of that rounded figure and the policy's `limit_per_claim`, with the cap applied after the rounding."

        Design: Corner/calculations/formula_reserve_caps_at_the_per_claim_limit_and_floors_the_expense
        """
        bundle = _two_formula_reserved_claims(api)

        assert_money(
            bundle["big_entry"]["computed_indemnity_amount"], 1000000.00,
            "capped computed_indemnity_amount",
        )
        assert_money(
            bundle["small_entry"]["computed_indemnity_amount"], 5800.00,
            "uncapped computed_indemnity_amount",
        )

    def test_the_expense_projection_never_falls_below_the_floor(self, api):
        """28 percent of the large reserve stands; the small one is lifted to 15000.00.

        PRD: "`computed_expense_amount` is the greater of two figures: twenty-eight percent of `computed_indemnity_amount` rounded half up to two decimal places, and an expense reserve floor of 15000.00 — again with the floor applied after the rounding."

        Design: Corner/calculations/formula_reserve_caps_at_the_per_claim_limit_and_floors_the_expense
        """
        bundle = _two_formula_reserved_claims(api)

        assert_money(
            bundle["big_entry"]["computed_expense_amount"], 280000.00,
            "computed_expense_amount above the floor",
        )
        assert_money(
            bundle["small_entry"]["computed_expense_amount"], 15000.00,
            "floored computed_expense_amount",
        )

    def test_the_claim_carries_the_governing_posting(self, api):
        """The claim shows the reserve of record and the basis it was set on.

        PRD: "The claim's `indemnity_reserve`, `expense_reserve` and `reserve_method_current` are re-derived from that governing entry after every posting — 0.00, 0.00 and null respectively when the claim has no postings at all — and every posting on the claim is visible in the claim's append-only posting list, filterable by `method`."

        Design: Corner/calculations/formula_reserve_caps_at_the_per_claim_limit_and_floors_the_expense
        """
        bundle = _two_formula_reserved_claims(api)

        big = validate_success(api.get_claim(bundle["big"]["id"], ADJ))
        assert_money(big["indemnity_reserve"], 1000000.00, "indemnity_reserve")
        assert_money(big["expense_reserve"], 280000.00, "expense_reserve")
        assert big["reserve_method_current"] == "FORMULA_BASIS"
        small = validate_success(api.get_claim(bundle["small"]["id"], ADJ))
        assert_money(small["expense_reserve"], 15000.00, "floored expense_reserve")
        postings, _meta = validate_paginated(
            api.list_reserve_entries(bundle["big"]["id"], ADJ)
        )
        assert [entry["id"] for entry in postings] == [bundle["big_entry"]["id"]]

    def test_the_demand_places_the_claim_in_its_severity_band(self, api):
        """A 2500000.00 demand is band four; a 20000.00 demand is band one.

        PRD: "A demand below 250000.00 is `BAND_1`; from 250000.00 up to but not including 750000.00 is `BAND_2`; from 750000.00 up to but not including 2000000.00 is `BAND_3`; 2000000.00 or above is `BAND_4`."

        Design: Corner/calculations/formula_reserve_caps_at_the_per_claim_limit_and_floors_the_expense
        """
        bundle = _two_formula_reserved_claims(api)

        assert bundle["big"]["severity_band"] == "BAND_4"
        assert float(bundle["big"]["severity_band_factor"]) == 0.60
        assert bundle["small"]["severity_band"] == "BAND_1"
        assert float(bundle["small"]["severity_band_factor"]) == 0.20


class TestCaseBasisReserveProjection:
    """The adjuster's own figures are taken as posted, guards and all."""

    def _case_posted_claim(self, api):
        book = _live_obstetrics_book(api)
        claim = fx.build_claim(
            api, book["insured"]["id"],
            incident_date="2026-08-05", report_date="2026-09-01",
            demand_amount=800000.00,
        )
        entry = fx.post_reserve(
            api, claim["id"], "CASE_BASIS", "2026-09-02T00:00:00Z",
            indemnity_amount=1500000.00, expense_amount=5000.00,
            rationale="adjuster judgement above the limit with a thin expense",
        )
        return claim, entry

    def test_case_amounts_survive_the_cap_and_the_floor(self, api):
        """1500000.00 above the limit and 5000.00 below the floor both stand.

        PRD: "Under `CASE_BASIS` those are simply the adjuster's `indemnity_amount` and `expense_amount`, each rounded half up to two decimal places and taken verbatim otherwise: neither the per-claim limit cap nor the expense floor is applied to an adjuster's own numbers."

        Design: Corner/calculations/case_basis_amounts_are_taken_verbatim_past_the_cap_and_under_the_floor
        """
        _claim, entry = self._case_posted_claim(api)

        assert entry["method"] == "CASE_BASIS"
        assert_money(
            entry["computed_indemnity_amount"], 1500000.00,
            "computed_indemnity_amount",
        )
        assert_money(
            entry["computed_expense_amount"], 5000.00, "computed_expense_amount"
        )

    def test_the_claim_records_the_case_basis_as_its_current_method(self, api):
        """The reserve of record is the adjuster's posting, on its own basis.

        PRD: "The claim's `indemnity_reserve`, `expense_reserve` and `reserve_method_current` are re-derived from that governing entry after every posting — 0.00, 0.00 and null respectively when the claim has no postings at all — and every posting on the claim is visible in the claim's append-only posting list, filterable by `method`."

        Design: Corner/calculations/case_basis_amounts_are_taken_verbatim_past_the_cap_and_under_the_floor
        """
        claim, _entry = self._case_posted_claim(api)

        after = validate_success(api.get_claim(claim["id"], ADJ))
        assert_money(after["indemnity_reserve"], 1500000.00, "indemnity_reserve")
        assert_money(after["expense_reserve"], 5000.00, "expense_reserve")
        assert after["reserve_method_current"] == "CASE_BASIS"


def _enrolled_but_incomplete(api):
    """A credentialed insured sitting in a risk course it has not finished."""
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(api, specialty["id"])
    enrollment = fx.enrol_insured(api, insured["id"], "CME_RISK_101", "2026-08-01")
    policy = fx.build_policy(api, insured["id"])
    term = fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    return {
        "insured": insured, "enrollment": enrollment,
        "policy": policy, "term": term,
    }


def _course_completed_and_requoted(api):
    """The course is finished on 2026-08-15 and a fresh policy is then quoted."""
    state = _enrolled_but_incomplete(api)
    state["bound_term"] = fx.issue_term(api, state["term"]["id"])
    fx.advance_clock(api, "2026-08-15T00:00:00Z")
    state["completed"] = fx.complete_enrolment(
        api, state["enrollment"]["id"], "2026-08-15", "ATT-CME-0001"
    )
    state["second_policy"] = fx.build_policy(
        api, state["insured"]["id"], retroactive_date="2026-09-01"
    )
    state["fresh_term"] = fx.build_term(
        api, state["second_policy"]["id"], "2026-09-01", "2027-09-01"
    )
    return state


class TestOnlyCompletedProgrammesEarnCredit:
    """A course in progress earns nothing; a finished one earns three percent."""

    def test_an_unfinished_course_earns_no_credit(self, api):
        """The term rates at the full 19285.00 while the course is only enrolled.

        PRD: "Enrollments in `ENROLLED` or `EXPIRED` status contribute nothing."

        Design: Corner/calculations/only_completed_enrollments_move_the_program_credit
        """
        state = _enrolled_but_incomplete(api)

        assert state["enrollment"]["status"] == "ENROLLED"
        assert_ratio(state["term"]["credit_pct_applied"], 0, "credit_pct_applied")
        assert_money(state["term"]["premium_net"], STEP_ONE_NET, "premium_net")

    def test_completion_freezes_the_credit_and_dates_its_expiry(self, api):
        """Finishing the course banks three percent for the next two years.

        PRD: "`ENROLLED` → `COMPLETED` freezes `credit_pct_snapshot` at the credit percentage published for that programme, sets `expires_on` to 730 calendar days after `completed_on`, recomputes the insured's stacked credit, re-rates every `DRAFT` term on the insured's policies and recomputes each affected policy's `quoted_premium_total`."

        Design: Corner/calculations/only_completed_enrollments_move_the_program_credit
        """
        state = _course_completed_and_requoted(api)

        completed = state["completed"]
        assert completed["status"] == "COMPLETED"
        assert completed["completed_on"] == "2026-08-15"
        assert_ratio(completed["credit_pct_snapshot"], 0.03, "credit_pct_snapshot")
        assert completed["expires_on"] == days_after("2026-08-15", 730)

    def test_the_completed_course_credits_the_next_quote(self, api):
        """The risk course published at three percent is the credit applied.

        PRD: "The surviving rows' credit percentages are then added — three percent for `CME_RISK_101`, five percent for `SIM_LAB`, four percent for `CHART_AUDIT`, two percent for `TEAMSTEPPS` and two and a half percent for `EHR_SAFETY` — the sum is rounded half up to four decimal places, and the result is capped at ten percent however many programmes the insured has completed."

        Design: Corner/calculations/only_completed_enrollments_move_the_program_credit
        """
        state = _course_completed_and_requoted(api)

        assert_ratio(
            state["fresh_term"]["credit_pct_applied"], 0.03, "credit_pct_applied"
        )

    def test_the_credit_comes_off_the_manual_premium(self, api):
        """19285.00 manual less three percent nets 18706.45.

        PRD: "`premium_net` is `premium_manual` multiplied by the quantity one minus `credit_pct_applied` plus `surcharge_pct_applied`, rounded half up to two decimal places."

        Design: Corner/calculations/only_completed_enrollments_move_the_program_credit
        """
        state = _course_completed_and_requoted(api)

        term = state["fresh_term"]
        assert_money(term["premium_manual"], STEP_ONE_NET, "premium_manual")
        assert_ratio(term["surcharge_pct_applied"], 0, "surcharge_pct_applied")
        assert_money(term["premium_net"], CREDITED_NET, "premium_net")

    def test_the_credited_quote_carries_the_lower_fee_tier(self, api):
        """A net premium under 25000.00 pays the 250.00 flat fee.

        PRD: "The fee ladder keys the flat administrative fee on the net premium — not on the term total — and keys the guaranty fund assessment on the net premium plus that administrative fee, again not on the term total."

        Design: Corner/calculations/only_completed_enrollments_move_the_program_credit
        """
        state = _course_completed_and_requoted(api)

        term = state["fresh_term"]
        assert_money(term["administrative_fee"], 250.00, "administrative_fee")
        assert_money(
            term["guaranty_fund_assessment"], 236.96, "guaranty_fund_assessment"
        )
        assert_money(term["term_total"], 19193.41, "term_total")
        assert_fee_ladder(term)

    def test_the_already_bound_term_is_never_re_rated(self, api):
        """The term issued before the course finished keeps its bound premium.

        PRD: "Terms that are already `ISSUED`, `IN_FORCE` or terminal keep the premium they were bound at; they are never re-rated."

        Design: Corner/calculations/only_completed_enrollments_move_the_program_credit
        """
        state = _course_completed_and_requoted(api)

        bound = validate_success(api.get_policy_term(state["term"]["id"], UW))
        assert_money(bound["premium_net"], STEP_ONE_NET, "bound premium_net")
        assert_ratio(bound["credit_pct_applied"], 0, "bound credit_pct_applied")


def _renewal_quoted_on_a_live_policy(api):
    """A live first year plus a future-dated renewal still sitting in DRAFT."""
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(api, specialty["id"], "2030-01-01")
    policy = fx.build_policy(api, insured["id"])
    first = fx.issue_term(
        api, fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")["id"]
    )
    renewal = fx.build_term(
        api, policy["id"], "2027-08-01", "2028-08-01",
        predecessor_term_id=first["id"],
    )
    return {"policy": policy, "first": first, "renewal": renewal}


class TestIssuingTheRenewalMovesTheMoney:
    """The renewal total leaves the quoted roll-up and joins the written one."""

    def test_the_quoted_total_empties_once_the_renewal_binds(self, api):
        """33979.50 offered while DRAFT, and nothing outstanding afterwards.

        PRD: "`quoted_premium_total` is the sum of `term_total` over that policy's terms in `DRAFT` status, rounded to two decimal places."

        Design: Corner/calculations/issuing_the_renewal_moves_its_total_from_quoted_into_written
        """
        state = _renewal_quoted_on_a_live_policy(api)
        assert_money(state["renewal"]["term_total"], 33979.50, "term_total")
        before = validate_success(api.get_policy(state["policy"]["id"], UW))
        assert_money(
            before["quoted_premium_total"], 33979.50, "quoted_premium_total"
        )

        fx.issue_term(api, state["renewal"]["id"])

        after = validate_success(api.get_policy(state["policy"]["id"], UW))
        assert_money(after["quoted_premium_total"], 0.00, "quoted_premium_total")

    def test_the_written_ledger_gains_the_renewal_premium(self, api):
        """19285.00 written on year one becomes 52345.00 across both years.

        PRD: "`written_premium_net_total` is the sum, over that policy's terms in `ISSUED`, `IN_FORCE`, `EXPIRED`, `CANCELLED_FLAT` or `CANCELLED_PRO_RATA` status, of each term's `premium_net` less its `return_premium`, rounded to two decimal places."

        Design: Corner/calculations/issuing_the_renewal_moves_its_total_from_quoted_into_written
        """
        state = _renewal_quoted_on_a_live_policy(api)
        before = validate_success(api.get_policy(state["policy"]["id"], UW))
        assert_money(
            before["written_premium_net_total"], STEP_ONE_NET,
            "written_premium_net_total",
        )

        fx.issue_term(api, state["renewal"]["id"])

        after = validate_success(api.get_policy(state["policy"]["id"], UW))
        assert_money(
            after["written_premium_net_total"], 52345.00,
            "written_premium_net_total",
        )

    def test_the_second_term_climbs_the_claims_made_step(self, api):
        """Term two of a claims-made policy rates at the 0.60 step factor.

        PRD: "First the step position: on a claims-made policy, `claims_made_step_year` is the lesser of 5 and the sum of the term's `term_index` and the policy's `prior_acts_step_credit`, and `step_factor` is the factor published for that step year — 0.35 for step 1, 0.60 for step 2, 0.80 for step 3, 0.92 for step 4 and 1.00 for step 5."

        Design: Corner/calculations/issuing_the_renewal_moves_its_total_from_quoted_into_written
        """
        state = _renewal_quoted_on_a_live_policy(api)

        renewal = state["renewal"]
        assert renewal["term_index"] == 2
        assert renewal["claims_made_step_year"] == 2
        assert float(renewal["step_factor"]) == 0.60
        assert_money(renewal["premium_net"], 33060.00, "premium_net")

    def test_a_term_with_a_predecessor_is_rated_prospectively(self, api):
        """A renewal is rated on the renewal reading, not the intake snapshot.

        PRD: "`rating_variant` follows from the same fact: a first term with no predecessor is rated `UNDERWRITING_SNAPSHOT`, and a term with a predecessor is rated `RENEWAL_PROSPECTIVE`."

        Design: Corner/calculations/issuing_the_renewal_moves_its_total_from_quoted_into_written
        """
        state = _renewal_quoted_on_a_live_policy(api)

        assert state["first"]["rating_variant"] == "UNDERWRITING_SNAPSHOT"
        assert state["renewal"]["rating_variant"] == "RENEWAL_PROSPECTIVE"

    def test_a_future_dated_renewal_binds_into_issued(self, api):
        """Bound a year ahead of inception, the renewal waits rather than attaching.

        PRD: "When the effective date is still in the future, `DRAFT` → `ISSUED` fires and the term waits for the clock sweep to promote it."

        Design: Corner/calculations/issuing_the_renewal_moves_its_total_from_quoted_into_written
        """
        state = _renewal_quoted_on_a_live_policy(api)

        bound = fx.issue_term(api, state["renewal"]["id"])

        assert bound["status"] == "ISSUED"


def _three_firm_panel_with_a_conflict(api):
    """Three admitted obstetric firms, the strongest of them conflicted out."""
    book = _live_obstetrics_book(api)
    insured_id = book["insured"]["id"]
    gamma = fx.build_counsel_firm(
        api, firm_name="Gamma Trial Group LLP", blended_hourly_rate=900.00,
        quality_score=99, max_concurrent_assignments=5,
        conflict_insured_ids=[insured_id],
    )
    alpha = fx.build_counsel_firm(
        api, firm_name="Alpha Defense LLP", blended_hourly_rate=700.00,
        quality_score=95, max_concurrent_assignments=5, conflict_insured_ids=[],
    )
    beta = fx.build_counsel_firm(
        api, firm_name="Beta Litigation LLP", blended_hourly_rate=500.00,
        quality_score=95, max_concurrent_assignments=5, conflict_insured_ids=[],
    )
    claim = fx.build_claim(
        api, insured_id,
        incident_date="2026-08-05", report_date="2026-09-01",
        demand_amount=800000.00,
    )
    fx.decide_coverage(api, claim["id"], "COVERED")
    return {
        "book": book, "gamma": gamma, "alpha": alpha, "beta": beta, "claim": claim,
    }


class TestPanelCounselSelection:
    """Eligibility filters first, then quality, then the hourly rate."""

    def test_the_conflicted_firm_never_reaches_the_ranking(self, api):
        """The 99-quality firm is conflicted out, leaving a pool of two.

        PRD: "A firm is eligible when its `panel_status` is `ACTIVE`, when the claim's `venue_code` appears in its `admitted_venue_codes`, when the claim's `allegation_category` appears in its `allegation_specialties`, when the claim's `insured_id` does not appear in its `conflict_insured_ids`, when its `open_assignment_count` is strictly below its `max_concurrent_assignments`, and when its identifier does not appear in the claim's `excluded_counsel_firm_ids`."

        Design: Corner/calculations/panel_selection_ranks_quality_first_then_rate_and_drops_the_conflicted_firm
        """
        panel = _three_firm_panel_with_a_conflict(api)

        assignment = fx.assign_counsel(api, panel["claim"]["id"])

        assert assignment["candidate_pool_size"] == 2
        assert assignment["counsel_firm_id"] != panel["gamma"]["id"]

    def test_the_cheaper_of_the_two_equal_quality_firms_is_selected(self, api):
        """At equal quality the 500.00 rate beats the 700.00 rate.

        PRD: "The survivors are ranked by `quality_score` descending, then by `blended_hourly_rate` ascending, then by creation timestamp ascending — never by identifier — and the first-ranked firm is selected, so `selection_rank_snapshot` on the resulting assignment is 1."

        Design: Corner/calculations/panel_selection_ranks_quality_first_then_rate_and_drops_the_conflicted_firm
        """
        panel = _three_firm_panel_with_a_conflict(api)

        assignment = fx.assign_counsel(api, panel["claim"]["id"])

        assert assignment["counsel_firm_id"] == panel["beta"]["id"]
        assert assignment["selection_rank_snapshot"] == 1

    def test_the_assignment_opens_and_takes_one_slot_of_capacity(self, api):
        """Only the selected firm's capacity counter moves.

        PRD: "A successful assignment records `claim_id` and the selected `counsel_firm_id`, opens in `ASSIGNED` status with `assigned_at` at the current logical timestamp, `billed_expense_amount` at 0.00 and `decline_reason` and `closed_at` null, increments the firm's `open_assignment_count` by 1, and sets the claim's `counsel_reassignment_required` back to false."

        Design: Corner/calculations/panel_selection_ranks_quality_first_then_rate_and_drops_the_conflicted_firm
        """
        panel = _three_firm_panel_with_a_conflict(api)

        assignment = fx.assign_counsel(api, panel["claim"]["id"])

        assert assignment["assignment_status"] == "ASSIGNED"
        assert_money(
            assignment["billed_expense_amount"], 0.00, "billed_expense_amount"
        )
        assert assignment["decline_reason"] is None
        assert assignment["closed_at"] is None
        assert validate_success(
            api.get_counsel_firm(panel["beta"]["id"], APPROVER)
        )["open_assignment_count"] == 1
        for spare in ("alpha", "gamma"):
            assert validate_success(
                api.get_counsel_firm(panel[spare]["id"], APPROVER)
            )["open_assignment_count"] == 0
        claim = validate_success(api.get_claim(panel["claim"]["id"], ADJ))
        assert claim["counsel_reassignment_required"] is False

"""Pinned readings and pinned formula order.

Four rules in this domain admit a second defensible reading, and the API pins one
of them for persistence and enforcement while reporting the other side by side:
the evaluation deadline anchor (PRD §3.3), the provider minute ledger (PRD §3.8),
the composite eligibility variant (PRD §3.6) and the order in which service
minutes are rounded (PRD §3.6). This file also covers the pinned order of the two
travel steps — tier first from the direct total, per-location charges second.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_composite_profile,
    assert_delay_figures,
    assert_fields_absent,
    assert_instant,
    assert_provider_minute_ledger,
)
from test_helpers.constants import ts
from test_helpers.test_users import make_parent_headers

# ---------------------------------------------------------------- local helpers
# Five STANDARDIZED results for a child of 36 completed months at the assessment
# windows: COMMUNICATION 33.3 percent and COGNITIVE 36.1 percent qualify, the
# other three fall below the 25.0 threshold.
_STANDARDIZED_AGE_EQUIVALENTS = {
    "COMMUNICATION": 24,
    "COGNITIVE": 23,
    "PHYSICAL_MOTOR": 30,
    "SOCIAL_EMOTIONAL": 33,
    "ADAPTIVE": 34,
}

# One identical set of five results spanning every method, for a child of 33
# completed months at the assessment windows.
_MIXED_METHODS = {
    "COMMUNICATION": "PLAY_BASED",
    "SOCIAL_EMOTIONAL": "PLAY_BASED",
    "COGNITIVE": "STANDARDIZED",
    "PHYSICAL_MOTOR": "OBSERVATION",
    "ADAPTIVE": "PARENT_REPORT",
}
_MIXED_AGE_EQUIVALENTS = {
    "COMMUNICATION": 22,
    "SOCIAL_EMOTIONAL": 23,
    "COGNITIVE": 26,
    "PHYSICAL_MOTOR": 30,
    "ADAPTIVE": 28,
}


def _standardized_case(api, age_equivalents=None):
    """A DOMAINS_COMPLETE case whose five results were all standardized."""
    child = fx.register_child_aged(api, 36)
    equivalents = dict(_STANDARDIZED_AGE_EQUIVALENTS)
    if age_equivalents:
        equivalents.update(age_equivalents)
    return fx.setup_case_with_five_completed_domains(
        api,
        child["id"],
        assessment_protocol="STANDARDIZED",
        method="STANDARDIZED",
        age_equivalents=equivalents,
    )


def _mixed_method_case(api, assessment_protocol):
    """The same five mixed-method results under the named protocol."""
    return fx.setup_case_with_five_completed_domains(
        api,
        assessment_protocol=assessment_protocol,
        methods=_MIXED_METHODS,
        age_equivalents=_MIXED_AGE_EQUIVALENTS,
    )


def _draft_community_plan(api, provider_max_minutes=400):
    """A DRAFT community-preschool plan plus an unstaffed SLP to buy minutes from."""
    site = fx.register_site(api)
    slp = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=provider_max_minutes
    )
    context = fx.setup_draft_plan(
        api, setting="COMMUNITY_PRESCHOOL", community_site_id=site["id"]
    )
    context["site"] = site
    context["slp"] = slp
    return context


# ------------------------------------- the evaluation deadline: two 60-day anchors
def test_part_c_timeline_reports_both_anchors_and_pins_the_capped_date(api):
    """Late consent on the Part C pathway pins the third-birthday cap.

    PRD §3.3: "The pinned rule — the consent-anchored reading — takes the calendar
    date of `consent_granted_at` and adds 60 calendar days, weekends and holidays
    included."
    PRD §3.3: "For a referral on the `PART_C_TRANSITION_DEADLINE` pathway only, the
    result is then capped: `evaluation_due_date` becomes the **earlier** of that
    consent-anchored date and the child's `third_birthday`, so that the child's IEP
    is in place by the third birthday even when consent arrived late."
    PRD §3.3: "Alongside it the system can compute, but never persists on the
    referral, the receipt-anchored reading: the calendar date of `received_at` plus
    the same 60 calendar days, with **no** third-birthday cap."
    PRD §3.3: "Both readings are laid out side by side on the referral's compliance
    view, a read-only endpoint that returns `referral_id`, the referral's
    `eligibility_pathway`, its `received_date` and `consent_granted_date` as plain
    calendar dates, the `receipt_anchored_due_date` and `consent_anchored_due_date`
    as computed above, the `third_birthday_cap_date` that the Part C pathway would
    apply, the pinned `evaluation_due_date` actually in force, the `days_remaining`
    until it, and the `timeline_compliance` posture of §3.5."

    Design: Difficulty/dual_variant_calc/referral_due_date_consent_anchored_vs_receipt_anchored
    """
    child = fx.register_part_c_child(api, 33)
    assert child["third_birthday"] == "2026-11-01"
    referral = fx.create_referral(api, child["id"], source="PART_C_TRANSITION")
    assert referral["eligibility_pathway"] == "PART_C_TRANSITION_DEADLINE"
    consent = fx.issue_evaluation_notice(api, referral["id"])

    # Consent arrives 50 days after receipt, so the two anchors diverge.
    fx.set_clock(api, ts("2026-09-20T00:00:00Z"))
    fx.decide_consent(api, consent["id"], "GRANTED", make_parent_headers(child["id"]))
    chair = fx.register_chair(api)
    case = fx.open_case(api, referral["id"], chair["id"])

    timeline = fx.read_timeline(api, referral["id"])
    assert timeline["referral_id"] == referral["id"]
    assert timeline["eligibility_pathway"] == "PART_C_TRANSITION_DEADLINE"
    assert timeline["received_date"] == "2026-08-01"
    assert timeline["consent_granted_date"] == "2026-09-20"
    # 2026-08-01 + 60 days, uncapped.
    assert timeline["receipt_anchored_due_date"] == "2026-09-30"
    # 2026-09-20 + 60 days, uncapped.
    assert timeline["consent_anchored_due_date"] == "2026-11-19"
    assert timeline["third_birthday_cap_date"] == "2026-11-01"
    # The earlier of the consent-anchored date and the third birthday.
    assert timeline["evaluation_due_date"] == "2026-11-01"
    assert timeline["days_remaining"] == 42
    assert timeline["timeline_compliance"] == "ON_TIME"

    # The pinned reading, and only the pinned reading, is persisted.
    stored = fx.read_referral(api, referral["id"])
    assert stored["evaluation_due_date"] == "2026-11-01"
    assert fx.read_case(api, case["id"])["due_date"] == "2026-11-01"


def test_standard_pathway_due_date_stands_uncapped_beside_the_receipt_anchor(api):
    """The same late consent on the standard pathway ignores the third birthday.

    PRD §3.3: "For a referral on the `STANDARD_60_DAY` pathway the consent-anchored
    date stands uncapped."
    PRD §3.3: "Alongside it the system can compute, but never persists on the
    referral, the receipt-anchored reading: the calendar date of `received_at` plus
    the same 60 calendar days, with **no** third-birthday cap."

    Design: Difficulty/dual_variant_calc/referral_due_date_consent_anchored_vs_receipt_anchored
    """
    child = fx.register_child(api)
    assert child["third_birthday"] == "2026-11-01"
    referral = fx.create_referral(api, child["id"])
    assert referral["eligibility_pathway"] == "STANDARD_60_DAY"
    consent = fx.issue_evaluation_notice(api, referral["id"])

    fx.set_clock(api, ts("2026-09-20T00:00:00Z"))
    fx.decide_consent(api, consent["id"], "GRANTED")

    timeline = fx.read_timeline(api, referral["id"])
    assert timeline["receipt_anchored_due_date"] == "2026-09-30"
    assert timeline["consent_anchored_due_date"] == "2026-11-19"
    # No cap on this pathway, even though the child turns three on 2026-11-01.
    assert timeline["evaluation_due_date"] == "2026-11-19"
    assert timeline["days_remaining"] == 60
    assert fx.read_referral(api, referral["id"])["evaluation_due_date"] == "2026-11-19"


def test_evaluation_due_date_is_absent_until_consent_is_granted(api):
    """Neither reading is persisted before the grant that anchors the pinned one.

    PRD §3.3: "`consent_granted_at` records the logical-clock instant of the grant,
    and `evaluation_due_date` is computed from it and then persisted; until consent
    is granted, `evaluation_due_date` is absent, and a referral without a granted
    consent is excluded from every compliance aggregate."

    Design: Difficulty/dual_variant_calc/referral_due_date_consent_anchored_vs_receipt_anchored
    """
    referral = fx.create_referral(api)
    assert_fields_absent(referral, "evaluation_due_date", "consent_granted_at")

    consent = fx.issue_evaluation_notice(api, referral["id"])
    assert_fields_absent(
        fx.read_referral(api, referral["id"]), "evaluation_due_date", "consent_granted_at"
    )

    fx.set_clock(api, ts("2026-08-11T00:00:00Z"))
    fx.decide_consent(api, consent["id"], "GRANTED")

    granted = fx.read_referral(api, referral["id"])
    assert granted["intake_status"] == "EVALUATION_AUTHORIZED"
    assert granted["consent_status"] == "GRANTED"
    assert_instant(granted["consent_granted_at"], ts("2026-08-11T00:00:00Z"))
    # 2026-08-11 + 60 calendar days, not 2026-08-01 + 60.
    assert granted["evaluation_due_date"] == "2026-10-10"


# ------------------------- provider minutes: projected reading vs committed reading
def test_draft_plan_minutes_are_projected_immediately_but_committed_stays_zero(api):
    """A staffed line on a DRAFT plan loads the projected ledger only.

    PRD §3.8: "A provider's `direct_weekly_service_minutes` is the sum of
    `weekly_minutes` over every line that names that provider, stands at `STAFFED`,
    and belongs to a plan whose status is `DRAFT`, `PENDING_PARENT_CONSENT` or
    `ACTIVE`."
    PRD §3.8: "It returns `provider_id`, `direct_weekly_service_minutes`, the
    `distinct_site_count` behind the travel calculation, the `travel_tier_pct`
    actually selected, `travel_overhead_minutes`, the pinned
    `assigned_weekly_service_minutes`, and `committed_weekly_minutes` — the same
    computation performed with `DRAFT` plans **excluded**, so that only
    parent-facing commitments count, which yields a lower direct total, possibly a
    lower travel tier, and a lower assigned total than the pinned figure whenever a
    provider is staffed onto draft plans."
    PRD §3.8: "Only the projected reading, which holds minutes from the moment a
    line is staffed and before parental consent has even been requested, is ever
    compared against `max_weekly_service_minutes`."

    Design: Difficulty/dual_variant_calc/provider_minutes_projected_vs_committed_plan_states
    """
    site = fx.register_site(api)
    slp = fx.register_provider(api, discipline="SLP", max_weekly_service_minutes=400)
    context = fx.setup_staffed_draft_plan(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
        provider=slp,
    )
    assert context["plan"]["status"] == "DRAFT"
    assert context["line"]["status"] == "STAFFED"

    caseload = fx.read_caseload(api, slp["id"])
    assert caseload["provider_id"] == slp["id"]
    assert caseload["direct_weekly_service_minutes"] == 150
    assert caseload["distinct_site_count"] == 1
    # 150 x 5 percent is 7.5, with no location charge, rounded up once to 10.
    assert caseload["travel_overhead_minutes"] == 10
    assert caseload["assigned_weekly_service_minutes"] == 160
    # The only plan holding these minutes is still a draft.
    assert caseload["committed_weekly_minutes"] == 0
    assert caseload["max_weekly_service_minutes"] == 400
    assert caseload["utilization"] == pytest.approx(0.4)
    assert caseload["service_capacity_posture"] == "OPEN"

    # The projected reading is the one carried on the provider row itself.
    assert_provider_minute_ledger(context["line_provider"], 150, 10, 160, "OPEN")


def test_committed_minutes_catch_up_when_the_plan_leaves_draft(api):
    """Submitting the plan for parental consent is what commits the minutes.

    PRD §3.8: "It returns `provider_id`, `direct_weekly_service_minutes`, the
    `distinct_site_count` behind the travel calculation, the `travel_tier_pct`
    actually selected, `travel_overhead_minutes`, the pinned
    `assigned_weekly_service_minutes`, and `committed_weekly_minutes` — the same
    computation performed with `DRAFT` plans **excluded**, so that only
    parent-facing commitments count, which yields a lower direct total, possibly a
    lower travel tier, and a lower assigned total than the pinned figure whenever a
    provider is staffed onto draft plans."
    PRD §3.9: "The plan moves `DRAFT → PENDING_PARENT_CONSENT`, the named
    interpreter's `assigned_interpreter_assignment_count` is recomputed, and the
    plan's `version` increments."

    Design: Difficulty/dual_variant_calc/provider_minutes_projected_vs_committed_plan_states
    """
    site = fx.register_site(api)
    slp = fx.register_provider(api, discipline="SLP", max_weekly_service_minutes=400)
    context = fx.setup_staffed_draft_plan(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
        provider=slp,
    )
    assert fx.read_caseload(api, slp["id"])["committed_weekly_minutes"] == 0

    fx.submit_plan(api, context["plan"]["id"])
    assert fx.read_plan(api, context["plan"]["id"])["status"] == "PENDING_PARENT_CONSENT"

    caseload = fx.read_caseload(api, slp["id"])
    assert caseload["direct_weekly_service_minutes"] == 150
    assert caseload["assigned_weekly_service_minutes"] == 160
    # The same computation, now that no DRAFT plan has to be excluded from it.
    assert caseload["committed_weekly_minutes"] == 160


# ------------------- composite eligibility: strict standardized vs play-based
def test_eligibility_view_reports_both_weighting_variants_side_by_side(api):
    """One set of five results, two weightings, two opposite recommendations.

    PRD §3.6: "Under the strict standardized variant, only assessments whose
    `method` is `STANDARDIZED` count at all, and they count at full weight;
    `PLAY_BASED`, `OBSERVATION` and `PARENT_REPORT` results are excluded outright."
    PRD §3.6: "Under the inclusive play-based variant, `STANDARDIZED` counts at full
    weight, `PLAY_BASED` and `OBSERVATION` each count at a nine-tenths confidence
    discount, and `PARENT_REPORT` is still excluded."
    PRD §3.6: "A case pins the strict variant when its `assessment_protocol` is
    `STANDARDIZED` and the inclusive variant when its `assessment_protocol` is
    `PLAY_BASED`."
    PRD §3.6: "Otherwise, if `max_weighted_percent_delay` is present and has reached
    33.0 percent — a single domain severe enough to stand on its own — **or**
    `qualifying_domain_count` has reached 2 — two or more domains each at or above
    the 25.0 threshold — the recommendation is `ELIGIBLE_RECOMMENDED`."

    Design: Difficulty/dual_variant_calc/eligibility_composite_play_based_inclusive_vs_standardized_strict
    """
    context = _mixed_method_case(api, "PLAY_BASED")
    case_id = context["case"]["id"]

    profile = fx.read_eligibility_profile(api, case_id)
    assert profile["evaluation_case_id"] == case_id
    assert profile["completed_domain_count"] == 5
    # Strict: only the standardized cognitive result counts, at full weight.
    assert profile["standardized_strict_qualifying_domain_count"] == 0
    assert profile["standardized_strict_max_weighted_percent_delay"] == 21.2
    assert profile["standardized_strict_recommendation"] == "NOT_ELIGIBLE_RECOMMENDED"
    # Inclusive: the two play-based results survive the nine-tenths discount.
    assert profile["play_based_inclusive_qualifying_domain_count"] == 2
    assert profile["play_based_inclusive_max_weighted_percent_delay"] == 30.0
    assert profile["play_based_inclusive_recommendation"] == "ELIGIBLE_RECOMMENDED"
    # The protocol pinned the inclusive reading.
    assert profile["composite_eligibility_recommendation"] == "ELIGIBLE_RECOMMENDED"
    assert profile["recommended_weekly_minutes"] == 100


def test_pinned_inclusive_variant_discounts_each_row_and_drops_parent_report(api):
    """The pinned variant decides what each assessment row itself is worth.

    PRD §3.6: "Otherwise the order of operations is pinned and matters: the
    already-rounded one-decimal `percent_delay` is multiplied by the method weight,
    and the product is rounded half up to one decimal place again."
    PRD §3.6: "When the pinned variant excludes an assessment's method, that
    assessment's `weighted_percent_delay` is left absent and its `qualifies_delay`
    is false."
    PRD §3.6: "Under the inclusive play-based variant, `STANDARDIZED` counts at full
    weight, `PLAY_BASED` and `OBSERVATION` each count at a nine-tenths confidence
    discount, and `PARENT_REPORT` is still excluded."

    Design: Difficulty/dual_variant_calc/eligibility_composite_play_based_inclusive_vs_standardized_strict
    """
    context = _mixed_method_case(api, "PLAY_BASED")
    rows = {
        domain: fx.read_assessment(api, assessment["id"])
        for domain, assessment in context["assessments"].items()
    }

    # 33.3 x 0.9 = 29.97, rounded half up to 30.0.
    assert_delay_figures(rows["COMMUNICATION"], 33.3, 30.0, True)
    # 30.3 x 0.9 = 27.27, rounded half up to 27.3.
    assert_delay_figures(rows["SOCIAL_EMOTIONAL"], 30.3, 27.3, True)
    # Standardized results are never discounted.
    assert_delay_figures(rows["COGNITIVE"], 21.2, 21.2, False)
    # 9.1 x 0.9 = 8.19, rounded half up to 8.2.
    assert_delay_figures(rows["PHYSICAL_MOTOR"], 9.1, 8.2, False)
    # Parent report is excluded under both variants.
    assert rows["ADAPTIVE"]["percent_delay"] == 15.2
    assert rows["ADAPTIVE"]["qualifies_delay"] is False
    assert_fields_absent(rows["ADAPTIVE"], "weighted_percent_delay")

    case = fx.read_case(api, context["case"]["id"])
    assert_composite_profile(case, 5, 2, 30.0, "ELIGIBLE_RECOMMENDED", 100)


def test_strict_protocol_pins_the_other_reading_on_the_very_same_results(api):
    """Switching only the protocol flips the persisted recommendation.

    PRD §3.6: "Under the strict standardized variant, only assessments whose
    `method` is `STANDARDIZED` count at all, and they count at full weight;
    `PLAY_BASED`, `OBSERVATION` and `PARENT_REPORT` results are excluded outright."
    PRD §3.6: "A case pins the strict variant when its `assessment_protocol` is
    `STANDARDIZED` and the inclusive variant when its `assessment_protocol` is
    `PLAY_BASED`."
    PRD §3.6: "When no domain qualifies, the recommendation is 0."

    Design: Difficulty/dual_variant_calc/eligibility_composite_play_based_inclusive_vs_standardized_strict
    """
    context = _mixed_method_case(api, "STANDARDIZED")
    rows = {
        domain: fx.read_assessment(api, assessment["id"])
        for domain, assessment in context["assessments"].items()
    }
    assert_delay_figures(rows["COGNITIVE"], 21.2, 21.2, False)
    for domain in ("COMMUNICATION", "SOCIAL_EMOTIONAL", "PHYSICAL_MOTOR", "ADAPTIVE"):
        assert rows[domain]["qualifies_delay"] is False
        assert_fields_absent(rows[domain], "weighted_percent_delay")
    # The percentages themselves are still recorded; only the weighting excludes them.
    assert rows["COMMUNICATION"]["percent_delay"] == 33.3
    assert rows["SOCIAL_EMOTIONAL"]["percent_delay"] == 30.3

    case = fx.read_case(api, context["case"]["id"])
    assert_composite_profile(case, 5, 0, 21.2, "NOT_ELIGIBLE_RECOMMENDED", 0)

    profile = fx.read_eligibility_profile(api, context["case"]["id"])
    assert profile["standardized_strict_qualifying_domain_count"] == 0
    assert profile["standardized_strict_recommendation"] == "NOT_ELIGIBLE_RECOMMENDED"
    # The discarded reading is still reported, and still says the opposite.
    assert profile["play_based_inclusive_qualifying_domain_count"] == 2
    assert profile["play_based_inclusive_max_weighted_percent_delay"] == 30.0
    assert profile["play_based_inclusive_recommendation"] == "ELIGIBLE_RECOMMENDED"
    assert profile["composite_eligibility_recommendation"] == "NOT_ELIGIBLE_RECOMMENDED"
    assert profile["recommended_weekly_minutes"] == 0


# ------------------- service minutes: round each domain first, then add them up
def test_two_qualifying_domains_round_per_domain_before_summing(api):
    """The PRD's own worked example: 120 minutes is pinned, 115 is reported.

    PRD §3.6: "A base allocation of 50 minutes per qualifying domain is multiplied by
    that domain's multiplier in exact decimal, and the product is rounded **up to the
    next multiple of five for that domain alone**. Only then are the rounded
    per-domain figures added together to give `recommended_weekly_minutes`."
    PRD §3.6: "Two qualifying domains at 33.3 percent and 36.1 percent, for instance,
    both take the 1.15 multiplier and so both produce a raw allocation of 57.5
    minutes: rounding each up to 60 and then adding gives 120 minutes, whereas adding
    first to 115.0 and rounding once gives 115. The pinned answer is 120."

    Design: Difficulty/combinatorial_formula/service_minutes_ceil_per_line_then_sum_not_sum_then_ceil
    """
    context = _standardized_case(api)
    rows = {
        domain: fx.read_assessment(api, assessment["id"])
        for domain, assessment in context["assessments"].items()
    }
    assert_delay_figures(rows["COMMUNICATION"], 33.3, 33.3, True)
    assert_delay_figures(rows["COGNITIVE"], 36.1, 36.1, True)
    assert rows["PHYSICAL_MOTOR"]["qualifies_delay"] is False
    assert rows["SOCIAL_EMOTIONAL"]["qualifies_delay"] is False
    assert rows["ADAPTIVE"]["qualifies_delay"] is False

    case = fx.read_case(api, context["case"]["id"])
    assert_composite_profile(case, 5, 2, 36.1, "ELIGIBLE_RECOMMENDED", 120)

    profile = fx.read_eligibility_profile(api, context["case"]["id"])
    assert profile["per_line_rounded_minutes"] == 120
    assert profile["sum_then_rounded_minutes"] == 115
    assert profile["recommended_weekly_minutes"] == 120


def test_three_qualifying_domains_accumulate_three_separate_roundings(api):
    """Three domains at 57.5 raw minutes give 180 pinned against 175 discarded.

    PRD §3.6: "That rounding order is pinned and is not interchangeable with the
    alternative of summing the raw per-domain figures and rounding once at the end;
    the alternative yields a smaller total whenever the accumulated per-domain slack
    reaches five minutes."
    PRD §3.6: "Each domain's representative percentage selects a severity multiplier:
    a percentage that has reached 50.0 takes a multiplier of 1.4; one that has not
    reached 50.0 but has reached 33.0 takes 1.15; anything below 33.0 takes 1.0."

    Design: Difficulty/combinatorial_formula/service_minutes_ceil_per_line_then_sum_not_sum_then_ceil
    """
    context = _standardized_case(api, age_equivalents={"PHYSICAL_MOTOR": 22})
    rows = {
        domain: fx.read_assessment(api, assessment["id"])
        for domain, assessment in context["assessments"].items()
    }
    assert_delay_figures(rows["PHYSICAL_MOTOR"], 38.9, 38.9, True)

    case = fx.read_case(api, context["case"]["id"])
    # Three domains in the 1.15 band: 60 + 60 + 60, not ceil5(172.5) = 175.
    assert_composite_profile(case, 5, 3, 38.9, "ELIGIBLE_RECOMMENDED", 180)

    profile = fx.read_eligibility_profile(api, context["case"]["id"])
    assert profile["per_line_rounded_minutes"] == 180
    assert profile["sum_then_rounded_minutes"] == 175


def test_both_rounding_orders_agree_when_no_domain_leaves_slack(api):
    """With raw allocations already on a multiple of five the two orders coincide.

    PRD §3.6: "That rounding order is pinned and is not interchangeable with the
    alternative of summing the raw per-domain figures and rounding once at the end;
    the alternative yields a smaller total whenever the accumulated per-domain slack
    reaches five minutes."
    PRD §3.6: "Both band boundaries are inclusive lower bounds, so exactly 33.0 takes
    1.15 while 32.9 takes 1.0, and exactly 50.0 takes 1.4."

    Design: Difficulty/combinatorial_formula/service_minutes_ceil_per_line_then_sum_not_sum_then_ceil
    """
    context = _standardized_case(
        api, age_equivalents={"COMMUNICATION": 17, "COGNITIVE": 17}
    )
    rows = {
        domain: fx.read_assessment(api, assessment["id"])
        for domain, assessment in context["assessments"].items()
    }
    assert_delay_figures(rows["COMMUNICATION"], 52.8, 52.8, True)
    assert_delay_figures(rows["COGNITIVE"], 52.8, 52.8, True)

    case = fx.read_case(api, context["case"]["id"])
    # 50 x 1.4 is exactly 70 for each domain, so no slack accumulates.
    assert_composite_profile(case, 5, 2, 52.8, "ELIGIBLE_RECOMMENDED", 140)

    profile = fx.read_eligibility_profile(api, context["case"]["id"])
    assert profile["per_line_rounded_minutes"] == 140
    assert profile["sum_then_rounded_minutes"] == 140


# ---------------- travel overhead: tier from the direct total, then the locations
def test_travel_tier_is_chosen_from_the_direct_total_before_overhead_exists(api):
    """290 direct minutes draw the 5 percent tier, and 305 assigned never re-draws it.

    PRD §3.8: "First, the travel percentage is chosen from the direct total **alone**,
    before any travel minutes exist: a direct total of 300 minutes or fewer draws 5
    percent, a total above 300 but not above 600 draws 10 percent, and a total above
    600 draws 15 percent."
    PRD §3.8: "The tier is never re-chosen after the travel minutes have been added: a
    provider with 290 direct minutes across two distinct locations draws the 5 percent
    tier from 290, giving 14.5 plus 15, which is 29.5, rounded up to 30, for an
    assigned total of 320 — and not the 335 that would follow from re-reading the tier
    against 320."
    PRD §3.8: "Finally `assigned_weekly_service_minutes` is the direct total plus the
    travel overhead."

    Design: Difficulty/combinatorial_formula/travel_tier_selected_from_direct_minutes_before_overhead_is_added
    """
    context = fx.setup_draft_plan(api)
    slp = fx.register_provider(api, discipline="SLP", max_weekly_service_minutes=400)
    first = fx.add_line(api, context["plan"]["id"], discipline="SLP", weekly_minutes=150)
    second = fx.add_line(api, context["plan"]["id"], discipline="SLP", weekly_minutes=140)
    fx.staff_line(api, first["id"], slp["id"])
    fx.staff_line(api, second["id"], slp["id"])

    caseload = fx.read_caseload(api, slp["id"])
    assert caseload["direct_weekly_service_minutes"] == 290
    # Both lines default to the district centre, so there is one location.
    assert caseload["distinct_site_count"] == 1
    # 290 x 5 percent is 14.5, rounded up once to 15 - not 10 percent of 290.
    assert caseload["travel_overhead_minutes"] == 15
    assert caseload["assigned_weekly_service_minutes"] == 305
    assert caseload["utilization"] == pytest.approx(0.7625)
    assert caseload["service_capacity_posture"] == "OPEN"
    assert_provider_minute_ledger(fx.read_provider(api, slp["id"]), 290, 15, 305, "OPEN")


def test_direct_total_of_exactly_300_stays_in_the_five_percent_tier(api):
    """The inclusive top of the first tier is read off the direct total only.

    PRD §3.8: "First, the travel percentage is chosen from the direct total **alone**,
    before any travel minutes exist: a direct total of 300 minutes or fewer draws 5
    percent, a total above 300 but not above 600 draws 10 percent, and a total above
    600 draws 15 percent."
    PRD §3.8: "The tier is never re-chosen after the travel minutes have been added: a
    provider with 290 direct minutes across two distinct locations draws the 5 percent
    tier from 290, giving 14.5 plus 15, which is 29.5, rounded up to 30, for an
    assigned total of 320 — and not the 335 that would follow from re-reading the tier
    against 320."

    Design: Difficulty/combinatorial_formula/travel_tier_selected_from_direct_minutes_before_overhead_is_added
    """
    context = fx.setup_draft_plan(api)
    slp = fx.register_provider(api, discipline="SLP", max_weekly_service_minutes=400)
    for minutes in (150, 150):
        line = fx.add_line(
            api, context["plan"]["id"], discipline="SLP", weekly_minutes=minutes
        )
        fx.staff_line(api, line["id"], slp["id"])

    caseload = fx.read_caseload(api, slp["id"])
    assert caseload["direct_weekly_service_minutes"] == 300
    # 300 x 5 percent is exactly 15; the assigned 315 does not promote the tier.
    assert caseload["travel_overhead_minutes"] == 15
    assert caseload["assigned_weekly_service_minutes"] == 315
    assert caseload["service_capacity_posture"] == "OPEN"


def test_direct_total_just_above_300_draws_the_ten_percent_tier(api):
    """The tier moves with the direct total, and only with the direct total.

    PRD §3.8: "First, the travel percentage is chosen from the direct total **alone**,
    before any travel minutes exist: a direct total of 300 minutes or fewer draws 5
    percent, a total above 300 but not above 600 draws 10 percent, and a total above
    600 draws 15 percent."
    PRD §3.8: "`travel_overhead_minutes` is then the direct total multiplied by the
    chosen percentage, plus 15 minutes for each location beyond the first, with that
    **whole** expression rounded up once to the next multiple of five — the percentage
    part and the per-location part are never rounded separately."

    Design: Difficulty/combinatorial_formula/travel_tier_selected_from_direct_minutes_before_overhead_is_added
    """
    context = fx.setup_draft_plan(api)
    slp = fx.register_provider(api, discipline="SLP", max_weekly_service_minutes=400)
    for minutes in (150, 155):
        line = fx.add_line(
            api, context["plan"]["id"], discipline="SLP", weekly_minutes=minutes
        )
        fx.staff_line(api, line["id"], slp["id"])

    caseload = fx.read_caseload(api, slp["id"])
    assert caseload["direct_weekly_service_minutes"] == 305
    assert caseload["distinct_site_count"] == 1
    # 305 x 10 percent is 30.5, rounded up once to 35.
    assert caseload["travel_overhead_minutes"] == 35
    assert caseload["assigned_weekly_service_minutes"] == 340
    assert caseload["utilization"] == pytest.approx(0.85)
    assert caseload["service_capacity_posture"] == "NEAR_CAPACITY"


def test_only_locations_beyond_the_first_are_charged_fifteen_minutes(api):
    """Two locations behind 290 direct minutes cost one 15-minute charge, not two.

    PRD §3.8: "Second, the number of distinct delivery locations is counted across the
    same in-scope set of staffed lines, where an absent `delivery_site_id` normalises
    to a single sentinel district-centre location so that every district-delivered
    line collapses into one place; `CONSULT` and `PUSH_IN` lines **do** participate in
    this count even though they were excluded from the direct total, because they too
    require the provider to travel."
    PRD §3.8: "One location is free; each location beyond the first adds 15 minutes."
    PRD §3.8: "The tier is never re-chosen after the travel minutes have been added: a
    provider with 290 direct minutes across two distinct locations draws the 5 percent
    tier from 290, giving 14.5 plus 15, which is 29.5, rounded up to 30, for an
    assigned total of 320 — and not the 335 that would follow from re-reading the tier
    against 320."
    PRD §3.8: "The ratio is compared as an exact decimal and never pre-rounded, so a
    provider at 320 assigned minutes against a 400-minute ceiling sits exactly on
    eight tenths and is `NEAR_CAPACITY`."

    Design: Difficulty/combinatorial_formula/travel_overhead_charges_only_the_extra_sites_beyond_the_first
    """
    context = _draft_community_plan(api)
    partner_site = fx.register_site(api)
    slp = context["slp"]

    first = fx.add_line(api, context["plan"]["id"], discipline="SLP", weekly_minutes=150)
    second = fx.add_line(api, context["plan"]["id"], discipline="SLP", weekly_minutes=140)
    # The first line stays at the site holding the IEP seat.
    fx.staff_line(api, first["id"], slp["id"])
    # The second is delivered at a partner site, which is the only extra location.
    fx.staff_line(
        api, second["id"], slp["id"], delivery_site_id=partner_site["id"]
    )

    caseload = fx.read_caseload(api, slp["id"])
    assert caseload["direct_weekly_service_minutes"] == 290
    assert caseload["distinct_site_count"] == 2
    # 14.5 plus a single 15-minute charge is 29.5, rounded up once to 30.
    assert caseload["travel_overhead_minutes"] == 30
    assert caseload["assigned_weekly_service_minutes"] == 320
    assert caseload["max_weekly_service_minutes"] == 400
    assert caseload["utilization"] == pytest.approx(0.8)
    assert caseload["service_capacity_posture"] == "NEAR_CAPACITY"
    assert_provider_minute_ledger(
        fx.read_provider(api, slp["id"]), 290, 30, 320, "NEAR_CAPACITY"
    )


def test_a_consult_location_is_counted_even_though_its_minutes_are_not(api):
    """A third location adds a second 15-minute charge without adding direct minutes.

    PRD §3.8: "Second, the number of distinct delivery locations is counted across the
    same in-scope set of staffed lines, where an absent `delivery_site_id` normalises
    to a single sentinel district-centre location so that every district-delivered
    line collapses into one place; `CONSULT` and `PUSH_IN` lines **do** participate in
    this count even though they were excluded from the direct total, because they too
    require the provider to travel."
    PRD §3.8: "One location is free; each location beyond the first adds 15 minutes."
    PRD §3.8: "`travel_overhead_minutes` is then the direct total multiplied by the
    chosen percentage, plus 15 minutes for each location beyond the first, with that
    **whole** expression rounded up once to the next multiple of five — the percentage
    part and the per-location part are never rounded separately."

    Design: Difficulty/combinatorial_formula/travel_overhead_charges_only_the_extra_sites_beyond_the_first
    """
    context = _draft_community_plan(api)
    partner_site = fx.register_site(api)
    consult_site = fx.register_site(api)
    slp = context["slp"]

    first = fx.add_line(api, context["plan"]["id"], discipline="SLP", weekly_minutes=150)
    second = fx.add_line(api, context["plan"]["id"], discipline="SLP", weekly_minutes=140)
    third = fx.add_line(
        api,
        context["plan"]["id"],
        discipline="SLP",
        weekly_minutes=100,
        delivery_model="CONSULT",
    )
    fx.staff_line(api, first["id"], slp["id"])
    fx.staff_line(api, second["id"], slp["id"], delivery_site_id=partner_site["id"])
    fx.staff_line(api, third["id"], slp["id"], delivery_site_id=consult_site["id"])

    caseload = fx.read_caseload(api, slp["id"])
    # The consult minutes never enter the direct total.
    assert caseload["direct_weekly_service_minutes"] == 290
    assert caseload["distinct_site_count"] == 3
    # 14.5 plus two 15-minute charges is 44.5, rounded up once to 45.
    assert caseload["travel_overhead_minutes"] == 45
    assert caseload["assigned_weekly_service_minutes"] == 335
    assert caseload["service_capacity_posture"] == "NEAR_CAPACITY"

    # All three lines are still commitments of the plan.
    assert fx.read_plan(api, context["plan"]["id"])["assigned_weekly_minutes"] == 390

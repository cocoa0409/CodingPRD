"""Exact boundaries: the values one step either side of a threshold.

Four thresholds are pinned here at the precision the PRD states them. The
statutory age window is inclusive at 33 completed months and excludes 32. An
empty entering-assessment set leaves ``max_weighted_percent_delay`` absent rather
than 0.0 and makes a later determination refusable. A ``weighted_percent_delay``
of exactly 25.0 qualifies, whether it arrives directly or by rounding half up onto
the threshold, while 20.0 does not. And a staffing request landing exactly on
``max_weekly_service_minutes`` is accepted while the next one is refused.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_composite_profile,
    assert_delay_figures,
    assert_page_meta,
    assert_provider_minute_ledger,
)
from test_helpers.constants import (  # noqa: E402
    expected_assigned_minutes,
    expected_percent_delay,
    expected_travel_overhead,
    expected_weighted_delay,
    PLAY_BASED_CONFIDENCE_WEIGHT,
)
from test_helpers.test_users import TEST_USERS, make_chair_headers  # noqa: E402

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]


# -------------------------------------- statutory age window (PRD §3.3)
def test_a_child_of_exactly_thirty_three_months_is_in_scope(api):
    """The lower bound of the preschool span is inclusive.

    PRD §3.3 spans 33 through 71 completed months with both bounds inclusive, so
    "a child of exactly 33 months is in scope"; being inside the span and not an
    early-intervention child, the referral takes the STANDARD_60_DAY pathway.

    Design: Difficulty/boundary_precision_check/referral_age_boundary_thirty_three_months_accepted_thirty_two_rejected
    """
    child = fx.register_child_aged(api, 33)

    response = api.create_referral(f.referral_payload(child["id"]), COORDINATOR)

    referral = validate_success(response, 201)
    assert referral["age_months_at_referral"] == 33
    assert referral["eligibility_pathway"] == "STANDARD_60_DAY"
    assert referral["intake_status"] == "RECEIVED"
    assert referral["consent_status"] == "NOT_REQUESTED"
    assert fx.read_child(api, child["id"])["status"] == "REFERRED"


def test_a_child_of_exactly_thirty_two_months_is_refused_with_no_row_written(api):
    """One month below the bound the manual intake is refused outright.

    PRD §3.3 puts a child of 32 completed months outside the span, and a
    coordinator's manual intake whose computed pathway is AGE_INELIGIBLE "is
    refused with ERR_AGE_INELIGIBLE and no referral row is written at all", so the
    child stays at NO_ACTIVE_REFERRAL.

    Design: Difficulty/boundary_precision_check/referral_age_boundary_thirty_three_months_accepted_thirty_two_rejected
    """
    child = fx.register_child_aged(api, 32)

    response = api.create_referral(f.referral_payload(child["id"]), COORDINATOR)

    validate_error(response, ApiErrorId.ERR_AGE_INELIGIBLE.value)
    rows, meta = fx.listing(api, "list_referrals", COORDINATOR, child_id=child["id"])
    assert rows == []
    assert_page_meta(meta, expected_total=0)
    assert fx.read_child(api, child["id"])["status"] == "NO_ACTIVE_REFERRAL"


def test_the_upper_age_bound_admits_seventy_one_months_and_excludes_seventy_two(api):
    """The upper bound is inclusive on the same terms as the lower one.

    PRD §3.3: "a child of exactly 71 months is in scope while one of 72 is not".

    Design: Difficulty/boundary_precision_check/referral_age_boundary_thirty_three_months_accepted_thirty_two_rejected
    """
    oldest_in_scope = fx.register_child_aged(api, 71)
    referral = validate_success(
        api.create_referral(f.referral_payload(oldest_in_scope["id"]), COORDINATOR), 201
    )
    assert referral["age_months_at_referral"] == 71
    assert referral["eligibility_pathway"] == "STANDARD_60_DAY"

    just_out_of_scope = fx.register_child_aged(api, 72)
    refused = api.create_referral(
        f.referral_payload(just_out_of_scope["id"]), COORDINATOR
    )
    validate_error(refused, ApiErrorId.ERR_AGE_INELIGIBLE.value)
    rows, _ = fx.listing(
        api, "list_referrals", COORDINATOR, child_id=just_out_of_scope["id"]
    )
    assert rows == []


# ------------------------- an empty entering-assessment set (PRD §3.5 / §3.6)
def _drafted_case_with_every_assessment_invalidated(api):
    """A case at REPORT_DRAFTED whose five completed assessments were all invalidated.

    PRD §3.5 leaves the status untouched when the invalidation happens at
    REPORT_DRAFTED, which is what makes the entering set empty while the case is
    still eligible to be determined.
    """
    context = fx.setup_case_with_five_completed_domains(
        api, assessment_protocol="STANDARDIZED", method="STANDARDIZED"
    )
    fx.draft_report(api, context["case"]["id"], context["chair"]["id"])
    for domain, assessment in context["assessments"].items():
        fx.invalidate_assessment(
            api, assessment["id"], context["evaluators"][domain]["id"]
        )
    context["case"] = fx.read_case(api, context["case"]["id"])
    return context


def test_an_empty_entering_set_leaves_the_maximum_absent_rather_than_zero(api):
    """With nothing entering, the maximum is absent and never 0.0.

    PRD §3.6 defines ``max_weighted_percent_delay`` as the largest
    ``weighted_percent_delay`` among the entering assessments — "absent, never 0.0,
    when nothing enters" — and PRD §3.5 keeps the historical figures on each
    invalidated row while removing that row from every case aggregate.

    Design: Difficulty/boundary_precision_check/empty_completed_assessment_set_yields_null_max_and_domains_incomplete
    """
    context = _drafted_case_with_every_assessment_invalidated(api)
    case = context["case"]

    assert case["status"] == "REPORT_DRAFTED"
    assert case["max_weighted_percent_delay"] is None
    assert_composite_profile(case, 0, 0, None, "INDETERMINATE", 0)

    # The rows themselves keep what they measured; only the aggregate is empty.
    for assessment in fx.assessments_for_case(api, case["id"]):
        assert assessment["status"] == "INVALIDATED"
        assert_delay_figures(assessment, 33.3, 33.3, True)


def test_the_eligibility_view_reports_both_rounding_orders_as_zero_when_nothing_enters(api):
    """Every variant of the audit view collapses to the empty reading.

    PRD §3.6 makes the recommendation INDETERMINATE whenever
    ``completed_domain_count`` is below five, gives a recommendation of 0 minutes
    when no domain qualifies, and reports both the pinned ``per_line_rounded_minutes``
    and the discarded ``sum_then_rounded_minutes`` side by side.

    Design: Difficulty/boundary_precision_check/empty_completed_assessment_set_yields_null_max_and_domains_incomplete
    """
    context = _drafted_case_with_every_assessment_invalidated(api)

    profile = fx.read_eligibility_profile(api, context["case"]["id"])

    assert profile["evaluation_case_id"] == context["case"]["id"]
    assert profile["completed_domain_count"] == 0
    assert profile["standardized_strict_qualifying_domain_count"] == 0
    assert profile["standardized_strict_max_weighted_percent_delay"] is None
    assert profile["standardized_strict_recommendation"] == "INDETERMINATE"
    assert profile["play_based_inclusive_qualifying_domain_count"] == 0
    assert profile["play_based_inclusive_max_weighted_percent_delay"] is None
    assert profile["play_based_inclusive_recommendation"] == "INDETERMINATE"
    assert profile["composite_eligibility_recommendation"] == "INDETERMINATE"
    assert profile["recommended_weekly_minutes"] == 0
    assert profile["per_line_rounded_minutes"] == 0
    assert profile["sum_then_rounded_minutes"] == 0


def test_determination_on_an_empty_entering_set_is_refused_as_domains_incomplete(api):
    """The determination independently re-checks that all five domains stand COMPLETED.

    PRD §3.7 requires all five domains still to stand COMPLETED and refuses with
    ERR_DOMAINS_INCOMPLETE otherwise, "which is the refusal a mid-flight
    invalidation of a completed assessment produces"; no plan is created.

    Design: Difficulty/boundary_precision_check/empty_completed_assessment_set_yields_null_max_and_domains_incomplete
    """
    context = _drafted_case_with_every_assessment_invalidated(api)
    case = context["case"]

    response = api.determine_eligibility(
        case["id"], f.not_eligible_determination_payload(case["version"]), PLACEMENT
    )

    validate_error(response, ApiErrorId.ERR_DOMAINS_INCOMPLETE.value)
    after = fx.read_case(api, case["id"])
    assert after["status"] == "REPORT_DRAFTED"
    assert after["version"] == case["version"]
    assert after["max_weighted_percent_delay"] is None
    assert fx.plans_for_case(api, case["id"]) == []


def test_redrafting_after_a_revision_request_is_refused_as_domains_incomplete(api):
    """The same empty set blocks the chair's second draft.

    PRD §3.5 calls the untouched REPORT_DRAFTED status "the only reachable way for
    a later report draft or determination to be refused with
    ERR_DOMAINS_INCOMPLETE", and PRD §3.7 has the closing draft "again require the
    chair's own identity and all five domains complete".

    Design: Difficulty/boundary_precision_check/empty_completed_assessment_set_yields_null_max_and_domains_incomplete
    """
    context = _drafted_case_with_every_assessment_invalidated(api)
    revised = fx.request_revision(api, context["case"]["id"])
    assert revised["status"] == "REVISIONS_REQUESTED"
    assert revised["revision_round"] == 1

    response = api.draft_report(
        context["case"]["id"],
        f.report_payload(),
        make_chair_headers(context["chair"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DOMAINS_INCOMPLETE.value)
    assert fx.read_case(api, context["case"]["id"])["status"] == "REVISIONS_REQUESTED"


# ------------------- the inclusive 25.0 percent qualifying threshold (PRD §3.6)
THRESHOLD_WINDOW = "2026-08-10T09:00:00Z"
THRESHOLD_AGE_MONTHS = 36


def _case_at_thirty_six_months(api):
    """An inclusive-variant case for a child who is exactly 36 months old.

    A chronological age of 36 months makes the percentage arithmetic land on the
    threshold exactly rather than near it.
    """
    child = fx.register_child(api, date_of_birth="2023-08-01")
    context = fx.setup_case(api, child["id"], assessment_protocol="PLAY_BASED")
    context["evaluators"] = {
        "COGNITIVE": fx.register_provider(api, discipline="ECSE_TEACHER"),
        "COMMUNICATION": fx.register_provider(api, discipline="SLP"),
        "SOCIAL_EMOTIONAL": fx.register_provider(api, discipline="SOCIAL_WORKER"),
    }
    return context


def _assess(api, context, domain, method, age_equivalent_months):
    """Schedule and complete one domain, checking the derived age on the way."""
    evaluator = context["evaluators"][domain]
    scheduled = fx.schedule_assessment(
        api,
        context["case"]["id"],
        evaluator["id"],
        domain=domain,
        method=method,
        window_start_utc=THRESHOLD_WINDOW,
    )
    assert scheduled["chronological_age_months"] == THRESHOLD_AGE_MONTHS
    return fx.complete_assessment(
        api, scheduled["id"], evaluator["id"], age_equivalent_months
    )


def test_a_percent_delay_of_exactly_twenty_five_qualifies(api):
    """The qualifying threshold is an inclusive lower bound.

    PRD §3.6 makes ``qualifies_delay`` true exactly when
    ``weighted_percent_delay`` "has reached 25.0 percent; the threshold is
    inclusive, so 25.0 qualifies and 24.9 does not". A standardized method counts
    at full weight under either variant, so the weighted figure is the raw one.

    Design: Difficulty/boundary_precision_check/percent_delay_exactly_at_the_twenty_five_percent_threshold_qualifies
    """
    context = _case_at_thirty_six_months(api)

    assessment = _assess(api, context, "COGNITIVE", "STANDARDIZED", 27)

    assert expected_percent_delay(THRESHOLD_AGE_MONTHS, 27) == 25.0
    assert_delay_figures(assessment, 25.0, 25.0, True)


def test_a_weighted_delay_rounding_up_onto_the_threshold_qualifies(api):
    """The pinned order of operations lands the discounted figure on 25.0 exactly.

    PRD §3.6 weights the already-rounded one-decimal ``percent_delay`` and rounds
    the product half up again — never the unrounded quotient — so 27.8 discounted
    by nine tenths gives 25.02, which becomes 25.0 and therefore qualifies.

    Design: Difficulty/boundary_precision_check/percent_delay_exactly_at_the_twenty_five_percent_threshold_qualifies
    """
    context = _case_at_thirty_six_months(api)

    assessment = _assess(api, context, "COMMUNICATION", "PLAY_BASED", 26)

    assert expected_percent_delay(THRESHOLD_AGE_MONTHS, 26) == 27.8
    assert expected_weighted_delay(27.8, PLAY_BASED_CONFIDENCE_WEIGHT) == 25.0
    assert_delay_figures(assessment, 27.8, 25.0, True)


def test_a_weighted_delay_just_below_the_threshold_does_not_qualify(api):
    """Twenty percent is below the bound, and the case rollup counts only the two above it.

    PRD §3.6 discounts a play-based administration to nine tenths, so 22.2 becomes
    20.0 and does not reach the threshold; the case's own aggregates then report
    three completed domains of which two qualify, with the maximum standing at the
    threshold value, and PRD §3.5 keeps the case at IN_PROGRESS until five distinct
    domains stand COMPLETED.

    Design: Difficulty/boundary_precision_check/percent_delay_exactly_at_the_twenty_five_percent_threshold_qualifies
    """
    context = _case_at_thirty_six_months(api)
    _assess(api, context, "COGNITIVE", "STANDARDIZED", 27)
    _assess(api, context, "COMMUNICATION", "PLAY_BASED", 26)

    assessment = _assess(api, context, "SOCIAL_EMOTIONAL", "PLAY_BASED", 28)

    assert expected_percent_delay(THRESHOLD_AGE_MONTHS, 28) == 22.2
    assert expected_weighted_delay(22.2, PLAY_BASED_CONFIDENCE_WEIGHT) == 20.0
    assert_delay_figures(assessment, 22.2, 20.0, False)

    case = fx.read_case(api, context["case"]["id"])
    assert case["status"] == "IN_PROGRESS"
    # Two qualifying domains, each below the 33.0 severity band, take the 1.0
    # multiplier on the 50-minute base allocation (PRD §3.6).
    assert_composite_profile(case, 3, 2, 25.0, "INDETERMINATE", 100)


# --------------------- the weekly service-minute ceiling (PRD §3.8)
CAP_MINUTES = 320


def _plan_with_three_lines_and_one_staffed(api):
    """A draft community-preschool plan whose SLP already carries 160 minutes.

    The provider's ceiling is set so that the second line lands exactly on it and
    the third, five-minute line cannot. The two lines are delivered at different
    sites so the per-location travel charge is in play.
    """
    first_site = fx.register_site(api)
    second_site = fx.register_site(api)
    provider = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=CAP_MINUTES
    )
    context = fx.setup_draft_plan(
        api, setting="COMMUNITY_PRESCHOOL", community_site_id=first_site["id"]
    )
    plan_id = context["plan"]["id"]
    lines = [
        fx.add_line(
            api, plan_id, discipline="SLP", weekly_minutes=minutes, delivery_model="DIRECT"
        )
        for minutes in (150, 140, 5)
    ]
    fx.staff_line(api, lines[0]["id"], provider["id"], delivery_site_id=first_site["id"])
    context["first_site"] = first_site
    context["second_site"] = second_site
    context["provider"] = fx.read_provider(api, provider["id"])
    context["lines"] = lines
    return context


def test_a_staffing_request_landing_exactly_on_the_ceiling_is_accepted(api):
    """Equality with the ceiling is accepted and leaves the provider AT_CAPACITY.

    PRD §3.8 refuses only a request whose resulting assigned total would exceed
    ``max_weekly_service_minutes``: "the comparison is strictly greater, so a
    request landing exactly on the ceiling is accepted". The travel tier is chosen
    from the direct total alone, so 290 direct minutes across two locations draw 5
    percent — 14.5 plus 15, which is 29.5, rounded up to 30 — for 320 assigned.

    Design: Difficulty/boundary_precision_check/assigned_minutes_landing_exactly_on_the_cap_is_accepted_one_more_is_not
    """
    context = _plan_with_three_lines_and_one_staffed(api)
    assert_provider_minute_ledger(
        context["provider"], 150, expected_travel_overhead(150, 1), 160, "OPEN"
    )

    response = api.staff_service_line(
        context["lines"][1]["id"],
        f.staffing_payload(
            context["provider"]["id"],
            context["provider"]["version"],
            delivery_site_id=context["second_site"]["id"],
        ),
        PLACEMENT,
    )

    line = validate_success(response)
    assert line["status"] == "STAFFED"
    assert line["provider_id"] == context["provider"]["id"]
    assert expected_travel_overhead(290, 2) == 30
    assert expected_assigned_minutes(290, 2) == CAP_MINUTES
    provider = fx.read_provider(api, context["provider"]["id"])
    assert_provider_minute_ledger(provider, 290, 30, CAP_MINUTES, "AT_CAPACITY")


def test_one_more_minute_past_the_ceiling_is_refused(api):
    """The next line after the ceiling is reached is refused, and nothing moves.

    PRD §3.8: "a request that lands exactly on the ceiling is accepted and leaves
    the provider AT_CAPACITY; the next minute is refused." Adding five direct
    minutes takes the total to 295, whose travel overhead is still 30, so the
    assigned total would be 325 against a ceiling of 320.

    Design: Difficulty/boundary_precision_check/assigned_minutes_landing_exactly_on_the_cap_is_accepted_one_more_is_not
    """
    context = _plan_with_three_lines_and_one_staffed(api)
    fx.staff_line(
        api,
        context["lines"][1]["id"],
        context["provider"]["id"],
        delivery_site_id=context["second_site"]["id"],
    )
    provider_at_cap = fx.read_provider(api, context["provider"]["id"])
    assert provider_at_cap["assigned_weekly_service_minutes"] == CAP_MINUTES
    assert expected_assigned_minutes(295, 2) == 325

    response = api.staff_service_line(
        context["lines"][2]["id"],
        f.staffing_payload(
            provider_at_cap["id"],
            provider_at_cap["version"],
            delivery_site_id=context["first_site"]["id"],
        ),
        PLACEMENT,
    )

    validate_error(response, ApiErrorId.ERR_PROVIDER_CASELOAD_EXCEEDED.value)
    refused_line = fx.read_line(api, context["lines"][2]["id"])
    assert refused_line["status"] == "PROPOSED"
    assert refused_line["provider_id"] is None
    after = fx.read_provider(api, provider_at_cap["id"])
    assert_provider_minute_ledger(after, 290, 30, CAP_MINUTES, "AT_CAPACITY")
    assert after["version"] == provider_at_cap["version"]


def test_the_caseload_view_shows_the_ledger_sitting_exactly_on_the_ceiling(api):
    """The audit view reproduces every input to the ceiling comparison.

    PRD §3.8 has the caseload view return the ``distinct_site_count`` behind the
    travel calculation, the pinned assigned total, the exact ``utilization`` ratio,
    and ``committed_weekly_minutes`` — the same computation with DRAFT plans
    excluded, which is zero while the only plan is still a draft.

    Design: Difficulty/boundary_precision_check/assigned_minutes_landing_exactly_on_the_cap_is_accepted_one_more_is_not
    """
    context = _plan_with_three_lines_and_one_staffed(api)
    fx.staff_line(
        api,
        context["lines"][1]["id"],
        context["provider"]["id"],
        delivery_site_id=context["second_site"]["id"],
    )

    caseload = fx.read_caseload(api, context["provider"]["id"])

    assert caseload["provider_id"] == context["provider"]["id"]
    assert caseload["direct_weekly_service_minutes"] == 290
    assert caseload["distinct_site_count"] == 2
    assert caseload["travel_overhead_minutes"] == 30
    assert caseload["assigned_weekly_service_minutes"] == CAP_MINUTES
    assert caseload["max_weekly_service_minutes"] == CAP_MINUTES
    assert caseload["utilization"] == pytest.approx(1.0)
    assert caseload["service_capacity_posture"] == "AT_CAPACITY"
    assert caseload["committed_weekly_minutes"] == 0

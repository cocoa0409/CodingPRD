"""The half-open reporting window of the treat-to-target quality report.

Source: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rule `boundary_precision_check`.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_one_decimal_place
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.factories import score_visit_cdai_payload
from test_helpers.fixtures import (
    ADMIN,
    checked_in_visit,
    score_visit,
    set_clock,
    visit_ready_practice,
)

VISIT_AT = instant(2026, 8, 3, 14, 0, 0)
ONE_SECOND_LATER = instant(2026, 8, 3, 14, 0, 1)
PERIOD_START = instant(2026, 8, 1, 0, 0, 0)
NEXT_DAY = instant(2026, 8, 4, 0, 0, 0)


def _reported_practice():
    """A consenting patient with exactly one `FOLLOW_UP` visit at
    2026-08-03T14:00:00Z, scored CDAI 9.00 — `LOW`, at target — and no infusion
    appointment anywhere, so `administered_dose_count` is 0."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = visit_ready_practice()
    checked_in_visit(scenario, VISIT_AT)
    scored = score_visit(scenario, score_visit_cdai_payload())
    assert scored["status"] == "SCORED"
    assert scored["activity_score"] == 9.00
    assert scored["activity_category"] == "LOW"
    assert scenario.refresh_patient()["registry_consent"] is True
    return scenario


def _report(scenario, period_start, period_end):
    return api_client.get_quality_report(
        scenario.patient_id,
        ADMIN,
        {"period_start": period_start, "period_end": period_end},
    )


# ---------------------------------------------------------------------------
# boundary_precision_check /
# quality_report_half_open_window_excludes_visit_at_period_end
# ---------------------------------------------------------------------------
def test_a_visit_sitting_exactly_at_period_end_empties_the_denominator():
    """The upper bound is exclusive, and here that is the difference between 200 and 422.

    PRD §3.9: "The half-open boundary matters here more than anywhere else: a visit
    whose `visit_datetime` equals `period_end` is excluded, and that alone can empty
    the denominator and turn a 200 into that rejection."

    Design: Difficulty/boundary_precision_check/quality_report_half_open_window_excludes_visit_at_period_end
    """
    scenario = _reported_practice()

    response = _report(scenario, PERIOD_START, VISIT_AT)

    validate_error(response, ApiErrorId.ERR_QUALITY_PERIOD_NO_VISITS.value, 422)


def test_extending_period_end_by_one_second_admits_that_same_visit():
    """One second of window is all that separates the empty report from the full one.

    PRD §3.9: "A `RegistryAdmin` or a `Rheumatologist` may read a patient's
    treat-to-target quality report over a window given as `period_start` and
    `period_end`, and that window is **half-open**: an event counts when its instant
    is at or after `period_start` and strictly before `period_end`."

    Design: Difficulty/boundary_precision_check/quality_report_half_open_window_excludes_visit_at_period_end
    """
    scenario = _reported_practice()

    excluded = _report(scenario, PERIOD_START, VISIT_AT)
    validate_error(excluded, ApiErrorId.ERR_QUALITY_PERIOD_NO_VISITS.value, 422)

    report = get_success_data(_report(scenario, PERIOD_START, ONE_SECOND_LATER))

    assert report["qualifying_visit_count"] == 1
    assert report["scored_visit_count"] == 1
    assert report["at_target_visit_count"] == 1
    assert report["escalation_indicated_count"] == 0
    assert report["escalation_acted_count"] == 0
    assert report["administered_dose_count"] == 0


def test_the_four_percentages_of_one_at_target_visit():
    """Each percentage either divides by a live denominator or falls back to 0.0.

    PRD §3.9: "Then `completeness_pct` is one hundred multiplied by the scored count
    divided by the qualifying count, rounded half up to one decimal place."

    PRD §3.9: "`escalation_action_pct` is one hundred multiplied by the acted count
    divided by the indicated count, rounded the same way, and is reported as 0.0 when
    no escalation was indicated."

    Design: Difficulty/boundary_precision_check/quality_report_half_open_window_excludes_visit_at_period_end
    """
    scenario = _reported_practice()

    report = get_success_data(_report(scenario, PERIOD_START, ONE_SECOND_LATER))

    for key in (
        "completeness_pct",
        "treat_to_target_attainment_pct",
        "escalation_action_pct",
        "biosimilar_uptake_pct",
    ):
        assert_one_decimal_place(report[key], key)

    assert report["completeness_pct"] == 100.0
    assert report["treat_to_target_attainment_pct"] == 100.0
    assert report["escalation_action_pct"] == 0.0, (
        "no escalation was indicated, so the ratio falls back rather than dividing by zero"
    )
    assert report["biosimilar_uptake_pct"] == 0.0, (
        "no dose was administered in the window, so the ratio falls back to 0.0"
    )


def test_the_instant_excluded_as_period_end_is_included_as_period_start():
    """The same instant is outside the window above and inside it below.

    PRD §3.9: "The qualifying denominator is the patient's visits whose `visit_type`
    is `NEW` or `FOLLOW_UP` and whose `visit_datetime` falls inside the half-open
    window; `URGENT` visits are excluded from both numerator and denominator
    everywhere in this report."

    Design: Difficulty/boundary_precision_check/quality_report_half_open_window_excludes_visit_at_period_end
    """
    scenario = _reported_practice()

    as_upper_bound = _report(scenario, PERIOD_START, VISIT_AT)
    validate_error(as_upper_bound, ApiErrorId.ERR_QUALITY_PERIOD_NO_VISITS.value, 422)

    report = get_success_data(_report(scenario, VISIT_AT, NEXT_DAY))

    assert report["qualifying_visit_count"] == 1, (
        "period_start is inclusive, so the visit at that exact instant counts"
    )
    assert report["scored_visit_count"] == 1
    assert report["at_target_visit_count"] == 1
    assert report["completeness_pct"] == 100.0

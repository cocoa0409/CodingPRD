"""Numeric boundaries in the pay arithmetic and in language-access reporting.

Two boundaries are exercised on both sides: the free-travel radius (exactly at
the radius pays nothing, one tenth of a mile past it pays the whole round trip)
and the coverage-rate denominator (an empty resolved pool is pinned to 100.00
while a resolved pool with nothing served reports 0.00).

Every test builds its own world from scratch — the harness relaunches the API
before each individual test, so no state is shared.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    create_unmet_need_report_payload,
    validate_error,
    validate_success,
)
import test_helpers.fixtures as fixtures


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------
H3_START = "2026-09-12T09:00:00.000Z"
H3_END = "2026-09-12T10:00:00.000Z"
H4_START = "2026-09-13T09:00:00.000Z"
H4_END = "2026-09-13T10:00:00.000Z"
CHECK_IN_CLOCK = "2026-09-12T09:00:00Z"
ACTUAL_END = "2026-09-12T09:45:00.000Z"


def _in_person_trial_overrides(case_number, scheduled_start, scheduled_end):
    """A one-hour in-person trial, in custody — class B on the default clock."""
    return {
        "case_number": case_number,
        "hearing_type": "TRIAL",
        "in_custody": True,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "requested_delivery_mode": "IN_PERSON",
    }


def _setup_reporting_world():
    """One CONTINUED hearing and one never-covered SCHEDULED hearing.

    The clock ends at 2026-09-01T00:00:00Z, which is exactly the exclusive end
    of the 2026-08-01 .. 2026-09-01 reporting window.
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    continued = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CV-2026-0601",
        hearing_type="CIVIL_MOTION",
        in_custody=False,
        scheduled_start="2026-08-15T09:00:00.000Z",
        scheduled_end="2026-08-15T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    continued = fixtures.continue_hearing(continued["id"], reason_code="COURT_CONGESTION")
    uncovered = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CV-2026-0602",
        hearing_type="CIVIL_MOTION",
        in_custody=False,
        scheduled_start="2026-08-16T09:00:00.000Z",
        scheduled_end="2026-08-16T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    fixtures.set_clock("2026-09-01T00:00:00Z")
    return {
        "language": config["language"],
        "courthouse": config["courthouse"],
        "continued": continued,
        "uncovered": uncovered,
    }


# ---------------------------------------------------------------------------
# The free-travel radius is inclusive, and one tenth of a mile past it is a cliff
# ---------------------------------------------------------------------------
def test_mileage_exactly_at_the_free_radius_reimburses_nothing():
    """PRD §3.8: "If the assignment's `delivery_mode` is anything other than `IN_PERSON`, or if the variant's one-way mileage is at or below the schedule's `travel_free_radius_miles`, the reimbursable mileage is 0."
    PRD §3.8: "The `PROVISIONAL` variant measures the *scheduled* window, from the hearing's `scheduled_start` up to but not including its `scheduled_end`, and takes its mileage from the assignment's `estimated_one_way_miles`."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and always carried to two decimal places."
    PRD §3.8: "Multiply `billable_hours` by the selected hourly rate and then by the multiplier, and round the product to whole cents half up; that is `service_cents`."
    PRD §3.8: "Add the three already-rounded components — `service_cents`, `rare_premium_cents`, and `travel_cents` — to obtain the total."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."

    Design: Difficulty/boundary_precision_check/travel_free_radius_inclusive_at_thirty_miles_and_round_trip_cliff
    """
    bundle = fixtures.setup_confirmed_assignment(
        hearing_overrides=_in_person_trial_overrides("CR-2026-0301", H3_START, H3_END),
        assignment_overrides={"estimated_one_way_miles": 30.0},
    )
    schedule = bundle["rate_schedule"]
    assert schedule["travel_free_radius_miles"] == pytest.approx(
        TEST_DEFAULTS["TRAVEL_FREE_RADIUS_MILES"]
    ), (
        f"expected a {TEST_DEFAULTS['TRAVEL_FREE_RADIUS_MILES']} mile free radius, got "
        f"{schedule['travel_free_radius_miles']}"
    )
    hearing = bundle["hearing"]
    assert hearing["priority_score"] == 65, (
        f"expected priority_score 65, got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "B", (
        f"expected class B, got {hearing['priority_class']}"
    )

    claim = bundle["pay_claim"]
    assert claim["variant"] == "PROVISIONAL", (
        f"expected variant PROVISIONAL, got {claim['variant']} at confirmation"
    )
    assert claim["status"] == "ENCUMBERED", (
        f"expected status ENCUMBERED, got {claim['status']} at confirmation"
    )
    assert claim["billable_hours"] == pytest.approx(2.00), (
        f"expected 2.00 billable hours, got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == 17500, (
        f"expected 17500 service cents, got {claim['service_cents']}"
    )
    assert claim["rare_premium_cents"] == 0, (
        f"expected no rare premium, got {claim['rare_premium_cents']}"
    )
    assert claim["travel_cents"] == 0, (
        f"expected 0 travel cents exactly at the free radius, got {claim['travel_cents']}"
    )
    assert claim["provisional_total_cents"] == 17500, (
        f"expected 17500 provisional cents, got {claim['provisional_total_cents']}"
    )


def test_one_tenth_of_a_mile_past_the_radius_pays_the_whole_round_trip():
    """PRD §3.8: "Otherwise the reimbursable mileage is twice the one-way figure, because the interpreter drives there and back once past the radius."
    PRD §3.8: "Multiply the reimbursable mileage by the schedule's `travel_mileage_rate_cents` and round to whole cents half up; that is `travel_cents`."
    PRD §3.8: "Note that the free radius is a cliff rather than a deduction: an interpreter one mile past the radius is reimbursed for the whole round trip, not for the excess."
    PRD §3.8: "Add the three already-rounded components — `service_cents`, `rare_premium_cents`, and `travel_cents` — to obtain the total."
    PRD §3.8: "The `PROVISIONAL` variant writes that total to `provisional_total_cents`; the `FINAL` and `LATE_CANCELLATION` variants write it to `final_total_cents` and leave `provisional_total_cents` frozen at whatever the provisional run produced."

    Design: Difficulty/boundary_precision_check/travel_free_radius_inclusive_at_thirty_miles_and_round_trip_cliff
    """
    bundle = fixtures.setup_confirmed_assignment(
        hearing_overrides=_in_person_trial_overrides("CR-2026-0302", H4_START, H4_END),
        assignment_overrides={"estimated_one_way_miles": 30.1},
    )
    schedule = bundle["rate_schedule"]
    assert schedule["travel_mileage_rate_cents"] == pytest.approx(
        TEST_DEFAULTS["TRAVEL_MILEAGE_RATE_CENTS"]
    ), (
        f"expected a {TEST_DEFAULTS['TRAVEL_MILEAGE_RATE_CENTS']} cent mileage rate, got "
        f"{schedule['travel_mileage_rate_cents']}"
    )

    claim = bundle["pay_claim"]
    assert claim["service_cents"] == 17500, (
        f"expected 17500 service cents, got {claim['service_cents']}"
    )
    assert claim["travel_cents"] == 4064, (
        f"expected 4064 travel cents for the 60.2 mile round trip, got "
        f"{claim['travel_cents']}"
    )
    assert claim["provisional_total_cents"] == 21564, (
        f"expected 21564 provisional cents, got {claim['provisional_total_cents']}"
    )
    assert claim["final_total_cents"] is None, (
        f"expected final_total_cents null while encumbered, got {claim['final_total_cents']}"
    )


def test_final_variant_at_the_radius_floors_to_the_minimum_call_and_still_pays_no_travel():
    """PRD §3.8: "The `FINAL` variant measures the *served* window, from the assignment's `check_in_utc` up to but not including its `actual_end_utc`, and takes its mileage from `actual_one_way_miles`."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and always carried to two decimal places."
    PRD §3.8: "If the assignment's `delivery_mode` is anything other than `IN_PERSON`, or if the variant's one-way mileage is at or below the schedule's `travel_free_radius_miles`, the reimbursable mileage is 0."
    PRD §3.7: "For a rostered interpreter, completion also settles the money: the pay claim moves `ENCUMBERED → FINALIZED` with `variant` set to `FINAL` and `final_total_cents` computed by the final arithmetic of §3.8, the courthouse's `encumbered_pay_cents`, `obligated_pay_cents` and `available_pay_cents` are all recomputed, and the interpreter's `pending_pay_cents` is recomputed to include the newly finalized amount."
    PRD §3.7: "Completion moves the hearing `COVERED → SERVED` and increments the hearing's `version` by 1."

    Design: Difficulty/boundary_precision_check/travel_free_radius_inclusive_at_thirty_miles_and_round_trip_cliff
    """
    bundle = fixtures.setup_served_assignment(
        CHECK_IN_CLOCK,
        ACTUAL_END,
        one_way_miles=30.0,
        hearing_overrides=_in_person_trial_overrides("CR-2026-0301", H3_START, H3_END),
        assignment_overrides={"estimated_one_way_miles": 30.0},
    )
    assert bundle["hearing"]["status"] == "SERVED", (
        f"expected SERVED, got {bundle['hearing']['status']} after completion"
    )

    claim = bundle["pay_claim"]
    assert claim["status"] == "FINALIZED", (
        f"expected status FINALIZED, got {claim['status']} after completion"
    )
    assert claim["variant"] == "FINAL", (
        f"expected variant FINAL, got {claim['variant']} after completion"
    )
    assert claim["billable_hours"] == pytest.approx(2.00), (
        f"expected the 2.00 hour minimum call, got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == 17500, (
        f"expected 17500 service cents, got {claim['service_cents']}"
    )
    assert claim["travel_cents"] == 0, (
        f"expected 0 travel cents at exactly 30.0 served miles, got {claim['travel_cents']}"
    )
    assert claim["rare_premium_cents"] == 0, (
        f"expected no rare premium, got {claim['rare_premium_cents']}"
    )
    assert claim["final_total_cents"] == 17500, (
        f"expected 17500 final cents, got {claim['final_total_cents']}"
    )
    assert claim["provisional_total_cents"] == 17500, (
        f"expected the frozen 17500 provisional cents, got "
        f"{claim['provisional_total_cents']}"
    )


def test_courthouse_ledger_separates_the_finalized_and_encumbered_sides_of_the_boundary():
    """PRD §2.9: "`encumbered_pay_cents` is the sum of `provisional_total_cents` over every pay claim whose `status` is `ENCUMBERED` and whose assignment's hearing sits at this courthouse."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every pay claim whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or `PAID`, reached through the same assignment-to-hearing-to-courthouse path."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Difficulty/boundary_precision_check/travel_free_radius_inclusive_at_thirty_miles_and_round_trip_cliff
    """
    config = fixtures.setup_program_config()
    interpreter_bundle = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="CERTIFIED"
    )
    interpreter_id = interpreter_bundle["interpreter"]["id"]

    at_radius_hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        **_in_person_trial_overrides("CR-2026-0301", H3_START, H3_END),
    )
    at_radius = fixtures.propose_assignment(
        at_radius_hearing["id"], interpreter_id, estimated_one_way_miles=30.0
    )
    at_radius = fixtures.confirm_assignment(at_radius["id"], interpreter_id)

    past_radius_hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        **_in_person_trial_overrides("CR-2026-0302", H4_START, H4_END),
    )
    past_radius = fixtures.propose_assignment(
        past_radius_hearing["id"], interpreter_id, estimated_one_way_miles=30.1
    )
    past_radius = fixtures.confirm_assignment(past_radius["id"], interpreter_id)

    fixtures.set_clock(CHECK_IN_CLOCK)
    fixtures.check_in_assignment(at_radius["id"], interpreter_id)
    fixtures.complete_assignment(at_radius["id"], interpreter_id, ACTUAL_END, 30.0)

    courthouse = fixtures.read_courthouse(config["courthouse"]["id"])
    assert courthouse["obligated_pay_cents"] == 17500, (
        f"expected 17500 obligated cents, got {courthouse['obligated_pay_cents']}"
    )
    assert courthouse["encumbered_pay_cents"] == 21564, (
        f"expected 21564 encumbered cents, got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4960936, (
        f"expected 4960936 available cents, got {courthouse['available_pay_cents']}"
    )


# ---------------------------------------------------------------------------
# The coverage-rate denominator: an empty pool is 100.00, a pool with nothing
# served is 0.00
# ---------------------------------------------------------------------------
def test_empty_resolved_pool_reports_coverage_one_hundred_and_compliant(
    api, quality_reviewer_headers
):
    """PRD §3.10: "The report's pool is every hearing at the named courthouse whose `scheduled_start` falls inside that window and whose `status` is either `SERVED` or `UNMET`."
    PRD §3.10: "Hearings still `SCHEDULED` or `COVERED` are not yet resolved and are excluded; hearings that were `CONTINUED` are excluded too, which is what keeps a postponement from depressing a court's coverage rate."
    PRD §3.10: "When `resolved_hearing_count` is 0 the division is undefined, and the program pins the convention: `coverage_rate_pct` is exactly 100.00 for an empty pool."
    PRD §3.10: "Otherwise the verdict is `COMPLIANT`."
    PRD §3.10: "Finally `by_language` breaks the same window down per language: it is an object keyed by the language's `code`, ordered by `code` ascending, whose value for each language appearing in the pool is an object carrying that language's `resolved`, `served`, and `unmet` counts."
    PRD §3.10: "The window is half-open on the hearing's `scheduled_start`: it begins at midnight UTC on `period_start` inclusive and ends at midnight UTC on `period_end` exclusive."

    Design: Difficulty/boundary_precision_check/empty_resolved_pool_reports_coverage_100_while_zero_served_reports_0
    """
    world = _setup_reporting_world()

    response = api.create_unmet_need_report(
        create_unmet_need_report_payload(
            world["courthouse"]["id"], "2026-08-01", "2026-09-01"
        ),
        quality_reviewer_headers,
    )
    report = validate_success(response, 201)

    assert report["resolved_hearing_count"] == 0, (
        f"expected 0 resolved hearings, got {report['resolved_hearing_count']}"
    )
    assert report["served_hearing_count"] == 0, (
        f"expected 0 served hearings, got {report['served_hearing_count']}"
    )
    assert report["unmet_hearing_count"] == 0, (
        f"expected 0 unmet hearings, got {report['unmet_hearing_count']}"
    )
    assert report["rare_language_unmet_count"] == 0, (
        f"expected 0 rare-language unmet hearings, got "
        f"{report['rare_language_unmet_count']}"
    )
    assert report["coverage_rate_pct"] == pytest.approx(100.00), (
        f"expected 100.00 coverage for an empty pool, got {report['coverage_rate_pct']}"
    )
    assert report["compliance_status"] == "COMPLIANT", (
        f"expected COMPLIANT, got {report['compliance_status']} on an empty pool"
    )
    assert report["by_language"] == {}, (
        f"expected an empty by_language breakdown, got {report['by_language']}"
    )


def test_daily_sweep_sweeps_only_the_uncovered_hearing_to_unmet():
    """PRD §3.10: "**Step three, uncovered hearings.** Every hearing still in `SCHEDULED` status whose `scheduled_start` has been reached or passed by the logical clock, and which has no assignment in `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`, moves `SCHEDULED → UNMET`, and each of that hearing's assignments still in `PROPOSED` is cancelled with `cancel_reason_code` set to `COORDINATOR_CANCELLED`."
    PRD §3.10: "Its response carries `swept_at`, the logical-clock instant the run executed, together with six identifier arrays: `lapsed_credential_ids`, `downgraded_interpreter_ids`, `expired_action_ids`, `reinstated_interpreter_ids`, `unmet_hearing_ids`, `cancelled_assignment_ids`, and `voided_pay_claim_ids`."
    PRD §3.5: "A continued hearing is terminal — the coordinator files a fresh hearing for the new date rather than reopening this one — and it is excluded from every counter in language-access reporting, so a continuance never depresses a courthouse's coverage rate."

    Design: Difficulty/boundary_precision_check/empty_resolved_pool_reports_coverage_100_while_zero_served_reports_0
    """
    world = _setup_reporting_world()

    sweep = fixtures.run_daily_sweep()
    assert sweep["unmet_hearing_ids"] == [world["uncovered"]["id"]], (
        f"expected only the uncovered hearing swept, got {sweep['unmet_hearing_ids']}"
    )

    assert fixtures.read_hearing(world["continued"]["id"])["status"] == "CONTINUED", (
        "the continued hearing must stay CONTINUED across the sweep"
    )
    assert fixtures.read_hearing(world["uncovered"]["id"])["status"] == "UNMET", (
        "the uncovered hearing must be swept to UNMET"
    )


def test_resolved_pool_with_nothing_served_reports_coverage_zero_and_non_compliant(
    api, quality_reviewer_headers
):
    """PRD §3.10: "From that pool, `resolved_hearing_count` is the size of the pool, `served_hearing_count` counts the pool members whose `status` is `SERVED`, `unmet_hearing_count` counts those whose `status` is `UNMET`, and `rare_language_unmet_count` counts the unmet subset restricted to hearings whose language has `tier_class` `RARE`."
    PRD §3.10: "`coverage_rate_pct` is 100 multiplied by `served_hearing_count`, divided by `resolved_hearing_count`, rounded half up to two decimal places."
    PRD §3.10: "A `coverage_rate_pct` below 85.00 is `NON_COMPLIANT`."

    Design: Difficulty/boundary_precision_check/empty_resolved_pool_reports_coverage_100_while_zero_served_reports_0
    """
    world = _setup_reporting_world()
    fixtures.run_daily_sweep()

    response = api.create_unmet_need_report(
        create_unmet_need_report_payload(
            world["courthouse"]["id"], "2026-08-01", "2026-09-01"
        ),
        quality_reviewer_headers,
    )
    report = validate_success(response, 201)

    assert report["resolved_hearing_count"] == 1, (
        f"expected 1 resolved hearing, got {report['resolved_hearing_count']}"
    )
    assert report["served_hearing_count"] == 0, (
        f"expected 0 served hearings, got {report['served_hearing_count']}"
    )
    assert report["unmet_hearing_count"] == 1, (
        f"expected 1 unmet hearing, got {report['unmet_hearing_count']}"
    )
    assert report["rare_language_unmet_count"] == 0, (
        f"expected 0 rare-language unmet hearings, got "
        f"{report['rare_language_unmet_count']}"
    )
    assert report["coverage_rate_pct"] == pytest.approx(0.00), (
        f"expected 0.00 coverage with nothing served, got {report['coverage_rate_pct']}"
    )
    assert report["compliance_status"] == "NON_COMPLIANT", (
        f"expected NON_COMPLIANT, got {report['compliance_status']} at 0.00 coverage"
    )


def test_by_language_breakdown_lists_only_the_resolved_pool(
    api, quality_reviewer_headers
):
    """PRD §3.10: "Finally `by_language` breaks the same window down per language: it is an object keyed by the language's `code`, ordered by `code` ascending, whose value for each language appearing in the pool is an object carrying that language's `resolved`, `served`, and `unmet` counts."
    PRD §3.10: "Hearings still `SCHEDULED` or `COVERED` are not yet resolved and are excluded; hearings that were `CONTINUED` are excluded too, which is what keeps a postponement from depressing a court's coverage rate."

    Design: Difficulty/boundary_precision_check/empty_resolved_pool_reports_coverage_100_while_zero_served_reports_0
    """
    world = _setup_reporting_world()
    fixtures.run_daily_sweep()

    response = api.create_unmet_need_report(
        create_unmet_need_report_payload(
            world["courthouse"]["id"], "2026-08-01", "2026-09-01"
        ),
        quality_reviewer_headers,
    )
    report = validate_success(response, 201)

    expected = {
        TEST_DEFAULTS["LANGUAGE_CODE"]: {"resolved": 1, "served": 0, "unmet": 1}
    }
    assert report["by_language"] == expected, (
        f"expected {expected}, got {report['by_language']}"
    )


def test_period_end_past_the_logical_clock_is_refused_as_an_open_window(
    api, quality_reviewer_headers
):
    """PRD §3.10: "`period_end` must be strictly after `period_start` — otherwise the request is malformed and refused with `ERR_INVALID_REQUEST` — the window must be entirely in the past, meaning midnight UTC on `period_end` is at or before the current logical clock, and it may span at most 400 days; a window that is still open or too long is refused with `ERR_REPORT_PERIOD_INVALID` (HTTP 422)."
    PRD §2.12 rung 37: "An unmet-need report period is closed and of legal length — otherwise `ERR_REPORT_PERIOD_INVALID` (422). Applies to `POST /unmet-need-reports`."

    Design: Difficulty/boundary_precision_check/empty_resolved_pool_reports_coverage_100_while_zero_served_reports_0
    """
    world = _setup_reporting_world()

    response = api.create_unmet_need_report(
        create_unmet_need_report_payload(
            world["courthouse"]["id"], "2026-08-01", "2026-09-02"
        ),
        quality_reviewer_headers,
    )
    validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_INVALID.value)

"""Two different shapes of contention over a scarce resource.

Pilot skids at one entry point are compared interval against interval with a
buffer added on both sides; a laboratory's throughput is instead a headcount
inside a fixed UTC calendar day.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_LAB_DAILY_CAPACITY_EXCEEDED,
    ERR_PILOT_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    open_evaluation,
    read_entry_point,
    read_lab_result,
    read_pilot,
    read_sample,
    received_sample,
    register_contaminant,
    register_entry_point,
    register_laboratory,
    register_pilot,
    submit_result,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    make_laboratory_manager_headers,
)

_GAC_END = "2026-05-15T00:00:00.000Z"
_ONE_DAY_AFTER_THE_GAC_WINDOW = "2026-05-16T00:00:00.000Z"
_EXACTLY_48_HOURS_AFTER_THE_GAC_WINDOW = "2026-05-17T00:00:00.000Z"


def _entry_point_with_a_planned_gac_window(api):
    """A PLANNED GAC skid holding [2026-05-01, 2026-05-15) at one entry point."""
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"])
    gac = register_pilot(
        api,
        f.gac_pilot_payload(
            evaluation["id"],
            window_start_at="2026-05-01T00:00:00.000Z",
            window_end_at=_GAC_END,
        ),
    )
    return evaluation, gac


def test_a_second_skid_inside_the_decontamination_buffer_is_refused(api):
    """A 24-hour gap is inside the 48-hour exclusion zone on the near side.

    The GAC window closes on 2026-05-15, which the buffer widens out to
    2026-05-17, so an IX window opening on 2026-05-16 overlaps the widened
    interval and is refused; only the original GAC pilot survives.

    PRD: "Each such existing window is first widened by 48 hours on both sides —
    a decontamination buffer, so that a skid finishing on Monday cannot be
    followed by another starting Tuesday."

    Design: Difficulty/resource_temporal_overlap/pilot_windows_conflict_inside_the_decontamination_buffer_and_pass_at_exactly_48_hours
    """
    evaluation, gac = _entry_point_with_a_planned_gac_window(api)

    validate_error(
        api.create_pilot_test(
            f.ix_pilot_payload(
                evaluation["id"],
                window_start_at=_ONE_DAY_AFTER_THE_GAC_WINDOW,
                window_end_at="2026-05-30T00:00:00.000Z",
                capital_cost_estimate_cents=900000000,
                annual_om_estimate_cents=40000000,
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_PILOT_WINDOW_CONFLICT,
        422,
    )

    rows = assert_total_count(
        api.list_pilot_tests(
            TREATMENT_ENGINEER_HEADERS, params={"treatment_evaluation_id": evaluation["id"]}
        ),
        1,
    )
    assert_equals(rows[0], "id", gac["id"])
    assert_status(read_pilot(api, gac["id"]), "PLANNED")


def test_a_skid_starting_exactly_48_hours_later_is_accepted(api):
    """Touching the widened boundary is legal; crossing it is not.

    Opening the IX window on 2026-05-17 puts its start instant exactly at the end
    of the widened GAC interval, and because both intervals are half-open the
    start instant is not inside the exclusion zone, so the second skid is
    registered in PLANNED alongside the first.

    PRD: "The requested window is then tested for overlap against each widened
    window, treating both as half-open intervals that include their start instant
    and exclude their end instant."

    Design: Difficulty/resource_temporal_overlap/pilot_windows_conflict_inside_the_decontamination_buffer_and_pass_at_exactly_48_hours
    """
    evaluation, gac = _entry_point_with_a_planned_gac_window(api)
    validate_error(
        api.create_pilot_test(
            f.ix_pilot_payload(
                evaluation["id"],
                window_start_at=_ONE_DAY_AFTER_THE_GAC_WINDOW,
                window_end_at="2026-05-30T00:00:00.000Z",
                capital_cost_estimate_cents=900000000,
                annual_om_estimate_cents=40000000,
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_PILOT_WINDOW_CONFLICT,
        422,
    )

    ix = validate_success(
        api.create_pilot_test(
            f.ix_pilot_payload(
                evaluation["id"],
                window_start_at=_EXACTLY_48_HOURS_AFTER_THE_GAC_WINDOW,
                window_end_at="2026-05-31T00:00:00.000Z",
                capital_cost_estimate_cents=900000000,
                annual_om_estimate_cents=40000000,
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        201,
    )

    assert_status(ix, "PLANNED")
    assert_equals(ix, "technology", "IX")
    assert_instant_equals(
        ix["window_start_at"], _EXACTLY_48_HOURS_AFTER_THE_GAC_WINDOW, label="window_start_at"
    )
    assert_instant_equals(ix["window_end_at"], "2026-05-31T00:00:00.000Z", label="window_end_at")
    assert_instant_equals(read_pilot(api, gac["id"])["window_end_at"], _GAC_END, label="window_end_at")
    assert_total_count(
        api.list_pilot_tests(
            TREATMENT_ENGINEER_HEADERS, params={"treatment_evaluation_id": evaluation["id"]}
        ),
        2,
    )


_FIRST_SLOT = "2026-04-20T01:00:00.000Z"
_LAST_SECOND_OF_THE_SAME_DAY = "2026-04-20T23:59:59.000Z"
_MIDDAY_OF_THE_FULL_DAY = "2026-04-20T12:00:00.000Z"
_ONE_SECOND_INTO_THE_NEXT_DAY = "2026-04-21T00:00:00.000Z"


def _laboratory_with_a_full_day(api):
    """A two-analysis laboratory whose 2026-04-20 UTC day is already occupied."""
    first = register_contaminant(api, code="PFOA")
    second = register_contaminant(api, code="PFHXS")
    third = register_contaminant(api, code="PFNA")
    laboratory = register_laboratory(api, daily_analysis_capacity=2)
    entry_point = register_entry_point(api)
    sample = received_sample(
        api,
        entry_point["id"],
        [first["id"], second["id"], third["id"]],
        laboratory["id"],
        monitoring_period="2026Q2",
        collected_at="2026-04-10T08:00:00.000Z",
        preservative_lot="LOT-CAP",
    )
    submit_result(
        api,
        laboratory["id"],
        sample["id"],
        first["id"],
        reported_ng_per_l=1.50,
        detection_limit_ng_per_l=1.00,
        analyzed_at=_FIRST_SLOT,
    )
    second_result = submit_result(
        api,
        laboratory["id"],
        sample["id"],
        second["id"],
        reported_ng_per_l=1.50,
        detection_limit_ng_per_l=1.00,
        analyzed_at=_LAST_SECOND_OF_THE_SAME_DAY,
    )
    return laboratory, entry_point, sample, third, second_result


def test_a_third_analysis_inside_a_full_calendar_day_is_refused(api):
    """The bucket is a calendar day, so a 23-hour-wide day can still be full.

    Two live analyses already carry an analyzed_at on 2026-04-20, which equals the
    laboratory's capacity of two, so a third analysis dated midday on that same
    day is refused and the laboratory still holds exactly two results.

    PRD: "The system counts the laboratory's existing results whose status is
    `SUBMITTED` or `ACCEPTED` and whose `analyzed_at` falls on the same UTC
    calendar day as the submitted analysis instant; when that count already equals
    or exceeds the laboratory's `daily_analysis_capacity`, the submission is
    refused with `ERR_LAB_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/laboratory_capacity_counts_a_utc_calendar_day_bucket_rather_than_a_rolling_window
    """
    laboratory, entry_point, sample, third, _ = _laboratory_with_a_full_day(api)

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                third["id"],
                reported_ng_per_l=1.50,
                detection_limit_ng_per_l=1.00,
                analyzed_at=_MIDDAY_OF_THE_FULL_DAY,
            ),
            make_laboratory_manager_headers(laboratory["id"]),
        ),
        ERR_LAB_DAILY_CAPACITY_EXCEEDED,
        422,
    )

    assert_total_count(
        api.list_lab_results(
            COMPLIANCE_OFFICER_HEADERS, params={"laboratory_id": laboratory["id"]}
        ),
        2,
    )
    assert_status(read_sample(api, sample["id"]), "RECEIVED")
    assert_entry_point_posture(read_entry_point(api, entry_point["id"]), accepted_result_count=0)


def test_the_next_calendar_day_opens_a_fresh_bucket_one_second_later(api):
    """A rolling twenty-four-hour window would have rejected this; the day bucket does not.

    Moving the analysis instant one second past midnight puts it in the
    2026-04-21 bucket, which holds nothing, so the identical analysis that was
    refused at midday of the previous day is accepted even though it sits barely
    an hour after the pair that blocked it.

    PRD: "Throughput is bounded by `daily_analysis_capacity`, an integer of at
    least 1 that defaults to 3 and caps how many live analyses the laboratory may
    hold inside a single UTC calendar day."

    Design: Difficulty/resource_temporal_overlap/laboratory_capacity_counts_a_utc_calendar_day_bucket_rather_than_a_rolling_window
    """
    laboratory, _, sample, third, second_result = _laboratory_with_a_full_day(api)
    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                third["id"],
                reported_ng_per_l=1.50,
                detection_limit_ng_per_l=1.00,
                analyzed_at=_MIDDAY_OF_THE_FULL_DAY,
            ),
            make_laboratory_manager_headers(laboratory["id"]),
        ),
        ERR_LAB_DAILY_CAPACITY_EXCEEDED,
        422,
    )

    accepted_into_the_new_day = validate_success(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                third["id"],
                reported_ng_per_l=1.50,
                detection_limit_ng_per_l=1.00,
                analyzed_at=_ONE_SECOND_INTO_THE_NEXT_DAY,
            ),
            make_laboratory_manager_headers(laboratory["id"]),
        ),
        201,
    )

    assert_status(accepted_into_the_new_day, "SUBMITTED")
    assert_instant_equals(
        accepted_into_the_new_day["analyzed_at"], _ONE_SECOND_INTO_THE_NEXT_DAY, label="analyzed_at"
    )
    assert_equals(accepted_into_the_new_day, "laboratory_id", laboratory["id"])
    assert_instant_equals(
        read_lab_result(api, second_result["id"])["analyzed_at"],
        _LAST_SECOND_OF_THE_SAME_DAY,
        label="analyzed_at",
    )
    assert_total_count(
        api.list_lab_results(
            COMPLIANCE_OFFICER_HEADERS, params={"laboratory_id": laboratory["id"]}
        ),
        3,
    )

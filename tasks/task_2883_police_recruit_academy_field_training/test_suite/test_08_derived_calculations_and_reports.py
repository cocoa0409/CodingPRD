"""The derived readings: hours, fitness points, thresholds and the two reports.

Every number here is computed from rows the test itself created, so the pinned
rounding order and the pinned input sets are both visible in the answers.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_hours_equals,
    assert_rate_equals,
    assert_stage_order,
)
from test_helpers.test_users import (
    coordinator_headers,
    custodian_headers,
    director_headers,
)

PATROL = "PATROL"


def _patrol_curriculum(world, required_hours=6.0, min_total_hours=6.0,
                       exam_required=False, **standard_kwargs):
    return world.curriculum(topic_code=PATROL, required_hours=required_hours,
                            exam_required=exam_required,
                            min_total_hours=min_total_hours,
                            session_starts_at="2026-08-10T09:00:00Z",
                            session_ends_at="2026-08-10T11:00:00Z",
                            after_session="2026-08-10T12:00:00Z",
                            **standard_kwargs)


def _block(world, built, day, starts="09:00:00", ends="11:00:00",
           min_enrollment=1):
    """One PATROL block in room R1 on the named day."""
    return world.schedule_session(built["cohort"]["id"],
                                  built["lesson_plan"]["id"],
                                  built["instructor"]["id"], room_code="R1",
                                  starts_at=f"{day}T{starts}Z",
                                  ends_at=f"{day}T{ends}Z",
                                  min_enrollment=min_enrollment)


def _read_cohort(world, built):
    return validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))


def test_each_session_interval_is_rounded_to_hours_on_its_own(world):
    """Fifty, eighty and thirty minutes read 0.83, 1.33 and 0.50 hours.

    PRD: "`scheduled_hours` is the elapsed time from `starts_at` to `ends_at`
    expressed in hours - the number of seconds between them divided by 3600,
    rounded half up to 2 decimal places."

    Design: Corner/calculations/correct_result_session_scheduled_hours_rounds_each_interval_independently
    """
    built = _patrol_curriculum(world)

    fifty = _block(world, built, "2026-08-10", "09:00:00", "09:50:00")
    eighty = _block(world, built, "2026-08-11", "09:00:00", "10:20:00")
    thirty = _block(world, built, "2026-08-12", "09:00:00", "09:30:00")

    assert_hours_equals(fifty["scheduled_hours"], "0.83", "scheduled_hours")
    assert_hours_equals(eighty["scheduled_hours"], "1.33", "scheduled_hours")
    assert_hours_equals(thirty["scheduled_hours"], "0.50", "scheduled_hours")

    # The lesson plan's contact hours are never copied into the interval: the
    # plan is authored for four hours and none of the three blocks reads that.
    assert_hours_equals(built["lesson_plan"]["contact_hours"], "4.00",
                        "contact_hours")

    # Each already-rounded value is what the projection sums.
    projected = _read_cohort(world, built)["projected_topic_hours"]
    assert_hours_equals(projected[PATROL], "2.66", "projected_topic_hours")


def test_only_credited_rows_of_delivered_sessions_reach_the_hour_totals(world):
    """Of three rostered blocks, only the credited one moves any total.

    PRD: "Rows at `PROVISIONAL` or `VOIDED`, and rows whose session sits at
    `SCHEDULED`, `UNDER_MIN_ENROLLMENT`, `CANCELLED` or `VOIDED`, contribute
    nothing at all."

    Design: Corner/calculations/input_set_filtering_only_credited_rows_of_delivered_sessions_count
    """
    built = _patrol_curriculum(world, required_hours=10.0, min_total_hours=10.0)
    recruit = world.recruit_in_academy(built["cohort"]["id"])

    kept = _block(world, built, "2026-08-10")
    reversed_block = _block(world, built, "2026-08-11")
    upcoming = _block(world, built, "2026-08-12")
    kept_row = world.record_attendance(kept["id"], recruit["id"], "PRESENT", 2.0)
    reversed_row = world.record_attendance(reversed_block["id"], recruit["id"],
                                           "PRESENT", 2.0)
    upcoming_row = world.record_attendance(upcoming["id"], recruit["id"],
                                           "PRESENT", 2.0)

    world.set_clock("2026-08-11T12:00:00Z")
    world.deliver_session(kept["id"])
    world.deliver_session(reversed_block["id"])
    world.void_delivery(reversed_block["id"], "instructor recalled to duty")

    def read_row(row_id):
        return validate_success(world.client.get_attendance_record(
            row_id, coordinator_headers()))

    assert read_row(kept_row["id"])["ledger_status"] == "CREDITED"
    assert read_row(reversed_row["id"])["ledger_status"] == "VOIDED"
    assert read_row(upcoming_row["id"])["ledger_status"] == "PROVISIONAL"
    assert_hours_equals(read_row(reversed_row["id"])["credited_hours"], "0.00",
                        "credited_hours")
    assert_hours_equals(read_row(upcoming_row["id"])["credited_hours"], "0.00",
                        "credited_hours")

    _rows, meta = validate_paginated(world.client.list_attendance_records(
        coordinator_headers(), {"recruit_id": recruit["id"]}))
    assert meta["total_count"] == 3

    stored = world.read_recruit(recruit["id"])
    assert_hours_equals(stored["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_hours_equals(stored["per_topic_credited_hours"][PATROL], "2.00",
                        "per_topic_credited_hours")

    cohort = _read_cohort(world, built)
    assert_hours_equals(cohort["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")
    assert_hours_equals(cohort["unmet_topic_hours"][PATROL], "8.00",
                        "unmet_topic_hours")
    # The scheduled block still projects; the voided one no longer does.
    assert_hours_equals(cohort["projected_topic_hours"][PATROL], "4.00",
                        "projected_topic_hours")

    progress = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers()))
    assert_hours_equals(progress["total_hours"], "2.00", "total_hours")
    assert progress["eligible_for_certification"] is False


def test_the_fitness_reference_table_is_keyed_by_the_recruits_age_bracket(world):
    """The same four results score 30 in the youngest bracket and 85 in the oldest.

    PRD: "For `AGE_20_29` the references are 30 push-ups, 38 sit-ups, 750
    seconds on the 1.5-mile run and 18 inches of vertical jump. For `AGE_30_39`
    they are 24 push-ups, 32 sit-ups, 810 seconds and 16 inches. For
    `AGE_40_49` they are 18 push-ups, 26 sit-ups, 900 seconds and 14 inches."

    Design: Corner/calculations/constants_applied_fitness_standards_table_is_keyed_by_the_recruits_age_bracket
    """
    built = _patrol_curriculum(world, fitness_event_floor_points=10,
                               fitness_pass_score=60)
    metrics = {"push_ups": 24, "sit_ups": 30, "run_1_5_mile_seconds": 800,
               "vertical_jump_inches": 15}

    younger = world.create_recruit(built["cohort"]["id"],
                                   full_name="Rae Ortiz",
                                   date_of_birth="1999-04-12",
                                   age_bracket="AGE_20_29")
    older = world.create_recruit(built["cohort"]["id"], full_name="Hal Croft",
                                 date_of_birth="1982-03-15",
                                 age_bracket="AGE_40_49")

    younger_record = world.record_findings(
        world.order_screening(younger["id"], "PHYSICAL_FITNESS")["id"],
        "PHYSICAL_FITNESS", raw_metrics=metrics)
    older_record = world.record_findings(
        world.order_screening(older["id"], "PHYSICAL_FITNESS")["id"],
        "PHYSICAL_FITNESS", raw_metrics=metrics)

    # 24/30, 30/38 and 15/18 all land in the 0.70 tier; 750/800 is inverted
    # into 0.9375, so the raw total is 30 and one event sits under the floor.
    assert younger_record["composite_score"] == 30
    # Against the oldest bracket the same results beat every reference.
    assert older_record["composite_score"] == 85

    for record in (younger_record, older_record):
        assert record["status"] == "FINDINGS_RECORDED"
        assert record["findings_recorded_by_user_id"] is not None


def test_absence_accrual_flips_the_review_only_once_the_limit_is_passed(world):
    """Four hours of unexcused absence hold; four and a half do not.

    PRD: "Mandatory dismissal review is triggered when that accrual is
    **strictly greater than** the standard's `max_absence_hours`; landing
    exactly on the limit does not trigger it."

    Design: Corner/calculations/threshold_absence_accrual_flips_dismissal_pending_only_once_it_is_exceeded
    """
    built = _patrol_curriculum(world, max_absence_hours=4.0)
    recruit = world.recruit_in_academy(built["cohort"]["id"])

    first = _block(world, built, "2026-08-10")
    second = _block(world, built, "2026-08-11")
    half_hour = _block(world, built, "2026-08-12", "09:00:00", "09:30:00")
    for session in (first, second, half_hour):
        world.record_attendance(session["id"], recruit["id"],
                                "ABSENT_UNEXCUSED", 0.0)

    world.set_clock("2026-08-10T12:00:00Z")
    world.deliver_session(first["id"])
    world.set_clock("2026-08-11T12:00:00Z")
    world.deliver_session(second["id"])

    at_the_limit = world.read_recruit(recruit["id"])
    assert_hours_equals(at_the_limit["unexcused_absence_hours"], "4.00",
                        "unexcused_absence_hours")
    assert at_the_limit["academy_status"] == "IN_PROGRESS"

    world.set_clock("2026-08-12T12:00:00Z")
    world.deliver_session(half_hour["id"])

    past_the_limit = world.read_recruit(recruit["id"])
    # The half hour contributed is the session's scheduled_hours, not the
    # recruit's present_hours of zero.
    assert_hours_equals(past_the_limit["unexcused_absence_hours"], "4.50",
                        "unexcused_absence_hours")
    assert past_the_limit["academy_status"] == "DISMISSAL_PENDING"
    assert_hours_equals(past_the_limit["credited_hours_total"], "0.00",
                        "credited_hours_total")


def _one_partial_row(world):
    """A single PARTIAL row of 1.5 hours on a delivered two-hour PATROL block."""
    built = _patrol_curriculum(world, required_hours=10.0, min_total_hours=10.0)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _block(world, built, "2026-08-10")
    row = world.record_attendance(session["id"], recruit["id"], "PARTIAL", 1.5)
    world.set_clock("2026-08-10T12:00:00Z")
    world.deliver_session(session["id"])
    return built, recruit, session, row


def test_the_basis_parameter_picks_the_hour_variant_and_echoes_it_back(world):
    """The same 1.5-hour partial row reads 1.13 attended and 2.00 scheduled.

    PRD: "The `basis` query parameter selects which hour basis to report -
    `ATTENDED` when omitted, or `SCHEDULED` - and the selected value is echoed
    back in the response's `basis`."

    Design: Corner/calculations/variant_selection_basis_query_parameter_picks_the_hour_variant_and_echoes_it
    """
    _built, recruit, _session, _row = _one_partial_row(world)

    def progress(params=None):
        return validate_success(world.client.get_certification_progress(
            recruit["id"], coordinator_headers(), params))

    default = progress()
    attended = progress({"basis": "ATTENDED"})
    scheduled = progress({"basis": "SCHEDULED"})

    assert default["basis"] == "ATTENDED"
    # 1.50 present hours against a 2.00 hour block is a 0.75 ratio.
    assert_hours_equals(default["total_hours"], "1.13", "total_hours")
    assert attended["basis"] == "ATTENDED"
    assert_hours_equals(attended["total_hours"], "1.13", "total_hours")
    assert scheduled["basis"] == "SCHEDULED"
    assert_hours_equals(scheduled["total_hours"], "2.00", "total_hours")

    for report in (default, attended, scheduled):
        assert PATROL in report["per_topic_hours"]
        assert report["eligible_for_certification"] is False

    stored = world.read_recruit(recruit["id"])
    assert_hours_equals(stored["credited_hours_total"], "1.13",
                        "credited_hours_total")
    assert_hours_equals(stored["scheduled_basis_hours_total"], "2.00",
                        "scheduled_basis_hours_total")


def test_the_stored_recruit_totals_agree_with_the_recomputed_progress_report(world):
    """Recruit, report, cohort, ledger and attendance row all read 1.13.

    PRD: "A recruit's curriculum progress is available as a report that is
    recomputed from current state on every read and persisted nowhere."

    Design: Corner/calculations/reconciliation_stored_recruit_totals_agree_with_the_recomputed_progress_report
    """
    built, recruit, _session, row = _one_partial_row(world)

    stored = world.read_recruit(recruit["id"])
    assert_hours_equals(stored["credited_hours_total"], "1.13",
                        "credited_hours_total")
    assert_hours_equals(stored["per_topic_credited_hours"][PATROL], "1.13",
                        "per_topic_credited_hours")
    assert list(stored["per_topic_credited_hours"].keys()) == [PATROL]

    report = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers()))
    assert_hours_equals(report["total_hours"], "1.13", "total_hours")
    assert_hours_equals(report["per_topic_hours"][PATROL], "1.13",
                        "per_topic_hours")

    cohort = _read_cohort(world, built)
    assert_hours_equals(cohort["credited_topic_hours_total"], "1.13",
                        "credited_topic_hours_total")
    # The cohort's unmet map is a delivered-hours reading, not an attended one:
    # ten required less the session's two delivered hours.
    assert_hours_equals(cohort["unmet_topic_hours"][PATROL], "8.00",
                        "unmet_topic_hours")

    ledger, meta = validate_paginated(world.client.list_training_record_entries(
        custodian_headers(),
        {"recruit_id": recruit["id"], "kind": "HOURS_CREDIT", "limit": 100}))
    assert meta["total_count"] == 1
    assert_hours_equals(ledger[0]["hours_delta"], "1.13", "hours_delta")

    credited = validate_success(world.client.get_attendance_record(
        row["id"], coordinator_headers()))
    assert_hours_equals(credited["credited_hours"], "1.13", "credited_hours")
    assert_hours_equals(credited["counted_absence_hours"], "0.00",
                        "counted_absence_hours")
    # Neither the raw present hours nor the whole block is ever the credit.
    assert_hours_equals(credited["present_hours"], "1.50", "present_hours")


def _four_recruit_cohort(world):
    """Four recruits: two into the academy, one dismissed, one withdrawn."""
    built = _patrol_curriculum(world, required_hours=2.0, min_total_hours=2.0)
    cohort_id = built["cohort"]["id"]
    first = world.recruit_in_academy(cohort_id, full_name="Ada Reyes")
    second = world.recruit_in_academy(cohort_id, full_name="Ben Osei")
    dismissed = world.recruit_in_screening(cohort_id, full_name="Cal Iversen")
    withdrawn = world.recruit_in_screening(cohort_id, full_name="Dot Marsh")

    world.dismiss(dismissed["id"], "INTEGRITY", "Sustained integrity finding")
    world.dismiss(withdrawn["id"], "VOLUNTARY_WITHDRAWAL",
                  "Accepted employment elsewhere")
    return built, {"first": first, "second": second,
                   "dismissed": dismissed, "withdrawn": withdrawn}


def test_the_attrition_report_and_the_forecast_pin_every_derived_number(world):
    """Four entered screening, one adverse and one voluntary: 0.2500 and 14 applicants.

    PRD: "`survival_to_certification` is the product, over the stages whose
    entered count is greater than zero, of one minus each stage's attrition rate,
    rounded half up to 4 decimal places."

    Design: Corner/calculations/aggregation_attrition_report_and_pipeline_forecast_pin_every_derived_number
    """
    built, _recruits = _four_recruit_cohort(world)
    cohort_id = built["cohort"]["id"]

    report = validate_success(world.client.get_attrition_analysis(
        cohort_id, director_headers()))
    assert report["academy_class_id"] == cohort_id
    assert_stage_order(report["stages"])
    by_stage = {stage["stage_code"]: stage for stage in report["stages"]}

    screening = by_stage["SCREENING"]
    assert (screening["entered"], screening["adverse_exits"],
            screening["voluntary_exits"]) == (4, 1, 1)
    assert_rate_equals(screening["attrition_rate"], "0.2500", "attrition_rate")

    academy = by_stage["ACADEMY"]
    assert (academy["entered"], academy["adverse_exits"],
            academy["voluntary_exits"]) == (2, 0, 0)
    assert_rate_equals(academy["attrition_rate"], "0.0000", "attrition_rate")

    for empty_stage in ("FIELD_TRAINING", "PROBATION"):
        stage = by_stage[empty_stage]
        assert (stage["entered"], stage["adverse_exits"],
                stage["voluntary_exits"]) == (0, 0, 0)
        assert stage["attrition_rate"] is None, empty_stage

    # 0.75 at screening times one at the academy; the two empty stages
    # contribute nothing at all.
    assert_rate_equals(report["survival_to_certification"], "0.7500",
                       "survival_to_certification")
    assert report["voluntary_exits_total"] == 1
    assert report["rolling_mean_scores"] == {}

    forecast = validate_success(world.client.get_pipeline_forecast(
        cohort_id, director_headers(), {"target_sworn_officers": 10}))
    assert forecast["academy_class_id"] == cohort_id
    assert forecast["target_sworn_officers"] == 10
    assert_rate_equals(forecast["survival_to_certification"], "0.7500",
                       "survival_to_certification")
    # Ten divided by 0.7500 is 13.33 recurring, and the ceiling is 14.
    assert forecast["required_applicants"] == 14
    # Each step of the forward pass is floored: 14, then floor(14 x 0.75) = 10,
    # which the two later factors of one carry through unchanged.
    assert forecast["per_stage_expected"] == {
        "SCREENING": 14, "ACADEMY": 10, "FIELD_TRAINING": 10, "PROBATION": 10}

    smaller = validate_success(world.client.get_pipeline_forecast(
        cohort_id, director_headers(), {"target_sworn_officers": 3}))
    assert smaller["target_sworn_officers"] == 3
    assert smaller["required_applicants"] == 4

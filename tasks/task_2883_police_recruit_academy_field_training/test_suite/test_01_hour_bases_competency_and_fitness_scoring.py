"""The two hour bases, the two competency variants and the fitness composite.

Each of these readings is computed twice from the same rows under two different
disciplines, and the contract pins where the rounding happens in each.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_FITNESS_STANDARD_NOT_MET
from test_helpers.assertions import (
    assert_hours_equals,
    assert_score_equals,
)
from test_helpers.test_users import (
    coordinator_alt_headers,
    coordinator_headers,
    director_headers,
)

PATROL = "PATROL"


def _three_partial_sessions(world, curriculum, recruit):
    """Three two-hour sessions, each attended PARTIAL for one and a half hours."""
    sessions = []
    for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
        session = world.schedule_session(
            curriculum["cohort"]["id"], curriculum["lesson_plan"]["id"],
            curriculum["instructor"]["id"], room_code="R1",
            starts_at=f"{day}T09:00:00Z", ends_at=f"{day}T11:00:00Z",
            min_enrollment=1)
        world.record_attendance(session["id"], recruit["id"], "PARTIAL", 1.5)
        sessions.append(session)
    world.set_clock("2026-08-12T12:00:00Z")
    for session in sessions:
        world.deliver_session(session["id"])
    return sessions


def _partial_attendance_world(world):
    curriculum = world.curriculum(topic_code=PATROL, required_hours=6.0,
                                  exam_required=False, min_total_hours=6.0)
    recruit = world.recruit_in_academy(curriculum["cohort"]["id"])
    _three_partial_sessions(world, curriculum, recruit)
    return curriculum, recruit


def test_partial_rows_are_rounded_before_they_are_summed(world):
    """Three partially attended two-hour blocks credit 3.39 attended hours.

    PRD: "Three delivered two-hour sessions of one topic, each attended
    `PARTIAL` for one and a half hours, credit one and thirteen hundredths of an
    hour each and total three and thirty-nine hundredths hours - not the three
    and thirty-eight hundredths that summing first would give."

    Design: Difficulty/dual_variant_calc/attended_basis_vs_scheduled_basis_diverge_on_partial_attendance
    """
    curriculum, recruit = _partial_attendance_world(world)

    stored = world.read_recruit(recruit["id"])
    assert_hours_equals(stored["credited_hours_total"], "3.39",
                        "credited_hours_total")
    assert_hours_equals(stored["per_topic_credited_hours"][PATROL], "3.39",
                        f"per_topic_credited_hours[{PATROL}]")

    cohort = validate_success(
        world.client.get_academy_class(curriculum["cohort"]["id"],
                                       director_headers()))
    assert_hours_equals(cohort["credited_topic_hours_total"], "3.39",
                        "credited_topic_hours_total")
    assert cohort["status"] == "IN_SESSION"


def test_scheduled_basis_reports_whole_seat_time_for_the_same_rows(world):
    """The scheduled basis reads six flat hours where the attended basis reads 3.39.

    PRD: "The same three partially attended two-hour sessions read three and
    thirty-nine hundredths hours on the attended basis and six hours flat on the
    scheduled basis."

    Design: Difficulty/dual_variant_calc/attended_basis_vs_scheduled_basis_diverge_on_partial_attendance
    """
    _curriculum, recruit = _partial_attendance_world(world)

    attended = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers(), {"basis": "ATTENDED"}))
    scheduled = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers(), {"basis": "SCHEDULED"}))

    assert attended["basis"] == "ATTENDED"
    assert scheduled["basis"] == "SCHEDULED"
    assert_hours_equals(attended["total_hours"], "3.39", "attended total_hours")
    assert_hours_equals(scheduled["total_hours"], "6.00", "scheduled total_hours")

    stored = world.read_recruit(recruit["id"])
    assert_hours_equals(stored["scheduled_basis_hours_total"], "6.00",
                        "scheduled_basis_hours_total")


def test_asking_for_the_scheduled_basis_cannot_open_the_curriculum_gate(world):
    """Only the attended basis decides the certification verdict.

    PRD: "Finally, `eligible_for_certification` is a curriculum verdict that
    **always reads the attended basis** regardless of the requested `basis`."

    Design: Difficulty/dual_variant_calc/attended_basis_vs_scheduled_basis_diverge_on_partial_attendance
    """
    _curriculum, recruit = _partial_attendance_world(world)

    default_basis = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers()))
    assert default_basis["basis"] == "ATTENDED"
    assert_hours_equals(default_basis["total_hours"], "3.39", "total_hours")
    assert default_basis["eligible_for_certification"] is False

    scheduled = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers(), {"basis": "SCHEDULED"}))
    assert scheduled["eligible_for_certification"] is False

    stored = world.read_recruit(recruit["id"])
    assert stored["academy_status"] == "IN_PROGRESS"


def _slumping_rotation(world):
    """A live rotation carrying four reports whose ratings slump 6, 6, 3, 3."""
    curriculum = world.curriculum(topic_code=PATROL, required_hours=2.0,
                                  exam_required=False, min_total_hours=2.0,
                                  session_ends_at="2026-08-03T11:00:00Z",
                                  after_session="2026-08-03T11:00:00Z")
    recruit = world.recruit_in_field_training(curriculum)
    fto = world.create_certified_fto()
    rotation = world.plan_rotation(recruit, fto["id"], phase_number=1,
                                   start_date="2027-03-01", end_date="2027-03-31")
    rotation = world.activate_rotation(rotation["id"])
    world.set_clock("2027-03-20T12:00:00Z")
    for observed_on, rating in (("2027-03-10", 6), ("2027-03-11", 6),
                                ("2027-03-12", 3)):
        world.file_report(rotation["id"], fto["id"], observed_on,
                          f.dimension_ratings(rating))
    return curriculum, recruit, fto, rotation


def test_a_late_slump_pulls_the_terminally_weighted_score_below_the_pool(world):
    """Rating sums 30, 30, 15, 15 read 4.50 pooled and 4.80 recency weighted.

    PRD: "Four reports whose ratings are uniform within each report at 6, 6, 3
    and 3 - rating sums 30, 30, 15, 15 - give a rolling mean of 90 divided by
    20, or 4.50; the recent bucket is the last three (30, 15, 15) for a recent
    mean of 4.0, the earlier bucket is the single 30 for an earlier mean of 6.0,
    and the terminally weighted score is 0.60 times 4.0 plus 0.40 times 6.0, or
    4.80."

    Design: Difficulty/dual_variant_calc/terminal_weighted_vs_rolling_mean_diverge_on_late_slump
    """
    _curriculum, _recruit, fto, rotation = _slumping_rotation(world)

    report = world.file_report(rotation["id"], fto["id"], "2027-03-13",
                              f.dimension_ratings(3))
    assert_score_equals(report["dor_mean"], "3.00", "dor_mean")

    read = world.read_rotation(rotation["id"])
    assert_score_equals(read["competency_score"], "4.80", "competency_score")
    assert_score_equals(read["rolling_mean_score"], "4.50", "rolling_mean_score")
    assert read["dor_count"] == 4


def test_the_remedial_flip_reads_the_terminally_weighted_variant_only(world):
    """A pooled mean of 4.50 and a weighted 4.80 both hold the rotation ACTIVE.

    PRD: "The two variants deliberately disagree, and only the terminally
    weighted one carries authority."

    Design: Difficulty/dual_variant_calc/terminal_weighted_vs_rolling_mean_diverge_on_late_slump
    """
    _curriculum, recruit, fto, rotation = _slumping_rotation(world)

    world.file_report(rotation["id"], fto["id"], "2027-03-13",
                      f.dimension_ratings(3))

    read = world.read_rotation(rotation["id"])
    assert read["status"] == "ACTIVE"
    assert read["remedial_flag_count"] == 0

    trainee = world.read_recruit(recruit["id"])
    assert trainee["probation_status"] == "NOT_APPLICABLE"


def test_the_attrition_report_publishes_the_pooled_variant_for_a_live_rotation(world):
    """rolling_mean_scores carries the rotation's pooled 4.50, not its 4.80.

    PRD: "That last is an object keyed by rotation identifier whose value is
    that rotation's rolling-mean score at 2 decimal places, or null while its
    `dor_count` is zero, covering every rotation of the cohort whose `status` is
    `ACTIVE` or `REMEDIAL`."

    Design: Difficulty/dual_variant_calc/terminal_weighted_vs_rolling_mean_diverge_on_late_slump
    """
    curriculum, _recruit, fto, rotation = _slumping_rotation(world)

    world.file_report(rotation["id"], fto["id"], "2027-03-13",
                      f.dimension_ratings(3))

    report = validate_success(world.client.get_attrition_analysis(
        curriculum["cohort"]["id"], director_headers()))
    assert_score_equals(report["rolling_mean_scores"][rotation["id"]], "4.50",
                        "rolling_mean_scores entry")


def _two_fitness_candidates(world):
    """Two recruits of the same age bracket, each with a fitness screening ordered."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)],
        fitness_event_floor_points=10, fitness_pass_score=60)
    cohort = world.create_cohort(standard["id"])
    weak = world.create_recruit(cohort["id"], full_name="Alba Reyes",
                                age_bracket="AGE_20_29")
    strong = world.create_recruit(cohort["id"], full_name="Boyd Chen",
                                  age_bracket="AGE_20_29")
    weak_screening = world.order_screening(weak["id"], "PHYSICAL_FITNESS")
    strong_screening = world.order_screening(strong["id"], "PHYSICAL_FITNESS")
    return {
        "standard": standard, "cohort": cohort,
        "weak": weak, "strong": strong,
        "weak_screening": weak_screening, "strong_screening": strong_screening,
    }


def test_four_event_tiers_sum_into_the_fitness_composite(world):
    """36, 38, 700 and 16 score 25 + 20 + 20 + 12 for the youngest bracket.

    PRD: "Each ratio earns points on a five-tier scale: 25 points at a ratio of
    at least 1.20; 20 points at a ratio of at least 1.00 but below 1.20; 12
    points at a ratio of at least 0.85 but below 1.00; 6 points at a ratio of at
    least 0.70 but below 0.85; and 0 points at a ratio below 0.70."

    Design: Difficulty/combinatorial_formula/fitness_composite_five_inputs_non_linear_floor_cap
    """
    built = _two_fitness_candidates(world)

    recorded = world.record_findings(
        built["strong_screening"]["id"], "PHYSICAL_FITNESS",
        raw_metrics=f.FITNESS_PASSING_METRICS)
    assert recorded["composite_score"] == 77

    cleared = world.adjudicate(built["strong_screening"]["id"],
                              "PHYSICAL_FITNESS", "CLEAR")
    assert cleared["status"] == "CLEARED"


def test_one_weak_event_caps_the_composite_below_the_pass_mark(world):
    """A raw total of 71 is capped at 59 because one event fell under the floor.

    PRD: "A non-linear gate then applies, and it is what makes a single weak
    event decisive: if the *smallest* of the four per-event point values is below
    the standard's `fitness_event_floor_points`, the composite is the lesser of
    the raw total and 59 - a hard cap that sits below the default pass mark no
    matter how strong the other three events were."

    Design: Difficulty/combinatorial_formula/fitness_composite_five_inputs_non_linear_floor_cap
    """
    built = _two_fitness_candidates(world)

    recorded = world.record_findings(
        built["weak_screening"]["id"], "PHYSICAL_FITNESS",
        raw_metrics=f.FITNESS_FLOOR_CAPPED_METRICS)
    assert recorded["composite_score"] == 59
    assert recorded["status"] == "FINDINGS_RECORDED"

    refused = world.client.adjudicate_screening(
        built["weak_screening"]["id"], f.adjudicate_payload("CLEAR"),
        coordinator_alt_headers())
    validate_error(refused, ERR_FITNESS_STANDARD_NOT_MET, 422)

    unchanged = validate_success(world.client.get_screening_record(
        built["weak_screening"]["id"], coordinator_headers()))
    assert unchanged["status"] == "FINDINGS_RECORDED"


def test_one_cleared_leg_of_four_leaves_the_clearance_partial(world):
    """A single cleared screening reads PARTIAL while an untouched one reads PENDING.

    PRD: "From `PENDING` it becomes `PARTIAL` when at least one of the recruit's
    screenings sits at `CLEARED` or `WAIVED`, fewer than four of them do, and
    none sits at `DISQUALIFIED`; a `PARTIAL` recruit stays in `pipeline_stage`
    `SCREENING`."

    Design: Difficulty/combinatorial_formula/fitness_composite_five_inputs_non_linear_floor_cap
    """
    built = _two_fitness_candidates(world)

    world.record_findings(built["weak_screening"]["id"], "PHYSICAL_FITNESS",
                          raw_metrics=f.FITNESS_FLOOR_CAPPED_METRICS)
    world.record_findings(built["strong_screening"]["id"], "PHYSICAL_FITNESS",
                          raw_metrics=f.FITNESS_PASSING_METRICS)
    world.adjudicate(built["strong_screening"]["id"], "PHYSICAL_FITNESS", "CLEAR")

    assert world.read_recruit(built["strong"]["id"])["clearance_status"] == "PARTIAL"
    assert world.read_recruit(built["weak"]["id"])["clearance_status"] == "PENDING"


def _probation_with_two_rotations(world):
    """A probationary recruit whose phase one ended before the milestone date."""
    curriculum = world.curriculum(topic_code=PATROL, required_hours=2.0,
                                 exam_required=False, min_total_hours=2.0,
                                 session_ends_at="2026-08-03T11:00:00Z",
                                 after_session="2026-08-03T11:00:00Z")
    recruit = world.recruit_in_field_training(curriculum)
    first_fto = world.create_certified_fto()
    second_fto = world.create_certified_fto()

    phase_one = world.plan_rotation(recruit, first_fto["id"], phase_number=1,
                                    start_date="2027-03-01",
                                    end_date="2027-03-31")
    world.activate_rotation(phase_one["id"])
    world.set_clock("2027-03-13T12:00:00Z")
    world.file_report(phase_one["id"], first_fto["id"], "2027-03-10",
                      f.dimension_ratings(6))
    world.set_clock("2027-03-31T12:00:00Z")
    world.complete_rotation(phase_one["id"])

    recruit = world.advance(recruit["id"], "PROBATION",
                            probation_start="2027-01-01",
                            probation_base_days=365)
    return {
        "curriculum": curriculum, "recruit": recruit,
        "first_fto": first_fto, "second_fto": second_fto,
        "phase_one": phase_one,
    }


def _add_slumping_phase_two(world, built):
    """Plan, activate and fill phase two with reports that slump to 4.80."""
    recruit = world.read_recruit(built["recruit"]["id"])
    phase_two = world.plan_rotation(
        recruit, built["second_fto"]["id"], phase_number=2,
        start_date="2027-04-01", end_date="2027-04-30",
        prior_rotation_id=built["phase_one"]["id"])
    world.activate_rotation(phase_two["id"])
    # A report may not be observed later than the clock's own date.
    world.set_clock("2027-04-08T12:00:00Z")
    for observed_on, rating in (("2027-04-05", 6), ("2027-04-06", 6),
                                ("2027-04-07", 3), ("2027-04-08", 3)):
        world.file_report(phase_two["id"], built["second_fto"]["id"],
                          observed_on, f.dimension_ratings(rating))
    world.set_clock("2027-04-30T12:00:00Z")
    return phase_two


def test_the_probation_milestone_reads_the_base_days_and_nothing_else(world):
    """365 base days from 2027-01-01 fix the milestone at 2027-07-02 throughout.

    PRD: "Step 1 derives `probation_milestone_due_date` from
    `probation_base_days` **only**: it is `probation_start` plus the floor of
    `probation_base_days` multiplied by one half, counted in days by exact
    calendar addition."

    Design: Difficulty/combinatorial_formula/probation_schedule_pinned_four_step_forward_pass
    """
    built = _probation_with_two_rotations(world)

    entered = built["recruit"]
    assert entered["probation_milestone_due_date"] == "2027-07-02"
    assert_score_equals(entered["probation_milestone_score"], "6.00",
                        "probation_milestone_score")
    assert entered["probation_extension_days"] == 0
    assert entered["probation_scheduled_end"] == "2028-01-01"

    phase_two = _add_slumping_phase_two(world, built)
    world.complete_rotation(phase_two["id"])

    after = world.read_recruit(built["recruit"]["id"])
    assert after["probation_milestone_due_date"] == "2027-07-02"


def test_the_milestone_score_selector_ranks_by_end_date_descending(world):
    """Phase two's later end date displaces phase one's higher score.

    PRD: "Eligible rows are ranked by `end_date` descending, with `created_at`
    descending as tie-break - never by identifier - and
    `probation_milestone_score` becomes the terminally weighted
    `competency_score` of the top-ranked row."

    Design: Difficulty/combinatorial_formula/probation_schedule_pinned_four_step_forward_pass
    """
    built = _probation_with_two_rotations(world)
    phase_two = _add_slumping_phase_two(world, built)

    completed = world.complete_rotation(phase_two["id"])
    assert completed["status"] == "COMPLETED"
    assert_score_equals(completed["competency_score"], "4.80", "competency_score")
    assert_score_equals(completed["rolling_mean_score"], "4.50",
                        "rolling_mean_score")

    after = world.read_recruit(built["recruit"]["id"])
    assert_score_equals(after["probation_milestone_score"], "4.80",
                        "probation_milestone_score")
    assert after["probation_extension_days"] == 30
    assert after["probation_scheduled_end"] == "2028-01-31"
    assert after["probation_status"] == "ACTIVE"
    assert after["probation_base_days"] == 365


def test_closing_a_rotation_releases_the_officers_trainee_load(world):
    """The officer's conserved trainee count falls back to zero on completion.

    PRD: "The rotation moves to `COMPLETED`, which is terminal, the
    `final_narrative` is stored, the officer's `active_trainee_count` falls by
    one, and the trainee re-derives the probation schedule whenever
    `probation_start` is not null."

    Design: Difficulty/combinatorial_formula/probation_schedule_pinned_four_step_forward_pass
    """
    built = _probation_with_two_rotations(world)
    phase_two = _add_slumping_phase_two(world, built)

    loaded = validate_success(world.client.get_instructor(
        built["second_fto"]["id"], director_headers()))
    assert loaded["active_trainee_count"] == 1

    world.complete_rotation(phase_two["id"])

    released = validate_success(world.client.get_instructor(
        built["second_fto"]["id"], director_headers()))
    assert released["active_trainee_count"] == 0

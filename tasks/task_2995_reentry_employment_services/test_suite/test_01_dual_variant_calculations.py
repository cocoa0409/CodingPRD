"""
Two-variant computations that read the same rows through different filters.

The wage subsidy is stored twice on a placement, once for what is scheduled and
once for what was actually worked, and the funder outcome report is available
under two denominators over the same placements. In both cases a single input set
must produce two different, simultaneously visible numbers.
"""

from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_nullable_rate,
    assert_one_decimal_place,
    validate_unpaginated,
)
from test_helpers.constants import (
    EMPLOYMENT_ACTIVE,
    EMPLOYMENT_SEPARATED,
    FUNDING_POSTURE_OPEN,
    RECIDIVISM_TECHNICAL_VIOLATION,
    REPORT_VARIANT_COHORT,
    REPORT_VARIANT_EXIT_BASED,
    RETENTION_RETAINED,
    RETENTION_UNREACHABLE,
    SEPARATION_LAYOFF,
    SHIFT_SCHEDULED,
    SHIFT_WORKED,
    STAGE_EXITED,
    STAGE_PLACED,
    EXIT_EMPLOYED_STABLE,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
)


def _placement_with_two_shifts(api, build):
    """A live subsidised placement holding two eight-hour shifts."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    build.case_authorized(participant["id"])
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])
    first = build.work_shift(
        placement["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"
    )
    second = build.work_shift(
        placement["id"], "2026-08-04T09:00:00.000Z", "2026-08-04T17:00:00.000Z"
    )
    return grant, participant, opening, placement, first, second


def test_projected_variant_keeps_the_scheduled_shift_that_actual_variant_drops(
    api, build, clock
):
    """
    The projected and actual subsidy figures diverge on one shift set.

    PRD section 3.7: "The **projected** variant, stored in
    `projected_subsidy_cents`, reads the placement's shifts whose `status` is
    `SCHEDULED` or `WORKED`; this is the figure the grant's `committed_cents`
    holds while the placement is active."

    Two eight-hour shifts at 1850 cents an hour sit wholly inside the first
    subsidy tier, so sixteen scheduled hours project 14,800 cents while the one
    worked shift accounts for only 7,400 of them.

    Design: Difficulty/dual_variant_calc/projected_vs_actual_wage_subsidy_diverge_on_same_shift_set
    """
    grant, participant, opening, placement, first, second = _placement_with_two_shifts(
        api, build
    )

    clock.set("2026-08-03T18:00:00.000Z")
    worked = validate_unpaginated(
        api.set_work_shift_status(first["id"], f.shift_status_payload(SHIFT_WORKED), CASE_MANAGER)
    )
    assert worked["status"] == SHIFT_WORKED
    assert worked["scheduled_hours"] == 8.0

    still_scheduled = validate_unpaginated(api.get_work_shift(second["id"], CASE_MANAGER))
    assert still_scheduled["status"] == SHIFT_SCHEDULED

    settled = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(settled, "projected_subsidy_cents", 14800)
    assert_money_cents(settled, "actual_subsidy_cents", 7400)
    assert settled["projected_subsidy_cents"] != settled["actual_subsidy_cents"]
    assert_money_cents(settled, "disbursed_subsidy_cents", 0)
    assert settled["employment_status"] == EMPLOYMENT_ACTIVE
    assert_int_field(settled, "match_score", 75)


def test_grant_ledger_commits_the_projected_figure_while_the_placement_is_active(
    api, build, clock
):
    """
    The ledger holds the projected figure, not the worked-only figure.

    PRD section 3.8: "`committed_cents` is the sum of `total_charge_cents` across
    every support request on this grant whose `status` is `APPROVED`, plus the sum
    of `projected_subsidy_cents` across every placement on this grant whose
    `employment_status` is `ACTIVE`."

    Design: Difficulty/dual_variant_calc/projected_vs_actual_wage_subsidy_diverge_on_same_shift_set
    """
    grant, participant, opening, placement, first, second = _placement_with_two_shifts(
        api, build
    )

    clock.set("2026-08-03T18:00:00.000Z")
    validate_unpaginated(
        api.set_work_shift_status(first["id"], f.shift_status_payload(SHIFT_WORKED), CASE_MANAGER)
    )

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "authorized_cents", 5000000)
    assert_money_cents(ledger, "committed_cents", 14800)
    assert_money_cents(ledger, "disbursed_cents", 0)
    assert_money_cents(ledger, "available_cents", 4985200)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(ledger)


def _two_started_placements_one_exited(api, build, clock):
    """Two placements on one opening, of which one separates and exits."""
    grant = build.grant(
        authorized_cents=5000000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])

    first_participant = build.participant_released()
    second_participant = build.participant_released(full_name="Rosalind Frey")
    first_placement = build.placement_active(
        first_participant["id"], opening["id"], grant["id"]
    )
    second_placement = build.placement_active(
        second_participant["id"], opening["id"], grant["id"]
    )

    clock.set("2026-11-02T09:00:00.000Z")
    validate_unpaginated(
        api.record_retention_check(
            first_placement["id"],
            f.retention_check_payload(90, RETENTION_RETAINED),
            CASE_MANAGER,
        )
    )
    validate_unpaginated(
        api.record_retention_check(
            second_placement["id"],
            f.retention_check_payload(
                90, RETENTION_UNREACHABLE, RECIDIVISM_TECHNICAL_VIOLATION
            ),
            CASE_MANAGER,
        )
    )
    validate_unpaginated(
        api.separate_placement(
            first_placement["id"],
            f.separation_payload(SEPARATION_LAYOFF, "2026-11-02"),
            EMPLOYER_LIAISON,
        )
    )
    validate_unpaginated(
        api.exit_participant(
            first_participant["id"],
            f.exit_payload(EXIT_EMPLOYED_STABLE, "2026-11-02"),
            PROGRAM_DIRECTOR,
        )
    )
    return grant, first_participant, second_participant, first_placement, second_placement


def test_cohort_variant_counts_every_started_placement_regardless_of_exit(
    api, build, clock
):
    """
    The default denominator spans started placements whether or not the
    participant's case is closed.

    PRD section 3.9: "Under `COHORT` — the default, used when `variant` is
    omitted or equals `COHORT` — the input set is every placement on this grant
    whose `employment_status` is `ACTIVE` or `SEPARATED`, that is, every placement
    that actually started, regardless of whether the participant has exited."

    Design: Difficulty/dual_variant_calc/outcome_report_cohort_vs_exit_based_denominators
    """
    grant, first, second, first_placement, second_placement = (
        _two_started_placements_one_exited(api, build, clock)
    )

    report = validate_unpaginated(
        api.get_outcome_report(
            grant["id"], FUNDER_ANALYST, f.outcome_report_params(REPORT_VARIANT_COHORT)
        )
    )
    assert report["variant"] == REPORT_VARIANT_COHORT
    assert_int_field(report, "denominator_placements", 2)
    assert_int_field(report, "retained_placements", 1)
    assert_int_field(report, "participants_served", 2)
    assert_one_decimal_place(report, "retention_rate_pct", 50.0)
    assert_one_decimal_place(report, "recidivism_rate_pct", 50.0)
    assert report["benchmark_met"] is False

    separated = validate_unpaginated(api.get_placement(first_placement["id"], CASE_MANAGER))
    assert separated["employment_status"] == EMPLOYMENT_SEPARATED
    active = validate_unpaginated(api.get_placement(second_placement["id"], CASE_MANAGER))
    assert active["employment_status"] == EMPLOYMENT_ACTIVE


def test_exit_based_variant_narrows_the_same_rows_to_exited_participants(
    api, build, clock
):
    """
    The closed-case denominator keeps only the placements of exited participants,
    which lifts the very same numerator to a passing rate.

    PRD section 3.9: "Under `EXIT_BASED` the input set is narrowed to those same
    started placements whose participant's `stage` is `EXITED`, which is the
    closed-case denominator funders use for final reporting."

    Design: Difficulty/dual_variant_calc/outcome_report_cohort_vs_exit_based_denominators
    """
    grant, first, second, first_placement, second_placement = (
        _two_started_placements_one_exited(api, build, clock)
    )

    report = validate_unpaginated(
        api.get_outcome_report(
            grant["id"], FUNDER_ANALYST, f.outcome_report_params(REPORT_VARIANT_EXIT_BASED)
        )
    )
    assert report["variant"] == REPORT_VARIANT_EXIT_BASED
    assert_int_field(report, "denominator_placements", 1)
    assert_int_field(report, "retained_placements", 1)
    assert_int_field(report, "participants_served", 1)
    assert_nullable_rate(report, "retention_rate_pct", 100.0)
    assert_nullable_rate(report, "recidivism_rate_pct", 0.0)
    assert report["benchmark_met"] is True

    exited = validate_unpaginated(api.get_participant(first["id"], CASE_MANAGER))
    assert exited["stage"] == STAGE_EXITED
    placed = validate_unpaginated(api.get_participant(second["id"], CASE_MANAGER))
    assert placed["stage"] == STAGE_PLACED

"""Dual-variant figures: the two billable-night counts and the two risk figures.

Each pair shares its inputs and diverges only in the rule applied, so the tests
here pin both members of the pair on one fixture and check the delta between
them as well as the individual values.
"""

from test_helpers import (
    CASE_MANAGER,
    assert_admission,
    assert_safety_screening,
    assert_youth,
    clear_screening,
    discharge,
    fetch_admission,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    log_outreach_contact,
    move_clock,
    request_admission,
    run_census,
    submit_screening,
)

# ─── Instance: projected versus chronological-actual billable nights ───

SEVEN_NIGHT_PLANNED_DISCHARGE = instant("2026-08-08")
DISCHARGE_AFTER_NOON = instant("2026-08-08", "15:00:00")


def _seven_night_active_stay():
    """A youth aged 16 at the clock's start holding an `ACTIVE` admission that
    runs from the clock instant to a planned discharge seven days later."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter",
        licensed_bed_capacity=2,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    youth = intake_youth(
        legal_first_name="Ava",
        legal_last_name="Reyes",
        date_of_birth="2010-03-15",
        unaccompanied=True,
    )
    clear_screening(youth["id"])
    admission = request_admission(
        youth["id"], program["id"], SEVEN_NIGHT_PLANNED_DISCHARGE
    )
    return program, youth, admission


def test_projected_billable_nights_counts_calendar_days_to_planned_discharge(api):
    """PRD §3.5: "It is the number of whole calendar days from the calendar date
    of `admitted_at` to the calendar date of `planned_discharge_at`."
    PRD §3.5: "The planned discharge date is never itself a billable night, and
    the clock-time component of both instants is ignored entirely, so this figure
    can never award the noon-cutoff night described below."
    PRD §3.5: "It is null until the admission is discharged."

    Design: Difficulty/dual_variant_calc/admission_billable_nights_projected_versus_chronological_actual
    """
    _program, _youth, admission = _seven_night_active_stay()

    assert_admission(admission)
    assert admission["status"] == "ACTIVE", (
        f"A cleared screening admits straight into the bed, got {admission['status']}"
    )
    assert admission["projected_billable_nights"] == 7, (
        "2026-08-01 to 2026-08-08 is seven whole calendar days, so "
        f"projected_billable_nights should be 7, got {admission['projected_billable_nights']}"
    )
    assert admission["final_billable_nights"] is None, (
        "final_billable_nights stays null until discharge, got "
        f"{admission['final_billable_nights']}"
    )


def test_final_billable_nights_adds_the_noon_cutoff_night(api):
    """PRD §3.5: "At discharge it is the number of whole calendar days from the
    calendar date of `admitted_at` to the calendar date of `discharged_at`, plus
    one further night when the hour of the discharge instant is at or after
    twelve — a youth still in the bed at or after 12:00:00Z on the discharge date
    has occupied that night's bed for federal reporting purposes."
    PRD §3.5: "Consequently, a youth discharged on the planned date at 15:00Z
    ends with exactly one night more than was projected."

    Design: Difficulty/dual_variant_calc/admission_billable_nights_projected_versus_chronological_actual
    """
    _program, _youth, admission = _seven_night_active_stay()
    projected = admission["projected_billable_nights"]

    move_clock(DISCHARGE_AFTER_NOON)
    discharged = discharge(admission["id"], "TRANSITIONAL_LIVING")

    assert discharged["status"] == "DISCHARGED", (
        f"Discharge from ACTIVE is terminal, got {discharged['status']}"
    )
    assert discharged["final_billable_nights"] == 8, (
        "seven calendar days plus the 15:00Z cutoff night is 8 nights, got "
        f"{discharged['final_billable_nights']}"
    )
    assert discharged["final_billable_nights"] - projected == 1, (
        "the chronological-actual figure exceeds the projected figure by exactly "
        f"one night, got {discharged['final_billable_nights']} against {projected}"
    )
    assert discharged["projected_billable_nights"] == 7, (
        "discharge never revises the forward-looking figure, got "
        f"{discharged['projected_billable_nights']}"
    )
    assert discharged["outcome_positive"] is True, (
        "a TRANSITIONAL_LIVING destination is a positive outcome, got "
        f"{discharged['outcome_positive']}"
    )


def test_discharge_accrues_final_nights_onto_the_youth_and_frees_the_bed(api):
    """PRD §3.5: "the youth's `cumulative_shelter_nights` rises by the final
    billable nights, and the youth's `status` moves to `REUNIFIED` if the youth
    was in `REUNIFIED_PENDING` and the destination is `FAMILY_REUNIFIED`, and
    otherwise to `EXITED`, with the youth's `version` incremented by one and
    `governance_vote_eligible` recomputed to false either way."
    PRD §3.5: "Second, because the admission has left the set of bed-holding
    statuses, the program's `occupied_beds` falls by one."

    Design: Difficulty/dual_variant_calc/admission_billable_nights_projected_versus_chronological_actual
    """
    program, youth, admission = _seven_night_active_stay()

    move_clock(DISCHARGE_AFTER_NOON)
    discharge(admission["id"], "TRANSITIONAL_LIVING")

    after = fetch_youth(youth["id"])
    assert_youth(after)
    assert after["cumulative_shelter_nights"] == 8, (
        "the youth accrues the chronological-actual figure of 8 nights, got "
        f"{after['cumulative_shelter_nights']}"
    )
    assert after["status"] == "EXITED", (
        f"a TRANSITIONAL_LIVING exit leaves the youth EXITED, got {after['status']}"
    )
    assert after["governance_vote_eligible"] is False, (
        "discharge recomputes governance_vote_eligible to false, got "
        f"{after['governance_vote_eligible']}"
    )

    released = fetch_program(program["id"])
    assert released["occupied_beds"] == 0, (
        f"the discharged stay releases its bed, got {released['occupied_beds']}"
    )
    stay = fetch_admission(admission["id"])
    assert stay["final_billable_nights"] == 8, (
        f"the finalized figure is durable on the row, got {stay['final_billable_nights']}"
    )


# ─── Instance: screening snapshot versus decayed outreach history ───

TWO_WEEKS_LATER = instant("2026-08-16")
CONTROL_AND_DEBT = ["THIRD_PARTY_CONTROL", "QUOTA_DEBT"]


def _youth_with_fifteen_day_old_indicators():
    """A youth carrying one outreach encounter logged at the clock's start whose
    indicator set is worth 30 plus 25 points, read fifteen days later."""
    youth = intake_youth(
        legal_first_name="Kai",
        legal_last_name="Osei",
        date_of_birth="2010-05-04",
        unaccompanied=True,
    )
    log_outreach_contact(
        youth["id"],
        engagement_stage="RAPPORT_BUILDING",
        basic_needs_provided=["FOOD", "HYGIENE_KIT"],
        indicator_flags=list(CONTROL_AND_DEBT),
    )
    move_clock(TWO_WEEKS_LATER)
    return youth


def test_screening_score_is_the_undecayed_indicator_snapshot(api):
    """PRD §3.2: "The screening's own `score` is the **undecayed snapshot** of
    exactly one indicator set: the sum of the weights of the distinct codes
    supplied on this screening, capped at 100, with no decay of any kind applied
    and no other screening or contact participating."
    PRD §3.1: "`THIRD_PARTY_CONTROL` is worth 30 points, `QUOTA_DEBT` 25,
    `COMMERCIAL_SEX` 40, `DOCUMENT_WITHHELD` 20, `RECRUITER_PRESENT` 15 and
    `CURFEW_ENFORCED` 10."
    PRD §3.2: "The server stamps `screened_at` with the clock instant, records the
    submitter as `screener_user_id`, and opens the screening in `status`
    `SUBMITTED` with `disposition_user_id` still null."

    Design: Difficulty/dual_variant_calc/trafficking_risk_score_screening_snapshot_versus_decayed_outreach_history
    """
    youth = _youth_with_fifteen_day_old_indicators()

    screening = submit_screening(youth["id"], CONTROL_AND_DEBT, CASE_MANAGER)

    assert_safety_screening(screening)
    assert screening["score"] == 55, (
        "30 for THIRD_PARTY_CONTROL plus 25 for QUOTA_DEBT is 55 undecayed "
        f"points, got {screening['score']}"
    )
    assert screening["tier"] == "ELEVATED", (
        f"a score of 55 tiers as ELEVATED, got {screening['tier']}"
    )
    assert screening["status"] == "SUBMITTED", (
        f"a fresh screening opens in SUBMITTED, got {screening['status']}"
    )
    assert screening["disposition_user_id"] is None, (
        f"an undispositioned screening carries no disposition_user_id, got "
        f"{screening['disposition_user_id']}"
    )


def test_youth_history_score_decays_ten_points_per_completed_week(api):
    """PRD §3.1: "For each contact it takes the whole number of days between that
    contact's `contacted_at` and the current clock, divides by seven and floors to
    get the number of completed weeks, and derives a retained percentage of one
    hundred minus ten percentage points for each completed week, held at a floor
    of zero so a contact older than ten weeks contributes nothing."
    PRD §3.1: "because every completed week strips ten percentage points off each
    contribution and each contribution is floored individually, an identical
    indicator set scores strictly lower as history than it does at screening time
    once any contact is at least seven days old."
    PRD §3.10: "and every youth's `trafficking_risk_score` is re-decayed against
    the new clock by the history rule of §3.1, with every program posture and
    youth posture recomputed at the end."

    Design: Difficulty/dual_variant_calc/trafficking_risk_score_screening_snapshot_versus_decayed_outreach_history
    """
    youth = _youth_with_fifteen_day_old_indicators()
    screening = submit_screening(youth["id"], CONTROL_AND_DEBT, CASE_MANAGER)

    run_census()

    after = fetch_youth(youth["id"])
    assert_youth(after)
    assert after["trafficking_risk_score"] == 44, (
        "fifteen days is two completed weeks, so 55 raw points retain eighty "
        f"percent and floor to 44, got {after['trafficking_risk_score']}"
    )
    assert after["trafficking_risk_tier"] == "ELEVATED", (
        f"a score of 44 tiers as ELEVATED, got {after['trafficking_risk_tier']}"
    )
    assert screening["score"] - after["trafficking_risk_score"] == 11, (
        "the same indicator set reads 55 at screening time and 44 as history, a "
        f"delta of 11, got {screening['score']} against {after['trafficking_risk_score']}"
    )


def test_submitted_screening_leaves_the_youth_risk_posture_open(api):
    """PRD §3.2: "A screening in `SUBMITTED` never freezes a youth on its own; the
    youth's `risk_posture` is recomputed on submission, but only a disposition can
    drive it to `FROZEN`."
    PRD §2.7: "the posture is `FROZEN` when the most recent screening exists and
    is in status `ESCALATED`; otherwise it is `RESTRICTED` when an open
    notification obligation exists or the youth's `trafficking_risk_tier` is
    `CRITICAL`; otherwise it is `OPEN`."

    Design: Difficulty/dual_variant_calc/trafficking_risk_score_screening_snapshot_versus_decayed_outreach_history
    """
    youth = _youth_with_fifteen_day_old_indicators()
    submit_screening(youth["id"], CONTROL_AND_DEBT, CASE_MANAGER)

    run_census()

    after = fetch_youth(youth["id"])
    assert after["trafficking_risk_tier"] == "ELEVATED", (
        "an ELEVATED tier is below the CRITICAL restriction clause, got "
        f"{after['trafficking_risk_tier']}"
    )
    assert after["risk_posture"] == "OPEN", (
        "with no escalated screening and no notification obligation the youth "
        f"stands OPEN, got {after['risk_posture']}"
    )

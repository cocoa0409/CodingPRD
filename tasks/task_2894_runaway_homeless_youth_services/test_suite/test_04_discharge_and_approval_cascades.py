"""Transitive cascades: every hop is caused by the hop before it.

Discharging the only occupant frees a bed, which reopens the program, which is
the only reason the waitlist selector can run; approving a reunification case
reaches across aggregate roots to schedule a discharge without releasing a bed.
"""

from test_helpers import (
    USER_IDS,
    assert_admission,
    assert_guardian_notification,
    assert_reunification_case,
    assert_instant_equals,
    assert_program_counters,
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
    notification_of_admission,
    request_admission,
    setup_approved_case,
)

# ─── Instance: discharge frees a bed, promotes the waitlist, mints the obligation ───

DISCHARGE_CLOCK = instant("2026-08-05", "10:00:00")
OCCUPANT_PLANNED_DISCHARGE = instant("2026-08-20")
WAITLIST_PLANNED_DISCHARGE = instant("2026-08-25")


def _frozen_one_bed_program_with_two_waitlisted():
    """A one-bed program whose single bed is taken, with two cleared youths of
    different priority scores resting on the waitlist."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter",
        licensed_bed_capacity=1,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    occupant = intake_youth(
        legal_first_name="Ava", legal_last_name="Reyes",
        date_of_birth="2010-03-15", unaccompanied=True,
    )
    clear_screening(occupant["id"])
    occupant_admission = request_admission(
        occupant["id"], program["id"], OCCUPANT_PLANNED_DISCHARGE
    )

    higher = intake_youth(
        legal_first_name="Bo", legal_last_name="Nakamura",
        date_of_birth="2012-06-10", unaccompanied=True,
    )
    log_outreach_contact(higher["id"], engagement_stage="FIRST_CONTACT",
                         basic_needs_provided=["FOOD"], indicator_flags=[])
    log_outreach_contact(higher["id"], engagement_stage="RAPPORT_BUILDING",
                         basic_needs_provided=["HYGIENE_KIT"], indicator_flags=[])
    clear_screening(higher["id"])
    higher_admission = request_admission(
        higher["id"], program["id"], WAITLIST_PLANNED_DISCHARGE
    )

    lower = intake_youth(
        legal_first_name="Cy", legal_last_name="Ferrer",
        date_of_birth="2014-01-20", unaccompanied=True,
    )
    clear_screening(lower["id"])
    lower_admission = request_admission(
        lower["id"], program["id"], WAITLIST_PLANNED_DISCHARGE
    )
    return {
        "program": program,
        "occupant": occupant,
        "occupant_admission": occupant_admission,
        "higher": higher,
        "higher_admission": higher_admission,
        "lower": lower,
        "lower_admission": lower_admission,
    }


def test_discharge_finalizes_the_stay_and_releases_the_bed(api):
    """PRD §3.5: "First, `discharged_at` is stamped with the clock instant, the
    supplied `exit_destination` is stored, `final_billable_nights` is computed by
    the chronological-actual rule, and `outcome_positive` is derived as true exactly
    when the destination is `FAMILY_REUNIFIED`, `TRANSITIONAL_LIVING` or
    `INDEPENDENT_HOUSING` and false otherwise — the field is null until discharge;
    the youth's `cumulative_shelter_nights` rises by the final billable nights, and
    the youth's `status` moves to `REUNIFIED` if the youth was in
    `REUNIFIED_PENDING` and the destination is `FAMILY_REUNIFIED`, and otherwise to
    `EXITED`, with the youth's `version` incremented by one and
    `governance_vote_eligible` recomputed to false either way."

    Design: Difficulty/transitive_cascade/discharge_releases_bed_then_promotes_waitlist_then_creates_notification
    """
    setup = _frozen_one_bed_program_with_two_waitlisted()
    assert setup["higher_admission"]["status"] == "WAITLISTED", (
        "the frozen program diverts the request onto the waitlist, got "
        f"{setup['higher_admission']['status']}"
    )

    move_clock(DISCHARGE_CLOCK)
    discharged = discharge(setup["occupant_admission"]["id"], "OTHER_SHELTER")

    assert discharged["status"] == "DISCHARGED", (
        f"the stay is terminal, got {discharged['status']}"
    )
    assert discharged["final_billable_nights"] == 4, (
        "2026-08-01 to 2026-08-05 is four calendar days and a 10:00Z discharge "
        f"earns no cutoff night, got {discharged['final_billable_nights']}"
    )
    assert discharged["outcome_positive"] is False, (
        "an OTHER_SHELTER destination is not a positive outcome, got "
        f"{discharged['outcome_positive']}"
    )
    exited = fetch_youth(setup["occupant"]["id"])
    assert exited["status"] == "EXITED", (
        f"the discharged youth leaves the program, got {exited['status']}"
    )
    assert exited["cumulative_shelter_nights"] == 4, (
        f"four final nights accrue to the youth, got {exited['cumulative_shelter_nights']}"
    )


def test_freed_bed_promotes_the_highest_priority_waitlisted_admission(api):
    """PRD §3.3: "Candidates are ranked by `priority_score` in descending order,
    with earlier `created_at` breaking a tie in favour of the longer-waiting youth."
    PRD §3.3: "Exactly one candidate is promoted per freeing event, and an empty
    candidate set is simply a no-op rather than an error."
    PRD §3.3: "Promotion clears `capacity_blocked` back to false, stamps
    `admitted_at` with the promotion clock instant, recomputes
    `projected_billable_nights` against the **original** `planned_discharge_at`,
    lowers the program's `waitlisted_count` by one, raises the program's
    `occupied_beds` by one — which again forces `utilization_bp` and `posture` to be
    recomputed and can drive the program straight back to `FROZEN` — creates that
    admission's own parental-notification obligation in `PENDING` with a due instant
    twenty-four hours after the promotion, which flips that youth's `risk_posture`
    to `RESTRICTED`, and moves that youth's `status` to `SHELTERED` with the youth's
    `version` incremented by one."

    Design: Difficulty/transitive_cascade/discharge_releases_bed_then_promotes_waitlist_then_creates_notification
    """
    setup = _frozen_one_bed_program_with_two_waitlisted()
    assert setup["higher_admission"]["priority_score"] == 41, (
        "sixteen age points plus ten engagement points plus fifteen exposure "
        f"points is 41, got {setup['higher_admission']['priority_score']}"
    )
    assert setup["lower_admission"]["priority_score"] == 39, (
        "twenty-four age points plus fifteen exposure points is 39, got "
        f"{setup['lower_admission']['priority_score']}"
    )

    move_clock(DISCHARGE_CLOCK)
    discharge(setup["occupant_admission"]["id"], "OTHER_SHELTER")

    promoted = fetch_admission(setup["higher_admission"]["id"])
    assert promoted["status"] == "ACTIVE", (
        f"the higher-scoring candidate takes the freed bed, got {promoted['status']}"
    )
    assert_instant_equals(promoted["admitted_at"], DISCHARGE_CLOCK,
                          "the promoted admission's admitted_at")
    assert promoted["projected_billable_nights"] == 20, (
        "2026-08-05 to the original 2026-08-25 planned discharge is twenty "
        f"calendar days, got {promoted['projected_billable_nights']}"
    )
    passed_over = fetch_admission(setup["lower_admission"]["id"])
    assert passed_over["status"] == "WAITLISTED", (
        f"only one candidate is promoted per freeing event, got {passed_over['status']}"
    )

    program = fetch_program(setup["program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 1, (
        f"the promotion re-consumes the single bed, got {program['occupied_beds']}"
    )
    assert program["waitlisted_count"] == 1, (
        f"one candidate is left waiting, got {program['waitlisted_count']}"
    )
    assert program["utilization_bp"] == 10000, (
        f"one of one bed is 10000 basis points, got {program['utilization_bp']}"
    )
    assert program["posture"] == "FROZEN", (
        f"the refilled bed drives the program straight back to FROZEN, got {program['posture']}"
    )


def test_promotion_mints_the_promoted_youths_own_notification(api):
    """PRD §3.4: "The obligation references its admission through `admission_id`,
    opens in `status` `PENDING` with `attempt_count` at 0, `last_attempt_at` null and
    `resolved_at` null, and carries a `due_at` computed as the admission's
    `admitted_at` plus twenty-four hours."
    PRD §3.5: "Fifth, the promoted admission's own parental-notification obligation
    is created in `PENDING`, which flips that second youth's `risk_posture` to
    `RESTRICTED`."

    Design: Difficulty/transitive_cascade/discharge_releases_bed_then_promotes_waitlist_then_creates_notification
    """
    setup = _frozen_one_bed_program_with_two_waitlisted()

    move_clock(DISCHARGE_CLOCK)
    discharge(setup["occupant_admission"]["id"], "OTHER_SHELTER")

    notification = notification_of_admission(setup["higher_admission"]["id"])
    assert_guardian_notification(notification)
    assert notification["status"] == "PENDING", (
        f"the fresh obligation opens in PENDING, got {notification['status']}"
    )
    assert notification["attempt_count"] == 0, (
        f"no attempt has been recorded yet, got {notification['attempt_count']}"
    )
    assert notification["last_attempt_at"] is None, (
        f"last_attempt_at is null on a fresh obligation, got {notification['last_attempt_at']}"
    )
    assert_instant_equals(notification["due_at"], instant("2026-08-06", "10:00:00"),
                          "the obligation's due_at")

    promoted_youth = fetch_youth(setup["higher"]["id"])
    assert promoted_youth["status"] == "SHELTERED", (
        f"the promoted youth is sheltered, got {promoted_youth['status']}"
    )
    assert promoted_youth["risk_posture"] == "RESTRICTED", (
        "the new pending obligation restricts the promoted youth, got "
        f"{promoted_youth['risk_posture']}"
    )
    untouched = fetch_youth(setup["lower"]["id"])
    assert untouched["status"] == "PROSPECT", (
        f"a waitlisted request never touches the youth's status, got {untouched['status']}"
    )


# ─── Instance: approval waives the obligation and schedules the discharge ───

MEDIATION_CLOCK = instant("2026-08-03", "15:00:00")
AFTERCARE_DUE = instant("2026-08-06", "15:00:00")
LAKEVIEW = {
    "name": "Lakeview Emergency Shelter",
    "licensed_bed_capacity": 2,
    "min_age_years": 12,
    "max_age_years": 17,
}
LENA = {
    "legal_first_name": "Lena",
    "legal_last_name": "Ortiz",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}


def _approved_reunification_case():
    """A sheltered youth whose case has cleared mediation with an `AGREEMENT`, a
    `SAFE` home assessment and an approval signed by a second specialist, with the
    guardian obligation still open at one recorded attempt when the approval lands."""
    return setup_approved_case(
        "SAFE",
        "ATTEMPTED",
        outcome="AGREEMENT",
        program_overrides=dict(LAKEVIEW),
        youth_overrides=dict(LENA),
        planned_discharge_at=instant("2026-08-15"),
    )


def test_approval_opens_the_aftercare_window_and_moves_the_youth(api):
    """PRD §3.6: "An accepted approval fires a four-hop cascade."
    PRD §3.6: "The case's `aftercare_plan_due_at` is set to the clock instant plus
    seventy-two hours and the case moves to `APPROVED`."
    PRD §3.6: "Because the case became approved, the youth moves `SHELTERED →
    REUNIFIED_PENDING`, the youth's `risk_posture` is recomputed and the youth's
    `version` increments by one."
    PRD §3.6: "Both branches store the acting identifier as `decision_user_id`."

    Design: Difficulty/transitive_cascade/reunification_approval_waives_notification_then_schedules_discharge
    """
    setup = _approved_reunification_case()
    case = setup["case"]

    assert_reunification_case(case)
    assert case["status"] == "APPROVED", (
        f"the accepted approval moves the case to APPROVED, got {case['status']}"
    )
    assert case["safety_assessment_result"] == "SAFE", (
        f"the recorded verdict stands, got {case['safety_assessment_result']}"
    )
    assert_instant_equals(case["aftercare_plan_due_at"], AFTERCARE_DUE,
                          "the case's aftercare_plan_due_at")
    assert case["decision_user_id"] == USER_IDS["REUNIFICATION_SPECIALIST"], (
        "the deciding specialist is stamped onto the case, got "
        f"{case['decision_user_id']}"
    )
    youth = setup["youth"]
    assert youth["status"] == "REUNIFIED_PENDING", (
        f"the approval moves the youth out of SHELTERED, got {youth['status']}"
    )


def test_scheduled_discharge_keeps_the_bed_and_leaves_the_stay_unfinalized(api):
    """PRD §3.6: "Because the youth became `REUNIFIED_PENDING`, every admission of
    the youth in `ACTIVE` or `EXTENDED` moves to `DISCHARGE_SCHEDULED`."
    PRD §3.5: "The bed is still held, so the program's `occupied_beds` is
    deliberately unchanged by that move; what does change is the admission's
    notification obligation, which is waived as described in §3.4."

    Design: Difficulty/transitive_cascade/reunification_approval_waives_notification_then_schedules_discharge
    """
    setup = _approved_reunification_case()
    admission = setup["admission"]

    assert_admission(admission)
    assert admission["status"] == "DISCHARGE_SCHEDULED", (
        "the approval reserves the bed for the reunification, got "
        f"{admission['status']}"
    )
    assert admission["discharged_at"] is None, (
        f"no discharge has been performed yet, got {admission['discharged_at']}"
    )
    assert admission["final_billable_nights"] is None, (
        "the stay is not finalized until discharge, got "
        f"{admission['final_billable_nights']}"
    )

    program = fetch_program(setup["program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 1, (
        f"the reserved bed is still counted as occupied, got {program['occupied_beds']}"
    )
    assert program["utilization_bp"] == 5000, (
        f"one of two beds is 5000 basis points, got {program['utilization_bp']}"
    )
    assert program["posture"] == "OPEN", (
        f"half a program's beds and no overdue obligation is OPEN, got {program['posture']}"
    )


def test_approval_waives_the_open_obligation_by_court_order(api):
    """PRD §3.6: "And because each such admission left its bed-holding operational
    state, each of those admissions' guardian notifications standing in `PENDING`,
    `ATTEMPTED` or `OVERDUE` is waived with `waiver_reason` `COURT_ORDER`, which
    recomputes the owning program's `overdue_notification_count` and `posture`."
    PRD §3.4: "One further path into `WAIVED` exists and is not client-driven: when
    a reunification case for the youth is approved, each of that youth's still-open
    obligations — those in `PENDING`, `ATTEMPTED` or `OVERDUE` — is waived by the
    server with `waiver_reason` set to `COURT_ORDER`, `resolved_at` set to the clock
    instant, and `resolving_user_id` set to the identifier that decided the case."

    Design: Difficulty/transitive_cascade/reunification_approval_waives_notification_then_schedules_discharge
    """
    setup = _approved_reunification_case()
    notification = setup["notification"]

    assert_guardian_notification(notification)
    assert notification["status"] == "WAIVED", (
        f"the server waives the still-open obligation, got {notification['status']}"
    )
    assert notification["waiver_reason"] == "COURT_ORDER", (
        f"the server-driven waiver reason is COURT_ORDER, got {notification['waiver_reason']}"
    )
    assert notification["attempt_count"] == 1, (
        "the single recorded attempt is preserved through the waiver, got "
        f"{notification['attempt_count']}"
    )
    assert_instant_equals(notification["resolved_at"], MEDIATION_CLOCK,
                          "the waived obligation's resolved_at")
    assert notification["resolving_user_id"] == USER_IDS["REUNIFICATION_SPECIALIST"], (
        "the deciding identifier resolves the obligation, got "
        f"{notification['resolving_user_id']}"
    )

    program = fetch_program(setup["program"]["id"])
    assert program["overdue_notification_count"] == 0, (
        "no obligation is overdue, got "
        f"{program['overdue_notification_count']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["risk_posture"] == "OPEN", (
        "resolving the last open obligation lifts the restriction, got "
        f"{youth['risk_posture']}"
    )

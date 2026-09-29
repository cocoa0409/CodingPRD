"""Deep cascades and the pinned order of the refusal ladder.

Two cascades are exercised end to end: revoking an evaluation consent, which
propagates through the consent record, the referral's two state dimensions, the
referral's evaluation case, that case's live domain assessments and the chairing
provider's evaluation rollups; and exiting an active service plan to
kindergarten, which discontinues the plan's service lines, restores the released
provider's minute ledger and frees the community site's IEP seat.

The remaining tests pin three explicitly ordered refusal pairs from PRD §2.5:
own/related state above the provider-active rung, slot containment above
screening capacity, and language access above interpreter availability.
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
    assert_clock_date,
    assert_provider_minute_ledger,
    assert_version_incremented,
)
from test_helpers.constants import (  # noqa: E402
    expected_travel_overhead,
    plus_minutes,
    ts,
)
from test_helpers.test_users import TEST_USERS  # noqa: E402

COORDINATOR = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------- helpers
def _consent_revocation_scenario(api, chair_caseload=1):
    """A case IN_PROGRESS behind a granted consent, with two live assessments.

    The chair's ``max_evaluation_caseload`` is deliberately small so that the one
    open case puts the chair at its evaluation ceiling; one assessment is left
    SCHEDULED and one is carried through to COMPLETED so the cascade has to reach
    both of the statuses the PRD names.
    """
    chair = fx.register_chair(api, max_evaluation_caseload=chair_caseload)
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")
    child = fx.register_child(api, date_of_birth="2023-11-01")
    granted = fx.setup_referral_with_granted_consent(api, child["id"])
    case = fx.open_case(
        api, granted["referral"]["id"], chair["id"], assessment_protocol="PLAY_BASED"
    )
    communication = fx.schedule_assessment(
        api,
        case["id"],
        evaluator["id"],
        domain="COMMUNICATION",
        method="PLAY_BASED",
        window_start_utc="2026-08-10T09:00:00Z",
    )
    cognitive = fx.schedule_assessment(
        api,
        case["id"],
        evaluator["id"],
        domain="COGNITIVE",
        method="STANDARDIZED",
        window_start_utc="2026-08-10T10:00:00Z",
    )
    communication = fx.complete_assessment(
        api, communication["id"], evaluator["id"], 22
    )
    return {
        "chair": fx.read_provider(api, chair["id"]),
        "evaluator": fx.read_provider(api, evaluator["id"]),
        "child": child,
        "referral": fx.read_referral(api, granted["referral"]["id"]),
        "consent": granted["consent"],
        "case": fx.read_case(api, case["id"]),
        "completed_assessment": communication,
        "scheduled_assessment": cognitive,
    }


def _active_community_preschool_plan(api, weekly_minutes=100):
    """An ACTIVE community-preschool plan holding one STAFFED DIRECT line.

    The plan reserves one IEP seat on its named site and the staffed line loads
    the provider's minute ledger, so both conserved quantities are in play.
    """
    site = fx.register_site(api, iep_seat_capacity=2)
    child = fx.register_child(api)
    context = fx.setup_active_plan(
        api,
        child["id"],
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=weekly_minutes,
        delivery_model="DIRECT",
    )
    context["site"] = fx.read_site(api, site["id"])
    return context


def _plan_at_packet_sent(api, weekly_minutes=100, conference_date="2029-01-15"):
    """An ACTIVE plan whose kindergarten_transition_status has reached PACKET_SENT."""
    context = _active_community_preschool_plan(api, weekly_minutes=weekly_minutes)
    fx.transition(
        api,
        context["plan"]["id"],
        "SCHEDULE_CONFERENCE",
        transition_conference_date=conference_date,
    )
    fx.transition(
        api, context["plan"]["id"], "SEND_PACKET", receiving_school_code="ELEM-014"
    )
    context["plan"] = fx.read_plan(api, context["plan"]["id"])
    context["line_provider"] = fx.read_provider(api, context["line_provider"]["id"])
    context["site"] = fx.read_site(api, context["site"]["id"])
    return context


# ------------------------------------------- consent revocation cascade (PRD §3.4)
def test_consent_revocation_cascades_through_all_five_levels(api):
    """Revoking an evaluation consent unwinds the whole evaluation chain.

    PRD §2.9 names this as the deepest chain in the system: the consent record,
    the referral's two state dimensions, the referral's live evaluation case, that
    case's scheduled and completed assessments, and finally the chairing
    provider's evaluation rollups and the child's derived status.

    Design: Difficulty/transitive_cascade/consent_revocation_cascades_referral_case_assessments_and_chair_capacity
    """
    scenario = _consent_revocation_scenario(api)

    revoked = fx.decide_consent(api, scenario["consent"]["id"], "REVOKED")

    assert revoked["decision"] == "REVOKED"

    # Level two: both referral state dimensions move together (PRD §3.4).
    referral = fx.read_referral(api, scenario["referral"]["id"])
    assert referral["intake_status"] == "WITHDRAWN"
    assert referral["consent_status"] == "REVOKED"

    # Level three: the live evaluation case is cancelled (PRD §3.5).
    case = fx.read_case(api, scenario["case"]["id"])
    assert case["status"] == "CANCELLED"

    # Level four: every assessment at SCHEDULED or COMPLETED is invalidated with
    # the cascade's own reason (PRD §3.5).
    for original in (scenario["scheduled_assessment"], scenario["completed_assessment"]):
        assessment = fx.read_assessment(api, original["id"])
        assert assessment["status"] == "INVALIDATED"
        assert assessment["invalidation_reason"] == "CASE_CANCELLED"

    # Level five: the chair's evaluation rollups and the child's status re-derive.
    chair = fx.read_provider(api, scenario["chair"]["id"])
    assert chair["active_evaluation_count"] == 0
    assert chair["evaluation_intake_posture"] == "OPEN"
    child = fx.read_child(api, scenario["child"]["id"])
    assert child["status"] == "NO_ACTIVE_REFERRAL"


def test_consent_revocation_retains_the_pinned_evaluation_due_date(api):
    """The pinned deadline survives the cascade as a historical record.

    PRD §3.4 keeps the already-pinned ``evaluation_due_date`` "as the historical
    deadline rather than cleared", and PRD §2.9 requires every record the cascade
    touches to have its ``version`` incremented.

    Design: Difficulty/transitive_cascade/consent_revocation_cascades_referral_case_assessments_and_chair_capacity
    """
    scenario = _consent_revocation_scenario(api)
    referral_before = scenario["referral"]
    case_before = scenario["case"]
    pinned_due_date = referral_before["evaluation_due_date"]
    assert pinned_due_date is not None

    fx.decide_consent(api, scenario["consent"]["id"], "REVOKED")

    referral_after = fx.read_referral(api, referral_before["id"])
    assert referral_after["evaluation_due_date"] == pinned_due_date
    assert referral_after["version"] > referral_before["version"]

    case_after = fx.read_case(api, case_before["id"])
    assert_version_incremented(case_before, case_after)

    for original in (scenario["scheduled_assessment"], scenario["completed_assessment"]):
        after = fx.read_assessment(api, original["id"])
        assert_version_incremented(original, after)


def test_consent_revocation_frees_the_chairs_evaluation_capacity(api):
    """Cancelling the case removes it from the chair's active count.

    PRD §3.5 excludes cases at CANCELLED from ``active_evaluation_count``, "which
    is precisely why cancelling a case frees capacity"; with a ceiling of one, the
    same chair can only take a second case once the first has been unwound.

    Design: Difficulty/transitive_cascade/consent_revocation_cascades_referral_case_assessments_and_chair_capacity
    """
    scenario = _consent_revocation_scenario(api, chair_caseload=1)
    chair_id = scenario["chair"]["id"]
    assert scenario["chair"]["evaluation_intake_posture"] == "AT_CAPACITY"

    second = fx.setup_referral_with_granted_consent(api)
    blocked = api.open_evaluation_case(
        second["referral"]["id"], f.evaluation_case_payload(chair_id), COORDINATOR
    )
    validate_error(blocked, ApiErrorId.ERR_EVALUATION_CASELOAD_EXCEEDED.value)

    fx.decide_consent(api, scenario["consent"]["id"], "REVOKED")

    allowed = api.open_evaluation_case(
        second["referral"]["id"], f.evaluation_case_payload(chair_id), COORDINATOR
    )
    validate_success(allowed, 201)
    assert fx.read_provider(api, chair_id)["active_evaluation_count"] == 1


# --------------------------------------- kindergarten exit cascade (PRD §3.9)
def test_kindergarten_exit_closes_the_plan_and_discontinues_its_lines(api):
    """EXIT closes the plan, stamps the exit date and unwinds every service line.

    PRD §3.9 moves the plan ACTIVE → EXITED_TO_KINDERGARTEN, sets ``exit_date`` to
    the logical clock's current date, advances ``kindergarten_transition_status``
    to COMPLETE and moves every line at PROPOSED, STAFFED or UNSTAFFED to
    DISCONTINUED, leaving the child's derived status at EXITED_TO_KINDERGARTEN.

    Design: Difficulty/transitive_cascade/kindergarten_exit_cascades_plan_lines_provider_minutes_and_seat_release
    """
    context = _plan_at_packet_sent(api)
    plan_before = context["plan"]
    assert plan_before["status"] == "ACTIVE"
    assert plan_before["kindergarten_transition_status"] == "PACKET_SENT"
    assert plan_before["receiving_school_code"] == "ELEM-014"

    exit_instant = "2029-06-15T00:00:00Z"
    fx.set_clock(api, exit_instant)
    exited = fx.transition(api, plan_before["id"], "EXIT")

    assert exited["status"] == "EXITED_TO_KINDERGARTEN"
    assert exited["kindergarten_transition_status"] == "COMPLETE"
    assert_clock_date(exited["exit_date"], exit_instant, "plan.exit_date")
    assert_version_incremented(plan_before, exited)

    line = fx.read_line(api, context["line"]["id"])
    assert line["status"] == "DISCONTINUED"

    child = fx.read_child(api, context["child"]["id"])
    assert child["status"] == "EXITED_TO_KINDERGARTEN"


def test_kindergarten_exit_releases_provider_minutes_and_the_iep_seat(api):
    """The two conserved quantities are both returned by the exit cascade.

    PRD §3.9 recomputes the released provider's three minute figures and
    re-derives its posture, and on the community-preschool branch decreases the
    named site's ``reserved_iep_seat_count`` by one. PRD §2.4 requires the
    quantities to be recomputed from the contributing rows, so nothing is left
    behind once the only staffed line is discontinued.

    Design: Difficulty/transitive_cascade/kindergarten_exit_cascades_plan_lines_provider_minutes_and_seat_release
    """
    context = _plan_at_packet_sent(api, weekly_minutes=100)
    provider_before = context["line_provider"]
    assert_provider_minute_ledger(
        provider_before, 100, expected_travel_overhead(100, 1), 105
    )
    assert context["site"]["reserved_iep_seat_count"] == 1

    fx.set_clock(api, "2029-06-15T00:00:00Z")
    fx.transition(api, context["plan"]["id"], "EXIT")

    provider_after = fx.read_provider(api, provider_before["id"])
    assert_provider_minute_ledger(provider_after, 0, 0, 0, "OPEN")
    assert_version_incremented(provider_before, provider_after)

    site_after = fx.read_site(api, context["site"]["id"])
    assert site_after["reserved_iep_seat_count"] == 0


def test_kindergarten_exit_keeps_the_discontinued_lines_assignment_for_audit(api):
    """A line cascading out of STAFFED keeps who delivered it and where.

    PRD §3.8 has a line cascading from STAFFED retain ``provider_id`` and
    ``delivery_site_id`` for audit rather than clearing them, even though the line
    itself has left the in-scope set that feeds the provider's minute figures.

    Design: Difficulty/transitive_cascade/kindergarten_exit_cascades_plan_lines_provider_minutes_and_seat_release
    """
    context = _plan_at_packet_sent(api)
    line_before = fx.read_line(api, context["line"]["id"])
    assert line_before["status"] == "STAFFED"
    assert line_before["provider_id"] == context["line_provider"]["id"]

    fx.set_clock(api, "2029-06-15T00:00:00Z")
    fx.transition(api, context["plan"]["id"], "EXIT")

    line_after = fx.read_line(api, line_before["id"])
    assert line_after["status"] == "DISCONTINUED"
    assert line_after["provider_id"] == context["line_provider"]["id"]
    assert line_after["delivery_site_id"] == line_before["delivery_site_id"]


# ------------------------- case state above provider availability (PRD §2.5)
def _cancelled_case(api):
    """A PLANNED case driven to CANCELLED by revoking the evaluation consent."""
    chair = fx.register_chair(api)
    granted = fx.setup_referral_with_granted_consent(api)
    case = fx.open_case(api, granted["referral"]["id"], chair["id"])
    fx.decide_consent(api, granted["consent"]["id"], "REVOKED")
    return {"chair": chair, "case": fx.read_case(api, case["id"])}


def _on_leave_evaluator(api, discipline="ECSE_TEACHER"):
    """An evaluator of an eligible discipline whose status has been set ON_LEAVE."""
    provider = fx.register_provider(api, discipline=discipline)
    return fx.patch_provider(api, provider["id"], status="ON_LEAVE")


def test_cancelled_case_state_outranks_an_inactive_evaluator(api):
    """Both guards fail at once and the case-state guard is the one reported.

    PRD §2.5 places ERR_PROVIDER_NOT_ACTIVE at rung 18, strictly below the own- and
    related-state rungs 11 and 12, and calls that placement the pinned tie-break
    for the state-versus-referential conflict. PRD §3.5 refuses scheduling against
    a CANCELLED case with ERR_INVALID_CASE_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_provider_not_active_on_a_cancelled_case
    """
    context = _cancelled_case(api)
    assert context["case"]["status"] == "CANCELLED"
    evaluator = _on_leave_evaluator(api)
    assert evaluator["status"] == "ON_LEAVE"

    response = api.schedule_domain_assessment(
        context["case"]["id"],
        f.domain_assessment_payload(
            evaluator["id"], domain="ADAPTIVE", method="PARENT_REPORT"
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)
    assert fx.assessments_for_case(api, context["case"]["id"]) == []


def test_an_inactive_evaluator_alone_is_refused_on_a_live_case(api):
    """The lower-ranked guard is live: on its own it is the reported failure.

    PRD §3.2 refuses a new domain assessment for a provider whose status is
    ON_LEAVE or INACTIVE with ERR_PROVIDER_NOT_ACTIVE, which is what surfaces once
    the case-state guard above it passes.

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_provider_not_active_on_a_cancelled_case
    """
    context = fx.setup_case(api)
    assert context["case"]["status"] == "PLANNED"
    evaluator = _on_leave_evaluator(api)

    response = api.schedule_domain_assessment(
        context["case"]["id"],
        f.domain_assessment_payload(
            evaluator["id"], domain="ADAPTIVE", method="PARENT_REPORT"
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_PROVIDER_NOT_ACTIVE.value)
    assert fx.assessments_for_case(api, context["case"]["id"]) == []


def test_cancelled_case_state_alone_is_refused_for_an_active_evaluator(api):
    """The higher-ranked guard is live on its own too, so the pair is a real tie.

    PRD §3.5 refuses scheduling against a case that is CANCELLED or
    ELIGIBILITY_DETERMINED with ERR_INVALID_CASE_STATE regardless of who was
    named as the evaluator.

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_provider_not_active_on_a_cancelled_case
    """
    context = _cancelled_case(api)
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")
    assert evaluator["status"] == "ACTIVE"

    response = api.schedule_domain_assessment(
        context["case"]["id"],
        f.domain_assessment_payload(
            evaluator["id"], domain="ADAPTIVE", method="PARENT_REPORT"
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)


# ------------------- slot containment above screening capacity (PRD §2.5)
EVENT_START = "2026-08-05T09:00:00Z"


def _full_single_slot_event(api):
    """An OPEN event holding exactly one appointment, already taken.

    The window is twenty minutes long with twenty-minute appointments, so the
    effective capacity computed in PRD §3.2 is one and the single booking fills it.
    """
    event = fx.create_open_screening_event(
        api,
        None,
        window_start_utc=ts(EVENT_START),
        window_end_utc=plus_minutes(EVENT_START, 20),
        slot_capacity=1,
        slot_length_minutes=20,
    )
    first_child = fx.register_child(api)
    fx.book_slot(api, event, first_child["id"], slot_start_utc=EVENT_START)
    return fx.read_event(api, event["id"])


def test_slot_outside_the_window_outranks_a_full_screening_event(api):
    """A late start on a full event reports the containment failure, not capacity.

    PRD §2.5 puts slot containment at rung 23 and calls its placement above the
    capacity rung the pinned tie-break for the temporal-versus-capacity conflict.

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_error_wins_over_screening_capacity_on_a_full_event
    """
    event = _full_single_slot_event(api)
    assert event["effective_slot_capacity"] == 1
    assert event["booked_slot_count"] == 1
    second_child = fx.register_child(api)

    response = api.book_screening_slot(
        event["id"],
        f.slot_booking_payload(
            second_child["id"], event["version"], slot_start_utc=plus_minutes(EVENT_START, 30)
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_EVENT_WINDOW.value)
    unchanged = fx.read_event(api, event["id"])
    assert unchanged["booked_slot_count"] == 1


def test_a_full_screening_event_alone_is_refused_for_capacity(api):
    """The lower-ranked guard is live: an in-window booking hits the ceiling.

    PRD §3.2 refuses the next booking with ERR_SCREENING_CAPACITY_EXCEEDED once
    ``booked_slot_count`` has reached ``effective_slot_capacity``; equality is
    enough to refuse.

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_error_wins_over_screening_capacity_on_a_full_event
    """
    event = _full_single_slot_event(api)
    second_child = fx.register_child(api)

    response = api.book_screening_slot(
        event["id"],
        f.slot_booking_payload(
            second_child["id"], event["version"], slot_start_utc=EVENT_START
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_CAPACITY_EXCEEDED.value)
    assert fx.read_event(api, event["id"])["booked_slot_count"] == 1


def test_slot_outside_the_window_alone_is_refused_with_capacity_to_spare(api):
    """The higher-ranked guard stands on its own, so the pair is a genuine tie.

    PRD §3.2 requires the appointment's start plus the event's slot length to fall
    at or before ``window_end_utc``, so an appointment that would overrun the
    window is refused even while the event still has free places.

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_error_wins_over_screening_capacity_on_a_full_event
    """
    event = fx.create_open_screening_event(
        api,
        None,
        window_start_utc=ts(EVENT_START),
        window_end_utc=plus_minutes(EVENT_START, 60),
        slot_capacity=2,
        slot_length_minutes=20,
    )
    assert event["effective_slot_capacity"] == 2
    assert event["booked_slot_count"] == 0
    child = fx.register_child(api)

    response = api.book_screening_slot(
        event["id"],
        f.slot_booking_payload(
            child["id"], event["version"], slot_start_utc=plus_minutes(EVENT_START, 50)
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_EVENT_WINDOW.value)


# --------------- language access above interpreter availability (PRD §2.5)
def _spanish_speaking_referral(api):
    """A RECEIVED referral for a child whose home language is not English."""
    child = fx.register_child(api, primary_language_code="es")
    referral = fx.create_referral(api, child["id"])
    return {"child": child, "referral": referral}


def test_language_access_outranks_the_interpreters_own_assignment_ceiling(api):
    """An unservable language is reported even when the interpreter is also full.

    PRD §2.5 rung 14 is "the highest business-safety rule below consent itself, and
    it is checked before the interpreter's own availability ceiling", which PRD §3.4
    tests only "after language access has passed" at the bottom of the ladder.

    Design: Difficulty/priority_pair_validation_conflict/language_access_error_wins_over_interpreter_capacity_cap
    """
    context = _spanish_speaking_referral(api)
    assert context["child"]["interpreter_required"] is True
    interpreter = fx.register_interpreter(
        api, languages=["fr"], max_weekly_interpreter_assignments=0
    )

    response = api.issue_consent_request(
        context["referral"]["id"],
        f.interpreted_consent_request_payload(interpreter["id"]),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INTERPRETER_NOT_PROVIDED.value)
    referral = fx.read_referral(api, context["referral"]["id"])
    assert referral["intake_status"] == "RECEIVED"
    assert referral["consent_status"] == "NOT_REQUESTED"
    assert fx.read_provider(api, interpreter["id"])["assigned_interpreter_assignment_count"] == 0
    assert fx.consent_records_for_referral(api, referral["id"]) == []


def test_an_over_committed_interpreter_alone_is_refused_as_unavailable(api):
    """The lower-ranked guard is live once the language rule is satisfied.

    PRD §3.4 refuses an interpreter whose ``assigned_interpreter_assignment_count``
    has already reached ``max_weekly_interpreter_assignments`` with
    ERR_INTERPRETER_UNAVAILABLE; PRD §3.2 notes that an interpreter registered
    without an explicit ceiling can be named on no notices at all.

    Design: Difficulty/priority_pair_validation_conflict/language_access_error_wins_over_interpreter_capacity_cap
    """
    context = _spanish_speaking_referral(api)
    interpreter = fx.register_interpreter(
        api, languages=["es"], max_weekly_interpreter_assignments=0
    )

    response = api.issue_consent_request(
        context["referral"]["id"],
        f.interpreted_consent_request_payload(interpreter["id"]),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INTERPRETER_UNAVAILABLE.value)
    referral = fx.read_referral(api, context["referral"]["id"])
    assert referral["consent_status"] == "NOT_REQUESTED"


def test_language_access_alone_is_refused_for_an_available_interpreter(api):
    """The higher-ranked guard stands on its own, so the pair is a genuine tie.

    PRD §2.7 requires the notice either to be written in the child's own language
    or to name an interpreter whose ``languages`` contain it; an interpreter with
    room to spare but the wrong language satisfies neither condition.

    Design: Difficulty/priority_pair_validation_conflict/language_access_error_wins_over_interpreter_capacity_cap
    """
    context = _spanish_speaking_referral(api)
    interpreter = fx.register_interpreter(
        api, languages=["fr"], max_weekly_interpreter_assignments=1
    )

    response = api.issue_consent_request(
        context["referral"]["id"],
        f.interpreted_consent_request_payload(interpreter["id"]),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INTERPRETER_NOT_PROVIDED.value)
    assert fx.read_provider(api, interpreter["id"])["assigned_interpreter_assignment_count"] == 0

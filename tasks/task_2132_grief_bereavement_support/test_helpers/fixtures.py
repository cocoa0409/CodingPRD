"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database using
only PRD-declared endpoints, and uses the lenient success reader so that a broken
precondition surfaces as a clear setup failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK
from .factories import (
    create_assessment_payload,
    create_cohort_payload,
    create_companion_match_payload,
    create_counseling_referral_payload,
    create_counselor_payload,
    create_grant_award_payload,
    create_grant_report_payload,
    create_invitation_payload,
    create_meeting_space_payload,
    create_referral_payload,
    create_remembrance_event_payload,
    create_volunteer_companion_payload,
    unique_contact_email,
)
from .test_users import (
    GO,
    IC,
    PD,
    RS,
    make_counselor_headers,
    make_participant_headers,
    make_volunteer_companion_headers,
)


# ==========================================================================
# Tier 0: clock, sweep and plain readers
# ==========================================================================
def set_clock(to_iso8601: str = BASE_CLOCK) -> dict:
    """Reposition the logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, PD))


def run_cadence_sweep() -> dict:
    """Invoke the operational sweep. Returns the six counters."""
    return get_success_data(api_client.cadence_run(PD))


def read_referral(referral_id: str) -> dict:
    return get_success_data(api_client.get_referral(referral_id, IC))


def read_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, IC))


def read_meeting_space(space_id: str) -> dict:
    return get_success_data(api_client.get_meeting_space(space_id, PD))


def read_cohort(cohort_id: str) -> dict:
    return get_success_data(api_client.get_cohort(cohort_id, PD))


def read_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, IC))


def read_counselor(counselor_id: str) -> dict:
    return get_success_data(api_client.get_counselor(counselor_id, PD))


def read_counseling_referral(referral_id: str) -> dict:
    return get_success_data(api_client.get_counseling_referral(referral_id, IC))


def read_volunteer_companion(companion_id: str) -> dict:
    return get_success_data(api_client.get_volunteer_companion(companion_id, PD))


def read_companion_match(match_id: str) -> dict:
    return get_success_data(api_client.get_companion_match(match_id, IC))


def read_remembrance_event(event_id: str) -> dict:
    return get_success_data(api_client.get_remembrance_event(event_id, PD))


def read_invitation(invitation_id: str) -> dict:
    return get_success_data(api_client.get_invitation(invitation_id, IC))


def read_grant_award(award_id: str) -> dict:
    return get_success_data(api_client.get_grant_award(award_id, PD))


def read_funding_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_funding_allocation(allocation_id, PD))


def read_grant_report(report_id: str) -> dict:
    return get_success_data(api_client.get_grant_report(report_id, PD))


def read_outreach_plan(participant_id: str, **params) -> list:
    resp = api_client.list_anniversary_outreaches(
        participant_id, IC, params=params or None)
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"Setup failed reading outreach plan: {body}"
    return body["data"]


def read_assessments(participant_id: str, **params) -> list:
    resp = api_client.list_assessments(participant_id, IC, params=params or None)
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"Setup failed reading assessments: {body}"
    return body["data"]


def cohort_version(cohort_id: str) -> int:
    return read_cohort(cohort_id)["version"]


def counselor_version(counselor_id: str) -> int:
    return read_counselor(counselor_id)["version"]


def grant_award_version(award_id: str) -> int:
    return read_grant_award(award_id)["version"]


# ==========================================================================
# Tier 1: single-entity creation
# ==========================================================================
def create_meeting_space(**overrides) -> dict:
    return get_success_data(
        api_client.create_meeting_space(create_meeting_space_payload(**overrides), PD))


def create_referral(**overrides) -> dict:
    overrides.setdefault("contact_email", unique_contact_email())
    return get_success_data(
        api_client.create_referral(create_referral_payload(**overrides), RS))


def screen_referral(referral_id: str, eligibility_note: str = "in service area") -> dict:
    return get_success_data(
        api_client.screen_referral(
            referral_id, {"eligibility_note": eligibility_note}, IC))


def accept_referral(referral_id: str) -> dict:
    return get_success_data(api_client.accept_referral(referral_id, IC))


def create_participant(**overrides) -> dict:
    """File, screen and accept one intake record. Returns the minted participant."""
    referral = create_referral(**overrides)
    screen_referral(referral["id"])
    return accept_referral(referral["id"])


def record_assessment(participant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment(
            participant_id, create_assessment_payload(**overrides), IC))


def create_assessed_participant(grief_severity: int = 20, isolation_index: int = 8,
                                functional_impairment: int = 8,
                                suicidality_flag: bool = False,
                                instrument: str = "ICG_SF",
                                **referral_overrides) -> dict:
    """Accepted participant carrying one NEEDS assessment, so they are enrollable.

    Returns the refreshed participant record.
    """
    participant = create_participant(**referral_overrides)
    record_assessment(
        participant["id"], kind="NEEDS", instrument=instrument,
        grief_severity=grief_severity, isolation_index=isolation_index,
        functional_impairment=functional_impairment,
        suicidality_flag=suicidality_flag,
    )
    return read_participant(participant["id"])


def create_cohort(meeting_space_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cohort(
            create_cohort_payload(meeting_space_id, **overrides), PD))


def open_cohort(cohort_id: str) -> dict:
    return get_success_data(api_client.open_cohort_enrollment(cohort_id, PD))


def create_counselor(**overrides) -> dict:
    return get_success_data(
        api_client.create_counselor(create_counselor_payload(**overrides), PD))


def create_volunteer_companion(**overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer_companion(
            create_volunteer_companion_payload(**overrides), PD))


def record_training(companion_id: str, module_code: str, hours) -> dict:
    return get_success_data(
        api_client.create_training_record(
            companion_id, {"module_code": module_code, "hours": hours}, PD))


def create_remembrance_event(meeting_space_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_remembrance_event(
            create_remembrance_event_payload(meeting_space_id, **overrides), PD))


def confirm_remembrance_event(event_id: str) -> dict:
    return get_success_data(api_client.confirm_remembrance_event(event_id, PD))


def create_grant_award(**overrides) -> dict:
    return get_success_data(
        api_client.create_grant_award(create_grant_award_payload(**overrides), PD))


def create_grant_report(grant_award_id: str, user_id: str = "pd-001", **overrides) -> dict:
    from .test_users import make_program_director_headers
    return get_success_data(
        api_client.create_grant_report(
            create_grant_report_payload(grant_award_id, **overrides),
            make_program_director_headers(user_id)))


# ==========================================================================
# Tier 2: entity hierarchy — space + cohort + seats
# ==========================================================================
def create_open_cohort(space_overrides=None, **cohort_overrides):
    """Register a room and open one cohort for enrolment.

    Returns (space, cohort) with the cohort refreshed after open-enrollment.
    """
    space = create_meeting_space(**(space_overrides or {}))
    cohort = create_cohort(space["id"], **cohort_overrides)
    cohort = open_cohort(cohort["id"])
    return space, cohort


def enroll(participant_id: str, cohort_id: str, expected_cohort_version=None) -> dict:
    """Hold a seat, reading the cohort's live version when none is supplied."""
    if expected_cohort_version is None:
        expected_cohort_version = cohort_version(cohort_id)
    payload = {
        "participant_id": participant_id,
        "cohort_id": cohort_id,
        "expected_cohort_version": expected_cohort_version,
    }
    return get_success_data(api_client.create_enrollment(payload, IC))


def confirm_enrollment(enrollment_id: str, participant_id=None) -> dict:
    headers = make_participant_headers(participant_id) if participant_id else IC
    return get_success_data(api_client.confirm_enrollment(enrollment_id, headers))


def withdraw_enrollment(enrollment_id: str,
                        withdraw_reason: str = "PARTICIPANT_REQUEST") -> dict:
    return get_success_data(
        api_client.withdraw_enrollment(
            enrollment_id, {"withdraw_reason": withdraw_reason}, IC))


def log_attendance(enrollment_id: str, sessions_delta: int) -> dict:
    return get_success_data(
        api_client.log_attendance(enrollment_id, sessions_delta, IC))


def setup_cohort_with_confirmed_seat(cohort_overrides=None, space_overrides=None,
                                     participant_overrides=None):
    """Open cohort + one assessed participant holding a CONFIRMED seat.

    Returns (space, cohort, participant, enrollment) with cohort and enrollment
    refreshed after the confirmation.
    """
    space, cohort = create_open_cohort(
        space_overrides=space_overrides, **(cohort_overrides or {}))
    participant = create_assessed_participant(
        loss_type=cohort["loss_type"], **(participant_overrides or {}))
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    enrollment = confirm_enrollment(enrollment["id"])
    return space, read_cohort(cohort["id"]), participant, enrollment


def setup_running_cohort(cohort_overrides=None, space_overrides=None,
                         participant_overrides=None):
    """Open cohort + one CONFIRMED seat + launch, so the cohort is RUNNING and the
    seat is ATTENDING.

    Returns (space, cohort, participant, enrollment).
    """
    space, cohort, participant, enrollment = setup_cohort_with_confirmed_seat(
        cohort_overrides=cohort_overrides, space_overrides=space_overrides,
        participant_overrides=participant_overrides)
    cohort = get_success_data(api_client.launch_cohort(cohort["id"], PD))
    return space, cohort, participant, read_enrollment(enrollment["id"])


# ==========================================================================
# Tier 3: counselling waitlist
# ==========================================================================
def create_counseling_referral(participant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_counseling_referral(
            create_counseling_referral_payload(participant_id, **overrides), IC))


def assign_counseling_referral(referral_id: str, counselor_id: str,
                               expected_counselor_version=None) -> dict:
    if expected_counselor_version is None:
        expected_counselor_version = counselor_version(counselor_id)
    payload = {
        "counselor_id": counselor_id,
        "expected_counselor_version": expected_counselor_version,
    }
    return get_success_data(
        api_client.assign_counseling_referral(referral_id, payload, IC))


def close_counseling_referral(referral_id: str, close_reason: str = "COMPLETED",
                              counselor_id=None) -> dict:
    headers = make_counselor_headers(counselor_id) if counselor_id else IC
    return get_success_data(
        api_client.close_counseling_referral(
            referral_id, {"close_reason": close_reason}, headers))


def deactivate_counselor(counselor_id: str) -> dict:
    return get_success_data(api_client.deactivate_counselor(counselor_id, PD))


def setup_assigned_counseling_case(counselor_overrides=None,
                                   referral_overrides=None,
                                   participant_overrides=None):
    """One ACTIVE counsellor + one accepted participant whose counselling referral
    is ASSIGNED to that counsellor.

    Returns (counselor, participant, counseling_referral) refreshed after assignment.
    """
    counselor = create_counselor(**(counselor_overrides or {}))
    participant = create_participant(
        loss_type="SUDDEN_DEATH", **(participant_overrides or {}))
    referral = create_counseling_referral(
        participant["id"], **(referral_overrides or {}))
    referral = assign_counseling_referral(
        referral["id"], counselor["id"], counselor["version"])
    return read_counselor(counselor["id"]), participant, referral


# ==========================================================================
# Tier 4: volunteer companions
# ==========================================================================
def create_certified_companion(endorsed_loss_types=None, max_concurrent_matches=3,
                               listening_hours=16, safety_hours=8, **overrides):
    """Register an applicant and train them past both certification bars.

    Default hours give a CERTIFIED volunteer with training_hours 24; pass
    listening_hours=8 / safety_hours=8 for a volunteer certified at exactly 16.
    Returns the refreshed volunteer record.
    """
    companion = create_volunteer_companion(
        endorsed_loss_types=endorsed_loss_types or ["ANTICIPATED_ILLNESS"],
        max_concurrent_matches=max_concurrent_matches, **overrides)
    record_training(companion["id"], "CORE_LISTENING", listening_hours)
    record_training(companion["id"], "CORE_SAFETY", safety_hours)
    return read_volunteer_companion(companion["id"])


def propose_companion_match(companion_id: str, participant_id: str) -> dict:
    return get_success_data(
        api_client.create_companion_match(
            create_companion_match_payload(companion_id, participant_id), IC))


def respond_companion_match(match_id: str, companion_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.respond_companion_match(
            match_id, decision, make_volunteer_companion_headers(companion_id)))


def end_companion_match(match_id: str, companion_id: str,
                        end_reason: str = "COMPLETED") -> dict:
    return get_success_data(
        api_client.end_companion_match(
            match_id, end_reason, make_volunteer_companion_headers(companion_id)))


def setup_active_companion_match(loss_type="ANTICIPATED_ILLNESS",
                                 max_concurrent_matches=3,
                                 participant_scores=(10, 4, 4)):
    """Certified volunteer + assessed participant + one ACTIVE match.

    Returns (companion, participant, match) all refreshed.
    """
    companion = create_certified_companion(
        endorsed_loss_types=[loss_type], max_concurrent_matches=max_concurrent_matches)
    participant = create_assessed_participant(
        loss_type=loss_type,
        grief_severity=participant_scores[0],
        isolation_index=participant_scores[1],
        functional_impairment=participant_scores[2],
    )
    match = propose_companion_match(companion["id"], participant["id"])
    match = respond_companion_match(match["id"], companion["id"], "ACCEPT")
    return (read_volunteer_companion(companion["id"]),
            read_participant(participant["id"]), match)


# ==========================================================================
# Tier 5: remembrance events, invitations and the RSVP window
# ==========================================================================
def create_invitation(event_id: str, participant_id: str, guest_count: int = 0) -> dict:
    return get_success_data(
        api_client.create_invitation(
            create_invitation_payload(event_id, participant_id,
                                      guest_count=guest_count), IC))


def send_invitation(invitation_id: str) -> dict:
    return get_success_data(api_client.send_invitation(invitation_id, IC))


def respond_invitation(invitation_id: str, participant_id: str, response: str) -> dict:
    return get_success_data(
        api_client.respond_invitation(
            invitation_id, response, make_participant_headers(participant_id)))


def setup_confirmed_event(space_overrides=None, **event_overrides):
    """Register a hall and plan + confirm one remembrance event in it.

    Returns (space, event).
    """
    space = create_meeting_space(
        **(space_overrides or {"name": "Hall A", "capacity": 60,
                               "turnover_buffer_minutes": 30}))
    event = create_remembrance_event(space["id"], **event_overrides)
    event = confirm_remembrance_event(event["id"])
    return space, event


def setup_event_with_accepted_invitation(guest_count: int = 2, **event_overrides):
    """Confirmed event + one accepted invitation.

    Returns (space, event, participant, invitation) with the event refreshed.
    """
    space, event = setup_confirmed_event(**event_overrides)
    participant = create_participant(loss_type="SUDDEN_DEATH")
    invitation = create_invitation(event["id"], participant["id"], guest_count)
    send_invitation(invitation["id"])
    invitation = respond_invitation(invitation["id"], participant["id"], "ACCEPT")
    return space, read_remembrance_event(event["id"]), participant, invitation


# ==========================================================================
# Tier 6: grant money — awards, allocations, reports
# ==========================================================================
def create_funding_allocation(grant_award_id: str, category: str, cohort_id=None,
                              event_id=None, expected_grant_award_version=None) -> dict:
    if expected_grant_award_version is None:
        expected_grant_award_version = grant_award_version(grant_award_id)
    payload = {
        "grant_award_id": grant_award_id,
        "category": category,
        "expected_grant_award_version": expected_grant_award_version,
    }
    if cohort_id is not None:
        payload["cohort_id"] = cohort_id
    if event_id is not None:
        payload["event_id"] = event_id
    return get_success_data(api_client.create_funding_allocation(payload, PD))


def release_funding_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.release_funding_allocation(allocation_id, PD))


def setup_funded_event(awarded_cents: int = 500_000, direct_cost_cents: int = 10_220,
                       **event_overrides):
    """Award + planned event + one COMMITTED remembrance-event allocation.

    Returns (space, event, award, allocation) with the award refreshed.
    """
    space = create_meeting_space(name="Hall A", capacity=60, turnover_buffer_minutes=30)
    award = create_grant_award(
        awarded_cents=awarded_cents, allowed_categories=["REMEMBRANCE_EVENT"])
    event = create_remembrance_event(
        space["id"], direct_cost_cents=direct_cost_cents, **event_overrides)
    allocation = create_funding_allocation(
        award["id"], "REMEMBRANCE_EVENT", event_id=event["id"],
        expected_grant_award_version=award["version"])
    return space, event, read_grant_award(award["id"]), allocation


def setup_funded_cohort_with_confirmed_seat(awarded_cents: int = 5_000_000,
                                            direct_cost_cents: int = 240_000,
                                            cohort_overrides=None):
    """Award + open cohort + one CONFIRMED seat + one COMMITTED group allocation.

    Returns (cohort, participant, enrollment, award, allocation).
    """
    overrides = dict(cohort_overrides or {})
    overrides.setdefault("direct_cost_cents", direct_cost_cents)
    award = create_grant_award(
        awarded_cents=awarded_cents, allowed_categories=["GROUP_PROGRAM"])
    space, cohort, participant, enrollment = setup_cohort_with_confirmed_seat(
        cohort_overrides=overrides)
    allocation = create_funding_allocation(
        award["id"], "GROUP_PROGRAM", cohort_id=cohort["id"],
        expected_grant_award_version=award["version"])
    return (read_cohort(cohort["id"]), participant, enrollment,
            read_grant_award(award["id"]), allocation)


def submit_grant_report(report_id: str, user_id: str = "pd-001") -> dict:
    from .test_users import make_program_director_headers
    return get_success_data(
        api_client.submit_grant_report(
            report_id, make_program_director_headers(user_id)))


def return_grant_report(report_id: str, return_reason: str,
                        user_id: str = "go-001") -> dict:
    from .test_users import make_grant_officer_headers
    return get_success_data(
        api_client.return_grant_report(
            report_id, return_reason, make_grant_officer_headers(user_id)))


def revise_grant_report(report_id: str, user_id: str = "pd-001") -> dict:
    from .test_users import make_program_director_headers
    return get_success_data(
        api_client.revise_grant_report(
            report_id, make_program_director_headers(user_id)))


def accept_grant_report(report_id: str, user_id: str = "go-002") -> dict:
    from .test_users import make_grant_officer_headers
    return get_success_data(
        api_client.accept_grant_report(
            report_id, make_grant_officer_headers(user_id)))


def setup_submitted_grant_report(submitter_id: str = "op-777",
                                 award_overrides=None, report_overrides=None):
    """ACTIVE award + one report submitted by `submitter_id`.

    Returns (award, report) with the report refreshed after submission.
    """
    award = create_grant_award(
        **(award_overrides or {"awarded_cents": 100_000,
                               "allowed_categories": ["GROUP_PROGRAM"]}))
    report = create_grant_report(
        award["id"], user_id=submitter_id, **(report_overrides or {}))
    report = submit_grant_report(report["id"], user_id=submitter_id)
    return award, report


# ==========================================================================
# Tier 7: outreach cadence helpers
# ==========================================================================
def set_outreach_hold(participant_id: str, hold: bool, as_participant: bool = False):
    headers = make_participant_headers(participant_id) if as_participant else IC
    return get_success_data(
        api_client.set_outreach_hold(participant_id, hold, headers))


def send_outreach(outreach_id: str) -> dict:
    return get_success_data(api_client.send_outreach(outreach_id, IC))


def acknowledge_outreach(outreach_id: str) -> dict:
    return get_success_data(api_client.acknowledge_outreach(outreach_id, IC))


def withdraw_participant(participant_id: str, as_participant: bool = False) -> dict:
    headers = make_participant_headers(participant_id) if as_participant else IC
    return get_success_data(api_client.withdraw_participant(participant_id, headers))


def setup_due_outreach(date_of_death: str = "2026-06-01",
                       sweep_clock: str = "2026-08-15T00:00:00Z",
                       after_clock: str = "2026-09-01T00:00:00Z"):
    """Accept a participant whose earliest touchpoint is already past due, sweep it
    to DUE, then reposition the clock.

    Returns (participant, due_touchpoint, sweep_counters).
    """
    set_clock(sweep_clock)
    participant = create_participant(date_of_death=date_of_death)
    counters = run_cadence_sweep()
    set_clock(after_clock)
    due_rows = read_outreach_plan(participant["id"], status="DUE")
    assert due_rows, "Setup failed: no touchpoint reached DUE"
    return participant, due_rows[0], counters

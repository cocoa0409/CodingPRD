"""Difficulty tests: cross_entity_state_dependency — an operation on one
entity is gated by the current state of a different entity (roster
submission by the owning body's status; trials entry by the athlete's
eligibility dimension).
"""
from test_helpers import (
    ApiErrorId,
    COMMITTEE_ADMIN_ID,
    answer_slot,
    clear_screening,
    create_athlete,
    enter_trials,
    file_complaint,
    investigate_complaint,
    make_athlete_headers,
    make_eligible,
    make_ngb_admin_headers,
    open_registration,
    read_governing_body,
    read_procedure,
    record_training,
    resolve_complaint,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_locked_procedure,
    setup_nominated_roster,
    submit_roster,
    triage_complaint,
    validate_error,
)


def test_roster_submission_gated_by_body_status(api, committee_admin_headers):
    """PRD user/role section: "An `NGBAdmin` may not submit a roster while
    their own governing body is `INTERIM_MANAGED`; in that posture only
    `CommitteeAdmin` callers — including the appointed interim manager
    identified by the body's `interim_manager_id` — may submit, and an
    `NGBAdmin` attempt is rejected with `ERR_UNAUTHORIZED`."
    PRD complaints/decertification section: "When a `CRITICAL` complaint is
    resolved `SUBSTANTIATED` while the body is `CERTIFIED` or `PROBATION`, the
    body cascades to `INTERIM_MANAGED`".
    PRD selection section: "The submitter is recorded as
    `submitted_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/roster_submission_gated_by_body_status
    """
    body = setup_certified_body(
        api=api,
        name="US Luge",
        sport_code="LUGE",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="A One", date_of_birth="1998-01-01"
    )
    _proc, roster = setup_nominated_roster(
        body["id"],
        {athlete["id"]: 90},
        api=api,
        quota_slots=1,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    # The sole PRIMARY slot is answered, and no appeals exist, so only the
    # body-standing rule distinguishes the two submit attempts.
    answer_slot(roster["id"], athlete["id"], "ACCEPTED", api=api)

    # A CRITICAL complaint substantiated at 2026-12-21 cascades the body to
    # INTERIM_MANAGED.
    set_logical_clock("2026-12-21T00:00:00Z", api=api)
    complaint = file_complaint(
        body["id"],
        api=api,
        headers=make_athlete_headers(athlete["id"]),
        category="GOVERNANCE",
        severity="CRITICAL",
        description="Board falsified election results",
    )
    triage_complaint(complaint["id"], api=api)
    investigate_complaint(complaint["id"], api=api)
    resolve_complaint(complaint["id"], "SUBSTANTIATED", api=api)
    body_mid = read_governing_body(body["id"], api=api)
    assert body_mid["status"] == "INTERIM_MANAGED"

    # The same SUBMITTED transition is denied for the body's NGBAdmin while
    # the body is INTERIM_MANAGED...
    resp = api.transition_roster(
        roster["id"], {"to_state": "SUBMITTED"}, make_ngb_admin_headers(body["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    # ...and succeeds for a CommitteeAdmin, who is recorded as the submitter.
    submitted = submit_roster(roster["id"], committee_admin_headers, api=api)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == COMMITTEE_ADMIN_ID


def test_trials_entry_gated_by_athlete_eligibility(api, committee_admin_headers):
    """PRD selection section: "Entry eligibility is the safety triad of §2.6:
    the athlete must be `ELIGIBLE` (else `ERR_ATHLETE_NOT_ELIGIBLE`),
    screening-cleared and unexpired (else `ERR_SCREENING_NOT_CLEARED`), and
    training-current within 365 days (else `ERR_TRAINING_EXPIRED`)".
    PRD selection section: "An accepted entry appends to the procedure's
    `entries` as a record of `athlete_id`, `entry_status` of `REGISTERED`,
    `score` null, and `result_recorded_at` null."
    PRD athlete section: "Promotion from `REGISTERED` to `ELIGIBLE`, performed
    by a `SafeSportOfficer`, requires both prongs of safe-sport currency at
    once".

    Design: Difficulty/cross_entity_state_dependency/trials_entry_gated_by_athlete_eligibility
    """
    body = setup_certified_body(
        api=api,
        name="US Surf",
        sport_code="SURF",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # Screening cleared and training current, but eligibility never promoted
    # out of REGISTERED.
    athlete = create_athlete(
        body["id"], api=api, full_name="Kai Wave", date_of_birth="2000-06-06"
    )
    clear_screening(athlete["id"], api=api)
    record_training(athlete["id"], api=api)

    # LOCKED procedure with the trials dimension open for registration; the
    # startup clock sits at/before the default registration deadline.
    proc = setup_locked_procedure(body["id"], api=api)
    proc = open_registration(proc["id"], body["id"], api=api)
    assert proc["trials_status"] == "REGISTRATION_OPEN"

    # Eligibility REGISTERED blocks the entry despite cleared screening and
    # current training.
    resp = api.create_trials_entry(
        proc["id"],
        {"athlete_id": athlete["id"]},
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ATHLETE_NOT_ELIGIBLE)

    # After promotion to ELIGIBLE the same entry is accepted.
    make_eligible(athlete["id"], api=api)
    enter_trials(proc["id"], athlete["id"], body["id"], api=api)

    proc_after = read_procedure(body["id"], proc["id"], api=api)
    assert proc_after["entries"] == [
        {
            "athlete_id": athlete["id"],
            "entry_status": "REGISTERED",
            "score": None,
            "result_recorded_at": None,
        }
    ], f"accepted entry must append the PRD record shape, got {proc_after['entries']!r}"

"""Surveys and sessions: state gates, overlap semantics, minute reconciliation,
on-site conflicts, and the evidence/advance gating (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_case,
    add_evidence,
    add_session,
    accept_evidence,
    adjudicate_question,
    cancel_session,
    cancel_survey,
    complete_session,
    complete_survey,
    confirm_survey,
    create_sample,
    create_score,
    create_scored_sample,
    create_survey_on_app,
    create_surveyor,
    fill_sample_with_cases,
    get_success_data,
    log_question,
    make_accreditation_officer_headers,
    make_surveyor_headers,
    setup_evidence_review,
    setup_planned_full_survey,
    setup_scoring,
    setup_survey_scheduling,
    submit_sample,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BASE_TIMELY_CASES, api_client


def _officer():
    return make_accreditation_officer_headers()


def test_state_beats_temporal_on_session_create(api):
    """PRD §2.5: "the first failure encountered terminates evaluation and
    produces the response." with state-machine preconditions (item 7, e.g.
    `ERR_SURVEY_INVALID_STATE`) listed before temporal windows and overlaps
    (item 10, e.g. `ERR_SURVEYOR_SESSION_OVERLAP`).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_session_create
    """
    ctx = setup_planned_full_survey()
    # S1 540-660 on 2026-10-05 by the surveyor, then the survey is cancelled.
    add_session(ctx["survey"]["id"], ctx["surveyor"]["id"],
                session_date="2026-10-05", start_minute=540, end_minute=660)
    cancel_survey(ctx["survey"]["id"])

    # Overlapping interval 600-700 against the same surveyor/date on a CANCELLED
    # survey: the state check must fire first.
    r = api_client.create_survey_session(
        ctx["survey"]["id"],
        {"surveyor_id": ctx["surveyor"]["id"], "session_date": "2026-10-05",
         "start_minute": 600, "end_minute": 700, "is_onsite": False},
        _officer(),
    )
    err = validate_error(r, ApiErrorId.ERR_SURVEY_INVALID_STATE)
    assert r.status_code == 409
    assert err["error_id"] != "ERR_SURVEYOR_SESSION_OVERLAP"


def test_state_beats_temporal_on_session_create_survey_completed(api):
    """PRD §2.5: "the first failure encountered terminates evaluation and
    produces the response." with state-machine preconditions (item 7, e.g.
    `ERR_SURVEY_INVALID_STATE`) listed before temporal windows and overlaps
    (item 10, e.g. `ERR_SURVEYOR_SESSION_OVERLAP`). The same ordering holds on a
    COMPLETED survey: an overlapping new session is rejected for state, not for
    overlap.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_session_create
    """
    ctx = setup_planned_full_survey()
    session = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"],
                          session_date="2026-10-05", start_minute=540, end_minute=660)
    confirm_survey(ctx["survey"]["id"])
    complete_session(session["id"], ctx["surveyor"]["id"])
    complete_survey(ctx["survey"]["id"])

    r = api_client.create_survey_session(
        ctx["survey"]["id"],
        {"surveyor_id": ctx["surveyor"]["id"], "session_date": "2026-10-05",
         "start_minute": 600, "end_minute": 700, "is_onsite": False},
        _officer(),
    )
    err = validate_error(r, ApiErrorId.ERR_SURVEY_INVALID_STATE)
    assert r.status_code == 409
    assert err["error_id"] != "ERR_SURVEYOR_SESSION_OVERLAP"


def test_temporal_beats_constraint_on_case_create(api):
    """PRD §2.5: "the first failure encountered terminates evaluation and
    produces the response." with temporal windows (item 10,
    `ERR_CASE_OUTSIDE_REVIEW_PERIOD`) listed before uniqueness, cardinality and
    aggregate checks (item 11, `ERR_INVALID_TURNAROUND_DAYS`).

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_case_create
    """
    ctx = setup_evidence_review()
    sample = create_sample(ctx["app"]["id"])
    r = api_client.create_file_review_case(
        sample["id"],
        {"case_reference": "BAD-1", "service_date": "2024-06-01T00:00:00Z",
         "decision_date": "2024-06-10T00:00:00Z",
         "resolution_date": "2024-06-10T00:00:00Z", "required_turnaround_days": 0},
        make_plan_coordinator_headers_for(ctx),
    )
    err = validate_error(r, ApiErrorId.ERR_CASE_OUTSIDE_REVIEW_PERIOD)
    assert r.status_code == 422
    assert err["error_id"] != "ERR_INVALID_TURNAROUND_DAYS"


def make_plan_coordinator_headers_for(ctx):
    from test_helpers import make_plan_coordinator_headers
    return make_plan_coordinator_headers(ctx["plan"]["id"])


def test_temporal_beats_constraint_on_case_create_negative_turnaround(api):
    """PRD §2.5: "the first failure encountered terminates evaluation and
    produces the response." with temporal windows (item 10,
    `ERR_CASE_OUTSIDE_REVIEW_PERIOD`) listed before uniqueness, cardinality and
    aggregate checks (item 11, `ERR_INVALID_TURNAROUND_DAYS`). A case whose
    service_date precedes the review period AND whose turnaround is below the
    floor is rejected for the temporal reason first.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_case_create
    """
    ctx = setup_evidence_review()
    sample = create_sample(ctx["app"]["id"])
    r = api_client.create_file_review_case(
        sample["id"],
        {"case_reference": "BAD-2", "service_date": "2024-12-31T00:00:00Z",
         "decision_date": "2025-01-10T00:00:00Z",
         "resolution_date": "2025-01-10T00:00:00Z", "required_turnaround_days": -3},
        make_plan_coordinator_headers_for(ctx),
    )
    err = validate_error(r, ApiErrorId.ERR_CASE_OUTSIDE_REVIEW_PERIOD)
    assert r.status_code == 422
    assert err["error_id"] != "ERR_INVALID_TURNAROUND_DAYS"


def test_session_complete_blocked_when_survey_not_confirmed(api):
    """PRD §3.5: "A session completes when its assigned `Surveyor` marks it
    complete; completion requires the session to be `SCHEDULED` (otherwise
    `ERR_SESSION_INVALID_STATE`), the owning survey to be `CONFIRMED` (otherwise
    `ERR_SURVEY_INVALID_STATE`), and the caller's `X-User-ID` to equal the
    session's `surveyor_id` (otherwise `ERR_OWNERSHIP_MISMATCH`)."

    Design: Difficulty/cross_entity_state_dependency/session_complete_blocked_when_survey_not_confirmed
    """
    ctx = setup_planned_full_survey()
    session = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"])
    r = api_client.complete_survey_session(
        session["id"], make_surveyor_headers(ctx["surveyor"]["id"])
    )
    validate_error(r, ApiErrorId.ERR_SURVEY_INVALID_STATE)
    assert r.status_code == 409
    after = get_success_data(api_client.get_survey_session(session["id"], _officer()))
    assert after["status"] == "SCHEDULED", "failed completion leaves the session SCHEDULED"


def test_session_complete_requires_confirmed_survey_not_planned(api):
    """PRD §3.5: "A session completes when its assigned `Surveyor` marks it complete; completion requires the session to be `SCHEDULED` (otherwise `ERR_SESSION_INVALID_STATE`), the owning survey to be `CONFIRMED` (otherwise `ERR_SURVEY_INVALID_STATE`), and the caller's `X-User-ID` to equal the session's `surveyor_id` (otherwise `ERR_OWNERSHIP_MISMATCH`)."

    Design: Difficulty/cross_entity_state_dependency/session_complete_blocked_when_survey_not_confirmed
    """
    ctx = setup_planned_full_survey()
    session = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"])

    # Still PLANNED: rejected.
    r = api_client.complete_survey_session(
        session["id"], make_surveyor_headers(ctx["surveyor"]["id"])
    )
    validate_error(r, ApiErrorId.ERR_SURVEY_INVALID_STATE)

    # After confirm, the same call succeeds.
    confirm_survey(ctx["survey"]["id"])
    done = complete_session(session["id"], ctx["surveyor"]["id"])
    assert done["status"] == "COMPLETED"


def test_advance_blocked_by_unaccepted_evidence(api):
    """PRD §3.3: "An `AccreditationOfficer` advances the application from
    `EVIDENCE_REVIEW` to `SURVEY_SCHEDULING` only when, for every standard
    element of the application's edition whose `evidence_required_count` is
    greater than 0, the application holds at least that many evidence items in
    `ACCEPTED` status; otherwise the request is rejected with
    `ERR_EVIDENCE_COMPLETENESS_UNMET` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/advance_blocked_by_unaccepted_evidence
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]

    # UM-1 requires 2 ACCEPTED; file 1 ACCEPTED + 1 REJECTED.
    ev1 = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], "UM policy")
    ev2 = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], "UM procedure")
    accept_evidence(ev1["id"])
    rj = api_client.reject_evidence_item(ev2["id"], {"review_note": "stale document"}, _officer())
    get_success_data(rj)
    # CR-1 and QI-1 each get their single required item ACCEPTED.
    for code in ("CR-1", "QI-1"):
        ev = add_evidence(app_id, plan_id, ctx["elements"][code], f"{code} evidence")
        accept_evidence(ev["id"])

    r = api_client.advance_to_survey_scheduling(app_id, _officer())
    validate_error(r, ApiErrorId.ERR_EVIDENCE_COMPLETENESS_UNMET)
    assert r.status_code == 422

    # Resubmit + accept the rejected item; the advance now succeeds.
    from test_helpers import advance_to_survey_scheduling
    rs = api_client.resubmit_evidence_item(ev2["id"], {},
                                           make_plan_coordinator_headers_for(ctx))
    get_success_data(rs)
    accept_evidence(ev2["id"])
    advanced = advance_to_survey_scheduling(app_id)
    assert advanced["status"] == "SURVEY_SCHEDULING"


def test_advance_succeeds_once_evidence_completeness_holds(api):
    """PRD §3.3: "An `AccreditationOfficer` advances the application from `EVIDENCE_REVIEW` to `SURVEY_SCHEDULING` only when, for every standard element of the application's edition whose `evidence_required_count` is greater than 0, the application holds at least that many evidence items in `ACCEPTED` status"."

    Design: Difficulty/cross_entity_state_dependency/advance_blocked_by_unaccepted_evidence
    """
    ctx = setup_survey_scheduling()
    assert ctx["app"]["status"] == "SURVEY_SCHEDULING"


def test_finalize_blocked_by_single_open_gap_question(api):
    """PRD §3.7: "no surveyor question with `raises_gap` true and status
    `LOGGED` may reference this element within this application's surveys; an
    unadjudicated gap-flagged question blocks finalization with
    `ERR_OPEN_GAP_QUESTIONS_REMAIN` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/finalize_blocked_by_single_open_gap_question
    """
    # SCORING with exactly one LOGGED gap question on UM-1 (not adjudicated).
    ctx = setup_survey_scheduling()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    create_scored_sample(app_id, plan_id, BASE_TIMELY_CASES, prefix="DN")
    survey = create_survey_on_app(app_id, survey_type="FULL")
    surveyor = create_surveyor()
    session = add_session(survey["id"], surveyor["id"])
    confirm_survey(survey["id"])
    q = log_question(session["id"], surveyor["id"], ctx["elements"]["UM-1"],
                     "UM turnaround controls q1")
    complete_session(session["id"], surveyor["id"])
    complete_survey(survey["id"])

    score_um1 = create_score(app_id, ctx["elements"]["UM-1"])
    score_cr1 = create_score(app_id, ctx["elements"]["CR-1"])
    cr1_final = finalize_score_safe(score_cr1["id"])
    assert cr1_final["awarded_points"] == 4.00, (
        "no CR sample exists -> full file component 2.40 + evidence 1.60"
    )

    r = api_client.finalize_element_score(score_um1["id"], _officer())
    validate_error(r, ApiErrorId.ERR_OPEN_GAP_QUESTIONS_REMAIN)
    assert r.status_code == 422

    adjudicate_question(q["id"], False)
    final = finalize_score_safe(score_um1["id"])
    assert final["status"] == "FINAL"
    assert final["awarded_points"] == 4.00, (
        f"rate 1.0000, evidence 2/2, zero confirmed gaps -> 4.00, got {final['awarded_points']}"
    )


def finalize_score_safe(score_id):
    from test_helpers import finalize_score
    return finalize_score(score_id)


def test_finalize_succeeds_with_zero_open_gap_questions(api):
    """PRD §3.7: "no surveyor question with `raises_gap` true and status
    `LOGGED` may reference this element within this application's surveys" — with
    zero such questions the finalize gate passes.

    Design: Difficulty/boundary_precision_check/finalize_blocked_by_single_open_gap_question
    """
    ctx = setup_scoring()
    score = create_score(ctx["app"]["id"], ctx["elements"]["UM-1"])
    final = finalize_score_safe(score["id"])
    assert final["status"] == "FINAL"
    assert final["awarded_points"] == 4.00


def test_surveyor_session_half_open_overlap(api):
    """PRD §3.5: "The new session's half-open `[start_minute, end_minute)`
    interval must not overlap any other `SCHEDULED` or `COMPLETED` session of
    the same surveyor on the same calendar date; two sessions where one ends
    exactly when the other begins are treated as adjacent, not overlapping
    (violations return `ERR_SURVEYOR_SESSION_OVERLAP`, HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/surveyor_session_half_open_overlap
    """
    ctx = setup_planned_full_survey()
    survey_id = ctx["survey"]["id"]
    surveyor_id = ctx["surveyor"]["id"]
    add_session(survey_id, surveyor_id, session_date="2026-10-05",
                start_minute=540, end_minute=660)

    # Adjacent 660-780: legal (end == start).
    adj = add_session(survey_id, surveyor_id, session_date="2026-10-05",
                      start_minute=660, end_minute=780)
    assert adj["status"] == "SCHEDULED"

    # Overlapping 630-720: rejected.
    r = api_client.create_survey_session(
        survey_id,
        {"surveyor_id": surveyor_id, "session_date": "2026-10-05",
         "start_minute": 630, "end_minute": 720, "is_onsite": False},
        _officer(),
    )
    validate_error(r, ApiErrorId.ERR_SURVEYOR_SESSION_OVERLAP)
    assert r.status_code == 409

    survey = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert survey["scheduled_minutes"] == 240, "120 + 120; the rejected session added nothing"


def test_surveyor_session_adjacency_allowed_on_reschedule(api):
    """PRD §3.5: "the new half-open interval must not overlap another
    `SCHEDULED` or `COMPLETED` session of the same surveyor on the same date
    with adjacency allowed (otherwise `ERR_SURVEYOR_SESSION_OVERLAP`)" — the
    reschedule self-loop observes the same constraint.

    Design: Difficulty/resource_temporal_overlap/surveyor_session_half_open_overlap
    """
    ctx = setup_planned_full_survey()
    survey_id = ctx["survey"]["id"]
    surveyor_id = ctx["surveyor"]["id"]
    s1 = add_session(survey_id, surveyor_id, session_date="2026-10-05",
                     start_minute=540, end_minute=660)
    s2 = add_session(survey_id, surveyor_id, session_date="2026-10-06",
                     start_minute=540, end_minute=660)

    # Reschedule s2 onto 2026-10-05 adjacent to s1: allowed.
    moved = get_success_data(api_client.reschedule_survey_session(
        s2["id"],
        {"session_date": "2026-10-05", "start_minute": 660, "end_minute": 780},
        _officer(),
    ))
    assert moved["status"] == "SCHEDULED"
    assert moved["session_date"] == "2026-10-05"
    assert moved["duration_minutes"] == 120

    # Reschedule s2 onto an interval overlapping s1: rejected.
    r = api_client.reschedule_survey_session(
        s2["id"],
        {"session_date": "2026-10-05", "start_minute": 630, "end_minute": 720},
        _officer(),
    )
    validate_error(r, ApiErrorId.ERR_SURVEYOR_SESSION_OVERLAP)


def test_survey_date_range_closed_interval_overlap(api):
    """PRD §3.5: "no other survey of the same application in `PLANNED` or
    `CONFIRMED` status may have a closed `[start_date, end_date]` date range
    intersecting this survey's `[start_date, end_date]` range, with touching
    boundary dates counting as overlap (otherwise `ERR_SURVEY_DATE_OVERLAP`,
    HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/survey_date_range_closed_interval_overlap
    """
    ctx = setup_planned_full_survey()
    survey_a = ctx["survey"]
    add_session(survey_a["id"], ctx["surveyor"]["id"])
    # A stays PLANNED: the overlap rule covers PLANNED or CONFIRMED surveys.
    # A occupies [2026-10-05, 2026-10-09].

    survey_b = create_survey_on_app(ctx["app"]["id"], survey_type="FULL",
                                    start_date="2026-10-09", end_date="2026-10-12",
                                    budgeted_surveyor_hours=4)
    add_session(survey_b["id"], ctx["surveyor"]["id"], session_date="2026-10-09",
                start_minute=800, end_minute=860)
    r = api_client.confirm_survey(survey_b["id"], _officer())
    validate_error(r, ApiErrorId.ERR_SURVEY_DATE_OVERLAP)
    assert r.status_code == 409
    after = get_success_data(api_client.get_survey(survey_b["id"], _officer()))
    assert after["status"] == "PLANNED"


def test_survey_date_range_clear_after_boundary(api):
    """PRD §3.5: "no other survey of the same application in `PLANNED` or `CONFIRMED` status may have a closed `[start_date, end_date]` date range intersecting this survey's `[start_date, end_date]` range, with touching boundary dates counting as overlap (otherwise `ERR_SURVEY_DATE_OVERLAP`, HTTP 409)" — starting the day after survey A's end date (2026-10-10 vs A's [2026-10-05, 2026-10-09]) is clear and confirms.

    Design: Difficulty/resource_temporal_overlap/survey_date_range_closed_interval_overlap
    """
    ctx = setup_planned_full_survey()
    survey_a = ctx["survey"]
    add_session(survey_a["id"], ctx["surveyor"]["id"])
    # A stays PLANNED, occupying [2026-10-05, 2026-10-09].

    survey_b = create_survey_on_app(ctx["app"]["id"], survey_type="FULL",
                                    start_date="2026-10-10", end_date="2026-10-12",
                                    budgeted_surveyor_hours=4)
    add_session(survey_b["id"], ctx["surveyor"]["id"], session_date="2026-10-10",
                start_minute=800, end_minute=860)
    confirmed = confirm_survey(survey_b["id"])
    assert confirmed["status"] == "CONFIRMED"


def test_survey_active_minutes_conserved_across_cancel_replacement(api):
    """PRD §3.5: "`active_minutes` is `scheduled_minutes` plus
    `completed_minutes`. Cancelling a session and scheduling a replacement of
    equal duration therefore leaves `active_minutes` unchanged — this is the
    conserved quantity of the reconciliation."

    Design: Difficulty/compensating_invariant/survey_active_minutes_conserved_across_cancel_replacement
    """
    ctx = setup_planned_full_survey()
    survey_id = ctx["survey"]["id"]
    surveyor_id = ctx["surveyor"]["id"]
    s1 = add_session(survey_id, surveyor_id, session_date="2026-10-05",
                     start_minute=540, end_minute=660)
    add_session(survey_id, surveyor_id, session_date="2026-10-05",
                start_minute=660, end_minute=780)
    add_session(survey_id, surveyor_id, session_date="2026-10-05",
                start_minute=780, end_minute=900)
    add_session(survey_id, surveyor_id, session_date="2026-10-05",
                start_minute=900, end_minute=1020)

    before = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert before["active_minutes"] == 480

    cancel_session(s1["id"])
    mid = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert mid["active_minutes"] == 360, "480 - 120 after the cancel"
    assert mid["cancelled_minutes"] == 120

    add_session(survey_id, surveyor_id, session_date="2026-10-06",
                start_minute=540, end_minute=660)
    after = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert after["active_minutes"] == 480, "identical to the pre-cancel value"
    assert after["cancelled_minutes"] == 120, (
        "the cancelled ledger grew; it is not part of the conserved quantity"
    )
    assert after["scheduled_minutes"] == 480
    assert after["completed_minutes"] == 0


def test_survey_minutes_track_completion_and_cancellation(api):
    """PRD §3.5: "`scheduled_minutes` is the sum of `duration_minutes` over
    sessions in `SCHEDULED`; `completed_minutes` is the same sum over
    `COMPLETED` sessions; `cancelled_minutes` is the same sum over `CANCELLED`
    sessions; and `active_minutes` is `scheduled_minutes` plus
    `completed_minutes`."

    Design: Difficulty/compensating_invariant/survey_active_minutes_conserved_across_cancel_replacement
    """
    ctx = setup_planned_full_survey()
    survey_id = ctx["survey"]["id"]
    surveyor_id = ctx["surveyor"]["id"]
    s1 = add_session(survey_id, surveyor_id, session_date="2026-10-05",
                     start_minute=540, end_minute=660)
    s2 = add_session(survey_id, surveyor_id, session_date="2026-10-06",
                     start_minute=540, end_minute=660)
    confirm_survey(survey_id)
    complete_session(s1["id"], surveyor_id)

    mid = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert mid["completed_minutes"] == 120
    assert mid["scheduled_minutes"] == 120
    assert mid["active_minutes"] == 240

    cancel_session(s2["id"])
    after = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert after["cancelled_minutes"] == 120
    assert after["active_minutes"] == 120


def test_onsite_same_date_conflict(api):
    """PRD §3.5: "At most one on-site session per calendar date per survey: if
    `is_onsite` is true and another non-`CANCELLED` on-site session of the same
    survey already exists on that date, the request is rejected with
    `ERR_ONSITE_SAME_DATE_CONFLICT` (HTTP 409)."

    Design: Corner/validations/onsite_same_date_conflict
    """
    ctx = setup_planned_full_survey()
    survey_id = ctx["survey"]["id"]
    surveyor_id = ctx["surveyor"]["id"]
    add_session(survey_id, surveyor_id, session_date="2026-10-05",
                start_minute=540, end_minute=660, is_onsite=True)

    r = api_client.create_survey_session(
        survey_id,
        {"surveyor_id": surveyor_id, "session_date": "2026-10-05",
         "start_minute": 780, "end_minute": 900, "is_onsite": True},
        _officer(),
    )
    validate_error(r, ApiErrorId.ERR_ONSITE_SAME_DATE_CONFLICT)
    assert r.status_code == 409

    # A virtual session on the same date at a disjoint time is fine.
    ok = add_session(survey_id, surveyor_id, session_date="2026-10-05",
                     start_minute=780, end_minute=900, is_onsite=False)
    assert ok["status"] == "SCHEDULED"


def test_session_outside_survey_window_rejected(api):
    """PRD §3.5: "The `session_date` must fall within the survey's
    `[start_date, end_date]` window inclusive (otherwise
    `ERR_SESSION_OUTSIDE_SURVEY_WINDOW`)."

    Design: Corner/validations/session_outside_survey_window_rejected
    """
    ctx = setup_planned_full_survey()
    r = api_client.create_survey_session(
        ctx["survey"]["id"],
        {"surveyor_id": ctx["surveyor"]["id"], "session_date": "2026-10-10",
         "start_minute": 540, "end_minute": 660, "is_onsite": False},
        _officer(),
    )
    validate_error(r, ApiErrorId.ERR_SESSION_OUTSIDE_SURVEY_WINDOW)
    assert r.status_code == 422


def test_survey_complete_blocked_by_unfinished_session(api):
    """PRD §3.5: "A confirmed survey completes when the officer marks it
    complete and every session under it is finished — meaning every session is
    in `COMPLETED` or `CANCELLED`; a survey with any session still `SCHEDULED`
    is rejected with `ERR_SESSIONS_NOT_FINISHED`."

    Design: Corner/state_machines/survey_complete_blocked_by_unfinished_session
    """
    ctx = setup_planned_full_survey()
    survey_id = ctx["survey"]["id"]
    surveyor_id = ctx["surveyor"]["id"]
    s1 = add_session(survey_id, surveyor_id, session_date="2026-10-05",
                     start_minute=540, end_minute=660)
    add_session(survey_id, surveyor_id, session_date="2026-10-06",
                start_minute=540, end_minute=660)
    confirm_survey(survey_id)
    complete_session(s1["id"], surveyor_id)

    r = api_client.complete_survey(survey_id, _officer())
    validate_error(r, ApiErrorId.ERR_SESSIONS_NOT_FINISHED)
    assert r.status_code == 409
    after = get_success_data(api_client.get_survey(survey_id, _officer()))
    assert after["status"] == "CONFIRMED"


def test_sample_submit_below_required_size(api):
    """PRD §3.4: "submission while the case count is still short is rejected
    with `ERR_SAMPLE_INCOMPLETE` (HTTP 422)."

    Design: Corner/state_machines/sample_submit_below_required_size
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    sample = create_sample(app_id, required_size=5)
    fill_sample_with_cases(sample["id"], plan_id, BASE_TIMELY_CASES[:4], prefix="C")

    r = api_client.submit_file_review_sample(sample["id"],
                                             make_plan_coordinator_headers_for(ctx))
    validate_error(r, ApiErrorId.ERR_SAMPLE_INCOMPLETE)
    assert r.status_code == 422

    add_case(sample["id"], plan_id, case_reference="C5", **BASE_TIMELY_CASES[4])
    submitted = submit_sample(sample["id"], plan_id)
    assert submitted["status"] == "SUBMITTED"

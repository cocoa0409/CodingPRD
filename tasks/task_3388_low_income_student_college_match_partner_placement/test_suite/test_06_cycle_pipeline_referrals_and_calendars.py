"""Cycle pipeline gates, referral lifecycle (conversion, expiry, polymorphic
referrer), and the two interval-overlap regimes (prep programs half-open,
cycle windows closed)."""
from test_helpers import (
    ApiErrorId,
    CLOCK_PAST_ALL_WINDOWS,
    TEST_USERS,
    advance_cycle_to_phase,
    assert_match_cycle,
    create_application,
    create_community_partner,
    create_counselor,
    create_cycle,
    create_cycle_payload,
    create_prep_program,
    create_prep_program_payload,
    create_referral,
    create_student,
    expect_created,
    expect_error,
    expect_success,
    get_cycle,
    make_counselor_headers,
    make_partner_staff_headers,
    reset_clock,
    set_clock,
    setup_finalist_application,
    setup_submitted_application,
    submit_application,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_advance_to_match_run_blocked_while_reviews_pending(api):
    """PRD §3.4: "The advance from `RANKING` to `MATCH_RUN` is the point of no
    return, and it is gated twice: the logical clock must have reached
    `ranking_closes_at`, and no application of the cycle may still be sitting
    in `UNDER_REVIEW`. Either failure rejects the advance with
    `ERR_CYCLE_BLOCKED`."

    Design: Corner/state_machines/advance_to_match_run_blocked_while_reviews_pending
    """
    ctx = setup_submitted_application()  # application stays UNDER_REVIEW
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_PAST_ALL_WINDOWS)
    resp = api.advance_cycle(ctx["cycle"]["id"], _ADMIN)
    expect_error(resp, ApiErrorId.ERR_CYCLE_BLOCKED)
    assert get_cycle(ctx["cycle"]["id"])["phase"] == "RANKING", (
        "a blocked advance leaves the cycle in RANKING"
    )


def test_advance_to_regular_decision_before_run_returns_cycle_blocked(api):
    """PRD §3.5: "Until the run has executed, the advance from `MATCH_RUN` to
    `REGULAR_DECISION` is blocked with `ERR_CYCLE_BLOCKED` — the pipeline
    cannot skip its own match."

    Design: Corner/state_machines/advance_to_regular_decision_before_run_returns_cycle_blocked
    """
    ctx = setup_finalist_application()
    advance_cycle_to_phase(ctx["cycle"]["id"], "MATCH_RUN")
    resp = api.advance_cycle(ctx["cycle"]["id"], _ADMIN)
    expect_error(resp, ApiErrorId.ERR_CYCLE_BLOCKED)
    assert get_cycle(ctx["cycle"]["id"])["phase"] == "MATCH_RUN"


def test_referral_converts_on_submit(api):
    """PRD §3.3: "A successful submit stamps `submitted_at` from the logical
    clock, flips the cited referral (when there is one) from `NOMINATED` to
    `CONVERTED`, advances the student's `student_stage` to `APPLICANT`, and
    increments the application's `version`."
    PRD §3.2: "The only path to `CONVERTED` runs through application
    submission in §3.3, and a converted referral is what later feeds the
    referral bonus in regular-pool ordering (§3.8)."

    Design: Corner/state_machines/referral_converts_on_submit
    """
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    counselor = create_counselor()
    partner = create_community_partner()
    student = create_student()
    cited = create_referral(
        student["id"], cycle["id"], make_counselor_headers(counselor["id"])
    )
    uncited = create_referral(
        student["id"], cycle["id"], make_partner_staff_headers(partner["id"])
    )
    advance_cycle_to_phase(cycle["id"], "APPLICATION_OPEN")
    application = create_application(
        student["id"], cycle["id"], referral_id=cited["id"]
    )
    submit_application(application["id"], student["id"])
    ref_cited = expect_success(api.get_referral(cited["id"], _ADMIN), 200)
    ref_uncited = expect_success(api.get_referral(uncited["id"], _ADMIN), 200)
    assert ref_cited["status"] == "CONVERTED", (
        "the referral cited by the submitted application converts"
    )
    assert ref_uncited["status"] == "NOMINATED", (
        "the same student's uncited referral is untouched"
    )


def test_referral_expires_when_application_window_closes(api):
    """PRD §3.2: "Nominations the student never acted on die with the
    application window: the cycle's advance from `APPLICATION_OPEN` to
    `REVIEW` moves every still-`NOMINATED` referral of that cycle to
    `EXPIRED`."

    Design: Corner/state_machines/referral_expires_when_application_window_closes
    """
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    counselor = create_counselor()
    student = create_student()
    referral = create_referral(
        student["id"], cycle["id"], make_counselor_headers(counselor["id"])
    )
    assert referral["status"] == "NOMINATED"
    advance_cycle_to_phase(cycle["id"], "REVIEW")
    refreshed = expect_success(api.get_referral(referral["id"], _ADMIN), 200)
    assert refreshed["status"] == "EXPIRED", (
        "the APPLICATION_OPEN -> REVIEW advance sweeps NOMINATED referrals"
    )


def test_referral_polymorphic_referrer_sets_exactly_one_fk(api):
    """PRD §3.2: "The referrer's identity is recorded polymorphically from the
    role headers: when a counselor files the nomination the referral's
    `counselor_id` is set from `X-User-ID` and `partner_id` stays null; when
    partner staff file it the `partner_id` is set and `counselor_id` stays
    null."

    Design: Corner/entities/referral_polymorphic_referrer_sets_exactly_one_fk
    """
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    counselor = create_counselor()
    partner = create_community_partner()
    student = create_student()
    by_counselor = create_referral(
        student["id"], cycle["id"], make_counselor_headers(counselor["id"]),
        note="counselor nomination",
    )
    assert by_counselor["counselor_id"] == counselor["id"]
    assert by_counselor["partner_id"] is None
    assert by_counselor["status"] == "NOMINATED"
    by_partner = create_referral(
        student["id"], cycle["id"], make_partner_staff_headers(partner["id"]),
        note="partner nomination",
    )
    assert by_partner["partner_id"] == partner["id"]
    assert by_partner["counselor_id"] is None
    assert by_partner["status"] == "NOMINATED"


def test_prep_program_touching_intervals_allowed(api):
    """PRD §3.2: "The interval is half-open: it includes its start and
    excludes its end. A new enrollment is rejected with `ERR_PROGRAM_OVERLAP`
    whenever its interval intersects another non-`WITHDRAWN` enrollment of the
    same student; touching endpoints do not intersect, so back-to-back
    programs are allowed."

    Design: Difficulty/resource_temporal_overlap/prep_program_half_open_adjacency_allows_touching_intervals
    """
    reset_clock()
    student = create_student()
    first = create_prep_program(
        student["id"], program_type="SUMMER", cohort_label="s-2026",
        starts_on="2026-06-01T00:00:00Z", ends_on="2026-08-01T00:00:00Z",
    )
    second = create_prep_program(
        student["id"], program_type="SCHOLAR", cohort_label="f-2026",
        starts_on="2026-08-01T00:00:00Z", ends_on="2026-09-01T00:00:00Z",
    )
    assert first["status"] == "ENROLLED"
    assert second["status"] == "ENROLLED", (
        "a program starting exactly at another's ends_on shares no instant "
        "with it (half-open), so it must be created"
    )


def test_prep_program_intersecting_interval_rejected(api):
    """PRD §3.2: "A new enrollment is rejected with `ERR_PROGRAM_OVERLAP`
    whenever its interval intersects another non-`WITHDRAWN` enrollment of the
    same student; touching endpoints do not intersect, so back-to-back
    programs are allowed."

    Design: Difficulty/resource_temporal_overlap/prep_program_half_open_adjacency_allows_touching_intervals
    """
    reset_clock()
    student = create_student()
    create_prep_program(
        student["id"], program_type="SUMMER", cohort_label="s-2026",
        starts_on="2026-06-01T00:00:00Z", ends_on="2026-08-01T00:00:00Z",
    )
    payload = create_prep_program_payload(
        student["id"], program_type="SUMMER", cohort_label="x-2026",
        starts_on="2026-07-15T00:00:00Z", ends_on="2026-08-15T00:00:00Z",
    )
    resp = api.create_prep_program(payload, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_PROGRAM_OVERLAP, payload)


def test_cycle_touching_application_window_date_rejected(api):
    """PRD §3.1: "One scheduling rule protects the calendar: the new cycle's
    application window must not share a single date with the application
    window of any cycle that is not yet `CLOSED`. Because the windows are
    closed intervals, two windows that merely touch on one date still
    conflict, and such a create is rejected with `ERR_CYCLE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/cycle_window_closed_interval_touching_date_conflicts
    """
    reset_clock()
    create_cycle()  # application window 2026-09-01 .. 2026-09-30 (inclusive)
    payload = create_cycle_payload(
        name="Cycle B",
        app_opens_at="2026-09-30T00:00:00Z",
        app_closes_at="2026-10-30T23:59:59Z",
        ranking_opens_at="2026-11-15T00:00:00Z",
        ranking_closes_at="2026-11-30T23:59:59Z",
    )
    resp = api.create_cycle(payload, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP, payload)


def test_cycle_disjoint_application_window_accepted(api):
    """PRD §3.1: "One scheduling rule protects the calendar: the new cycle's
    application window must not share a single date with the application
    window of any cycle that is not yet `CLOSED`." — a window opening the day
    after the existing window's last date shares no date with it.
    PRD §3.1: "The new cycle's `phase` starts at `SETUP` and its
    `match_run_completed` flag starts false."

    Design: Difficulty/resource_temporal_overlap/cycle_window_closed_interval_touching_date_conflicts
    """
    reset_clock()
    create_cycle()  # application window covers 2026-09-01 .. 2026-09-30
    payload = create_cycle_payload(
        name="Cycle C",
        app_opens_at="2026-10-01T00:00:00Z",
        app_closes_at="2026-10-31T23:59:59Z",
        ranking_opens_at="2026-11-15T00:00:00Z",
        ranking_closes_at="2026-11-30T23:59:59Z",
    )
    resp = api.create_cycle(payload, _ADMIN)
    data = expect_created(resp, payload)
    assert_match_cycle(data)
    assert data["phase"] == "SETUP"
    assert data["match_run_completed"] is False

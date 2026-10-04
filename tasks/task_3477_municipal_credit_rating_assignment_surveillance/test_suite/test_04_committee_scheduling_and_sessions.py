"""Committee scheduling rules and session lifecycle edges.

Covers the chair calendar's half-open overlap semantics, the 24-hour
same-engagement cooling-off buffer, the exactly-five voter pool rule, the
half-open open window, chair-cancel adjournment, and role/state guards on
close and voting (PRD sections 2.1, 2.10 and 3.3).
"""

from test_helpers import (
    CHAIR_HEADERS,
    ApiErrorId,
    advance_clock,
    cast_vote,
    get_engagement,
    get_ratings_for_engagement,
    get_session,
    make_committee_member_headers,
    open_session,
    schedule_session,
    session_payload,
    setup_active_criteria,
    setup_committee_ready_engagement,
    create_issuer,
    validate_error,
    validate_paginated,
    validate_success,
)

WINDOW_START = "2026-09-02T10:00:00Z"
WINDOW_END = "2026-09-02T12:00:00Z"


def test_chair_calendar_half_open_adjacency(api):
    """PRD section 3.3: "The chair may not hold another `SCHEDULED` or
    `IN_SESSION` session whose half-open window intersects the requested one —
    windows that merely touch, one ending exactly as the other begins, are
    permitted, while a true overlap is rejected with
    `ERR_SESSION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/chair_calendar_half_open_adjacency
    """
    issuer = create_issuer(api)
    criteria = setup_active_criteria(api)
    ctx_a = setup_committee_ready_engagement(
        api, issuer=issuer, criteria_version=criteria
    )
    ctx_b = setup_committee_ready_engagement(
        api, issuer=issuer, criteria_version=criteria
    )
    ctx_c = setup_committee_ready_engagement(
        api, issuer=issuer, criteria_version=criteria
    )

    resp_a = api.schedule_session(
        ctx_a["engagement"]["id"],
        session_payload(start_at=WINDOW_START, end_at=WINDOW_END),
        headers=CHAIR_HEADERS,
    )
    validate_success(resp_a, 201)

    resp_b = api.schedule_session(
        ctx_b["engagement"]["id"],
        session_payload(
            start_at="2026-09-02T12:00:00Z", end_at="2026-09-02T14:00:00Z"
        ),
        headers=CHAIR_HEADERS,
    )
    validate_success(resp_b, 201)
    # B.start == A.end: adjacency is not overlap under half-open semantics.

    resp_c = api.schedule_session(
        ctx_c["engagement"]["id"],
        session_payload(
            start_at="2026-09-02T11:00:00Z", end_at="2026-09-02T13:00:00Z"
        ),
        headers=CHAIR_HEADERS,
    )
    validate_error(resp_c, ApiErrorId.ERR_SESSION_WINDOW_OVERLAP)


def test_engagement_cooling_off_buffer_24h(api):
    """PRD section 3.3: "a new session on the same engagement must respect a
    24-hour cooling-off: its `start_at` may not fall earlier than 24 hours
    after the latest prior session's `end_at` on that engagement, though a gap
    of exactly 24 hours is allowed; violations yield
    `ERR_SESSION_COOLING_OFF`."

    Design: Difficulty/resource_temporal_overlap/engagement_cooling_off_buffer_24h
    """
    ctx = setup_committee_ready_engagement(api)
    engagement_id = ctx["engagement"]["id"]

    first = api.schedule_session(
        engagement_id,
        session_payload(start_at=WINDOW_START, end_at=WINDOW_END),
        headers=CHAIR_HEADERS,
    )
    validate_success(first, 201)

    too_soon = api.schedule_session(
        engagement_id,
        session_payload(
            start_at="2026-09-02T20:00:00Z", end_at="2026-09-02T22:00:00Z"
        ),
        headers=CHAIR_HEADERS,
    )
    validate_error(too_soon, ApiErrorId.ERR_SESSION_COOLING_OFF)

    exactly_24h = api.schedule_session(
        engagement_id,
        session_payload(
            start_at="2026-09-03T12:00:00Z", end_at="2026-09-03T14:00:00Z"
        ),
        headers=CHAIR_HEADERS,
    )
    # start == prior end_at + 24h sits on the inclusive-permitting boundary.
    validate_success(exactly_24h, 201)


def test_undersized_voter_pool_rejected(api):
    """PRD section 3.3: "Scheduling a session takes a `start_at` and an
    `end_at` ... and a `voter_ids` pool of exactly 5 distinct voter
    identifiers, with any other pool rejected as `ERR_VOTER_POOL_INVALID`."

    Design: Corner/errors/undersized_voter_pool_rejected
    """
    ctx = setup_committee_ready_engagement(api)
    resp = api.schedule_session(
        ctx["engagement"]["id"],
        session_payload(voter_ids=["voter-1", "voter-2", "voter-3", "voter-4"]),
        headers=CHAIR_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_VOTER_POOL_INVALID)
    sessions, meta = validate_paginated(
        api.list_sessions(
            headers=CHAIR_HEADERS,
            params={"engagement_id": ctx["engagement"]["id"]},
        )
    )
    assert sessions == [] and meta["total_count"] == 0


def test_session_open_window_half_open_enforcement(api):
    """PRD section 3.3: "Opening moves a session `SCHEDULED` → `IN_SESSION`
    and may happen only inside its window: the clock must have reached
    `start_at` and must not yet have reached `end_at`, otherwise the open
    fails with `ERR_SESSION_NOT_OPENABLE`."

    Design: Corner/state_machines/session_open_window_half_open_enforcement
    """
    ctx = setup_committee_ready_engagement(api)
    session = schedule_session(
        api,
        ctx["engagement"],
        start_at="2026-09-02T10:00:00Z",
        end_at="2026-09-02T10:01:00Z",
    )

    advance_clock(api, "2026-09-02T09:59:59Z")
    early = api.open_session(session["id"], headers=CHAIR_HEADERS)
    validate_error(early, ApiErrorId.ERR_SESSION_NOT_OPENABLE)

    advance_clock(api, "2026-09-02T10:01:00Z")
    late = api.open_session(session["id"], headers=CHAIR_HEADERS)
    validate_error(late, ApiErrorId.ERR_SESSION_NOT_OPENABLE)

    current = get_session(api, session["id"])
    assert current["status"] == "SCHEDULED", (
        "both rejections leave the session unopened"
    )


def test_session_close_from_scheduled_adjourns_without_votes(api):
    """PRD section 3.3: "If the chair closes a session that was never opened,
    the session is adjourned outright with `adjourn_reason` `QUORUM_NOT_MET`
    and zero votes recorded."
    PRD section 3.3: "An adjourned session, by contrast, leaves the engagement
    `COMMITTEE_READY`, and the chair may schedule a fresh session for another
    attempt".

    Design: Corner/state_machines/session_close_from_scheduled_adjourns_without_votes
    """
    ctx = setup_committee_ready_engagement(api)
    session = schedule_session(api, ctx["engagement"])
    resp = api.close_session(session["id"], headers=CHAIR_HEADERS)
    closed = validate_success(resp, 200)
    assert closed["status"] == "ADJOURNED"
    assert closed["adjourn_reason"] == "QUORUM_NOT_MET"
    assert closed["outcome_notch"] is None
    assert get_ratings_for_engagement(api, ctx["engagement"]["id"]) == [], (
        "an adjourned session assigns no rating"
    )
    assert get_engagement(api, ctx["engagement"]["id"])["status"] == (
        "COMMITTEE_READY"
    )


def test_committee_member_cannot_close_session(api):
    """PRD section 3.3: "Closing the session — again, only the scheduling
    chair — tallies the committee."
    PRD section 2.1: "Each endpoint admits a fixed set of roles; a caller
    whose role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/committee_member_cannot_close_session
    """
    ctx = setup_committee_ready_engagement(api)
    session = schedule_session(api, ctx["engagement"])
    session = open_session(api, session)
    cast_vote(api, session["id"], "voter-1", notch="A")
    resp = api.close_session(
        session["id"], headers=make_committee_member_headers("voter-1")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_session(api, session["id"])["status"] == "IN_SESSION", (
        "no tally ran on the rejected close"
    )


def test_vote_on_scheduled_session_rejected(api):
    """PRD section 3.3: "While a session is `IN_SESSION`, each
    `CommitteeMember` casts exactly one ballot; any ballot offered while the
    session is in another state is rejected with `ERR_SESSION_STATE_INVALID`."

    Design: Corner/errors/vote_on_scheduled_session_rejected
    """
    ctx = setup_committee_ready_engagement(api)
    session = schedule_session(api, ctx["engagement"])
    # The clock sits inside the window, but open was never called: the state
    # gate, not the temporal window, governs voting.
    advance_clock(api, "2026-09-02T10:30:00Z")
    resp = api.cast_vote(
        session["id"],
        {"voter_id": "voter-1", "notch_vote": "A"},
        headers=make_committee_member_headers("voter-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_STATE_INVALID)
    votes, _meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert votes == []

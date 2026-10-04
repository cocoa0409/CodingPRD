"""Boundary precision on the ranking-list size and the state-before-window
validation priority on ranking submission."""
from test_helpers import (
    ApiErrorId,
    CLOCK_IN_RANKING_WINDOW,
    CLOCK_PAST_ALL_WINDOWS,
    MAX_RANKS,
    TEST_USERS,
    advance_cycle_to_phase,
    create_college,
    create_colleges,
    expect_error,
    get_application,
    get_current_rankings,
    make_student_headers,
    ranking_entry,
    set_clock,
    setup_finalist_application,
    setup_submitted_application,
    submit_rankings,
    submit_rankings_payload,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def _finalist_with_many_colleges(college_count):
    """One FINALIST application in a cycle parked in RANKING with the clock
    inside the ranking window, plus `college_count` ACTIVE colleges."""
    ctx = setup_finalist_application()
    colleges = create_colleges(college_count)
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    return ctx, colleges


def test_twelve_rank_entries_accepted(api):
    """PRD §3.4: "the list must hold at least 1 and at most 12 entries — more
    than twelve is `ERR_TOO_MANY_RANKS`, an empty list is
    `ERR_INVALID_REQUEST`; and the positions must be exactly the contiguous
    integers 1 through N with no repeats and no college appearing twice,
    otherwise `ERR_RANK_ORDER_INVALID`."

    Design: Difficulty/boundary_precision_check/twelfth_rank_accepted_thirteenth_rejected
    """
    ctx, colleges = _finalist_with_many_colleges(13)
    entries = [
        ranking_entry(college["id"], i + 1) for i, college in enumerate(colleges[:12])
    ]
    assert len(entries) == MAX_RANKS
    ranked = submit_rankings(
        ctx["application"]["id"], ctx["student"]["id"],
        entries, ctx["application_version"],
    )
    assert ranked["status"] == "RANKING_SUBMITTED", (
        "exactly MAX_RANKS (12) entries is accepted"
    )
    rows = get_current_rankings(ctx["application"]["id"])
    assert len(rows) == 12
    assert sorted(row["rank_position"] for row in rows) == list(range(1, 13))
    assert all(row["list_seq"] == 1 for row in rows)


def test_thirteen_rank_entries_rejected_and_prior_list_intact(api):
    """PRD §3.4: "the list must hold at least 1 and at most 12 entries — more
    than twelve is `ERR_TOO_MANY_RANKS`, an empty list is
    `ERR_INVALID_REQUEST`; ..."
    PRD §3.4: "An accepted submission replaces the application's ranking rows
    atomically — the previous list is discarded wholesale, never edited row by
    row — and the new rows carry a `list_seq` one higher than the previous
    list's, starting at 1 on the first accepted submission."

    Design: Difficulty/boundary_precision_check/twelfth_rank_accepted_thirteenth_rejected
    """
    ctx, colleges = _finalist_with_many_colleges(13)
    headers = make_student_headers(ctx["student"]["id"])
    accepted = submit_rankings(
        ctx["application"]["id"], ctx["student"]["id"],
        [ranking_entry(college["id"], i + 1) for i, college in enumerate(colleges[:12])],
        ctx["application_version"],
    )
    over_payload = submit_rankings_payload(
        [ranking_entry(college["id"], i + 1) for i, college in enumerate(colleges)],
        accepted["version"],
    )
    assert len(over_payload["entries"]) == MAX_RANKS + 1
    resp = api.submit_rankings(ctx["application"]["id"], over_payload, headers)
    expect_error(resp, ApiErrorId.ERR_TOO_MANY_RANKS, over_payload)
    rows = get_current_rankings(ctx["application"]["id"])
    assert len(rows) == 12, "the rejected 13-entry list replaces nothing"
    assert all(row["list_seq"] == 1 for row in rows), (
        "the accepted 12-entry list is still list_seq 1"
    )
    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["version"] == accepted["version"]


def _under_review_application_past_ranking_window():
    """One application stuck in UNDER_REVIEW while the cycle sits in RANKING
    with the logical clock past ranking_closes_at."""
    ctx = setup_submitted_application()
    college = create_college()
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_PAST_ALL_WINDOWS)
    return ctx, college


def test_state_error_beats_window_closed_on_rankings(api):
    """PRD §2.10: "When a single request could fail several checks at once,
    the earliest failure in a fixed global order wins and later checks are
    never evaluated." — the order places "5. State-machine legality of the
    requested transition — `ERR_INVALID_STATE` (HTTP 409)." ahead of "7.
    Time-window checks against the logical clock — `ERR_WINDOW_CLOSED` (HTTP
    409) for application submission and ranking submission outside their
    windows, ...".
    PRD §3.4: "The guards fire in the global order: the application must be
    `FINALIST` or `RANKING_SUBMITTED` (`ERR_INVALID_STATE`); the cycle must be
    in `RANKING` (`ERR_WRONG_CYCLE_PHASE`); the logical clock must sit inside
    the ranking window, both `ranking_opens_at` and `ranking_closes_at`
    inclusive (`ERR_WINDOW_CLOSED`); ..."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_window_closed_on_rankings
    """
    ctx, college = _under_review_application_past_ranking_window()
    payload = submit_rankings_payload(
        [ranking_entry(college["id"], 1)], ctx["application_version"]
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(ctx["student"]["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_INVALID_STATE, payload)


def test_state_rejection_creates_no_ranking_rows(api):
    """PRD §2.10: "When a single request could fail several checks at once,
    the earliest failure in a fixed global order wins and later checks are
    never evaluated." — the state rejection pre-empts the window check, so the
    request performs no transition at all.
    PRD §3.4: "the application must be `FINALIST` or `RANKING_SUBMITTED`
    (`ERR_INVALID_STATE`)" — an UNDER_REVIEW application has no accepted list.

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_window_closed_on_rankings
    """
    ctx, college = _under_review_application_past_ranking_window()
    payload = submit_rankings_payload(
        [ranking_entry(college["id"], 1)], ctx["application_version"]
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(ctx["student"]["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_INVALID_STATE, payload)
    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["status"] == "UNDER_REVIEW"
    assert get_current_rankings(ctx["application"]["id"]) == [], (
        "a state-rejected submission must create no RankingEntry rows"
    )

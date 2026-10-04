"""Review gating and the ranking-submission rule set: window, shape,
referential, suspension, OCC, the append-only row shape, and the per-mutation
version counter."""
from test_helpers import (
    ApiErrorId,
    CLOCK_IN_RANKING_WINDOW,
    CLOCK_PAST_ALL_WINDOWS,
    TEST_USERS,
    UNKNOWN_UUID,
    advance_cycle_to_phase,
    assert_ranking_entry,
    create_college,
    expect_error,
    expect_success,
    get_application,
    get_current_rankings,
    make_student_headers,
    ranking_entry,
    review_payload,
    set_clock,
    setup_draft_application,
    setup_finalist_application,
    setup_ranking_submitted,
    setup_submitted_application,
    submit_application,
    submit_rankings,
    submit_rankings_payload,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_review_during_application_open_returns_wrong_cycle_phase(api):
    """PRD §3.4: "Reviewing an application that is not currently
    `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`, and review attempted
    outside the `REVIEW` phase fails with `ERR_WRONG_CYCLE_PHASE`."

    Design: Corner/validations/review_during_application_open_returns_wrong_cycle_phase
    """
    ctx = setup_submitted_application()
    payload = review_payload("FINALIST")
    resp = api.review_application(ctx["application"]["id"], payload, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_WRONG_CYCLE_PHASE, payload)


def test_review_already_decided_returns_invalid_state(api):
    """PRD §3.4: "Reviewing an application that is not currently
    `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`, and review attempted
    outside the `REVIEW` phase fails with `ERR_WRONG_CYCLE_PHASE`."

    Design: Corner/state_machines/review_already_decided_returns_invalid_state
    """
    ctx = setup_finalist_application()
    payload = review_payload("NOT_FINALIST")
    resp = api.review_application(ctx["application"]["id"], payload, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_INVALID_STATE, payload)
    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["status"] == "FINALIST", (
        "a rejected review leaves the earlier committee decision in place"
    )


def test_ranking_entry_carries_no_version_or_updated_at(api):
    """PRD §2.5: "`RankingEntry` is the single exception to this convention. A
    ranking row carries only `id` and `created_at`; both `updated_at` and
    `version` are absent, because a ranking row is never mutated in place —
    revision replaces the whole list atomically, as §3.4 describes."
    PRD §3.4: "An accepted submission replaces the application's ranking rows
    atomically — the previous list is discarded wholesale, never edited row by
    row — and the new rows carry a `list_seq` one higher than the previous
    list's, starting at 1 on the first accepted submission."

    Design: Corner/entities/ranking_entry_carries_no_version_or_updated_at
    """
    ctx = setup_ranking_submitted()
    rows = ctx["ranking_entries"]
    assert len(rows) == 1, f"one accepted one-entry list, got {len(rows)} rows"
    row = rows[0]
    assert_ranking_entry(row)  # pins id/created_at present, no version/updated_at
    assert row["college_id"] == ctx["college"]["id"]
    assert row["rank_position"] == 1
    assert row["list_seq"] == 1
    assert row["application_id"] == ctx["application"]["id"]


def test_rankings_after_window_returns_window_closed(api):
    """PRD §3.4: "The guards fire in the global order: the application must be
    `FINALIST` or `RANKING_SUBMITTED` (`ERR_INVALID_STATE`); the cycle must be
    in `RANKING` (`ERR_WRONG_CYCLE_PHASE`); the logical clock must sit inside
    the ranking window, both `ranking_opens_at` and `ranking_closes_at`
    inclusive (`ERR_WINDOW_CLOSED`); ..."

    Design: Corner/validations/rankings_after_window_returns_window_closed
    """
    ctx = setup_finalist_application()
    college = create_college()
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_PAST_ALL_WINDOWS)
    payload = submit_rankings_payload(
        [ranking_entry(college["id"], 1)], ctx["application_version"]
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(ctx["student"]["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_WINDOW_CLOSED, payload)


def test_non_contiguous_or_duplicate_rankings_return_rank_order_invalid(api):
    """PRD §3.4: "and the positions must be exactly the contiguous integers 1
    through N with no repeats and no college appearing twice, otherwise
    `ERR_RANK_ORDER_INVALID`."

    Design: Corner/validations/non_contiguous_or_duplicate_rankings_return_rank_order_invalid
    """
    ctx = setup_finalist_application()
    college_a = create_college()
    college_b = create_college()
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    version = ctx["application_version"]
    headers = make_student_headers(ctx["student"]["id"])

    gap_payload = submit_rankings_payload(
        [ranking_entry(college_a["id"], 1), ranking_entry(college_b["id"], 3)],
        version,
    )
    resp = api.submit_rankings(ctx["application"]["id"], gap_payload, headers)
    expect_error(resp, ApiErrorId.ERR_RANK_ORDER_INVALID, gap_payload)

    dupe_payload = submit_rankings_payload(
        [ranking_entry(college_a["id"], 1), ranking_entry(college_a["id"], 2)],
        version,
    )
    resp = api.submit_rankings(ctx["application"]["id"], dupe_payload, headers)
    expect_error(resp, ApiErrorId.ERR_RANK_ORDER_INVALID, dupe_payload)

    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["status"] == "FINALIST"
    assert refreshed["version"] == version, (
        "two rejected submissions must not advance the application's version"
    )
    assert get_current_rankings(ctx["application"]["id"]) == [], (
        "no ranking rows may exist after two rejected submissions"
    )


def test_unknown_college_in_rankings_returns_unknown_college(api):
    """PRD §3.4: "every `college_id` in the list must resolve to an existing
    partner college (`ERR_UNKNOWN_COLLEGE`) and must name an `ACTIVE` college
    (`ERR_COLLEGE_INACTIVE`)"

    Design: Corner/validations/unknown_college_in_rankings_returns_unknown_college
    """
    ctx = setup_finalist_application()
    create_college()
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    payload = submit_rankings_payload(
        [ranking_entry(UNKNOWN_UUID, 1)], ctx["application_version"]
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(ctx["student"]["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_UNKNOWN_COLLEGE, payload)


def test_suspended_college_in_new_ranking_list_returns_college_inactive(api):
    """PRD §3.4: "every `college_id` in the list must resolve to an existing
    partner college (`ERR_UNKNOWN_COLLEGE`) and must name an `ACTIVE` college
    (`ERR_COLLEGE_INACTIVE`)"
    PRD §3.1: "a suspended college is excluded from future ranking submissions
    and from the next match run, while its existing matches and aid packages
    are entirely unaffected."

    Design: Corner/validations/suspended_college_in_new_ranking_list_returns_college_inactive
    """
    ctx = setup_finalist_application()
    college = create_college()
    expect_success(api.suspend_college(college["id"], _ADMIN), 200)
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    payload = submit_rankings_payload(
        [ranking_entry(college["id"], 1)], ctx["application_version"]
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(ctx["student"]["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_COLLEGE_INACTIVE, payload)


def test_rankings_stale_version_returns_stale_version(api):
    """PRD §2.8: "Submitting or revising a student's ranking list requires the
    request to carry `expected_application_version`, the caller's last
    observed `version` of the application. If the application's current
    `version` has advanced since the caller last read it — because a prior
    accepted submission already replaced the list and moved the version
    forward — the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the
    caller would otherwise overwrite a list they have never seen."

    Design: Corner/cross_cutting_layers/rankings_stale_version_returns_stale_version
    """
    ctx = setup_finalist_application()
    college_a = create_college()
    college_b = create_college()
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    pre_submit_version = ctx["application_version"]
    submit_rankings(
        ctx["application"]["id"], ctx["student"]["id"],
        [ranking_entry(college_a["id"], 1)], pre_submit_version,
    )
    stale_payload = submit_rankings_payload(
        [ranking_entry(college_b["id"], 1)], pre_submit_version
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], stale_payload,
        make_student_headers(ctx["student"]["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_STALE_VERSION, stale_payload)
    rows = get_current_rankings(ctx["application"]["id"])
    assert len(rows) == 1
    assert rows[0]["college_id"] == college_a["id"]
    assert rows[0]["list_seq"] == 1, (
        "the stale resubmission must not replace the accepted list"
    )


def test_application_version_increments_on_each_mutation(api):
    """PRD §2.5: "`version` is an integer that increments by exactly 1 on
    every mutation, including mutations the server performs itself as cascade
    side effects — an advance of the cycle, a committee decision, an accepted
    ranking submission, a finalize, a release all move the owning resource's
    `version` and `updated_at` together."
    PRD §3.4: "Every accepted submission increments the application's
    `version` by 1, which is precisely what invalidates any stale
    `expected_application_version` a client may still be holding."

    Design: Corner/cross_cutting_layers/application_version_increments_on_each_mutation
    """
    ctx = setup_draft_application()
    application = ctx["application"]
    student = ctx["student"]
    college = create_college()
    v_create = application["version"]

    submitted = submit_application(application["id"], student["id"])
    assert submitted["version"] == v_create + 1, (
        "submit moves the version by exactly 1"
    )

    advance_cycle_to_phase(ctx["cycle"]["id"], "REVIEW")
    reviewed = expect_success(
        api.review_application(
            application["id"], review_payload("FINALIST"), _ADMIN
        ),
        200,
    )
    assert reviewed["version"] == submitted["version"] + 1, (
        "the committee decision moves the version by exactly 1"
    )

    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    ranked = submit_rankings(
        application["id"], student["id"],
        [ranking_entry(college["id"], 1)], reviewed["version"],
    )
    assert ranked["version"] == reviewed["version"] + 1, (
        "the accepted ranking submission moves the version by exactly 1 — and "
        "the call accepting expected_application_version == the post-review "
        "version proves OCC reads the same counter"
    )

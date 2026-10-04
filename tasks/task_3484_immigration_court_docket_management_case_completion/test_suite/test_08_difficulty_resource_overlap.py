"""Difficulty probes: resource temporal overlap geometry.

The judge's calendar uses half-open intervals — [start, end) — so exact
adjacency is conflict-free. The interpreter selector instead reserves a
strict 15-minute buffer on both sides of every existing hearing, so a gap of
exactly 15 minutes passes while anything tighter empties the pool.
"""

from test_helpers import (
    ApiErrorId,
    case_version,
    create_interpreter,
    list_case_hearings,
    make_hearing_payload,
    same_instant,
    schedule_hearing,
    setup_docketed_case,
    validate_error,
)

SPA_CASE = {"primary_language_code": "spa", "interpreter_required": True}


def test_judge_schedule_allows_exact_adjacency(api, admin_headers):
    """PRD §3.3: "Separately, the judge's calendar must stay free of overlap: the new hearing's half-open interval — `scheduled_start` inclusive through `scheduled_end` exclusive — may not intersect the corresponding interval of any other `SCHEDULED` hearing of the same judge. Adjacency is allowed, so a hearing that ends exactly when another begins is not a conflict; a genuine overlap is rejected with `ERR_JUDGE_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/judge_overlap_half_open_allows_exact_adjacency
    """
    ctx = setup_docketed_case()
    second = setup_docketed_case(court=ctx["court"], judge=ctx["judge"],
                                 initial_clock=False)
    first_hearing = schedule_hearing(
        ctx["case"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z"
    )
    # The first hearing occupies the half-open interval [10:00, 10:30).
    assert same_instant(first_hearing["scheduled_end"], "2026-09-03T10:30:00Z")
    # A second hearing beginning exactly when the first ends is accepted.
    second_hearing = schedule_hearing(
        second["case"], "MASTER_CALENDAR", "2026-09-03T10:30:00Z"
    )
    assert second_hearing["status"] == "SCHEDULED"
    assert same_instant(second_hearing["scheduled_end"], "2026-09-03T11:00:00Z")


def test_judge_schedule_rejects_partial_overlap(api, admin_headers):
    """PRD §3.3: "Adjacency is allowed, so a hearing that ends exactly when another begins is not a conflict; a genuine overlap is rejected with `ERR_JUDGE_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/judge_overlap_half_open_allows_exact_adjacency
    """
    ctx = setup_docketed_case()
    third = setup_docketed_case(court=ctx["court"], judge=ctx["judge"],
                                initial_clock=False)
    # [10:00, 10:30) stands on the judge's calendar.
    schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z")
    # [10:15, 10:45) genuinely intersects it.
    payload = make_hearing_payload(
        third["case"]["id"], "MASTER_CALENDAR", "2026-09-03T10:15:00Z",
        case_version(third["case"]["id"]),
    )
    resp = api.create_hearing(payload, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_JUDGE_SCHEDULE_CONFLICT)
    assert list_case_hearings(third["case"]["id"]) == []


def test_interpreter_assignment_allows_exactly_fifteen_minute_gap(api, admin_headers):
    """PRD §3.3: "In plain terms, a 15-minute buffer is reserved on both sides of every existing hearing, and because both comparisons are strict, a gap of exactly 15 minutes on either side passes."
    PRD §3.3: "Among the candidates the system selects the interpreter with the fewest `SCHEDULED` hearings on that date, breaking ties by earliest `created_at`; the interpreter's `id` and any random property play no role in selection."

    Design: Difficulty/resource_temporal_overlap/interpreter_buffer_blocks_gap_under_fifteen_minutes
    """
    ctx = setup_docketed_case(**SPA_CASE)
    interpreter = create_interpreter(
        ctx["court"]["id"], language_codes=["spa"], daily_hearing_cap=4
    )
    first_hearing = schedule_hearing(
        ctx["case"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z"
    )
    assert first_hearing["interpreter_id"] == interpreter["id"]
    second = setup_docketed_case(court=ctx["court"], judge=ctx["judge"],
                                 initial_clock=False, **SPA_CASE)
    # 10:45 leaves exactly a 15-minute gap after the 10:30 end of the first
    # hearing; the strict-inequality buffer rule lets it pass.
    second_hearing = schedule_hearing(
        second["case"], "MASTER_CALENDAR", "2026-09-03T10:45:00Z"
    )
    assert second_hearing["interpreter_id"] == interpreter["id"]


def test_interpreter_assignment_rejects_gap_inside_buffer(api, admin_headers):
    """PRD §3.3: "the candidate is disqualified only if an existing hearing both ends strictly after a point 15 minutes before the new hearing's start and begins strictly before a point 15 minutes after the new hearing's end."
    PRD §3.3: "If the candidate pool is empty, creation fails with `ERR_NO_INTERPRETER_AVAILABLE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/interpreter_buffer_blocks_gap_under_fifteen_minutes
    """
    ctx = setup_docketed_case(**SPA_CASE)
    create_interpreter(ctx["court"]["id"], language_codes=["spa"], daily_hearing_cap=4)
    schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z")
    second = setup_docketed_case(court=ctx["court"], judge=ctx["judge"],
                                 initial_clock=False, **SPA_CASE)
    schedule_hearing(second["case"], "MASTER_CALENDAR", "2026-09-03T10:45:00Z")
    third = setup_docketed_case(court=ctx["court"], judge=ctx["judge"],
                                initial_clock=False, **SPA_CASE)
    # The 11:15 start is exactly adjacent to the 10:45 hearing's 11:15 end, so
    # the judge's half-open calendar is free; but the interpreter's strict
    # buffer disqualifies the candidate: the existing hearing ends at 11:15,
    # strictly after 11:00 (15 minutes before the new start), and begins at
    # 10:45, strictly before 12:00 (15 minutes after the new end).  The
    # single-member pool is empty.
    payload = make_hearing_payload(
        third["case"]["id"], "MASTER_CALENDAR", "2026-09-03T11:15:00Z",
        case_version(third["case"]["id"]),
    )
    resp = api.create_hearing(payload, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_NO_INTERPRETER_AVAILABLE)
    assert list_case_hearings(third["case"]["id"]) == []

"""Cross-cutting probes: optimistic concurrency on the case version and the
creation-time freezing of derived hearing durations.

The three OCC-guarded writes (hearing scheduling, decision issuance, backlog
reassignment) reject a stale expected_case_version with 412 after every
business rule has passed; the case version steps by exactly one per mutation;
and a legal-orientation coverage change re-derives durations only for
hearings created afterwards.
"""

from test_helpers import (
    ApiErrorId,
    advance_case_to_merits,
    assign_case_to_judge,
    case_version,
    complete_hearing,
    create_case,
    create_court,
    create_judge,
    create_orientation_program,
    get_success_data,
    list_case_decisions,
    list_case_hearings,
    make_decision_payload,
    make_hearing_payload,
    make_judge_headers,
    make_reassignment_payload,
    read_case,
    read_hearing,
    same_instant,
    schedule_hearing,
    set_clock,
    set_program_coverage,
    setup_backlog_critical_source,
    setup_docketed_case,
    validate_error,
    MASTER_HEARING_START_ISO,
    MERITS_HEARING_CLOCK_ISO,
    MERITS_HEARING_START_ISO,
)


def test_stale_case_version_on_hearing_create_returns_412(api, admin_headers):
    """PRD §2.7: "Exactly three write operations are guarded by optimistic concurrency control on the case's `version`: scheduling a hearing, issuing a decision, and executing a backlog-driven case reassignment. Each of these requests must carry `expected_case_version`, a non-optional body field holding the `version` of the target `Case` as the client last observed it. If the case's current `version` no longer equals `expected_case_version` — because any other write has advanced the case since the client read it, whether a scheduling write that legitimately occupied the case's single `SCHEDULED` slot, a decision that moved the case to `DECIDED`, or a granted venue motion — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is written; the client must re-read the case before retrying. The check runs at tier 11 of §2.6: it never masks an earlier business-rule failure, and a request rejected at an earlier tier never reaches it."

    Design: Corner/cross_cutting_layers/stale_case_version_on_hearing_create_returns_412
    """
    ctx = setup_docketed_case()
    stale_version = ctx["case"]["version"]  # 2, observed right after docketing
    # Hearing creation (v3) and the master completion (v4) advance the case.
    m = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    case_id = ctx["case"]["id"]
    assert case_version(case_id) == stale_version + 2

    # An otherwise-valid merits hearing replaying the stale version: every
    # business rule passes (case MERITS, type matches, future start, no live
    # SCHEDULED hearing, no interpreter required), so tier 11 alone rejects.
    resp = api.create_hearing(
        make_hearing_payload(
            case_id, "INDIVIDUAL_MERITS", "2026-09-08T10:00:00Z", stale_version
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

    hearings = list_case_hearings(case_id)
    assert len(hearings) == 1, "the stale write persisted nothing"
    assert hearings[0]["id"] == m["master_hearing"]["id"]
    assert hearings[0]["status"] == "COMPLETED"


def test_stale_case_version_on_decision_create_returns_412(api):
    """PRD §2.7: "Exactly three write operations are guarded by optimistic concurrency control on the case's `version`: scheduling a hearing, issuing a decision, and executing a backlog-driven case reassignment. Each of these requests must carry `expected_case_version`, a non-optional body field holding the `version` of the target `Case` as the client last observed it. If the case's current `version` no longer equals `expected_case_version` — because any other write has advanced the case since the client read it, whether a scheduling write that legitimately occupied the case's single `SCHEDULED` slot, a decision that moved the case to `DECIDED`, or a granted venue motion — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is written; the client must re-read the case before retrying. The check runs at tier 11 of §2.6: it never masks an earlier business-rule failure, and a request rejected at an earlier tier never reaches it."

    Design: Corner/cross_cutting_layers/stale_case_version_on_decision_create_returns_412
    """
    ctx = setup_docketed_case()
    stale_version = ctx["case"]["version"]  # 2
    judge_id = ctx["judge"]["id"]
    m = advance_case_to_merits(ctx["case"], judge_id=judge_id)
    merits = schedule_hearing(m["case"], "INDIVIDUAL_MERITS", MERITS_HEARING_START_ISO)
    set_clock(MERITS_HEARING_CLOCK_ISO)
    complete_hearing(merits, judge_id=judge_id)
    case_id = ctx["case"]["id"]

    # The case is MERITS with a COMPLETED merits hearing and the caller is
    # the assigned judge — only the replayed stale version can reject this.
    resp = api.create_decision(
        make_decision_payload(case_id, "REMOVAL", stale_version),
        headers=make_judge_headers(judge_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

    assert list_case_decisions(case_id) == [], "the stale write persisted nothing"
    assert read_case(case_id)["status"] == "MERITS"


def test_stale_case_version_on_reassignment_returns_412(api, admin_headers):
    """PRD §2.7: "Exactly three write operations are guarded by optimistic concurrency control on the case's `version`: scheduling a hearing, issuing a decision, and executing a backlog-driven case reassignment. Each of these requests must carry `expected_case_version`, a non-optional body field holding the `version` of the target `Case` as the client last observed it. If the case's current `version` no longer equals `expected_case_version` — because any other write has advanced the case since the client read it, whether a scheduling write that legitimately occupied the case's single `SCHEDULED` slot, a decision that moved the case to `DECIDED`, or a granted venue motion — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is written; the client must re-read the case before retrying. The check runs at tier 11 of §2.6: it never masks an earlier business-rule failure, and a request rejected at an earlier tier never reaches it."

    Design: Corner/cross_cutting_layers/stale_case_version_on_reassignment_returns_412
    """
    # Critical source (goal 4, one pending case) plus an eligible destination
    # (goal 100, empty): every business tier passes, so the deliberately
    # stale version — one behind the case's create version — reaches tier 11.
    ctx = setup_backlog_critical_source(source_goal=4, dest_goal=100)
    case = ctx["case"]

    resp = api.create_case_reassignment(
        make_reassignment_payload(case["id"], case["version"] - 1),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

    assert read_case(case["id"])["court_id"] == ctx["source_court"]["id"]
    records = get_success_data(
        api.list_case_reassignments(
            headers=admin_headers, params={"case_id": case["id"], "limit": 100}
        )
    )
    assert records == [], "the stale write persisted nothing"


def test_case_version_increments_on_every_mutation():
    """PRD §2.5: "`version` (integer): a system-managed integer that increments by 1 with every modification of the resource; this is the field the optimistic concurrency control of §2.7 reads."
    PRD §3.2: "On success the case's `assigned_judge_id` is set to that judge and the case's `version` increments by 1."
    PRD §3.3: "A successful creation copies the case's `assigned_judge_id` onto the hearing's `judge_id`, marks the hearing `SCHEDULED` with `auto_created` false and `supersedes_hearing_id` null, and increments the case's `version` by 1."

    Design: Corner/cross_cutting_layers/case_version_increments_on_every_mutation
    """
    court = create_court()
    judge = create_judge(court["id"])

    case = create_case(court["id"])
    assert case["version"] == 1, "the create response carries version 1"

    case = assign_case_to_judge(case["id"], judge["id"])
    assert case["version"] == 2, "docketing increments the case version by exactly 1"

    schedule_hearing(case, "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    case = read_case(case["id"])
    assert case["version"] == 3, "hearing creation bumps the parent case by exactly 1"


def test_lop_coverage_threshold_reconciles_only_new_hearings():
    """PRD §3.1: "An administrator may later adjust `coverage_pct`, `active`, or both through the program's set-coverage operation, which increments the program's `version` by 1; the change re-derives the duration factor only for hearings created afterwards, and hearings already on the calendar keep the durations they were created with."
    PRD §3.3: "A master-calendar hearing's raw length is 30 minutes, multiplied by a factor of 0.5 — halved — when at least one active legal orientation program at the case's court has a `coverage_pct` of 50 or more, and left at the full 30 otherwise."

    Design: Corner/cross_cutting_layers/lop_coverage_threshold_reconciles_only_new_hearings
    """
    court = create_court()
    judge = create_judge(court["id"])
    # Active program at coverage 49: below the inclusive >= 50 threshold.
    program = create_orientation_program(court["id"], coverage_pct=49, active=True)

    case1 = assign_case_to_judge(create_case(court["id"])["id"], judge["id"])
    first = schedule_hearing(case1, "MASTER_CALENDAR", "2026-09-03T10:00:00Z")
    assert first["duration_minutes"] == 30, "coverage 49 leaves the full 30-minute block"

    # Crossing the threshold to exactly 50 activates the 0.5 factor.
    set_program_coverage(program["id"], coverage_pct=50)

    case2 = assign_case_to_judge(create_case(court["id"])["id"], judge["id"])
    second = schedule_hearing(case2, "MASTER_CALENDAR", "2026-09-03T11:00:00Z")
    assert second["duration_minutes"] == 15, "30 * 0.5 at coverage 50 (inclusive)"
    assert same_instant(second["scheduled_end"], "2026-09-03T11:15:00Z")

    # The already-scheduled hearing keeps its stored duration: derived
    # durations are frozen at creation and never reconcile backwards.
    assert read_hearing(first["id"])["duration_minutes"] == 30

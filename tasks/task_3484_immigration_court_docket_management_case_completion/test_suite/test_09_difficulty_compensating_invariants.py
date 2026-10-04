"""Difficulty probes: compensating invariants.

A backlog reassignment moves exactly one pending case out of a critical court
and into another, conserving the global pending total. A continuance grant
writes a compensating pair — the old hearing CONTINUED plus exactly one
SCHEDULED successor — conserving the per-case count of live scheduled
hearings.
"""

from test_helpers import (
    ApiErrorId,
    assert_backlog_flag,
    assert_case_reassignment,
    assert_single_scheduled_hearing,
    decide_continuance,
    file_continuance,
    list_case_hearings,
    make_reassignment_payload,
    read_case,
    read_court,
    read_hearing,
    reassign_case,
    same_instant,
    schedule_hearing,
    scheduled_hearing_of,
    setup_backlog_critical_source,
    setup_docketed_case,
    validate_error,
)


def test_reassignment_conserves_global_pending_case_count(api, admin_headers):
    """PRD §2.9: "Reassignment between courts is volume-neutral: it rewrites venue, so the source court's `pending_case_count` falls by one and the destination court's rises by one, both courts recompute their backlog flags, and the global pending total is conserved."
    PRD §3.7: "Execution writes an immutable `CaseReassignment` record: its `from_court_id` is the source court, its `to_court_id` the selected destination, its `reason` is always `BACKLOG_REBALANCE`, and its `executed_at` is the clock. It applies the same reset as a granted venue motion — new `court_id`, null `assigned_judge_id`, every `SCHEDULED` hearing `CANCELLED`, status back to `FILED` from any of `FILED`, `CALENDAR`, or `MERITS`, `version` incremented by 1 — and both courts' `pending_case_count` and `is_backlog_critical` recompute, conserving the global pending total as §2.9 requires."

    Design: Difficulty/compensating_invariant/reassignment_conserves_global_pending_case_count
    """
    # Source goal 4 -> threshold ceil(0.25 * 4) = 1, so its single FILED case
    # makes it backlog-critical; the destination (goal 100) is empty.
    ctx = setup_backlog_critical_source(source_goal=4, dest_goal=100)
    source, dest, case = ctx["source_court"], ctx["dest_court"], ctx["case"]
    assert_backlog_flag(source, 1, True)
    assert_backlog_flag(dest, 0, False)
    version_before = case["version"]
    record = reassign_case(case, expected_case_version=version_before)
    assert_case_reassignment(record)
    assert record["from_court_id"] == source["id"]
    assert record["to_court_id"] == dest["id"]
    assert record["reason"] == "BACKLOG_REBALANCE"
    source_after = read_court(source["id"])
    dest_after = read_court(dest["id"])
    # The transfer out of the critical court is exactly compensated by the
    # arrival at the destination: 1 + 0 before, 0 + 1 after.
    assert_backlog_flag(source_after, 0, False)
    assert_backlog_flag(dest_after, 1, False)
    assert source_after["pending_case_count"] + dest_after["pending_case_count"] == 1
    assert source["pending_case_count"] + dest["pending_case_count"] == 1
    moved = read_case(case["id"])
    assert moved["court_id"] == dest["id"]
    assert moved["assigned_judge_id"] is None
    assert moved["status"] == "FILED"
    assert moved["version"] == version_before + 1


def test_reassignment_replay_with_stale_version_rejected(api, admin_headers):
    """PRD §2.7: "If the case's current `version` no longer equals `expected_case_version` — because any other write has advanced the case since the client last observed it, whether a scheduling write that legitimately occupied the case's single `SCHEDULED` slot, a decision that moved the case to `DECIDED`, or a granted venue motion — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is written; the client must re-read the case before retrying."
    PRD §2.9: "a court is backlog-critical when its `pending_case_count` reaches at least one quarter of its `annual_completion_goal`, with that quarter rounded up to a whole case before the comparison."

    Design: Difficulty/compensating_invariant/reassignment_conserves_global_pending_case_count
    """
    # Destination goal 4 -> threshold 1, so after the transfer the case's new
    # court is itself backlog-critical: a replay then passes every business
    # tier (including ERR_COURT_NOT_BACKLOG_CRITICAL) and reaches the
    # concurrency check, which alone rejects it.
    ctx = setup_backlog_critical_source(source_goal=4, dest_goal=4)
    case = ctx["case"]
    stale_version = case["version"]
    record = reassign_case(case, expected_case_version=stale_version)
    assert record["to_court_id"] == ctx["dest_court"]["id"]
    assert read_court(ctx["dest_court"]["id"])["is_backlog_critical"] is True
    resp = api.create_case_reassignment(
        make_reassignment_payload(case["id"], stale_version),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


def test_continuance_grant_conserves_single_scheduled_hearing():
    """PRD §3.3: "And a case may hold at most one `SCHEDULED` hearing at a time — a second attempt while one stands fails with `ERR_CASE_HAS_SCHEDULED_HEARING`."
    PRD §3.4: "For any `reason_code` other than `PENDING_APPLICATION`, the targeted hearing becomes `CONTINUED` and the system auto-creates its replacement: the same case, hearing type, judge, and `is_remote` flag; `auto_created` true; `supersedes_hearing_id` pointing at the continued hearing; and a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one — with the candidate slot then advanced one calendar day at a time until the judge-overlap, judge daily-minutes, detained-capacity, and interpreter-selection checks of §3.3 all pass, a deterministic forward search."

    Design: Difficulty/compensating_invariant/continuance_grant_conserves_single_scheduled_hearing
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")
    # Filed at the 2026-09-01 clock anchor, more than 24h before the start.
    request = file_continuance(ctx["case"]["id"], hearing["id"], "EVIDENCE_GATHERING")
    before = list_case_hearings(ctx["case"]["id"], status="SCHEDULED")
    assert len(before) == 1 and before[0]["id"] == hearing["id"]
    decide_continuance(request, "GRANTED", judge_id=ctx["judge"]["id"])
    # The compensating pair (CONTINUED + created) conserves the per-case
    # SCHEDULED count at exactly one, while the total hearing count grows.
    after = list_case_hearings(ctx["case"]["id"], status="SCHEDULED")
    assert len(after) == 1
    assert after[0]["id"] != hearing["id"]
    assert read_hearing(hearing["id"])["status"] == "CONTINUED"
    all_hearings = list_case_hearings(ctx["case"]["id"])
    assert len(all_hearings) == 2, "1 CONTINUED + 1 SCHEDULED"
    assert_single_scheduled_hearing(all_hearings)


def test_continuance_grant_superseding_hearing_bumped_28_days():
    """PRD §3.4: "the same case, hearing type, judge, and `is_remote` flag; `auto_created` true; `supersedes_hearing_id` pointing at the continued hearing; and a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one — with the candidate slot then advanced one calendar day at a time until the judge-overlap, judge daily-minutes, detained-capacity, and interpreter-selection checks of §3.3 all pass, a deterministic forward search."

    Design: Difficulty/compensating_invariant/continuance_grant_conserves_single_scheduled_hearing
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")
    request = file_continuance(ctx["case"]["id"], hearing["id"], "EVIDENCE_GATHERING")
    decide_continuance(request, "GRANTED", judge_id=ctx["judge"]["id"])
    successor = scheduled_hearing_of(ctx["case"]["id"])
    assert successor is not None
    # 2026-09-10T10:00Z + 28 days (non-detained bump), no advancement needed.
    assert same_instant(successor["scheduled_start"], "2026-10-08T10:00:00Z")
    assert successor["supersedes_hearing_id"] == hearing["id"]
    assert successor["auto_created"] is True
    assert successor["hearing_type"] == "MASTER_CALENDAR"
    assert successor["judge_id"] == ctx["judge"]["id"]
    assert successor["is_remote"] is False, "the replacement copies the original flag"

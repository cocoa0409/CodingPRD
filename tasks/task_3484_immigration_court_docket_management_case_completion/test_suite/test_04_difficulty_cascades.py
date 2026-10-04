"""Difficulty probes: transitive cascades.

A granted motion to reopen cascades three deep: motion ruled -> decision
rescinded -> case restored to CALENDAR -> fresh master hearing auto-created.
A recorded no-show cascades: hearing NO_SHOW -> case IN_ABSENTIA -> system
synthesizes the in absentia removal decision with derived deadlines.
"""

from test_helpers import (
    assert_decision,
    decide_motion_to_reopen,
    file_motion_to_reopen,
    list_case_decisions,
    list_case_hearings,
    read_case,
    read_decision,
    read_hearing,
    same_instant,
    setup_case_in_absentia,
    setup_in_absentia_with_defective_notice,
)


def test_reopen_grant_rescinds_decision_and_restores_calendar():
    """PRD §3.5: "A grant unwinds the removal: the decision becomes `RESCINDED`, the case returns `IN_ABSENTIA → CALENDAR`, its `version` increments by 1, and the system auto-creates a fresh `MASTER_CALENDAR` hearing 21 days out from the clock — `auto_created` true, the case's retained `assigned_judge_id` presiding, the interpreter re-selected, and the candidate slot advanced one calendar day at a time until every applicable scheduling check of §3.3 passes."
    PRD §3.5: "The assigned judge then rules, supplying a `decision` of `GRANTED` or `DENIED`; the motion must still be `FILED` (otherwise `ERR_MOTION_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`), and either ruling stamps `decided_by_judge_id` and `decided_at`."

    Design: Difficulty/transitive_cascade/reopen_grant_cascade_motion_decision_case_hearing
    """
    # No-show at clock 2026-09-05T11:00Z put the case IN_ABSENTIA with an
    # ISSUED in-absentia decision; the notice was then marked DEFECTIVE.
    ctx = setup_in_absentia_with_defective_notice()
    motion = file_motion_to_reopen(
        ctx["case"]["id"], ctx["decision"]["id"], "NOTICE_DEFECTIVE"
    )
    granted = decide_motion_to_reopen(motion, "GRANTED", judge_id=ctx["judge"]["id"])
    # Link A: the motion itself is ruled.
    assert granted["status"] == "GRANTED"
    assert granted["decided_by_judge_id"] == ctx["judge"]["id"]
    # Link B: the grant rescinds the targeted in-absentia decision.
    decision = read_decision(ctx["decision"]["id"])
    assert decision["status"] == "RESCINDED"
    # Link C: the rescission reactivates the case.
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "CALENDAR"


def test_reopen_grant_auto_creates_master_hearing_21_days_out():
    """PRD §3.5: "A grant unwinds the removal: the decision becomes `RESCINDED`, the case returns `IN_ABSENTIA → CALENDAR`, its `version` increments by 1, and the system auto-creates a fresh `MASTER_CALENDAR` hearing 21 days out from the clock — `auto_created` true, the case's retained `assigned_judge_id` presiding, the interpreter re-selected, and the candidate slot advanced one calendar day at a time until every applicable scheduling check of §3.3 passes."
    PRD §3.5: "The hearing becomes `NO_SHOW`."

    Design: Difficulty/transitive_cascade/reopen_grant_cascade_motion_decision_case_hearing
    """
    ctx = setup_in_absentia_with_defective_notice()
    motion = file_motion_to_reopen(
        ctx["case"]["id"], ctx["decision"]["id"], "NOTICE_DEFECTIVE"
    )
    decide_motion_to_reopen(motion, "GRANTED", judge_id=ctx["judge"]["id"])
    # Link D: the case's return to CALENDAR itself synthesizes the reopen
    # hearing at the ruling clock (2026-09-05T11:00Z) + 21 days.
    scheduled = list_case_hearings(ctx["case"]["id"], status="SCHEDULED")
    assert len(scheduled) == 1, "exactly one fresh hearing is auto-created"
    reopen_hearing = scheduled[0]
    assert reopen_hearing["hearing_type"] == "MASTER_CALENDAR"
    assert reopen_hearing["auto_created"] is True
    assert reopen_hearing["supersedes_hearing_id"] is None
    assert reopen_hearing["judge_id"] == ctx["judge"]["id"]
    assert same_instant(reopen_hearing["scheduled_start"], "2026-09-26T11:00:00Z")
    # The cascade does not rewrite history: the no-show hearing keeps its
    # terminal posture.
    old = read_hearing(ctx["hearing"]["id"])
    assert old["status"] == "NO_SHOW"


def test_no_show_flips_case_to_in_absentia_retaining_judge():
    """PRD §3.5: "A successful no-show is the widest cascade in the system. The hearing becomes `NO_SHOW`. The case — whether it stood at `CALENDAR` or at `MERITS` — moves to `IN_ABSENTIA`, retaining its `assigned_judge_id`, and its `version` increments by 1."

    Design: Difficulty/transitive_cascade/no_show_cascade_hearing_case_decision
    """
    # Master hearing 2026-09-05T10:00Z with notice personally served
    # 2026-08-20; the no-show is recorded at clock 2026-09-05T11:00Z.
    ctx = setup_case_in_absentia(service_method="PERSONAL_SERVICE")
    # Link A: the ruling mutates the hearing.
    assert ctx["hearing"]["status"] == "NO_SHOW"
    # Link B: the hearing mutation flips the case, judge retained.
    case = ctx["case"]
    assert case["status"] == "IN_ABSENTIA"
    assert case["assigned_judge_id"] == ctx["judge"]["id"]


def test_no_show_synthesizes_in_absentia_decision_with_deadlines():
    """PRD §3.5: "And the system itself enters the removal order: a `Decision` whose `outcome` is `IN_ABSENTIA_REMOVAL`, whose `status` is `ISSUED`, whose `judge_id` is the no-show hearing's judge, whose `source_hearing_id` names the hearing that produced it, whose `issued_at` is the clock, whose `appeal_deadline` falls exactly 30 days later, and whose `reopen_deadline` falls exactly 180 days later."

    Design: Difficulty/transitive_cascade/no_show_cascade_hearing_case_decision
    """
    ctx = setup_case_in_absentia(service_method="PERSONAL_SERVICE")
    decisions = list_case_decisions(ctx["case"]["id"])
    assert len(decisions) == 1, "exactly one decision is synthesized by the no-show"
    decision = decisions[0]
    assert_decision(decision)
    assert decision["outcome"] == "IN_ABSENTIA_REMOVAL"
    assert decision["status"] == "ISSUED"
    assert decision["source_hearing_id"] == ctx["hearing"]["id"]
    assert decision["judge_id"] == ctx["judge"]["id"]
    # Deadlines derive from the ruling clock 2026-09-05T11:00Z.
    assert same_instant(decision["issued_at"], "2026-09-05T11:00:00Z")
    assert same_instant(decision["appeal_deadline"], "2026-10-05T11:00:00Z")
    assert same_instant(decision["reopen_deadline"], "2027-03-04T11:00:00Z")

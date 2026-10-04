"""Difficulty probes: non-linear state machines.

The Case machine is cyclic — MERITS -> DECIDED -> APPEALED -> MERITS via
remand — and the loop can be traversed repeatedly. The Hearing machine forks
from SCHEDULED into COMPLETED (advancing a CALENDAR case to MERITS, creating
nothing) or CONTINUED (holding the case in place, auto-creating a superseding
hearing).
"""

from test_helpers import (
    complete_hearing,
    decide_appeal,
    decide_continuance,
    file_appeal,
    file_continuance,
    issue_decision,
    list_case_decisions,
    list_case_hearings,
    read_case,
    read_decision,
    read_hearing,
    same_instant,
    schedule_hearing,
    scheduled_hearing_of,
    set_clock,
    setup_docketed_case,
    setup_remanded_case,
    validate_paginated,
)


def test_first_remand_returns_case_to_merits_with_auto_hearing():
    """PRD §3.6: "`REMANDED` instead returns the case for further proceedings: it requires `remand_instructions` to accompany the ruling (omitting them is `ERR_REMAND_INSTRUCTIONS_REQUIRED`, HTTP 422), records those instructions on the appeal, moves the decision to `REMANDED`, returns the case `APPEALED → MERITS`, increments its `version` by 1, and auto-creates the remand hearing — an `INDIVIDUAL_MERITS` hearing 42 days out from the clock, `auto_created` true, the case's assigned judge presiding, the interpreter re-selected, and the candidate slot advanced a day at a time until the scheduling checks of §3.3 pass."

    Design: Difficulty/non_linear_state_machine/case_appeal_remand_cycle_traversed_twice
    """
    # Fixture lands: decision issued and appealed at clock 2026-09-04T12:00Z,
    # then ruled REMANDED at the same clock.
    ctx = setup_remanded_case()
    case = ctx["case"]
    assert case["status"] == "MERITS", "remand returns the case to the merits phase"
    assert ctx["decision"]["status"] == "REMANDED"
    remand_hearing = ctx["remand_hearing"]
    assert remand_hearing is not None
    assert remand_hearing["hearing_type"] == "INDIVIDUAL_MERITS"
    assert remand_hearing["auto_created"] is True
    assert remand_hearing["judge_id"] == ctx["judge"]["id"]
    # 2026-09-04T12:00Z + 42 days, no advancement needed on an empty calendar.
    assert same_instant(remand_hearing["scheduled_start"], "2026-10-16T12:00:00Z")
    hearings = list_case_hearings(case["id"])
    # completed master + completed merits + the auto-created remand hearing.
    assert len(hearings) == 3


def test_second_remand_completes_cycle_twice(api, admin_headers):
    """PRD §3.6: "Remand, in other words, reopens the merits phase rather than ending the case, and a remanded case is decided, appealed, and checkpointed again on its own terms."
    PRD §3.6: "moves the decision to `REMANDED`, returns the case `APPEALED → MERITS`, increments its `version` by 1, and auto-creates the remand hearing — an `INDIVIDUAL_MERITS` hearing 42 days out from the clock, `auto_created` true, the case's assigned judge presiding, the interpreter re-selected, and the candidate slot advanced a day at a time until the scheduling checks of §3.3 pass."

    Design: Difficulty/non_linear_state_machine/case_appeal_remand_cycle_traversed_twice
    """
    ctx = setup_remanded_case()
    judge_id = ctx["judge"]["id"]
    case_id = ctx["case"]["id"]
    # Complete the first auto-created remand hearing at its scheduled start.
    first_remand = ctx["remand_hearing"]
    assert same_instant(first_remand["scheduled_start"], "2026-10-16T12:00:00Z")
    set_clock("2026-10-16T12:00:00Z")
    complete_hearing(first_remand, judge_id=judge_id)
    case = read_case(case_id)
    assert case["status"] == "MERITS"
    # Second pass through DECIDED -> APPEALED.
    decision2 = issue_decision(case, "GRANT_RELIEF", judge_id=judge_id)
    appeal2 = file_appeal(decision2["id"])
    # Trigger: the board remands a second time, at clock 2026-10-16T12:00Z.
    decide_appeal(
        appeal2["id"], "REMANDED",
        remand_instructions="Reopen the record for new evidence",
    )
    case = read_case(case_id)
    assert case["status"] == "MERITS", (
        "the MERITS -> DECIDED -> APPEALED -> MERITS loop has now closed twice"
    )
    assert read_decision(ctx["decision"]["id"])["status"] == "REMANDED"
    assert read_decision(decision2["id"])["status"] == "REMANDED"
    decisions = list_case_decisions(case_id)
    assert len(decisions) == 2, "exactly two decisions exist after two merits phases"
    appeals, _meta = validate_paginated(
        api.list_appeals(headers=admin_headers,
                         params={"case_id": case_id, "limit": 100})
    )
    assert len(appeals) == 2, "exactly two appeals exist after two remands"
    second_remand = scheduled_hearing_of(case_id)
    assert second_remand is not None
    assert second_remand["hearing_type"] == "INDIVIDUAL_MERITS"
    assert second_remand["auto_created"] is True
    assert second_remand["supersedes_hearing_id"] is None
    # clock 2026-10-16T12:00Z + 42 days.
    assert same_instant(second_remand["scheduled_start"], "2026-11-27T12:00:00Z")


def test_master_completion_advances_case_without_replacement():
    """PRD §3.4: "Completion moves the hearing `SCHEDULED → COMPLETED`, and when the completed hearing was a master-calendar hearing of a `CALENDAR` case, the case itself advances `CALENDAR → MERITS` with its `version` incremented by 1. That master-calendar completion is the only path into the merits phase."

    Design: Difficulty/non_linear_state_machine/hearing_branching_divergent_side_effects
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z")
    set_clock("2026-09-03T10:30:00Z")
    completed = complete_hearing(hearing, judge_id=ctx["judge"]["id"])
    assert completed["status"] == "COMPLETED"
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "MERITS", "the COMPLETED branch advances the case"
    hearings = list_case_hearings(ctx["case"]["id"])
    assert len(hearings) == 1, "the COMPLETED branch creates no replacement hearing"


def test_continuance_grant_holds_case_and_supersedes_hearing():
    """PRD §3.4: "For any `reason_code` other than `PENDING_APPLICATION`, the targeted hearing becomes `CONTINUED` and the system auto-creates its replacement: the same case, hearing type, judge, and `is_remote` flag; `auto_created` true; `supersedes_hearing_id` pointing at the continued hearing; and a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one — with the candidate slot then advanced one calendar day at a time until the judge-overlap, judge daily-minutes, detained-capacity, and interpreter-selection checks of §3.3 all pass, a deterministic forward search."
    PRD §3.4: "either ruling stamps `decided_by_judge_id` with the acting judge and `decided_at` with the clock."

    Design: Difficulty/non_linear_state_machine/hearing_branching_divergent_side_effects
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-03T11:00:00Z")
    # Filed at the 2026-09-01 clock anchor, more than 24h before the start.
    request = file_continuance(ctx["case"]["id"], hearing["id"], "EVIDENCE_GATHERING")
    set_clock("2026-09-03T10:30:00Z")
    granted = decide_continuance(request, "GRANTED", judge_id=ctx["judge"]["id"])
    assert granted["status"] == "GRANTED"
    assert granted["decided_by_judge_id"] == ctx["judge"]["id"]
    old = read_hearing(hearing["id"])
    assert old["status"] == "CONTINUED"
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "CALENDAR", "the CONTINUED branch does not advance the case"
    hearings = list_case_hearings(ctx["case"]["id"])
    assert len(hearings) == 2, "the continued hearing plus its auto-created replacement"
    successor = scheduled_hearing_of(ctx["case"]["id"])
    assert successor is not None
    assert successor["id"] != hearing["id"]
    # 2026-09-03T11:00Z + 28 days (non-detained bump).
    assert same_instant(successor["scheduled_start"], "2026-10-01T11:00:00Z")
    assert successor["supersedes_hearing_id"] == hearing["id"]
    assert successor["auto_created"] is True
    assert successor["status"] == "SCHEDULED"

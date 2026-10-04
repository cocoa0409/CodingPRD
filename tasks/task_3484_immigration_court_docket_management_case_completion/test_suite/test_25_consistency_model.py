"""Consistency probe: immediate visibility of a mutation in its own response
and in the very next reads.

The hearing-completion response itself carries COMPLETED, and the immediately
following GETs show the hearing COMPLETED and the owning case advanced to
MERITS — no settlement lag, no reconciliation window.
"""

from test_helpers import (
    make_judge_headers,
    schedule_hearing,
    set_clock,
    setup_docketed_case,
    validate_success,
    MASTER_HEARING_CLOCK_ISO,
    MASTER_HEARING_START_ISO,
)


def test_immediate_consistency_visible_in_same_and_next_read(api, admin_headers):
    """PRD §2.4: "Consistency is immediate throughout: every mutation is visible in the response of the request that performed it and in every subsequent read. The system has no eventual-consistency window."
    PRD §3.4: "Completion moves the hearing `SCHEDULED → COMPLETED`, and when the completed hearing was a master-calendar hearing of a `CALENDAR` case, the case itself advances `CALENDAR → MERITS` with its `version` incremented by 1."
    PRD §3.2: "On success the case's `assigned_judge_id` is set to that judge and the case's `version` increments by 1."
    PRD §3.3: "A successful creation copies the case's `assigned_judge_id` onto the hearing's `judge_id`, marks the hearing `SCHEDULED` with `auto_created` false and `supersedes_hearing_id` null, and increments the case's `version` by 1."

    Design: Corner/consistency_model/immediate_consistency_visible_in_same_and_next_read
    """
    ctx = setup_docketed_case()
    case, judge = ctx["case"], ctx["judge"]
    hearing = schedule_hearing(case, "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    set_clock(MASTER_HEARING_CLOCK_ISO)

    # The mutation is visible in the response of the request that performed it.
    resp = api.complete_hearing(
        hearing["id"], headers=make_judge_headers(judge["id"])
    )
    completed = validate_success(resp)
    assert completed["status"] == "COMPLETED", (
        "the completion response itself carries the new hearing state"
    )

    # ... and in every subsequent read, with no reconciliation window.
    reread_hearing = validate_success(
        api.get_hearing(hearing["id"], headers=admin_headers)
    )
    assert reread_hearing["status"] == "COMPLETED"
    reread_case = validate_success(api.get_case(case["id"], headers=admin_headers))
    assert reread_case["status"] == "MERITS", (
        "the master completion advanced the case on the very next read"
    )
    # create(1) + assign-judge(2) + hearing create(3) + master completion(4).
    assert reread_case["version"] == 4

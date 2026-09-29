"""Two multi-hop cascades: a safety escalation that reaches the installer's network
status, and a licence rejection that reaches a confirmed install window.

Each cascade is triggered by a single call that names only its primary target; every
later hop is observable only through the reverse-discovery listings and reads.
"""

from test_helpers import (
    NETWORK_MANAGER,
    PROJECT_COORDINATOR,
    PROJECT_COORDINATOR_USER_ID,
    AssignmentStatus,
    CredentialStatus,
    DefectSeverity,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    PermitStatus,
    PunchItemStatus,
    QualityResult,
    ReleaseReason,
    ScorecardEventSource,
    ScorecardEventType,
    assert_committed_minutes,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_scorecard_dimensions,
    factories as f,
    fixtures as fx,
    get_success_data,
)

COMPLETION_INSTANT = "2026-08-25T15:30:00.000Z"
QUOTED = 196673
DEPOSIT = 59002


def _escalated_safety_defect(api):
    """Install one project, record a safety defect against it and escalate that defect
    as the project coordinator."""
    ctx = fx.installed_project(api)
    ctx["project"] = get_success_data(
        api.record_quality_inspection(
            ctx["project"]["id"],
            f.quality_inspection_payload(
                QualityResult.PASS_WITH_PUNCH, 72,
                [f.defect(DefectSeverity.SAFETY,
                          "Exposed tack strip at the hall doorway",
                          due_at="2026-08-28T00:00:00.000Z")]),
            PROJECT_COORDINATOR)
    )
    item = fx.list_punch_items(api, ctx["project"]["id"])[0]
    ctx["punch_item"] = get_success_data(
        api.escalate_punch_item(
            item["id"],
            f.escalation_payload("Safety defect needs a service manager on site"),
            PROJECT_COORDINATOR)
    )
    ctx["project"] = fx.read_project(api, ctx["project"]["id"])
    ctx["installer"] = fx.read_installer(api, ctx["installer"]["id"])
    return ctx


def test_safety_escalation_marks_the_item_and_flags_the_project(api):
    """Hops one and two: the punch item records the escalation and the project counts
    it and demands a service-manager review.

    PRD 3.7: "The item's `status` becomes `ESCALATED`, `escalated_at` is stamped from
    the clock, the reason is recorded, and `escalated_to_user_id` is set to the acting
    `X-User-ID` — an opaque operator handle that is never compared to any entity id."

    Design: Difficulty/transitive_cascade/safety_punch_escalation_cascades_five_hops_to_installer_probation
    """
    ctx = _escalated_safety_defect(api)
    item = ctx["punch_item"]

    assert item["status"] == PunchItemStatus.ESCALATED
    assert item["severity"] == DefectSeverity.SAFETY
    assert_instant(item["escalated_at"], COMPLETION_INSTANT, "escalated_at")
    assert item["escalation_reason"] == "Safety defect needs a service manager on site"
    assert item["escalated_to_user_id"] == PROJECT_COORDINATOR_USER_ID

    project = ctx["project"]
    assert project["escalated_punch_count"] == 1
    assert project["service_manager_review_required"] is True
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.PUNCH_OPEN,
                             financial=FinancialStatus.BALANCE_DUE,
                             permit=PermitStatus.NOT_REQUIRED)
    assert_money(project["final_labor_cents"], QUOTED, "final_labor_cents")
    assert_money(project["total_due_cents"], QUOTED, "total_due_cents")
    assert_money(project["balance_due_cents"], QUOTED - DEPOSIT,
                 "balance_due_cents")


def test_safety_escalation_reaches_the_installers_network_status(api):
    """Hops three, four and five: a second PUNCH_SAFETY event is appended, the score is
    recomputed from it, and the firm drops to probation.

    PRD 3.7: "And caused by that, when the recomputed `composite_score` is 78.00 or
    below and `rolling_event_count` is 3 or more, the firm moves `ACTIVE → PROBATION`
    with `probation_started_at` stamped from the clock."

    Design: Difficulty/transitive_cascade/safety_punch_escalation_cascades_five_hops_to_installer_probation
    """
    ctx = _escalated_safety_defect(api)
    installer = ctx["installer"]

    safety_events = fx.list_installer_events(
        api, installer["id"], {"event_type": ScorecardEventType.PUNCH_SAFETY})
    # One event came from the quality inspection that opened the item, the second from
    # the escalation itself.
    assert len(safety_events) == 2, (
        "the quality inspection and the escalation each append one PUNCH_SAFETY event"
    )
    escalation_event = safety_events[-1]
    assert escalation_event["source"] == ScorecardEventSource.SYSTEM
    assert escalation_event["project_id"] == ctx["project"]["id"]
    assert_instant(escalation_event["occurred_at"], COMPLETION_INSTANT,
                   "occurred_at")

    # ON_TIME_COMPLETION plus two PUNCH_SAFETY events: quality 85 + 2 - 15 - 15,
    # timeliness 85 + 6 - 3 - 3, satisfaction 85 + 1 - 8 - 8, composite 25.65 + 25.50
    # + 17.50.
    assert_scorecard_dimensions(installer, quality=57.00, timeliness=85.00,
                                satisfaction=70.00, composite=68.65)
    assert installer["rolling_event_count"] == 3
    assert installer["removal_eligible"] is True
    assert installer["status"] == InstallerStatus.PROBATION
    assert_instant(installer["probation_started_at"], COMPLETION_INSTANT,
                   "probation_started_at")


def _rejected_sole_credential(api):
    """Confirm an install window for a firm holding exactly one verified licence, then
    reject that licence."""
    ctx = fx.confirmed_project(api)
    ctx["credential"] = get_success_data(
        api.verify_credential(
            ctx["credential"]["id"],
            f.reject_payload("Licence number is not on the state register"),
            NETWORK_MANAGER)
    )
    ctx["installer"] = fx.read_installer(api, ctx["installer"]["id"])
    ctx["assignment"] = fx.read_assignment(api, ctx["assignment"]["id"])
    ctx["project"] = fx.read_project(api, ctx["project"]["id"])
    return ctx


def test_rejecting_the_last_verified_licence_suspends_the_firm(api):
    """Hops one and two: the licence lands at REJECTED with its reason recorded, and
    the firm's recomputed licence count drops it out of the assignable network.

    PRD 3.2: "When a rejection — or the clock-driven expiry sweep of §2.4 — leaves a
    firm with a recomputed `verified_credential_count` of zero, the firm moves
    `ACTIVE → SUSPENDED` or `PROBATION → SUSPENDED`."

    Design: Difficulty/transitive_cascade/credential_rejection_cascades_four_hops_to_released_assignment
    """
    ctx = _rejected_sole_credential(api)

    credential = ctx["credential"]
    assert credential["verification_status"] == CredentialStatus.REJECTED
    assert credential["rejection_reason"] == (
        "Licence number is not on the state register"
    )

    installer = ctx["installer"]
    assert installer["verified_credential_count"] == 0
    assert installer["status"] == InstallerStatus.SUSPENDED


def test_the_suspension_releases_the_confirmed_window_and_frees_capacity(api):
    """Hops three and four: the confirmed assignment is released with the suspension
    reason, the firm's committed minutes fall back to zero and the project becomes
    reschedulable.

    PRD 3.2: "hop three transitions every assignment of that firm whose `status` is
    `HELD` or `CONFIRMED` to `RELEASED` with `release_reason` recorded as
    `INSTALLER_SUSPENDED`, and hop four — caused by hop three — reduces the firm's
    `committed_minutes` by each released assignment's `duration_minutes` and reverts
    each affected project `SCHEDULED → MEASURED`."

    Design: Difficulty/transitive_cascade/credential_rejection_cascades_four_hops_to_released_assignment
    """
    ctx = _rejected_sole_credential(api)

    assignment = ctx["assignment"]
    assert assignment["status"] == AssignmentStatus.RELEASED
    assert assignment["release_reason"] == ReleaseReason.INSTALLER_SUSPENDED
    # The released row keeps its own length; only the firm's running total moves.
    assert assignment["duration_minutes"] == 480

    assert_committed_minutes(ctx["installer"], 0)

    project = ctx["project"]
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD,
                              permit=PermitStatus.NOT_REQUIRED)
    assert_money(project["deposit_held_cents"], DEPOSIT, "deposit_held_cents")

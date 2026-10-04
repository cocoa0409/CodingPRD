"""Contractor visit-window geometry, credential gates, and the posture-gated
event lock (PRD §2.8/§2.10/§3.6/§3.7)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_contractor,
    create_work_order,
    drive_work_order_to,
    get_event,
    get_project,
    get_work_order,
    schedule_work_order,
    schedule_work_order_payload,
    setup_event_with_team_leader,
    setup_project_with_work_order,
    setup_selected_project,
    trade_scope_item_payload,
    validate_error,
    validate_ok,
    STAFF,
)


def _setup_two_item_project(contractor_overrides=None):
    """One selected project with two ELECTRICAL items (50000 each) and one
    contractor; returns (ctx, contractor, items-by-description)."""
    ctx = setup_selected_project(
        budget_cents=2_000_000,
        scope_items=[
            trade_scope_item_payload(description="e1"),
            trade_scope_item_payload(description="e2"),
        ],
    )
    contractor = create_contractor(**(contractor_overrides or {}))
    items = {i["description"]: i for i in ctx["scope_items"]}
    return ctx, contractor, items


def _approved_order(project_id, contractor_id, item_id, quote_cents=50_000):
    wo = create_work_order(project_id, contractor_id, [item_id])
    return drive_work_order_to(
        wo["id"], contractor_id, "APPROVED", quote_cents=quote_cents
    )


def test_schedule_with_expired_insurance_and_overlap_safety_beats_temporal():
    """PRD §2.10: "8. Contractor credential qualification
    (`ERR_CONTRACTOR_NOT_QUALIFIED`)."
    PRD §2.10: "9. Temporal rules (`ERR_EVENT_DATE_PAST`,
    `ERR_INVALID_DATE_RANGE`, `ERR_TRADE_WINDOW_CONFLICT`,
    `ERR_VOLUNTEER_DOUBLE_BOOKED`, `ERR_CONTRACTOR_DAY_CAPACITY`,
    `ERR_WARRANTY_EXPIRED`)."
    PRD §3.7: "The contractor must still be credentialed: `ACTIVE`, with
    `license_expires_on` and `insurance_expires_on` each on or after the visit
    start date, otherwise `ERR_CONTRACTOR_NOT_QUALIFIED`."

    Insurance expired 2026-10-10 < visit start 2026-10-11 AND the window
    overlaps an existing booking: the safety check at priority 8 beats the
    temporal conflict at priority 9.

    Design: Difficulty/priority_pair_validation_conflict/schedule_with_expired_insurance_and_overlap_safety_beats_temporal
    """
    ctx, contractor, items = _setup_two_item_project(
        {
            "legal_name": "Risky Electric",
            "license_expires_on": "2027-01-01",
            "insurance_expires_on": "2026-10-10",
        }
    )
    project_id = ctx["project"]["id"]
    wo_a = _approved_order(project_id, contractor["id"], items["e1"]["id"])
    schedule_work_order(
        wo_a["id"], "2026-10-10T08:00:00Z", "2026-10-12T12:00:00Z"
    )
    wo_b = _approved_order(project_id, contractor["id"], items["e2"]["id"])
    resp = api_client.schedule_trade_work_order(
        wo_b["id"],
        schedule_work_order_payload(
            "2026-10-11T08:00:00Z", "2026-10-11T12:00:00Z"
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_QUALIFIED)
    assert get_work_order(wo_b["id"])["status"] == "APPROVED", (
        "no partial transition"
    )


def test_window_conflict_fires_when_credentials_valid():
    """PRD §3.7: "The window must not collide: treating each visit as a
    half-open interval, a conflict exists exactly when an existing order of the
    same contractor in `SCHEDULED` or `IN_PROGRESS` starts before the new visit
    ends and the new visit starts before that existing visit ends; back-to-back
    windows, where one order's `visit_end` equals the other's `visit_start`,
    are expressly permitted, and a true overlap is
    `ERR_TRADE_WINDOW_CONFLICT`."

    Control for the priority pair: with insurance valid on the visit start
    date, the same overlapping geometry surfaces ERR_TRADE_WINDOW_CONFLICT —
    the temporal rule is live once safety passes.

    Design: Difficulty/priority_pair_validation_conflict/schedule_with_expired_insurance_and_overlap_safety_beats_temporal
    """
    ctx, contractor, items = _setup_two_item_project(
        {
            "legal_name": "Risky Electric",
            "license_expires_on": "2027-01-01",
            "insurance_expires_on": "2026-10-10",
            "max_concurrent_jobs": 5,
        }
    )
    project_id = ctx["project"]["id"]
    wo_a = _approved_order(project_id, contractor["id"], items["e1"]["id"])
    schedule_work_order(
        wo_a["id"], "2026-10-10T08:00:00Z", "2026-10-12T12:00:00Z"
    )
    wo_b = _approved_order(project_id, contractor["id"], items["e2"]["id"])
    resp = api_client.schedule_trade_work_order(
        wo_b["id"],
        schedule_work_order_payload(
            "2026-10-10T09:00:00Z", "2026-10-10T10:00:00Z"
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_WINDOW_CONFLICT)
    assert get_work_order(wo_b["id"])["status"] == "APPROVED"


def test_contractor_half_open_adjacency_passes():
    """PRD §3.7: "The window must not collide: treating each visit as a
    half-open interval, a conflict exists exactly when an existing order of the
    same contractor in `SCHEDULED` or `IN_PROGRESS` starts before the new visit
    ends and the new visit starts before that existing visit ends; back-to-back
    windows, where one order's `visit_end` equals the other's `visit_start`,
    are expressly permitted, and a true overlap is
    `ERR_TRADE_WINDOW_CONFLICT`."

    [08:00,12:00) followed by [12:00,15:00): touching endpoints do not collide
    under half-open semantics.

    Design: Difficulty/resource_temporal_overlap/contractor_half_open_windows_adjacency_passes_overlap_fails
    """
    ctx = setup_selected_project(
        scope_items=[
            trade_scope_item_payload(description="e1"),
            trade_scope_item_payload(description="e2"),
            trade_scope_item_payload(description="e3"),
        ],
    )
    contractor = create_contractor(max_concurrent_jobs=5)
    items = {i["description"]: i for i in ctx["scope_items"]}
    project_id = ctx["project"]["id"]
    wo1 = _approved_order(project_id, contractor["id"], items["e1"]["id"])
    schedule_work_order(wo1["id"], "2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
    wo2 = _approved_order(project_id, contractor["id"], items["e2"]["id"])
    scheduled2 = schedule_work_order(
        wo2["id"], "2026-10-05T12:00:00Z", "2026-10-05T15:00:00Z"
    )
    assert scheduled2["status"] == "SCHEDULED", (
        "12:00 == 12:00 adjacency is legal under half-open semantics"
    )


def test_contractor_overlap_fails_against_both_neighbours():
    """PRD §3.7: "The window must not collide: treating each visit as a
    half-open interval, a conflict exists exactly when an existing order of the
    same contractor in `SCHEDULED` or `IN_PROGRESS` starts before the new visit
    ends and the new visit starts before that existing visit ends; back-to-back
    windows, where one order's `visit_end` equals the other's `visit_start`,
    are expressly permitted, and a true overlap is
    `ERR_TRADE_WINDOW_CONFLICT`."

    [11:00,13:00) intersects both [08:00,12:00) and [12:00,15:00) and is
    rejected; the order stays APPROVED.

    Design: Difficulty/resource_temporal_overlap/contractor_half_open_windows_adjacency_passes_overlap_fails
    """
    ctx = setup_selected_project(
        scope_items=[
            trade_scope_item_payload(description="e1"),
            trade_scope_item_payload(description="e2"),
            trade_scope_item_payload(description="e3"),
        ],
    )
    contractor = create_contractor(max_concurrent_jobs=5)
    items = {i["description"]: i for i in ctx["scope_items"]}
    project_id = ctx["project"]["id"]
    wo1 = _approved_order(project_id, contractor["id"], items["e1"]["id"])
    schedule_work_order(wo1["id"], "2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
    wo2 = _approved_order(project_id, contractor["id"], items["e2"]["id"])
    schedule_work_order(wo2["id"], "2026-10-05T12:00:00Z", "2026-10-05T15:00:00Z")
    wo3 = _approved_order(project_id, contractor["id"], items["e3"]["id"])
    resp = api_client.schedule_trade_work_order(
        wo3["id"],
        schedule_work_order_payload(
            "2026-10-05T11:00:00Z", "2026-10-05T13:00:00Z"
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_WINDOW_CONFLICT)
    assert get_work_order(wo3["id"])["status"] == "APPROVED"


def test_contractor_day_capacity_boundary():
    """PRD §3.7: "And the day must not overflow: the count of that contractor's
    distinct `SCHEDULED` or `IN_PROGRESS` orders whose `visit_start` falls on
    the same UTC calendar day (day boundaries at 00:00:00Z) must be below
    `max_concurrent_jobs`, otherwise `ERR_CONTRACTOR_DAY_CAPACITY`."

    With max_concurrent_jobs 1, two merely-touching windows on the same
    calendar day still collide: the day-count rule (existing count 1 is not
    < 1) is a separate gate from half-open overlap.

    Design: Corner/calculations/contractor_day_capacity_boundary
    """
    ctx, contractor, items = _setup_two_item_project(
        {"legal_name": "Solo Electric", "max_concurrent_jobs": 1}
    )
    project_id = ctx["project"]["id"]
    wo_a = _approved_order(project_id, contractor["id"], items["e1"]["id"])
    schedule_work_order(
        wo_a["id"], "2026-10-05T08:00:00Z", "2026-10-05T10:00:00Z"
    )
    wo_b = _approved_order(project_id, contractor["id"], items["e2"]["id"])
    resp = api_client.schedule_trade_work_order(
        wo_b["id"],
        schedule_work_order_payload(
            "2026-10-05T10:00:00Z", "2026-10-05T12:00:00Z"
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_DAY_CAPACITY)
    assert get_work_order(wo_b["id"])["status"] == "APPROVED"


def test_schedule_reversed_window_returns_invalid_date_range():
    """PRD §3.7: "The window must be well formed: `visit_end` strictly after
    `visit_start`, otherwise `ERR_INVALID_DATE_RANGE`."

    An equal endpoint (zero-length window) is rejected, not clamped.

    Design: Corner/validations/schedule_reversed_window_returns_invalid_date_range
    """
    ctx = setup_project_with_work_order(
        wo_target_status="APPROVED", quote_cents=50_000
    )
    wo_id = ctx["work_order"]["id"]
    resp = api_client.schedule_trade_work_order(
        wo_id,
        schedule_work_order_payload(
            "2026-10-05T08:00:00Z", "2026-10-05T08:00:00Z"
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
    assert get_work_order(wo_id)["status"] == "APPROVED"


def test_event_lock_blocked_until_trade_work_scheduled():
    """PRD §3.6: "Staff move `PUBLISHED` → `LOCKED`, which demands two proofs,
    each reported as `ERR_EVENT_NOT_LOCKABLE`: at least one active team-leader
    enrollment exists on the event — `is_team_leader` true with the enrollment
    in `ENROLLED` or `CONFIRMED` — and the host project's `readiness_posture`
    is `READY`."
    PRD §2.8: "The posture is `READY` exactly when both halves of a conjunction
    hold: every scope item in `INCLUDED` whose `volunteer_performable` is false
    is covered by a trade work order in one of `SCHEDULED`, `IN_PROGRESS`,
    `PENDING_INSPECTION`, `INSPECTED`, `INVOICED`, or `PAID`; and no material
    order of the project is in `ORDERED` or `STAGED`."

    A QUOTE_REQUESTED order does not count as coverage: posture is BLOCKED and
    the lock is rejected even with a team leader enrolled.

    Design: Difficulty/cross_entity_state_dependency/event_lock_blocked_until_trade_work_scheduled
    """
    ctx = setup_project_with_work_order(
        item_est=(100_000, 100_000),
        include_volunteer_item=True,
        wo_target_status="QUOTE_REQUESTED",
        quote_cents=100_000,
    )
    project = get_project(ctx["project"]["id"])
    assert project["readiness_posture"] == "BLOCKED", (
        "a licensed item with no live covering order blocks readiness"
    )
    ev = setup_event_with_team_leader(ctx["project"]["id"], max_volunteers=2)
    resp = api_client.patch_event(
        ev["event"]["id"], {"status": "LOCKED"}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_LOCKABLE)
    assert get_event(ev["event"]["id"])["status"] == "PUBLISHED"


def test_event_lock_succeeds_after_work_scheduled():
    """PRD §3.6: "Staff move `PUBLISHED` → `LOCKED`, which demands two proofs,
    each reported as `ERR_EVENT_NOT_LOCKABLE`: at least one active team-leader
    enrollment exists on the event — `is_team_leader` true with the enrollment
    in `ENROLLED` or `CONFIRMED` — and the host project's `readiness_posture`
    is `READY`."
    PRD §3.6: "On lock, every `ENROLLED` enrollment of the event becomes
    `CONFIRMED`, and the host project advances `READY` → `EVENT_SCHEDULED`."

    Once the covering order is SCHEDULED the posture flips to READY and the
    same lock succeeds — the gate read a different entity's state.

    Design: Difficulty/cross_entity_state_dependency/event_lock_blocked_until_trade_work_scheduled
    """
    ctx = setup_project_with_work_order(
        item_est=(100_000, 100_000),
        include_volunteer_item=True,
        wo_target_status="QUOTE_REQUESTED",
        quote_cents=100_000,
    )
    ev = setup_event_with_team_leader(ctx["project"]["id"], max_volunteers=2)
    drive_work_order_to(
        ctx["work_order"]["id"], ctx["contractor"]["id"], "SCHEDULED",
        quote_cents=100_000,
    )
    project = get_project(ctx["project"]["id"])
    assert project["readiness_posture"] == "READY"
    assert project["status"] == "READY"
    locked = validate_ok(
        api_client.patch_event(ev["event"]["id"], {"status": "LOCKED"}, STAFF)
    )
    assert locked["status"] == "LOCKED"
    project_after = get_project(ctx["project"]["id"])
    assert project_after["status"] == "EVENT_SCHEDULED"
    assert project_after["readiness_posture"] == "READY"

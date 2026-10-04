"""Scheduling: urgency classification, the RAPID 14-day deadline, treatment
blackout closed-interval semantics, and the clearance-vs-blackout guard order.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_approved_wish,
    create_chapter,
    create_treatment_window,
    create_treatment_windows_payload,
    create_wish_event_payload,
    get_child,
    get_wish,
    schedule_event,
    set_clock,
    setup_ready_to_schedule_wish,
    validate_error,
    validate_paginated,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
MEDICAL_PROVIDER = TEST_USERS["medical_provider_headers"]


def test_urgency_prognosis_threshold_boundary():
    """PRD section 3.3: "`RAPID` when the referral's `prognosis_months` was
    provided and is at most 6 — the boundary month itself classifies as rapid
    — and `STANDARD` otherwise, including when no prognosis was recorded at
    all."

    Design: Corner/calculations/urgency_prognosis_threshold_boundary
    """
    set_clock()
    chapter = create_chapter(territory_zip_prefixes=["900"])
    rapid = create_approved_wish(chapter=chapter, prognosis_months=6)["wish"]
    standard = create_approved_wish(
        chapter=chapter, zip_code="90044", child_full_name="Theo Alvarez",
        child_date_of_birth="2015-06-15", parent_email="alvarez@example.org",
        diagnosis_summary="cardiomyopathy", source_type="MEDICAL_PROFESSIONAL",
        prognosis_months=7)["wish"]
    assert rapid["urgency"] == "RAPID", "prognosis 6 <= 6 classifies RAPID"
    assert standard["urgency"] == "STANDARD", "prognosis 7 > 6 stays STANDARD"


def test_rapid_sla_deadline_boundary():
    """PRD section 3.8: "a `RAPID` wish must start promptly: its
    `event_start_date` may be no later than the calendar date of the wish's
    `determined_at` plus 14 days, with the boundary day itself allowed; a
    later start fails with `ERR_URGENT_SLA_VIOLATION` (HTTP 422)."
    Determined at the 2026-09-01 logical clock, the deadline is 2026-09-15.

    Design: Corner/calculations/rapid_sla_deadline_boundary
    """
    ctx = setup_ready_to_schedule_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a treehouse fast",
        prognosis_months=4, cash_cost_cents=50000)
    wish = ctx["wish"]
    assert wish["urgency"] == "RAPID"

    late = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-09-16", "2026-09-17"),
        WISH_COORDINATOR)
    validate_error(late, ApiErrorId.ERR_URGENT_SLA_VIOLATION)
    assert get_wish(wish["id"])["status"] == "READY_TO_SCHEDULE", (
        "the rejected attempt must leave the wish schedulable"
    )

    on_deadline = schedule_event(wish["id"], "2026-09-15", "2026-09-16")
    assert on_deadline["status"] == "SCHEDULED"


def test_treatment_window_inverted_rejected():
    """PRD section 3.8: "each entry pairs a `start_date` with an `end_date`,
    both valid dates with the start no later than the end, and any malformed
    entry fails the whole replacement with `ERR_TREATMENT_WINDOW_INVALID`
    (HTTP 422)."

    Design: Corner/validations/treatment_window_inverted_rejected
    """
    ctx = create_approved_wish()
    child_id = ctx["child_id"]
    resp = api_client.patch_child(
        child_id,
        create_treatment_windows_payload(
            [create_treatment_window("2026-09-25", "2026-09-20")]),
        MEDICAL_PROVIDER)
    validate_error(resp, ApiErrorId.ERR_TREATMENT_WINDOW_INVALID)
    assert get_child(child_id)["treatment_windows"] == [], (
        "the failed replacement must leave prior windows untouched"
    )


def test_blackout_event_start_on_window_end_conflicts():
    """PRD section 3.8: "both the event window and each treatment window are
    closed intervals, inclusive of both ends, so a conflict exists whenever
    the event starts on or before a window's last day and that window starts
    on or before the event's last day — an event beginning exactly on the
    final day of a treatment window conflicts, because closed intervals share
    that day. A clash is rejected with `ERR_TREATMENT_BLACKOUT_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/wish_event_blackout_closed_interval_overlap
    """
    ctx = setup_ready_to_schedule_wish(wish_type="RECEIVE_ITEM",
                                       captured_true_wish="a Lego castle",
                                       cash_cost_cents=100000)
    wish = ctx["wish"]
    patched = api_client.patch_child(
        ctx["child_id"],
        create_treatment_windows_payload(
            [create_treatment_window("2026-09-20", "2026-09-25")]),
        MEDICAL_PROVIDER)
    assert patched.status_code == 200, f"window setup failed: {patched.text}"

    conflict = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-09-25", "2026-09-27"),
        WISH_COORDINATOR)
    validate_error(conflict, ApiErrorId.ERR_TREATMENT_BLACKOUT_CONFLICT)
    assert get_wish(wish["id"])["status"] == "READY_TO_SCHEDULE"


def test_blackout_disjoint_event_succeeds():
    """PRD section 3.8: "a conflict exists whenever the event starts on or
    before a window's last day and that window starts on or before the
    event's last day" — an event starting the day AFTER the window's last day
    shares no day and is schedulable.

    Design: Difficulty/resource_temporal_overlap/wish_event_blackout_closed_interval_overlap
    """
    ctx = setup_ready_to_schedule_wish(wish_type="RECEIVE_ITEM",
                                       captured_true_wish="a Lego castle",
                                       cash_cost_cents=100000)
    wish = ctx["wish"]
    patched = api_client.patch_child(
        ctx["child_id"],
        create_treatment_windows_payload(
            [create_treatment_window("2026-09-20", "2026-09-25")]),
        MEDICAL_PROVIDER)
    assert patched.status_code == 200, f"window setup failed: {patched.text}"

    conflict = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-09-25", "2026-09-27"),
        WISH_COORDINATOR)
    validate_error(conflict, ApiErrorId.ERR_TREATMENT_BLACKOUT_CONFLICT)

    disjoint = schedule_event(wish["id"], "2026-09-26", "2026-09-28")
    assert disjoint["status"] == "SCHEDULED"
    assert get_wish(wish["id"])["status"] == "SCHEDULED"


def test_travel_scheduling_reports_clearance_before_blackout():
    """PRD section 3.8: "Three guards then run in order. First, a `TRAVEL`
    wish must hold a medical clearance in `CLEARED` or `CONDITIONAL` status
    whose `valid_until` falls on or after `event_end_date` — a clearance
    expiring mid-event is not good enough — or scheduling fails with
    `ERR_MEDICAL_CLEARANCE_INVALID` (HTTP 422); non-travel wishes skip this
    guard entirely. Second, the event window must avoid every entry of the
    child's `treatment_windows`"

    Design: Difficulty/priority_pair_validation_conflict/travel_clearance_safety_beats_blackout_temporal
    """
    ctx = setup_ready_to_schedule_wish(
        wish_type="TRAVEL", captured_true_wish="fly to the mountains",
        cash_cost_cents=100000, clearance_valid_until="2026-09-30")
    wish = ctx["wish"]
    patched = api_client.patch_child(
        ctx["child_id"],
        create_treatment_windows_payload(
            [create_treatment_window("2026-10-05", "2026-10-10")]),
        MEDICAL_PROVIDER)
    assert patched.status_code == 200, f"window setup failed: {patched.text}"

    # Violates BOTH guards: clearance valid_until (2026-09-30) < event_end
    # (2026-10-08), and [2026-10-06, 2026-10-08] intersects the blackout.
    resp = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-10-06", "2026-10-08"),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_MEDICAL_CLEARANCE_INVALID)


def test_travel_dual_guard_failure_leaves_no_event():
    """PRD section 3.8: "the wish must be `READY_TO_SCHEDULE`, otherwise
    `ERR_INVALID_WISH_STATE`. Three guards then run in order." — a request
    rejected by the first guard creates no event and leaves the wish
    schedulable.

    Design: Difficulty/priority_pair_validation_conflict/travel_clearance_safety_beats_blackout_temporal
    """
    ctx = setup_ready_to_schedule_wish(
        wish_type="TRAVEL", captured_true_wish="fly to the mountains",
        cash_cost_cents=100000, clearance_valid_until="2026-09-30")
    wish = ctx["wish"]
    patched = api_client.patch_child(
        ctx["child_id"],
        create_treatment_windows_payload(
            [create_treatment_window("2026-10-05", "2026-10-10")]),
        MEDICAL_PROVIDER)
    assert patched.status_code == 200, f"window setup failed: {patched.text}"

    resp = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-10-06", "2026-10-08"),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_MEDICAL_CLEARANCE_INVALID)

    assert get_wish(wish["id"])["status"] == "READY_TO_SCHEDULE"
    events = api_client.list_wish_events(wish["id"], WISH_COORDINATOR)
    _, meta = validate_paginated(events)
    assert meta["total_count"] == 0, "no event may be created by the rejected call"

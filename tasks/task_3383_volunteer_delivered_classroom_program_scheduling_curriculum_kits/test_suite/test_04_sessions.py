"""Sessions: cadence, delivery windows, overlap, substitution, sweeps (PRD §3.5)."""
from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    TUESDAYS_4,
    add_partner_with_volunteer,
    add_session,
    api_client,
    base_world,
    confirm_session,
    get_delivery,
    get_session,
    get_volunteer,
    make_delivery,
    make_volunteer,
    plan_delivery,
    planned_delivery,
    record_session_delivery,
    schedule_delivery,
    scheduled_delivery,
    session_payload,
    set_clock,
    transition_delivery,
    validate_error,
    validate_success,
)


def test_cadence_gap_boundaries_three_and_fourteen_inclusive(api):
    """PRD §3.5: "Only adjacent pairs in that ordering are checked, and each
    gap must be at least 3 days and at most 14 days, both bounds inclusive."

    Design: Corner/calculations/corner_cadence_gap_boundaries_three_and_fourteen_inclusive
    """
    world = base_world()
    delivery = planned_delivery(world, enrolled_count=10)
    vol = world["volunteer"]["id"]
    s1 = add_session(delivery["id"], vol, "2026-09-08", confirm=True)  # Tuesday
    s2 = add_session(delivery["id"], vol, "2026-09-11", confirm=True)  # Friday, gap 3
    s3 = add_session(delivery["id"], vol, "2026-09-22", confirm=True)  # Tuesday, gap 11
    assert s1["status"] == s2["status"] == s3["status"] == "SCHEDULED"

    sx = add_session(delivery["id"], vol, "2026-09-10", start_minutes=780, end_minutes=840)
    resp_x = api_client.transition_session(sx["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp_x, ApiErrorId.ERR_CADENCE_VIOLATION)  # 2 days after s1

    sy = add_session(delivery["id"], vol, "2026-10-07")  # Wednesday, 15 days after s3
    resp_y = api_client.transition_session(sy["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp_y, ApiErrorId.ERR_CADENCE_VIOLATION)

    sw = add_session(delivery["id"], vol, "2026-10-06")  # Tuesday, 14 days after s3
    ok_w = confirm_session(sw["id"])
    assert ok_w["status"] == "SCHEDULED", "14-day gap is at the inclusive ceiling"
    assert get_session(sx["id"])["status"] == "TENTATIVE"
    assert get_session(sy["id"])["status"] == "TENTATIVE"


def test_session_on_non_instructional_day_rejected(api):
    """PRD §3.5: "The `scheduled_date` must not precede the logical clock's
    current date, and its weekday must be one of the school's
    `instructional_days`; either failure is `ERR_SESSION_DATE_INVALID`."

    Design: Corner/validations/corner_session_on_non_instructional_day_rejected
    """
    world = base_world()
    delivery = planned_delivery(world, enrolled_count=10)
    s1 = add_session(delivery["id"], world["volunteer"]["id"], "2026-09-12")  # Saturday
    resp = api_client.transition_session(s1["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SESSION_DATE_INVALID)
    assert get_session(s1["id"])["status"] == "TENTATIVE"


def test_record_delivery_before_scheduled_date_rejected(api):
    """PRD §3.5: "the logical clock's date must fall inside the session's
    delivery window: on or after `scheduled_date` and no later than seven days
    after it, both ends inclusive, else `ERR_SESSION_DATE_INVALID`."

    Design: Corner/validations/corner_record_delivery_before_scheduled_date_rejected
    """
    world = base_world(assemble=20)
    sched = scheduled_delivery(world, TUESDAYS_4, enrolled_count=10)
    s1 = sched["sessions"][0]
    # clock is still the default 2026-09-01, ahead of the 2026-09-08 session
    resp = api_client.transition_session(s1["id"], {"action": "RECORD_DELIVERY"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SESSION_DATE_INVALID)
    assert get_session(s1["id"])["status"] == "SCHEDULED"
    assert get_volunteer(world["volunteer"]["id"])["hours_contributed"] == 0


def test_session_delivered_terminal_no_reconfirm(api):
    """PRD §3.5: "CANCEL moves a session from TENTATIVE, SCHEDULED,
    NEEDS_SUBSTITUTE, or NO_SHOW to CANCELLED, whether requested directly or
    arriving as a delivery cascade; DELIVERED and CANCELLED are terminal."
    PRD §3.5: "Success credits the volunteer session hours — the session's
    duration in minutes divided by 60, rounded half-up to two decimal places
    for that session before joining any sum"

    Design: Corner/state_machines/corner_session_delivered_terminal_no_reconfirm
    """
    world = base_world(assemble=20)
    sched = scheduled_delivery(world, TUESDAYS_4, enrolled_count=10)
    s1 = sched["sessions"][0]
    record_session_delivery(s1["id"], "2026-09-08")

    resp = api_client.transition_session(s1["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_session(s1["id"])["status"] == "DELIVERED"
    hours = get_volunteer(world["volunteer"]["id"])["hours_contributed"]
    assert hours == 1.0, f"60-minute session credited once, got {hours}"


def test_session_reschedule_self_loop_updates_fields(api):
    """PRD §3.5: "Rescheduling is a self-loop from SCHEDULED to SCHEDULED and
    also the recovery path from NO_SHOW back to SCHEDULED; both branches are
    identical. The request must carry `new_date`, `new_start_minutes`, and
    `new_end_minutes` — any that is absent is `ERR_VALIDATION` — and re-runs
    the same date, overlap, and cadence checks evaluated against the new
    values; success replaces the date and minute fields and recomputes
    `duration_minutes`."

    Design: Corner/state_machines/corner_session_reschedule_self_loop_updates_fields
    """
    world = base_world()
    delivery = planned_delivery(world, enrolled_count=10)
    vol = world["volunteer"]["id"]
    add_session(delivery["id"], vol, "2026-09-08", confirm=True)
    s2 = add_session(delivery["id"], vol, "2026-09-15", confirm=True)
    version_before = s2["version"]

    bad = api_client.transition_session(
        s2["id"],
        {"action": "RESCHEDULE", "new_date": "2026-09-10", "new_start_minutes": 540, "new_end_minutes": 600},
        COORDINATOR,
    )
    validate_error(bad, ApiErrorId.ERR_CADENCE_VIOLATION)  # 2 days after 09-08
    assert get_session(s2["id"])["scheduled_date"] == "2026-09-15"

    ok = api_client.transition_session(
        s2["id"],
        {"action": "RESCHEDULE", "new_date": "2026-09-18", "new_start_minutes": 780, "new_end_minutes": 840},
        COORDINATOR,
    )
    data = validate_success(ok, 200)
    assert data["status"] == "SCHEDULED"
    assert data["scheduled_date"] == "2026-09-18"
    assert data["start_minutes"] == 780
    assert data["duration_minutes"] == 60
    assert data["version"] == version_before + 1, "a mutation increments version by 1 (PRD §2.5)"


def test_delivery_first_record_delivery_bubbles_to_in_progress(api):
    """PRD §3.4: "The first session recorded DELIVERED bubbles the delivery
    from SCHEDULED to IN_PROGRESS automatically, recomputing
    `sessions_delivered_count`."

    Design: Corner/state_machines/corner_delivery_first_record_delivery_bubbles_to_in_progress
    """
    world = base_world(assemble=20)
    sched = scheduled_delivery(world, TUESDAYS_4, enrolled_count=10)
    assert sched["delivery"]["status"] == "SCHEDULED"

    record_session_delivery(sched["sessions"][0]["id"], "2026-09-08")
    after = get_delivery(sched["delivery"]["id"])
    assert after["status"] == "IN_PROGRESS", "first RECORD_DELIVERY bubbles the delivery up"
    assert after["sessions_delivered_count"] == 1


def test_substitute_stale_delivery_version_rejected(api):
    """PRD §2.6: "Substituting a session's volunteer requires the client to
    supply `expected_delivery_version`, carrying the parent delivery's
    `version` as last observed. If the delivery's current `version` no longer
    matches — for example because a credential-expiry cascade or an earlier
    substitution has recomputed the delivery's blocked-session count since the
    client last read it — the request is rejected with
    `ERR_STALE_DELIVERY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/corner_substitute_stale_delivery_version_rejected
    """
    world = base_world()
    second = add_partner_with_volunteer()
    delivery = planned_delivery(world, enrolled_count=10)
    s1 = add_session(delivery["id"], world["volunteer"]["id"], "2026-09-08", confirm=True)
    stale_version = get_delivery(delivery["id"])["version"]
    transition_delivery(delivery["id"], "CONFIRM_TEACHER")  # mutates the delivery

    resp = api_client.substitute_session(
        s1["id"],
        {"new_volunteer_id": second["volunteer"]["id"], "expected_delivery_version": stale_version},
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_DELIVERY_VERSION)
    after = get_session(s1["id"])
    assert after["volunteer_id"] == world["volunteer"]["id"]
    assert after["status"] == "SCHEDULED"


def test_volunteer_screening_expiry_sweep_flips_scheduled_session(api):
    """PRD §2.4: "A volunteer whose background-screening clearance has lapsed —
    the clock now reading later than `screening_expires_on` — moves from
    CLEARED to EXPIRED, and a volunteer whose training currency has lapsed past
    `training_expires_on` moves from COMPLETED to EXPIRED; each expiry cascades
    to that volunteer's SCHEDULED sessions as described in §3.2."
    PRD §3.2: "In each case the volunteer's sessions in SCHEDULED move to
    NEEDS_SUBSTITUTE, and each affected delivery recomputes
    `sessions_blocked_count`, bumping its `version`."

    Design: Corner/state_machines/corner_volunteer_screening_expiry_sweep_flips_scheduled_session
    """
    world = base_world()
    delivery = planned_delivery(world, enrolled_count=10)
    # Wednesday 2027-09-08: past the 2027-09-01 credential expiry, but within
    # its own +7-day delivery window when the clock lands on 2027-09-02.
    s1 = add_session(delivery["id"], world["volunteer"]["id"], "2027-09-08", confirm=True)
    assert s1["status"] == "SCHEDULED"

    set_clock("2027-09-02T00:00:00Z")
    vol_after = get_volunteer(world["volunteer"]["id"])
    assert vol_after["screening_status"] == "EXPIRED"
    assert vol_after["eligible"] is False
    assert get_session(s1["id"])["status"] == "NEEDS_SUBSTITUTE"
    assert get_delivery(delivery["id"])["sessions_blocked_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: volunteer half-open overlap (two tests)
# ---------------------------------------------------------------------------

def _three_planned_deliveries():
    """One volunteer leading three PLANNED deliveries under one agreement."""
    world = base_world()
    vol = world["volunteer"]["id"]
    deliveries = [
        planned_delivery(world, enrolled_count=10, classroom_label=f"Room {12 + i}")
        for i in range(3)
    ]
    return world, vol, deliveries


def test_volunteer_sessions_back_to_back_allowed(api):
    """PRD §3.5: "The candidate must not overlap any other SCHEDULED session of
    the same volunteer on the same date, where overlap uses half-open
    intervals: two sessions clash when the candidate starts before the other
    ends and the other starts before the candidate ends, so back-to-back
    sessions are allowed — a clash is `ERR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/volunteer_sessions_half_open_overlap_back_to_back_allowed
    """
    world, vol, deliveries = _three_planned_deliveries()
    s_a = add_session(deliveries[0]["id"], vol, "2026-09-08", start_minutes=540, end_minutes=630, confirm=True)
    assert s_a["status"] == "SCHEDULED"
    # back-to-back: starts exactly when the earlier session ends
    s_b = add_session(deliveries[1]["id"], vol, "2026-09-08", start_minutes=630, end_minutes=720, confirm=True)
    assert s_b["status"] == "SCHEDULED", "half-open intervals: 630 == 630 is not an overlap"


def test_volunteer_sessions_strict_interior_overlap_rejected(api):
    """PRD §3.5: "two sessions clash when the candidate starts before the other
    ends and the other starts before the candidate ends, so back-to-back
    sessions are allowed — a clash is `ERR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/volunteer_sessions_half_open_overlap_back_to_back_allowed
    """
    world, vol, deliveries = _three_planned_deliveries()
    add_session(deliveries[0]["id"], vol, "2026-09-08", start_minutes=540, end_minutes=630, confirm=True)
    # 600 < 630 and 540 < 660: strict interior overlap
    s_c = add_session(deliveries[2]["id"], vol, "2026-09-08", start_minutes=600, end_minutes=660)
    resp = api_client.transition_session(s_c["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)
    assert get_session(s_c["id"])["status"] == "TENTATIVE"


# ---------------------------------------------------------------------------
# Difficulty: safety error masks cadence error (two tests)
# ---------------------------------------------------------------------------

def _ineligible_confirm_world():
    """PLANNED delivery (eligible lead) with s1 SCHEDULED on 2026-09-08, plus
    an uncredentialed volunteer of the same sponsor partner."""
    world = base_world()
    vol_bad = make_volunteer(
        world["partner"]["id"], credentialed=False, full_name="Vol Un", email="un@acme.example"
    )
    delivery = planned_delivery(world, enrolled_count=10)
    add_session(delivery["id"], world["volunteer"]["id"], "2026-09-08", confirm=True)
    return world, vol_bad, delivery


def test_confirm_ineligible_volunteer_reports_safety_error_not_cadence(api):
    """PRD §2.7: "Every request is validated against an ordered ladder, and the
    first failing tier reports its error; later tiers are never consulted once
    an earlier one fails."
    PRD §2.7: "Volunteer eligibility for assignment — evaluated on delivery
    planning, session confirmation, and session substitution — else
    `ERR_VOLUNTEER_INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_ineligible_volunteer_safety_error_masks_cadence_error
    """
    world, vol_bad, delivery = _ineligible_confirm_world()
    # 2026-09-10 is 2 days after the sibling SCHEDULED session (cadence
    # violation) AND the volunteer is ineligible; safety (tier 7) wins.
    s2 = add_session(delivery["id"], vol_bad["id"], "2026-09-10")
    resp = api_client.transition_session(s2["id"], {"action": "CONFIRM"}, COORDINATOR)
    err = validate_error(resp, ApiErrorId.ERR_VOLUNTEER_INELIGIBLE)
    assert err["error_id"] != ApiErrorId.ERR_CADENCE_VIOLATION.value
    assert get_session(s2["id"])["status"] == "TENTATIVE"


def test_confirm_same_gap_reports_cadence_once_volunteer_eligible(api):
    """PRD §2.7: "Within this tier a fixed sub-order applies: date validity
    (`ERR_SESSION_DATE_INVALID`) is evaluated first, then volunteer time
    overlap (`ERR_SESSION_OVERLAP`), then cadence (`ERR_CADENCE_VIOLATION`)"
    PRD §3.5: "each gap must be at least 3 days and at most 14 days, both
    bounds inclusive."

    Design: Difficulty/priority_pair_validation_conflict/confirm_ineligible_volunteer_safety_error_masks_cadence_error
    """
    world, vol_bad, delivery = _ineligible_confirm_world()
    # eligible volunteer, same 2-day gap: the cadence tier now reports.
    s2 = add_session(delivery["id"], world["volunteer"]["id"], "2026-09-10", start_minutes=780, end_minutes=840)
    resp = api_client.transition_session(s2["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CADENCE_VIOLATION)
    assert get_session(s2["id"])["status"] == "TENTATIVE"

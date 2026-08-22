"""Street closures, displacement and the officer-triggered epoch advance."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_closure_order, assert_epoch_report,
    set_clock, create_zone, create_pitch,
    setup_active_permit, setup_district_pitch_and_active_permit,
    book_session, draft_closure, activate_closure, draft_and_activate_closure,
    run_epoch_advance, read_zone, read_pitch, read_permit, read_booking,
    read_closure, permit_version,
    make_officer_headers,
    OFFICER_ALPHA,
)
from test_helpers.api_client import api_client


OLD_TOWN = dict(name="Old Town", code="OT", base_noise_cap_db=72,
                evening_start_minute=1020, quiet_hours_start_minute=1260,
                quiet_hours_end_minute=480, weekend_noise_bonus_db=0,
                evening_penalty_db=8, max_concurrent_closures=2)


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade /
#          closure_activation_cascades_to_pitch_booking_and_minute_credit
# ---------------------------------------------------------------------------

def _district_with_fallback_pair_and_booking():
    zone = create_zone()
    fallback = create_pitch(zone["id"], code="RP-02", tier="STANDARD",
                            noise_cap_db=80, amplification_allowed=True,
                            max_session_minutes=120, daily_session_cap=3,
                            premium_slots_per_draw=1)
    primary = create_pitch(zone["id"], code="RP-01", tier="STANDARD",
                           noise_cap_db=82, amplification_allowed=True,
                           max_session_minutes=120, daily_session_cap=3,
                           premium_slots_per_draw=1,
                           fallback_pitch_id=fallback["id"])
    ctx = setup_active_permit(zone["id"])
    ctx.update(zone=zone, pitch=primary, fallback=fallback)
    ctx["booking"] = book_session(ctx["permit"]["id"], primary["id"],
                                  "2026-08-25T10:00:00Z",
                                  "2026-08-25T11:30:00Z",
                                  ctx["performer"]["id"])
    return ctx


def test_zone_wide_activation_closes_every_pitch_in_the_district(api):
    """PRD §3.9: "An admitted activation cascades four levels deep. The order
    moves `DRAFT → ACTIVE` and the district's `active_closure_count` is brought
    up to the number of `ACTIVE` orders in that district. That activation sets
    `availability_status` to `CLOSED` on every pitch in scope — the single named
    pitch when `pitch_id` was supplied, otherwise every pitch in the order's
    district."

    Design: Difficulty/transitive_cascade/closure_activation_cascades_to_pitch_booking_and_minute_credit
    """
    ctx = _district_with_fallback_pair_and_booking()
    closure = draft_closure(ctx["zone"]["id"], "2026-08-25T09:00:00Z",
                            "2026-08-25T12:00:00Z", reason="SPECIAL_EVENT")
    assert closure["status"] == "DRAFT"
    assert read_pitch(ctx["pitch"]["id"])["availability_status"] == "OPEN", \
        "nothing at all is closed until the order is activated"

    activated = activate_closure(closure["id"])
    assert_closure_order(activated)
    assert activated["status"] == "ACTIVE"
    assert read_zone(ctx["zone"]["id"])["active_closure_count"] == 1
    assert read_pitch(ctx["pitch"]["id"])["availability_status"] == "CLOSED"
    assert read_pitch(ctx["fallback"]["id"])["availability_status"] == "CLOSED"


def test_displaced_session_is_cancelled_when_its_fallback_is_also_closed(api):
    """PRD §3.9: "A displaced session is **relocated** when the pitch nominates a
    `fallback_pitch_id`, that fallback pitch is itself `OPEN`, and the session's
    window survives the buffered conflict test on the fallback pitch; otherwise
    it is **cancelled outright**."
    PRD §3.9: "An outright cancellation moves the session to
    `CANCELLED_BY_CLOSURE`, and that cancellation itself credits the permit twice
    over: `season_minutes_used` is reduced by the session's `duration_minutes`
    and `closure_credit_minutes` grows by the same figure."
    PRD §3.9: "When the cascade finishes, the order records
    `relocated_booking_count`, `cancelled_booking_count` and
    `affected_booking_count`, the last being the total of the other two."

    Design: Difficulty/transitive_cascade/closure_activation_cascades_to_pitch_booking_and_minute_credit
    """
    ctx = _district_with_fallback_pair_and_booking()
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 90

    closure = draft_closure(ctx["zone"]["id"], "2026-08-25T09:00:00Z",
                            "2026-08-25T12:00:00Z", reason="SPECIAL_EVENT")
    activated = activate_closure(closure["id"])

    booking = read_booking(ctx["booking"]["id"])
    assert booking["status"] == "CANCELLED_BY_CLOSURE"
    assert booking["pitch_id"] == ctx["pitch"]["id"], \
        "an outright cancellation leaves the session on its original pitch"
    assert booking["relocated_from_pitch_id"] is None

    permit = read_permit(ctx["permit"]["id"])
    assert permit["season_minutes_used"] == 0
    assert permit["closure_credit_minutes"] == 90

    assert activated["affected_booking_count"] == 1
    assert activated["relocated_booking_count"] == 0
    assert activated["cancelled_booking_count"] == 1


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap /
#          zone_closure_closed_intervals_exhaust_concurrent_capacity
# ---------------------------------------------------------------------------

def _old_town_with_two_active_closures():
    zone = create_zone(**OLD_TOWN)
    pitch = create_pitch(zone["id"], code="OT-01", tier="STANDARD",
                         noise_cap_db=70, amplification_allowed=False,
                         max_session_minutes=120, daily_session_cap=2,
                         premium_slots_per_draw=1)
    first = draft_and_activate_closure(zone["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z",
                                       reason="SPECIAL_EVENT")
    second = draft_and_activate_closure(zone["id"], "2026-08-10T12:00:00Z",
                                        "2026-08-10T16:00:00Z", reason="PARADE")
    return {"zone": zone, "pitch": pitch, "first": first, "second": second}


def test_endpoint_touching_closures_both_activate_below_the_capacity(api):
    """PRD §3.9: "Activation is capacity-limited rather than mutually exclusive.
    Two closures intersect when the first one's `starts_at` is at or before the
    second one's `ends_at` and the first one's `ends_at` is at or after the
    second one's `starts_at`, so orders that merely touch at an endpoint do
    intersect. Count the other closure orders in the same district that are
    currently `ACTIVE` and intersect the order being activated; activation is
    admitted only while that count is strictly below the district's
    `max_concurrent_closures`, and is otherwise refused with
    `ERR_CLOSURE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/zone_closure_closed_intervals_exhaust_concurrent_capacity
    """
    ctx = _old_town_with_two_active_closures()
    assert ctx["first"]["status"] == "ACTIVE"
    assert ctx["second"]["status"] == "ACTIVE", (
        "the second order touches the first at exactly 12:00:00Z and is still "
        "admitted because one intersecting ACTIVE order is below the ceiling of 2")
    assert read_zone(ctx["zone"]["id"])["active_closure_count"] == 2
    assert read_pitch(ctx["pitch"]["id"])["availability_status"] == "CLOSED"


def test_third_intersecting_closure_exhausts_the_concurrent_capacity(api):
    """PRD §3.9: "Count the other closure orders in the same district that are
    currently `ACTIVE` and intersect the order being activated; activation is
    admitted only while that count is strictly below the district's
    `max_concurrent_closures`, and is otherwise refused with
    `ERR_CLOSURE_WINDOW_CONFLICT`. Orders in `DRAFT` or `LIFTED` never consume
    capacity."

    Design: Difficulty/resource_temporal_overlap/zone_closure_closed_intervals_exhaust_concurrent_capacity
    """
    ctx = _old_town_with_two_active_closures()
    third = draft_closure(ctx["zone"]["id"], "2026-08-10T10:00:00Z",
                          "2026-08-10T14:00:00Z", reason="CONSTRUCTION")

    resp = api.activate_closure_order(third["id"],
                                      make_officer_headers(OFFICER_ALPHA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_CLOSURE_WINDOW_CONFLICT)

    assert read_closure(third["id"])["status"] == "DRAFT"
    assert read_zone(ctx["zone"]["id"])["active_closure_count"] == 2
    assert read_pitch(ctx["pitch"]["id"])["availability_status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Queue B: relocation and the epoch advance
# ---------------------------------------------------------------------------

def test_pitch_scoped_closure_relocates_the_session_to_its_fallback(api):
    """PRD §3.9: "A relocation writes the old pitch into
    `relocated_from_pitch_id`, rewrites `pitch_id` to the fallback pitch,
    recomputes `effective_noise_cap_db` against the fallback pitch, and moves the
    session `RESERVED → RELOCATED`; the permit's `season_minutes_used` is
    deliberately unchanged, because a relocated session still consumes its
    minutes."
    PRD §3.9: "An optional `pitch_id` narrows the order to a single pitch; when
    it is omitted the order covers every pitch in the district."
    PRD §2.11: "Session listings filter on `permit_id`, on `pitch_id`, on
    `lottery_entry_id`, on `relocated_from_pitch_id` and on `status`."

    Design: Corner/state_machines/corner_closure_relocates_booking_to_fallback_pitch
    """
    ctx = _district_with_fallback_pair_and_booking()
    closure = draft_closure(ctx["zone"]["id"], "2026-08-25T09:00:00Z",
                            "2026-08-25T12:00:00Z", reason="CONSTRUCTION",
                            pitch_id=ctx["pitch"]["id"])
    activated = activate_closure(closure["id"])
    assert activated["status"] == "ACTIVE"

    assert read_pitch(ctx["pitch"]["id"])["availability_status"] == "CLOSED"
    assert read_pitch(ctx["fallback"]["id"])["availability_status"] == "OPEN", \
        "a pitch-scoped order leaves the sibling pitch open"

    booking = read_booking(ctx["booking"]["id"])
    assert booking["status"] == "RELOCATED"
    assert booking["pitch_id"] == ctx["fallback"]["id"]
    assert booking["relocated_from_pitch_id"] == ctx["pitch"]["id"]
    assert booking["effective_noise_cap_db"] == 78, (
        "recomputed against the fallback pitch: min(80, district 78), got "
        f"{booking['effective_noise_cap_db']}")

    permit = read_permit(ctx["permit"]["id"])
    assert permit["season_minutes_used"] == 90, \
        "a relocated session still consumes its minutes"
    assert permit["closure_credit_minutes"] == 0

    assert activated["relocated_booking_count"] == 1
    assert activated["cancelled_booking_count"] == 0

    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(),
        params={"relocated_from_pitch_id": ctx["pitch"]["id"]}))
    assert meta["total_count"] == 1


def test_epoch_advance_lifts_an_expired_closure_and_reopens_its_pitch(api):
    """PRD §3.9: "Step one lifts closures: every `ACTIVE` order whose `ends_at`
    is strictly before the clock moves `ACTIVE → LIFTED`, decrements its
    district's `active_closure_count` by one, and returns every pitch in its
    scope that no other `ACTIVE` order still covers to `availability_status`
    `OPEN`."
    PRD §3.9: "The epoch advance answers with a small report rather than an
    entity: `processed_at` carrying the clock instant the run executed, and the
    counters `closures_lifted_count`, `invoices_past_due_count`,
    `permits_expired_count`, `bookings_completed_count` and
    `performers_rescored_count`."

    Design: Corner/state_machines/corner_ops_run_lifts_expired_closure_and_reopens_pitch
    """
    zone = create_zone(**OLD_TOWN)
    pitch = create_pitch(zone["id"], code="OT-01", tier="STANDARD",
                         noise_cap_db=70, amplification_allowed=False)
    closure = draft_and_activate_closure(zone["id"], "2026-08-10T08:00:00Z",
                                         "2026-08-10T12:00:00Z", reason="PARADE")
    assert read_pitch(pitch["id"])["availability_status"] == "CLOSED"

    set_clock("2026-08-11T00:00:00Z")
    report = run_epoch_advance()
    assert_epoch_report(report)
    assert report["closures_lifted_count"] == 1

    assert read_closure(closure["id"])["status"] == "LIFTED"
    assert read_pitch(pitch["id"])["availability_status"] == "OPEN"
    assert read_zone(zone["id"])["active_closure_count"] == 0


def test_epoch_advance_completes_a_finished_session_without_releasing_minutes(api):
    """PRD §3.9: "Step four completes work already done: every session whose
    `status` is `RESERVED` or `RELOCATED` and whose `end_at` is at or before the
    clock moves to `COMPLETED`, and the permit's `season_minutes_used` is
    deliberately unchanged, because completed sessions still count against the
    season allowance."

    Design: Corner/state_machines/corner_ops_run_completes_finished_booking_without_releasing_minutes
    """
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True))
    booking = book_session(ctx["permit"]["id"], ctx["pitch"]["id"],
                           "2026-08-25T10:00:00Z", "2026-08-25T11:30:00Z",
                           ctx["performer"]["id"])

    set_clock("2026-08-26T00:00:00Z")
    report = run_epoch_advance()
    assert report["bookings_completed_count"] == 1
    assert report["permits_expired_count"] == 0
    assert report["invoices_past_due_count"] == 0

    assert read_booking(booking["id"])["status"] == "COMPLETED"
    permit = read_permit(ctx["permit"]["id"])
    assert permit["season_minutes_used"] == 90
    assert permit["lifecycle_status"] == "ACTIVE"


def test_epoch_advance_expires_the_permit_and_cancels_its_future_sessions(api):
    """PRD §3.9: "Step three expires permits. A permit whose lifecycle axis is
    `ACTIVE` or `RENEWAL_PENDING` expires once the clock is strictly past the end
    of its season, which is `23:59:59Z` on 31 December of its `season_year`; at
    exactly that instant the permit is still live. Expiry moves the lifecycle
    axis to `EXPIRED`, cancels every session of that permit that is `RESERVED` or
    `RELOCATED` with a `start_at` still in the future into `CANCELLED_BY_EXPIRY`
    — each crediting its `duration_minutes` back to `season_minutes_used` — and
    forfeits every lottery entry of that permit still `SUBMITTED`."

    Design: Corner/state_machines/corner_ops_run_expires_permit_and_cancels_future_bookings
    """
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True))
    set_clock("2026-12-20T00:00:00Z")
    booking = book_session(ctx["permit"]["id"], ctx["pitch"]["id"],
                           "2027-01-10T10:00:00Z", "2027-01-10T11:00:00Z",
                           ctx["performer"]["id"])
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 60

    set_clock("2027-01-02T00:00:00Z")
    report = run_epoch_advance()
    assert report["permits_expired_count"] == 1

    permit = read_permit(ctx["permit"]["id"])
    assert permit["lifecycle_status"] == "EXPIRED"
    assert permit["compliance_status"] == "CLEAR", \
        "expiry moves the lifecycle axis alone"
    assert read_booking(booking["id"])["status"] == "CANCELLED_BY_EXPIRY"
    assert permit["season_minutes_used"] == 0


def test_epoch_advance_reports_zero_counts_when_nothing_is_due(api):
    """PRD §3.9: "The epoch advance answers with a small report rather than an
    entity: `processed_at` carrying the clock instant the run executed, and the
    counters `closures_lifted_count`, `invoices_past_due_count`,
    `permits_expired_count`, `bookings_completed_count` and
    `performers_rescored_count`."
    PRD §3.9: "Every row the run mutates has its `version` incremented in the
    usual way."

    Design: Corner/endpoints/corner_ops_run_reports_zero_counts_when_nothing_is_due
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    version_before = permit_version(ctx["permit"]["id"])

    resp = api.run_epoch_advance(make_officer_headers(OFFICER_ALPHA))
    report = validate_success(resp, 200)
    assert_epoch_report(report)
    assert report["closures_lifted_count"] == 0
    assert report["invoices_past_due_count"] == 0
    assert report["permits_expired_count"] == 0
    assert report["bookings_completed_count"] == 0
    assert report["performers_rescored_count"] == 0

    permit = read_permit(ctx["permit"]["id"])
    assert permit["version"] == version_before, \
        "a run that mutates nothing must not advance any row's version"
    assert permit["lifecycle_status"] == "ACTIVE"

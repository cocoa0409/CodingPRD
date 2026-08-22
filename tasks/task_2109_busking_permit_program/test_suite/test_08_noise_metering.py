"""Metering live sessions against the effective sound ceiling."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_noise_reading,
    create_noise_reading_payload, create_session_booking_payload,
    set_clock, setup_district_pitch_and_active_permit,
    book_session, file_noise_reading, file_noise_readings,
    read_permit, read_booking, permit_version, reinstate_permit,
    make_officer_headers, make_performer_headers, make_inspector_headers,
)
from test_helpers.api_client import api_client


PITCH = dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
             amplification_allowed=True, max_session_minutes=120,
             daily_session_cap=3, premium_slots_per_draw=1)


def _metered_session(start_at="2026-08-12T10:00:00Z",
                     end_at="2026-08-12T12:00:00Z",
                     clock="2026-08-12T10:30:00Z", pitch_overrides=None,
                     zone_overrides=None):
    ctx = setup_district_pitch_and_active_permit(
        zone_overrides=zone_overrides,
        pitch_overrides=pitch_overrides or PITCH)
    ctx["booking"] = book_session(ctx["permit"]["id"], ctx["pitch"]["id"],
                                  start_at, end_at, ctx["performer"]["id"])
    set_clock(clock)
    return ctx


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / noise_reading_exactly_at_effective_cap_is_compliant
# ---------------------------------------------------------------------------

def test_reading_exactly_at_the_effective_cap_is_compliant(api):
    """PRD §3.8: "The `verdict` is `COMPLIANT` when `reading_db` is less than or
    equal to `effective_cap_db` and `VIOLATION` otherwise — the ceiling is
    inclusive, so a reading of exactly the cap is compliant."
    PRD §3.1: "Start with the district allowance: the district's
    `base_noise_cap_db`, plus its `weekend_noise_bonus_db` when the evaluation
    instant falls on a Saturday or Sunday in UTC, and nothing extra on the other
    five days. Take the smaller of that allowance and the pitch's own
    `noise_cap_db`."

    Design: Difficulty/boundary_precision_check/noise_reading_exactly_at_effective_cap_is_compliant
    """
    ctx = _metered_session(start_at="2026-08-12T14:00:00Z",
                           end_at="2026-08-12T16:00:00Z",
                           clock="2026-08-12T14:10:00Z")
    assert ctx["booking"]["effective_noise_cap_db"] == 78, (
        "min(pitch 82, district 78) on a Wednesday afternoon before the evening "
        f"threshold, got {ctx['booking']['effective_noise_cap_db']}")

    resp = api.create_noise_reading(
        create_noise_reading_payload(ctx["booking"]["id"],
                                     "2026-08-12T14:15:00Z", 78),
        make_inspector_headers("inspector-1"))
    reading = validate_success(resp, 201)
    assert_noise_reading(reading)
    assert reading["effective_cap_db"] == 78
    assert reading["verdict"] == "COMPLIANT", \
        "a reading of exactly the cap is compliant"

    permit = read_permit(ctx["permit"]["id"])
    assert permit["noise_violation_count"] == 0
    assert permit["compliance_status"] == "CLEAR"
    assert read_booking(ctx["booking"]["id"])["noise_violation_count"] == 0


def test_reading_one_decibel_over_the_cap_is_a_violation(api):
    """PRD §3.8: "The `verdict` is `COMPLIANT` when `reading_db` is less than or
    equal to `effective_cap_db` and `VIOLATION` otherwise — the ceiling is
    inclusive, so a reading of exactly the cap is compliant."
    PRD §3.8: "A `VIOLATION` increments both the session's
    `noise_violation_count` and the permit's `noise_violation_count`, and then
    the compliance axis escalates."
    PRD §3.8: "When the permit's counter reaches exactly two while the axis is
    `CLEAR`, the permit moves `CLEAR → WARNED`; from that point on, every
    subsequent ceiling evaluation for that permit subtracts a further 3 dB,
    which makes a second offence progressively harder to avoid."

    Design: Difficulty/boundary_precision_check/noise_reading_exactly_at_effective_cap_is_compliant
    """
    ctx = _metered_session(start_at="2026-08-12T14:00:00Z",
                           end_at="2026-08-12T16:00:00Z",
                           clock="2026-08-12T14:10:00Z")
    at_cap = file_noise_reading(ctx["booking"]["id"], "2026-08-12T14:15:00Z", 78)
    assert at_cap["verdict"] == "COMPLIANT"

    over = file_noise_reading(ctx["booking"]["id"], "2026-08-12T14:20:00Z", 79)
    assert over["effective_cap_db"] == 78
    assert over["verdict"] == "VIOLATION", \
        "79 dB against an inclusive 78 dB ceiling is a violation"

    assert read_booking(ctx["booking"]["id"])["noise_violation_count"] == 1
    permit = read_permit(ctx["permit"]["id"])
    assert permit["noise_violation_count"] == 1
    assert permit["compliance_status"] == "CLEAR", \
        "the axis only escalates when the counter reaches exactly two"


# ---------------------------------------------------------------------------
# Queue B: the ceiling formula
# ---------------------------------------------------------------------------

def test_weekend_bonus_and_evening_penalty_both_shape_the_ceiling(api):
    """PRD §3.1: "Start with the district allowance: the district's
    `base_noise_cap_db`, plus its `weekend_noise_bonus_db` when the evaluation
    instant falls on a Saturday or Sunday in UTC, and nothing extra on the other
    five days. Take the smaller of that allowance and the pitch's own
    `noise_cap_db`. If the evaluation instant's minute-of-day in UTC is at or
    after the district's `evening_start_minute`, subtract the district's
    `evening_penalty_db`."
    PRD §3.8: "The server then recomputes the effective sound ceiling of section
    3.1 from scratch at `taken_at`, using the session's **current** pitch (the
    fallback pitch after a relocation, never the pitch recorded in
    `relocated_from_pitch_id`), that pitch's district, the session's
    `amplification_planned` flag and the permit's compliance axis at the filing
    instant, and stores the result as `effective_cap_db`."

    Design: Corner/calculations/corner_effective_cap_applies_weekend_bonus_and_evening_penalty
    """
    ctx = _metered_session(start_at="2026-08-15T19:00:00Z",
                           end_at="2026-08-15T20:30:00Z",
                           clock="2026-08-15T19:10:00Z")
    assert ctx["booking"]["effective_noise_cap_db"] == 76, (
        "Saturday lifts the district allowance to 81, min with the pitch's 82 "
        "keeps 81, and the evening penalty of 5 brings it to 76, got "
        f"{ctx['booking']['effective_noise_cap_db']}")

    compliant = file_noise_reading(ctx["booking"]["id"],
                                   "2026-08-15T19:30:00Z", 76)
    assert compliant["effective_cap_db"] == 76
    assert compliant["verdict"] == "COMPLIANT"

    violation = file_noise_reading(ctx["booking"]["id"],
                                   "2026-08-15T19:40:00Z", 77)
    assert violation["verdict"] == "VIOLATION"

    permit = read_permit(ctx["permit"]["id"])
    assert permit["noise_violation_count"] == 1
    assert permit["compliance_status"] == "CLEAR"


def test_effective_ceiling_never_falls_below_the_absolute_floor(api):
    """PRD §3.1: "Whatever remains is then raised to an absolute floor of 55 dB:
    the effective ceiling is the larger of the computed figure and 55, so no
    combination of penalties can push a pitch below 55 dB."
    PRD §3.8: "The `verdict` is `COMPLIANT` when `reading_db` is less than or
    equal to `effective_cap_db` and `VIOLATION` otherwise — the ceiling is
    inclusive, so a reading of exactly the cap is compliant."

    Design: Corner/calculations/corner_effective_cap_never_falls_below_the_absolute_floor
    """
    ctx = _metered_session(
        start_at="2026-08-25T19:00:00Z", end_at="2026-08-25T20:00:00Z",
        clock="2026-08-25T19:10:00Z",
        zone_overrides=dict(name="Cathedral Close", code="CC",
                            base_noise_cap_db=56, evening_start_minute=1020,
                            quiet_hours_start_minute=1380,
                            quiet_hours_end_minute=360,
                            weekend_noise_bonus_db=0, evening_penalty_db=8,
                            max_concurrent_closures=1),
        pitch_overrides=dict(code="CC-01", tier="STANDARD", noise_cap_db=60,
                             amplification_allowed=False))

    at_floor = file_noise_reading(ctx["booking"]["id"],
                                  "2026-08-25T19:20:00Z", 55)
    assert at_floor["effective_cap_db"] == 55, (
        "56 minus the 8 dB evening penalty would be 48, but the floor pins it "
        f"at 55, got {at_floor['effective_cap_db']}")
    assert at_floor["verdict"] == "COMPLIANT"

    over_floor = file_noise_reading(ctx["booking"]["id"],
                                    "2026-08-25T19:30:00Z", 56)
    assert over_floor["effective_cap_db"] == 55
    assert over_floor["verdict"] == "VIOLATION"


def test_reading_taken_at_the_session_end_instant_is_refused(api):
    """PRD §3.8: "The measurement instant must fall inside the session's own
    window — at or after its `start_at` and strictly before its `end_at` — and a
    reading outside that range is refused with `ERR_READING_OUTSIDE_SESSION`."

    Design: Corner/validations/corner_noise_reading_outside_the_session_window_rejected
    """
    ctx = _metered_session(clock="2026-08-12T12:30:00Z")

    at_end = api.create_noise_reading(
        create_noise_reading_payload(ctx["booking"]["id"],
                                     "2026-08-12T12:00:00Z", 70),
        make_inspector_headers("inspector-1"))
    assert at_end.status_code == 422, f"Expected 422, got {at_end.status_code}"
    validate_error(at_end, ApiErrorId.ERR_READING_OUTSIDE_SESSION)

    at_start = api.create_noise_reading(
        create_noise_reading_payload(ctx["booking"]["id"],
                                     "2026-08-12T10:00:00Z", 70),
        make_inspector_headers("inspector-1"))
    reading = validate_success(at_start, 201)
    assert reading["verdict"] == "COMPLIANT", \
        "taken_at exactly at start_at is inside the half-open window"
    assert reading["effective_cap_db"] == 78

    _, meta = validate_paginated(api.list_noise_readings(
        ctx["booking"]["id"], make_officer_headers()))
    assert meta["total_count"] == 1


def test_inspector_may_file_a_reading_and_read_the_shared_resources(api):
    """PRD §2.1: "When `X-User-Role` is `NoiseInspector`, `X-User-ID` is likewise
    an opaque operator identifier not tied to any persisted entity; the server
    records it as `inspector_user_id` on each metering record but never compares
    it to any entity's `id`."
    PRD §3.8: "The reading's `inspector_user_id` is taken from the filing
    inspector's identity."

    Design: Corner/roles/corner_noise_inspector_shared_read_and_exclusive_write_both_work
    """
    ctx = _metered_session()
    inspector = make_inspector_headers("inspector-1")

    resp = api.create_noise_reading(
        create_noise_reading_payload(ctx["booking"]["id"],
                                     "2026-08-12T10:31:00Z", 70),
        inspector)
    reading = validate_success(resp, 201)
    assert reading["inspector_user_id"] == "inspector-1"
    assert reading["effective_cap_db"] == 78
    assert reading["verdict"] == "COMPLIANT"

    validate_success(api.get_session_booking(ctx["booking"]["id"], inspector))
    validate_success(api.get_pitch(ctx["pitch"]["id"], inspector))
    _, meta = validate_paginated(api.list_noise_readings(
        ctx["booking"]["id"], inspector))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine /
#          permit_lifecycle_and_compliance_axes_advance_independently
# ---------------------------------------------------------------------------

def test_two_violations_move_only_the_compliance_axis(api):
    """PRD §3.8: "A permit carries **two independent status axes on one row**,
    and confusing them is the most common way to get this domain wrong. The
    lifecycle axis — `PENDING_FEE`, `ACTIVE`, `RENEWAL_PENDING`, `EXPIRED`,
    `REVOKED` — is about money and seasons. The compliance axis — `CLEAR`,
    `WARNED`, `SUSPENDED` — is about behaviour. Neither axis constrains the
    other's transitions: a permit can be suspended while `RENEWAL_PENDING`, and
    an expiry does not clear a suspension."
    PRD §3.8: "When the permit's counter reaches exactly two while the axis is
    `CLEAR`, the permit moves `CLEAR → WARNED`; from that point on, every
    subsequent ceiling evaluation for that permit subtracts a further 3 dB,
    which makes a second offence progressively harder to avoid."

    Design: Difficulty/non_linear_state_machine/permit_lifecycle_and_compliance_axes_advance_independently
    """
    ctx = _metered_session()
    file_noise_readings(ctx["booking"]["id"],
                        ["2026-08-12T10:31:00Z", "2026-08-12T10:32:00Z"],
                        reading_db=85)

    permit = read_permit(ctx["permit"]["id"])
    assert permit["compliance_status"] == "WARNED"
    assert permit["lifecycle_status"] == "ACTIVE", \
        "the enforcement axis never drags the lifecycle axis with it"
    assert permit["noise_violation_count"] == 2
    assert permit["season_minutes_used"] == 120
    assert read_booking(ctx["booking"]["id"])["status"] == "RESERVED"


def test_reinstatement_clears_the_compliance_axis_and_leaves_lifecycle_alone(api):
    """PRD §3.8: "Reinstatement is admissible from `WARNED → CLEAR` and from
    `SUSPENDED → CLEAR`, and is refused with `ERR_PERFORMER_BARRED` while the
    holder's `standing` is still `BARRED`. Both edges reset
    `noise_violation_count` to 0; the edge out of `SUSPENDED` additionally
    clears `suspended_at` back to null."
    PRD §3.8: "Neither axis constrains the other's transitions: a permit can be
    suspended while `RENEWAL_PENDING`, and an expiry does not clear a
    suspension."

    Design: Difficulty/non_linear_state_machine/permit_lifecycle_and_compliance_axes_advance_independently
    """
    ctx = _metered_session()
    file_noise_readings(ctx["booking"]["id"],
                        ["2026-08-12T10:31:00Z", "2026-08-12T10:32:00Z"],
                        reading_db=85)
    assert read_permit(ctx["permit"]["id"])["compliance_status"] == "WARNED"

    reinstated = reinstate_permit(ctx["permit"]["id"],
                                  note="Sound check passed at the kerb")
    assert reinstated["compliance_status"] == "CLEAR"
    assert reinstated["lifecycle_status"] == "ACTIVE"
    assert reinstated["noise_violation_count"] == 0
    assert reinstated["season_minutes_used"] == 120, \
        "the minute ledger is untouched by either compliance transition"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency /
#          booking_admission_depends_on_permit_compliance_axis
# ---------------------------------------------------------------------------

def _suspended_by_four_violations():
    ctx = _metered_session()
    file_noise_readings(ctx["booking"]["id"],
                        ["2026-08-12T10:31:00Z", "2026-08-12T10:32:00Z",
                         "2026-08-12T10:33:00Z", "2026-08-12T10:34:00Z"],
                        reading_db=85)
    return ctx


def test_booking_is_refused_while_the_permit_compliance_axis_is_suspended(api):
    """PRD §3.8: "When the counter reaches four or more while the axis is
    `WARNED`, the permit moves `WARNED → SUSPENDED`."
    PRD §3.6: "A booking may only be made against a permit whose lifecycle axis
    is `ACTIVE`, otherwise `ERR_PERMIT_NOT_ACTIVE`; whose compliance axis is not
    `SUSPENDED`, otherwise `ERR_PERMIT_SUSPENDED`; and whose
    `expected_permit_version` is current, otherwise `ERR_STALE_PERMIT_VERSION`."

    Design: Difficulty/cross_entity_state_dependency/booking_admission_depends_on_permit_compliance_axis
    """
    ctx = _suspended_by_four_violations()
    permit = read_permit(ctx["permit"]["id"])
    assert permit["compliance_status"] == "SUSPENDED"
    assert permit["lifecycle_status"] == "ACTIVE"
    assert permit["noise_violation_count"] == 4

    resp = api.create_session_booking(
        create_session_booking_payload(ctx["permit"]["id"], ctx["pitch"]["id"],
                                       "2026-08-20T10:00:00Z",
                                       "2026-08-20T11:00:00Z",
                                       permit["version"]),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PERMIT_SUSPENDED)


def test_the_identical_booking_is_admitted_after_reinstatement(api):
    """PRD §3.8: "Recovery is never automatic. Regaining `GOOD` or `WATCH`
    standing does not lift a suspension by itself; only an officer's
    reinstatement does, and it takes an optional `note`."
    PRD §3.6: "A booking may only be made against a permit whose lifecycle axis
    is `ACTIVE`, otherwise `ERR_PERMIT_NOT_ACTIVE`; whose compliance axis is not
    `SUSPENDED`, otherwise `ERR_PERMIT_SUSPENDED`; and whose
    `expected_permit_version` is current, otherwise `ERR_STALE_PERMIT_VERSION`."

    Design: Difficulty/cross_entity_state_dependency/booking_admission_depends_on_permit_compliance_axis
    """
    ctx = _suspended_by_four_violations()
    reinstated = reinstate_permit(ctx["permit"]["id"],
                                  note="Limiter fitted and re-tested")
    assert reinstated["compliance_status"] == "CLEAR"
    assert reinstated["noise_violation_count"] == 0

    resp = api.create_session_booking(
        create_session_booking_payload(ctx["permit"]["id"], ctx["pitch"]["id"],
                                       "2026-08-20T10:00:00Z",
                                       "2026-08-20T11:00:00Z",
                                       permit_version(ctx["permit"]["id"])),
        make_performer_headers(ctx["performer"]["id"]))
    booking = validate_success(resp, 201)
    assert booking["status"] == "RESERVED"
    assert booking["duration_minutes"] == 60
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 180
    assert read_booking(ctx["booking"]["id"])["status"] == "RESERVED"


def test_reinstatement_does_not_restore_the_sessions_the_suspension_cancelled(api):
    """PRD §3.8: "Suspension is a real cascade: `suspended_at` is stamped from
    the clock, every session of that permit whose `status` is `RESERVED` or
    `RELOCATED` and whose `start_at` is still in the future is moved to
    `CANCELLED_BY_SUSPENSION` with its `duration_minutes` credited back to
    `season_minutes_used`, and every lottery entry of that permit still
    `SUBMITTED` is `FORFEITED`."
    PRD §3.8: "Sessions cancelled during the suspension are **not** restored,
    and the permit's minute ledger keeps the credits those cancellations
    produced."

    Design: Corner/state_machines/corner_reinstate_does_not_restore_bookings_cancelled_by_suspension
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id, performer_id = ctx["permit"]["id"], ctx["performer"]["id"]
    metered = book_session(permit_id, ctx["pitch"]["id"],
                           "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z",
                           performer_id)
    future = book_session(permit_id, ctx["pitch"]["id"],
                          "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z",
                          performer_id)
    assert read_permit(permit_id)["season_minutes_used"] == 180

    set_clock("2026-08-12T10:30:00Z")
    file_noise_readings(metered["id"],
                        ["2026-08-12T10:31:00Z", "2026-08-12T10:32:00Z",
                         "2026-08-12T10:33:00Z", "2026-08-12T10:34:00Z"],
                        reading_db=85)

    before = read_permit(permit_id)
    assert before["compliance_status"] == "SUSPENDED"
    assert before["season_minutes_used"] == 120
    assert read_booking(future["id"])["status"] == "CANCELLED_BY_SUSPENSION"

    after = reinstate_permit(permit_id, note="Limiter fitted")
    assert after["compliance_status"] == "CLEAR"
    assert after["noise_violation_count"] == 0
    assert after["season_minutes_used"] == 120, \
        "the minute ledger keeps the credit the cancellation produced"
    assert read_booking(future["id"])["status"] == "CANCELLED_BY_SUSPENSION"
    assert read_booking(metered["id"])["status"] == "RESERVED"

"""Two resource axes: booth intervals and the talent's daily aggregate."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

_MORNING = ("2026-09-10T09:00:00Z", "2026-09-10T12:00:00Z")
_BACK_TO_BACK = ("2026-09-10T12:00:00Z", "2026-09-10T13:00:00Z")


def _two_booths_with_different_buffers(api):
    """One DE market, a 30-minute booth and a 0-minute booth, both booked 09:00-12:00.

    Each talent carries their own signed contract, so the daily cap never
    interferes with the booth geometry under test.
    """
    world = fx.build_market(api, title_code="NOVA-26", name="Nova Drift 26",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=9000000,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-F",
                            turnaround_buffer_minutes=30,
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["booth_g"] = fx.create_booth(api, "BER-G", "Berlin", 0)
    world["bruno"] = fx.add_talent_with_contract(
        api, world, talent_name="Bruno Falk", territory_scope=["DE"],
        media_scope="ALL_MEDIA", buyout_fee_cents=400000, per_line_rate_cents=200,
    )
    world["session_a"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=_MORNING[0], end_utc=_MORNING[1],
        planned_line_count=120,
    )
    world["session_b"] = fx.book_session(
        api, world["plan"]["id"], world["bruno"]["talent"]["id"],
        world["booth_g"]["id"], world["bruno"]["contract"]["id"],
        start_utc=_MORNING[0], end_utc=_MORNING[1], planned_line_count=120,
    )
    return world


def _booking_on(world, talent_id, booth_id, contract_id, window,
                planned_line_count=40):
    return f.voice_session_payload(
        world["plan"]["id"], talent_id, booth_id, contract_id,
        start_utc=window[0], end_utc=window[1],
        planned_line_count=planned_line_count,
    )


def test_the_buffer_on_the_booth_row_decides_the_identical_back_to_back_booking(api):
    """Byte-identical bookings diverge because the two booths differ.

    "That buffer is the mandatory teardown-and-setup gap appended to every
    booking of this booth, and it is always read from the booth row and never
    from the session."

    "Because both intervals are half-open, a session starting exactly at an
    existing session's `occupied_end_utc` is accepted, while one starting a
    single minute earlier is rejected."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    On the buffered booth the occupied interval runs to 12:30 and the 12:00
    booking collides; on the zero-buffer booth the intervals merely touch at
    12:00 and the same booking is accepted, leaving 240 reserved minutes there
    against 210 on the buffered one.

    Design: Difficulty/resource_temporal_overlap/booth_buffer_is_read_from_the_booth_row_not_the_session
    """
    world = _two_booths_with_different_buffers(api)
    A.assert_instant_equals(world["session_a"]["occupied_end_utc"],
                            "2026-09-10T12:30:00Z", "occupied_end_utc")
    A.assert_instant_equals(world["session_b"]["occupied_end_utc"],
                            "2026-09-10T12:00:00Z", "occupied_end_utc")

    refused = api.create_voice_session(
        _booking_on(world, world["talent"]["id"], world["booth"]["id"],
                    world["contract"]["id"], _BACK_TO_BACK),
        users.PRODUCER,
    )
    accepted = api.create_voice_session(
        _booking_on(world, world["bruno"]["talent"]["id"], world["booth_g"]["id"],
                    world["bruno"]["contract"]["id"], _BACK_TO_BACK),
        users.PRODUCER,
    )

    validate_error(refused, E.ERR_BOOTH_WINDOW_CONFLICT, expected_status=409)
    on_the_zero_buffer_booth = validate_success(accepted, expected_status=201)
    assert on_the_zero_buffer_booth["status"] == "SCHEDULED"
    A.assert_instant_equals(on_the_zero_buffer_booth["occupied_end_utc"],
                            "2026-09-10T13:00:00Z", "occupied_end_utc")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 210
    assert fx.read_booth(api, world["booth_g"]["id"])["reserved_minutes_total"] == 240


def test_cancelling_the_blocking_session_frees_the_exact_refused_window(api):
    """The released interval is the one the refusal named.

    "`CANCELLED` sessions are excluded from the scan entirely."

    "`CANCELLED` sessions contribute nothing. The three-hour session above
    therefore contributes 210 minutes. This total is recomputed on every
    booking, on every cancellation, and on every cascaded cancellation."

    The buffered booth drops from 210 reserved minutes to zero, and the
    previously refused 12:00-13:00 booking then leaves it holding 90.

    Design: Difficulty/resource_temporal_overlap/booth_buffer_is_read_from_the_booth_row_not_the_session
    """
    world = _two_booths_with_different_buffers(api)
    booking = _booking_on(world, world["talent"]["id"], world["booth"]["id"],
                          world["contract"]["id"], _BACK_TO_BACK)
    validate_error(api.create_voice_session(booking, users.PRODUCER),
                   E.ERR_BOOTH_WINDOW_CONFLICT)

    cancelled = fx.cancel_session(api, world["session_a"]["id"])

    assert cancelled["status"] == "CANCELLED"
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    freed = validate_success(api.create_voice_session(booking, users.PRODUCER),
                             expected_status=201)
    assert freed["status"] == "SCHEDULED"
    assert freed["duration_minutes"] == 60
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 90


_CAP_DATE = "2026-09-10T00:00:00Z"
_AFTERNOON_NINETY = ("2026-09-10T13:00:00Z", "2026-09-10T14:30:00Z")
_NEXT_DAY_NINETY = ("2026-09-11T13:00:00Z", "2026-09-11T14:30:00Z")
_AFTERNOON_SIXTY = ("2026-09-10T13:00:00Z", "2026-09-10T14:00:00Z")


def _talent_with_three_hours_already_booked(api):
    """Cora is capped at 240 minutes a day and already holds a 180-minute booking.

    The clock sits on the booking's own UTC date so that
    ``reserved_minutes_on_clock_date`` reports that date's bucket, and the second
    booth is empty, which isolates the aggregate rule from booth geometry.
    """
    fx.set_clock(api, _CAP_DATE)
    world = fx.build_market(api, title_code="NOVA-27", name="Nova Drift 27",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=9000000,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-H",
                            turnaround_buffer_minutes=30,
                            talent_name="Cora Lang",
                            max_daily_recording_minutes=240,
                            buyout_fee_cents=600000, per_line_rate_cents=150,
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["booth_i"] = fx.create_booth(api, "BER-I", "Berlin", 30)
    world["session_a"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=_MORNING[0], end_utc=_MORNING[1],
        planned_line_count=120,
    )
    return world


def _cora_booking(world, window, planned_line_count=60):
    return _booking_on(world, world["talent"]["id"], world["booth_i"]["id"],
                       world["contract"]["id"], window, planned_line_count)


def test_the_daily_cap_collides_across_booths_with_no_overlap_in_time(api):
    """The talent limit is an aggregate over a date, not a pairwise overlap.

    "A new booking is rejected with `ERR_TALENT_DAILY_CAPACITY_EXCEEDED` when the
    talent's already-reserved minutes on the date of the new session's
    `start_utc`, plus the new session's `duration_minutes`, is strictly greater
    than the talent's `max_daily_recording_minutes`."

    "This is an aggregate rule, not a pairwise one: a talent capped at four hours
    a day who already has a three-hour session on a date accepts a further
    one-hour session on that date (three hours plus one hour is exactly four
    hours, which is not greater than the cap) but rejects a ninety-minute one —
    even in a completely different booth at a completely non-overlapping time."

    Design: Difficulty/resource_temporal_overlap/talent_daily_capacity_aggregates_across_booths_and_resets_per_utc_date
    """
    world = _talent_with_three_hours_already_booked(api)
    talent = fx.read_talent(api, world["talent"]["id"])
    assert talent["max_daily_recording_minutes"] == 240
    assert talent["reserved_minutes_on_clock_date"] == 180

    response = api.create_voice_session(
        _cora_booking(world, _AFTERNOON_NINETY), users.PRODUCER
    )

    validate_error(response, E.ERR_TALENT_DAILY_CAPACITY_EXCEEDED,
                   expected_status=409)
    assert fx.read_booth(api, world["booth_i"]["id"])["reserved_minutes_total"] == 0
    assert fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"] == 180


def test_the_refused_ninety_minutes_fit_one_utc_day_later(api):
    """The bucket is keyed on the calendar date of `start_utc`.

    "A talent's reserved minutes on a given UTC calendar date is the sum of
    `duration_minutes` over every session for that talent whose `status` is
    `SCHEDULED`, `IN_PROGRESS` or `RECORDED` and whose `start_utc` falls on that
    date; `CANCELLED` sessions are excluded."

    "Reading a talent exposes `reserved_minutes_on_clock_date`, which is that
    aggregate evaluated for the logical clock's current UTC date."

    Design: Difficulty/resource_temporal_overlap/talent_daily_capacity_aggregates_across_booths_and_resets_per_utc_date
    """
    world = _talent_with_three_hours_already_booked(api)
    validate_error(
        api.create_voice_session(_cora_booking(world, _AFTERNOON_NINETY),
                                 users.PRODUCER),
        E.ERR_TALENT_DAILY_CAPACITY_EXCEEDED,
    )

    next_day = validate_success(
        api.create_voice_session(_cora_booking(world, _NEXT_DAY_NINETY),
                                 users.PRODUCER),
        expected_status=201,
    )

    assert next_day["status"] == "SCHEDULED"
    assert next_day["duration_minutes"] == 90
    assert fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"] == 180
    assert fx.read_booth(api, world["booth_i"]["id"])["reserved_minutes_total"] == 120


def test_a_sixty_minute_booking_lands_exactly_on_the_daily_cap(api):
    """Equality with the cap is accepted, and the next day's session is excluded.

    "Booking a talent to exactly their daily cap is therefore accepted."

    "Because a session is required to start and end on the same UTC date, no
    session ever straddles two date buckets."

    180 minutes plus 60 is exactly the 240-minute cap, so the day's bucket closes
    at 240 while the 2026-09-11 booking sits outside it, and each booth ends up
    holding 210 reserved minutes.

    Design: Difficulty/resource_temporal_overlap/talent_daily_capacity_aggregates_across_booths_and_resets_per_utc_date
    """
    world = _talent_with_three_hours_already_booked(api)
    fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                    world["booth_i"]["id"], world["contract"]["id"],
                    start_utc=_NEXT_DAY_NINETY[0], end_utc=_NEXT_DAY_NINETY[1],
                    planned_line_count=60)

    at_the_cap = validate_success(
        api.create_voice_session(_cora_booking(world, _AFTERNOON_SIXTY, 40),
                                 users.PRODUCER),
        expected_status=201,
    )

    assert at_the_cap["status"] == "SCHEDULED"
    assert at_the_cap["duration_minutes"] == 60
    assert fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"] == 240
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 210
    assert fx.read_booth(api, world["booth_i"]["id"])["reserved_minutes_total"] == 210

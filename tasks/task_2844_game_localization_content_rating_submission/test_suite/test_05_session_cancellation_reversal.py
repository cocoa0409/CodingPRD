"""Cancelling a recorded session and the exactness of its reversal."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _voiced_market_with_a_recorded_session(api):
    world = fx.build_market(api, title_code="NOVA-16", name="Nova Drift 16",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=5000000,
                            required_voice_line_count=0, booth_code="BER-B",
                            stage=fx.STAGE_IN_LOCALIZATION)
    session = fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                              world["booth"]["id"], world["contract"]["id"],
                              start_utc="2026-09-10T09:00:00Z",
                              end_utc="2026-09-10T12:00:00Z",
                              planned_line_count=120)
    world["session"] = fx.record_session_at_its_start(api, session,
                                                      world["talent"]["id"], 120)
    return world


def test_a_recorded_session_charges_the_ledger_the_booth_and_the_market(api):
    """The five figures the cancellation will have to reverse.

    "Completion stores `recorded_line_count`, sets `line_fee_cents` to
    `recorded_line_count` multiplied by the contract's `per_line_rate_cents`,
    recomputes the contract's `committed_fee_cents`, recomputes the market plan's
    `voice_recorded_line_count` together with its `localization_cost_cents` and
    `overage_cents`, and increments the `version` of the session, the contract
    and the market plan by 1 each."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    120 lines at 250 cents is a 30,000-cent fee on top of a 500,000-cent buyout,
    a three-hour booking plus a thirty-minute buffer is 210 reserved minutes, and
    the FULL_VOICE text component of 32,508 cents plus the voice component is
    62,508 cents.

    Design: Difficulty/transitive_cascade/voice_session_cancel_reverses_five_downstream_effects
    """
    world = _voiced_market_with_a_recorded_session(api)

    session = world["session"]
    assert session["status"] == "RECORDED"
    assert session["duration_minutes"] == 180
    A.assert_money_cents(session["line_fee_cents"], 30000, "line_fee_cents")
    contract = fx.read_contract(api, world["contract"]["id"])
    A.assert_money_cents(contract["committed_fee_cents"], 530000,
                         "committed_fee_cents")
    booth = fx.read_booth(api, world["booth"]["id"])
    assert booth["reserved_minutes_total"] == 210
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 120
    A.assert_money_cents(plan["localization_cost_cents"], 62508,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")


def test_cancelling_a_recorded_session_reverses_every_derived_figure(api):
    """The reversal is exact: the fee, the ledger, the booth and the cost.

    "Hop one sets `status` to `CANCELLED` and `line_fee_cents` to 0, and
    recomputes the booth's `reserved_minutes_total` and the talent's reserved
    minutes for the clock date — the occupation is released, so a booking that
    previously collided now succeeds."

    "Hop two, caused by hop one's fee reversal, recomputes the contract's
    `committed_fee_cents`, which drops back by exactly the reversed line fee."

    "Hop three, caused by hop two, recomputes the market plan's
    `voice_recorded_line_count`, `localization_cost_cents` and `overage_cents`."

    The ledger returns to the 500,000-cent buyout, the booth to zero reserved
    minutes and the market to its 32,508-cent text-only-and-voiceless cost.

    Design: Difficulty/transitive_cascade/voice_session_cancel_reverses_five_downstream_effects
    """
    world = _voiced_market_with_a_recorded_session(api)

    cancelled = validate_success(
        api.cancel_voice_session(world["session"]["id"], users.PRODUCER)
    )

    assert cancelled["status"] == "CANCELLED"
    A.assert_money_cents(cancelled["line_fee_cents"], 0, "line_fee_cents")
    contract = fx.read_contract(api, world["contract"]["id"])
    A.assert_money_cents(contract["committed_fee_cents"], 500000,
                         "committed_fee_cents")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    assert fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"] == 0
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 0
    A.assert_money_cents(plan["localization_cost_cents"], 32508,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")


def test_the_released_interval_frees_a_window_that_was_refused_before(api):
    """The cancelled booking no longer occupies the booth.

    "A new booking is rejected with `ERR_BOOTH_WINDOW_CONFLICT` when there
    exists any other session on the same booth whose `status` is `SCHEDULED`,
    `IN_PROGRESS` or `RECORDED` and whose own half-open occupied interval
    intersects the new one."

    "`CANCELLED` sessions are excluded from the scan entirely."

    An 11:00-12:00 booking collides with the recorded session and is refused;
    once that session is cancelled the same booking is accepted and leaves 60
    minutes plus the thirty-minute buffer reserved on the booth.

    Design: Difficulty/transitive_cascade/voice_session_cancel_reverses_five_downstream_effects
    """
    world = _voiced_market_with_a_recorded_session(api)
    rebooking = f.voice_session_payload(
        world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc="2026-09-10T11:00:00Z",
        end_utc="2026-09-10T12:00:00Z", planned_line_count=30,
    )
    validate_error(api.create_voice_session(rebooking, users.PRODUCER),
                   E.ERR_BOOTH_WINDOW_CONFLICT)

    fx.cancel_session(api, world["session"]["id"])

    accepted = validate_success(
        api.create_voice_session(rebooking, users.PRODUCER), expected_status=201
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["duration_minutes"] == 60
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 90

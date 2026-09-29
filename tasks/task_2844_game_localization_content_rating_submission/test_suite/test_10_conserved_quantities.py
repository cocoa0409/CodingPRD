"""The two conserved quantities: committed money and reserved booth minutes."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# One MENU key of 125 source characters at a 96 per cent match is 0.10 effort
# units, so the FULL_VOICE text component is round_half_up(0.10 * 4200 * 1.80).
_TEXT_ONLY_COST_CENTS = 756
_BUYOUT_CENTS = 750000
_LINE_FEE_CENTS = 15400            # 88 recorded lines at 175 cents
_PEAK_COMMITTED_CENTS = 765400
_PEAK_COST_CENTS = 16156


def _voiced_market_with_a_scheduled_session(api):
    """A DE FULL_VOICE market, Dora under a 750,000-cent buyout, one booking."""
    world = fx.build_market(api, title_code="NOVA-28", name="Nova Drift 28",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=9000000,
                            required_voice_line_count=0,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-J",
                            turnaround_buffer_minutes=30,
                            talent_name="Dora Vogt", buyout_fee_cents=_BUYOUT_CENTS,
                            per_line_rate_cents=175, media_scope="ALL_MEDIA",
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["session"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc="2026-09-10T09:00:00Z",
        end_utc="2026-09-10T12:00:00Z", planned_line_count=88,
    )
    return world


def test_completing_the_session_books_the_line_fee_into_both_derived_ledgers(api):
    """The peak values the reversal will have to undo.

    "A contract's `committed_fee_cents` is its `buyout_fee_cents` plus the sum,
    over every recording session booked against this contract whose `status` is
    `RECORDED`, of that session's `recorded_line_count` multiplied by the
    contract's `per_line_rate_cents`."

    "Completion stores `recorded_line_count`, sets `line_fee_cents` to
    `recorded_line_count` multiplied by the contract's `per_line_rate_cents`,
    recomputes the contract's `committed_fee_cents`, recomputes the market plan's
    `voice_recorded_line_count` together with its `localization_cost_cents` and
    `overage_cents`, and increments the `version` of the session, the contract and
    the market plan by 1 each."

    88 lines at 175 cents is 15,400, so the ledger climbs from 750,000 to 765,400
    and the market's cost from 756 to 16,156.

    Design: Difficulty/compensating_invariant/contract_committed_fee_returns_exactly_to_buyout_after_cancel
    """
    world = _voiced_market_with_a_scheduled_session(api)
    signed = fx.read_contract(api, world["contract"]["id"])
    A.assert_money_cents(signed["committed_fee_cents"], _BUYOUT_CENTS,
                         "committed_fee_cents")
    A.assert_money_cents(fx.read_plan(api, world["plan"]["id"])[
        "localization_cost_cents"], _TEXT_ONLY_COST_CENTS,
        "localization_cost_cents")

    recorded = fx.record_session_at_its_start(api, world["session"],
                                              world["talent"]["id"], 88)

    assert recorded["status"] == "RECORDED"
    assert recorded["recorded_line_count"] == 88
    A.assert_money_cents(recorded["line_fee_cents"], _LINE_FEE_CENTS,
                         "line_fee_cents")
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])[
        "committed_fee_cents"], _PEAK_COMMITTED_CENTS, "committed_fee_cents")
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 88
    A.assert_money_cents(plan["localization_cost_cents"], _PEAK_COST_CENTS,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")
    assert plan["status"] == "IN_LOCALIZATION"


def test_the_cancellation_returns_the_ledger_exactly_to_the_buyout(api):
    """No proration, no cancellation fee, no residual drift.

    "The money quantity is a talent contract's `committed_fee_cents`. Completing a
    recording session and then cancelling that same session must leave
    `committed_fee_cents` at exactly the value it held before completion."

    "Hop two, caused by hop one's fee reversal, recomputes the contract's
    `committed_fee_cents`, which drops back by exactly the reversed line fee."

    "The buyout term is present from the moment the contract is `SIGNED` and is
    never reversed."

    Design: Difficulty/compensating_invariant/contract_committed_fee_returns_exactly_to_buyout_after_cancel
    """
    world = _voiced_market_with_a_scheduled_session(api)
    fx.record_session_at_its_start(api, world["session"], world["talent"]["id"], 88)

    cancelled = validate_success(
        api.cancel_voice_session(world["session"]["id"], users.PRODUCER)
    )

    assert cancelled["status"] == "CANCELLED"
    A.assert_money_cents(cancelled["line_fee_cents"], 0, "line_fee_cents")
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])[
        "committed_fee_cents"], _BUYOUT_CENTS, "committed_fee_cents")
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 0
    A.assert_money_cents(plan["localization_cost_cents"], _TEXT_ONLY_COST_CENTS,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")
    assert plan["status"] == "IN_LOCALIZATION"


def test_a_second_cancellation_refuses_and_compensates_nothing_twice(api):
    """The compensation is applied once and only once.

    "A `LocalizationProducer` may cancel a session in `SCHEDULED`, `IN_PROGRESS`
    or `RECORDED`; an already-`CANCELLED` session refuses with
    `ERR_SESSION_STATE_INVALID`, and cancellation is forbidden once the owning
    market plan has reached `RELEASE_READY`."

    Design: Difficulty/compensating_invariant/contract_committed_fee_returns_exactly_to_buyout_after_cancel
    """
    world = _voiced_market_with_a_scheduled_session(api)
    fx.record_session_at_its_start(api, world["session"], world["talent"]["id"], 88)
    once = fx.cancel_session(api, world["session"]["id"])

    response = api.cancel_voice_session(world["session"]["id"], users.PRODUCER)

    validate_error(response, E.ERR_SESSION_STATE_INVALID, expected_status=409)
    after = fx.read_session(api, world["session"]["id"])
    assert after["status"] == "CANCELLED"
    A.assert_unchanged_row(after, once, "voice_session")
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])[
        "committed_fee_cents"], _BUYOUT_CENTS, "committed_fee_cents")
    A.assert_money_cents(fx.read_plan(api, world["plan"]["id"])[
        "localization_cost_cents"], _TEXT_ONLY_COST_CENTS,
        "localization_cost_cents")


_ERIK_BUYOUT_CENTS = 300000
_ERIK_WINDOW = ("2026-09-10T14:00:00Z", "2026-09-10T15:30:00Z")
_FRITZ_WINDOW = ("2026-09-10T15:00:00Z", "2026-09-10T16:00:00Z")


def _booth_holding_one_scheduled_session(api):
    """A 45-minute-buffer booth holding Erik's 90-minute booking, plus Fritz idle."""
    world = fx.build_market(api, title_code="NOVA-29", name="Nova Drift 29",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=9000000,
                            required_voice_line_count=0,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-K",
                            turnaround_buffer_minutes=45,
                            talent_name="Erik Baum",
                            buyout_fee_cents=_ERIK_BUYOUT_CENTS,
                            per_line_rate_cents=150,
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["fritz"] = fx.add_talent_with_contract(
        api, world, talent_name="Fritz Adler", territory_scope=["DE"],
        media_scope="IN_GAME_AND_TRAILER", buyout_fee_cents=320000,
        per_line_rate_cents=160,
    )
    world["session"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=_ERIK_WINDOW[0],
        end_utc=_ERIK_WINDOW[1], planned_line_count=60,
    )
    return world


def _fritz_booking(world):
    return f.voice_session_payload(
        world["plan"]["id"], world["fritz"]["talent"]["id"], world["booth"]["id"],
        world["fritz"]["contract"]["id"], start_utc=_FRITZ_WINDOW[0],
        end_utc=_FRITZ_WINDOW[1], planned_line_count=40,
    )


def test_a_refused_booking_consumes_none_of_the_booth_capacity(api):
    """The 45-minute buffer is on the books, and the refusal adds nothing to it.

    "Every session occupies its booth for a half-open interval that begins at
    `start_utc` and ends at `occupied_end_utc`, which is `end_utc` advanced by the
    booth's `turnaround_buffer_minutes`."

    "A new booking is rejected with `ERR_BOOTH_WINDOW_CONFLICT` when there exists
    any other session on the same booth whose `status` is `SCHEDULED`,
    `IN_PROGRESS` or `RECORDED` and whose own half-open occupied interval
    intersects the new one."

    Erik's 90-minute booking contributes 135 minutes and occupies the booth up to
    16:15, so Fritz's 15:00-16:00 request collides and leaves the total untouched.

    Design: Difficulty/compensating_invariant/booth_capacity_minutes_return_to_zero_and_free_the_refused_booking
    """
    world = _booth_holding_one_scheduled_session(api)
    assert world["session"]["duration_minutes"] == 90
    A.assert_instant_equals(world["session"]["occupied_end_utc"],
                            "2026-09-10T16:15:00Z", "occupied_end_utc")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 135

    response = api.create_voice_session(_fritz_booking(world), users.PRODUCER)

    validate_error(response, E.ERR_BOOTH_WINDOW_CONFLICT, expected_status=409)
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 135
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])[
        "committed_fee_cents"], _ERIK_BUYOUT_CENTS, "committed_fee_cents")


def test_cancelling_the_scheduled_booking_returns_the_minutes_and_frees_the_window(api):
    """Capacity is conserved, and the proof is behavioural.

    "The capacity quantity is a booth's `reserved_minutes_total`. Booking a
    session and then cancelling that same session must return
    `reserved_minutes_total` to exactly its pre-booking value, and the booth
    interval must be released so a booking that previously collided now succeeds."

    "Sessions in `SCHEDULED`, `IN_PROGRESS` or `CANCELLED` contribute exactly
    zero."

    The booth returns to zero reserved minutes — not 45 and not 90 — the
    previously refused booking is then accepted, and Erik's ledger never moved,
    because a `SCHEDULED` session books no line fee.

    Design: Difficulty/compensating_invariant/booth_capacity_minutes_return_to_zero_and_free_the_refused_booking
    """
    world = _booth_holding_one_scheduled_session(api)
    booking = _fritz_booking(world)
    validate_error(api.create_voice_session(booking, users.PRODUCER),
                   E.ERR_BOOTH_WINDOW_CONFLICT)

    cancelled = fx.cancel_session(api, world["session"]["id"])

    assert cancelled["status"] == "CANCELLED"
    A.assert_money_cents(cancelled["line_fee_cents"], 0, "line_fee_cents")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])[
        "committed_fee_cents"], _ERIK_BUYOUT_CENTS, "committed_fee_cents")

    freed = validate_success(api.create_voice_session(booking, users.PRODUCER),
                             expected_status=201)
    assert freed["status"] == "SCHEDULED"
    assert freed["duration_minutes"] == 60
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 105

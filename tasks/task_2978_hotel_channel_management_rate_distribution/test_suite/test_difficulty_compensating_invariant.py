"""The two conserved quantities of the distribution contract.

Section 2.9 names exactly two conservation identities and demands that both hold
after every event that could disturb them. For an inventory day the overbooking
ceiling always equals held units plus committed units plus shared pool units, so
an allotment draw, a pool draw, a cancellation, a release and a recall may each
move a unit along a different edge but may never create or destroy one. For a
channel ledger gross revenue always equals net revenue plus accrued commission,
and a cancellation restores the money exactly - with no residue and no drift -
while `bookings_count` and `cancellations_count` are monotonic counters that are
never reversed. These tests walk those sequences and re-assert the identity at
every hop.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    REVENUE_DIRECTOR_HEADERS,
    REVENUE_MANAGER_HEADERS,
    assert_channel_ledger,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_nightly_breakdown,
    assert_performance,
    assert_reservation_totals,
    assert_version,
)
from test_helpers import factories, fixtures

# ── The canonical world these scenarios lean on ────────────────────────────

# Property HTL-SFO allows 1000 basis points of overbooking and room type KING has
# ten physical rooms, so the nightly ceiling is 10 + floor(10 * 1000 / 10000) = 11.
CAPACITY = fixtures.KING_CAPACITY
CEILING = fixtures.KING_CEILING

STAY_1 = fixtures.STAY_DATE            # 2026-09-10
STAY_2 = fixtures.STAY_DATE_2          # 2026-09-11
STAY_3 = fixtures.STAY_DATE_3          # 2026-09-12
LATE_STAY = fixtures.date_offset(fixtures.STAY_DATE, 10)  # 2026-09-20

# The served market of the canonical OTA. Its geo_market_codes list is non-empty,
# so every booking and quote against it must name one of its markets.
OTA_MARKET = fixtures.OTA_GEO_MARKET

# A window of exactly mix_window_days days, which the analytics reads accept.
WINDOW_START = "2026-09-01"
WINDOW_END = "2026-09-30"


# ── Module-local composition over the shared helpers ───────────────────────


def _day(api: Any, inventory_day_id: str) -> Dict[str, Any]:
    """One inventory day, read back at a pinned 200."""
    return validate_success(api.get_inventory_day(inventory_day_id, REVENUE_MANAGER_HEADERS))


def _allocation(api: Any, allocation_id: str) -> Dict[str, Any]:
    return validate_success(api.get_allocation(allocation_id, REVENUE_MANAGER_HEADERS))


def _channel(api: Any, channel_id: str) -> Dict[str, Any]:
    """The single-channel read, which is where the lifetime ledger is inspected."""
    return validate_success(api.get_channel(channel_id, REVENUE_MANAGER_HEADERS))


def _book(
    api: Any,
    channel_id: str,
    rate_plan_id: str,
    room_type_id: str,
    arrival_date: str,
    nights: int = 1,
    **guest: Any,
) -> Dict[str, Any]:
    """Book a stay as the revenue manager; a creation returns 201."""
    payload = factories.reservation_payload(
        channel_id=channel_id,
        rate_plan_id=rate_plan_id,
        room_type_id=room_type_id,
        arrival_date=arrival_date,
        nights=nights,
        **guest,
    )
    return validate_success(api.create_reservation(payload, REVENUE_MANAGER_HEADERS), 201)


def _cancel(api: Any, reservation_id: str) -> Dict[str, Any]:
    return validate_success(api.cancel_reservation(reservation_id, REVENUE_MANAGER_HEADERS))


def _release(api: Any, allocation_id: str) -> Dict[str, Any]:
    return validate_success(api.release_allocation(allocation_id, REVENUE_MANAGER_HEADERS))


def _ledger(
    gross: int, commission: int, net: int, room_nights: int, bookings: int, cancellations: int
) -> Dict[str, int]:
    """A full expected ledger, including the alert counter cancellation never touches."""
    return {
        "gross_revenue_cents": gross,
        "commission_accrued_cents": commission,
        "net_revenue_cents": net,
        "room_nights_sold": room_nights,
        "bookings_count": bookings,
        "cancellations_count": cancellations,
        "mismatch_alert_count": 0,
    }


def _guard_restrictions(api: Any, room_type_id: str) -> List[Dict[str, Any]]:
    """Every automatic overbooking guard the system placed on this room type."""
    rows = fixtures.list_restrictions(api, room_type_id=room_type_id)
    return [row for row in rows if row["origin"] == "AUTO_OVERBOOK_GUARD"]


# ── Unit conservation on the shared availability pool ──────────────────────


def test_unit_conservation_holds_after_every_hop_of_the_draw_and_reversal_cycle(api, world):
    """Five events move units along four different edges, and the ceiling still equals
    held plus committed plus shared pool after every one of them: an allotment draw
    moves a unit from held to committed, a pool draw moves one from the shared pool to
    committed, each cancellation reverses its own edge, and the release hands the whole
    remaining allotment back to the pool.

    Design: Difficulty/compensating_invariant/unit_conservation_survives_allotment_draw_pool_draw_cancellation_and_release
    """
    room_type_id = world["room_type_id"]
    plan_id = world["rate_plan_id"]
    ota_id = world["channel_id"]
    brand_id = fixtures.create_brand_channel(api, world["property_id"])["channel"]["id"]
    day_id = fixtures.open_inventory_day(api, room_type_id, STAY_1)["id"]

    # Four of the eleven units are carved out for the OTA, so the pool holds 11 - 4 = 7.
    allocation = fixtures.create_allocation(api, room_type_id, ota_id, 4, STAY_1, STAY_1)
    versions = []

    start = _day(api, day_id)
    assert_inventory_day(
        start,
        capacity=CAPACITY,
        ceiling=CEILING,
        allocated=4,
        committed=0,
        shared=7,
        pooled_state="OPEN",
    )
    assert _allocation(api, allocation["id"])["consumed_units"] == 0
    versions.append(start["version"])

    # The OTA holds an OPEN allotment with an unconsumed unit on this night, so its
    # booking draws from the allotment: held 4 -> 3, committed 0 -> 1, pool untouched.
    ota_reservation = _book(
        api, ota_id, plan_id, room_type_id, STAY_1, geo_market_code=OTA_MARKET
    )
    after_allotment_draw = _day(api, day_id)
    assert_inventory_day(
        after_allotment_draw, allocated=3, committed=1, shared=7, pooled_state="OPEN"
    )
    assert_fields(
        _allocation(api, allocation["id"]),
        {"consumed_units": 1, "allocation_state": "OPEN"},
        entity_name="allotment",
    )
    versions.append(after_allotment_draw["version"])

    # The brand channel holds no allotment, so its booking draws from the shared pool:
    # pool 7 -> 6, committed 1 -> 2, held untouched at 3.
    brand_reservation = _book(api, brand_id, plan_id, room_type_id, STAY_1)
    after_pool_draw = _day(api, day_id)
    assert_inventory_day(after_pool_draw, allocated=3, committed=2, shared=6, pooled_state="OPEN")
    assert _allocation(api, allocation["id"])["consumed_units"] == 1
    versions.append(after_pool_draw["version"])

    # Cancelling the pool booking reverses the pool edge only.
    _cancel(api, brand_reservation["id"])
    after_pool_reversal = _day(api, day_id)
    assert_inventory_day(
        after_pool_reversal, allocated=3, committed=1, shared=7, pooled_state="OPEN"
    )
    assert _allocation(api, allocation["id"])["consumed_units"] == 1
    versions.append(after_pool_reversal["version"])

    # Cancelling the allotment booking reverses the allotment edge, and the day is back
    # at its start numbers with no drift.
    _cancel(api, ota_reservation["id"])
    after_allotment_reversal = _day(api, day_id)
    assert_inventory_day(
        after_allotment_reversal,
        allocated=4,
        committed=0,
        shared=7,
        pooled_state="OPEN",
    )
    assert_fields(
        _allocation(api, allocation["id"]),
        {"consumed_units": 0, "allocation_state": "OPEN"},
        entity_name="allotment",
    )
    versions.append(after_allotment_reversal["version"])

    # The release moves the whole remaining block out of the held sum: 11 == 0 + 0 + 11.
    released = _release(api, allocation["id"])
    assert_fields(released, {"allocation_state": "RELEASED"}, entity_name="allotment")
    after_release = _day(api, day_id)
    assert_inventory_day(
        after_release,
        allocated=0,
        committed=0,
        shared=CEILING,
        pooled_state="OPEN",
    )
    versions.append(after_release["version"])

    # The day's own version is a monotonic counter: every recompute moves it forward and
    # no compensation ever winds it back.
    assert versions == sorted(versions), f"inventory day version should never fall: {versions}"

    for reservation_id in (ota_reservation["id"], brand_reservation["id"]):
        cancelled = validate_success(api.get_reservation(reservation_id, REVENUE_MANAGER_HEADERS))
        assert cancelled["reservation_state"] == "CANCELLED", (
            f"reservation {reservation_id} should be CANCELLED, got {cancelled['reservation_state']}"
        )
        assert_instant_equals(
            cancelled["cancelled_at"], fixtures.FIXTURE_CLOCK, "reservation.cancelled_at"
        )

    # The night never went OVERSOLD, so the system placed no automatic stop-sell guard.
    assert _guard_restrictions(api, room_type_id) == [], (
        "no AUTO_OVERBOOK_GUARD restriction should exist for a night that never oversold"
    )


def test_releasing_a_partly_consumed_allotment_frees_only_its_unconsumed_units(api, world):
    """A release is the compensating operation for a carve-out, and it compensates only
    what is still held: the unconsumed units return to the shared pool while the unit a
    confirmed booking already consumed stays committed, so the ceiling identity holds
    across the release and the day's version never falls.

    Design: Difficulty/compensating_invariant/unit_conservation_survives_allotment_draw_pool_draw_cancellation_and_release
    """
    room_type_id = world["room_type_id"]
    plan_id = world["rate_plan_id"]
    ota_id = world["channel_id"]
    day_id = fixtures.open_inventory_day(api, room_type_id, STAY_1)["id"]
    allocation = fixtures.create_allocation(api, room_type_id, ota_id, 4, STAY_1, STAY_1)

    reservation = _book(api, ota_id, plan_id, room_type_id, STAY_1, geo_market_code=OTA_MARKET)
    before = _day(api, day_id)
    # One of the four held units has been consumed: 11 == 3 + 1 + 7.
    assert_inventory_day(before, allocated=3, committed=1, shared=7, pooled_state="OPEN")

    released = _release(api, allocation["id"])
    assert_fields(
        released,
        {"allocation_state": "RELEASED", "allocated_units": 4, "consumed_units": 1},
        entity_name="allotment",
    )
    assert released["recalled_at"] is None, "a release should not set recalled_at"
    assert released["superseded_at"] is None, "a release should not set superseded_at"

    after = _day(api, day_id)
    # The three unconsumed units join the pool: 7 + 3 = 10, and 11 == 0 + 1 + 10.
    assert_inventory_day(
        after, allocated=0, committed=1, shared=10, pooled_state="OPEN"
    )

    # What the release must leave alone: the committed unit, the live reservation and the
    # channel's monotonic booking counter.
    assert after["committed_units"] == before["committed_units"], (
        "a release must not lower committed_units"
    )
    still_confirmed = validate_success(api.get_reservation(reservation["id"], REVENUE_MANAGER_HEADERS))
    assert still_confirmed["reservation_state"] == "CONFIRMED", (
        "releasing an allotment must not cancel the booking that consumed it"
    )
    assert_channel_ledger(_channel(api, ota_id), {"bookings_count": 1, "cancellations_count": 0})
    assert after["version"] > before["version"], (
        f"the released day should have been recomputed, version stayed at {before['version']}"
    )


def test_reversing_the_draw_order_reaches_the_same_conserved_end_state(api, world):
    """The draw source is decided per booking from the state the booking finds, so taking
    the pool draw first and the allotment draw second walks through a different
    intermediate day - held 4 / committed 1 / pool 6 rather than held 3 / committed 1 /
    pool 7 - and still lands on exactly the same conserved end state.

    Design: Difficulty/compensating_invariant/unit_conservation_survives_allotment_draw_pool_draw_cancellation_and_release
    """
    room_type_id = world["room_type_id"]
    plan_id = world["rate_plan_id"]
    ota_id = world["channel_id"]
    brand_id = fixtures.create_brand_channel(api, world["property_id"])["channel"]["id"]
    day_id = fixtures.open_inventory_day(api, room_type_id, STAY_1)["id"]
    allocation = fixtures.create_allocation(api, room_type_id, ota_id, 4, STAY_1, STAY_1)

    # The pool draw goes first this time. The brand channel holds no allotment, and the
    # night is nowhere near physical capacity, so no overbooking override is consumed.
    brand_reservation = _book(api, brand_id, plan_id, room_type_id, STAY_1)
    intermediate = _day(api, day_id)
    assert_inventory_day(
        intermediate, allocated=4, committed=1, shared=6, pooled_state="OPEN"
    )
    assert _allocation(api, allocation["id"])["consumed_units"] == 0, (
        "a pool draw on another channel must not consume the OTA's allotment"
    )
    assert intermediate["overbooking_ceiling_units"] == CEILING

    # The allotment draw follows: held 4 -> 3, committed 1 -> 2, the pool untouched at 6.
    ota_reservation = _book(
        api, ota_id, plan_id, room_type_id, STAY_1, geo_market_code=OTA_MARKET
    )
    end_state = _day(api, day_id)
    assert_inventory_day(end_state, allocated=3, committed=2, shared=6, pooled_state="OPEN")
    assert_fields(
        _allocation(api, allocation["id"]),
        {"consumed_units": 1, "allocation_state": "OPEN"},
        entity_name="allotment",
    )

    # Unwinding in the same reversed order returns the day to its start numbers.
    _cancel(api, ota_reservation["id"])
    assert_inventory_day(
        _day(api, day_id), allocated=4, committed=1, shared=6, pooled_state="OPEN"
    )
    _cancel(api, brand_reservation["id"])
    assert_inventory_day(
        _day(api, day_id), allocated=4, committed=0, shared=7, pooled_state="OPEN"
    )
    assert _allocation(api, allocation["id"])["consumed_units"] == 0
    assert _guard_restrictions(api, room_type_id) == [], (
        "no AUTO_OVERBOOK_GUARD restriction should exist for a night that never oversold"
    )


def test_a_recall_returns_held_units_to_the_pool_exactly_as_a_release_does(api, world):
    """A release and a suspension-driven recall are different routes out of a carve-out -
    one operator-driven and one cascaded from connectivity health - yet each hands back
    exactly its own held units and leaves the ceiling identity intact, so two blocks
    removed by the two different routes leave the whole ceiling in the shared pool.

    Design: Difficulty/compensating_invariant/unit_conservation_survives_allotment_draw_pool_draw_cancellation_and_release
    """
    room_type_id = world["room_type_id"]
    ota_id = world["channel_id"]
    brand = fixtures.create_brand_channel(api, world["property_id"])
    brand_id = brand["channel"]["id"]
    brand_connection_id = brand["connection"]["id"]
    day_id = fixtures.open_inventory_day(api, room_type_id, STAY_1)["id"]

    # Two overlapping carve-outs are legal while their aggregate stays inside the
    # ceiling: 4 + 3 + 0 committed = 7, which is at or below 11.
    ota_allocation = fixtures.create_allocation(api, room_type_id, ota_id, 4, STAY_1, STAY_1)
    brand_allocation = fixtures.create_allocation(api, room_type_id, brand_id, 3, STAY_1, STAY_1)
    assert_inventory_day(
        _day(api, day_id), allocated=7, committed=0, shared=4, pooled_state="OPEN"
    )

    # Route one: the operator releases the OTA's four units back into the pool.
    released = _release(api, ota_allocation["id"])
    assert_fields(released, {"allocation_state": "RELEASED"}, entity_name="released allotment")
    assert released["recalled_at"] is None, "a release should not set recalled_at"
    after_release = _day(api, day_id)
    assert_inventory_day(
        after_release, allocated=3, committed=0, shared=8, pooled_state="OPEN"
    )

    # Route two: three consecutive failure events suspend the brand connection, which
    # recalls the allotment it held and recomputes the day exactly as a release does.
    suspended = fixtures.suspend_connection(api, brand_connection_id)
    assert_fields(
        suspended,
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        entity_name="connection",
    )
    recalled = _allocation(api, brand_allocation["id"])
    assert_fields(recalled, {"allocation_state": "RECALLED"}, entity_name="recalled allotment")
    assert_instant_equals(recalled["recalled_at"], fixtures.FIXTURE_CLOCK, "allotment.recalled_at")

    after_recall = _day(api, day_id)
    assert_inventory_day(
        after_recall, allocated=0, committed=0, shared=CEILING, pooled_state="OPEN"
    )
    # Each compensation moved exactly the units it held: 4 + 3 = 7 = 11 - 4.
    assert after_release["shared_pool_units"] - 4 == 4, (
        "the release should have raised the pool by exactly the four units it held"
    )
    assert after_recall["shared_pool_units"] - after_release["shared_pool_units"] == 3, (
        "the recall should have raised the pool by exactly the three units it held"
    )
    assert _guard_restrictions(api, room_type_id) == [], (
        "no AUTO_OVERBOOK_GUARD restriction should exist for a night that never oversold"
    )


# ── Money conservation on the channel ledger ───────────────────────────────


def _seed_stacked_promotions(api, rate_plan_id: str) -> None:
    """One member rate over the whole month and one geo offer over the first two nights.

    The member offer takes 10% off the running amount and the geo offer then subtracts a
    flat 1000 cents, so nights the geo window covers price differently from nights it
    does not - which is what makes the per-night commission rounding observable.
    """
    fixtures.create_approved_promotion(
        api,
        rate_plan_id,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    fixtures.create_approved_promotion(
        api,
        rate_plan_id,
        start_date=STAY_1,
        end_date=STAY_2,
        code="GEO10USD",
        promo_kind="GEO_OFFER",
        discount_kind="AMOUNT",
        discount_amount_cents=1000,
        geo_market_codes=[OTA_MARKET],
    )


def _performance(api: Any, channel_id: str) -> Dict[str, Any]:
    """The stay-basis performance read over a window exactly mix_window_days long."""
    params = factories.performance_params(WINDOW_START, WINDOW_END, basis="STAY")
    return validate_success(
        api.get_channel_performance(channel_id, REVENUE_DIRECTOR_HEADERS, params)
    )


# Reservation A: nights 2026-09-10, 2026-09-11 and 2026-09-12 on the member rate from
# US-CA. Base 25000 -> 25000 x 9000 / 10000 = 22500; the geo offer covers the first two
# nights only, so those pay 22500 - 1000 = 21500 and the third pays 22500. The total
# discount of 3500 on the first two nights is under the floored cap of 7500, the channel
# adjustment is 0 bp, and 21500 and 22500 both sit inside the 18000 / 40000 band.
A_NIGHTS = [
    # 21500 x 1750 / 10000 = 3762.5 -> 3763 half up
    {"stay_date": STAY_1, "sell_rate_cents": 21500, "commissionable_cents": 21500, "commission_cents": 3763},
    {"stay_date": STAY_2, "sell_rate_cents": 21500, "commissionable_cents": 21500, "commission_cents": 3763},
    # 22500 x 1750 / 10000 = 3937.5 -> 3938 half up
    {"stay_date": STAY_3, "sell_rate_cents": 22500, "commissionable_cents": 22500, "commission_cents": 3938},
]
A_GROSS = 65500          # 21500 + 21500 + 22500
A_COMMISSION = 11464     # 3763 + 3763 + 3938, each rounded per night before summing
A_NET = 54036            # 65500 - 11464
A_LOYALTY = 2161         # 50000 <= 65500 < 70000 -> 400 bp; 54036 x 400 / 10000 = 2161.44 -> 2161

# Reservation B: one night on 2026-09-20. The member offer still covers it, the geo offer
# does not, so it prices at 22500 with a commission of 3938 and no loyalty tier.
B_GROSS = 22500
B_COMMISSION = 3938
B_NET = 18562            # 22500 - 3938
B_LOYALTY = 0            # 22500 < 50000 -> tier 0 bp


def test_money_conservation_holds_after_every_hop_of_the_booking_and_cancellation_cycle(api, world):
    """Gross always equals net plus accrued commission on the channel's lifetime ledger,
    through an empty ledger, two bookings priced night by night, and both cancellations -
    and the two counters part company at the reversal, because `cancellations_count`
    climbs while `bookings_count` counts every reservation ever taken and never falls.

    Design: Difficulty/compensating_invariant/money_conservation_survives_cancellation_while_counters_stay_monotonic
    """
    room_type_id = world["room_type_id"]
    plan_id = world["rate_plan_id"]
    ota_id = world["channel_id"]
    fixtures.open_inventory_days(api, room_type_id, [STAY_1, STAY_2, STAY_3, LATE_STAY])
    _seed_stacked_promotions(api, plan_id)

    assert_channel_ledger(_channel(api, ota_id), _ledger(0, 0, 0, 0, 0, 0))

    reservation_a = _book(
        api, ota_id, plan_id, room_type_id, STAY_1, nights=3,
        member_flag=True, geo_market_code=OTA_MARKET,
    )
    assert_nightly_breakdown(reservation_a, A_NIGHTS)
    assert_reservation_totals(
        reservation_a, gross=A_GROSS, commission=A_COMMISSION, net=A_NET, loyalty_credit=A_LOYALTY
    )
    assert_channel_ledger(
        _channel(api, ota_id), _ledger(A_GROSS, A_COMMISSION, A_NET, 3, 1, 0)
    )

    reservation_b = _book(
        api, ota_id, plan_id, room_type_id, LATE_STAY,
        member_flag=True, geo_market_code=OTA_MARKET,
    )
    assert_nightly_breakdown(
        reservation_b,
        [{"stay_date": LATE_STAY, "sell_rate_cents": B_GROSS, "commission_cents": B_COMMISSION}],
    )
    assert_reservation_totals(
        reservation_b, gross=B_GROSS, commission=B_COMMISSION, net=B_NET, loyalty_credit=B_LOYALTY
    )
    # 65500 + 22500 = 88000, 11464 + 3938 = 15402, 54036 + 18562 = 72598, 3 + 1 = 4 nights.
    assert_channel_ledger(
        _channel(api, ota_id),
        _ledger(A_GROSS + B_GROSS, A_COMMISSION + B_COMMISSION, A_NET + B_NET, 4, 2, 0),
    )

    # Reversing the later booking leaves exactly the earlier one's money behind.
    _cancel(api, reservation_b["id"])
    assert_channel_ledger(
        _channel(api, ota_id), _ledger(A_GROSS, A_COMMISSION, A_NET, 3, 2, 1)
    )

    # Reversing the first one empties the money entirely, with no residual cent.
    _cancel(api, reservation_a["id"])
    assert_channel_ledger(_channel(api, ota_id), _ledger(0, 0, 0, 0, 2, 2))

    # The loyalty credit is terminal: it never entered the ledger, so nothing had to
    # reverse it, and the ledger reaches exactly zero rather than 2161 short of it.
    final = _channel(api, ota_id)
    assert final["bookings_count"] - final["cancellations_count"] == 0, (
        "bookings minus cancellations is the count of live bookings, which is now zero"
    )


def test_cancelling_reverses_the_money_exactly_while_the_bookings_counter_never_falls(api, world):
    """The cancellation is the compensating operation, and what it must leave alone is as
    load-bearing as what it reverses: the money and the room nights fall back to where
    they started, `cancellations_count` rises by one, and `bookings_count` - a monotonic
    counter of every reservation ever taken - stays exactly where it was.

    Design: Difficulty/compensating_invariant/money_conservation_survives_cancellation_while_counters_stay_monotonic
    """
    room_type_id = world["room_type_id"]
    plan_id = world["rate_plan_id"]
    ota_id = world["channel_id"]
    fixtures.open_inventory_days(api, room_type_id, [STAY_1, STAY_2, STAY_3])
    _seed_stacked_promotions(api, plan_id)

    reservation = _book(
        api, ota_id, plan_id, room_type_id, STAY_1, nights=3,
        member_flag=True, geo_market_code=OTA_MARKET,
    )
    assert_version(reservation, 1, entity_name="reservation")
    before = _channel(api, ota_id)
    assert_channel_ledger(before, _ledger(A_GROSS, A_COMMISSION, A_NET, 3, 1, 0))

    cancelled = _cancel(api, reservation["id"])
    assert_fields(
        cancelled, {"reservation_state": "CANCELLED"}, entity_name="reservation"
    )
    assert_instant_equals(
        cancelled["cancelled_at"], fixtures.FIXTURE_CLOCK, "reservation.cancelled_at"
    )
    assert_version(cancelled, 2, entity_name="cancelled reservation")

    # The reservation keeps its own priced totals; only the ledger unwinds.
    assert_reservation_totals(
        cancelled, gross=A_GROSS, commission=A_COMMISSION, net=A_NET, loyalty_credit=A_LOYALTY
    )

    after = _channel(api, ota_id)
    # Reversed exactly: every figure back to zero, not merely close to it.
    assert_channel_ledger(after, _ledger(0, 0, 0, 0, 1, 1))
    assert after["bookings_count"] == before["bookings_count"], (
        "bookings_count counts every reservation ever taken and must not be reversed"
    )
    assert after["cancellations_count"] == before["cancellations_count"] + 1, (
        "cancellations_count should have risen by exactly one"
    )
    assert after["mismatch_alert_count"] == 0, (
        "a cancellation has nothing to do with rate parity alerts"
    )
    assert after["version"] > before["version"], (
        "the channel row should have been touched by the reversal"
    )


def test_the_windowed_performance_read_unwinds_to_the_same_totals_as_the_ledger(api, world):
    """The performance read recomputes the same money from the surviving confirmed
    reservations rather than reading the stored ledger, so it is a second, independent
    route to the conserved totals: it agrees with the ledger after each booking and after
    each cancellation, and an emptied window reports zero with both ratios null.

    Design: Difficulty/compensating_invariant/money_conservation_survives_cancellation_while_counters_stay_monotonic
    """
    room_type_id = world["room_type_id"]
    plan_id = world["rate_plan_id"]
    ota_id = world["channel_id"]
    fixtures.open_inventory_days(api, room_type_id, [STAY_1, STAY_2, STAY_3, LATE_STAY])
    _seed_stacked_promotions(api, plan_id)

    reservation_a = _book(
        api, ota_id, plan_id, room_type_id, STAY_1, nights=3,
        member_flag=True, geo_market_code=OTA_MARKET,
    )
    # Every night of both stays falls inside 2026-09-01 through 2026-09-30, so the stay
    # basis sees all of the money. 54036 / 3 = 18012 exactly; 11464 x 10000 / 65500 =
    # 1750.2 -> 1750 half up.
    assert_performance(
        _performance(api, ota_id),
        {
            "channel_id": ota_id,
            "basis": "STAY",
            "window_start_date": WINDOW_START,
            "window_end_date": WINDOW_END,
            "gross_amount_cents": A_GROSS,
            "commission_amount_cents": A_COMMISSION,
            "net_amount_cents": A_NET,
            "room_nights": 3,
            "net_adr_cents": 18012,
            "commission_cost_ratio_bp": 1750,
            "health_score_bp": None,
        },
    )

    reservation_b = _book(
        api, ota_id, plan_id, room_type_id, LATE_STAY,
        member_flag=True, geo_market_code=OTA_MARKET,
    )
    # 72598 / 4 = 18149.5 -> 18150 half up, rounded once at the end and never per stay.
    assert_performance(
        _performance(api, ota_id),
        {
            "gross_amount_cents": A_GROSS + B_GROSS,
            "commission_amount_cents": A_COMMISSION + B_COMMISSION,
            "net_amount_cents": A_NET + B_NET,
            "room_nights": 4,
            "net_adr_cents": 18150,
            "commission_cost_ratio_bp": 1750,
        },
    )

    _cancel(api, reservation_b["id"])
    # A cancelled reservation leaves the window entirely, so the read falls back to A.
    after_first_reversal = _performance(api, ota_id)
    assert_performance(
        after_first_reversal,
        {
            "gross_amount_cents": A_GROSS,
            "commission_amount_cents": A_COMMISSION,
            "net_amount_cents": A_NET,
            "room_nights": 3,
            "net_adr_cents": 18012,
            "commission_cost_ratio_bp": 1750,
        },
    )
    ledger_after_first_reversal = _channel(api, ota_id)
    for read_field, ledger_field in (
        ("gross_amount_cents", "gross_revenue_cents"),
        ("commission_amount_cents", "commission_accrued_cents"),
        ("net_amount_cents", "net_revenue_cents"),
        ("room_nights", "room_nights_sold"),
    ):
        assert after_first_reversal[read_field] == ledger_after_first_reversal[ledger_field], (
            f"performance {read_field} should agree with ledger {ledger_field}: "
            f"{after_first_reversal[read_field]} vs {ledger_after_first_reversal[ledger_field]}"
        )

    _cancel(api, reservation_a["id"])
    # An empty window: zero money, zero nights, and both derived ratios null rather than 0.
    assert_performance(
        _performance(api, ota_id),
        {
            "gross_amount_cents": 0,
            "commission_amount_cents": 0,
            "net_amount_cents": 0,
            "room_nights": 0,
            "net_adr_cents": None,
            "commission_cost_ratio_bp": None,
        },
    )
    assert_channel_ledger(_channel(api, ota_id), _ledger(0, 0, 0, 0, 2, 2))

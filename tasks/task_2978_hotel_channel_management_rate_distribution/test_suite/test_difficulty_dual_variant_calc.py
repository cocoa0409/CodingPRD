"""Analytics reads whose two declared variants answer differently on one data set.

Two reads in the contract take an optional variant selector and deliberately
return different numbers from identical stored data: the channel performance
read chooses between the stay basis and the booked basis, and the booking pace
read chooses between the rolling baseline and the same-time-last-year baseline.
Each test below pins one variant's own arithmetic and, where the contract makes
the two comparable, the divergence between them.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    REVENUE_MANAGER_HEADERS,
    assert_pace,
    assert_performance,
    assert_reservation_totals,
    factories,
    fixtures,
)

# ── The two-reservation performance world ──────────────────────────────────

# The analytics window both bases are asked for.
WINDOW_START = "2026-09-01"
WINDOW_END = "2026-09-11"

# Reservation A: three nights from 2026-09-10, booked while the clock sits at
# 2026-08-25, so its created_at date is outside the window above.
RES_A_ARRIVAL = "2026-09-10"
RES_A_NIGHTS = 3

# Reservation B: one night on 2026-09-20, booked after the clock moves to
# 2026-09-03, so its created_at date is inside the window and its stay is not.
BOOKED_CLOCK_DAY = "2026-09-03"
RES_B_ARRIVAL = "2026-09-20"


def _book(
    api,
    channel_id: str,
    rate_plan_id: str,
    room_type_id: str,
    arrival_date: str,
    nights: int,
):
    """Book one member stay from the served geo market and pin the 201."""
    payload = factories.reservation_payload(
        channel_id=channel_id,
        rate_plan_id=rate_plan_id,
        room_type_id=room_type_id,
        arrival_date=arrival_date,
        nights=nights,
        member_flag=True,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    return validate_success(api.create_reservation(payload, REVENUE_MANAGER_HEADERS), 201)


def _two_reservation_world(api, world):
    """One channel, one plan, two approved offers and two confirmed stays.

    The plan is the canonical public plan at 25000. A member percent offer runs
    the whole of September and a geo amount offer covers only 2026-09-10 and
    2026-09-11, so the three nights of the first stay price at 21500, 21500 and
    22500. The second stay is booked after the clock moves, which is what makes
    the two performance bases select different rows.
    """
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-10",
        end_date="2026-09-11",
        code="GEO10USD",
        promo_kind="GEO_OFFER",
        discount_kind="AMOUNT",
        discount_amount_cents=1000,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    fixtures.open_inventory_days(
        api,
        world["room_type_id"],
        ["2026-09-10", "2026-09-11", "2026-09-12", RES_B_ARRIVAL],
    )
    reservation_a = _book(
        api,
        world["channel_id"],
        world["rate_plan_id"],
        world["room_type_id"],
        RES_A_ARRIVAL,
        RES_A_NIGHTS,
    )
    fixtures.set_clock(api, fixtures.instant(BOOKED_CLOCK_DAY))
    reservation_b = _book(
        api,
        world["channel_id"],
        world["rate_plan_id"],
        world["room_type_id"],
        RES_B_ARRIVAL,
        1,
    )
    return {"reservation_a": reservation_a, "reservation_b": reservation_b}


def _performance(api, channel_id: str, basis: str):
    """The windowed performance read for one basis, with its 200 pinned."""
    query = factories.performance_params(WINDOW_START, WINDOW_END, basis=basis)
    response = api.get_channel_performance(channel_id, REVENUE_MANAGER_HEADERS, query)
    return validate_success(response, 200)


def test_channel_performance_stay_basis_counts_only_the_in_window_nights(api, world):
    """On the stay basis a reservation contributes only the nights that fall inside
    the window, and its booking date is irrelevant: the three-night stay lends two
    of its nights, so net ADR is the once-rounded net over those two room nights.

    Design: Difficulty/dual_variant_calc/channel_net_adr_stay_basis_versus_booked_basis
    """
    rows = _two_reservation_world(api, world)

    # The whole stay: 21500 + 21500 + 22500 = 65500 gross, per-night commission
    # 3763 + 3763 + 3938 = 11464, net 54036.
    assert_reservation_totals(
        rows["reservation_a"], gross=65500, commission=11464, net=54036
    )

    stay = _performance(api, world["channel_id"], "STAY")
    # 2026-09-10 and 2026-09-11 are in the window, 2026-09-12 is not:
    # gross 21500 + 21500 = 43000, commission 3763 + 3763 = 7526, net 35474,
    # net ADR 35474 / 2 = 17737, ratio 7526 x 10000 / 43000 = 1750.
    assert_performance(
        stay,
        {
            "basis": "STAY",
            "window_start_date": WINDOW_START,
            "window_end_date": WINDOW_END,
            "room_nights": 2,
            "gross_amount_cents": 43000,
            "commission_amount_cents": 7526,
            "net_amount_cents": 35474,
            "net_adr_cents": 17737,
            "commission_cost_ratio_bp": 1750,
        },
    )
    # No distribution job has resolved on this channel, so the health ratio has
    # no denominator and is reported as null rather than as zero.
    assert stay["health_score_bp"] is None, (
        f"health_score_bp should be null with no resolved job, got {stay['health_score_bp']!r}"
    )

    # The stay basis leaves out the reservation booked inside the window because
    # its single night sits outside it; the booked basis picks that row instead,
    # and the same GET therefore answers 825 cents higher.
    booked = _performance(api, world["channel_id"], "BOOKED")
    assert booked["net_adr_cents"] == 18562, (
        f"booked-basis net_adr_cents should be 18562, got {booked['net_adr_cents']}"
    )
    assert booked["net_adr_cents"] - stay["net_adr_cents"] == 825, (
        "the two bases should diverge by 825 cents on identical data, got "
        f"{booked['net_adr_cents']} versus {stay['net_adr_cents']}"
    )


def test_channel_performance_booked_basis_counts_whole_reservations_created_in_window(
    api, world
):
    """On the booked basis a reservation contributes when the date part of its
    created_at falls inside the window, and then contributes every one of its
    nights, so the stay booked before the window drops out altogether.

    Design: Difficulty/dual_variant_calc/channel_net_adr_stay_basis_versus_booked_basis
    """
    rows = _two_reservation_world(api, world)

    # The later stay prices at 22500 for its single night: the September member
    # offer applies, the 2026-09-10..2026-09-11 geo offer does not.
    assert_reservation_totals(
        rows["reservation_b"], gross=22500, commission=3938, net=18562
    )

    booked = _performance(api, world["channel_id"], "BOOKED")
    # Only the reservation created on 2026-09-03 is selected, and all of it:
    # gross 22500, commission 3938, net 18562, net ADR 18562 / 1 = 18562,
    # ratio 3938 x 10000 / 22500 = 1750.2 rounded half up to 1750.
    assert_performance(
        booked,
        {
            "basis": "BOOKED",
            "window_start_date": WINDOW_START,
            "window_end_date": WINDOW_END,
            "room_nights": 1,
            "gross_amount_cents": 22500,
            "commission_amount_cents": 3938,
            "net_amount_cents": 18562,
            "net_adr_cents": 18562,
            "commission_cost_ratio_bp": 1750,
        },
    )
    assert booked["health_score_bp"] is None, (
        f"health_score_bp should be null with no resolved job, got {booked['health_score_bp']!r}"
    )

    # The three-night stay is excluded entirely rather than partially: were any
    # of it counted, the room-night total would exceed the one night above.
    assert booked["room_nights"] == 1, (
        "the booked basis should exclude the reservation created before the window, "
        f"got room_nights {booked['room_nights']}"
    )


# ── The booking pace world ─────────────────────────────────────────────────

# The future night whose pace is asked for, and the clock it is asked from.
TARGET_STAY_DATE = "2026-09-10"
PACE_AS_OF_DAY = "2026-09-03"
PACE_DAYS_OUT = 7

# The same-time-last-year date: the target less the 364-day offset, which lands
# on the same weekday one year back.
STLY_STAY_DATE = "2025-09-11"
STLY_BOOKED_CLOCK_DAY = "2025-09-04"

# Two nights inside the rolling baseline window 2026-09-03..2026-09-09, booked
# early enough to clear each of their own per-date cutoffs.
ROLLING_ARRIVAL = "2026-09-03"
ROLLING_BOOKED_CLOCK_DAY = "2026-08-25"


def _pace_world(api):
    """A room type carrying one night last year, two nights in the baseline
    window and one night on the target date, each booked at its own clock.

    The clock is walked forward three times because every on-the-books count is
    filtered by a cutoff on the reservation's own created_at date, so when a
    stay was booked is as load-bearing as which nights it occupies. No promotion
    exists, so every night prices at the plan's base amount.
    """
    fixtures.set_clock(api, fixtures.instant(STLY_BOOKED_CLOCK_DAY))
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    ota = fixtures.create_ota_channel(api, property_row["id"])
    rate_plan = fixtures.create_active_rate_plan(
        api,
        property_row["id"],
        code=fixtures.BAR_CODE,
        rate_class="PUBLIC",
        base_amount_cents=fixtures.BAR_BASE_CENTS,
        floor_amount_cents=fixtures.BAR_FLOOR_CENTS,
        ceiling_amount_cents=fixtures.BAR_CEILING_CENTS,
    )
    channel_id = ota["channel"]["id"]

    # Last year's single night, booked at its own cutoff date 2025-09-04, which
    # is 2025-09-11 less the seven days the target sits out.
    fixtures.open_inventory_day(api, room_type["id"], STLY_STAY_DATE)
    stly_reservation = _book(
        api, channel_id, rate_plan["id"], room_type["id"], STLY_STAY_DATE, 1
    )

    # This year's two baseline nights, booked on 2026-08-25 - before the
    # per-date cutoffs 2026-08-27 and 2026-08-28 that the two dates carry.
    fixtures.set_clock(api, fixtures.instant(ROLLING_BOOKED_CLOCK_DAY))
    fixtures.open_inventory_days(
        api, room_type["id"], [ROLLING_ARRIVAL, "2026-09-04", TARGET_STAY_DATE]
    )
    rolling_reservation = _book(
        api, channel_id, rate_plan["id"], room_type["id"], ROLLING_ARRIVAL, 2
    )

    # The target night, booked once the clock reaches the as-of date.
    fixtures.set_clock(api, fixtures.instant(PACE_AS_OF_DAY))
    target_reservation = _book(
        api, channel_id, rate_plan["id"], room_type["id"], TARGET_STAY_DATE, 1
    )
    return {
        "room_type_id": room_type["id"],
        "stly_reservation": stly_reservation,
        "rolling_reservation": rolling_reservation,
        "target_reservation": target_reservation,
    }


def _pace(api, room_type_id: str, baseline: str):
    """The pace read for one baseline variant, with its 200 pinned."""
    query = factories.pace_params(TARGET_STAY_DATE, baseline=baseline)
    return validate_success(api.get_pace(room_type_id, REVENUE_MANAGER_HEADERS, query), 200)


def test_booking_pace_rolling_baseline_divides_by_the_seven_day_total(api):
    """The rolling baseline sums on-the-books over the seven dates before the
    target, each measured at its own cutoff, and because that denominator is a
    seven-day total the numerator carries the seven-day multiplier.

    Design: Difficulty/dual_variant_calc/booking_pace_rolling_baseline_versus_stly_baseline
    """
    rows = _pace_world(api)

    rolling = _pace(api, rows["room_type_id"], "ROLLING")
    # 2026-09-03 and 2026-09-04 each hold one room night at their own cutoffs
    # and the other five baseline dates hold none, so the denominator is 2:
    # 1 x 7 x 10000 / 2 = 35000, which is above 11000 and therefore AHEAD.
    assert_pace(
        rolling,
        {
            "room_type_id": rows["room_type_id"],
            "target_stay_date": TARGET_STAY_DATE,
            "baseline": "ROLLING",
            "as_of_date": PACE_AS_OF_DAY,
            "days_out": PACE_DAYS_OUT,
            "target_room_nights": 1,
            "baseline_room_nights": 2,
            "pace_index_bp": 35000,
            "pace_state": "AHEAD",
        },
    )

    # The same target night against the other baseline: the numerator is
    # unchanged at one room night, yet the index and the verdict both move,
    # because only the denominator and the window multiplier differ.
    stly = _pace(api, rows["room_type_id"], "STLY")
    assert stly["target_room_nights"] == rolling["target_room_nights"], (
        "both variants should count the same target room nights, got "
        f"{stly['target_room_nights']} versus {rolling['target_room_nights']}"
    )
    assert stly["pace_index_bp"] == 10000, (
        f"the STLY index should be 10000, got {stly['pace_index_bp']}"
    )
    assert stly["pace_state"] == "ON_PACE", (
        f"the STLY verdict should be ON_PACE, got {stly['pace_state']!r}"
    )


def test_booking_pace_stly_baseline_divides_by_the_single_offset_date(api):
    """The same-time-last-year baseline is the single on-the-books count for the
    target less 364 days, measured at that date less days_out, and its index
    carries no window multiplier at all.

    Design: Difficulty/dual_variant_calc/booking_pace_rolling_baseline_versus_stly_baseline
    """
    rows = _pace_world(api)

    stly = _pace(api, rows["room_type_id"], "STLY")
    # 2025-09-11 holds one room night at cutoff 2025-09-04, so the denominator
    # is 1: 1 x 10000 / 1 = 10000, which lies inside the ON_PACE band whose
    # boundaries 9000 and 11000 are themselves ON_PACE.
    assert_pace(
        stly,
        {
            "room_type_id": rows["room_type_id"],
            "target_stay_date": TARGET_STAY_DATE,
            "baseline": "STLY",
            "as_of_date": PACE_AS_OF_DAY,
            "days_out": PACE_DAYS_OUT,
            "target_room_nights": 1,
            "baseline_room_nights": 1,
            "pace_index_bp": 10000,
            "pace_state": "ON_PACE",
        },
    )

    # Last year's night is the whole of this baseline, and this year's two
    # baseline-window nights contribute nothing to it: were they counted the
    # denominator would be 3 rather than 1.
    rolling = _pace(api, rows["room_type_id"], "ROLLING")
    assert rolling["baseline_room_nights"] == 2, (
        "the rolling baseline should hold this year's two nights, got "
        f"{rolling['baseline_room_nights']}"
    )
    assert stly["baseline_room_nights"] == 1, (
        "the STLY baseline should hold last year's single night, got "
        f"{stly['baseline_room_nights']}"
    )

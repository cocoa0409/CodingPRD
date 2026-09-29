"""Inclusive-versus-exclusive boundaries in the pool, surveillance and mix rules.

Three of this contract's numeric limits are inclusive on one side only: an
allotment sum exactly equal to the nightly overbooking ceiling is accepted, an
observed-rate delta exactly equal to the mismatch tolerance is still in sync, and
an analytics window exactly as long as the property's mix window is accepted.
Each test here sits one request exactly on such a boundary and one request a
single unit past it, and pins the derived consequence rather than the status
alone.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    REVENUE_MANAGER_HEADERS,
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_nightly_breakdown,
    assert_ranked_channel,
    assert_reservation_totals,
    assert_version,
    factories,
    fixtures,
)

# KING holds ten physical rooms at the property's 1000 bp allowance:
# 10 + floor(10 x 1000 / 10000) = 11 units of nightly ceiling.
CEILING_UNITS = fixtures.KING_CEILING

# The surveillance tolerance the canonical property declares.
TOLERANCE_CENTS = fixtures.PROPERTY_TOLERANCE_CENTS

# The distributed rate is promotion-free: resolved base 25000 at the OTA's
# default 0 bp adjustment, inside the 18000/40000 band, plus 0 inclusion.
DISTRIBUTED_RATE_CENTS = fixtures.BAR_BASE_CENTS

# The property's mix window is 30 days, so 2026-09-01 through 2026-09-30 is
# exactly 30 inclusive days and 2026-09-01 through 2026-10-01 is 31.
MIX_WINDOW_START = "2026-09-01"
MIX_WINDOW_END_AT_LIMIT = "2026-09-30"
MIX_WINDOW_END_ONE_DAY_PAST = "2026-10-01"


def _pool_with_six_held_and_two_committed(api: Any, world: Dict[str, Any]) -> str:
    """Three open nights, six units held for the OTA and two pool bookings.

    The middle night 2026-09-11 therefore carries allocated_units 6,
    committed_units 2 and shared_pool_units 11 - 6 - 2 = 3, which leaves exactly
    three units of headroom before the ceiling. The two bookings are made on the
    direct channel, which holds no allotment, so they draw from the shared pool
    and leave the OTA's held units unconsumed. Returns the direct channel's id.
    """
    fixtures.open_inventory_range(
        api, world["room_type_id"], fixtures.STAY_DATE, fixtures.STAY_DATE_3
    )
    fixtures.create_allocation(
        api,
        world["room_type_id"],
        world["channel_id"],
        6,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE_3,
    )
    brand = fixtures.create_brand_channel(api, world["property_id"])
    for _ in range(2):
        fixtures.create_reservation(
            api,
            brand["channel"]["id"],
            world["rate_plan_id"],
            world["room_type_id"],
            arrival_date=fixtures.STAY_DATE_2,
            nights=1,
        )
    day = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE_2)
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=CEILING_UNITS,
        allocated=6,
        committed=2,
        shared=3,
        pooled_state="OPEN",
    )
    return str(brand["channel"]["id"])


def test_allotment_summing_exactly_to_the_ceiling_is_accepted(api, world) -> None:
    """An aggregate sum exactly equal to the ceiling is accepted.

    The per-date aggregate check refuses only a sum strictly greater than the
    date's overbooking ceiling, so holding the last three free units on a night
    already carrying six held and two committed units — 6 + 2 + 3 = 11, exactly
    the ceiling — is admitted and empties the shared pool.

    Design: Difficulty/boundary_precision_check/allotment_exactly_at_overbooking_ceiling_is_accepted_one_more_unit_is_not
    """
    brand_channel_id = _pool_with_six_held_and_two_committed(api, world)

    payload = factories.allocation_payload(
        channel_id=brand_channel_id,
        allocated_units=3,
        start_date=fixtures.STAY_DATE_2,
        end_date=fixtures.STAY_DATE_2,
        expected_room_type_version=fixtures.room_type_version(api, world["room_type_id"]),
    )
    allocation = validate_success(
        api.create_allocation(world["room_type_id"], payload, REVENUE_MANAGER_HEADERS), 201
    )

    assert_common_fields(allocation, "allocation")
    assert_version(allocation, 1, "allocation")
    assert_fields(
        allocation,
        {
            "channel_id": brand_channel_id,
            "allocated_units": 3,
            "consumed_units": 0,
            "allocation_state": "OPEN",
            "start_date": fixtures.STAY_DATE_2,
            "end_date": fixtures.STAY_DATE_2,
            "superseded_at": None,
            "recalled_at": None,
        },
        entity_name="allocation",
    )
    middle = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE_2)
    assert_inventory_day(
        middle, ceiling=CEILING_UNITS, allocated=9, committed=2, shared=0, pooled_state="EXHAUSTED"
    )
    # The one-night allotment leaves the flanking nights of the OTA's block alone.
    for untouched in (fixtures.STAY_DATE, fixtures.STAY_DATE_3):
        day = fixtures.inventory_day_on(api, world["room_type_id"], untouched)
        assert_inventory_day(
            day, ceiling=CEILING_UNITS, allocated=6, committed=0, shared=5, pooled_state="OPEN"
        )


def test_allotment_one_unit_past_the_ceiling_is_refused(api, world) -> None:
    """One unit beyond the same boundary is refused with nothing applied.

    Asking for a fourth unit on that night makes the aggregate 6 + 2 + 4 = 12,
    strictly greater than the ceiling of 11, so the allotment is refused with
    ERR_ALLOCATION_EXCEEDS_CEILING and no room-type version is spent.

    Design: Difficulty/boundary_precision_check/allotment_exactly_at_overbooking_ceiling_is_accepted_one_more_unit_is_not
    """
    brand_channel_id = _pool_with_six_held_and_two_committed(api, world)
    version_before = fixtures.room_type_version(api, world["room_type_id"])

    payload = factories.allocation_payload(
        channel_id=brand_channel_id,
        allocated_units=4,
        start_date=fixtures.STAY_DATE_2,
        end_date=fixtures.STAY_DATE_2,
        expected_room_type_version=version_before,
    )
    response = api.create_allocation(world["room_type_id"], payload, REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.ALLOCATION_EXCEEDS_CEILING.value, 409)
    allocations = fixtures.list_allocations(api, room_type_id=world["room_type_id"])
    assert len(allocations) == 1, "a refused allotment must create no row"
    assert fixtures.room_type_version(api, world["room_type_id"]) == version_before, (
        "a refused allotment must not spend the room type's version"
    )
    middle = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE_2)
    assert_inventory_day(
        middle, ceiling=CEILING_UNITS, allocated=6, committed=2, shared=3, pooled_state="OPEN"
    )


def _mapping_with_a_distributed_rate(api: Any, world: Dict[str, Any]) -> str:
    """A verified mapping whose last pushed rate is on record.

    Repricing the active plan queues one rate batch that fans out one job per
    verified mapping, and dispatching it applies the promotion-free distributed
    rate of 25000 cents to the mapping. Raising the ceiling to 41000 leaves the
    resolved base at 25000 and keeps it inside the plan's band, so the pushed
    number is the plan's base amount. Returns the mapping's id.
    """
    mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    batches_before = {batch["id"] for batch in fixtures.list_batches(api)}
    fixtures.reprice_rate_plan(api, world["rate_plan_id"], ceiling_amount_cents=41000)
    queued = [
        batch for batch in fixtures.list_batches(api) if batch["id"] not in batches_before
    ]
    assert len(queued) == 1, "repricing queues exactly one distribution batch"
    assert_fields(
        queued[0],
        {"payload_kind": "RATE", "source_ref_kind": "RATE_PLAN", "batch_state": "QUEUED"},
        entity_name="batch",
    )
    fixtures.dispatch_batch(api, queued[0]["id"])

    pushed = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        pushed,
        {
            "mapping_state": "VERIFIED",
            "last_pushed_rate_cents": DISTRIBUTED_RATE_CENTS,
            "observed_rate_cents": None,
            "mismatch_state": "UNKNOWN",
            "mismatch_delta_cents": None,
        },
        entity_name="mapping",
    )
    assert_instant_equals(pushed["last_push_at"], fixtures.FIXTURE_CLOCK, "mapping.last_push_at")
    return str(mapping["id"])


def _alert_count(api: Any, world: Dict[str, Any]) -> int:
    """The channel's live count of mappings currently reading MISMATCHED."""
    return int(fixtures.read_channel(api, world["channel_id"])["mismatch_alert_count"])


def test_observed_rate_delta_equal_to_the_tolerance_is_in_sync_on_both_signs(api, world) -> None:
    """A delta exactly equal to the tolerance stays in sync above and below.

    The verdict is MISMATCHED only when the absolute delta strictly exceeds the
    property's tolerance, so an observation 200 cents above the distributed rate
    and one 200 cents below it both read IN_SYNC and raise no channel alert.

    Design: Difficulty/boundary_precision_check/rate_mismatch_delta_equal_to_tolerance_stays_in_sync_on_both_signs
    """
    mapping_id = _mapping_with_a_distributed_rate(api, world)

    # 25200 - 25000 = +200, exactly the 200 cent tolerance.
    high = fixtures.record_observed_rate(
        api, mapping_id, DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS, fixtures.STAY_DATE
    )
    assert_fields(
        high,
        {
            "observed_rate_cents": DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS,
            "observed_stay_date": fixtures.STAY_DATE,
            "mismatch_delta_cents": TOLERANCE_CENTS,
            "mismatch_state": "IN_SYNC",
            "mapping_state": "VERIFIED",
        },
        entity_name="mapping",
    )
    assert _alert_count(api, world) == 0, "an in-sync mapping raises no alert"

    # 24800 - 25000 = -200, whose absolute value is again exactly the tolerance.
    low = fixtures.record_observed_rate(
        api, mapping_id, DISTRIBUTED_RATE_CENTS - TOLERANCE_CENTS, fixtures.STAY_DATE
    )
    assert_fields(
        low,
        {
            "observed_rate_cents": DISTRIBUTED_RATE_CENTS - TOLERANCE_CENTS,
            "mismatch_delta_cents": -TOLERANCE_CENTS,
            "mismatch_state": "IN_SYNC",
        },
        entity_name="mapping",
    )
    assert _alert_count(api, world) == 0, "an in-sync mapping raises no alert"


def test_observed_rate_delta_one_cent_past_the_tolerance_is_mismatched_on_both_signs(
    api, world
) -> None:
    """One cent beyond the tolerance is mismatched above and below.

    A single cent past the tolerance in either direction makes the absolute delta
    strictly greater than the tolerance, so the verdict becomes MISMATCHED, the
    signed delta is recorded with its sign, and the channel counts one alert.

    Design: Difficulty/boundary_precision_check/rate_mismatch_delta_equal_to_tolerance_stays_in_sync_on_both_signs
    """
    mapping_id = _mapping_with_a_distributed_rate(api, world)

    # 25201 - 25000 = +201, one cent past the 200 cent tolerance.
    high = fixtures.record_observed_rate(
        api, mapping_id, DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS + 1, fixtures.STAY_DATE
    )
    assert_fields(
        high,
        {
            "observed_rate_cents": DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS + 1,
            "mismatch_delta_cents": TOLERANCE_CENTS + 1,
            "mismatch_state": "MISMATCHED",
            "mapping_state": "VERIFIED",
        },
        entity_name="mapping",
    )
    assert _alert_count(api, world) == 1, "a mismatched mapping raises one alert"

    # 24799 - 25000 = -201, one cent past the tolerance on the low side.
    low = fixtures.record_observed_rate(
        api, mapping_id, DISTRIBUTED_RATE_CENTS - TOLERANCE_CENTS - 1, fixtures.STAY_DATE
    )
    assert_fields(
        low,
        {
            "observed_rate_cents": DISTRIBUTED_RATE_CENTS - TOLERANCE_CENTS - 1,
            "mismatch_delta_cents": -(TOLERANCE_CENTS + 1),
            "mismatch_state": "MISMATCHED",
        },
        entity_name="mapping",
    )
    assert _alert_count(api, world) == 1, "the one mapping still accounts for one alert"


def test_mismatch_alert_count_follows_the_current_verdict_not_the_event_count(
    api, world
) -> None:
    """Each observation replaces the last, and the alert count is re-counted.

    No history of observations is kept, so an observation that lands back on the
    tolerance boundary pulls the mapping from MISMATCHED to IN_SYNC and drops the
    channel's alert count from one to zero.

    Design: Difficulty/boundary_precision_check/rate_mismatch_delta_equal_to_tolerance_stays_in_sync_on_both_signs
    """
    mapping_id = _mapping_with_a_distributed_rate(api, world)

    fixtures.record_observed_rate(
        api, mapping_id, DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS + 1, fixtures.STAY_DATE
    )
    assert _alert_count(api, world) == 1

    settled = fixtures.record_observed_rate(
        api, mapping_id, DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS, fixtures.STAY_DATE
    )
    assert_fields(
        settled,
        {
            "observed_rate_cents": DISTRIBUTED_RATE_CENTS + TOLERANCE_CENTS,
            "mismatch_delta_cents": TOLERANCE_CENTS,
            "mismatch_state": "IN_SYNC",
        },
        entity_name="mapping",
    )
    assert _alert_count(api, world) == 0, "the alert count is re-counted, never accumulated"


def _three_night_stay_with_stacked_promotions(api: Any, world: Dict[str, Any]) -> None:
    """One three-night OTA stay priced through two stacked promotions.

    A 1000 bp member rate covers all of September and a 1000 cent geo offer
    covers only the first two nights, so the nights price at
    25000 - 2500 - 1000 = 21500, 21500 and 25000 - 2500 = 22500. The total
    discount of 3500 on the first two nights stays under the stacking cap of
    floor(25000 x 3000 / 10000) = 7500, so nothing is pulled back. Commission at
    1750 bp rounds per night: 3763, 3763 and 3938.
    """
    fixtures.open_inventory_range(
        api, world["room_type_id"], fixtures.STAY_DATE, fixtures.STAY_DATE_3
    )
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date=MIX_WINDOW_START,
        end_date=MIX_WINDOW_END_AT_LIMIT,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date=fixtures.STAY_DATE,
        end_date=fixtures.STAY_DATE_2,
        code="GEO10USD",
        promo_kind="GEO_OFFER",
        discount_kind="AMOUNT",
        discount_amount_cents=1000,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    reservation = fixtures.create_reservation(
        api,
        world["channel_id"],
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=3,
        member_flag=True,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": fixtures.STAY_DATE,
                "sell_rate_cents": 21500,
                "commissionable_cents": 21500,
                "commission_cents": 3763,
            },
            {
                "stay_date": fixtures.STAY_DATE_2,
                "sell_rate_cents": 21500,
                "commissionable_cents": 21500,
                "commission_cents": 3763,
            },
            {
                "stay_date": fixtures.STAY_DATE_3,
                "sell_rate_cents": 22500,
                "commissionable_cents": 22500,
                "commission_cents": 3938,
            },
        ],
    )
    # 21500 + 21500 + 22500 = 65500 gross; 3763 + 3763 + 3938 = 11464 commission.
    assert_reservation_totals(reservation, gross=65500, commission=11464, net=54036)


def test_mix_window_of_exactly_mix_window_days_is_accepted(api, world) -> None:
    """A window exactly as long as mix_window_days is accepted and ranks.

    Thirty inclusive days is exactly the property's mix window, so the read
    succeeds and ranks the one eligible channel from its stay-basis figures:
    net 54036 over 3 room nights gives net_adr_cents 18012, and commission 11464
    against gross 65500 gives a cost ratio of 1750 bp.

    Design: Difficulty/boundary_precision_check/analytics_window_exactly_mix_window_days_is_accepted_and_empty_set_is_refused
    """
    _three_night_stay_with_stacked_promotions(api, world)

    response = api.get_channel_mix(
        world["property_id"],
        REVENUE_MANAGER_HEADERS,
        factories.mix_params(MIX_WINDOW_START, MIX_WINDOW_END_AT_LIMIT),
    )
    mix = validate_success(response, 200)

    assert_fields(
        mix,
        {
            "property_id": world["property_id"],
            "window_start_date": MIX_WINDOW_START,
            "window_end_date": MIX_WINDOW_END_AT_LIMIT,
        },
        entity_name="channel mix",
    )
    assert len(mix["ranked_channels"]) == 1, "only the one sellable channel qualifies"
    assert_ranked_channel(
        mix["ranked_channels"][0],
        {
            "rank": 1,
            "net_adr_cents": 18012,
            "commission_bp": fixtures.OTA_COMMISSION_BP,
            "commission_cost_ratio_bp": 1750,
            "room_nights": 3,
        },
    )


def test_mix_window_one_day_longer_than_mix_window_days_is_refused(api, world) -> None:
    """A window one day longer than mix_window_days is refused.

    Thirty-one inclusive days exceeds the property's mix window of thirty, so the
    read is refused with ERR_ANALYTICS_WINDOW_INVALID even though the same data
    ranks cleanly over the thirty-day window.

    Design: Difficulty/boundary_precision_check/analytics_window_exactly_mix_window_days_is_accepted_and_empty_set_is_refused
    """
    _three_night_stay_with_stacked_promotions(api, world)

    response = api.get_channel_mix(
        world["property_id"],
        REVENUE_MANAGER_HEADERS,
        factories.mix_params(MIX_WINDOW_START, MIX_WINDOW_END_ONE_DAY_PAST),
    )

    validate_error(response, ApiErrorId.ANALYTICS_WINDOW_INVALID.value, 422)


def test_mix_window_with_no_in_window_room_nights_is_refused(api, world) -> None:
    """A well-formed window that selects no room nights leaves nobody eligible.

    Eligibility needs a sellable connection and at least one stay-basis room
    night inside the window. The stay's nights end on 2026-09-12, so a window
    opening on 2026-09-13 selects none of them and the read is refused with
    ERR_NO_ELIGIBLE_CHANNEL rather than returning an empty ranking.

    Design: Difficulty/boundary_precision_check/analytics_window_exactly_mix_window_days_is_accepted_and_empty_set_is_refused
    """
    _three_night_stay_with_stacked_promotions(api, world)

    # 2026-09-13 through 2026-09-30 is 18 inclusive days, well inside the
    # 30-day mix window, so the window check passes and eligibility decides.
    response = api.get_channel_mix(
        world["property_id"],
        REVENUE_MANAGER_HEADERS,
        factories.mix_params(fixtures.STAY_DATE_4, MIX_WINDOW_END_AT_LIMIT),
    )

    validate_error(response, ApiErrorId.NO_ELIGIBLE_CHANNEL.value, 409)

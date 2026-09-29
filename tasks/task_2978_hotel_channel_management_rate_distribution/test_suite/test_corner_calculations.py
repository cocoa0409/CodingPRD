"""The computed amounts of the distribution contract.

These scenarios pin the arithmetic the server owns: the derivation walk that
resolves a rate plan's base amount and the depth cap that bounds it, the
six-step sell-rate resolution and its two-sided plan clamp, the way overlapping
minimum-stay windows combine, connectivity health scoring over resolved jobs
only, the two-condition content parity verdict, and the two analytics bases of
the channel performance and channel mix reads.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CHANNEL_OPS_ENGINEER_HEADERS,
    REVENUE_MANAGER_HEADERS,
    assert_batch_counters,
    assert_channel_ledger,
    assert_fields,
    assert_job,
    assert_performance,
    assert_quoted_rate,
    assert_ranked_channel,
    assert_reservation_totals,
    assert_sequence_indices_one_based,
    assert_version,
    factories,
    find_by,
    fixtures,
)

# The quoted-rate read carries its guest attributes in the query string, so the
# boolean loyalty flag travels as the lowercase JSON literal for true.
MEMBER_FLAG_TRUE = "true"

# The analytics windows these scenarios query. The first spans the whole of
# September, exactly the property's 30-day mix window; the second stops on
# 2026-09-11 so that only two of a three-night stay fall inside it.
SEPTEMBER_START = "2026-09-01"
SEPTEMBER_END = "2026-09-30"
SHORT_WINDOW_END = "2026-09-11"


# ── Derivation chains ──────────────────────────────────────────────────────


def _derive(api, property_id, parent_id, code, **overrides):
    """Author one derived plan and pin the 201 the contract promises."""
    payload = factories.derived_rate_plan_payload(parent_id, code=code, **overrides)
    return validate_success(
        api.create_rate_plan(property_id, payload, REVENUE_MANAGER_HEADERS), 201
    )


def test_derivation_chain_accepts_depth_two_and_stores_each_resolved_amount(api, world):
    """A chain of three plans is legal, and each link resolves its own amount.

    A root plan sits at depth 0 on its own base amount, a percent offset resolves
    against its parent's resolved amount, and an amount offset adds to the
    parent's resolved amount rather than to the root's.

    Design: Corner/calculations/rate_plan_derivation_depth_two_is_accepted_and_a_third_level_is_refused
    """
    bar = world["rate_plan"]
    assert_fields(
        bar,
        {"derivation_depth": 0, "resolved_base_amount_cents": 25000},
        entity_name="root plan",
    )

    corp = _derive(
        api,
        world["property_id"],
        bar["id"],
        "CORP",
        rate_class="NEGOTIATED",
        offset_kind="PERCENT",
        offset_bp=-1500,
        floor_amount_cents=15000,
        ceiling_amount_cents=40000,
        negotiated_account_code="ACME",
    )
    assert_fields(
        corp,
        {
            "derivation_depth": 1,
            # 25000 x (10000 - 1500) / 10000 = 21250, half up, exact here
            "resolved_base_amount_cents": 21250,
        },
        entity_name="depth-one plan",
    )

    corppkg = _derive(
        api,
        world["property_id"],
        corp["id"],
        "CORPPKG",
        rate_class="PACKAGE",
        offset_kind="AMOUNT",
        offset_amount_cents=8000,
        floor_amount_cents=20000,
        ceiling_amount_cents=60000,
        package_inclusion_cents=2500,
    )
    assert_fields(
        corppkg,
        {
            "derivation_depth": 2,
            # 21250 + 8000 = 29250: the parent's resolved amount, not the root's
            "resolved_base_amount_cents": 29250,
        },
        entity_name="depth-two plan",
    )


def test_derivation_beyond_depth_two_is_refused_and_stores_no_plan(api, world):
    """A fourth link in the chain would sit at depth three and is refused.

    The refusal is a conflict rather than a shape failure, and it leaves no row
    behind, so the property still lists exactly the three plans that were built.

    Design: Corner/calculations/rate_plan_derivation_depth_two_is_accepted_and_a_third_level_is_refused
    """
    corp = _derive(
        api,
        world["property_id"],
        world["rate_plan_id"],
        "CORP",
        rate_class="NEGOTIATED",
        offset_kind="PERCENT",
        offset_bp=-1500,
        floor_amount_cents=15000,
        ceiling_amount_cents=40000,
        negotiated_account_code="ACME",
    )
    corppkg = _derive(
        api,
        world["property_id"],
        corp["id"],
        "CORPPKG",
        rate_class="PACKAGE",
        offset_kind="AMOUNT",
        offset_amount_cents=8000,
        floor_amount_cents=20000,
        ceiling_amount_cents=60000,
        package_inclusion_cents=2500,
    )

    too_deep = factories.derived_rate_plan_payload(
        corppkg["id"],
        code="TOODEEP",
        rate_class="PACKAGE",
        offset_kind="AMOUNT",
        offset_amount_cents=1000,
        floor_amount_cents=20000,
        ceiling_amount_cents=60000,
    )
    validate_error(
        api.create_rate_plan(world["property_id"], too_deep, REVENUE_MANAGER_HEADERS),
        ApiErrorId.DERIVATION_DEPTH_EXCEEDED.value,
        409,
    )

    plans, meta = validate_paginated(
        api.list_rate_plans(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=100, property_id=world["property_id"]),
        )
    )
    assert meta["total_count"] == 3, "the refused plan must leave no row behind"
    assert {plan["code"] for plan in plans} == {"BAR", "CORP", "CORPPKG"}


# ── The six-step sell rate and its plan clamp ──────────────────────────────


def _floored_plan_world(api, world):
    """A member-enabled brand channel selling a plan whose floor is 22000.

    Two approved offers run on the plan: a ten percent member discount across
    the whole of September, and a 1000-cent geo offer that closes on 2026-09-11.
    Together they dig the running amount below the plan's floor; alone, the
    member discount does not.
    """
    brand = fixtures.create_brand_channel(
        api,
        world["property_id"],
        allows_member_rate=True,
        sell_adjustment_bp=0,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    plan = fixtures.create_active_rate_plan(
        api,
        world["property_id"],
        code="FLOORED",
        rate_class="PUBLIC",
        base_amount_cents=25000,
        floor_amount_cents=22000,
        ceiling_amount_cents=40000,
    )
    mapping = fixtures.create_verified_mapping(
        api, plan["id"], brand["channel"]["id"], world["room_type_id"]
    )
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=SEPTEMBER_START,
        end_date=SEPTEMBER_END,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=fixtures.STAY_DATE,
        end_date=fixtures.STAY_DATE_2,
        code="GEO10USD",
        promo_kind="GEO_OFFER",
        discount_kind="AMOUNT",
        discount_amount_cents=1000,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    return mapping


def _read_quote(api, mapping_id, stay_date):
    """The quoted rate for one member booking from the served geo market."""
    params = factories.quoted_rate_params(
        stay_date=stay_date,
        member_flag=MEMBER_FLAG_TRUE,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    return validate_success(api.get_quoted_rate(mapping_id, REVENUE_MANAGER_HEADERS, params))


def test_quoted_rate_lifts_a_sub_floor_stack_to_the_plan_floor(api, world):
    """Both offers stack under the cap, and the plan's floor lifts the result.

    The read exposes the amount after the channel adjustment next to the amount
    after the clamp, so the lift from 21500 to the 22000 floor is observable
    rather than inferred, and the untouched cap proves it is the floor that bit.

    Design: Corner/calculations/quoted_rate_clamps_up_to_the_plan_floor_only_when_the_stack_digs_below_it
    """
    mapping = _floored_plan_world(api, world)

    quote = _read_quote(api, mapping["id"], fixtures.STAY_DATE)
    assert_quoted_rate(
        quote,
        {
            "channel_mapping_id": mapping["id"],
            "stay_date": fixtures.STAY_DATE,
            "base_amount_cents": 25000,
            # 25000 -> 22500 (member 10%) -> 21500 (geo 1000): 3500 discounted
            "promotion_discount_cents": 3500,
            # floor(25000 x 3000 / 10000) = 7500, and 3500 is well under it
            "discount_cap_cents": 7500,
            # 21500 x (10000 + 0) / 10000 = 21500
            "channel_adjusted_cents": 21500,
            # 21500 is below the plan floor 22000, so it rises to the floor
            "clamped_cents": 22000,
            # package inclusion 0, so the clamped amount is the sell amount
            "sell_amount_cents": 22000,
            "applied_promotion_codes": ["MEMBER10", "GEO10USD"],
        },
    )


def test_quoted_rate_leaves_an_in_band_amount_untouched_by_the_clamp(api, world):
    """One day past the geo window the same plan and channel need no lifting.

    Only the member offer is eligible, the running amount lands inside the
    plan's band, and the clamped amount equals the channel-adjusted amount,
    which is what proves the clamp is a bound and not an addition.

    Design: Corner/calculations/quoted_rate_clamps_up_to_the_plan_floor_only_when_the_stack_digs_below_it
    """
    mapping = _floored_plan_world(api, world)

    quote = _read_quote(api, mapping["id"], fixtures.STAY_DATE_3)
    assert_quoted_rate(
        quote,
        {
            "channel_mapping_id": mapping["id"],
            "stay_date": fixtures.STAY_DATE_3,
            "base_amount_cents": 25000,
            # 25000 x 9000 / 10000 = 22500, so 2500 discounted
            "promotion_discount_cents": 2500,
            "discount_cap_cents": 7500,
            "channel_adjusted_cents": 22500,
            # 22500 sits inside [22000, 40000], so the clamp is inert
            "clamped_cents": 22500,
            "sell_amount_cents": 22500,
            "applied_promotion_codes": ["MEMBER10"],
        },
    )


# ── Combining overlapping minimum-stay windows ─────────────────────────────


def _min_stay_world(api, world):
    """Three open nights and two minimum-stay windows that overlap on 09-11.

    The first window demands two nights of every plan on the room type; the
    second demands three and is scoped to the canonical plan, which is why both
    may be active at once - the overlap rule keys on the plan as well as on the
    type. Bookings run on a zero-commission brand channel that serves every
    geo market.
    """
    brand = fixtures.create_brand_channel(api, world["property_id"])
    fixtures.open_inventory_days(
        api,
        world["room_type_id"],
        [fixtures.STAY_DATE, fixtures.STAY_DATE_2, fixtures.STAY_DATE_3],
    )
    fixtures.create_restriction(
        api,
        world["room_type_id"],
        "MIN_STAY",
        fixtures.STAY_DATE,
        fixtures.STAY_DATE_2,
        value_nights=2,
    )
    fixtures.create_restriction(
        api,
        world["room_type_id"],
        "MIN_STAY",
        fixtures.STAY_DATE_2,
        fixtures.STAY_DATE_3,
        rate_plan_id=world["rate_plan_id"],
        value_nights=3,
    )
    return brand["channel"]["id"]


def _booking(world, channel_id, arrival_date, nights):
    return factories.reservation_payload(
        channel_id=channel_id,
        rate_plan_id=world["rate_plan_id"],
        room_type_id=world["room_type_id"],
        arrival_date=arrival_date,
        nights=nights,
    )


def test_arrival_inside_the_overlap_takes_the_strictest_minimum_stay(api, world):
    """An arrival both windows cover must satisfy the larger of the two demands.

    The effective minimum is the largest value_nights among the covering
    windows, never their sum, so a two-night stay arriving on 2026-09-11 is
    refused against a demand of three and no reservation is stored.

    Design: Corner/calculations/overlapping_min_stay_windows_take_the_strictest_value_not_their_sum
    """
    channel_id = _min_stay_world(api, world)

    validate_error(
        api.create_reservation(
            _booking(world, channel_id, fixtures.STAY_DATE_2, 2), REVENUE_MANAGER_HEADERS
        ),
        ApiErrorId.MIN_STAY_NOT_MET.value,
        422,
    )
    assert fixtures.list_reservations(api, channel_id=channel_id) == [], (
        "a refused booking must not store a reservation"
    )


def test_arrival_before_the_overlap_sees_only_the_two_night_window(api, world):
    """The same two-night request one day earlier is admitted.

    Only the plan-agnostic two-night window covers 2026-09-10, and the
    three-night window is ignored even though the stay runs into it, because a
    minimum-stay restriction reads the arrival date alone.

    Design: Corner/calculations/overlapping_min_stay_windows_take_the_strictest_value_not_their_sum
    """
    channel_id = _min_stay_world(api, world)

    reservation = validate_success(
        api.create_reservation(
            _booking(world, channel_id, fixtures.STAY_DATE, 2), REVENUE_MANAGER_HEADERS
        ),
        201,
    )
    assert_fields(
        reservation,
        {"reservation_state": "CONFIRMED", "departure_date": fixtures.STAY_DATE_3},
        entity_name="reservation",
    )
    # 25000 x 2 nights on a channel charging no commission
    assert_reservation_totals(reservation, gross=50000, commission=0, net=50000)

    _, meta = validate_paginated(
        api.list_reservations(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=100, channel_id=channel_id),
        )
    )
    assert meta["total_count"] == 1, "only the admitted stay may exist"


# ── Health scoring over resolved jobs only ─────────────────────────────────


def _three_mapping_world(api, world):
    """Three verified mappings on one channel, two of them out of parity.

    Each room type publishes its own description hash, so all three mappings
    start in parity; the twin and suite mappings then drop one image below the
    property's floor of five. Repricing the plan queues one rate batch that fans
    out a job per verified mapping, which is the queue these reads measure.
    """
    twin = fixtures.create_room_type(
        api,
        world["property_id"],
        code="TWIN",
        name="Twin Room",
        physical_capacity_units=2,
        master_description_hash="twinv1",
        master_image_count=5,
    )
    suite = fixtures.create_room_type(
        api,
        world["property_id"],
        code="SUITE",
        name="Harbor Suite",
        physical_capacity_units=5,
        master_description_hash="suitev1",
        master_image_count=5,
    )
    king_mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    twin_mapping = fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        twin["id"],
        content_description_hash="twinv1",
    )
    suite_mapping = fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        suite["id"],
        content_description_hash="suitev1",
    )
    fixtures.patch_mapping_content(api, twin_mapping["id"], content_image_count=4)
    fixtures.patch_mapping_content(api, suite_mapping["id"], content_image_count=4)
    fixtures.reprice_rate_plan(api, world["rate_plan_id"], ceiling_amount_cents=41000)
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")
    return {
        "batch_id": batch["id"],
        "king_mapping_id": king_mapping["id"],
        "twin_mapping_id": twin_mapping["id"],
        "suite_mapping_id": suite_mapping["id"],
    }


def _read_performance(api, channel_id, window_end=SEPTEMBER_END, **params):
    params = factories.performance_params(SEPTEMBER_START, window_end, **params)
    return validate_success(
        api.get_channel_performance(channel_id, REVENUE_MANAGER_HEADERS, params)
    )


def test_health_score_is_null_while_every_job_is_still_queued(api, world):
    """A queue of unresolved work scores nothing at all.

    Only jobs that reached APPLIED or REJECTED enter the ratio, so a batch whose
    three children are all queued leaves the score null, alongside the zeros and
    nulls an empty revenue window reports.

    Design: Corner/calculations/health_score_is_null_until_a_job_resolves_and_a_retry_shrinks_the_denominator
    """
    scenario = _three_mapping_world(api, world)

    batch = fixtures.read_batch(api, scenario["batch_id"])
    assert_batch_counters(
        batch,
        batch_state="QUEUED",
        total_jobs=3,
        applied_jobs=0,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    jobs = fixtures.jobs_of(api, scenario["batch_id"])
    assert_sequence_indices_one_based(jobs)
    assert all(job["job_state"] == "QUEUED" for job in jobs), "nothing is dispatched yet"

    performance = _read_performance(api, world["channel_id"])
    assert_performance(
        performance,
        {
            "gross_amount_cents": 0,
            "commission_amount_cents": 0,
            "net_amount_cents": 0,
            "room_nights": 0,
            "net_adr_cents": None,
            "commission_cost_ratio_bp": None,
            "health_score_bp": None,
        },
    )


def test_health_score_counts_resolved_jobs_and_rises_when_a_rejected_job_is_retried(api, world):
    """Resolving three jobs scores one in three; requeuing one scores one in two.

    The dispatch applies the mapping that is in parity and rejects the two that
    are not, so the score is the applied count over the resolved count. Retrying
    a rejected job returns it to the queue and removes it from the denominator,
    which raises the score without any new job succeeding.

    Design: Corner/calculations/health_score_is_null_until_a_job_resolves_and_a_retry_shrinks_the_denominator
    """
    scenario = _three_mapping_world(api, world)

    validate_success(
        api.dispatch_batch(scenario["batch_id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )

    batch = fixtures.read_batch(api, scenario["batch_id"])
    assert_batch_counters(
        batch,
        batch_state="PARTIALLY_APPLIED",
        total_jobs=3,
        applied_jobs=1,
        rejected_jobs=2,
        abandoned_jobs=0,
    )

    jobs = fixtures.jobs_of(api, scenario["batch_id"])
    assert_job(
        find_by(jobs, channel_mapping_id=scenario["king_mapping_id"]),
        job_state="APPLIED",
        attempt_count=1,
        failure_reason=None,
        # the promotion-free rate card: 25000 x (10000 + 0) / 10000, inside
        # [18000, 41000], plus a package inclusion of 0
        payload_rate_cents=25000,
    )
    for mapping_key in ("twin_mapping_id", "suite_mapping_id"):
        assert_job(
            find_by(jobs, channel_mapping_id=scenario[mapping_key]),
            job_state="REJECTED",
            attempt_count=1,
            failure_reason="PARITY_BLOCKED",
        )

    performance = _read_performance(api, world["channel_id"])
    # round_half_up(1 applied x 10000 / 3 resolved) = 3333
    assert_performance(performance, {"health_score_bp": 3333})

    connection = fixtures.read_connection(api, world["connection_id"])
    assert_fields(
        connection,
        {
            # two rejections, one short of the suspension threshold of three
            "connection_state": "DEGRADED",
            "consecutive_failures": 2,
            "last_failure_code": "MAPPING_REJECTED",
        },
        entity_name="connection",
    )

    rejected = find_by(jobs, channel_mapping_id=scenario["twin_mapping_id"])
    retried = validate_success(api.retry_job(rejected["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_job(
        retried,
        job_state="QUEUED",
        # the attempt is preserved, so the reject-and-retry cycle stays bounded
        attempt_count=1,
        failure_reason=None,
    )

    performance = _read_performance(api, world["channel_id"])
    # round_half_up(1 applied x 10000 / 2 resolved) = 5000: the requeued job
    # left the resolved set, so the score rose with no new success
    assert_performance(performance, {"health_score_bp": 5000})


# ── Content parity as a two-condition conjunction ──────────────────────────


def _patch_content(api, mapping_id, **fields):
    payload = factories.mapping_content_payload(**fields)
    return validate_success(
        api.patch_mapping_content(mapping_id, payload, CHANNEL_OPS_ENGINEER_HEADERS)
    )


def test_parity_requires_the_image_count_to_clear_the_required_floor(api, world):
    """The image test is a floor, not an equality.

    A mapping publishing the matching hash and exactly the required five images
    is in parity; dropping to four falls out of parity; and republishing six
    returns it to parity, because clearing the floor is what the rule asks for.

    Design: Corner/calculations/parity_requires_both_the_hash_match_and_the_image_count_floor
    """
    mapping = fixtures.create_mapping_in_parity(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    assert_fields(mapping, {"parity_state": "IN_PARITY"}, entity_name="mapping")
    assert_version(mapping, 1, entity_name="mapping")

    below = _patch_content(api, mapping["id"], content_image_count=4)
    # 4 images against the property's required 5: one short is enough to fail
    assert_fields(below, {"parity_state": "OUT_OF_PARITY"}, entity_name="mapping")
    assert_version(below, 2, entity_name="mapping")

    above = _patch_content(api, mapping["id"], content_image_count=6)
    # 6 images clears the floor of 5, and the hash still matches
    assert_fields(above, {"parity_state": "IN_PARITY"}, entity_name="mapping")
    assert_version(above, 3, entity_name="mapping")


def test_parity_requires_an_exact_hash_match_regardless_of_image_count(api, world):
    """A plentiful image count cannot rescue a stale description hash.

    Both conditions must hold, so a mapping that is in parity with six images
    falls out of parity the moment its description hash stops matching the room
    type's master hash, even though nothing about the images changed.

    Design: Corner/calculations/parity_requires_both_the_hash_match_and_the_image_count_floor
    """
    mapping = fixtures.create_mapping_in_parity(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    assert_fields(mapping, {"parity_state": "IN_PARITY"}, entity_name="mapping")

    plentiful = _patch_content(api, mapping["id"], content_image_count=6)
    assert_fields(
        plentiful,
        {"parity_state": "IN_PARITY", "content_image_count": 6},
        entity_name="mapping",
    )
    assert_version(plentiful, 2, entity_name="mapping")

    stale = _patch_content(api, mapping["id"], content_description_hash="kingv2")
    assert_fields(
        stale,
        {
            # the hash no longer equals the room type's master hash
            "parity_state": "OUT_OF_PARITY",
            "content_description_hash": "kingv2",
            "content_image_count": 6,
        },
        entity_name="mapping",
    )
    assert_version(stale, 3, entity_name="mapping")


# ── The two analytics bases ────────────────────────────────────────────────


def _stay_world(api, world):
    """One three-night stay on the public OTA, booked well before the window.

    The stay runs 2026-09-10 to 2026-09-13 at 25000 a night on a channel
    charging 1750 basis points, and it is created while the clock still reads
    2026-08-25, which is what puts its booking date outside every September
    window. The OTA serves only one geo market, so the booking states it.
    """
    fixtures.open_inventory_days(
        api,
        world["room_type_id"],
        [fixtures.STAY_DATE, fixtures.STAY_DATE_2, fixtures.STAY_DATE_3],
    )
    return fixtures.create_reservation(
        api,
        world["channel_id"],
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=3,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )


def test_performance_read_omitting_basis_uses_the_stay_basis(api, world):
    """An omitted basis materialises as the stay basis in the response.

    On that basis a reservation contributes only the nights inside the window
    and its booking date is irrelevant, so two of the three nights are reported
    and the echoed basis is the string the default resolved to.

    Design: Corner/calculations/performance_read_defaults_to_stay_basis_when_basis_is_omitted
    """
    reservation = _stay_world(api, world)
    # 3 nights x 25000; per-night commission round_half_up(25000 x 1750 / 10000)
    # = 4375, summed per night to 13125, leaving 61875 net
    assert_reservation_totals(reservation, gross=75000, commission=13125, net=61875)

    performance = _read_performance(api, world["channel_id"], window_end=SHORT_WINDOW_END)
    assert_performance(
        performance,
        {
            "channel_id": world["channel_id"],
            # the default is materialised, not left null and not BOOKED
            "basis": "STAY",
            "window_start_date": SEPTEMBER_START,
            "window_end_date": SHORT_WINDOW_END,
            # only 2026-09-10 and 2026-09-11 fall inside the window
            "gross_amount_cents": 50000,
            "commission_amount_cents": 8750,
            "net_amount_cents": 41250,
            "room_nights": 2,
            # 41250 / 2 nights, rounded once at the end
            "net_adr_cents": 20625,
            # 8750 x 10000 / 50000 = 1750
            "commission_cost_ratio_bp": 1750,
        },
    )


def test_performance_read_on_the_booked_basis_drops_a_stay_booked_before_the_window(api, world):
    """The booked basis selects on the booking date, so the same window is empty.

    The reservation was created on 2026-08-25, which is outside the window, so
    the production view reports the empty-window answer even though the stay
    itself is entirely inside September.

    Design: Corner/calculations/performance_read_defaults_to_stay_basis_when_basis_is_omitted
    """
    _stay_world(api, world)

    performance = _read_performance(
        api, world["channel_id"], window_end=SHORT_WINDOW_END, basis="BOOKED"
    )
    assert_performance(
        performance,
        {
            "basis": "BOOKED",
            "gross_amount_cents": 0,
            "commission_amount_cents": 0,
            "net_amount_cents": 0,
            "room_nights": 0,
            "net_adr_cents": None,
            "commission_cost_ratio_bp": None,
        },
    )


# ── Channel mix eligibility ────────────────────────────────────────────────


def _mix_world(api, world):
    """Two live channels, one of which has sold a night.

    The brand channel takes a single 25000 night on 2026-09-10; the public OTA
    keeps its healthy connection and sells nothing at all, which is the channel
    the ranking must drop.
    """
    brand = fixtures.create_brand_channel(api, world["property_id"])
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    fixtures.create_reservation(
        api,
        brand["channel"]["id"],
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=1,
    )
    return brand


def _read_mix(api, property_id):
    return api.get_channel_mix(
        property_id,
        REVENUE_MANAGER_HEADERS,
        factories.mix_params(SEPTEMBER_START, SEPTEMBER_END),
    )


def test_channel_mix_ranks_only_channels_with_room_nights_in_the_window(api, world):
    """A live channel that sold nothing in the window is not ranked.

    Eligibility needs both a sellable connection and at least one room night, so
    the ranking holds exactly the one earning channel, and each entry carries
    only the five declared ranking fields.

    Design: Corner/calculations/channel_mix_excludes_zero_night_channels_and_unsellable_connections
    """
    _mix_world(api, world)

    mix = validate_success(_read_mix(api, world["property_id"]))
    assert_fields(
        mix,
        {
            "property_id": world["property_id"],
            "window_start_date": SEPTEMBER_START,
            "window_end_date": SEPTEMBER_END,
        },
        entity_name="channel mix",
    )
    entries = mix["ranked_channels"]
    assert len(entries) == 1, (
        f"the healthy channel with no room nights must be dropped, got {entries}"
    )
    assert_ranked_channel(
        entries[0],
        {
            "rank": 1,
            # one night of 25000 net of no commission
            "net_adr_cents": 25000,
            "commission_bp": 0,
            "commission_cost_ratio_bp": 0,
            "room_nights": 1,
        },
    )


def test_channel_mix_refuses_when_suspending_the_only_earning_channel_empties_the_set(api, world):
    """Suspending the earning channel's connection leaves nothing to rank.

    Three failure events suspend the connection without touching the channel's
    lifetime ledger, and a suspended connection is not sellable, so the request
    that just succeeded now has no eligible channel to report.

    Design: Corner/calculations/channel_mix_excludes_zero_night_channels_and_unsellable_connections
    """
    brand = _mix_world(api, world)
    validate_success(_read_mix(api, world["property_id"]))

    for _ in range(3):
        fixtures.record_heartbeat(
            api, brand["connection"]["id"], status="ERROR", failure_code="TIMEOUT"
        )
    connection = fixtures.read_connection(api, brand["connection"]["id"])
    assert_fields(
        connection,
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        entity_name="connection",
    )
    channel = fixtures.read_channel(api, brand["channel"]["id"])
    assert_channel_ledger(
        channel,
        {
            # the revenue is untouched by a connectivity failure
            "gross_revenue_cents": 25000,
            "commission_accrued_cents": 0,
            "net_revenue_cents": 25000,
            "room_nights_sold": 1,
        },
    )

    validate_error(
        _read_mix(api, world["property_id"]),
        ApiErrorId.NO_ELIGIBLE_CHANNEL.value,
        409,
    )

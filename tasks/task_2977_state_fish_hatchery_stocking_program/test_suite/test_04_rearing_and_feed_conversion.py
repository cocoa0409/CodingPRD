"""
Rearing a lot: feed arithmetic, the two feed-conversion variants, the density
hard cap, and the two orthogonal dimensions a lot carries.

Covers half-up rounding on biomass and both FCRs, the four-decimal station
density recomputed from that biomass, the inclusive stage-weight gates and the
one-step-at-a-time stage machine, the inclusive density cap and the refusal that
writes nothing, and the independence of `rearing_stage` from `health_status`.
"""

from test_helpers import (
    assert_fish_conservation,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import VET_ANNA_HEADERS


def test_lot_biomass_and_fcr_round_half_up_to_the_declared_places(api):
    """
    20000 fish at 3.99 g is 175.92573... lbs, which is reported as 175.93, and the
    FCR denominator of 171.52 gives 0.583 at three places. With no mortality the
    two variants coincide, which is the only condition under which they may.

    PRD 3.4: "The lot's `biomass_lbs` is then recomputed from the surviving
    `count_on_hand` and the new `avg_weight_g`, and `feed_lbs` is added to
    `cumulative_feed_lbs`."

    Design: Corner/calculations/lot_biomass_and_fcr_round_half_up_to_the_declared_places
    """
    ctx = fx.lot_at_egg(api)
    assert_number_equals(
        ctx["lot"]["initial_biomass_lbs"], 4.41, 2, "initial_biomass_lbs"
    )

    fed = validate_success(
        api.record_feeding(
            ctx["lot"]["id"],
            f.feeding_payload(
                fed_at=f.instant(2026, 8, 10, 12),
                feed_lbs=100.0,
                avg_weight_g_after=3.99,
                mortality_count=0,
            ),
            ctx["manager"],
        ),
        200,
    )

    assert_number_equals(fed["biomass_lbs"], 175.93, 2, "biomass_lbs")
    assert_integer_equals(fed["count_on_hand"], 20000, "count_on_hand")
    assert_integer_equals(
        fed["cumulative_mortality_count"], 0, "cumulative_mortality_count"
    )
    assert_number_equals(
        fed["cumulative_mortality_biomass_lbs"],
        0.0,
        2,
        "cumulative_mortality_biomass_lbs",
    )
    assert_number_equals(fed["cumulative_feed_lbs"], 100.0, 2, "cumulative_feed_lbs")
    assert_number_equals(fed["fcr_biological"], 0.583, 3, "fcr_biological")
    assert_number_equals(fed["fcr_economic"], 0.583, 3, "fcr_economic")
    assert_fish_conservation(fed)


def test_density_index_is_recomputed_from_station_biomass_to_four_decimals(api):
    """
    175.93 over a permitted 2000.0 lbs is 0.087965, reported as 0.0880 — neither
    the two-place 0.09 nor the truncated 0.0879 — and a second feeding lands the
    station on exactly 0.8000.

    PRD 2.5: "The **standing-crop meter** is `biomass_on_hand_lbs`, the sum of
    `biomass_lbs` across the station's rearing lots whose `rearing_stage` is
    neither `RELEASED` nor `TERMINATED`, and `density_index`, that biomass divided
    by the station's permitted `rearing_capacity_lbs`."

    Design: Corner/calculations/density_index_is_recomputed_from_station_biomass_to_four_decimals
    """
    ctx = fx.lot_at_egg(api, {"rearing_capacity_lbs": 2000.0})

    fx.record_feeding(
        api, ctx["hatchery"], ctx["lot"]["id"], f.instant(2026, 8, 10, 12), 100.0, 3.99, 0
    )

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(
        station["biomass_on_hand_lbs"], 175.93, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(station["density_index"], 0.0880, 4, "density_index")
    assert station["operating_posture"] == k.POSTURE_OPEN

    fx.record_feeding(
        api,
        ctx["hatchery"],
        ctx["lot"]["id"],
        f.instant(2026, 8, 10, 18),
        1500.0,
        45.3592,
        4000,
    )

    after = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(
        after["biomass_on_hand_lbs"], 1600.0, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(after["density_index"], 0.8000, 4, "density_index")
    assert after["operating_posture"] == k.POSTURE_OPEN


def test_stage_weight_gate_is_satisfied_exactly_at_the_gate_weight(api):
    """
    A lot at exactly 4.0 g passes the FINGERLING gate, so the rule is a strict
    `<` and not a `<=`.

    PRD 3.4: "Each target carries a minimum mean weight the lot must have
    reached, and the gate is inclusive: `FRY` requires an `avg_weight_g` of at
    least 1.0 grams, `FINGERLING` at least 4.0 grams, and `YEARLING` at least
    45.0 grams."

    Design: Corner/validations/stage_weight_gate_is_satisfied_exactly_at_the_gate_weight
    """
    ctx = fx.lot_at_egg(api)
    lot_id = ctx["lot"]["id"]
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10, 12), 100.0, 4.0, 0
    )
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FRY)

    advanced = validate_success(
        api.advance_stage(
            lot_id, f.advance_stage_payload(k.STAGE_FINGERLING), ctx["manager"]
        ),
        200,
    )

    assert advanced["rearing_stage"] == k.STAGE_FINGERLING
    assert_number_equals(advanced["avg_weight_g"], 4.0, 4, "avg_weight_g")
    assert_number_equals(advanced["biomass_lbs"], 176.37, 2, "biomass_lbs")
    assert advanced["health_status"] == k.HEALTH_UNSCREENED


def test_stage_weight_gate_refuses_an_advance_one_hundredth_below_the_gate(api):
    """
    The same lot a hundredth of a gram lighter is refused on the weight, not on
    the transition, because FRY to FINGERLING is a declared edge.

    PRD 3.4: "A lot at exactly 4.0 grams may advance to `FINGERLING`; one at 3.99
    grams may not, and is refused with `ERR_STAGE_WEIGHT_NOT_MET` (HTTP 422)."

    Design: Corner/validations/stage_weight_gate_refuses_an_advance_one_hundredth_below_the_gate
    """
    ctx = fx.lot_at_egg(api)
    lot_id = ctx["lot"]["id"]
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10, 12), 100.0, 3.99, 0
    )
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FRY)

    response = api.advance_stage(
        lot_id, f.advance_stage_payload(k.STAGE_FINGERLING), ctx["manager"]
    )

    validate_error(response, err.ERR_STAGE_WEIGHT_NOT_MET, 422)

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert lot["rearing_stage"] == k.STAGE_FRY
    assert_number_equals(lot["avg_weight_g"], 3.99, 4, "avg_weight_g")


def test_advance_stage_skipping_fingerling_is_an_invalid_transition(api):
    """
    A FRY lot already past the YEARLING gate weight is still refused the jump: the
    target stage is wrong, not the weight.

    PRD 3.4: "Advancement is strictly one step at a time: from `EGG` the only
    legal target is `FRY`, from `FRY` only `FINGERLING`, and from `FINGERLING`
    only `YEARLING`."

    Design: Corner/state_machines/advance_stage_skipping_fingerling_is_an_invalid_transition
    """
    ctx = fx.lot_at_egg(api)
    lot_id = ctx["lot"]["id"]
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10), 300.0, 4.53592, 2000
    )
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FRY)
    fx.set_clock(api, f.instant(2026, 8, 20))
    fed = fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 20), 1500.0, 45.3592, 2000
    )
    assert_integer_equals(fed["count_on_hand"], 16000, "count_on_hand")
    assert_number_equals(fed["avg_weight_g"], 45.3592, 4, "avg_weight_g")

    response = api.advance_stage(
        lot_id, f.advance_stage_payload(k.STAGE_YEARLING), ctx["manager"]
    )

    validate_error(response, err.ERR_INVALID_STATE, 409)
    assert fx.read_lot(api, ctx["hatchery"], lot_id)["rearing_stage"] == k.STAGE_FRY

    stepwise = fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FINGERLING)
    assert stepwise["rearing_stage"] == k.STAGE_FINGERLING
    final = fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_YEARLING)
    assert final["rearing_stage"] == k.STAGE_YEARLING


def test_fcr_biological_and_economic_diverge_on_the_same_lot(api):
    """
    The two variants differ only in whether the pounds lost to mortality are
    credited as production, so the economic ratio is strictly lower than the
    biological one on the very same feeding row.

    PRD 3.4: "Because the economic denominator is the biological one plus the
    mortality pounds, `fcr_economic` is always at or below `fcr_biological`, and
    the two coincide only for a lot that has recorded no mortality at all."

    Design: Difficulty/dual_variant_calc/fcr_biological_vs_economic_diverge_on_same_lot
    """
    ctx = fx.lot_at_egg(api, {"rearing_capacity_lbs": 2000.0})
    lot_id = ctx["lot"]["id"]
    first = fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10), 300.0, 4.53592, 2000
    )
    assert_integer_equals(first["count_on_hand"], 18000, "count_on_hand")
    assert_number_equals(first["biomass_lbs"], 180.0, 2, "biomass_lbs")
    assert_number_equals(
        first["cumulative_mortality_biomass_lbs"],
        20.0,
        2,
        "cumulative_mortality_biomass_lbs",
    )
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FRY)
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FINGERLING)
    fx.set_clock(api, f.instant(2026, 8, 20))

    second = validate_success(
        api.record_feeding(
            lot_id,
            f.feeding_payload(
                fed_at=f.instant(2026, 8, 20),
                feed_lbs=1500.0,
                avg_weight_g_after=45.3592,
                mortality_count=2000,
            ),
            ctx["manager"],
        ),
        200,
    )

    assert_integer_equals(second["count_on_hand"], 16000, "count_on_hand")
    assert_number_equals(second["biomass_lbs"], 1600.0, 2, "biomass_lbs")
    assert_number_equals(second["fcr_biological"], 1.128, 3, "fcr_biological")
    assert_number_equals(second["fcr_economic"], 0.991, 3, "fcr_economic")
    assert float(second["fcr_economic"]) < float(second["fcr_biological"]), second


def test_both_feed_conversion_variants_are_stored_side_by_side(api):
    """
    There is no selector between the two conventions: both are stored on the lot
    alongside the mortality pounds that separate them, and the growth rate is
    reported over the whole-day span between the two feedings.

    PRD 3.4: "There is no selector between them — both are computed and both are
    stored, and the two are the lot's current cumulative figures."

    Design: Difficulty/dual_variant_calc/fcr_biological_vs_economic_diverge_on_same_lot
    """
    ctx = fx.lot_at_egg(api, {"rearing_capacity_lbs": 2000.0})
    lot_id = ctx["lot"]["id"]
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10), 300.0, 4.53592, 2000
    )
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FRY)
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FINGERLING)
    fx.set_clock(api, f.instant(2026, 8, 20))
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 20), 1500.0, 45.3592, 2000
    )

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)

    assert_number_equals(lot["cumulative_feed_lbs"], 1800.0, 2, "cumulative_feed_lbs")
    assert_number_equals(
        lot["cumulative_mortality_biomass_lbs"],
        220.0,
        2,
        "cumulative_mortality_biomass_lbs",
    )
    assert_integer_equals(
        lot["cumulative_mortality_count"], 4000, "cumulative_mortality_count"
    )
    assert_number_equals(lot["fcr_biological"], 1.128, 3, "fcr_biological")
    assert_number_equals(lot["fcr_economic"], 0.991, 3, "fcr_economic")
    assert_number_equals(
        lot["growth_rate_g_per_day"], 4.0823, 4, "growth_rate_g_per_day"
    )
    assert_fish_conservation(lot)

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(
        station["biomass_on_hand_lbs"], 1600.0, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(station["density_index"], 0.8000, 4, "density_index")
    assert station["operating_posture"] == k.POSTURE_OPEN


def test_a_feeding_landing_exactly_on_the_density_cap_is_accepted(api):
    """
    A feeding that lands the station at exactly 1.0000 is written, and the posture
    flips to RESTRICTED because 1.0000 is at or above the 0.90 threshold.

    PRD 3.4: "The cap boundary is inclusive on the legal side: a feeding that
    lands the station at exactly 1.0000 is accepted, while one that would land it
    at 1.0100 is refused and nothing is written."

    Design: Difficulty/boundary_precision_check/density_cap_admits_exactly_one_then_refuses_the_next_increment
    """
    ctx = fx.yearling_lot(api, {"rearing_capacity_lbs": 2000.0})
    fx.set_clock(api, f.instant(2026, 8, 21))

    fed = validate_success(
        api.record_feeding(
            ctx["lot"]["id"],
            f.feeding_payload(
                fed_at=f.instant(2026, 8, 21),
                feed_lbs=400.0,
                avg_weight_g_after=56.699,
                mortality_count=0,
            ),
            ctx["manager"],
        ),
        200,
    )

    assert_number_equals(fed["biomass_lbs"], 2000.0, 2, "biomass_lbs")
    assert_number_equals(fed["cumulative_feed_lbs"], 2200.0, 2, "cumulative_feed_lbs")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(
        station["biomass_on_hand_lbs"], 2000.0, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(station["density_index"], 1.0000, 4, "density_index")
    assert station["operating_posture"] == k.POSTURE_RESTRICTED


def test_the_feeding_past_the_density_cap_is_refused_with_nothing_written(api):
    """
    The next increment would put the station at 1.0100, so it is refused outright
    and not even the feed is booked.

    PRD 3.4: "Second, a feeding is refused outright — with nothing written at all,
    not even the feed — when the `density_index` the station would carry afterwards
    would exceed the hard cap of 1.0000; that refusal is
    `ERR_DENSITY_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/density_cap_admits_exactly_one_then_refuses_the_next_increment
    """
    ctx = fx.yearling_lot(api, {"rearing_capacity_lbs": 2000.0})
    lot_id = ctx["lot"]["id"]
    fx.set_clock(api, f.instant(2026, 8, 21))
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 21), 400.0, 56.699, 0
    )
    fx.set_clock(api, f.instant(2026, 8, 22))

    response = api.record_feeding(
        lot_id,
        f.feeding_payload(
            fed_at=f.instant(2026, 8, 22),
            feed_lbs=20.0,
            avg_weight_g_after=57.2659,
            mortality_count=0,
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_DENSITY_CAP_EXCEEDED, 422)

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_number_equals(lot["avg_weight_g"], 56.699, 4, "avg_weight_g")
    assert_number_equals(lot["biomass_lbs"], 2000.0, 2, "biomass_lbs")
    assert_number_equals(lot["cumulative_feed_lbs"], 2200.0, 2, "cumulative_feed_lbs")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["density_index"], 1.0000, 4, "density_index")


def test_reinspecting_a_certified_lot_moves_only_the_health_dimension(api):
    """
    Opening a re-inspection moves `health_status` from CERTIFIED to
    UNDER_INSPECTION and nulls the certificate, while `rearing_stage` stays
    YEARLING and the historical inspection row is untouched.

    PRD 3.4: "The two advance on their own triggers: a lot may perfectly well be
    `YEARLING` and `QUARANTINED`, or `FRY` and `CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/rearing_lot_stage_and_health_dimensions_move_independently
    """
    ctx = fx.certified_yearling_lot(api)
    first_inspection = ctx["inspection"]
    assert ctx["lot"]["health_status"] == k.HEALTH_CERTIFIED
    assert ctx["lot"]["rearing_stage"] == k.STAGE_YEARLING

    second = validate_success(
        api.create_health_inspection(
            f.health_inspection_payload(
                ctx["lot"]["id"],
                inspection_type=k.INSPECTION_TYPE_ROUTINE,
                sample_size=30,
                sampled_at=f.instant(2026, 8, 25),
            ),
            VET_ANNA_HEADERS,
        ),
        201,
    )

    assert second["status"] == k.INSPECTION_SAMPLED
    historical = validate_success(
        api.get_health_inspection(first_inspection["id"], VET_ANNA_HEADERS), 200
    )
    assert historical["status"] == k.INSPECTION_CERTIFIED

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_UNDER_INSPECTION
    assert_is_none(lot["certificate_expires_at"], "certificate_expires_at")
    assert lot["rearing_stage"] == k.STAGE_YEARLING


def test_a_feeding_lands_on_the_growth_dimension_while_health_is_under_inspection(api):
    """
    A feeding recorded while the health dimension sits in UNDER_INSPECTION still
    lands on the growth dimension: the feed accumulates and the stage does not
    move.

    PRD 3.4: "A rearing lot carries two entirely independent state dimensions on
    the same record, and keeping them separate is essential to reading the rest of
    this document correctly."

    Design: Difficulty/non_linear_state_machine/rearing_lot_stage_and_health_dimensions_move_independently
    """
    ctx = fx.certified_yearling_lot(api)
    lot_id = ctx["lot"]["id"]
    fx.open_inspection(
        api,
        lot_id,
        VET_ANNA_HEADERS,
        inspection_type=k.INSPECTION_TYPE_ROUTINE,
        sample_size=30,
        sampled_at=f.instant(2026, 8, 25),
    )

    fed = validate_success(
        api.record_feeding(
            lot_id,
            f.feeding_payload(
                fed_at=f.instant(2026, 8, 25),
                feed_lbs=10.0,
                avg_weight_g_after=45.3592,
                mortality_count=0,
            ),
            ctx["manager"],
        ),
        200,
    )

    assert_number_equals(fed["cumulative_feed_lbs"], 1810.0, 2, "cumulative_feed_lbs")
    assert_integer_equals(fed["count_on_hand"], 16000, "count_on_hand")
    assert_number_equals(fed["biomass_lbs"], 1600.0, 2, "biomass_lbs")
    assert_number_equals(
        fed["growth_rate_g_per_day"], 0.0, 4, "growth_rate_g_per_day"
    )
    assert fed["rearing_stage"] == k.STAGE_YEARLING
    assert fed["health_status"] == k.HEALTH_UNDER_INSPECTION

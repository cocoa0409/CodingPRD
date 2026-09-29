"""Breadth coverage of the substantive gates that sit above the ladder's structural rungs:
the substitution ceiling on a bed, the two recipe gates on a design, and the two window gates
on an outage.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount
from test_helpers.test_users import ADMIN_HEADERS, ENGINEER_HEADERS


def _reference_spine(api):
    """Plant, catalogue, kiln and silos, with the clock at the start of August."""
    fx.reset_clock(api)
    return fx.plant_environment(api)


def _reference_bed_with_fly_ash_registered(api):
    """The canonical 1041.28 as-received bed — 1000.00 dry — plus an ALT_RAW fly ash whose
    substitution ceiling is 8.00 percent."""
    env = _reference_spine(api)
    env["fly_ash"] = fx.data_of(
        api.create_raw_material(
            f.alt_raw_payload("FLY-1", max_substitution_pct=8.00), ENGINEER_HEADERS
        )
    )
    assert env["fly_ash"]["is_alternative"] is True
    assert_amount(
        env["fly_ash"]["max_substitution_pct"], 8.00, "max_substitution_pct"
    )

    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_open_pile(api, env["plant_id"], design["id"])
    bed = fx.add_reference_additions(api, pile["id"], env["materials"])
    assert_amount(bed["as_received_tonnes"], 1041.28, "as_received_tonnes")
    assert_amount(bed["dry_tonnes"], 1000.00, "dry_tonnes")
    assert_amount(bed["alt_raw_share_pct"], 0.00, "alt_raw_share_pct")
    return env, pile


# ---------------------------------------------------------------------------
# validations: rung 94 admits the delivery that lands exactly on the ceiling
# ---------------------------------------------------------------------------
def test_an_alternative_delivery_landing_exactly_on_the_ceiling_is_accepted(api):
    """90.55 tonnes of fly ash on 1041.28 as-received tonnes is 8.00 percent to the hundredth,
    which is the ceiling itself, so the delivery stands and the bed grows to 1131.83 received
    and 1089.64 dry.

    PRD: "After each addition, the pile's `alt_raw_share_pct` must be no greater than the
    smallest `max_substitution_pct` among the alternative materials present in the pile, with
    equality accepted; an addition that would push the share past that floor is refused with
    `ERR_ALT_RAW_SUBSTITUTION_EXCEEDED`."

    Design: Corner/validations/alt_raw_share_exactly_at_the_substitution_cap_is_accepted
    """
    env, pile = _reference_bed_with_fly_ash_registered(api)

    after = validate_success(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(env["fly_ash"]["id"], 90.55, 1.0),
            ENGINEER_HEADERS,
        )
    )
    assert_amount(after["alt_raw_share_pct"], 8.00, "alt_raw_share_pct")
    assert_amount(after["as_received_tonnes"], 1131.83, "as_received_tonnes")
    assert_amount(after["dry_tonnes"], 1089.64, "dry_tonnes")
    assert len(after["additions"]) == 3
    assert after["status"] == "OPEN"


def test_the_ceiling_is_measured_on_the_as_received_basis_not_the_dry_one(api):
    """91.00 tonnes is 8.04 percent of the 1132.28 tonnes actually delivered and is refused,
    while the dry-basis figure for the accepted 90.55 delivery would have been 8.23 percent —
    a bed weighed the modules' way would have turned away a legal delivery. The refusal leaves
    the two-addition bed exactly as it stood.

    PRD: "Alternative raw materials are capped on an **as-received** basis, deliberately unlike
    the dry basis the modules use. After each addition, the pile's `alt_raw_share_pct` must be
    no greater than the smallest `max_substitution_pct` among the alternative materials present
    in the pile, with equality accepted; an addition that would push the share past that floor
    is refused with `ERR_ALT_RAW_SUBSTITUTION_EXCEEDED`."

    Design: Corner/validations/alt_raw_share_exactly_at_the_substitution_cap_is_accepted
    """
    env, pile = _reference_bed_with_fly_ash_registered(api)

    validate_error(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(env["fly_ash"]["id"], 91.00, 1.0),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_ALT_RAW_SUBSTITUTION_EXCEEDED.value,
        422,
    )

    unchanged = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert_amount(unchanged["alt_raw_share_pct"], 0.00, "alt_raw_share_pct")
    assert_amount(unchanged["dry_tonnes"], 1000.00, "dry_tonnes")
    assert_amount(unchanged["as_received_tonnes"], 1041.28, "as_received_tonnes")
    assert len(unchanged["additions"]) == 2


# ---------------------------------------------------------------------------
# validations: rung 91 demands exactly 100.00 across at least two components
# ---------------------------------------------------------------------------
def _three_component_payload(env, limestone_pct, code="DX", target_lsf=97.00):
    materials = env["materials"]
    return f.design_payload(
        env["plant_id"],
        [
            f.component(materials["limestone"]["id"], limestone_pct),
            f.component(materials["clay"]["id"], 16.00),
            f.component(materials["iron_ore"]["id"], 4.00),
        ],
        code=code,
        target_lsf=target_lsf,
        target_sm=1.50,
        target_am=0.80,
    )


def test_a_recipe_that_misses_one_hundred_by_a_hundredth_is_refused_at_authoring(api):
    """99.99 is not 100.00, and the gate refuses rather than normalising: a design that
    silently scaled the fractions would report as-designed oxides for a mix nobody wrote. The
    corrected recipe authors cleanly a moment later.

    PRD: "On design creation and design amendment, else `ERR_COMPONENTS_SUM_INVALID` (422)."

    Design: Corner/validations/design_components_that_do_not_sum_to_one_hundred_are_rejected
    """
    env = _reference_spine(api)

    validate_error(
        api.create_design(_three_component_payload(env, 79.99), ENGINEER_HEADERS),
        ApiErrorId.ERR_COMPONENTS_SUM_INVALID.value,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_designs(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0

    corrected = validate_success(
        api.create_design(_three_component_payload(env, 80.00), ENGINEER_HEADERS),
        201,
    )
    assert corrected["status"] == "DRAFT"
    assert_amount(corrected["as_designed_lsf"], 96.94, "as_designed_lsf")
    assert len(corrected["components"]) == 3


def test_a_single_component_recipe_is_refused_even_at_exactly_one_hundred(api):
    """The gate is two conditions, not one: a lone limestone entry sums to exactly 100.00 and
    is still refused, because a recipe needs at least two components.

    PRD: "The recipe must contain at least two components and every `raw_material_id` in it
    must resolve to a registered material, with the mass fractions summing to exactly 100.00 —
    an under-populated or unbalanced recipe is refused with `ERR_COMPONENTS_SUM_INVALID`, and an
    unresolvable material identifier is refused with `ERR_RAW_MATERIAL_NOT_FOUND`."

    Design: Corner/validations/design_components_that_do_not_sum_to_one_hundred_are_rejected
    """
    env = _reference_spine(api)

    validate_error(
        api.create_design(
            f.design_payload(
                env["plant_id"],
                [f.component(env["materials"]["limestone"]["id"], 100.00)],
                code="DY",
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_COMPONENTS_SUM_INVALID.value,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_designs(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0

    # Two components summing to 100.00 are accepted on the same endpoint.
    pair = fx.create_draft_design(api, env["plant_id"], env["materials"])
    assert len(pair["components"]) == 2
    assert_amount(pair["as_designed_lsf"], 96.98, "as_designed_lsf")


# ---------------------------------------------------------------------------
# validations: rung 92 fires on submission and admits equality
# ---------------------------------------------------------------------------
def test_a_design_sitting_exactly_on_its_lsf_tolerance_submits(api):
    """The achieved 96.94 is 1.50 from a 95.44 target and the default tolerance is 1.50, so the
    submission is accepted on the boundary. The same recipe pointed at a 90.00 target is still
    authorable, because this gate lives on the transition and not on the create.

    PRD: "Then the achieved lime saturation must sit near the target: the absolute difference
    between `as_designed_lsf` and `target_lsf`, rounded half up to two decimals, must be no
    greater than `module_tolerance_lsf`, with equality accepted."

    Design: Corner/validations/module_deviation_exactly_at_tolerance_passes_submit
    """
    env = _reference_spine(api)

    on_the_line = validate_success(
        api.create_design(
            _three_component_payload(env, 80.00, code="DT", target_lsf=95.44),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert on_the_line["status"] == "DRAFT"
    assert_amount(on_the_line["as_designed_lsf"], 96.94, "as_designed_lsf")
    assert_amount(on_the_line["module_tolerance_lsf"], 1.50, "module_tolerance_lsf")

    submitted = validate_success(
        api.submit_design(on_the_line["id"], ENGINEER_HEADERS)
    )
    assert submitted["status"] == "SUBMITTED"
    assert_amount(submitted["as_designed_lsf"], 96.94, "as_designed_lsf")

    far_off = validate_success(
        api.create_design(
            _three_component_payload(env, 80.00, code="DU", target_lsf=90.00),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert far_off["status"] == "DRAFT"
    assert_amount(far_off["as_designed_lsf"], 96.94, "as_designed_lsf")


def test_widening_the_tolerance_lets_the_refused_design_submit(api):
    """A 6.94 deviation is refused against the default 1.50 and the design stays in DRAFT; once
    the engineer amends the tolerance to 7.0 the identical recipe submits, which is what shows
    the gate reads the stored tolerance rather than a hard-coded one.

    PRD: "Then the achieved lime saturation must sit near the target: the absolute difference
    between `as_designed_lsf` and `target_lsf`, rounded half up to two decimals, must be no
    greater than `module_tolerance_lsf`, with equality accepted. A wider deviation is refused
    with `ERR_MODULE_TARGET_DEVIATION`."

    Design: Corner/validations/module_deviation_exactly_at_tolerance_passes_submit
    """
    env = _reference_spine(api)

    far_off = validate_success(
        api.create_design(
            _three_component_payload(env, 80.00, code="DU", target_lsf=90.00),
            ENGINEER_HEADERS,
        ),
        201,
    )

    validate_error(
        api.submit_design(far_off["id"], ENGINEER_HEADERS),
        ApiErrorId.ERR_MODULE_TARGET_DEVIATION.value,
        422,
    )
    still_draft = validate_success(api.get_design(far_off["id"], ENGINEER_HEADERS))
    assert still_draft["status"] == "DRAFT"

    widened = validate_success(
        api.patch_design(
            far_off["id"], {"module_tolerance_lsf": 7.0}, ENGINEER_HEADERS
        )
    )
    assert widened["status"] == "DRAFT"
    assert_amount(widened["module_tolerance_lsf"], 7.0, "module_tolerance_lsf")
    assert_amount(widened["as_designed_lsf"], 96.94, "as_designed_lsf")

    submitted = validate_success(api.submit_design(far_off["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# validations: rung 81 orders the outage window before anything seasonal
# ---------------------------------------------------------------------------
def test_an_outage_window_that_does_not_run_forwards_from_now_is_refused(api):
    """Three shapes fail the same rung: a zero-length window, a backwards one, and an ordered
    one that opens in July, before the clock. The July case is the telling one — July is a peak
    month, so a handler that reached the seasonality gate first would have named it. No row is
    written by any of the three, and the ordered October window is then accepted.

    PRD: "On kiln-run creation, outage creation and loadout order creation: `window_start` is
    strictly earlier than `window_end`, and `window_start` is at or after the logical clock,
    else `ERR_INVALID_WINDOW` (422)."

    Design: Corner/validations/outage_window_ending_before_it_starts_is_rejected
    """
    env = _reference_spine(api)
    kiln_id = env["kiln"]["id"]

    for start, end in (
        ("2026-10-03T00:00:00Z", "2026-10-03T00:00:00Z"),
        ("2026-10-05T00:00:00Z", "2026-10-03T00:00:00Z"),
        ("2026-07-01T00:00:00Z", "2026-07-03T00:00:00Z"),
    ):
        validate_error(
            api.create_outage(
                f.outage_payload(kiln_id, start, end), ENGINEER_HEADERS
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            422,
        )

    _rows, meta = validate_paginated(
        api.list_outages(ENGINEER_HEADERS, params={"kiln_id": kiln_id})
    )
    assert meta["total_count"] == 0

    ordered = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert ordered["status"] == "PLANNED"
    assert ordered["demand_season_class"] == "SHOULDER"


# ---------------------------------------------------------------------------
# validations: rung 108 pins both the flag and the caller
# ---------------------------------------------------------------------------
def test_a_peak_season_outage_needs_the_flag_and_a_plant_admin_together(api):
    """September is one of the plant's peak months, so the engineer is refused twice — once
    without the override and once with it — and only the PlantAdmin's override gets the window
    booked.

    PRD: "Because an outage in peak season costs the plant sales it cannot recover, a window
    intersecting any peak month is permitted only when `peak_season_override` is true **and**
    the caller is a `PlantAdmin`; that flag defaults to false, and a peak-season window without
    a `PlantAdmin` override is refused with `ERR_PEAK_SEASON_OUTAGE`."

    Design: Corner/validations/peak_season_outage_without_an_override_is_rejected
    """
    env = _reference_spine(api)
    kiln_id = env["kiln"]["id"]
    assert env["plant"]["peak_season_months"] == [5, 6, 7, 8, 9]

    plain = f.outage_payload(
        kiln_id, "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z", scope="COMBINED"
    )
    validate_error(
        api.create_outage(plain, ENGINEER_HEADERS),
        ApiErrorId.ERR_PEAK_SEASON_OUTAGE.value,
        422,
    )

    overridden = f.outage_payload(
        kiln_id,
        "2026-09-10T00:00:00Z",
        "2026-09-12T00:00:00Z",
        scope="COMBINED",
        peak_season_override=True,
    )
    validate_error(
        api.create_outage(overridden, ENGINEER_HEADERS),
        ApiErrorId.ERR_PEAK_SEASON_OUTAGE.value,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_outages(ENGINEER_HEADERS, params={"kiln_id": kiln_id})
    )
    assert meta["total_count"] == 0

    granted = validate_success(api.create_outage(overridden, ADMIN_HEADERS), 201)
    assert granted["status"] == "PLANNED"
    assert granted["peak_season_override"] is True
    assert granted["demand_season_class"] == "PEAK"
    assert granted["refractory_replaced"] is False


def test_the_season_class_takes_the_worst_month_the_window_touches(api):
    """A window living entirely in October is shoulder season and needs no override at all,
    while one that starts on 28 September and ends in October is classed PEAK on the strength
    of those three September days.

    PRD: "Its `demand_season_class` is computed from the calendar months the window intersects
    and takes the worst — that is, the highest-demand — class among them: `PEAK` if any
    intersected month is listed in the plant's `peak_season_months`, otherwise `OFF` only if
    every intersected month falls in December, January or February, and `SHOULDER` in every
    other case."

    Design: Corner/validations/peak_season_outage_without_an_override_is_rejected
    """
    env = _reference_spine(api)
    kiln_id = env["kiln"]["id"]

    shoulder = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert shoulder["demand_season_class"] == "SHOULDER"
    assert shoulder["peak_season_override"] is False

    spanning = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id,
                "2026-09-28T00:00:00Z",
                "2026-10-02T00:00:00Z",
                peak_season_override=True,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert spanning["demand_season_class"] == "PEAK"

    _rows, meta = validate_paginated(
        api.list_outages(
            ENGINEER_HEADERS,
            params={"kiln_id": kiln_id, "demand_season_class": "PEAK"},
        )
    )
    assert meta["total_count"] == 1

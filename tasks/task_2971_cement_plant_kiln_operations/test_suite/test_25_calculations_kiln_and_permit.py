"""Breadth coverage of the thermal ladder that turns fuel into clinker, of the declared
decimal precision of the emission and tonnage ledgers, and of the plant's rolling permit
figure that aggregates a whole month of burns.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_intensity
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    ENV_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)


def _assert_decimals(value, places: int, field: str) -> None:
    """A derived figure must not carry more decimals than the PRD declares for it."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    number = float(value)
    assert round(number, places) == number, (
        f"{field}: {value!r} carries more than {places} decimal places"
    )


def _sub_tier_burning_run(api):
    """A sealed 1000.00 dry-tonne bed under a BURNING run that has fired 79.00 tonnes of
    coal — 2133.00 gigajoules, which is short of the 600.00-tonne tier boundary."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    charged = fx.charge(api, run["id"], env["fuels"]["coal"]["id"], 79.00)
    return env, pile, run, charged


# ---------------------------------------------------------------------------
# calculations: the three-tier specific heat consumption ladder
# ---------------------------------------------------------------------------
def test_a_sub_tier_burn_selects_the_four_gigajoule_ladder_step(api):
    """2133.00 gigajoules over the kiln's nominal 3.60 gives a provisional 592.50 tonnes,
    which sits below the 600.00 boundary, so the burn is charged the wasteful 4.00 and
    yields 533.25 tonnes — not the 592.50 a nominal-consumption reading would report and
    not the 576.49 the 3.70 step would give.

    PRD: "**`effective_shc_gj_per_tonne`** is then selected from the provisional tonnage on
    a three-tier ladder, because small burns are thermally wasteful and large burns approach
    best practice: a provisional tonnage below 600.00 tonnes selects a specific heat
    consumption of 4.00 gigajoules per tonne; a provisional tonnage from 600.00 tonnes up to
    but not including 900.00 tonnes selects 3.70; and a provisional tonnage of 900.00 tonnes
    or more selects 3.45."

    Design: Corner/calculations/tier_one_burn_produces_the_low_efficiency_clinker_yield
    """
    env, _pile, _run, charged = _sub_tier_burning_run(api)

    assert_amount(charged["gross_energy_gj"], 2133.00, "gross_energy_gj")
    assert_amount(
        charged["provisional_clinker_tonnes"], 592.50, "provisional_clinker_tonnes"
    )
    assert_amount(
        charged["effective_shc_gj_per_tonne"], 4.00, "effective_shc_gj_per_tonne"
    )
    assert_amount(charged["clinker_tonnes"], 533.25, "clinker_tonnes")
    assert_amount(charged["tsr_pct"], 0.00, "tsr_pct")
    assert len(charged["fuel_charges"]) == 1
    assert_amount(charged["fuel_charges"][0]["energy_gj"], 2133.00, "energy_gj")

    # The kiln's nominal figure is untouched by the tier selection.
    kiln = validate_success(api.get_kiln(env["kiln"]["id"], ENGINEER_HEADERS))
    assert_amount(kiln["nominal_shc_gj_per_tonne"], 3.60, "nominal_shc_gj_per_tonne")


def test_the_sub_tier_yield_drives_the_runs_intensity_above_the_permit_cap(api):
    """Every downstream figure is keyed off the 533.25, so 746.55 kilograms of oxides over
    that smaller tonnage reads 1.400 against a 1.20 cap and the informational flag stands.

    PRD: "The run's own emission intensity, **`nox_intensity_kg_per_tonne`**, is
    `nox_emitted_kg` divided by `clinker_tonnes`, rounded half up to three decimals, and
    **`nox_intensity_breach`** is true when that intensity is strictly greater than the
    plant's `permit_nox_kg_per_tonne_clinker_cap`."

    Design: Corner/calculations/tier_one_burn_produces_the_low_efficiency_clinker_yield
    """
    env, _pile, _run, charged = _sub_tier_burning_run(api)

    assert_amount(charged["nox_emitted_kg"], 746.55, "nox_emitted_kg")
    assert_amount(charged["chlorine_input_kg"], 15.80, "chlorine_input_kg")
    assert_intensity(
        charged["nox_intensity_kg_per_tonne"], 1.400, "nox_intensity_kg_per_tonne"
    )
    assert charged["nox_intensity_breach"] is True

    plant = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_amount(
        plant["permit_nox_kg_per_tonne_clinker_cap"],
        1.20,
        "permit_nox_kg_per_tonne_clinker_cap",
    )
    assert_amount(
        plant["permit_nox_budget_remaining_kg"],
        1999253.45,
        "permit_nox_budget_remaining_kg",
    )


def test_the_sub_tier_burn_still_fits_the_frozen_bed_at_completion(api):
    """533.25 tonnes of clinker eat 826.54 dry tonnes of raw meal, comfortably inside the
    1000.00 the bed was sealed at, so completion succeeds and books the whole yield into the
    clinker silo as physically present but unreleased.

    PRD: "The pile must have been able to feed the burn: each tonne of clinker consumes 1.55
    dry tonnes of raw meal, so the clinker tonnage multiplied by 1.55 and rounded half up to
    two decimals must be no greater than the pile's frozen `dry_tonnes`, with equality
    allowed, else `ERR_INSUFFICIENT_KILN_FEED`."

    Design: Corner/calculations/tier_one_burn_produces_the_low_efficiency_clinker_yield
    """
    env, pile, run, _charged = _sub_tier_burning_run(api)

    fx.set_clock(api, "2026-08-01T12:00:00Z")
    completed = validate_success(api.complete_kiln_run(run["id"], OPERATOR_HEADERS))
    assert completed["process_state"] == "COMPLETED"
    assert_amount(completed["clinker_tonnes"], 533.25, "clinker_tonnes")

    fed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert_amount(fed["dry_tonnes"], 1000.00, "dry_tonnes")
    assert_amount(fed["consumed_dry_tonnes"], 826.54, "consumed_dry_tonnes")

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], OPERATOR_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 533.25, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 533.25, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 0.00, "available_tonnes")


def test_a_lone_dirty_burn_cannot_pass_the_rolling_permit_gate_at_release(api):
    """With this single burn the only member of the rolling window, the plant ledger reads
    the run's own 1.400 and the release is refused even though the free-lime reading is in
    specification.

    PRD: "Three further gates then apply in ladder order: the receiving clinker silo must be
    `OPEN`, else `ERR_SILO_BLOCKED`; the run must have at least one `FREE_LIME` test recorded
    and its newest reading must be no greater than the plant's `clinker_free_lime_max_pct`,
    else `ERR_FREE_LIME_OUT_OF_SPEC` — a run with no free-lime test at all fails this gate
    exactly as an out-of-specification one does; and the plant's
    `rolling_nox_intensity_kg_per_tonne` must be no greater than its
    `permit_nox_kg_per_tonne_clinker_cap`, with equality allowed, else
    `ERR_PERMIT_NOX_INTENSITY_EXCEEDED`."

    Design: Corner/calculations/tier_one_burn_produces_the_low_efficiency_clinker_yield
    """
    env, _pile, run, _charged = _sub_tier_burning_run(api)

    fx.set_clock(api, "2026-08-01T12:00:00Z")
    validate_success(api.complete_kiln_run(run["id"], OPERATOR_HEADERS))
    in_spec = fx.record_free_lime(api, run["id"], 1.20)
    assert in_spec["in_spec"] is True

    breached = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_intensity(
        breached["rolling_nox_intensity_kg_per_tonne"],
        1.400,
        "rolling_nox_intensity_kg_per_tonne",
    )

    validate_error(
        api.release_clinker(run["id"], QUALITY_HEADERS),
        ApiErrorId.ERR_PERMIT_NOX_INTENSITY_EXCEEDED.value,
        422,
    )

    quarantined_by_permit = validate_success(api.get_kiln_run(run["id"], ENV_HEADERS))
    assert quarantined_by_permit["process_state"] == "COMPLETED"
    assert quarantined_by_permit["quality_state"] == "PENDING_LAB"

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], QUALITY_HEADERS))
    assert_amount(silo["unreleased_tonnes"], 533.25, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 0.00, "available_tonnes")


# ---------------------------------------------------------------------------
# calculations: declared decimal precision of the derived figures
# ---------------------------------------------------------------------------
def _released_gas_burn(api):
    """The canonical clean burn: 45.00 tonnes of natural gas, completed and released."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    env["design"] = fx.create_approved_design(api, env["plant_id"], env["materials"])
    env["pile"] = fx.create_sealed_pile(
        api, env["plant_id"], env["design"]["id"], env["materials"]
    )
    env["run"] = fx.create_released_run(
        api,
        env["kiln"]["id"],
        env["pile"]["id"],
        env["clinker_silo"]["id"],
        env["fuels"]["gas"]["id"],
        45.00,
    )
    return env


def test_the_emission_intensity_carries_exactly_three_decimal_places(api):
    """216.00 over 583.78 is 0.3700024..., and the permit-grade figure must arrive rounded to
    0.370 rather than as the raw quotient, on the run and on the plant alike.

    PRD: "Emission intensities, being small numbers whose third digit matters to a permit, are
    carried to three decimal places."

    Design: Corner/calculations/nox_and_tonnage_precision_is_three_and_two_decimals
    """
    env = _released_gas_burn(api)

    run = validate_success(api.get_kiln_run(env["run"]["id"], ENV_HEADERS))
    assert_intensity(
        run["nox_intensity_kg_per_tonne"], 0.370, "nox_intensity_kg_per_tonne"
    )
    _assert_decimals(
        run["nox_intensity_kg_per_tonne"], 3, "nox_intensity_kg_per_tonne"
    )
    assert run["nox_intensity_breach"] is False

    plant = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_intensity(
        plant["rolling_nox_intensity_kg_per_tonne"],
        0.370,
        "rolling_nox_intensity_kg_per_tonne",
    )
    _assert_decimals(
        plant["rolling_nox_intensity_kg_per_tonne"],
        3,
        "rolling_nox_intensity_kg_per_tonne",
    )


def test_the_tonnage_and_budget_ledgers_carry_exactly_two_decimal_places(api):
    """The thermal chain and the permit ledger are two-decimal figures throughout: 2160.00
    gigajoules, a provisional 600.00 that lands exactly on the boundary and therefore selects
    3.70, a yield of 583.78, and an annual allowance drawn down to 1999784.00.

    PRD: "Tonnages, percentages, energies and monetary amounts are carried to two decimal
    places."

    Design: Corner/calculations/nox_and_tonnage_precision_is_three_and_two_decimals
    """
    env = _released_gas_burn(api)

    run = validate_success(api.get_kiln_run(env["run"]["id"], ENV_HEADERS))
    for field, expected in (
        ("gross_energy_gj", 2160.00),
        ("provisional_clinker_tonnes", 600.00),
        ("effective_shc_gj_per_tonne", 3.70),
        ("clinker_tonnes", 583.78),
        ("nox_emitted_kg", 216.00),
        ("chlorine_input_kg", 0.00),
        ("tsr_pct", 0.00),
    ):
        assert_amount(run[field], expected, field)
        _assert_decimals(run[field], 2, field)

    plant = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_amount(
        plant["permit_nox_budget_remaining_kg"],
        1999784.00,
        "permit_nox_budget_remaining_kg",
    )
    _assert_decimals(
        plant["permit_nox_budget_remaining_kg"], 2, "permit_nox_budget_remaining_kg"
    )
    # Clinker is not cement, so the cement ledger has not moved.
    assert_amount(
        plant["cement_tonne_balance_tonnes"], 0.00, "cement_tonne_balance_tonnes"
    )
    _assert_decimals(
        plant["cement_tonne_balance_tonnes"], 2, "cement_tonne_balance_tonnes"
    )


# ---------------------------------------------------------------------------
# calculations: the rolling ledger is a ratio of two sums
# ---------------------------------------------------------------------------
def _clean_burn_then_dirty_burn(api):
    """One released 45.00-tonne gas burn on 1 August, then a 79.00-tonne coal burn on
    2 August completed on the same kiln."""
    env = _released_gas_burn(api)
    clean = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_intensity(
        clean["rolling_nox_intensity_kg_per_tonne"],
        0.370,
        "rolling_nox_intensity_kg_per_tonne",
    )

    second_bed = fx.create_sealed_pile(
        api,
        env["plant_id"],
        env["design"]["id"],
        env["materials"],
        pile_code="PB",
    )
    dirty = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        second_bed["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T12:00:00Z",
    )
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    validate_success(api.light_kiln_run(dirty["id"], OPERATOR_HEADERS))
    fx.charge(api, dirty["id"], env["fuels"]["coal"]["id"], 79.00)
    fx.set_clock(api, "2026-08-02T12:00:00Z")
    completed = validate_success(api.complete_kiln_run(dirty["id"], OPERATOR_HEADERS))
    assert_amount(completed["clinker_tonnes"], 533.25, "clinker_tonnes")
    assert_amount(completed["nox_emitted_kg"], 746.55, "nox_emitted_kg")
    env["dirty_run"] = completed
    return env


def test_the_rolling_ledger_is_a_ratio_of_sums_not_a_mean_of_intensities(api):
    """962.55 kilograms over 1117.03 tonnes is 0.862, while the arithmetic mean of the two
    per-run intensities would read 0.885; the second completion must re-derive the figure over
    the whole window set in one write.

    PRD: "`rolling_nox_intensity_kg_per_tonne` is the sum of `nox_emitted_kg` over that set
    divided by the sum of `clinker_tonnes` over the same set, rounded half up to three
    decimals."

    Design: Corner/calculations/rolling_intensity_is_re_derived_over_the_whole_completed_set
    """
    env = _clean_burn_then_dirty_burn(api)

    plant = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_intensity(
        plant["rolling_nox_intensity_kg_per_tonne"],
        0.862,
        "rolling_nox_intensity_kg_per_tonne",
    )
    assert_amount(
        plant["permit_nox_budget_remaining_kg"],
        1999037.45,
        "permit_nox_budget_remaining_kg",
    )

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENV_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 1117.03, "tonnes_on_hand")

    # The per-run diagnostics are untouched by the plant-level aggregation.
    clean = validate_success(api.get_kiln_run(env["run"]["id"], ENV_HEADERS))
    assert_intensity(
        clean["nox_intensity_kg_per_tonne"], 0.370, "nox_intensity_kg_per_tonne"
    )
    dirty = validate_success(api.get_kiln_run(env["dirty_run"]["id"], ENV_HEADERS))
    assert_intensity(
        dirty["nox_intensity_kg_per_tonne"], 1.400, "nox_intensity_kg_per_tonne"
    )
    assert dirty["nox_intensity_breach"] is True


def test_a_dirty_burn_is_released_on_the_strength_of_the_clean_run_before_it(api):
    """The same 1.400 burn that no permit gate would pass on its own is releasable here,
    because the aggregate of the month — 0.862 — is the legal quantity.

    PRD: "Because the figure aggregates the whole month, a dirty coal-fired run can be
    released on the strength of a clean gas-fired run that preceded it, and the same dirty run
    cannot be released once the clean run is aborted out of the window — the aggregate, not
    the individual burn, is the legal quantity."

    Design: Corner/calculations/rolling_intensity_is_re_derived_over_the_whole_completed_set
    """
    env = _clean_burn_then_dirty_burn(api)
    run_id = env["dirty_run"]["id"]

    fx.record_free_lime(api, run_id, 1.20)
    released = validate_success(api.release_clinker(run_id, QUALITY_HEADERS))
    assert released["process_state"] == "COMPLETED"
    assert released["quality_state"] == "RELEASED"

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], QUALITY_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 1117.03, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 1117.03, "available_tonnes")

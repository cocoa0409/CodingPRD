"""Depth scenarios over the validation ladder's declared collisions and over the
inclusive boundaries: the three priority pairs of the ladder note, the free-lime
ceiling, the single-pass heat-consumption tier and the substitution ceiling.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals, assert_intensity
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    LAB_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)

BIG_PILE_ADDITIONS = ((2510.19, 2.0), (613.65, 12.0))


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_chlorine_excursion_outranks_the_lapsed_burn_test_authorisation(api):
    """A 63.00 tonne charge of RDF whose authorisation lapsed on 08-31 would take the run's
    chlorine input to 522.00 kg against a 500.00 kg permit; both rungs are violated and the
    answer is the chlorine one. Charging only 40.00 tonnes keeps chlorine at 338.00 kg and
    surfaces the expiry, which proves the lower rung is live rather than dead.

    PRD: "A chlorine-rich charge of a fuel whose trial-burn authorization has also lapsed
    reports `ERR_CHLORINE_INPUT_EXCEEDED`, not `ERR_BURN_TEST_EXPIRED`, because the safety
    rung at priority 70 precedes the temporal rung at priority 80."

    Design: Difficulty/priority_pair_validation_conflict/chlorine_input_priority_70_beats_expired_burn_test_priority_80
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    burn = fx.create_authorized_burn_test(
        api, env["plant_id"], env["fuels"]["rdf"]["id"], 35.00, 35.00, valid_days=30
    )
    assert burn["status"] == "AUTHORIZED"
    assert_instant_equals(burn["valid_from"], "2026-08-01T00:00:00Z", "valid_from")
    assert_instant_equals(burn["valid_until"], "2026-08-31T00:00:00Z", "valid_until")

    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(
        api,
        env["plant_id"],
        design["id"],
        env["materials"],
        additions=BIG_PILE_ADDITIONS,
    )

    # 45 days after the adjudication, so the authorisation is stale.
    fx.set_clock(api, "2026-09-15T00:00:00Z")
    run = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-09-15T00:00:00Z",
        window_end="2026-09-16T00:00:00Z",
    )
    coal_charged = validate_success(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 90.00),
            OPERATOR_HEADERS,
        ),
        200,
    )
    assert_amount(coal_charged["gross_energy_gj"], 2430.00, "gross_energy_gj")
    assert_amount(coal_charged["chlorine_input_kg"], 18.00, "chlorine_input_kg")
    assert_amount(coal_charged["tsr_pct"], 0.00, "tsr_pct")

    validate_error(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["rdf"]["id"], 63.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_CHLORINE_INPUT_EXCEEDED.value,
        422,
    )

    unchanged = validate_success(api.get_kiln_run(run["id"], OPERATOR_HEADERS))
    assert len(unchanged["fuel_charges"]) == 1
    assert_amount(unchanged["chlorine_input_kg"], 18.00, "chlorine_input_kg")
    assert_amount(unchanged["tsr_pct"], 0.00, "tsr_pct")

    # Under the chlorine ceiling, the temporal rung answers instead.
    validate_error(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["rdf"]["id"], 40.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_BURN_TEST_EXPIRED.value,
        422,
    )


def test_blocked_clinker_silo_outranks_the_short_stock_arithmetic(api):
    """A batch for 700.00 tonnes against a silo that is both BLOCKED and holding only
    583.78 tonnes reports the state rung; returning the silo to service and re-issuing the
    identical request then surfaces the fiscal rung, so both are live and only their order
    distinguishes the implementations. The state rung answers 409 and the fiscal rung 422.

    PRD: "A cement batch created against a clinker silo that is both `BLOCKED` and short of
    stock reports `ERR_SILO_BLOCKED`, not `ERR_INSUFFICIENT_CLINKER`, because the state rung
    at priority 62 precedes the fiscal rung at priority 103."

    Design: Difficulty/priority_pair_validation_conflict/silo_blocked_priority_62_beats_insufficient_clinker_priority_103
    """
    env = fx.released_clinker_environment(api)
    silo_id = env["clinker_silo"]["id"]

    blocked = validate_success(
        api.patch_silo(
            silo_id, {"status": "BLOCKED", "block_reason": "BIN_SCAN"}, ADMIN_HEADERS
        )
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["block_reason"] == "BIN_SCAN"
    assert_amount(blocked["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(blocked["available_tonnes"], 583.78, "available_tonnes")

    def batch_payload(version: int) -> dict:
        return f.cement_batch_payload(
            env["plant_id"],
            silo_id,
            env["cement_silo"]["id"],
            version,
            cement_type="TYPE_IL",
            clinker_tonnes_drawn=700.00,
            gypsum_pct=5.00,
            limestone_pct=8.00,
            blaine_target_m2_per_kg=400,
        )

    validate_error(
        api.create_cement_batch(batch_payload(blocked["version"]), ENGINEER_HEADERS),
        ApiErrorId.ERR_SILO_BLOCKED.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_cement_batches(ENGINEER_HEADERS, {"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    still_free = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(still_free["reserved_tonnes"], 0.00, "reserved_tonnes")

    reopened = validate_success(
        api.patch_silo(silo_id, {"status": "OPEN"}, ADMIN_HEADERS)
    )
    assert reopened["status"] == "OPEN"

    validate_error(
        api.create_cement_batch(batch_payload(reopened["version"]), ENGINEER_HEADERS),
        ApiErrorId.ERR_INSUFFICIENT_CLINKER.value,
        422,
    )


def test_limestone_limit_outranks_the_short_stock_arithmetic(api):
    """A TYPE_I batch asking for 8.00 percent interground limestone against 5.00 permitted,
    while also drawing 700.00 tonnes from 583.78 available, reports the constraint rung with
    HTTP 422; correcting only the recipe surfaces the 409 fiscal rung, and correcting the
    draw as well succeeds at 555.56 tonnes of cement.

    PRD: "And a `TYPE_I` batch asking for 8.00 percent interground limestone against an
    under-stocked silo reports `ERR_LIMESTONE_LIMIT_EXCEEDED`, not `ERR_INSUFFICIENT_CLINKER`,
    because the constraint rung at priority 96 precedes the fiscal rung at priority 103."

    Design: Difficulty/priority_pair_validation_conflict/limestone_limit_priority_96_beats_insufficient_clinker_priority_103
    """
    env = fx.released_clinker_environment(api)
    silo_id = env["clinker_silo"]["id"]

    open_silo = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert open_silo["status"] == "OPEN"
    assert_amount(open_silo["available_tonnes"], 583.78, "available_tonnes")

    def batch_payload(version: int, limestone_pct: float, drawn: float) -> dict:
        return f.cement_batch_payload(
            env["plant_id"],
            silo_id,
            env["cement_silo"]["id"],
            version,
            cement_type="TYPE_I",
            clinker_tonnes_drawn=drawn,
            gypsum_pct=5.00,
            limestone_pct=limestone_pct,
            blaine_target_m2_per_kg=400,
        )

    validate_error(
        api.create_cement_batch(
            batch_payload(open_silo["version"], 8.00, 700.00), ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_LIMESTONE_LIMIT_EXCEEDED.value,
        422,
    )

    untouched = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(untouched["reserved_tonnes"], 0.00, "reserved_tonnes")

    validate_error(
        api.create_cement_batch(
            batch_payload(untouched["version"], 5.00, 700.00), ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_INSUFFICIENT_CLINKER.value,
        422,
    )

    legal = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    batch = validate_success(
        api.create_cement_batch(
            batch_payload(legal["version"], 5.00, 500.00), ENGINEER_HEADERS
        ),
        201,
    )
    assert batch["cement_type"] == "TYPE_I"
    assert_amount(batch["total_batch_tonnes"], 555.56, "total_batch_tonnes")
    assert_amount(batch["gypsum_tonnes"], 27.78, "gypsum_tonnes")
    assert_amount(batch["limestone_tonnes"], 27.78, "limestone_tonnes")
    assert_amount(batch["cement_tonnes"], 555.56, "cement_tonnes")
    assert_amount(batch["so3_pct"], 2.87, "so3_pct")


# ---------------------------------------------------------------------------
# boundary_precision_check
# ---------------------------------------------------------------------------
def test_free_lime_exactly_at_the_plant_ceiling_is_in_spec(api):
    """A reading of exactly 1.50 against a 1.50 ceiling is in specification, leaves the run
    at PENDING_LAB and releases; the one hundredth more at 1.51 is out of specification and
    quarantines its run, after which the release is refused on the run's state.

    PRD: "For `FREE_LIME`, the `unit` is `PCT`, `spec_min` is null because the specification
    is one-sided, `spec_max` is the plant's `clinker_free_lime_max_pct`, and `in_spec` is
    true when the `value` is no greater than that inclusive ceiling."

    Design: Difficulty/boundary_precision_check/free_lime_exactly_at_the_plant_ceiling_is_in_spec
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    kiln_two = fx.create_kiln(api, env["plant_id"], code="K2")
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile_a = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PA"
    )
    pile_b = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PB"
    )

    run_a = fx.create_burning_run(
        api, env["kiln"]["id"], pile_a["id"], env["clinker_silo"]["id"]
    )
    run_b = fx.create_burning_run(
        api, kiln_two["id"], pile_b["id"], env["clinker_silo"]["id"]
    )
    fx.charge(api, run_a["id"], env["fuels"]["gas"]["id"], 45.00)
    fx.charge(api, run_b["id"], env["fuels"]["gas"]["id"], 45.00)
    fx.set_clock(api, "2026-08-01T12:00:00Z")
    fx.data_of(api.complete_kiln_run(run_a["id"], OPERATOR_HEADERS))
    fx.data_of(api.complete_kiln_run(run_b["id"], OPERATOR_HEADERS))

    # One hundredth over the ceiling.
    over = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.51, kiln_run_id=run_b["id"]), LAB_HEADERS
        ),
        201,
    )
    assert over["in_spec"] is False
    assert over["spec_min"] is None
    assert_amount(over["spec_max"], 1.50, "spec_max")
    assert over["unit"] == "PCT"

    quarantined = validate_success(api.get_kiln_run(run_b["id"], QUALITY_HEADERS))
    assert quarantined["quality_state"] == "QUARANTINED"

    # Exactly at the ceiling.
    at_ceiling = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.50, kiln_run_id=run_a["id"]), LAB_HEADERS
        ),
        201,
    )
    assert at_ceiling["in_spec"] is True
    assert at_ceiling["spec_min"] is None
    assert_amount(at_ceiling["spec_max"], 1.50, "spec_max")
    assert at_ceiling["unit"] == "PCT"

    pending = validate_success(api.get_kiln_run(run_a["id"], QUALITY_HEADERS))
    assert pending["quality_state"] == "PENDING_LAB"
    assert pending["process_state"] == "COMPLETED"
    assert_amount(pending["free_lime_pct"], 1.50, "free_lime_pct")

    released = validate_success(api.release_clinker(run_a["id"], QUALITY_HEADERS))
    assert released["quality_state"] == "RELEASED"

    # The out-of-specification reading has already driven run_b to QUARANTINED, so the
    # subject-state rung answers first: PRD 3.6 says a release on a run "whose quality
    # dimension sits at QUARANTINED ... is refused with ERR_INVALID_RUN_STATE".
    validate_error(
        api.release_clinker(run_b["id"], QUALITY_HEADERS),
        ApiErrorId.ERR_INVALID_RUN_STATE.value,
        409,
    )


def test_heat_consumption_tier_comes_from_the_provisional_tonnage_only(api):
    """80.00 tonnes of coal give 2160.00 GJ and a provisional tonnage of exactly 600.00,
    which selects 3.70 rather than 4.00; the reported output is therefore 583.78 tonnes even
    though that figure itself falls back inside the first tier, and the run completes because
    583.78 x 1.55 = 904.86 dry tonnes fits the 1000.00 tonne bed.

    PRD: "The tier is chosen from the provisional tonnage and is never re-chosen from the
    final result, even when the final result lands in a different tier from the one that
    produced it — which happens routinely, since dividing by a smaller heat consumption
    yields a larger tonnage."

    Design: Difficulty/boundary_precision_check/shc_tier_is_selected_from_the_provisional_tonnage_and_never_re_selected
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    assert_amount(pile["dry_tonnes"], 1000.00, "dry_tonnes")

    run = fx.create_burning_run(
        api, env["kiln"]["id"], pile["id"], env["clinker_silo"]["id"]
    )
    charged = validate_success(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 80.00),
            OPERATOR_HEADERS,
        ),
        200,
    )
    assert_amount(charged["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(charged["provisional_clinker_tonnes"], 600.00, "provisional_clinker_tonnes")
    assert_amount(charged["effective_shc_gj_per_tonne"], 3.70, "effective_shc_gj_per_tonne")
    assert_amount(charged["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_amount(charged["nox_emitted_kg"], 756.00, "nox_emitted_kg")
    assert_intensity(charged["nox_intensity_kg_per_tonne"], 1.295, "nox_intensity")
    assert charged["nox_intensity_breach"] is True

    fx.set_clock(api, "2026-08-01T12:00:00Z")
    completed = validate_success(api.complete_kiln_run(run["id"], OPERATOR_HEADERS))
    assert completed["process_state"] == "COMPLETED"
    assert_amount(completed["clinker_tonnes"], 583.78, "clinker_tonnes")

    burnt_pile = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert_amount(burnt_pile["consumed_dry_tonnes"], 904.86, "consumed_dry_tonnes")


def test_one_tonne_less_coal_drops_into_the_lower_heat_consumption_tier(api):
    """79.00 tonnes of coal give 2133.00 GJ and a provisional tonnage of 592.50, just under
    the 600.00 edge, so the ladder selects 4.00 and the output is 533.25 tonnes: one tonne
    less fuel costs 50.53 tonnes of clinker because the tier changed, not the arithmetic.

    PRD: "Both tier boundaries are inclusive upward, so a provisional figure of exactly
    600.00 selects 3.70 and one of exactly 900.00 selects 3.45."

    Design: Difficulty/boundary_precision_check/shc_tier_is_selected_from_the_provisional_tonnage_and_never_re_selected
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_burning_run(
        api, env["kiln"]["id"], pile["id"], env["clinker_silo"]["id"]
    )

    charged = validate_success(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 79.00),
            OPERATOR_HEADERS,
        ),
        200,
    )
    assert_amount(charged["gross_energy_gj"], 2133.00, "gross_energy_gj")
    assert_amount(charged["provisional_clinker_tonnes"], 592.50, "provisional_clinker_tonnes")
    assert_amount(charged["effective_shc_gj_per_tonne"], 4.00, "effective_shc_gj_per_tonne")
    assert_amount(charged["clinker_tonnes"], 533.25, "clinker_tonnes")


def test_substitution_rate_exactly_at_the_ceiling_is_accepted(api):
    """45.00 tonnes of RDF on top of 90.00 tonnes of coal put the run at exactly 25.00
    percent substitution against a 25.00 percent authorisation, and equality is allowed.

    PRD: "Second, substitution rate: the `tsr_pct` the run *would* carry after the charge
    must be no greater than the effective ceiling described next, with equality allowed, else
    `ERR_TSR_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/tsr_at_exactly_the_ceiling_is_allowed_and_one_hundredth_over_is_refused
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    fx.create_authorized_burn_test(
        api, env["plant_id"], env["fuels"]["rdf"]["id"], 25.00, 25.00
    )
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(
        api,
        env["plant_id"],
        design["id"],
        env["materials"],
        additions=BIG_PILE_ADDITIONS,
    )
    run = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )

    coal = fx.charge(api, run["id"], env["fuels"]["coal"]["id"], 90.00)
    assert_amount(coal["gross_energy_gj"], 2430.00, "gross_energy_gj")
    assert_amount(coal["tsr_pct"], 0.00, "tsr_pct")

    charged = validate_success(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["rdf"]["id"], 45.00),
            OPERATOR_HEADERS,
        ),
        200,
    )
    assert_amount(charged["gross_energy_gj"], 3240.00, "gross_energy_gj")
    assert_amount(charged["tsr_pct"], 25.00, "tsr_pct")
    assert_amount(charged["nox_emitted_kg"], 1028.70, "nox_emitted_kg")
    assert_amount(charged["chlorine_input_kg"], 378.00, "chlorine_input_kg")


def test_substitution_rate_one_hundredth_over_the_ceiling_is_refused(api):
    """One tonne more of the same RDF takes the run to 25.41 percent — 828.00 GJ of 3258.00,
    rounded half up to two decimals — which exceeds the same 25.00 percent ceiling, so the
    charge is refused and the run keeps only its coal.

    PRD: "**`tsr_pct`**, the thermal substitution rate, is the summed `energy_gj` of those
    charges whose fuel carries `is_alternative` true, divided by `gross_energy_gj`, multiplied
    by 100 and rounded half up to two decimals; it is 0.00 when the run has no energy at all."

    Design: Difficulty/boundary_precision_check/tsr_at_exactly_the_ceiling_is_allowed_and_one_hundredth_over_is_refused
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    fx.create_authorized_burn_test(
        api, env["plant_id"], env["fuels"]["rdf"]["id"], 25.00, 25.00
    )
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(
        api,
        env["plant_id"],
        design["id"],
        env["materials"],
        additions=BIG_PILE_ADDITIONS,
    )
    run = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    fx.charge(api, run["id"], env["fuels"]["coal"]["id"], 90.00)

    validate_error(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["rdf"]["id"], 46.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_TSR_CAP_EXCEEDED.value,
        422,
    )

    unchanged = validate_success(api.get_kiln_run(run["id"], OPERATOR_HEADERS))
    assert len(unchanged["fuel_charges"]) == 1
    assert_amount(unchanged["gross_energy_gj"], 2430.00, "gross_energy_gj")
    assert_amount(unchanged["tsr_pct"], 0.00, "tsr_pct")

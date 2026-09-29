"""Depth scenarios over the two-variant chemistry and the combinatorial formulas:
design-basis versus pile-basis modules, the per-run versus rolling NOx variants,
the nested substitution ceiling, and the mandated round-then-sum proportioning.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_intensity, assert_oxide
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    ENV_HEADERS,
    LAB_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)


# ---------------------------------------------------------------------------
# dual_variant_calc
# ---------------------------------------------------------------------------
def test_raw_mix_modules_diverge_between_design_and_pile_basis(api):
    """The same 80 / 16 / 4 recipe reports as_designed_lsf 96.94 from the design's dry
    mass fractions and as_blended_lsf 104.82 from the pile's own dry tonnages, because
    the 12 percent-moisture clay surrenders far less dry mass than its as-received
    tonnage suggests; lsf_deviation is therefore 7.82 and the pile cannot be sealed.

    PRD: "Each addition's dry contribution is its as-received tonnage multiplied by one
    minus its own `moisture_pct` divided by 100, rounded half up to two decimals;
    `dry_tonnes` is the sum of those per-addition rounded dry tonnages, itself rounded
    half up to two decimals."

    Design: Difficulty/dual_variant_calc/raw_mix_modules_diverge_between_design_basis_and_pile_basis
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    components = [
        f.component(materials["limestone"]["id"], 80.00),
        f.component(materials["clay"]["id"], 16.00),
        f.component(materials["iron_ore"]["id"], 4.00),
    ]
    design = fx.create_approved_design(
        api,
        plant["id"],
        materials,
        components=components,
        code="D1",
        target_lsf=97.00,
        target_sm=1.50,
        target_am=0.80,
    )

    # The design basis: dry mass fractions straight off the recipe.
    assert_oxide(design["as_designed_cao_pct"], 41.8000, "as_designed_cao_pct")
    assert_oxide(design["as_designed_sio2_pct"], 12.7200, "as_designed_sio2_pct")
    assert_oxide(design["as_designed_al2o3_pct"], 3.7600, "as_designed_al2o3_pct")
    assert_oxide(design["as_designed_fe2o3_pct"], 4.7200, "as_designed_fe2o3_pct")
    assert_amount(design["as_designed_lsf"], 96.94, "as_designed_lsf")
    assert_amount(design["as_designed_sm"], 1.50, "as_designed_sm")
    assert_amount(design["as_designed_am"], 0.80, "as_designed_am")

    pile = fx.create_open_pile(api, plant["id"], design["id"], pile_code="PL1")
    fx.data_of(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(materials["limestone"]["id"], 800.00, 2.0),
            ENGINEER_HEADERS,
        )
    )
    fx.data_of(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(materials["clay"]["id"], 160.00, 12.0),
            ENGINEER_HEADERS,
        )
    )

    # The pile basis: the same 80 / 16 / 4 ratio fed as-received.
    blended = validate_success(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(materials["iron_ore"]["id"], 40.00, 5.0),
            ENGINEER_HEADERS,
        )
    )
    assert_amount(blended["as_received_tonnes"], 1000.00, "as_received_tonnes")
    assert_amount(blended["dry_tonnes"], 962.80, "dry_tonnes")
    assert_oxide(blended["as_blended_cao_pct"], 42.5289, "as_blended_cao_pct")
    assert_oxide(blended["as_blended_sio2_pct"], 11.9402, "as_blended_sio2_pct")
    assert_oxide(blended["as_blended_al2o3_pct"], 3.5256, "as_blended_al2o3_pct")
    assert_oxide(blended["as_blended_fe2o3_pct"], 4.5883, "as_blended_fe2o3_pct")
    assert_amount(blended["as_blended_lsf"], 104.82, "as_blended_lsf")
    assert_amount(blended["as_blended_sm"], 1.47, "as_blended_sm")
    assert_amount(blended["as_blended_am"], 0.77, "as_blended_am")
    assert_amount(blended["lsf_deviation"], 7.82, "lsf_deviation")

    # 7.82 exceeds the default pile_lsf_tolerance of 2.00.
    validate_error(
        api.seal_pile(pile["id"], ENGINEER_HEADERS),
        ApiErrorId.ERR_PILE_LSF_OFF_TARGET.value,
    )


def test_per_run_nox_breach_does_not_block_release_gated_on_the_rolling_window(api):
    """A coal-fired run whose own intensity is 1.295 against a 1.20 cap still releases,
    because the permit gate reads the plant's thirty-day rolling aggregate of 0.833 over
    the clean gas-fired run and the dirty coal-fired one. The per-run flag and the
    release gate deliberately disagree about the same run.

    PRD: "It is essential to understand that the per-run figure is purely diagnostic:
    `nox_intensity_breach` is an informational flag and gates nothing whatsoever."

    Design: Difficulty/dual_variant_calc/per_run_nox_intensity_breaches_while_rolling_window_variant_permits_release
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile_a = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PA"
    )
    pile_b = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PB"
    )

    run0 = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        pile_a["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    run1 = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        pile_b["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )

    fx.data_of(api.light_kiln_run(run0["id"], OPERATOR_HEADERS))
    charged0 = validate_success(
        api.charge_fuel(
            run0["id"],
            f.fuel_charge_payload(env["fuels"]["gas"]["id"], 45.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(charged0["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(charged0["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_amount(charged0["nox_emitted_kg"], 216.00, "nox_emitted_kg")
    assert_intensity(charged0["nox_intensity_kg_per_tonne"], 0.370, "nox_intensity")
    assert charged0["nox_intensity_breach"] is False

    fx.set_clock(api, "2026-08-01T12:00:00Z")
    fx.data_of(api.complete_kiln_run(run0["id"], OPERATOR_HEADERS))

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    fx.data_of(api.light_kiln_run(run1["id"], OPERATOR_HEADERS))
    charged1 = validate_success(
        api.charge_fuel(
            run1["id"],
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 80.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(charged1["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(charged1["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_amount(charged1["nox_emitted_kg"], 756.00, "nox_emitted_kg")
    assert_intensity(charged1["nox_intensity_kg_per_tonne"], 1.295, "nox_intensity")
    assert charged1["nox_intensity_breach"] is True

    fx.set_clock(api, "2026-08-03T00:00:00Z")
    fx.data_of(api.complete_kiln_run(run1["id"], OPERATOR_HEADERS))
    fx.record_free_lime(api, run1["id"], 1.20)

    plant = validate_success(api.get_plant(env["plant_id"], QUALITY_HEADERS))
    assert_intensity(
        plant["rolling_nox_intensity_kg_per_tonne"], 0.833, "rolling_nox_intensity"
    )

    released = validate_success(api.release_clinker(run1["id"], QUALITY_HEADERS))
    assert released["quality_state"] == "RELEASED"
    assert released["process_state"] == "COMPLETED"

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], QUALITY_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 1167.56, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 583.78, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 583.78, "available_tonnes")


# ---------------------------------------------------------------------------
# combinatorial_formula
# ---------------------------------------------------------------------------
@pytest.fixture
def tsr_env(api):
    """A plant with two alternative fuels authorised to different ceilings, and one
    lit run holding 3000.00 dry tonnes of sealed feed."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    fx.create_authorized_burn_test(
        api, env["plant_id"], env["fuels"]["rdf"]["id"], 25.00, 25.00
    )
    fx.create_authorized_burn_test(
        api, env["plant_id"], env["fuels"]["tdf"]["id"], 20.00, 10.00
    )
    env["design"] = fx.create_approved_design(api, env["plant_id"], env["materials"])
    env["pile"] = fx.create_sealed_pile(
        api,
        env["plant_id"],
        env["design"]["id"],
        env["materials"],
        pile_code="PA",
        additions=((2510.19, 2.0), (613.65, 12.0)),
    )
    env["run"] = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        env["pile"]["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    return env


def test_tsr_ceiling_is_a_nested_minimum_over_permit_and_every_charged_fuel(api, tsr_env):
    """Coal plus RDF bring the run to exactly the 25.00 ceiling and are accepted, but a
    single tonne of TDF collapses the ceiling to min(35.00, 25.00, 10.00) = 10.00 and is
    refused; the run is left exactly as the RDF charge left it.

    PRD: "It is the smallest of the plant's `permit_max_tsr_pct` and, for each *distinct*
    alternative fuel charged on the run, that fuel's `authorized_max_tsr_pct` taken from
    the applicable trial-burn authorisation selected as §3.3 describes."

    Design: Difficulty/combinatorial_formula/tsr_ceiling_is_a_nested_min_over_permit_and_every_charged_fuel_authorization
    """
    run_id = tsr_env["run"]["id"]
    fx.charge(api, run_id, tsr_env["fuels"]["coal"]["id"], 90.00)
    after_rdf = validate_success(
        api.charge_fuel(
            run_id,
            f.fuel_charge_payload(tsr_env["fuels"]["rdf"]["id"], 45.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(after_rdf["gross_energy_gj"], 3240.00, "gross_energy_gj")
    assert_amount(after_rdf["tsr_pct"], 25.00, "tsr_pct")

    validate_error(
        api.charge_fuel(
            run_id,
            f.fuel_charge_payload(tsr_env["fuels"]["tdf"]["id"], 1.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_TSR_CAP_EXCEEDED.value,
    )

    unchanged = validate_success(api.get_kiln_run(run_id, OPERATOR_HEADERS))
    assert len(unchanged["fuel_charges"]) == 2
    assert_amount(unchanged["gross_energy_gj"], 3240.00, "gross_energy_gj")
    assert_amount(unchanged["tsr_pct"], 25.00, "tsr_pct")
    assert_amount(unchanged["nox_emitted_kg"], 1028.70, "nox_emitted_kg")
    assert_amount(unchanged["chlorine_input_kg"], 378.00, "chlorine_input_kg")


def test_tdf_alone_is_chargeable_up_to_its_own_lower_authorization(api, tsr_env):
    """The refusal above comes from the combination, not from TDF being unauthorised: on
    a run carrying only coal and TDF, 9.00 tonnes of TDF take the run to exactly 10.00
    percent substitution and are accepted.

    PRD: "Second, substitution rate: the `tsr_pct` the run *would* carry after the charge
    must be no greater than the effective ceiling described next, with equality allowed,
    else `ERR_TSR_CAP_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/tsr_ceiling_is_a_nested_min_over_permit_and_every_charged_fuel_authorization
    """
    run_id = tsr_env["run"]["id"]
    fx.charge(api, run_id, tsr_env["fuels"]["coal"]["id"], 90.00)
    charged = validate_success(
        api.charge_fuel(
            run_id,
            f.fuel_charge_payload(tsr_env["fuels"]["tdf"]["id"], 9.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(charged["gross_energy_gj"], 2700.00, "gross_energy_gj")
    assert_amount(charged["tsr_pct"], 10.00, "tsr_pct")
    assert len(charged["fuel_charges"]) == 2


def test_cement_tonnage_uses_round_then_sum_not_sum_then_round(api):
    """A TYPE_IL batch drawing 500.00 tonnes with 5.00 percent gypsum and 8.00 percent
    interground limestone reports total_batch_tonnes 574.71 but cement_tonnes 574.72:
    the reported product tonnage sums the already-rounded component tonnages.

    PRD: "Rounding before summing is mandatory here, and it is precisely why
    `cement_tonnes` can differ from `total_batch_tonnes` in the last decimal place; the
    round-then-sum figure is the correct one."

    Design: Difficulty/combinatorial_formula/cement_tonnage_uses_round_then_sum_not_sum_then_round
    """
    env = fx.released_clinker_environment(api)
    silo = fx.data_of(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))

    batch = validate_success(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                env["clinker_silo"]["id"],
                env["cement_silo"]["id"],
                silo["version"],
                cement_type="TYPE_IL",
                clinker_tonnes_drawn=500.00,
                gypsum_pct=5.00,
                limestone_pct=8.00,
                blaine_target_m2_per_kg=400,
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert_amount(batch["total_batch_tonnes"], 574.71, "total_batch_tonnes")
    assert_amount(batch["gypsum_tonnes"], 28.74, "gypsum_tonnes")
    assert_amount(batch["limestone_tonnes"], 45.98, "limestone_tonnes")
    assert_amount(batch["cement_tonnes"], 574.72, "cement_tonnes")
    assert batch["cement_tonnes"] != batch["total_batch_tonnes"]
    assert_amount(batch["so3_pct"], 2.85, "so3_pct")
    assert batch["status"] == "PLANNED"
    assert batch["feed_state"] == "FEED_READY"
    assert batch["strength_branch_state"] == "PENDING"
    assert batch["fineness_branch_state"] == "PENDING"

    reserved = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert_amount(reserved["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(reserved["available_tonnes"], 83.78, "available_tonnes")


def test_a_certificate_for_the_full_round_then_sum_tonnage_is_issuable(api):
    """The round-then-sum figure is the certifiable one: a mill certificate for exactly
    574.72 tonnes of the batch issues, which a sum-then-round implementation reporting
    574.71 would refuse with ERR_CERTIFIED_TONNES_EXCEED_BATCH.

    PRD: "And the batch must have the tonnage to give: the batch's
    `certified_tonnes_allocated` plus this certificate's `certified_tonnes` must be no
    greater than the batch's `cement_tonnes`, with equality allowed, else
    `ERR_CERTIFIED_TONNES_EXCEED_BATCH`."

    Design: Difficulty/combinatorial_formula/cement_tonnage_uses_round_then_sum_not_sum_then_round
    """
    env = fx.qualified_cement_environment(api)
    assert_amount(env["batch"]["cement_tonnes"], 574.72, "cement_tonnes")
    customer = fx.create_customer(api)
    certificate = fx.create_draft_certificate(api, env["batch"]["id"], customer["id"], 574.72)

    issued = validate_success(
        api.issue_mill_certificate(certificate["id"], QUALITY_HEADERS)
    )
    assert issued["status"] == "ISSUED"
    assert_amount(issued["certified_tonnes"], 574.72, "certified_tonnes")

    batch = validate_success(api.get_cement_batch(env["batch"]["id"], QUALITY_HEADERS))
    assert batch["status"] == "CERTIFIED"
    assert_amount(batch["certified_tonnes_allocated"], 574.72, "certified_tonnes_allocated")

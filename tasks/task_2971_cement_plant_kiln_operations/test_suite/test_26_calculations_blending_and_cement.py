"""Breadth coverage of the two mass bases that the module formulas run on, of the plant's
cement conservation ledger, and of the acceptance bounds a laboratory reading is judged
against.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_int, assert_oxide
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    QUALITY_HEADERS,
)


def _bed_with_an_iron_ore_delivery(api):
    """The reference bed — 820.00 + 180.00 dry tonnes at an as-blended LSF of 96.98 — with
    one further 10.00 tonne delivery of iron ore at 5.0 percent moisture dropped onto it."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    env["design"] = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_open_pile(api, env["plant_id"], env["design"]["id"])
    on_target = fx.add_reference_additions(api, pile["id"], env["materials"])
    assert_amount(on_target["as_blended_lsf"], 96.98, "as_blended_lsf")

    after = validate_success(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(env["materials"]["iron_ore"]["id"], 10.00, 5.0),
            ENGINEER_HEADERS,
        )
    )
    return env, pile, after


# ---------------------------------------------------------------------------
# calculations: the as-blended variant runs on the delivered dry mass
# ---------------------------------------------------------------------------
def test_an_iron_ore_delivery_moves_the_piles_own_chemistry(api):
    """The addition is weighed on the dry basis — 10.00 as received at 5.0 percent moisture
    is 9.50 dry — and the four oxides are re-derived over the new 1009.50 tonne total, which
    drags the bed's lime saturation from 96.98 down to 95.43.

    PRD: "For each oxide, multiply each addition's rounded dry tonnage by that addition's
    material content for the oxide, sum across the additions, divide by the pile's total dry
    tonnage, and round half up to four decimals, giving `as_blended_cao_pct`,
    `as_blended_sio2_pct`, `as_blended_al2o3_pct` and `as_blended_fe2o3_pct`."

    Design: Corner/calculations/pile_additions_never_rewrite_the_designs_own_basis
    """
    _env, _pile, after = _bed_with_an_iron_ore_delivery(api)

    assert_amount(after["as_received_tonnes"], 1051.28, "as_received_tonnes")
    assert_amount(after["dry_tonnes"], 1009.50, "dry_tonnes")
    assert_oxide(after["as_blended_cao_pct"], 42.4264, "as_blended_cao_pct")
    assert_oxide(after["as_blended_sio2_pct"], 13.6166, "as_blended_sio2_pct")
    assert_oxide(after["as_blended_al2o3_pct"], 4.0406, "as_blended_al2o3_pct")
    assert_oxide(after["as_blended_fe2o3_pct"], 2.4071, "as_blended_fe2o3_pct")
    assert_amount(after["as_blended_lsf"], 95.43, "as_blended_lsf")
    assert_amount(after["as_blended_sm"], 2.11, "as_blended_sm")
    assert_amount(after["as_blended_am"], 1.68, "as_blended_am")
    assert_amount(after["lsf_deviation"], 1.57, "lsf_deviation")
    assert_amount(after["alt_raw_share_pct"], 0.00, "alt_raw_share_pct")
    assert len(after["additions"]) == 3


def test_a_delivery_record_never_rewrites_the_approved_recipe(api):
    """The as-designed basis is a property of the recipe's dry mass fractions, so the design
    still reads 96.98 / 2.39 / 2.43 after the delivery that moved the bed to 95.43 — a shared
    recompute would have rewritten an APPROVED recipe from a weighbridge ticket.

    PRD: "The four **as-designed oxide contents** are recomputed on every authoring or
    amendment."

    Design: Corner/calculations/pile_additions_never_rewrite_the_designs_own_basis
    """
    env, pile, _after = _bed_with_an_iron_ore_delivery(api)

    design = validate_success(api.get_design(env["design"]["id"], ENGINEER_HEADERS))
    assert design["status"] == "APPROVED"
    assert_oxide(design["as_designed_cao_pct"], 42.8200, "as_designed_cao_pct")
    assert_oxide(design["as_designed_sio2_pct"], 13.6700, "as_designed_sio2_pct")
    assert_oxide(design["as_designed_al2o3_pct"], 4.0600, "as_designed_al2o3_pct")
    assert_oxide(design["as_designed_fe2o3_pct"], 1.6700, "as_designed_fe2o3_pct")
    assert_amount(design["as_designed_lsf"], 96.98, "as_designed_lsf")
    assert_amount(design["as_designed_sm"], 2.39, "as_designed_sm")
    assert_amount(design["as_designed_am"], 2.43, "as_designed_am")
    assert len(design["components"]) == 2

    # A 1.57 deviation is still inside the 2.00 the design allows on the ground.
    sealed = validate_success(api.seal_pile(pile["id"], ENGINEER_HEADERS))
    assert sealed["status"] == "SEALED"
    assert_amount(sealed["lsf_deviation"], 1.57, "lsf_deviation")


# ---------------------------------------------------------------------------
# calculations: cement mass conservation at plant level
# ---------------------------------------------------------------------------
def test_the_cement_balance_ignores_a_merely_reserved_order(api):
    """A reservation is a promise, not a shipment: the 120.00 tonnes are still standing in the
    silo, so the balance is the silo's 574.72 and not 694.72.

    PRD: "The plant's `cement_tonne_balance_tonnes` is the sum of `tonnes_on_hand` across all
    of the plant's silos whose `material_kind` is `CEMENT`, plus the sum of `loaded_tonnes`
    across all loadout orders on those silos whose status is `COMPLETED`, rounded to two
    decimals."

    Design: Corner/calculations/cement_balance_counts_only_completed_orders
    """
    env = fx.certificate_chain(api)

    order = validate_success(api.get_loadout_order(env["order"]["id"], LOGISTICS_HEADERS))
    assert order["status"] == "RESERVED"
    assert_amount(order["loaded_tonnes"], 0.00, "loaded_tonnes")

    cement = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(cement["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(cement["reserved_tonnes"], 120.00, "reserved_tonnes")
    assert_amount(cement["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(cement["available_tonnes"], 454.72, "available_tonnes")

    # The clinker silo still holds 83.78 tonnes and contributes nothing to the figure.
    clinker = validate_success(api.get_silo(env["clinker_silo"]["id"], LOGISTICS_HEADERS))
    assert clinker["material_kind"] == "CLINKER"
    assert_amount(clinker["tonnes_on_hand"], 83.78, "tonnes_on_hand")

    plant = validate_success(api.get_plant(env["plant_id"], LOGISTICS_HEADERS))
    assert_amount(
        plant["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )


def test_shipping_the_order_moves_the_tonnes_without_moving_the_balance(api):
    """Once the truck has gone the 120.00 tonnes have merely changed column — silo stock
    454.72 plus shipped 120.00 — and the plant total is still exactly 574.72.

    PRD: "Completing a loadout order leaves this balance unchanged because it moves tonnes
    from silo stock into shipped stock, and voiding a completed order leaves it unchanged
    because it moves them back; the balance changes only when cement is newly created by
    finish-grinding, or when the plant's set of silos changes."

    Design: Corner/calculations/cement_balance_counts_only_completed_orders
    """
    env = fx.certificate_chain(api)

    fx.set_clock(api, "2026-08-05T06:00:00Z")
    loading = validate_success(api.start_loading(env["order"]["id"], LOGISTICS_HEADERS))
    assert loading["status"] == "LOADING"

    shipped = validate_success(
        api.complete_loadout_order(
            env["order"]["id"], {"loaded_tonnes": 120.00}, LOGISTICS_HEADERS
        )
    )
    assert shipped["status"] == "COMPLETED"
    assert_amount(shipped["loaded_tonnes"], 120.00, "loaded_tonnes")

    cement = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(cement["tonnes_on_hand"], 454.72, "tonnes_on_hand")
    assert_amount(cement["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(cement["available_tonnes"], 454.72, "available_tonnes")

    plant = validate_success(api.get_plant(env["plant_id"], LOGISTICS_HEADERS))
    assert_amount(
        plant["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )

    customer = validate_success(
        api.get_customer(env["customer"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(customer["open_reserved_tonnes"], 0.00, "open_reserved_tonnes")
    assert_amount(customer["lifetime_loaded_tonnes"], 120.00, "lifetime_loaded_tonnes")


# ---------------------------------------------------------------------------
# calculations: acceptance bounds are read from the subject batch
# ---------------------------------------------------------------------------
def _type_three_batch_payload(api, env):
    """A 50.00 tonne TYPE_III batch drawn from the clinker left after the TYPE_IL grind."""
    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    return f.cement_batch_payload(
        env["plant_id"],
        env["clinker_silo"]["id"],
        env["cement_silo"]["id"],
        silo["version"],
        cement_type="TYPE_III",
        clinker_tonnes_drawn=50.00,
        gypsum_pct=5.00,
        limestone_pct=5.00,
        blaine_target_m2_per_kg=520,
    )


def _two_ground_batches_of_different_types(api):
    """B1 is the reference TYPE_IL grind; B3 is a small TYPE_III grind from what is left."""
    env = fx.released_clinker_environment(api)
    b1 = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    b3 = fx.create_ground_batch(
        api,
        env["plant_id"],
        env["clinker_silo"]["id"],
        env["cement_silo"]["id"],
        cement_type="TYPE_III",
        clinker_tonnes_drawn=50.00,
        gypsum_pct=5.00,
        limestone_pct=5.00,
        blaine_target_m2_per_kg=520,
    )
    assert b1["status"] == "GROUND"
    assert b3["status"] == "GROUND"
    return env, b1, b3


def test_the_same_blaine_reading_passes_one_batch_and_fails_another(api):
    """400 square metres per kilogram is comfortably inside the TYPE_IL band of 380 to 460 and
    a hundred units short of the TYPE_III band that begins at 500, so the identical number
    qualifies one grind and rejects the other.

    PRD: "For `BLAINE`, the `unit` is `M2_PER_KG`, `spec_min` and `spec_max` are the lower and
    upper ends of the batch's cement-type Blaine band from §2.11, and `in_spec` is true when
    the `value` lies within that band inclusive at both ends."

    Design: Corner/calculations/blaine_bounds_follow_the_subject_batchs_cement_type
    """
    env, b1, b3 = _two_ground_batches_of_different_types(api)

    coarse = validate_success(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, cement_batch_id=b3["id"]), LAB_HEADERS
        ),
        201,
    )
    assert coarse["unit"] == "M2_PER_KG"
    assert_int(coarse["spec_min"], 500, "spec_min")
    assert_int(coarse["spec_max"], 600, "spec_max")
    assert coarse["in_spec"] is False

    rejected = validate_success(api.get_cement_batch(b3["id"], QUALITY_HEADERS))
    assert rejected["fineness_branch_state"] == "FAILED"
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "FINENESS_OUT_OF_SPEC"

    fine = validate_success(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, cement_batch_id=b1["id"]), LAB_HEADERS
        ),
        201,
    )
    assert fine["unit"] == "M2_PER_KG"
    assert_int(fine["spec_min"], 380, "spec_min")
    assert_int(fine["spec_max"], 460, "spec_max")
    assert fine["in_spec"] is True

    passing = validate_success(api.get_cement_batch(b1["id"], QUALITY_HEADERS))
    assert passing["fineness_branch_state"] == "PASSED"
    assert passing["status"] == "GROUND"

    # The rejected 55.56 tonnes stay stranded alongside B1's not-yet-qualified cement.
    silo = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 630.28, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 630.28, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 0.00, "available_tonnes")


def test_the_small_type_three_batch_rounds_then_sums_its_component_tonnages(api):
    """50.00 tonnes of clinker at a combined 10 percent additive share gives an intermediate
    55.56, whose 5 percent shares round to 2.78 each, and it is those already-rounded figures
    the reported 55.56 tonnes of product is built from.

    PRD: "Third, `cement_tonnes` — the reported product tonnage — is the drawn clinker tonnage
    plus those two *already-rounded* component tonnages, that sum rounded half up to two
    decimals."

    Design: Corner/calculations/blaine_bounds_follow_the_subject_batchs_cement_type
    """
    env = fx.released_clinker_environment(api)
    fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )

    batch = validate_success(
        api.create_cement_batch(_type_three_batch_payload(api, env), ENGINEER_HEADERS),
        201,
    )
    assert batch["cement_type"] == "TYPE_III"
    assert_amount(batch["total_batch_tonnes"], 55.56, "total_batch_tonnes")
    assert_amount(batch["gypsum_tonnes"], 2.78, "gypsum_tonnes")
    assert_amount(batch["limestone_tonnes"], 2.78, "limestone_tonnes")
    assert_amount(batch["cement_tonnes"], 55.56, "cement_tonnes")


def test_the_type_three_sulphate_clears_the_rapid_hardening_ceiling(api):
    """The same 5.00 percent gypsum share that would sink a TYPE_I batch yields 2.87 percent
    here, well inside the 4.50 the rapid-hardening type is allowed, so the batch is accepted.

    PRD: "Fourth, the blended sulphate content `so3_pct` is computed from the step-two
    tonnages and the step-three total: the drawn clinker tonnage multiplied by 0.60, plus
    `gypsum_tonnes` multiplied by 46.50, plus `limestone_tonnes` multiplied by 0.05, that sum
    divided by `cement_tonnes`, rounded half up to two decimals."

    Design: Corner/calculations/blaine_bounds_follow_the_subject_batchs_cement_type
    """
    env = fx.released_clinker_environment(api)
    fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )

    batch = validate_success(
        api.create_cement_batch(_type_three_batch_payload(api, env), ENGINEER_HEADERS),
        201,
    )
    assert_amount(batch["so3_pct"], 2.87, "so3_pct")
    assert batch["status"] == "PLANNED"
    assert batch["feed_state"] == "FEED_READY"


def test_a_fineness_target_outside_the_subjects_band_is_refused_at_creation(api):
    """400 is a legal target for a TYPE_IL grind and an illegal one for a TYPE_III grind, and
    the refusal arrives as a shape error before any proportioning figure is derived.

    PRD: "`gypsum_pct` must lie between 2.00 and 7.00 inclusive and `blaine_target_m2_per_kg`
    must sit inside the cement type's Blaine band from §2.11 — either violation is a shape
    error and yields `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/blaine_bounds_follow_the_subject_batchs_cement_type
    """
    env = fx.released_clinker_environment(api)
    fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )

    payload = _type_three_batch_payload(api, env)
    payload["blaine_target_m2_per_kg"] = 400
    validate_error(
        api.create_cement_batch(payload, ENGINEER_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    accepted = validate_success(
        api.create_cement_batch(_type_three_batch_payload(api, env), ENGINEER_HEADERS),
        201,
    )
    assert_int(accepted["blaine_target_m2_per_kg"], 520, "blaine_target_m2_per_kg")

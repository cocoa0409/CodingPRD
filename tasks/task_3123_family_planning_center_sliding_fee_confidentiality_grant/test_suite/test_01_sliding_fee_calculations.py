"""Depth tests: FPL percentage, tier assignment, and sliding-fee charge rules."""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_fee_tier, create_patient, create_assessment, create_encounter,
    create_assessment_payload, create_catalog_entry_payload,
    setup_tx_clinic, setup_patient_with_assessment,
    get_patient,
    FPL_INCOME_H4_PCT_48, FPL_INCOME_H1_PCT_174,
    FPL_INCOME_FOR_PCT_100, FPL_INCOME_FOR_PCT_99,
    ENC_START, ENC_END,
)


def test_documented_assessment_selects_doc_only_full_discount_tier(api):
    """PRD §3.3: "A `DOCUMENTED` assessment is eligible for every candidate."
    PRD §3.3: "an optional `nominal_copay_cents` floor defaulting to 0 that the
    patient owes even at full discount".

    With tier A (100% discount, requires_documentation) available, a DOCUMENTED
    household-4 assessment at income 1500000 computes fpl_pct 48 and selects
    tier A; the encounter charge is the 500-cent copay floor.

    Design: Difficulty/dual_variant_calc/sliding_fee_documented_vs_self_declared
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    aff = clinic["affiliate"]
    patient = create_patient(
        aff["id"], external_ref="P1", date_of_birth="1990-05-01",
        insurance_policy_id="POL-1",
    )
    asm = create_assessment(
        patient, household_size=4, annual_income_cents=FPL_INCOME_H4_PCT_48,
        income_basis="DOCUMENTED",
    )
    assert asm["fpl_pct"] == 48, f"expected fpl_pct 48, got {asm['fpl_pct']}"
    assert asm["assigned_tier_code"] == "A", (
        f"expected tier A for DOCUMENTED, got {asm['assigned_tier_code']}"
    )
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           scheduled_start=ENC_START, scheduled_end=ENC_END)
    assert enc["patient_charge_cents"] == 500, (
        f"100% discount floored at 500-cent nominal copay, got "
        f"{enc['patient_charge_cents']}"
    )


def test_self_declared_assessment_excluded_from_doc_only_and_capped_tiers(api):
    """PRD §3.3: "A `SELF_DECLARED` assessment is eligible only for candidates
    whose `requires_documentation` is `false` **and** whose `discount_pct` does
    not exceed 80 — the self-declaration ceiling — regardless of any tier
    configuration to the contrary."
    PRD §3.3: "The dual variant between `DOCUMENTED` and `SELF_DECLARED` is
    intentional: identical income and household size can yield different
    `assigned_tier_code` values depending on which basis the assessment was
    recorded under."

    Same income/household as the documented case, but SELF_DECLARED excludes
    tier A and lands on tier B (80% discount): charge 20000 - 16000 = 4000,
    differing from the documented variant's 500.

    Design: Difficulty/dual_variant_calc/sliding_fee_documented_vs_self_declared
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    aff = clinic["affiliate"]
    patient = create_patient(
        aff["id"], external_ref="P2", date_of_birth="1990-05-01",
        insurance_policy_id="POL-2",
    )
    asm = create_assessment(
        patient, household_size=4, annual_income_cents=FPL_INCOME_H4_PCT_48,
        income_basis="SELF_DECLARED",
    )
    assert asm["fpl_pct"] == 48
    assert asm["assigned_tier_code"] == "B", (
        f"expected tier B for SELF_DECLARED, got {asm['assigned_tier_code']}"
    )
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           scheduled_start=ENC_START, scheduled_end=ENC_END)
    assert enc["patient_charge_cents"] == 4000, (
        f"80% discount on 20000 yields 4000, got {enc['patient_charge_cents']}"
    )
    assert enc["patient_charge_cents"] != 500, (
        "identical income and household size must yield a different charge "
        "under the SELF_DECLARED variant"
    )


def test_full_discount_still_owes_nominal_copay_floor(api):
    """PRD §3.2: "an optional `nominal_copay_cents` floor defaulting to 0 that
    the patient owes even at full discount".
    PRD §3.4: "the patient charge is then `full_fee_cents` minus that floored
    discount, with the further constraint that the charge never falls below the
    tier's `nominal_copay_cents` floor."

    At 100% discount on a 20000-cent service with a 500-cent copay, the charge
    is exactly 500 — the max() against the copay floor fires, not zero.

    Design: Difficulty/combinatorial_formula/sliding_fee_nominal_copay_floor_with_full_discount
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    patient = create_patient(clinic["affiliate"]["id"],
                             external_ref="F1", date_of_birth="1992-03-03")
    create_assessment(patient, household_size=4,
                      annual_income_cents=FPL_INCOME_H4_PCT_48,
                      income_basis="DOCUMENTED")
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           scheduled_start=ENC_START, scheduled_end=ENC_END)
    assert enc["patient_charge_cents"] == 500, (
        f"nominal copay floor binds at full discount, got "
        f"{enc['patient_charge_cents']}"
    )
    assert enc["patient_charge_cents"] != 0


def test_full_discount_copay_floor_is_max_not_subtraction(api):
    """PRD §3.4: "the patient charge is then `full_fee_cents` minus that floored
    discount, with the further constraint that the charge never falls below the
    tier's `nominal_copay_cents` floor."

    The copay floor is a lower bound on the charge: with fee 20000, tier A
    (100% discount, copay 500) the result is max(20000 - 20000, 500) == 500.

    Design: Difficulty/combinatorial_formula/sliding_fee_nominal_copay_floor_with_full_discount
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    patient = create_patient(clinic["affiliate"]["id"],
                             external_ref="F2", date_of_birth="1992-03-03")
    asm = create_assessment(patient, household_size=4,
                            annual_income_cents=FPL_INCOME_H4_PCT_48,
                            income_basis="DOCUMENTED")
    assert asm["assigned_tier_code"] == "A"
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           scheduled_start=ENC_START, scheduled_end=ENC_END)
    # full_fee - floor(full_fee * 100 / 100) = 0, raised to the 500 copay floor
    assert enc["patient_charge_cents"] == 500


def test_discount_floored_before_subtraction_yields_odd_cent(api):
    """PRD §3.4: "The discount in cents is the floor of `full_fee_cents`
    multiplied by the tier's `discount_pct` and divided by 100; the patient
    charge is then `full_fee_cents` minus that floored discount".
    PRD §2.6: "Where a calculation produces a discounted amount, the discount
    itself is floored to integer cents **before** being subtracted from the
    gross amount — round-then-subtract, never sum-then-round."

    floor(33333 * 50 / 100) = 16666; 33333 - 16666 = 16667. Flooring the net
    instead would give 16666 — 16667 is the only correct answer.

    Design: Difficulty/combinatorial_formula/sliding_fee_discount_floored_before_subtraction
    """
    clinic = setup_tx_clinic(service_code="STI_SCREEN", full_fee_cents=33333)
    patient = create_patient(clinic["affiliate"]["id"],
                             external_ref="R1", date_of_birth="1995-07-07")
    asm = create_assessment(patient, household_size=1,
                            annual_income_cents=FPL_INCOME_H1_PCT_174,
                            income_basis="DOCUMENTED")
    assert asm["fpl_pct"] == 174, f"expected fpl_pct 174, got {asm['fpl_pct']}"
    assert asm["assigned_tier_code"] == "C"
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           service_code="STI_SCREEN",
                           scheduled_start=ENC_START, scheduled_end=ENC_END)
    assert enc["patient_charge_cents"] == 16667, (
        f"floor applies to the discount, not the net: expected 16667, got "
        f"{enc['patient_charge_cents']}"
    )
    assert enc["patient_charge_cents"] != 16666


def test_round_then_subtract_differs_from_sum_then_round(api):
    """PRD §3.4: "each per-service discount is rounded down **before** any
    subtraction, and a multi-service visit sums the per-service rounded charges
    — round-per-line-then-sum; the alternative sum-then-round ordering is
    forbidden."

    The pinned evaluation order makes 16667 (not 16666) the charge for a
    50%-discounted 33333-cent service.

    Design: Difficulty/combinatorial_formula/sliding_fee_discount_floored_before_subtraction
    """
    clinic = setup_tx_clinic(service_code="STI_SCREEN", full_fee_cents=33333)
    patient = create_patient(clinic["affiliate"]["id"],
                             external_ref="R2", date_of_birth="1995-07-07")
    create_assessment(patient, household_size=1,
                      annual_income_cents=FPL_INCOME_H1_PCT_174,
                      income_basis="DOCUMENTED")
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           service_code="STI_SCREEN",
                           scheduled_start=ENC_START, scheduled_end=ENC_END)
    expected = 33333 - (33333 * 50 // 100)
    assert expected == 16667
    assert enc["patient_charge_cents"] == expected


def test_income_exactly_at_fpl_base_yields_100_and_falls_out_of_half_open_band(api):
    """PRD §3.3: "The `fpl_pct` is then the integer floor of
    `annual_income_cents` multiplied by 100 and divided by the applicable base
    — truncated toward zero. Income exactly equal to the base yields exactly
    100, not 99."
    PRD §3.2: "a `fpl_pct_max_exclusive` upper bound (the band is `[min, max)`)".

    Income 1506000 (exactly the household-1 base) yields fpl_pct 100, which is
    NOT < 100 and therefore lands in tier B, not tier A.

    Design: Difficulty/boundary_precision_check/fpl_exactly_100_excluded_from_lowest_band
    """
    clinic = setup_tx_clinic()
    patient = create_patient(clinic["affiliate"]["id"],
                             external_ref="PB", date_of_birth="1990-01-01")
    asm = create_assessment(patient, household_size=1,
                            annual_income_cents=FPL_INCOME_FOR_PCT_100,
                            income_basis="DOCUMENTED")
    assert asm["fpl_pct"] == 100, (
        f"income exactly equal to the base yields exactly 100, got "
        f"{asm['fpl_pct']}"
    )
    assert asm["assigned_tier_code"] == "B", (
        f"100 is not < 100 — half-open band excludes tier A, got "
        f"{asm['assigned_tier_code']}"
    )


def test_income_one_cent_below_fpl_base_yields_99_and_lowest_band(api):
    """PRD §3.3: "Candidate tiers are those whose half-open band contains
    `fpl_pct` — that is, `fpl_pct_min_inclusive` is less than or equal to
    `fpl_pct` and `fpl_pct` is strictly less than `fpl_pct_max_exclusive`."

    Income 1505999 (one cent below the household-1 base) floors to fpl_pct 99,
    which satisfies 0 <= 99 < 100 and lands in tier A: a one-cent income
    difference flips the assigned tier.

    Design: Difficulty/boundary_precision_check/fpl_exactly_100_excluded_from_lowest_band
    """
    clinic = setup_tx_clinic()
    patient = create_patient(clinic["affiliate"]["id"],
                             external_ref="PA", date_of_birth="1990-01-01")
    asm = create_assessment(patient, household_size=1,
                            annual_income_cents=FPL_INCOME_FOR_PCT_99,
                            income_basis="DOCUMENTED")
    assert asm["fpl_pct"] == 99, f"expected fpl_pct 99, got {asm['fpl_pct']}"
    assert asm["assigned_tier_code"] == "A", (
        f"99 < 100 lands in tier A, got {asm['assigned_tier_code']}"
    )

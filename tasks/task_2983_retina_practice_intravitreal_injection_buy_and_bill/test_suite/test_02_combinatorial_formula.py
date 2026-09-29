"""
Multi-term formulas whose rounding and branch order are pinned.

The billing split rounds each line independently before summation, and the
patient-responsibility waterfall keys its per-encounter cap on the coinsurance
rather than on the allowed total.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assert_money_cents
from test_helpers import factories as f


# ==========================================================================
# billing_units_rounded_per_line_before_summation
# ==========================================================================


def test_each_billing_line_rounds_half_up_independently_before_the_lines_are_added(
    depth,
):
    """
    0.06 ml drawn from a 0.27 ml vial at 40 mg/ml bills 2 + 8 = 10 units, not the
    11 that summing the milligrams first would produce.

    The PRD pins the order: "Each of those two milligram figures is then divided
    by the drug's `billing_unit_mg` and rounded half up to a whole number
    **independently**, producing `administered_billing_units` and
    `wasted_billing_units`. Only after both lines have been rounded are they added
    together to give `total_billed_billing_units`."  It then works this exact
    product: "The administered milligrams are 2.4, which rounds to 2 units; the
    wasted volume is 0.21 ml, or 8.4 mg, which rounds to 8 units; the total billed
    is therefore 10 units. Summing first would give 10.8 mg and round to 11 units
    — that answer is wrong and is rejected."  Wastage volume itself comes from
    "`wasted_ml` is the effective drug's `vial_fill_ml` less
    `administered_dose_ml`, rounded half up to three decimal places".

    Design: Difficulty/combinatorial_formula/billing_units_rounded_per_line_before_summation
    """
    depth.enc1
    documented = depth.document(
        depth.enc1["id"], clinician_id=depth.cl1["id"], administered_dose_ml=0.06
    )

    assert documented["status"] == "DOCUMENTED"
    assert documented["administered_dose_ml"] == 0.06
    assert round(float(documented["wasted_ml"]), 3) == 0.21
    assert documented["administered_billing_units"] == 2
    assert documented["wasted_billing_units"] == 8
    assert documented["total_billed_billing_units"] == 10
    assert documented["total_billed_billing_units"] != 11


def test_the_modifier_array_pins_laterality_first_then_the_wastage_modifier(depth):
    """
    The same documentation stamps `["RT", "JW"]` on a right-eye single-dose
    injection that discarded eight billable units.

    The PRD pins both positions: "Position zero is always laterality: `RT` when
    the encounter's `eye` is `OD`, `LT` when it is `OS`. For a `SINGLE_DOSE`
    effective product a wastage modifier is appended second — `JW` when
    `wasted_billing_units` is greater than zero, and `JZ` when it is exactly
    zero".  This encounter is on the `OD` eye of a `SINGLE_DOSE` product with
    eight wasted units, so both positions are determined.

    Design: Difficulty/combinatorial_formula/billing_units_rounded_per_line_before_summation
    """
    depth.enc1
    documented = depth.document(
        depth.enc1["id"], clinician_id=depth.cl1["id"], administered_dose_ml=0.06
    )

    assert documented["eye"] == "OD"
    assert documented["modifiers"] == f.modifiers("RT", "JW")


# ==========================================================================
# responsibility_waterfall_tier_cap_keyed_on_coinsurance
# ==========================================================================


def test_a_sub_threshold_coinsurance_halves_the_per_encounter_cap(depth, billing):
    """
    A coinsurance of 34400 cents sits below the 50000-cent high-tier threshold, so
    the 40000-cent per-encounter cap is halved and foundation relief lands at
    20000 rather than covering the balance in full.

    The PRD keys the cap on step 2's figure: "The per-encounter cap is keyed on the
    coinsurance computed in step 2, not on the allowed total. With no enrollment
    the cap is 0. When `coinsurance_cents` is greater than or equal to 50000 cents,
    the high tier applies and the cap is the enrollment's `per_encounter_cap_cents`
    in full. Below that threshold the cap is the enrollment's
    `per_encounter_cap_cents` multiplied by 0.5 and rounded half up to whole
    cents".  With `total_allowed_cents` of 172000 and a 0.2 rate,
    "`coinsurance_cents` is `total_allowed_cents` multiplied by the payer's
    `coinsurance_rate`, rounded half up to whole cents" gives 34400, and
    "`foundation_applied_cents` is the smallest of three quantities:
    `coinsurance_cents`, the per-encounter cap from step 4, and the remaining
    benefit" selects 20000 out of {34400, 20000, 500000}.

    Design: Difficulty/combinatorial_formula/responsibility_waterfall_tier_cap_keyed_on_coinsurance
    """
    depth.enc1_attested
    enrollment = depth.enrollment1

    response = depth.api.create_claim(
        f.claim_payload(injection_encounter_id=depth.enc1["id"]), billing
    )
    claim = validate_success(response, 201)

    assert_money_cents(
        claim,
        "total_allowed_cents",
        "coinsurance_cents",
        "foundation_applied_cents",
        "patient_responsibility_cents",
        "practice_writeoff_cents",
    )
    assert claim["total_allowed_cents"] == 172000
    assert claim["coinsurance_cents"] == 34400
    assert claim["coinsurance_cents"] < 50000
    assert claim["foundation_applied_cents"] == 20000
    assert claim["foundation_applied_cents"] != claim["coinsurance_cents"]
    assert claim["assistance_enrollment_id"] == enrollment["id"]


def test_the_residual_balance_survives_small_balance_relief_and_posts_to_the_ledger(
    depth, billing
):
    """
    The 14400-cent residue is above the 1000-cent relief threshold, so the patient
    owes all of it, the provisional payer shortfall is 0, and the enrollment's
    ledger absorbs exactly the applied relief.

    The PRD pins step 6 and step 7: "The pre-relief patient balance is
    `coinsurance_cents` less `foundation_applied_cents`" — 34400 - 20000 = 14400 —
    and "When that pre-relief balance is less than or equal to 1000 cents, the
    whole of it becomes a small-balance write-off and
    `patient_responsibility_cents` becomes 0; above that threshold the write-off is
    0 and `patient_responsibility_cents` is the full pre-relief balance".  On the
    provisional pass "the payer is assumed to pay exactly its share, so the paid
    total is treated as `total_allowed_cents` less `coinsurance_cents` and the payer
    shortfall is therefore 0".  Step 8 posts the ledger: "the selected
    enrollment's `benefit_used_cents` increases by `foundation_applied_cents`, and
    the enrollment flips `ACTIVE → EXHAUSTED` when its `benefit_used_cents` reaches
    or passes its `annual_benefit_cents`" — 20000 of a 500000 grant leaves it
    `ACTIVE`.

    Design: Difficulty/combinatorial_formula/responsibility_waterfall_tier_cap_keyed_on_coinsurance
    """
    depth.enc1_attested
    enrollment = depth.enrollment1
    claim = depth.claim(injection_encounter_id=depth.enc1["id"])

    assert claim["patient_responsibility_cents"] == 14400
    assert claim["practice_writeoff_cents"] == 0

    ledger = depth.read_enrollment(enrollment["id"])
    assert ledger["benefit_used_cents"] == 20000
    assert ledger["status"] == "ACTIVE"

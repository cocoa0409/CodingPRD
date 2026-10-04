"""Premium formula: tiers, baseline/excess split, variants, deductions (PRD §3.3)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_premium_payment_payload,
    make_enrollment, make_assessed_enrollment, make_payment, finalize_payment,
)

DPM = TEST_USERS["dairy_program_manager_headers"]





def test_premium_tier_below_bar_pays_zero(api):
    """PRD §3.3: "The tier percentage comes from the enrollment's `blended_score`: below 60 the tier is 0 percent; at least 60 but below 75 it is 5 percent; at least 75 but below 90 it is 8 percent; at least 90 it is 12 percent — every lower bound inclusive."
    PRD §3.3: "When the tier is 0 percent the farm is below the program bar: no
    premium and no excess bonus, so `gross_amount_cents` is 0 regardless of
    volume."

    Design: Corner/calculations/premium_tier_below_bar_pays_zero
    """
    enrollment = make_assessed_enrollment(env_score=59, welfare_score=59,
                                          baseline_volume_liters=8000,
                                          farm_name="Below Bar Farm")
    assert enrollment["blended_score"] == 59
    payment = make_payment(enrollment["id"], period="Q3",
                           declared_volume_liters=10000,
                           commodity_price_cents_per_liter=45)
    assert payment["premium_pct"] == 0
    assert payment["gross_amount_cents"] == 0


def test_premium_provisional_vs_final_diverge(api):
    """PRD §3.3: "`PROVISIONAL`, computed at creation, uses `declared_volume_liters` and zero non-conformance deductions. `FINAL` is produced by finalization: the `DairyProgramManager` supplies `metered_volume_liters` and `non_conformance_count`, the payment's `calc_variant` flips from `PROVISIONAL` to `FINAL` — a self-loop that keeps the payment in `CALCULATED` — and `premium_pct` and `gross_amount_cents` recompute with the metered volume and the actual deductions."
    PRD §3.3: "the base volume is the smaller of the period volume and `baseline_volume_liters`, and the excess volume is whatever the period volume exceeds the baseline by (zero when it does not). The gross is the round-half-up integer-cent value of the base volume times the commodity price times the effective percentage, plus the excess volume times the commodity price times the effective percentage plus one percentage point — the marginal excess bonus."
    PRD §3.3: "The effective premium percentage is the tier minus a deduction
    of 2 percentage points per non-conformance, floored at zero".

    Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_diverge
    """
    enrollment = make_assessed_enrollment(env_score=80, welfare_score=70,
                                          baseline_volume_liters=8000,
                                          farm_name="Elm Farm")
    assert enrollment["blended_score"] == 75  # tier 8%

    payment = make_payment(enrollment["id"], period="Q1",
                           declared_volume_liters=10000,
                           commodity_price_cents_per_liter=45)
    assert payment["calc_variant"] == "PROVISIONAL"
    assert payment["premium_pct"] == 8
    # 8000*45*0.08 + 2000*45*0.09 = 28800 + 8100
    assert payment["gross_amount_cents"] == 36900

    finalized = finalize_payment(payment["id"], metered_volume_liters=9000,
                                 non_conformance_count=1)
    assert finalized["calc_variant"] == "FINAL"
    assert finalized["status"] == "CALCULATED", "finalize is a self-loop"
    assert finalized["premium_pct"] == 6  # tier 8 minus 2 points
    # 8000*45*0.06 + 1000*45*0.07 = 21600 + 3150
    assert finalized["gross_amount_cents"] == 24750
    assert finalized["gross_amount_cents"] != payment["gross_amount_cents"]


def test_premium_provisional_ignores_metered_inputs(api):
    """PRD §3.3: "`PROVISIONAL`, computed at creation, uses `declared_volume_liters` and zero non-conformance deductions. `FINAL` is produced by finalization: the `DairyProgramManager` supplies `metered_volume_liters` and `non_conformance_count`, the payment's `calc_variant` flips from `PROVISIONAL` to `FINAL` — a self-loop that keeps the payment in `CALCULATED` — and `premium_pct` and `gross_amount_cents` recompute with the metered volume and the actual deductions."

    Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_diverge
    """
    enrollment = make_assessed_enrollment(env_score=80, welfare_score=70,
                                          baseline_volume_liters=8000)
    # Volume below baseline: no excess component in either variant.
    payment = make_payment(enrollment["id"], declared_volume_liters=5000,
                           commodity_price_cents_per_liter=45)
    assert payment["premium_pct"] == 8
    assert payment["gross_amount_cents"] == 18000  # 5000*45*0.08
    assert payment["metered_volume_liters"] is None
    assert payment["non_conformance_count"] == 0

    finalized = finalize_payment(payment["id"], metered_volume_liters=5000,
                                 non_conformance_count=2)
    assert finalized["premium_pct"] == 4  # 8 - 2*2
    assert finalized["gross_amount_cents"] == 9000  # 5000*45*0.04


def test_premium_tier_boundary_with_deduction(api):
    """PRD §3.3: "The tier percentage comes from the enrollment's `blended_score`: below 60 the tier is 0 percent; at least 60 but below 75 it is 5 percent; at least 75 but below 90 it is 8 percent; at least 90 it is 12 percent — every lower bound inclusive."
    PRD §3.3: "the base volume is the smaller of the period volume and `baseline_volume_liters`, and the excess volume is whatever the period volume exceeds the baseline by (zero when it does not). The gross is the round-half-up integer-cent value of the base volume times the commodity price times the effective percentage, plus the excess volume times the commodity price times the effective percentage plus one percentage point — the marginal excess bonus."

    Design: Difficulty/combinatorial_formula/premium_tier_boundary_with_deduction
    """
    enrollment = make_assessed_enrollment(env_score=70, welfare_score=50,
                                          baseline_volume_liters=8000,
                                          farm_name="Boundary Farm")
    assert enrollment["blended_score"] == 60, "boundary 60 is inclusive"

    payment = make_payment(enrollment["id"], period="Q2",
                           declared_volume_liters=8000,
                           commodity_price_cents_per_liter=40)
    assert payment["premium_pct"] == 5
    assert payment["gross_amount_cents"] == 16000  # 8000*40*0.05

    finalized = finalize_payment(payment["id"], metered_volume_liters=8000,
                                 non_conformance_count=1)
    assert finalized["premium_pct"] == 3  # 5 - 2*1
    assert finalized["gross_amount_cents"] == 9600  # 8000*40*0.03


def test_premium_tier_75_boundary_with_two_deductions(api):
    """PRD §3.3: "The tier percentage comes from the enrollment's `blended_score`: below 60 the tier is 0 percent; at least 60 but below 75 it is 5 percent; at least 75 but below 90 it is 8 percent; at least 90 it is 12 percent — every lower bound inclusive."
    PRD §3.3: "The effective premium percentage is the tier minus a deduction
    of 2 percentage points per non-conformance, floored at zero".

    Design: Difficulty/combinatorial_formula/premium_tier_boundary_with_deduction
    """
    enrollment = make_assessed_enrollment(env_score=80, welfare_score=70,
                                          baseline_volume_liters=8000)
    assert enrollment["blended_score"] == 75  # lower bound of tier 8, inclusive
    payment = make_payment(enrollment["id"], declared_volume_liters=1000,
                           commodity_price_cents_per_liter=40)
    assert payment["premium_pct"] == 8
    assert payment["gross_amount_cents"] == 3200  # 1000*40*0.08

    finalized = finalize_payment(payment["id"], metered_volume_liters=1000,
                                 non_conformance_count=2)
    assert finalized["premium_pct"] == 4  # 8 - 2*2
    assert finalized["gross_amount_cents"] == 1600  # 1000*40*0.04

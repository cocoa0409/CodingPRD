"""Dual-variant work-in-process valuation: ACTUAL vs PROVISIONAL."""
from test_helpers import (
    TEST_USERS,
    assert_valuation,
    get_build_order,
    get_success_data,
    get_wood_batch,
    setup_build_in_stage,
    setup_completed_instrument,
)

WM = TEST_USERS["workshop_manager_headers"]

# MODEL_B material 3,600,000; logs 100h RIM_BENDING + 30h SEASONING_CHECK.
EXPECTED_ACTUAL = 3_600_000 + 100 * 14_500 + 30 * 9_500  # 5,335,000
# Untaken from SEASONING: 40x9,500 + 200x21,000 + 160x24,000 = 8,420,000.
EXPECTED_PROVISIONAL = EXPECTED_ACTUAL + 8_420_000  # 13,755,000


def _seasoned_model_b_build():
    return setup_build_in_stage(
        "MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30}
    )


def test_wip_actual_and_provisional_diverge_on_same_logs(api):
    """PRD section 3.2: "The ACTUAL variant is then the allocated batch's material
    cost (zero while no batch is allocated) plus that labor sum".
    PRD section 3.2: the PROVISIONAL variant "adds planned labor for every forward
    transition not yet taken: planned hours are 120 for the entry into `RIM_BENT`,
    40 for `SEASONING`, 40 for `ACTION_REGULATION`, 200 for `VOICING`, and 160 for
    `COMPLETED`".

    Design: Difficulty/dual_variant_calc/wip_provisional_vs_actual_diverge_on_same_logs
    """
    ctx = _seasoned_model_b_build()
    valuation = get_success_data(api.get_build_valuation(ctx["build"]["id"], WM))
    assert_valuation(valuation)
    assert valuation["actual_wip_cents"] == EXPECTED_ACTUAL
    assert valuation["provisional_wip_cents"] == EXPECTED_PROVISIONAL
    assert valuation["delta_cents"] == EXPECTED_PROVISIONAL - EXPECTED_ACTUAL


def test_wip_stored_field_matches_actual_variant(api):
    """PRD section 2.10: "The ACTUAL variant, stored on the order as
    `wip_value_cents`, counts only what has already been consumed: the material cost
    of the allocated batch plus the rounded labor of every stage log."

    Design: Difficulty/dual_variant_calc/wip_provisional_vs_actual_diverge_on_same_logs
    """
    ctx = _seasoned_model_b_build()
    build = get_build_order(ctx["build"]["id"])
    assert build["wip_value_cents"] == 5_335_000
    assert build["status"] == "SEASONING"
    assert build["version"] == ctx["build"]["version"]


def test_wip_variants_converge_at_completion(api):
    """PRD section 3.2: "with identical logs the provisional figure is always at
    least the actual one, and the two are equal only at `COMPLETED`."
    PRD section 3.2: "the allocated batch moves to `CONSUMED` with its `version`
    incremented."
    Planned-hours MODEL_B: 3,600,000 + (120x14,500 + 40x9,500 + 40x9,500 +
    200x21,000 + 160x24,000) = 14,140,000 cents.

    Design: Corner/calculations/wip_variants_converge_at_completion
    """
    ctx = setup_completed_instrument("MODEL_B")
    valuation = get_success_data(api.get_build_valuation(ctx["build"]["id"], WM))
    assert_valuation(valuation)
    assert valuation["actual_wip_cents"] == 14_140_000
    assert valuation["provisional_wip_cents"] == 14_140_000
    assert valuation["delta_cents"] == 0
    assert get_wood_batch(ctx["batch"]["id"])["status"] == "CONSUMED"

"""Dual-variant calculations: cumulative-vs-window lot rates and the two rounding paths.

Difficulty queue A: dual_variant_calc. Corner queue B: calculations.
"""
from test_helpers import (
    LEVEL_CAP_HOURS,
    TEST_USERS,
    get_lot,
    get_success_data,
    observe,
    set_clock,
    setup_failed_unit_claim,
    setup_system_with_units,
)

from test_helpers import api_client

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: lot defect rate, cumulative vs trailing window ──────────

def _lot_with_failures(code: str, failed: int, total: int, threshold: float):
    """Commission `total` units on one lot, then fail the first `failed` of them at
    an instant the clock has left behind, so the trailing window is unambiguous."""
    serials = [f"{code}-U{i}" for i in range(1, total + 1)]
    ctx = setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=serials,
        unit_models=["IQ7"] * total, lot_code=f"LOT-{code}", embed_model_code="IQ7",
        replacement_model_code="IQ8", defect_threshold_pct=threshold,
        commissioned_at="2026-01-15T00:00:00Z", site_address=f"1 {code} Way",
    )
    set_clock("2026-03-05T00:00:00Z")
    for index in range(failed):
        observe(ctx["units"][index]["id"], 0.0, "2026-03-05T00:00:00Z")
    set_clock("2026-09-01T00:00:00Z")
    return ctx


def test_lot_cumulative_rate_decides_recall_while_failures_age_out(api):
    """PRD §3.5: "`failed_unit_count` counts every unit of the lot whose
    `monitored_status` is `FAILED`, with no regard to when the failure happened.
    Dividing the second by the first and multiplying by one hundred, rounded half-up
    to two decimal places, gives `defect_rate_cumulative_pct`. This cumulative figure
    is authoritative for the lot's status." PRD §3.5: "Otherwise the rounded
    cumulative percentage is compared against `defect_threshold_pct`: at or above the
    threshold the lot becomes `RECALL`".

    Design: Difficulty/dual_variant_calc/lot_defect_cumulative_vs_trailing_window
    """
    ctx = _lot_with_failures("DDV1", failed=4, total=10, threshold=5.0)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["failed_unit_count"] == 4
    assert lot["units_registered_count"] == 10
    assert lot["defect_rate_cumulative_pct"] == 40.0
    assert lot["lot_status"] == "RECALL"
    assert lot["corrective_action_required"] is True


def test_lot_trailing_window_rate_reports_zero_after_failures_age_out(api):
    """PRD §3.5: "`window_failed_unit_count` counts only units that entered `FAILED`
    at an instant inside the trailing ninety days ending at the current logical clock,
    inclusive of both ends, and `defect_rate_window_pct` is that count divided by the
    same registered-unit denominator, again to two decimal places. The window view
    never decides a status".

    Design: Difficulty/dual_variant_calc/lot_defect_cumulative_vs_trailing_window
    """
    ctx = _lot_with_failures("DDV1B", failed=4, total=10, threshold=5.0)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["window_failed_unit_count"] == 0, (
        "all four failures sit outside the trailing ninety-day window"
    )
    assert lot["defect_rate_window_pct"] == 0.0
    assert lot["defect_rate_cumulative_pct"] == 40.0, (
        "the window view leaves the authoritative cumulative rate unchanged"
    )
    assert lot["lot_status"] == "RECALL", "the status follows the cumulative view, not the window"


# ─── Queue A: labor per-component rounding vs single rounding ─────────

def _gold_labor_case(code: str, claimed_hours: float, commissioned_at: str):
    ctx = setup_failed_unit_claim(
        installer_code=code, claim_target="APPROVED", claimed_hours=claimed_hours,
        unit_serials=[f"{code}-U1"], unit_models=["IQ7"], lot_code=f"LOT-{code}",
        embed_model_code="IQ7", replacement_model_code="IQ8",
        commissioned_at=commissioned_at, site_address=f"2 {code} Way",
    )
    return ctx


def test_labor_amount_rounds_each_component_before_summing(api):
    """PRD §3.8: "The `labor_component_cents` is the allowed hours multiplied by the
    base rate, then by the level factor, then by the age factor, rounded half-up to a
    whole number of cents." PRD §3.8: "a `GOLD` installer billing two hours on a
    one-hundred-and-thirty-month system produces a labor component of 7013 cents and a
    diagnostic component of 3188 cents, for a net of 10201 cents".

    Design: Difficulty/dual_variant_calc/labor_per_component_vs_sum_then_round
    """
    ctx = _gold_labor_case("DDV2", claimed_hours=2.0, commissioned_at="2015-11-01T00:00:00Z")
    reimbursement = ctx["reimbursement"]
    assert reimbursement["level_factor"] == 1.10
    assert reimbursement["age_factor"] == 0.375
    assert reimbursement["allowed_hours"] == 2.0
    assert reimbursement["cap_applied"] is False
    assert reimbursement["labor_component_cents"] == 7013
    assert reimbursement["diagnostic_component_cents"] == 3188
    assert reimbursement["net_amount_cents"] == 10201


def test_labor_quote_reports_the_persisted_amount_and_the_single_rounding_alternative(api):
    """PRD §3.8: "a read-only quote view shows both variants side by side, reporting
    the persisted `net_amount_cents` alongside a `blended_total_cents` that reflects
    the single-rounding alternative and is never paid". PRD §3.8: "the two approaches
    disagree by exactly one cent on that input and agree on every input whose
    components happen to land on whole cents already".

    Design: Difficulty/dual_variant_calc/labor_per_component_vs_sum_then_round
    """
    ctx = _gold_labor_case("DDV2B", claimed_hours=2.0, commissioned_at="2015-11-01T00:00:00Z")
    reimbursement = ctx["reimbursement"]
    quote = get_success_data(api_client.get_labor_quote(reimbursement["id"], PLATFORM_ADMIN))
    assert quote["net_amount_cents"] == 10201, "the quote reproduces the persisted per-component amount"
    assert isinstance(quote["blended_total_cents"], int)
    assert quote["blended_total_cents"] == 10201 - 1, (
        "the single-rounding alternative lands one cent below the persisted amount on this input"
    )
    assert quote["allowed_hours"] == 2.0
    assert quote["age_factor"] == 0.375


def test_labor_amount_equals_the_single_rounded_amount_when_components_are_whole_cents(api):
    """PRD §3.8: "such as a `GOLD` installer billing four hours at ninety months,
    where both yield 34425".

    Design: Difficulty/dual_variant_calc/labor_per_component_vs_sum_then_round
    """
    ctx = _gold_labor_case("DDV2C", claimed_hours=4.0, commissioned_at="2019-03-01T00:00:00Z")
    reimbursement = ctx["reimbursement"]
    assert reimbursement["age_factor"] == 0.750
    assert reimbursement["allowed_hours"] == 4.0
    assert LEVEL_CAP_HOURS["GOLD"] == 4.0
    assert reimbursement["cap_applied"] is False
    assert reimbursement["net_amount_cents"] == 34425


# ─── Queue B: calculations ────────────────────────────────────────────

def test_lot_status_compares_the_rounded_percentage_against_the_threshold(api):
    """PRD §2.9: "A defect-rate percentage is carried to two decimal places with
    round-half-up, and the lot-status decision compares the rounded percentage against
    the threshold rather than the raw quotient." PRD §3.5: "at or above the threshold
    the lot becomes `RECALL`".

    Design: Corner/calculations/lot_threshold_boundary_rounds_before_comparing
    """
    ctx = _lot_with_failures("C8", failed=3, total=20, threshold=15.0)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["failed_unit_count"] == 3
    assert lot["units_registered_count"] == 20
    assert lot["defect_rate_cumulative_pct"] == 15.0
    assert lot["lot_status"] == "RECALL", (
        "15.00 percent meets the 15.0 threshold under the rounded comparison"
    )
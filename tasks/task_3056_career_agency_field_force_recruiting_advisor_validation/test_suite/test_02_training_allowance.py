"""Training-allowance draws: the flat and production-draw variants, the
pause-on-production branch and the allowance cap."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    fetch_contract,
    new_office,
    new_policy,
    setup_contracted_rep,
    set_clock,
    validate_error,
    validate_success,
    md_headers,
    any_headers,
)


def test_flat_and_production_draw_modes_pay_different_amounts():
    """PRD §3.3: "the flat mode draws 200000 cents per window and the
    production-draw mode draws 75000 cents for the same contract figures."

    Design: Difficulty/dual_variant_calc/training_allowance_flat_vs_production_draw
    """
    set_clock()
    office = new_office()

    flat = setup_contracted_rep(office["id"], name="Flat Mode Advisor", mode="FLAT_MONTHLY",
                                validation_requirement_cents=300000,
                                training_allowance_total_cents=1200000)
    draw = setup_contracted_rep(office["id"], name="Draw Mode Advisor", mode="PRODUCTION_DRAW",
                                validation_requirement_cents=300000,
                                training_allowance_total_cents=1200000)

    flat_after = validate_success(api_client.draw_training_allowance(flat["contract"]["id"], md_headers))
    draw_after = validate_success(api_client.draw_training_allowance(draw["contract"]["id"], md_headers))

    assert flat_after["training_allowance_paid_cents"] == 200000
    assert draw_after["training_allowance_paid_cents"] == 75000


def test_the_two_modes_never_pay_the_same_instalment():
    """PRD §3.3: "The two modes are genuinely different products: the flat mode
    draws 200000 cents per window and the production-draw mode draws 75000 cents
    for the same contract figures."

    Design: Difficulty/dual_variant_calc/training_allowance_flat_vs_production_draw
    """
    set_clock()
    office = new_office()

    flat = setup_contracted_rep(office["id"], name="Flat Differ", mode="FLAT_MONTHLY")
    draw = setup_contracted_rep(office["id"], name="Draw Differ", mode="PRODUCTION_DRAW")

    flat_after = validate_success(api_client.draw_training_allowance(flat["contract"]["id"], md_headers))
    draw_after = validate_success(api_client.draw_training_allowance(draw["contract"]["id"], md_headers))

    assert flat_after["training_allowance_paid_cents"] == 200000
    assert draw_after["training_allowance_paid_cents"] == 75000
    assert flat_after["training_allowance_paid_cents"] != draw_after["training_allowance_paid_cents"]


def test_production_draw_amount_is_a_quarter_of_the_requirement():
    """PRD §3.3: "the draw is the contract's `validation_requirement_cents`
    multiplied by 0.25 and rounded half up to the nearest cent, which is 75000
    cents for a 300000-cent requirement."

    Design: Difficulty/dual_variant_calc/training_allowance_flat_vs_production_draw
    """
    set_clock()
    office = new_office()
    draw = setup_contracted_rep(office["id"], name="Draw Quarter", mode="PRODUCTION_DRAW",
                                validation_requirement_cents=300000)

    after = validate_success(api_client.draw_training_allowance(draw["contract"]["id"], md_headers))
    assert after["training_allowance_paid_cents"] == pytest.approx(75000, abs=1)


def test_draw_pauses_once_the_product_requirement_is_met():
    """PRD §3.3: "if the product requirement is met, the draw is zero: the
    allowance *pauses*, it does not repay, and no clawback is taken from an
    advisor who has begun producing."
    PRD §3.3: "The threshold is the contract's `validation_requirement_cents`
    multiplied by 0.35" ... "so a 300000-cent requirement sets the threshold at
    105000 cents."

    Design: Corner/calculations/training_allowance_draw_pauses_once_the_product_requirement_is_met
    """
    set_clock()
    office = new_office()
    ctx = setup_contracted_rep(office["id"], name="Xena Pause", mode="FLAT_MONTHLY",
                               validation_requirement_cents=300000,
                               training_allowance_total_cents=1200000)

    first = validate_success(api_client.draw_training_allowance(ctx["contract"]["id"], md_headers))
    assert first["training_allowance_paid_cents"] == 200000

    # A 510000-cent premium credit is 204000 cents, comfortably over 105000.
    new_policy(ctx["advisor"]["id"], annual_premium_cents=510000,
               policy_number="NM-C401", issue_date="2026-09-04T00:00:00Z")

    second = validate_success(api_client.draw_training_allowance(ctx["contract"]["id"], md_headers))
    assert second["training_allowance_paid_cents"] == 200000, \
        "the allowance paused, it did not accrue a second instalment"
    assert second["training_allowance_paid_cents"] != 400000


def test_draw_beyond_the_allowance_total_is_refused():
    """PRD §3.3: "A draw that would push `training_allowance_paid_cents` beyond
    `training_allowance_total_cents` is refused with `ERR_ALLOWANCE_CAP_EXCEEDED`
    at the payment-required status rather than being silently truncated."

    Design: Corner/errors/training_allowance_draw_beyond_the_total_is_rejected
    """
    set_clock()
    office = new_office()
    ctx = setup_contracted_rep(office["id"], name="Kit Allowance", mode="FLAT_MONTHLY",
                               validation_requirement_cents=300000,
                               training_allowance_total_cents=250000)

    first = validate_success(api_client.draw_training_allowance(ctx["contract"]["id"], md_headers))
    assert first["training_allowance_paid_cents"] == 200000

    response = api_client.draw_training_allowance(ctx["contract"]["id"], md_headers)
    validate_error(response, ApiErrorId.ERR_ALLOWANCE_CAP_EXCEEDED.value)

    after = fetch_contract(ctx["contract"]["id"])
    assert after["training_allowance_paid_cents"] == 200000
    assert after["training_allowance_total_cents"] == 250000


def test_each_successful_draw_creates_one_allowance_ledger_row():
    """PRD §3.3: "Each successful draw also creates a commission credit row of
    type `TRAINING_ALLOWANCE` for the advisor, which is an allowance ledger
    entry and is excluded from production attainment and from override accrual."

    Design: Corner/errors/training_allowance_draw_beyond_the_total_is_rejected
    """
    set_clock()
    office = new_office()
    ctx = setup_contracted_rep(office["id"], name="Kit Ledger", mode="FLAT_MONTHLY",
                               validation_requirement_cents=300000,
                               training_allowance_total_cents=250000)

    validate_success(api_client.draw_training_allowance(ctx["contract"]["id"], md_headers))
    refused = api_client.draw_training_allowance(ctx["contract"]["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_ALLOWANCE_CAP_EXCEEDED.value)

    rows = validate_success(api_client.list_advisor_commission_credits(
        ctx["advisor"]["id"], any_headers,
        {"credit_type": "TRAINING_ALLOWANCE"}))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    assert len(rows) == 1, "the refused draw must not post a second ledger row"
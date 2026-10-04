"""Violation penalties: provisional projection vs final cure, the order-level
cap, and segregation of duties on confirmation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assess_penalty,
    assert_violation_penalty,
    confirm_penalty,
    expected_final_penalty,
    expected_provisional_penalty,
    setup_monitored_order,
    validate_error,
)

_MONITOR_1 = TEST_USERS["compliance_monitor_headers"]  # cm-1


def test_penalty_provisional_projection_vs_final_cure():
    """PRD section 3.4: "`provisional_days` is fixed at 30 days, and
    `provisional_amount_cents` is the severity's per-day rate (§2.7)
    multiplied by 30, capped at the order's `max_penalty_cents`."
    PRD section 3.4: "`final_days` is the number of whole days from
    `detected_on` to `cured_on`, floored, and never less than 1;
    `final_amount_cents` is the per-day rate multiplied by `final_days`,
    capped at the order's `max_penalty_cents`."
    PRD section 2.7: "The per-day civil penalty rates are 1,000,000 cents for
    a `STANDARD` violation, 4,353,000 cents for an `AGGRAVATED` violation, and
    5,000,000 cents for an `EGREGIOUS` violation."

    Design: Difficulty/dual_variant_calc/penalty_provisional_projection_vs_final_cure
    """
    bundle = setup_monitored_order()
    order_id = bundle["order"]["id"]

    penalty = assess_penalty(
        order_id, severity="AGGRAVATED", detected_on="2026-10-01T00:00:00Z",
        description="Billing disclosures still deceptive",
    )
    assert_violation_penalty(penalty)
    expected_prov = expected_provisional_penalty("AGGRAVATED", 500_000_000)
    assert penalty["provisional_days"] == 30
    assert penalty["provisional_amount_cents"] == expected_prov["provisional_amount_cents"] == 130_590_000
    assert penalty["status"] == "ASSESSED_PROVISIONAL"
    assert penalty["assessed_by_user_id"] == "cm-1"

    confirmed = confirm_penalty(penalty["id"], cured_on="2026-10-11T00:00:00Z")
    assert confirmed["status"] == "CONFIRMED"
    expected_final = expected_final_penalty(
        "AGGRAVATED", "2026-10-01T00:00:00Z", "2026-10-11T00:00:00Z", 500_000_000
    )
    assert confirmed["final_days"] == expected_final["final_days"] == 10
    assert confirmed["final_amount_cents"] == expected_final["final_amount_cents"] == 43_530_000
    assert confirmed["provisional_amount_cents"] != confirmed["final_amount_cents"], (
        "same severity and detected_on: the 30-day projection must differ from the 10-day cure"
    )


def test_penalty_provisional_amount_capped_at_order_maximum():
    """PRD section 3.4: "`provisional_days` is fixed at 30 days, and
    `provisional_amount_cents` is the severity's per-day rate (§2.7)
    multiplied by 30, capped at the order's `max_penalty_cents`."

    Design: Corner/calculations/penalty_provisional_amount_capped_at_order_maximum
    """
    bundle = setup_monitored_order(max_penalty_cents=100_000_000)
    penalty = assess_penalty(
        bundle["order"]["id"],
        severity="EGREGIOUS",
        detected_on="2026-10-01T00:00:00Z",
        description="Knowing violation of the billing prohibition",
    )
    assert penalty["provisional_days"] == 30
    assert penalty["provisional_amount_cents"] == 100_000_000, (
        "min(5000000 * 30, max_penalty_cents) must clamp to the order cap, not 150000000"
    )
    assert penalty["status"] == "ASSESSED_PROVISIONAL"
    assert penalty["assessed_by_user_id"] == "cm-1"


def test_sod_penalty_confirm_by_assessing_user_rejected():
    """PRD section 3.4: "Segregation of duties forbids self-confirmation — if
    the confirming monitor's identity equals `assessed_by_user_id`, the
    request fails with `ERR_SOD_PENALTY_CONFIRM`."

    Design: Corner/cross_cutting_layers/sod_penalty_confirm_by_assessing_user_rejected
    """
    bundle = setup_monitored_order()
    penalty = assess_penalty(
        bundle["order"]["id"],
        severity="AGGRAVATED",
        detected_on="2026-10-01T00:00:00Z",
        description="Billing disclosures still deceptive",
    )
    assert penalty["assessed_by_user_id"] == "cm-1"

    self_confirm = api_client.transition_violation_penalty(
        penalty["id"],
        {"target_state": "CONFIRMED", "cured_on": "2026-10-06T00:00:00Z"},
        _MONITOR_1,
    )
    validate_error(self_confirm, ApiErrorId.ERR_SOD_PENALTY_CONFIRM)

    confirmed = confirm_penalty(penalty["id"], cured_on="2026-10-06T00:00:00Z")
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["final_days"] == 5
    assert confirmed["final_amount_cents"] == 21_765_000
    assert confirmed["confirmed_by_user_id"] == "cm-2"

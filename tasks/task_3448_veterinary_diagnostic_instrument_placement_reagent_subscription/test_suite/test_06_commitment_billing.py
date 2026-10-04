"""Commitment periods: attribution variants, shortfall billing, payment, OCC (PRD §2.8, §2.9, §3.5, §3.6)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_2026_10_02,
    CLOCK_2026_10_05,
    CLOCK_2026_11_01,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_closed_period_shape,
    assert_open_period_shape,
    cancel_reagent_order,
    close_commitment_period,
    close_commitment_period_payload,
    current_agreement_version,
    fulfill_reagent_order,
    get_agreement,
    get_clinic,
    list_commitment_periods,
    place_reagent_order,
    reagent_line,
    record_exact_payment,
    record_payment_payload,
    request_renegotiation,
    resolve_renegotiation,
    setup_agreement_with_closed_period,
    setup_clinic_with_active_reagent_commitment,
    update_caseload,
    validate_error,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_FINANCE = TEST_USERS["finance_reviewer_headers"]


def test_provisional_attribution_uses_fulfillment_month(api):
    """PRD §3.5: "While a period is `OPEN`, reading it surfaces
    `provisional_fulfilled_cents`: the sum of `final_total_cents` over the
    agreement's `FULFILLED` orders whose `fulfilled_at` calendar month equals
    the period's `period_month`." — an order fulfilled in October contributes
    nothing to the still-OPEN September period even though its declared
    `order_month` is September.

    Design: Difficulty/dual_variant_calc/commitment_attribution_provisional_vs_final
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    order = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09",
        lines=[reagent_line("VC300_CHEM_SLIDE", 100)],
    )
    advance_clock(CLOCK_2026_10_02)
    fulfill_reagent_order(order["id"], clinic["id"])  # fulfilled_at lands in 2026-10

    periods = list_commitment_periods(agreement["id"])
    september = periods[0]
    assert september["period_month"] == "2026-09"
    assert september["period_status"] == "OPEN"
    assert september["provisional_fulfilled_cents"] == 0


def test_final_attribution_at_close_uses_order_month(api):
    """PRD §3.5: "The close locks the final variant of fulfillment
    attribution: `fulfilled_cents` becomes the sum of `final_total_cents`
    over the agreement's `FULFILLED` orders whose declared `order_month`
    equals the `period_month` — order-month attribution, which diverges from
    the provisional figure whenever an order's fulfillment month differs from
    its declared month." PRD §3.5: "`billed_cents` is that shortfall
    multiplied by the platform's shortfall billing rate of 0.80
    (`SHORTFALL_BILLING_RATE`), rounded half up to whole cents." The same
    order set reads 0 provisionally and locks 42000 at close.

    Design: Difficulty/dual_variant_calc/commitment_attribution_provisional_vs_final
    """
    scenario = setup_agreement_with_closed_period(
        order_specs=[{
            "order_month": "2026-09",
            "lines": [reagent_line("VC300_CHEM_SLIDE", 100)],
        }],
        fulfill_after_clock_advance=True,  # fulfilled in October, declared 2026-09
    )
    period = scenario["period"]
    assert period["period_status"] == "CLOSED"
    assert period["billing_status"] == "ISSUED"
    assert period["fulfilled_cents"] == 42000  # 100 x 420 by order_month
    assert period["shortfall_cents"] == 58000  # 100000 - 42000
    assert period["billed_cents"] == 46400  # round_half_up(58000 * 0.80)
    assert period["provisional_fulfilled_cents"] is None

    agreement = scenario["agreement"]
    assert agreement["cumulative_billed_cents"] == 46400
    assert agreement["cumulative_unpaid_billed_cents"] == 46400


def test_commitment_period_computed_fields_null_until_close(api):
    """PRD §3.5: "This provisional variant is fulfillment-date attribution,
    recomputed on every read; `fulfilled_cents`, `shortfall_cents`, and
    `billed_cents` remain null until close." PRD §2.3: "an agreement's
    commitment periods are instead ordered by `period_month` ascending."
    PRD §3.3: "One commitment period per term month is created".

    Design: Corner/entities/commitment_period_computed_fields_null_until_close
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    periods = list_commitment_periods(scenario["agreement"]["id"])
    assert len(periods) == 24
    assert periods[0]["period_month"] == "2026-09"
    assert periods[-1]["period_month"] == "2028-08"
    assert [p["period_month"] for p in periods] == sorted(p["period_month"] for p in periods)

    first = periods[0]
    assert_open_period_shape(first)
    assert first["minimum_cents"] == 100000
    assert first["provisional_fulfilled_cents"] == 0
    assert first["fulfilled_cents"] is None
    assert first["shortfall_cents"] is None
    assert first["billed_cents"] is None


def test_commitment_provisional_counts_only_fulfilled_orders(api):
    """PRD §3.5: "`SUBMITTED` and `CANCELLED` orders never count toward
    either variant". PRD §3.4: "Fulfillment stamps `fulfilled_at` from the
    logical clock and makes the order count toward commitment attribution
    per §3.5."

    Design: Corner/calculations/commitment_provisional_counts_only_fulfilled_orders
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]

    order = place_reagent_order(clinic["id"], agreement["id"], order_month="2026-09")
    assert list_commitment_periods(agreement["id"])[0]["provisional_fulfilled_cents"] == 0

    fulfill_reagent_order(order["id"], clinic["id"])
    assert list_commitment_periods(agreement["id"])[0]["provisional_fulfilled_cents"] == 42000

    cancelled = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09",
        lines=[reagent_line("VH500_CBC_CART", 5)],
    )
    cancel_reagent_order(cancelled["id"], clinic["id"])
    assert list_commitment_periods(agreement["id"])[0]["provisional_fulfilled_cents"] == 42000


def _sum_of_rounds_setup() -> dict:
    """Two periods each carrying one 33333c fulfilled order (79 slides + 1
    strip), closed chronologically once both months have elapsed."""
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    lines = [reagent_line("VC300_CHEM_SLIDE", 79), reagent_line("VU200_URINE_STRIP", 1)]

    order_a = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09", lines=lines
    )
    fulfill_reagent_order(order_a["id"], clinic["id"])
    advance_clock(CLOCK_2026_10_05)
    order_b = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-10", lines=lines
    )
    fulfill_reagent_order(order_b["id"], clinic["id"])
    advance_clock(CLOCK_2026_11_01)
    return scenario


def test_shortfall_billing_rounds_per_period(api):
    """PRD §3.5: "`billed_cents` is that shortfall multiplied by the
    platform's shortfall billing rate of 0.80 (`SHORTFALL_BILLING_RATE`),
    rounded half up to whole cents." PRD §2.6: "the method is round half up,
    applied exactly where the rule states — per unit price in reagent
    pricing, per commitment period in shortfall billing". Each period's
    shortfall is 66667c, billing round_half_up(53333.6) = 53334c.

    Design: Difficulty/combinatorial_formula/shortfall_billing_sum_of_rounds
    """
    scenario = _sum_of_rounds_setup()
    agreement = scenario["agreement"]

    september = close_commitment_period(agreement["id"], "2026-09")
    assert september["fulfilled_cents"] == 33333
    assert september["shortfall_cents"] == 66667
    assert september["billed_cents"] == 53334

    october = close_commitment_period(agreement["id"], "2026-10")
    assert october["fulfilled_cents"] == 33333
    assert october["shortfall_cents"] == 66667
    assert october["billed_cents"] == 53334


def test_shortfall_agreement_total_is_sum_of_rounds(api):
    """PRD §3.5: "Both cumulative totals are sums of per-period amounts that
    were each rounded at close time — sum-of-rounds; recomputing an agreement
    total by rounding an aggregate shortfall is forbidden, because
    round-of-sum differs from sum-of-rounds." 53334 + 53334 = 106668, not
    round_half_up(133334 * 0.80) = 106667.

    Design: Difficulty/combinatorial_formula/shortfall_billing_sum_of_rounds
    """
    scenario = _sum_of_rounds_setup()
    agreement = scenario["agreement"]
    close_commitment_period(agreement["id"], "2026-09")
    close_commitment_period(agreement["id"], "2026-10")

    after = get_agreement(agreement["id"])
    assert after["cumulative_billed_cents"] == 106668
    assert after["cumulative_unpaid_billed_cents"] == 106668


def test_close_commitment_period_side_effects(api):
    """PRD §3.5: "The period's `period_status` becomes `CLOSED`,
    `provisional_fulfilled_cents` is null thereafter, and when `billed_cents`
    is positive the same mutation flips `billing_status` from `NONE` to
    `ISSUED` — the period's `version` moves exactly once for the whole
    close". PRD §3.5: "The close also debits the agreement's ledgers:
    `cumulative_billed_cents` and `cumulative_unpaid_billed_cents` each grow
    by the period's `billed_cents`, and the agreement's `version` increments
    by 1."

    Design: Corner/endpoints/close_commitment_period_side_effects
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    advance_clock(CLOCK_2026_10_02)

    open_period = list_commitment_periods(agreement["id"])[0]
    agreement_before = get_agreement(agreement["id"])

    closed = close_commitment_period(agreement["id"], "2026-09")
    assert_closed_period_shape(closed)
    assert closed["period_status"] == "CLOSED"
    assert closed["billing_status"] == "ISSUED"
    assert closed["fulfilled_cents"] == 0
    assert closed["shortfall_cents"] == 100000
    assert closed["billed_cents"] == 80000
    assert closed["version"] == open_period["version"] + 1  # one mutation event

    after = get_agreement(agreement["id"])
    assert after["cumulative_billed_cents"] == 80000
    assert after["cumulative_unpaid_billed_cents"] == 80000
    assert after["version"] == agreement_before["version"] + 1
    assert after["status"] == "ACTIVE"  # 80000 < 250000: no breach
    assert get_clinic(clinic["id"])["status"] == "ACTIVE"


def test_record_payment_amount_mismatch_rejected(api):
    """PRD §3.5: "An issued bill is settled through payment recording by
    `FinanceReviewer`, which demands `amount_cents` exactly equal to the
    period's `billed_cents` — anything else is `ERR_PAYMENT_AMOUNT_MISMATCH`
    (HTTP 402)".

    Design: Corner/errors/record_payment_amount_mismatch_rejected
    """
    scenario = setup_agreement_with_closed_period()
    period = scenario["period"]
    assert period["billed_cents"] == 80000

    resp = api_client.record_payment(
        period["id"], record_payment_payload(79999), _FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    periods = list_commitment_periods(scenario["agreement"]["id"])
    assert periods[0]["billing_status"] == "ISSUED"
    assert get_agreement(scenario["agreement"]["id"])["cumulative_unpaid_billed_cents"] == 80000


def test_record_payment_on_open_period_rejected(api):
    """PRD §3.5: payment recording applies "against a period whose
    `billing_status` is still `ISSUED` (`ERR_PERIOD_INVALID_STATE`)" — an
    OPEN period is still `NONE`, so payment cannot precede billing.

    Design: Corner/state_machines/record_payment_on_open_period_rejected
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    period = list_commitment_periods(scenario["agreement"]["id"])[0]
    assert period["period_status"] == "OPEN"
    assert period["billing_status"] == "NONE"

    resp = api_client.record_payment(
        period["id"], record_payment_payload(80000), _FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_INVALID_STATE)

    after = list_commitment_periods(scenario["agreement"]["id"])[0]
    assert after["period_status"] == "OPEN"
    assert after["billing_status"] == "NONE"
    assert get_agreement(scenario["agreement"]["id"])["cumulative_unpaid_billed_cents"] == 0


def test_derived_unpaid_reconciles_after_exact_payment(api):
    """PRD §3.5: "Success moves `billing_status` `ISSUED` → `PAID`, subtracts
    the payment from the agreement's `cumulative_unpaid_billed_cents` while
    leaving `cumulative_billed_cents` untouched". PRD §3.5: "`PAID` and
    `WAIVED` are likewise terminal" — a second payment hits
    `ERR_PERIOD_INVALID_STATE`.

    Design: Corner/cross_cutting_layers/derived_unpaid_reconciles_after_exact_payment
    """
    scenario = setup_agreement_with_closed_period()
    period = scenario["period"]
    agreement_id = scenario["agreement"]["id"]

    paid = record_exact_payment(period["id"], 80000)
    assert paid["billing_status"] == "PAID"

    agreement = get_agreement(agreement_id)
    assert agreement["cumulative_unpaid_billed_cents"] == 0
    assert agreement["cumulative_billed_cents"] == 80000  # payment never unbills

    resp = api_client.record_payment(
        period["id"], record_payment_payload(80000), _FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_INVALID_STATE)


def test_occ_close_period_stale_version_rejected(api):
    """PRD §2.8: "If that value does not equal the agreement's current
    `version` — because another writer has advanced the agreement since the
    client read it — the request is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and nothing is mutated". The
    September close advanced the agreement, so replaying October's close
    with the pre-close version is stale.

    Design: Corner/cross_cutting_layers/occ_close_period_stale_version_rejected
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    agreement = scenario["agreement"]
    observed_at_activation = agreement["version"]
    advance_clock(CLOCK_2026_11_01)

    close_commitment_period(agreement["id"], "2026-09")  # advances the agreement

    stale = api_client.close_commitment_period(
        agreement["id"],
        close_commitment_period_payload("2026-10", observed_at_activation),
        _ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)

    refreshed = current_agreement_version(agreement["id"])
    october = close_commitment_period(
        agreement["id"], "2026-10", expected_agreement_version=refreshed
    )
    assert october["period_status"] == "CLOSED"


def _waived_period_scenario() -> dict:
    """Closed ISSUED period (80000c) subsequently waived through an accepted
    renegotiation; the agreement is back to ACTIVE with zero unpaid."""
    scenario = setup_agreement_with_closed_period()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    period = scenario["period"]
    update_caseload(clinic["id"], 1400)
    requested = request_renegotiation(agreement["id"], clinic["id"])
    resolve_renegotiation(
        agreement["id"], True, requested["version"],
        new_minimum_cents=120000, waive_period_ids=[period["id"]],
    )
    return scenario


def test_state_error_beats_fiscal_error_on_waived_period(api):
    """PRD §2.9: "Checks run in a fixed sequence of tiers, and a request that
    fails several checks reports the failure from the earliest tier" — tier 6
    state legality (`ERR_PERIOD_INVALID_STATE`) precedes tier 10 fiscal gates
    (`ERR_PAYMENT_AMOUNT_MISMATCH`). A payment against a WAIVED period with a
    wrong amount reports the state failure.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_waived_period_payment
    """
    scenario = _waived_period_scenario()
    period = scenario["period"]

    resp = api_client.record_payment(
        period["id"], record_payment_payload(1), _FINANCE  # wrong amount AND waived
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_INVALID_STATE)
    assert resp.status_code == 409


def test_waived_period_stays_waived_and_unpaid_stays_zero(api):
    """PRD §3.6: "Each waived period moves `ISSUED` → `WAIVED`, its
    `billed_cents` is subtracted from the agreement's
    `cumulative_unpaid_billed_cents`". PRD §3.5: "`PAID` and `WAIVED` are
    likewise terminal" — even the exact amount cannot reopen a waived bill.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_waived_period_payment
    """
    scenario = _waived_period_scenario()
    period = scenario["period"]
    agreement_id = scenario["agreement"]["id"]

    resp = api_client.record_payment(
        period["id"], record_payment_payload(80000), _FINANCE  # exact amount, still waived
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_INVALID_STATE)

    periods = list_commitment_periods(agreement_id)
    assert periods[0]["billing_status"] == "WAIVED"
    agreement = get_agreement(agreement_id)
    assert agreement["cumulative_unpaid_billed_cents"] == 0
    assert agreement["cumulative_billed_cents"] == 80000

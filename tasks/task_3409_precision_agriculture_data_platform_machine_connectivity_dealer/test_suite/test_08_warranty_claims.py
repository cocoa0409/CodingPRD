"""Warranty claim lifecycle, the payout waterfall, age brackets, and the
absolute payout ceiling."""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_machine_in,
    activate_plan,
    add_machine,
    create_claim,
    create_plan,
    decide_claim,
    ingest_batch,
    provision_modem_success,
    read_dealer,
    setup_machine_with_coverage,
    setup_submitted_claim,
    submit_claim,
    validate_error,
    validate_success,
)


def test_claim_settle_before_approve_and_decide_twice_rejected(api):
    """PRD section 3.8: "Settlement, also `PlatformAdmin`, moves `APPROVED` →
    `SETTLED`" and "An `APPROVE` decision moves `SUBMITTED` → `APPROVED`" —
    settle on a `SUBMITTED` claim and a second decide on an `APPROVED` claim
    are transitions that do not exist (`ERR_INVALID_STATE_TRANSITION`, PRD
    section 2.10 step 6). The payout computed by the single legal decide is
    floor(200000*0.9) + floor(min(300000, 500000)*0.9) = 450000 at age 12
    months ("0.90 when the machine is at most 24 months old").

    Design: Corner/state_machines/claim_settle_before_approve_and_decide_twice_rejected
    """
    ctx = setup_submitted_claim(api, claim_amount_cents=500000,
                                parts_amount_cents=200000)
    claim_id = ctx["claim"]["id"]

    response = api.settle_warranty_claim(claim_id, headers=ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    claim = decide_claim(api, claim_id, "APPROVE")
    assert claim["status"] == "APPROVED"
    assert claim["payout_cents"] == 450000

    response = api.decide_warranty_claim(claim_id, "APPROVE", headers=ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    dealer = read_dealer(ctx, api, ctx["dealer"]["id"])
    assert dealer["warranty_reserve_cents"] == 500000


def test_warranty_age_bracket_boundaries_24_vs_25_months(api):
    """PRD section 3.8: "the machine's age is the whole-month count between its
    `manufacture_date` and the current logical date, floored. Second, the age
    bracket fixes the coverage fraction: 0.90 when the machine is at most 24
    months old, 0.70 when at most 60 months old, and 0.50 beyond that". At the
    2026-09-30 clock, a machine manufactured 2024-09-01 is exactly 24 months
    (keeps 0.90) and one manufactured 2024-08-01 is 25 months (drops to 0.70).

    Design: Corner/calculations/warranty_age_bracket_boundaries_24_vs_25_months
    """
    ctx = setup_machine_with_coverage(
        api, filled_hours=648, machine_overrides={"manufacture_date": "2024-09-01"}
    )
    machine2 = add_machine(ctx, api, serial_number="SN-0002",
                           modem_imei="IMEI-0002",
                           manufacture_date="2024-08-01")
    provision_modem_success(ctx, api, machine2["id"])
    plan2 = create_plan(ctx, api, machine2["id"])
    activate_plan(ctx, api, plan2["id"])
    activate_machine_in(ctx, api, machine2["id"])
    ingest_batch(ctx, api, machine2["id"], batch_id="cov-2",
                 start_hour_iso="2026-08-31T00:00:00Z", hour_count=648,
                 payload_mb=50)

    claim1 = create_claim(ctx, api, ctx["machine"]["id"],
                          claim_amount_cents=1000000,
                          parts_amount_cents=1000000,
                          description="Hydraulic pump failure")
    claim2 = create_claim(ctx, api, machine2["id"],
                          claim_amount_cents=1000000,
                          parts_amount_cents=1000000,
                          description="Gearbox wear")
    submit_claim(ctx, api, claim1["id"])
    submit_claim(ctx, api, claim2["id"])

    claim1 = decide_claim(api, claim1["id"], "APPROVE")
    claim2 = decide_claim(api, claim2["id"], "APPROVE")
    assert claim1["coverage_pct_applied"] == pytest.approx(0.9)
    assert claim1["payout_cents"] == 900000
    assert claim2["coverage_pct_applied"] == pytest.approx(0.7)
    assert claim2["payout_cents"] == 700000


def test_warranty_payout_capped_at_absolute_maximum(api):
    """PRD section 3.8: "`payout_cents` is the smallest of three values: the
    full `claim_amount_cents`, the sum of covered parts and covered labor, and
    a hard ceiling of 2000000 cents." A 5000000-cent all-parts claim at 0.90
    coverage computes 4500000 but pays exactly 2000000.

    Design: Corner/calculations/warranty_payout_capped_at_absolute_maximum
    """
    ctx = setup_submitted_claim(api, claim_amount_cents=5000000,
                                parts_amount_cents=5000000)
    claim = decide_claim(api, ctx["claim"]["id"], "APPROVE")
    assert claim["payout_cents"] == 2000000


def test_warranty_payout_nested_minimums(api):
    """PRD section 3.8: "the parts coverage is `parts_amount_cents` multiplied
    by the coverage fraction, floored to integer cents ... the covered labor is
    the smaller of the labor portion and the cap, multiplied by the coverage
    fraction, floored to integer cents. Finally, `payout_cents` is the smallest
    of three values: the full `claim_amount_cents`, the sum of covered parts
    and covered labor, and a hard ceiling of 2000000 cents." Claim 1000000 with
    600000 parts at age 12 months on a STANDARD dealer: floor(600000*0.9) +
    floor(min(400000, 500000)*0.9) = 540000 + 360000 = 900000.

    Design: Difficulty/combinatorial_formula/warranty_payout_nested_minimums
    """
    ctx = setup_submitted_claim(api, claim_amount_cents=1000000,
                                parts_amount_cents=600000)
    claim = decide_claim(api, ctx["claim"]["id"], "APPROVE")
    assert claim["status"] == "APPROVED"
    assert claim["coverage_pct_applied"] == pytest.approx(0.9)
    assert claim["payout_cents"] == 900000


def test_warranty_approve_holds_reserve_until_settle(api):
    """PRD section 3.8: "the dealer read always reflects the sum of claim
    amounts over claims sitting `SUBMITTED` or `APPROVED`" — the reservation
    taken at submit survives the approval decision and is only released at
    settlement ("`warranty_reserve_cents` decreases by `claim_amount_cents`"
    on `APPROVED` → `SETTLED`).

    Design: Difficulty/combinatorial_formula/warranty_payout_nested_minimums
    """
    ctx = setup_submitted_claim(api, claim_amount_cents=1000000,
                                parts_amount_cents=600000)
    decide_claim(api, ctx["claim"]["id"], "APPROVE")
    dealer = read_dealer(ctx, api, ctx["dealer"]["id"])
    assert dealer["warranty_reserve_cents"] == 1000000
    assert dealer["warranty_paid_cents"] == 0

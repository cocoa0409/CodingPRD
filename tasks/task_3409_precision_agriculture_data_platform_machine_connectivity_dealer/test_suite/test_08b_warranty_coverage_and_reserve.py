"""Warranty data-coverage gate at exactly 90% and the dealer reserve
submit/deny compensating round-trip."""

from test_helpers import (
    ApiErrorId,
    activate_machine_in,
    activate_plan,
    add_machine,
    create_claim,
    create_plan,
    decide_claim,
    ingest_batch,
    provision_modem_success,
    read_claim,
    read_dealer,
    setup_machine_with_coverage,
    submit_claim,
    validate_error,
)


def _two_coverage_machines(api):
    """Two IN_SERVICE machines at the 2026-09-30 clock: M1 with 648 filled
    hour-buckets (conservative coverage exactly 90.0) and M2 with 647 (89.9).
    Returns (ctx, machine2)."""
    ctx = setup_machine_with_coverage(api, filled_hours=648)
    machine2 = add_machine(ctx, api, serial_number="SN-0002",
                           modem_imei="IMEI-0002")
    provision_modem_success(ctx, api, machine2["id"])
    plan2 = create_plan(ctx, api, machine2["id"])
    activate_plan(ctx, api, plan2["id"])
    activate_machine_in(ctx, api, machine2["id"])
    ingest_batch(ctx, api, machine2["id"], batch_id="cov-2",
                 start_hour_iso="2026-08-31T00:00:00Z", hour_count=647,
                 payload_mb=50)
    return ctx, machine2


def test_warranty_coverage_at_exactly_ninety_percent_passes(api):
    """PRD section 3.8: "the machine's conservative uptime score must be at
    least 90.0 — exactly 90.0 passes — or the submit is rejected with
    `ERR_INSUFFICIENT_DATA_COVERAGE`." 648 of 720 buckets scores exactly 90.0
    and submits; 647 buckets scores 89.9 and is rejected.

    Design: Difficulty/boundary_precision_check/warranty_coverage_at_exactly_ninety_percent
    """
    ctx, machine2 = _two_coverage_machines(api)
    claim1 = create_claim(ctx, api, ctx["machine"]["id"],
                          claim_amount_cents=500000, parts_amount_cents=200000,
                          description="Alternator failure")
    claim2 = create_claim(ctx, api, machine2["id"],
                          claim_amount_cents=500000, parts_amount_cents=200000,
                          description="Sensor drift")

    claim1 = submit_claim(ctx, api, claim1["id"])
    assert claim1["status"] == "SUBMITTED"

    response = api.submit_warranty_claim(
        claim2["id"], headers=ctx["dealer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_DATA_COVERAGE)


def test_warranty_coverage_shortfall_leaves_claim_draft(api):
    """PRD section 3.8: "Submitting the draft moves `DRAFT` → `SUBMITTED` and
    enforces the coverage gate" — a rejected submit performs no move, so the
    647-bucket machine's claim remains `DRAFT`.

    Design: Difficulty/boundary_precision_check/warranty_coverage_at_exactly_ninety_percent
    """
    ctx, machine2 = _two_coverage_machines(api)
    claim1 = create_claim(ctx, api, ctx["machine"]["id"],
                          claim_amount_cents=500000, parts_amount_cents=200000,
                          description="Alternator failure")
    claim2 = create_claim(ctx, api, machine2["id"],
                          claim_amount_cents=500000, parts_amount_cents=200000,
                          description="Sensor drift")

    submit_claim(ctx, api, claim1["id"])
    response = api.submit_warranty_claim(
        claim2["id"], headers=ctx["dealer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_DATA_COVERAGE)

    claim2 = read_claim(ctx, api, claim2["id"])
    assert claim2["status"] == "DRAFT"


def test_dealer_reserve_submit_reserves_claim_amount(api):
    """PRD section 3.8: "On submission the claimed amount is reserved on the
    dealer: `warranty_reserve_cents` increases by `claim_amount_cents`, so the
    dealer read always reflects the sum of claim amounts over claims sitting
    `SUBMITTED` or `APPROVED`."

    Design: Difficulty/compensating_invariant/dealer_reserve_submit_deny_roundtrip
    """
    ctx = setup_machine_with_coverage(api, filled_hours=648)
    claim = create_claim(ctx, api, ctx["machine"]["id"],
                         claim_amount_cents=1000000, parts_amount_cents=600000,
                         description="Hydraulic pump failure")
    dealer = read_dealer(ctx, api, ctx["dealer"]["id"])
    assert dealer["warranty_reserve_cents"] == 0

    submit_claim(ctx, api, claim["id"])
    dealer = read_dealer(ctx, api, ctx["dealer"]["id"])
    assert dealer["warranty_reserve_cents"] == 1000000


def test_dealer_reserve_deny_compensates_exactly(api):
    """PRD section 3.8: "A `DENY` decision moves `SUBMITTED` → `DENIED` —
    terminal — stamps `decided_at`, and releases the reserve by subtracting
    `claim_amount_cents` from `warranty_reserve_cents`, exactly compensating
    the submit-time reservation."

    Design: Difficulty/compensating_invariant/dealer_reserve_submit_deny_roundtrip
    """
    ctx = setup_machine_with_coverage(api, filled_hours=648)
    claim = create_claim(ctx, api, ctx["machine"]["id"],
                         claim_amount_cents=1000000, parts_amount_cents=600000,
                         description="Hydraulic pump failure")
    submit_claim(ctx, api, claim["id"])

    claim = decide_claim(api, claim["id"], "DENY")
    assert claim["status"] == "DENIED"
    assert claim["payout_cents"] is None

    dealer = read_dealer(ctx, api, ctx["dealer"]["id"])
    assert dealer["warranty_reserve_cents"] == 0
    assert dealer["warranty_paid_cents"] == 0

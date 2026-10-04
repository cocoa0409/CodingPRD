"""Daily holdback sweeps, the loan balance ledger, and compensating reversal."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_loan_ledger_invariants,
    create_active_loan,
    create_batch_payload,
    get_loan,
    post_sweep,
    record_finalized_batch,
    record_open_batch,
    repay_loan_fully,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SERVICER = TEST_USERS["servicer_agent_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / daily_holdback_per_day_rounding
# ---------------------------------------------------------------------------

def test_per_day_rounding_accumulates_101_per_day(api):
    """PRD Section 3.4: "The holdback amount follows a pinned rounding order: round per day, then accumulate. The raw holdback is the batch's `net_settled_cents` multiplied by the loan's `holdback_pct`; that product is rounded half-up to whole cents for that day — never aggregated over a week and then rounded, which would yield different cents."

    Design: Difficulty/combinatorial_formula/daily_holdback_per_day_rounding
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    merchant_id = bundle["merchant"]["id"]

    batch_ids = []
    for day in range(2, 9):
        batch = record_finalized_batch(merchant_id, f"2026-09-{day:02d}", 1005)
        batch_ids.append(batch["id"])
    for batch_id in batch_ids:
        post_sweep(loan_id, batch_id)

    loan = get_loan(loan_id)
    # Each day rounds 100.5 half-up to 101; seven days accumulate to 707
    # (weekly-sum-then-round would yield 704).
    assert loan["paid_to_date_cents"] == 707
    assert loan["remaining_balance_cents"] == 554_293


def test_each_daily_sweep_records_rounded_holdback(api):
    """PRD Section 3.4: "The posted `holdback_cents` is then the smaller of that daily figure and the loan's current `remaining_balance_cents`; when the raw daily figure exceeded the remaining balance, the sweep's `clipped` flag is true."

    Design: Difficulty/combinatorial_formula/daily_holdback_per_day_rounding
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    merchant_id = bundle["merchant"]["id"]

    for day in range(2, 9):
        batch = record_finalized_batch(merchant_id, f"2026-09-{day:02d}", 1005)
        sweep = post_sweep(loan_id, batch["id"])
        assert sweep["holdback_cents"] == 101
        assert sweep["clipped"] is False

    sweeps, _meta = validate_paginated(api.list_loan_sweeps(loan_id, SERVICER))
    assert len(sweeps) == 7
    assert all(s["holdback_cents"] == 101 for s in sweeps)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / final_sweep_clip_to_zero
# ---------------------------------------------------------------------------

def test_final_sweep_clipped_to_remaining_balance(api):
    """PRD Section 3.4: "The posted `holdback_cents` is then the smaller of that daily figure and the loan's current `remaining_balance_cents`; when the raw daily figure exceeded the remaining balance, the sweep's `clipped` flag is true."

    Design: Difficulty/boundary_precision_check/final_sweep_clip_to_zero
    """
    bundle = create_active_loan(principal_cents=500_000)
    post_sweep(
        bundle["loan"]["id"],
        record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 5_545_000)["id"],
    )
    loan = get_loan(bundle["loan"]["id"])
    assert loan["remaining_balance_cents"] == 500

    second_batch = record_finalized_batch(
        bundle["merchant"]["id"], "2026-09-03", 10_000)
    sweep = post_sweep(bundle["loan"]["id"], second_batch["id"])
    assert sweep["holdback_cents"] == 500, "raw 1,000 clipped to the remaining 500"
    assert sweep["clipped"] is True

    loan_after = get_loan(bundle["loan"]["id"])
    assert loan_after["remaining_balance_cents"] == 0, "exactly zero, not negative"
    assert loan_after["status"] == "REPAID"


def test_repaid_loan_paid_to_date_equals_total_repayment(api):
    """PRD Section 2.8: "Every loan maintains a double-entry-style ledger view: `remaining_balance_cents` starts at the loan's total repayment obligation and falls as value is applied; `paid_to_date_cents` starts at zero and rises by the same amounts. The two always move together — the sum of applied sweeps, applied catch-up payments, and enforcement draws equals `paid_to_date_cents`, and `total_repayment_cents` minus that same sum equals `remaining_balance_cents`."

    Design: Difficulty/boundary_precision_check/final_sweep_clip_to_zero
    """
    bundle = create_active_loan(principal_cents=500_000)
    repay_loan_fully(bundle)
    loan = get_loan(bundle["loan"]["id"])
    assert loan["status"] == "REPAID"
    assert loan["paid_to_date_cents"] == 555_000
    assert_loan_ledger_invariants(loan)


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / repayment_completion_renewal_cascade
# ---------------------------------------------------------------------------

def test_repayment_cascade_clears_merchant_and_counts_repayment(api):
    """PRD Section 3.5: "The repayment cascade clears the merchant's `active_loan_id`, increments `loans_repaid_count` by 1, and increments the merchant's `version`; and when the merchant's status is `ELIGIBLE` at that moment, a renewal offer is auto-created in `DRAFT` with freshly recomputed pre-approval amounts."

    Design: Difficulty/transitive_cascade/repayment_completion_renewal_cascade
    """
    bundle = create_active_loan(principal_cents=500_000)
    merchant_id = bundle["merchant"]["id"]

    repay_loan_fully(bundle)

    loan = get_loan(bundle["loan"]["id"])
    assert loan["status"] == "REPAID"

    merchant = validate_success(api.get_merchant(merchant_id, ADMIN))
    assert merchant["active_loan_id"] is None
    assert merchant["loans_repaid_count"] == 1


def test_repayment_cascade_auto_creates_renewal_offer(api):
    """PRD Section 3.5: "A loan reaches `REPAID` automatically the moment `remaining_balance_cents` reaches zero, from any of `ACTIVE`, `DELINQUENT`, or `DEFAULTED` — via a sweep, a catch-up, or an enforcement draw."
    PRD Section 3.5: "The repayment cascade clears the merchant's `active_loan_id`, increments `loans_repaid_count` by 1, and increments the merchant's `version`; and when the merchant's status is `ELIGIBLE` at that moment, a renewal offer is auto-created in `DRAFT` with freshly recomputed pre-approval amounts."

    Design: Difficulty/transitive_cascade/repayment_completion_renewal_cascade
    """
    bundle = create_active_loan(principal_cents=500_000)
    merchant_id = bundle["merchant"]["id"]
    original_offer_id = bundle["offer"]["id"]

    repay_loan_fully(bundle)

    offers, _meta = validate_paginated(api.list_offers(merchant_id, ADMIN))
    assert len(offers) == 2, "original ACCEPTED offer plus the auto-created renewal"
    by_id = {o["id"]: o for o in offers}
    assert by_id[original_offer_id]["status"] == "ACCEPTED"
    renewal = next(o for o in offers if o["id"] != original_offer_id)
    assert renewal["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / sweep_reversal_balance_conservation
# ---------------------------------------------------------------------------

def test_sweep_reversal_restores_ledger_and_batch(api):
    """PRD Section 3.4: "Reversal is compensating: the sweep moves to `REVERSED` with `reversed_at` stamped, the loan's `remaining_balance_cents` rises and `paid_to_date_cents` falls by exactly the sweep's `holdback_cents`, and the batch returns from `SWEPT` to `FINALIZED`."

    Design: Difficulty/compensating_invariant/sweep_reversal_balance_conservation
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 100_000)

    sweep = post_sweep(loan_id, batch["id"])
    assert sweep["holdback_cents"] == 10_000
    mid = get_loan(loan_id)
    assert mid["remaining_balance_cents"] == 545_000
    assert mid["paid_to_date_cents"] == 10_000
    assert_loan_ledger_invariants(mid)

    reversed_sweep = validate_success(api.reverse_sweep(sweep["id"], SERVICER))
    assert reversed_sweep["status"] == "REVERSED"

    loan = get_loan(loan_id)
    assert loan["remaining_balance_cents"] == 555_000
    assert loan["paid_to_date_cents"] == 0
    assert_loan_ledger_invariants(loan)

    batch_after = validate_success(api.get_batch(batch["id"], SERVICER))
    assert batch_after["status"] == "FINALIZED"


def test_sweep_reversal_conserves_repayment_total(api):
    """PRD Section 2.8: "Reversals are compensating, never deletions: reversing a sweep or a catch-up payment restores the loan's balances by exactly the reversed amount and leaves the original record in place with terminal status."

    Design: Difficulty/compensating_invariant/sweep_reversal_balance_conservation
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 100_000)
    sweep = post_sweep(loan_id, batch["id"])

    validate_success(api.reverse_sweep(sweep["id"], SERVICER))

    kept = validate_success(api.get_sweep(sweep["id"], SERVICER))
    assert kept["status"] == "REVERSED", "original record left in place, terminal"
    loan = get_loan(loan_id)
    # Zero drift: remaining + applied payments == total after compensation.
    assert loan["remaining_balance_cents"] + loan["paid_to_date_cents"] == 555_000


# ---------------------------------------------------------------------------
# Queue B: validations — sweep preconditions
# ---------------------------------------------------------------------------

def test_sweep_batch_not_finalized_rejected(api):
    """PRD Section 3.4: "The referenced batch must belong to the loan's merchant and be in `FINALIZED` status — a batch still `OPEN` or otherwise not finalized is rejected with `ERR_BATCH_NOT_FINALIZED`, and a batch already swept by a non-reversed sweep is rejected with `ERR_BATCH_ALREADY_SWEPT`."

    Design: Corner/validations/sweep_batch_not_finalized_rejected
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    open_batch = record_open_batch(bundle["merchant"]["id"], "2026-09-02", 50_000)

    loan = get_loan(loan_id)
    from test_helpers import create_sweep_payload
    resp = api.create_sweep(
        loan_id, create_sweep_payload(open_batch["id"], loan["version"]), SERVICER)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_FINALIZED)
    assert validate_success(
        api.get_batch(open_batch["id"], SERVICER))["status"] == "OPEN"


def test_sweep_batch_already_swept_rejected(api):
    """PRD Section 3.4: "The referenced batch must belong to the loan's merchant and be in `FINALIZED` status — a batch still `OPEN` or otherwise not finalized is rejected with `ERR_BATCH_NOT_FINALIZED`, and a batch already swept by a non-reversed sweep is rejected with `ERR_BATCH_ALREADY_SWEPT`."

    Design: Corner/validations/sweep_batch_already_swept_rejected
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 50_000)
    post_sweep(loan_id, batch["id"])

    loan = get_loan(loan_id)
    from test_helpers import create_sweep_payload
    resp = api.create_sweep(
        loan_id, create_sweep_payload(batch["id"], loan["version"]), SERVICER)
    validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_SWEPT)

    loan_after = get_loan(loan_id)
    assert loan_after["paid_to_date_cents"] == 5000, "single application only"


# ---------------------------------------------------------------------------
# Queue B: state_machines — sweep terminal lockdown
# ---------------------------------------------------------------------------

def test_sweep_reverse_from_reversed_rejected(api):
    """PRD Section 3.4: "Reversing an `APPLIED` sweep is a `ServicerAgent` operation permitted only while the loan is `ACTIVE` or `DELINQUENT` — on a terminal loan it is rejected with `ERR_LOAN_ALREADY_TERMINAL`."

    Design: Corner/state_machines/sweep_reverse_from_reversed_rejected
    """
    bundle = create_active_loan(principal_cents=500_000)
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 50_000)
    sweep = post_sweep(bundle["loan"]["id"], batch["id"])
    validate_success(api.reverse_sweep(sweep["id"], SERVICER))

    resp = api.reverse_sweep(sweep["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert validate_success(api.get_sweep(sweep["id"], SERVICER))["status"] == "REVERSED"


# ---------------------------------------------------------------------------
# Queue B: endpoints — filtered listing
# ---------------------------------------------------------------------------

def test_sweeps_filtered_list_by_batch_id(api):
    """PRD Section 2.3: "Most list endpoints additionally accept an optional `status` query parameter that filters results to the named status value, and the cross-entity list endpoints for loans, sweeps, enforcement actions, and sales also accept the foreign-key filters `merchant_id`, `offer_id`, `loan_id`, `batch_id`, `guarantor_id`, and `bank_id` as shown in Section 4."

    Design: Corner/endpoints/sweeps_filtered_list_by_batch_id
    """
    bundle = create_active_loan(principal_cents=500_000)
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 50_000)
    sweep = post_sweep(bundle["loan"]["id"], batch["id"])

    data, _meta = validate_paginated(
        api.list_sweeps(AUDITOR, params={"batch_id": batch["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == sweep["id"]
    assert data[0]["batch_id"] == batch["id"]
    assert data[0]["holdback_cents"] == 5000


# ---------------------------------------------------------------------------
# Queue B: consistency_model — immediate consistency
# ---------------------------------------------------------------------------

def test_sweep_effect_immediately_visible(api):
    """PRD Section 3.4: "The new sweep is born `APPLIED` with `reversed_at` null; the batch cascades from `FINALIZED` to `SWEPT`; the loan's `remaining_balance_cents` falls and `paid_to_date_cents` rises by `holdback_cents`; and the loan's `version` increments by 1."

    Design: Corner/consistency_model/sweep_effect_immediately_visible
    """
    bundle = create_active_loan(principal_cents=500_000)
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 50_000)

    sweep = post_sweep(bundle["loan"]["id"], batch["id"])
    assert sweep["holdback_cents"] == 5000

    loan = get_loan(bundle["loan"]["id"])
    assert loan["remaining_balance_cents"] == 550_000
    assert loan["paid_to_date_cents"] == 5000

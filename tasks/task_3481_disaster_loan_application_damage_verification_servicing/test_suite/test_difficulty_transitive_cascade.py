"""Difficulty queue: transitive_cascade — multi-hop mutations from one trigger."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    apply_settlement_payload,
    list_receivable_data,
    list_tranche_data,
    loan_version,
    read_loan,
    release_stage,
    report_settlement,
    set_clock,
    setup_loan_with_t1_released,
    validate_success,
    verify_milestone,
)


def test_settlement_apply_cascade_commitment_tranche_receivable(api):
    """PRD §3.8: "Third, the new commitment is the smaller of `approved_amount_cents` and the new net loss, and the loan's `commitment_amount_cents` is set to it."
    PRD §3.8: "Fourth, the waterfall walks the un-released tranches in descending `stage_number`: whole tranches are cancelled, largest stage first, while the sum of un-released amounts minus the tranche's amount stays at or above the target — the target being the new commitment minus `disbursed_total_cents`, floored at zero — and the tranche where that test fails is instead reduced so the sum of un-released amounts lands exactly on the target; reduced amounts never go below zero, and cancelled tranches move to `CANCELLED` from either `SCHEDULED` or `ELIGIBLE`."
    PRD §3.8: "Sixth, a positive excess creates the loan's excess-funds receivable — or tops up the existing one — by that amount."
    PRD §3.8: "The receivable's `due_date` is its `created_at` plus 30 days."

    Design: Difficulty/transitive_cascade/settlement_apply_cascade_commitment_tranche_receivable
    """
    # Setup: homeowner loan approved 20000000, accepted 2026-11-01; T1 (2500000)
    # and T2 (8750000) RELEASED (disbursed 11250000); milestones 9000000 +
    # 3000000 VERIFIED so stage 3 (8750000) is ELIGIBLE but unreleased.
    ctx = setup_loan_with_t1_released()
    verify_milestone(ctx, claimed_cost_cents=9000000)
    release_stage(ctx, 1)
    verify_milestone(ctx, claimed_cost_cents=3000000)
    settlement = report_settlement(ctx, 16000000)

    # Trigger: apply the 16000000 settlement at 2026-12-15 (OCC-guarded).
    set_clock("2026-12-15T00:00:00Z", ctx["admin_headers"])
    version = loan_version(ctx)
    resp = api.apply_insurance_settlement(
        settlement["id"],
        apply_settlement_payload(expected_loan_version=version),
        ctx["servicing_headers"])
    applied = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["apply_insurance_settlement"])

    # Hop 1: total insurance 5000000 + 16000000 = 21000000; new net loss
    # max(0, 25000000 - 21000000) = 4000000; commitment = min(20000000, 4000000).
    loan = read_loan(ctx)
    assert loan["commitment_amount_cents"] == 4000000
    assert applied["clawback_commitment_delta_cents"] == 16000000

    # Hop 2: waterfall target max(0, 4000000 - 11250000) = 0; stage 3 cancelled
    # (8750000 - 8750000 = 0 >= 0), stages 1-2 remain RELEASED.
    tranches = list_tranche_data(ctx)
    assert tranches[0]["status"] == "RELEASED"
    assert tranches[1]["status"] == "RELEASED"
    assert tranches[2]["status"] == "CANCELLED"

    # Hop 3: excess = 11250000 - 4000000 = 7250000 -> exactly one receivable.
    receivables = list_receivable_data(ctx)
    assert len(receivables) == 1
    assert receivables[0]["amount_due_cents"] == 7250000
    assert receivables[0]["status"] == "OPEN"
    assert applied["excess_due_cents"] == 7250000
    # due_date = created_at (2026-12-15, the apply instant) + 30 days.
    assert receivables[0]["due_date"].startswith("2027-01-14T00:00:00")

    # The clawback does not itself touch principal already out the door.
    assert loan["disbursed_total_cents"] == 11250000
    assert loan["outstanding_balance_cents"] == 11250000


def test_milestone_verify_cascade_enables_next_tranche(api):
    """PRD §3.7: "Eligibility is computed by walking the schedule in ascending `stage_number`: stage 1 is eligible exactly when the loan is `ACTIVE`, and each later stage becomes eligible when every earlier stage is `RELEASED` and the cumulative `verified_cost_cents` over the loan's `VERIFIED` milestones is at least the sum of the `amount_cents` of all earlier stages — equality at that boundary suffices."
    PRD §3.7: "Eligibility is re-evaluated at every milestone verification and at every tranche release."

    Design: Difficulty/transitive_cascade/milestone_verify_cascade_enables_next_tranche
    """
    # Setup: homeowner loan approved 20000000, accepted 2026-11-01; T1
    # (2500000) RELEASED; no milestones yet, so stage 2 is SCHEDULED.
    ctx = setup_loan_with_t1_released()
    assert ctx["tranches"][1]["status"] == "SCHEDULED"
    assert ctx["tranches"][2]["status"] == "SCHEDULED"

    # Trigger: one milestone decided VERIFIED at exactly the stage-1 amount.
    resp = api.create_milestone(
        ctx["loan"]["id"],
        {"description": "roof replaced", "claimed_cost_cents": 2500000},
        ctx["applicant_headers"])
    milestone = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_milestone"])
    resp = api.decide_milestone(
        milestone["id"],
        {"decision": "VERIFIED", "verified_cost_cents": 2500000},
        ctx["milestone_verifier_headers"])
    decided = validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_milestone"])
    # Hop 1: the milestone itself.
    assert decided["status"] == "VERIFIED"
    assert decided["verified_cost_cents"] == 2500000

    # Hop 2: with no tranche endpoint call in between, stage 2 flipped to
    # ELIGIBLE (cumulative verified 2500000 >= stage-1 amount 2500000).
    tranches = list_tranche_data(ctx)
    assert tranches[1]["status"] == "ELIGIBLE"
    # Stage 3 still short: 2500000 < stage1+stage2 amounts 11250000.
    assert tranches[2]["status"] == "SCHEDULED"

"""Depth tests: encounter parallel state axes and claim resubmission cycle."""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_tx_clinic, setup_assessed_encounter, setup_completed_encounter,
    setup_submitted_claim, set_clock, get_encounter, get_claim,
    TEST_USERS, FPL_INCOME_H1_PCT_174,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_clinical_axis_advances_while_billing_stays_unbilled(api):
    """PRD §3.5: "an encounter's clinical dimension moves through `SCHEDULED`,
    `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`, while its billing dimension
    moves through `UNBILLED`, `CLAIMED`, `SETTLED`, or `WAIVED`. The two
    dimensions evolve in parallel".

    Start then complete the encounter: clinical walks to COMPLETED while
    billing remains UNBILLED — the clinical axis never touches billing.

    Design: Difficulty/non_linear_state_machine/encounter_parallel_clinical_and_billing_dimensions
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-9",
    )
    enc_id = ctx["encounter"]["id"]
    set_clock("2026-09-10T10:00:00Z")

    started = validate_success(api_client.start_encounter(enc_id, CLINICIAN))
    assert started["clinical_status"] == "IN_PROGRESS"
    assert started["billing_status"] == "UNBILLED"

    completed = validate_success(api_client.complete_encounter(enc_id, CLINICIAN))
    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "UNBILLED", (
        "billing untouched by the clinical axis"
    )


def test_billing_axis_advances_while_clinical_stays_completed(api):
    """PRD §3.7: "Successful submission flips the encounter's `billing_status`
    from `UNBILLED` to `CLAIMED`."
    PRD §3.7: "Settlement flips the encounter from `CLAIMED` to `SETTLED`".

    Claim submission and settlement move billing UNBILLED -> CLAIMED ->
    SETTLED while clinical stays COMPLETED; the claim reaches PAID with
    net_receivable_cents 0 before settlement.

    Design: Difficulty/non_linear_state_machine/encounter_parallel_clinical_and_billing_dimensions
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-9",
    )
    enc = ctx["encounter"]
    claim = ctx["claim"]
    assert enc["clinical_status"] == "COMPLETED"
    assert enc["billing_status"] == "CLAIMED", (
        "submitting flips billing to CLAIMED while clinical stays COMPLETED"
    )

    paid = validate_success(
        api_client.adjudicate_claim(claim["id"], {"amount_cents": 10000}, BILLING)
    )
    assert paid["status"] == "PAID"
    assert paid["net_receivable_cents"] == 0

    settled = validate_success(api_client.settle_claim(claim["id"], BILLING))
    assert settled["billing_status"] == "SETTLED"
    assert settled["clinical_status"] == "COMPLETED", (
        "settlement never moves the clinical axis"
    )


def test_return_resubmit_cycle_increments_submission_round(api):
    """PRD §3.7: "A payer may return a submitted claim for correction; a
    `BillingSpecialist` records that transition as `SUBMITTED` → `RETURNED`.
    A returned claim may be resubmitted, flipping back to `SUBMITTED` and
    incrementing `submission_round` by 1".

    Two full return/resubmit loops move submission_round 1 -> 2 -> 3.

    Design: Difficulty/non_linear_state_machine/claim_return_resubmit_cycle_with_round_cap
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-CY",
    )
    claim_id = ctx["claim"]["id"]
    assert ctx["claim"]["submission_round"] == 1

    validate_success(api_client.return_claim(claim_id, BILLING))
    round2 = validate_success(api_client.resubmit_claim(claim_id, BILLING))
    assert round2["status"] == "SUBMITTED"
    assert round2["submission_round"] == 2

    validate_success(api_client.return_claim(claim_id, BILLING))
    round3 = validate_success(api_client.resubmit_claim(claim_id, BILLING))
    assert round3["status"] == "SUBMITTED"
    assert round3["submission_round"] == 3


def test_resubmit_at_round_three_rejected_with_exhausted_error(api):
    """PRD §3.7: "a returned claim may be resubmitted ... but only while
    `submission_round` is strictly less than 3 — a resubmit attempted at
    round 3 is rejected with `ERR_CLAIM_RESUBMISSION_EXHAUSTED` (HTTP 409)."

    After two loops the claim sits at round 3; the third resubmit attempt is
    rejected and submission_round does not drift past 3.

    Design: Difficulty/non_linear_state_machine/claim_return_resubmit_cycle_with_round_cap
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-CY2",
    )
    claim_id = ctx["claim"]["id"]
    for _ in range(2):
        validate_success(api_client.return_claim(claim_id, BILLING))
        validate_success(api_client.resubmit_claim(claim_id, BILLING))

    validate_success(api_client.return_claim(claim_id, BILLING))
    res = api_client.resubmit_claim(claim_id, BILLING)
    validate_error(res, "ERR_CLAIM_RESUBMISSION_EXHAUSTED", expected_status=409)

    claim = get_claim(claim_id)
    assert claim["submission_round"] == 3, (
        f"no drift after the rejected resubmit, got {claim['submission_round']}"
    )
    assert claim["status"] == "RETURNED"

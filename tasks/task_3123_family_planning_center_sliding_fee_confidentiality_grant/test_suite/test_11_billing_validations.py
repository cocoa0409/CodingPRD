"""Breadth tests: claim confidentiality, overpayment, settlement, and waiver."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_tx_clinic, setup_assessed_encounter, setup_completed_encounter,
    setup_submitted_claim, create_affiliate,
    set_clock, get_encounter, get_claim,
    TEST_USERS, FPL_INCOME_H1_PCT_174, FPL_INCOME_H1_PCT_265,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_confidential_minor_claim_submit_rejected(api):
    """PRD §3.7: "The `confidential_suppression` flag is set to `true`
    whenever the patient was a minor at the time of the encounter **or** the
    patient's `confidentiality_flag` is `true`; confidential services bypass
    third-party billing entirely."
    PRD §3.7: "a suppressed claim may never reach a payer, and submitting one
    is rejected with `ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL` (HTTP 422)."

    A minor's claim is created with confidential_suppression true and
    billed_cents 0; submitting it is rejected and nothing moves.

    Design: Corner/validations/confidential_minor_claim_submit_rejected
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_completed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        external_ref="MIN-C", date_of_birth="2011-06-01",
        insurance_policy_id="POL-MIN",
    )
    claim = validate_success(
        api_client.create_claim(ctx["encounter"]["id"], BILLING), 201
    )
    assert claim["confidential_suppression"] is True, (
        "a minor's claim carries confidential_suppression true"
    )
    assert claim["billed_cents"] == 0

    res = api_client.submit_claim(claim["id"], BILLING)
    validate_error(res, "ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL",
                   expected_status=422)

    claim_after = get_claim(claim["id"])
    assert claim_after["status"] == "DRAFT"
    enc_after = get_encounter(ctx["encounter"]["id"])
    assert enc_after["billing_status"] == "UNBILLED", (
        "the rejected submit never flips billing"
    )


def test_overpayment_beyond_net_receivable_rejected(api):
    """PRD §3.7: "The payment is capped: an amount exceeding the current
    `net_receivable_cents` is rejected with `ERR_OVERPAYMENT` (HTTP 422)."

    Adjudicating 10001 against a 10000-cent receivable is rejected and
    paid_cents does not move.

    Design: Corner/validations/overpayment_beyond_net_receivable_rejected
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-OV",
    )
    claim_id = ctx["claim"]["id"]
    assert ctx["claim"]["billed_cents"] == 10000

    res = api_client.adjudicate_claim(claim_id, {"amount_cents": 10001},
                                      BILLING)
    validate_error(res, "ERR_OVERPAYMENT", expected_status=422)
    claim_after = get_claim(claim_id)
    assert claim_after["paid_cents"] == 0
    assert claim_after["status"] == "SUBMITTED"


def test_report_finalize_before_period_close_rejected(api):
    """PRD §3.10: "Finalization requires the period to have closed: a
    finalize attempted before the logical clock has reached `period_end` is
    rejected with `ERR_REPORT_PERIOD_OPEN` (HTTP 409)."

    Mid-period finalize is 409 ERR_REPORT_PERIOD_OPEN; after the clock
    reaches period_end exactly, the same finalize succeeds.

    Design: Corner/validations/report_finalize_before_period_close_rejected
    """
    set_clock("2026-09-01T00:00:00Z")

    aff = create_affiliate()
    set_clock("2026-09-15T00:00:00Z")
    report = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff["version"]},
            ADMIN,
        ),
        201,
    )
    res = api_client.finalize_grant_report(report["id"], ADMIN)
    validate_error(res, "ERR_REPORT_PERIOD_OPEN", expected_status=409)
    draft = validate_success(api_client.get_grant_report(report["id"], ADMIN))
    assert draft["status"] == "DRAFT"

    set_clock("2026-10-01T00:00:00Z")
    finalized = validate_success(
        api_client.finalize_grant_report(report["id"], ADMIN)
    )
    assert finalized["status"] == "FINALIZED", (
        "after the clock reaches period_end exactly, finalize succeeds"
    )


def test_overlapping_draft_report_period_rejected(api):
    """PRD §3.10: "no two `DRAFT` reports on the same affiliate may have
    overlapping half-open periods; creation of a second overlapping draft is
    rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

    A second DRAFT overlapping the first by one second is 409; a back-to-back
    period starting exactly at the prior period_end is allowed.

    Design: Corner/validations/overlapping_draft_report_period_rejected
    """
    set_clock("2026-09-01T00:00:00Z")

    aff = create_affiliate()
    set_clock("2026-09-15T00:00:00Z")
    report1 = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff["version"]},
            ADMIN,
        ),
        201,
    )
    aff_now = validate_success(api_client.get_affiliate(aff["id"], ADMIN))

    res = api_client.create_grant_report(
        aff["id"],
        {"period_start": "2026-09-30T23:59:59Z",
         "period_end": "2026-11-01T00:00:00Z",
         "valuation_variant": "FIFO",
         "expected_affiliate_version": aff_now["version"]},
        ADMIN,
    )
    validate_error(res, "ERR_REPORT_PERIOD_OVERLAP", expected_status=409)

    aff_after_reject = validate_success(
        api_client.get_affiliate(aff["id"], ADMIN)
    )
    assert aff_after_reject["version"] == aff_now["version"], (
        "the rejected create leaves the affiliate version unchanged"
    )

    report2 = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-10-01T00:00:00Z",
             "period_end": "2026-11-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff_after_reject["version"]},
            ADMIN,
        ),
        201,
    )
    assert report2["status"] == "DRAFT", (
        "back-to-back half-open periods do not overlap"
    )


def test_settle_requires_zero_net_or_denial(api):
    """PRD §3.7: "Settlement is available when the encounter is `COMPLETED`
    and `CLAIMED` and the open claim has reached `PAID` with
    `net_receivable_cents` equal to 0, or has reached `DENIED` (the denial
    implying a patient write-off). ... settling under any other claim
    configuration is rejected with `ERR_CLAIM_NOT_SETTLEABLE` (HTTP 409)."
    PRD §3.7: "its `net_receivable_cents` is computed as `billed_cents` minus
    `paid_cents` plus `recouped_cents`".

    A partial adjudication leaves net 4000 — settle is 409; a recoup then
    RAISES the residual to 8000, so the second settle is also 409 and billing
    stays CLAIMED.

    Design: Corner/endpoints/settle_requires_zero_net_or_denial
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-S",
    )
    claim_id = ctx["claim"]["id"]
    enc_id = ctx["encounter"]["id"]

    validate_success(
        api_client.adjudicate_claim(claim_id, {"amount_cents": 6000}, BILLING)
    )
    res = api_client.settle_claim(claim_id, BILLING)
    validate_error(res, "ERR_CLAIM_NOT_SETTLEABLE", expected_status=409)

    recouped = validate_success(
        api_client.recoup_claim(claim_id, {"amount_cents": 4000}, BILLING)
    )
    assert recouped["net_receivable_cents"] == 8000, (
        "recoupment moves the claim away from settleable: "
        "10000 - 6000 + 4000 = 8000"
    )
    res2 = api_client.settle_claim(claim_id, BILLING)
    validate_error(res2, "ERR_CLAIM_NOT_SETTLEABLE", expected_status=409)

    enc_after = get_encounter(enc_id)
    assert enc_after["billing_status"] == "CLAIMED", (
        "never SETTLED with a residual receivable"
    )

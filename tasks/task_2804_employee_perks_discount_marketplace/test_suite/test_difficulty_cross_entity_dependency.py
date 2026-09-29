"""Queue A — cross_entity_state_dependency.

Every test below translates exactly one instance of §1.8's difficulty design
index; the `Design:` line of each docstring names it.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    AgreementStatus, ApiErrorId, DisputeReason, IntegrationStatus,
    MerchantStatus, OfferStatus, ProgramPosture, VerificationStatus,
    api_client, assertions as A, constants as C, factories as F,
    fixtures as fx, make_employee_headers, make_merchant_headers,
)


def _program_whose_feed_has_gone_stale():
    """A `LIVE` programme that the epoch sweep drags to `RESTRICTED`.

    The roster is applied at 2026-08-01, one redemption is reserved at
    2026-09-14 while the programme is still `LIVE`, and the clock then moves to
    2026-09-16 — past `last_sync_at` plus 45 days but short of the redemption's
    own 2026-09-17 verification deadline.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        employer_overrides={"employee_count_declared": 1},
        offer_overrides={
            "title": "20 percent off dinner", "min_spend_cents": 1000,
            "window_start": "2026-08-01T00:00:00Z",
            "window_end": "2026-12-01T00:00:00Z",
        },
    )
    assert program["employer"]["program_posture"] == ProgramPosture.LIVE.value

    fx.set_clock("2026-09-14T00:00:00Z")
    program["redemption"] = fx.create_redemption(
        program["offer"]["id"], program["memberships"][0]["id"],
        intended_gross_amount_cents=5000,
    )
    A.assert_iso_equals(
        program["redemption"]["verification_expires_at"], "2026-09-17T00:00:00Z"
    )
    fx.set_clock("2026-09-16T00:00:00Z")
    program["sweep"] = fx.run_epoch()
    return program


def test_stale_eligibility_feed_restricts_the_programme_and_blocks_new_reservations():
    """The redemption write is gated by the *employer's* derived posture.

    PRD: "A `RESTRICTED` posture refuses exactly one operation, creating a redemption, with `ERR_PROGRAM_RESTRICTED` — a published storefront running on a stale eligibility feed accepts no new commitments, but a redemption that was already `PENDING` when the feed went stale can still be verified and fulfilled normally, and slots may still be reserved and confirmed against it."

    Design: Difficulty/cross_entity_state_dependency/restricted_posture_from_stale_feed_blocks_new_redemption_while_pending_one_still_verifies
    """
    program = _program_whose_feed_has_gone_stale()

    A.assert_sweep_counts(
        program["sweep"], stale_employer_count=1, voided_redemption_count=0
    )
    employer = fx.get_employer(program["employer"]["id"])
    A.assert_fields(employer, {
        "integration_status": IntegrationStatus.STALE.value,
        "program_posture": ProgramPosture.RESTRICTED.value,
    }, "employer")

    membership_id = program["memberships"][0]["id"]
    response = api_client.create_redemption(
        F.redemption_payload(
            program["offer"]["id"], membership_id, intended_gross_amount_cents=5000
        ),
        make_employee_headers(membership_id),
    )
    validate_error(response, ApiErrorId.PROGRAM_RESTRICTED)


def test_a_pending_redemption_still_verifies_against_a_restricted_programme():
    """The dependency is asymmetric: creation is refused, verification is not.

    PRD: "the employer's `program_posture` must be `LIVE` or `RESTRICTED`, so a `FROZEN` programme is refused with `ERR_PROGRAM_FROZEN` — note that a `RESTRICTED` programme still permits verification even though it refuses new reservations"

    Design: Difficulty/cross_entity_state_dependency/restricted_posture_from_stale_feed_blocks_new_redemption_while_pending_one_still_verifies
    """
    program = _program_whose_feed_has_gone_stale()
    assert fx.get_employer(program["employer"]["id"])["program_posture"] == (
        ProgramPosture.RESTRICTED.value
    )

    verified = fx.verify_redemption(
        program["redemption"], program["merchant"]["id"], gross_amount_cents=5000
    )

    assert verified["verification_status"] == VerificationStatus.VERIFIED.value
    A.assert_line_economics(verified, 5000, 1000, 4000, 480, 120, 360)


def _partner_with_two_fault_disputes():
    """Two verified lines, each disputed, the first already judged at fault.

    Both resolutions land on 2026-08-01 so both fault events sit in the
    undecayed tier: one event scores 20 and two score 40, exactly the
    suspension threshold.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        employer_overrides={"employee_count_declared": 1},
        offer_overrides={
            "title": "20 percent off dinner", "min_spend_cents": 1000,
            "inventory_limit": 10, "per_member_limit": 5,
        },
    )
    merchant_id = program["merchant"]["id"]
    membership_id = program["memberships"][0]["id"]
    lines = []
    for _ in range(2):
        created = fx.create_redemption(
            program["offer"]["id"], membership_id, intended_gross_amount_cents=5000
        )
        fx.verify_redemption(created, merchant_id, gross_amount_cents=5000)
        lines.append(created)

    first = fx.file_dispute(
        lines[0]["id"], membership_id, reason=DisputeReason.NOT_HONORED,
        description="The discount was refused at the till.",
    )
    fx.resolve_dispute(first["id"], "MERCHANT_FAULT", outcome_credit_cents=0)
    after_one = fx.get_merchant(merchant_id)
    assert after_one["fulfillment_failure_score"] == 20
    assert after_one["status"] == MerchantStatus.ACTIVE.value

    second = fx.file_dispute(
        lines[1]["id"], membership_id, reason=DisputeReason.NOT_HONORED,
        description="Second visit, discount refused again.",
    )
    program["second_dispute"] = second
    return program


def test_second_merchant_fault_reaches_forty_points_and_pauses_the_partner_offer():
    """The offer leaves `ACTIVE` because the *merchant* crossed the threshold.

    PRD: "When the recomputed score reaches the suspension threshold and the partner's `status` is `ACTIVE`, that status moves `ACTIVE → SUSPENDED` with `suspended_at` set to the logical clock, every `ACTIVE` offer of the partner is paused with `paused_reason` of `MERCHANT_SUSPENDED`, and every `RESERVED` or `CONFIRMED` placement slot of those offers is released with `release_reason` of `OFFER_PAUSED`, each formerly `CONFIRMED` slot writing its compensating placement-fee refund."

    Design: Difficulty/cross_entity_state_dependency/merchant_fault_score_suspension_pauses_offer_and_blocks_resume
    """
    program = _partner_with_two_fault_disputes()
    merchant_id = program["merchant"]["id"]

    fx.resolve_dispute(
        program["second_dispute"]["id"], "MERCHANT_FAULT", outcome_credit_cents=0
    )

    merchant = fx.get_merchant(merchant_id)
    A.assert_fields(merchant, {
        "fulfillment_failure_score": C.MERCHANT_SUSPEND_SCORE,
        "fault_event_count": 2,
        "status": MerchantStatus.SUSPENDED.value,
    }, "merchant")
    assert merchant["fulfillment_failure_score"] == 40
    offer = fx.get_offer(program["offer"]["id"])
    A.assert_fields(offer, {
        "status": OfferStatus.PAUSED.value,
        "paused_reason": C.MERCHANT_SUSPENDED_REASON,
    }, "offer")


def test_paused_offer_cannot_be_resumed_while_its_partner_stays_suspended():
    """The block comes from the merchant dimension, not from the agreement.

    PRD: "A resumption attempt on a suspended partner is refused with `ERR_MERCHANT_SUSPENDED`, one on a lapsed agreement with `ERR_AGREEMENT_NOT_ACTIVE`, and one whose redemption window has already closed with `ERR_OFFER_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/merchant_fault_score_suspension_pauses_offer_and_blocks_resume
    """
    program = _partner_with_two_fault_disputes()
    merchant_id = program["merchant"]["id"]
    offer_id = program["offer"]["id"]
    fx.resolve_dispute(
        program["second_dispute"]["id"], "MERCHANT_FAULT", outcome_credit_cents=0
    )

    response = api_client.resume_offer(offer_id, make_merchant_headers(merchant_id))

    validate_error(response, ApiErrorId.MERCHANT_SUSPENDED)
    # The governing agreement never left ACTIVE, so nothing but the partner's
    # own status can be refusing the resume.
    assert fx.get_agreement(program["agreement"]["id"])["status"] == (
        AgreementStatus.ACTIVE.value
    )
    assert fx.get_offer(offer_id)["status"] == OfferStatus.PAUSED.value

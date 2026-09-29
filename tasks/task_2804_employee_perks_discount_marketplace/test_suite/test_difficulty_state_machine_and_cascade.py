"""Queue A — non_linear_state_machine and transitive_cascade.

Every test below translates exactly one instance of §1.8's difficulty design
index; the `Design:` line of each docstring names it.
"""
from prd_bench_local_runner.testing import (
    validate_error, validate_paginated, validate_success,
)

from test_helpers import (
    AgreementStatus, ApiErrorId, DisputeStatus, EmploymentStatus,
    FulfillmentStatus, LedgerEntryType, MembershipStatus, MerchantStatus,
    OfferStatus, PlacementTier, ProposerRole, ReleaseReason, SlotStatus,
    VerificationStatus, VoidReason, api_client, assertions as A,
    factories as F, fixtures as fx, make_admin_headers,
    make_merchant_headers, make_partner_manager_headers,
)


# ── non_linear_state_machine ────────────────────────────────────────────────


def _negotiating_lane():
    """A `PROSPECT` DINING/CA partner with one `DRAFT` agreement on it."""
    fx.set_clock("2026-08-01T00:00:00Z")
    merchant = fx.create_merchant(
        legal_name="Bistro Uno", contact_email="ops@bistrouno.example",
        primary_category="DINING", region_codes=["CA"],
    )
    agreement = fx.create_agreement(
        merchant["id"], category="DINING", region_code="CA"
    )
    assert agreement["round_count"] == 0
    return merchant, agreement


def _four_rounds(merchant, agreement):
    """Alternate provider and merchant rounds until `round_count` is 4.

    Returns the agreement status observed after each of the four rounds, in
    order.
    """
    merchant_id = merchant["id"]
    statuses = []
    terms = [
        (1200, 36000, 2500, "round 1 provider"),
        (900, 30000, 1000, "round 2 merchant"),
        (1100, 34000, 2000, "round 3 provider"),
        (1000, 32000, 1500, "round 4 merchant"),
    ]
    for index, (commission, base, share, note) in enumerate(terms):
        current = fx.get_agreement(agreement["id"])
        overrides = {
            "commission_rate_bps": commission,
            "placement_fee_base_cents": base,
            "employer_revenue_share_bps": share,
            "note": note,
        }
        if index % 2 == 0:
            fx.propose_round(current, **overrides)
        else:
            fx.counter_round(current, merchant_id, **overrides)
        statuses.append(fx.get_agreement(agreement["id"])["status"])
    return statuses


def test_agreement_reenters_provider_proposed_after_a_merchant_counter():
    """Round 3 puts the agreement back into a state it had already left.

    PRD: "A `PartnerManager` proposes terms, moving the agreement `DRAFT → PROVIDER_PROPOSED` or, when the merchant has already replied, `MERCHANT_COUNTERED → PROVIDER_PROPOSED`."

    Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycle_revisits_provider_proposed_and_stops_at_round_cap
    """
    merchant, agreement = _negotiating_lane()

    statuses = _four_rounds(merchant, agreement)

    assert statuses == [
        AgreementStatus.PROVIDER_PROPOSED.value,
        AgreementStatus.MERCHANT_COUNTERED.value,
        # The cycle closes here: PROVIDER_PROPOSED is occupied a second time.
        AgreementStatus.PROVIDER_PROPOSED.value,
        AgreementStatus.MERCHANT_COUNTERED.value,
    ]
    final = fx.get_agreement(agreement["id"])
    assert final["round_count"] == 4
    assert fx.get_merchant(merchant["id"])["status"] == MerchantStatus.IN_NEGOTIATION.value


def test_fifth_negotiation_round_is_refused_once_round_count_reaches_four():
    """The cycle is bounded by the counter, not by the state graph.

    PRD: "Proposing or countering while `round_count` is already 4 or greater is refused with `ERR_NEGOTIATION_ROUND_LIMIT` — that is, the fifth round attempt on one agreement fails, whichever side attempts it."

    Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycle_revisits_provider_proposed_and_stops_at_round_cap
    """
    merchant, agreement = _negotiating_lane()
    _four_rounds(merchant, agreement)
    standing = fx.get_agreement(agreement["id"])

    # MERCHANT_COUNTERED -> PROVIDER_PROPOSED is a declared transition, so only
    # the round budget can refuse this call.
    response = api_client.propose_round(
        agreement["id"],
        F.round_payload(
            standing["version"], commission_rate_bps=1050,
            placement_fee_base_cents=33000, employer_revenue_share_bps=1800,
            note="round 5 provider",
        ),
        make_partner_manager_headers(),
    )
    validate_error(response, ApiErrorId.NEGOTIATION_ROUND_LIMIT)

    after = fx.get_agreement(agreement["id"])
    assert after["round_count"] == 4
    assert after["status"] == AgreementStatus.MERCHANT_COUNTERED.value
    # The refused round left the standing terms exactly where round 4 put them.
    assert after["commission_rate_bps"] == 1000
    assert after["placement_fee_base_cents"] == 32000
    assert after["employer_revenue_share_bps"] == 1500


def test_negotiation_history_records_the_alternating_authorship_of_the_cycle():
    """Four immutable rounds, numbered 1 to 4, alternating between the sides.

    PRD: "The full round history is readable as an append-only list ordered by `round_number` ascending; rounds are immutable, and as noted in §2.5 they carry neither `updated_at` nor `version`."

    Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycle_revisits_provider_proposed_and_stops_at_round_cap
    """
    merchant, agreement = _negotiating_lane()
    _four_rounds(merchant, agreement)

    response = api_client.list_negotiation_rounds(
        agreement["id"], make_partner_manager_headers()
    )
    rounds, meta = validate_paginated(response)

    assert meta["total_count"] == 4
    assert [row["round_number"] for row in rounds] == [1, 2, 3, 4]
    assert [row["proposer_role"] for row in rounds] == [
        ProposerRole.PARTNER_MANAGER.value,
        ProposerRole.MERCHANT.value,
        ProposerRole.PARTNER_MANAGER.value,
        ProposerRole.MERCHANT.value,
    ]
    for row in rounds:
        A.assert_append_only_record(row, "negotiation round")


def _disputed_line():
    """One verified 8,396 cent line, fulfilled and then disputed.

    Returns ``{"program", "redemption", "dispute"}``; the merchant has already
    answered the dispute, so it sits in `MERCHANT_RESPONDED`.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        offer_overrides={
            "title": "20 percent off dinner", "min_spend_cents": 1000,
            "inventory_limit": 10, "per_member_limit": 5,
        },
    )
    merchant_id = program["merchant"]["id"]
    membership_id = program["memberships"][0]["id"]
    created = fx.create_redemption(
        program["offer"]["id"], membership_id, intended_gross_amount_cents=8396
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.verify_redemption(created, merchant_id, gross_amount_cents=8396)
    fulfilled = fx.fulfill_redemption(created["id"], merchant_id)
    assert fulfilled["fulfillment_status"] == FulfillmentStatus.FULFILLED.value

    dispute = fx.file_dispute(
        created["id"], membership_id, reason="WRONG_DISCOUNT",
        description="The till applied a smaller discount than advertised.",
    )
    fx.respond_dispute(
        dispute["id"], merchant_id,
        response_note="Till receipt shows the advertised discount was applied.",
    )
    return {
        "program": program, "redemption": created, "dispute": dispute,
        "fulfilled_at": fulfilled["fulfilled_at"],
    }


def test_no_fault_resolution_returns_the_fulfilment_dimension_to_fulfilled():
    """FULFILLED → DISPUTED → FULFILLED: the dimension revisits its own state.

    PRD: "It moves the redemption's fulfilment dimension `DISPUTED → FULFILLED` — completing the cycle `AWAITING` or `FULFILLED` → `DISPUTED` → `FULFILLED` — and stamps `fulfilled_at` from the logical clock only when it was still null, so a redemption that had already been fulfilled before the dispute keeps its original `fulfilled_at`."

    Design: Difficulty/non_linear_state_machine/redemption_fulfilment_dimension_reenters_fulfilled_while_verification_dimension_frozen
    """
    scenario = _disputed_line()
    redemption_id = scenario["redemption"]["id"]
    merchant_id = scenario["program"]["merchant"]["id"]

    disputed = fx.get_redemption(redemption_id, merchant_id=merchant_id)
    assert disputed["fulfillment_status"] == FulfillmentStatus.DISPUTED.value

    dispute = fx.resolve_dispute(scenario["dispute"]["id"], "NO_FAULT")

    A.assert_fields(dispute, {
        "status": DisputeStatus.RESOLVED_NO_FAULT.value,
        "outcome_credit_cents": 0,
    }, "dispute")
    resolved = fx.get_redemption(redemption_id, merchant_id=merchant_id)
    assert resolved["fulfillment_status"] == FulfillmentStatus.FULFILLED.value
    A.assert_iso_equals(resolved["fulfilled_at"], scenario["fulfilled_at"])


def test_verification_dimension_stays_frozen_across_the_fulfilment_cycle():
    """Three fulfilment moves later the line is still `VERIFIED` and unrefunded.

    PRD: "It writes no ledger entry, never touches any statement, and leaves `fault_event_count`, `fulfillment_failure_score`, `accrued_commission_payable_cents` and `accrued_share_cents` exactly as they were."

    Design: Difficulty/non_linear_state_machine/redemption_fulfilment_dimension_reenters_fulfilled_while_verification_dimension_frozen
    """
    scenario = _disputed_line()
    redemption_id = scenario["redemption"]["id"]
    merchant_id = scenario["program"]["merchant"]["id"]

    fx.resolve_dispute(scenario["dispute"]["id"], "NO_FAULT")

    resolved = fx.get_redemption(redemption_id, merchant_id=merchant_id)
    assert resolved["verification_status"] == VerificationStatus.VERIFIED.value
    A.assert_nulls(resolved, ["refunded_at", "voided_at", "void_reason"], "redemption")

    entries = fx.redemption_ledger_entries(redemption_id)
    A.assert_ledger_signature(entries, [
        (LedgerEntryType.COMMISSION_ACCRUAL.value, 806),
        (LedgerEntryType.EMPLOYER_SHARE.value, -202),
    ])
    merchant = fx.get_merchant(merchant_id)
    A.assert_fields(merchant, {
        "fault_event_count": 0,
        "fulfillment_failure_score": 0,
        "status": MerchantStatus.ACTIVE.value,
    }, "merchant")


# ── transitive_cascade ──────────────────────────────────────────────────────


def _sold_out_single_unit_program():
    """One offer with `inventory_limit` 1 held by the roster's only member.

    The single `PENDING` redemption puts `inventory_reserved` at 1 and
    `sold_out` at true, so releasing that unit is observable.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        employer_overrides={"employee_count_declared": 1},
        offer_overrides={
            "title": "20 percent off dinner", "min_spend_cents": 1000,
            "inventory_limit": 1, "per_member_limit": 5,
        },
    )
    program["membership"] = program["memberships"][0]
    program["redemption"] = fx.create_redemption(
        program["offer"]["id"], program["membership"]["id"],
        intended_gross_amount_cents=5000,
    )
    held = fx.get_offer(program["offer"]["id"])
    assert held["inventory_reserved"] == 1
    assert held["sold_out"] is True
    return program


def test_employment_termination_revokes_the_membership_and_voids_its_redemption():
    """One employment write drives eligibility, which drives the redemption.

    PRD: "Writing `TERMINATED` moves the membership `ELIGIBLE → REVOKED` and runs a three-level cascade: the employment write drives the eligibility dimension to `REVOKED`, which voids the membership's `PENDING` redemptions with `void_reason` `MEMBERSHIP_INELIGIBLE`, which in turn lowers each affected offer's `inventory_reserved` by 1 and recomputes its `sold_out` flag."

    Design: Difficulty/transitive_cascade/employment_termination_revokes_membership_voids_redemption_and_frees_inventory
    """
    program = _sold_out_single_unit_program()
    employer_id = program["employer"]["id"]
    membership_id = program["membership"]["id"]

    fx.set_employment_status(
        membership_id, employer_id, EmploymentStatus.TERMINATED.value
    )

    membership = fx.get_membership(membership_id, employer_id)
    A.assert_fields(membership, {
        "employment_status": EmploymentStatus.TERMINATED.value,
        "status": MembershipStatus.REVOKED.value,
    }, "membership")
    voided = fx.get_redemption(program["redemption"]["id"])
    A.assert_fields(voided, {
        "verification_status": VerificationStatus.VOID.value,
        "void_reason": VoidReason.MEMBERSHIP_INELIGIBLE.value,
    }, "redemption")


def test_voiding_the_cascaded_redemption_frees_the_last_inventory_unit():
    """Link 3 of the chain flips `sold_out` from true back to false.

    PRD: "All three release the reserved inventory unit and recompute `sold_out` in exactly the same way."

    Design: Difficulty/transitive_cascade/employment_termination_revokes_membership_voids_redemption_and_frees_inventory
    """
    program = _sold_out_single_unit_program()
    employer_id = program["employer"]["id"]

    fx.set_employment_status(
        program["membership"]["id"], employer_id, EmploymentStatus.TERMINATED.value
    )

    offer = fx.get_offer(program["offer"]["id"])
    A.assert_fields(offer, {
        "inventory_reserved": 0,
        "inventory_redeemed": 0,
        "sold_out": False,
        "status": OfferStatus.ACTIVE.value,
    }, "offer")
    # The revoked membership no longer counts toward the reach figure either.
    assert fx.get_employer(employer_id)["eligible_headcount"] == 0


def _confirmed_placement_program():
    """An `ACTIVE` partner whose only offer carries one `CONFIRMED` slot.

    The employer's `eligible_headcount` is 1, so the reach surcharge tier is 0
    basis points and the two-day STANDARD slot prices at a flat 72,000 cents.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, placement_fee_base_cents=36000,
        employer_revenue_share_bps=2500, revenue_share_enabled=True,
        privacy_min_cohort_size=3,
        employer_overrides={"employee_count_declared": 1},
        offer_overrides={
            "title": "20 percent off dinner", "min_spend_cents": 1000,
            "inventory_limit": 10, "per_member_limit": 5,
        },
    )
    slot = fx.reserve_slot(
        program["offer"], program["employer"]["id"], program["merchant"]["id"],
        placement_tier=PlacementTier.STANDARD,
        slot_window_start="2026-09-01T00:00:00Z",
        slot_window_end="2026-09-03T00:00:00Z",
    )
    assert slot["placement_fee_cents"] == 72000
    program["slot"] = fx.confirm_slot(slot["id"])
    assert program["slot"]["status"] == SlotStatus.CONFIRMED.value
    return program


def test_partner_termination_cascades_through_agreement_offer_and_slot():
    """Four levels fall from one call, each impossible without the one above.

    PRD: "It moves the partner to the terminal `TERMINATED` status and cascades four levels: every agreement of the partner whose `status` is `DRAFT`, `PROVIDER_PROPOSED`, `MERCHANT_COUNTERED`, `ACCEPTED` or `ACTIVE` is terminated with `terminated_reason` set to the fixed string `MERCHANT_TERMINATED`; each terminated agreement expires its `DRAFT`, `PENDING_REVIEW`, `ACTIVE` and `PAUSED` offers; each expired offer releases its `RESERVED` and `CONFIRMED` slots, every formerly `CONFIRMED` slot writing its compensating placement-fee refund; and `active_agreement_count` is recomputed, which necessarily leaves it at 0."

    Design: Difficulty/transitive_cascade/merchant_termination_cascades_agreement_offer_slot_and_refunds_placement_fee
    """
    program = _confirmed_placement_program()
    merchant_id = program["merchant"]["id"]

    response = api_client.terminate_merchant(
        merchant_id, F.terminate_payload(terminated_reason="Partner exited the programme"),
        make_admin_headers(),
    )
    validate_success(response)

    merchant = fx.get_merchant(merchant_id)
    A.assert_fields(merchant, {
        "status": MerchantStatus.TERMINATED.value,
        "active_agreement_count": 0,
    }, "merchant")
    assert fx.get_agreement(program["agreement"]["id"])["status"] == (
        AgreementStatus.TERMINATED.value
    )
    assert fx.get_offer(program["offer"]["id"])["status"] == OfferStatus.EXPIRED.value
    slot = fx.get_slot(program["slot"]["id"])
    A.assert_fields(slot, {
        "status": SlotStatus.RELEASED.value,
        "release_reason": ReleaseReason.AGREEMENT_TERMINATED.value,
    }, "placement slot")


def test_released_confirmed_slot_writes_a_compensating_placement_fee_refund():
    """The deepest link of the chain is a ledger pair that nets to zero.

    PRD: "`PLACEMENT_FEE_REFUND`, negative, written when a `CONFIRMED` slot is released, for the same `placement_fee_cents`."

    Design: Difficulty/transitive_cascade/merchant_termination_cascades_agreement_offer_slot_and_refunds_placement_fee
    """
    program = _confirmed_placement_program()
    merchant_id = program["merchant"]["id"]
    slot_id = program["slot"]["id"]

    before = fx.ledger_entries(placement_slot_id=slot_id)
    A.assert_ledger_signature(before, [(LedgerEntryType.PLACEMENT_FEE.value, 72000)])
    assert fx.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 72000

    validate_success(api_client.terminate_merchant(
        merchant_id, F.terminate_payload(terminated_reason="Partner exited the programme"),
        make_admin_headers(),
    ))

    after = fx.ledger_entries(placement_slot_id=slot_id)
    A.assert_ledger_signature(after, [
        (LedgerEntryType.PLACEMENT_FEE.value, 72000),
        (LedgerEntryType.PLACEMENT_FEE_REFUND.value, -72000),
    ])
    A.assert_ledger_nets_to_zero(after)
    assert fx.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 0

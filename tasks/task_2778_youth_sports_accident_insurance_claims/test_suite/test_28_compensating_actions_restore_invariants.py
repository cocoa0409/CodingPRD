"""Compensating actions and the aggregates they must put back.

Two compensations are exercised. Voiding a benefit payment must undo both halves
of what issuing it did: the cash it added to the term's paid loss and the case
reserve the closing claim released. Withdrawing a claim must undo the open-claim
cardinality and the reserve that verification created, and must sweep the claim's
priced charges to voided.

Every test builds its own world from an empty database through PRD-declared
endpoints, threading the real League id into every LeagueAdministrator call.
"""
from test_helpers import (
    BASEBALL_404_ANNUAL_PREMIUM_CENTS,
    RESERVE_BY_SEVERITY_CENTS,
    VERIFYING_OFFICIAL_USER_ID,
    assert_benefit_payment,
    assert_claim,
    assert_league_policy,
    assert_loss_position_invariants,
    assert_open_claim_cardinality,
    assert_paid_loss_matches_issued_payments,
    assert_provider_bill,
    bills_for_claim,
    canonical_iso,
    create_benefit_payment_payload,
    discover_claim,
    file_injury_report,
    list_rows,
    make_claims_examiner_headers,
    make_league_admin_headers,
    payments_for_claim,
    read_claim,
    read_injury_report,
    read_policy,
    read_provider_bill,
    record_provider_bill,
    reprice_bill,
    set_clock,
    setup_approved_full_excess_claim,
    setup_sanctioned_activity,
    validate_success,
    verify_injury_report,
)

CLAIMS_EXAMINER = make_claims_examiner_headers()

# The logical clock both worlds sit on from the moment the report is filed.
FILING_CLOCK = "2026-07-12T00:00:00Z"

# A 404-life BASEBALL_U12 term earning 822,840 cents of annual premium.
ANNUAL_PREMIUM_CENTS = BASEBALL_404_ANNUAL_PREMIUM_CENTS
FULL_EXCESS_TERM = {
    "enrolled_participant_count": 404,
    "coverage_basis_election": "FULL_EXCESS_PERMITTED",
    "cat_layer_elected": True,
}
EXCESS_ONLY_TERM = {
    "enrolled_participant_count": 404,
    "coverage_basis_election": "EXCESS_ONLY",
    "cat_layer_elected": True,
}

# A SEVERE knee injury inside the default game window, reserving 1,500,000 cents.
SEVERE_KNEE_REPORT = {
    "injury_datetime": "2026-07-11T19:15:00Z",
    "body_part": "KNEE",
    "injury_description": "outfield collision, suspected meniscus tear",
    "severity_tier": "SEVERE",
}
SEVERE_RESERVE_CENTS = RESERVE_BY_SEVERITY_CENTS["SEVERE"]

# In-network emergency-room charge: allowed 385,000 under the SEVERE-adjusted
# 575,000 cap, leaving 335,000 payable after the doubled 50,000 deductible.
EMERGENCY_ROOM_CHARGE = {
    "provider_npi": "1639072284",
    "provider_name": "Mill Creek Emergency Associates",
    "network_status": "IN_NETWORK",
    "service_category": "EMERGENCY_ROOM",
    "service_date": "2026-07-11",
    "billed_charge_cents": 620000,
    "fee_schedule_amount_cents": 385000,
}
BENEFIT_PAYABLE_CENTS = 335000

# In-network diagnostic-imaging charge on the withdrawal world.
IMAGING_CHARGE = {
    "provider_npi": "1720345508",
    "provider_name": "Prairie Ridge Orthopedics",
    "network_status": "IN_NETWORK",
    "service_category": "DIAGNOSTIC_IMAGING",
    "service_date": "2026-07-11",
    "billed_charge_cents": 480000,
    "fee_schedule_amount_cents": 260000,
}

# 1,500,000 * 10000 / 822,840 rounded half up; 335,000 * 10000 / 822,840 likewise.
RESERVED_LOSS_RATIO_BPS = 18230
PAID_LOSS_RATIO_BPS = 4071

LOSS_AGGREGATE_FIELDS = (
    "paid_loss_cents",
    "reserve_cents",
    "incurred_loss_cents",
    "open_claim_count",
    "incurred_loss_ratio_bps",
    "paid_loss_ratio_bps",
    "experience_tier",
    "coverage_posture",
)

# The whole loss position of a 404-life term carrying one open SEVERE claim.
ONE_OPEN_SEVERE_CLAIM = {
    "paid_loss_cents": 0,
    "reserve_cents": SEVERE_RESERVE_CENTS,
    "incurred_loss_cents": SEVERE_RESERVE_CENTS,
    "open_claim_count": 1,
    "incurred_loss_ratio_bps": RESERVED_LOSS_RATIO_BPS,
    "paid_loss_ratio_bps": 0,
    "experience_tier": "DECLINE",
    "coverage_posture": "CLAIMS_REVIEW",
}

# The same term once the single claim has been paid out in full and closed.
ONE_PAID_SEVERE_CLAIM = {
    "paid_loss_cents": BENEFIT_PAYABLE_CENTS,
    "reserve_cents": 0,
    "incurred_loss_cents": BENEFIT_PAYABLE_CENTS,
    "open_claim_count": 0,
    "incurred_loss_ratio_bps": PAID_LOSS_RATIO_BPS,
    "paid_loss_ratio_bps": PAID_LOSS_RATIO_BPS,
    "experience_tier": "STANDARD",
    "coverage_posture": "OPEN",
}

# The loss position of a 404-life term that carries no claim at all.
NO_CLAIMS_AT_ALL = {
    "paid_loss_cents": 0,
    "reserve_cents": 0,
    "incurred_loss_cents": 0,
    "open_claim_count": 0,
    "incurred_loss_ratio_bps": 0,
    "paid_loss_ratio_bps": 0,
    "experience_tier": "PREFERRED",
    "coverage_posture": "OPEN",
}


def _loss_aggregates(policy):
    """The eight figures a compensating action is required to put back."""
    return {field: policy[field] for field in LOSS_AGGREGATE_FIELDS}


def _claims_for_policy(api, league_policy_id):
    return list_rows(
        api.list_claims(CLAIMS_EXAMINER, {"league_policy_id": league_policy_id})
    )


def _approved_full_excess_claim():
    """A 404-life term with one SEVERE knee claim adjudicated on a full-excess
    footing and its emergency-room charge already ADJUDICATED."""
    return setup_approved_full_excess_claim(
        policy_overrides=dict(FULL_EXCESS_TERM),
        report_overrides=dict(SEVERE_KNEE_REPORT),
        bill_overrides=dict(EMERGENCY_ROOM_CHARGE),
    )


def _term_with_pending_severe_report():
    """A 404-life EXCESS_ONLY term with one SEVERE report still awaiting the
    official's verification decision, so the term carries no claim yet."""
    bundle = setup_sanctioned_activity(policy_overrides=dict(EXCESS_ONLY_TERM))
    set_clock(FILING_CLOCK)
    bundle["injury_report"] = file_injury_report(
        bundle["enrollment"]["id"],
        bundle["activity"]["id"],
        bundle["league"]["id"],
        **SEVERE_KNEE_REPORT,
    )
    return bundle


def _open_and_price_the_claim(bundle):
    """Verify the pending report, discover the claim it opens and reprice one
    imaging charge against it, which advances the claim to UNDER_ADJUDICATION."""
    verify_injury_report(bundle["injury_report"]["id"], VERIFYING_OFFICIAL_USER_ID)
    bundle["injury_report"] = read_injury_report(bundle["injury_report"]["id"])
    bundle["claim"] = discover_claim(bundle["injury_report"]["id"])
    bill = record_provider_bill(bundle["claim"]["id"], **IMAGING_CHARGE)
    bundle["provider_bill"] = reprice_bill(bill["id"])
    bundle["claim"] = read_claim(bundle["claim"]["id"])
    return bundle


def test_issuing_the_full_payable_benefit_moves_the_claim_to_paid_and_swaps_reserve_for_paid_loss(api):
    """PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.6: "On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "The **catastrophic-eligible amount** is `benefit_before_limit_cents` less the policy's `cat_attachment_point_cents`, floored at zero."
    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "Approval stamps `adjudicated_at` and `adjudicated_by_user_id` and **freezes** five determination figures — `deductible_applied_cents`, `benefit_before_limit_cents`, `base_layer_benefit_cents`, `cat_layer_benefit_cents` and `benefit_payable_cents` — which are never recomputed again on that claim."
    PRD §3.8: "An issued payment takes `status` `ISSUED`, stamps `issued_at` with the logical clock and `issued_by_user_id` with the examiner's `X-User-ID`, and leaves `void_reason` and `voided_at` null."
    PRD §3.8: "The claim's `paid_base_cents` (the sum of `ISSUED` `BASE`-layer amounts on the claim), `paid_cat_cents` (the same for the `CATASTROPHIC` layer) and `paid_to_date_cents` (their sum) are recomputed, and once `paid_to_date_cents` has reached or passed `benefit_payable_cents` the claim moves `APPROVED → PAID`, taking it out of the open set."
    PRD §3.8: "And in the same request the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, both loss ratios, `open_claim_count`, `experience_tier` and `coverage_posture` are recomputed."

    Design: Difficulty/compensating_invariant/benefit_payment_void_restores_paid_loss_and_reserve_money_invariant
    """
    bundle = _approved_full_excess_claim()
    policy_id = bundle["policy"]["id"]
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]

    approved_claim = read_claim(claim_id)
    assert_claim(approved_claim)
    assert approved_claim["adjudication_status"] == "APPROVED"
    assert approved_claim["benefit_payable_cents"] == BENEFIT_PAYABLE_CENTS
    assert approved_claim["base_layer_benefit_cents"] == BENEFIT_PAYABLE_CENTS
    assert approved_claim["reserve_amount_cents"] == SEVERE_RESERVE_CENTS
    assert approved_claim["paid_base_cents"] == 0
    assert approved_claim["paid_cat_cents"] == 0
    assert approved_claim["paid_to_date_cents"] == 0

    before = read_policy(policy_id)
    assert_league_policy(before)
    assert before["annual_premium_cents"] == ANNUAL_PREMIUM_CENTS
    assert _loss_aggregates(before) == ONE_OPEN_SEVERE_CLAIM
    assert_loss_position_invariants(before)
    assert_open_claim_cardinality(before, _claims_for_policy(api, policy_id))

    payment = validate_success(
        api.create_benefit_payment(
            create_benefit_payment_payload(
                claim_id,
                bill_id,
                BENEFIT_PAYABLE_CENTS,
                layer="BASE",
                payee_type="PROVIDER",
            ),
            CLAIMS_EXAMINER,
        ),
        201,
    )
    assert_benefit_payment(payment)
    assert payment["status"] == "ISSUED"
    assert payment["amount_cents"] == BENEFIT_PAYABLE_CENTS
    assert payment["layer"] == "BASE"
    assert payment["void_reason"] is None
    assert payment["voided_at"] is None
    assert canonical_iso(payment["issued_at"]) == canonical_iso(FILING_CLOCK)

    paid_claim = read_claim(claim_id)
    assert paid_claim["adjudication_status"] == "PAID"
    assert paid_claim["paid_base_cents"] == BENEFIT_PAYABLE_CENTS
    assert paid_claim["paid_cat_cents"] == 0
    assert paid_claim["paid_to_date_cents"] == BENEFIT_PAYABLE_CENTS
    assert paid_claim["benefit_payable_cents"] == BENEFIT_PAYABLE_CENTS

    after = read_policy(policy_id)
    assert after["annual_premium_cents"] == ANNUAL_PREMIUM_CENTS
    assert _loss_aggregates(after) == ONE_PAID_SEVERE_CLAIM
    assert_loss_position_invariants(after)
    assert_paid_loss_matches_issued_payments(after, payments_for_claim(claim_id))
    assert_open_claim_cardinality(after, _claims_for_policy(api, policy_id))


def test_voiding_the_benefit_payment_restores_every_loss_aggregate_and_reopens_the_paid_claim(api):
    """PRD §3.8: "This is the compensating action for issuance and its governing requirement is that it must leave the policy's `paid_loss_cents` exactly where it stood before the payment."
    PRD §3.8: "The void stamps `voided_at` with the logical clock and stores the reason, moving the payment `ISSUED → VOIDED`."
    PRD §3.8: "Because of that alone, the claim's `paid_base_cents`, `paid_cat_cents` and `paid_to_date_cents` are recomputed, and if the claim was `PAID` and its `paid_to_date_cents` now falls below `benefit_payable_cents`, the claim moves `PAID → APPROVED`."
    PRD §3.8: "Because of the reopen alone, the claim re-joins the open set and the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `experience_tier` and `coverage_posture` are all recomputed."
    PRD §3.8: "Approval stamps `adjudicated_at` and `adjudicated_by_user_id` and **freezes** five determination figures — `deductible_applied_cents`, `benefit_before_limit_cents`, `base_layer_benefit_cents`, `cat_layer_benefit_cents` and `benefit_payable_cents` — which are never recomputed again on that claim."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.6: "On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "The **catastrophic-eligible amount** is `benefit_before_limit_cents` less the policy's `cat_attachment_point_cents`, floored at zero."
    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`VOIDED` payments contribute nothing, which is exactly what makes a void restore the prior figure."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."

    Design: Difficulty/compensating_invariant/benefit_payment_void_restores_paid_loss_and_reserve_money_invariant
    """
    bundle = _approved_full_excess_claim()
    policy_id = bundle["policy"]["id"]
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]

    checkpoint_before = _loss_aggregates(read_policy(policy_id))
    assert checkpoint_before == ONE_OPEN_SEVERE_CLAIM

    payment = validate_success(
        api.create_benefit_payment(
            create_benefit_payment_payload(
                claim_id, bill_id, BENEFIT_PAYABLE_CENTS, layer="BASE"
            ),
            CLAIMS_EXAMINER,
        ),
        201,
    )
    assert read_claim(claim_id)["adjudication_status"] == "PAID"
    assert _loss_aggregates(read_policy(policy_id)) == ONE_PAID_SEVERE_CLAIM

    voided = validate_success(
        api.void_benefit_payment(
            payment["id"],
            {
                "void_reason": "payment issued against the wrong remittance batch"
                " and was recalled by the bank"
            },
            CLAIMS_EXAMINER,
        )
    )
    assert voided["status"] == "VOIDED"

    reopened_claim = read_claim(claim_id)
    assert reopened_claim["adjudication_status"] == "APPROVED"
    assert reopened_claim["paid_base_cents"] == 0
    assert reopened_claim["paid_cat_cents"] == 0
    assert reopened_claim["paid_to_date_cents"] == 0
    assert reopened_claim["benefit_payable_cents"] == BENEFIT_PAYABLE_CENTS
    assert reopened_claim["base_layer_benefit_cents"] == BENEFIT_PAYABLE_CENTS
    assert reopened_claim["cat_layer_benefit_cents"] == 0
    assert reopened_claim["reserve_amount_cents"] == SEVERE_RESERVE_CENTS

    restored = read_policy(policy_id)
    assert restored["annual_premium_cents"] == ANNUAL_PREMIUM_CENTS
    assert _loss_aggregates(restored) == checkpoint_before
    assert _loss_aggregates(restored) == ONE_OPEN_SEVERE_CLAIM
    assert_loss_position_invariants(restored)
    assert_paid_loss_matches_issued_payments(restored, payments_for_claim(claim_id))
    assert_open_claim_cardinality(restored, _claims_for_policy(api, policy_id))


def test_voided_benefit_payment_survives_as_a_voided_row_carrying_its_reason(api):
    """PRD §3.8: "A payment issued in error is voided with a `void_reason`, which requires the payment to be `ISSUED` (otherwise `ERR_INVALID_PAYMENT_STATE`)."
    PRD §3.8: "The void stamps `voided_at` with the logical clock and stores the reason, moving the payment `ISSUED → VOIDED`."
    PRD §3.8: "An issued payment takes `status` `ISSUED`, stamps `issued_at` with the logical clock and `issued_by_user_id` with the examiner's `X-User-ID`, and leaves `void_reason` and `voided_at` null."
    PRD §3.9: "`VOIDED` payments contribute nothing, which is exactly what makes a void restore the prior figure."
    PRD §3.8: "Approval also moves every bill of the claim still in `REPRICED` to `ADJUDICATED`."
    PRD §3.8: "Because of the reopen alone, the claim re-joins the open set and the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `experience_tier` and `coverage_posture` are all recomputed."

    Design: Difficulty/compensating_invariant/benefit_payment_void_restores_paid_loss_and_reserve_money_invariant
    """
    bundle = _approved_full_excess_claim()
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]
    assert read_provider_bill(bill_id)["status"] == "ADJUDICATED"

    payment = validate_success(
        api.create_benefit_payment(
            create_benefit_payment_payload(
                claim_id, bill_id, BENEFIT_PAYABLE_CENTS, layer="BASE"
            ),
            CLAIMS_EXAMINER,
        ),
        201,
    )
    payment_id = payment["id"]

    void_reason = "the remittance batch was recalled by the bank before settlement"
    voided = validate_success(
        api.void_benefit_payment(payment_id, {"void_reason": void_reason}, CLAIMS_EXAMINER)
    )
    assert_benefit_payment(voided)
    assert voided["id"] == payment_id
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == void_reason
    assert canonical_iso(voided["voided_at"]) == canonical_iso(FILING_CLOCK)
    assert voided["amount_cents"] == BENEFIT_PAYABLE_CENTS
    assert voided["layer"] == "BASE"

    # The compensated row is marked, never removed: it is still addressable and
    # still listed under its claim.
    reread = validate_success(api.get_benefit_payment(payment_id, CLAIMS_EXAMINER))
    assert reread["id"] == payment_id
    assert reread["status"] == "VOIDED"
    assert reread["void_reason"] == void_reason
    assert reread["amount_cents"] == BENEFIT_PAYABLE_CENTS

    listed = payments_for_claim(claim_id)
    assert [row["id"] for row in listed] == [payment_id]
    assert listed[0]["status"] == "VOIDED"

    # Voiding the cash does not unwind the charge it satisfied.
    settled_bill = read_provider_bill(bill_id)
    assert_provider_bill(settled_bill)
    assert settled_bill["status"] == "ADJUDICATED"


def test_verifying_the_severe_report_raises_the_open_claim_count_and_strikes_its_case_reserve(api):
    """PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.5: "Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed."
    PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."

    Design: Difficulty/compensating_invariant/claim_withdrawal_restores_open_claim_cardinality_and_voids_its_bills
    """
    bundle = _term_with_pending_severe_report()
    policy_id = bundle["policy"]["id"]

    before = read_policy(policy_id)
    assert_league_policy(before)
    assert before["annual_premium_cents"] == ANNUAL_PREMIUM_CENTS
    assert _loss_aggregates(before) == NO_CLAIMS_AT_ALL
    assert_loss_position_invariants(before)
    assert _claims_for_policy(api, policy_id) == []

    bundle = _open_and_price_the_claim(bundle)
    assert bundle["injury_report"]["status"] == "VERIFIED"

    claim = bundle["claim"]
    assert_claim(claim)
    assert claim["adjudication_status"] == "UNDER_ADJUDICATION"
    assert claim["reserve_amount_cents"] == SEVERE_RESERVE_CENTS
    assert bundle["provider_bill"]["status"] == "REPRICED"

    after = read_policy(policy_id)
    assert after["annual_premium_cents"] == ANNUAL_PREMIUM_CENTS
    assert _loss_aggregates(after) == ONE_OPEN_SEVERE_CLAIM
    assert_loss_position_invariants(after)
    assert_open_claim_cardinality(after, _claims_for_policy(api, policy_id))


def test_withdrawing_the_claim_restores_the_open_claim_count_and_reserve_to_their_pre_claim_values(api):
    """PRD §3.8: "From `PENDING_COORDINATION` the claim moves to `WITHDRAWN`, the reason is stored, and the claim leaves the open set so the policy's `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `coverage_posture` and `experience_tier` are recomputed."
    PRD §3.8: "From `UNDER_ADJUDICATION` the same happens, and in addition every bill of the claim in `SUBMITTED` or `REPRICED` moves to `VOIDED` with `void_reason` set to `CLAIM_WITHDRAWN`."
    PRD §3.9: "Everything the program knows about how a policy term is performing is recomputed at the end of every write that changes one of its claims, changes a benefit payment beneath one of those claims, or changes the policy's own `annual_premium_cents`."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."
    PRD §3.9: "Closing a claim by any route therefore releases its whole case reserve at once."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."

    Design: Difficulty/compensating_invariant/claim_withdrawal_restores_open_claim_cardinality_and_voids_its_bills
    """
    bundle = _term_with_pending_severe_report()
    policy_id = bundle["policy"]["id"]
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    checkpoint_before = _loss_aggregates(read_policy(policy_id))
    assert checkpoint_before == NO_CLAIMS_AT_ALL

    bundle = _open_and_price_the_claim(bundle)
    claim_id = bundle["claim"]["id"]
    assert _loss_aggregates(read_policy(policy_id)) == ONE_OPEN_SEVERE_CLAIM

    withdrawn = validate_success(
        api.withdraw_claim(
            claim_id,
            {
                "withdrawal_reason": "the family elected to pursue the claim solely"
                " through their own carrier"
            },
            league_headers,
        )
    )
    assert withdrawn["adjudication_status"] == "WITHDRAWN"

    restored = read_policy(policy_id)
    assert restored["annual_premium_cents"] == ANNUAL_PREMIUM_CENTS
    assert _loss_aggregates(restored) == checkpoint_before
    assert _loss_aggregates(restored) == NO_CLAIMS_AT_ALL
    assert_loss_position_invariants(restored)
    assert_open_claim_cardinality(restored, _claims_for_policy(api, policy_id))


def test_withdrawn_claim_keeps_its_row_and_voids_its_repriced_bill_while_the_report_stays_verified(api):
    """PRD §3.8: "A league that no longer wishes to pursue a claim withdraws it, supplying a `withdrawal_reason`."
    PRD §3.8: "From `PENDING_COORDINATION` the claim moves to `WITHDRAWN`, the reason is stored, and the claim leaves the open set so the policy's `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `coverage_posture` and `experience_tier` are recomputed."
    PRD §3.8: "From `UNDER_ADJUDICATION` the same happens, and in addition every bill of the claim in `SUBMITTED` or `REPRICED` moves to `VOIDED` with `void_reason` set to `CLAIM_WITHDRAWN`."
    PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."

    Design: Difficulty/compensating_invariant/claim_withdrawal_restores_open_claim_cardinality_and_voids_its_bills
    """
    bundle = _term_with_pending_severe_report()
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    bundle = _open_and_price_the_claim(bundle)
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]
    report_id = bundle["injury_report"]["id"]
    assert bundle["provider_bill"]["status"] == "REPRICED"

    withdrawn = validate_success(
        api.withdraw_claim(
            claim_id,
            {
                "withdrawal_reason": "the league will not pursue this claim any"
                " further this season"
            },
            league_headers,
        )
    )
    assert_claim(withdrawn)
    assert withdrawn["id"] == claim_id
    assert withdrawn["adjudication_status"] == "WITHDRAWN"

    # The compensated claim is marked, never removed: it is still addressable and
    # still discoverable through the filtered claim list.
    reread_claim = read_claim(claim_id)
    assert reread_claim["id"] == claim_id
    assert reread_claim["adjudication_status"] == "WITHDRAWN"
    assert [row["id"] for row in _claims_for_policy(api, bundle["policy"]["id"])] == [
        claim_id
    ]

    swept_bill = read_provider_bill(bill_id)
    assert_provider_bill(swept_bill)
    assert swept_bill["status"] == "VOIDED"
    assert swept_bill["void_reason"] == "CLAIM_WITHDRAWN"
    assert [row["id"] for row in bills_for_claim(claim_id)] == [bill_id]

    # The compensation is scoped to the claim and its charges: the independent
    # verification that opened the claim is not rolled back.
    assert read_injury_report(report_id)["status"] == "VERIFIED"

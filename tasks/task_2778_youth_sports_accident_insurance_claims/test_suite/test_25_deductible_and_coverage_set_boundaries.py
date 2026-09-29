"""Boundary behaviour of the per-claim deductible and of the other-coverage set.

Two boundaries are probed here. The first is the money equality inside the
deductible leg of the benefit determination: an allowed-amount total exactly
equal to the deductible pays nothing, while one cent more pays exactly one cent
and flips the claim's terminal state. The second is a set-cardinality boundary:
the other-coverage-on-file set holding exactly one qualifying family health plan
blocks the no-other-coverage attestation, and taking that set to zero members by
attesting the single plan unblocks the identical call.

Every test builds its own world from an empty database through the program's own
endpoints, threading the real League id into every league-administrator call and
the real Participant id into every guardian-portal call.
"""
from test_helpers import (
    ApiErrorId,
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    add_family_health_plan,
    add_participant,
    discover_claim,
    enroll_participant,
    file_injury_report,
    make_claims_examiner_headers,
    read_claim,
    read_policy,
    read_provider_bill,
    record_provider_bill,
    reprice_bill,
    request_eob,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_active_policy,
    setup_verified_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_injury_report,
)

CLAIMS_EXAMINER = make_claims_examiner_headers()

# The per-claim deductible carried by the BASEBALL_U12 coverage architecture.
DEDUCTIBLE_CENTS = 25000

# One physician-office charge, priced twice: once against a fee schedule exactly
# equal to the deductible and once against one a single cent above it.
PHYSICIAN_OFFICE_CHARGE = {
    "provider_npi": "1477203366",
    "provider_name": "Cedar Park Sports Medicine",
    "network_status": "IN_NETWORK",
    "service_category": "PHYSICIAN_OFFICE",
    "service_date": "2026-07-11",
    "billed_charge_cents": 60000,
}


def _build_deductible_boundary_world():
    """Two MINOR-severity claims on one active term, carrying identical
    in-network physician-office charges that differ only in the fee schedule:
    exactly the deductible on the first, one cent more on the second.

    Both claims have an outstanding explanation-of-benefits request and the clock
    is then moved forty-six days past it, so each settles on an excess-of-other
    footing with no other-insurance payment and the face deductible applying.
    """
    bundle = setup_active_policy(
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Cedar Park Little League",
            "league_code": "CPL-030",
            "state_code": "TX",
            "governing_body_code": "USYSA",
            "contact_email": "admin@cpl.example",
        },
        policy_overrides={
            "term_effective_date": "2026-03-01",
            "term_expiration_date": "2027-03-01",
            "enrolled_participant_count": 404,
            "coverage_basis_election": "EXCESS_ONLY",
            "cat_layer_elected": True,
        },
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]

    first_athlete = add_participant(
        league_id,
        first_name="Mira",
        last_name="Osei",
        date_of_birth="2014-02-11",
        guardian_email="g12@cpl.example",
    )
    second_athlete = add_participant(
        league_id,
        first_name="Noah",
        last_name="Feldman",
        date_of_birth="2014-06-23",
        guardian_email="g13@cpl.example",
    )
    first_enrollment = enroll_participant(
        first_athlete["id"], policy_id, league_id, enrolled_on_date="2026-03-05"
    )
    second_enrollment = enroll_participant(
        second_athlete["id"], policy_id, league_id, enrolled_on_date="2026-03-05"
    )

    for athlete, policy_number in (
        (first_athlete, "LSH-40011"),
        (second_athlete, "LSH-40012"),
    ):
        add_family_health_plan(
            athlete["id"],
            carrier_name="Lone Star Health",
            policy_number=policy_number,
            plan_type="HDHP",
            individual_deductible_cents=400000,
            coinsurance_bps=3000,
            effective_date="2026-01-01",
        )

    activity = schedule_activity(
        policy_id,
        league_id,
        activity_type="GAME",
        venue_name="Cedar Park Field 1",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )
    sanction_activity(activity["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")

    at_boundary_report = file_injury_report(
        first_enrollment["id"],
        activity["id"],
        league_id,
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="HAND_WRIST",
        injury_description="jammed thumb sliding into third base",
        severity_tier="MINOR",
    )
    verify_injury_report(at_boundary_report["id"], VERIFYING_OFFICIAL_USER_ID)
    at_boundary_claim = discover_claim(at_boundary_report["id"])

    past_boundary_report = file_injury_report(
        second_enrollment["id"],
        activity["id"],
        league_id,
        injury_datetime="2026-07-11T19:05:00Z",
        body_part="HAND_WRIST",
        injury_description="jammed thumb catching a line drive",
        severity_tier="MINOR",
    )
    verify_injury_report(past_boundary_report["id"], VERIFYING_OFFICIAL_USER_ID)
    past_boundary_claim = discover_claim(past_boundary_report["id"])

    at_boundary_bill = record_provider_bill(
        at_boundary_claim["id"],
        fee_schedule_amount_cents=DEDUCTIBLE_CENTS,
        **PHYSICIAN_OFFICE_CHARGE,
    )
    past_boundary_bill = record_provider_bill(
        past_boundary_claim["id"],
        fee_schedule_amount_cents=DEDUCTIBLE_CENTS + 1,
        **PHYSICIAN_OFFICE_CHARGE,
    )
    reprice_bill(at_boundary_bill["id"])
    reprice_bill(past_boundary_bill["id"])

    request_eob(
        at_boundary_claim["id"],
        note="explanation of benefits requested from Lone Star Health",
    )
    request_eob(
        past_boundary_claim["id"],
        note="explanation of benefits requested from Lone Star Health",
    )

    # Forty-six whole days after the request, so the waiver sweep settles both.
    set_clock("2026-08-27T00:00:00Z")

    return {
        "policy_id": policy_id,
        "at_boundary_claim_id": at_boundary_claim["id"],
        "at_boundary_bill_id": at_boundary_bill["id"],
        "past_boundary_claim_id": past_boundary_claim["id"],
        "past_boundary_bill_id": past_boundary_bill["id"],
    }


def test_claim_whose_allowed_total_exactly_equals_the_deductible_denies_for_no_benefit_payable(api):
    """PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`balance_billed_cents` is the billed charge less the allowed amount, floored at zero."
    PRD §3.7: "For an in-network provider it is **always exactly zero** — a participating provider may bill the family nothing above the allowed amount."
    PRD §3.6: "A day count of exactly forty-five leaves the claim in `EOB_REQUESTED`; the forty-sixth day waives it."
    PRD §3.6: "A waived claim takes `coordination_basis` `EXCESS_OF_OTHER` with `other_insurance_paid_cents` treated as zero, and no explanation-of-benefits record may be filed against it afterwards."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`."
    PRD §3.7: "If either condition fails, `cat_layer_benefit_cents` is exactly zero."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "Adjudication reaches `UNDER_ADJUDICATION → DENIED` when exactly one of two conditions holds, and the order in which they are tested is fixed: the enrollment's `status` being `WITHDRAWN` is tested **first** and sets `denial_reason` to `ENROLLMENT_WITHDRAWN`; only if the enrollment is still enrolled is `benefit_payable_cents` of zero tested, setting `denial_reason` to `NO_BENEFIT_PAYABLE`."
    PRD §3.7: "When the parent claim is denied, every bill still in `REPRICED` moves `REPRICED → DENIED` and nothing further happens to it."

    Design: Difficulty/boundary_precision_check/deductible_exactly_equals_allowed_amount_pays_zero_vs_one_cent_more
    """
    world = _build_deductible_boundary_world()

    bill = read_provider_bill(world["at_boundary_bill_id"])
    assert bill["negotiated_amount_cents"] == 25000
    assert bill["scheduled_cap_cents"] == 50000
    assert bill["allowed_amount_cents"] == 25000
    assert bill["balance_billed_cents"] == 35000
    assert bill["family_responsibility_cents"] == 0

    claim = read_claim(world["at_boundary_claim_id"])
    assert claim["coordination_status"] == "EOB_WAIVED"
    assert claim["coordination_basis"] == "EXCESS_OF_OTHER"
    assert claim["other_insurance_paid_cents"] == 0

    adjudicated = validate_success(
        api.adjudicate_claim(
            world["at_boundary_claim_id"],
            {"examiner_note": "allowed amount equals the deductible exactly"},
            CLAIMS_EXAMINER,
        )
    )
    assert adjudicated["allowed_amount_total_cents"] == 25000
    assert adjudicated["deductible_applied_cents"] == 25000
    assert adjudicated["benefit_before_limit_cents"] == 0
    assert adjudicated["base_layer_benefit_cents"] == 0
    assert adjudicated["cat_layer_benefit_cents"] == 0
    assert adjudicated["benefit_payable_cents"] == 0
    assert adjudicated["adjudication_status"] == "DENIED"
    assert adjudicated["denial_reason"] == "NO_BENEFIT_PAYABLE"

    assert read_provider_bill(world["at_boundary_bill_id"])["status"] == "DENIED"


def test_claim_whose_allowed_total_exceeds_the_deductible_by_one_cent_approves_a_one_cent_benefit(api):
    """PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`balance_billed_cents` is the billed charge less the allowed amount, floored at zero."
    PRD §3.6: "A day count of exactly forty-five leaves the claim in `EOB_REQUESTED`; the forty-sixth day waives it."
    PRD §3.6: "A waived claim takes `coordination_basis` `EXCESS_OF_OTHER` with `other_insurance_paid_cents` treated as zero, and no explanation-of-benefits record may be filed against it afterwards."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "It reaches `UNDER_ADJUDICATION → APPROVED` when the athlete's enrollment `status` is `ENROLLED` and `benefit_payable_cents` is at least one cent, and when the determination does not reach into the catastrophic layer without certification: where the policy's `cat_layer_elected` is true and `benefit_before_limit_cents` exceeds the policy's `cat_attachment_point_cents`, the claim's `cat_certification_status` must be `CERTIFIED`, and otherwise the adjudication is refused with `ERR_CAT_CERTIFICATION_REQUIRED` rather than quietly paying the base layer alone."
    PRD §3.8: "Approval also moves every bill of the claim still in `REPRICED` to `ADJUDICATED`."

    Design: Difficulty/boundary_precision_check/deductible_exactly_equals_allowed_amount_pays_zero_vs_one_cent_more
    """
    world = _build_deductible_boundary_world()

    bill = read_provider_bill(world["past_boundary_bill_id"])
    assert bill["negotiated_amount_cents"] == 25001
    assert bill["scheduled_cap_cents"] == 50000
    assert bill["allowed_amount_cents"] == 25001
    assert bill["balance_billed_cents"] == 34999

    claim = read_claim(world["past_boundary_claim_id"])
    assert claim["coordination_status"] == "EOB_WAIVED"
    assert claim["coordination_basis"] == "EXCESS_OF_OTHER"
    assert claim["other_insurance_paid_cents"] == 0

    adjudicated = validate_success(
        api.adjudicate_claim(
            world["past_boundary_claim_id"],
            {"examiner_note": "allowed amount exceeds the deductible by one cent"},
            CLAIMS_EXAMINER,
        )
    )
    assert adjudicated["allowed_amount_total_cents"] == 25001
    assert adjudicated["deductible_applied_cents"] == 25000
    assert adjudicated["benefit_before_limit_cents"] == 1
    assert adjudicated["base_layer_benefit_cents"] == 1
    assert adjudicated["benefit_payable_cents"] == 1
    assert adjudicated["adjudication_status"] == "APPROVED"

    assert read_provider_bill(world["past_boundary_bill_id"])["status"] == "ADJUDICATED"


def test_denying_the_claim_at_the_deductible_boundary_releases_its_reserve_from_the_loss_position(api):
    """PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.8: "Adjudication reaches `UNDER_ADJUDICATION → DENIED` when exactly one of two conditions holds, and the order in which they are tested is fixed: the enrollment's `status` being `WITHDRAWN` is tested **first** and sets `denial_reason` to `ENROLLMENT_WITHDRAWN`; only if the enrollment is still enrolled is `benefit_payable_cents` of zero tested, setting `denial_reason` to `NO_BENEFIT_PAYABLE`."
    PRD §3.8: "Denial stamps `adjudicated_at`, `adjudicated_by_user_id` and `denial_reason`, moves every bill still in `REPRICED` to `DENIED`, and takes the claim out of the policy's open set — so the policy's `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `coverage_posture` and `experience_tier` are all recomputed, which is frequently what lifts a policy back out of `CLAIMS_REVIEW`."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "Closing a claim by any route therefore releases its whole case reserve at once."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."

    Design: Difficulty/boundary_precision_check/deductible_exactly_equals_allowed_amount_pays_zero_vs_one_cent_more
    """
    world = _build_deductible_boundary_world()

    denied = validate_success(
        api.adjudicate_claim(
            world["at_boundary_claim_id"],
            {"examiner_note": "allowed amount equals the deductible exactly"},
            CLAIMS_EXAMINER,
        )
    )
    assert denied["adjudication_status"] == "DENIED"
    assert denied["reserve_amount_cents"] == 50000

    approved = validate_success(
        api.adjudicate_claim(
            world["past_boundary_claim_id"],
            {"examiner_note": "allowed amount exceeds the deductible by one cent"},
            CLAIMS_EXAMINER,
        )
    )
    assert approved["adjudication_status"] == "APPROVED"
    assert approved["reserve_amount_cents"] == 50000

    policy = read_policy(world["policy_id"])
    assert policy["open_claim_count"] == 1
    assert policy["paid_loss_cents"] == 0
    assert policy["reserve_cents"] == 50000
    assert policy["incurred_loss_cents"] == 50000
    assert policy["incurred_loss_ratio_bps"] == 608
    assert policy["experience_tier"] == "PREFERRED"


def _build_single_plan_coordination_world():
    """One athlete on a full-excess-permitted term whose verified injury report has
    opened a claim, holding exactly one family health plan: active coverage that
    the claims desk has not yet spoken to the carrier about.
    """
    bundle = setup_verified_claim(
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Harbor Bay Baseball",
            "league_code": "HBB-031",
            "state_code": "WA",
            "governing_body_code": "USYSA",
            "contact_email": "admin@hbb.example",
        },
        policy_overrides={
            "term_effective_date": "2026-03-01",
            "term_expiration_date": "2027-03-01",
            "enrolled_participant_count": 404,
            "coverage_basis_election": "FULL_EXCESS_PERMITTED",
            "cat_layer_elected": True,
        },
        participant_overrides={
            "first_name": "Sena",
            "last_name": "Alwan",
            "date_of_birth": "2014-05-30",
            "guardian_email": "g14@hbb.example",
        },
        enrollment_overrides={"enrolled_on_date": "2026-03-05"},
        activity_overrides={
            "activity_type": "PRACTICE",
            "venue_name": "Harbor Bay Diamond",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID,
        filing_clock="2026-07-12T00:00:00Z",
        report_overrides={
            "injury_datetime": "2026-07-11T19:00:00Z",
            "body_part": "KNEE",
            "injury_description": "twisted knee fielding a grounder",
            "severity_tier": "MODERATE",
        },
        verifying_official_id=VERIFYING_OFFICIAL_USER_ID,
        official_attestation="head coach witnessed the play",
    )
    bundle["family_health_plan"] = add_family_health_plan(
        bundle["participant"]["id"],
        carrier_name="Cascade Family Health",
        policy_number="CFH-77120",
        plan_type="HMO",
        individual_deductible_cents=250000,
        coinsurance_bps=2500,
        effective_date="2026-01-01",
    )
    return bundle


def test_confirming_no_other_coverage_with_exactly_one_qualifying_plan_is_refused(api):
    """PRD §3.6: "The plan's `coverage_state` is derived from the logical clock rather than stored: it is `ACTIVE` when the `effective_date` is at or before the current logical clock **and** either the `termination_date` is absent or the clock is strictly before it; otherwise it is `TERMINATED`."
    PRD §3.6: "It begins `UNVERIFIED`, with `verified_at` and `verified_by_user_id` null."
    PRD §3.6: "Throughout the rest of this section, the phrase **other coverage on file** means precisely this: the set of family health plans belonging to the claim's athlete whose `coverage_state` is `ACTIVE` and whose `verification_status` is *not* `NO_COVERAGE_ATTESTED`."
    PRD §3.6: "A single such plan is enough to constitute other coverage."
    PRD §3.6: "The mirror-image move is the examiner confirming that no other coverage exists, supplied with an `attestation_note`, which drives `NOT_STARTED → NO_OTHER_COVERAGE_CONFIRMED`."
    PRD §3.6: "It carries the opposite membership test: the set of qualifying plans must be **empty**, and any single plan with an `ACTIVE` coverage state that has not been attested as no-coverage refuses the request with `ERR_OTHER_COVERAGE_ON_FILE`."
    PRD §3.6: "Coordination begins at `NOT_STARTED` and settles at one of three values — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — and both moves out of `NOT_STARTED` require the claim's `adjudication_status` to be `PENDING_COORDINATION` or `UNDER_ADJUDICATION`."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."

    Design: Difficulty/boundary_precision_check/other_coverage_on_file_empty_set_boundary_at_exactly_one_plan
    """
    bundle = _build_single_plan_coordination_world()
    participant_id = bundle["participant"]["id"]
    claim_id = bundle["claim"]["id"]

    plans, _meta = validate_paginated(
        api.list_family_health_plans(CLAIMS_EXAMINER, {"participant_id": participant_id})
    )
    assert len(plans) == 1
    assert plans[0]["coverage_state"] == "ACTIVE"
    assert plans[0]["verification_status"] == "UNVERIFIED"

    validate_error(
        api.confirm_no_other_coverage(
            claim_id,
            {"attestation_note": "guardian states there is no other coverage"},
            CLAIMS_EXAMINER,
        ),
        ApiErrorId.ERR_OTHER_COVERAGE_ON_FILE.value,
        409,
    )

    claim = read_claim(claim_id)
    assert claim["coordination_status"] == "NOT_STARTED"
    assert claim["coordination_basis"] is None


def test_attesting_the_only_plan_as_no_coverage_empties_the_set_and_admits_the_full_excess_footing(api):
    """PRD §3.6: "A `ClaimsExaminer` records the outcome by supplying a `decision` and a `note`, and the plan moves either `UNVERIFIED → VERIFIED` — the carrier confirmed the coverage — or `UNVERIFIED → NO_COVERAGE_ATTESTED`, meaning the carrier confirmed there is in fact no coverage here."
    PRD §3.6: "The two branches differ in exactly one further respect: a plan attested as having no coverage stops counting as other coverage on file, which is what unblocks the full-excess route below."
    PRD §3.6: "The plan's `coverage_state` is derived from the logical clock rather than stored: it is `ACTIVE` when the `effective_date` is at or before the current logical clock **and** either the `termination_date` is absent or the clock is strictly before it; otherwise it is `TERMINATED`."
    PRD §3.6: "Throughout the rest of this section, the phrase **other coverage on file** means precisely this: the set of family health plans belonging to the claim's athlete whose `coverage_state` is `ACTIVE` and whose `verification_status` is *not* `NO_COVERAGE_ATTESTED`."
    PRD §3.6: "A single such plan is enough to constitute other coverage."
    PRD §3.6: "The mirror-image move is the examiner confirming that no other coverage exists, supplied with an `attestation_note`, which drives `NOT_STARTED → NO_OTHER_COVERAGE_CONFIRMED`."
    PRD §3.6: "It carries the opposite membership test: the set of qualifying plans must be **empty**, and any single plan with an `ACTIVE` coverage state that has not been attested as no-coverage refuses the request with `ERR_OTHER_COVERAGE_ON_FILE`."
    PRD §3.6: "It carries one further requirement of its own: the governing policy's `coverage_basis_election` must be `FULL_EXCESS_PERMITTED`."
    PRD §3.6: "On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."
    PRD §3.6: "Every claim carries `coordination_status` as a second, independent state axis alongside its adjudication status, and the two evolve without reference to one another except at a single declared join described in §3.8."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."

    Design: Difficulty/boundary_precision_check/other_coverage_on_file_empty_set_boundary_at_exactly_one_plan
    """
    bundle = _build_single_plan_coordination_world()
    participant_id = bundle["participant"]["id"]
    claim_id = bundle["claim"]["id"]
    plan_id = bundle["family_health_plan"]["id"]

    attested = validate_success(
        api.verify_family_health_plan(
            plan_id,
            {
                "decision": "NO_COVERAGE_ATTESTED",
                "note": "guardian attests the listed plan lapsed before the season",
            },
            CLAIMS_EXAMINER,
        )
    )
    assert attested["verification_status"] == "NO_COVERAGE_ATTESTED"
    assert attested["coverage_state"] == "ACTIVE"

    confirmed = validate_success(
        api.confirm_no_other_coverage(
            claim_id,
            {"attestation_note": "guardian states there is no other coverage"},
            CLAIMS_EXAMINER,
        )
    )
    assert confirmed["coordination_status"] == "NO_OTHER_COVERAGE_CONFIRMED"
    assert confirmed["coordination_basis"] == "FULL_EXCESS"
    assert confirmed["adjudication_status"] == "PENDING_COORDINATION"

    # The qualifying set is empty, but the plan row itself was never deleted.
    plans, _meta = validate_paginated(
        api.list_family_health_plans(CLAIMS_EXAMINER, {"participant_id": participant_id})
    )
    assert len(plans) == 1
    assert plans[0]["id"] == plan_id
    assert plans[0]["coverage_state"] == "ACTIVE"
    assert plans[0]["verification_status"] == "NO_COVERAGE_ATTESTED"

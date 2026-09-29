"""Injury-report correction cycling and the claim's two independent state axes.

The injury report loops between pending verification and the correction desk under
a two-round budget and stays verifiable afterwards; a claim carries an adjudication
axis and a coordination axis that advance on separate writes and meet only at
adjudication.
"""
from test_helpers import (
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    ApiErrorId,
    add_family_health_plan,
    claims_for_report,
    create_coordination_record_payload,
    file_injury_report,
    make_claims_examiner_headers,
    make_league_admin_headers,
    make_league_official_headers,
    read_claim,
    read_injury_report,
    read_provider_bill,
    record_provider_bill,
    set_clock,
    setup_enrolled_athlete,
    setup_sanctioned_activity,
    setup_verified_claim,
    validate_error,
    validate_success,
    verify_family_plan,
)

FILING_CLOCK = "2026-07-12T00:00:00Z"


def _pending_minor_report(severity_tier="MINOR"):
    """A league on an ACTIVE term with one enrolled athlete, one sanctioned
    practice and one freshly filed report awaiting an official's decision."""
    bundle = setup_sanctioned_activity(
        activity_overrides={"activity_type": "PRACTICE", "venue_name": "Riverside Cage 1"},
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID,
    )
    set_clock(FILING_CLOCK)
    bundle["injury_report"] = file_injury_report(
        bundle["enrollment"]["id"],
        bundle["activity"]["id"],
        bundle["league"]["id"],
        body_part="TORSO",
        injury_description="bruised ribs",
        severity_tier=severity_tier,
    )
    return bundle


def _severe_claim_with_verified_family_plan():
    """A verified severe-injury claim whose athlete carries one active, carrier
    verified family health plan, plus one submitted in-network charge."""
    bundle = setup_enrolled_athlete()
    plan = add_family_health_plan(bundle["participant"]["id"])
    bundle["family_health_plan"] = verify_family_plan(plan["id"])
    bundle = setup_sanctioned_activity(bundle=bundle)
    bundle = setup_verified_claim(
        bundle=bundle, report_overrides={"severity_tier": "SEVERE"}
    )
    bundle["provider_bill"] = record_provider_bill(bundle["claim"]["id"])
    return bundle


def test_two_correction_rounds_carry_the_round_count_forward_without_resetting(api):
    """PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §3.5: "This moves the report `PENDING_VERIFICATION → RETURNED_FOR_CORRECTION`, increments `correction_round_count` by one, and stores the note as the most recent correction note on the report."
    PRD §3.5: "Resubmission moves the report `RETURNED_FOR_CORRECTION → PENDING_VERIFICATION` and deliberately does **not** reset `correction_round_count`, so the two-round budget is consumed across the whole life of the report rather than per round-trip."

    Design: Difficulty/non_linear_state_machine/injury_report_correction_loop_capped_at_two_rounds_then_verifiable
    """
    bundle = _pending_minor_report()
    report_id = bundle["injury_report"]["id"]
    official_headers = make_league_official_headers(VERIFYING_OFFICIAL_USER_ID)
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    assert bundle["injury_report"]["status"] == "PENDING_VERIFICATION"
    assert bundle["injury_report"]["correction_round_count"] == 0

    first_return = validate_success(
        api.return_injury_report_for_correction(
            report_id,
            {"correction_note": "body part and mechanism of injury inconsistent"},
            official_headers,
        )
    )
    assert first_return["status"] == "RETURNED_FOR_CORRECTION"
    assert first_return["correction_round_count"] == 1
    assert (
        first_return["correction_note"]
        == "body part and mechanism of injury inconsistent"
    )

    first_resubmit = validate_success(
        api.resubmit_injury_report(
            report_id,
            {
                "injury_description": "bruised ribs, left side, contact with catcher's mask",
                "severity_tier": "MINOR",
            },
            league_headers,
        )
    )
    assert first_resubmit["status"] == "PENDING_VERIFICATION"
    assert first_resubmit["correction_round_count"] == 1
    assert (
        first_resubmit["injury_description"]
        == "bruised ribs, left side, contact with catcher's mask"
    )

    second_return = validate_success(
        api.return_injury_report_for_correction(
            report_id,
            {"correction_note": "still missing which drill the athlete was performing"},
            official_headers,
        )
    )
    assert second_return["status"] == "RETURNED_FOR_CORRECTION"
    assert second_return["correction_round_count"] == 2
    assert (
        second_return["correction_note"]
        == "still missing which drill the athlete was performing"
    )

    second_resubmit = validate_success(
        api.resubmit_injury_report(
            report_id,
            {
                "injury_description": "bruised ribs, left side, contact during bunt-defence drill",
                "severity_tier": "MINOR",
            },
            league_headers,
        )
    )
    assert second_resubmit["status"] == "PENDING_VERIFICATION"
    assert second_resubmit["correction_round_count"] == 2

    persisted = read_injury_report(report_id)
    assert persisted["status"] == "PENDING_VERIFICATION"
    assert persisted["correction_round_count"] == 2


def test_third_return_for_correction_is_refused_once_the_two_round_budget_is_spent(api):
    """PRD §3.5: "The loop is bounded at **two rounds**: a return attempted when `correction_round_count` already equals two is refused with `ERR_CORRECTION_ROUNDS_EXHAUSTED`."
    PRD §3.5: "Resubmission moves the report `RETURNED_FOR_CORRECTION → PENDING_VERIFICATION` and deliberately does **not** reset `correction_round_count`, so the two-round budget is consumed across the whole life of the report rather than per round-trip."

    Design: Difficulty/non_linear_state_machine/injury_report_correction_loop_capped_at_two_rounds_then_verifiable
    """
    bundle = _pending_minor_report()
    report_id = bundle["injury_report"]["id"]
    official_headers = make_league_official_headers(VERIFYING_OFFICIAL_USER_ID)
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    for round_number in (1, 2):
        returned = validate_success(
            api.return_injury_report_for_correction(
                report_id,
                {"correction_note": f"correction request number {round_number}"},
                official_headers,
            )
        )
        assert returned["correction_round_count"] == round_number
        resubmitted = validate_success(
            api.resubmit_injury_report(
                report_id,
                {
                    "injury_description": f"bruised ribs, narrative revision {round_number}",
                    "severity_tier": "MINOR",
                },
                league_headers,
            )
        )
        assert resubmitted["correction_round_count"] == round_number

    validate_error(
        api.return_injury_report_for_correction(
            report_id,
            {"correction_note": "third bite at the apple"},
            official_headers,
        ),
        ApiErrorId.ERR_CORRECTION_ROUNDS_EXHAUSTED.value,
        409,
    )

    unchanged = read_injury_report(report_id)
    assert unchanged["status"] == "PENDING_VERIFICATION"
    assert unchanged["correction_round_count"] == 2


def test_report_with_exhausted_correction_budget_still_verifies_and_opens_one_claim(api):
    """PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."

    Design: Difficulty/non_linear_state_machine/injury_report_correction_loop_capped_at_two_rounds_then_verifiable
    """
    bundle = _pending_minor_report()
    report_id = bundle["injury_report"]["id"]
    official_headers = make_league_official_headers(VERIFYING_OFFICIAL_USER_ID)
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    for round_number in (1, 2):
        validate_success(
            api.return_injury_report_for_correction(
                report_id,
                {"correction_note": f"correction request number {round_number}"},
                official_headers,
            )
        )
        validate_success(
            api.resubmit_injury_report(
                report_id,
                {
                    "injury_description": f"bruised ribs, narrative revision {round_number}",
                    "severity_tier": "MINOR",
                },
                league_headers,
            )
        )

    verified = validate_success(
        api.record_verification_decision(
            report_id,
            {
                "decision": "VERIFY",
                "official_attestation": "drill roster and coach statement on file",
            },
            official_headers,
        )
    )
    assert verified["status"] == "VERIFIED"
    assert verified["correction_round_count"] == 2
    assert verified["verifying_official_id"] == VERIFYING_OFFICIAL_USER_ID
    assert verified["official_attestation"] == "drill roster and coach statement on file"

    claims = claims_for_report(report_id)
    assert len(claims) == 1
    claim = claims[0]
    assert claim["adjudication_status"] == "PENDING_COORDINATION"
    assert claim["coordination_status"] == "NOT_STARTED"
    assert claim["reserve_amount_cents"] == 50000


def test_adjudication_before_either_axis_moves_is_refused_as_invalid_claim_state(api):
    """PRD §3.8: "Four requirements are common to both outcomes: the claim's `adjudication_status` must be `UNDER_ADJUDICATION` (otherwise `ERR_INVALID_CLAIM_STATE`); its `coordination_status` must have reached a settled value — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — which is the **single declared join** between the two axes, and a claim still `NOT_STARTED`, or still `EOB_REQUESTED` with the forty-five-day waiver window not yet elapsed, is refused with `ERR_COORDINATION_INCOMPLETE`; the governing policy's `status` must be `ACTIVE` or `RUN_OFF`; and the policy's posture must not be `FROZEN`."
    PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."

    Design: Difficulty/non_linear_state_machine/claim_dual_axis_adjudication_and_coordination_advance_independently
    """
    bundle = _severe_claim_with_verified_family_plan()
    claim_id = bundle["claim"]["id"]
    examiner_headers = make_claims_examiner_headers()

    assert bundle["claim"]["adjudication_status"] == "PENDING_COORDINATION"
    assert bundle["claim"]["coordination_status"] == "NOT_STARTED"

    validate_error(
        api.adjudicate_claim(
            claim_id,
            {"examiner_note": "premature - coordination axis has not started"},
            examiner_headers,
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
        409,
    )

    unchanged = read_claim(claim_id)
    assert unchanged["adjudication_status"] == "PENDING_COORDINATION"
    assert unchanged["coordination_status"] == "NOT_STARTED"


def test_repricing_a_charge_advances_only_the_adjudication_axis(api):
    """PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."
    PRD §3.7: "That advance happens on the **first** successful reprice on any bill of the claim and is independent of where the coordination axis has got to."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."

    Design: Difficulty/non_linear_state_machine/claim_dual_axis_adjudication_and_coordination_advance_independently
    """
    bundle = _severe_claim_with_verified_family_plan()
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]
    examiner_headers = make_claims_examiner_headers()

    repriced = validate_success(
        api.reprice_provider_bill(bill_id, examiner_headers)
    )
    assert repriced["status"] == "REPRICED"
    assert repriced["allowed_amount_cents"] == 385000

    claim = read_claim(claim_id)
    assert claim["adjudication_status"] == "UNDER_ADJUDICATION"
    assert claim["coordination_status"] == "NOT_STARTED"


def test_requesting_the_explanation_of_benefits_advances_only_the_coordination_axis(api):
    """PRD §3.6: "Every claim carries `coordination_status` as a second, independent state axis alongside its adjudication status, and the two evolve without reference to one another except at a single declared join described in §3.8."
    PRD §3.6: "A `ClaimsExaminer` requesting the explanation of benefits, optionally with a `note`, drives `NOT_STARTED → EOB_REQUESTED` and stamps `eob_requested_at` with the logical clock."

    Design: Difficulty/non_linear_state_machine/claim_dual_axis_adjudication_and_coordination_advance_independently
    """
    bundle = _severe_claim_with_verified_family_plan()
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]
    examiner_headers = make_claims_examiner_headers()

    validate_success(api.reprice_provider_bill(bill_id, examiner_headers))

    requested = validate_success(
        api.request_eob(
            claim_id,
            {"note": "requesting explanation of benefits from the family carrier"},
            examiner_headers,
        )
    )
    assert requested["coordination_status"] == "EOB_REQUESTED"
    assert requested["adjudication_status"] == "UNDER_ADJUDICATION"

    claim = read_claim(claim_id)
    assert claim["coordination_status"] == "EOB_REQUESTED"
    assert claim["adjudication_status"] == "UNDER_ADJUDICATION"


def test_settled_coordination_lets_the_adjudication_axis_approve_the_claim(api):
    """PRD §3.6: "Filing the first record on a claim also drives the coordination axis `EOB_REQUESTED → EOB_RECEIVED`, after which `coordination_basis` reads `EXCESS_OF_OTHER`, and the claim's `other_insurance_paid_cents` and its whole benefit determination are recomputed."
    PRD §3.6: "At the claim level, `other_insurance_paid_cents` is the sum of `other_plan_paid_cents` across this claim's `ACTIVE` coordination records whose `provider_bill_id` names one of the claim's bills in `REPRICED` or `ADJUDICATED` status."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "Approval also moves every bill of the claim still in `REPRICED` to `ADJUDICATED`."

    Design: Difficulty/non_linear_state_machine/claim_dual_axis_adjudication_and_coordination_advance_independently
    """
    bundle = _severe_claim_with_verified_family_plan()
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]
    plan_id = bundle["family_health_plan"]["id"]
    examiner_headers = make_claims_examiner_headers()

    validate_success(api.reprice_provider_bill(bill_id, examiner_headers))
    validate_success(
        api.request_eob(
            claim_id,
            {"note": "requesting explanation of benefits from the family carrier"},
            examiner_headers,
        )
    )

    claim_version = read_claim(claim_id)["version"]
    validate_success(
        api.create_coordination_record(
            create_coordination_record_payload(
                claim_id,
                bill_id,
                plan_id,
                claim_version,
                other_plan_allowed_cents=385000,
                other_plan_paid_cents=200000,
                patient_responsibility_cents=185000,
            ),
            examiner_headers,
        ),
        201,
    )

    coordinated = read_claim(claim_id)
    assert coordinated["coordination_status"] == "EOB_RECEIVED"
    assert coordinated["adjudication_status"] == "UNDER_ADJUDICATION"
    assert coordinated["other_insurance_paid_cents"] == 200000

    approved = validate_success(
        api.adjudicate_claim(
            claim_id,
            {"examiner_note": "coordination settled, both axes ready"},
            examiner_headers,
        )
    )
    assert approved["adjudication_status"] == "APPROVED"
    assert approved["coordination_status"] == "EOB_RECEIVED"
    assert approved["allowed_amount_total_cents"] == 385000
    assert approved["deductible_applied_cents"] == 25000
    assert approved["benefit_before_limit_cents"] == 160000
    assert approved["base_layer_benefit_cents"] == 160000
    assert approved["benefit_payable_cents"] == 160000

    assert read_provider_bill(bill_id)["status"] == "ADJUDICATED"

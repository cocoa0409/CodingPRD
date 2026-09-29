"""Long propagation chains: the loss-driven freeze and lifetime exhaustion.

Two writes in this program disturb four or five entities at once. An official's
verification of an injury report walks from the report to a new claim, from the
claim to the term's loss aggregates, from those aggregates to the operating
posture and from a frozen posture out to the activities still waiting to be
sanctioned. A catastrophic benefit payment runs the other way: from the money row
to the claim's paid totals, from those totals to the athlete's lifetime
catastrophic usage and from an exhausted athlete back to the injury reports still
waiting for a decision. Each test below rebuilds its whole chain and then reads
the downstream rows through their own endpoints, because a transition response
never carries the cascade's downstream victims.
"""
from test_helpers import (
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    adjudicate_claim,
    certify_catastrophic,
    confirm_no_other_coverage,
    create_benefit_payment_payload,
    discover_claim,
    file_injury_report,
    issue_benefit_payment,
    make_claims_examiner_headers,
    make_league_official_headers,
    read_activity,
    read_claim,
    read_enrollment,
    read_injury_report,
    read_policy,
    record_provider_bill,
    reprice_bill,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_enrolled_athlete,
    validate_paginated,
    validate_success,
    verify_injury_report,
)

CHEER_ATTESTATION = "two coaches and the meet director witnessed the fall"


# ---------------------------------------------------------------------------
# Chain A - a high-hazard cheer term whose aggregate limit (500000 cents) is
# smaller than the reserve a catastrophic injury strikes, so opening one claim
# is enough to freeze the term.
# ---------------------------------------------------------------------------
def _build_cheer_term_with_one_pending_catastrophic_report():
    bundle = setup_enrolled_athlete(
        classification="cheer",
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Summit Allstar Cheer",
            "league_code": "SAC-001",
            "state_code": "OH",
            "governing_body_code": "USASF",
            "contact_email": "admin@sac.example",
        },
        policy_overrides={
            "term_effective_date": "2026-03-01",
            "term_expiration_date": "2027-03-01",
            "enrolled_participant_count": 30,
            "coverage_basis_election": "EXCESS_ONLY",
            "cat_layer_elected": True,
        },
        participant_overrides={
            "first_name": "Gia",
            "last_name": "Delacroix",
            "date_of_birth": "2014-11-22",
            "guardian_email": "g7@sac.example",
        },
        enrollment_overrides={"enrolled_on_date": "2026-03-05"},
    )
    sanctioned_activity = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="PRACTICE",
        venue_name="Summit Gym A",
        starts_at="2026-03-10T18:00:00Z",
        ends_at="2026-03-10T20:00:00Z",
    )
    sanction_activity(sanctioned_activity["id"], SANCTIONING_OFFICIAL_USER_ID)
    pending_activity = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="GAME",
        venue_name="Buckeye Regional Arena",
        starts_at="2026-04-10T18:00:00Z",
        ends_at="2026-04-10T20:00:00Z",
    )
    set_clock("2026-03-11T00:00:00Z")
    report = file_injury_report(
        bundle["enrollment"]["id"],
        sanctioned_activity["id"],
        bundle["league"]["id"],
        injury_datetime="2026-03-10T19:00:00Z",
        body_part="HEAD_NECK",
        injury_description="fell from top of pyramid, cervical injury with neurological deficit",
        severity_tier="CATASTROPHIC",
    )
    bundle["sanctioned_activity"] = sanctioned_activity
    bundle["pending_activity"] = pending_activity
    bundle["injury_report"] = report
    return bundle


def test_verification_of_a_catastrophic_report_opens_exactly_one_claim_reserved_at_the_policy_exposure_cap(api):
    """PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."

    Design: Difficulty/transitive_cascade/cascade_a_report_verification_freezes_policy_and_rejects_pending_activity
    """
    bundle = _build_cheer_term_with_one_pending_catastrophic_report()
    report_id = bundle["injury_report"]["id"]

    decided = validate_success(
        api.record_verification_decision(
            report_id,
            {"decision": "VERIFY", "official_attestation": CHEER_ATTESTATION},
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        )
    )

    assert decided["status"] == "VERIFIED"
    assert decided["verifying_official_id"] == VERIFYING_OFFICIAL_USER_ID
    assert decided["official_attestation"] == CHEER_ATTESTATION

    rows, _meta = validate_paginated(
        api.list_claims(
            make_claims_examiner_headers(), {"injury_report_id": report_id}
        )
    )
    assert len(rows) == 1
    claim = rows[0]
    assert claim["adjudication_status"] == "PENDING_COORDINATION"
    assert claim["coordination_status"] == "NOT_STARTED"
    # 7,500,000 standard catastrophic reserve capped by 300000 + 600000 exposure
    assert claim["reserve_amount_cents"] == 900000
    assert claim["league_policy_id"] == bundle["policy"]["id"]
    assert claim["enrollment_id"] == bundle["enrollment"]["id"]
    assert claim["injury_report_id"] == report_id


def test_new_claim_joining_the_open_set_rewrites_the_terms_reserve_and_incurred_loss(api):
    """PRD §3.5: "Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."

    Design: Difficulty/transitive_cascade/cascade_a_report_verification_freezes_policy_and_rejects_pending_activity
    """
    bundle = _build_cheer_term_with_one_pending_catastrophic_report()
    policy_id = bundle["policy"]["id"]

    before = read_policy(policy_id)
    assert before["reserve_cents"] == 0
    assert before["incurred_loss_cents"] == 0
    assert before["open_claim_count"] == 0

    validate_success(
        api.record_verification_decision(
            bundle["injury_report"]["id"],
            {"decision": "VERIFY", "official_attestation": CHEER_ATTESTATION},
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        )
    )

    after = read_policy(policy_id)
    assert after["reserve_cents"] == 900000
    assert after["paid_loss_cents"] == 0
    assert after["incurred_loss_cents"] == 900000
    assert after["open_claim_count"] == 1


def test_the_terms_incurred_loss_ratio_and_experience_tier_are_rebanded_off_the_new_reserve(api):
    """PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."

    Design: Difficulty/transitive_cascade/cascade_a_report_verification_freezes_policy_and_rejects_pending_activity
    """
    bundle = _build_cheer_term_with_one_pending_catastrophic_report()
    policy_id = bundle["policy"]["id"]
    assert read_policy(policy_id)["annual_premium_cents"] == 100681

    validate_success(
        api.record_verification_decision(
            bundle["injury_report"]["id"],
            {"decision": "VERIFY", "official_attestation": CHEER_ATTESTATION},
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        )
    )

    after = read_policy(policy_id)
    assert after["annual_premium_cents"] == 100681
    assert after["incurred_loss_ratio_bps"] == 89391
    assert after["experience_tier"] == "DECLINE"


def test_the_loss_driven_freeze_sweeps_the_terms_still_pending_activity_into_rejection(api):
    """PRD §3.5: "Caused by those recomputed figures alone, the policy's `coverage_posture` is re-derived and may move to `CLAIMS_REVIEW` or `FROZEN` — a third open claim is exactly what tips a policy into claims review."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "The test is inclusive: an incurred loss exactly equal to the aggregate limit freezes the term."
    PRD §3.5: "Caused by that posture change alone, if the posture landed on `FROZEN`, every activity of that policy still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` `POLICY_FROZEN`, which in turn rejects the injury reports hanging off those activities as described in §3.4."
    PRD §2.8: "Posture is what actually gates whether new exposure and new claim activity may be written; `status` records where the term is in its life, posture records whether the program is presently willing to let anything happen under it."

    Design: Difficulty/transitive_cascade/cascade_a_report_verification_freezes_policy_and_rejects_pending_activity
    """
    bundle = _build_cheer_term_with_one_pending_catastrophic_report()
    policy_id = bundle["policy"]["id"]

    assert read_policy(policy_id)["coverage_posture"] == "OPEN"
    assert read_activity(bundle["pending_activity"]["id"])["status"] == "PENDING_SANCTION"

    validate_success(
        api.record_verification_decision(
            bundle["injury_report"]["id"],
            {"decision": "VERIFY", "official_attestation": CHEER_ATTESTATION},
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        )
    )

    policy = read_policy(policy_id)
    # 900000 of incurred loss against a 500000 aggregate limit
    assert policy["coverage_posture"] == "FROZEN"
    assert policy["status"] == "ACTIVE"

    swept = read_activity(bundle["pending_activity"]["id"])
    assert swept["status"] == "REJECTED"
    assert swept["rejection_reason"] == "POLICY_FROZEN"

    # the sweep reaches only activities still in PENDING_SANCTION
    untouched = read_activity(bundle["sanctioned_activity"]["id"])
    assert untouched["status"] == "SANCTIONED"


# ---------------------------------------------------------------------------
# Chain B - a low-hazard swim term with a deliberately small catastrophic
# lifetime maximum (100000 cents), so one catastrophic-layer payment exhausts
# the athlete for life and reaches back to a second, undecided report.
# ---------------------------------------------------------------------------
def _build_swim_claim_approved_with_base_paid_and_second_report_pending():
    bundle = setup_enrolled_athlete(
        classification="swim",
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Lakeshore Swim Club",
            "league_code": "LSC-001",
            "state_code": "MI",
            "governing_body_code": "USAS",
            "contact_email": "admin@lsc.example",
        },
        policy_overrides={
            "term_effective_date": "2026-03-01",
            "term_expiration_date": "2027-03-01",
            "enrolled_participant_count": 40,
            "coverage_basis_election": "FULL_EXCESS_PERMITTED",
            "cat_layer_elected": True,
        },
        participant_overrides={
            "first_name": "Hana",
            "last_name": "Bergstrom",
            "date_of_birth": "2012-08-03",
            "guardian_email": "g8@lsc.example",
        },
        enrollment_overrides={"enrolled_on_date": "2026-03-05"},
    )
    first_activity = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="PRACTICE",
        venue_name="Lakeshore Natatorium",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )
    sanction_activity(first_activity["id"], SANCTIONING_OFFICIAL_USER_ID)
    second_activity = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="GAME",
        venue_name="Regional Invitational Pool",
        starts_at="2026-08-20T18:00:00Z",
        ends_at="2026-08-20T20:00:00Z",
    )
    sanction_activity(second_activity["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")
    first_report = file_injury_report(
        bundle["enrollment"]["id"],
        first_activity["id"],
        bundle["league"]["id"],
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="HEAD_NECK",
        injury_description="shallow-end dive, cervical fracture with cord involvement",
        severity_tier="CATASTROPHIC",
    )
    verify_injury_report(
        first_report["id"],
        VERIFYING_OFFICIAL_USER_ID,
        "meet referee and two lifeguards witnessed",
    )
    claim = discover_claim(first_report["id"])
    bill = record_provider_bill(
        claim["id"],
        provider_npi="1902845517",
        provider_name="Lakeshore Regional Neurosurgery",
        network_status="IN_NETWORK",
        service_category="SURGERY",
        service_date="2026-07-11",
        billed_charge_cents=700000,
        fee_schedule_amount_cents=660000,
    )
    bill = reprice_bill(bill["id"])
    confirm_no_other_coverage(claim["id"])
    certify_catastrophic(
        claim["id"],
        "permanent neurological deficit documented by treating neurosurgeon",
    )
    claim = adjudicate_claim(
        claim["id"],
        "covered PRACTICE activity, program primary, catastrophic layer certified",
    )
    issue_benefit_payment(claim["id"], bill["id"], 500000, layer="BASE")

    set_clock("2026-08-21T00:00:00Z")
    second_report = file_injury_report(
        bundle["enrollment"]["id"],
        second_activity["id"],
        bundle["league"]["id"],
        injury_datetime="2026-08-20T19:00:00Z",
        body_part="SHOULDER_ARM",
        injury_description="shoulder impingement after 200m butterfly heat",
        severity_tier="MINOR",
    )
    bundle["claim"] = claim
    bundle["provider_bill"] = bill
    bundle["second_report"] = second_report
    return bundle


def _issue_catastrophic_payment(api, claim_id, provider_bill_id, amount_cents=100000):
    return validate_success(
        api.create_benefit_payment(
            create_benefit_payment_payload(
                claim_id,
                provider_bill_id,
                amount_cents,
                payee_type="PROVIDER",
                layer="CATASTROPHIC",
            ),
            make_claims_examiner_headers(),
        ),
        201,
    )


def test_catastrophic_layer_payment_is_issued_against_the_frozen_two_layer_determination(api):
    """PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.3: "Otherwise the coverage status is `COVERED`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §3.8: "An issued payment takes `status` `ISSUED`, stamps `issued_at` with the logical clock and `issued_by_user_id` with the examiner's `X-User-ID`, and leaves `void_reason` and `voided_at` null."

    Design: Difficulty/transitive_cascade/cascade_b_catastrophic_payment_exhausts_lifetime_and_rejects_pending_report
    """
    bundle = _build_swim_claim_approved_with_base_paid_and_second_report_pending()

    before_claim = read_claim(bundle["claim"]["id"])
    assert before_claim["base_layer_benefit_cents"] == 500000
    assert before_claim["cat_layer_benefit_cents"] == 100000
    assert before_claim["benefit_payable_cents"] == 600000
    assert read_enrollment(bundle["enrollment"]["id"])["coverage_status"] == "COVERED"
    assert read_injury_report(bundle["second_report"]["id"])["status"] == "PENDING_VERIFICATION"

    payment = _issue_catastrophic_payment(
        api, bundle["claim"]["id"], bundle["provider_bill"]["id"]
    )

    assert payment["status"] == "ISSUED"
    assert payment["layer"] == "CATASTROPHIC"
    assert payment["amount_cents"] == 100000
    assert payment["void_reason"] is None
    assert payment["voided_at"] is None


def test_final_catastrophic_payment_closes_the_claim_and_exhausts_the_athletes_lifetime_benefit(api):
    """PRD §3.8: "The claim's `paid_base_cents` (the sum of `ISSUED` `BASE`-layer amounts on the claim), `paid_cat_cents` (the same for the `CATASTROPHIC` layer) and `paid_to_date_cents` (their sum) are recomputed, and once `paid_to_date_cents` has reached or passed `benefit_payable_cents` the claim moves `APPROVED → PAID`, taking it out of the open set."
    PRD §3.8: "Caused by that alone, the athlete's `lifetime_cat_benefit_used_cents` is re-accumulated — it is the sum of `amount_cents` over every `ISSUED` payment on the `CATASTROPHIC` layer across **every** claim of that enrollment, regardless of those claims' adjudication statuses — and the enrollment's `coverage_status` may flip to `LIFETIME_EXHAUSTED`."
    PRD §3.3: "Otherwise, if `lifetime_cat_benefit_used_cents` has reached or passed the governing policy's `cat_lifetime_max_cents`, the coverage status is `LIFETIME_EXHAUSTED` — the test is inclusive, so paying out exactly the lifetime maximum exhausts the athlete."

    Design: Difficulty/transitive_cascade/cascade_b_catastrophic_payment_exhausts_lifetime_and_rejects_pending_report
    """
    bundle = _build_swim_claim_approved_with_base_paid_and_second_report_pending()
    assert read_claim(bundle["claim"]["id"])["adjudication_status"] == "APPROVED"

    _issue_catastrophic_payment(api, bundle["claim"]["id"], bundle["provider_bill"]["id"])

    claim = read_claim(bundle["claim"]["id"])
    assert claim["paid_base_cents"] == 500000
    assert claim["paid_cat_cents"] == 100000
    assert claim["paid_to_date_cents"] == 600000
    assert claim["adjudication_status"] == "PAID"

    enrollment = read_enrollment(bundle["enrollment"]["id"])
    assert enrollment["lifetime_cat_benefit_used_cents"] == 100000
    assert enrollment["coverage_status"] == "LIFETIME_EXHAUSTED"


def test_lifetime_exhaustion_rejects_the_athletes_still_undecided_injury_report(api):
    """PRD §3.8: "Caused by that alone, the athlete's `lifetime_cat_benefit_used_cents` is re-accumulated — it is the sum of `amount_cents` over every `ISSUED` payment on the `CATASTROPHIC` layer across **every** claim of that enrollment, regardless of those claims' adjudication statuses — and the enrollment's `coverage_status` may flip to `LIFETIME_EXHAUSTED`."
    PRD §3.8: "Caused by *that* alone, every injury report of the same enrollment still in `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION` moves to `REJECTED` with `rejection_reason` `LIFETIME_BENEFIT_EXHAUSTED`."
    PRD §2.9: "Every aggregate is correct at the end of the request that disturbed it, and the propagation is explicitly chained: each link is caused by the link before it alone, so an implementation that fires only the first hop will diverge on the second and third."

    Design: Difficulty/transitive_cascade/cascade_b_catastrophic_payment_exhausts_lifetime_and_rejects_pending_report
    """
    bundle = _build_swim_claim_approved_with_base_paid_and_second_report_pending()
    second_report_id = bundle["second_report"]["id"]
    assert read_injury_report(second_report_id)["status"] == "PENDING_VERIFICATION"

    _issue_catastrophic_payment(api, bundle["claim"]["id"], bundle["provider_bill"]["id"])

    assert read_enrollment(bundle["enrollment"]["id"])["coverage_status"] == "LIFETIME_EXHAUSTED"
    swept = read_injury_report(second_report_id)
    assert swept["status"] == "REJECTED"
    assert swept["rejection_reason"] == "LIFETIME_BENEFIT_EXHAUSTED"


def test_paying_the_claim_out_releases_its_whole_case_reserve_from_the_terms_loss_position(api):
    """PRD §3.8: "And in the same request the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, both loss ratios, `open_claim_count`, `experience_tier` and `coverage_posture` are recomputed."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."

    Design: Difficulty/transitive_cascade/cascade_b_catastrophic_payment_exhausts_lifetime_and_rejects_pending_report
    """
    bundle = _build_swim_claim_approved_with_base_paid_and_second_report_pending()
    policy_id = bundle["policy"]["id"]

    before = read_policy(policy_id)
    assert before["paid_loss_cents"] == 500000
    assert before["reserve_cents"] == 600000
    assert before["open_claim_count"] == 1

    _issue_catastrophic_payment(api, bundle["claim"]["id"], bundle["provider_bill"]["id"])

    after = read_policy(policy_id)
    assert after["paid_loss_cents"] == 600000
    assert after["reserve_cents"] == 0
    assert after["incurred_loss_cents"] == 600000
    assert after["open_claim_count"] == 0


def test_the_paid_out_term_lands_on_claims_review_rather_than_frozen(api):
    """PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "Otherwise, if the policy's `open_claim_count` is three or more, the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."

    Design: Difficulty/transitive_cascade/cascade_b_catastrophic_payment_exhausts_lifetime_and_rejects_pending_report
    """
    bundle = _build_swim_claim_approved_with_base_paid_and_second_report_pending()
    policy_id = bundle["policy"]["id"]
    assert read_policy(policy_id)["annual_premium_cents"] == 39060

    _issue_catastrophic_payment(api, bundle["claim"]["id"], bundle["provider_bill"]["id"])

    policy = read_policy(policy_id)
    assert policy["annual_premium_cents"] == 39060
    assert policy["incurred_loss_ratio_bps"] == 153610
    assert policy["paid_loss_ratio_bps"] == 153610
    assert policy["experience_tier"] == "DECLINE"
    # 600000 of incurred loss is far short of the 4000000 aggregate limit, so the
    # loss-ratio test is reached and the term reads CLAIMS_REVIEW, not FROZEN
    assert policy["coverage_posture"] == "CLAIMS_REVIEW"

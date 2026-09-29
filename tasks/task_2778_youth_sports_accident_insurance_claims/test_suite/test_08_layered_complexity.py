"""Optimistic concurrency, threshold stepping and immediate read-after-write.

Three concerns are exercised here. The first is the pair of version-carrying
writes: filing an explanation of benefits against a claim and quoting the
following term off a policy. Both overwrite data another writer may have moved,
so both demand the client's last observed parent version and refuse a token that
has fallen behind, leaving the parent untouched. The second is the operating
posture stepping down its ordered ladder as reserves accumulate on a
deliberately thin term - first into claims review on the loss ratio, then into a
freeze the moment incurred loss lands exactly on the aggregate ceiling. The
third is visibility: the claim an official's verification mints, and every
policy aggregate that verification disturbs, must be right on the very first
read that follows, with no second write and no re-read loop.

Every test rebuilds its own world from scratch: the harness restarts the API
before each test, so nothing is ever inherited.
"""
from test_helpers import (
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    ApiErrorId,
    activate_policy,
    add_family_health_plan,
    add_participant,
    bind_policy,
    canonical_iso,
    create_coordination_record_payload,
    create_enrollment_payload,
    create_league,
    create_sport_classification,
    discover_claim,
    enroll_participant,
    file_coordination_record,
    file_injury_report,
    make_claims_examiner_headers,
    make_league_admin_headers,
    make_program_admin_headers,
    quote_policy,
    read_activity,
    read_claim,
    read_loss_experience,
    read_policy,
    read_provider_bill,
    record_provider_bill,
    renewal_quote_payload,
    reprice_bill,
    request_eob,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_enrolled_athlete,
    setup_sanctioned_activity,
    setup_verified_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_injury_report,
)

EOB_FIGURES = {
    "eob_received_date": "2026-07-18",
    "other_plan_allowed_cents": 300000,
    "other_plan_paid_cents": 210000,
    "patient_responsibility_cents": 90000,
}

NORTHGATE_ER_BILL = {
    "provider_npi": "1200112233",
    "provider_name": "Northgate Regional ER",
    "network_status": "IN_NETWORK",
    "service_category": "EMERGENCY_ROOM",
    "service_date": "2026-07-11",
    "billed_charge_cents": 400000,
    "fee_schedule_amount_cents": 360000,
}

CHEER_ATTESTATION_A = "coach and spotter both witnessed the landing"
CHEER_ATTESTATION_B = "coach witnessed the pyramid dismount"
QUILLAN_ATTESTATION = "first-base official witnessed the play"


def _baseball_claim_awaiting_an_explanation_of_benefits():
    """A moderate baseball claim carrying one repriced in-network charge, with
    the explanation of benefits already requested from the family's carrier.

    The claim version observed the instant the claim is minted is kept alongside
    the version left by the requesting call, so a caller can file with either.
    """
    bundle = setup_enrolled_athlete(
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Northgate Baseball",
            "league_code": "NGB-147",
            "state_code": "MI",
            "governing_body_code": "USYSA",
            "contact_email": "admin@ngb.example",
        },
        participant_overrides={
            "first_name": "Dagny",
            "last_name": "Halvorsen",
            "date_of_birth": "2016-02-09",
            "guardian_email": "g47@ngb.example",
        },
    )
    bundle["family_health_plan"] = add_family_health_plan(
        bundle["participant"]["id"],
        carrier_name="Great Lakes Health",
        policy_number="GL-31200",
        plan_type="PPO",
        individual_deductible_cents=150000,
        coinsurance_bps=2000,
        effective_date="2026-01-01",
    )
    bundle = setup_sanctioned_activity(
        bundle=bundle,
        activity_overrides={
            "activity_type": "GAME",
            "venue_name": "Northgate Field 1",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID,
    )
    bundle = setup_verified_claim(
        bundle=bundle,
        report_overrides={
            "injury_datetime": "2026-07-11T19:00:00Z",
            "body_part": "TORSO",
            "injury_description": "rib contusion blocking the plate",
            "severity_tier": "MODERATE",
        },
        filing_clock="2026-07-12T00:00:00Z",
        verifying_official_id=VERIFYING_OFFICIAL_USER_ID,
        official_attestation="official witnessed the collision at the plate",
    )
    bundle["claim_version_at_mint"] = bundle["claim"]["version"]
    bill = record_provider_bill(bundle["claim"]["id"], **NORTHGATE_ER_BILL)
    bundle["provider_bill"] = reprice_bill(bill["id"])
    claim_after_request = request_eob(
        bundle["claim"]["id"],
        note="requesting the family carrier explanation of benefits",
    )
    bundle["claim"] = claim_after_request
    bundle["claim_version_current"] = claim_after_request["version"]
    return bundle


def _thin_cheer_term_with_two_pending_moderate_reports():
    """A high-hazard cheer term whose aggregate ceiling (500000 cents) is exactly
    two moderate case reserves wide, with both reports filed and awaiting a
    decision. Both athletes are enrolled up front, because a term already in
    claims review will not take on a further covered life.
    """
    bundle = setup_enrolled_athlete(
        classification="cheer",
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Pemberton Cheer",
            "league_code": "PBC-149",
            "state_code": "TX",
            "governing_body_code": "USASF",
            "contact_email": "admin@pbc.example",
        },
        policy_overrides={
            "term_effective_date": "2026-03-01",
            "term_expiration_date": "2027-03-01",
            "enrolled_participant_count": 30,
            "coverage_basis_election": "EXCESS_ONLY",
            "cat_layer_elected": True,
        },
        participant_overrides={
            "first_name": "Elowen",
            "last_name": "Pritchard",
            "date_of_birth": "2016-03-10",
            "guardian_email": "g48@pbc.example",
        },
    )
    second_athlete = add_participant(
        bundle["league"]["id"],
        first_name="Finnian",
        last_name="Doyle",
        date_of_birth="2016-04-11",
        guardian_email="g49@pbc.example",
    )
    second_enrollment = enroll_participant(
        second_athlete["id"],
        bundle["policy"]["id"],
        bundle["league"]["id"],
        enrolled_on_date="2026-03-05",
    )
    activity = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="PRACTICE",
        venue_name="Pemberton Gym",
        starts_at="2026-07-11T15:00:00Z",
        ends_at="2026-07-11T17:00:00Z",
    )
    activity = sanction_activity(activity["id"], SANCTIONING_OFFICIAL_USER_ID)
    set_clock("2026-07-12T00:00:00Z")
    report_a = file_injury_report(
        bundle["enrollment"]["id"],
        activity["id"],
        bundle["league"]["id"],
        injury_datetime="2026-07-11T16:00:00Z",
        body_part="ANKLE_FOOT",
        injury_description="ankle injured landing a basket toss",
        severity_tier="MODERATE",
    )
    report_b = file_injury_report(
        second_enrollment["id"],
        activity["id"],
        bundle["league"]["id"],
        injury_datetime="2026-07-11T16:20:00Z",
        body_part="SHOULDER_ARM",
        injury_description="shoulder injured spotting a pyramid",
        severity_tier="MODERATE",
    )
    bundle["second_participant"] = second_athlete
    bundle["second_enrollment"] = second_enrollment
    bundle["activity"] = activity
    bundle["report_a"] = report_a
    bundle["report_b"] = report_b
    return bundle


def test_explanation_of_benefits_filed_on_a_stale_claim_version_is_refused_and_the_refiling_settles_coordination(api):
    """PRD §2.10: "In each case the guard is a required input field carrying the client's last observed `version` of a *parent* row, and a value that does not match that parent's current `version` is rejected outright."
    PRD §2.10: "Filing an explanation-of-benefits record requires `expected_claim_version`, carrying the `version` the client last read on the claim named by `claim_id`."
    PRD §2.10: "If it does not equal that claim's current `version`, the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §3.6: "A newly filed record takes `status` `ACTIVE` with `superseded_by_record_id` null, and increments the parent claim's `version` by one."
    PRD §3.6: "Filing the first record on a claim also drives the coordination axis `EOB_REQUESTED → EOB_RECEIVED`, after which `coordination_basis` reads `EXCESS_OF_OTHER`, and the claim's `other_insurance_paid_cents` and its whole benefit determination are recomputed."
    PRD §3.6: "At the claim level, `other_insurance_paid_cents` is the sum of `other_plan_paid_cents` across this claim's `ACTIVE` coordination records whose `provider_bill_id` names one of the claim's bills in `REPRICED` or `ADJUDICATED` status."

    Design: Corner/cross_cutting_complexity_layers/coordination_record_with_a_stale_expected_claim_version_rejected
    """
    bundle = _baseball_claim_awaiting_an_explanation_of_benefits()
    claim_id = bundle["claim"]["id"]
    stale_version = bundle["claim_version_at_mint"]
    current_version = bundle["claim_version_current"]

    assert current_version > stale_version, (
        "repricing the charge and requesting the explanation of benefits each "
        f"mutate the claim, so its version must have moved past {stale_version}, "
        f"got {current_version}"
    )

    examiner_headers = make_claims_examiner_headers()
    stale_request = create_coordination_record_payload(
        claim_id,
        bundle["provider_bill"]["id"],
        bundle["family_health_plan"]["id"],
        stale_version,
        **EOB_FIGURES,
    )
    validate_error(
        api.create_coordination_record(stale_request, examiner_headers),
        ApiErrorId.ERR_STALE_CLAIM_VERSION,
        expected_status=412,
    )

    after_refusal = read_claim(claim_id)
    assert after_refusal["version"] == current_version, (
        "a refused stale-version filing mutates nothing, so the claim version "
        f"must still read {current_version}, got {after_refusal['version']}"
    )
    assert after_refusal["coordination_status"] == "EOB_REQUESTED"
    assert after_refusal["other_insurance_paid_cents"] == 0
    rows, meta = validate_paginated(
        api.list_coordination_records(examiner_headers, {"claim_id": claim_id})
    )
    assert meta["total_count"] == 0, (
        "the refused filing must not have written a partial record, got "
        f"{meta['total_count']} coordination records"
    )
    assert rows == []

    fresh_request = dict(stale_request)
    fresh_request["expected_claim_version"] = current_version
    record = validate_success(
        api.create_coordination_record(fresh_request, examiner_headers),
        expected_status=201,
    )
    assert record["status"] == "ACTIVE"
    assert record["superseded_by_record_id"] is None
    assert record["other_plan_paid_cents"] == 210000
    assert record["other_plan_allowed_cents"] == 300000
    assert record["patient_responsibility_cents"] == 90000

    settled = read_claim(claim_id)
    assert settled["coordination_status"] == "EOB_RECEIVED"
    assert settled["coordination_basis"] == "EXCESS_OF_OTHER"
    assert settled["other_insurance_paid_cents"] == 210000
    assert settled["version"] == current_version + 1, (
        "filing the record increments the parent claim's version by exactly one, "
        f"so it must read {current_version + 1}, got {settled['version']}"
    )


def test_explanation_of_benefits_accepted_on_the_current_claim_version_reprices_the_payable_benefit_excess_of_the_family_plan(api):
    """PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "If either condition fails, `cat_layer_benefit_cents` is exactly zero."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."

    Design: Corner/cross_cutting_complexity_layers/coordination_record_with_a_stale_expected_claim_version_rejected
    """
    bundle = _baseball_claim_awaiting_an_explanation_of_benefits()
    claim_id = bundle["claim"]["id"]

    file_coordination_record(
        claim_id,
        bundle["provider_bill"]["id"],
        bundle["family_health_plan"]["id"],
        bundle["claim_version_current"],
        **EOB_FIGURES,
    )

    bill = read_provider_bill(bundle["provider_bill"]["id"])
    assert bill["negotiated_amount_cents"] == 360000
    assert bill["scheduled_cap_cents"] == 500000
    assert bill["allowed_amount_cents"] == 360000

    settled = read_claim(claim_id)
    assert settled["allowed_amount_total_cents"] == 360000
    assert settled["other_insurance_paid_cents"] == 210000
    assert settled["deductible_applied_cents"] == 25000
    assert settled["benefit_before_limit_cents"] == 125000
    assert settled["base_layer_benefit_cents"] == 125000
    assert settled["cat_layer_benefit_cents"] == 0, (
        "the catastrophic layer stays at zero while the claim carries no "
        "catastrophic certification, got "
        f"{settled['cat_layer_benefit_cents']}"
    )
    assert settled["benefit_payable_cents"] == 125000


def test_renewal_quote_written_on_a_pre_activation_policy_version_is_refused_and_the_requote_publishes_the_priced_term(api):
    """PRD §2.10: "Producing a renewal quote requires `expected_league_policy_version`, carrying the `version` the client last read on the addressed policy."
    PRD §2.10: "A mismatch with the policy's current `version` is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."
    PRD §3.9: "`renewal_loss_ratio_bps` is set to `incurred_loss_ratio_bps` when `loss_experience_basis` is `INCURRED`, and to `paid_loss_ratio_bps` when it is `PAID_ONLY`."
    PRD §3.9: "`renewal_experience_tier` is banded from `renewal_loss_ratio_bps` using the same four bands as `experience_tier`, and `renewal_experience_modifier_bps` is read from that tier: `PREFERRED` is −1500 basis points (a credit), `STANDARD` is 0, `ADVERSE` is +2750 and `DECLINE` is +6000."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "The banded gross premium of §3.2 and the six-step annual assembly that follows it are both run again with the participant count set to `renewal_enrolled_participant_count`, keeping the **same** `SportClassification` and the same `cat_layer_elected` election as the expiring term."
    PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000."
    PRD §3.2: "The second band covers participants 76 through 400 at a factor of 0.9250, a seven-and-a-half percent volume discount."
    PRD §3.2: "The third band covers every participant beyond 400 at a factor of 0.8500."
    PRD §3.2: "Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "`gross_premium_cents` is then the plain sum of the three already-rounded band lines."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "`volume_credit_bps` is the credit rate selected **from the subtotal computed in step 2** — never from the gross premium, and never from the final annual premium."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.9: "The result is `renewal_base_premium_cents`."
    PRD §3.9: "`renewal_quoted_premium_cents` is the larger of 25,000 cents (the same minimum annual premium as a new term) and `renewal_base_premium_cents` multiplied by the quantity 10000 plus `renewal_experience_modifier_bps`, divided by 10000, rounded half up."
    PRD §3.9: "Quoting increments the policy's `version`, sets `renewal_quote_status` to `QUOTED`, records `renewal_quote_effective_date` and `renewal_enrolled_participant_count`, and **overwrites any previous renewal block wholesale** — a second quote on the same policy leaves no trace of the first, which is precisely why the stale-version guard matters here."

    Design: Corner/cross_cutting_complexity_layers/renewal_quote_with_a_stale_expected_policy_version_rejected
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Oakmere Baseball",
        league_code="OMB-148",
        state_code="TN",
        governing_body_code="USYSA",
        contact_email="admin@omb.example",
    )
    sport_classification = create_sport_classification("baseball")
    policy = quote_policy(league["id"], sport_classification["id"])
    assert policy["renewal_quote_status"] == "NONE"

    bound = bind_policy(policy["id"])
    stale_version = bound["version"]
    activated = activate_policy(policy["id"])
    current_version = activated["version"]
    assert activated["status"] == "ACTIVE"
    assert current_version == stale_version + 1, (
        "activation is one mutation of the policy row, so the version observed at "
        f"bind time must be exactly one behind, got {stale_version} then "
        f"{current_version}"
    )
    premium_before_quoting = activated["annual_premium_cents"]

    admin_headers = make_program_admin_headers()
    validate_error(
        api.create_renewal_quote(
            policy["id"],
            renewal_quote_payload("INCURRED", "2027-03-01", 410, stale_version),
            admin_headers,
        ),
        ApiErrorId.ERR_STALE_POLICY_VERSION,
        expected_status=412,
    )

    after_refusal = read_policy(policy["id"])
    assert after_refusal["version"] == current_version, (
        "a refused stale-version quote mutates nothing, so the policy version "
        f"must still read {current_version}, got {after_refusal['version']}"
    )
    assert after_refusal["renewal_quote_status"] == "NONE", (
        "the refused quote must not have published a renewal block, got "
        f"renewal_quote_status {after_refusal['renewal_quote_status']!r}"
    )
    assert after_refusal["annual_premium_cents"] == premium_before_quoting

    quoted = validate_success(
        api.create_renewal_quote(
            policy["id"],
            renewal_quote_payload("INCURRED", "2027-03-01", 410, current_version),
            admin_headers,
        ),
        expected_status=200,
    )
    assert quoted["renewal_quote_status"] == "QUOTED"
    assert quoted["renewal_loss_experience_basis"] == "INCURRED"
    assert quoted["renewal_loss_ratio_bps"] == 0
    assert quoted["renewal_experience_tier"] == "PREFERRED"
    assert quoted["renewal_experience_modifier_bps"] == -1500
    assert quoted["renewal_base_premium_cents"] == 833912
    assert quoted["renewal_quoted_premium_cents"] == 708825
    assert quoted["renewal_enrolled_participant_count"] == 410
    assert quoted["annual_premium_cents"] == premium_before_quoting, (
        "the re-rate is published into the renewal block, it does not rewrite the "
        f"expiring term's own annual premium of {premium_before_quoting}, got "
        f"{quoted['annual_premium_cents']}"
    )
    assert quoted["version"] == current_version + 1


def test_one_moderate_case_reserve_on_a_thin_high_hazard_term_tips_the_posture_into_claims_review_and_bars_a_further_covered_life(api):
    """PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "The gross premium slices the declared head count into three cumulative volume bands and prices each band separately."
    PRD §3.2: "The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000."
    PRD §3.2: "Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "`gross_premium_cents` is then the plain sum of the three already-rounded band lines."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "A `CLAIMS_REVIEW` posture is narrower: it blocks only the writing of *new covered lives*, so enrolling a further athlete is refused with `ERR_POLICY_UNDER_CLAIMS_REVIEW` while claims already in flight continue to be repriced, coordinated, adjudicated and paid."
    PRD §3.7: "A recorded bill enters `SUBMITTED` with `allowed_amount_cents` 0 and with `negotiated_amount_cents`, `scheduled_cap_cents`, `balance_billed_cents`, `family_responsibility_cents`, `repriced_at`, `repriced_by_user_id` and `void_reason` all still unset."
    PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."

    Design: Corner/cross_cutting_complexity_layers/coverage_posture_steps_to_claims_review_then_freezes_at_the_aggregate_limit
    """
    bundle = _thin_cheer_term_with_two_pending_moderate_reports()
    policy_id = bundle["policy"]["id"]
    league_id = bundle["league"]["id"]

    assert bundle["policy"]["annual_premium_cents"] == 100681, (
        "thirty high-hazard cheer lives price in the first band alone: 30 x 2450 "
        "loaded by 2625 basis points rounds to 92794, the elected catastrophic "
        "layer adds 7887, and a subtotal of 100681 is below the first credit tier"
    )
    assert bundle["policy"]["aggregate_limit_cents"] == 500000
    assert bundle["policy"]["per_injury_limit_cents"] == 300000
    assert bundle["policy"]["cat_lifetime_max_cents"] == 600000
    assert bundle["policy"]["cat_layer_elected"] is True

    verify_injury_report(
        bundle["report_a"]["id"],
        VERIFYING_OFFICIAL_USER_ID,
        CHEER_ATTESTATION_A,
    )
    first_claim = discover_claim(bundle["report_a"]["id"])
    assert first_claim["reserve_amount_cents"] == 250000, (
        "the standard moderate reserve of 250000 is smaller than the term's "
        "900000-cent exposure cap for one injury, so it is the figure struck"
    )

    position = read_loss_experience(policy_id)
    assert position["paid_loss_cents"] == 0
    assert position["reserve_cents"] == 250000
    assert position["incurred_loss_cents"] == 250000
    assert position["open_claim_count"] == 1
    assert position["paid_loss_ratio_bps"] == 0
    assert position["incurred_loss_ratio_bps"] == 24831, (
        "250000 cents of incurred loss against 100681 cents of earned premium is "
        f"24831 basis points, got {position['incurred_loss_ratio_bps']}"
    )
    assert position["experience_tier"] == "DECLINE"
    assert position["coverage_posture"] == "CLAIMS_REVIEW", (
        "one open claim is short of the three-claim test and 250000 of incurred "
        "loss is short of the 500000 aggregate limit, so the loss ratio test is "
        f"what tips the term, got {position['coverage_posture']}"
    )

    late_joiner = add_participant(
        league_id,
        first_name="Isolde",
        last_name="Marchetti",
        date_of_birth="2016-05-22",
        guardian_email="g50@pbc.example",
    )
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                late_joiner["id"], policy_id, enrolled_on_date="2026-07-12"
            ),
            make_league_admin_headers(league_id),
        ),
        ApiErrorId.ERR_POLICY_UNDER_CLAIMS_REVIEW,
        expected_status=409,
    )

    charge = record_provider_bill(
        first_claim["id"],
        provider_npi="1509887766",
        provider_name="Pemberton Imaging Center",
        network_status="IN_NETWORK",
        service_category="DIAGNOSTIC_IMAGING",
        service_date="2026-07-11",
        billed_charge_cents=130000,
        fee_schedule_amount_cents=90000,
    )
    assert charge["status"] == "SUBMITTED"
    assert charge["allowed_amount_cents"] == 0
    repriced = reprice_bill(charge["id"])
    assert repriced["status"] == "REPRICED", (
        "claims review does not gate the pricing of a charge already in flight, "
        f"got bill status {repriced['status']!r}"
    )
    assert read_claim(first_claim["id"])["adjudication_status"] == "UNDER_ADJUDICATION"

    unchanged = read_loss_experience(policy_id)
    assert unchanged["open_claim_count"] == 1
    assert unchanged["incurred_loss_cents"] == 250000
    assert unchanged["coverage_posture"] == "CLAIMS_REVIEW"


def test_a_second_moderate_reserve_landing_exactly_on_the_aggregate_limit_freezes_the_term_and_sweeps_the_undecided_activity(api):
    """PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."
    PRD §3.4: "Every new activity starts in `PENDING_SANCTION`, with `sanctioning_official_id` and `rejection_reason` both null."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed."
    PRD §3.5: "Caused by those recomputed figures alone, the policy's `coverage_posture` is re-derived and may move to `CLAIMS_REVIEW` or `FROZEN` — a third open claim is exactly what tips a policy into claims review."
    PRD §3.5: "Caused by that posture change alone, if the posture landed on `FROZEN`, every activity of that policy still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` `POLICY_FROZEN`, which in turn rejects the injury reports hanging off those activities as described in §3.4."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §2.8: "Posture is what actually gates whether new exposure and new claim activity may be written; `status` records where the term is in its life, posture records whether the program is presently willing to let anything happen under it."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "The test is inclusive: an incurred loss exactly equal to the aggregate limit freezes the term."
    PRD §2.8: "So `ERR_POLICY_FROZEN` can arise from enrolling an athlete, scheduling an activity, taking a sanction decision, filing an injury report, resubmitting one, taking a verification decision, recording a provider bill, repricing one, filing a coordination record, requesting an explanation of benefits, confirming no other coverage, adjudicating a claim, issuing a benefit payment or quoting a renewal."

    Design: Corner/cross_cutting_complexity_layers/coverage_posture_steps_to_claims_review_then_freezes_at_the_aggregate_limit
    """
    bundle = _thin_cheer_term_with_two_pending_moderate_reports()
    policy_id = bundle["policy"]["id"]
    league_id = bundle["league"]["id"]
    assert bundle["policy"]["aggregate_limit_cents"] == 500000

    verify_injury_report(
        bundle["report_a"]["id"],
        VERIFYING_OFFICIAL_USER_ID,
        CHEER_ATTESTATION_A,
    )

    undecided_activity = schedule_activity(
        policy_id,
        league_id,
        activity_type="PRACTICE",
        venue_name="Pemberton Gym",
        starts_at="2026-08-01T15:00:00Z",
        ends_at="2026-08-01T17:00:00Z",
    )
    assert undecided_activity["status"] == "PENDING_SANCTION"
    late_joiner = add_participant(
        league_id,
        first_name="Isolde",
        last_name="Marchetti",
        date_of_birth="2016-05-22",
        guardian_email="g50@pbc.example",
    )

    verify_injury_report(
        bundle["report_b"]["id"],
        VERIFYING_OFFICIAL_USER_ID,
        CHEER_ATTESTATION_B,
    )
    second_claim = discover_claim(bundle["report_b"]["id"])
    assert second_claim["reserve_amount_cents"] == 250000
    assert second_claim["adjudication_status"] == "PENDING_COORDINATION"
    assert second_claim["coordination_status"] == "NOT_STARTED"

    position = read_loss_experience(policy_id)
    assert position["paid_loss_cents"] == 0
    assert position["open_claim_count"] == 2
    assert position["reserve_cents"] == 500000
    assert position["incurred_loss_cents"] == 500000, (
        "two moderate reserves of 250000 each stand unpaid in the open set, so "
        f"incurred loss lands exactly on the 500000 ceiling, got {position['incurred_loss_cents']}"
    )
    assert position["coverage_posture"] == "FROZEN", (
        "the aggregate test is inclusive, so incurred loss of exactly 500000 "
        f"against an aggregate limit of 500000 freezes the term, got {position['coverage_posture']}"
    )

    frozen_policy = read_policy(policy_id)
    assert frozen_policy["coverage_posture"] == "FROZEN"
    assert frozen_policy["status"] == "ACTIVE", (
        "the freeze is an operating posture, not a lifecycle move: the term is "
        f"still where it was in its life, got status {frozen_policy['status']!r}"
    )

    swept = read_activity(undecided_activity["id"])
    assert swept["status"] == "REJECTED"
    assert swept["rejection_reason"] == "POLICY_FROZEN"
    still_sanctioned = read_activity(bundle["activity"]["id"])
    assert still_sanctioned["status"] == "SANCTIONED", (
        "only activities still awaiting a sanction decision are swept, so the "
        f"activity the injuries happened at is untouched, got {still_sanctioned['status']!r}"
    )
    assert still_sanctioned["rejection_reason"] is None

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                late_joiner["id"], policy_id, enrolled_on_date="2026-07-12"
            ),
            make_league_admin_headers(league_id),
        ),
        ApiErrorId.ERR_POLICY_FROZEN,
        expected_status=409,
    )


def test_the_claim_and_every_policy_aggregate_a_verification_disturbs_are_correct_on_the_first_read_that_follows(api):
    """PRD §2.9: "This system has no eventual consistency and no background jobs."
    PRD §2.9: "Every aggregate is correct at the end of the request that disturbed it, and the propagation is explicitly chained: each link is caused by the link before it alone, so an implementation that fires only the first hop will diverge on the second and third."
    PRD §2.9: "An official's verification of an injury report stamps the report, creates exactly one claim, brings that claim into the policy's open set, forces the policy's loss aggregates and posture to be recomputed, and — if the posture lands on `FROZEN` — sweeps the policy's still-unsanctioned activities into rejection."
    PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "It copies `league_policy_id` and `enrollment_id` off the report's enrollment onto itself — the latter so that lifetime catastrophic accumulation is addressable without traversing back through the report — records the originating report as `injury_report_id`, and is struck with a case reserve."
    PRD §3.5: "Note that the new claim is **not** returned in the verification response body; it is discovered through the filtered claim list of §2.3."
    PRD §3.5: "Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed."
    PRD §3.5: "Caused by those recomputed figures alone, the policy's `coverage_posture` is re-derived and may move to `CLAIMS_REVIEW` or `FROZEN` — a third open claim is exactly what tips a policy into claims review."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §2.3: "Claims may be filtered by `injury_report_id`, `league_policy_id`, `enrollment_id`, `adjudication_status` and `coordination_status` — and because a claim is born as a side effect of verification rather than by a direct create call, this filtered list is the only channel through which a client discovers a newly created claim."
    PRD §3.9: "Everything the program knows about how a policy term is performing is recomputed at the end of every write that changes one of its claims, changes a benefit payment beneath one of those claims, or changes the policy's own `annual_premium_cents`."
    PRD §3.9: "There is no batch job and no nightly close: the figures are always current as of the last write, and they are exposed as a computed read that returns `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `open_claim_count`, `experience_tier` and the current `coverage_posture` together."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000."
    PRD §3.2: "The second band covers participants 76 through 400 at a factor of 0.9250, a seven-and-a-half percent volume discount."
    PRD §3.2: "The third band covers every participant beyond 400 at a factor of 0.8500."
    PRD §3.2: "Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "`gross_premium_cents` is then the plain sum of the three already-rounded band lines."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "`volume_credit_bps` is the credit rate selected **from the subtotal computed in step 2** — never from the gross premium, and never from the final annual premium."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §2.8: "The posture is selected by walking six tests strictly from the top and stopping at the first that matches:"
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "Otherwise, if the policy's `open_claim_count` is three or more, the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."

    Design: Corner/consistency_model/verification_cascade_is_fully_visible_in_the_immediately_following_reads
    """
    bundle = setup_sanctioned_activity(
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Quillan Baseball",
            "league_code": "QLB-150",
            "state_code": "KY",
            "governing_body_code": "USYSA",
            "contact_email": "admin@qlb.example",
        },
        participant_overrides={
            "first_name": "Rhiannon",
            "last_name": "Vasquez",
            "date_of_birth": "2016-06-14",
            "guardian_email": "g51@qlb.example",
        },
        activity_overrides={
            "activity_type": "GAME",
            "venue_name": "Quillan Diamond 2",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID,
    )
    policy_id = bundle["policy"]["id"]
    assert bundle["policy"]["annual_premium_cents"] == 822840, (
        "404 declared lives price as 154706 + 620114 + 7013 = 781833 gross, plus "
        "66456 for the catastrophic layer, less the 300 basis point credit of "
        "25449 earned on the 848289 subtotal"
    )
    assert bundle["policy"]["aggregate_limit_cents"] == 25000000
    assert bundle["policy"]["per_injury_limit_cents"] == 2500000
    assert bundle["policy"]["cat_lifetime_max_cents"] == 100000000

    set_clock("2026-07-12T00:00:00Z")
    report = file_injury_report(
        bundle["enrollment"]["id"],
        bundle["activity"]["id"],
        bundle["league"]["id"],
        injury_datetime="2026-07-11T19:10:00Z",
        body_part="KNEE",
        injury_description="knee twisted sliding into first base",
        severity_tier="MODERATE",
    )
    verified = verify_injury_report(
        report["id"], VERIFYING_OFFICIAL_USER_ID, QUILLAN_ATTESTATION
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verifying_official_id"] == VERIFYING_OFFICIAL_USER_ID
    assert verified["official_attestation"] == QUILLAN_ATTESTATION
    assert canonical_iso(verified["verified_at"]) == canonical_iso("2026-07-12T00:00:00Z")
    assert "claim" not in verified
    assert "claim_id" not in verified

    rows, meta = validate_paginated(
        api.list_claims(
            make_claims_examiner_headers(), {"injury_report_id": report["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the verification itself is the only write, and the one claim it minted "
        f"must already be discoverable on this first filtered read, got {meta['total_count']}"
    )
    minted = rows[0]
    assert minted["injury_report_id"] == report["id"]
    assert minted["league_policy_id"] == policy_id
    assert minted["enrollment_id"] == bundle["enrollment"]["id"]
    assert minted["adjudication_status"] == "PENDING_COORDINATION"
    assert minted["coordination_status"] == "NOT_STARTED"
    assert minted["reserve_amount_cents"] == 250000

    position = read_loss_experience(policy_id)
    assert position["paid_loss_cents"] == 0
    assert position["reserve_cents"] == 250000
    assert position["incurred_loss_cents"] == 250000
    assert position["open_claim_count"] == 1
    assert position["paid_loss_ratio_bps"] == 0
    assert position["incurred_loss_ratio_bps"] == 3038, (
        "250000 cents of incurred loss against 822840 cents of earned premium is "
        f"3038 basis points on the very first read, got {position['incurred_loss_ratio_bps']}"
    )
    assert position["experience_tier"] == "PREFERRED"
    assert position["coverage_posture"] == "OPEN", (
        "one open claim, 250000 of incurred loss against a 25000000 aggregate "
        "limit and 3038 basis points of loss ratio fail all five freezing and "
        f"review tests, got {position['coverage_posture']}"
    )
    assert read_policy(policy_id)["coverage_posture"] == "OPEN"

    reported_figures = (
        "paid_loss_cents",
        "reserve_cents",
        "incurred_loss_cents",
        "incurred_loss_ratio_bps",
        "paid_loss_ratio_bps",
        "open_claim_count",
        "experience_tier",
        "coverage_posture",
    )
    repeat = read_loss_experience(policy_id)
    assert {key: repeat[key] for key in reported_figures} == {
        key: position[key] for key in reported_figures
    }, (
        "a second read with no intervening write must return the same figures, "
        f"got {repeat} after {position}"
    )

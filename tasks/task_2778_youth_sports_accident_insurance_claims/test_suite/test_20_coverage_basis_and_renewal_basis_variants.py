"""Two-variant calculations: the coordination basis on a claim's benefit
determination, and the elected loss basis on a renewal quote.

Each test builds its own world from an empty database through PRD-declared
endpoints, threading the real League id into every LeagueAdministrator call and
the real Participant id into every GuardianPortal call.
"""
from test_helpers import (
    ApiErrorId,
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    add_family_health_plan,
    add_participant,
    adjudicate_claim,
    confirm_no_other_coverage,
    discover_claim,
    enroll_participant,
    file_coordination_record,
    file_injury_report,
    make_program_admin_headers,
    read_claim,
    read_policy,
    read_provider_bill,
    record_provider_bill,
    renewal_quote_payload,
    reprice_bill,
    request_eob,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_active_policy,
    validate_error,
    validate_success,
    verify_family_plan,
    verify_injury_report,
)

PROGRAM_ADMIN = make_program_admin_headers()

# The emergency-room charge both claims carry, identically.
EMERGENCY_ROOM_CHARGE = {
    "provider_npi": "1730294856",
    "provider_name": "Riverside General ED",
    "network_status": "IN_NETWORK",
    "service_category": "EMERGENCY_ROOM",
    "service_date": "2026-07-11",
    "billed_charge_cents": 620000,
    "fee_schedule_amount_cents": 385000,
}

# The diagnostic-imaging charge both claims carry, identically.
DIAGNOSTIC_IMAGING_CHARGE = {
    "provider_npi": "1447203981",
    "provider_name": "Northside Imaging",
    "network_status": "OUT_OF_NETWORK",
    "service_category": "DIAGNOSTIC_IMAGING",
    "service_date": "2026-07-11",
    "billed_charge_cents": 480000,
    "fee_schedule_amount_cents": 260000,
}


def _build_two_coordination_basis_claims():
    """Two claims on one term carrying byte-identical provider billing, one
    settled on an explanation of benefits and one on a no-other-coverage
    attestation.
    """
    bundle = setup_active_policy(
        clock="2026-03-05T00:00:00Z",
        policy_overrides={
            "enrolled_participant_count": 404,
            "coverage_basis_election": "FULL_EXCESS_PERMITTED",
            "cat_layer_elected": True,
        },
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]

    insured_athlete = add_participant(
        league_id,
        first_name="Ada",
        last_name="Nowak",
        date_of_birth="2014-04-02",
        guardian_email="g1@ryb.example",
    )
    uninsured_athlete = add_participant(
        league_id,
        first_name="Ben",
        last_name="Ortiz",
        date_of_birth="2014-09-19",
        guardian_email="g2@ryb.example",
    )
    insured_enrollment = enroll_participant(
        insured_athlete["id"], policy_id, league_id, enrolled_on_date="2026-03-05"
    )
    uninsured_enrollment = enroll_participant(
        uninsured_athlete["id"], policy_id, league_id, enrolled_on_date="2026-03-05"
    )

    family_plan = add_family_health_plan(
        insured_athlete["id"],
        carrier_name="Buckeye Mutual",
        policy_number="BM-99413",
        plan_type="PPO",
        individual_deductible_cents=150000,
        coinsurance_bps=2000,
        effective_date="2026-01-01",
    )
    verify_family_plan(family_plan["id"])

    activity = schedule_activity(
        policy_id,
        league_id,
        activity_type="GAME",
        venue_name="Riverside Field 2",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:30:00Z",
    )
    sanction_activity(activity["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")

    insured_report = file_injury_report(
        insured_enrollment["id"],
        activity["id"],
        league_id,
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="KNEE",
        injury_description="collision at second base, suspected ACL tear",
        severity_tier="SEVERE",
    )
    verify_injury_report(insured_report["id"], VERIFYING_OFFICIAL_USER_ID)
    excess_claim = discover_claim(insured_report["id"])

    uninsured_report = file_injury_report(
        uninsured_enrollment["id"],
        activity["id"],
        league_id,
        injury_datetime="2026-07-11T19:05:00Z",
        body_part="SHOULDER_ARM",
        injury_description="outfield collision, suspected labral tear",
        severity_tier="SEVERE",
    )
    verify_injury_report(uninsured_report["id"], VERIFYING_OFFICIAL_USER_ID)
    full_excess_claim = discover_claim(uninsured_report["id"])

    bills = {}
    for key, claim_id in (
        ("excess", excess_claim["id"]),
        ("full_excess", full_excess_claim["id"]),
    ):
        emergency_bill = record_provider_bill(claim_id, **EMERGENCY_ROOM_CHARGE)
        reprice_bill(emergency_bill["id"])
        imaging_bill = record_provider_bill(claim_id, **DIAGNOSTIC_IMAGING_CHARGE)
        reprice_bill(imaging_bill["id"])
        bills[key] = {"emergency": emergency_bill, "imaging": imaging_bill}

    request_eob(
        excess_claim["id"], note="requesting explanation of benefits from Buckeye Mutual"
    )
    file_coordination_record(
        excess_claim["id"],
        bills["excess"]["emergency"]["id"],
        family_plan["id"],
        read_claim(excess_claim["id"])["version"],
        eob_received_date="2026-07-20",
        other_plan_allowed_cents=0,
        other_plan_paid_cents=0,
        patient_responsibility_cents=0,
    )
    confirm_no_other_coverage(
        full_excess_claim["id"],
        attestation_note="guardian attests no other health coverage exists for this athlete",
    )

    return {
        "excess_claim_id": excess_claim["id"],
        "full_excess_claim_id": full_excess_claim["id"],
        "bills": bills,
    }


def test_excess_of_other_claim_absorbs_the_face_deductible_and_pays_705000_cents(api):
    """PRD §3.6: "`coordination_basis` itself is derived, never supplied. It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "It reaches `UNDER_ADJUDICATION → APPROVED` when the athlete's enrollment `status` is `ENROLLED` and `benefit_payable_cents` is at least one cent, and when the determination does not reach into the catastrophic layer without certification: where the policy's `cat_layer_elected` is true and `benefit_before_limit_cents` exceeds the policy's `cat_attachment_point_cents`, the claim's `cat_certification_status` must be `CERTIFIED`, and otherwise the adjudication is refused with `ERR_CAT_CERTIFICATION_REQUIRED` rather than quietly paying the base layer alone."

    Design: Difficulty/dual_variant_calc/benefit_determination_excess_of_other_vs_full_excess
    """
    world = _build_two_coordination_basis_claims()

    before_adjudication = read_claim(world["excess_claim_id"])
    assert before_adjudication["coordination_status"] == "EOB_RECEIVED"
    assert before_adjudication["coordination_basis"] == "EXCESS_OF_OTHER"
    assert before_adjudication["allowed_amount_total_cents"] == 730000
    assert before_adjudication["other_insurance_paid_cents"] == 0

    adjudicated = adjudicate_claim(
        world["excess_claim_id"],
        examiner_note="covered GAME activity, excess of other coverage",
    )

    assert adjudicated["adjudication_status"] == "APPROVED"
    assert adjudicated["deductible_applied_cents"] == 25000
    assert adjudicated["benefit_before_limit_cents"] == 705000
    assert adjudicated["base_layer_benefit_cents"] == 705000
    assert adjudicated["cat_layer_benefit_cents"] == 0
    assert adjudicated["benefit_payable_cents"] == 705000


def test_full_excess_claim_absorbs_the_doubled_deductible_and_pays_680000_cents(api):
    """PRD §3.6: "It carries one further requirement of its own: the governing policy's `coverage_basis_election` must be `FULL_EXCESS_PERMITTED`."
    PRD §3.6: "On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."

    Design: Difficulty/dual_variant_calc/benefit_determination_excess_of_other_vs_full_excess
    """
    world = _build_two_coordination_basis_claims()

    before_adjudication = read_claim(world["full_excess_claim_id"])
    assert before_adjudication["coordination_status"] == "NO_OTHER_COVERAGE_CONFIRMED"
    assert before_adjudication["coordination_basis"] == "FULL_EXCESS"
    assert before_adjudication["allowed_amount_total_cents"] == 730000
    assert before_adjudication["other_insurance_paid_cents"] == 0

    adjudicated = adjudicate_claim(
        world["full_excess_claim_id"],
        examiner_note="covered GAME activity, program primary on a full-excess footing",
    )

    assert adjudicated["adjudication_status"] == "APPROVED"
    assert adjudicated["deductible_applied_cents"] == 50000
    assert adjudicated["benefit_before_limit_cents"] == 680000
    assert adjudicated["base_layer_benefit_cents"] == 680000
    assert adjudicated["cat_layer_benefit_cents"] == 0
    assert adjudicated["benefit_payable_cents"] == 680000


def test_identical_severe_charges_reprice_to_the_same_730000_allowed_total_on_both_claims(api):
    """PRD §3.7: "`negotiated_amount_cents` branches on the network status. For an in-network provider it is the smaller of the billed charge and the fee-schedule amount. For an out-of-network provider the program is willing to go above its own fee schedule but not without limit: take the fee-schedule amount, multiply by 14000 basis points — one hundred and forty percent — divide by ten thousand and round half up to whole cents, then take the smaller of the billed charge and that number."
    PRD §3.7: "`scheduled_cap_cents` is the benefit schedule's cap for this service category, adjusted for how badly the athlete was hurt. Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`family_responsibility_cents` is the balance-protection figure and it is where the program's promise to families lives. For an in-network provider it is **always exactly zero** — a participating provider may bill the family nothing above the allowed amount. For an out-of-network provider it is the balance billed, but capped at 15,000 cents (one hundred and fifty dollars); anything beyond that cap is the provider's problem, not the family's."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."

    Design: Difficulty/dual_variant_calc/benefit_determination_excess_of_other_vs_full_excess
    """
    world = _build_two_coordination_basis_claims()

    for key in ("excess", "full_excess"):
        emergency_bill = read_provider_bill(world["bills"][key]["emergency"]["id"])
        assert emergency_bill["status"] == "REPRICED"
        assert emergency_bill["negotiated_amount_cents"] == 385000
        assert emergency_bill["scheduled_cap_cents"] == 575000
        assert emergency_bill["allowed_amount_cents"] == 385000
        assert emergency_bill["balance_billed_cents"] == 235000
        assert emergency_bill["family_responsibility_cents"] == 0

        imaging_bill = read_provider_bill(world["bills"][key]["imaging"]["id"])
        assert imaging_bill["status"] == "REPRICED"
        assert imaging_bill["negotiated_amount_cents"] == 364000
        assert imaging_bill["scheduled_cap_cents"] == 345000
        assert imaging_bill["allowed_amount_cents"] == 345000
        assert imaging_bill["balance_billed_cents"] == 135000
        assert imaging_bill["family_responsibility_cents"] == 15000

    excess_claim = read_claim(world["excess_claim_id"])
    full_excess_claim = read_claim(world["full_excess_claim_id"])
    assert excess_claim["allowed_amount_total_cents"] == 730000
    assert full_excess_claim["allowed_amount_total_cents"] == 730000

    excess_approved = adjudicate_claim(
        world["excess_claim_id"], examiner_note="excess of other coverage"
    )
    full_excess_approved = adjudicate_claim(
        world["full_excess_claim_id"], examiner_note="program primary, full-excess footing"
    )
    assert excess_approved["benefit_payable_cents"] == 705000
    assert full_excess_approved["benefit_payable_cents"] == 680000
    assert (
        excess_approved["benefit_payable_cents"]
        - full_excess_approved["benefit_payable_cents"]
        == 25000
    )


def _build_reserve_only_loss_position():
    """One ACTIVE term whose whole loss position is case reserve: two MODERATE
    claims left in PENDING_COORDINATION and not a cent paid out.
    """
    bundle = setup_active_policy(
        clock="2026-03-05T00:00:00Z",
        policy_overrides={
            "enrolled_participant_count": 404,
            "coverage_basis_election": "EXCESS_ONLY",
            "cat_layer_elected": True,
        },
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]

    first_athlete = add_participant(
        league_id,
        first_name="Cleo",
        last_name="Marsh",
        date_of_birth="2014-01-30",
        guardian_email="g3@ryb.example",
    )
    second_athlete = add_participant(
        league_id,
        first_name="Dov",
        last_name="Reyes",
        date_of_birth="2014-06-11",
        guardian_email="g4@ryb.example",
    )
    first_enrollment = enroll_participant(
        first_athlete["id"], policy_id, league_id, enrolled_on_date="2026-03-05"
    )
    second_enrollment = enroll_participant(
        second_athlete["id"], policy_id, league_id, enrolled_on_date="2026-03-05"
    )

    activity = schedule_activity(
        policy_id,
        league_id,
        activity_type="PRACTICE",
        venue_name="Riverside Cage 1",
        starts_at="2026-06-02T17:00:00Z",
        ends_at="2026-06-02T19:00:00Z",
    )
    sanction_activity(activity["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-06-03T00:00:00Z")

    first_report = file_injury_report(
        first_enrollment["id"],
        activity["id"],
        league_id,
        injury_datetime="2026-06-02T18:00:00Z",
        body_part="ANKLE_FOOT",
        injury_description="rolled ankle on batting cage mat",
        severity_tier="MODERATE",
    )
    verify_injury_report(
        first_report["id"],
        VERIFYING_OFFICIAL_USER_ID,
        official_attestation="assistant coach witnessed",
    )
    second_report = file_injury_report(
        second_enrollment["id"],
        activity["id"],
        league_id,
        injury_datetime="2026-06-02T18:20:00Z",
        body_part="HAND_WRIST",
        injury_description="jammed wrist fielding grounder",
        severity_tier="MODERATE",
    )
    verify_injury_report(
        second_report["id"],
        VERIFYING_OFFICIAL_USER_ID,
        official_attestation="assistant coach witnessed",
    )

    return {"policy_id": policy_id, "policy": read_policy(policy_id)}


def test_renewal_quote_on_the_incurred_basis_prices_reserves_into_the_standard_tier(api):
    """PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up. `paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`renewal_loss_ratio_bps` is set to `incurred_loss_ratio_bps` when `loss_experience_basis` is `INCURRED`, and to `paid_loss_ratio_bps` when it is `PAID_ONLY`."
    PRD §3.9: "The elected basis is recorded as `renewal_loss_experience_basis`."
    PRD §3.9: "`renewal_experience_tier` is banded from `renewal_loss_ratio_bps` using the same four bands as `experience_tier`, and `renewal_experience_modifier_bps` is read from that tier: `PREFERRED` is −1500 basis points (a credit), `STANDARD` is 0, `ADVERSE` is +2750 and `DECLINE` is +6000."
    PRD §3.9: "The banded gross premium of §3.2 and the six-step annual assembly that follows it are both run again with the participant count set to `renewal_enrolled_participant_count`, keeping the **same** `SportClassification` and the same `cat_layer_elected` election as the expiring term. The result is `renewal_base_premium_cents`."
    PRD §3.9: "`renewal_quoted_premium_cents` is the larger of 25,000 cents (the same minimum annual premium as a new term) and `renewal_base_premium_cents` multiplied by the quantity 10000 plus `renewal_experience_modifier_bps`, divided by 10000, rounded half up."

    Design: Difficulty/dual_variant_calc/renewal_quote_incurred_basis_vs_paid_only_basis
    """
    world = _build_reserve_only_loss_position()
    policy = world["policy"]

    assert policy["annual_premium_cents"] == 822840
    assert policy["reserve_cents"] == 500000
    assert policy["paid_loss_cents"] == 0
    assert policy["incurred_loss_cents"] == 500000
    assert policy["incurred_loss_ratio_bps"] == 6077
    assert policy["paid_loss_ratio_bps"] == 0
    assert policy["open_claim_count"] == 2

    quoted = validate_success(
        api.create_renewal_quote(
            world["policy_id"],
            renewal_quote_payload(
                "INCURRED", "2027-03-01", 410, policy["version"]
            ),
            PROGRAM_ADMIN,
        )
    )

    assert quoted["renewal_loss_experience_basis"] == "INCURRED"
    assert quoted["renewal_loss_ratio_bps"] == 6077
    assert quoted["renewal_experience_tier"] == "STANDARD"
    assert quoted["renewal_experience_modifier_bps"] == 0
    assert quoted["renewal_base_premium_cents"] == 833912
    assert quoted["renewal_quoted_premium_cents"] == 833912
    assert quoted["renewal_quote_status"] == "QUOTED"


def test_renewal_quote_on_the_paid_only_basis_ignores_reserves_and_earns_the_preferred_credit(api):
    """PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up. `paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`renewal_loss_ratio_bps` is set to `incurred_loss_ratio_bps` when `loss_experience_basis` is `INCURRED`, and to `paid_loss_ratio_bps` when it is `PAID_ONLY`."
    PRD §3.9: "This is the whole of the difference between the two variants, and it is a large difference: the incurred basis charges the league for case reserves on claims that have not paid a cent, while the paid-only basis ignores every reserve."
    PRD §3.9: "The elected basis is recorded as `renewal_loss_experience_basis`."
    PRD §3.9: "`renewal_experience_tier` is banded from `renewal_loss_ratio_bps` using the same four bands as `experience_tier`, and `renewal_experience_modifier_bps` is read from that tier: `PREFERRED` is −1500 basis points (a credit), `STANDARD` is 0, `ADVERSE` is +2750 and `DECLINE` is +6000."
    PRD §3.9: "`renewal_quoted_premium_cents` is the larger of 25,000 cents (the same minimum annual premium as a new term) and `renewal_base_premium_cents` multiplied by the quantity 10000 plus `renewal_experience_modifier_bps`, divided by 10000, rounded half up."

    Design: Difficulty/dual_variant_calc/renewal_quote_incurred_basis_vs_paid_only_basis
    """
    world = _build_reserve_only_loss_position()
    policy = world["policy"]

    assert policy["annual_premium_cents"] == 822840
    assert policy["paid_loss_cents"] == 0
    assert policy["paid_loss_ratio_bps"] == 0

    quoted = validate_success(
        api.create_renewal_quote(
            world["policy_id"],
            renewal_quote_payload(
                "PAID_ONLY", "2027-03-01", 410, policy["version"]
            ),
            PROGRAM_ADMIN,
        )
    )

    assert quoted["renewal_loss_experience_basis"] == "PAID_ONLY"
    assert quoted["renewal_loss_ratio_bps"] == 0
    assert quoted["renewal_experience_tier"] == "PREFERRED"
    assert quoted["renewal_experience_modifier_bps"] == -1500
    assert quoted["renewal_base_premium_cents"] == 833912
    assert quoted["renewal_quoted_premium_cents"] == 708825
    assert quoted["renewal_quote_status"] == "QUOTED"


def test_requoting_on_the_paid_only_basis_overwrites_the_incurred_renewal_block_wholesale(api):
    """PRD §3.9: "`renewal_loss_ratio_bps` is set to `incurred_loss_ratio_bps` when `loss_experience_basis` is `INCURRED`, and to `paid_loss_ratio_bps` when it is `PAID_ONLY`."
    PRD §3.9: "Because step 1 may have selected the paid-only ratio, `renewal_experience_tier` is not required to agree with the policy's own `experience_tier`, which is always banded from the incurred ratio."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §3.9: "Quoting increments the policy's `version`, sets `renewal_quote_status` to `QUOTED`, records `renewal_quote_effective_date` and `renewal_enrolled_participant_count`, and **overwrites any previous renewal block wholesale** — a second quote on the same policy leaves no trace of the first, which is precisely why the stale-version guard matters here."
    PRD §3.9: "`renewal_quoted_premium_cents` is the larger of 25,000 cents (the same minimum annual premium as a new term) and `renewal_base_premium_cents` multiplied by the quantity 10000 plus `renewal_experience_modifier_bps`, divided by 10000, rounded half up."

    Design: Difficulty/dual_variant_calc/renewal_quote_incurred_basis_vs_paid_only_basis
    """
    world = _build_reserve_only_loss_position()

    incurred_quote = validate_success(
        api.create_renewal_quote(
            world["policy_id"],
            renewal_quote_payload(
                "INCURRED", "2027-03-01", 410, world["policy"]["version"]
            ),
            PROGRAM_ADMIN,
        )
    )
    assert incurred_quote["renewal_experience_tier"] == "STANDARD"
    assert incurred_quote["renewal_quoted_premium_cents"] == 833912

    paid_only_quote = validate_success(
        api.create_renewal_quote(
            world["policy_id"],
            renewal_quote_payload(
                "PAID_ONLY", "2027-03-01", 410, incurred_quote["version"]
            ),
            PROGRAM_ADMIN,
        )
    )

    assert paid_only_quote["renewal_loss_experience_basis"] == "PAID_ONLY"
    assert paid_only_quote["renewal_loss_ratio_bps"] == 0
    assert paid_only_quote["renewal_experience_tier"] == "PREFERRED"
    assert paid_only_quote["renewal_experience_modifier_bps"] == -1500
    assert paid_only_quote["renewal_base_premium_cents"] == 833912
    assert paid_only_quote["renewal_quoted_premium_cents"] == 708825
    assert paid_only_quote["renewal_quote_status"] == "QUOTED"

    # The term's own tier stays banded from the incurred ratio it never stopped
    # carrying, so the two tiers legitimately disagree.
    assert paid_only_quote["experience_tier"] == "STANDARD"
    assert paid_only_quote["incurred_loss_ratio_bps"] == 6077
    assert (
        incurred_quote["renewal_quoted_premium_cents"]
        - paid_only_quote["renewal_quoted_premium_cents"]
        == 125087
    )


def test_second_renewal_quote_carrying_the_pre_quote_policy_version_is_rejected_as_stale(api):
    """PRD §2.10: "Producing a renewal quote requires `expected_league_policy_version`, carrying the `version` the client last read on the addressed policy. A mismatch with the policy's current `version` is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."
    PRD §3.9: "Quoting increments the policy's `version`, sets `renewal_quote_status` to `QUOTED`, records `renewal_quote_effective_date` and `renewal_enrolled_participant_count`, and **overwrites any previous renewal block wholesale** — a second quote on the same policy leaves no trace of the first, which is precisely why the stale-version guard matters here."

    Design: Difficulty/dual_variant_calc/renewal_quote_incurred_basis_vs_paid_only_basis
    """
    world = _build_reserve_only_loss_position()
    stale_version = world["policy"]["version"]

    incurred_quote = validate_success(
        api.create_renewal_quote(
            world["policy_id"],
            renewal_quote_payload("INCURRED", "2027-03-01", 410, stale_version),
            PROGRAM_ADMIN,
        )
    )
    assert incurred_quote["version"] > stale_version

    validate_error(
        api.create_renewal_quote(
            world["policy_id"],
            renewal_quote_payload("PAID_ONLY", "2027-03-01", 410, stale_version),
            PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_STALE_POLICY_VERSION.value,
        412,
    )

    unchanged = read_policy(world["policy_id"])
    assert unchanged["renewal_loss_experience_basis"] == "INCURRED"
    assert unchanged["renewal_experience_tier"] == "STANDARD"
    assert unchanged["renewal_quoted_premium_cents"] == 833912

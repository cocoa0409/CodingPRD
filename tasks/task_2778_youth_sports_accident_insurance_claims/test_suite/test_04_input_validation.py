"""Rejections and acceptances at the exact edge of each declared rule.

The program's rules are written with pinned endpoints: a policy term is closed at
its effective date and open at its expiration date, an activity window is closed
at both ends, a layer ceiling is inclusive, a catastrophic certification is only
demanded when the layer was actually purchased, and the rule ladder decides which
of two simultaneously broken rules a caller hears about. Every test below builds
its own league, sport classification, term and roster from scratch and probes one
of those edges from both sides where the specification commits to both answers.
"""
from test_helpers import (
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    ApiErrorId,
    add_participant,
    activate_policy,
    bind_policy,
    confirm_no_other_coverage,
    create_benefit_payment_payload,
    create_enrollment_payload,
    create_injury_report_payload,
    create_league,
    create_sport_classification,
    discover_claim,
    enroll_participant,
    file_injury_report,
    issue_benefit_payment,
    make_claims_examiner_headers,
    make_league_admin_headers,
    make_medical_reviewer_headers,
    make_program_admin_headers,
    payments_for_claim,
    quote_policy,
    read_claim,
    read_league,
    read_participant,
    read_policy,
    record_provider_bill,
    reprice_bill,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_active_policy,
    setup_approved_full_excess_claim,
    setup_sanctioned_activity,
    validate_error,
    validate_paginated,
    validate_success,
    verify_injury_report,
)


BASEBALL_TERM_POLICY = {
    "term_effective_date": "2026-03-01",
    "term_expiration_date": "2027-03-01",
    "enrolled_participant_count": 404,
    "coverage_basis_election": "EXCESS_ONLY",
    "cat_layer_elected": True,
}


def test_enrollment_dated_outside_the_half_open_term_is_refused_at_both_ends(api):
    """PRD §3.3: "The `enrolled_on_date` must fall inside the policy's half-open term, or the request is refused with `ERR_ENROLLMENT_OUTSIDE_TERM`."

    PRD §2.11: "A **policy term** is the half-open interval running from `term_effective_date` inclusive to `term_expiration_date` exclusive."
    PRD §2.11: "A date equal to the effective date is inside the term; a date equal to the expiration date is outside it."
    PRD §3.3: "`roster_status` is `ROSTERED` while at least one enrollment of the athlete is `ENROLLED`, becomes `INACTIVE` once every enrollment of the athlete has been withdrawn, and — importantly for the moment just after an athlete is added — reads `ROSTERED` when the athlete has no enrollment rows at all."

    Design: Corner/validations/enrollment_outside_the_half_open_policy_term_rejected
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Talbot Baseball",
            "league_code": "TLB-125",
            "state_code": "VT",
            "governing_body_code": "USYSA",
            "contact_email": "admin@tlb.example",
        },
        policy_overrides=dict(BASEBALL_TERM_POLICY),
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]
    league_headers = make_league_admin_headers(league_id)
    athlete = add_participant(
        league_id,
        first_name="Liesl",
        last_name="Brandt",
        date_of_birth="2014-10-24",
        guardian_email="g29@tlb.example",
    )

    one_day_early = api.create_enrollment(
        create_enrollment_payload(
            athlete["id"], policy_id, enrolled_on_date="2026-02-28"
        ),
        league_headers,
    )
    validate_error(
        one_day_early, ApiErrorId.ERR_ENROLLMENT_OUTSIDE_TERM, expected_status=422
    )

    # 2027-03-01 is the expiration date itself, the first day the term no longer covers.
    on_the_expiration_date = api.create_enrollment(
        create_enrollment_payload(
            athlete["id"], policy_id, enrolled_on_date="2027-03-01"
        ),
        league_headers,
    )
    validate_error(
        on_the_expiration_date,
        ApiErrorId.ERR_ENROLLMENT_OUTSIDE_TERM,
        expected_status=422,
    )

    rows, meta = validate_paginated(
        api.list_enrollments(league_headers, {"league_policy_id": policy_id})
    )
    assert meta["total_count"] == 0, "a refused enrollment must leave no row behind"
    assert rows == []

    athlete_after = read_participant(athlete["id"])
    assert athlete_after["enrolled_policy_count"] == 0
    assert athlete_after["roster_status"] == "ROSTERED"


def test_enrollment_dated_exactly_on_the_term_effective_date_is_accepted(api):
    """PRD §2.11: "A date equal to the effective date is inside the term; a date equal to the expiration date is outside it."

    PRD §3.3: "The `enrolled_on_date` must fall inside the policy's half-open term, or the request is refused with `ERR_ENROLLMENT_OUTSIDE_TERM`."
    PRD §3.3: "A new enrollment starts with `status` `ENROLLED`, `lifetime_cat_benefit_used_cents` 0 and `coverage_status` `COVERED`, and its creation immediately recomputes the athlete's `enrolled_policy_count` and `roster_status`."
    PRD §3.3: "The `withdrawn_on_date` field stays null while the enrollment is live."

    Design: Corner/validations/enrollment_on_the_exact_term_effective_date_accepted
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Umberland Baseball",
            "league_code": "UMB-126",
            "state_code": "NH",
            "governing_body_code": "USYSA",
            "contact_email": "admin@umb.example",
        },
        policy_overrides=dict(BASEBALL_TERM_POLICY),
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]
    league_headers = make_league_admin_headers(league_id)
    athlete = add_participant(
        league_id,
        first_name="Mateo",
        last_name="Villalobos",
        date_of_birth="2014-11-25",
        guardian_email="g30@umb.example",
    )

    created = validate_success(
        api.create_enrollment(
            create_enrollment_payload(
                athlete["id"], policy_id, enrolled_on_date="2026-03-01"
            ),
            league_headers,
        ),
        expected_status=201,
    )

    assert created["enrolled_on_date"].startswith("2026-03-01")
    assert created["status"] == "ENROLLED"
    assert created["coverage_status"] == "COVERED"
    assert created["lifetime_cat_benefit_used_cents"] == 0
    assert created["withdrawn_on_date"] is None

    athlete_after = read_participant(athlete["id"])
    assert athlete_after["roster_status"] == "ROSTERED"
    assert athlete_after["enrolled_policy_count"] == 1


def test_injury_one_minute_after_the_final_out_is_refused_while_the_closing_bell_is_covered(api):
    """PRD §3.5: "The `injury_datetime` must fall inside the activity's closed window from `starts_at` to `ends_at`, with both endpoints counting as inside, or the filing is refused with `ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW`."

    PRD §2.11: "An **activity window** is the closed interval running from `starts_at` to `ends_at`, with both endpoints inside the window."
    PRD §2.11: "An injury recorded at exactly `starts_at` or exactly `ends_at` happened during the activity."
    PRD §3.4: "Note the asymmetry with the buffer: the buffer widens the collision footprint but never extends the coverage window, so the term test uses the raw window."
    PRD §3.5: "`days_to_report` is the whole number of UTC calendar days from the calendar date of `injury_datetime` to `reported_on_date`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."

    Design: Corner/validations/injury_one_minute_after_the_activity_ends_rejected_but_at_the_bell_accepted
    """
    bundle = setup_sanctioned_activity(
        league_overrides={
            "name": "Vaughn Baseball",
            "league_code": "VNB-127",
            "state_code": "ME",
            "governing_body_code": "USYSA",
            "contact_email": "admin@vnb.example",
        },
        policy_overrides=dict(BASEBALL_TERM_POLICY),
        participant_overrides={
            "first_name": "Nadia",
            "last_name": "Okonjo",
            "date_of_birth": "2014-12-26",
            "guardian_email": "g31@vnb.example",
        },
        activity_overrides={
            "activity_type": "GAME",
            "venue_name": "Vaughn Field 3",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID,
    )
    league_headers = make_league_admin_headers(bundle["league"]["id"])
    enrollment_id = bundle["enrollment"]["id"]
    activity_id = bundle["activity"]["id"]
    # The sport classification carries a 60-minute travel buffer, so 20:01 sits
    # inside the collision footprint but outside the coverage window.
    assert bundle["sport_classification"]["travel_buffer_minutes"] == 60
    set_clock("2026-07-12T00:00:00Z")

    after_the_bell = api.create_injury_report(
        create_injury_report_payload(
            enrollment_id,
            activity_id,
            injury_datetime="2026-07-11T20:01:00Z",
            body_part="SHOULDER_ARM",
            injury_description="shoulder injured packing up after the final out",
            severity_tier="MODERATE",
        ),
        league_headers,
    )
    validate_error(
        after_the_bell,
        ApiErrorId.ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW,
        expected_status=422,
    )

    at_the_bell = validate_success(
        api.create_injury_report(
            create_injury_report_payload(
                enrollment_id,
                activity_id,
                injury_datetime="2026-07-11T20:00:00Z",
                body_part="SHOULDER_ARM",
                injury_description="shoulder injured on the last throw of the game",
                severity_tier="MODERATE",
            ),
            league_headers,
        ),
        expected_status=201,
    )
    assert at_the_bell["status"] == "PENDING_VERIFICATION"
    assert at_the_bell["days_to_report"] == 1
    assert at_the_bell["correction_round_count"] == 0
    assert at_the_bell["verifying_official_id"] is None
    assert at_the_bell["verified_at"] is None
    assert at_the_bell["rejection_reason"] is None

    before_first_pitch = api.create_injury_report(
        create_injury_report_payload(
            enrollment_id,
            activity_id,
            injury_datetime="2026-07-11T17:59:00Z",
            body_part="SHOULDER_ARM",
            injury_description="shoulder tweaked during pre-game warmups",
            severity_tier="MODERATE",
        ),
        league_headers,
    )
    validate_error(
        before_first_pitch,
        ApiErrorId.ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW,
        expected_status=422,
    )

    rows, meta = validate_paginated(
        api.list_injury_reports(
            make_program_admin_headers(), {"sanctioned_activity_id": activity_id}
        )
    )
    assert meta["total_count"] == 1, "only the injury at exactly ends_at may be on file"
    assert [row["id"] for row in rows] == [at_the_bell["id"]]


def test_two_base_layer_payments_whose_sum_overdraws_the_layer_are_refused_at_the_second(api):
    """PRD §3.8: "The payment must not overdraw its own layer: for a `BASE` payment, the claim's `paid_base_cents` plus this amount must not exceed the frozen `base_layer_benefit_cents`, and for a `CATASTROPHIC` payment, `paid_cat_cents` plus this amount must not exceed the frozen `cat_layer_benefit_cents`."

    PRD §3.8: "Any of these is refused with `ERR_PAYMENT_EXCEEDS_BENEFIT`."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.8: "The claim's `paid_base_cents` (the sum of `ISSUED` `BASE`-layer amounts on the claim), `paid_cat_cents` (the same for the `CATASTROPHIC` layer) and `paid_to_date_cents` (their sum) are recomputed, and once `paid_to_date_cents` has reached or passed `benefit_payable_cents` the claim moves `APPROVED → PAID`, taking it out of the open set."

    Design: Corner/validations/second_payment_overdrawing_the_base_layer_rejected
    """
    policy_overrides = dict(BASEBALL_TERM_POLICY)
    policy_overrides["coverage_basis_election"] = "FULL_EXCESS_PERMITTED"
    bundle = setup_approved_full_excess_claim(
        league_overrides={
            "name": "Westmere Baseball",
            "league_code": "WMB-128",
            "state_code": "RI",
            "governing_body_code": "USYSA",
            "contact_email": "admin@wmb.example",
        },
        policy_overrides=policy_overrides,
        participant_overrides={
            "first_name": "Omar",
            "last_name": "Haddad",
            "date_of_birth": "2015-01-27",
            "guardian_email": "g32@wmb.example",
        },
        activity_overrides={
            "activity_type": "GAME",
            "venue_name": "Westmere Field 1",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        report_overrides={
            "injury_datetime": "2026-07-11T19:00:00Z",
            "body_part": "TORSO",
            "injury_description": "rib contusion from a collision at the plate",
            "severity_tier": "MODERATE",
        },
        bill_overrides={
            "provider_npi": "1033445566",
            "provider_name": "Westmere Regional ER",
            "network_status": "IN_NETWORK",
            "service_category": "EMERGENCY_ROOM",
            "service_date": "2026-07-11",
            "billed_charge_cents": 400000,
            "fee_schedule_amount_cents": 360000,
        },
    )
    claim_id = bundle["claim"]["id"]
    bill_id = bundle["provider_bill"]["id"]
    examiner_headers = make_claims_examiner_headers()

    # An in-network 400000 charge against a 360000 fee schedule allows 360000;
    # on the full-excess footing the 25000 deductible doubles to 50000.
    approved = read_claim(claim_id)
    assert approved["adjudication_status"] == "APPROVED"
    assert approved["coordination_basis"] == "FULL_EXCESS"
    assert approved["allowed_amount_total_cents"] == 360000
    assert approved["deductible_applied_cents"] == 50000
    assert approved["benefit_before_limit_cents"] == 310000
    assert approved["base_layer_benefit_cents"] == 310000
    assert approved["cat_layer_benefit_cents"] == 0
    assert approved["benefit_payable_cents"] == 310000

    first_payment = issue_benefit_payment(claim_id, bill_id, 300000, layer="BASE")
    assert first_payment["status"] == "ISSUED"
    assert read_claim(claim_id)["paid_base_cents"] == 300000

    # 300000 + 15000 overdraws the 310000 base layer even though 15000 alone is tiny.
    overdrawing = api.create_benefit_payment(
        create_benefit_payment_payload(claim_id, bill_id, 15000, layer="BASE"),
        examiner_headers,
    )
    validate_error(
        overdrawing, ApiErrorId.ERR_PAYMENT_EXCEEDS_BENEFIT, expected_status=422
    )

    # 300000 + 10000 lands exactly on the layer ceiling, which is inclusive.
    second_payment = validate_success(
        api.create_benefit_payment(
            create_benefit_payment_payload(claim_id, bill_id, 10000, layer="BASE"),
            examiner_headers,
        ),
        expected_status=201,
    )
    assert second_payment["status"] == "ISSUED"
    assert second_payment["amount_cents"] == 10000

    settled = read_claim(claim_id)
    assert settled["paid_base_cents"] == 310000
    assert settled["paid_cat_cents"] == 0
    assert settled["paid_to_date_cents"] == 310000
    assert settled["adjudication_status"] == "PAID"

    payments = payments_for_claim(claim_id)
    assert len(payments) == 2, "the refused 15000 payment must have left no row"
    assert sorted(payment["amount_cents"] for payment in payments) == [10000, 300000]


SWIM_TERM = {
    "term_effective_date": "2026-03-01",
    "term_expiration_date": "2027-03-01",
    "enrolled_participant_count": 40,
    "coverage_basis_election": "FULL_EXCESS_PERMITTED",
}
CATASTROPHIC_DIVE = "cervical spine injury on a racing dive into the shallow end"


def _swim_claim_piercing_the_attachment_point(
    league_overrides, sport_classification_id, cat_layer_elected, athlete_overrides, npi, provider_name
):
    """One swim league whose athlete's catastrophic claim clears the 500000
    attachment point by 140000 cents, settled onto the full-excess footing."""
    league = create_league(**league_overrides)
    policy = quote_policy(
        league["id"],
        sport_classification_id,
        cat_layer_elected=cat_layer_elected,
        **SWIM_TERM,
    )
    bind_policy(policy["id"])
    policy = activate_policy(policy["id"])
    athlete = add_participant(league["id"], **athlete_overrides)
    enrollment = enroll_participant(
        athlete["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    activity = schedule_activity(
        policy["id"],
        league["id"],
        activity_type="GAME",
        venue_name=f"{league_overrides['name']} Aquatic Center",
        starts_at="2026-07-11T14:00:00Z",
        ends_at="2026-07-11T17:00:00Z",
    )
    sanction_activity(activity["id"], SANCTIONING_OFFICIAL_USER_ID)
    return {
        "league": league,
        "policy": policy,
        "athlete": athlete,
        "enrollment": enrollment,
        "activity": activity,
        "npi": npi,
        "provider_name": provider_name,
    }


def _settle_swim_claim_on_the_full_excess_footing(side):
    report = file_injury_report(
        side["enrollment"]["id"],
        side["activity"]["id"],
        side["league"]["id"],
        injury_datetime="2026-07-11T15:30:00Z",
        body_part="HEAD_NECK",
        injury_description=CATASTROPHIC_DIVE,
        severity_tier="CATASTROPHIC",
    )
    verify_injury_report(
        report["id"], VERIFYING_OFFICIAL_USER_ID, "meet referee witnessed the dive"
    )
    claim = discover_claim(report["id"])
    bill = record_provider_bill(
        claim["id"],
        provider_npi=side["npi"],
        provider_name=side["provider_name"],
        network_status="IN_NETWORK",
        service_category="SURGERY",
        service_date="2026-07-11",
        billed_charge_cents=700000,
        fee_schedule_amount_cents=660000,
    )
    reprice_bill(bill["id"])
    confirm_no_other_coverage(claim["id"])
    side["injury_report"] = report
    side["claim"] = claim
    side["provider_bill"] = bill
    return side


def test_adjudication_demands_catastrophic_certification_only_on_the_electing_policy(api):
    """PRD §3.8: "It reaches `UNDER_ADJUDICATION → APPROVED` when the athlete's enrollment `status` is `ENROLLED` and `benefit_payable_cents` is at least one cent, and when the determination does not reach into the catastrophic layer without certification: where the policy's `cat_layer_elected` is true and `benefit_before_limit_cents` exceeds the policy's `cat_attachment_point_cents`, the claim's `cat_certification_status` must be `CERTIFIED`, and otherwise the adjudication is refused with `ERR_CAT_CERTIFICATION_REQUIRED` rather than quietly paying the base layer alone."

    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`."
    PRD §3.7: "If either condition fails, `cat_layer_benefit_cents` is exactly zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "A reviewer certifies by supplying a `certification_note`, which moves the claim's `cat_certification_status` from `NONE` to `CERTIFIED`, stamps `cat_certified_at` with the logical clock and `cat_certified_by_user_id` with the reviewer's `X-User-ID`, stores the note as `cat_certification_note`, and recomputes the benefit determination — which is what can lift `cat_layer_benefit_cents` above zero for the first time."

    Design: Corner/validations/catastrophic_certification_required_only_when_the_cat_layer_is_elected
    """
    set_clock("2026-03-05T00:00:00Z")
    sport = create_sport_classification("swim", cat_lifetime_max_cents=800000)
    assert sport["per_injury_limit_cents"] == 500000
    assert sport["cat_attachment_point_cents"] == 500000
    assert sport["deductible_cents"] == 10000
    assert sport["service_category_caps"]["SURGERY"] == 600000

    electing = _swim_claim_piercing_the_attachment_point(
        {
            "name": "Ashgrove Swim Club",
            "league_code": "AGS-129",
            "state_code": "OR",
            "governing_body_code": "USAS",
            "contact_email": "admin@ags.example",
        },
        sport["id"],
        True,
        {
            "first_name": "Priya",
            "last_name": "Raghavan",
            "date_of_birth": "2013-02-14",
            "guardian_email": "g33@ags.example",
        },
        "1144556677",
        "Ashgrove Orthopedic Surgery",
    )
    non_electing = _swim_claim_piercing_the_attachment_point(
        {
            "name": "Bellamy Swim Club",
            "league_code": "BLS-130",
            "state_code": "OR",
            "governing_body_code": "USAS",
            "contact_email": "admin@bls.example",
        },
        sport["id"],
        False,
        {
            "first_name": "Quentin",
            "last_name": "Boisvert",
            "date_of_birth": "2013-03-15",
            "guardian_email": "g34@bls.example",
        },
        "1155667788",
        "Bellamy Orthopedic Surgery",
    )
    set_clock("2026-07-12T00:00:00Z")
    _settle_swim_claim_on_the_full_excess_footing(electing)
    _settle_swim_claim_on_the_full_excess_footing(non_electing)

    examiner_headers = make_claims_examiner_headers()
    electing_claim_id = electing["claim"]["id"]
    non_electing_claim_id = non_electing["claim"]["id"]

    # Both determinations are identical: 660000 allowed, a doubled 20000 deductible
    # and 640000 before the limit, which is 140000 above the 500000 attachment point.
    for claim_id in (electing_claim_id, non_electing_claim_id):
        pre = read_claim(claim_id)
        assert pre["allowed_amount_total_cents"] == 660000
        assert pre["deductible_applied_cents"] == 20000
        assert pre["benefit_before_limit_cents"] == 640000
        assert pre["adjudication_status"] == "UNDER_ADJUDICATION"

    refused = api.adjudicate_claim(
        electing_claim_id,
        {"examiner_note": "catastrophic dive injury on the electing policy"},
        examiner_headers,
    )
    validate_error(
        refused, ApiErrorId.ERR_CAT_CERTIFICATION_REQUIRED, expected_status=422
    )

    approved_without_the_layer = validate_success(
        api.adjudicate_claim(
            non_electing_claim_id,
            {"examiner_note": "catastrophic dive injury on the non-electing policy"},
            examiner_headers,
        ),
        expected_status=200,
    )
    assert approved_without_the_layer["adjudication_status"] == "APPROVED"
    assert approved_without_the_layer["base_layer_benefit_cents"] == 500000
    assert approved_without_the_layer["cat_layer_benefit_cents"] == 0
    assert approved_without_the_layer["benefit_payable_cents"] == 500000

    certified = validate_success(
        api.certify_catastrophic(
            electing_claim_id,
            {
                "certification_note": "board-certified neurosurgeon confirms permanent impairment"
            },
            make_medical_reviewer_headers(),
        ),
        expected_status=200,
    )
    assert certified["cat_certification_status"] == "CERTIFIED"

    approved_with_the_layer = validate_success(
        api.adjudicate_claim(
            electing_claim_id,
            {"examiner_note": "re-adjudicating now that certification is on file"},
            examiner_headers,
        ),
        expected_status=200,
    )
    assert approved_with_the_layer["adjudication_status"] == "APPROVED"
    assert approved_with_the_layer["base_layer_benefit_cents"] == 500000
    assert approved_with_the_layer["cat_layer_benefit_cents"] == 140000
    assert approved_with_the_layer["benefit_payable_cents"] == 640000


def test_bind_reports_the_term_overlap_ahead_of_the_undersized_head_count(api):
    """PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."

    PRD §2.7: "28. through 37. **Business constraints** — in order: no overlapping in-force term for the same league and sport (`ERR_POLICY_TERM_OVERLAP`); no per-athlete activity collision (`ERR_PARTICIPANT_ACTIVITY_CONFLICT`); no duplicate active enrollment (`ERR_DUPLICATE_ENROLLMENT`); correction rounds not exhausted (`ERR_CORRECTION_ROUNDS_EXHAUSTED`); the service category is on the benefit schedule (`ERR_SERVICE_CATEGORY_NOT_SCHEDULED`); league and sport codes unique (`ERR_DUPLICATE_LEAGUE_CODE`, `ERR_DUPLICATE_SPORT_CODE`); no other coverage on file when none is being attested (`ERR_OTHER_COVERAGE_ON_FILE`); the policy permits a full-excess footing (`ERR_FULL_EXCESS_NOT_PERMITTED`); some other coverage exists when an explanation of benefits is requested (`ERR_NO_OTHER_COVERAGE_ON_FILE`); and no issued payment stands in the way of a void or withdrawal (`ERR_PAYMENT_ON_FILE`)."
    PRD §2.7: "38. through 42. **Fiscal limits** — last of all, in order: the declared head count meets the sport's minimum (`ERR_MINIMUM_PARTICIPANTS_NOT_MET`); the enrollment's lifetime catastrophic benefit is not exhausted (`ERR_LIFETIME_BENEFIT_EXHAUSTED`); nothing being closed out still carries an open claim (`ERR_OPEN_CLAIMS_ON_ENROLLMENT`, `ERR_OPEN_CLAIMS_ON_POLICY`); the payment does not overdraw its layer (`ERR_PAYMENT_EXCEEDS_BENEFIT`); and the payment does not breach the term aggregate (`ERR_AGGREGATE_LIMIT_EXCEEDED`)."
    PRD §3.2: "Binding requires the policy to be in `QUOTED`, the holding league to be `SANCTIONED` (otherwise `ERR_LEAGUE_NOT_SANCTIONED`), the declared `enrolled_participant_count` to be at least the sport's `minimum_participants` (otherwise `ERR_MINIMUM_PARTICIPANTS_NOT_MET`), and no other policy for the same league-and-sport pairing whose `status` is `BOUND`, `ACTIVE` or `RUN_OFF` to hold a term intersecting this one (otherwise `ERR_POLICY_TERM_OVERLAP`)."
    PRD §2.11: "Two terms that merely touch — one term's expiration date equal to the next term's effective date — do not overlap, and both may be bound."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §3.1: "That count is derived, not stored input: at any moment it is the number of policy terms held by this league whose lifecycle `status` is `BOUND`, `ACTIVE` or `RUN_OFF`."

    Design: Corner/validations/bind_reports_term_overlap_before_minimum_participants
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Yarrow Baseball",
            "league_code": "YRB-131",
            "state_code": "IA",
            "governing_body_code": "USYSA",
            "contact_email": "admin@yrb.example",
        },
        policy_overrides=dict(BASEBALL_TERM_POLICY),
    )
    league_id = bundle["league"]["id"]
    sport_id = bundle["sport_classification"]["id"]
    assert bundle["sport_classification"]["minimum_participants"] == 25
    assert bundle["policy"]["status"] == "ACTIVE"

    # Ten athletes is below the floor of 25 on both quotes; only the first quote's
    # term also intersects the live term.
    overlapping = quote_policy(
        league_id,
        sport_id,
        term_effective_date="2026-06-01",
        term_expiration_date="2027-06-01",
        enrolled_participant_count=10,
        coverage_basis_election="EXCESS_ONLY",
        cat_layer_elected=False,
    )
    abutting = quote_policy(
        league_id,
        sport_id,
        term_effective_date="2027-03-01",
        term_expiration_date="2028-03-01",
        enrolled_participant_count=10,
        coverage_basis_election="EXCESS_ONLY",
        cat_layer_elected=False,
    )
    admin_headers = make_program_admin_headers()

    both_broken = api.bind_league_policy(overlapping["id"], admin_headers)
    validate_error(both_broken, ApiErrorId.ERR_POLICY_TERM_OVERLAP, expected_status=409)

    only_the_floor_broken = api.bind_league_policy(abutting["id"], admin_headers)
    validate_error(
        only_the_floor_broken,
        ApiErrorId.ERR_MINIMUM_PARTICIPANTS_NOT_MET,
        expected_status=422,
    )

    for refused in (overlapping, abutting):
        unchanged = read_policy(refused["id"])
        assert unchanged["status"] == "QUOTED"
        assert unchanged["version"] == 1

    assert read_league(league_id)["in_force_policy_count"] == 1

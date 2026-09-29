"""Precedence between competing rungs of the rule evaluation ladder.

A single injury filing can break more than one rule at once, and which rejection
the league sees is part of the contract rather than an implementation detail. Two
pairings are exercised here. A frozen term that is also being filed against long
after the ninety-day window must answer with the freeze, one rung class earlier
than any temporal window; and a filing against the team barbecue for an athlete
whose lifetime catastrophic benefit is already spent must answer with the
coverage-safety failure, many rungs before the fiscal limit is reached. In each
pairing a control filing proves the lower-ranked rule is genuinely live rather
than merely unimplemented.
"""
from test_helpers import (
    ApiErrorId,
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    activate_policy,
    add_participant,
    adjudicate_claim,
    bind_policy,
    certify_catastrophic,
    confirm_no_other_coverage,
    create_injury_report_payload,
    create_league,
    create_sport_classification,
    discover_claim,
    enroll_participant,
    file_injury_report,
    issue_benefit_payment,
    make_league_admin_headers,
    quote_policy,
    read_enrollment,
    read_policy,
    record_provider_bill,
    reports_for_enrollment,
    reprice_bill,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_enrolled_athlete,
    validate_error,
    verify_injury_report,
)


def _build_frozen_and_open_cheer_terms():
    """Two allstar cheer terms on one small-aggregate classification.

    The first term carries a verified catastrophic claim whose case reserve alone
    exceeds the term aggregate, so its operating posture reads FROZEN while its
    lifecycle status is still ACTIVE. The second term is identical but claim-free,
    so its posture reads OPEN. Both hold a sanctioned game on 2026-04-10 and the
    logical clock is left at 2026-07-12, ninety-three days later.
    """
    set_clock("2026-03-05T00:00:00Z")
    frozen_league = create_league(
        name="Summit Allstar Cheer",
        league_code="SAC-010",
        state_code="OH",
        governing_body_code="USASF",
        contact_email="admin@sac.example",
    )
    open_league = create_league(
        name="Valley Spirit Cheer",
        league_code="VSC-010",
        state_code="OH",
        governing_body_code="USASF",
        contact_email="admin@vsc.example",
    )
    sport = create_sport_classification("cheer")

    frozen_policy = quote_policy(
        frozen_league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=30,
        coverage_basis_election="EXCESS_ONLY",
        cat_layer_elected=True,
    )
    bind_policy(frozen_policy["id"])
    activate_policy(frozen_policy["id"])

    open_policy = quote_policy(
        open_league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=30,
        coverage_basis_election="EXCESS_ONLY",
        cat_layer_elected=True,
    )
    bind_policy(open_policy["id"])
    activate_policy(open_policy["id"])

    frozen_athlete = add_participant(
        frozen_league["id"],
        first_name="Ines",
        last_name="Vargas",
        date_of_birth="2014-07-07",
        guardian_email="g9@sac.example",
    )
    frozen_enrollment = enroll_participant(
        frozen_athlete["id"],
        frozen_policy["id"],
        frozen_league["id"],
        enrolled_on_date="2026-03-05",
    )
    open_athlete = add_participant(
        open_league["id"],
        first_name="Jonah",
        last_name="Petrov",
        date_of_birth="2014-03-18",
        guardian_email="g10@vsc.example",
    )
    open_enrollment = enroll_participant(
        open_athlete["id"],
        open_policy["id"],
        open_league["id"],
        enrolled_on_date="2026-03-05",
    )

    # The practice whose catastrophic claim drives the first term's aggregate.
    freezing_practice = schedule_activity(
        frozen_policy["id"],
        frozen_league["id"],
        activity_type="PRACTICE",
        venue_name="Summit Gym A",
        starts_at="2026-03-10T18:00:00Z",
        ends_at="2026-03-10T20:00:00Z",
    )
    sanction_activity(freezing_practice["id"], SANCTIONING_OFFICIAL_USER_ID)
    frozen_game = schedule_activity(
        frozen_policy["id"],
        frozen_league["id"],
        activity_type="GAME",
        venue_name="Buckeye Regional Arena",
        starts_at="2026-04-10T18:00:00Z",
        ends_at="2026-04-10T20:00:00Z",
    )
    sanction_activity(frozen_game["id"], SANCTIONING_OFFICIAL_USER_ID)
    open_game = schedule_activity(
        open_policy["id"],
        open_league["id"],
        activity_type="GAME",
        venue_name="Buckeye Regional Arena",
        starts_at="2026-04-10T18:00:00Z",
        ends_at="2026-04-10T20:00:00Z",
    )
    sanction_activity(open_game["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-03-11T00:00:00Z")
    catastrophic_report = file_injury_report(
        frozen_enrollment["id"],
        freezing_practice["id"],
        frozen_league["id"],
        injury_datetime="2026-03-10T19:00:00Z",
        body_part="HEAD_NECK",
        injury_description="fell from pyramid apex, cervical injury with neurological deficit",
        severity_tier="CATASTROPHIC",
    )
    verify_injury_report(
        catastrophic_report["id"],
        VERIFYING_OFFICIAL_USER_ID,
        "two coaches witnessed the fall",
    )

    set_clock("2026-07-12T00:00:00Z")
    return {
        "frozen_league": frozen_league,
        "open_league": open_league,
        "frozen_policy": frozen_policy,
        "open_policy": open_policy,
        "frozen_enrollment": frozen_enrollment,
        "open_enrollment": open_enrollment,
        "frozen_game": frozen_game,
        "open_game": open_game,
        "catastrophic_report": catastrophic_report,
    }


def test_late_filing_on_a_frozen_cheer_term_is_refused_for_the_freeze_not_the_filing_window(api):
    """PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "11. **Policy not frozen** — the governing policy's operating posture is not `FROZEN` (`ERR_POLICY_FROZEN`)."
    PRD §2.7: "20. through 27. **Temporal windows** — in order: the injury instant lies inside the activity window (`ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW`); the filing window has not expired (`ERR_FILING_WINDOW_EXPIRED`); the verification window has not expired (`ERR_VERIFICATION_WINDOW_EXPIRED`); the activity lies inside the policy term (`ERR_ACTIVITY_OUTSIDE_TERM`); the enrollment date lies inside the term (`ERR_ENROLLMENT_OUTSIDE_TERM`); the service date lies inside the term (`ERR_SERVICE_DATE_OUTSIDE_TERM`); term and renewal dates are ordered correctly (`ERR_TERM_DATES_INVALID`); and coordination has reached a settled position (`ERR_COORDINATION_INCOMPLETE`)."
    PRD §2.7: "A frozen policy's rejection surfaces before any temporal window is examined."
    PRD §2.8: "So `ERR_POLICY_FROZEN` can arise from enrolling an athlete, scheduling an activity, taking a sanction decision, filing an injury report, resubmitting one, taking a verification decision, recording a provider bill, repricing one, filing a coordination record, requesting an explanation of benefits, confirming no other coverage, adjudicating a claim, issuing a benefit payment or quoting a renewal."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "The test is inclusive: an incurred loss exactly equal to the aggregate limit freezes the term."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.5: "The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/policy_frozen_state_check_outranks_filing_window_temporal_check
    """
    terms = _build_frozen_and_open_cheer_terms()

    # The catastrophic reserve is capped at the term's exposure for one injury:
    # 300000 per-injury limit plus the 600000 elected lifetime maximum is 900000,
    # smaller than the 7500000 standard catastrophic reserve, and that alone has
    # reached the 500000 term aggregate.
    frozen_policy = read_policy(terms["frozen_policy"]["id"])
    assert frozen_policy["incurred_loss_cents"] == 900000, (
        "the verified catastrophic claim reserves 900000 cents of incurred loss, got "
        f"{frozen_policy['incurred_loss_cents']}"
    )
    assert frozen_policy["status"] == "ACTIVE", (
        f"the term's lifecycle status stays ACTIVE, got {frozen_policy['status']}"
    )
    assert frozen_policy["coverage_posture"] == "FROZEN", (
        "an incurred loss of 900000 cents against a 500000 aggregate limit freezes "
        f"the posture, got {frozen_policy['coverage_posture']}"
    )

    # 2026-04-10 to the 2026-07-12 clock is 93 calendar days, so the ninety-day
    # filing window is also broken by this very same request.
    response = api.create_injury_report(
        create_injury_report_payload(
            terms["frozen_enrollment"]["id"],
            terms["frozen_game"]["id"],
            injury_datetime="2026-04-10T19:00:00Z",
            body_part="ANKLE_FOOT",
            injury_description="landed awkwardly out of a basket toss",
            severity_tier="MODERATE",
        ),
        make_league_admin_headers(terms["frozen_league"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_POLICY_FROZEN, expected_status=409)


def test_late_filing_on_an_unfrozen_cheer_term_is_refused_for_the_expired_filing_window(api):
    """PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "11. **Policy not frozen** — the governing policy's operating posture is not `FROZEN` (`ERR_POLICY_FROZEN`)."
    PRD §2.7: "20. through 27. **Temporal windows** — in order: the injury instant lies inside the activity window (`ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW`); the filing window has not expired (`ERR_FILING_WINDOW_EXPIRED`); the verification window has not expired (`ERR_VERIFICATION_WINDOW_EXPIRED`); the activity lies inside the policy term (`ERR_ACTIVITY_OUTSIDE_TERM`); the enrollment date lies inside the term (`ERR_ENROLLMENT_OUTSIDE_TERM`); the service date lies inside the term (`ERR_SERVICE_DATE_OUTSIDE_TERM`); term and renewal dates are ordered correctly (`ERR_TERM_DATES_INVALID`); and coordination has reached a settled position (`ERR_COORDINATION_INCOMPLETE`)."
    PRD §2.8: "6. Failing all of them, the posture is `OPEN`."
    PRD §3.5: "`days_to_report` is the whole number of UTC calendar days from the calendar date of `injury_datetime` to `reported_on_date`."
    PRD §3.5: "The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`."
    PRD §2.11: "Each window is inclusive of the stated day count: a count equal to the limit is still inside the window, and only the first day beyond it is late."

    Design: Difficulty/priority_pair_validation_conflict/policy_frozen_state_check_outranks_filing_window_temporal_check
    """
    terms = _build_frozen_and_open_cheer_terms()

    # The control term carries no claim at all, so nothing has reached its
    # aggregate limit and the frozen rung cannot fire on this filing.
    open_policy = read_policy(terms["open_policy"]["id"])
    assert open_policy["incurred_loss_cents"] == 0, (
        "the claim-free control term carries no incurred loss, got "
        f"{open_policy['incurred_loss_cents']}"
    )
    assert open_policy["coverage_posture"] == "OPEN", (
        f"the claim-free control term reads OPEN, got {open_policy['coverage_posture']}"
    )

    # Identical filing, identical 93-day lateness, unfrozen term: the temporal
    # rung is reached and answers instead of the frozen rung.
    response = api.create_injury_report(
        create_injury_report_payload(
            terms["open_enrollment"]["id"],
            terms["open_game"]["id"],
            injury_datetime="2026-04-10T19:00:00Z",
            body_part="ANKLE_FOOT",
            injury_description="landed awkwardly out of a basket toss",
            severity_tier="MODERATE",
        ),
        make_league_admin_headers(terms["open_league"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FILING_WINDOW_EXPIRED, expected_status=422)


def test_late_filing_refused_on_the_unfrozen_cheer_term_leaves_the_enrollment_with_no_report(api):
    """PRD §3.5: "The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §2.3: "Injury reports may be filtered by `enrollment_id`, `sanctioned_activity_id`, `status` and `severity_tier`."

    Design: Difficulty/priority_pair_validation_conflict/policy_frozen_state_check_outranks_filing_window_temporal_check
    """
    terms = _build_frozen_and_open_cheer_terms()

    response = api.create_injury_report(
        create_injury_report_payload(
            terms["open_enrollment"]["id"],
            terms["open_game"]["id"],
            injury_datetime="2026-04-10T19:00:00Z",
            body_part="ANKLE_FOOT",
            injury_description="landed awkwardly out of a basket toss",
            severity_tier="MODERATE",
        ),
        make_league_admin_headers(terms["open_league"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FILING_WINDOW_EXPIRED, expected_status=422)

    # A refused filing writes no report row at all.
    control_reports = reports_for_enrollment(terms["open_enrollment"]["id"])
    assert control_reports == [], (
        "the refused late filing must leave the control enrollment with no injury "
        f"report, got {len(control_reports)} row(s)"
    )

    # The frozen term's own enrollment still carries only the report that opened
    # the catastrophic claim during setup.
    frozen_reports = reports_for_enrollment(terms["frozen_enrollment"]["id"])
    assert [row["id"] for row in frozen_reports] == [
        terms["catastrophic_report"]["id"]
    ], (
        "only the pre-existing catastrophic report stands on the frozen term's "
        f"enrollment, got {[row['id'] for row in frozen_reports]}"
    )


def _build_exhausted_swim_athlete():
    """One swim term whose athlete has spent the whole catastrophic lifetime max.

    The classification's `cat_lifetime_max_cents` is 100000, and a single ISSUED
    catastrophic payment of exactly that amount exhausts the enrollment. The term
    then holds two further activities: a team social on 2026-10-15 that is not a
    covered activity type, and a sanctioned practice on 2026-11-12 that is. The
    logical clock is left at 2026-11-13, inside the ninety-day filing window for
    both of them.
    """
    bundle = setup_enrolled_athlete(
        classification="swim",
        clock="2026-03-05T00:00:00Z",
        league_overrides={
            "name": "Lakeshore Swim Club",
            "league_code": "LSC-020",
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
            "first_name": "Kai",
            "last_name": "Lindqvist",
            "date_of_birth": "2012-12-01",
            "guardian_email": "g11@lsc.example",
        },
        enrollment_overrides={"enrolled_on_date": "2026-03-05"},
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]
    enrollment_id = bundle["enrollment"]["id"]

    catastrophic_practice = schedule_activity(
        policy_id,
        league_id,
        activity_type="PRACTICE",
        venue_name="Lakeshore Natatorium",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )
    sanction_activity(catastrophic_practice["id"], SANCTIONING_OFFICIAL_USER_ID)
    team_social = schedule_activity(
        policy_id,
        league_id,
        activity_type="TEAM_SOCIAL",
        venue_name="Team Pizza Night",
        starts_at="2026-10-15T18:00:00Z",
        ends_at="2026-10-15T20:00:00Z",
    )
    covered_practice = schedule_activity(
        policy_id,
        league_id,
        activity_type="PRACTICE",
        venue_name="Lakeshore Natatorium",
        starts_at="2026-11-12T18:00:00Z",
        ends_at="2026-11-12T20:00:00Z",
    )
    sanction_activity(covered_practice["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")
    report = file_injury_report(
        enrollment_id,
        catastrophic_practice["id"],
        league_id,
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="HEAD_NECK",
        injury_description="shallow-end dive, cervical fracture with cord involvement",
        severity_tier="CATASTROPHIC",
    )
    verify_injury_report(
        report["id"],
        VERIFYING_OFFICIAL_USER_ID,
        "meet referee and two lifeguards witnessed",
    )
    claim = discover_claim(report["id"])

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
    reprice_bill(bill["id"])
    confirm_no_other_coverage(
        claim["id"],
        "guardian attests the family carries no other health coverage",
    )
    certify_catastrophic(
        claim["id"],
        "permanent neurological deficit documented by treating neurosurgeon",
    )
    adjudicate_claim(
        claim["id"],
        "covered PRACTICE activity, program primary, catastrophic layer certified",
    )
    issue_benefit_payment(
        claim["id"], bill["id"], 100000, layer="CATASTROPHIC", payee_type="PROVIDER"
    )

    set_clock("2026-11-13T00:00:00Z")
    return {
        "league": bundle["league"],
        "policy": bundle["policy"],
        "enrollment": bundle["enrollment"],
        "injury_report": report,
        "team_social": team_social,
        "covered_practice": covered_practice,
    }


def test_team_social_filing_for_an_exhausted_swim_athlete_is_refused_as_an_uncovered_activity(api):
    """PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "15. through 19. **Coverage safety** — the activity is a covered type (`ERR_ACTIVITY_NOT_COVERED`); the activity's sanctioning state permits the operation (`ERR_ACTIVITY_NOT_SANCTIONED`); the acting official is not the one who sanctioned the activity (`ERR_OFFICIAL_SEGREGATION_VIOLATION`); catastrophic certification is only touched on a catastrophic-severity injury (`ERR_SEVERITY_NOT_CATASTROPHIC`); and a determination that reaches into the catastrophic layer requires certification first (`ERR_CAT_CERTIFICATION_REQUIRED`), in exactly that order."
    PRD §2.7: "38. through 42. **Fiscal limits** — last of all, in order: the declared head count meets the sport's minimum (`ERR_MINIMUM_PARTICIPANTS_NOT_MET`); the enrollment's lifetime catastrophic benefit is not exhausted (`ERR_LIFETIME_BENEFIT_EXHAUSTED`); nothing being closed out still carries an open claim (`ERR_OPEN_CLAIMS_ON_ENROLLMENT`, `ERR_OPEN_CLAIMS_ON_POLICY`); the payment does not overdraw its layer (`ERR_PAYMENT_EXCEEDS_BENEFIT`); and the payment does not breach the term aggregate (`ERR_AGGREGATE_LIMIT_EXCEEDED`)."
    PRD §2.7: "The practical consequence worth internalising is that **authorisation outranks existence, existence outranks state, state outranks safety, safety outranks time, time outranks constraints, and constraints outrank money**."
    PRD §3.4: "Only the first four are covered activities, and the boolean `is_covered_activity` is computed from the type on this basis — true for a practice, a game, sanctioned travel or a tryout, and false for a team social."
    PRD §3.5: "The activity must be a covered type, so a report against a team social is refused with `ERR_ACTIVITY_NOT_COVERED`."
    PRD §3.3: "Otherwise, if `lifetime_cat_benefit_used_cents` has reached or passed the governing policy's `cat_lifetime_max_cents`, the coverage status is `LIFETIME_EXHAUSTED` — the test is inclusive, so paying out exactly the lifetime maximum exhausts the athlete."
    PRD §3.8: "Caused by that alone, the athlete's `lifetime_cat_benefit_used_cents` is re-accumulated — it is the sum of `amount_cents` over every `ISSUED` payment on the `CATASTROPHIC` layer across **every** claim of that enrollment, regardless of those claims' adjudication statuses — and the enrollment's `coverage_status` may flip to `LIFETIME_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/activity_not_covered_safety_check_outranks_lifetime_exhausted_fiscal_check
    """
    swim = _build_exhausted_swim_athlete()

    # The single issued catastrophic payment of 100000 cents is exactly the swim
    # classification's lifetime maximum, so the athlete is exhausted.
    enrollment = read_enrollment(swim["enrollment"]["id"])
    assert enrollment["lifetime_cat_benefit_used_cents"] == 100000, (
        "the issued catastrophic payment accumulates 100000 cents of lifetime usage, "
        f"got {enrollment['lifetime_cat_benefit_used_cents']}"
    )
    assert enrollment["coverage_status"] == "LIFETIME_EXHAUSTED", (
        "usage equal to the 100000 lifetime maximum exhausts the athlete, got "
        f"{enrollment['coverage_status']}"
    )
    assert swim["team_social"]["is_covered_activity"] is False, (
        "a TEAM_SOCIAL is not a covered activity, got "
        f"{swim['team_social']['is_covered_activity']}"
    )

    # Both the coverage-safety rung and the fiscal rung are violated by this one
    # filing, and both errors carry HTTP 422, so only the error id discriminates.
    response = api.create_injury_report(
        create_injury_report_payload(
            swim["enrollment"]["id"],
            swim["team_social"]["id"],
            injury_datetime="2026-10-15T19:00:00Z",
            body_part="DENTAL",
            injury_description="chipped tooth at the team pizza night",
            severity_tier="MINOR",
        ),
        make_league_admin_headers(swim["league"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ACTIVITY_NOT_COVERED, expected_status=422)


def test_covered_practice_filing_for_an_exhausted_swim_athlete_is_refused_for_the_spent_lifetime_benefit(api):
    """PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "15. through 19. **Coverage safety** — the activity is a covered type (`ERR_ACTIVITY_NOT_COVERED`); the activity's sanctioning state permits the operation (`ERR_ACTIVITY_NOT_SANCTIONED`); the acting official is not the one who sanctioned the activity (`ERR_OFFICIAL_SEGREGATION_VIOLATION`); catastrophic certification is only touched on a catastrophic-severity injury (`ERR_SEVERITY_NOT_CATASTROPHIC`); and a determination that reaches into the catastrophic layer requires certification first (`ERR_CAT_CERTIFICATION_REQUIRED`), in exactly that order."
    PRD §2.7: "38. through 42. **Fiscal limits** — last of all, in order: the declared head count meets the sport's minimum (`ERR_MINIMUM_PARTICIPANTS_NOT_MET`); the enrollment's lifetime catastrophic benefit is not exhausted (`ERR_LIFETIME_BENEFIT_EXHAUSTED`); nothing being closed out still carries an open claim (`ERR_OPEN_CLAIMS_ON_ENROLLMENT`, `ERR_OPEN_CLAIMS_ON_POLICY`); the payment does not overdraw its layer (`ERR_PAYMENT_EXCEEDS_BENEFIT`); and the payment does not breach the term aggregate (`ERR_AGGREGATE_LIMIT_EXCEEDED`)."
    PRD §3.4: "Only the first four are covered activities, and the boolean `is_covered_activity` is computed from the type on this basis — true for a practice, a game, sanctioned travel or a tryout, and false for a team social."
    PRD §3.5: "And the athlete's enrollment must not have run out of lifetime catastrophic benefit; a `coverage_status` of `LIFETIME_EXHAUSTED` refuses the filing with `ERR_LIFETIME_BENEFIT_EXHAUSTED`."
    PRD §3.5: "The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/activity_not_covered_safety_check_outranks_lifetime_exhausted_fiscal_check
    """
    swim = _build_exhausted_swim_athlete()

    assert swim["covered_practice"]["is_covered_activity"] is True, (
        "a PRACTICE is a covered activity, got "
        f"{swim['covered_practice']['is_covered_activity']}"
    )
    enrollment = read_enrollment(swim["enrollment"]["id"])
    assert enrollment["coverage_status"] == "LIFETIME_EXHAUSTED", (
        "the athlete's lifetime catastrophic benefit is spent, got "
        f"{enrollment['coverage_status']}"
    )

    # The coverage-safety rung is satisfied here and the filing is one day old, so
    # the fiscal rung is reached and proves it is live.
    response = api.create_injury_report(
        create_injury_report_payload(
            swim["enrollment"]["id"],
            swim["covered_practice"]["id"],
            injury_datetime="2026-11-12T19:00:00Z",
            body_part="SHOULDER_ARM",
            injury_description="shoulder impingement during butterfly set",
            severity_tier="MINOR",
        ),
        make_league_admin_headers(swim["league"]["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_LIFETIME_BENEFIT_EXHAUSTED, expected_status=422
    )


def test_both_refused_filings_leave_only_the_verified_report_on_the_exhausted_swim_enrollment(api):
    """PRD §3.5: "The activity must be a covered type, so a report against a team social is refused with `ERR_ACTIVITY_NOT_COVERED`."
    PRD §3.5: "And the athlete's enrollment must not have run out of lifetime catastrophic benefit; a `coverage_status` of `LIFETIME_EXHAUSTED` refuses the filing with `ERR_LIFETIME_BENEFIT_EXHAUSTED`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §2.3: "Injury reports may be filtered by `enrollment_id`, `sanctioned_activity_id`, `status` and `severity_tier`."

    Design: Difficulty/priority_pair_validation_conflict/activity_not_covered_safety_check_outranks_lifetime_exhausted_fiscal_check
    """
    swim = _build_exhausted_swim_athlete()

    uncovered = api.create_injury_report(
        create_injury_report_payload(
            swim["enrollment"]["id"],
            swim["team_social"]["id"],
            injury_datetime="2026-10-15T19:00:00Z",
            body_part="DENTAL",
            injury_description="chipped tooth at the team pizza night",
            severity_tier="MINOR",
        ),
        make_league_admin_headers(swim["league"]["id"]),
    )
    validate_error(uncovered, ApiErrorId.ERR_ACTIVITY_NOT_COVERED, expected_status=422)

    exhausted = api.create_injury_report(
        create_injury_report_payload(
            swim["enrollment"]["id"],
            swim["covered_practice"]["id"],
            injury_datetime="2026-11-12T19:00:00Z",
            body_part="SHOULDER_ARM",
            injury_description="shoulder impingement during butterfly set",
            severity_tier="MINOR",
        ),
        make_league_admin_headers(swim["league"]["id"]),
    )
    validate_error(
        exhausted, ApiErrorId.ERR_LIFETIME_BENEFIT_EXHAUSTED, expected_status=422
    )

    # Neither refusal wrote a report row: only the catastrophic report that opened
    # the paid claim during setup stands on this enrollment.
    rows = reports_for_enrollment(swim["enrollment"]["id"])
    assert [row["id"] for row in rows] == [swim["injury_report"]["id"]], (
        "the two refused filings must create nothing, leaving exactly the verified "
        f"catastrophic report on file, got {[row['id'] for row in rows]}"
    )
    assert rows[0]["status"] == "VERIFIED", (
        f"the surviving report is the VERIFIED one, got {rows[0]['status']}"
    )

"""Every refusal the program owes a caller, named precisely.

The accident program refuses a great many requests, and the whole value of the
error catalogue is that each refusal names the thing that actually blocked it: the
league code that was already taken rather than a generic conflict, the entity
whose identifier failed to resolve rather than a shared not-found, the artifact
whose own state was wrong rather than its parent's, and the issued cheque that
stands in the way of a void rather than the state the void was allowed from.
These tests walk the coordination entry points, the benefit-schedule and
certification gates, the verification window, the identity headers, the repeat
actions on settled paperwork, the enrollment and family-plan lifecycles, the
term-boundary refusals and the term aggregate ceiling, asserting the exact
error_id and the exact HTTP status of each, and asserting that the refused write
left nothing behind.
"""
from test_helpers import (
    ApiErrorId,
    BASEBALL_U12_CAPS,
    CLAIMS_EXAMINER_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    activate_policy,
    activities_for_policy,
    add_family_health_plan,
    add_participant,
    adjudicate_claim,
    bills_for_claim,
    bind_policy,
    build_user_headers,
    canonical_iso,
    confirm_no_other_coverage,
    create_benefit_payment_payload,
    create_enrollment_payload,
    create_family_health_plan_payload,
    create_injury_report_payload,
    create_league,
    create_league_payload,
    create_league_policy_payload,
    create_participant_payload,
    create_provider_bill_payload,
    create_sanctioned_activity_payload,
    create_sport_classification,
    create_sport_classification_payload,
    discover_claim,
    enroll_participant,
    file_injury_report,
    issue_benefit_payment,
    make_claims_examiner_headers,
    make_guardian_headers,
    make_league_admin_headers,
    make_league_official_headers,
    make_medical_reviewer_headers,
    make_program_admin_headers,
    payments_for_claim,
    quote_policy,
    read_benefit_payment,
    read_claim,
    read_enrollment,
    read_family_health_plan,
    read_injury_report,
    read_loss_experience,
    read_participant,
    read_policy,
    read_provider_bill,
    record_provider_bill,
    reports_for_enrollment,
    reprice_bill,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_verified_claim,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    verify_injury_report,
)

PROGRAM_ADMIN = make_program_admin_headers()
EXAMINER = make_claims_examiner_headers()
REVIEWER = make_medical_reviewer_headers()
SANCTIONING_OFFICIAL = make_league_official_headers(SANCTIONING_OFFICIAL_USER_ID)
DECIDING_OFFICIAL = make_league_official_headers(VERIFYING_OFFICIAL_USER_ID)

# Well-formed UUIDs that were never minted by the server.
UNKNOWN_ID_1 = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ID_2 = "00000000-0000-4000-8000-000000000002"
UNKNOWN_ID_3 = "00000000-0000-4000-8000-000000000003"
UNKNOWN_ID_4 = "00000000-0000-4000-8000-000000000004"


def _assert_error_envelope(response):
    """The error envelope of PRD §2.2 carries exactly two data keys and a meta
    limited to the request identifier and its timestamp."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"error responses declare response_type 'error', got {body['response_type']!r}"
    )
    assert set(body["data"]) == {"error_id", "message"}, (
        f"error data carries only error_id and message, got {sorted(body['data'])}"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        "error meta carries only api_request_id and api_request_timestamp, got "
        f"{sorted(body['meta'])}"
    )
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"], "api_request_id must be a non-empty string"


def test_reused_league_code_and_reused_sport_code_each_name_their_own_conflict(api):
    """PRD §3.1: "The `league_code` must be unique across all leagues and must be between 3 and 16 characters drawn from uppercase letters, digits and the hyphen; re-using a code already on file is refused with `ERR_DUPLICATE_LEAGUE_CODE`."
    PRD §3.1: "A classification is created with a unique `sport_code` (a duplicate is refused with `ERR_DUPLICATE_SPORT_CODE`), a human-readable `sport_name`, a `hazard_class` of `CLASS_1_LOW`, `CLASS_2_MODERATE`, `CLASS_3_HIGH` or `CLASS_4_CONTACT`, and a manual annual `base_rate_per_participant_cents` of at least one cent."

    Design: Corner/errors/duplicate_league_code_and_duplicate_sport_code_rejected
    """
    validate_success(
        api.create_league(
            create_league_payload(
                name="Dunmore Baseball",
                league_code="DPL-136",
                state_code="CT",
                governing_body_code="USYSA",
                contact_email="admin@dpl.example",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_sport_classification(
            create_sport_classification_payload(sport_code="BASEBALL_U12"),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    # The same league code in a different state is still the same code.
    duplicate_league = api.create_league(
        create_league_payload(
            name="Dunmore Baseball North",
            league_code="DPL-136",
            state_code="NY",
            governing_body_code="USYSA",
            contact_email="north@dpl.example",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(
        duplicate_league, ApiErrorId.ERR_DUPLICATE_LEAGUE_CODE, expected_status=409
    )

    duplicate_sport = api.create_sport_classification(
        create_sport_classification_payload(
            sport_code="BASEBALL_U12",
            sport_name="Baseball U12 Recreational",
            hazard_class="CLASS_1_LOW",
            base_rate_per_participant_cents=1200,
            deductible_cents=20000,
            per_injury_limit_cents=1000000,
            cat_attachment_point_cents=1000000,
            aggregate_limit_cents=8000000,
            cat_lifetime_max_cents=2000000,
            minimum_participants=15,
            travel_buffer_minutes=45,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(
        duplicate_sport, ApiErrorId.ERR_DUPLICATE_SPORT_CODE, expected_status=409
    )

    # A neighbouring, genuinely distinct league code still registers.
    validate_success(
        api.create_league(
            create_league_payload(
                name="Dunmore Baseball South",
                league_code="DPL-137",
                state_code="CT",
                governing_body_code="USYSA",
                contact_email="south@dpl.example",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    _rows, league_meta = validate_paginated(api.list_leagues(PROGRAM_ADMIN))
    assert league_meta["total_count"] == 2, (
        "the refused duplicate must not have been written: expected 2 leagues on "
        f"file, got {league_meta['total_count']}"
    )
    _rows, sport_meta = validate_paginated(api.list_sport_classifications(PROGRAM_ADMIN))
    assert sport_meta["total_count"] == 1, (
        "the refused duplicate sport code must not have been written: expected 1 "
        f"classification on file, got {sport_meta['total_count']}"
    )


def test_reads_of_unknown_identifiers_each_name_their_own_entity_in_the_error_envelope(api):
    """PRD §2.6: "The first segment that does not resolve to a live row determines the response, which is the 404 code naming that entity: `ERR_LEAGUE_NOT_FOUND`, `ERR_SPORT_CLASSIFICATION_NOT_FOUND`, `ERR_LEAGUE_POLICY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_FAMILY_HEALTH_PLAN_NOT_FOUND`, `ERR_SANCTIONED_ACTIVITY_NOT_FOUND`, `ERR_INJURY_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PROVIDER_BILL_NOT_FOUND`, `ERR_COORDINATION_RECORD_NOT_FOUND` or `ERR_BENEFIT_PAYMENT_NOT_FOUND`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/not_found_errors_are_per_entity_and_use_the_error_envelope
    """
    probes = [
        (api.get_league(UNKNOWN_ID_1, PROGRAM_ADMIN), ApiErrorId.ERR_LEAGUE_NOT_FOUND),
        (api.get_claim(UNKNOWN_ID_2, EXAMINER), ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (
            api.get_benefit_payment(UNKNOWN_ID_3, EXAMINER),
            ApiErrorId.ERR_BENEFIT_PAYMENT_NOT_FOUND,
        ),
        (
            api.get_coordination_record(UNKNOWN_ID_4, EXAMINER),
            ApiErrorId.ERR_COORDINATION_RECORD_NOT_FOUND,
        ),
    ]

    for response, expected_error in probes:
        validate_error(response, expected_error, expected_status=404)
        _assert_error_envelope(response)
        message = response.json()["data"]["message"]
        assert isinstance(message, str) and message.strip(), (
            f"the refusal naming {expected_error.value} must carry a human-readable "
            f"message, got {message!r}"
        )


def test_coordination_moves_are_refused_by_the_coverage_posture_they_contradict(api):
    """PRD §3.6: "Throughout the rest of this section, the phrase **other coverage on file** means precisely this: the set of family health plans belonging to the claim's athlete whose `coverage_state` is `ACTIVE` and whose `verification_status` is *not* `NO_COVERAGE_ATTESTED`."
    PRD §3.6: "A `ClaimsExaminer` requesting the explanation of benefits, optionally with a `note`, drives `NOT_STARTED → EOB_REQUESTED` and stamps `eob_requested_at` with the logical clock."
    PRD §3.6: "It requires other coverage to be on file; if the athlete holds no qualifying plan, there is nothing to request an explanation of benefits from and the request is refused with `ERR_NO_OTHER_COVERAGE_ON_FILE`."
    PRD §3.6: "It carries the opposite membership test: the set of qualifying plans must be **empty**, and any single plan with an `ACTIVE` coverage state that has not been attested as no-coverage refuses the request with `ERR_OTHER_COVERAGE_ON_FILE`."
    PRD §3.6: "It carries one further requirement of its own: the governing policy's `coverage_basis_election` must be `FULL_EXCESS_PERMITTED`."
    PRD §3.6: "A term written on an `EXCESS_ONLY` basis may never run a claim as program-primary, and the attempt is refused with `ERR_FULL_EXCESS_NOT_PERMITTED`."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."
    PRD §2.7: "28. through 37. **Business constraints** — in order: no overlapping in-force term for the same league and sport (`ERR_POLICY_TERM_OVERLAP`); no per-athlete activity collision (`ERR_PARTICIPANT_ACTIVITY_CONFLICT`); no duplicate active enrollment (`ERR_DUPLICATE_ENROLLMENT`); correction rounds not exhausted (`ERR_CORRECTION_ROUNDS_EXHAUSTED`); the service category is on the benefit schedule (`ERR_SERVICE_CATEGORY_NOT_SCHEDULED`); league and sport codes unique (`ERR_DUPLICATE_LEAGUE_CODE`, `ERR_DUPLICATE_SPORT_CODE`); no other coverage on file when none is being attested (`ERR_OTHER_COVERAGE_ON_FILE`); the policy permits a full-excess footing (`ERR_FULL_EXCESS_NOT_PERMITTED`); some other coverage exists when an explanation of benefits is requested (`ERR_NO_OTHER_COVERAGE_ON_FILE`); and no issued payment stands in the way of a void or withdrawal (`ERR_PAYMENT_ON_FILE`)."

    Design: Corner/errors/coordination_entry_points_reject_the_wrong_coverage_posture
    """
    bundle = setup_verified_claim(
        league_overrides={
            "name": "Elmwood Baseball",
            "league_code": "EWB-138",
            "state_code": "OH",
            "governing_body_code": "USYSA",
            "contact_email": "admin@ewb.example",
        },
        policy_overrides={"coverage_basis_election": "EXCESS_ONLY"},
        participant_overrides={
            "first_name": "Viveka",
            "last_name": "Sandoval",
            "date_of_birth": "2015-06-01",
            "guardian_email": "g39@ewb.example",
        },
        report_overrides={
            "injury_description": "knee sprain on a rundown between second and third",
            "severity_tier": "MODERATE",
        },
    )
    claim = bundle["claim"]
    athlete = bundle["participant"]
    assert bundle["policy"]["coverage_basis_election"] == "EXCESS_ONLY", (
        "the Elmwood term is written excess of any family coverage, got "
        f"{bundle['policy']['coverage_basis_election']}"
    )
    assert claim["coordination_status"] == "NOT_STARTED", (
        f"a freshly opened claim has not begun coordination, got {claim['coordination_status']}"
    )

    # Nothing to ask a carrier about: the household has no plan on file at all.
    validate_error(
        api.request_eob(
            claim["id"],
            {"note": "asking the family carrier for an explanation of benefits"},
            EXAMINER,
        ),
        ApiErrorId.ERR_NO_OTHER_COVERAGE_ON_FILE,
        expected_status=409,
    )

    # The empty-plan-set test passes, so the excess-only election is what bites.
    validate_error(
        api.confirm_no_other_coverage(
            claim["id"],
            {"attestation_note": "guardian states the household has no other coverage"},
            EXAMINER,
        ),
        ApiErrorId.ERR_FULL_EXCESS_NOT_PERMITTED,
        expected_status=422,
    )

    plan = validate_success(
        api.create_family_health_plan(
            create_family_health_plan_payload(
                athlete["id"],
                carrier_name="Buckeye Mutual Health",
                policy_number="BM-44210",
                plan_type="HMO",
                individual_deductible_cents=200000,
                coinsurance_bps=2500,
                effective_date="2026-01-01",
            ),
            make_guardian_headers(athlete["id"]),
        ),
        expected_status=201,
    )
    assert plan["coverage_state"] == "ACTIVE", (
        "a plan effective 2026-01-01 with no termination date is live at the current "
        f"logical clock, got {plan['coverage_state']}"
    )
    assert plan["verification_status"] == "UNVERIFIED", (
        "the claims desk has not spoken to Buckeye Mutual yet, got "
        f"{plan['verification_status']}"
    )

    # With one ACTIVE, un-attested plan on file the membership test now fires first.
    validate_error(
        api.confirm_no_other_coverage(
            claim["id"],
            {"attestation_note": "second attempt at the program-primary attestation"},
            EXAMINER,
        ),
        ApiErrorId.ERR_OTHER_COVERAGE_ON_FILE,
        expected_status=409,
    )

    requested = validate_success(
        api.request_eob(
            claim["id"],
            {"note": "now that a plan is on file, requesting the explanation of benefits"},
            EXAMINER,
        ),
        expected_status=200,
    )
    assert requested["coordination_status"] == "EOB_REQUESTED", (
        "the same request that was refused a moment ago now moves the coordination "
        f"axis off NOT_STARTED, got {requested['coordination_status']}"
    )
    assert canonical_iso(requested["eob_requested_at"]) == canonical_iso(
        "2026-07-12T00:00:00Z"
    ), (
        "the request is stamped with the logical clock, got "
        f"{requested['eob_requested_at']}"
    )

    stored = read_claim(claim["id"])
    assert stored["coordination_basis"] is None, (
        "requesting an explanation of benefits is not receiving one, so the basis is "
        f"still undetermined, got {stored['coordination_basis']!r}"
    )


def test_an_unscheduled_dental_charge_and_a_moderate_injury_block_pricing_and_certification(api):
    """PRD §3.7: "A recorded bill enters `SUBMITTED` with `allowed_amount_cents` 0 and with `negotiated_amount_cents`, `scheduled_cap_cents`, `balance_billed_cents`, `family_responsibility_cents`, `repriced_at`, `repriced_by_user_id` and `void_reason` all still unset."
    PRD §3.7: "The examiner then reprices the charge, which requires the bill to be `SUBMITTED` (otherwise `ERR_INVALID_BILL_STATE`), the parent claim's `adjudication_status` to be `PENDING_COORDINATION` or `UNDER_ADJUDICATION`, the governing policy's posture not to be `FROZEN`, and — the substantive gate — the bill's `service_category` to be a declared key of the governing sport classification's `service_category_caps` benefit schedule."
    PRD §3.7: "A charge in a category the sport does not schedule cannot be priced at all and is refused with `ERR_SERVICE_CATEGORY_NOT_SCHEDULED`."
    PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`balance_billed_cents` is the billed charge less the allowed amount, floored at zero."
    PRD §3.7: "For an in-network provider it is **always exactly zero** — a participating provider may bill the family nothing above the allowed amount."
    PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.8: "Certification may only be issued on a claim whose originating report carries a `severity_tier` of `CATASTROPHIC`; anything else is refused with `ERR_SEVERITY_NOT_CATASTROPHIC`."

    Design: Corner/errors/bill_and_certification_refusals_on_one_verified_claim
    """
    caps_without_dental = {
        category: cap
        for category, cap in BASEBALL_U12_CAPS.items()
        if category != "DENTAL"
    }
    bundle = setup_verified_claim(
        league_overrides={
            "name": "Fairhaven Baseball",
            "league_code": "FHB-139",
            "state_code": "MA",
            "governing_body_code": "USYSA",
            "contact_email": "admin@fhb.example",
        },
        sport_overrides={
            "sport_code": "BASEBALL_U12_NO_DENTAL",
            "sport_name": "Baseball U12 without dental",
            "service_category_caps": caps_without_dental,
        },
        participant_overrides={
            "first_name": "Wesley",
            "last_name": "Ferreira",
            "date_of_birth": "2015-07-02",
            "guardian_email": "g40@fhb.example",
        },
        report_overrides={
            "body_part": "DENTAL",
            "injury_description": "chipped incisor from a bad hop",
            "severity_tier": "MODERATE",
        },
        official_attestation="official saw the ball strike the batter's mouth",
    )
    claim = bundle["claim"]
    assert "DENTAL" not in bundle["sport_classification"]["service_category_caps"], (
        "the Fairhaven benefit schedule deliberately omits dental work altogether"
    )

    # A charge in an unscheduled category is still recordable: recording and pricing
    # are separate acts.
    dental_bill = validate_success(
        api.create_provider_bill(
            create_provider_bill_payload(
                claim["id"],
                provider_npi="1177889900",
                provider_name="Fairhaven Pediatric Dental",
                network_status="IN_NETWORK",
                service_category="DENTAL",
                service_date="2026-07-11",
                billed_charge_cents=180000,
                fee_schedule_amount_cents=140000,
            ),
            EXAMINER,
        ),
        expected_status=201,
    )
    assert dental_bill["status"] == "SUBMITTED", (
        f"a recorded charge enters SUBMITTED, got {dental_bill['status']}"
    )
    office_bill = validate_success(
        api.create_provider_bill(
            create_provider_bill_payload(
                claim["id"],
                provider_npi="1188990011",
                provider_name="Fairhaven Pediatrics",
                network_status="IN_NETWORK",
                service_category="PHYSICIAN_OFFICE",
                service_date="2026-07-11",
                billed_charge_cents=60000,
                fee_schedule_amount_cents=42000,
            ),
            EXAMINER,
        ),
        expected_status=201,
    )

    validate_error(
        api.reprice_provider_bill(dental_bill["id"], EXAMINER),
        ApiErrorId.ERR_SERVICE_CATEGORY_NOT_SCHEDULED,
        expected_status=422,
    )
    stored_dental = read_provider_bill(dental_bill["id"])
    assert stored_dental["status"] == "SUBMITTED", (
        "the refused repricing leaves the dental charge exactly where it was, got "
        f"{stored_dental['status']}"
    )
    assert stored_dental["allowed_amount_cents"] == 0, (
        "an unpriced charge allows nothing, got "
        f"{stored_dental['allowed_amount_cents']}"
    )

    # The same claim prices a scheduled category normally: in-network negotiated
    # amount 42000 against a MODERATE-adjusted cap of 50000.
    repriced = validate_success(
        api.reprice_provider_bill(office_bill["id"], EXAMINER), expected_status=200
    )
    assert repriced["status"] == "REPRICED", (
        f"a priced charge reads REPRICED, got {repriced['status']}"
    )
    assert repriced["negotiated_amount_cents"] == 42000, (
        "in network the negotiated amount is the smaller of 60000 billed and 42000 "
        f"fee-schedule, got {repriced['negotiated_amount_cents']}"
    )
    assert repriced["scheduled_cap_cents"] == 50000, (
        "the physician-office cap of 50000 is untouched by the MODERATE factor of "
        f"10000 basis points, got {repriced['scheduled_cap_cents']}"
    )
    assert repriced["allowed_amount_cents"] == 42000, (
        "the smaller of 42000 negotiated and the 50000 cap is allowed, got "
        f"{repriced['allowed_amount_cents']}"
    )
    assert repriced["balance_billed_cents"] == 18000, (
        f"60000 billed less 42000 allowed leaves 18000, got {repriced['balance_billed_cents']}"
    )
    assert repriced["family_responsibility_cents"] == 0, (
        "an in-network provider may bill the family nothing above the allowed amount, "
        f"got {repriced['family_responsibility_cents']}"
    )

    validate_error(
        api.certify_catastrophic(
            claim["id"],
            {"certification_note": "attempting certification on a moderate dental injury"},
            REVIEWER,
        ),
        ApiErrorId.ERR_SEVERITY_NOT_CATASTROPHIC,
        expected_status=422,
    )

    settled = read_claim(claim["id"])
    assert settled["allowed_amount_total_cents"] == 42000, (
        "only the priced physician-office charge contributes to the allowed total; "
        f"the unpriced dental charge contributes nothing, got {settled['allowed_amount_total_cents']}"
    )
    assert settled["adjudication_status"] == "UNDER_ADJUDICATION", (
        "the first successful reprice advanced the adjudication axis, got "
        f"{settled['adjudication_status']}"
    )
    assert settled["cat_certification_status"] == "NONE", (
        "the refused certification left the catastrophic axis untouched, got "
        f"{settled['cat_certification_status']}"
    )


def test_a_report_thirty_one_days_old_cannot_be_verified_while_a_fresh_one_can(api):
    """PRD §3.5: "The whole number of UTC days from the report's `created_at` to the logical clock must be no more than thirty, or the decision is refused with `ERR_VERIFICATION_WINDOW_EXPIRED`."
    PRD §3.5: "`days_to_report` is the whole number of UTC calendar days from the calendar date of `injury_datetime` to `reported_on_date`."
    PRD §3.5: "The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."

    Design: Corner/errors/verification_decision_one_day_past_the_thirty_day_window_rejected
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Glenmoor Baseball",
        league_code="GMB-140",
        state_code="IN",
        governing_body_code="USYSA",
        contact_email="admin@gmb.example",
    )
    sport = create_sport_classification("baseball")
    policy = quote_policy(league["id"], sport["id"])
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    league_headers = make_league_admin_headers(league["id"])

    athlete = add_participant(
        league["id"],
        first_name="Xiomara",
        last_name="Delgado",
        date_of_birth="2015-08-03",
        guardian_email="g41@gmb.example",
    )
    enrollment = enroll_participant(
        athlete["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    game = schedule_activity(
        policy["id"],
        league["id"],
        activity_type="GAME",
        venue_name="Glenmoor Field 2",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )
    sanction_activity(game["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")
    stale_report = file_injury_report(
        enrollment["id"],
        game["id"],
        league["id"],
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="HIP_GROIN",
        injury_description="groin strain stealing third",
        severity_tier="MODERATE",
    )
    assert stale_report["status"] == "PENDING_VERIFICATION", (
        f"the filed report awaits a decision, got {stale_report['status']}"
    )

    # Exactly thirty-one whole UTC days after the report was created.
    set_clock("2026-08-12T00:00:00Z")

    validate_error(
        api.record_verification_decision(
            stale_report["id"],
            {
                "decision": "VERIFY",
                "official_attestation": "late attestation from the base official",
            },
            DECIDING_OFFICIAL,
        ),
        ApiErrorId.ERR_VERIFICATION_WINDOW_EXPIRED,
        expected_status=422,
    )
    still_pending = read_injury_report(stale_report["id"])
    assert still_pending["status"] == "PENDING_VERIFICATION", (
        "the refused decision leaves the report awaiting verification, got "
        f"{still_pending['status']}"
    )
    assert still_pending["verified_at"] is None, (
        f"nothing was stamped on the refused report, got {still_pending['verified_at']!r}"
    )

    # A report filed at this same later clock is 32 days from its injury, which is
    # well inside the ninety-day filing window, and its own verification clock
    # starts now.
    fresh_report = validate_success(
        api.create_injury_report(
            create_injury_report_payload(
                enrollment["id"],
                game["id"],
                injury_datetime="2026-07-11T19:10:00Z",
                body_part="KNEE",
                injury_description="knee soreness discovered a month later",
                severity_tier="MINOR",
            ),
            league_headers,
        ),
        expected_status=201,
    )
    assert fresh_report["days_to_report"] == 32, (
        "2026-07-11 to 2026-08-12 is 32 whole calendar days, got "
        f"{fresh_report['days_to_report']}"
    )

    verified = validate_success(
        api.record_verification_decision(
            fresh_report["id"],
            {
                "decision": "VERIFY",
                "official_attestation": "official confirms the same play",
            },
            DECIDING_OFFICIAL,
        ),
        expected_status=200,
    )
    assert verified["status"] == "VERIFIED", (
        "the verification window runs from each report's own creation, not from the "
        f"injury date, got {verified['status']}"
    )

    _rows, meta = validate_paginated(
        api.list_claims(EXAMINER, {"enrollment_id": enrollment["id"]})
    )
    assert meta["total_count"] == 1, (
        "only the freshly verified report minted a claim; the report refused for "
        f"lateness minted none, got total_count {meta['total_count']}"
    )


def test_each_remaining_entity_addressed_or_referenced_by_an_unknown_id_names_itself(api):
    """PRD §2.6: "Templated path segments — `{league_id}`, `{sport_classification_id}`, `{league_policy_id}`, `{participant_id}`, `{enrollment_id}`, `{family_health_plan_id}`, `{sanctioned_activity_id}`, `{injury_report_id}`, `{claim_id}`, `{provider_bill_id}`, `{coordination_record_id}` and `{benefit_payment_id}` — are resolved strictly left to right."
    PRD §2.6: "The first segment that does not resolve to a live row determines the response, which is the 404 code naming that entity: `ERR_LEAGUE_NOT_FOUND`, `ERR_SPORT_CLASSIFICATION_NOT_FOUND`, `ERR_LEAGUE_POLICY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_FAMILY_HEALTH_PLAN_NOT_FOUND`, `ERR_SANCTIONED_ACTIVITY_NOT_FOUND`, `ERR_INJURY_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PROVIDER_BILL_NOT_FOUND`, `ERR_COORDINATION_RECORD_NOT_FOUND` or `ERR_BENEFIT_PAYMENT_NOT_FOUND`."
    PRD §2.6: "Identifier fields carried in a request body are resolved after the path and in the order the endpoint declares its input fields, using the same catalogue of 404 codes."
    PRD §2.7: "3. **Ownership** — for the two entity-backed roles, the caller owns the addressed resource (`ERR_OWNERSHIP_MISMATCH`)."
    PRD §2.7: "6. **Body reference existence** — every identifier field in the body resolves, in declared field order (the same 404 codes)."

    Design: Corner/errors/every_remaining_entity_addressed_by_an_unknown_id_returns_its_own_not_found_code
    """
    league = create_league(
        name="Silverbrook Baseball",
        league_code="SBB-151",
        state_code="OH",
        governing_body_code="USYSA",
        contact_email="admin@sbb.example",
    )
    sport = create_sport_classification("baseball")

    unknown_sport = "00000000-0000-4000-8000-000000000201"
    unknown_athlete = "00000000-0000-4000-8000-000000000202"
    unknown_enrollment = "00000000-0000-4000-8000-000000000203"
    unknown_plan = "00000000-0000-4000-8000-000000000204"
    unknown_activity = "00000000-0000-4000-8000-000000000205"
    unknown_report = "00000000-0000-4000-8000-000000000206"
    unknown_bill = "00000000-0000-4000-8000-000000000207"
    unknown_referenced_sport = "00000000-0000-4000-8000-000000000208"
    unknown_referenced_league = "00000000-0000-4000-8000-000000000209"

    addressed_probes = [
        (
            api.get_sport_classification(unknown_sport, PROGRAM_ADMIN),
            ApiErrorId.ERR_SPORT_CLASSIFICATION_NOT_FOUND,
        ),
        (
            api.get_participant(unknown_athlete, PROGRAM_ADMIN),
            ApiErrorId.ERR_PARTICIPANT_NOT_FOUND,
        ),
        (
            api.get_enrollment(unknown_enrollment, PROGRAM_ADMIN),
            ApiErrorId.ERR_ENROLLMENT_NOT_FOUND,
        ),
        (
            api.get_family_health_plan(unknown_plan, EXAMINER),
            ApiErrorId.ERR_FAMILY_HEALTH_PLAN_NOT_FOUND,
        ),
        (
            api.get_sanctioned_activity(unknown_activity, PROGRAM_ADMIN),
            ApiErrorId.ERR_SANCTIONED_ACTIVITY_NOT_FOUND,
        ),
        (
            api.get_injury_report(unknown_report, EXAMINER),
            ApiErrorId.ERR_INJURY_REPORT_NOT_FOUND,
        ),
        (
            api.get_provider_bill(unknown_bill, EXAMINER),
            ApiErrorId.ERR_PROVIDER_BILL_NOT_FOUND,
        ),
    ]
    for response, expected_error in addressed_probes:
        validate_error(response, expected_error, expected_status=404)
        _assert_error_envelope(response)

    # A referenced parent that does not exist is reported with the parent's own code,
    # not with the code of the entity being created.
    quote_attempt = api.create_league_policy(
        create_league_policy_payload(league["id"], unknown_referenced_sport),
        PROGRAM_ADMIN,
    )
    validate_error(
        quote_attempt, ApiErrorId.ERR_SPORT_CLASSIFICATION_NOT_FOUND, expected_status=404
    )
    _assert_error_envelope(quote_attempt)
    _rows, policy_meta = validate_paginated(
        api.list_league_policies(PROGRAM_ADMIN, {"league_id": league["id"]})
    )
    assert policy_meta["total_count"] == 0, (
        "the refused quote wrote no policy term for Silverbrook, got total_count "
        f"{policy_meta['total_count']}"
    )

    # The roster write claims the caller's own league in its identity header and an
    # unknown league in its body, so either the ownership rung or the body-reference
    # rung may answer first.
    roster_attempt = api.create_participant(
        create_participant_payload(
            unknown_referenced_league,
            first_name="Sorrel",
            last_name="Kaminski",
            date_of_birth="2016-06-13",
            guardian_email="g51@sbb.example",
        ),
        make_league_admin_headers(league["id"]),
    )
    actual = validate_error_is_one_of(
        roster_attempt,
        [ApiErrorId.ERR_OWNERSHIP_MISMATCH, ApiErrorId.ERR_LEAGUE_NOT_FOUND],
    )
    _assert_error_envelope(roster_attempt)
    expected_status = 403 if actual == ApiErrorId.ERR_OWNERSHIP_MISMATCH else 404
    assert roster_attempt.status_code == expected_status, (
        f"{actual} is declared as HTTP {expected_status}, got "
        f"{roster_attempt.status_code}"
    )
    _rows, roster_meta = validate_paginated(
        api.list_participants(PROGRAM_ADMIN, {"league_id": league["id"]})
    )
    assert roster_meta["total_count"] == 0, (
        "the refused roster write left Silverbrook's roster empty, got total_count "
        f"{roster_meta['total_count']}"
    )
    assert sport["id"] != unknown_referenced_sport, (
        "the probe must address an identifier the server never minted"
    )


def test_missing_empty_and_undeclared_identity_headers_are_all_answered_as_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act."
    PRD §2.1: "If either header is missing or empty, or if `X-User-Role` does not name one of the six roles declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "If the role is recognised but is not among the roles authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "1. **Authentication** — headers present and the role recognised (`ERR_UNAUTHENTICATED`)."
    PRD §2.7: "5. **Path existence** — every templated identifier resolves, left to right (the entity-specific 404 codes)."

    Design: Corner/errors/calls_with_a_missing_or_unknown_identity_header_are_rejected_as_unauthenticated
    """
    league = create_league(
        name="Thornbury Baseball",
        league_code="TBB-152",
        state_code="IN",
        governing_body_code="USYSA",
        contact_email="admin@tbb.example",
    )
    unknown_league = "00000000-0000-4000-8000-000000000210"

    # No identity at all.
    anonymous = api.get_league(league["id"], {})
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    _assert_error_envelope(anonymous)

    # An empty role names no capacity, which is the same as naming none.
    empty_role = api.get_league(
        league["id"], build_user_headers(PROGRAM_ADMIN_USER_ID, "")
    )
    validate_error(empty_role, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    _assert_error_envelope(empty_role)

    # A role outside the six declared capacities never reaches the authorisation
    # rung, so the answer is 401 rather than 403.
    undeclared_role = api.get_league(
        league["id"], build_user_headers(PROGRAM_ADMIN_USER_ID, "ClaimsSupervisor")
    )
    validate_error(undeclared_role, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    _assert_error_envelope(undeclared_role)

    # Authentication outranks existence, so an unknown league is still a 401 and the
    # refusal leaks nothing about whether the row is on file.
    undeclared_role_unknown_row = api.get_league(
        unknown_league, build_user_headers(PROGRAM_ADMIN_USER_ID, "ClaimsSupervisor")
    )
    validate_error(
        undeclared_role_unknown_row, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401
    )
    _assert_error_envelope(undeclared_role_unknown_row)

    # The same read with a declared capacity succeeds, which is what proves the four
    # refusals were caused by identity alone.
    control = validate_success(api.get_league(league["id"], PROGRAM_ADMIN), 200)
    assert control["id"] == league["id"], (
        f"the authenticated read returns the Thornbury league, got {control['id']}"
    )


def test_repeat_actions_on_a_settled_report_bill_and_payment_name_the_blocking_artifact(api):
    """PRD §3.5: "A resubmission attempted on a report that is not `RETURNED_FOR_CORRECTION`, or a return or verification decision attempted on a report that is not `PENDING_VERIFICATION`, is refused with `ERR_INVALID_REPORT_STATE`."
    PRD §3.7: "The examiner then reprices the charge, which requires the bill to be `SUBMITTED` (otherwise `ERR_INVALID_BILL_STATE`), the parent claim's `adjudication_status` to be `PENDING_COORDINATION` or `UNDER_ADJUDICATION`, the governing policy's posture not to be `FROZEN`, and — the substantive gate — the bill's `service_category` to be a declared key of the governing sport classification's `service_category_caps` benefit schedule."
    PRD §3.6: "Either move attempted from a coordination status that is not `NOT_STARTED` is refused with `ERR_INVALID_COORDINATION_STATE`."
    PRD §3.6: "On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb."
    PRD §3.7: "From `REPRICED` and from `ADJUDICATED` it additionally requires that no benefit payment with `status` `ISSUED` references the bill, and an attempt against a paid bill is refused with `ERR_PAYMENT_ON_FILE`."
    PRD §3.8: "Withdrawal is available from three points on the adjudication axis and in every case requires the claim's `paid_to_date_cents` to be zero; an attempt while any `ISSUED` payment exists on the claim is refused with `ERR_PAYMENT_ON_FILE`."
    PRD §3.8: "A payment issued in error is voided with a `void_reason`, which requires the payment to be `ISSUED` (otherwise `ERR_INVALID_PAYMENT_STATE`)."
    PRD §3.8: "The void stamps `voided_at` with the logical clock and stores the reason, moving the payment `ISSUED → VOIDED`."
    PRD §3.8: "Because of that alone, the claim's `paid_base_cents`, `paid_cat_cents` and `paid_to_date_cents` are recomputed, and if the claim was `PAID` and its `paid_to_date_cents` now falls below `benefit_payable_cents`, the claim moves `PAID → APPROVED`."
    PRD §2.7: "8. **The addressed resource's own state** — the row is in a state from which the requested transition is legal."

    Design: Corner/errors/repeat_actions_on_a_settled_report_bill_and_payment_are_rejected
    """
    bundle = setup_verified_claim(
        league_overrides={
            "name": "Underhill Baseball",
            "league_code": "UHB-153",
            "state_code": "IA",
            "governing_body_code": "USYSA",
            "contact_email": "admin@uhb.example",
        },
        policy_overrides={"coverage_basis_election": "FULL_EXCESS_PERMITTED"},
        participant_overrides={
            "first_name": "Tamsin",
            "last_name": "Okonkwo",
            "date_of_birth": "2016-07-14",
            "guardian_email": "g52@uhb.example",
        },
        report_overrides={
            "body_part": "SHOULDER_ARM",
            "injury_description": "shoulder strained on an overhand throw",
            "severity_tier": "MODERATE",
        },
        official_attestation="third-base official witnessed the throw",
    )
    claim = bundle["claim"]
    report = bundle["injury_report"]
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    bill = record_provider_bill(
        claim["id"],
        provider_npi="1300112244",
        provider_name="Underhill Regional ER",
        network_status="IN_NETWORK",
        service_category="EMERGENCY_ROOM",
        service_date="2026-07-11",
        billed_charge_cents=400000,
        fee_schedule_amount_cents=360000,
    )
    bill = reprice_bill(bill["id"])
    assert bill["allowed_amount_cents"] == 360000, (
        "in network the allowed amount is the 360000 fee-schedule figure under the "
        f"500000 emergency-room cap, got {bill['allowed_amount_cents']}"
    )
    settled_coordination = confirm_no_other_coverage(
        claim["id"], "no family health coverage on file for this athlete"
    )
    assert settled_coordination["coordination_basis"] == "FULL_EXCESS", (
        "ruling other coverage out puts the claim on a full-excess footing, got "
        f"{settled_coordination['coordination_basis']!r}"
    )

    # The report is VERIFIED, so all three report-level moves are past their window.
    validate_error(
        api.record_verification_decision(
            report["id"],
            {
                "decision": "VERIFY",
                "official_attestation": "second attempt at the same decision",
            },
            DECIDING_OFFICIAL,
        ),
        ApiErrorId.ERR_INVALID_REPORT_STATE,
        expected_status=409,
    )
    validate_error(
        api.return_injury_report_for_correction(
            report["id"],
            {"correction_note": "trying to pull a verified report back"},
            DECIDING_OFFICIAL,
        ),
        ApiErrorId.ERR_INVALID_REPORT_STATE,
        expected_status=409,
    )
    validate_error(
        api.resubmit_injury_report(
            report["id"],
            {
                "injury_description": "resubmitting a verified report",
                "severity_tier": "SEVERE",
            },
            league_headers,
        ),
        ApiErrorId.ERR_INVALID_REPORT_STATE,
        expected_status=409,
    )
    stored_report = read_injury_report(report["id"])
    assert stored_report["severity_tier"] == "MODERATE", (
        "the refused resubmission did not overwrite the severity tier, got "
        f"{stored_report['severity_tier']}"
    )
    assert read_claim(claim["id"])["reserve_amount_cents"] == 250000, (
        "the case reserve struck from the MODERATE tier is untouched by the refused "
        "resubmission"
    )

    # The charge is already REPRICED while the claim is still open, so only the
    # bill's own state can block a second pricing run.
    validate_error(
        api.reprice_provider_bill(bill["id"], EXAMINER),
        ApiErrorId.ERR_INVALID_BILL_STATE,
        expected_status=409,
    )
    assert read_provider_bill(bill["id"])["allowed_amount_cents"] == 360000, (
        "the refused second pricing run left the allowed amount alone"
    )

    # Both coordination entry points require NOT_STARTED, and this claim has settled.
    validate_error(
        api.confirm_no_other_coverage(
            claim["id"], {"attestation_note": "second attestation"}, EXAMINER
        ),
        ApiErrorId.ERR_INVALID_COORDINATION_STATE,
        expected_status=409,
    )
    validate_error(
        api.request_eob(
            claim["id"],
            {
                "note": "asking for an explanation of benefits after coordination already settled"
            },
            EXAMINER,
        ),
        ApiErrorId.ERR_INVALID_COORDINATION_STATE,
        expected_status=409,
    )
    mid_claim = read_claim(claim["id"])
    assert mid_claim["coordination_status"] == "NO_OTHER_COVERAGE_CONFIRMED", (
        "the two refused coordination moves left the axis settled where it was, got "
        f"{mid_claim['coordination_status']}"
    )
    assert mid_claim["coordination_basis"] == "FULL_EXCESS", (
        f"the basis stays FULL_EXCESS, got {mid_claim['coordination_basis']!r}"
    )

    approved = adjudicate_claim(
        claim["id"], "covered game injury, full-excess basis"
    )
    assert approved["adjudication_status"] == "APPROVED", (
        f"the determination funds a benefit, so the claim approves, got {approved['adjudication_status']}"
    )
    assert approved["deductible_applied_cents"] == 50000, (
        "the full-excess basis doubles the 25000 deductible, got "
        f"{approved['deductible_applied_cents']}"
    )
    assert approved["benefit_payable_cents"] == 310000, (
        "360000 allowed less the doubled 50000 deductible is payable in full under "
        f"the 2500000 per-injury limit, got {approved['benefit_payable_cents']}"
    )

    payment = issue_benefit_payment(claim["id"], bill["id"], 300000)
    assert payment["status"] == "ISSUED", (
        f"the cheque is out the door, got {payment['status']}"
    )
    paid_claim = read_claim(claim["id"])
    assert paid_claim["paid_to_date_cents"] == 300000, (
        f"300000 of the 310000 payable has been paid, got {paid_claim['paid_to_date_cents']}"
    )
    assert paid_claim["adjudication_status"] == "APPROVED", (
        "300000 has not reached the 310000 payable, so the claim stays APPROVED, got "
        f"{paid_claim['adjudication_status']}"
    )
    assert read_provider_bill(bill["id"])["status"] == "ADJUDICATED", (
        "approval swept the repriced charge to ADJUDICATED"
    )

    # ADJUDICATED is a declared from-state for voiding a charge, so the refusal must
    # name the issued cheque rather than the bill's state.
    validate_error(
        api.void_provider_bill(
            bill["id"], {"void_reason": "billing error discovered late"}, EXAMINER
        ),
        ApiErrorId.ERR_PAYMENT_ON_FILE,
        expected_status=409,
    )
    assert read_provider_bill(bill["id"])["status"] == "ADJUDICATED", (
        "the refused void left the charge adjudicated"
    )

    # APPROVED is likewise a declared from-state for withdrawal, so again the money
    # already paid is what refuses it.
    validate_error(
        api.withdraw_claim(
            claim["id"],
            {"withdrawal_reason": "family asked to drop the claim"},
            league_headers,
        ),
        ApiErrorId.ERR_PAYMENT_ON_FILE,
        expected_status=409,
    )
    assert read_claim(claim["id"])["adjudication_status"] == "APPROVED", (
        "the refused withdrawal left the claim approved"
    )

    voided = validate_success(
        api.void_benefit_payment(
            payment["id"],
            {"void_reason": "payment issued against the wrong bill"},
            EXAMINER,
        ),
        expected_status=200,
    )
    assert voided["status"] == "VOIDED", (
        f"the compensating action moves the cheque to VOIDED, got {voided['status']}"
    )
    reopened = read_claim(claim["id"])
    assert reopened["paid_to_date_cents"] == 0, (
        "the void unwinds the money exactly, got "
        f"{reopened['paid_to_date_cents']}"
    )
    assert reopened["adjudication_status"] == "APPROVED", (
        "the claim was never PAID, so it simply stays APPROVED, got "
        f"{reopened['adjudication_status']}"
    )
    policy_after = read_policy(bundle["policy"]["id"])
    assert policy_after["paid_loss_cents"] == 0, (
        "the void must leave paid loss exactly where it stood before the payment, got "
        f"{policy_after['paid_loss_cents']}"
    )
    assert policy_after["reserve_cents"] == 250000, (
        "the claim is still in the open set carrying its MODERATE reserve, got "
        f"{policy_after['reserve_cents']}"
    )
    assert policy_after["incurred_loss_cents"] == 250000, (
        "incurred loss is nothing paid plus the 250000 reserve, got "
        f"{policy_after['incurred_loss_cents']}"
    )

    validate_error(
        api.void_benefit_payment(
            payment["id"], {"void_reason": "second void of the same payment"}, EXAMINER
        ),
        ApiErrorId.ERR_INVALID_PAYMENT_STATE,
        expected_status=409,
    )
    assert (
        read_benefit_payment(payment["id"])["void_reason"]
        == "payment issued against the wrong bill"
    ), "the refused second void must not overwrite the reason the first one stored"
    assert len(payments_for_claim(claim["id"])) == 1, (
        "the claim carries exactly the one cheque that was issued and then voided"
    )


def test_duplicate_enrollment_open_claims_and_settled_paperwork_each_refuse_their_own_way(api):
    """PRD §3.3: "The policy must not already carry an enrollment of this same athlete whose `status` is `ENROLLED`, or the request is refused with `ERR_DUPLICATE_ENROLLMENT` — note that a previously withdrawn enrollment does not block a fresh one."
    PRD §3.3: "Withdrawing an athlete from a policy roster is the league administrator's own act, carried out with a `withdrawal_note`, and it drives the enrollment `ENROLLED → WITHDRAWN`."
    PRD §3.3: "It is refused if the enrollment still carries a claim in `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`, with `ERR_OPEN_CLAIMS_ON_ENROLLMENT`; the league must let those claims finish or withdraw them first."
    PRD §3.3: "On success the enrollment's `withdrawn_on_date` is stamped with the logical clock, its `coverage_status` becomes `WITHDRAWN_NO_COVERAGE`, and the athlete's `enrolled_policy_count` and `roster_status` are recomputed — which is how an athlete's last withdrawal flips them to `INACTIVE`."
    PRD §3.3: "Withdrawing an already-withdrawn enrollment is refused with `ERR_INVALID_ENROLLMENT_STATE`, as is filing an injury report against a withdrawn enrollment."
    PRD §3.6: "A `ClaimsExaminer` records the outcome by supplying a `decision` and a `note`, and the plan moves either `UNVERIFIED → VERIFIED` — the carrier confirmed the coverage — or `UNVERIFIED → NO_COVERAGE_ATTESTED`, meaning the carrier confirmed there is in fact no coverage here."
    PRD §3.6: "Both branches stamp `verified_at` with the logical clock and `verified_by_user_id` with the examiner's `X-User-ID`."
    PRD §3.6: "A verification attempted on a plan that is no longer `UNVERIFIED` is refused with `ERR_INVALID_FAMILY_PLAN_STATE`."

    Design: Corner/errors/duplicate_and_stale_enrollment_or_family_plan_actions_are_rejected
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Vandermere Baseball",
        league_code="VMB-154",
        state_code="MO",
        governing_body_code="USYSA",
        contact_email="admin@vmb.example",
    )
    sport = create_sport_classification("baseball")
    policy = quote_policy(league["id"], sport["id"])
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    league_headers = make_league_admin_headers(league["id"])

    athlete_a = add_participant(
        league["id"],
        first_name="Winifred",
        last_name="Achebe",
        date_of_birth="2016-08-15",
        guardian_email="g53@vmb.example",
    )
    athlete_b = add_participant(
        league["id"],
        first_name="Xavier",
        last_name="Bellweather",
        date_of_birth="2016-09-16",
        guardian_email="g54@vmb.example",
    )
    enrollment_a = enroll_participant(
        athlete_a["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    enrollment_b = enroll_participant(
        athlete_b["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    plan = add_family_health_plan(
        athlete_a["id"],
        carrier_name="Heartland Mutual",
        policy_number="HM-77120",
        plan_type="HMO",
        individual_deductible_cents=120000,
        coinsurance_bps=2500,
        effective_date="2026-01-01",
    )
    game = schedule_activity(
        policy["id"],
        league["id"],
        activity_type="GAME",
        venue_name="Vandermere Field 3",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )
    sanction_activity(game["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")
    report_a = file_injury_report(
        enrollment_a["id"],
        game["id"],
        league["id"],
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="HAND_WRIST",
        injury_description="wrist jammed sliding into second",
        severity_tier="MODERATE",
    )
    verify_injury_report(
        report_a["id"], VERIFYING_OFFICIAL_USER_ID, "base official witnessed the slide"
    )
    claim_a = discover_claim(report_a["id"])
    assert claim_a["adjudication_status"] == "PENDING_COORDINATION", (
        f"athlete A's claim is open, got {claim_a['adjudication_status']}"
    )

    # An athlete who is still enrolled cannot be enrolled on the same term twice.
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                athlete_a["id"], policy["id"], enrolled_on_date="2026-07-12"
            ),
            league_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_ENROLLMENT,
        expected_status=409,
    )
    _rows, enrollment_meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN, {"participant_id": athlete_a["id"]})
    )
    assert enrollment_meta["total_count"] == 1, (
        "the refused duplicate wrote no second enrollment row, got total_count "
        f"{enrollment_meta['total_count']}"
    )

    # An athlete with a claim still in flight cannot be withdrawn at all.
    validate_error(
        api.withdraw_enrollment(
            enrollment_a["id"],
            {"withdrawal_note": "family relocating mid-season"},
            league_headers,
        ),
        ApiErrorId.ERR_OPEN_CLAIMS_ON_ENROLLMENT,
        expected_status=409,
    )
    assert read_enrollment(enrollment_a["id"])["status"] == "ENROLLED", (
        "the refused withdrawal left athlete A on the roster"
    )

    # Athlete B carries no claim, so the same call succeeds.
    withdrawn = validate_success(
        api.withdraw_enrollment(
            enrollment_b["id"],
            {"withdrawal_note": "athlete switched to a different sport"},
            league_headers,
        ),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"the enrollment leaves the roster, got {withdrawn['status']}"
    )
    assert withdrawn["coverage_status"] == "WITHDRAWN_NO_COVERAGE", (
        f"a withdrawn athlete is no longer covered, got {withdrawn['coverage_status']}"
    )
    assert withdrawn["withdrawn_on_date"] is not None, (
        "the withdrawal date is stamped from the logical clock, got null"
    )
    assert str(withdrawn["withdrawn_on_date"]).startswith("2026-07-12"), (
        "the withdrawal is stamped with the 2026-07-12 logical clock, got "
        f"{withdrawn['withdrawn_on_date']}"
    )
    athlete_b_after = read_participant(athlete_b["id"])
    assert athlete_b_after["enrolled_policy_count"] == 0, (
        "athlete B holds no live enrollment any more, got "
        f"{athlete_b_after['enrolled_policy_count']}"
    )
    assert athlete_b_after["roster_status"] == "INACTIVE", (
        "the last withdrawal flips the athlete off the roster, got "
        f"{athlete_b_after['roster_status']}"
    )

    # WITHDRAWN is terminal, and it also bars any fresh paperwork against it.
    validate_error(
        api.withdraw_enrollment(
            enrollment_b["id"],
            {"withdrawal_note": "second withdrawal of the same enrollment"},
            league_headers,
        ),
        ApiErrorId.ERR_INVALID_ENROLLMENT_STATE,
        expected_status=409,
    )
    assert read_enrollment(enrollment_b["id"])["status"] == "WITHDRAWN", (
        "the refused second withdrawal changed nothing"
    )
    validate_error(
        api.create_injury_report(
            create_injury_report_payload(
                enrollment_b["id"],
                game["id"],
                injury_datetime="2026-07-11T19:30:00Z",
                body_part="KNEE",
                injury_description="knee twisted in the outfield",
                severity_tier="MINOR",
            ),
            league_headers,
        ),
        ApiErrorId.ERR_INVALID_ENROLLMENT_STATE,
        expected_status=409,
    )
    assert reports_for_enrollment(enrollment_b["id"]) == [], (
        "no injury report was written against the withdrawn enrollment"
    )

    # The carrier verification decision is terminal on first use.
    verified_plan = validate_success(
        api.verify_family_health_plan(
            plan["id"],
            {"decision": "VERIFIED", "note": "carrier confirmed active coverage by phone"},
            EXAMINER,
        ),
        expected_status=200,
    )
    assert verified_plan["verification_status"] == "VERIFIED", (
        f"the carrier confirmed the coverage, got {verified_plan['verification_status']}"
    )
    assert verified_plan["verified_by_user_id"] == CLAIMS_EXAMINER_USER_ID, (
        "the decision records the examiner who made it, got "
        f"{verified_plan['verified_by_user_id']!r}"
    )
    assert canonical_iso(verified_plan["verified_at"]) == canonical_iso(
        "2026-07-12T00:00:00Z"
    ), f"the decision is stamped with the logical clock, got {verified_plan['verified_at']}"

    validate_error(
        api.verify_family_health_plan(
            plan["id"],
            {
                "decision": "NO_COVERAGE_ATTESTED",
                "note": "trying to overwrite the verified decision",
            },
            EXAMINER,
        ),
        ApiErrorId.ERR_INVALID_FAMILY_PLAN_STATE,
        expected_status=409,
    )
    assert read_family_health_plan(plan["id"])["verification_status"] == "VERIFIED", (
        "the refused second decision did not overwrite the first"
    )

    policy_after = read_policy(policy["id"])
    assert policy_after["open_claim_count"] == 1, (
        "none of the refusals touched the loss position: one claim is open, got "
        f"{policy_after['open_claim_count']}"
    )
    assert policy_after["reserve_cents"] == 250000, (
        "the single MODERATE reserve still stands at 250000, got "
        f"{policy_after['reserve_cents']}"
    )


def test_writes_before_the_term_is_in_force_and_outside_its_dates_are_each_refused(api):
    """PRD §2.11: "A **policy term** is the half-open interval running from `term_effective_date` inclusive to `term_expiration_date` exclusive."
    PRD §2.11: "A date equal to the effective date is inside the term; a date equal to the expiration date is outside it."
    PRD §3.2: "The expiration date must be strictly after the effective date, or the quote is refused with `ERR_TERM_DATES_INVALID`."
    PRD §2.8: "Enrolling an athlete, scheduling an activity and taking a sanction decision on an activity require the policy to be `BOUND` or `ACTIVE`."
    PRD §2.8: "Any of these attempted against a policy outside its required set is refused with `ERR_POLICY_NOT_IN_FORCE`."
    PRD §3.2: "On success the whole premium build-up is recomputed from scratch, `status` moves `QUOTED → BOUND`, the holding league's `in_force_policy_count` increases by one, and posture is recomputed."
    PRD §3.2: "A bound term goes on risk as `BOUND → ACTIVE` once the logical clock has reached or passed its `term_effective_date`; attempting it earlier is refused, and posture is recomputed on success."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."
    PRD §3.4: "First, the activity's own **unbuffered** closed window must lie inside the governing policy's half-open term, and `starts_at` must not be later than `ends_at`; a violation is `ERR_ACTIVITY_OUTSIDE_TERM`."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.7: "The `service_date` must fall inside the governing policy's half-open term, and it must not precede the calendar date of the injury the claim arose from; either violation is refused with `ERR_SERVICE_DATE_OUTSIDE_TERM`."
    PRD §3.2: "A cancellation attempted against a term that still carries an open claim is refused with `ERR_OPEN_CLAIMS_ON_POLICY`; run-off, and not cancellation, is the sanctioned path for a term whose claims have not finished, which is precisely why the run-off transition deliberately carries no such check."

    Design: Corner/errors/policy_not_in_force_and_out_of_term_writes_are_rejected
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Wrenfield Baseball",
        league_code="WFB-155",
        state_code="KS",
        governing_body_code="USYSA",
        contact_email="admin@wfb.example",
    )
    sport = create_sport_classification("baseball")
    league_headers = make_league_admin_headers(league["id"])
    policy = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=404,
        coverage_basis_election="FULL_EXCESS_PERMITTED",
        cat_layer_elected=True,
    )
    assert policy["status"] == "QUOTED", (
        f"a newly quoted term starts in QUOTED, got {policy['status']}"
    )
    athlete = add_participant(
        league["id"],
        first_name="Yolanda",
        last_name="Castellanos",
        date_of_birth="2016-10-17",
        guardian_email="g55@wfb.example",
    )

    # An expiration date equal to the effective date is not strictly after it.
    validate_error(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2026-03-01",
                enrolled_participant_count=404,
            ),
            PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_TERM_DATES_INVALID,
        expected_status=422,
    )
    validate_error(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2026-02-28",
                enrolled_participant_count=404,
            ),
            PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_TERM_DATES_INVALID,
        expected_status=422,
    )
    _rows, meta = validate_paginated(
        api.list_league_policies(PROGRAM_ADMIN, {"league_id": league["id"]})
    )
    assert meta["total_count"] == 1, (
        "neither ill-ordered term was written, so the league still holds exactly the "
        f"one quoted term, got total_count {meta['total_count']}"
    )

    # The quoted term is not yet in force for exposure writes.
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                athlete["id"], policy["id"], enrolled_on_date="2026-03-05"
            ),
            league_headers,
        ),
        ApiErrorId.ERR_POLICY_NOT_IN_FORCE,
        expected_status=409,
    )
    validate_error(
        api.create_sanctioned_activity(
            create_sanctioned_activity_payload(
                policy["id"],
                activity_type="GAME",
                venue_name="Wrenfield Field 1",
                starts_at="2026-07-11T18:00:00Z",
                ends_at="2026-07-11T20:00:00Z",
            ),
            league_headers,
        ),
        ApiErrorId.ERR_POLICY_NOT_IN_FORCE,
        expected_status=409,
    )

    bound = validate_success(
        api.bind_league_policy(policy["id"], PROGRAM_ADMIN), 200
    )
    assert bound["status"] == "BOUND", (
        f"the quoted term goes on risk as QUOTED → BOUND, got {bound['status']}"
    )
    activated = validate_success(
        api.activate_league_policy(policy["id"], PROGRAM_ADMIN), 200
    )
    assert activated["status"] == "ACTIVE", (
        "the clock has passed the effective date, so the bound term activates, got "
        f"{activated['status']}"
    )
    assert activated["coverage_posture"] == "OPEN", (
        "a freshly activated term with no claims under it fails every freeze and "
        f"review test, so its posture is OPEN, got {activated['coverage_posture']}"
    )

    # The term is in force now, but these two windows fall outside it.
    validate_error(
        api.create_sanctioned_activity(
            create_sanctioned_activity_payload(
                policy["id"],
                activity_type="PRACTICE",
                venue_name="Wrenfield Gym",
                starts_at="2026-02-28T18:00:00Z",
                ends_at="2026-02-28T20:00:00Z",
            ),
            league_headers,
        ),
        ApiErrorId.ERR_ACTIVITY_OUTSIDE_TERM,
        expected_status=422,
    )
    # 2027-03-01 is the excluded end of the term, so a window reaching into it is out.
    validate_error(
        api.create_sanctioned_activity(
            create_sanctioned_activity_payload(
                policy["id"],
                activity_type="PRACTICE",
                venue_name="Wrenfield Gym",
                starts_at="2027-02-28T23:00:00Z",
                ends_at="2027-03-01T01:00:00Z",
            ),
            league_headers,
        ),
        ApiErrorId.ERR_ACTIVITY_OUTSIDE_TERM,
        expected_status=422,
    )
    assert activities_for_policy(policy["id"]) == [], (
        "neither out-of-term window was written, so the term carries no activity yet"
    )

    enrollment = enroll_participant(
        athlete["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    game = schedule_activity(
        policy["id"],
        league["id"],
        activity_type="GAME",
        venue_name="Wrenfield Field 1",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )
    sanction_activity(game["id"], SANCTIONING_OFFICIAL_USER_ID)
    set_clock("2026-07-12T00:00:00Z")
    report = file_injury_report(
        enrollment["id"],
        game["id"],
        league["id"],
        injury_datetime="2026-07-11T19:00:00Z",
        body_part="TORSO",
        injury_description="back strained diving for a line drive",
        severity_tier="MODERATE",
    )
    verify_injury_report(
        report["id"], VERIFYING_OFFICIAL_USER_ID, "official witnessed the dive"
    )
    claim = discover_claim(report["id"])
    assert claim["adjudication_status"] == "PENDING_COORDINATION", (
        "the verification opened exactly one claim on the coordination runway, got "
        f"{claim['adjudication_status']}"
    )
    assert claim["reserve_amount_cents"] == 250000, (
        "a MODERATE injury reserves 250000 cents, which is well under this term's "
        f"exposure cap for one injury, got {claim['reserve_amount_cents']}"
    )

    # A charge dated before the term began.
    validate_error(
        api.create_provider_bill(
            create_provider_bill_payload(
                claim["id"],
                provider_npi="1400112255",
                provider_name="Wrenfield Orthopedics",
                network_status="IN_NETWORK",
                service_category="PHYSICIAN_OFFICE",
                service_date="2026-02-25",
                billed_charge_cents=60000,
                fee_schedule_amount_cents=42000,
            ),
            EXAMINER,
        ),
        ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_TERM,
        expected_status=422,
    )
    # A charge inside the term but dated the day before the injury itself.
    validate_error(
        api.create_provider_bill(
            create_provider_bill_payload(
                claim["id"],
                provider_npi="1400112255",
                provider_name="Wrenfield Orthopedics",
                network_status="IN_NETWORK",
                service_category="PHYSICIAN_OFFICE",
                service_date="2026-07-10",
                billed_charge_cents=60000,
                fee_schedule_amount_cents=42000,
            ),
            EXAMINER,
        ),
        ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_TERM,
        expected_status=422,
    )
    assert bills_for_claim(claim["id"]) == [], (
        "neither refused charge was written, so the claim carries no bill at all"
    )

    validate_error(
        api.cancel_league_policy(
            policy["id"], PROGRAM_ADMIN, {"cancel_reason": "league folded mid-season"}
        ),
        ApiErrorId.ERR_OPEN_CLAIMS_ON_POLICY,
        expected_status=409,
    )
    final_policy = read_policy(policy["id"])
    assert final_policy["open_claim_count"] == 1, (
        "the one open claim is what blocked the cancellation, got "
        f"{final_policy['open_claim_count']}"
    )
    assert final_policy["status"] == "ACTIVE", (
        f"the refused cancellation left the term ACTIVE, got {final_policy['status']}"
    )
    assert final_policy["coverage_posture"] == "OPEN", (
        "the refused cancellation did not freeze the term, got "
        f"{final_policy['coverage_posture']}"
    )
    assert final_policy["cancel_reason"] is None, (
        "the refused cancellation stored no cancel_reason, got "
        f"{final_policy['cancel_reason']!r}"
    )


def test_a_payment_that_would_drive_paid_loss_past_the_term_aggregate_is_refused(api):
    """PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents. If the layer was not elected, the charge is exactly 0."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.3: "And, uniquely among the operations in this system, enrolling is also blocked when the policy's posture is `CLAIMS_REVIEW`, with `ERR_POLICY_UNDER_CLAIMS_REVIEW`: a term whose loss position has deteriorated may finish the claims it already has but may not take on further covered lives until that position clears."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.6: "On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb."
    PRD §3.7: "`negotiated_amount_cents` branches on the network status. For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`. If either condition fails, `cat_layer_benefit_cents` is exactly zero."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "Two fiscal ceilings then apply, in order."
    PRD §3.8: "The payment must not overdraw its own layer: for a `BASE` payment, the claim's `paid_base_cents` plus this amount must not exceed the frozen `base_layer_benefit_cents`, and for a `CATASTROPHIC` payment, `paid_cat_cents` plus this amount must not exceed the frozen `cat_layer_benefit_cents`."
    PRD §3.8: "Then the term aggregate: the policy's `paid_loss_cents` plus this amount must not exceed its `aggregate_limit_cents`, because the aggregate is a hard ceiling on cash out the door, and a breach is refused with `ERR_AGGREGATE_LIMIT_EXCEEDED`."
    PRD §3.8: "An issued payment takes `status` `ISSUED`, stamps `issued_at` with the logical clock and `issued_by_user_id` with the examiner's `X-User-ID`, and leaves `void_reason` and `voided_at` null."
    PRD §3.8: "The claim's `paid_base_cents` (the sum of `ISSUED` `BASE`-layer amounts on the claim), `paid_cat_cents` (the same for the `CATASTROPHIC` layer) and `paid_to_date_cents` (their sum) are recomputed, and once `paid_to_date_cents` has reached or passed `benefit_payable_cents` the claim moves `APPROVED → PAID`, taking it out of the open set."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up. `paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "The test is inclusive: an incurred loss exactly equal to the aggregate limit freezes the term."
    PRD §2.8: "Otherwise, if the policy's `open_claim_count` is three or more, the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "A `CLAIMS_REVIEW` posture is narrower: it blocks only the writing of *new covered lives*, so enrolling a further athlete is refused with `ERR_POLICY_UNDER_CLAIMS_REVIEW` while claims already in flight continue to be repriced, coordinated, adjudicated and paid."

    Design: Corner/errors/payment_that_would_drive_paid_loss_past_the_aggregate_limit_is_rejected
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Yardley Track Club",
        league_code="YTC-156",
        state_code="NE",
        governing_body_code="USATF",
        contact_email="admin@ytc.example",
    )
    league_headers = make_league_admin_headers(league["id"])
    # A deliberately thin schedule: two paid claims can reach the term aggregate.
    sport = create_sport_classification(
        "baseball",
        sport_code="TRACK_U10",
        sport_name="Track and Field U10",
        hazard_class="CLASS_1_LOW",
        base_rate_per_participant_cents=1200,
        deductible_cents=10000,
        per_injury_limit_cents=400000,
        cat_attachment_point_cents=400000,
        aggregate_limit_cents=500000,
        cat_lifetime_max_cents=500000,
        minimum_participants=10,
        travel_buffer_minutes=30,
        service_category_caps={
            "EMERGENCY_ROOM": 200000,
            "SURGERY": 600000,
            "DIAGNOSTIC_IMAGING": 120000,
            "PHYSICAL_THERAPY": 15000,
            "DENTAL": 100000,
            "AMBULANCE": 80000,
            "PHYSICIAN_OFFICE": 30000,
        },
    )
    policy = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=30,
        coverage_basis_election="FULL_EXCESS_PERMITTED",
        cat_layer_elected=False,
    )
    bind_policy(policy["id"])
    activated = activate_policy(policy["id"])
    assert activated["annual_premium_cents"] == 36000, (
        "thirty athletes sit wholly in the first volume band at a factor of 1.0000 "
        "and a low-hazard sport carries no load, so the term earns 30 x 1200 = 36000 "
        "cents with no catastrophic charge and no volume credit, got "
        f"{activated['annual_premium_cents']}"
    )
    assert activated["aggregate_limit_cents"] == 500000, (
        "the term mirrors the thin aggregate limit off its classification, got "
        f"{activated['aggregate_limit_cents']}"
    )

    athlete_a = add_participant(
        league["id"],
        first_name="Zerlina",
        last_name="Duarte",
        date_of_birth="2017-01-18",
        guardian_email="g56@ytc.example",
    )
    athlete_b = add_participant(
        league["id"],
        first_name="Ambrose",
        last_name="Fitzwilliam",
        date_of_birth="2017-02-19",
        guardian_email="g57@ytc.example",
    )
    # This third athlete is deliberately left off the roster until the loss position
    # has deteriorated.
    athlete_c = add_participant(
        league["id"],
        first_name="Bertram",
        last_name="Nakagawa",
        date_of_birth="2017-03-20",
        guardian_email="g58@ytc.example",
    )
    enrollment_a = enroll_participant(
        athlete_a["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    enrollment_b = enroll_participant(
        athlete_b["id"], policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    practice = schedule_activity(
        policy["id"],
        league["id"],
        activity_type="PRACTICE",
        venue_name="Yardley Oval",
        starts_at="2026-07-11T15:00:00Z",
        ends_at="2026-07-11T17:00:00Z",
    )
    sanction_activity(practice["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")
    report_a = file_injury_report(
        enrollment_a["id"],
        practice["id"],
        league["id"],
        injury_datetime="2026-07-11T16:00:00Z",
        body_part="ANKLE_FOOT",
        injury_description="ankle rolled on the curve",
        severity_tier="MINOR",
    )
    report_b = file_injury_report(
        enrollment_b["id"],
        practice["id"],
        league["id"],
        injury_datetime="2026-07-11T16:20:00Z",
        body_part="KNEE",
        injury_description="knee struck a hurdle",
        severity_tier="MINOR",
    )
    verify_injury_report(
        report_a["id"], VERIFYING_OFFICIAL_USER_ID, "coach witnessed the roll on the curve"
    )
    verify_injury_report(
        report_b["id"], VERIFYING_OFFICIAL_USER_ID, "coach witnessed the hurdle contact"
    )
    claim_a = discover_claim(report_a["id"])
    claim_b = discover_claim(report_b["id"])
    for claim in (claim_a, claim_b):
        assert claim["reserve_amount_cents"] == 50000, (
            "a MINOR injury reserves 50000 cents, which is under this term's "
            "per-injury exposure cap of 400000 with no catastrophic layer bought, got "
            f"{claim['reserve_amount_cents']}"
        )

    opening = read_loss_experience(policy["id"])
    assert opening["open_claim_count"] == 2, (
        f"both claims are on the coordination runway, got {opening['open_claim_count']}"
    )
    assert opening["reserve_cents"] == 100000, (
        f"two open case reserves of 50000 each, got {opening['reserve_cents']}"
    )
    assert opening["paid_loss_cents"] == 0, (
        f"no cash has left the account yet, got {opening['paid_loss_cents']}"
    )
    assert opening["incurred_loss_cents"] == 100000, (
        f"nothing paid plus 100000 reserved, got {opening['incurred_loss_cents']}"
    )
    assert opening["incurred_loss_ratio_bps"] == 27778, (
        "100000 cents of incurred loss against 36000 cents of earned premium is "
        f"27778 basis points once rounded half up, got {opening['incurred_loss_ratio_bps']}"
    )
    assert opening["experience_tier"] == "DECLINE", (
        "a ratio at or above 10000 basis points bands as DECLINE, got "
        f"{opening['experience_tier']}"
    )
    assert opening["coverage_posture"] == "CLAIMS_REVIEW", (
        "with only two open claims it is the loss ratio, not the open count, that "
        f"puts the term under claims review, got {opening['coverage_posture']}"
    )

    # A term under claims review may finish its claims but may not take a new life on.
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                athlete_c["id"], policy["id"], enrolled_on_date="2026-07-12"
            ),
            league_headers,
        ),
        ApiErrorId.ERR_POLICY_UNDER_CLAIMS_REVIEW,
        expected_status=409,
    )
    assert read_participant(athlete_c["id"])["enrolled_policy_count"] == 0, (
        "the refused enrollment wrote nothing, so the third athlete is still on no "
        "roster at all"
    )

    # Repricing, coordinating, adjudicating and paying all continue regardless.
    bill_a = record_provider_bill(
        claim_a["id"],
        provider_npi="1500112266",
        provider_name="Yardley Surgical Center",
        network_status="IN_NETWORK",
        service_category="SURGERY",
        service_date="2026-07-11",
        billed_charge_cents=620000,
        fee_schedule_amount_cents=600000,
    )
    repriced_a = reprice_bill(bill_a["id"])
    assert repriced_a["allowed_amount_cents"] == 600000, (
        "the in-network negotiated amount is 600000 and a MINOR injury leaves the "
        f"600000 surgery cap untouched, got {repriced_a['allowed_amount_cents']}"
    )
    confirm_no_other_coverage(claim_a["id"], "no family health coverage on file")
    approved_a = adjudicate_claim(
        claim_a["id"], "covered practice injury, full-excess basis"
    )
    assert approved_a["adjudication_status"] == "APPROVED", (
        f"the claim is approved for payment, got {approved_a['adjudication_status']}"
    )
    assert approved_a["deductible_applied_cents"] == 20000, (
        "running as program primary doubles the 10000 deductible, got "
        f"{approved_a['deductible_applied_cents']}"
    )
    assert approved_a["benefit_before_limit_cents"] == 580000, (
        "600000 allowed less the doubled deductible, got "
        f"{approved_a['benefit_before_limit_cents']}"
    )
    assert approved_a["base_layer_benefit_cents"] == 400000, (
        "the base layer is capped at the 400000 per-injury limit, got "
        f"{approved_a['base_layer_benefit_cents']}"
    )
    assert approved_a["cat_layer_benefit_cents"] == 0, (
        "this term never bought the catastrophic layer, so that layer funds nothing, "
        f"got {approved_a['cat_layer_benefit_cents']}"
    )
    assert approved_a["benefit_payable_cents"] == 400000, (
        f"400000 from the base layer and nothing above it, got {approved_a['benefit_payable_cents']}"
    )

    payment_a = issue_benefit_payment(claim_a["id"], bill_a["id"], 400000)
    assert payment_a["status"] == "ISSUED", (
        "400000 of cash out the door is at or below the 500000 aggregate, so the "
        f"cheque issues, got {payment_a['status']}"
    )
    assert read_claim(claim_a["id"])["adjudication_status"] == "PAID", (
        "the payment satisfied the whole payable benefit, so the claim closes as PAID"
    )
    midway = read_loss_experience(policy["id"])
    assert midway["paid_loss_cents"] == 400000, (
        f"one cheque of 400000 has cleared, got {midway['paid_loss_cents']}"
    )
    assert midway["reserve_cents"] == 50000, (
        "the paid claim left the open set and released its reserve, leaving only the "
        f"second athlete's 50000, got {midway['reserve_cents']}"
    )
    assert midway["incurred_loss_cents"] == 450000, (
        f"400000 paid plus 50000 still reserved, got {midway['incurred_loss_cents']}"
    )
    assert midway["open_claim_count"] == 1, (
        f"only the second athlete's claim is still open, got {midway['open_claim_count']}"
    )
    assert midway["incurred_loss_ratio_bps"] == 125000, (
        "450000 against 36000 of premium is 125000 basis points, got "
        f"{midway['incurred_loss_ratio_bps']}"
    )
    assert midway["paid_loss_ratio_bps"] == 111111, (
        "400000 against 36000 of premium is 111111 basis points once rounded half up, "
        f"got {midway['paid_loss_ratio_bps']}"
    )
    assert midway["coverage_posture"] == "CLAIMS_REVIEW", (
        "450000 of incurred loss has not yet reached the 500000 aggregate, so the "
        f"term is still only under review, got {midway['coverage_posture']}"
    )

    bill_b = record_provider_bill(
        claim_b["id"],
        provider_npi="1500112266",
        provider_name="Yardley Surgical Center",
        network_status="IN_NETWORK",
        service_category="SURGERY",
        service_date="2026-07-11",
        billed_charge_cents=620000,
        fee_schedule_amount_cents=600000,
    )
    repriced_b = reprice_bill(bill_b["id"])
    assert repriced_b["allowed_amount_cents"] == 600000, (
        f"the second charge prices identically, got {repriced_b['allowed_amount_cents']}"
    )
    confirm_no_other_coverage(claim_b["id"], "no family health coverage on file")
    approved_b = adjudicate_claim(
        claim_b["id"], "second covered practice injury, full-excess basis"
    )
    assert approved_b["benefit_payable_cents"] == 400000, (
        "the second determination is the same 400000 of base-layer benefit, got "
        f"{approved_b['benefit_payable_cents']}"
    )

    # The second claim's own layer would allow all 400000, but the term aggregate
    # would not: 400000 already out the door plus 400000 is 800000.
    validate_error(
        api.create_benefit_payment(
            create_benefit_payment_payload(claim_b["id"], bill_b["id"], 400000),
            EXAMINER,
        ),
        ApiErrorId.ERR_AGGREGATE_LIMIT_EXCEEDED,
        expected_status=422,
    )
    # One cent past the ceiling is still past the ceiling: 400000 + 100001 = 500001.
    validate_error(
        api.create_benefit_payment(
            create_benefit_payment_payload(claim_b["id"], bill_b["id"], 100001),
            EXAMINER,
        ),
        ApiErrorId.ERR_AGGREGATE_LIMIT_EXCEEDED,
        expected_status=422,
    )
    # Exactly on the ceiling is not above it: 400000 + 100000 = 500000.
    payment_b = validate_success(
        api.create_benefit_payment(
            create_benefit_payment_payload(claim_b["id"], bill_b["id"], 100000),
            EXAMINER,
        ),
        201,
    )
    assert payment_b["status"] == "ISSUED", (
        "a payment that lands exactly on the aggregate limit is not a breach of it, "
        f"got {payment_b['status']}"
    )
    assert payment_b["amount_cents"] == 100000, (
        f"the accepted cheque is the 100000 one, got {payment_b['amount_cents']}"
    )

    issued = payments_for_claim(claim_b["id"])
    assert len(issued) == 1, (
        "the two refused payments wrote nothing, so the second claim carries exactly "
        f"one payment, got {len(issued)}"
    )
    assert issued[0]["id"] == payment_b["id"]

    claim_b_after = read_claim(claim_b["id"])
    assert claim_b_after["paid_to_date_cents"] == 100000, (
        f"only 100000 of the second claim's benefit has been paid, got {claim_b_after['paid_to_date_cents']}"
    )
    assert claim_b_after["adjudication_status"] == "APPROVED", (
        "100000 falls short of the 400000 payable, so the second claim stays open at "
        f"APPROVED, got {claim_b_after['adjudication_status']}"
    )

    closing = read_loss_experience(policy["id"])
    assert closing["paid_loss_cents"] == 500000, (
        f"500000 of cash has now left the account, got {closing['paid_loss_cents']}"
    )
    assert closing["reserve_cents"] == 50000, (
        "the second claim is still in the open set, so its reserve still stands, got "
        f"{closing['reserve_cents']}"
    )
    assert closing["incurred_loss_cents"] == 550000, (
        f"500000 paid plus 50000 reserved, got {closing['incurred_loss_cents']}"
    )
    assert closing["coverage_posture"] == "FROZEN", (
        "incurred loss has passed the 500000 aggregate limit, which freezes the term, "
        f"got {closing['coverage_posture']}"
    )
    assert read_policy(policy["id"])["status"] == "ACTIVE", (
        "the freeze is a posture, not a lifecycle change: the term is still ACTIVE"
    )

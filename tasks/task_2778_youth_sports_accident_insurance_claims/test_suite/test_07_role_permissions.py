"""Who may act, and on whose behalf.

Nobody in this program can move an injury from the field to a cheque alone. The
claims desk prices and pays but may not certify a catastrophic injury; the
medical reviewer certifies but may never adjudicate or issue a cent; the official
who sanctioned a game is barred from deciding the injury reports arising from it.
Two of the six roles are entity-backed, so the same role name and the same
endpoint must succeed for one ``X-User-ID`` and be refused for another: a league
administrator is confined to the league whose id it carries, and a guardian to
the single athlete whose id it carries. The tests below thread real league and
participant identifiers through every call, because a made-up identifier would
only ever prove that an unknown row is unreachable.
"""
from test_helpers import (
    BASEBALL_404_ANNUAL_PREMIUM_CENTS,
    SANCTIONING_OFFICIAL_USER_ID,
    THIRD_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    ApiErrorId,
    activate_policy,
    add_family_health_plan,
    add_participant,
    assert_claim,
    assert_family_health_plan,
    assert_injury_report,
    assert_league_policy,
    assert_provider_bill,
    bind_policy,
    claims_for_report,
    create_benefit_payment_payload,
    create_family_health_plan_payload,
    create_league,
    create_participant_payload,
    create_sport_classification,
    file_injury_report,
    make_claims_examiner_headers,
    make_guardian_headers,
    make_league_admin_headers,
    make_league_official_headers,
    make_medical_reviewer_headers,
    make_program_admin_headers,
    quote_policy,
    read_activity,
    read_claim,
    read_injury_report,
    read_policy,
    read_provider_bill,
    record_provider_bill,
    set_clock,
    setup_active_policy,
    setup_sanctioned_activity,
    setup_verified_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_claims_desk_and_medical_reviewer_crossing_into_each_others_exclusive_decisions_are_refused(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "A `ClaimsExaminer` is the program's claims desk: verifying the family's other coverage, recording and repricing provider charges, collecting explanations of benefits, adjudicating claims and issuing or voiding benefit payments."
    PRD §2.1: "An examiner may not certify a catastrophic injury and may not touch the policy lifecycle."
    PRD §2.1: "A `MedicalReviewer` alone may certify — or revoke certification of — a catastrophic injury, which is what unlocks the catastrophic excess layer."
    PRD §2.1: "A reviewer deliberately cannot adjudicate or pay, so the decision that unlocks the dollars and the decision that releases them sit with different people."
    PRD §2.1: "Officials sanction scheduled activities and independently decide injury-report verifications."
    PRD §3.8: "The catastrophic excess layer is not unlocked by arithmetic alone; it takes an independent clinical judgement, and only a `MedicalReviewer` may make it."
    PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "2. **Role authorisation** — the role appears in the endpoint's authorised set (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/claims_desk_and_medical_reviewer_cannot_perform_each_others_exclusives
    """
    # A catastrophic injury verified into an open claim, so a certification and an
    # adjudication are both plausible next steps for somebody.
    bundle = setup_verified_claim(
        league_overrides={
            "name": "Harrowgate Baseball",
            "league_code": "HGB-141",
            "state_code": "DE",
            "governing_body_code": "USYSA",
            "contact_email": "admin@hgb.example",
        },
        participant_overrides={
            "first_name": "Yusuf",
            "last_name": "Bello",
            "date_of_birth": "2015-09-04",
            "guardian_email": "g42@hgb.example",
        },
        activity_overrides={
            "activity_type": "GAME",
            "venue_name": "Harrowgate Field 1",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        report_overrides={
            "body_part": "HEAD_NECK",
            "injury_description": "cervical injury from an outfield collision",
            "severity_tier": "CATASTROPHIC",
        },
        official_attestation="field official witnessed the collision",
    )
    claim = bundle["claim"]
    assert_claim(claim)
    assert claim["adjudication_status"] == "PENDING_COORDINATION", (
        f"a newly opened claim starts at PENDING_COORDINATION, got {claim['adjudication_status']}"
    )

    bill = record_provider_bill(
        claim["id"],
        provider_npi="1199001122",
        provider_name="Harrowgate Trauma Center",
        network_status="IN_NETWORK",
        service_category="SURGERY",
        service_date="2026-07-11",
        billed_charge_cents=2100000,
        fee_schedule_amount_cents=2000000,
    )
    assert_provider_bill(bill)
    assert bill["status"] == "SUBMITTED", (
        f"a recorded charge is not priced at record time, got {bill['status']}"
    )

    # The claims desk reaching for the reviewer's clinical judgement.
    validate_error(
        api.certify_catastrophic(
            claim["id"],
            {"certification_note": "examiner attempting to certify the injury themselves"},
            make_claims_examiner_headers(),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )

    # The reviewer reaching for the desk's adjudication. Coordination has not been
    # settled on this claim, so a role check that ran late would surface
    # ERR_COORDINATION_INCOMPLETE instead.
    validate_error(
        api.adjudicate_claim(
            claim["id"],
            {"examiner_note": "medical reviewer attempting to adjudicate"},
            make_medical_reviewer_headers(),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )

    # The reviewer reaching for the cheque book. The claim is not APPROVED, so a
    # late role check would surface ERR_INVALID_CLAIM_STATE instead.
    validate_error(
        api.create_benefit_payment(
            create_benefit_payment_payload(claim["id"], bill["id"], 100000),
            make_medical_reviewer_headers(),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )

    # An official whose remit is sanctioning and verification reaching for repricing.
    validate_error(
        api.reprice_provider_bill(
            bill["id"], make_league_official_headers(THIRD_OFFICIAL_USER_ID)
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )

    # None of the four refusals moved anything.
    settled_claim = read_claim(claim["id"])
    assert settled_claim["cat_certification_status"] == "NONE", (
        "the refused certification must leave cat_certification_status at NONE, got "
        f"{settled_claim['cat_certification_status']}"
    )
    assert settled_claim["adjudication_status"] == "PENDING_COORDINATION", (
        "the refused adjudication must leave the claim at PENDING_COORDINATION, got "
        f"{settled_claim['adjudication_status']}"
    )
    assert settled_claim["paid_base_cents"] == 0, (
        f"the refused payment must leave paid_base_cents at 0, got {settled_claim['paid_base_cents']}"
    )
    assert read_provider_bill(bill["id"])["status"] == "SUBMITTED", (
        "the refused repricing must leave the charge in SUBMITTED"
    )
    _payments, payment_meta = validate_paginated(
        api.list_benefit_payments(make_claims_examiner_headers(), {"claim_id": claim["id"]})
    )
    assert payment_meta["total_count"] == 0, (
        f"no benefit payment may exist on the claim, got {payment_meta['total_count']}"
    )


def test_league_administrator_addressing_another_leagues_policy_and_roster_is_refused(api):
    """PRD §2.1: "When `X-User-Role` is `LeagueAdministrator`, `X-User-ID` is the `id` of the acting `League`; ownership checks on any addressed resource compare `X-User-ID` to the `League` reached from that resource — directly for a league, through `league_id` for a policy or a participant, through the policy for an enrollment or an activity, through the enrollment and then the policy for an injury report, and through `league_policy_id` for a claim."
    PRD §2.1: "A caller in either role that reaches outside its own subtree is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §2.7: "3. **Ownership** — for the two entity-backed roles, the caller owns the addressed resource (`ERR_OWNERSHIP_MISMATCH`)."
    PRD §2.7: "This applies to every endpoint whose authorised roles include `LeagueAdministrator` or `GuardianPortal`."
    PRD §2.7: "The practical consequence worth internalising is that **authorisation outranks existence, existence outranks state, state outranks safety, safety outranks time, time outranks constraints, and constraints outrank money**."
    PRD §2.7: "A guardian addressing another family's claim gets an ownership failure, not a not-found."

    Design: Corner/rbac/league_administrator_is_confined_to_its_own_league_subtree
    """
    set_clock("2026-03-05T00:00:00Z")
    league_a = create_league(
        name="Ironbridge Baseball",
        league_code="IBB-142",
        state_code="WI",
        governing_body_code="USYSA",
        contact_email="admin@ibb.example",
    )
    league_b = create_league(
        name="Junction City Baseball",
        league_code="JCB-143",
        state_code="WI",
        governing_body_code="USYSA",
        contact_email="admin@jcb.example",
    )
    sport = create_sport_classification("baseball")
    policy_a = quote_policy(league_a["id"], sport["id"])
    bind_policy(policy_a["id"])
    policy_a = activate_policy(policy_a["id"])

    # Identical role, different real league identity on each side.
    admin_of_a = make_league_admin_headers(league_a["id"])
    admin_of_b = make_league_admin_headers(league_b["id"])

    # League B's administrator reading league A's term.
    validate_error(
        api.get_league_policy(policy_a["id"], admin_of_b),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
        expected_status=403,
    )

    # The same role on the same row succeeds for the league that holds it.
    owned = validate_success(api.get_league_policy(policy_a["id"], admin_of_a))
    assert_league_policy(owned)
    assert owned["id"] == policy_a["id"], (
        f"the owning administrator reads its own term, got {owned['id']}"
    )
    assert owned["league_id"] == league_a["id"], (
        f"the term is held by league A, got {owned['league_id']}"
    )

    # Naming league A in the body does not buy league B's administrator a roster
    # write: the ownership rung precedes body reference resolution and shape checks.
    validate_error(
        api.create_participant(
            create_participant_payload(
                league_a["id"],
                first_name="Zaid",
                last_name="Rahimi",
                date_of_birth="2015-10-05",
                guardian_email="g43@ibb.example",
            ),
            admin_of_b,
        ),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
        expected_status=403,
    )

    # The computed loss read is scoped exactly like the plain read.
    validate_error(
        api.get_loss_experience(policy_a["id"], admin_of_b),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
        expected_status=403,
    )

    # The refused roster write left league A's roster empty.
    _rows, roster_meta = validate_paginated(
        api.list_participants(
            make_program_admin_headers(), {"league_id": league_a["id"]}
        )
    )
    assert roster_meta["total_count"] == 0, (
        "the refused create must not have added an athlete to league A, got "
        f"{roster_meta['total_count']}"
    )


def test_guardian_reaching_another_athletes_family_coverage_is_refused(api):
    """PRD §2.1: "When `X-User-Role` is `GuardianPortal`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks compare `X-User-ID` to the participant reached from the addressed resource — directly for a participant, through `participant_id` for a family health plan, and through the claim's enrollment for a claim, a provider bill or a benefit payment."
    PRD §2.1: "A caller in either role that reaches outside its own subtree is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §2.1: "A `GuardianPortal` caller is a parent or guardian acting for a single athlete."
    PRD §2.1: "Guardians file the family's other health coverage and read that athlete's claims, provider bills and payments so the family can see its protected balance."
    PRD §2.7: "3. **Ownership** — for the two entity-backed roles, the caller owns the addressed resource (`ERR_OWNERSHIP_MISMATCH`)."
    PRD §3.6: "Either a `GuardianPortal` caller acting for the athlete or a `ClaimsExaminer` may record a **FamilyHealthPlan** against a `participant_id`."
    PRD §3.6: "The plan's `coverage_state` is derived from the logical clock rather than stored: it is `ACTIVE` when the `effective_date` is at or before the current logical clock **and** either the `termination_date` is absent or the clock is strictly before it; otherwise it is `TERMINATED`."

    Design: Corner/rbac/guardian_portal_sees_only_its_own_athletes_coverage
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Kingsmere Baseball",
        league_code="KMB-144",
        state_code="VA",
        governing_body_code="USYSA",
        contact_email="admin@kmb.example",
    )
    athlete_a = add_participant(
        league["id"],
        first_name="Amara",
        last_name="Osei",
        date_of_birth="2015-11-06",
        guardian_email="g44@kmb.example",
    )
    athlete_b = add_participant(
        league["id"],
        first_name="Bruno",
        last_name="Castellano",
        date_of_birth="2015-12-07",
        guardian_email="g45@kmb.example",
    )
    plan_a = add_family_health_plan(
        athlete_a["id"],
        carrier_name="Old Dominion Health",
        policy_number="OD-77310",
        plan_type="PPO",
        individual_deductible_cents=120000,
        coinsurance_bps=1500,
        effective_date="2026-01-01",
    )
    assert_family_health_plan(plan_a)

    # Identical role, different real athlete identity on each side.
    guardian_of_a = make_guardian_headers(athlete_a["id"])
    guardian_of_b = make_guardian_headers(athlete_b["id"])

    # Athlete B's guardian reading athlete A's coverage.
    validate_error(
        api.get_family_health_plan(plan_a["id"], guardian_of_b),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
        expected_status=403,
    )

    # The same role on the same row succeeds for the athlete's own guardian.
    own_view = validate_success(api.get_family_health_plan(plan_a["id"], guardian_of_a))
    assert own_view["id"] == plan_a["id"], (
        f"athlete A's guardian reads athlete A's plan, got {own_view['id']}"
    )
    assert own_view["participant_id"] == athlete_a["id"], (
        f"the plan belongs to athlete A, got {own_view['participant_id']}"
    )
    assert own_view["coverage_state"] == "ACTIVE", (
        "an effective date of 2026-01-01 with no termination date reads ACTIVE against "
        f"a 2026-03-05 clock, got {own_view['coverage_state']}"
    )

    # Athlete B's guardian filing coverage in athlete A's name.
    validate_error(
        api.create_family_health_plan(
            create_family_health_plan_payload(
                athlete_a["id"],
                carrier_name="Rival Carrier",
                policy_number="RC-00001",
                plan_type="HMO",
                individual_deductible_cents=100000,
                coinsurance_bps=1000,
                effective_date="2026-01-01",
            ),
            guardian_of_b,
        ),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
        expected_status=403,
    )

    # The claims desk carries an opaque identity and is scoped to nobody, so its
    # unfiltered read shows that the refused filing wrote no second plan.
    _plans, plan_meta = validate_paginated(
        api.list_family_health_plans(make_claims_examiner_headers())
    )
    assert plan_meta["total_count"] == 1, (
        "exactly one family health plan may exist after the refused filing, got "
        f"{plan_meta['total_count']}"
    )


def test_official_who_sanctioned_the_game_may_not_decide_its_injury_report(api):
    """PRD §3.5: "Both branches require the report to be in `PENDING_VERIFICATION` and both are subject to the program's central segregation rule: the deciding official's `X-User-ID` must differ from the `sanctioning_official_id` recorded on the linked activity."
    PRD §3.5: "An official who sanctioned an activity may not decide an injury report arising from it, and an attempt is refused with `ERR_OFFICIAL_SEGREGATION_VIOLATION`."
    PRD §3.5: "Returning a report is also subject to segregation of duties — the official sending it back may not be the official who sanctioned the underlying activity."
    PRD §2.7: "15. through 19. **Coverage safety** — the activity is a covered type (`ERR_ACTIVITY_NOT_COVERED`); the activity's sanctioning state permits the operation (`ERR_ACTIVITY_NOT_SANCTIONED`); the acting official is not the one who sanctioned the activity (`ERR_OFFICIAL_SEGREGATION_VIOLATION`); catastrophic certification is only touched on a catastrophic-severity injury (`ERR_SEVERITY_NOT_CATASTROPHIC`); and a determination that reaches into the catastrophic layer requires certification first (`ERR_CAT_CERTIFICATION_REQUIRED`), in exactly that order."
    PRD §3.4: "A `SANCTION` decision additionally requires the governing policy's `status` to be `BOUND` or `ACTIVE` and its posture not to be `FROZEN`; on success the activity moves `PENDING_SANCTION → SANCTIONED` and the deciding official's `X-User-ID` is written to `sanctioning_official_id`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §3.5: "1. The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "In practice this means at least two distinct official identities are needed to move any claim forward — which is the whole point."

    Design: Corner/rbac/the_official_who_sanctioned_an_activity_may_not_verify_its_reports
    """
    bundle = setup_sanctioned_activity(
        league_overrides={
            "name": "Lowfield Baseball",
            "league_code": "LFB-145",
            "state_code": "NC",
            "governing_body_code": "USYSA",
            "contact_email": "admin@lfb.example",
        },
        participant_overrides={
            "first_name": "Cleo",
            "last_name": "Mwangi",
            "date_of_birth": "2016-01-08",
            "guardian_email": "g46@lfb.example",
        },
        activity_overrides={
            "activity_type": "GAME",
            "venue_name": "Lowfield Field 1",
            "starts_at": "2026-07-11T18:00:00Z",
            "ends_at": "2026-07-11T20:00:00Z",
        },
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID,
    )
    assert bundle["activity"]["sanctioning_official_id"] == SANCTIONING_OFFICIAL_USER_ID, (
        "the sanctioning decision records its own official's id, got "
        f"{bundle['activity']['sanctioning_official_id']}"
    )

    set_clock("2026-07-12T00:00:00Z")
    report = file_injury_report(
        bundle["enrollment"]["id"],
        bundle["activity"]["id"],
        bundle["league"]["id"],
        body_part="KNEE",
        injury_description="knee twisted on an awkward tag",
        severity_tier="MODERATE",
    )
    assert_injury_report(report)
    assert report["status"] == "PENDING_VERIFICATION", (
        f"a newly filed report awaits verification, got {report['status']}"
    )

    # Both refusals carry the correct role; only the acting identity disqualifies them.
    sanctioning_official = make_league_official_headers(SANCTIONING_OFFICIAL_USER_ID)
    validate_error(
        api.record_verification_decision(
            report["id"],
            {
                "decision": "VERIFY",
                "official_attestation": "sanctioning official attests to their own game",
            },
            sanctioning_official,
        ),
        ApiErrorId.ERR_OFFICIAL_SEGREGATION_VIOLATION,
        expected_status=422,
    )
    validate_error(
        api.return_injury_report_for_correction(
            report["id"],
            {
                "correction_note": (
                    "sanctioning official asking for more detail on their own game"
                )
            },
            sanctioning_official,
        ),
        ApiErrorId.ERR_OFFICIAL_SEGREGATION_VIOLATION,
        expected_status=422,
    )

    # Neither refusal consumed a correction round or stamped a decision.
    untouched = read_injury_report(report["id"])
    assert untouched["status"] == "PENDING_VERIFICATION", (
        f"the report is still awaiting a decision, got {untouched['status']}"
    )
    assert untouched["correction_round_count"] == 0, (
        "a refused return may not consume a correction round, got "
        f"{untouched['correction_round_count']}"
    )
    assert untouched["verifying_official_id"] is None, (
        "a refused decision may not stamp verifying_official_id, got "
        f"{untouched['verifying_official_id']}"
    )
    assert untouched["verified_at"] is None, (
        f"a refused decision may not stamp verified_at, got {untouched['verified_at']}"
    )
    assert claims_for_report(report["id"]) == [], (
        "no claim may be opened by a refused verification"
    )

    # An independent official carrying the same role decides the very same report.
    decided = validate_success(
        api.record_verification_decision(
            report["id"],
            {
                "decision": "VERIFY",
                "official_attestation": (
                    "independent official reviewed the scorebook and the injury log"
                ),
            },
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        )
    )
    assert decided["status"] == "VERIFIED", (
        f"the independent official's verification stands, got {decided['status']}"
    )
    assert decided["verifying_official_id"] == VERIFYING_OFFICIAL_USER_ID, (
        "the verification records the deciding official's id, got "
        f"{decided['verifying_official_id']}"
    )

    # The sanctioning record itself was never rewritten by the refusals.
    activity = read_activity(bundle["activity"]["id"])
    assert activity["sanctioning_official_id"] == SANCTIONING_OFFICIAL_USER_ID, (
        "sanctioning_official_id still names the official who sanctioned the game, got "
        f"{activity['sanctioning_official_id']}"
    )
    assert activity["status"] == "SANCTIONED", (
        f"the activity is still SANCTIONED, got {activity['status']}"
    )


def test_policy_read_serves_its_three_declared_roles_identically_and_refuses_the_medical_reviewer(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.7: "2. **Role authorisation** — the role appears in the endpoint's authorised set (`ERR_ROLE_NOT_PERMITTED`)."
    PRD §4: "| GET | `/league-policies/{league_policy_id}` | Read one policy including its premium build-up, loss aggregates and renewal block. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |"
    PRD §4: "| GET | `/claims` | List claims, filterable by originating report, policy and enrollment; this is the only discovery channel for a cascade-created claim. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer, MedicalReviewer, GuardianPortal |"
    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."

    Design: Corner/rbac/shared_policy_read_works_for_every_declared_role_and_no_other
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Marchmont Baseball",
            "league_code": "MMB-146",
            "state_code": "IL",
            "governing_body_code": "USYSA",
            "contact_email": "admin@mmb.example",
        }
    )
    policy = bundle["policy"]

    underwriting_view = validate_success(
        api.get_league_policy(policy["id"], make_program_admin_headers())
    )
    league_view = validate_success(
        api.get_league_policy(policy["id"], make_league_admin_headers(bundle["league"]["id"]))
    )
    claims_desk_view = validate_success(
        api.get_league_policy(policy["id"], make_claims_examiner_headers())
    )

    for view in (underwriting_view, league_view, claims_desk_view):
        assert_league_policy(view)
        assert view["id"] == policy["id"], (
            f"every declared role reads the same term, got {view['id']}"
        )
        assert view["status"] == "ACTIVE", (
            f"the term is on risk, got {view['status']}"
        )
        assert view["annual_premium_cents"] == BASEBALL_404_ANNUAL_PREMIUM_CENTS, (
            "the 404-athlete moderate-hazard term is priced at "
            f"{BASEBALL_404_ANNUAL_PREMIUM_CENTS} cents, got {view['annual_premium_cents']}"
        )

    # The shared read is not narrowed per role.
    assert underwriting_view == league_view == claims_desk_view, (
        "the three authorised roles must receive field-for-field identical policy reads"
    )

    # A role outside the endpoint's declared set is refused, even though it is a
    # program insider that holds other reads.
    validate_error(
        api.get_league_policy(policy["id"], make_medical_reviewer_headers()),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )

    # And the reviewer keeps the claim reads it is actually granted.
    reviewer_claims, reviewer_meta = validate_paginated(
        api.list_claims(make_medical_reviewer_headers())
    )
    assert reviewer_meta["total_count"] == 0, (
        f"no claim exists under this term yet, got {reviewer_meta['total_count']}"
    )
    assert reviewer_claims == [], (
        f"the reviewer's claim list is empty, got {reviewer_claims}"
    )

    # Reads never mutate, so the term's version counter has not moved.
    assert read_policy(policy["id"])["version"] == policy["version"], (
        "no read may increment the policy's version, expected "
        f"{policy['version']}, got {read_policy(policy['id'])['version']}"
    )

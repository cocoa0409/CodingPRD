"""Medical clearance: the bounded deferral cycle, pinned-tier gap evaluation,
admissibility matrix, dental gate, and duplicate-active rejection."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    MEDICAL_OFFICER_ID,
    TEST_USERS,
    adjudicate_background,
    api_client,
    assert_legal_overall_consistency,
    create_medical_clearance,
    create_program_with_opening,
    determine_medical_clearance,
    determine_medical_payload,
    get_application,
    get_legal_clearance,
    get_opening,
    make_applicant_headers,
    resubmit_medical_clearance,
    run_applicant_to_accepted,
    create_applicant,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLACER = TEST_USERS["placement_officer_headers"]
MEDIC = TEST_USERS["medical_officer_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def _clearance(app_id):
    clearances = validate_success(
        api_client.list_medical_clearances(app_id, MEDIC), 200)
    assert len(clearances) == 1
    return clearances[0]


class TestDeferralCycle:
    def test_deferral_resubmission_cycle_bounded_at_two(self):
        """PRD §3.5: "Deferral is rationed as well: a `DEFERRED`
        determination requires the clearance's `deferral_count` to still be
        below two, otherwise `ERR_MAX_DEFERRALS_REACHED` (HTTP 422)."
        PRD §3.5: "Resubmission increments `deferral_count`, recomputes
        `max_tier_gap`, and returns the clearance to `SUBMITTED`."
        PRD §3.5: "The clearance is born `SUBMITTED`, with `deferral_count`
        at zero and `reviewed_by` null until the first determination."

        Design: Difficulty/non_linear_state_machine/medical_clearance_deferral_resubmission_cycle
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 3})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(app_id, ana["id"])
        assert clearance["status"] == "SUBMITTED"
        assert clearance["deferral_count"] == 0

        # Loop 1: defer, resubmit (count -> 1, filing replaced wholesale).
        deferred = determine_medical_clearance(clearance["id"], determination="DEFERRED")
        assert deferred["status"] == "DEFERRED"
        back = resubmit_medical_clearance(
            clearance["id"], ana["id"],
            conditions=[{"condition_code": "ASTHMA", "severity": 1,
                         "required_support_tier": 2}],
            dental_status="CLEAR")
        assert back["status"] == "SUBMITTED"
        assert back["deferral_count"] == 1
        assert back["conditions"] == [
            {"condition_code": "ASTHMA", "severity": 1, "required_support_tier": 2}]
        assert back["max_tier_gap"] == 0, \
            "tier-2 condition against pinned tier 3 never exceeds it"

        # Loop 2: defer, resubmit (count -> 2).
        determine_medical_clearance(clearance["id"], determination="DEFERRED")
        back2 = resubmit_medical_clearance(
            clearance["id"], ana["id"], conditions=[], dental_status="CLEAR")
        assert back2["status"] == "SUBMITTED"
        assert back2["deferral_count"] == 2

        # The third defer hits the ration.
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="DEFERRED"),
                MEDIC),
            ApiErrorId.ERR_MAX_DEFERRALS_REACHED, 422)
        current = _clearance(app_id)
        assert current["status"] == "SUBMITTED"
        assert current["deferral_count"] == 2

    def test_resubmit_recomputes_max_tier_gap(self):
        """PRD §3.5: "Every clearance is measured against the pinned tier,
        never the live one: the clearance's `max_tier_gap` is the largest
        amount by which any declared condition's `required_support_tier`
        exceeds the `pinned_country_medical_tier` of the application's
        accepted invitation, or zero when no conditions are declared or none
        exceeds the pinned tier. The gap is computed at creation and
        recomputed at every resubmission, and it constrains which
        determinations a `MedicalOfficer` may reach — even if the country
        program's live `medical_support_tier` has changed since issuance, the
        review never consults it."
        PRD §3.5: "With a gap of exactly one, the admissible outcomes are
        `CLEARED_WITH_ACCOMMODATION` — which additionally requires
        `accommodation_granted` to be true in the request — `DENIED`, or
        `DEFERRED`."

        Design: Difficulty/non_linear_state_machine/medical_clearance_deferral_resubmission_cycle
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 2})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]

        clearance = create_medical_clearance(app_id, ana["id"])
        assert clearance["max_tier_gap"] == 0
        determine_medical_clearance(clearance["id"], determination="DEFERRED")

        # Resubmission replaces the filing wholesale and recomputes the gap.
        resubmitted = resubmit_medical_clearance(
            clearance["id"], ana["id"],
            conditions=[{"condition_code": "ASTHMA_SEVERE", "severity": 2,
                         "required_support_tier": 3}],
            dental_status="CLEAR")
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["deferral_count"] == 1
        assert resubmitted["max_tier_gap"] == 1, "tier 3 vs pinned tier 2"

        # With gap exactly one, plain CLEARED is inadmissible ...
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="CLEARED"),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        # ... and the accommodation outcome requires the grant flag ...
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"],
                determine_medical_payload(determination="CLEARED_WITH_ACCOMMODATION"),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        # ... while a granted accommodation succeeds.
        granted = determine_medical_clearance(
            clearance["id"], determination="CLEARED_WITH_ACCOMMODATION",
            accommodation_granted=True)
        assert granted["status"] == "CLEARED_WITH_ACCOMMODATION"


class TestPinnedTier:
    def test_review_uses_pinned_tier_after_live_tier_drop(self):
        """PRD §2.6: "Later administrative edits to the country program —
        suspending it, closing it, changing its medical support tier,
        training capacity, or language threshold — never rewrite these pinned
        values. Every downstream consumer evaluates against the snapshot:
        medical clearance reviews measure declared conditions against the
        `pinned_country_medical_tier` even if the live program tier has since
        changed, and training enrollment requires the cohort to belong to the
        `pinned_country_program_id` rather than to whatever program the
        opening might later be associated with."

        Design: Difficulty/combinatorial_formula/medical_review_evaluates_pinned_tier_not_live_tier
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 3})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(
            app_id, ana["id"],
            conditions=[{"condition_code": "CARDIAC_STABLE", "severity": 2,
                         "required_support_tier": 3}])
        assert clearance["max_tier_gap"] == 0

        # Drop the live tier from 3 to 1; the review must still see tier 3.
        validate_success(
            api_client.update_country_program(
                program["id"], {"medical_support_tier": 1}, ADMIN), 200)
        assert api_client.get_country_program(
            program["id"], ADMIN).json()["data"]["medical_support_tier"] == 1

        cleared = determine_medical_clearance(clearance["id"], determination="CLEARED")
        assert cleared["status"] == "CLEARED", \
            "gap 0 against the pinned tier 3 admits CLEARED"
        invitation = validate_success(
            api_client.get_invitation(bundle["invitation"]["id"], PLACER), 200)
        assert invitation["pinned_country_medical_tier"] == 3, \
            "the pinned snapshot is immutable"

    def test_review_ignores_live_tier_increase(self):
        """PRD §3.5: "Every clearance is measured against the pinned tier,
        never the live one: the clearance's `max_tier_gap` is the largest
        amount by which any declared condition's `required_support_tier`
        exceeds the `pinned_country_medical_tier` of the application's
        accepted invitation, or zero when no conditions are declared or none
        exceeds the pinned tier. The gap is computed at creation and
        recomputed at every resubmission, and it constrains which
        determinations a `MedicalOfficer` may reach — even if the country
        program's live `medical_support_tier` has changed since issuance, the
        review never consults it."
        PRD §3.5: "With a gap of two or more, only `DENIED` or `DEFERRED`
        remain."

        Design: Difficulty/combinatorial_formula/medical_review_evaluates_pinned_tier_not_live_tier
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 1})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(
            app_id, ana["id"],
            conditions=[{"condition_code": "CARDIAC_MONITORED", "severity": 3,
                         "required_support_tier": 3}])
        assert clearance["max_tier_gap"] == 2, "tier 3 vs pinned tier 1"

        # Raise the live tier to 3: an implementation consulting the live
        # tier would now admit CLEARED; the pinned tier forbids it.
        validate_success(
            api_client.update_country_program(
                program["id"], {"medical_support_tier": 3}, ADMIN), 200)
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="CLEARED"),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"],
                determine_medical_payload(
                    determination="CLEARED_WITH_ACCOMMODATION",
                    accommodation_granted=True),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        # Only DENIED or DEFERRED remain admissible.
        denied = determine_medical_clearance(clearance["id"], determination="DENIED")
        assert denied["status"] == "DENIED"


class TestDeterminationGates:
    def test_medical_duplicate_active_clearance_rejected(self):
        """PRD §3.5: "Creation requires the application to be `ACCEPTED` —
        otherwise `ERR_INVALID_APPLICATION_STATE` — and forbids a second
        active clearance: if a medical clearance in `SUBMITTED` or `DEFERRED`
        already exists for the application, the attempt fails with
        `ERR_DUPLICATE_ACTIVE_CLEARANCE` (HTTP 409)."

        Design: Corner/state_machines/medical_duplicate_active_clearance_rejected
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(app_id, ana["id"])

        validate_error(
            api_client.create_medical_clearance(
                {"application_id": app_id, "conditions": [], "dental_status": "CLEAR"},
                make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_DUPLICATE_ACTIVE_CLEARANCE, 409)
        listed = validate_success(
            api_client.list_medical_clearances(app_id, MEDIC), 200)
        assert len(listed) == 1
        assert listed[0]["id"] == clearance["id"]
        assert listed[0]["status"] == "SUBMITTED"

    def test_medical_gap_two_must_deny(self):
        """PRD §3.5: "With a gap of two or more, only `DENIED` or `DEFERRED`
        remain. Any inadmissible pairing is rejected with
        `ERR_ACCOMMODATION_DETERMINATION_INVALID` (HTTP 422): an accommodation
        outcome without a gap of exactly one, an accommodation outcome
        without the grant flag, or a cleared outcome the gap forbids."
        PRD §3.5: "A `DENIED` determination fires the full denial cascade:
        the application's accepted invitation becomes `RESCINDED`; that
        rescission returns the application from `ACCEPTED` to `UNDER_REVIEW`
        and releases the committed seat, reopening the opening from `FILLED`
        to `OPEN` if the committed count has fallen below `seats_total`; and
        the application's legal clearance lifecycle becomes `VOID`."

        Design: Corner/state_machines/medical_gap_two_must_deny
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 1})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(
            app_id, ana["id"],
            conditions=[{"condition_code": "CARDIAC_MONITORED", "severity": 3,
                         "required_support_tier": 3}])
        assert clearance["max_tier_gap"] == 2

        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"],
                determine_medical_payload(
                    determination="CLEARED_WITH_ACCOMMODATION",
                    accommodation_granted=True),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="CLEARED"),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        assert _clearance(app_id)["status"] == "SUBMITTED", \
            "rejected determinations must not move the clearance"

        denied = determine_medical_clearance(clearance["id"], determination="DENIED")
        assert denied["status"] == "DENIED"
        # The denial cascade fires.
        invitation = validate_success(
            api_client.get_invitation(bundle["invitation"]["id"], PLACER), 200)
        assert invitation["status"] == "RESCINDED"
        assert get_application(app_id)["status"] == "UNDER_REVIEW"
        assert get_opening(opening["id"])["seats_committed"] == 0

    def test_medical_gap_one_requires_accommodation(self):
        """PRD §3.5: "With a gap of exactly one, the admissible outcomes are
        `CLEARED_WITH_ACCOMMODATION` — which additionally requires
        `accommodation_granted` to be true in the request — `DENIED`, or
        `DEFERRED`."
        PRD §3.5: "Determination acts only on a `SUBMITTED` clearance —
        anything else fails with `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` — and
        records the acting officer's `X-User-ID` in `reviewed_by`."

        Design: Corner/state_machines/medical_gap_one_requires_accommodation
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 2})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(
            app_id, ana["id"],
            conditions=[{"condition_code": "ASTHMA_SEVERE", "severity": 2,
                         "required_support_tier": 3}])
        assert clearance["max_tier_gap"] == 1

        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="CLEARED"),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"],
                determine_medical_payload(determination="CLEARED_WITH_ACCOMMODATION"),
                MEDIC),
            ApiErrorId.ERR_ACCOMMODATION_DETERMINATION_INVALID, 422)

        granted = determine_medical_clearance(
            clearance["id"], determination="CLEARED_WITH_ACCOMMODATION",
            accommodation_granted=True)
        assert granted["status"] == "CLEARED_WITH_ACCOMMODATION"
        assert granted["reviewed_by"] == MEDICAL_OFFICER_ID
        # No denial, so no cascade: the acceptance stands.
        assert get_application(app_id)["status"] == "ACCEPTED"
        invitation = validate_success(
            api_client.get_invitation(bundle["invitation"]["id"], PLACER), 200)
        assert invitation["status"] == "ACCEPTED"

    def test_dental_needs_treatment_blocks_clearance(self):
        """PRD §3.5: "Independently, a `dental_status` of `NEEDS_TREATMENT`
        forbids both cleared outcomes and surfaces
        `ERR_DENTAL_TREATMENT_PENDING` (HTTP 422)."
        PRD §3.5: "the applicant may resubmit a `DEFERRED` clearance —
        resubmitting from any other clearance state violates the state guard
        (HTTP 409), and the application must remain `ACCEPTED` or the request
        fails with `ERR_INVALID_APPLICATION_STATE` — supplying fresh
        `conditions` and `dental_status`, which replace the previous filing
        wholesale."

        Design: Corner/state_machines/dental_needs_treatment_blocks_clearance
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 3})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(
            app_id, ana["id"], conditions=[], dental_status="NEEDS_TREATMENT")

        # Zero conditions (gap 0), yet the dental gate blocks CLEARED.
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="CLEARED"),
                MEDIC),
            ApiErrorId.ERR_DENTAL_TREATMENT_PENDING, 422)

        # Defer, fix the dental filing, and the clearance can complete.
        determine_medical_clearance(clearance["id"], determination="DEFERRED")
        resubmitted = resubmit_medical_clearance(
            clearance["id"], ana["id"], conditions=[], dental_status="CLEAR")
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["deferral_count"] == 1
        cleared = determine_medical_clearance(clearance["id"], determination="CLEARED")
        assert cleared["status"] == "CLEARED"

    def test_determine_deferred_clearance_not_reviewable(self):
        """PRD §3.5: "Determination acts only on a `SUBMITTED` clearance —
        anything else fails with `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` — and
        records the acting officer's `X-User-ID` in `reviewed_by`."

        Design: Corner/state_machines/determine_deferred_clearance_not_reviewable
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = create_medical_clearance(app_id, ana["id"])
        determine_medical_clearance(clearance["id"], determination="DEFERRED")

        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="CLEARED"),
                MEDIC),
            ApiErrorId.ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE, 409)
        current = _clearance(app_id)
        assert current["status"] == "DEFERRED"
        assert current["deferral_count"] == 0


class TestDenialCascade:
    def test_medical_denial_cascades_and_reopens_filled_opening(self):
        """PRD §3.5: "A `DENIED` determination fires the full denial cascade:
        the application's accepted invitation becomes `RESCINDED`; that
        rescission returns the application from `ACCEPTED` to `UNDER_REVIEW`
        and releases the committed seat, reopening the opening from `FILLED`
        to `OPEN` if the committed count has fallen below `seats_total`; and
        the application's legal clearance lifecycle becomes `VOID`."
        PRD §3.6: "A derived `overall_status` summarizes the pair: `VOID`
        when the clearance's `lifecycle` is `VOID`; otherwise `DENIED` when
        the background is `ADVERSE` or the suitability `UNFAVORABLE`;
        otherwise `CLEARED` when the background is `CLEAR` and the
        suitability `FAVORABLE`; otherwise still `PENDING`."

        Design: Difficulty/transitive_cascade/medical_denial_cascades_invitation_application_opening_legal
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 3},
            opening_overrides={"seats_total": 1})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        # The single seat is committed: the opening is FILLED.
        filled = get_opening(opening["id"])
        assert filled["status"] == "FILLED"
        assert filled["seats_committed"] == 1

        clearance = create_medical_clearance(
            app_id, ana["id"],
            conditions=[{"condition_code": "CARDIAC_STABLE", "severity": 2,
                         "required_support_tier": 3}])
        # The legal dimension was partially adjudicated before the denial.
        adjudicate_background(bundle["legal_clearance"]["id"], outcome="CLEAR")

        denied = determine_medical_clearance(clearance["id"], determination="DENIED")
        assert denied["status"] == "DENIED"

        # Link 1: the accepted invitation is rescinded.
        invitation = validate_success(
            api_client.get_invitation(bundle["invitation"]["id"], PLACER), 200)
        assert invitation["status"] == "RESCINDED"
        # Link 2: the application returns to the matching pool.
        assert get_application(app_id)["status"] == "UNDER_REVIEW"
        # Link 3: the committed seat is released; FILLED reopens to OPEN.
        after = get_opening(opening["id"])
        assert after["seats_committed"] == 0
        assert after["status"] == "OPEN"
        # Link 3': the legal clearance is voided.
        legal = get_legal_clearance(app_id)
        assert legal["lifecycle"] == "VOID"
        assert legal["overall_status"] == "VOID"
        assert_legal_overall_consistency(legal)

    def test_medical_denial_releases_committed_seat_below_capacity(self):
        """PRD §3.5: "A `DENIED` determination fires the full denial cascade:
        the application's accepted invitation becomes `RESCINDED`; that
        rescission returns the application from `ACCEPTED` to `UNDER_REVIEW`
        and releases the committed seat, reopening the opening from `FILLED`
        to `OPEN` if the committed count has fallen below `seats_total`; and
        the application's legal clearance lifecycle becomes `VOID`."

        Design: Difficulty/transitive_cascade/medical_denial_cascades_invitation_application_opening_legal
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 3},
            opening_overrides={"seats_total": 2})
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        # One of two seats committed: the opening never left OPEN.
        before = get_opening(opening["id"])
        assert before["status"] == "OPEN"
        assert before["seats_committed"] == 1

        clearance = create_medical_clearance(
            app_id, ana["id"],
            conditions=[{"condition_code": "CARDIAC_STABLE", "severity": 2,
                         "required_support_tier": 3}])
        denied = determine_medical_clearance(clearance["id"], determination="DENIED")
        assert denied["status"] == "DENIED"

        invitation = validate_success(
            api_client.get_invitation(bundle["invitation"]["id"], PLACER), 200)
        assert invitation["status"] == "RESCINDED"
        assert get_application(app_id)["status"] == "UNDER_REVIEW"
        after = get_opening(opening["id"])
        assert after["seats_committed"] == 0, "the committed seat is released"
        assert after["status"] == "OPEN"
        legal = validate_success(
            api_client.list_legal_clearances(app_id, LEGAL), 200)[0]
        assert legal["lifecycle"] == "VOID"
        assert legal["overall_status"] == "VOID"

"""Field, cross-reference, window, quorum and ownership rules, each on its own code."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import (
    APPEAL_WINDOW_CLOSES,
    CYCLE_CALENDAR,
    DECISION_CLOCK,
    ISSUANCE_CLOCK,
    SCORE_ONE_SHEET,
    SCORE_TWO_SHEETS,
    SHEET_REV_1,
)
from test_helpers.factories import (
    batching_cycle_payload,
    certificate_payload,
    letter_of_intent_payload,
    progress_report_payload,
    public_comment_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    PUBLIC,
    advance_cycle,
    file_letter_of_intent,
    file_score_sheet,
    refresh_applicant,
    refresh_application,
    refresh_certificate,
    refresh_cycle,
    refresh_health_service_area,
    seed_applicant,
    seed_application_submitted,
    seed_batching_cycle,
    seed_comparative_review,
    seed_decided_cycle,
    seed_draft_application,
    seed_issued_certificate,
    seed_reference_data,
    seed_second_applicant,
    seed_two_score_sheets,
    set_clock,
)
from test_helpers.test_users import (
    REVIEWER_USER_ID_1,
    make_applicant_headers,
    make_decision_officer_headers,
)

COMMENT_CLOSE_INSTANT = "2026-08-25T00:00:00Z"
ONE_SECOND_PAST_COMMENT_CLOSE = "2026-08-25T00:00:01Z"
LOI_DEADLINE = "2026-08-10T00:00:00Z"
ONE_SECOND_PAST_LOI_DEADLINE = "2026-08-10T00:00:01Z"
INTERVENTION_DEADLINE = "2026-08-28T00:00:00Z"
ONE_SECOND_PAST_INTERVENTION_DEADLINE = "2026-08-28T00:00:01Z"
INSIDE_APPEAL_WINDOW_CLOCK = "2026-09-11T00:00:00Z"


class TestCycleWindowOrdering:
    def test_an_application_deadline_before_the_letter_deadline_is_refused(self):
        """The two opening bounds are inverted, so no cycle is created at all.

        PRD §3.2: "The six instants must be ordered so that `loi_deadline_at` is
        strictly before `application_deadline_at`, and from there each is at or
        before the next: `application_deadline_at` at or before
        `comment_period_closes_at`, `comment_period_closes_at` at or before
        `intervention_deadline_at`, `intervention_deadline_at` at or before
        `completeness_deadline_at`, and `completeness_deadline_at` at or before
        `decision_deadline_at`."
        PRD §3.2: "A calendar that breaks the ordering is refused with
        `ERR_INVALID_CYCLE_WINDOW`."

        Design: Corner/validations/cycle_with_application_deadline_before_loi_deadline_returns_invalid_cycle_window
        """
        reference = seed_reference_data()

        response = api_client.create_batching_cycle(
            batching_cycle_payload(
                reference["hsa"]["id"],
                reference["formula"]["id"],
                loi_deadline_at="2026-08-20T00:00:00Z",
                application_deadline_at="2026-08-10T00:00:00Z",
            ),
            ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_WINDOW, 422)
        _, meta = validate_paginated(
            api_client.list_batching_cycles(
                ADMIN, params={"hsa_id": reference["hsa"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestLetterOfIntentFilingRules:
    def test_a_second_letter_in_the_same_cycle_is_a_duplicate_until_withdrawn(self):
        """FILED blocks the second filing; WITHDRAWN releases the slot.

        PRD §2.10: "Seven uniqueness rules share one rejection code,
        `ERR_DUPLICATE_LOI` at HTTP 409, and together they define what the
        programme treats as a duplicate filing: one planning area per `code`; one
        hearing room per `name`; one applicant per `legal_name`; one `ACTIVE` score
        sheet per combination of `application_id` and `reviewer_user_id`; one letter
        of intent per combination of `applicant_id` and `batching_cycle_id` that has
        not been withdrawn — in practice a letter still in `FILED` or already
        `CONVERTED` blocks a second filing while a `WITHDRAWN` letter does not; one
        application per `loi_id`; and one certificate per `application_id` whose
        `lifecycle_status` is `ISSUED`, `IMPLEMENTED` or `SUSPENDED`."
        PRD §3.3: "A second non-withdrawn letter from the same applicant in the same
        cycle is refused with `ERR_DUPLICATE_LOI`, and an applicant whose `standing`
        is not `GOOD` cannot file at all, receiving
        `ERR_APPLICANT_STANDING_RESTRICTED`."

        Design: Corner/validations/second_letter_of_intent_by_the_same_applicant_in_one_cycle_returns_duplicate_loi
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        world["applicant"] = applicant
        first = file_letter_of_intent(world, applicant)
        second_payload = letter_of_intent_payload(
            applicant["id"],
            world["hsa"]["id"],
            world["cycle"]["id"],
            project_description="Alternative 8-bed proposal",
            capital_cost_cents=600000000,
            bed_delta=8,
        )
        headers = make_applicant_headers(applicant["id"])

        response = api_client.create_letter_of_intent(second_payload, headers)

        validate_error(response, ApiErrorId.ERR_DUPLICATE_LOI, 409)
        _, meta = validate_paginated(
            api_client.list_letters_of_intent(
                ADMIN, params={"batching_cycle_id": world["cycle"]["id"]}
            )
        )
        assert meta["total_count"] == 1

        get_success_data(
            api_client.withdraw_letter_of_intent(
                first["id"], {"reason": "Replaced by a smaller proposal"}, headers
            )
        )
        retry = get_success_data(
            api_client.create_letter_of_intent(second_payload, headers), 201
        )
        assert retry["capital_cost_cents"] == 600000000

    def test_a_letter_whose_service_type_differs_from_the_cycle_is_incoherent(self):
        """The enum value is valid; it just does not match the addressed cycle.

        PRD §3.3: "The letter's `service_type` must equal the cycle's
        `service_type`, or the filing is refused with `ERR_SERVICE_TYPE_MISMATCH`."
        PRD §2.8: "**Service-type coherence.** A letter of intent's `service_type`
        equals the addressed cycle's `service_type`, and a cycle's `service_type`
        equals the pinned formula's `service_type` — otherwise
        `ERR_SERVICE_TYPE_MISMATCH` (422)."

        Design: Corner/validations/letter_of_intent_whose_service_type_differs_from_the_cycle_returns_service_type_mismatch
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()

        response = api_client.create_letter_of_intent(
            letter_of_intent_payload(
                applicant["id"],
                world["hsa"]["id"],
                world["cycle"]["id"],
                service_type="PSYCHIATRIC_BEDS",
                project_description="20-bed behavioural health unit",
                capital_cost_cents=900000000,
                bed_delta=20,
            ),
            make_applicant_headers(applicant["id"]),
        )

        body = validate_error(response, ApiErrorId.ERR_SERVICE_TYPE_MISMATCH, 422)
        assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST
        _, meta = validate_paginated(
            api_client.list_letters_of_intent(
                ADMIN, params={"batching_cycle_id": world["cycle"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_letter_deadline_is_inclusive_to_the_second(self):
        """Exactly at the deadline is accepted; one second later is closed.

        PRD §3.3: "Filing after the cycle's `loi_deadline_at`, or into a cycle that
        is no longer `OPEN_FOR_LOI`, is refused with `ERR_LOI_WINDOW_CLOSED`."
        PRD §3.2: "A cycle begins life at `OPEN_FOR_LOI` and moves through its
        stages one step at a time, driven by an `IntakeAnalyst` who names the
        destination as `to_status`."

        Design: Corner/validations/letter_of_intent_filed_one_second_past_the_loi_deadline_returns_loi_window_closed
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        payload = letter_of_intent_payload(
            applicant["id"], world["hsa"]["id"], world["cycle"]["id"]
        )
        headers = make_applicant_headers(applicant["id"])
        set_clock(ONE_SECOND_PAST_LOI_DEADLINE)
        assert refresh_cycle(world["cycle"]["id"])["status"] == "OPEN_FOR_LOI"

        response = api_client.create_letter_of_intent(payload, headers)

        validate_error(response, ApiErrorId.ERR_LOI_WINDOW_CLOSED, 409)
        _, meta = validate_paginated(
            api_client.list_letters_of_intent(
                ADMIN, params={"batching_cycle_id": world["cycle"]["id"]}
            )
        )
        assert meta["total_count"] == 0

        set_clock(LOI_DEADLINE)
        on_time = get_success_data(
            api_client.create_letter_of_intent(payload, headers), 201
        )
        assert_instant_equals(on_time["filed_at"], LOI_DEADLINE)


class TestApplicantOwnership:
    def test_another_organizations_user_id_cannot_submit_the_filing(self):
        """The role is right and the state is right; the identity is not.

        PRD §3.4: "Only the owning applicant may submit, or the request fails with
        `ERR_NOT_FILING_OWNER`; the applicant's `standing` must be `GOOD`, or
        `ERR_APPLICANT_STANDING_RESTRICTED` applies; and the logical clock must be
        at or before the cycle's `application_deadline_at`, or the request is
        refused with `ERR_FILING_WINDOW_CLOSED`."
        PRD §2.8: "**Applicant ownership.** `X-User-ID` equals the applicant of
        record for the target — otherwise `ERR_NOT_FILING_OWNER` (403)."

        Design: Corner/validations/applicant_submitting_another_organizations_application_returns_not_filing_owner
        """
        world = seed_draft_application()
        advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
        intruder = seed_second_applicant()

        response = api_client.submit_application(
            world["application"]["id"], make_applicant_headers(intruder["id"])
        )

        validate_error(response, ApiErrorId.ERR_NOT_FILING_OWNER, 403)
        unchanged = refresh_application(world["application"]["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["version"] == world["application"]["version"]

        submitted = get_success_data(
            api_client.submit_application(
                world["application"]["id"],
                make_applicant_headers(world["applicant"]["id"]),
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"


class TestParticipationWindows:
    def test_the_comment_period_closes_inclusively(self):
        """A comment at the closing instant lands; one second later it does not.

        PRD §3.6: "A comment filed after the cycle's `comment_period_closes_at` is
        refused with `ERR_COMMENT_PERIOD_CLOSED`; a comment filed exactly at that
        instant is accepted."

        Design: Corner/validations/public_comment_at_exactly_the_close_instant_passes_and_one_second_later_is_closed
        """
        world = seed_application_submitted()
        assert (
            CYCLE_CALENDAR["comment_period_closes_at"] == COMMENT_CLOSE_INSTANT
        )
        set_clock(COMMENT_CLOSE_INSTANT)
        on_time = get_success_data(
            api_client.create_public_comment(
                world["application"]["id"],
                public_comment_payload(
                    commenter_display_name="Ward 4 Neighbourhood Council",
                    stance="SUPPORT",
                    body="Filed at the closing instant.",
                ),
                PUBLIC,
            ),
            201,
        )
        assert on_time["stance"] == "SUPPORT"
        set_clock(ONE_SECOND_PAST_COMMENT_CLOSE)

        response = api_client.create_public_comment(
            world["application"]["id"],
            public_comment_payload(
                commenter_display_name="Ward 4 Neighbourhood Council",
                stance="SUPPORT",
                body="One second too late.",
            ),
            PUBLIC,
        )

        validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_CLOSED, 409)
        _, meta = validate_paginated(
            api_client.list_public_comments(world["application"]["id"], PUBLIC)
        )
        assert meta["total_count"] == 1

    def test_the_intervention_deadline_is_inclusive_to_the_second(self):
        """One second past the deadline writes no intervention row.

        PRD §3.6: "The request must arrive at or before the cycle's
        `intervention_deadline_at`, otherwise `ERR_INTERVENTION_DEADLINE_PASSED`,
        and a `BARRED` applicant may not file it at all."

        Design: Corner/validations/intervention_filed_one_second_past_the_deadline_returns_intervention_deadline_passed
        """
        world = seed_application_submitted()
        affected_party = seed_second_applicant()
        assert (
            CYCLE_CALENDAR["intervention_deadline_at"] == INTERVENTION_DEADLINE
        )
        set_clock(ONE_SECOND_PAST_INTERVENTION_DEADLINE)

        response = api_client.create_intervention(
            {
                "application_id": world["application"]["id"],
                "affected_party_applicant_id": affected_party["id"],
                "grounds": "Lakeview serves the same census tracts",
                "requested_hearing": True,
            },
            make_applicant_headers(affected_party["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INTERVENTION_DEADLINE_PASSED, 409)
        _, meta = validate_paginated(
            api_client.list_interventions(
                ADMIN, params={"application_id": world["application"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_an_applicant_cannot_intervene_against_its_own_filing(self):
        """Party eligibility, not timing: the window is wide open.

        PRD §3.6: "Two eligibility rules apply, both reported as
        `ERR_NOT_AFFECTED_PARTY`: the `affected_party_applicant_id` must differ from
        the target application's own `applicant_id`, since a provider cannot
        intervene against itself, and it must equal the caller's `X-User-ID`, since a
        provider cannot intervene on another's behalf."
        PRD §2.8: "**Affected-party eligibility.** An intervention's
        `affected_party_applicant_id` must differ from the target application's
        `applicant_id`; an appeal's `appellant_applicant_id` must be either the
        application's own `applicant_id` or the `affected_party_applicant_id` of a
        `GRANTED` intervention on that application."

        Design: Corner/validations/intervention_naming_the_applications_own_applicant_returns_not_affected_party
        """
        world = seed_application_submitted()
        applicant = world["applicant"]

        response = api_client.create_intervention(
            {
                "application_id": world["application"]["id"],
                "affected_party_applicant_id": applicant["id"],
                "grounds": "We wish to intervene in our own filing",
                "requested_hearing": False,
            },
            make_applicant_headers(applicant["id"]),
        )

        validate_error(response, ApiErrorId.ERR_NOT_AFFECTED_PARTY, 403)
        _, meta = validate_paginated(
            api_client.list_interventions(
                ADMIN, params={"application_id": world["application"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestComparativeDecisionPreconditions:
    def test_a_single_active_sheet_does_not_meet_the_quorum(self):
        """The score exists but one reviewer's opinion is not enough to decide.

        PRD §3.7: "Every candidate must have at least 2 `ACTIVE` score sheets — the
        programme will not decide on a single reviewer's opinion — or
        `ERR_INSUFFICIENT_SCORE_SHEETS`."
        PRD §2.8: "**Comparative-review quorum and pool.** The candidate set is
        non-empty (`ERR_NO_ELIGIBLE_APPLICATIONS`, 422); every candidate has at
        least 2 `ACTIVE` score sheets (`ERR_INSUFFICIENT_SCORE_SHEETS`, 422); no
        application of the cycle is still `SUBMITTED` or `COMPLETENESS_REVIEW` when
        advancing to `COMPARATIVE_REVIEW` (`ERR_CYCLE_HAS_UNRESOLVED_APPLICATIONS`,
        409); and every `GRANTED` intervention that demanded a hearing has a `HELD`
        hearing in the cycle (`ERR_MANDATORY_HEARING_NOT_HELD`, 409)."

        Design: Corner/validations/comparative_decision_with_only_one_score_sheet_returns_insufficient_score_sheets
        """
        world = seed_comparative_review()
        file_score_sheet(world["application"], SHEET_REV_1, REVIEWER_USER_ID_1)
        application = refresh_application(world["application"]["id"])
        assert application["score_sheet_count"] == 1
        assert application["comparative_score"] == SCORE_ONE_SHEET
        set_clock(DECISION_CLOCK)

        response = api_client.run_comparative_decision(
            world["cycle"]["id"],
            {"decision_note": "Attempted decision on a single sheet"},
            OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SCORE_SHEETS, 422)
        cycle = refresh_cycle(world["cycle"]["id"])
        assert cycle["status"] == "COMPARATIVE_REVIEW"
        assert cycle["unallocated_bed_need"] == 19
        after = refresh_application(world["application"]["id"])
        assert after["status"] == "COMPARATIVE_REVIEW"
        assert after["allocated_bed_count"] == 0

    def test_an_officer_who_scored_a_candidate_may_not_decide_the_batch(self):
        """Quorum, timing and role are satisfied; the user identity collides.

        PRD §3.7: "And the acting officer's `X-User-ID` must not equal the
        `reviewer_user_id` of any `ACTIVE` score sheet on any candidate
        application, or `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.9: "First, the `DecisionOfficer` running a cycle's comparative
        decision must not appear as the `reviewer_user_id` of any `ACTIVE` score
        sheet on any candidate application of that cycle."
        PRD §2.9: "A user who scored even one competing application in the batch is
        disqualified from deciding the batch."

        Design: Corner/validations/decision_officer_who_scored_a_candidate_cannot_run_the_comparative_decision
        """
        world = seed_two_score_sheets()
        application = refresh_application(world["application"]["id"])
        assert application["score_sheet_count"] == 2
        assert application["comparative_score"] == SCORE_TWO_SHEETS
        set_clock(DECISION_CLOCK)

        response = api_client.run_comparative_decision(
            world["cycle"]["id"],
            {"decision_note": "Officer is also a scorer"},
            make_decision_officer_headers(REVIEWER_USER_ID_1),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert refresh_cycle(world["cycle"]["id"])["status"] == "COMPARATIVE_REVIEW"
        blocked = refresh_application(world["application"]["id"])
        assert blocked["status"] == "COMPARATIVE_REVIEW"
        assert blocked["decision_at"] is None

        cycle = get_success_data(
            api_client.run_comparative_decision(
                world["cycle"]["id"], {"decision_note": "Decided by the officer"}, OFFICER
            ),
            200,
        )
        assert cycle["status"] == "DECIDED"

    def test_a_stale_formula_pin_blocks_the_decision_until_the_need_is_rerun(self):
        """Everything else is in order; the pin has drifted from the formula.

        PRD §2.9: "A stale pin does not block intake work, but it does block the
        comparative decision, which is refused with `ERR_FORMULA_VERSION_STALE`
        (HTTP 409) until the cycle is re-pinned and its need re-run."
        PRD §3.7: "The cycle's `pinned_formula_version` must still equal the current
        `version` of its formula, or `ERR_FORMULA_VERSION_STALE`."

        Design: Corner/validations/comparative_decision_against_an_amended_formula_returns_formula_version_stale
        """
        world = seed_two_score_sheets()
        assert world["cycle"]["pinned_formula_version"] == 1
        amended = get_success_data(
            api_client.amend_state_plan_formula(
                world["formula"]["id"], {"use_rate_per_1000": 110.0}, ADMIN
            )
        )
        assert amended["version"] == 2
        set_clock(DECISION_CLOCK)

        response = api_client.run_comparative_decision(
            world["cycle"]["id"],
            {"decision_note": "Decision attempted on a stale pin"},
            OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_FORMULA_VERSION_STALE, 409)
        blocked_cycle = refresh_cycle(world["cycle"]["id"])
        assert blocked_cycle["status"] == "COMPARATIVE_REVIEW"
        assert blocked_cycle["pinned_formula_version"] == 1
        assert (
            refresh_application(world["application"]["id"])["status"]
            == "COMPARATIVE_REVIEW"
        )

        repinned = get_success_data(
            api_client.recompute_need(world["cycle"]["id"], ADMIN)
        )
        assert repinned["unmet_bed_need_at_open"] == 28
        decided = get_success_data(
            api_client.run_comparative_decision(
                world["cycle"]["id"], {"decision_note": "Decided on a fresh pin"}, OFFICER
            ),
            200,
        )
        assert decided["status"] == "DECIDED"


class TestCertificateAndReportingLimits:
    def test_a_certificate_may_not_issue_while_the_appeal_window_is_open(self):
        """One day into the 30-day window, the authorisation is withheld.

        PRD §3.8: "The logical clock must be strictly later than the application's
        `appeal_window_closes_at`, because the state does not hand out an
        authorisation while it can still be appealed; issuing too early is refused
        with `ERR_APPEAL_WINDOW_OPEN`."
        PRD §3.8: "On the planning area, `approved_unimplemented_beds` is increased
        by the certificate's `authorized_bed_count` and
        `capital_authorization_committed_cents` is increased by its
        `approved_expenditure_limit_cents`."

        Design: Corner/validations/certificate_issued_while_the_appeal_window_is_open_returns_appeal_window_open
        """
        world = seed_decided_cycle()
        application = refresh_application(world["application"]["id"])
        assert application["status"] == "APPROVED"
        assert_instant_equals(
            application["appeal_window_closes_at"], APPEAL_WINDOW_CLOSES
        )
        set_clock(INSIDE_APPEAL_WINDOW_CLOCK)

        response = api_client.create_certificate(
            certificate_payload(application["id"]), OFFICER
        )

        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_OPEN, 409)
        _, meta = validate_paginated(
            api_client.list_certificates(
                ADMIN, params={"application_id": application["id"]}
            )
        )
        assert meta["total_count"] == 0
        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["capital_authorization_committed_cents"] == 0

        set_clock(ISSUANCE_CLOCK)
        certificate = get_success_data(
            api_client.create_certificate(
                certificate_payload(application["id"]), OFFICER
            ),
            201,
        )
        assert certificate["lifecycle_status"] == "ISSUED"

    def test_a_single_period_over_twice_the_limit_is_a_filing_error(self):
        """2100000000 in one period is refused outright, not treated as a breach.

        PRD §3.8: "One sanity limit applies to the period itself: if the period's
        own `disbursed_cents` plus `obligated_cents` alone exceeds twice the
        certificate's `approved_expenditure_limit_cents`, the programme treats that
        as a filing error rather than as a breach and refuses it with
        `ERR_EXPENDITURE_LIMIT_EXCEEDED`."
        PRD §3.8: "Separately, `expenditure_ceiling_cents` is the certificate's
        `approved_expenditure_limit_cents` multiplied by 1.05 — a five percent
        overrun tolerance band — rounded half up to a whole cent."

        Design: Corner/validations/progress_report_period_exceeding_twice_the_limit_returns_expenditure_limit_exceeded
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        assert certificate["expenditure_ceiling_cents"] == 1050000000

        response = api_client.create_progress_report(
            progress_report_payload(
                certificate["id"],
                certificate["version"],
                disbursed_cents=1500000000,
                obligated_cents=600000000,
                physical_completion_pct=40,
            ),
            make_applicant_headers(world["applicant"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_EXPENDITURE_LIMIT_EXCEEDED, 422)
        _, meta = validate_paginated(
            api_client.list_progress_reports(certificate["id"], ADMIN)
        )
        assert meta["total_count"] == 0
        stored = refresh_certificate(certificate["id"])
        assert stored["cumulative_expenditure_cash_cents"] == 0
        assert stored["cumulative_expenditure_accrual_cents"] == 0
        assert stored["expenditure_status"] == "WITHIN_LIMIT"
        assert stored["lifecycle_status"] == "ISSUED"
        assert stored["version"] == certificate["version"]
        assert refresh_applicant(world["applicant"]["id"])["compliance_strike_count"] == 0

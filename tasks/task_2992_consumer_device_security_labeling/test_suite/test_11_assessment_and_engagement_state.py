"""State-machine behaviour of conformance assessments, bench engagements and cases.

Every scenario here drives the public API only: the assessment lifecycle from its
initial DRAFT state through supersession and resubmission, the bench engagement's
reserving states and terminal lockdown, and the two-leg enforcement-case fork.
"""
from test_helpers import (
    ADMIN,
    ADMIN_2_USER_ID,
    ADMIN_USER_ID,
    DEFAULT_CLOCK,
    REVIEWER,
    ApiErrorId,
    api_client,
    assert_assessment_status,
    assert_bench_hour_ledger,
    assert_case_statuses,
    assert_instant_equals,
    assert_pagination_meta,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    assert_version_is,
    factories,
    fixtures,
    make_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared program shapes
# --------------------------------------------------------------------------
# Four criteria of equal weight, one per practice area, none of them needing the
# bench: every area therefore scores 100.00 on the provisional pass.
SELF_DECLARED_CATALOGUE = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]

# The same catalogue with DATA_PROTECTION made lab-verifiable, so a purely
# self-declared DATA_PROTECTION area scores 60.00 (weight 10 x factor 0.60) and
# rises to 100.00 once the bench reports a PASS.
LAB_VERIFIED_CATALOGUE = [
    dict(criterion, requires_lab_verification=(criterion["criterion_code"] == "DAT-1"))
    for criterion in SELF_DECLARED_CATALOGUE
]

SPEAKER_PRODUCT = {
    "model_name": "Speaker One",
    "sku": "SPK-001",
    "firmware_version": "1.0.0",
    "declared_support_period_end": "2029-08-01T00:00:00Z",
    "retail_units_shipped": 1000,
}
CAMERA_PRODUCT = {
    "model_name": "Camera One",
    "sku": "CAM-001",
    "firmware_version": "2.0.0",
    "declared_support_period_end": "2029-08-01T00:00:00Z",
    "retail_units_shipped": 5000,
}

BENCH_WINDOW_8H = {
    "window_start": "2026-08-10T09:00:00Z",
    "window_end": "2026-08-12T09:00:00Z",
    "bench_hours": 8,
}
BENCH_WINDOW_48H = dict(BENCH_WINDOW_8H, bench_hours=48)


def _self_attestation_program(criteria=None):
    """TIER_1: SELF_ATTESTATION, 365-day labels, minimum score 70.00."""
    return fixtures.create_program(
        "SELF_ATTESTATION",
        tier_overrides={"min_overall_score": 70.00},
        category_overrides={"min_support_period_days": 180},
        criteria=criteria or SELF_DECLARED_CATALOGUE,
    )


def _third_party_program(criteria=None):
    """TIER_2: THIRD_PARTY_TEST, one deficiency round, minimum score 70.00."""
    return fixtures.create_program(
        "THIRD_PARTY_TEST",
        tier_overrides={"min_overall_score": 70.00},
        category_overrides={
            "category_code": "SMART_CAMERA",
            "display_name": "Smart Camera",
            "min_support_period_days": 180,
        },
        criteria=criteria or LAB_VERIFIED_CATALOGUE,
    )


def _acme():
    return fixtures.enrol_manufacturer(
        legal_name="Acme Devices",
        contact_email="ops@acme.example",
        annual_us_revenue_cents=900000000,
    )


def _northline_lab():
    return fixtures.register_lab(lab_name="Northline Labs", total_bench_hours=200)


def _probation_lab():
    return fixtures.register_lab(
        lab_name="Probation Labs",
        accreditation_status="PROBATION",
        total_bench_hours=120,
        concurrent_bench_capacity=1,
    )


def _draft_claim(program, sponsor=None, product_overrides=None):
    """A product plus one DRAFT assessment, with the product handle refreshed."""
    sponsor = sponsor or _acme()
    product = fixtures.register_product(
        program, sponsor, **(product_overrides or SPEAKER_PRODUCT)
    )
    assessment = fixtures.open_assessment(program, sponsor, product)
    claim = fixtures.Claim(
        program=program, sponsor=sponsor, product=product, assessment=assessment
    )
    claim.refresh_product()
    return claim


def _book(claim, lab, **window):
    """Book a bench engagement, asserting the 201, and remember it on the claim."""
    engagement = validate_success(
        api_client.create_test_engagement(
            factories.create_test_engagement_payload(
                claim.assessment_id, lab.id, **(window or BENCH_WINDOW_8H)
            ),
            claim.sponsor.headers,
        ),
        201,
    )
    claim.lab = lab
    claim.engagement = engagement
    return engagement


def _response_for(claim, criterion_code):
    criterion_id = claim.program.criterion_id(criterion_code)
    for response in claim.responses:
        if response["criterion_id"] == criterion_id:
            return response
    raise AssertionError(f"no criterion response recorded for {criterion_code}")


def _fabricated_case(sponsor, code, channel, unit_count, listing_ref, note):
    return fixtures.open_case(
        sponsor,
        reported_scannable_code=code,
        violation_type="UNAUTHORIZED_DISPLAY",
        violation_line_items=[factories.violation_line(listing_ref, channel, unit_count)],
        reporter_note=note,
    )


# The initial state of the two entities created by the manufacturer's own
# actions: the conformance assessment and the bench engagement.
class TestAssessmentAndEngagementInitialState:

    def test_new_assessment_opens_in_draft_with_the_route_and_revision_snapshot(self):
        """A newly opened assessment is DRAFT at deficiency round 0, carrying the tier's route and the product's spec revision.

        PRD: "The new assessment records the `product_id` it belongs to, copies the `required_route` of the product's device category's program tier into its own `route` — so `route` reads either `SELF_ATTESTATION` or `THIRD_PARTY_TEST` — snapshots the product's current `spec_revision` into `assessed_spec_revision`, sets `status` to `DRAFT` and `deficiency_round` to 0, and increments the product's `version` by one."
        Design: Corner/state_machines/initial_state_assessment_draft_and_engagement_scheduled_on_creation
        """
        fixtures.reset_clock()
        claim = _draft_claim(_self_attestation_program())

        assessment = validate_success(api_client.get_assessment(claim.assessment_id, ADMIN))
        assert_assessment_status(assessment, "DRAFT")
        assert assessment["deficiency_round"] == 0, assessment["deficiency_round"]
        assert_status(assessment, "route", "SELF_ATTESTATION")
        assert assessment["assessed_spec_revision"] == 1, assessment["assessed_spec_revision"]
        assert assessment["product_id"] == claim.product_id
        assert_version_is(claim.product, 2)

    def test_new_assessment_leaves_every_score_and_decision_field_null(self):
        """Opening an assessment writes no score, no reviewer trail and no supersession pointer.

        PRD: "Scores start empty: `provisional_overall_score`, `verified_area_scores`, `verified_overall_score`, `decided_overall_score`, `decided_min_area_score` and `grade` are all null, `gate_applied` is false, and `reviewer_note`, `submitted_at`, `decided_at`, `decided_by_user_id`, `last_deficiency_by_user_id` and `superseded_by_assessment_id` are all null."
        Design: Corner/state_machines/initial_state_assessment_draft_and_engagement_scheduled_on_creation
        """
        fixtures.reset_clock()
        claim = _draft_claim(_self_attestation_program())

        assessment = validate_success(api_client.get_assessment(claim.assessment_id, ADMIN))
        for field in (
            "provisional_overall_score",
            "verified_area_scores",
            "verified_overall_score",
            "decided_overall_score",
            "decided_min_area_score",
            "grade",
            "reviewer_note",
            "submitted_at",
            "decided_at",
            "decided_by_user_id",
            "last_deficiency_by_user_id",
            "superseded_by_assessment_id",
        ):
            assert assessment[field] is None, f"{field} should start null, got {assessment[field]!r}"
        assert assessment["gate_applied"] is False, assessment["gate_applied"]

    def test_new_engagement_starts_scheduled_with_no_report_fields(self):
        """A booked engagement is SCHEDULED with its report and cancellation fields still null.

        PRD: "Booking also leaves `failed_criterion_codes`, `report_reference`, `cancellation_reason` and `completed_at` null until the report or cancellation writes them."
        Design: Corner/state_machines/initial_state_assessment_draft_and_engagement_scheduled_on_creation
        """
        fixtures.reset_clock()
        claim = _draft_claim(_self_attestation_program())
        engagement = _book(claim, _northline_lab())

        assert_status(engagement, "status", "SCHEDULED")
        assert engagement["completed_at"] is None, engagement["completed_at"]
        assert engagement["report_reference"] is None, engagement["report_reference"]
        assert engagement["cancellation_reason"] is None, engagement["cancellation_reason"]
        assert engagement["failed_criterion_codes"] is None, engagement["failed_criterion_codes"]

    def test_booking_reserves_the_requested_bench_hours(self):
        """Booking eight hours against a 200-hour laboratory reserves eight and leaves 192 available.

        PRD: "Booking an engagement therefore raises `reserved_bench_hours` by the requested `bench_hours` and lowers `available_bench_hours` by the same amount."
        Design: Corner/state_machines/initial_state_assessment_draft_and_engagement_scheduled_on_creation
        """
        fixtures.reset_clock()
        claim = _draft_claim(_self_attestation_program())
        lab = _northline_lab()
        _book(claim, lab)

        lab_row = lab.refresh()
        assert_bench_hour_ledger(lab_row, reserved=8)
        assert lab_row["available_bench_hours"] == 192, lab_row["available_bench_hours"]


# Supersession closes the older assessment for good: the terminal SUPERSEDED
# state refuses the submission that would have been legal a moment earlier.
class TestSupersededAssessmentRefusesSubmission:

    @staticmethod
    def _superseded_pair():
        fixtures.reset_clock()
        program = _self_attestation_program()
        claim = _draft_claim(program)
        predecessor_id = claim.assessment_id
        successor = fixtures.open_assessment(program, claim.sponsor, claim.product)
        return claim, predecessor_id, successor

    def test_submitting_a_superseded_assessment_is_rejected(self):
        """Submission aimed at an assessment already SUPERSEDED is refused with ERR_INVALID_ASSESSMENT_STATE.

        PRD: "A `SUPERSEDED` assessment accepts nothing thereafter; so do `APPROVED` and `REJECTED`, which together with `SUPERSEDED` are the three terminal values of `status`."
        Design: Corner/state_machines/invalid_transition_submit_on_superseded_assessment_rejected
        """
        claim, predecessor_id, _successor = self._superseded_pair()

        response = api_client.submit_assessment(predecessor_id, claim.sponsor.headers)
        validate_error(response, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value)

    def test_rejected_submission_leaves_the_superseded_assessment_untouched(self):
        """The refused submission stamps no `submitted_at` and does not disturb the supersession pointer.

        PRD: "If an existing assessment of the same product has a `status` of `DRAFT`, `UNDER_REVIEW` or `DEFICIENT`, that older assessment moves to `SUPERSEDED` and its `superseded_by_assessment_id` is set to the new assessment's identifier."
        Design: Corner/state_machines/invalid_transition_submit_on_superseded_assessment_rejected
        """
        claim, predecessor_id, successor = self._superseded_pair()
        validate_error(
            api_client.submit_assessment(predecessor_id, claim.sponsor.headers),
            ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value,
        )

        predecessor = validate_success(api_client.get_assessment(predecessor_id, ADMIN))
        assert_assessment_status(predecessor, "SUPERSEDED")
        assert predecessor["submitted_at"] is None, predecessor["submitted_at"]
        assert predecessor["superseded_by_assessment_id"] == successor["id"]
        still_open = validate_success(api_client.get_assessment(successor["id"], ADMIN))
        assert_assessment_status(still_open, "DRAFT")
        assert still_open["superseded_by_assessment_id"] is None


# CANCELLED is terminal on the engagement machine, and the hours it released are
# released exactly once.
class TestCancelledEngagementIsTerminal:
    CANCELLATION_REASON = "Manufacturer withdrew the booking"

    @classmethod
    def _cancelled(cls):
        fixtures.reset_clock()
        claim = _draft_claim(_self_attestation_program())
        lab = _northline_lab()
        engagement = _book(claim, lab)
        cancelled = validate_success(
            api_client.cancel_test_engagement(
                engagement["id"],
                factories.cancel_engagement_payload(cancellation_reason=cls.CANCELLATION_REASON),
                claim.sponsor.headers,
            ),
            201,
        )
        return claim, lab, cancelled

    def test_second_cancellation_of_the_same_engagement_is_rejected(self):
        """A cancellation aimed at an engagement already CANCELLED is refused with ERR_INVALID_ENGAGEMENT_STATE.

        PRD: "`COMPLETED` and `CANCELLED` are terminal: any report or cancellation aimed at an engagement already in either state is rejected with `ERR_INVALID_ENGAGEMENT_STATE`."
        Design: Corner/state_machines/terminal_state_lockdown_cancelled_engagement_rejects_cancel_and_report
        """
        claim, _lab, cancelled = self._cancelled()

        response = api_client.cancel_test_engagement(
            cancelled["id"],
            factories.cancel_engagement_payload(cancellation_reason="Second withdrawal attempt"),
            claim.sponsor.headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value)

    def test_report_filed_against_a_cancelled_engagement_is_rejected(self):
        """A bench report aimed at an engagement already CANCELLED is refused with ERR_INVALID_ENGAGEMENT_STATE.

        PRD: "`COMPLETED` and `CANCELLED` are terminal: any report or cancellation aimed at an engagement already in either state is rejected with `ERR_INVALID_ENGAGEMENT_STATE`."
        Design: Corner/state_machines/terminal_state_lockdown_cancelled_engagement_rejects_cancel_and_report
        """
        _claim, lab, cancelled = self._cancelled()

        response = api_client.report_test_engagement(
            cancelled["id"],
            factories.report_payload([], report_reference="RPT-LATE-0001"),
            lab.headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value)

    def test_both_refused_triggers_leave_the_cancellation_and_the_ledger_alone(self):
        """Neither refused trigger re-stamps the cancellation nor releases the bench hours a second time.

        PRD: "It is accepted from either `SCHEDULED` or `IN_PROGRESS` — `SCHEDULED → CANCELLED` and `IN_PROGRESS → CANCELLED` behave identically — and it credits the reserved hours back so that `reserved_bench_hours` plus `available_bench_hours` still equals `total_bench_hours` and `reserved_bench_hours` returns to exactly its pre-booking value."
        Design: Corner/state_machines/terminal_state_lockdown_cancelled_engagement_rejects_cancel_and_report
        """
        claim, lab, cancelled = self._cancelled()
        validate_error(
            api_client.cancel_test_engagement(
                cancelled["id"],
                factories.cancel_engagement_payload(cancellation_reason="Second withdrawal attempt"),
                claim.sponsor.headers,
            ),
            ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value,
        )
        validate_error(
            api_client.report_test_engagement(
                cancelled["id"],
                factories.report_payload([], report_reference="RPT-LATE-0001"),
                lab.headers,
            ),
            ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value,
        )

        engagement = validate_success(api_client.get_test_engagement(cancelled["id"], ADMIN))
        assert_status(engagement, "status", "CANCELLED")
        assert engagement["cancellation_reason"] == self.CANCELLATION_REASON
        assert engagement["completed_at"] is None, engagement["completed_at"]
        assert engagement["report_reference"] is None, engagement["report_reference"]
        lab_row = lab.refresh()
        assert_bench_hour_ledger(lab_row, reserved=0)
        assert lab_row["available_bench_hours"] == 200, lab_row["available_bench_hours"]


# The notice leg fires exactly once, so a second notice is not an idempotent
# no-op: it is a rejected transition that leaves the first notice standing.
class TestSecondNoticeOnTheSameCase:
    FABRICATED_CODE = "ZZ-NO-SUCH-CD001"
    FIRST_REFERENCE = "NOT-2026-0001"

    @classmethod
    def _noticed(cls):
        fixtures.reset_clock()
        sponsor = _acme()
        case = _fabricated_case(
            sponsor,
            cls.FABRICATED_CODE,
            "ONLINE",
            10,
            "LST-MARKET-01",
            "Program label artwork observed on an unlisted marketplace page",
        )
        noticed = fixtures.issue_notice(case, ADMIN, notice_reference=cls.FIRST_REFERENCE)
        return sponsor, noticed

    def test_second_notice_on_a_noticed_case_is_rejected(self):
        """A second statutory notice against the same case is refused with ERR_INVALID_CASE_STATE.

        PRD: "It is admissible from `OPENED` or from `LAB_REFERRAL`, but only while `notice_issued_by_user_id` is still null — the notice is issued exactly once — and it drives `case_status` to `NOTICE_ISSUED`."
        Design: Corner/state_machines/idempotency_second_notice_on_the_same_case_rejected
        """
        _sponsor, noticed = self._noticed()

        response = api_client.issue_case_notice(
            noticed["id"],
            factories.notice_payload(notice_reference="NOT-2026-0002"),
            make_admin_headers(ADMIN_2_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)

    def test_rejected_second_notice_does_not_restamp_the_notice_trail(self):
        """The refused second notice leaves the original reference and issuing administrator in place.

        PRD: "The **notice leg** issues the statutory notice of alleged misuse to the subject: it records the `notice_reference` document reference and stamps `notice_issued_by_user_id` with the acting administrator's `X-User-ID`."
        Design: Corner/state_machines/idempotency_second_notice_on_the_same_case_rejected
        """
        _sponsor, noticed = self._noticed()
        validate_error(
            api_client.issue_case_notice(
                noticed["id"],
                factories.notice_payload(notice_reference="NOT-2026-0002"),
                make_admin_headers(ADMIN_2_USER_ID),
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
        )

        case = validate_success(api_client.get_enforcement_case(noticed["id"], ADMIN))
        assert_case_statuses(case, "NOTICE_ISSUED", "NONE")
        assert case["notice_reference"] == self.FIRST_REFERENCE, case["notice_reference"]
        assert case["notice_issued_by_user_id"] == ADMIN_USER_ID, case["notice_issued_by_user_id"]

    def test_the_frozen_creation_derivations_survive_the_refused_notice(self):
        """`code_matches_registry` stays false and `violation_unit_count` stays 10 across the refused notice.

        PRD: "On creation the system computes `violation_unit_count` as the sum of `unit_count` across all lines, and computes `code_matches_registry` as true exactly when `reported_scannable_code` equals the `scannable_code` of some label grant."
        Design: Corner/state_machines/idempotency_second_notice_on_the_same_case_rejected
        """
        _sponsor, noticed = self._noticed()
        validate_error(
            api_client.issue_case_notice(
                noticed["id"],
                factories.notice_payload(notice_reference="NOT-2026-0002"),
                make_admin_headers(ADMIN_2_USER_ID),
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
        )

        case = validate_success(api_client.get_enforcement_case(noticed["id"], ADMIN))
        assert case["code_matches_registry"] is False, case["code_matches_registry"]
        assert case["violation_unit_count"] == 10, case["violation_unit_count"]


# Adjudication is not reachable from OPENED: the notice leg is a mandatory
# waypoint, and skipping it writes nothing at all.
class TestAdjudicationRequiresTheNoticeLeg:
    FABRICATED_CODE = "ZZ-NO-SUCH-CD002"

    @classmethod
    def _opened(cls):
        fixtures.reset_clock()
        sponsor = _acme()
        case = _fabricated_case(
            sponsor,
            cls.FABRICATED_CODE,
            "IN_STORE",
            4,
            "LST-SHELF-01",
            "Shelf talker carrying the program label with no grant behind it",
        )
        return sponsor, case

    def test_adjudicating_a_case_still_at_opened_is_rejected(self):
        """Adjudication attempted before the notice leg is refused with ERR_INVALID_CASE_STATE.

        PRD: "A case still at `OPENED`, a case sitting in `LAB_REFERRAL` that never completed the notice leg, and a case already adjudicated or vacated are all rejected with `ERR_INVALID_CASE_STATE`."
        Design: Corner/state_machines/invalid_transition_adjudicate_before_notice_issued_rejected
        """
        _sponsor, case = self._opened()

        response = api_client.adjudicate_case(
            case["id"],
            factories.adjudicate_payload("UPHELD", adjudication_note="Premature adjudication attempt"),
            make_admin_headers(ADMIN_2_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)

    def test_the_refused_adjudication_leaves_both_case_dimensions_at_their_initial_values(self):
        """No penalty is struck and no adjudication trail is written by the refused transition.

        PRD: "A new case starts at `OPENED` on its `case_status` dimension and `NONE` on its `penalty_status` dimension, with `penalty_cents` 0 and `penalty_variant`, `aggravation_multiplier`, `notice_reference`, `notice_issued_by_user_id`, `referred_test_lab_id`, `adjudicated_at`, `adjudicated_by_user_id`, `vacate_reason` and `payment_reference` all null."
        Design: Corner/state_machines/invalid_transition_adjudicate_before_notice_issued_rejected
        """
        _sponsor, opened = self._opened()
        validate_error(
            api_client.adjudicate_case(
                opened["id"],
                factories.adjudicate_payload("UPHELD", adjudication_note="Premature adjudication attempt"),
                make_admin_headers(ADMIN_2_USER_ID),
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
        )

        case = validate_success(api_client.get_enforcement_case(opened["id"], ADMIN))
        assert_case_statuses(case, "OPENED", "NONE")
        assert case["penalty_cents"] == 0, case["penalty_cents"]
        for field in ("penalty_variant", "aggravation_multiplier", "adjudicated_at", "adjudicated_by_user_id"):
            assert case[field] is None, f"{field} should still be null, got {case[field]!r}"

    def test_the_refused_adjudication_leaves_the_subject_ledger_at_zero(self):
        """The subject's penalty ledger is untouched, so its standing stays GOOD.

        PRD: "Enrolment initialises the penalty ledger explicitly: `standing` starts at `GOOD`, and `outstanding_penalty_cents`, `paid_penalty_cents`, `vacated_penalty_cents`, `total_assessed_penalty_cents` and `upheld_case_count` all start at 0."
        Design: Corner/state_machines/invalid_transition_adjudicate_before_notice_issued_rejected
        """
        sponsor, opened = self._opened()
        validate_error(
            api_client.adjudicate_case(
                opened["id"],
                factories.adjudicate_payload("UPHELD", adjudication_note="Premature adjudication attempt"),
                make_admin_headers(ADMIN_2_USER_ID),
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
        )

        manufacturer = validate_success(api_client.get_manufacturer(sponsor.id, ADMIN))
        assert_penalty_ledger(manufacturer, outstanding=0, paid=0, vacated=0)
        assert manufacturer["total_assessed_penalty_cents"] == 0
        assert manufacturer["upheld_case_count"] == 0, manufacturer["upheld_case_count"]
        assert_status(manufacturer, "standing", "GOOD")


# The lab-referral leg carries an accreditation guard the notice leg does not,
# so the very same referral payload is refused for one lab and accepted for another.
class TestLabReferralAccreditationGuard:
    FABRICATED_CODE = "ZZ-NO-SUCH-CD003"

    @classmethod
    def _opened(cls):
        fixtures.reset_clock()
        sponsor = _acme()
        case = _fabricated_case(
            sponsor,
            cls.FABRICATED_CODE,
            "ONLINE",
            6,
            "LST-MARKET-02",
            "Marketplace listing reusing the program label artwork",
        )
        return sponsor, case

    def test_referral_to_a_lab_on_probation_is_rejected(self):
        """A referral naming a laboratory in PROBATION is refused with ERR_LAB_NOT_ACCREDITED.

        PRD: "Unlike the notice leg it demands that the named laboratory's `accreditation_status` be `ACCREDITED`, so a lab in `PROBATION` or `REVOKED` cannot receive a referral and the attempt is rejected with `ERR_LAB_NOT_ACCREDITED`."
        Design: Corner/state_machines/guarded_transition_lab_referral_requires_an_accredited_lab
        """
        _sponsor, case = self._opened()
        probation = _probation_lab()

        response = api_client.refer_case_to_lab(
            case["id"],
            factories.lab_referral_payload(probation.id, referral_note="Teardown requested"),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_LAB_NOT_ACCREDITED.value)

        unchanged = validate_success(api_client.get_enforcement_case(case["id"], ADMIN))
        assert_case_statuses(unchanged, "OPENED", "NONE")
        assert unchanged["referred_test_lab_id"] is None, unchanged["referred_test_lab_id"]

    def test_the_same_referral_to_an_accredited_lab_moves_the_case(self):
        """The identical referral payload succeeds once the named laboratory is ACCREDITED.

        PRD: "The **lab-referral leg** sends the disputed device to an accredited laboratory for evidentiary testing: it names a `test_lab_id` and a `referral_note`, records `referred_test_lab_id`, and drives `case_status` to `LAB_REFERRAL`."
        Design: Corner/state_machines/guarded_transition_lab_referral_requires_an_accredited_lab
        """
        _sponsor, case = self._opened()
        probation = _probation_lab()
        accredited = _northline_lab()

        validate_error(
            api_client.refer_case_to_lab(
                case["id"],
                factories.lab_referral_payload(probation.id, referral_note="Teardown requested"),
                ADMIN,
            ),
            ApiErrorId.ERR_LAB_NOT_ACCREDITED.value,
        )
        referred = validate_success(
            api_client.refer_case_to_lab(
                case["id"],
                factories.lab_referral_payload(accredited.id, referral_note="Teardown requested"),
                ADMIN,
            ),
            201,
        )

        assert_case_statuses(referred, "LAB_REFERRAL", "NONE")
        assert referred["referred_test_lab_id"] == accredited.id, referred["referred_test_lab_id"]
        assert referred["notice_issued_by_user_id"] is None, referred["notice_issued_by_user_id"]


# One accepted report moves the engagement machine, the laboratory's ledger and
# the assessment's score set in a single step.
class TestReportSynchronisesLedgerAndVerifiedScores:
    REPORT_REFERENCE = "RPT-2026-0001"

    @classmethod
    def _reported(cls):
        fixtures.reset_clock()
        program = _third_party_program()
        claim = _draft_claim(program, product_overrides=CAMERA_PRODUCT)
        claim.responses = fixtures.attach_responses(program, claim.sponsor, claim.assessment)
        fixtures.submit_claim(claim)
        lab = _northline_lab()
        _book(claim, lab)
        fixtures.file_report(claim, [], report_reference=cls.REPORT_REFERENCE)
        return claim, lab

    def test_the_report_completes_the_engagement_and_stamps_the_clock(self):
        """Accepting the report drives SCHEDULED to COMPLETED and stamps `completed_at` from the logical clock.

        PRD: "It sets `status` to `COMPLETED`, stamps `completed_at` from the logical clock and stores the supplied `failed_criterion_codes` and `report_reference`."
        Design: Corner/state_machines/ledger_sync_completed_report_releases_reserved_bench_hours_and_writes_verified_scores
        """
        claim, _lab = self._reported()

        engagement = validate_success(api_client.get_test_engagement(claim.engagement["id"], ADMIN))
        assert_status(engagement, "status", "COMPLETED")
        assert_instant_equals(engagement["completed_at"], DEFAULT_CLOCK, "completed_at")
        assert engagement["report_reference"] == self.REPORT_REFERENCE
        assert engagement["failed_criterion_codes"] == []

    def test_the_report_releases_the_reserved_bench_hours(self):
        """Completion returns the eight reserved hours, leaving the conserved ledger at 0 reserved and 200 available.

        PRD: "Finally it credits the bench hours back: the laboratory's `reserved_bench_hours` drops by this engagement's `bench_hours` and `available_bench_hours` rises by the same amount."
        Design: Corner/state_machines/ledger_sync_completed_report_releases_reserved_bench_hours_and_writes_verified_scores
        """
        _claim, lab = self._reported()

        lab_row = lab.refresh()
        assert_bench_hour_ledger(lab_row, reserved=0)
        assert lab_row["available_bench_hours"] == 200, lab_row["available_bench_hours"]

    def test_the_report_marks_every_criterion_response_verified(self):
        """An empty failure array stamps PASS and `lab_verified` true on every response, lab-verifiable or not.

        PRD: "It then writes the bench verdict onto *every* criterion response of the assessment: each response whose criterion's `criterion_code` appears in `failed_criterion_codes` gets `lab_result` set to `FAIL`, every other response gets `lab_result` set to `PASS`, and all of them get `lab_verified` set to true — the report covered the whole claim, so nothing is left `NOT_TESTED`."
        Design: Corner/state_machines/ledger_sync_completed_report_releases_reserved_bench_hours_and_writes_verified_scores
        """
        claim, _lab = self._reported()

        for code in ("AUTH-1", "UPD-1", "DAT-1", "VLN-1"):
            response = validate_success(
                api_client.get_criterion_response(_response_for(claim, code)["id"], ADMIN)
            )
            assert_status(response, "lab_result", "PASS")
            assert response["lab_verified"] is True, f"{code}: {response['lab_verified']!r}"

    def test_the_verified_pass_lifts_the_lab_verifiable_area_to_full_credit(self):
        """DATA_PROTECTION scores 60.00 provisionally on the self-declaration and 100.00 once the bench passes it.

        PRD: "In the verified variant the logic inverts for lab-verifiable criteria: when `requires_lab_verification` is true, the criterion earns its full `weight` if `lab_result` is `PASS` and nothing if it is anything else, and `self_declared_conformant` is ignored entirely; when `requires_lab_verification` is false, the criterion earns its full `weight` if `self_declared_conformant` is true and nothing otherwise."
        Design: Corner/state_machines/ledger_sync_completed_report_releases_reserved_bench_hours_and_writes_verified_scores
        """
        claim, _lab = self._reported()

        assessment = validate_success(api_client.get_assessment(claim.assessment_id, ADMIN))
        assert_score(assessment["provisional_area_scores"]["DATA_PROTECTION"], 60.00, "provisional DATA_PROTECTION")
        assert_score(assessment["verified_area_scores"]["DATA_PROTECTION"], 100.00, "verified DATA_PROTECTION")
        assert_score(assessment["provisional_overall_score"], 90.00, "provisional_overall_score")
        assert_score(assessment["verified_overall_score"], 100.00, "verified_overall_score")

    def test_the_verified_score_becomes_the_decided_score_and_the_grade(self):
        """On the third-party route the report's verified score is copied to `decided_overall_score` and grades A.

        PRD: "It then recomputes the assessment in the verified variant of §3.4, writing `verified_area_scores`, `verified_overall_score`, `decided_min_area_score` and `gate_applied`, and because a tested assessment is by definition on the `THIRD_PARTY_TEST` route it also sets `decided_overall_score` from `verified_overall_score` and re-derives `grade`."
        Design: Corner/state_machines/ledger_sync_completed_report_releases_reserved_bench_hours_and_writes_verified_scores
        """
        claim, _lab = self._reported()

        assessment = validate_success(api_client.get_assessment(claim.assessment_id, ADMIN))
        assert_score(assessment["decided_overall_score"], 100.00, "decided_overall_score")
        assert_score(assessment["decided_min_area_score"], 100.00, "decided_min_area_score")
        assert_status(assessment, "grade", "A")
        assert assessment["gate_applied"] is False, assessment["gate_applied"]
        assert_assessment_status(assessment, "UNDER_REVIEW")


# Revising a deficient claim rewinds the bench: the laboratory's verdict and the
# verified score set are invalidated, but the deficiency budget already spent is not.
class TestResubmissionInvalidatesTheBenchVerdict:
    REVISED_EVIDENCE = "EV-DAT-1-REV2"

    @classmethod
    def _resubmitted(cls):
        fixtures.reset_clock()
        program = _third_party_program()
        claim = _draft_claim(program, product_overrides=CAMERA_PRODUCT)
        claim.responses = fixtures.attach_responses(program, claim.sponsor, claim.assessment)
        fixtures.submit_claim(claim)
        lab = _northline_lab()
        _book(claim, lab)
        fixtures.file_report(claim, [], report_reference="RPT-2026-0002")
        fixtures.decide_claim(claim, "DEFICIENT", REVIEWER)
        payload = factories.resubmit_payload(
            responses=[
                factories.response_item(
                    program.criterion_id("DAT-1"), True, evidence_ref=cls.REVISED_EVIDENCE
                )
            ],
            resubmission_note="Replaced the DAT-1 evidence bundle after the deficiency finding",
        )
        resubmitted = validate_success(
            api_client.resubmit_assessment(claim.assessment_id, payload, claim.sponsor.headers), 201
        )
        claim.assessment = resubmitted
        return claim

    def test_resubmission_returns_the_claim_to_review_without_refunding_the_deficiency_round(self):
        """The revision moves DEFICIENT back to UNDER_REVIEW while `deficiency_round` stays at 1.

        PRD: "One thing is deliberately *not* reset: `deficiency_round` keeps its accumulated value, so the deficiency budget is spent across the whole life of the assessment rather than per round."
        Design: Corner/state_machines/side_effect_execution_resubmit_resets_lab_results_and_clears_verified_scores
        """
        claim = self._resubmitted()

        assessment = validate_success(api_client.get_assessment(claim.assessment_id, ADMIN))
        assert_assessment_status(assessment, "UNDER_REVIEW")
        assert assessment["deficiency_round"] == 1, assessment["deficiency_round"]

    def test_resubmission_clears_the_verified_and_decided_score_set(self):
        """The verified scores, the decided score and the grade are all cleared, and only the provisional pass re-runs.

        PRD: "Every criterion response of the assessment has its `lab_result` reset to `NOT_TESTED` and its `lab_verified` reset to false; `verified_area_scores` and `verified_overall_score` are cleared to null; and on a `THIRD_PARTY_TEST` route `decided_overall_score` and `grade` are cleared to null as well, because the verified score they were derived from no longer exists."
        Design: Corner/state_machines/side_effect_execution_resubmit_resets_lab_results_and_clears_verified_scores
        """
        claim = self._resubmitted()

        assessment = validate_success(api_client.get_assessment(claim.assessment_id, ADMIN))
        for field in ("verified_area_scores", "verified_overall_score", "decided_overall_score", "grade"):
            assert assessment[field] is None, f"{field} should be cleared, got {assessment[field]!r}"
        assert_score(assessment["provisional_overall_score"], 90.00, "provisional_overall_score")

    def test_resubmission_resets_every_criterion_response_to_not_tested(self):
        """Every response loses the bench verdict, including the three the revision never mentioned.

        PRD: "A resubmission also invalidates everything the laboratory had established, because the claim it tested has changed underneath it."
        Design: Corner/state_machines/side_effect_execution_resubmit_resets_lab_results_and_clears_verified_scores
        """
        claim = self._resubmitted()

        for code in ("AUTH-1", "UPD-1", "DAT-1", "VLN-1"):
            response = validate_success(
                api_client.get_criterion_response(_response_for(claim, code)["id"], ADMIN)
            )
            assert_status(response, "lab_result", "NOT_TESTED")
            assert response["lab_verified"] is False, f"{code}: {response['lab_verified']!r}"

    def test_the_named_response_is_upserted_rather_than_duplicated(self):
        """The revised DAT-1 evidence overwrites the existing row, leaving the assessment with four responses.

        PRD: "The resubmission carries a mandatory `resubmission_note` and an optional `responses` array in the same shape as the original batch; supplied elements are upserted onto the pairing of `assessment_id` with `criterion_id`, leaving responses the manufacturer did not mention exactly as they were."
        Design: Corner/state_machines/side_effect_execution_resubmit_resets_lab_results_and_clears_verified_scores
        """
        claim = self._resubmitted()

        revised = validate_success(
            api_client.get_criterion_response(_response_for(claim, "DAT-1")["id"], ADMIN)
        )
        assert revised["evidence_ref"] == self.REVISED_EVIDENCE, revised["evidence_ref"]
        items, meta = validate_paginated(
            api_client.list_criterion_responses(ADMIN, params={"assessment_id": claim.assessment_id})
        )
        assert_pagination_meta(meta, 10, 0, total_count=4)
        assert len(items) == 4, [item["criterion_id"] for item in items]


# Opening a second assessment reaches across into the bench: the predecessor's
# scheduled engagement is cancelled for it and its hours released.
class TestSupersessionCancelsTheScheduledEngagement:

    @staticmethod
    def _superseded():
        fixtures.reset_clock()
        program = _self_attestation_program()
        claim = _draft_claim(program)
        claim.responses = fixtures.attach_responses(program, claim.sponsor, claim.assessment)
        fixtures.submit_claim(claim)
        lab = _northline_lab()
        engagement = _book(claim, lab, **BENCH_WINDOW_48H)
        predecessor_id = claim.assessment_id
        claim.refresh_product()
        successor = fixtures.open_assessment(program, claim.sponsor, claim.product)
        return claim, lab, engagement, predecessor_id, successor

    def test_the_new_assessment_supersedes_the_assessment_under_review(self):
        """The predecessor moves to SUPERSEDED and points at the successor, which opens in DRAFT.

        PRD: "If an existing assessment of the same product has a `status` of `DRAFT`, `UNDER_REVIEW` or `DEFICIENT`, that older assessment moves to `SUPERSEDED` and its `superseded_by_assessment_id` is set to the new assessment's identifier."
        Design: Corner/state_machines/cross_entity_new_assessment_supersedes_predecessor_and_cancels_its_engagement
        """
        _claim, _lab, _engagement, predecessor_id, successor = self._superseded()

        predecessor = validate_success(api_client.get_assessment(predecessor_id, ADMIN))
        assert_assessment_status(predecessor, "SUPERSEDED")
        assert predecessor["superseded_by_assessment_id"] == successor["id"]
        opened = validate_success(api_client.get_assessment(successor["id"], ADMIN))
        assert_assessment_status(opened, "DRAFT")
        assert opened["deficiency_round"] == 0, opened["deficiency_round"]
        assert opened["assessed_spec_revision"] == 1, opened["assessed_spec_revision"]

    def test_supersession_cancels_the_engagement_and_credits_its_bench_hours(self):
        """The predecessor's SCHEDULED engagement is cancelled as ASSESSMENT_SUPERSEDED and its 48 hours return.

        PRD: "Supersession is not merely bookkeeping: any test engagement of the superseded assessment whose `status` is `SCHEDULED` or `IN_PROGRESS` is cancelled, with `cancellation_reason` recorded as `ASSESSMENT_SUPERSEDED`, and its `bench_hours` are credited back to the laboratory's balance as described in §3.5."
        Design: Corner/state_machines/cross_entity_new_assessment_supersedes_predecessor_and_cancels_its_engagement
        """
        _claim, lab, engagement, _predecessor_id, _successor = self._superseded()

        cancelled = validate_success(api_client.get_test_engagement(engagement["id"], ADMIN))
        assert_status(cancelled, "status", "CANCELLED")
        assert cancelled["cancellation_reason"] == "ASSESSMENT_SUPERSEDED", cancelled["cancellation_reason"]
        assert cancelled["completed_at"] is None, cancelled["completed_at"]
        lab_row = lab.refresh()
        assert_bench_hour_ledger(lab_row, reserved=0)
        assert lab_row["available_bench_hours"] == 200, lab_row["available_bench_hours"]

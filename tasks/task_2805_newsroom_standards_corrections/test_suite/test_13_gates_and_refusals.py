"""Rules that stand between a well-formed request and the record it wants."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W
from test_helpers import make_reporter_headers


class TestAnonymousSourceApprovalGates:
    """The two gates that stand only in front of ``APPROVE``."""

    def test_a_source_whose_identity_no_editor_holds_cannot_be_approved(
        self, api, desk
    ):
        """A long justification does not make the documentation complete.

        PRD §3.2: "Approval, moving the record `REQUESTED → APPROVED`, is gated
        twice: `documentation_complete` must be true, and a failure here is
        `ERR_INSUFFICIENT_SOURCE_DOCUMENTATION`". PRD §3.2 derives the flag at
        filing: `documentation_complete` "is true exactly when
        `identity_known_to_editor` is true **and** `justification_text` is at
        least 20 characters long, and false otherwise."

        Design: Corner/validations/approving_source_without_editor_known_identity_returns_insufficient_documentation
        """
        story = W.open_story(api, desk, "An unverified whisper")
        source = W.request_source(
            api,
            desk,
            story["id"],
            source_alias="anon-tip",
            source_category=C.SOURCE_CATEGORY_CORPORATE,
            harm_risk=C.HARM_LOW,
            identity_known_to_editor=False,
            corroboration_count=3,
            justification_text=(
                "The tipster refuses to give a name even to the standards desk."
            ),
        )

        response = api.decide_source_approval(
            source["id"],
            F.source_decision_payload(
                C.DECISION_APPROVE, "Attempting to approve an undocumented source."
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_INSUFFICIENT_SOURCE_DOCUMENTATION, 422)

        held = get_success_data(
            api.get_source_approval(source["id"], desk.sed_headers)
        )
        assert held["documentation_complete"] is False
        assert held["status"] == C.SOURCE_REQUESTED
        A.assert_story_counters(
            W.read_story(api, desk, story["id"]), approved_sources=0
        )

    def test_a_severe_source_on_one_corroboration_falls_to_the_second_gate(
        self, api, desk
    ):
        """Documentation passes, so the corroboration floor is what refuses.

        PRD §3.2: "and if `harm_risk` is `SEVERE`, `corroboration_count` must be
        at least 2, with a shortfall refused as `ERR_INSUFFICIENT_CORROBORATION`."
        PRD §3.2 keeps the story's figure where creation left it, because
        "Approvals in `REQUESTED`, `DENIED` or `REVOKED` contribute nothing to this
        base".

        Design: Corner/validations/approving_severe_source_with_one_corroboration_returns_insufficient_corroboration
        """
        story = W.open_story(api, desk, "A witness in danger")
        source = W.request_source(
            api,
            desk,
            story["id"],
            source_alias="witness-one",
            source_category=C.SOURCE_CATEGORY_VICTIM,
            harm_risk=C.HARM_SEVERE,
            identity_known_to_editor=True,
            corroboration_count=1,
            justification_text=(
                "Naming this witness would expose them to retaliation."
            ),
        )

        response = api.decide_source_approval(
            source["id"],
            F.source_decision_payload(
                C.DECISION_APPROVE, "Attempting approval on one corroboration."
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_INSUFFICIENT_CORROBORATION, 422)

        held = get_success_data(
            api.get_source_approval(source["id"], desk.sed_headers)
        )
        assert held["documentation_complete"] is True
        assert held["status"] == C.SOURCE_REQUESTED
        A.assert_risk_figures(
            W.read_story(api, desk, story["id"]), estimate=0.00
        )

    def test_the_same_alias_cannot_be_used_twice_on_one_story(self, api, desk):
        """Uniqueness is per story, so the follow-up may reuse the name.

        PRD §3.2: a request supplies "a `source_alias` — the non-identifying name
        that will appear in copy, 1 to 80 characters, and unique among that
        story's approvals, with a repeat refused as `ERR_DUPLICATE_SOURCE_ALIAS`."

        Design: Corner/validations/second_source_with_same_alias_on_one_story_returns_duplicate_source_alias
        """
        first = W.open_story(api, desk, "Part one of the permit series")
        second = W.open_story(api, desk, "Part two of the permit series")
        W.request_source(
            api,
            desk,
            first["id"],
            source_alias="permit-clerk",
            harm_risk=C.HARM_ELEVATED,
            corroboration_count=2,
            justification_text="Custodian of the permit ledger for four years.",
        )
        W.request_source(
            api,
            desk,
            second["id"],
            source_alias="permit-clerk",
            harm_risk=C.HARM_ELEVATED,
            corroboration_count=2,
            justification_text="Same custodian, carried into the follow-up story.",
        )

        response = api.create_source_approval(
            F.source_approval_payload(
                first["id"],
                source_alias="permit-clerk",
                harm_risk=C.HARM_LOW,
                corroboration_count=2,
                justification_text=(
                    "A duplicate alias filed against the first story."
                ),
            ),
            desk.reporter_headers,
        )

        validate_error(response, E.ERR_DUPLICATE_SOURCE_ALIAS, 409)

        A.assert_total_count(
            api.list_story_source_approvals(first["id"], desk.sed_headers), 1
        )
        A.assert_total_count(
            api.list_story_source_approvals(second["id"], desk.sed_headers), 1
        )


class TestHighTierPublicationTrainingGate:
    """The one publication guard that applies to a single tier."""

    def _cleared_high_tier_story(self, api, desk, legal_reviewer):
        story = W.open_story(
            api,
            desk,
            "Ten allegations and five private lives",
            defamation_claim_count=10,
            privacy_subject_count=5,
        )
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)
        W.record_legal_pass(
            api,
            desk,
            review["id"],
            legal_reviewer,
            defamation_findings=10,
            privacy_findings=5,
            findings_note="Every allegation is documented.",
        )
        W.record_standards_pass(api, desk, review["id"])
        W.clear_round(api, desk, review["id"])
        return story

    def test_a_high_tier_story_is_held_back_by_its_untrained_lead(
        self, api, desk, legal_reviewer
    ):
        """Exactly forty points is a ``HIGH`` tier, and the gate then applies.

        PRD §3.2: `risk_tier` "is `HIGH` when `risk_index_estimate` is 40.00 or
        greater". PRD §3.5: "When the story's `risk_tier` is `HIGH`, its lead
        journalist must have `training_current` true, and a shortfall is refused
        with `ERR_TRAINING_NOT_CURRENT`; stories at `STANDARD` and `ELEVATED` tier
        are exempt from the training gate entirely." PRD §3.8 derives the flag:
        "`training_current` is then true exactly when
        `completed_required_module_count` equals the number of codes in
        `required_module_codes`, and false otherwise."

        Design: Corner/validations/publishing_high_tier_story_with_untrained_lead_returns_training_not_current
        """
        story = self._cleared_high_tier_story(api, desk, legal_reviewer)

        response = api.publish_story(story["id"], {}, desk.exec_headers)

        validate_error(response, E.ERR_TRAINING_NOT_CURRENT, 422)

        held = W.read_story(api, desk, story["id"])
        A.assert_risk_figures(held, estimate=40.00, tier=C.TIER_HIGH)
        assert held["publication_status"] == C.PUB_CLEARED
        assert held["published_at"] is None

        reporter = W.read_journalist(api, desk, desk.reporter_id)
        assert reporter["training_current"] is False
        assert reporter["completed_required_module_count"] == 0

    def test_the_identical_publish_is_admitted_once_the_module_is_filed(
        self, api, desk, legal_reviewer
    ):
        """The gate reads a derived flag, not the tier alone.

        PRD §3.8: "The journalist's `completed_required_module_count` is
        recomputed as the number of **distinct** `module_code` values across their
        training records that also appear in their newsroom's
        `required_module_codes`", and PRD §3.1 says `required_module_codes`
        "defaults to a single-element array containing `SOURCING`". PRD §3.5 then
        admits the story: "On success `published_at` is stamped from the logical
        clock, an audit event of type `STORY_PUBLISHED` is appended, and the
        story's `version` advances by one. Publication is also the moment
        `risk_index_actual` comes into existence, computed for the first time." PRD
        §3.5 adds that the retrospective figure "never influences `risk_tier`."

        Design: Corner/validations/same_high_tier_publish_succeeds_once_lead_completes_required_module
        """
        W.file_training(api, desk, module_code=C.MODULE_SOURCING,
                        case_study_reference="CS-2025-04")
        story = self._cleared_high_tier_story(api, desk, legal_reviewer)

        published = W.publish_story(api, desk, story["id"])

        assert published["publication_status"] == C.PUB_PUBLISHED
        A.assert_instant_equals(published["published_at"], C.CLOCK_EPOCH)
        A.assert_risk_figures(published, actual=40.00, tier=C.TIER_HIGH)

        reporter = W.read_journalist(api, desk, desk.reporter_id)
        assert reporter["training_current"] is True
        assert reporter["completed_required_module_count"] == 1

        assert W.read_summary(api, desk)["published_story_count"] == 1


class TestTrainingModuleUniqueness:
    """One record per module per journalist, and no more."""

    def test_the_same_module_cannot_be_filed_twice(self, api):
        """The distinct-module count is unmoved by the refusal.

        PRD §3.8: "A journalist may file at most one record per `module_code`, and
        a duplicate is refused with `ERR_DUPLICATE_TRAINING_MODULE`." PRD §3.8
        counts only distinct codes: "The journalist's
        `completed_required_module_count` is recomputed as the number of
        **distinct** `module_code` values across their training records that also
        appear in their newsroom's `required_module_codes`", and "`training_current`
        is then true exactly when `completed_required_module_count` equals the
        number of codes in `required_module_codes`, and false otherwise."

        Design: Corner/validations/second_training_record_for_same_module_returns_duplicate_training_module
        """
        desk = W.build_desk(
            api, required_module_codes=[C.MODULE_SOURCING, C.MODULE_CORRECTIONS]
        )
        W.file_training(
            api, desk, module_code=C.MODULE_SOURCING,
            case_study_reference="CS-2025-04",
        )

        response = api.create_training_record(
            F.training_record_payload(
                desk.reporter_id, C.MODULE_SOURCING, "CS-2025-09"
            ),
            make_reporter_headers(desk.reporter_id),
        )

        validate_error(response, E.ERR_DUPLICATE_TRAINING_MODULE, 409)

        A.assert_total_count(
            api.list_journalist_training_records(
                desk.reporter_id, desk.reporter_headers
            ),
            1,
        )
        reporter = W.read_journalist(api, desk, desk.reporter_id)
        assert reporter["completed_required_module_count"] == 1
        assert reporter["training_current"] is False


class TestNoticeTextRule:
    """One error id guarding both directions of the notice requirement."""

    def test_a_no_action_outcome_may_not_carry_a_notice(self, api, desk):
        """Supplying a notice with ``NO_ACTION`` is the mirror-image mistake.

        PRD §3.6: "`notice_text` is required whenever `outcome_type` is
        `CORRECTION`, `CLARIFICATION`, `UPDATE` or `EDITORS_NOTE`, and must be
        absent when it is `NO_ACTION`; either mistake is refused with
        `ERR_NOTICE_TEXT_REQUIRED`." PRD §3.6 leaves the adjudicated grading
        unwritten, since `adjudicated_severity_score` and
        `adjudicated_severity_band` are "both of which are null until then."

        Design: Corner/validations/no_action_adjudication_carrying_notice_text_returns_notice_text_required
        """
        story = W.open_story(api, desk, "A complaint under review")
        request = W.investigating_correction(
            api,
            desk,
            story["id"],
            claim_text="The chart axis is mislabelled.",
            claimed_error_category=C.CATEGORY_NUMERIC,
            reader_reported_reach=4000,
            subject_named=False,
        )

        response = api.adjudicate_correction_request(
            request["id"],
            F.adjudication_payload(
                C.OUTCOME_NO_ACTION,
                C.CATEGORY_NUMERIC,
                4000,
                "We stand by the chart as published.",
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_NOTICE_TEXT_REQUIRED, 422)

        held = W.read_correction_request(api, desk, request["id"])
        assert held["status"] == C.CORRECTION_INVESTIGATING
        assert held["notice_text"] is None
        assert held["adjudicated_severity_band"] is None
        A.assert_story_counters(
            W.read_story(api, desk, story["id"]), open_corrections=1
        )


class TestRestrictedBeatGate:
    """A bar on outside work that one record writes and another reads."""

    def test_a_paid_engagement_on_a_barred_beat_cannot_be_approved(self, api, desk):
        """The restriction arrives through the disclosure, not the request.

        PRD §3.8: "`IMPOSE_RESTRICTION` moves it `SUBMITTED → RESTRICTION_IMPOSED`
        and requires the `restricted_beats` array to be present and non-empty; the
        supplied beat labels are stored on the disclosure, and the journalist's own
        `restricted_beats` field is then recomputed as the union of
        `restricted_beats` over all of that journalist's disclosures in
        `RESTRICTION_IMPOSED`." PRD §3.8 then reads it back: approval requires
        "that the request's `related_beat` is not a member of the journalist's
        `restricted_beats`, or the approval is refused with
        `ERR_ACTIVITY_BEAT_RESTRICTED`", and the request itself stays where PRD
        §3.8 created it: "The request is created in `status` `REQUESTED`."

        Design: Corner/validations/approving_activity_on_restricted_beat_returns_activity_beat_restricted
        """
        disclosure = W.file_disclosure(
            api,
            desk,
            disclosure_type=C.DISCLOSURE_FINANCIAL,
            subject_entity_name="Northline Power",
            description="Inherited equity in a regional utility.",
        )
        W.review_disclosure(
            api, desk, disclosure["id"], C.REVIEW_IMPOSE_RESTRICTION, ["energy"]
        )
        request = W.request_activity(
            api,
            desk,
            "2026-09-10T09:00:00Z",
            "2026-09-10T17:00:00Z",
            activity_type=C.ACTIVITY_SPEAKING,
            compensated=True,
            related_beat="energy",
            host_organization="Regional Utility Forum",
        )

        response = api.decide_activity_request(
            request["id"],
            F.activity_decision_payload(
                C.DECISION_APPROVE, "Attempting approval on a barred beat."
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_ACTIVITY_BEAT_RESTRICTED, 422)

        assert W.read_journalist(api, desk, desk.reporter_id)["restricted_beats"] == [
            "energy"
        ]
        assert (
            W.read_disclosure(api, desk, disclosure["id"])["status"]
            == C.DISCLOSURE_RESTRICTION_IMPOSED
        )
        held = W.read_activity_request(api, desk, request["id"])
        assert held["status"] == C.ACTIVITY_REQUESTED
        assert held["decided_at"] is None


class TestReviewAssignmentAdmission:
    """The checks a booking must clear before any minute is committed."""

    def test_a_standards_reviewer_cannot_take_the_legal_stage(self, api, desk):
        """The required discipline follows the stage the round waits on.

        PRD §3.4: "the reviewer's `discipline` must match the stage the round is
        actually waiting on: `LEGAL` when the round's `status` is `SUBMITTED` and
        its `requires_legal_review` is true, and `STANDARDS` in every other case. A
        mismatch is refused with `ERR_REVIEWER_DISCIPLINE_MISMATCH`." PRD §3.3
        pins the track at submission: `requires_legal_review` "is true when
        `high_risk_declared` is true **or** when the story's `risk_tier` is `HIGH`
        at that moment, and false otherwise."

        Design: Corner/validations/booking_standards_reviewer_on_legal_stage_returns_reviewer_discipline_mismatch
        """
        reviewer = W.add_reviewer(
            api,
            desk,
            full_name="Tomas Neri",
            discipline=C.DISCIPLINE_STANDARDS,
            weekly_capacity_minutes=480,
        )
        story = W.open_story(api, desk, "A story the lawyers must read first")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                reviewer["id"],
                "2026-08-02T09:00:00Z",
                "2026-08-02T10:00:00Z",
                reviewer["version"],
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_REVIEWER_DISCIPLINE_MISMATCH, 422)

        held_round = W.read_review(api, desk, review["id"])
        assert held_round["requires_legal_review"] is True
        assert held_round["status"] == C.REVIEW_SUBMITTED

        untouched = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(untouched, 0, 480)
        assert untouched["version"] == reviewer["version"]

    def test_a_slot_that_ends_before_it_starts_is_refused_before_any_arithmetic(
        self, api, desk
    ):
        """Interval sanity comes first, so no negative duration is ever derived.

        PRD §3.4: "`ends_at` must be strictly after `starts_at`, and a
        non-positive interval is refused with `ERR_INVALID_INTERVAL`." PRD §3.4
        leaves the ledger a pure re-aggregation: "`reserved_minutes` is never
        adjusted by a delta. It is always recomputed as the sum of
        `duration_minutes` over every booking of that reviewer whose `status` is
        `SCHEDULED`".

        Design: Corner/validations/assignment_ending_before_it_starts_returns_invalid_interval
        """
        reviewer = W.add_reviewer(
            api,
            desk,
            full_name="Tomas Neri",
            discipline=C.DISCIPLINE_STANDARDS,
            weekly_capacity_minutes=480,
        )
        story = W.open_story(api, desk, "A routine read")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                reviewer["id"],
                "2026-08-02T11:00:00Z",
                "2026-08-02T10:00:00Z",
                reviewer["version"],
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_INVALID_INTERVAL, 400)

        untouched = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(untouched, 0, 480)
        A.assert_total_count(
            api.list_assignments(desk.sed_headers, {"review_id": review["id"]}), 0
        )


class TestUnpublishJustification:
    """Removal from the site needs something on the record to point at."""

    def test_a_story_nothing_faults_cannot_be_taken_down(self, api, desk):
        """Neither a sustained finding nor a severe correction exists.

        PRD §3.5: "Beyond that, at least one of two things must be true: either
        some misconduct investigation with `status` `SUSTAINED` names this story,
        or the story's `severe_correction_count` is 1 or more. If neither holds,
        the removal is refused with `ERR_UNPUBLISH_NOT_JUSTIFIED` — editors may not
        quietly disappear a story that nothing on the record faults." PRD §3.5
        describes what a successful removal would have written: "`unpublished_at`
        is stamped from the logical clock, `editors_note_text` is stored on the
        story".

        Design: Corner/validations/unpublishing_a_clean_story_returns_unpublish_not_justified
        """
        story = W.published_story(api, desk, "A story nobody has disputed")

        response = api.unpublish_story(
            story["id"],
            F.unpublish_payload(
                "An editor changed their mind about the framing.",
                "This story has been removed.",
            ),
            desk.exec_headers,
        )

        validate_error(response, E.ERR_UNPUBLISH_NOT_JUSTIFIED, 422)

        held = W.read_story(api, desk, story["id"])
        A.assert_story_dimensions(held, C.PUB_PUBLISHED, C.STD_CLEAN)
        A.assert_story_counters(held, severe_corrections=0)
        assert held["unpublished_at"] is None
        assert held["editors_note_text"] is None

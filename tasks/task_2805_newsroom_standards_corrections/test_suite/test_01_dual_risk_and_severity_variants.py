"""The two figures a story and a complaint each carry twice over."""

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as W


def _published_high_tier_story(api, desk):
    """A ``PUBLISHED`` story whose ``risk_index_estimate`` is exactly 40.00.

    Seven potentially defamatory assertions (21), three identifiable private
    individuals (6), one unverified document (5) and two approved anonymous
    sources at ``SEVERE`` harm risk (8) add to a subtotal of 40, which an
    unblemished lead journalist passes through unchanged.
    """
    legal_reviewer = W.add_legal_reviewer(api, desk)
    W.file_training(api, desk, desk.reporter, C.MODULE_SOURCING)
    story = W.open_story(
        api,
        desk,
        "Contract steering at the port authority",
        defamation_claim_count=7,
        privacy_subject_count=3,
        unverified_document_count=1,
    )
    W.approved_sources(api, desk, story["id"], C.HARM_SEVERE, 2)
    review = W.submit_review(api, desk, story["id"], high_risk_declared=False)
    W.record_legal_pass(
        api,
        desk,
        review["id"],
        legal_reviewer,
        defamation_findings=7,
        privacy_findings=3,
    )
    W.record_standards_pass(api, desk, review["id"])
    W.clear_round(api, desk, review["id"])
    return W.publish_story(api, desk, story["id"])


class TestStoryRiskIndexVariants:
    """``risk_index_estimate`` and ``risk_index_actual`` on one story."""

    def test_actual_index_is_born_equal_to_the_estimate_at_publication(
        self, api, desk
    ):
        """Publication mints the retrospective figure from the same inputs.

        PRD §3.5: "Publication is also the moment `risk_index_actual` comes
        into existence, computed for the first time." PRD §3.5 also states that
        "`risk_index_actual` follows the same skeleton as the estimate from
        §3.2 — the same sourcing base, the same journalist multiplier, the same
        100.00 ceiling, the same half-up rounding to 2 decimal places in the
        same pinned order — but it adds what actually went wrong to the two
        declared-exposure terms." With nothing yet gone wrong the two figures
        agree.

        Design: Difficulty/dual_variant_calc/story_risk_index_estimate_versus_actual_diverge_after_severe_correction
        """
        story = _published_high_tier_story(api, desk)

        A.assert_story_dimensions(story, C.PUB_PUBLISHED, C.STD_CLEAN)
        A.assert_risk_figures(story, estimate=40.00, actual=40.00, tier=C.TIER_HIGH)
        A.assert_story_counters(story, approved_sources=2, severe_corrections=0)

    def test_severe_adjudication_moves_only_the_actual_index(self, api, desk):
        """A sustained severe correction reprices the past, not the forecast.

        PRD §3.5: to the claim term the actual index "adds six points for
        every one of the story's correction requests whose `status` is
        `ADJUDICATED` or `RESOLVED` and whose `adjudicated_severity_band` is
        `MAJOR` or `SEVERE`". PRD §3.2 pins the forward-looking figure to the
        declared inventory alone, and PRD §3.5 adds that the actual index
        "never influences `risk_tier`".

        Design: Difficulty/dual_variant_calc/story_risk_index_estimate_versus_actual_diverge_after_severe_correction
        """
        story = _published_high_tier_story(api, desk)
        request = W.investigating_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email="counsel@portauthority.test",
            claim_text=(
                "The story misidentifies the official who signed the steering memo."
            ),
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=250000,
            subject_named=True,
        )

        adjudicated = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CORRECTION,
            C.CATEGORY_IDENTIFICATION,
            250000,
            notice_text=(
                "An earlier version misidentified the official who signed the memo."
            ),
        )

        A.assert_adjudicated_severity(adjudicated, 21, C.BAND_SEVERE)
        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, severe_corrections=1)
        A.assert_risk_figures(reread, estimate=40.00, actual=46.00, tier=C.TIER_HIGH)
        assert reread["publication_status"] == C.PUB_PUBLISHED


class TestCorrectionSeverityVariants:
    """The provisional and adjudicated gradings of one complaint."""

    def _subject_identification_complaint(self, api, desk):
        story = W.open_story(
            api, desk, "Transit budget overrun reaches nine figures",
            defamation_claim_count=1,
        )
        request = W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email="press@transit.test",
            claim_text="You named the wrong deputy director as the budget owner.",
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=250000,
            subject_named=False,
        )
        return story, request

    def test_provisional_grading_reads_the_complainants_own_account(
        self, api, desk
    ):
        """Intake grades the complaint as the complainant described it.

        PRD §3.6: "The first run happens once, at intake, from the
        complainant's own account: the category is `claimed_error_category`,
        the reach is `reader_reported_reach`, and the subject flag is set
        exactly when `submitter_type` is `SUBJECT`." An `IDENTIFICATION` claim
        (8) from a subject (4) reporting a reach of 250,000 (6) raws at 18,
        which PRD §3.6 bands `SEVERE` and surcharges by 3.

        Design: Difficulty/dual_variant_calc/correction_severity_provisional_versus_adjudicated_bands_disagree
        """
        story, request = self._subject_identification_complaint(api, desk)

        A.assert_provisional_severity(request, 21, C.BAND_SEVERE)
        assert request["status"] == C.CORRECTION_INTAKE
        assert request["adjudicated_severity_score"] is None
        assert request["adjudicated_severity_band"] is None
        assert request["placement"] is None

    def test_adjudicated_grading_reads_the_desks_findings_and_disagrees(
        self, api, desk
    ):
        """The desk's verified account bands the same row two steps lower.

        PRD §3.6: "The second run happens at adjudication, from the desk's
        verified account: the category is `adjudicated_error_category`, the
        reach is `verified_reach`, and the subject flag is the request's own
        `subject_named` field." A `NUMERIC` finding (4) with no named subject
        (0) at a verified reach of 8,000 (2) raws at 6, which bands `MINOR`.
        PRD §3.6: "A `CORRECTION` is placed at the `TOP_OF_STORY` when its
        adjudicated band is `MAJOR` or `SEVERE`, and at the `END_OF_STORY` when
        that band is `TRIVIAL` or `MINOR`."

        Design: Difficulty/dual_variant_calc/correction_severity_provisional_versus_adjudicated_bands_disagree
        """
        story, request = self._subject_identification_complaint(api, desk)
        W.start_investigation(api, desk, request["id"])

        adjudicated = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CORRECTION,
            C.CATEGORY_NUMERIC,
            8000,
            notice_text="The overrun was 94 million dollars, not 194 million.",
        )

        A.assert_provisional_severity(adjudicated, 21, C.BAND_SEVERE)
        A.assert_adjudicated_severity(adjudicated, 7, C.BAND_MINOR)
        assert adjudicated["placement"] == C.PLACEMENT_END_OF_STORY
        assert adjudicated["status"] == C.CORRECTION_ADJUDICATED
        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, severe_corrections=0)
        assert reread["standards_status"] == C.STD_CORRECTED

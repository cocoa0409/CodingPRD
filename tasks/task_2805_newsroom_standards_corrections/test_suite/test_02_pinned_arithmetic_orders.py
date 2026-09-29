"""Formulas whose answer depends on the order their steps are taken in."""

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as W


class TestRiskIndexMultiplierOrder:
    """Subtotal, then multiplier, then cap, then rounding."""

    def test_multiplier_scales_the_subtotal_and_leaves_a_half_point(
        self, api, desk
    ):
        """A 1.10 multiplier on a subtotal of 45 lands on 49.50.

        PRD §3.2: "Read `penalty_points` from the journalist named in
        `lead_journalist_id`. If that figure is 6 or more, the subtotal is
        multiplied by 1.25; otherwise, if it is 3 or more, the subtotal is
        multiplied by 1.10; otherwise the multiplier is 1.00 and the subtotal
        passes through unchanged." PRD §3.2 also fixes that "The order matters
        and is fixed: subtotal first, then the multiplier, then the cap, then
        the rounding." Ten defamatory assertions (30), five private
        individuals (10) and one unverified document (5) make the subtotal 45.

        Design: Difficulty/combinatorial_formula/risk_index_multiplier_applied_before_cap_and_rounding
        """
        W.sustained_investigation(
            api,
            desk,
            desk.reporter_id,
            C.ALLEGATION_PLAGIARISM,
            C.SEVERITY_SERIOUS,
            allegation_summary=(
                "Three paragraphs of a 2025 feature reproduce a trade-journal "
                "article without attribution."
            ),
        )
        lead = W.read_journalist(api, desk, desk.reporter_id)
        assert lead["penalty_points"] == 5
        assert lead["employment_status"] == C.EMPLOYMENT_ACTIVE

        story = W.open_story(
            api,
            desk,
            "Ten disputed assertions about the housing authority",
            defamation_claim_count=10,
            privacy_subject_count=5,
            unverified_document_count=1,
        )

        A.assert_risk_figures(story, estimate=49.50, tier=C.TIER_HIGH)

    def test_cap_binds_the_multiplied_product_rather_than_the_subtotal(
        self, api, desk
    ):
        """A subtotal of 160 multiplied to 176 is held at the 100.00 ceiling.

        PRD §3.2: "The product is then capped at 100.00 — the index can never
        exceed that ceiling however lurid the story — and only after the
        capping is the result rounded half up to 2 decimal places." Fifty
        defamatory assertions (150) and five private individuals (10) make the
        subtotal 160, which the 1.10 disciplinary multiplier takes past the
        ceiling.

        Design: Difficulty/combinatorial_formula/risk_index_multiplier_applied_before_cap_and_rounding
        """
        W.sustained_investigation(
            api,
            desk,
            desk.reporter_id,
            C.ALLEGATION_PLAGIARISM,
            C.SEVERITY_SERIOUS,
            allegation_summary=(
                "Three paragraphs of a 2025 feature reproduce a trade-journal "
                "article without attribution."
            ),
        )

        story = W.open_story(
            api,
            desk,
            "Fifty disputed assertions across the whole procurement series",
            defamation_claim_count=50,
            privacy_subject_count=5,
            unverified_document_count=0,
        )

        A.assert_risk_figures(story, estimate=100.00, tier=C.TIER_HIGH)


class TestTrainingComplianceIndexRoundingOrder:
    """Each journalist's ratio is rounded before the cohort is averaged."""

    def _three_journalist_cohort(self, api):
        desk = W.build_desk(
            api,
            required_module_codes=[
                C.MODULE_SOURCING,
                C.MODULE_CORRECTIONS,
                C.MODULE_LEGAL_RISK,
            ],
        )
        W.file_training(api, desk, desk.exec_editor, C.MODULE_SOURCING)
        W.file_training(api, desk, desk.standards_editor, C.MODULE_SOURCING)
        W.file_training(api, desk, desk.reporter, C.MODULE_SOURCING)
        W.file_training(api, desk, desk.reporter, C.MODULE_CORRECTIONS)
        return desk

    def test_summary_reports_the_two_stage_rounded_index(self, api):
        """Completion counts of 1, 1 and 2 against three modules give 44.33.

        PRD §3.8: "First, for each journalist in the cohort, divide their
        `completed_required_module_count` by the number of codes in
        `required_module_codes` and round that individual ratio half up to 2
        decimal places. Second, add those already-rounded ratios together,
        divide by the number of journalists in the cohort, multiply by 100, and
        round half up to 2 decimal places again." PRD §3.8 names the wrong
        answer explicitly: "with three required modules and a three-journalist
        cohort whose completed counts are 1, 1 and 2, the pinned order yields
        44.33 while the single-rounding order would yield 44.44.
        Implementations must produce 44.33."

        Design: Difficulty/combinatorial_formula/training_compliance_index_rounds_each_ratio_before_averaging
        """
        desk = self._three_journalist_cohort(api)

        summary = W.read_summary(api, desk)

        A.assert_decimal_equals(summary["training_compliance_index"], 44.33)

    def test_newsroom_read_and_per_journalist_counts_agree_with_the_index(
        self, api
    ):
        """The cohort figures the index is built from are readable themselves.

        PRD §3.8: "The journalist's `completed_required_module_count` is
        recomputed as the number of **distinct** `module_code` values across
        their training records that also appear in their newsroom's
        `required_module_codes`" and "`training_current` is then true exactly
        when `completed_required_module_count` equals the number of codes in
        `required_module_codes`, and false otherwise."

        Design: Difficulty/combinatorial_formula/training_compliance_index_rounds_each_ratio_before_averaging
        """
        desk = self._three_journalist_cohort(api)

        newsroom = W.read_newsroom(api, desk)
        reporter = W.read_journalist(api, desk, desk.reporter_id)
        exec_editor = W.read_journalist(api, desk, desk.exec_id)

        A.assert_decimal_equals(newsroom["training_compliance_index"], 44.33)
        assert reporter["completed_required_module_count"] == 2
        assert reporter["training_current"] is False
        assert exec_editor["completed_required_module_count"] == 1


class TestSeverityBandPinnedToTheRawFigure:
    """The band is read off raw and is never re-derived from the score."""

    def _quote_complaint_raw_fifteen(self, api, desk):
        story = W.open_story(
            api,
            desk,
            "Council member quoted on the zoning swap",
            defamation_claim_count=2,
        )
        request = W.file_correction(
            api,
            desk,
            story["id"],
            headers=desk.sed_headers,
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email="aide@council.test",
            claim_text=(
                "The quotation attributed to the council member was never said "
                "in those words."
            ),
            claimed_error_category=C.CATEGORY_QUOTE,
            reader_reported_reach=120000,
            subject_named=True,
        )
        W.start_investigation(api, desk, request["id"])
        return story, request

    def test_raw_fifteen_bands_major_and_stores_a_score_of_seventeen(
        self, api, desk
    ):
        """A score above the severe edge does not promote a major band.

        PRD §3.6: "the band comes from the raw figure, the surcharge comes from
        the band, and the band is **never** re-derived from the final score. A
        raw figure of 15 bands as `MAJOR` and stores a score of 17; the fact
        that 17 exceeds the `SEVERE` edge of 16 does not promote it." A `QUOTE`
        error (5) affecting a named subject (4) at a reach of 120,000 (6) raws
        at exactly 15.

        Design: Difficulty/combinatorial_formula/correction_band_pinned_from_raw_never_rebanded_from_final_score
        """
        story, request = self._quote_complaint_raw_fifteen(api, desk)

        adjudicated = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CORRECTION,
            C.CATEGORY_QUOTE,
            120000,
            notice_text="The council member's words were paraphrased, not quoted.",
        )

        A.assert_adjudicated_severity(adjudicated, 17, C.BAND_MAJOR)
        A.assert_provisional_severity(adjudicated, 17, C.BAND_MAJOR)
        A.assert_band_not_rebanded_from_score(adjudicated)

    def test_major_band_places_the_notice_at_the_top_and_fills_the_pool_once(
        self, api, desk
    ):
        """A major adjudication counts once, and one is below a threshold of 2.

        PRD §3.6: "A `CORRECTION` is placed at the `TOP_OF_STORY` when its
        adjudicated band is `MAJOR` or `SEVERE`" and "when the adjudicated band
        is `MAJOR` or `SEVERE` the story's `severe_correction_count` is
        incremented". PRD §2.9: "Otherwise, when it reaches the threshold or
        more, the posture is `HEIGHTENED`. Below the threshold it is `OPEN`."

        Design: Difficulty/combinatorial_formula/correction_band_pinned_from_raw_never_rebanded_from_final_score
        """
        story, request = self._quote_complaint_raw_fifteen(api, desk)

        adjudicated = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CORRECTION,
            C.CATEGORY_QUOTE,
            120000,
            notice_text="The council member's words were paraphrased, not quoted.",
        )

        assert adjudicated["placement"] == C.PLACEMENT_TOP_OF_STORY
        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, severe_corrections=1)
        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_OPEN, 1)

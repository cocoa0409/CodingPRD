"""Calculation corner shapes: agreement, empty captures, precision, bubble-up."""
import pytest

from test_helpers import api_client, validate_success, get_success_data, COMPLIANCE, DEVELOPER, REASON_ADMIN, create_archive_sample, create_migration_event_payload, schedule_study, run_study, author_variant, create_model, release_variant, setup_bubble_up_tree, setup_license_with_postings, setup_protected_class_partition, release_model_with_doc


class TestRecalibrationAgreement:

    def test_identical_curves_make_both_routes_agree_exactly(self, api):
        """PRD §3.9: "When the two variants carry identical `ref_score`, `base_odds`
        and `double_odds_points`, both routes produce the same integer cut-off and
        the disagreement is exactly zero."

        Design: Corner/calculations/recalibration_variants_agree_when_the_curves_are_identical
        """
        m1 = create_model(version_label="CREDIT-DUAL-V1")
        v1 = author_variant(m1["id"])
        release_variant(v1["id"])
        m2 = create_model(version_label="PRIME-SHIFT-V2")
        v2 = author_variant(m2["id"])
        release_variant(v2["id"])
        data = validate_success(api_client.create_migration_event(
            create_migration_event_payload(
                from_score_variant_id=v1["id"], to_score_variant_id=v2["id"],
                event_type="RECALIBRATED", old_cutoff_score=640,
                evidence_ref="WS-IDENT-1"), COMPLIANCE), 201)
        assert data["new_cutoff_score_preserving"] == 640
        assert data["new_cutoff_odds_preserving"] == 640

    def test_the_disagreement_diagnostic_is_reported_as_zero(self, api):
        """PRD §3.9: "The disagreement between the two routes — the score-preserving
        cut-off minus the odds-preserving cut-off — is reported as
        `cutoff_disagreement_points` and is never by itself a reason to reject the
        request."
        PRD §3.9: "When the two variants carry identical `ref_score`, `base_odds`
        and `double_odds_points`, both routes produce the same integer cut-off and
        the disagreement is exactly zero."

        Design: Corner/calculations/recalibration_variants_agree_when_the_curves_are_identical
        """
        m1 = create_model(version_label="CREDIT-DUAL-V1")
        v1 = author_variant(m1["id"])
        release_variant(v1["id"])
        m2 = create_model(version_label="PRIME-SHIFT-V2")
        v2 = author_variant(m2["id"])
        release_variant(v2["id"])
        data = validate_success(api_client.create_migration_event(
            create_migration_event_payload(
                from_score_variant_id=v1["id"], to_score_variant_id=v2["id"],
                event_type="RECALIBRATED", old_cutoff_score=640,
                evidence_ref="WS-IDENT-1"), COMPLIANCE), 201)
        assert data["cutoff_disagreement_points"] == 0


class TestEmptyCapture:

    def _empty_capture_study(self, api):
        """A released model, a VALIDATION sample and a scheduled CROSS_BUREAU
        study, with no licence and therefore no postings."""
        m1 = create_model(version_label="CREDIT-DUAL-V1")
        v1 = author_variant(m1["id"])
        release_variant(v1["id"])
        release_model_with_doc(m1["id"], "CREDIT-DUAL-V1")
        sample = create_archive_sample(m1["id"], sample_ref="XFER-EMPTY",
                                       record_count=3000, segment_name="PRIME",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        return schedule_study(m1["id"], sample["id"], study_path="CROSS_BUREAU",
                              performed_by="va-empty")

    def test_a_cross_bureau_run_over_no_postings_returns_zeroes(self, api):
        """PRD §3.4: "A boundary case is pinned explicitly: when the captured set
        yields zero non-voided postings, both composites return 0.0000 and the
        variance is exactly 0.00, rather than any divide-by-zero."

        Design: Corner/calculations/composite_score_over_an_empty_capture_returns_zero
        """
        study = self._empty_capture_study(api)
        ran = run_study(study["id"])
        assert ran["weighted_composite"] == 0.0
        assert ran["unweighted_composite"] == 0.0
        assert ran["reconciliation_variance"] == 0.0

    def test_the_empty_run_still_completes(self, api):
        """PRD §3.3: "On success the study moves to `VALIDATION_COMPLETE`, and the
        run is priced with `expected_study_version`."

        Design: Corner/calculations/composite_score_over_an_empty_capture_returns_zero
        """
        study = self._empty_capture_study(api)
        ran = run_study(study["id"])
        assert ran["status"] == "VALIDATION_COMPLETE"

    def test_there_really_were_no_postings_in_the_capture(self, api):
        """PRD §3.4: "Its captured set is the non-voided postings whose variant
        belongs to the study's model version across every bureau"

        Design: Corner/calculations/composite_score_over_an_empty_capture_returns_zero
        """
        self._empty_capture_study(api)
        res = api_client.list_score_results(DEVELOPER)
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 0


class TestDisparateImpactRatio:

    def test_the_protected_class_ratio_is_the_pinned_parts_per_million(self, api):
        """PRD §3.4: "The ratio is the protected rate divided by the reference rate,
        multiplied by one million, rounded half-up to a whole parts-per-million
        integer."

        With six approvals and four declines among protected postings against
        eighteen approvals and two declines among the rest, the protected rate is
        0.6 and the reference rate is 0.9, so the ratio is 666,667 ppm.

        Design: Corner/calculations/disparate_impact_ratio_reports_the_pinned_parts_per_million_value
        """
        capture, study = setup_protected_class_partition()
        assert study["disparate_impact_ratio_ppm"] == 666667

    def test_the_cross_bureau_diagnostic_stays_unset_on_a_protected_class_run(self, api):
        """PRD §3.3: "a protected-class run computes the `disparate_impact_ratio_ppm`
        of §3.4 and leaves `reconciliation_variance` null"

        Design: Corner/calculations/disparate_impact_ratio_reports_the_pinned_parts_per_million_value
        """
        capture, study = setup_protected_class_partition()
        assert study["reconciliation_variance"] is None

    def test_undecided_postings_leave_the_ratio_untouched(self, api):
        """PRD §3.4: "A posting counts as a positive outcome when its `decision` is
        `APPROVE` and as a negative outcome when its `decision` is `DECLINE`;
        postings still sitting at `UNDECIDED` are excluded from both the numerator
        and the denominator."

        Design: Corner/calculations/disparate_impact_ratio_reports_the_pinned_parts_per_million_value
        """
        capture, study = setup_protected_class_partition()
        assert study["disparate_impact_ratio_ppm"] == 666667
        assert study["status"] == "VALIDATION_COMPLETE"


class TestOddsPrecision:

    def test_the_odds_field_carries_four_decimal_places(self, api):
        """PRD §2.6: "The `odds_at_posted_score` recorded on a posting carries
        exactly four decimal places, rounded half-up."

        Design: Corner/calculations/score_effective_odds_carry_four_decimal_places
        """
        # raw 790 on the CREDIT-DUAL-V1 AUTO curve lands on effective 784, whose
        # odds are 18 * 2^(84/35) = 95.0046 -- a value that only matches to four
        # decimal places if the whole term is rounded half-up at the end.
        fixture = setup_license_with_postings(num_postings=1, consumer_ref="cons-prec",
                                              raw_posted_score=790)
        posting = fixture["results"][0]
        assert posting["effective_score"] == 784
        assert posting["odds_at_posted_score"] == pytest.approx(95.0046, abs=0.00005)

    def test_the_odds_are_read_at_the_effective_score_not_the_raw_one(self, api):
        """PRD §3.8: "The odds reported alongside the score are formed from the
        effective score rather than the raw one."

        Design: Corner/calculations/score_effective_odds_carry_four_decimal_places
        """
        fixture = setup_license_with_postings(num_postings=1, consumer_ref="cons-prec")
        posting = fixture["results"][0]
        assert posting["effective_score"] == 700
        assert posting["odds_at_posted_score"] != 715.0

    def test_the_stored_row_keeps_the_same_precision(self, api):
        """PRD §2.6: "The `odds_at_posted_score` recorded on a posting carries
        exactly four decimal places, rounded half-up."

        Design: Corner/calculations/score_effective_odds_carry_four_decimal_places
        """
        fixture = setup_license_with_postings(num_postings=1, consumer_ref="cons-prec",
                                              raw_posted_score=790)
        stored = get_success_data(
            api_client.get_score_result(fixture["results"][0]["id"], DEVELOPER), 200)
        assert stored["odds_at_posted_score"] == pytest.approx(95.0046, abs=0.00005)


class TestBubbleUpRouting:

    def test_a_below_floor_leaf_routes_its_whole_weight_to_its_parent(self, api):
        """PRD §3.5: "A child whose `weight_pct` is below 0.05 routes its entire
        weight to its `parent_reason_code_id`, and that parent's
        `weight_received_pct` becomes the sum of every such child's `weight_pct`."

        Design: Corner/calculations/bubble_up_weight_reaches_only_the_immediate_parent
        """
        _, _, _, a, b, c, d = setup_bubble_up_tree()
        validate_success(
            api_client.archive_reason_code(c["id"], REASON_ADMIN), 200)
        # The routed share lands on the *parent* (PRD §3.5), not on the leaf.
        parent = get_success_data(api_client.get_reason_code(b["id"], REASON_ADMIN), 200)
        assert parent["weight_received_pct"] == 0.03

    def test_the_parents_effective_weight_absorbs_the_routed_share(self, api):
        """PRD §3.5: "and the `weight_effective_pct`, which is the entry's own
        `weight_pct` plus whatever `weight_received_pct` has bubbled up to it,
        rounded half-up to four decimal places."

        Design: Corner/calculations/bubble_up_weight_reaches_only_the_immediate_parent
        """
        _, _, _, a, b, c, d = setup_bubble_up_tree()
        api_client.archive_reason_code(c["id"], REASON_ADMIN)
        parent = get_success_data(api_client.get_reason_code(b["id"], REASON_ADMIN), 200)
        assert parent["weight_received_pct"] == 0.03
        assert parent["weight_effective_pct"] == pytest.approx(0.23, abs=1e-9)

    def test_routing_stops_after_one_hop(self, api):
        """PRD §3.5: "Routing is exactly one hop: if both a parent and a grandparent
        would qualify as recipients, only the immediate parent receives the share and
        the grandparent receives nothing."

        Design: Corner/calculations/bubble_up_weight_reaches_only_the_immediate_parent
        """
        _, _, _, a, b, c, d = setup_bubble_up_tree()
        api_client.archive_reason_code(c["id"], REASON_ADMIN)
        grandparent = get_success_data(api_client.get_reason_code(a["id"], REASON_ADMIN), 200)
        assert grandparent["weight_received_pct"] == 0

    def test_a_sibling_above_the_floor_routes_nothing(self, api):
        """PRD §3.5: "A child whose `weight_pct` is at or above 0.05 routes nothing."

        Design: Corner/calculations/bubble_up_weight_reaches_only_the_immediate_parent
        """
        _, _, _, a, b, c, d = setup_bubble_up_tree()
        assert d["weight_pct"] == 0.30
        sibling = get_success_data(api_client.get_reason_code(d["id"], REASON_ADMIN), 200)
        assert sibling["status"] == "ACTIVE"
        assert sibling["weight_received_pct"] == 0

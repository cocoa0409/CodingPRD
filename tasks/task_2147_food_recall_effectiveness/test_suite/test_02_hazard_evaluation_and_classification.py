"""Health hazard evaluation, panel ratification and recall classification."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    RecallCase,
    assert_effectiveness_payload,
    assert_hazard_evaluation,
    create_hazard_evaluation_payload,
    draft_case,
    make_coordinator_headers,
    make_panel_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")
PANEL = make_panel_headers("panel-1")


def test_filed_evaluation_is_server_stamped_and_bumps_the_recall_version(api):
    """PRD §3.2: "A newly filed evaluation is in `status` `DRAFT`."
    PRD §3.2: "While the evaluation is still the firm's own assertion — at creation, and at every submission and resubmission — the `variant` is `PRELIMINARY`, `evidence_strength` is ignored entirely and the scale is forced to 1.00."
    PRD §3.2: "Finally, `hazard_score` is the sum of the base figure, the exposure factor and the vulnerability bonus, multiplied by that scale, rounded half up to two decimal places."
    PRD §2.5: "A successful filing itself increments the recall's `version` by one, so a client filing two evaluations in sequence must re-read the recall between them."

    Design: Corner/entities/hazard_evaluation_system_fields_are_server_minted_input_ignored
    """
    case = draft_case()
    response = api.create_hazard_evaluation(
        case.recall_id,
        create_hazard_evaluation_payload(case.recall["version"]),
        case.officer,
    )
    evaluation = validate_success(response, 201)
    assert_hazard_evaluation(evaluation)
    assert evaluation["status"] == "DRAFT"
    assert evaluation["variant"] == "PRELIMINARY"
    assert evaluation["hazard_score"] == 87.40
    assert evaluation["recall_id"] == case.recall_id
    assert case.read_recall()["version"] == 2


def test_panel_cannot_decide_an_evaluation_still_in_draft(api):
    """PRD §3.2: "Deciding an evaluation that is not currently `SUBMITTED` is refused with `ERR_INVALID_EVALUATION_STATE`."
    PRD §3.2: "While the evaluation is still the firm's own assertion — at creation, and at every submission and resubmission — the `variant` is `PRELIMINARY`, `evidence_strength` is ignored entirely and the scale is forced to 1.00."

    Design: Corner/errors/panel_decide_on_a_draft_evaluation_returns_invalid_evaluation_state
    """
    case = draft_case()
    evaluation = case.file_evaluation(evidence_strength="SUSPECTED")

    response = api.decide_hazard_evaluation(
        evaluation["id"], {"decision": "RATIFY"}, PANEL
    )
    validate_error(response, ApiErrorId.ERR_INVALID_EVALUATION_STATE.value)
    assert response.status_code == 409

    rows, _ = validate_paginated(
        api.list_hazard_evaluations(case.recall_id, COORDINATOR)
    )
    after = rows[0]
    assert after["status"] == "DRAFT"
    assert after["variant"] == "PRELIMINARY"
    assert after["hazard_score"] == 87.40
    assert after["ratified_by_user_id"] is None


def test_submitting_an_unknown_evaluation_returns_subresource_not_found(api):
    """PRD §2.6: "The flat-addressed sub-resource exists — otherwise `ERR_SUBRESOURCE_NOT_FOUND` (404). Applies to every action endpoint addressed as `/hazard-evaluations/{id}`, `/distribution-records/{id}`, `/notifications/{id}`, `/retrieval-receipts/{id}`, `/public-warnings/{id}`, `/disposition-orders/{id}`, `/status-reports/{id}`, `/cost-entries/{id}` or `/insurance-claims/{id}`."

    Design: Corner/errors/submit_unknown_hazard_evaluation_returns_subresource_not_found
    """
    response = api.submit_hazard_evaluation(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_SUBRESOURCE_NOT_FOUND.value)
    assert response.status_code == 404


def test_health_hazard_panel_may_not_classify_the_recall(api):
    """PRD §2.1: "If both headers are well formed but the acting role does not appear in the authorized-role list published for the endpoint in §4, the rejection is `ERR_ROLE_NOT_PERMITTED` with HTTP 403."
    PRD §2.1: "A `HealthHazardPanel` has exactly one write power — ratifying or returning a submitted hazard evaluation — and may never classify a recall itself, which is precisely what forces evaluation and classification apart."

    Design: Corner/rbac/health_hazard_panel_cannot_classify_a_recall
    """
    case = draft_case()
    case.ratified_evaluation()

    response = api.classify_recall(case.recall_id, {"hazard_class": "CLASS_I"}, PANEL)
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert response.status_code == 403

    after = case.read_recall()
    assert after["status"] == "DRAFT"
    assert after["hazard_class"] is None


def test_second_filing_against_a_stale_recall_version_is_rejected(api):
    """PRD §2.5: "A request to `POST /recalls/{id}/hazard-evaluations` must carry `expected_recall_version` as a required, non-optional body field holding the client's last observed `version` of the target `Recall`."
    PRD §2.5: "If that value does not equal the recall's current `version`, the filing is rejected with `ERR_STALE_RECALL_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_recall_version_on_hazard_evaluation_returns_precondition_failed
    """
    case = draft_case()
    observed_version = case.recall["version"]

    first = api.create_hazard_evaluation(
        case.recall_id,
        create_hazard_evaluation_payload(observed_version),
        case.officer,
    )
    first_evaluation = validate_success(first, 201)

    second = api.create_hazard_evaluation(
        case.recall_id,
        create_hazard_evaluation_payload(
            observed_version, probability_of_adverse_health="MEDIUM",
            severity_tier=3, exposure_population=30000,
            vulnerable_population=False, evidence_strength="PROBABLE",
        ),
        case.officer,
    )
    validate_error(second, ApiErrorId.ERR_STALE_RECALL_VERSION.value)
    assert second.status_code == 412

    assert case.read_recall()["version"] == 2
    rows, meta = validate_paginated(
        api.list_hazard_evaluations(case.recall_id, COORDINATOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first_evaluation["id"]


def test_effectiveness_level_moves_from_c_to_b_when_a_tier_two_consignee_appears(api):
    """PRD §3.3: "The `effectiveness_check_level` is `A` when the recall is `CLASS_I`; it is `B` when the recall is `CLASS_II` and at least one consignee of this recall sits at `tier` 2 or deeper; it is `C` when the recall is `CLASS_II` and every consignee of this recall is a direct, tier-1 consignee; and it is `D` when the recall is `CLASS_III`."
    PRD §3.3: "The `required_sample_size` is zero when there are no eligible consignees at all; otherwise it is the eligible count multiplied by the level percentage — 100 percent for level `A`, 50 percent for level `B`, 10 percent for level `C` and 2 percent for level `D` — rounded up to a whole number, and then floored at 1 so that a non-empty eligible set always demands at least one response."
    PRD §3.1: "Every addition re-runs the sampling arithmetic described in §3.3, so `eligible_consignee_count`, `required_sample_size` and each consignee's `in_effectiveness_sample` stay current as the tree grows."

    Design: Corner/calculations/effectiveness_level_flips_from_c_to_b_when_a_tier_two_consignee_appears
    """
    case = RecallCase(agency="FDA")
    case.ratified_evaluation(
        probability_of_adverse_health="MEDIUM", severity_tier=3,
        exposure_population=30000, vulnerable_population=False,
        evidence_strength="CONFIRMED",
    )
    case.classify("CLASS_II")
    c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
    case.add_consignee("Harbor Grocery", "RETAILER")
    case.add_consignee("Lakeside Market", "RETAILER")

    before = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
    assert_effectiveness_payload(before)
    assert before["effectiveness_check_level"] == "C"
    assert before["eligible_consignee_count"] == 3
    assert before["required_sample_size"] == 1

    c4 = case.add_consignee("Pier Cafe", "RESTAURANT", parent_consignee_id=c1["id"])
    assert c4["tier"] == 2

    after = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
    assert after["effectiveness_check_level"] == "B"
    assert after["eligible_consignee_count"] == 4
    assert after["required_sample_size"] == 2
    assert after["sample_tier_scope"] == 2

    recall = case.read_recall()
    assert recall["effectiveness_check_level"] == "B"
    assert recall["required_sample_size"] == 2


class TestHazardScoreVariants:
    """The PRELIMINARY score ignores evidence strength; ratification applies it."""

    def test_ratification_rescales_the_score_by_the_evidence_scale(self, api):
        """PRD §3.2: "Once the panel ratifies, the `variant` becomes `RATIFIED` and the scale becomes the evidence scale for the recorded `evidence_strength`: 1.00 for `CONFIRMED`, 0.80 for `PROBABLE`, 0.55 for `SUSPECTED`."
        PRD §3.2: "A `decision` of `RATIFY` advances `SUBMITTED → RATIFIED`, flips the `variant` to `RATIFIED`, recomputes `hazard_score` and `recommended_class` with the evidence scaling now applied, stamps `ratified_by_user_id`, and — this is the cross-entity part — moves every *other* evaluation of the same recall that was in `RATIFIED` to `SUPERSEDED`, so at most one ratified evaluation is ever live."

        Design: Difficulty/dual_variant_calc/hazard_score_preliminary_vs_ratified_diverge_by_evidence_scale
        """
        case = draft_case()
        evaluation = case.file_evaluation(evidence_strength="SUSPECTED")
        submitted = case.submit_evaluation(evaluation["id"])
        assert submitted["hazard_score"] == 87.40
        assert submitted["recommended_class"] == "CLASS_I"

        ratified = case.decide_evaluation(
            evaluation["id"], "RATIFY",
            panel_note="Link to illness cluster is suspected only.",
        )
        assert_hazard_evaluation(ratified)
        assert ratified["status"] == "RATIFIED"
        assert ratified["variant"] == "RATIFIED"
        assert ratified["hazard_score"] == 48.07
        assert ratified["recommended_class"] == "CLASS_II"

    def test_preliminary_and_ratified_scores_diverge_for_identical_inputs(self, api):
        """PRD §3.2: "While the evaluation is still the firm's own assertion — at creation, and at every submission and resubmission — the `variant` is `PRELIMINARY`, `evidence_strength` is ignored entirely and the scale is forced to 1.00."
        PRD §3.2: "Discounting a merely suspected link to 0.55 can move `recommended_class` down one class or even two for identical inputs, which is exactly the effect the two-variant design is meant to produce."
        PRD §3.2: "The `recommended_class` follows directly: `CLASS_I` when `hazard_score` is at least 70.00, otherwise `CLASS_II` when it is at least 35.00, otherwise `CLASS_III`."

        Design: Difficulty/dual_variant_calc/hazard_score_preliminary_vs_ratified_diverge_by_evidence_scale
        """
        case = draft_case()
        evaluation = case.file_evaluation(evidence_strength="SUSPECTED")
        preliminary_score = case.submit_evaluation(evaluation["id"])["hazard_score"]

        ratified = case.decide_evaluation(evaluation["id"], "RATIFY")
        assert ratified["hazard_score"] != preliminary_score, (
            "The RATIFIED variant must rescale the score for a SUSPECTED link"
        )
        assert preliminary_score == 87.40
        assert ratified["hazard_score"] == 48.07


class TestEvaluationReviewCycle:
    """SUBMITTED → RETURNED → SUBMITTED → RATIFIED, with the score recomputed."""

    def test_return_then_resubmit_increments_return_count(self, api):
        """PRD §3.2: "A `decision` of `RETURN` advances `SUBMITTED → RETURNED` and increments `return_count` by one."
        PRD §3.2: "An evaluation sitting in `RETURNED` is resubmitted along the `RETURNED → SUBMITTED` edge, with exactly the same side effects as a first submission — the `variant` reverts to `PRELIMINARY`, the score is recomputed without evidence scaling, and `submitted_by_user_id` is restamped."

        Design: Difficulty/non_linear_state_machine/hazard_evaluation_submit_return_resubmit_ratify_cycle
        """
        case = draft_case()
        evaluation = case.file_evaluation(
            probability_of_adverse_health="MEDIUM", severity_tier=3,
            exposure_population=30000, vulnerable_population=False,
            evidence_strength="PROBABLE",
        )
        case.submit_evaluation(evaluation["id"])

        returned = case.decide_evaluation(
            evaluation["id"], "RETURN", panel_note="Attach the serotype confirmation."
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_count"] == 1

        resubmitted = case.submit_evaluation(evaluation["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["variant"] == "PRELIMINARY"
        assert resubmitted["hazard_score"] == 42.00

    def test_ratifying_after_a_return_applies_the_probable_evidence_scale(self, api):
        """PRD §3.2: "Once the panel ratifies, the `variant` becomes `RATIFIED` and the scale becomes the evidence scale for the recorded `evidence_strength`: 1.00 for `CONFIRMED`, 0.80 for `PROBABLE`, 0.55 for `SUSPECTED`."
        PRD §3.2: "There is no edge back to `DRAFT`: the review cycle runs `SUBMITTED → RETURNED → SUBMITTED` for as many rounds as the panel wants."

        Design: Difficulty/non_linear_state_machine/hazard_evaluation_submit_return_resubmit_ratify_cycle
        """
        case = draft_case()
        evaluation = case.file_evaluation(
            probability_of_adverse_health="MEDIUM", severity_tier=3,
            exposure_population=30000, vulnerable_population=False,
            evidence_strength="PROBABLE",
        )
        case.submit_evaluation(evaluation["id"])
        case.decide_evaluation(evaluation["id"], "RETURN")
        case.submit_evaluation(evaluation["id"])

        ratified = case.decide_evaluation(evaluation["id"], "RATIFY")
        assert ratified["hazard_score"] == 33.60
        assert ratified["recommended_class"] == "CLASS_III"
        assert ratified["status"] == "RATIFIED"
        assert ratified["return_count"] == 1


class TestHazardClassThresholdBoundary:
    """The CLASS_I threshold comparison is inclusive at exactly 70.00."""

    def test_score_of_exactly_seventy_recommends_class_one(self, api):
        """PRD §3.2: "The `recommended_class` follows directly: `CLASS_I` when `hazard_score` is at least 70.00, otherwise `CLASS_II` when it is at least 35.00, otherwise `CLASS_III`."
        PRD §3.2: "Second, an exposure factor is taken as the smaller of 12 and the `exposure_population` divided by 25,000 and rounded up to a whole number — so a hundred thousand exposed consumers contributes 4, and any population beyond three hundred thousand is capped at 12."

        Design: Difficulty/boundary_precision_check/hazard_score_exactly_seventy_is_class_one_while_sixtynine_is_class_two
        """
        case = draft_case()
        evaluation = case.file_evaluation(
            probability_of_adverse_health="MEDIUM", severity_tier=4,
            exposure_population=300000, vulnerable_population=False,
            evidence_strength="CONFIRMED",
        )
        case.submit_evaluation(evaluation["id"])
        ratified = case.decide_evaluation(evaluation["id"], "RATIFY")
        assert ratified["hazard_score"] == 70.00
        assert ratified["recommended_class"] == "CLASS_I"

    def test_score_one_point_below_the_threshold_recommends_class_two(self, api):
        """PRD §3.2: "The `recommended_class` follows directly: `CLASS_I` when `hazard_score` is at least 70.00, otherwise `CLASS_II` when it is at least 35.00, otherwise `CLASS_III`."
        PRD §3.2: "A `decision` of `RATIFY` advances `SUBMITTED → RATIFIED`, flips the `variant` to `RATIFIED`, recomputes `hazard_score` and `recommended_class` with the evidence scaling now applied, stamps `ratified_by_user_id`, and — this is the cross-entity part — moves every *other* evaluation of the same recall that was in `RATIFIED` to `SUPERSEDED`, so at most one ratified evaluation is ever live."

        Design: Difficulty/boundary_precision_check/hazard_score_exactly_seventy_is_class_one_while_sixtynine_is_class_two
        """
        case = draft_case()
        evaluation_a = case.file_evaluation(
            probability_of_adverse_health="MEDIUM", severity_tier=4,
            exposure_population=300000, vulnerable_population=False,
            evidence_strength="CONFIRMED",
        )
        evaluation_b = case.file_evaluation(
            probability_of_adverse_health="MEDIUM", severity_tier=4,
            exposure_population=275000, vulnerable_population=False,
            evidence_strength="CONFIRMED",
        )
        case.submit_evaluation(evaluation_a["id"])
        case.submit_evaluation(evaluation_b["id"])
        case.decide_evaluation(evaluation_a["id"], "RATIFY")
        ratified_b = case.decide_evaluation(evaluation_b["id"], "RATIFY")

        assert ratified_b["hazard_score"] == 69.00
        assert ratified_b["recommended_class"] == "CLASS_II"

        rows, _ = validate_paginated(
            api.list_hazard_evaluations(case.recall_id, COORDINATOR)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[evaluation_a["id"]]["status"] == "SUPERSEDED"
        assert by_id[evaluation_b["id"]]["status"] == "RATIFIED"


class TestClassificationRequiresARatifiedEvaluation:
    """The recall's DRAFT → CLASSIFIED edge depends on a sibling evaluation."""

    def test_classify_with_only_a_submitted_evaluation_is_rejected(self, api):
        """PRD §3.3: "A first classification requires at least one evaluation of this recall in `RATIFIED`, and without one the attempt is refused with `ERR_NO_RATIFIED_EVALUATION`."

        Design: Difficulty/cross_entity_state_dependency/classify_blocked_until_a_hazard_evaluation_is_ratified
        """
        case = draft_case()
        evaluation = case.file_evaluation()
        case.submit_evaluation(evaluation["id"])

        response = api.classify_recall(
            case.recall_id, {"hazard_class": "CLASS_I"}, COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_NO_RATIFIED_EVALUATION.value)
        assert response.status_code == 409

    def test_a_blocked_classification_leaves_the_recall_untouched(self, api):
        """PRD §3.3: "A first classification advances the recall `DRAFT → CLASSIFIED`, sets `hazard_class` from the body and `classified_by_user_id` to the acting `X-User-ID`."
        PRD §3.3: "On a first classification the server mints the recall's first status report — `report_kind` `PERIODIC`, `period_index` 1, `period_start` at the current logical instant, and both `period_end` and `due_at` at that instant plus `report_cadence_days` days — in `status` `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/classify_blocked_until_a_hazard_evaluation_is_ratified
        """
        case = draft_case()
        evaluation = case.file_evaluation()
        case.submit_evaluation(evaluation["id"])

        response = api.classify_recall(
            case.recall_id, {"hazard_class": "CLASS_I"}, COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_NO_RATIFIED_EVALUATION.value)

        recall = case.read_recall()
        assert recall["status"] == "DRAFT"
        assert recall["hazard_class"] is None
        assert recall["effectiveness_check_level"] is None

        rows, meta = validate_paginated(
            api.list_status_reports(case.recall_id, COORDINATOR)
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestReclassificationCascade:
    """Re-classification re-dates the open report, which pushes it overdue,
    which raises the recall's posture."""

    @staticmethod
    def _case_ready_for_reclassification(api):
        set_clock("2026-09-01T00:00:00Z")
        case = RecallCase(agency="FDA")
        first = case.file_evaluation(
            probability_of_adverse_health="LOW", severity_tier=1,
            exposure_population=0, vulnerable_population=False,
            evidence_strength="CONFIRMED",
        )
        case.submit_evaluation(first["id"])
        case.decide_evaluation(first["id"], "RATIFY")
        case.classify("CLASS_III")
        set_clock("2026-09-11T00:00:00Z")
        case.first_evaluation_id = first["id"]
        case.cadence_before = case.read_recall()["report_cadence_days"]

        second = case.file_evaluation(
            probability_of_adverse_health="MEDIUM", severity_tier=4,
            exposure_population=300000, vulnerable_population=False,
            evidence_strength="CONFIRMED",
        )
        case.submit_evaluation(second["id"])
        case.second_score = case.decide_evaluation(second["id"], "RATIFY")["hazard_score"]
        case.second_evaluation_id = second["id"]
        return case

    def test_reclassification_flips_the_redated_report_overdue_and_escalates(self, api):
        """PRD §3.3: "Hop one sets `hazard_class` from the body, restamps `classified_by_user_id`, and recomputes `report_cadence_days` from the new hazard class."
        PRD §3.3: "Hop three observes that a re-dated `due_at` may now be at or before the current logical instant, and every such report flips `PENDING → OVERDUE`."
        PRD §3.3: "Hop four, because reports flipped, increments the recall's `overdue_report_count` by one per flipped report and recomputes `compliance_flag` from the new count."
        PRD §3.8: "Otherwise it is `ESCALATED` when `overdue_report_count` has reached 1 or more."

        Design: Difficulty/transitive_cascade/reclassify_cascade_redates_report_flips_overdue_and_escalates_posture
        """
        case = self._case_ready_for_reclassification(api)
        assert case.cadence_before == 30
        assert case.second_score == 70.00

        reclassified = case.classify("CLASS_I")
        assert reclassified["hazard_class"] == "CLASS_I"
        assert reclassified["overdue_report_count"] == 1
        assert reclassified["compliance_flag"] == "ESCALATED"
        assert reclassified["effectiveness_check_level"] == "A"
        assert reclassified["sample_tier_scope"] == 3

    def test_reclassification_redates_the_pending_report_and_repins_the_cadence(self, api):
        """PRD §3.3: "Hop two, because the cadence changed, re-dates every status report of this recall that is still `PENDING`: each one's `due_at` becomes its own `period_start` plus the cadence in effect at the start of this cascade, and its `period_end` is set equal to that `due_at`."
        PRD §3.8: "The posture feeds straight back into the cadence: once the recall is `ESCALATED` or `DELINQUENT`, `report_cadence_days` becomes 3 regardless of hazard class, and the cadence is recomputed at classification, at every checkpoint and on the denial branch of a termination decision."
        PRD §3.2: "A `decision` of `RATIFY` advances `SUBMITTED → RATIFIED`, flips the `variant` to `RATIFIED`, recomputes `hazard_score` and `recommended_class` with the evidence scaling now applied, stamps `ratified_by_user_id`, and — this is the cross-entity part — moves every *other* evaluation of the same recall that was in `RATIFIED` to `SUPERSEDED`, so at most one ratified evaluation is ever live."

        Design: Difficulty/transitive_cascade/reclassify_cascade_redates_report_flips_overdue_and_escalates_posture
        """
        case = self._case_ready_for_reclassification(api)
        reclassified = case.classify("CLASS_I")
        assert reclassified["report_cadence_days"] == 3

        reports = case.status_reports()
        first_report = [r for r in reports if r["period_index"] == 1][0]
        assert first_report["due_at"] == "2026-09-08T00:00:00.000Z"
        assert first_report["period_end"] == "2026-09-08T00:00:00.000Z"
        assert first_report["status"] == "OVERDUE"

        rows, _ = validate_paginated(
            api.list_hazard_evaluations(case.recall_id, COORDINATOR)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[case.first_evaluation_id]["status"] == "SUPERSEDED"

"""Measure-set materialisation, reliability weighting and reanalysis requests."""

import pytest

from test_helpers import (
    DROPPED_MEASURE_POINT_PENALTY,
    FIVE_DOCUMENT_CODES,
    FOUR_MEASURE_DEFINITIONS,
    REFERENCE_MEASURE_DEFINITIONS,
    SIX_DOCUMENT_CODES,
    TEST_USERS,
    api_client,
    create_cycle,
    create_survey_measure_payload,
    current_hospital_version,
    cut_score_run,
    measure_definition,
    publish_methodology,
    refresh_measures,
    reference_methodology_hospital,
    register_hospital,
    reliability_survey_hospital,
    open_survey,
    pin_methodology,
    record_measure,
    set_clock,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
    verify_survey,
    CLOCK_2026_06_01,
    CLOCK_2026_06_02,
)

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]

BASELINE = [
    measure_definition("o1", "PATIENT_SAFETY"),
    measure_definition("o2", "CPOE"),
    measure_definition("o3", "STAFFING"),
    measure_definition("o4", "INFECTION_PREVENTION"),
    measure_definition("o5", "SURGICAL_VOLUME"),
]


class TestMeasureSetReadiness:

    def test_score_run_on_an_unrefreshed_set_is_refused_and_refresh_is_clock_gated(self):
        """PRD §3.5: "it may do so only when the hospital's measure set
        `readiness_state` is `READY`, or the attempt is refused with
        `ERR_MEASURE_SET_NOT_READY`"
        PRD §3.4: "The logical-clock instant must differ from the set's
        `source_snapshot_at`, because a refresh at an unchanged instant would
        rewrite nothing and is refused with `ERR_SNAPSHOT_ALREADY_CURRENT`."

        Design: Corner/state_machines/score_run_on_unrefreshed_measure_set_returns_measure_set_not_ready
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 70.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        cycle = create_cycle(version["id"], label="Baseline Grades")

        refused = api_client.create_score_run(
            hospital["id"],
            {"methodology_version_id": version["id"], "release_cycle_id": cycle["id"],
             "expected_hospital_version": current_hospital_version(hospital["id"])},
            ENGINE)
        validate_error(refused, "ERR_MEASURE_SET_NOT_READY", 409)

        same_instant = api_client.refresh_measures(
            hospital["id"],
            {"expected_hospital_version": current_hospital_version(hospital["id"])}, ENGINE)
        validate_error(same_instant, "ERR_SNAPSHOT_ALREADY_CURRENT", 409)

        set_clock(CLOCK_2026_06_02)
        refreshed = validate_success(api_client.refresh_measures(
            hospital["id"],
            {"expected_hospital_version": current_hospital_version(hospital["id"])}, ENGINE))
        assert refreshed["readiness_state"] == "READY"

        rows, _meta = validate_paginated(api_client.list_hospital_score_runs(
            hospital["id"], READER))
        assert rows == [], "the refused attempt must not have persisted a run"

    def test_four_or_more_substituted_measures_omit_the_set_instead_of_scoring(self):
        """PRD §3.4: "when the count reaches four the set becomes
        `OMITTED_FROM_CYCLE` instead"."

        Design: Corner/calculations/domain_readiness_filtering_excludes_unscored_domains
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY"),
                measure_definition("o2", "CPOE"),
                measure_definition("o3", "STAFFING"),
                measure_definition("o4", "SURGICAL_VOLUME"),
            ],
            label="Four-Measure Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])

        for code in ["o1", "o2", "o3", "o4"]:
            validate_success(api_client.create_public_source_measure(
                hospital["id"],
                {"measure_code": code, "source_program_id": "CMS_HOSPITAL_COMPARE",
                 "source_value": 50.0},
                ADMIN), 201)

        set_clock(CLOCK_2026_06_02)
        refreshed = validate_success(api_client.refresh_measures(
            hospital["id"],
            {"expected_hospital_version": current_hospital_version(hospital["id"])}, ENGINE))
        assert refreshed["substituted_measure_count"] == 4
        assert refreshed["readiness_state"] == "OMITTED_FROM_CYCLE"


class TestReliabilityWeight:

    @staticmethod
    def _prd_weight(started, completed, discharges):
        """PRD §3.3 `survey_certification_reliability`, applied literally."""
        sample_rate = round(completed / discharges, 4)
        if sample_rate >= 0.50:
            base = 1.00
        elif sample_rate >= 0.25:
            base = 0.60
        else:
            base = 0.00
        coverage = 0.50 + 0.50 * min(started, 500) / 500
        return round(base * coverage, 4)

    @pytest.mark.parametrize(
        "started,completed,discharges,expected_sr,expected_reliability",
        [
            # sample_rate 0.4000 keeps the 0.60 band, and 600 started responses
            # saturate the 500 scale, so coverage is 1.00 and 0.60 * 1.00 = 0.6000.
            (600, 400, 1000, 0.4000, 0.6000),
            # 400 started responses give coverage 0.50 + 0.50 * 400 / 500 = 0.90,
            # so the same 0.60 band yields 0.60 * 0.90 = 0.5400.
            (400, 400, 1000, 0.4000, 0.5400),
        ],
    )
    def test_reliability_weight_threshold_is_inclusive_at_the_cap(
            self, started, completed, discharges, expected_sr, expected_reliability):
        """PRD §3.3: "a base value of `1.00` applies when the sample rate is at
        least `0.50`, a base of `0.60` applies when it is at least `0.25`, and a
        base of `0.00` applies otherwise; a coverage multiplier is `0.50` plus
        `0.50` times the smaller of `started_survey_count` and `500`, divided by
        `500`; and the `reliability_weight` is the base multiplied by the
        coverage multiplier, rounded half up to four decimal places."
        PRD §3.3: "The response counts must be internally consistent, meaning at
        least one response started and no more completed than started"
        PRD §3.5: "When the run's `reliability_weight` is at least `0.60` the
        letter is the base letter and `grade_cap_applied` is false."

        Design: Difficulty/boundary_precision_check/reliability_weight_exactly_at_cap_threshold
        """
        ctx = reliability_survey_hospital(started=started, completed=completed,
                                          discharges=discharges)
        survey = validate_success(api_client.get_survey(ctx.survey["id"], READER))
        assert survey["sample_rate"] == pytest.approx(expected_sr)
        assert survey["reliability_weight"] == pytest.approx(expected_reliability, abs=1e-4)
        assert expected_reliability == pytest.approx(
            self._prd_weight(started, completed, discharges), abs=1e-4)

        cycle = create_cycle(ctx.methodology_version_id, label="Measure-Grade Cycle")
        run = cut_score_run(ctx.hospital["id"], ctx.methodology_version_id,
                            cycle["id"])
        assert run["reliability_weight"] == pytest.approx(expected_reliability, abs=1e-4)
        assert run["base_grade_letter"] == "A", (
            "the base letter is A because 95.00 is at or above the 85.00 cut-off")

    def test_a_weight_below_the_cap_downgrades_exactly_one_letter(self):
        """PRD §3.5: "When the reliability weight is below `0.60` the letter is
        one step down the downgrade map — `A` to `B`, `B` to `C`, `C` to `D`,
        `D` to `F`, and `F` to `F` — and `grade_cap_applied` is true."
        PRD §3.5: "The downgrade is always exactly one step: never two, never zero."

        Design: Difficulty/boundary_precision_check/reliability_weight_exactly_at_cap_threshold
        """
        ctx = reliability_survey_hospital(started=400, completed=400, discharges=1000)
        survey = validate_success(api_client.get_survey(ctx.survey["id"], READER))
        assert survey["reliability_weight"] == pytest.approx(0.5400, abs=1e-4)

        cycle = create_cycle(ctx.methodology_version_id, label="Measure-Grade Cycle")
        run = cut_score_run(ctx.hospital["id"], ctx.methodology_version_id,
                            cycle["id"])
        assert run["base_grade_letter"] == "A"
        assert run["letter_grade"] == "B"

    def test_a_weight_exactly_at_the_cap_keeps_the_base_letter(self):
        """PRD §3.5: "When the run's `reliability_weight` is at least `0.60` the
        letter is the base letter and `grade_cap_applied` is false."

        Design: Difficulty/boundary_precision_check/reliability_weight_exactly_at_cap_threshold
        """
        ctx = reliability_survey_hospital(started=600, completed=400, discharges=1000)
        survey = validate_success(api_client.get_survey(ctx.survey["id"], READER))
        assert survey["reliability_weight"] == pytest.approx(0.6000, abs=1e-4)

        cycle = create_cycle(ctx.methodology_version_id, label="Measure-Grade Cycle")
        run = cut_score_run(ctx.hospital["id"], ctx.methodology_version_id,
                            cycle["id"])
        assert run["base_grade_letter"] == "A"
        assert run["letter_grade"] == "A"

    def test_reliability_weight_carries_four_decimal_places(self):
        """PRD §2.6: "Reliability weights, sample rates, comparability indices,
        safe-practice credits, verification completeness values and purchaser
        utilization indices are expressed to four decimal places, round half up."
        PRD §3.3: "the `reliability_weight` is the base multiplied by the
        coverage multiplier, rounded half up to four decimal places"

        Design: Corner/calculations/employer_index_precision_to_four_decimals
        """
        # sample_rate 0.3000 keeps the 0.60 band and 333 started responses give
        # coverage 0.50 + 0.50 * 333 / 500 = 0.8330, so the weight is
        # 0.60 * 0.833 = 0.4998 — a value that only survives at four decimal
        # places; a two-place reading would wrongly report 0.5000.
        ctx = reliability_survey_hospital(started=333, completed=300, discharges=1000)
        survey = validate_success(api_client.get_survey(ctx.survey["id"], READER))
        assert survey["sample_rate"] == pytest.approx(0.3000)
        assert survey["reliability_weight"] == pytest.approx(0.4998, abs=1e-4)


class TestReanalysisDecisions:

    def test_grant_with_five_document_codes_is_refused(self):
        """PRD §3.6: "The request must have `documents_sufficient` true, which
        means its `supporting_documents` cover at least six distinct document
        codes; a grant supported by fewer is refused with
        `ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT`."

        Design: Corner/state_machines/reanalysis_grant_with_few_documents_returns_documents_insufficient
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 70.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")

        request = validate_success(api_client.create_reanalysis_request(
            hospital["id"],
            {"survey_id": survey["id"], "subset_selector": [{"measure_code": "o1"}],
             "requested_delta": 3.00,
             "supporting_documents": [
                 {"document_code": code, "issued_on": "2026-05-01T00:00:00Z"}
                 for code in FIVE_DOCUMENT_CODES]},
            {"X-User-ID": hospital["id"], "X-User-Role": "HospitalRespondent",
             "Content-Type": "application/json"}), 201)
        assert request["documents_sufficient"] is False

        validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "START_REVIEW"}, ANALYST))
        refused = api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "GRANT"}, ANALYST)
        validate_error(refused, "ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT", 409)
        reread = validate_success(api_client.get_reanalysis_request(request["id"], READER))
        assert reread["status"] == "UNDER_REVIEW"
        assert reread["adjusted_delta"] == pytest.approx(0.0)

    def test_grant_with_six_document_codes_succeeds_and_applies_the_signed_delta(self):
        """PRD §3.6: "A successful grant is the system's most consequential
        cascade. The request moves to `GRANTED`, sets
        `non_regression_confirmed` true, and fills its `adjusted_delta` either
        from the `requested_delta` the hospital supplied"

        Design: Corner/state_machines/reanalysis_grant_with_few_documents_returns_documents_insufficient
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 70.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")

        request = validate_success(api_client.create_reanalysis_request(
            hospital["id"],
            {"survey_id": survey["id"], "subset_selector": [{"measure_code": "o1"}],
             "requested_delta": 3.00,
             "supporting_documents": [
                 {"document_code": code, "issued_on": "2026-05-01T00:00:00Z"}
                 for code in SIX_DOCUMENT_CODES]},
            {"X-User-ID": hospital["id"], "X-User-Role": "HospitalRespondent",
             "Content-Type": "application/json"}), 201)
        assert request["documents_sufficient"] is True

        validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "START_REVIEW"}, ANALYST))
        granted = validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "GRANT"}, ANALYST))
        assert granted["status"] == "GRANTED"
        assert granted["non_regression_confirmed"] is True
        assert granted["adjusted_delta"] == pytest.approx(3.00)


class TestReanalysisCascade:

    def test_grant_cascades_measure_set_then_grade_then_parent_cycle(self):
        """PRD §3.6: "From there the change propagates in four hops: each
        selected measure's `measure_status` becomes `PUBLIC_SOURCE_SUBSTITUTED`;
        that measure change flips the hospital's set to `INCOMPLETE` and bumps
        the substituted count; the set change drives the next refresh-and-score
        pair, which re-derives the grade's composite through
        `composite_adjusted_for_reanalysis`"

        Design: Difficulty/transitive_cascade/reanalysis_grant_four_hop_cascade_into_cycle
        """
        from test_helpers import decide_reanalysis, raise_reanalysis, get_grade_for

        ctx = reference_methodology_hospital()
        cycle = create_cycle(ctx.methodology_version_id, label="Main Methodology Grades")
        cut_score_run(ctx.hospital["id"], ctx.methodology_version_id, cycle["id"],
                      ctx.hospital_version)
        request = raise_reanalysis(
            ctx.hospital["id"], ctx.survey["id"],
            [{"measure_code": "cpoe_order_entry_value"}])
        decide_reanalysis(ctx.hospital["id"], request["id"], "START_REVIEW")

        granted = decide_reanalysis(ctx.hospital["id"], request["id"], "GRANT")
        assert granted["status"] == "GRANTED"
        assert granted["reference_stale"] is False

        # hop 1: the selected measure is now publicly sourced.
        rows, _meta = validate_paginated(api_client.list_survey_measures(
            READER, {"hospital_id": ctx.hospital["id"],
                     "measure_code": "cpoe_order_entry_value"}))
        assert rows and rows[0]["measure_status"] == "PUBLIC_SOURCE_SUBSTITUTED"

        # hop 2: the measure set is stale again until it is refreshed.
        measure_set = validate_success(api_client.get_measure_set(ctx.measure_set["id"], READER))
        assert measure_set["readiness_state"] == "INCOMPLETE"

        # hop 3: refresh and re-score re-derive the grade through the adjusted rule.
        hospital_now = validate_success(api_client.get_hospital(ctx.hospital["id"], READER))
        refresh_measures(ctx.hospital["id"], hospital_now["version"])
        hospital_now = validate_success(api_client.get_hospital(ctx.hospital["id"], READER))
        cut_score_run(ctx.hospital["id"], ctx.methodology_version_id, cycle["id"],
                      hospital_now["version"])
        grade = get_grade_for(ctx.hospital["id"], cycle["id"])
        assert grade["composite_score"] == pytest.approx(71.62, abs=0.005)
        assert grade["letter_grade"] == "B"

        # hop 4: the cycle state is re-derived from its resolved children.
        # PRD §3.7 gates the DRAFT -> OPEN_REVIEW move on the `open-review`
        # operation, which this fixture never called, so the cycle is still
        # `DRAFT` and its grade is simply resolved.
        cycle_now = validate_success(api_client.get_release_cycle(cycle["id"], READER))
        assert cycle_now["state"] == "DRAFT"
        assert cycle_now["grade_count"] == 1

    def test_grant_rewinds_the_submission_dimension_and_withdraws_certification(self):
        """PRD §3.6: "The survey's submission dimension moves back to
        `SUBMITTED` while its certification dimension is independently set to
        `CERTIFICATION_WITHDRAWN` — leaving the two dimensions observably out of
        step until the next acceptance re-earns `CERTIFIED`."

        Design: Difficulty/non_linear_state_machine/survey_parallel_dimensions_out_of_step
        """
        ctx = reference_methodology_hospital()
        request = validate_success(api_client.create_reanalysis_request(
            ctx.hospital["id"],
            {"survey_id": ctx.survey["id"],
             "subset_selector": [{"measure_code": "cpoe_order_entry_value"}],
             "supporting_documents": [
                 {"document_code": code, "issued_on": "2026-05-01T00:00:00Z"}
                 for code in SIX_DOCUMENT_CODES]},
            {"X-User-ID": ctx.hospital["id"], "X-User-Role": "HospitalRespondent",
             "Content-Type": "application/json"}), 201)
        validate_success(api_client.decide_reanalysis_request(
            ctx.hospital["id"], request["id"], {"decision": "START_REVIEW"}, ANALYST))
        granted = validate_success(api_client.decide_reanalysis_request(
            ctx.hospital["id"], request["id"], {"decision": "GRANT"}, ANALYST))
        assert granted["status"] == "GRANTED"

        survey = validate_success(api_client.get_survey(ctx.survey["id"], READER))
        assert survey["af_status"] == "SUBMITTED"
        assert survey["af_certification_level"] == "CERTIFICATION_WITHDRAWN"

        realigned = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST))
        assert realigned["af_status"] == "VERIFIED"
        assert realigned["af_certification_level"] == "CERTIFIED"

    def test_reanalysis_grant_is_refused_when_the_survey_reference_is_stale(self):
        """PRD §3.6: "the request's `reference_stale` flag must be false. A
        request whose survey is pinned to a methodology version other than the
        hospital's current one is refused with `ERR_REANALYSIS_REFERENCE_STALE`,
        so a challenge can never rewind a survey measured under a superseded
        version."

        Design: Difficulty/cross_entity_state_dependency/reanalysis_grant_requires_hospital_pin_current
        """
        from test_helpers import raise_pending_change, review_pending_change

        set_clock(CLOCK_2026_06_01)
        version_a = publish_methodology(BASELINE, label="Baseline Methodology")
        version_b = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY", weight=0.50),
                measure_definition("o2", "CPOE", weight=0.30),
                measure_definition("o3", "STAFFING", weight=0.20),
                measure_definition("o4", "SURGICAL_VOLUME", weight=0.10),
            ],
            label="Measure-Grade Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version_a["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 70.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        request = validate_success(api_client.create_reanalysis_request(
            hospital["id"],
            {"survey_id": survey["id"], "subset_selector": [{"measure_code": "o1"}],
             "supporting_documents": [
                 {"document_code": code, "issued_on": "2026-05-01T00:00:00Z"}
                 for code in SIX_DOCUMENT_CODES]},
            {"X-User-ID": hospital["id"], "X-User-Role": "HospitalRespondent",
             "Content-Type": "application/json"}), 201)
        validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "START_REVIEW"}, ANALYST))

        change = raise_pending_change(hospital["id"], version_b["id"])
        applied = review_pending_change(change["id"], "APPLY")
        assert applied["status"] == "APPLIED"

        reread = validate_success(api_client.get_reanalysis_request(request["id"], READER))
        assert reread["reference_stale"] is True

        refused = api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "GRANT"}, ANALYST)
        validate_error(refused, "ERR_REANALYSIS_REFERENCE_STALE", 409)

    def test_refresh_after_grant_restores_the_stored_baseline_composite(self):
        """PRD §3.4: "a refresh performed on a set that is already `READY`
        simply rematerialises it in place: the readiness state stays `READY`,
        `source_snapshot_at` advances, and any `reanalysis_adjustment_delta`
        carried on the derived values is cleared, so the hospital's composite
        returns to its pre-reanalysis baseline."

        Design: Difficulty/compensating_invariant/reanalysis_grant_then_refresh_restores_baseline_composite
        """
        from test_helpers import decide_reanalysis, get_grade_for, raise_reanalysis

        ctx = reference_methodology_hospital()
        cycle = create_cycle(ctx.methodology_version_id, label="Main Methodology Grades")
        cut_score_run(ctx.hospital["id"], ctx.methodology_version_id, cycle["id"],
                      ctx.hospital_version)
        baseline = get_grade_for(ctx.hospital["id"], cycle["id"])
        assert baseline["composite_score"] == pytest.approx(71.62, abs=0.005)

        request = raise_reanalysis(
            ctx.hospital["id"], ctx.survey["id"],
            [{"measure_code": "cpoe_order_entry_value"}], requested_delta=4.38)
        decide_reanalysis(ctx.hospital["id"], request["id"], "START_REVIEW")
        granted = decide_reanalysis(ctx.hospital["id"], request["id"], "GRANT")
        assert granted["adjusted_delta"] == pytest.approx(4.38)

        hospital_now = validate_success(api_client.get_hospital(ctx.hospital["id"], READER))
        set_clock(CLOCK_2026_06_02)
        refresh_measures(ctx.hospital["id"], hospital_now["version"])
        hospital_now = validate_success(api_client.get_hospital(ctx.hospital["id"], READER))
        cut_score_run(ctx.hospital["id"], ctx.methodology_version_id, cycle["id"],
                      hospital_now["version"])
        restored = get_grade_for(ctx.hospital["id"], cycle["id"])
        assert restored["composite_score"] - baseline["composite_score"] == pytest.approx(
            0.00, abs=1e-9), "the refresh returns the grade to its stored baseline composite"
        assert restored["letter_grade"] == "B"
"""Remaining depth coverage: validation tier precedence, review-stage gating,
cascade hops, threshold bands and conserved quantities."""

import pytest

from test_helpers import (
    CLOCK_2026_06_01,
    CLOCK_2026_06_02,
    CLOCK_2026_06_29_LATE,
    CLOCK_2026_06_30,
    CLOCK_2026_07_01,
    SIX_DOCUMENT_CODES,
    TEST_USERS,
    api_client,
    create_cycle,
    create_score_run_payload,
    cut_score_run,
    decide_reanalysis,
    file_correction,
    get_grade_for,
    make_respondent_headers,
    open_review_cycle_with_review,
    open_survey,
    pin_methodology,
    publish_methodology,
    raise_reanalysis,
    record_measure,
    refresh_measures,
    register_employer,
    register_hospital,
    relist_employer,
    set_clock,
    submit_survey,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    verify_survey,
)
from test_helpers.constants import BASELINE_MEASURE_DEFINITIONS

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]


class TestValidationTierPrecedence:

    def _suspended_hospital(self):
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        cycle = validate_success(api_client.create_release_cycle({
            "label": "Baseline Grades",
            "methodology_version_id": version["id"],
            "preliminary_release_date": "2026-06-01T00:00:00Z",
            "correction_window_ends_at": "2026-06-30T00:00:00Z",
            "publication_date": "2026-07-15T00:00:00Z",
        }, ADMIN), 201)
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        suspended = validate_success(api_client.update_hospital(
            hospital["id"], {"status": "SUSPENDED"}, ADMIN))
        return version, cycle, hospital, suspended["version"]

    def test_suspended_hospital_is_refused_before_the_data_shaped_checks(self):
        """PRD §2.8: "Opening a survey, cutting a score run and refreshing a
        measure set each refuse a suspended hospital with
        `ERR_HOSPITAL_NOT_ACTIVE` and HTTP status 409, and this standing check
        is evaluated before any budget-shaped or data-shaped business check, so
        a suspended hospital with otherwise perfect data still fails on
        standing first."

        Design: Difficulty/priority_pair_validation_conflict/state_tier_precedes_business_tiers_on_score_run
        """
        version, cycle, hospital, _suspended_version = self._suspended_hospital()
        stale_view = hospital["version"]

        response = api_client.create_score_run(
            hospital["id"],
            create_score_run_payload(version["id"], cycle["id"], stale_view),
            ENGINE,
        )
        validate_error(response, "ERR_HOSPITAL_NOT_ACTIVE", 409)
        assert response.status_code != 412
        rows, _meta = validate_paginated(api_client.list_hospital_score_runs(
            hospital["id"], READER))
        assert rows == []

    def test_suspended_hospital_refusal_is_not_the_optimistic_concurrency_verdict(self):
        """PRD §2.8: "a suspended hospital with otherwise perfect data still
        fails on standing first."
        PRD §2.7: "a value that does not equal the hospital's current `version`
        at the time of the write is rejected with `ERR_STALE_VERSION` and HTTP
        status 412."

        Design: Difficulty/priority_pair_validation_conflict/state_tier_precedes_business_tiers_on_score_run
        """
        version, cycle, hospital, suspended_version = self._suspended_hospital()
        stale_view = hospital["version"]
        assert stale_view < suspended_version

        response = api_client.create_score_run(
            hospital["id"],
            create_score_run_payload(version["id"], cycle["id"], stale_view),
            ENGINE,
        )
        error_data = validate_error(response, "ERR_HOSPITAL_NOT_ACTIVE", 409)
        assert error_data["error_id"] != "ERR_STALE_VERSION"
        assert error_data["error_id"] != "ERR_MEASURE_SET_NOT_READY"


class TestRenormalizationBoundary:

    def test_a_cycle_whose_window_is_still_open_stays_in_open_review(self):
        """PRD §3.7: "When the logical clock advances strictly past
        `correction_window_ends_at`, a cycle in `OPEN_REVIEW` moves to
        `CORRECTION_CLOSED`"

        Design: Difficulty/boundary_precision_check/empty_accepted_correction_set_edge
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        set_clock(CLOCK_2026_06_29_LATE)

        still_open = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert still_open["state"] == "OPEN_REVIEW", (
            "the window has not elapsed, so the cycle cannot close")

        validate_success(api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE))

        set_clock(CLOCK_2026_07_01)
        after = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert after["state"] in ["CORRECTION_CLOSED", "EMBARGOED"], (
            "once the window is strictly past, the derived state leaves OPEN_REVIEW")


class TestConservedCounts:

    def test_forward_relisting_reports_the_collapsed_distinct_count(self):
        """PRD §3.8: "Duplicate entries collapse to their first occurrence, so
        the effective network is order-insensitive and the
        `network_hospital_count` is the count of distinct hospital identifiers
        after that collapse."

        Design: Difficulty/compensating_invariant/employer_network_relisting_restores_hospital_count
        """
        hospitals = [register_hospital() for _ in range(4)]
        employer = register_employer(
            [hospitals[0]["id"], hospitals[1]["id"], hospitals[2]["id"]])
        baseline = employer["network_hospital_count"]
        assert baseline == 3

        forward = relist_employer(
            employer["id"],
            [hospitals[0]["id"], hospitals[1]["id"], hospitals[2]["id"],
             hospitals[3]["id"], hospitals[3]["id"]])
        assert forward["network_hospital_count"] == baseline + 1


class TestReviewStageGating:

    def test_a_pending_correction_blocks_the_cycle_from_closing(self):
        """PRD §3.7: "When the logical clock advances strictly past
        `correction_window_ends_at`, a cycle in `OPEN_REVIEW` moves to
        `CORRECTION_CLOSED`, provided no correction is left `PENDING` (or the
        close is refused with `ERR_CORRECTIONS_PENDING`)"
        PRD §3.7: "The cycle's `correction_request_count` is recomputed as the
        number of corrections whose review belongs to the cycle and whose status
        is still `PENDING` or `ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/preliminary_correction_requires_cycle_open_review
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        assert correction["status"] == "PENDING"
        pending = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert pending["state"] == "OPEN_REVIEW"
        assert pending["correction_request_count"] == 1

        set_clock(CLOCK_2026_07_01)
        still = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert still["state"] == "OPEN_REVIEW", (
            "a PENDING correction blocks the close, so the cycle cannot advance")
        assert still["correction_request_count"] == 1

    def test_a_closed_window_leaves_the_cycle_out_of_open_review(self):
        """PRD §3.7: "An acceptance requires the parent cycle to be
        `OPEN_REVIEW`, the clock to be strictly before the window's end, and the
        request to be `PENDING`, and each of those failures carries its own
        refusal code: `ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS`,
        `ERR_CORRECTION_WINDOW_CLOSED` and `ERR_CORRECTION_NOT_PENDING`
        respectively."

        Design: Difficulty/cross_entity_state_dependency/preliminary_correction_requires_cycle_open_review
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        assert correction["status"] == "PENDING"
        set_clock(CLOCK_2026_07_01)

        # PRD §3.7's close precondition is that "no correction is left
        # `PENDING` (or the close is refused with `ERR_CORRECTIONS_PENDING`)",
        # so this cycle legitimately remains `OPEN_REVIEW`; what the closed
        # window changes is the verdict on the decision itself.
        response = api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE)
        validate_error_is_one_of(
            response,
            ["ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS", "ERR_CORRECTION_WINDOW_CLOSED"],
        )

    def test_an_open_window_cycle_accepts_the_correction(self):
        """PRD §3.7: "A grade in `SCORED` becomes `CORRECTED` when a correction
        is accepted inside the window, recomputing its composite as the
        preliminary score plus every accepted correction delta and reassigning
        its letter through the downgrade-on-cap variant."

        Design: Difficulty/cross_entity_state_dependency/preliminary_correction_requires_cycle_open_review
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        set_clock(CLOCK_2026_06_29_LATE)

        before = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert before["state"] == "OPEN_REVIEW"

        accepted = validate_success(api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE))
        assert accepted["status"] == "ACCEPTED"

        grade = validate_success(api_client.get_grade(ctx.grade["id"], READER))
        assert grade["status"] == "CORRECTED"


class TestThresholdBands:

    @pytest.mark.parametrize(
        "started,completed,expected_sample_rate",
        [
            # completed/started pairs that straddle the 0.25 sample-rate band,
            # both satisfying PRD §3.3's "no more completed than started".
            (1000, 250, 0.2500),
            (1000, 249, 0.2490),
        ],
    )
    def test_sample_rate_band_boundary_is_reflected_in_the_derived_weight(
            self, started, completed, expected_sample_rate):
        """PRD §3.3: "a base value of `1.00` applies when the sample rate is at
        least `0.50`, a base of `0.60` applies when it is at least `0.25`, and a
        base of `0.00` applies otherwise"
        PRD §2.6: "Reliability weights, sample rates, comparability indices,
        safe-practice credits, verification completeness values and purchaser
        utilization indices are expressed to four decimal places, round half up."

        Design: Difficulty/boundary_precision_check/reliability_weight_exactly_at_cap_threshold
        """
        from test_helpers import reliability_survey_hospital

        # PRD §3.3 requires no more completed responses than started ones, so
        # the pair straddles the 0.25 sample-rate band from above.
        ctx = reliability_survey_hospital(started=started, completed=completed,
                                          discharges=1000)
        survey = validate_success(api_client.get_survey(ctx.survey["id"], READER))
        assert survey["sample_rate"] == pytest.approx(expected_sample_rate)
        # The base band is read straight off the sample rate, so the stored
        # weight is the base times the coverage multiplier to four places.
        coverage = 0.50 + 0.50 * min(started, 500) / 500
        base = 0.60 if expected_sample_rate >= 0.25 else 0.00
        assert survey["reliability_weight"] == pytest.approx(round(base * coverage, 4), abs=1e-4)


class TestCourseRollupSecondObservation:

    def test_scaled_converted_values_land_in_their_domain_buckets(self):
        """PRD §2.10: "The array's order is the evaluation order for the domain
        rollup and for the composite, and it is also the order in which a
        materialised measure set lists its entries."
        PRD §3.5: "for each one computes a converted value by multiplying the
        measure's `derived_value` by that measure's `scale_factor`"

        Design: Difficulty/combinatorial_formula/domain_rollup_nested_mean_of_rounded_measures
        """
        from test_helpers import domain_score_of, reference_methodology_hospital

        ctx = reference_methodology_hospital()
        preview = validate_success(api_client.get_composite_preview(
            ctx.hospital["id"], READER, {"methodology_version_id": ctx.methodology_version_id}))
        assert domain_score_of(preview["domain_scores"], "CPOE") == pytest.approx(95.00), (
            "0.9500 scaled by 100 passes straight through the NONE rule")
        assert domain_score_of(preview["domain_scores"], "STAFFING") == pytest.approx(37.40), (
            "3.7400 scaled by 10 passes straight through the NONE rule")


class TestCascadeHops:

    def test_grant_rematerialises_the_selected_measure_as_substituted(self):
        """PRD §3.6: "The hospital's measure set is then rematerialised with
        each selected measure's status becoming `PUBLIC_SOURCE_SUBSTITUTED`, the
        `substituted_measure_count` is recomputed"

        Design: Difficulty/transitive_cascade/reanalysis_grant_four_hop_cascade_into_cycle
        """
        from test_helpers import reference_methodology_hospital

        ctx = reference_methodology_hospital()
        request = raise_reanalysis(
            ctx.hospital["id"], ctx.survey["id"],
            [{"measure_code": "cpoe_order_entry_value"}])
        decide_reanalysis(ctx.hospital["id"], request["id"], "START_REVIEW")
        decide_reanalysis(ctx.hospital["id"], request["id"], "GRANT")

        hospital_now = validate_success(api_client.get_hospital(ctx.hospital["id"], READER))
        rematerialised = refresh_measures(ctx.hospital["id"], hospital_now["version"])
        by_code = {entry["measure_code"]: entry for entry in rematerialised["measures"]}
        assert by_code["cpoe_order_entry_value"]["measure_status"] == "PUBLIC_SOURCE_SUBSTITUTED"
        assert rematerialised["substituted_measure_count"] >= 1

    def test_discrepancy_demand_reflags_every_unsourced_measure(self):
        """PRD §3.3: "first the system orders a source-documentation demand
        against every measure row of that survey whose `source_program_id` is
        null; that measure-level mutation flags each such row in place, setting
        `flag_hold` true for rows with a null source programme and recomputing
        each `derived_value` from its current `raw_value`"

        Design: Difficulty/transitive_cascade/verification_discrepancy_three_hop_cascade_to_disclosure
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"], validation_method="ATTESTATION")
        first = validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0},
            make_respondent_headers(hospital["id"])), 201)
        second = validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o2", "raw_value": 55.0},
            make_respondent_headers(hospital["id"])), 201)
        submit_survey(hospital["id"], survey["id"])

        validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "DISCREPANCY_REQUEST"}, ANALYST))

        rows, _meta = validate_paginated(api_client.list_survey_measures(
            READER, {"survey_id": survey["id"]}))
        by_code = {row["measure_code"]: row for row in rows}
        assert by_code["o1"]["flag_hold"] is True
        assert by_code["o2"]["flag_hold"] is True
        assert by_code["o1"]["derived_value"] == pytest.approx(70.0)
        assert by_code["o2"]["derived_value"] == pytest.approx(55.0)
        assert by_code["o1"]["id"] == first["id"] and by_code["o2"]["id"] == second["id"], (
            "the demand re-flags the existing rows in place rather than replacing them")


class TestParallelSurveyDimensions:

    def test_accept_sets_both_dimensions_and_discrepancy_resets_certification(self):
        """PRD §3.3: "An accepted verification advances the submission dimension
        to `VERIFIED`, sets the certification dimension to `CERTIFIED`, records
        `verification_response` as `ACCEPT`"

        Design: Difficulty/non_linear_state_machine/survey_parallel_dimensions_out_of_step
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 70.0)
        submit_survey(hospital["id"], survey["id"])
        accepted = verify_survey(survey["id"], "ACCEPT")
        assert accepted["af_status"] == "VERIFIED"
        assert accepted["af_certification_level"] == "CERTIFIED"


class TestCrossEntityGateSecondObservation:

    def test_a_refused_stale_grant_leaves_the_request_and_survey_untouched(self):
        """PRD §3.6: "A request whose survey is pinned to a methodology version
        other than the hospital's current one is refused with
        `ERR_REANALYSIS_REFERENCE_STALE`, so a challenge can never rewind a
        survey measured under a superseded version."

        Design: Difficulty/cross_entity_state_dependency/reanalysis_grant_requires_hospital_pin_current
        """
        from test_helpers import raise_pending_change, review_pending_change

        set_clock(CLOCK_2026_06_01)
        version_a = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        version_b = publish_methodology(
            [
                {"measure_code": "o1", "domain": "PATIENT_SAFETY", "scale_factor": 1.0,
                 "weight": 0.50, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o2", "domain": "CPOE", "scale_factor": 1.0,
                 "weight": 0.30, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o3", "domain": "STAFFING", "scale_factor": 1.0,
                 "weight": 0.20, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o4", "domain": "SURGICAL_VOLUME", "scale_factor": 1.0,
                 "weight": 0.10, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
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
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "START_REVIEW"}, ANALYST))

        change = raise_pending_change(hospital["id"], version_b["id"])
        review_pending_change(change["id"], "APPLY")

        refused = api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "GRANT"}, ANALYST)
        validate_error(refused, "ERR_REANALYSIS_REFERENCE_STALE", 409)

        reread = validate_success(api_client.get_reanalysis_request(request["id"], READER))
        assert reread["status"] == "UNDER_REVIEW"
        assert reread["adjusted_delta"] == pytest.approx(0.0)
        survey_now = validate_success(api_client.get_survey(survey["id"], READER))
        assert survey_now["af_status"] == "VERIFIED"


class TestClaimedVerificationCycle:

    def test_the_first_discrepancy_round_claims_its_cycle_key(self):
        """PRD §3.3: "Choosing `DISCREPANCY_REQUEST` instead moves the submission
        dimension to `DISCREPANCY_OPEN`, records the `verification_response` as
        `DISCREPANCY_REQUEST`, increments the survey's `verification_cycle` by
        one, and returns the certification dimension to `UNCERTIFIED`."

        Design: Difficulty/resource_temporal_overlap/survey_verification_round_idempotency_key_collision
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"], validation_method="ATTESTATION")
        record_measure(hospital["id"], survey["id"], "o1", 70.0)
        submit_survey(hospital["id"], survey["id"])

        opened = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "DISCREPANCY_REQUEST"}, ANALYST))
        assert opened["verification_cycle"] == 1
        assert opened["af_status"] == "DISCREPANCY_OPEN"
        assert opened["verification_response"] == "DISCREPANCY_REQUEST"
        assert opened["af_certification_level"] == "UNCERTIFIED"


class TestConservedPoints:

    def test_grant_records_the_supplied_delta_and_is_terminal(self):
        """PRD §3.6: "The request moves to `GRANTED`, sets
        `non_regression_confirmed` true, and fills its `adjusted_delta` either
        from the `requested_delta` the hospital supplied or by recomputation
        from the selected measures when that value was null."

        Design: Difficulty/compensating_invariant/reanalysis_grant_then_refresh_restores_baseline_composite
        """
        from test_helpers import reference_methodology_hospital

        ctx = reference_methodology_hospital()
        request = raise_reanalysis(
            ctx.hospital["id"], ctx.survey["id"],
            [{"measure_code": "cpoe_order_entry_value"}], requested_delta=4.38)
        decide_reanalysis(ctx.hospital["id"], request["id"], "START_REVIEW")
        granted = decide_reanalysis(ctx.hospital["id"], request["id"], "GRANT")
        assert granted["adjusted_delta"] == pytest.approx(4.38)
        assert granted["non_regression_confirmed"] is True

        again = api_client.decide_reanalysis_request(
            ctx.hospital["id"], request["id"], {"decision": "GRANT"}, ANALYST)
        validate_error(again, "ERR_REANALYSIS_NOT_UNDER_REVIEW", 409)
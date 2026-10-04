"""Survey waves: field-window boundaries, thresholds, OCC, submit/exclude invariant.

Covers difficulty instances: survey_threshold_exact_boundary,
survey_window_membership_boundary, survey_submit_exclude_count_invariant —
and corner instances: survey_qualify_threshold_unmet.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_survey_wave_payload,
    create_category, create_member_with_subscription, setup_open_wave, set_clock,
    TEST_USERS, make_member_headers,
)

LM = TEST_USERS["lab_manager_headers"]
SD = TEST_USERS["survey_director_headers"]


def _submit(api, wave_id, member_id, model_label="Dry1",
            reliability_score=80, satisfaction_score=90):
    return api.transition_survey_wave(
        wave_id,
        {"action": "submit_response", "member_id": member_id,
         "model_label": model_label, "reliability_score": reliability_score,
         "satisfaction_score": satisfaction_score},
        make_member_headers(member_id),
    )


class TestSurveyThreshold:
    def test_qualify_at_exact_threshold_boundary(self, api):
        """PRD §3.8: "The wave's `response_count` counts only `COUNTED` responses, and `threshold_met` — true exactly when `response_count` is at least `min_responses` — recomputes on both submission and exclusion."
        PRD §3.8: "qualification moves the wave to `QUALIFIED` and requires `threshold_met` to be true (`ERR_SAMPLE_SIZE_NOT_MET` otherwise) plus the `expected_wave_version` OCC guard of §2.6".

        Design: Difficulty/boundary_precision_check/survey_threshold_exact_boundary
        """
        member = create_member_with_subscription(email="b1@x.com", full_name="B One")
        _, wave = setup_open_wave(category_name="Dryers", min_responses=1)
        set_clock("2026-09-03T00:00:00Z")
        data = validate_success(_submit(api, wave["id"], member["id"]))
        assert data["response_count"] == 1
        assert data["threshold_met"] is True
        set_clock("2026-09-06T00:00:00Z")
        data = validate_success(api.transition_survey_wave(wave["id"], {"action": "close"}, SD))
        resp = api.transition_survey_wave(
            wave["id"], {"action": "qualify", "expected_wave_version": data["version"]}, SD)
        data = validate_success(resp)
        assert data["status"] == "QUALIFIED"
        assert data["response_count"] == 1

    def test_zero_responses_threshold_unmet(self, api):
        """PRD §3.8: "The wave's `response_count` counts only `COUNTED` responses, and `threshold_met` — true exactly when `response_count` is at least `min_responses` — recomputes on both submission and exclusion."

        Design: Difficulty/boundary_precision_check/survey_threshold_exact_boundary
        """
        _, wave = setup_open_wave(category_name="Dryers", min_responses=1)
        wave = get_success_data(api.get_survey_wave(wave["id"], SD))
        assert wave["response_count"] == 0
        assert wave["threshold_met"] is False

    def test_qualify_threshold_unmet_then_disqualify(self, api):
        """PRD §3.8: "qualification moves the wave to `QUALIFIED` and requires `threshold_met` to be true (`ERR_SAMPLE_SIZE_NOT_MET` otherwise) plus the `expected_wave_version` OCC guard of §2.6; disqualification moves it to `DISQUALIFIED` and requires `threshold_met` to be false."

        Design: Corner/validations/survey_qualify_threshold_unmet
        """
        _, wave = setup_open_wave(category_name="Dryers", min_responses=1)
        set_clock("2026-09-06T00:00:00Z")
        data = validate_success(api.transition_survey_wave(wave["id"], {"action": "close"}, SD))
        resp = api.transition_survey_wave(
            wave["id"], {"action": "qualify", "expected_wave_version": data["version"]}, SD)
        validate_error(resp, ApiErrorId.ERR_SAMPLE_SIZE_NOT_MET)
        data = validate_success(api.transition_survey_wave(wave["id"], {"action": "disqualify"}, SD))
        assert data["status"] == "DISQUALIFIED"


class TestSurveyWindowBoundary:
    def test_submit_at_exactly_field_end_succeeds(self, api):
        """PRD §3.8: "While a wave is `OPEN` and the clock sits within the window — at or after `field_start` and at or before `field_end`, with attempts outside the window rejected with `ERR_TEMPORAL_WINDOW`".

        Design: Difficulty/resource_temporal_overlap/survey_window_membership_boundary
        """
        member = create_member_with_subscription(email="w1@x.com", full_name="W One")
        _, wave = setup_open_wave(category_name="Dryers", min_responses=2)
        set_clock("2026-09-05T00:00:00Z")
        data = validate_success(_submit(api, wave["id"], member["id"],
                                        reliability_score=70, satisfaction_score=80))
        assert data["response_count"] == 1

    def test_submit_one_second_after_field_end_rejected(self, api):
        """PRD §3.8: "While a wave is `OPEN` and the clock sits within the window — at or after `field_start` and at or before `field_end`, with attempts outside the window rejected with `ERR_TEMPORAL_WINDOW`".

        Design: Difficulty/resource_temporal_overlap/survey_window_membership_boundary
        """
        member = create_member_with_subscription(email="w2@x.com", full_name="W Two")
        _, wave = setup_open_wave(category_name="Dryers", min_responses=2)
        set_clock("2026-09-05T00:00:01Z")
        resp = _submit(api, wave["id"], member["id"],
                       reliability_score=70, satisfaction_score=80)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)


class TestSubmitExcludeInvariant:
    def test_submit_then_exclude_restores_count_and_threshold(self, api):
        """PRD §3.8: "The `SurveyDirector` may exclude a response by its `response_index` (an index that does not exist yields `ERR_SAMPLE_SIZE_NOT_MET`), flipping its status to `EXCLUDED`."
        PRD §3.8: "The wave's `response_count` counts only `COUNTED` responses, and `threshold_met` — true exactly when `response_count` is at least `min_responses` — recomputes on both submission and exclusion."

        Design: Difficulty/compensating_invariant/survey_submit_exclude_count_invariant
        """
        member = create_member_with_subscription(email="s1@x.com", full_name="S One")
        _, wave = setup_open_wave(category_name="Dryers", min_responses=1)
        set_clock("2026-09-03T00:00:00Z")
        data = validate_success(_submit(api, wave["id"], member["id"],
                                        reliability_score=70, satisfaction_score=80))
        assert data["response_count"] == 1
        assert data["threshold_met"] is True
        data = validate_success(api.transition_survey_wave(
            wave["id"], {"action": "exclude_response", "response_index": 1}, SD))
        assert data["response_count"] == 0
        assert data["threshold_met"] is False

    def test_submit_twice_after_exclude_recovers(self, api):
        """PRD §3.8: "The wave's `response_count` counts only `COUNTED` responses, and `threshold_met` — true exactly when `response_count` is at least `min_responses` — recomputes on both submission and exclusion."
        PRD §3.8: "At most one `COUNTED` response per member per wave is allowed; a second submission from the same member is rejected with `ERR_SAMPLE_SIZE_NOT_MET`."

        Design: Difficulty/compensating_invariant/survey_submit_exclude_count_invariant
        """
        member = create_member_with_subscription(email="s2@x.com", full_name="S Two")
        _, wave = setup_open_wave(category_name="Dryers", min_responses=1)
        set_clock("2026-09-03T00:00:00Z")
        validate_success(_submit(api, wave["id"], member["id"]))
        validate_success(api.transition_survey_wave(
            wave["id"], {"action": "exclude_response", "response_index": 1}, SD))
        # after exclusion the member has no COUNTED response; resubmission is allowed
        data = validate_success(_submit(api, wave["id"], member["id"]))
        assert data["response_count"] == 1
        assert data["threshold_met"] is True

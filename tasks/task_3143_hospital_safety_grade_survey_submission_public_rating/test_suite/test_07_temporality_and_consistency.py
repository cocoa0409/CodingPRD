"""Logical clock, optimistic concurrency, immediate consistency and cascade order."""

import pytest

from test_helpers import (
    CLOCK_2026_06_01,
    CLOCK_2026_06_02,
    TEST_USERS,
    api_client,
    create_methodology_version_payload,
    create_survey_payload,
    make_respondent_headers,
    measure_definition,
    publish_methodology,
    register_hospital,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]

BASELINE = [
    measure_definition("o1", "PATIENT_SAFETY"),
    measure_definition("o2", "CPOE"),
    measure_definition("o3", "STAFFING"),
]


class TestOptimisticConcurrency:

    def test_refresh_carrying_a_superseded_version_is_rejected(self):
        """PRD §2.7: "Rematerialising a hospital's measure set requires the
        input field `expected_hospital_version` holding the client's last
        observed `version` of that hospital; a value that does not equal the
        hospital's current `version` at the time of the write is rejected with
        `ERR_STALE_VERSION` and HTTP status 412."

        Design: Corner/cross_cutting_complexity_layers/measure_set_refresh_occ_stale_version_rejected
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        validate_success(api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN), 201)
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        observed = validate_success(api_client.get_hospital(hospital["id"], READER))["version"]

        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)
        submitted = validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))
        assert submitted["af_status"] == "SUBMITTED"
        now = validate_success(api_client.get_hospital(hospital["id"], READER))["version"]
        assert now > observed

        stale = api_client.refresh_measures(
            hospital["id"], {"expected_hospital_version": observed}, ENGINE)
        validate_error(stale, "ERR_STALE_VERSION", 412)

        set_clock(CLOCK_2026_06_02)
        current = api_client.refresh_measures(
            hospital["id"], {"expected_hospital_version": now}, ENGINE)
        refreshed = validate_success(current)
        assert refreshed["readiness_state"] in ["INCOMPLETE", "READY"]

    def test_a_stale_version_is_visible_to_the_very_next_write(self):
        """PRD §2.7: "The field is not optional on either operation, and no
        other write operation in the API accepts a version field."

        Design: Corner/consistency_model/immediate_consistency_stale_version_is_observed_on_the_very_next_write
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        validate_success(api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN), 201)
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        before = validate_success(api_client.get_hospital(hospital["id"], READER))["version"]

        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)
        after = validate_success(api_client.get_hospital(hospital["id"], READER))["version"]
        assert after > before

        stale = api_client.refresh_measures(
            hospital["id"], {"expected_hospital_version": before}, ENGINE)
        validate_error(stale, "ERR_STALE_VERSION", 412)

        set_clock(CLOCK_2026_06_02)
        post = validate_success(api_client.get_hospital(hospital["id"], READER))["version"]
        validate_success(api_client.refresh_measures(
            hospital["id"], {"expected_hospital_version": post}, ENGINE))


class TestImmediateConsistency:

    def test_submit_advances_disclosure_and_version_atomically(self):
        """PRD §2.4: "Derived-field recomputation is a modification like any
        other: when a computed property such as a hospital's
        `disclosure_status` or a survey's `reliability_weight` is refreshed, the
        owning resource's `updated_at` moves and its `version` increments."
        PRD §3.3: "the hospital's `disclosure_status` becomes `SUBMITTED`, its
        `updated_at` is refreshed, its `version` increments"

        Design: Corner/consistency_model/immediate_consistency_disclosure_status_visible_in_the_submit_response
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        validate_success(api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN), 201)
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        before = validate_success(api_client.get_hospital(hospital["id"], READER))["version"]
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)

        submitted = validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))
        assert submitted["af_status"] == "SUBMITTED"

        hospital_now = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert hospital_now["disclosure_status"] == "SUBMITTED"
        assert hospital_now["version"] > before


class TestCascadeOrderSensitivity:

    def test_a_discrepancy_after_the_refresh_leaves_the_set_incomplete(self):
        """PRD §3.3: "the measure change then marks the hospital's measure set
        stale, flipping its `readiness_state` back to `INCOMPLETE`"
        PRD §3.3: "that incomplete set drives the hospital's
        `disclosure_status` to `UNVERIFIED` on the next read"

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_two_segment_chain_is_order_sensitive
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        validate_success(api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN), 201)
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(validation_method="ATTESTATION"),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0},
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))

        set_clock(CLOCK_2026_06_02)
        hospital_now = validate_success(api_client.get_hospital(hospital["id"], READER))
        measure_set = validate_success(api_client.refresh_measures(
            hospital["id"], {"expected_hospital_version": hospital_now["version"]}, ENGINE))
        assert measure_set["readiness_state"] == "READY"

        opened = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "DISCREPANCY_REQUEST"}, ANALYST))
        assert opened["af_status"] == "DISCREPANCY_OPEN"
        assert opened["verification_cycle"] == 1

        reread = validate_success(api_client.get_measure_set(measure_set["id"], READER))
        assert reread["readiness_state"] == "INCOMPLETE", (
            "the discrepancy landed after the refresh, so the materialised set is invalidated")
        assert validate_success(api_client.get_hospital(
            hospital["id"], READER))["disclosure_status"] == "UNVERIFIED"


class TestDerivedFieldReconciliation:

    def test_source_document_count_tracks_the_distinct_sourced_measures(self):
        """PRD §2.8: "a hospital also accumulates a
        `submitted_source_document_count` that counts the survey measures
        carrying a non-null `source_program_id` plus the adopted supporting
        documents attached to reanalysis requests."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_on_hospital_read
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE, label="Baseline Methodology")
        hospital = register_hospital()
        validate_success(api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN), 201)
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)

        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)
        one = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert one["submitted_source_document_count"] == 1

        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o2", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)
        two = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert two["submitted_source_document_count"] == 2

        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o2", "raw_value": 80.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)
        three = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert three["submitted_source_document_count"] == 2, (
            "a re-posted measure replaces its row rather than adding one")

        rows, _meta = validate_paginated(api_client.list_survey_measures(
            READER, {"survey_id": survey["id"]}))
        assert len(rows) == 2
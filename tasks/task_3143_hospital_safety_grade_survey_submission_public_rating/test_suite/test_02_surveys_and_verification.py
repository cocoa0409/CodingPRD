"""Survey creation, measure reporting, submission and independent verification."""

import pytest

from test_helpers import (
    CLOCK_2026_06_01,
    CLOCK_2026_07_01,
    CLOCK_2026_07_15,
    TEST_USERS,
    api_client,
    create_cycle,
    create_survey_measure_payload,
    create_survey_payload,
    current_hospital_version,
    cut_score_run,
    get_review_for,
    make_respondent_headers,
    open_cycle_review,
    open_survey,
    pin_methodology,
    publish_methodology,
    record_measure,
    refresh_measures,
    register_hospital,
    set_clock,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
    verify_survey,
)
from test_helpers.constants import BASELINE_MEASURE_DEFINITIONS

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]


def _pin_baseline(hospital_id):
    version = validate_success(api_client.create_methodology_version({
        "label": "Baseline Methodology",
        "measure_definitions": [
            {"measure_code": "o1", "domain": "PATIENT_SAFETY", "scale_factor": 1.0,
             "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
             "higher_is_better": True, "derivation_rule": "NONE"},
            {"measure_code": "o2", "domain": "CPOE", "scale_factor": 1.0,
             "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
             "higher_is_better": True, "derivation_rule": "NONE"},
            {"measure_code": "o3", "domain": "STAFFING", "scale_factor": 1.0,
             "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
             "higher_is_better": True, "derivation_rule": "NONE"},
        ],
        "publication_date": "2026-05-01T00:00:00Z",
    }, ADMIN), 201)
    api_client.publish_methodology_version(version["id"], ADMIN)
    pin = api_client.pin_methodology_version(
        hospital_id, {"methodology_version_id": version["id"]}, ADMIN)
    validate_success(pin, 201)
    return version


def _register_pinned_hospital():
    hospital = validate_success(api_client.create_hospital({
        "name": "C0 Community Hospital", "ccn": "261000", "state_code": "MO",
        "bed_count": 40, "teaching_status": "NON_TEACHING", "annual_discharges": 500,
        "survey_contact_email": "c0@example.org",
    }, ADMIN), 201)
    version = _pin_baseline(hospital["id"])
    return hospital, version


class TestSurveyCreation:

    def test_survey_pins_methodology_and_starts_awaiting_submission(self):
        """PRD §3.2: "A `HospitalRespondent` opens a survey against a hospital,
        and the methodology version that will govern the submission is captured
        at that moment from the hospital's `active_methodology_version_id`."
        PRD §3.2: "Dimension A is `af_status`, which begins at
        `AWAITING_SUBMISSION`; dimension B is `af_certification_level`, which
        begins at `UNCERTIFIED`."
        PRD §3.2: "The survey also starts at `verification_cycle` zero with a
        null `verification_response` and a null `reliability_weight`."

        Design: Corner/entities/survey_create_pins_methodology_and_starts_awaiting_submission
        """
        hospital, version = _register_pinned_hospital()
        response = api_client.create_survey(
            hospital["id"], create_survey_payload(), make_respondent_headers(hospital["id"]))
        survey = validate_success(response, 201)
        assert survey["methodology_version_id"] == version["id"]
        assert survey["af_status"] == "AWAITING_SUBMISSION"
        assert survey["af_certification_level"] == "UNCERTIFIED"
        assert survey["verification_cycle"] == 0
        assert survey["verification_response"] is None
        assert survey["submitted_by_user_id"] == hospital["id"]
        assert survey["reliability_weight"] is None


class TestMeasureReporting:

    def test_client_supplied_measure_status_and_version_are_ignored(self):
        """PRD §4: "Operations that create a new stand-alone resource, or add a
        new distinct resource to a collection, return a `201 Created` status code."
        PRD §2.4: "`version` — a system-managed integer that increments on every
        modification to the resource."

        Design: Corner/entities/survey_measure_extra_field_measure_status_is_ignored_input
        """
        hospital, _version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        response = api_client.create_survey_measure(
            hospital["id"],
            create_survey_measure_payload(
                survey["id"], "o1", 70.0, "CMS_HOSPITAL_COMPARE",
                measure_status="PUBLIC_SOURCE_SUBSTITUTED", version=99),
            make_respondent_headers(hospital["id"]),
        )
        measure = validate_success(response, 201)
        assert measure["measure_status"] == "REPORTED"
        assert isinstance(measure["version"], int)
        assert measure["derived_value"] == pytest.approx(70.0)
        rows, _meta = validate_paginated(api_client.list_survey_measures(
            READER, {"survey_id": survey["id"], "measure_status": "REPORTED"}))
        assert len(rows) == 1

    def test_missing_required_raw_value_is_invalid_request(self):
        """PRD §3.2: "A payload naming the `survey_id`, a `measure_code`, a
        `raw_value` of at least zero and an optional `source_program_id` creates
        or replaces the hospital's measure row for that code"."

        Design: Corner/entities/survey_measure_create_missing_raw_value_returns_invalid_request
        """
        hospital, _version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        response = api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1"},
            make_respondent_headers(hospital["id"]),
        )
        error_data = validate_error(response, "ERR_INVALID_REQUEST", 400)
        assert error_data["error_id"] != "ERR_SURVEY_NOT_FOUND"
        rows, _meta = validate_paginated(api_client.list_survey_measures(
            READER, {"survey_id": survey["id"]}))
        assert rows == []


class TestSubmissionGuards:

    def test_second_submit_is_refused_and_fires_no_cascade(self):
        """PRD §3.3: "The survey must still be `AWAITING_SUBMISSION`, or the
        attempt is refused with `ERR_SURVEY_ALREADY_SUBMITTED`."

        Design: Corner/state_machines/submit_already_submitted_survey_returns_survey_already_submitted
        """
        hospital, _version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            create_survey_measure_payload(survey["id"], "o1", 70.0),
            make_respondent_headers(hospital["id"])), 201)
        submitted = validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))
        after_submit = current_hospital_version(hospital["id"])
        assert after_submit > hospital["version"], (
            "PRD §3.3: submission increments the hospital's `version`")

        second = api_client.submit_survey(survey["id"], make_respondent_headers(hospital["id"]))
        validate_error(second, "ERR_SURVEY_ALREADY_SUBMITTED", 409)
        hospital_now = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert hospital_now["version"] == after_submit, (
            "the refused second submit must not increment the hospital's `version`")
        still = validate_success(api_client.get_survey(survey["id"], READER))
        assert still["af_status"] == "SUBMITTED"
        assert hospital_now["disclosure_status"] == "SUBMITTED"


class TestVerificationAndDiscrepancy:

    def test_self_verification_is_refused_at_the_segregation_of_duties_gate(self):
        """PRD §3.3: "Independently of that state check, the verifying
        `X-User-ID` must differ from the survey's `submitted_by_user_id`, and a
        self-verification is refused with `ERR_SELF_VERIFICATION_FORBIDDEN`."

        Design: Corner/state_machines/verify_own_survey_returns_self_verification_forbidden
        """
        hospital, _version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            create_survey_measure_payload(survey["id"], "o1", 70.0),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))

        refused = api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"},
            {"X-User-ID": hospital["id"], "X-User-Role": "VerificationAnalyst",
             "Content-Type": "application/json"})
        error_data = validate_error(refused, "ERR_SELF_VERIFICATION_FORBIDDEN", 403)
        assert error_data["error_id"] != "ERR_SURVEY_VERIFICATION_ALREADY_OPEN"
        still = validate_success(api_client.get_survey(survey["id"], READER))
        assert still["af_status"] == "SUBMITTED"
        assert still["reliability_weight"] is None

        accepted = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST))
        assert accepted["af_status"] == "VERIFIED"

    def test_accept_without_source_documentation_is_refused(self):
        """PRD §3.3: "Acceptance carries one further evidentiary condition:
        every measure row of the survey must have a non-null `source_program_id`,
        or the survey must carry at least one supporting-document entry adopted
        through a reanalysis request; otherwise the attempt is refused with
        `ERR_SOURCE_DOCUMENTATION_REQUIRED`."

        Design: Corner/state_machines/verify_without_source_program_returns_source_documentation_required
        """
        hospital, _version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(validation_method="ATTESTATION"),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0},
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))

        refused = api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST)
        validate_error(refused, "ERR_SOURCE_DOCUMENTATION_REQUIRED", 409)
        still = validate_success(api_client.get_survey(survey["id"], READER))
        assert still["af_status"] == "SUBMITTED"

        validate_success(api_client.create_survey_measure(
            hospital["id"],
            create_survey_measure_payload(survey["id"], "o1", 70.0),
            make_respondent_headers(hospital["id"])), 201)
        accepted = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST))
        assert accepted["af_status"] == "VERIFIED"

    def test_discrepancy_cascade_reaches_disclosure_and_blocks_reopening(self):
        """PRD §3.3: "first the system orders a source-documentation demand
        against every measure row of that survey whose `source_program_id` is null"
        PRD §3.3: "the measure change then marks the hospital's measure set
        stale, flipping its `readiness_state` back to `INCOMPLETE`"
        PRD §3.3: "that incomplete set drives the hospital's
        `disclosure_status` to `UNVERIFIED` on the next read"

        Design: Difficulty/transitive_cascade/verification_discrepancy_three_hop_cascade_to_disclosure
        """
        hospital, version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(validation_method="ATTESTATION"),
            make_respondent_headers(hospital["id"])), 201)
        measure = validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0},
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))

        opened = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "DISCREPANCY_REQUEST"}, ANALYST))
        assert opened["af_status"] == "DISCREPANCY_OPEN"
        assert opened["verification_cycle"] == 1

        measure_now = validate_success(api_client._request(
            "GET", f"/hospital-safety-rating/survey-measures/{measure['id']}", headers=READER))
        assert measure_now["flag_hold"] is True
        assert measure_now["derived_value"] == pytest.approx(70.0)

        measure_set_rows, _meta = validate_paginated(api_client._request(
            "GET", "/hospital-safety-rating/hospital-measure-sets", headers=READER,
            params={"hospital_id": hospital["id"]}))
        assert measure_set_rows, "the hospital must carry a materialised measure set"
        assert measure_set_rows[0]["readiness_state"] == "INCOMPLETE"

        hospital_now = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert hospital_now["disclosure_status"] == "UNVERIFIED"

        again = api_client.verify_survey(
            survey["id"], {"verification_response": "DISCREPANCY_REQUEST"}, ANALYST)
        validate_error(again, "ERR_SURVEY_VERIFICATION_ALREADY_OPEN", 409)

    def test_second_round_verify_on_a_claimed_cycle_is_refused(self):
        """PRD §3.3: "a survey that is in any other state, or that already
        carries a non-null `verification_response` that is not an open
        discrepancy, is refused with `ERR_SURVEY_VERIFICATION_ALREADY_OPEN`."

        Design: Difficulty/resource_temporal_overlap/survey_verification_round_idempotency_key_collision
        """
        hospital, _version = _register_pinned_hospital()
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(validation_method="ATTESTATION"),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0},
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))

        first = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "DISCREPANCY_REQUEST"}, ANALYST))
        assert first["verification_cycle"] == 1
        assert first["af_status"] == "DISCREPANCY_OPEN"

        second = api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST)
        validate_error(second, "ERR_SURVEY_VERIFICATION_ALREADY_OPEN", 409)
        unchanged = validate_success(api_client.get_survey(survey["id"], READER))
        assert unchanged["verification_cycle"] == 1

        # A distinct key value is free once the survey carries the demanded
        # source programme and the discrepancy is resolved.
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            create_survey_measure_payload(survey["id"], "o1", 70.0),
            make_respondent_headers(hospital["id"])), 201)
        resolved = validate_success(api_client.resolve_survey(
            survey["id"], make_respondent_headers(hospital["id"])))
        assert resolved["af_status"] == "DISCREPANCY_RESOLVED"
        accepted = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST))
        assert accepted["af_status"] == "VERIFIED"

    def test_open_review_cycle_closes_immediately_when_nothing_is_pending(self):
        """PRD §3.7: "When the logical clock advances strictly past
        `correction_window_ends_at`, a cycle in `OPEN_REVIEW` moves to
        `CORRECTION_CLOSED`, provided no correction is left `PENDING` (or the
        close is refused with `ERR_CORRECTIONS_PENDING`) and no review is left
        `PENDING` (or it is refused with `ERR_REVIEWS_PENDING`)."
        PRD §3.7: "From `CORRECTION_CLOSED` the cycle advances to `EMBARGOED`
        once every review in it is `ACCEPTED` or `CORRECTION_REQUESTED`"

        Design: Difficulty/boundary_precision_check/empty_accepted_correction_set_edge
        """
        set_clock(CLOCK_2026_06_01)
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 60.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
        cycle = create_cycle(version["id"], label="Baseline Grades")
        cut_score_run(hospital["id"], version["id"], cycle["id"])
        open_cycle_review(cycle["id"])

        review = get_review_for(hospital["id"], cycle["id"])
        hospital_now = validate_success(api_client.get_hospital(hospital["id"], READER))
        validate_success(api_client.accept_preliminary_result(
            hospital["id"], review["id"],
            {"expected_hospital_version": hospital_now["version"]},
            make_respondent_headers(hospital["id"])))

        set_clock(CLOCK_2026_07_01)
        cycle_now = validate_success(api_client.get_release_cycle(cycle["id"], READER))
        assert cycle_now["correction_request_count"] == 0
        assert cycle_now["state"] == "EMBARGOED", (
            "a zero-correction cycle closes and advances to EMBARGOED with no caller action")

        # PRD §3.7: publication happens only "at or after the cycle's
        # `publication_date`" — the 2026-07-01 instant sits inside the embargo.
        set_clock(CLOCK_2026_07_15)
        published = validate_success(api_client.publish_release_cycle(cycle["id"], ENGINE))
        assert published["state"] == "PUBLISHED"
        assert published["embargo_lifted"] is True
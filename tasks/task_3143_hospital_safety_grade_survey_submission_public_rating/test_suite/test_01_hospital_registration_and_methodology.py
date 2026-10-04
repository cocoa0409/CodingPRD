"""Hospital registration, methodology lineage and the authorisation tiers."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    anonymous_headers,
    create_hospital_payload,
    create_methodology_version_payload,
    create_survey_payload,
    headers_for,
    make_respondent_headers,
    measure_definition,
    publish_methodology,
    register_hospital,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]
PURCHASER = TEST_USERS["purchaser_headers"]


class TestHospitalRegistration:

    def test_registration_returns_every_declared_field_and_initial_defaults(self):
        """PRD §2.4: "carries the same four system-managed properties".
        PRD §3.1: "A successful registration lands the hospital in `ACTIVE`
        status with `disclosure_status` `NEVER_SUBMITTED`, a null
        `worst_grade_ever`, a null `active_methodology_version_id`, and a zero
        `submitted_source_document_count`."

        Design: Corner/entities/hospital_create_returns_every_declared_field_and_initial_defaults
        """
        response = api_client.create_hospital(create_hospital_payload(), ADMIN)
        data = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert data["status"] == "ACTIVE"
        assert isinstance(data["version"], int) and data["version"] >= 1
        assert data["disclosure_status"] == "NEVER_SUBMITTED"
        assert data["submitted_source_document_count"] == 0
        assert data["worst_grade_ever"] is None
        assert data["active_methodology_version_id"] is None
        assert data["id"] and data["created_at"] and data["updated_at"]
        meta = response.json()["meta"]
        assert meta["api_request_id"] and meta["api_request_timestamp"]

    def test_get_with_unknown_id_returns_hospital_not_found(self):
        """PRD §2.5: "Requests that target a resource nested inside another
        resolve their path identifiers from left to right and fail on the first
        identifier that does not correspond to a persisted resource."

        Design: Corner/entities/hospital_get_with_unknown_id_returns_hospital_not_found
        """
        response = api_client.get_hospital(NON_EXISTENT_UUID, READER)
        validate_error(response, "ERR_HOSPITAL_NOT_FOUND", 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_HOSPITAL_NOT_FOUND"
        assert body["data"]["message"]

    def test_duplicate_ccn_is_refused_and_creates_no_second_row(self):
        """PRD §3.1: "The `ccn` is immutable and unique across the entire
        programme: a registration whose `ccn` already belongs to another
        hospital is refused with `ERR_DUPLICATE_CCN`, and a `teaching_status`
        outside the two permitted values is refused with
        `ERR_INVALID_TEACHING_STATUS`."

        Design: Corner/entities/duplicate_ccn_returns_conflict
        """
        register_hospital(ccn="261000", state_code="MO")
        clash = api_client.create_hospital(
            create_hospital_payload(ccn="261000", name="Rival Hospital", state_code="KS"), ADMIN)
        validate_error(clash, "ERR_DUPLICATE_CCN", 409)
        rows, _meta = validate_paginated(
            api_client.list_hospitals(READER, {"state_code": "KS"}))
        assert rows == [], "the refused registration must not have created a row"


class TestErrorEnvelope:

    def test_hospital_not_found_error_is_triggerable_and_shaped_per_envelope(self):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/hospital_not_found_error_is_triggerable_and_shaped_per_envelope
        """
        response = api_client.get_hospital("00000000-0000-4000-8000-000000000021", READER)
        assert response.status_code == 404
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_HOSPITAL_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert body["meta"]["api_request_id"] and body["meta"]["api_request_timestamp"]

    def test_missing_user_context_header_is_rejected_before_any_business_tier(self):
        """PRD §2.1: "Missing or empty values on either header are refused with
        `ERR_MISSING_USER_CONTEXT_HEADER`; this check is the first thing the
        server evaluates on every operation, with the single exception of the
        test-driving facility that sets the logical clock."

        Design: Corner/errors/missing_user_context_header_is_rejected_before_any_business_tier
        """
        register_hospital(ccn="261000")
        response = api_client.create_hospital(
            create_hospital_payload(ccn="261000", name="Duplicate Hospital"),
            anonymous_headers(),
        )
        validate_error(response, "ERR_MISSING_USER_CONTEXT_HEADER", 400)
        rows, _meta = validate_paginated(api_client.list_hospitals(READER, {"state_code": "MO"}))
        assert len(rows) == 1, "the refused call must not have registered a hospital"

    def test_duplicate_ccn_error_is_triggerable_and_not_a_generic_conflict(self):
        """PRD §3.1: "The `ccn` is immutable and unique across the entire
        programme: a registration whose `ccn` already belongs to another
        hospital is refused with `ERR_DUPLICATE_CCN`, and a `teaching_status`
        outside the two permitted values is refused with
        `ERR_INVALID_TEACHING_STATUS`."

        Design: Corner/errors/duplicate_ccn_error_is_triggerable_and_not_a_generic_conflict
        """
        incumbent = register_hospital(ccn="261000", name="C0 Community Hospital")
        clash = api_client.create_hospital(
            create_hospital_payload(ccn="261000", name="C0 Clone Hospital"), ADMIN)
        error_data = validate_error(clash, "ERR_DUPLICATE_CCN", 409)
        assert error_data["error_id"] != "ERR_INVALID_REQUEST"
        reread = validate_success(api_client.get_hospital(incumbent["id"], READER))
        assert reread["name"] == "C0 Community Hospital"


class TestAuthorisationTiers:

    def test_rating_admin_cannot_verify_a_survey(self):
        """PRD §2.1: "It is deliberately excluded from verifying surveys and
        from deciding reanalysis requests, which are the analyst's prerogative."

        Design: Corner/rbac/rating_admin_cannot_verify_a_survey
        """
        hospital = register_hospital()
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY"),
                measure_definition("o2", "CPOE"),
                measure_definition("o3", "STAFFING"),
            ],
            label="Baseline Methodology",
        )
        api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN)
        survey = validate_success(api_client.create_survey(
            hospital["id"],
            create_survey_payload(),
            make_respondent_headers(hospital["id"]),
        ), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"]),
        ), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))

        refused = api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ADMIN)
        validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", 403)
        still = validate_success(api_client.get_survey(survey["id"], READER))
        assert still["af_status"] == "SUBMITTED"
        assert still["reliability_weight"] is None

        accepted = validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST))
        assert accepted["af_status"] == "VERIFIED"

    def test_verification_analyst_cannot_publish_a_release_cycle(self):
        """PRD §2.1: "It rematerialises measure sets, cuts score runs, opens
        review windows, publishes release cycles, and decides filed correction
        requests. It holds no verification or methodology-authoring authority."

        Design: Corner/rbac/verification_analyst_cannot_publish_a_release_cycle
        """
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY"),
                measure_definition("o2", "CPOE"),
                measure_definition("o3", "STAFFING"),
            ],
            label="Baseline Methodology",
        )
        cycle = validate_success(api_client.create_release_cycle(
            {
                "label": "Baseline Grades",
                "methodology_version_id": version["id"],
                "preliminary_release_date": "2026-06-01T00:00:00Z",
                "correction_window_ends_at": "2026-06-30T00:00:00Z",
                "publication_date": "2026-07-15T00:00:00Z",
            }, ADMIN), 201)

        refused = api_client.publish_release_cycle(cycle["id"], ANALYST)
        error_data = validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", 403)
        assert error_data["error_id"] != "ERR_CYCLE_HAS_NO_GRADES"
        reread = validate_success(api_client.get_release_cycle(cycle["id"], READER))
        assert reread["state"] == "DRAFT"
        assert reread["embargo_lifted"] is False

    def test_hospital_respondent_cannot_advance_its_own_reanalysis_request(self):
        """PRD §2.1: "This role verifies or disputes surveys, opens
        preliminary-result reviews, decides reanalysis requests, and reviews
        pending methodology changes."
        PRD §3.6: "A request may also be raised naming the hospital and then be
        withdrawn by that same hospital, which is permitted only when the acting
        principal corresponds to the hospital named in the request, or the
        attempt is refused with `ERR_HOSPITAL_OWNER_MISMATCH`."

        Design: Corner/rbac/hospital_respondent_cannot_verify_or_decide_reanalysis
        """
        hospital = register_hospital()
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY"),
                measure_definition("o2", "CPOE"),
                measure_definition("o3", "STAFFING"),
            ],
            label="Baseline Methodology",
        )
        api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN)
        survey = validate_success(api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.create_survey_measure(
            hospital["id"],
            {"survey_id": survey["id"], "measure_code": "o1", "raw_value": 70.0,
             "source_program_id": "CMS_HOSPITAL_COMPARE"},
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.submit_survey(
            survey["id"], make_respondent_headers(hospital["id"])))
        validate_success(api_client.verify_survey(
            survey["id"], {"verification_response": "ACCEPT"}, ANALYST))
        request = validate_success(api_client.create_reanalysis_request(
            hospital["id"],
            {"survey_id": survey["id"], "subset_selector": [{"measure_code": "o1"}],
             "supporting_documents": [
                 {"document_code": "HAND_HYGIENE", "issued_on": "2026-05-01T00:00:00Z"}]},
            make_respondent_headers(hospital["id"])), 201)

        refused = api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "START_REVIEW"},
            make_respondent_headers(hospital["id"]))
        validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", 403)
        reread = validate_success(api_client.get_reanalysis_request(request["id"], READER))
        assert reread["status"] == "PENDING"

        withdrawn = validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "WITHDRAW"},
            make_respondent_headers(hospital["id"])))
        assert withdrawn["status"] == "WITHDRAWN"

    def test_purchaser_admin_cannot_open_a_survey(self):
        """PRD §2.1: "This role registers purchasers and maintains their network
        listings and minimum acceptable letter."

        Design: Corner/rbac/purchaser_admin_cannot_touch_clinical_surfaces
        """
        hospital = register_hospital()
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY"),
                measure_definition("o2", "CPOE"),
                measure_definition("o3", "STAFFING"),
            ],
            label="Baseline Methodology",
        )
        api_client.pin_methodology_version(
            hospital["id"], {"methodology_version_id": version["id"]}, ADMIN)

        refused = api_client.create_survey(
            hospital["id"], create_survey_payload(), PURCHASER)
        validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", 403)
        rows, _meta = validate_paginated(
            api_client.list_hospital_surveys(hospital["id"], READER))
        assert rows == []

        allowed = api_client.create_survey(
            hospital["id"], create_survey_payload(),
            make_respondent_headers(hospital["id"]))
        validate_success(allowed, 201)
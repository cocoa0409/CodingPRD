"""SiteSurvey tests: initial state, attenuation derivation, approval boundary,
segregation of duties, and supersession side effects.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_survey,
    create_approved_survey,
    create_enterprise_with_site,
    create_submitted_survey,
    create_survey_payload,
    get_success_data,
    make_field_technician_headers,
    make_rf_engineer_headers,
    validate_error,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
FT = TEST_USERS["field_technician_headers"]


class TestSurveyCreation:
    def test_new_survey_initial_state_is_draft(self):
        """PRD §3.2: "A `FieldTechnician` visits the site and records a
        SiteSurvey in `DRAFT`".

        Design: Corner/state_machines/survey_initial_state_is_draft
        """
        _ent, site = create_enterprise_with_site()
        resp = api_client.create_survey(site["id"], create_survey_payload(), FT)
        data = validate_success(resp, expected_status=201)
        assert_survey(data)
        assert data["status"] == "DRAFT"

    def test_new_survey_carries_surveyor_id_and_inputs(self):
        """PRD §3.2: "supplying their own operator identifier as `surveyor_id`,
        the `survey_date` of the physical visit, the median reference signal
        received power `measured_rsrp_dbm`, the median
        signal-to-interference-plus-noise ratio `measured_sinr_db`, the
        measured indoor `floor_plan_area_sqm`, and a `building_material_class`
        of `OPEN`, `WOOD`, `CONCRETE`, `STEEL`, or `MIXED`."

        Design: Corner/state_machines/survey_initial_state_is_draft
        """
        _ent, site = create_enterprise_with_site()
        payload = create_survey_payload(
            surveyor_id="ft-check", measured_rsrp_dbm=-75, measured_sinr_db=22,
            floor_plan_area_sqm=750, building_material_class="WOOD",
        )
        resp = api_client.create_survey(site["id"], payload, FT)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["surveyor_id"] == "ft-check"
        assert data["measured_rsrp_dbm"] == -75
        assert data["measured_sinr_db"] == 22
        assert data["building_material_class"] == "WOOD"


class TestSurveyAttenuation:
    def test_attenuation_computed_from_material_steel(self):
        """PRD §3.2: "The moment the survey is created — and again whenever its
        `building_material_class` changes — the server derives
        `attenuation_factor_db` from the material class: `OPEN` maps to 3 dB,
        `WOOD` to 6 dB, `CONCRETE` to 12 dB, `STEEL` to 18 dB, and `MIXED` to
        10 dB."

        Design: Corner/entities/site_survey_attenuation_computed_from_material
        """
        _ent, site = create_enterprise_with_site()
        payload = create_survey_payload(building_material_class="STEEL")
        resp = api_client.create_survey(site["id"], payload, FT)
        data = validate_success(resp, expected_status=201)
        assert data["attenuation_factor_db"] == 18

    def test_attenuation_lookup_covers_all_materials(self):
        """PRD §3.2: "the server derives `attenuation_factor_db` from the
        material class: `OPEN` maps to 3 dB, `WOOD` to 6 dB, `CONCRETE` to
        12 dB, `STEEL` to 18 dB, and `MIXED` to 10 dB."

        Design: Corner/entities/site_survey_attenuation_computed_from_material
        """
        expected = {"OPEN": 3, "WOOD": 6, "CONCRETE": 12, "STEEL": 18, "MIXED": 10}
        _ent, site = create_enterprise_with_site()
        for material, att in expected.items():
            payload = create_survey_payload(building_material_class=material)
            resp = api_client.create_survey(site["id"], payload, FT)
            data = validate_success(resp, expected_status=201)
            assert data["attenuation_factor_db"] == att, (
                f"{material} should derive attenuation {att}, got {data['attenuation_factor_db']}"
            )


class TestSurveyRsrpBoundary:
    def test_approve_succeeds_at_exactly_minus_110_dbm(self):
        """PRD §3.2: "the survey's `measured_rsrp_dbm` must be at least
        -110 dBm — a weaker median signal is rejected with
        `ERR_SURVEY_SIGNAL_TOO_WEAK` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/survey_rsrp_threshold_negative_110
        """
        _ent, site = create_enterprise_with_site()
        survey, _ = create_submitted_survey(
            site["id"], surveyor_id="ft-b1", measured_rsrp_dbm=-110
        )
        resp = api_client.approve_survey(site["id"], survey["id"], RFE)
        data = validate_success(resp)
        assert data["status"] == "APPROVED"

    def test_approve_rejected_at_minus_111_dbm(self):
        """PRD §3.2: "the survey's `measured_rsrp_dbm` must be at least
        -110 dBm — a weaker median signal is rejected with
        `ERR_SURVEY_SIGNAL_TOO_WEAK` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/survey_rsrp_threshold_negative_110
        """
        _ent, site = create_enterprise_with_site()
        survey, _ = create_submitted_survey(
            site["id"], surveyor_id="ft-b2", measured_rsrp_dbm=-111
        )
        resp = api_client.approve_survey(site["id"], survey["id"], RFE)
        validate_error(resp, ApiErrorId.ERR_SURVEY_SIGNAL_TOO_WEAK)


class TestSurveySegregationOfDuties:
    def test_field_technician_cannot_approve_survey_role_blocked(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.2: "Approval belongs to a different pair of hands — an
        `RFEngineer`".

        Design: Corner/rbac/field_technician_cannot_approve_own_survey
        """
        _ent, site = create_enterprise_with_site()
        survey, ft_headers = create_submitted_survey(site["id"], surveyor_id="ft-007")
        # FieldTechnician role lacks the approve permission entirely.
        resp = api_client.approve_survey(site["id"], survey["id"], ft_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_self_approval_by_rf_engineer_rejected_with_segregation(self):
        """PRD §3.2: "the approving engineer may not be the same operator who
        submitted it; a self-approval is rejected with
        `ERR_SEGREGATION_OF_DUTY`."

        Design: Corner/rbac/field_technician_cannot_approve_own_survey
        """
        _ent, site = create_enterprise_with_site()
        # Submit under X-User-ID shared-op; then attempt approval by an
        # RFEngineer whose X-User-ID equals the submitter's X-User-ID.
        survey, _ = create_submitted_survey(site["id"], surveyor_id="op-777")
        rfe_same_op = make_rf_engineer_headers("op-777")
        resp = api_client.approve_survey(site["id"], survey["id"], rfe_same_op)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)

    def test_submit_restricted_to_surveying_technician(self):
        """PRD §3.2: "Submitting the survey moves it from `DRAFT` to
        `SUBMITTED` and is restricted to the technician who performed it:
        `surveyor_id` must equal the caller's `X-User-ID`."

        Design: Corner/rbac/field_technician_cannot_approve_own_survey
        """
        _ent, site = create_enterprise_with_site()
        payload = create_survey_payload(surveyor_id="ft-original")
        resp = api_client.create_survey(site["id"], payload, FT)
        survey = validate_success(resp, expected_status=201)
        # A different operator attempts to submit.
        other = make_field_technician_headers("ft-intruder")
        resp = api_client.submit_survey(site["id"], survey["id"], other)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestSurveyApprovalSideEffects:
    def test_approval_drives_site_planned_to_surveyed(self):
        """PRD §3.2: "Approving a survey is the hinge that moves the whole site
        forward: the parent Site transitions `PLANNED → SURVEYED`, its
        `posture` becomes `DESIGNING`, and its `version` increments."

        Design: Corner/state_machines/survey_initial_state_is_draft
        """
        _ent, site = create_enterprise_with_site()
        survey, _ = create_submitted_survey(site["id"], surveyor_id="ft-s1")
        before = get_success_data(api_client.get_site(site["id"], NA))
        resp = api_client.approve_survey(site["id"], survey["id"], RFE)
        data = validate_success(resp)
        assert data["status"] == "APPROVED"
        after = get_success_data(api_client.get_site(site["id"], NA))
        assert before["status"] == "PLANNED"
        assert after["status"] == "SURVEYED"
        assert after["posture"] == "DESIGNING"
        assert after["version"] == before["version"] + 1

    def test_newer_survey_approval_supersedes_prior(self):
        """PRD §3.2: "If an earlier survey for the same site was already
        `APPROVED`, the act of approving the newer one automatically supersedes
        the older — the older survey moves to `SUPERSEDED`".

        Design: Corner/state_machines/survey_initial_state_is_draft
        """
        _ent, site = create_enterprise_with_site()
        s1, site_after1 = create_approved_survey(site["id"], surveyor_id="ft-old")
        s2, _site_after2 = create_approved_survey(site["id"], surveyor_id="ft-new")

        older = get_success_data(api_client.get_survey(s1["id"], NA))
        newer = get_success_data(api_client.get_survey(s2["id"], NA))
        assert older["status"] == "SUPERSEDED"
        assert newer["status"] == "APPROVED"

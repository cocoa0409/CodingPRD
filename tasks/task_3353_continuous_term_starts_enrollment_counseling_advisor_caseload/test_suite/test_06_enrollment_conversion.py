"""Enrollment conversion gates: incentive-comp bar, caseload cap, licensure."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS, create_program,
    authorize_state, create_term, open_term, create_advisor,
    create_counselor, create_applicant, create_submitted_application,
    admit_application, create_completed_tce, create_tce_payload,
    create_enrollment_payload, setup_open_term_scenario, assert_enrollment,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


class TestSafetyErrorBeatsConstraintErrorOnEnroll:
    """Assigned counselor is INCENTIVE and the evaluation is only IN_REVIEW:
    the incentive-compensation bar outranks evaluation completeness."""

    def _setup_incentive_counselor_in_review_tce(self):
        ctx = setup_open_term_scenario()
        create_counselor(cap=5, compensation_plan="INCENTIVE",
                         full_name="Ivy Incentive")
        advisor = create_advisor()
        applicant = create_applicant()  # auto-assigned to the sole counselor
        application = create_submitted_application(
            applicant["id"], ctx["term"]["id"], ctx["program"]["id"])
        application = admit_application(application["id"])
        resp = api_client.create_tce(
            application["id"],
            create_tce_payload(accepted_credits=10, in_progress_credits=0),
            REGISTRAR)
        tce = get_success_data(resp)
        get_success_data(api_client.advance_tce(
            tce["id"], "IN_REVIEW", REGISTRAR))
        ctx.update({"advisor": advisor, "applicant": applicant,
                    "application": application})
        return ctx

    def test_incentive_bar_reported_not_evaluation_incomplete(self):
        """PRD §2.7: "Enrollment conversion continues that ordering:
        authorization status, then the restricted-state disclosure, then the
        licensure disclosure, then the incentive-compensation bar, then
        transfer-credit evaluation completeness, and finally advisor caseload
        capacity."
        PRD §3.6: "If the applicant's assigned counselor is on an `INCENTIVE`
        compensation plan, the conversion would attribute an enrollment to an
        incentive-paid counselor and is barred outright with
        `ERR_INCENTIVE_COMP_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_constraint_error_on_enroll
        """
        ctx = self._setup_incentive_counselor_in_review_tce()
        resp = api_client.create_enrollment(
            create_enrollment_payload(
                ctx["application"]["id"], ctx["advisor"]["id"],
                ctx["application"]["version"]),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_COMP_VIOLATION)

    def test_rejected_conversion_creates_no_enrollment(self):
        """PRD §2.7: "Enrollment conversion continues that ordering:
        authorization status, then the restricted-state disclosure, then the
        licensure disclosure, then the incentive-compensation bar, then
        transfer-credit evaluation completeness, and finally advisor caseload
        capacity."
        PRD §3.6: "If the applicant's assigned counselor is on an `INCENTIVE`
        compensation plan, the conversion would attribute an enrollment to an
        incentive-paid counselor and is barred outright with
        `ERR_INCENTIVE_COMP_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_constraint_error_on_enroll
        """
        ctx = self._setup_incentive_counselor_in_review_tce()
        resp = api_client.create_enrollment(
            create_enrollment_payload(
                ctx["application"]["id"], ctx["advisor"]["id"],
                ctx["application"]["version"]),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_COMP_VIOLATION)
        data, meta = validate_paginated(api_client.list_enrollments(
            REGISTRAR, params={"application_id": ctx["application"]["id"]}))
        assert len(data) == 0, "a rejected conversion must create nothing"
        application = get_success_data(
            api_client.get_application(ctx["application"]["id"], REGISTRAR))
        assert application["status"] == "ADMITTED", (
            f"application must remain ADMITTED after the rejected "
            f"conversion; got {application['status']}")


class TestAdvisorCaseloadCapEqualityBoundary:
    def _setup_three_admitted(self):
        ctx = setup_open_term_scenario()
        advisor = create_advisor(cap=2)
        create_counselor(cap=10)
        admitted = []
        for i in range(3):
            applicant = create_applicant(full_name=f"P{i+1}")
            application = create_submitted_application(
                applicant["id"], ctx["term"]["id"], ctx["program"]["id"])
            application = admit_application(application["id"])
            create_completed_tce(application["id"])
            admitted.append(application)
        ctx.update({"advisor": advisor, "admitted": admitted})
        return ctx

    def _enroll(self, application, advisor_id):
        return api_client.create_enrollment(
            create_enrollment_payload(
                application["id"], advisor_id, application["version"],
                tuition_cents=100000),
            REGISTRAR)

    def test_enrollments_up_to_cap_succeed(self):
        """PRD §3.6: "an advisor whose `active_caseload_count` has reached
        their `caseload_cap` is rejected with `ERR_CASELOAD_CAP_EXCEEDED`."
        PRD §3.3: "For an `ADVISOR` it counts the enrollments whose
        `advisor_id` is that member's `id` and whose `status` is
        `REGISTERED`, `ACTIVE`, or `DEFERRED`."

        Design: Difficulty/boundary_precision_check/advisor_caseload_cap_equality_boundary
        """
        ctx = self._setup_three_admitted()
        a1, a2, _ = ctx["admitted"]
        e1 = validate_success(self._enroll(a1, ctx["advisor"]["id"]),
                              expected_status=201)
        assert_enrollment(e1)
        e2 = validate_success(self._enroll(a2, ctx["advisor"]["id"]),
                              expected_status=201)
        assert_enrollment(e2)
        staff = get_success_data(
            api_client.get_staff(ctx["advisor"]["id"], REGISTRAR))
        assert staff["active_caseload_count"] == 2, (
            f"two REGISTERED enrollments against cap 2 must report count 2; "
            f"got {staff['active_caseload_count']}")

    def test_enrollment_beyond_cap_rejected(self):
        """PRD §3.6: "an advisor whose `active_caseload_count` has reached
        their `caseload_cap` is rejected with `ERR_CASELOAD_CAP_EXCEEDED`."
        PRD §3.3: "For an `ADVISOR` it counts the enrollments whose
        `advisor_id` is that member's `id` and whose `status` is
        `REGISTERED`, `ACTIVE`, or `DEFERRED`."

        Design: Difficulty/boundary_precision_check/advisor_caseload_cap_equality_boundary
        """
        ctx = self._setup_three_admitted()
        a1, a2, a3 = ctx["admitted"]
        validate_success(self._enroll(a1, ctx["advisor"]["id"]),
                         expected_status=201)
        validate_success(self._enroll(a2, ctx["advisor"]["id"]),
                         expected_status=201)
        # count == cap (2 == 2) is not strictly below the cap -> rejected.
        resp = self._enroll(a3, ctx["advisor"]["id"])
        validate_error(resp, ApiErrorId.ERR_CASELOAD_CAP_EXCEEDED)


def test_licensure_disclosure_required_at_enrollment():
    """PRD §3.6: "If the program's `licensure_flag` is true,
    `licensure_disclosure_acknowledged` must be true, otherwise
    `ERR_LICENSURE_DISCLOSURE_REQUIRED`."

    Design: Corner/validations/licensure_disclosure_required_at_enrollment
    """
    program = create_program(code="BSN-RN", licensure_flag=True)
    authorize_state(program["id"], state_code="CO")
    term = create_term()
    open_term(term["id"])
    advisor = create_advisor()

    # Application without the licensure acknowledgement.
    applicant1 = create_applicant(full_name="P1")
    app1 = create_submitted_application(
        applicant1["id"], term["id"], program["id"])
    app1 = admit_application(app1["id"])
    create_completed_tce(app1["id"])
    resp = api_client.create_enrollment(
        create_enrollment_payload(app1["id"], advisor["id"], app1["version"],
                                  tuition_cents=100000),
        REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_LICENSURE_DISCLOSURE_REQUIRED)

    # Application carrying licensure_disclosure_acknowledged = true.
    applicant2 = create_applicant(full_name="P2")
    app2 = create_submitted_application(
        applicant2["id"], term["id"], program["id"],
        licensure_disclosure_acknowledged=True)
    app2 = admit_application(app2["id"])
    create_completed_tce(app2["id"])
    resp = api_client.create_enrollment(
        create_enrollment_payload(app2["id"], advisor["id"], app2["version"],
                                  tuition_cents=100000),
        REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert_enrollment(data)
    assert data["status"] == "REGISTERED"

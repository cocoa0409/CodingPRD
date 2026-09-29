"""Role admission, patient scope and the two identity rules that outlive the role table.

Two of these rules cannot be written as a role table at all: the reviewer must not
be the acquirer, and the acquirer is the only writer, so the same role is admitted
and refused on the same endpoint depending only on who is holding it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    BMD_FEMORAL_NECK_OSTEOPENIC,
    CLOCK_SETUP,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_ALT_HEADERS,
    TECHNOLOGIST_ALT_USER_ID,
    TECHNOLOGIST_HEADERS,
    appointment_payload,
    assert_qc_scoring,
    assert_review_outcome,
    assert_score_one_decimal,
    densitometer_payload,
    diagnostic_report_payload,
    frax_payload,
    make_patient_headers,
    payer_policy_payload,
    positioning_review_payload,
    qc_run_payload,
    scan_order_payload,
    scan_session_payload,
    site_measurement_payload,
    treatment_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

LATER_SLOT_START = "2026-03-11T09:00:00Z"
LATER_SLOT_END = "2026-03-11T09:30:00Z"
SHARED_ORDER_DATE = "2026-03-12"
PORTAL_CLOCK = "2026-03-02T09:00:00Z"


class TestTheRoleModelIsSegregationRatherThanHierarchy:
    """No role is a superset of another, and the shared writes really are shared."""

    def test_eight_exclusive_writes_are_forbidden_while_three_shared_ones_land(
        self, world: ProgramWorld
    ):
        """The role gate answers before the body is parsed, so bogus references never matter.

        "Role admission is a property of the operation, not of the resource, and it is
        checked before existence. A role that is simply not admitted to an operation
        receives `ERR_FORBIDDEN_ROLE` even when the addressed resource does not exist"
        "A `PatientPortalUser` has no visibility at all into densitometers, phantom
        quality-control runs, calibration events, appointments, sessions, site
        measurements, positioning reviews or fracture risk assessments, and attempting any
        of those reads yields `ERR_FORBIDDEN_ROLE`."
        "A `Scheduler` runs the front office: patient registration, risk factor intake,
        order entry, and — exclusively — slot booking and slot cancellation."

        Design: Corner/rbac/every_role_exclusive_write_is_forbidden_to_the_other_roles
        """
        pipeline = world.foundation(clock=CLOCK_SETUP)
        order = world.create_order(pipeline.patient_id)
        appointment = world.book(order["id"], pipeline.device_id)
        portal_headers = make_patient_headers(pipeline.patient_id)

        forbidden = [
            world.api.create_payer_policy(
                payer_policy_payload(payer_code="PAY-X", name="Rogue Plan"),
                SCHEDULER_HEADERS,
            ),
            world.api.create_densitometer(
                densitometer_payload(
                    serial_number="HLG-0009",
                    manufacturer="NORLAND",
                    model="XR-600",
                    site_code="EAST",
                ),
                TECHNOLOGIST_HEADERS,
            ),
            world.api.create_scan_appointment(
                appointment_payload(
                    order["id"],
                    pipeline.device_id,
                    start_utc=LATER_SLOT_START,
                    end_utc=LATER_SLOT_END,
                ),
                ADMIN_HEADERS,
            ),
            world.api.create_scan_session(
                appointment["id"], scan_session_payload(), REVIEWER_HEADERS
            ),
            world.api.create_frax_assessment(
                frax_payload(pipeline.patient_id, pipeline.patient_id),
                TECHNOLOGIST_HEADERS,
            ),
            world.api.create_diagnostic_report(
                diagnostic_report_payload(appointment["id"]), REVIEWER_HEADERS
            ),
            world.api.create_treatment_plan(
                treatment_plan_payload(pipeline.patient_id, appointment["id"]),
                SCHEDULER_HEADERS,
            ),
            world.api.list_densitometers(portal_headers),
        ]
        for response in forbidden:
            validate_error(response, ApiErrorId.FORBIDDEN_ROLE.value, 403)

        shared_qc_run = validate_success(
            world.api.create_qc_run(
                pipeline.device_id, qc_run_payload(), ADMIN_HEADERS
            ),
            201,
        )
        assert_qc_scoring(shared_qc_run, 0.0050, 0.500, "PASS")

        shared_order = validate_success(
            world.api.create_scan_order(
                scan_order_payload(
                    pipeline.patient_id,
                    indication="HIGH_RISK_CASE_FINDING",
                    requested_sites=["TOTAL_HIP"],
                    requested_scan_date=SHARED_ORDER_DATE,
                ),
                PHYSICIAN_HEADERS,
            ),
            201,
        )
        assert shared_order["ordered_by_user_id"] == "phys-001"

        clock_by_patient = world.api.set_clock(PORTAL_CLOCK, portal_headers)
        assert clock_by_patient.status_code == 204

        _, policies = validate_paginated(world.api.list_payer_policies(ADMIN_HEADERS))
        assert policies["total_count"] == 1
        _, devices = validate_paginated(world.api.list_densitometers(ADMIN_HEADERS))
        assert devices["total_count"] == 1


def _two_patients_each_with_a_profile_and_an_order(world: ProgramWorld):
    """Two patients on one policy, each with a profile and an order of her own."""
    world.set_clock(CLOCK_SETUP)
    policy = world.create_policy()
    patient_a = world.create_patient(policy["id"], mrn="MRN-7701")
    patient_b = world.create_patient(
        policy["id"], mrn="MRN-7702", birth_date="1960-07-04", baseline_height_cm=158.0
    )
    world.create_profile(patient_a)
    world.create_profile(patient_b, height_cm=158.0, weight_kg=54.0)
    world.create_order(patient_a["id"])
    order_b = world.create_order(patient_b["id"], requested_scan_date="2026-03-11")
    return patient_a, patient_b, order_b


class TestThePortalRoleIsAuthorisedRowByRow:
    """The same endpoint answers 200 for one's own row and 403 for a neighbour's."""

    def test_a_patient_reads_only_her_own_record_orders_and_profiles(
        self, world: ProgramWorld
    ):
        """Four refusals that are neither a role error nor a not-found.

        "When `X-User-Role` is `PatientPortalUser`, by contrast, `X-User-ID` is the `id`
        of the acting `Patient`; ownership checks on any resource that references a
        `Patient` compare the resource's patient foreign key to `X-User-ID`, and a
        mismatch is rejected with `ERR_PATIENT_SCOPE_VIOLATION` (HTTP 403) rather than
        with `ERR_FORBIDDEN_ROLE`."
        "conversely, a `PatientPortalUser` who is admitted to an operation but addresses
        another patient's data receives the scope violation, not the role error."

        Design: Corner/rbac/patient_portal_reads_of_another_patient_are_forbidden
        """
        patient_a, patient_b, order_b = _two_patients_each_with_a_profile_and_an_order(
            world
        )
        as_patient_a = make_patient_headers(patient_a["id"])

        own_record = validate_success(
            world.api.get_patient(patient_a["id"], as_patient_a), 200
        )
        assert own_record["id"] == patient_a["id"]
        assert own_record["mrn"] == "MRN-7701"

        out_of_scope = [
            world.api.get_patient(patient_b["id"], as_patient_a),
            world.api.list_risk_factor_profiles(patient_b["id"], as_patient_a),
            world.api.list_scan_orders(as_patient_a, {"patient_id": patient_b["id"]}),
            world.api.get_scan_order(order_b["id"], as_patient_a),
        ]
        for response in out_of_scope:
            validate_error(response, ApiErrorId.PATIENT_SCOPE_VIOLATION.value, 403)


class TestTheReviewerMayNotBeTheAcquirer:
    """Segregation is decided on the identifier, not on the role."""

    def test_the_acquiring_technologist_is_refused_and_a_colleague_is_accepted(
        self, world: ProgramWorld
    ):
        """The identical body under the identical role succeeds for the other user.

        "a technologist may also sit as a positioning reviewer, but only ever for a study
        somebody else acquired."
        "(35) `X-User-ID` equals the session's `technologist_user_id`, on `POST
        /bone-density/scan-sessions/{id}/positioning-reviews` —
        `ERR_SEGREGATION_OF_DUTIES`, 403."

        Design: Corner/rbac/the_acquiring_technologist_cannot_review_their_own_positioning
        """
        pipeline = world.build(
            stop_after="submitted",
            sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)],
        )

        self_review = world.api.create_positioning_review(
            pipeline.session_id, positioning_review_payload([]), TECHNOLOGIST_HEADERS
        )
        validate_error(self_review, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
        assert world.read_session(pipeline.session_id)["review_status"] == "NOT_REVIEWED"

        colleague_review = validate_success(
            world.api.create_positioning_review(
                pipeline.session_id,
                positioning_review_payload([]),
                TECHNOLOGIST_ALT_HEADERS,
            ),
            201,
        )
        assert colleague_review["reviewer_user_id"] == TECHNOLOGIST_ALT_USER_ID
        assert_review_outcome(colleague_review, 0, False, "ACCEPTED")
        assert world.read_session(pipeline.session_id)["review_status"] == "ACCEPTED"

        _, meta = validate_paginated(
            world.api.list_positioning_reviews(pipeline.session_id, PHYSICIAN_HEADERS)
        )
        assert meta["total_count"] == 1


class TestAcquisitionWritesBelongToTheAcquiringUser:
    """The mirror image of the review rule, and a different error id.

    "That user is the only one permitted to post measurements, record a vertebral
    fracture assessment, submit or repeat this session — and, by the
    segregation-of-duties rule, the one user forbidden from reviewing its positioning."
    """

    def test_a_colleague_is_refused_on_both_writes_and_the_acquirer_is_not(
        self, world: ProgramWorld
    ):
        """Technologist is admitted to both endpoints, so the refusal names the user.

        "(36) `X-User-Role` is `Technologist` and `X-User-ID` is not the session's
        `technologist_user_id`, on `POST /bone-density/scan-sessions/{id}/site-measurements`,
        `POST /bone-density/scan-sessions/{id}/vfa`, `POST
        /bone-density/scan-sessions/{id}/submit-acquisition` and `POST
        /bone-density/scan-sessions/{id}/repeat-acquisition` —
        `ERR_NOT_SESSION_TECHNOLOGIST`, 403."

        Design: Corner/rbac/a_colleague_technologist_cannot_write_to_someone_elses_session
        """
        pipeline = world.build(stop_after="session")
        session_id = pipeline.session_id

        foreign_measurement = world.api.create_site_measurement(
            session_id,
            site_measurement_payload("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC),
            TECHNOLOGIST_ALT_HEADERS,
        )
        validate_error(
            foreign_measurement, ApiErrorId.NOT_SESSION_TECHNOLOGIST.value, 403
        )

        foreign_submit = world.api.submit_acquisition(
            session_id, TECHNOLOGIST_ALT_HEADERS
        )
        validate_error(foreign_submit, ApiErrorId.NOT_SESSION_TECHNOLOGIST.value, 403)
        assert world.read_session(session_id)["measured_site_count"] == 0

        own_measurement = validate_success(
            world.api.create_site_measurement(
                session_id,
                site_measurement_payload("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert own_measurement["site_code"] == "FEMORAL_NECK"

        submitted = validate_success(
            world.api.submit_acquisition(session_id, TECHNOLOGIST_HEADERS), 200
        )
        assert submitted["acquisition_status"] == "SUBMITTED"
        assert_score_one_decimal(submitted["lowest_t_score"], -2.0, "lowest_t_score")

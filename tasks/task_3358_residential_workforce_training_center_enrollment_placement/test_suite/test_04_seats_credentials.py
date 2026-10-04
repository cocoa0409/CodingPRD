"""Seat ledger conservation, parallel enrollment state axes, credential gates."""
from test_helpers import (
    ADVISOR,
    MANAGER,
    SPECIALIST,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_program_seat_invariant,
    assign_applicant,
    assign_bed,
    create_center,
    create_trade_program,
    enroll_applicant,
    get_applicant,
    get_enrollment,
    get_trade_program,
    make_eligible_applicant,
    record_credential,
    setup_enrolled_student,
    transition_credential,
    validate_error,
    validate_success,
)


def _assigned_applicant(program, full_name, barrier="FOSTER_CARE",
                        residential_track=False):
    applicant, _case = make_eligible_applicant(
        full_name=full_name, barrier_flags=[barrier],
    )
    assign_applicant(applicant, residential_track=residential_track)
    return get_applicant(applicant["id"])


class TestSeatConservation:
    def test_two_enrollments_fill_program_exactly(self):
        """PRD section 3.3: "Either way, creation consumes a seat:
        enrolled_count rises by 1, open_seats falls by 1, and a program whose
        open_seats reaches 0 flips from OPEN to FULL."

        Design: Difficulty/compensating_invariant/seat_enroll_unenroll_conserves_capacity
        """
        center = create_center(name="Seat Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=2)
        assert program["enrolled_count"] == 0
        assert program["open_seats"] == 2
        a1 = _assigned_applicant(program, "Seat One")
        a2 = _assigned_applicant(program, "Seat Two", barrier="HOMELESS")
        enroll_applicant(a1["id"], program["id"])
        enroll_applicant(a2["id"], program["id"])
        full = get_trade_program(center["id"], program["id"])
        assert full["enrolled_count"] == 2
        assert full["open_seats"] == 0
        assert full["status"] == "FULL"
        assert_program_seat_invariant(full)

    def test_compensating_unenroll_reopens_seat(self):
        """PRD section 3.3: "it stamps exit_date and exit_reason, releases the
        seat with the same FULL-to-OPEN flip".
        PRD section 2.9: "its open_seats is the remainder of capacity, and its
        status flips itself between OPEN and FULL as seats cross zero".

        Design: Difficulty/compensating_invariant/seat_enroll_unenroll_conserves_capacity
        """
        center = create_center(name="Seat Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=2)
        a1 = _assigned_applicant(program, "Seat One")
        a2 = _assigned_applicant(program, "Seat Two", barrier="HOMELESS")
        e1 = enroll_applicant(a1["id"], program["id"])
        enroll_applicant(a2["id"], program["id"])
        resp = api_client.transition_enrollment(
            e1["id"], {"action": "unenroll", "reason": "WITHDRAWN"}, MANAGER
        )
        assert validate_success(resp)["training_status"] == "UNENROLLED"
        after = get_trade_program(center["id"], program["id"])
        assert after["enrolled_count"] == 1
        assert after["open_seats"] == 1
        assert after["status"] == "OPEN"
        assert_program_seat_invariant(after)


class TestParallelDimensions:
    def test_dorm_assignment_moves_only_residential_axis(self):
        """PRD section 3.3: "The enrollment carries two state dimensions that
        evolve independently: training_status on the training axis and
        residential_status on the residential axis."
        PRD section 3.4: "A successful assignment starts ACTIVE with
        move_out_date null, moves the enrollment's residential axis from
        AWAITING_BED to RESIDENT".

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_training_residential_dims
        """
        bundle = setup_enrolled_student(
            center_name="Dim Center", total_beds=2, capacity=5,
            required_credential_types=["HSE"], supports_remediation=True,
            residential_track=True,
        )
        enrollment = bundle["enrollment"]
        assert enrollment["training_status"] == "REMEDIATION"
        assert enrollment["residential_status"] == "AWAITING_BED"
        assignment = assign_bed(enrollment["id"], move_in_date="2026-09-01",
                                bed_label="B-01")
        assert assignment["status"] == "ACTIVE"
        after = get_enrollment(enrollment["id"])
        assert after["residential_status"] == "RESIDENT"
        assert after["training_status"] == "REMEDIATION", (
            "the training axis must not move with the dormitory assignment"
        )

    def test_credential_verification_moves_only_training_axis(self):
        """PRD section 3.5: "when the credential's owning enrollment sits in
        REMEDIATION and this verification completes the set — every entry of
        the program's required_credential_types now held VERIFIED on this
        enrollment's own credentials — the enrollment auto-advances from
        REMEDIATION to TRAINING without a separate manager action."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_training_residential_dims
        """
        bundle = setup_enrolled_student(
            center_name="Dim Center", total_beds=2, capacity=5,
            required_credential_types=["HSE"], supports_remediation=True,
            residential_track=True,
        )
        enrollment = bundle["enrollment"]
        assign_bed(enrollment["id"], move_in_date="2026-09-01",
                   bed_label="B-01")
        credential = record_credential(enrollment["id"], credential_type="HSE")
        verified = transition_credential(credential["id"], "verify")
        assert verified["status"] == "VERIFIED"
        after = get_enrollment(enrollment["id"])
        assert after["training_status"] == "TRAINING"
        assert after["residential_status"] == "RESIDENT", (
            "the residential axis must not move with the credential verify"
        )
        rows = validate_success(
            api_client.list_dormitory_assignments(enrollment["id"], ADVISOR)
        )
        assert rows[0]["status"] == "ACTIVE"


class TestPrerequisiteGates:
    def _remediation_enrollment(self):
        bundle = setup_enrolled_student(
            center_name="Prereq Center", total_beds=2, capacity=5,
            required_credential_types=["HSE"], supports_remediation=True,
        )
        assert bundle["enrollment"]["training_status"] == "REMEDIATION"
        return bundle

    def test_begin_training_without_verified_prereq_rejected(self):
        """PRD section 3.3: "When the set is incomplete, begin-training fails
        with ERR_PREREQUISITE_NOT_MET."

        Design: Corner/state_machines/begin_training_without_verified_prereq_rejected
        """
        bundle = self._remediation_enrollment()
        enrollment = bundle["enrollment"]
        credential = record_credential(enrollment["id"], credential_type="HSE")
        assert credential["status"] == "EARNED"
        resp = api_client.transition_enrollment(
            enrollment["id"], {"action": "begin_training"}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET)
        assert get_enrollment(enrollment["id"])["training_status"] == "REMEDIATION"
        rows = validate_success(
            api_client.list_credentials(enrollment["id"],
                                        TEST_USERS["career_instructor_headers"])
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "EARNED"

    def test_revoked_credential_reblocks_completion(self):
        """PRD section 3.5: "Revocation moves a VERIFIED credential to REVOKED,
        which is terminal; revocation deliberately does not demote an
        enrollment already in TRAINING, because prerequisites are evaluated
        only at the gates that demand them — enrollment creation,
        begin-training, and completion."
        PRD section 3.3: "every required credential type must be held VERIFIED
        for this enrollment (else ERR_PREREQUISITE_NOT_MET)".

        Design: Corner/state_machines/revoked_credential_reblocks_completion
        """
        bundle = self._remediation_enrollment()
        enrollment = bundle["enrollment"]
        credential = record_credential(enrollment["id"], credential_type="HSE")
        transition_credential(credential["id"], "verify")
        assert get_enrollment(enrollment["id"])["training_status"] == "TRAINING"
        revoked = transition_credential(credential["id"], "revoke")
        assert revoked["status"] == "REVOKED"
        assert get_enrollment(enrollment["id"])["training_status"] == "TRAINING"
        resp = api_client.transition_enrollment(
            enrollment["id"], {"action": "complete"}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET)


class TestCredentialRbac:
    def test_specialist_cannot_record_credentials(self):
        """PRD section 2.1: "A request whose role is authenticated but is not
        listed among the roles authorized for the target endpoint is rejected
        with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/specialist_cannot_record_credentials
        """
        resp = api_client.create_credential(
            {"enrollment_id": "11111111-2222-3333-4444-555555555555",
             "credential_type": "HSE"},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

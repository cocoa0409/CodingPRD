"""Capacity boundary and commit state-vs-capacity priority pair (PRD §3.4, §2.10)."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    clear_application,
    commit_application,
    create_open_program,
    create_partner_agreement,
    create_student,
    create_submitted_application,
    make_student_headers,
    setup_open_program_with_application,
    validate_error,
    validate_success,
    api_client,
    COORD_A_HEADERS,
)


def _walk_to_approved(program, student):
    """Helper: submit + clear + approve one application."""
    application = create_submitted_application(student, program)
    application = clear_application(application, "CLEARED")
    return approve_application(application["id"]), application["id"]


class TestCapacityLastSeat:
    def test_commit_at_last_seat_succeeds(self, api):
        """PRD §3.4: "the program's `seats_taken` must be strictly less than its `capacity`,
        else `ERR_PROGRAM_FULL`."

        Design: Difficulty/boundary_precision_check/capacity_last_seat
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"], capacity=1)
        student1 = create_student(full_name="First Commit", email="c1@uni.edu")
        approved1, app1_id = _walk_to_approved(program, student1)

        committed = commit_application({"id": app1_id}, student1)
        assert committed["status"] == "COMMITTED"
        program_after = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert program_after["seats_taken"] == 1, (
            "Commit at seats_taken == capacity - 1 must succeed and consume the seat"
        )

    def test_commit_beyond_capacity_rejected(self, api):
        """PRD §3.4: "the program's `seats_taken` must be strictly less than its `capacity`,
        else `ERR_PROGRAM_FULL`."

        Design: Difficulty/boundary_precision_check/capacity_last_seat
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"], capacity=1)
        student1 = create_student(full_name="First Commit", email="c1@uni.edu")
        _approved1, app1_id = _walk_to_approved(program, student1)
        commit_application({"id": app1_id}, student1)

        student2 = create_student(full_name="Second Commit", email="c2@uni.edu")
        _approved2, app2_id = _walk_to_approved(program, student2)
        resp = api.commit_application(app2_id, make_student_headers(student2["id"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_FULL)


class TestCommitStateBeatsCapacity:
    def test_commit_from_returned_for_revision_returns_invalid_state(self, api):
        """PRD §2.10: "State-machine preconditions and cross-entity state gates. The target
        resource must be in a valid from-state for the requested transition ... otherwise
        `ERR_INVALID_STATE`." (tier 5, evaluated before "Money and capacity checks last" at
        tier 11.)

        Design: Difficulty/priority_pair_validation_conflict/commit_state_beats_capacity
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"], capacity=1)
        # Student 1 commits, filling the only seat.
        student1 = create_student(full_name="Seat Holder", email="s1@uni.edu")
        approved1, app1_id = _walk_to_approved(program, student1)
        commit_application({"id": app1_id}, student1)

        # Student 2's application sits in RETURNED_FOR_REVISION.
        student2 = create_student(full_name="Second Student", email="s2@uni.edu")
        app2 = create_submitted_application(student2, program)
        clear_application({"id": app2["id"]}, "RETURNED_FOR_REVISION")

        resp = api.commit_application(app2["id"], make_student_headers(student2["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        reread = validate_success(api.get_application(app2["id"], COORD_A_HEADERS))
        assert reread["status"] == "RETURNED_FOR_REVISION"

    def test_commit_from_submitted_returns_invalid_state(self, api):
        """PRD §2.10: "The target resource must be in a valid from-state for the requested
        transition ... otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/commit_state_beats_capacity
        """
        program, student, application = setup_open_program_with_application()
        resp = api.commit_application(
            application["id"], make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

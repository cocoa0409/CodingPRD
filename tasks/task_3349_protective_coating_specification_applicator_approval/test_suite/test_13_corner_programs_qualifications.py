"""Corner breadth index (entities + state machines): qualification-program
defaults and applicator-qualification enrollment/initial state.
"""
from test_helpers import (
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    ApiClient,
    assert_applicator_qualification,
    assert_qualification_program,
    create_applicator,
    create_coating_system,
    create_program,
    enroll_qualification,
    read_applicator,
    validate_success,
)


def test_qualification_program_creation_defaults(api: ApiClient):
    """PRD §3.3: "a `min_quality_history_score` floor, and three defaulted
    requirements: `min_consecutive_passed_inspections` defaults to 3,
    `requires_training` defaults to true, and `requires_equipment_audit`
    defaults to true. A program is created `ACTIVE`".

    Design: Corner/entities/qualification_program_creation_defaults
    """
    system = create_coating_system(api, system_code="SW-QP-01")

    # The three optional fields are omitted entirely so the server-side
    # defaults are what the response proves.
    payload = {
        "program_code": "QP-DFLT-1",
        "coating_system_id": system["id"],
        "min_quality_history_score": 400,
    }

    program = validate_success(
        api.create_qualification_program(payload, TECHNICAL_SERVICE_ENGINEER_HEADERS),
        expected_status=201,
    )
    assert_qualification_program(program)
    assert program["min_consecutive_passed_inspections"] == 3
    assert program["requires_training"] is True
    assert program["requires_equipment_audit"] is True
    assert program["status"] == "ACTIVE"


def test_applicator_qualification_enrollment_starts_candidate(api: ApiClient):
    """PRD §3.3: "An `ApplicatorRep` enrolls their company in a program,
    creating an **applicator qualification** in `CANDIDATE` status. Enrollment
    records the `program_id`; the `applicator_id` is fixed by the parent
    applicator in the path; `training_completed_at` (the timestamp of
    completed manufacturer training) may be null at creation;
    `equipment_audit_passed` defaults to false; and `suspension_count` starts
    at 0."

    Design: Corner/entities/applicator_qualification_enrollment_starts_candidate
    """
    applicator = create_applicator(api, company_name="Beta Blasters", contact_email="qa@beta.example")
    system = create_coating_system(api, system_code="SW-QP-02")
    program = create_program(api, system["id"], program_code="QP-ENR-1", min_quality_history_score=400)

    qualification = enroll_qualification(
        api, applicator["id"], program["id"],
        training_completed_at="2026-08-15T09:00:00Z", equipment_audit_passed=True,
    )

    assert_applicator_qualification(qualification)
    assert qualification["status"] == "CANDIDATE"
    assert qualification["suspension_count"] == 0
    assert qualification["applicator_id"] == applicator["id"]
    assert qualification["equipment_audit_passed"] is True


def test_applicator_qualification_initial_state_is_candidate(api: ApiClient):
    """PRD §3.3: "An `ApplicatorRep` enrolls their company in a program,
    creating an **applicator qualification** in `CANDIDATE` status."
    PRD §3.3: "On success the qualification becomes `CERTIFIED`, the
    applicator's `version` increments by 1, and — when this is the
    applicator's first certification — the applicator itself moves
    automatically from `REGISTERED` to `ACTIVE`."

    Design: Corner/state_machines/applicator_qualification_initial_state_is_candidate
    """
    applicator = create_applicator(api, company_name="Init Coaters", contact_email="i@init.example")
    system = create_coating_system(api, system_code="SW-INIT")
    program = create_program(api, system["id"], program_code="QP-INIT", min_quality_history_score=400)

    qualification = enroll_qualification(api, applicator["id"], program["id"])

    assert qualification["status"] == "CANDIDATE", (
        "the initial state is not skipped even though all certify preconditions hold"
    )
    assert read_applicator(api, applicator["id"])["status"] == "REGISTERED", (
        "no auto-activation before certification"
    )

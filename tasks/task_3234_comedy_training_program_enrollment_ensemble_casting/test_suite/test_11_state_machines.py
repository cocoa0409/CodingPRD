"""Corner queue: state_machines — invalid transitions, terminal lockdown,
idempotency, side effects."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, create_term_draft, get_term,
    create_placement_evaluation_payload, reset_clock,
    setup_open_term_with_section, enroll_with_fresh_version, confirm_enrollment,
    drop_enrollment, create_venue_slot, create_ensemble_cast_payload,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]
CD = TEST_USERS["casting_director_headers"]


def test_term_close_from_draft_returns_invalid_state():
    """PRD §3.1: "Closing the term moves it `IN_SESSION → CLOSED` (the term's
    terminal state)"
    PRD §3.1: "A term in any state other than the one a transition starts from
    rejects that transition with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/term_close_from_draft_returns_invalid_state
    """
    reset_clock()
    term = create_term_draft()
    resp = api_client.close_term(term["id"], PD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_term(term["id"])["status"] == "DRAFT"


def test_enrollment_drop_terminal_dropped_early_lockdown():
    """PRD §3.3: "Dropping an enrollment in any other state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enrollment_drop_terminal_dropped_early_lockdown
    """
    ctx = setup_open_term_with_section(capacity=4)
    student = create_student()
    enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
    confirm_enrollment(enr["id"])
    drop_enrollment(enr["id"])  # DROPPED_EARLY (clock still before deadline)
    resp = api_client.drop_enrollment(enr["id"], REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_placement_evaluation_grant_idempotent_second_attempt_fails():
    """PRD §3.3: "A PlacementOfficer begins review (`SUBMITTED → UNDER_REVIEW`),
    then either grants or denies."
    PRD §2.7: "then whether the target entity's current state permits the requested
    transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/placement_evaluation_grant_idempotent_second_attempt_fails
    """
    reset_clock()
    create_level(code="L1", allows_placement_bypass=False)
    lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                        allows_placement_bypass=True)
    student = create_student()
    pe = validate_success(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(
            student["id"], lvl2["id"], prior_institution="UCB", portfolio_score=0), PO), 201)
    validate_success(api_client.begin_review_placement(pe["id"], PO))
    validate_success(api_client.grant_placement(pe["id"], PO))
    resp = api_client.grant_placement(pe["id"], PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_ensemble_cast_open_casting_side_effect():
    """PRD §3.8: "It is born `OPEN_ROLES` with empty `principal_ids` and
    `understudy_ids`. Opening casting moves it `OPEN_ROLES → CASTING`."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource."

    Design: Corner/state_machines/ensemble_cast_open_casting_side_effect
    """
    reset_clock()
    slot = create_venue_slot(venue_name="M")
    cast = validate_success(api_client.create_ensemble_cast(
        create_ensemble_cast_payload(slot["id"], cast_size=2, understudy_slots=1), CD), 201)
    updated = validate_success(api_client.open_casting(cast["id"], CD))
    assert updated["status"] == "CASTING"
    assert updated["version"] == 2

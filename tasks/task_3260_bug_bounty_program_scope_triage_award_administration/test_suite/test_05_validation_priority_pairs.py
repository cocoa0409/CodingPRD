"""Difficulty tests: validation priority pairs — deterministic error precedence."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    get_success_data,
    make_researcher_headers,
    validate_error,
)
from test_helpers.factories import create_report_payload
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_award,
    create_validated_report,
    get_award,
    register_researcher,
    setup_active_program,
)


def test_existence_beats_state_on_report_submit(api):
    """PRD §2.5: "When a single request violates several rules, the system reports
    exactly one error, chosen by a fixed priority ordering so that the failure a
    caller sees is deterministic."
    PRD §2.5: "5. **Body reference existence** — foreign-key references carried in
    the request body (such as `program_id`, `asset_id`, `researcher_id`,
    `report_id`, or `duplicate_of_id`) must resolve to existing resources, else
    `ERR_NOT_FOUND`."
    PRD §2.5: "7. **Program posture** — operations that require an `ACTIVE`
    program (report submission, invitation issuance) fail with
    `ERR_PROGRAM_NOT_ACTIVE` when the program is `DRAFT`, `PAUSED`, or `CLOSED`"

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_report_submit
    """
    program, asset = setup_active_program()
    get_success_data(api.pause_program(program["id"], PROGRAM_ADMIN))
    researcher = register_researcher()
    resp = api.create_report(
        create_report_payload(program["id"], NON_EXISTENT_UUID),
        make_researcher_headers(researcher["id"]),
    )
    # Both ERR_NOT_FOUND (missing asset) and ERR_PROGRAM_NOT_ACTIVE (paused) apply;
    # existence (priority 5) is evaluated first.
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_state_beats_sanction_safety_on_award_pay(api):
    """PRD §2.5: "When a single request violates several rules, the system reports
    exactly one error, chosen by a fixed priority ordering so that the failure a
    caller sees is deterministic."
    PRD §2.5: "6. **State-machine legality** — the target resource's state machine
    must permit the requested transition from its current state, else
    `ERR_INVALID_STATE` (HTTP 409)"
    PRD §2.5: "9. **Sanctions screening** — payment to a researcher resident in a
    sanctioned country is refused with `ERR_SANCTIONED_COUNTRY` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_sanction_safety_on_award_pay
    """
    program, asset = setup_active_program()
    researcher = register_researcher(country_code="KP")
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    award = create_award(report["id"], "BOUNTY")
    approve_award(award["id"])
    get_success_data(api.void_award(award["id"], PROGRAM_ADMIN))
    assert get_award(award["id"])["status"] == "VOID"
    resp = api.pay_award(award["id"], PLATFORM_ADMIN)
    # Both ERR_INVALID_STATE (VOID terminal) and ERR_SANCTIONED_COUNTRY apply;
    # state-machine legality (priority 6) is evaluated first.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_award(award["id"])["status"] == "VOID"


def test_existence_beats_state_404_status(api):
    """PRD §2.5: "4. **Path existence** — every resource identifier appearing in
    the URL path must exist, validated strictly left to right; the first missing
    identifier yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.5: "5. **Body reference existence** — foreign-key references carried in
    the request body (such as `program_id`, `asset_id`, `researcher_id`,
    `report_id`, or `duplicate_of_id`) must resolve to existing resources, else
    `ERR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_report_submit
    """
    program, asset = setup_active_program()
    get_success_data(api.pause_program(program["id"], PROGRAM_ADMIN))
    researcher = register_researcher()
    resp = api.create_report(
        create_report_payload(program["id"], NON_EXISTENT_UUID),
        make_researcher_headers(researcher["id"]),
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_state_beats_sanction_safety_409_status(api):
    """PRD §2.5: "6. **State-machine legality** — the target resource's state
    machine must permit the requested transition from its current state, else
    `ERR_INVALID_STATE` (HTTP 409); several specialized variants are named where
    they apply, including `ERR_AWARD_NOT_PAYABLE`, `ERR_REPORT_NOT_RESOLVED`,
    `ERR_REPORT_NOT_VALIDATED`, `ERR_NEGOTIATION_EXHAUSTED`, and
    `ERR_INVITATION_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_sanction_safety_on_award_pay
    """
    program, asset = setup_active_program()
    researcher = register_researcher(country_code="KP")
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    award = create_award(report["id"], "BOUNTY")
    approve_award(award["id"])
    get_success_data(api.void_award(award["id"], PROGRAM_ADMIN))
    resp = api.pay_award(award["id"], PLATFORM_ADMIN)
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

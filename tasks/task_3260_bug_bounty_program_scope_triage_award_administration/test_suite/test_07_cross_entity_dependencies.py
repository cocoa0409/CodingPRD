"""Difficulty tests: cross-entity state dependencies — program posture and report gates."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_remediation_ticket_payload, create_report_payload
from test_helpers.fixtures import (
    PROGRAM_ADMIN,
    TRIAGER,
    get_report,
    register_researcher,
    set_clock,
    setup_active_program,
    submit_report,
)


def test_report_submission_rejected_while_program_paused(api):
    """PRD §3.1: "Pausing moves `ACTIVE` to `PAUSED` and carries a standing side
    effect: while a program is `PAUSED`, new report submissions are rejected with
    `ERR_PROGRAM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/report_submission_gated_by_program_pause
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    first = submit_report(program, asset, researcher, title="ok")
    assert first["status"] == "NEW"
    get_success_data(api.pause_program(program["id"], PROGRAM_ADMIN))
    resp = api.create_report(
        create_report_payload(program["id"], asset["id"], title="blocked"),
        make_researcher_headers(researcher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)


def test_report_submission_restored_after_reactivation(api):
    """PRD §3.1: "Activation transitions the program from `DRAFT` to `ACTIVE`,
    and later from `PAUSED` back to `ACTIVE`; both directions require that at
    least one scope version be effective at the current logical time, and an
    activation attempt without one is rejected with `ERR_SCOPE_VERSION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/report_submission_gated_by_program_pause
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    get_success_data(api.pause_program(program["id"], PROGRAM_ADMIN))
    blocked = api.create_report(
        create_report_payload(program["id"], asset["id"], title="blocked"),
        make_researcher_headers(researcher["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
    get_success_data(api.activate_program(program["id"], PROGRAM_ADMIN))
    resp = api.create_report(
        create_report_payload(program["id"], asset["id"], title="after-reactivate"),
        make_researcher_headers(researcher["id"]),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


def test_ticket_creation_rejected_for_triaged_report(api):
    """PRD §3.8: "Once a report is `VALIDATED`, a `ProgramAdmin` opens a
    remediation ticket bridging into the customer's engineering tracker by
    supplying the `report_id` and an `external_ref` such as a JIRA key. Creating
    a ticket for a report in any other status is rejected with
    `ERR_REPORT_NOT_VALIDATED`"

    Design: Difficulty/cross_entity_state_dependency/ticket_creation_gated_by_report_validation
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    report = submit_report(program, asset, researcher)
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    resp = api.create_remediation_ticket(
        create_remediation_ticket_payload(report["id"]), PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_VALIDATED)


def test_ticket_creation_rejection_leaves_no_ticket(api):
    """PRD §3.8: "Once a report is `VALIDATED`, a `ProgramAdmin` opens a
    remediation ticket bridging into the customer's engineering tracker by
    supplying the `report_id` and an `external_ref` such as a JIRA key. Creating
    a ticket for a report in any other status is rejected with
    `ERR_REPORT_NOT_VALIDATED`"

    Design: Difficulty/cross_entity_state_dependency/ticket_creation_gated_by_report_validation
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    report = submit_report(program, asset, researcher)
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    resp = api.create_remediation_ticket(
        create_remediation_ticket_payload(report["id"]), PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_VALIDATED)
    listing = api.list_remediation_tickets(
        PROGRAM_ADMIN, params={"report_id": report["id"]})
    data, meta = validate_paginated(listing)
    assert data == []
    assert meta["total_count"] == 0

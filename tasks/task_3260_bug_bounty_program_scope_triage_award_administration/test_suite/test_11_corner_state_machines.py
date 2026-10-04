"""Corner tests (state_machines): invalid transitions, terminal lockdown, and
clock-sweep automatic transitions."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    create_validated_report,
    get_researcher,
    get_report,
    issue_invitation,
    register_researcher,
    resolve_report,
    set_clock,
    setup_active_program,
    submit_report,
)


def test_triage_on_validated_report_returns_invalid_state(api):
    """PRD §3.6: "The plain triage action moves a `NEW` report to `TRIAGED` ...
    Requesting more information moves `TRIAGED` to `NEEDS_INFO`"
    PRD §2.5: "6. **State-machine legality** — the target resource's state machine
    must permit the requested transition from its current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/triage_on_validated_report_returns_invalid_state
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=5, exploitability=5, affected_scope=5)
    assert report["status"] == "VALIDATED"
    resp = api.triage_report(report["id"], {"action": "REQUEST_INFO"}, TRIAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_report(report["id"])["status"] == "VALIDATED"


def test_respond_on_declined_invitation_returns_invalid_state(api):
    """PRD §3.4: "The invited researcher responds with a `decision` of `ACCEPT`
    or `DECLINE`, and only the invited researcher may respond. ... Decline moves
    it to `DECLINED`."
    PRD §2.5: "6. **State-machine legality** — the target resource's state machine
    must permit the requested transition from its current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/respond_on_declined_invitation_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    program, asset = setup_active_program(visibility="PRIVATE", criticality="MEDIUM")
    researcher = register_researcher()
    invitation = issue_invitation(program["id"], researcher["id"])
    get_success_data(api.respond_invitation(
        invitation["id"], {"decision": "DECLINE"},
        make_researcher_headers(researcher["id"])))
    resp = api.respond_invitation(
        invitation["id"], {"decision": "ACCEPT"},
        make_researcher_headers(researcher["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_invitation(invitation["id"], PROGRAM_ADMIN))
    assert after["status"] == "DECLINED"


def test_clock_sweep_expires_pending_invitation(api):
    """PRD §2.8: "Setting the clock triggers a sweep with three effects: every
    `PENDING` invitation whose `expires_at` is strictly in the past flips to
    `EXPIRED`"
    PRD §3.4: "answering an already-expired invitation, or one whose expiry has
    passed, is rejected with `ERR_INVITATION_EXPIRED`."

    Design: Corner/state_machines/clock_sweep_expires_pending_invitation
    """
    program, asset = setup_active_program(visibility="PRIVATE", criticality="MEDIUM")
    researcher = register_researcher()
    invitation = issue_invitation(program["id"], researcher["id"])
    assert invitation["status"] == "PENDING"
    set_clock("2026-09-09T00:00:00Z")  # past expires_at (2026-09-08T00:00:00Z)
    expired = get_success_data(api.get_invitation(invitation["id"], PROGRAM_ADMIN))
    assert expired["status"] == "EXPIRED"
    resp = api.respond_invitation(
        invitation["id"], {"decision": "ACCEPT"},
        make_researcher_headers(researcher["id"]))
    validate_error(resp, ApiErrorId.ERR_INVITATION_EXPIRED)


def test_clock_sweep_reinstates_suspended_researcher(api):
    """PRD §2.8: "every `SUSPENDED` researcher whose `suspension_ends_at` has
    been reached or passed returns to `ACTIVE` with `suspension_ends_at` cleared
    to null"
    PRD §3.3: "A `STRIKE` increments `strike_count` and applies −50; when the
    strike brings the unreversed strike count to exactly 2 the researcher is
    suspended"

    Design: Corner/state_machines/clock_sweep_reinstates_suspended_researcher
    """
    set_clock("2026-09-01T00:00:00Z")
    researcher = register_researcher()
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "one"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "two"}, TRIAGER))
    suspended = get_researcher(researcher["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_ends_at"] == "2026-09-29T00:00:00Z"
    set_clock("2026-09-29T00:00:00Z")  # inclusive: now >= suspension_ends_at
    reinstated = get_researcher(researcher["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_ends_at"] is None
    assert reinstated["strike_count"] == 2


def test_ticket_verify_rejected_after_report_marked_duplicate(api):
    """PRD §3.8: "The pivotal action is `VERIFY`, permitted only from `FIXED` and
    only while the linked report is still `VALIDATED` — verifying against a
    report in any other status fails with `ERR_INVALID_STATE`."
    PRD §3.6: "Duplicate marking moves a report from `NEW`, `TRIAGED`,
    `NEEDS_INFO`, or even `VALIDATED` into `DUPLICATE`."

    Design: Corner/state_machines/ticket_verify_rejected_after_report_marked_duplicate
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    anchor = create_validated_report(
        program, asset, researcher, impact=5, exploitability=5, affected_scope=5,
        vulnerability_class="XSS")
    dupe = create_validated_report(
        program, asset, researcher, impact=5, exploitability=5, affected_scope=5,
        vulnerability_class="XSS")
    ticket = get_success_data(api.create_remediation_ticket(
        {"report_id": dupe["id"], "external_ref": "ENG-5"}, PROGRAM_ADMIN))
    get_success_data(api.transition_remediation_ticket(
        ticket["id"], {"action": "START"}, PROGRAM_ADMIN))
    get_success_data(api.transition_remediation_ticket(
        ticket["id"], {"action": "FIX"}, PROGRAM_ADMIN))
    get_success_data(api.triage_report(
        dupe["id"], {"action": "MARK_DUPLICATE", "duplicate_of_id": anchor["id"]}, TRIAGER))
    resp = api.transition_remediation_ticket(
        ticket["id"], {"action": "VERIFY"}, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    ticket_after = get_success_data(
        api.get_remediation_ticket(ticket["id"], PROGRAM_ADMIN))
    assert ticket_after["status"] == "FIXED"
    assert get_report(dupe["id"])["status"] == "DUPLICATE"

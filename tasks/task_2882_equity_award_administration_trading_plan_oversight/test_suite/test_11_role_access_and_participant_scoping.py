"""Role gating, the read-only Auditor, the two-branch grant approval gate, and the
row-level scoping that isolates one participant from another.

Every test builds the world it needs from scratch through the public endpoints,
because the harness restarts the server and empties the database before each one.
"""

import pytest

from test_helpers import (
    ADMIN,
    AUDITOR,
    BOARD,
    COMPLIANCE,
    OFFICER,
    api_client,
    assert_burn_rate_summary,
    assert_transaction_report,
    create_authority,
    create_draft_grant,
    create_open_window,
    create_participant,
    create_plan,
    create_preclearance,
    decide_preclearance,
    execute_preclearance,
    make_compliance_headers,
    make_participant_headers,
    read_authority,
    read_grant,
    read_plan,
    read_report,
    set_clock,
    submit_grant,
    validate_error,
    validate_paginated,
    validate_success,
)


def _plan_and_participant(plan_name, employee_number):
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name=plan_name,
        total_authorized_shares=200_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name="Ravi Role",
        employee_number=employee_number,
        hire_date="2020-01-06",
        birth_date="1985-03-03",
    )
    return plan, participant


# ---------------------------------------------------------------------------
# The read-only Auditor
# ---------------------------------------------------------------------------

_AUDITOR_WRITES = [
    (
        "register_a_plan",
        lambda ctx: api_client.create_equity_plan(
            {
                "name": "Corner Auditor Attempt Plan",
                "total_authorized_shares": 100_000,
                "common_shares_outstanding": 1_000_000,
                "fiscal_year_start_date": "2026-01-01",
            },
            AUDITOR,
        ),
    ),
    (
        "freeze_a_plan",
        lambda ctx: api_client.set_equity_plan_status(
            ctx["plan_id"], {"action": "FREEZE", "freeze_reason": "Auditor attempt."}, AUDITOR
        ),
    ),
    (
        "draft_a_grant",
        lambda ctx: api_client.create_grant(
            {
                "plan_id": ctx["plan_id"],
                "participant_id": ctx["participant_id"],
                "award_type": "RSU",
                "target_shares": 1000,
            },
            AUDITOR,
        ),
    ),
    (
        "schedule_a_trading_window",
        lambda ctx: api_client.create_trading_window(
            {
                "plan_id": ctx["plan_id"],
                "quarter_label": "Q1-FY2026-AUD",
                "open_at": "2026-01-05T00:00:00Z",
                "close_at": "2026-03-31T00:00:00Z",
            },
            AUDITOR,
        ),
    ),
    (
        "move_the_logical_clock",
        lambda ctx: api_client.set_clock("2026-02-01T00:00:00Z", AUDITOR),
    ),
]


@pytest.mark.parametrize(
    "call",
    [row[1] for row in _AUDITOR_WRITES],
    ids=[row[0] for row in _AUDITOR_WRITES],
)
def test_auditor_writes_are_all_refused(call):
    """PRD §2.1: "The `Auditor` role is read-only in the strongest sense: it appears in the authorised-role list of every read endpoint and of no write endpoint, so every write attempt by an `Auditor` — including an attempt to move the logical clock — is refused with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/auditor_cannot_perform_any_write_operation
    """
    plan, participant = _plan_and_participant("Corner Auditor Plan", "E-C-490")

    validate_error(
        call({"plan_id": plan["id"], "participant_id": participant["id"]}),
        "ERR_ROLE_NOT_PERMITTED",
    )

    untouched = read_plan(plan["id"])
    assert untouched["status"] == "ACTIVE", (
        f"the refused write left the plan untouched, got {untouched['status']}"
    )
    assert untouched["version"] == 1, (
        f"the refused write did not advance the plan version, got {untouched['version']}"
    )


def test_auditor_reads_are_permitted_everywhere_the_role_is_listed():
    """PRD §2.1: "The `Auditor` role is read-only in the strongest sense: it appears in the authorised-role list of every read endpoint and of no write endpoint, so every write attempt by an `Auditor` — including an attempt to move the logical clock — is refused with `ERR_ROLE_NOT_PERMITTED`."

    PRD §2.1: "When the headers are well formed but the named role is not permitted to invoke the endpoint, the answer is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_perform_any_write_operation
    """
    plan, participant = _plan_and_participant("Corner Auditor Read Plan", "E-C-491")

    read_back = validate_success(api_client.get_equity_plan(plan["id"], AUDITOR), 200)
    assert read_back["id"] == plan["id"]
    assert read_back["available_reserve_shares"] == 200_000

    summary = validate_success(api_client.get_burn_rate_summary(plan["id"], AUDITOR), 200)
    assert_burn_rate_summary(summary, read_back)

    rows, meta = validate_paginated(api_client.list_participants(AUDITOR))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == participant["id"]


# ---------------------------------------------------------------------------
# Compliance owns the trading calendar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "headers", [ADMIN, BOARD, OFFICER, AUDITOR], ids=["admin", "board", "officer", "auditor"]
)
def test_only_compliance_may_schedule_a_trading_window(headers):
    """PRD §3.9: "The trading calendar belongs to compliance: only a `ComplianceOfficer` may schedule a window or drive its status."

    Design: Corner/rbac/compliance_officer_exclusively_administers_trading_windows
    """
    plan, _participant = _plan_and_participant("Corner Calendar Plan", "E-C-500")

    validate_error(
        api_client.create_trading_window(
            {
                "plan_id": plan["id"],
                "quarter_label": "Q1-FY2026-CAL",
                "open_at": "2026-01-05T00:00:00Z",
                "close_at": "2026-03-31T00:00:00Z",
            },
            headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    _windows, meta = validate_paginated(
        api_client.list_plan_trading_windows(plan["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 0, (
        f"the refused scheduling wrote no window row, got {meta['total_count']}"
    )


def test_only_compliance_may_drive_a_window_and_the_role_gate_precedes_existence():
    """PRD §3.9: "The trading calendar belongs to compliance: only a `ComplianceOfficer` may schedule a window or drive its status."

    PRD §2.6: "The role gate, yielding `ERR_ROLE_NOT_PERMITTED`. This runs **before** any path parameter is resolved, so a role that may not call an endpoint receives 403 even when the addressed row does not exist."

    Design: Corner/rbac/compliance_officer_exclusively_administers_trading_windows
    """
    plan, _participant = _plan_and_participant("Corner Drive Plan", "E-C-501")
    window = validate_success(
        api_client.create_trading_window(
            {
                "plan_id": plan["id"],
                "quarter_label": "Q1-FY2026-DRV",
                "open_at": "2026-01-05T00:00:00Z",
                "close_at": "2026-03-31T00:00:00Z",
            },
            COMPLIANCE,
        ),
        201,
    )
    assert window["status"] == "SCHEDULED"

    validate_error(
        api_client.set_trading_window_status(window["id"], {"action": "OPEN"}, ADMIN),
        "ERR_ROLE_NOT_PERMITTED",
    )
    validate_error(
        api_client.set_trading_window_status(
            "00000000-0000-0000-0000-0000000000ff", {"action": "OPEN"}, ADMIN
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    still_scheduled = validate_success(
        api_client.get_trading_window(window["id"], ADMIN), 200
    )
    assert still_scheduled["status"] == "SCHEDULED", (
        f"the refused action did not open the window, got {still_scheduled['status']}"
    )
    assert still_scheduled["version"] == 1

    opened = validate_success(
        api_client.set_trading_window_status(window["id"], {"action": "OPEN"}, COMPLIANCE), 200
    )
    assert opened["status"] == "OPEN", (
        f"compliance drives the same transition successfully, got {opened['status']}"
    )


# ---------------------------------------------------------------------------
# The two branches of grant approval
# ---------------------------------------------------------------------------

def _submitted_grant_with_delegation():
    plan, participant = _plan_and_participant("Corner Approval Path Plan", "E-C-510")
    authority = create_authority(
        plan["id"],
        delegate_user_id="officer-1",
        per_grant_share_cap=5000,
        aggregate_share_cap=10000,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    grant, _rows = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="NSO",
        target_shares=2000,
        exercise_price_cents=2500,
        tranches=[
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-01-05",
                "target_shares": 2000,
            }
        ],
    )
    submit_grant(grant["id"])
    return plan, authority, grant


def test_each_approval_role_owns_only_its_own_branch():
    """PRD §2.1: "One endpoint carries a second layer of role gating. Grant approval is open to both `BoardMember` and `DelegatedOfficer`, but the two roles own different branches of the same operation: the `BOARD` approval path is the `BoardMember` branch and the `DELEGATED` approval path is the `DelegatedOfficer` branch. A `DelegatedOfficer` selecting the board path, or a `BoardMember` selecting the delegated path, is refused with `ERR_ROLE_NOT_PERMITTED` before any fiscal or delegation check runs."

    Design: Corner/rbac/delegated_officer_cannot_use_the_board_approval_path
    """
    plan, authority, grant = _submitted_grant_with_delegation()

    validate_error(
        api_client.approve_grant(grant["id"], {"approval_path": "BOARD"}, OFFICER),
        "ERR_ROLE_NOT_PERMITTED",
    )
    validate_error(
        api_client.approve_grant(
            grant["id"], {"approval_path": "DELEGATED", "authority_id": authority["id"]}, BOARD
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    still_pending = read_grant(grant["id"])
    assert still_pending["status"] == "PENDING_APPROVAL", (
        f"neither refusal approved the grant, got {still_pending['status']}"
    )
    assert still_pending["approved_at"] is None
    assert still_pending["approval_path"] is None
    assert still_pending["weighted_reserve_shares"] == 0

    untouched_authority = read_authority(authority["id"])
    assert untouched_authority["consumed_shares"] == 0, (
        "the refusal ran before any delegation check, so nothing was consumed, got "
        f"{untouched_authority['consumed_shares']}"
    )
    assert untouched_authority["version"] == 1
    assert read_plan(plan["id"])["version"] == 1, (
        "the refusals left the plan version untouched"
    )

    approved = validate_success(
        api_client.approve_grant(
            grant["id"], {"approval_path": "DELEGATED", "authority_id": authority["id"]}, OFFICER
        ),
        200,
    )
    assert approved["status"] == "APPROVED", (
        f"the DelegatedOfficer branch succeeds on its own path, got {approved['status']}"
    )
    assert approved["approval_path"] == "DELEGATED"
    assert approved["approved_by_user_id"] == "officer-1"


def test_the_branch_role_gate_runs_before_the_delegation_check():
    """PRD §2.1: "A `DelegatedOfficer` selecting the board path, or a `BoardMember` selecting the delegated path, is refused with `ERR_ROLE_NOT_PERMITTED` before any fiscal or delegation check runs."

    PRD §3.4: "A `REVOKED`, `EXHAUSTED`, or `EXPIRED` delegation, one belonging to another plan, one delegated to a different officer, or an approval dated outside the term all yield `ERR_AUTHORITY_NOT_EFFECTIVE`."

    Design: Corner/rbac/delegated_officer_cannot_use_the_board_approval_path
    """
    _plan, authority, grant = _submitted_grant_with_delegation()
    validate_success(
        api_client.revoke_approval_authority(
            authority["id"], {"revocation_reason": "Delegation withdrawn."}, BOARD
        ),
        200,
    )

    validate_error(
        api_client.approve_grant(
            grant["id"], {"approval_path": "DELEGATED", "authority_id": authority["id"]}, BOARD
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    validate_error(
        api_client.approve_grant(
            grant["id"], {"approval_path": "DELEGATED", "authority_id": authority["id"]}, OFFICER
        ),
        "ERR_AUTHORITY_NOT_EFFECTIVE",
    )
    assert read_grant(grant["id"])["status"] == "PENDING_APPROVAL"


# ---------------------------------------------------------------------------
# Shared reads, exclusive writes
# ---------------------------------------------------------------------------

def test_a_grant_reads_the_same_for_every_authorised_role_but_only_admin_creates_one():
    """PRD §2.1: "When the headers are well formed but the named role is not permitted to invoke the endpoint, the answer is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.1: "A `Participant` may therefore reach their own participant record, their own grants, tranches, settlements, tax allocations, mobility assignments, preclearance requests, trading plans, and Section 16 reports, and nothing belonging to a colleague."

    Design: Corner/rbac/grant_read_is_shared_across_roles_while_creation_is_not
    """
    plan, participant = _plan_and_participant("Corner Shared Read Plan", "E-C-520")
    grant, _rows = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="RSU",
        target_shares=1000,
        tranches=[
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-01-05",
                "target_shares": 1000,
            }
        ],
    )

    bodies = []
    for headers in (ADMIN, BOARD, OFFICER, COMPLIANCE, AUDITOR,
                    make_participant_headers(participant["id"])):
        bodies.append(validate_success(api_client.get_grant(grant["id"], headers), 200))
    for body in bodies[1:]:
        assert body == bodies[0], (
            "every authorised role reads the identical grant row, and one of them "
            f"differs: {body} vs {bodies[0]}"
        )
    assert bodies[0]["id"] == grant["id"]
    assert bodies[0]["participant_id"] == participant["id"]

    for headers, label in ((BOARD, "BoardMember"), (AUDITOR, "Auditor"),
                           (make_participant_headers(participant["id"]), "Participant")):
        validate_error(
            api_client.create_grant(
                {
                    "plan_id": plan["id"],
                    "participant_id": participant["id"],
                    "award_type": "RSU",
                    "target_shares": 500,
                },
                headers,
            ),
            "ERR_ROLE_NOT_PERMITTED",
        )

    rows, meta = validate_paginated(
        api_client.list_grants(ADMIN, params={"plan_id": plan["id"]})
    )
    assert meta["total_count"] == 1, (
        f"no refused creation wrote a grant row, got {meta['total_count']}"
    )
    assert rows[0]["id"] == grant["id"]


# ---------------------------------------------------------------------------
# Row-level scoping between participants
# ---------------------------------------------------------------------------

def _two_insiders_and_one_report(executed_shares):
    """Two Section 16 officers, one of whom has executed a cleared trade and so owns a
    Section 16 report."""
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Scoping Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    window = create_open_window(
        plan["id"], open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z"
    )
    owner = create_participant(
        full_name="Olive Owner",
        employee_number="E-C-530",
        hire_date="2019-01-07",
        birth_date="1980-04-04",
        insider_status="SECTION_16_OFFICER",
    )
    sibling = create_participant(
        full_name="Sid Sibling",
        employee_number="E-C-531",
        hire_date="2019-01-08",
        birth_date="1981-05-05",
        insider_status="SECTION_16_OFFICER",
    )
    request = create_preclearance(
        owner["id"],
        window["id"],
        transaction_type="SELL",
        requested_shares=executed_shares,
        intended_trade_date="2026-01-09",
    )
    decide_preclearance(request["id"], "APPROVE")

    set_clock("2026-01-08T14:00:00Z")
    execute_preclearance(
        request["id"],
        executed_shares,
        4500,
        headers=make_participant_headers(owner["id"]),
    )

    rows, meta = validate_paginated(
        api_client.list_participant_transaction_reports(owner["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 1, (
        f"the execution created exactly one Section 16 report, got {meta['total_count']}"
    )
    return owner, sibling, request, rows[0]


def test_a_participant_cannot_reach_a_colleagues_section_16_reports():
    """PRD §2.1: "An attempt to reach a sibling participant's row returns `ERR_PARTICIPANT_SCOPE_VIOLATION` (HTTP 403) and never a 404, so the mere existence of the other row is not disclosed."

    PRD §2.1: "A `Participant` may therefore reach their own participant record, their own grants, tranches, settlements, tax allocations, mobility assignments, preclearance requests, trading plans, and Section 16 reports, and nothing belonging to a colleague."

    Design: Corner/rbac/participant_peer_isolation_on_transaction_reports
    """
    owner, sibling, request, report = _two_insiders_and_one_report(200)
    owner_headers = make_participant_headers(owner["id"])
    sibling_headers = make_participant_headers(sibling["id"])

    rows, meta = validate_paginated(
        api_client.list_participant_transaction_reports(owner["id"], owner_headers)
    )
    assert meta["total_count"] == 1, (
        f"the owner reads their own report list, got {meta['total_count']}"
    )
    assert_transaction_report(rows[0])
    assert rows[0]["form_type"] == "FORM_4", (
        f"a SECTION_16_OFFICER files on FORM_4, got {rows[0]['form_type']}"
    )
    assert rows[0]["shares"] == 200, f"shares equal executed_shares, got {rows[0]['shares']}"
    own_report = validate_success(
        api_client.get_transaction_report(report["id"], owner_headers), 200
    )
    assert own_report["id"] == report["id"]

    validate_error(
        api_client.list_participant_transaction_reports(owner["id"], sibling_headers),
        "ERR_PARTICIPANT_SCOPE_VIOLATION",
    )
    validate_error(
        api_client.get_transaction_report(report["id"], sibling_headers),
        "ERR_PARTICIPANT_SCOPE_VIOLATION",
    )
    validate_error(
        api_client.get_preclearance_request(request["id"], sibling_headers),
        "ERR_PARTICIPANT_SCOPE_VIOLATION",
    )
    validate_error(
        api_client.get_participant(owner["id"], sibling_headers),
        "ERR_PARTICIPANT_SCOPE_VIOLATION",
    )

    _rows, sibling_meta = validate_paginated(
        api_client.list_participant_transaction_reports(sibling["id"], sibling_headers)
    )
    assert sibling_meta["total_count"] == 0, (
        f"the sibling owns no report of their own, got {sibling_meta['total_count']}"
    )
    _rows, compliance_meta = validate_paginated(
        api_client.list_participant_transaction_reports(sibling["id"], COMPLIANCE)
    )
    assert compliance_meta["total_count"] == 0, (
        "compliance skips the scoping rule and still sees no report for the sibling, got "
        f"{compliance_meta['total_count']}"
    )


def test_an_insider_cannot_file_their_own_section_16_report():
    """PRD §3.9: "The filer must not be the reporting insider — when `X-User-ID` equals the report's `participant_id` the filing is refused with `ERR_SEGREGATION_OF_DUTIES`, so an insider cannot certify their own filing."

    PRD §3.9: "Only a `ComplianceOfficer` files, and only a report that is `PENDING`; a second filing attempt on a report already `FILED` or `LATE_FILED` is refused with `ERR_REPORT_INVALID_STATE`."

    PRD §3.9: "Filing stamps `filed_at` from the logical clock and then branches on a single millisecond-precision comparison from the same trigger: at or before `due_at` the report becomes `FILED`, and strictly after `due_at` it becomes `LATE_FILED`."

    Design: Corner/rbac/report_filing_segregation_of_duties_against_the_reporting_participant
    """
    owner, _sibling, _request, report = _two_insiders_and_one_report(250)

    assert report["status"] == "PENDING"
    assert report["participant_id"] == owner["id"]
    assert report["shares"] == 250

    validate_error(
        api_client.file_transaction_report(report["id"], make_compliance_headers(owner["id"])),
        "ERR_SEGREGATION_OF_DUTIES",
    )
    unfiled = read_report(report["id"])
    assert unfiled["status"] == "PENDING", (
        f"the refused self-filing left the report pending, got {unfiled['status']}"
    )
    assert unfiled["filed_at"] is None
    assert unfiled["version"] == 1

    validate_error(
        api_client.file_transaction_report(report["id"], make_participant_headers(owner["id"])),
        "ERR_ROLE_NOT_PERMITTED",
    )

    filed = validate_success(api_client.file_transaction_report(report["id"], COMPLIANCE), 200)
    assert filed["status"] == "FILED", (
        f"an independent compliance officer files the report, got {filed['status']}"
    )
    assert filed["version"] == 2

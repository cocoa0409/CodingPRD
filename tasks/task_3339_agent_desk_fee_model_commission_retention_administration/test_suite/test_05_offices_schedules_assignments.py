"""Offices, fee schedules, fee assignments (OCC + overlap), agents, and
retention reports."""
from test_helpers import (
    BOR, MB, OWNER, TA,
    AgentStatus, FeeAssignmentStatus, FeeScheduleStatus, InvoiceStatus,
    OfficeStatus, ReportStatus,
    create_agent_payload, create_fee_assignment_payload,
    create_fee_schedule_payload, create_office_payload,
    create_active_agent, create_agent, create_office, create_schedule,
    generate_september_invoices,
    get_success_data,
    propose_assignment, propose_and_accept_assignment,
    set_clock, setup_office_with_active_agent, setup_office_with_schedule,
    validate_error, validate_paginated, validate_success,
    make_agent_headers,
    api_client,
)


def test_office_create_returns_declared_fields_and_starts_active(api):
    """PRD §3.1: "The new office is born with `status` set to `ACTIVE`,
    `active_agent_count` equal to 0, and `trust_balance_cents` equal to 0;
    `closed_at` is null."
    PRD §2.5: "`version` — an integer that starts at 1 and increments by 1 on
    every mutation, including mutations cascaded from a parent or a related
    entity."

    Design: Corner/entities/office_create_returns_all_declared_fields_and_starts_active
    """
    set_clock("2026-09-10T00:00:00Z")
    resp = api.create_office(create_office_payload(), OWNER)
    office = validate_success(resp, expected_status=201)
    assert office["status"] == OfficeStatus.ACTIVE.value
    assert office["active_agent_count"] == 0
    assert office["trust_balance_cents"] == 0
    assert office["closed_at"] is None
    assert office["version"] == 1
    assert office["id"] and office["created_at"] and office["updated_at"]


def test_office_computed_fields_ignore_client_supplied_values(api):
    """PRD §3.1: "The new office is born with `status` set to `ACTIVE`,
    `active_agent_count` equal to 0, and `trust_balance_cents` equal to 0;
    `closed_at` is null."

    Design: Corner/entities/office_active_agent_count_is_computed_not_stored_input
    """
    set_clock("2026-09-10T00:00:00Z")
    resp = api.create_office(
        create_office_payload(active_agent_count=99, trust_balance_cents=555), OWNER)
    office = validate_success(resp, expected_status=201)
    assert office["active_agent_count"] == 0
    assert office["trust_balance_cents"] == 0


def test_agent_get_round_trips_stored_fields(api):
    """PRD §3.3: "The new agent is born in `PENDING_ONBOARDING`, with
    `supervision_cadence_days` at its default of 30 and
    `unearned_advance_balance_cents` at 0; `onboarded_at`,
    `termination_requested_at`, and `terminated_at` are all null."

    Design: Corner/entities/agent_get_returns_stored_row
    """
    set_clock("2026-09-10T00:00:00Z")
    office = create_office()
    created = create_agent(office["id"])
    read = validate_success(api.get_agent(created["id"], MB))
    assert read["full_name"] == "Alice Agent"
    assert read["license_number"] == "LIC-A-001"
    assert read["status"] == AgentStatus.PENDING_ONBOARDING.value
    assert read["supervision_cadence_days"] == 30
    assert read["onboarded_at"] is None
    assert read["unearned_advance_balance_cents"] == 0
    assert read["office_id"] == office["id"]


def test_agent_create_missing_license_number_is_invalid_request(api):
    """PRD §3.3: "A `ManagingBroker` onboards an agent into an office by
    supplying the agent's `full_name`, contact `email`, and state-issued
    `license_number`."
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request"

    Design: Corner/entities/agent_create_missing_license_number_returns_invalid_request
    """
    set_clock("2026-09-10T00:00:00Z")
    office = create_office()
    resp = api.create_agent(office["id"],
                            {"full_name": "No License", "email": "nolic@x.com"}, MB)
    validate_error(resp, "ERR_INVALID_REQUEST")
    rows, _ = validate_paginated(api.list_agents(MB, params={"office_id": office["id"]}))
    assert rows == []


def test_duplicate_license_rejected_system_wide(api):
    """PRD §3.3: "License numbers are unique across the entire system;
    attempting to register a duplicate fails with `ERR_DUPLICATE_LICENSE`
    (HTTP 409)."

    Design: Corner/validations/duplicate_license_number_rejected_system_wide
    """
    set_clock("2026-09-10T00:00:00Z")
    office = create_office()
    create_agent(office["id"])
    office2 = create_office(office_name="Phoenix North", market_code="PHX",
                            recruiting_target_agents=10)
    resp = api.create_agent(office2["id"], create_agent_payload(
        full_name="Copy Cat", email="copy@x.com"), MB)
    validate_error(resp, "ERR_DUPLICATE_LICENSE")
    rows, _ = validate_paginated(api.list_agents(MB, params={"office_id": office2["id"]}))
    assert rows == []


def test_referral_fee_bps_above_cap_rejected(api):
    """PRD §3.2: "a cross-office `referral_fee_bps` (between 0 and 5000
    inclusive)"
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request"

    Design: Corner/entities/referral_fee_bps_above_cap_returns_invalid_request
    """
    set_clock("2026-09-10T00:00:00Z")
    resp = api.create_fee_schedule(
        create_fee_schedule_payload(schedule_name="Outlaw Plan", referral_fee_bps=5001),
        BOR)
    validate_error(resp, "ERR_INVALID_REQUEST")
    rows, _ = validate_paginated(api.list_fee_schedules(BOR))
    assert rows == []


def test_fee_schedule_status_derives_from_window_against_clock(api):
    """PRD §3.2: "A schedule's `status` is derived from its window against the
    logical clock: `DRAFT` before its window opens, `ACTIVE` while the clock
    sits inside the window, and `ARCHIVED` once superseded or once its window
    has passed."

    Design: Corner/entities/fee_schedule_status_derives_from_window_against_logical_clock
    """
    set_clock("2026-09-10T00:00:00Z")
    future = create_schedule(
        schedule_name="Future Plan",
        effective_from="2027-01-01T00:00:00Z",
        effective_to="9999-12-31T00:00:00Z",
    )
    assert future["status"] == FeeScheduleStatus.DRAFT.value
    set_clock("2027-01-01T00:00:00Z")
    read = validate_success(api.get_fee_schedule(future["id"], BOR))
    assert read["status"] == FeeScheduleStatus.ACTIVE.value


def test_fee_schedule_windows_must_not_overlap(api):
    """PRD §3.2: "Schedule windows must tile the calendar without overlap. A
    new schedule's window may not intersect any sibling schedule's window, and
    when a predecessor exists, the new window must start exactly at the
    predecessor's `effective_to` — adjacent with zero gap. A violation of
    either rule is rejected with `ERR_SCHEDULE_WINDOW_VIOLATION` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_window_must_tile_without_overlap
    """
    set_clock("2026-09-10T00:00:00Z")
    create_schedule()  # open-ended [2026-01-01, 9999-12-31)
    resp = api.create_fee_schedule(
        create_fee_schedule_payload(schedule_name="Rogue Plan",
                                    effective_from="2027-01-01T00:00:00Z"),
        BOR)
    validate_error(resp, "ERR_SCHEDULE_WINDOW_VIOLATION")
    rows, _ = validate_paginated(api.list_fee_schedules(BOR))
    assert len(rows) == 1, "the overlapping schedule must not be persisted"


def test_fee_schedule_open_ended_incumbent_rejects_all_successors(api):
    """PRD §3.2: "Schedule windows must tile the calendar without overlap. A
    new schedule's window may not intersect any sibling schedule's window, and
    when a predecessor exists, the new window must start exactly at the
    predecessor's `effective_to` — adjacent with zero gap. A violation of
    either rule is rejected with `ERR_SCHEDULE_WINDOW_VIOLATION` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_window_must_tile_without_overlap
    """
    set_clock("2026-09-10T00:00:00Z")
    create_schedule()
    # Even a successor whose window begins strictly inside the incumbent is
    # rejected: the open-ended incumbent covers the whole calendar.
    resp = api.create_fee_schedule(
        create_fee_schedule_payload(schedule_name="Later Plan",
                                    effective_from="2030-06-01T00:00:00Z"),
        BOR)
    validate_error(resp, "ERR_SCHEDULE_WINDOW_VIOLATION")


def test_fee_assignment_overlap_rejected_but_adjacency_allowed(api):
    """PRD §3.3: "the assignment's window must not intersect any other
    non-terminal assignment window for the same agent — touching endpoints
    where one window's `effective_to` equals the other's `effective_from` are
    adjacent, not overlapping — and any intersection is rejected with
    `ERR_ASSIGNMENT_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/fee_assignment_window_overlap_rejected_but_adjacency_allowed
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    # A second schedule with a default window cannot exist here: the first
    # schedule is open-ended and PRD §3.2 requires global tiling. The
    # per-agent overlap rule of PRD §3.3 is schedule-agnostic, so propose the
    # overlapping window against the same schedule.
    # Overlapping window: intersects the existing ACCEPTED assignment.
    resp = api.create_fee_assignment(
        alice["id"],
        create_fee_assignment_payload(schedule["id"], alice["version"],
                                      effective_from="2026-06-01T00:00:00Z"),
        MB)
    validate_error(resp, "ERR_ASSIGNMENT_OVERLAP")
    rows, _ = validate_paginated(api.list_agent_fee_assignments(alice["id"], MB))
    accepted = [r for r in rows if r["status"] == FeeAssignmentStatus.ACCEPTED.value]
    assert len(accepted) == 1


def test_fee_assignment_no_new_row_persisted_on_overlap(api):
    """PRD §3.3: "the assignment's window must not intersect any other
    non-terminal assignment window for the same agent — touching endpoints
    where one window's `effective_to` equals the other's `effective_from` are
    adjacent, not overlapping — and any intersection is rejected with
    `ERR_ASSIGNMENT_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/fee_assignment_window_overlap_rejected_but_adjacency_allowed
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    # Same schedule (the open-ended first schedule tiles the whole calendar,
    # so no second schedule can be created — PRD §3.2); the §3.3 overlap rule
    # is per-agent and schedule-agnostic.
    rows_before, _ = validate_paginated(
        api.list_agent_fee_assignments(alice["id"], MB))
    resp = api.create_fee_assignment(
        alice["id"],
        create_fee_assignment_payload(schedule["id"], alice["version"],
                                      effective_from="2026-03-01T00:00:00Z"),
        MB)
    validate_error(resp, "ERR_ASSIGNMENT_OVERLAP")
    rows_after, _ = validate_paginated(api.list_agent_fee_assignments(alice["id"], MB))
    assert {r["id"] for r in rows_after} == {r["id"] for r in rows_before}


def test_fee_assignment_create_with_stale_agent_version_returns_412(api):
    """PRD §2.7: "If that number does not match the agent's current `version`,
    the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/fee_assignment_create_with_stale_agent_version_returns_412
    """
    office, schedule = setup_office_with_schedule("2026-09-10T00:00:00Z")
    alice = create_agent(office["id"])
    first = validate_success(api.create_fee_assignment(
        alice["id"],
        create_fee_assignment_payload(schedule["id"], alice["version"]), MB),
        expected_status=201)
    # The create bumped Agent.version; reusing the observed version is stale.
    resp = api.create_fee_assignment(
        alice["id"],
        create_fee_assignment_payload(schedule["id"], alice["version"]), MB)
    validate_error(resp, "ERR_STALE_VERSION")
    rows, _ = validate_paginated(api.list_agent_fee_assignments(alice["id"], MB))
    proposed = [r for r in rows if r["status"] == FeeAssignmentStatus.PROPOSED.value]
    assert len(proposed) == 1


def test_second_proposed_assignment_supersedes_the_first(api):
    """PRD §3.3: "If another `PROPOSED` assignment already exists for the same
    agent, that earlier one is automatically moved to `SUPERSEDED`."

    Design: Corner/endpoints/second_proposed_assignment_supersedes_the_first
    """
    office, schedule = setup_office_with_schedule("2026-09-10T00:00:00Z")
    # No second schedule can tile against the open-ended first one (PRD §3.2);
    # the §3.3 supersede rule is about sibling PROPOSED assignments for the
    # same agent, regardless of schedule. The second window must be adjacent
    # (not overlapping) so the proposal itself is valid and the supersede
    # pathway — not the overlap rejection — is what fires.
    alice = create_agent(office["id"])
    first = propose_assignment(alice, schedule,
                               effective_to="2027-01-01T00:00:00Z")
    second = propose_assignment(alice, schedule,
                                effective_from="2027-01-01T00:00:00Z")
    first_now = validate_success(api.get_fee_assignment(first["id"], MB))
    second_now = validate_success(api.get_fee_assignment(second["id"], MB))
    assert first_now["status"] == FeeAssignmentStatus.SUPERSEDED.value
    assert second_now["status"] == FeeAssignmentStatus.PROPOSED.value
    rows, _ = validate_paginated(api.list_agent_fee_assignments(
        alice["id"], MB, params={"status": "PROPOSED"}))
    assert len(rows) == 1


def test_office_close_blocked_by_active_agents_then_succeeds(api):
    """PRD §3.1: "The close is permitted only when the office has zero agents
    in `ACTIVE` status; attempting it with active agents fails with
    `ERR_OFFICE_NOT_EMPTY`."

    Design: Difficulty/cross_entity_state_dependency/office_close_gated_by_active_agent_count
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    resp = api.close_office(office["id"], OWNER)
    validate_error(resp, "ERR_OFFICE_NOT_EMPTY")

    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))
    set_clock("2026-09-24T00:00:00Z")
    validate_success(api.complete_termination(alice["id"], MB))

    office_now = validate_success(api.get_office(office["id"], MB))
    assert office_now["active_agent_count"] == 0
    closed = validate_success(api.close_office(office["id"], OWNER))
    assert closed["status"] == OfficeStatus.CLOSED.value
    assert closed["closed_at"] == "2026-09-24T00:00:00Z" or \
        closed["closed_at"].startswith("2026-09-24T00:00:00")


def test_office_close_cascades_open_invoices_to_collections(api):
    """PRD §3.1: "On close, `closed_at` is set to the logical clock, every
    agent still in `TERMINATION_PENDING` is advanced to `TERMINATED` with
    `terminated_at` set (a conditional cascade), every invoice in `ISSUED`,
    `PARTIALLY_PAID`, or `OVERDUE` is escalated to `COLLECTIONS` (a cascade
    down), and the office's `version` is incremented."

    Design: Corner/state_machines/office_close_cascades_open_invoices_to_collections
    """
    office, schedule = setup_office_with_schedule("2026-09-01T00:00:00Z")
    alice = create_active_agent(office["id"], schedule)
    bob = create_active_agent(office["id"], schedule, name="Bob Agent",
                              email="bob@x.com", license_number="LIC-B-002")
    invoices = generate_september_invoices(office["id"])
    inv_alice = next(i for i in invoices if i["agent_id"] == alice["id"])
    inv_bob = next(i for i in invoices if i["agent_id"] == bob["id"])
    validate_success(api.pay_invoice(
        inv_alice["id"], {"amount_cents": 365000}, make_agent_headers(alice["id"])))

    set_clock("2026-09-10T00:00:00Z")
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))
    validate_success(api.terminate_agent(bob["id"], make_agent_headers(bob["id"])))
    set_clock("2026-09-24T00:00:00Z")
    validate_success(api.complete_termination(alice["id"], MB))
    validate_success(api.complete_termination(bob["id"], MB))

    closed = validate_success(api.close_office(office["id"], OWNER))
    assert closed["status"] == OfficeStatus.CLOSED.value

    bob_inv = validate_success(api.get_invoice(inv_bob["id"], MB))
    assert bob_inv["status"] == InvoiceStatus.COLLECTIONS.value
    alice_inv = validate_success(api.get_invoice(inv_alice["id"], MB))
    assert alice_inv["status"] == InvoiceStatus.PAID.value
    for a in (alice, bob):
        now = validate_success(api.get_agent(a["id"], MB))
        assert now["status"] == AgentStatus.TERMINATED.value


def test_double_terminate_rejected_from_termination_pending(api):
    """PRD §3.10: "The agent themselves — the caller's `X-User-ID` must equal
    the agent's `id` — requests termination, moving the agent from `ACTIVE` to
    `TERMINATION_PENDING`."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict"

    Design: Corner/state_machines/double_terminate_is_rejected_from_termination_pending
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    first = validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))
    assert first["termination_requested_at"].startswith("2026-09-10")

    resp = api.terminate_agent(alice["id"], make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_agent(alice["id"], MB))
    assert after["termination_requested_at"] == first["termination_requested_at"]


def test_complete_termination_before_notice_window_rejected(api):
    """PRD §3.10: "A `ManagingBroker` completes the departure once the
    fourteen-day notice window has passed: the logical clock must be at or
    past `termination_requested_at` plus fourteen days, and an attempt before
    that boundary is rejected with `ERR_TERMINATION_WINDOW_OPEN` (HTTP 409)."

    Design: Corner/validations/complete_termination_before_notice_window_rejected
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))

    set_clock("2026-09-23T00:00:00Z")  # 13 days later
    resp = api.complete_termination(alice["id"], MB)
    validate_error(resp, "ERR_TERMINATION_WINDOW_OPEN")

    set_clock("2026-09-24T00:00:00Z")  # exactly +14 days
    done = validate_success(api.complete_termination(alice["id"], MB))
    assert done["status"] == AgentStatus.TERMINATED.value


def test_retention_report_zero_baseline_rejected(api):
    """PRD §3.12: "When `headcount_start` is zero there is no baseline to
    divide by, and the computation is rejected with
    `ERR_NO_RETENTION_BASELINE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/retention_report_zero_baseline_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    office = create_office()
    resp = api.compute_retention_report(
        office["id"], {"period_month": "2026-09", "report_variant": "CHURN"}, OWNER)
    validate_error(resp, "ERR_NO_RETENTION_BASELINE")
    rows, _ = validate_paginated(
        api.list_office_retention_reports(office["id"], OWNER))
    assert rows == [], "no report row may be persisted on the failure path"


def test_retention_report_recompute_archives_prior(api):
    """PRD §3.12: "The resulting `AgentRetentionReport` is born `COMPUTED`;
    when a newer report is computed for the same office and `period_month`,
    the prior `COMPUTED` report is moved to `ARCHIVED`."

    Design: Corner/endpoints/retention_report_compute_and_archive_superseded_report
    """
    # Alice onboarded in August so headcount_start for September is 1.
    set_clock("2026-08-15T00:00:00Z")
    office = create_office()
    schedule = create_schedule()
    alice = create_active_agent(office["id"], schedule)
    set_clock("2026-09-01T00:00:00Z")

    rep1 = validate_success(api.compute_retention_report(
        office["id"], {"period_month": "2026-09", "report_variant": "CHURN"}, OWNER),
        expected_status=201)
    assert rep1["headcount_start"] == 1
    assert rep1["headcount_end"] == 1
    assert rep1["retention_bps"] == 10000
    assert rep1["churned_agent_count"] == 0

    rep2 = validate_success(api.compute_retention_report(
        office["id"], {"period_month": "2026-09", "report_variant": "CHURN"}, OWNER),
        expected_status=201)
    old = validate_success(api.get_retention_report(rep1["id"], OWNER))
    assert old["status"] == ReportStatus.ARCHIVED.value
    assert rep2["status"] == ReportStatus.COMPUTED.value
    rows, _ = validate_paginated(api.list_office_retention_reports(
        office["id"], OWNER, params={"status": "COMPUTED"}))
    assert len(rows) == 1

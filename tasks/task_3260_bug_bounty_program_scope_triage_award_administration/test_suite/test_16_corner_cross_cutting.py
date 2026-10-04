"""Corner tests (cross-cutting complexity layers + consistency): OCC conflicts,
sanctions gate, suspension gate, and logical-clock immediate consistency."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_report_payload
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_award,
    create_program,
    create_validated_report,
    get_award,
    get_program,
    get_report,
    get_researcher,
    register_researcher,
    setup_active_program,
    submit_report,
)


def test_program_patch_stale_version_occ_conflict(api):
    """PRD §2.7: "A request to update a program must carry
    `expected_program_version`, a non-optional input field holding the `version`
    of the program as the client last observed it. If the program's current
    `version` does not match `expected_program_version` — because another writer
    has advanced it since the client's last read — the update is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting
    program configuration it has not observed."

    Design: Corner/cross_cutting_complexity_layers/program_patch_stale_version_occ_conflict
    """
    program = create_program()
    observed_version = program["version"]  # 1
    first = api.patch_program(
        program["id"],
        {"expected_program_version": observed_version, "response_sla_hours": 48},
        PROGRAM_ADMIN,
    )
    assert first.status_code == 200, f"Expected 200, got {first.status_code}: {first.text}"
    first_data = get_success_data(first)
    assert first_data["response_sla_hours"] == 48
    assert first_data["version"] == 2
    stale = api.patch_program(
        program["id"],
        {"expected_program_version": observed_version, "response_sla_hours": 24},
        PROGRAM_ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412
    # Stale write did not take effect
    assert get_program(program["id"])["response_sla_hours"] == 48


def test_sanctioned_country_pay_blocked_no_recovery(api):
    """PRD §3.9: "Sanctions come first: a researcher whose `country_code` is one
    of KP, IR, CU, or SY cannot be paid; the attempt returns
    `ERR_SANCTIONED_COUNTRY` and moves the award from `APPROVED` to `BLOCKED`
    with `block_reason` set to `SANCTIONED_COUNTRY`, retaining the pool
    reservation."
    PRD §3.9: "There is no cure path for a sanctions block."

    Design: Corner/cross_cutting_complexity_layers/sanctioned_country_pay_blocked_no_recovery
    """
    program, asset = setup_active_program()
    researcher = register_researcher(country_code="KP")
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    award = create_award(report["id"], "BOUNTY")
    assert award["amount_cents"] == 2_200_000
    approve_award(award["id"])
    first = api.pay_award(award["id"], PLATFORM_ADMIN)
    validate_error(first, ApiErrorId.ERR_SANCTIONED_COUNTRY)
    blocked = get_award(award["id"])
    assert blocked["status"] == "BLOCKED"
    assert blocked["block_reason"] == "SANCTIONED_COUNTRY"
    retry = api.pay_award(award["id"], PLATFORM_ADMIN)
    validate_error(retry, ApiErrorId.ERR_SANCTIONED_COUNTRY)
    # Reservation retained throughout
    assert get_program(program["id"])["bounty_reserved_cents"] == 2_200_000


def test_suspended_researcher_cannot_submit_reports(api):
    """PRD §2.5: "8. **Researcher standing** — a `SUSPENDED` researcher may not
    submit reports (`ERR_RESEARCHER_SUSPENDED`, HTTP 403); a `BANNED` researcher
    may not submit reports, provide info, or receive new invitations
    (`ERR_RESEARCHER_BANNED`, HTTP 403)."
    PRD §3.3: "A `STRIKE` increments `strike_count` and applies −50; when the
    strike brings the unreversed strike count to exactly 2 the researcher is
    suspended"

    Design: Corner/cross_cutting_complexity_layers/suspended_researcher_cannot_submit_reports
    """
    program, asset = setup_active_program(criticality="HIGH")
    researcher = register_researcher()
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "one"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "two"}, TRIAGER))
    assert get_researcher(researcher["id"])["status"] == "SUSPENDED"
    resp = api.create_report(
        create_report_payload(program["id"], asset["id"]),
        make_researcher_headers(researcher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESEARCHER_SUSPENDED)


def test_report_read_reflects_logical_clock_immediately(api):
    """PRD §2.8: "All time-sensitive behavior in the system reads a server-side
    logical clock, never wall-clock time. The clock starts at exactly
    2026-09-01T00:00:00Z before any call is made, and it advances only when a
    `PlatformAdmin` sets it to a supplied `to_iso8601` instant via the
    test-driving clock capability; it never falls back to wall-clock."
    PRD §3.5: "The system stamps `submitted_at` from the logical clock and pins
    `scope_version_id` to the scope version whose half-open window contains the
    submission instant"
    PRD §3.5: "Intake then computes `response_due_at` as `submitted_at` plus the
    program's `response_sla_hours`."

    Design: Corner/consistency_model/report_read_reflects_logical_clock_immediately
    """
    # Clock never set: default 2026-09-01T00:00:00Z
    program, asset = setup_active_program(criticality="HIGH")
    researcher = register_researcher()
    create_resp = api.create_report(
        create_report_payload(program["id"], asset["id"]),
        make_researcher_headers(researcher["id"]),
    )
    created = validate_success(create_resp, expected_status=201)
    assert created["status"] == "NEW"
    assert created["submitted_at"] == "2026-09-01T00:00:00Z"
    assert created["response_due_at"] == "2026-09-04T00:00:00Z"
    read = get_report(created["id"])
    assert read["status"] == "NEW"
    assert read["submitted_at"] == "2026-09-01T00:00:00Z"
    assert read["response_due_at"] == "2026-09-04T00:00:00Z"

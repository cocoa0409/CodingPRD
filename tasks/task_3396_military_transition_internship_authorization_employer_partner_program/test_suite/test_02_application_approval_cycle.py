"""The program application: submission snapshot, commander decision, and the
bounded appeal cycle under segregation of duties."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    assert_instant,
    factories,
    fixtures,
    make_service_member_headers,
    make_unit_commander_headers,
)
from test_helpers.test_users import PROGRAM_OFFICE_HEADERS


def test_application_initial_state(api):
    """PRD §3.2: "A created application starts in `SUBMITTED` with `submitted_at`
    stamped from the logical clock, a `days_until_separation_at_submission` snapshot
    preserved for the audit trail, `installation_id` copied from the member's
    `home_installation_id` so the governing policy survives later member edits,
    `appeal_count` at 0, and `appeal_deadline` still null."

    Design: Corner/state_machines/application_initial_state
    """
    inst = fixtures.create_installation(api)
    member = fixtures.create_member(api, inst["id"])
    app = fixtures.submit_application(api, member["id"])
    assert app["status"] == "SUBMITTED"
    assert app["appeal_count"] == 0
    assert app["appeal_deadline"] is None
    assert app["decided_by_user_id"] is None
    # Separation 2027-01-15 is 136 whole days after the default clock 2026-09-01.
    assert app["days_until_separation_at_submission"] == 136
    assert app["installation_id"] == inst["id"]
    assert_instant(app["submitted_at"], "2026-09-01T00:00:00Z", "submitted_at")


def test_commander_decision_twice_rejected(api):
    """PRD §3.2: "The application must currently be `SUBMITTED`, otherwise
    `ERR_APPLICATION_NOT_SUBMITTED`."

    Design: Corner/state_machines/commander_decision_on_decided_application_rejected
    """
    w = fixtures.setup_member_with_application(api, approve=True)
    second = api.commander_decision(
        w.application["id"],
        factories.commander_decision_payload("DENY", "second thoughts"),
        make_unit_commander_headers("cmd-2"),
    )
    validate_error(second, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED)
    after = fixtures.get_application(api, w.application["id"])
    assert after["status"] == "APPROVED"
    assert after["decided_by_user_id"] == "cmd-1", "the recorded decision must not be overwritten"


def test_deny_requires_reason(api):
    """PRD §3.2: "On DENY the `reason` is mandatory and its absence is
    `ERR_VALIDATION`."
    PRD §3.2: "DENY moves it to `DENIED` and computes `appeal_deadline` as
    `decided_at` plus the installation's `appeal_window_days` days."

    Design: Corner/validations/deny_requires_reason
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    app_id = w.application["id"]

    missing = api.commander_decision(
        app_id, {"decision": "DENY"}, make_unit_commander_headers("cmd-1")
    )
    validate_error(missing, ApiErrorId.ERR_VALIDATION)
    assert fixtures.get_application(api, app_id)["status"] == "SUBMITTED"

    denied = fixtures.deny_application(api, app_id, reason="Manning requirements through Q1")
    assert denied["status"] == "DENIED"
    assert denied["decided_by_user_id"] == "cmd-1"
    # Decided at the default clock 2026-09-01 plus the 14-day appeal window.
    assert_instant(denied["appeal_deadline"], "2026-09-15T00:00:00Z", "appeal_deadline")


def test_pay_grade_excluded(api):
    """PRD §3.2: "The member's `pay_grade` must not appear in the home
    installation's `excluded_pay_grades`, else `ERR_PAY_GRADE_EXCLUDED`."

    Design: Corner/validations/pay_grade_excluded
    """
    inst = fixtures.create_installation(api, excluded_pay_grades=["E1", "E2"])
    member = fixtures.create_member(api, inst["id"], full_name="Junior Enlisted", pay_grade="E1")
    resp = api.create_application(
        factories.create_application_payload(member["id"]),
        make_service_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PAY_GRADE_EXCLUDED)
    data, meta = validate_paginated(
        api.list_applications(PROGRAM_OFFICE_HEADERS, params={"service_member_id": member["id"]})
    )
    assert data == [] and meta["total_count"] == 0


def test_second_live_application_rejected(api):
    """PRD §3.2: "The member may hold at most one live application at a time, where
    every status in `SUBMITTED`, `UNDER_APPEAL`, `APPROVED`, and `DENIED` counts as
    live; a second submission while one is live fails with
    `ERR_ACTIVE_APPLICATION_EXISTS`."

    Design: Corner/validations/second_active_application_rejected
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    resp = api.create_application(
        factories.create_application_payload(w.member["id"]),
        make_service_member_headers(w.member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_APPLICATION_EXISTS)
    data, meta = validate_paginated(
        api.list_applications(PROGRAM_OFFICE_HEADERS, params={"service_member_id": w.member["id"]})
    )
    assert len(data) == 1 and meta["total_count"] == 1
    assert data[0]["id"] == w.application["id"]


def test_tap_gate_conditional_on_installation_policy(api):
    """PRD §3.2: "A conditional TAP gate applies identically to both outcomes: when
    the governing installation's `requires_tap_complete` is true, the member's
    `tap_stage` must already be `CAPSTONE_DONE`, or the decision is rejected with
    `ERR_TAP_INCOMPLETE`."

    Design: Corner/validations/tap_gate_conditional_on_installation_policy
    """
    inst = fixtures.create_installation(
        api,
        name="Camp Lejeune",
        command_code="MCIEAST",
        region_code="R2",
        max_internship_duration_days=90,
        appeal_window_days=7,
        requires_tap_complete=True,
    )
    member = fixtures.create_member(api, inst["id"], service_branch="MARINES")
    app = fixtures.submit_application(api, member["id"])

    gated = api.commander_decision(
        app["id"], factories.commander_decision_payload("APPROVE"), make_unit_commander_headers("cmd-1")
    )
    validate_error(gated, ApiErrorId.ERR_TAP_INCOMPLETE)

    for stage in ("PRESEPARATION_COUNSELING_DONE", "CORE_CURRICULUM_DONE", "CAPSTONE_DONE"):
        fixtures.tap_advance(api, member["id"], stage)

    approved = fixtures.approve_application(api, app["id"])
    assert approved["status"] == "APPROVED"


def test_appeal_state_gates(api):
    """PRD §3.2: "Appealing requires the application to be `DENIED`
    (`ERR_APPLICATION_NOT_DENIED`), the logical clock to be on or before
    `appeal_deadline` (`ERR_APPEAL_WINDOW_EXPIRED`), and `appeal_count` to still be
    below the appeal budget of `MAX_APPEALS_PER_APPLICATION`, which is 2
    (`ERR_MAX_APPEALS_REACHED`); the window check precedes the count check."
    PRD §3.2: "The application must be `UNDER_APPEAL`, otherwise
    `ERR_NO_PENDING_APPEAL`, and segregation of duties forbids the adjudicator's
    `X-User-ID` from equaling the application's current `decided_by_user_id` — a
    commander never judges their own denial — else `ERR_APPEAL_ADJUDICATOR_CONFLICT`."

    Design: Corner/state_machines/appeal_state_gates
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    app_id = w.application["id"]

    premature = api.appeal_application(
        app_id, factories.appeal_payload("premature"), make_service_member_headers(w.member["id"])
    )
    validate_error(premature, ApiErrorId.ERR_APPLICATION_NOT_DENIED)

    no_pending = api.adjudicate_appeal(
        app_id,
        factories.adjudicate_payload("UPHELD", "nothing pending"),
        fixtures.make_installation_authority_headers("auth-1"),
    )
    validate_error(no_pending, ApiErrorId.ERR_NO_PENDING_APPEAL)


def test_appeal_window_expiry(api):
    """PRD §3.2: "Appealing requires the application to be `DENIED`
    (`ERR_APPLICATION_NOT_DENIED`), the logical clock to be on or before
    `appeal_deadline` (`ERR_APPEAL_WINDOW_EXPIRED`), and `appeal_count` to still be
    below the appeal budget of `MAX_APPEALS_PER_APPLICATION`, which is 2
    (`ERR_MAX_APPEALS_REACHED`); the window check precedes the count check."

    Denied at the default clock 2026-09-01 with a 14-day window, the deadline is
    2026-09-15; one day later the appeal is expired.

    Design: Corner/validations/appeal_window_expiry
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    fixtures.deny_application(api, w.application["id"], reason="Manning")
    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    resp = api.appeal_application(
        w.application["id"], factories.appeal_payload("too late"),
        make_service_member_headers(w.member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)


def test_appeal_adjudicator_segregation_enforced(api):
    """PRD §3.2: "The application must be `UNDER_APPEAL`, otherwise
    `ERR_NO_PENDING_APPEAL`, and segregation of duties forbids the adjudicator's
    `X-User-ID` from equaling the application's current `decided_by_user_id` — a
    commander never judges their own denial — else `ERR_APPEAL_ADJUDICATOR_CONFLICT`."
    PRD §3.2: "OVERTURNED moves the application to `APPROVED`; UPHELD returns it to
    `DENIED` and recomputes `appeal_deadline` from the new `decided_at` plus
    `appeal_window_days`."

    Design: Corner/rbac/appeal_adjudicator_segregation_enforced
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    app_id = w.application["id"]
    fixtures.deny_application(api, app_id, reason="Manning", commander_id="cmd-1")
    fixtures.appeal_application(api, app_id, w.member["id"], "request reconsideration")

    conflict = api.adjudicate_appeal(
        app_id,
        factories.adjudicate_payload("UPHELD", "self-review"),
        fixtures.make_installation_authority_headers("cmd-1"),
    )
    validate_error(conflict, ApiErrorId.ERR_APPEAL_ADJUDICATOR_CONFLICT)
    assert fixtures.get_application(api, app_id)["status"] == "UNDER_APPEAL"

    overturned = fixtures.adjudicate_appeal(
        api, app_id, "OVERTURNED", authority_id="auth-2", reason="independent review finds eligibility"
    )
    assert overturned["status"] == "APPROVED"
    assert overturned["decided_by_user_id"] == "auth-2"


def _walk_two_appeal_cycles(api):
    """Deny, appeal, uphold; appeal, uphold — the cycle edge traversed twice."""
    w = fixtures.setup_member_with_application(api, approve=False)
    app_id = w.application["id"]
    denied1 = fixtures.deny_application(api, app_id, reason="Manning requirements", commander_id="cmd-1")
    appeal1 = fixtures.appeal_application(api, app_id, w.member["id"], "New evidence")
    upheld1 = fixtures.adjudicate_appeal(api, app_id, "UPHELD", authority_id="auth-1", reason="Reviewed, denial stands")
    appeal2 = fixtures.appeal_application(api, app_id, w.member["id"], "Second appeal")
    upheld2 = fixtures.adjudicate_appeal(api, app_id, "UPHELD", authority_id="auth-2", reason="Final review")
    return w, app_id, denied1, appeal1, upheld1, appeal2, upheld2


def test_appeal_cycle_traverses_twice(api):
    """PRD §3.2: "The cycle edge from `DENIED` through `UNDER_APPEAL` back to
    `DENIED` may repeat while appeals remain; once `appeal_count` reaches 2, the
    appeal path itself refuses further filings and the denial stands."
    PRD §3.2: "UPHELD returns it to `DENIED` and recomputes `appeal_deadline` from
    the new `decided_at` plus `appeal_window_days`."

    Design: Difficulty/non_linear_state_machine/application_appeal_cycle_exhaustion
    """
    _, app_id, denied1, appeal1, upheld1, appeal2, upheld2 = _walk_two_appeal_cycles(api)
    assert denied1["status"] == "DENIED"
    assert_instant(denied1["appeal_deadline"], "2026-09-15T00:00:00Z", "first appeal_deadline")
    assert appeal1["status"] == "UNDER_APPEAL" and appeal1["appeal_count"] == 1
    assert upheld1["status"] == "DENIED", "cycle edge traversed once (auth-1 != denier cmd-1)"
    assert appeal2["status"] == "UNDER_APPEAL" and appeal2["appeal_count"] == 2
    assert upheld2["status"] == "DENIED", "cycle edge traversed twice (auth-2 != auth-1)"
    assert_instant(upheld2["appeal_deadline"], "2026-09-15T00:00:00Z", "recomputed appeal_deadline")


def test_third_appeal_rejected_budget_exhausted(api):
    """PRD §3.2: "Appealing requires the application to be `DENIED`
    (`ERR_APPLICATION_NOT_DENIED`), the logical clock to be on or before
    `appeal_deadline` (`ERR_APPEAL_WINDOW_EXPIRED`), and `appeal_count` to still be
    below the appeal budget of `MAX_APPEALS_PER_APPLICATION`, which is 2
    (`ERR_MAX_APPEALS_REACHED`); the window check precedes the count check."

    Design: Difficulty/non_linear_state_machine/application_appeal_cycle_exhaustion
    """
    w, app_id, *_ = _walk_two_appeal_cycles(api)
    third = api.appeal_application(
        app_id, factories.appeal_payload("Third attempt"),
        make_service_member_headers(w.member["id"]),
    )
    validate_error(third, ApiErrorId.ERR_MAX_APPEALS_REACHED)
    after = fixtures.get_application(api, app_id)
    assert after["status"] == "DENIED"
    assert after["appeal_count"] == 2

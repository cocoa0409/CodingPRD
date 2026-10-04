"""Difficulty tests: boundary precision — SLA breach deadline and reputation threshold."""
from test_helpers import ApiErrorId, get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    create_validated_report,
    get_researcher,
    get_report,
    register_researcher,
    resolve_report,
    set_clock,
    setup_active_program,
    submit_report,
)


def test_sla_response_breach_at_exact_deadline_not_breached(api):
    """PRD §3.5: "`response_breached` is true when no first response has been
    recorded and the logical now is strictly later than `response_due_at`, or when
    the recorded `first_response_at` is strictly later than the deadline; at the
    exact deadline instant the report is not breached."

    Design: Difficulty/boundary_precision_check/sla_response_breach_at_exact_deadline
    """
    program, asset = setup_active_program(response_sla_hours=72)
    researcher = register_researcher()
    report = submit_report(program, asset, researcher)
    assert report["response_due_at"] == "2026-09-04T00:00:00Z"
    set_clock("2026-09-04T00:00:00Z")
    at_deadline = get_report(report["id"])
    assert at_deadline["response_due_at"] == "2026-09-04T00:00:00Z"
    assert at_deadline["response_breached"] is False


def test_sla_response_breach_one_second_past_deadline(api):
    """PRD §3.5: "`response_breached` is true when no first response has been
    recorded and the logical now is strictly later than `response_due_at`, or when
    the recorded `first_response_at` is strictly later than the deadline; at the
    exact deadline instant the report is not breached."

    Design: Difficulty/boundary_precision_check/sla_response_breach_at_exact_deadline
    """
    program, asset = setup_active_program(response_sla_hours=72)
    researcher = register_researcher()
    report = submit_report(program, asset, researcher)
    set_clock("2026-09-04T00:00:01Z")
    past_deadline = get_report(report["id"])
    assert past_deadline["response_breached"] is True


def _researcher_at_reputation_150(program, asset):
    """Researcher whose lifetime is exactly 150: 100 + 50 (HIGH resolution)."""
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=8, exploitability=7, affected_scope=6,
        vulnerability_class="RCE")
    resolve_report(report["id"])
    return researcher


def test_invitation_min_reputation_exact_boundary_passes(api):
    """PRD §3.4: "requires the researcher's `reputation_lifetime` to be at least
    the program's `min_reputation`, where equality passes and only a strictly
    lower reputation is rejected with `ERR_REPUTATION_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/invitation_min_reputation_exact_boundary
    """
    program, asset = setup_active_program(min_reputation=150)
    researcher = _researcher_at_reputation_150(program, asset)
    assert get_researcher(researcher["id"])["reputation_lifetime"] == 150
    resp = api.create_invitation(
        {"program_id": program["id"], "researcher_id": researcher["id"]}, PROGRAM_ADMIN)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


def test_invitation_min_reputation_one_below_boundary_rejected(api):
    """PRD §3.4: "requires the researcher's `reputation_lifetime` to be at least
    the program's `min_reputation`, where equality passes and only a strictly
    lower reputation is rejected with `ERR_REPUTATION_TOO_LOW`."
    PRD §3.3: "A `WARNING` simply applies its −5."

    Design: Difficulty/boundary_precision_check/invitation_min_reputation_exact_boundary
    """
    program, asset = setup_active_program(min_reputation=150)
    researcher = _researcher_at_reputation_150(program, asset)
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "WARNING", "reason": "minor ToS lapse"}, TRIAGER))
    refreshed = get_researcher(researcher["id"])
    assert refreshed["reputation_lifetime"] == 145
    resp = api.create_invitation(
        {"program_id": program["id"], "researcher_id": researcher["id"]}, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPUTATION_TOO_LOW)

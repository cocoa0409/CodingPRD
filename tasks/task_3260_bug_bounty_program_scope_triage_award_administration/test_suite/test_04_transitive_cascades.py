"""Difficulty tests: transitive cascades — ticket VERIFY and conduct-strike chains."""
import pytest

from test_helpers import get_success_data, validate_success
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
)


def test_ticket_verify_cascades_report_resolution(api):
    """PRD §2.9: "Verifying a remediation ticket cascades outward in three hops:
    first the associated report moves from `VALIDATED` to `RESOLVED` with
    `resolved_at` stamped; second the researcher's reputation receives a delta
    sized by the report's final severity; third the researcher's tier is
    recomputed from the refreshed rolling reputation."

    Design: Difficulty/transitive_cascade/ticket_verify_cascades_report_resolve_and_tier_crossing
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    rep1 = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    assert rep1["severity_final"] == "CRITICAL"
    resolve_report(rep1["id"])  # +100 -> 200
    rep2 = create_validated_report(
        program, asset, researcher, impact=8, exploitability=7, affected_scope=6,
        vulnerability_class="SQLI")
    # base = 0.5*8+0.3*7+0.2*6 = 7.3; adjusted 7.3*1.2 = 8.76 -> 8.8 HIGH
    assert rep2["severity_final"] == "HIGH"
    rep2_resolved, ticket2 = resolve_report(rep2["id"])  # +50 -> 250
    assert ticket2["status"] == "VERIFIED"
    assert rep2_resolved["status"] == "RESOLVED"
    assert rep2_resolved["resolved_at"] == "2026-09-01T00:00:00Z"


def test_ticket_verify_cascade_reputation_and_tier_crossing(api):
    """PRD §3.8: "the researcher's reputation is credited by final severity (100
    for `CRITICAL`, 50 for `HIGH`, 20 for `MEDIUM`, 5 for `LOW`, 0 for `NONE`,
    applied to both lifetime and rolling figures), and the researcher's `tier` is
    recomputed."
    PRD §3.3: "`reputation_rolling180` ... drives the researcher's `tier`, which is
    `ELITE` when the rolling figure is at least 500, `ESTABLISHED` when it is at
    least 250 but below 500, and `NOVICE` otherwise, with both thresholds
    inclusive."

    Design: Difficulty/transitive_cascade/ticket_verify_cascades_report_resolve_and_tier_crossing
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    rep1 = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    resolve_report(rep1["id"])  # +100 -> lifetime 200, tier still NOVICE
    mid = get_researcher(researcher["id"])
    assert mid["reputation_lifetime"] == 200
    assert mid["tier"] == "NOVICE"
    rep2 = create_validated_report(
        program, asset, researcher, impact=8, exploitability=7, affected_scope=6,
        vulnerability_class="SQLI")
    resolve_report(rep2["id"])  # +50 -> 250, crosses the ESTABLISHED threshold
    final = get_researcher(researcher["id"])
    assert final["reputation_lifetime"] == 250
    assert final["reputation_rolling180"] == 250
    assert final["tier"] == "ESTABLISHED"


def test_conduct_second_strike_suspends_researcher(api):
    """PRD §3.3: "A `STRIKE` increments `strike_count` and applies −50; when the
    strike brings the unreversed strike count to exactly 2 the researcher is
    suspended, and when it reaches 3 or more the researcher is banned. Suspension
    sets `suspension_ends_at` to the strike time plus 14 days multiplied by the
    current `strike_count`"
    PRD §3.3: "and both suspension and banning cascade to decline every `PENDING`
    invitation the researcher holds."

    Design: Difficulty/transitive_cascade/conduct_strike_cascades_suspension_and_invitation_decline
    """
    program, asset = setup_active_program(visibility="PRIVATE", criticality="MEDIUM")
    researcher = register_researcher()
    invitation = issue_invitation(program["id"], researcher["id"])
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "scope violation"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "repeated scope violation"}, TRIAGER))
    refreshed = get_researcher(researcher["id"])
    assert refreshed["status"] == "SUSPENDED"
    assert refreshed["strike_count"] == 2
    assert refreshed["suspension_ends_at"] == "2026-09-29T00:00:00Z"  # 14 days * 2
    assert refreshed["reputation_lifetime"] == 0  # max(0, 100 - 50 - 50)


def test_conduct_second_strike_declines_pending_invitations(api):
    """PRD §2.9: "Conduct enforcement cascades differently: suspending or banning
    a researcher flips every `PENDING` invitation of that researcher to
    `DECLINED`, and closing a program does the same for every `PENDING` invitation
    of that program."

    Design: Difficulty/transitive_cascade/conduct_strike_cascades_suspension_and_invitation_decline
    """
    program, asset = setup_active_program(visibility="PRIVATE", criticality="MEDIUM")
    researcher = register_researcher()
    invitation = issue_invitation(program["id"], researcher["id"])
    assert invitation["status"] == "PENDING"
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "one"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "two"}, TRIAGER))
    invitation_after = get_success_data(
        api.get_invitation(invitation["id"], PROGRAM_ADMIN))
    assert invitation_after["status"] == "DECLINED"

"""Abuse reports: priority scoring, forwarding policy, reconsideration loop."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, make_partial_active_zone, zone_headers,
    reset_clock, drift_zone_to_moved, make_abuse_report, make_reviewing_report,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST_SAFETY = TEST_USERS["trust_safety_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Corner/calculations/abuse_trust_priority_category_base_plus_trust
# ---------------------------------------------------------------------------

def test_abuse_trust_priority_category_base_plus_trust(api):
    """PRD section 3.10: "The priority_score is the category's base weight plus
    the reporter trust score, exact integer addition with no normalization: CSAM
    weighs 1000, PHISHING 800, MALWARE 700, COPYRIGHT 500, SPAM 300, and OTHER
    100."

    Design: Corner/calculations/abuse_trust_priority_category_base_plus_trust
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="prio.example.com")
    r1 = make_abuse_report(
        zone, reporter_email="r1@example.org", category="PHISHING",
        description="d1", target_url="https://prio.example.com/a",
        reporter_trust_score=45,
    )
    r2 = make_abuse_report(
        zone, reporter_email="r2@example.org", category="CSAM",
        description="d2", target_url="https://prio.example.com/b",
        reporter_trust_score=72,
    )
    assert r1["priority_score"] == 845, "800 + 45"
    assert r2["priority_score"] == 1072, "1000 + 72"


# ---------------------------------------------------------------------------
# Corner/validations/abuse_routing_violation_on_proxied_take_action
# ---------------------------------------------------------------------------

def test_abuse_routing_violation_on_proxied_take_action(api):
    """PRD section 3.10: "A take-action disposition moves the report REVIEWING →
    ACTION_TAKEN — but only for HOSTED-routing reports; attempting direct
    enforcement on a PROXIED report violates the forwarding policy and is
    rejected with ERR_ABUSE_ROUTING_VIOLATION."

    Design: Corner/validations/abuse_routing_violation_on_proxied_take_action
    """
    acc = make_account(plan_tier="PRO")
    zone = make_partial_active_zone(
        acc, domain="proxied.example.com",
    )
    report = make_reviewing_report(
        zone, reporter_email="r@example.org", category="MALWARE",
        description="d", target_url="https://proxied.example.com/m",
        reporter_trust_score=50,
    )
    resp = api.disposition_abuse_report(
        report["id"], {"disposition": "TAKE_ACTION"}, TRUST_SAFETY
    )
    err = validate_error(resp, ApiErrorId.ERR_ABUSE_ROUTING_VIOLATION)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_ABUSE_ROUTING_VIOLATION"
    # forwarding the same report honors the proxied forwarding policy
    ok = api.disposition_abuse_report(
        report["id"], {"disposition": "FORWARD"}, TRUST_SAFETY
    )
    data = validate_success(ok)
    assert data["status"] == "FORWARDED"
    assert data["forwarded_to"] == zone["origin_host_email"], (
        "for a PROXIED report the destination is the zone's origin_host_email"
    )


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/abuse_forward_gated_by_zone_state
# ---------------------------------------------------------------------------

def _drifted_report_setup():
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_partial_active_zone(acc, domain="xdep.example.com")
    report = make_reviewing_report(
        zone, reporter_email="r@example.org", category="MALWARE",
        description="d", target_url="https://xdep.example.com/m",
        reporter_trust_score=50,
    )
    drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    return acc, zone, report


def test_abuse_forward_gated_by_zone_state(api):
    """PRD section 3.10: "From REVIEWING the analyst dispositions it by
    submitting a disposition of FORWARD or TAKE_ACTION, both directions
    requiring the zone to still be ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/abuse_forward_gated_by_zone_state
    """
    acc, zone, report = _drifted_report_setup()
    resp = api.disposition_abuse_report(
        report["id"], {"disposition": "FORWARD"}, TRUST_SAFETY
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_INVALID_STATE"


def test_rejected_forward_leaves_report_reviewing(api):
    """PRD section 3.10: "forwarded_to and forwarded_at remain null until
    disposition." A rejected disposition is no disposition.

    Design: Difficulty/cross_entity_state_dependency/abuse_forward_gated_by_zone_state
    """
    acc, zone, report = _drifted_report_setup()
    resp = api.disposition_abuse_report(
        report["id"], {"disposition": "FORWARD"}, TRUST_SAFETY
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_abuse_report(report["id"], TRUST_SAFETY))
    assert after["status"] == "REVIEWING"
    assert after["forwarded_to"] is None
    assert after["forwarded_at"] is None


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/abuse_report_reconsideration_loop
# ---------------------------------------------------------------------------

def test_abuse_report_reconsideration_loop_reaches_closed(api):
    """PRD section 3.10: "The platform also supports a reconsideration loop: an
    ACTION_TAKEN report can be walked back into REVIEWING by claiming it again —
    from there it may be re-acted, forwarded, or closed. Every claim,
    disposition, and close increments the report's version by 1."

    Design: Difficulty/non_linear_state_machine/abuse_report_reconsideration_loop
    """
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone(acc, domain="loop.example.com")
    report = make_abuse_report(
        zone, reporter_email="victim@example.org", category="PHISHING",
        description="phishing kit",
        target_url="https://loop.example.com/login",
        reporter_trust_score=45,
    )
    v0 = report["version"]
    get_success_data(api.claim_abuse_report(report["id"], TRUST_SAFETY))
    get_success_data(api.disposition_abuse_report(
        report["id"], {"disposition": "TAKE_ACTION"}, TRUST_SAFETY
    ))
    # reconsider: ACTION_TAKEN -> REVIEWING
    reopened = get_success_data(
        api.claim_abuse_report(report["id"], TRUST_SAFETY)
    )
    assert reopened["status"] == "REVIEWING"
    # re-act
    reacted = get_success_data(api.disposition_abuse_report(
        report["id"], {"disposition": "TAKE_ACTION"}, TRUST_SAFETY
    ))
    assert reacted["status"] == "ACTION_TAKEN"
    closed = get_success_data(api.close_abuse_report(report["id"], TRUST_SAFETY))
    assert closed["status"] == "CLOSED"
    assert closed["resolved_at"] is not None
    assert closed["version"] == v0 + 5, (
        "claim + action + claim + action + close each increment version by 1"
    )


def test_reconsidered_report_never_forwarded_keeps_null_stamps(api):
    """PRD section 3.10: "forwarded_to and forwarded_at remain null until
    disposition." A report that loops REVIEWING -> ACTION_TAKEN -> REVIEWING ->
    ACTION_TAKEN -> CLOSED never passes through FORWARDED.

    Design: Difficulty/non_linear_state_machine/abuse_report_reconsideration_loop
    """
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone(acc, domain="loop2.example.com")
    report = make_abuse_report(zone, reporter_email="victim@example.org")
    get_success_data(api.claim_abuse_report(report["id"], TRUST_SAFETY))
    get_success_data(api.disposition_abuse_report(
        report["id"], {"disposition": "TAKE_ACTION"}, TRUST_SAFETY
    ))
    get_success_data(api.claim_abuse_report(report["id"], TRUST_SAFETY))
    get_success_data(api.disposition_abuse_report(
        report["id"], {"disposition": "TAKE_ACTION"}, TRUST_SAFETY
    ))
    closed = get_success_data(api.close_abuse_report(report["id"], TRUST_SAFETY))
    assert closed["forwarded_at"] is None
    assert closed["forwarded_to"] is None

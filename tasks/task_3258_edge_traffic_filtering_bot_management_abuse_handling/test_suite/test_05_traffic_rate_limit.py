"""Traffic hits, rolling-window rate limits, and mitigation freeze."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, zone_headers, get_zone,
    reset_clock, set_clock, make_active_zone_with_rate_limit,
    make_activated_ddos_event, firewall_rule,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST_SAFETY = TEST_USERS["trust_safety_headers"]

CLIENT_IP = "198.51.100.20"


def _hits_setup():
    """PRO account, ACTIVE zone, RATE_LIMIT rule threshold 3 action BLOCK."""
    reset_clock()
    set_clock("2026-09-01T09:00:00Z")
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone_with_rate_limit(
        acc, domain="boundary.example.com", threshold_rpm=3
    )
    # one hit 62 seconds before the crossing hit (excluded from its window)
    get_success_data(api_client.record_traffic_hit(
        zone["id"],
        {"occurred_at": "2026-09-01T09:00:00Z", "client_ip": CLIENT_IP},
        zone_headers(acc),
    ))
    return acc, zone


def _hit(api, zone, acc, occurred_at):
    return api.record_traffic_hit(
        zone["id"],
        {"occurred_at": occurred_at, "client_ip": CLIENT_IP},
        zone_headers(acc),
    )


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/rate_limit_threshold_exact_count
# ---------------------------------------------------------------------------

def test_rate_limit_below_threshold_hits_do_not_trigger(api):
    """PRD section 3.5: "the window is the closed interval starting 59 seconds
    before occurred_at and ending at occurred_at, so a hit exactly 60 seconds
    older than the current hit is excluded. When the count of the rule's logged
    hits inside that window reaches the rule's rate_limit_threshold_rpm, the
    rule triggers."

    Design: Difficulty/boundary_precision_check/rate_limit_threshold_exact_count
    """
    acc, zone = _hits_setup()
    h1 = validate_success(_hit(api, zone, acc, "2026-09-01T09:01:00Z"),
                          expected_status=201)
    h2 = validate_success(_hit(api, zone, acc, "2026-09-01T09:01:01Z"),
                          expected_status=201)
    assert h1["triggered_rule_names"] == [], (
        "window count 1 is below threshold 3"
    )
    assert h2["triggered_rule_names"] == [], (
        "window count 2 is below threshold 3"
    )


def test_rate_limit_third_hit_in_window_triggers(api):
    """PRD section 3.5: "When the count of the rule's logged hits inside that
    window reaches the rule's rate_limit_threshold_rpm, the rule triggers — and
    only the threshold-crossing hit reports triggered true in the response."

    Design: Difficulty/boundary_precision_check/rate_limit_threshold_exact_count
    """
    acc, zone = _hits_setup()
    _hit(api, zone, acc, "2026-09-01T09:01:00Z")
    _hit(api, zone, acc, "2026-09-01T09:01:01Z")
    h3 = validate_success(_hit(api, zone, acc, "2026-09-01T09:01:02Z"),
                          expected_status=201)
    assert h3["triggered_rule_names"] == ["rl1"], (
        "the 09:00:00Z hit is 62 seconds older than the crossing hit and is "
        "excluded; the window holds exactly 3 hits and triggers"
    )


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/rate_limit_trigger_creates_provisional_block
# ---------------------------------------------------------------------------

def _triggering_setup():
    reset_clock()
    set_clock("2026-09-01T10:00:00Z")
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone_with_rate_limit(
        acc, domain="ratelimit.example.com", threshold_rpm=3
    )
    headers = zone_headers(acc)
    for second in ("01", "02"):
        get_success_data(api_client.record_traffic_hit(
            zone["id"],
            {"occurred_at": f"2026-09-01T10:00:{second}Z",
             "client_ip": "198.51.100.99"},
            headers,
        ))
    resp = api_client.record_traffic_hit(
        zone["id"],
        {"occurred_at": "2026-09-01T10:00:03Z", "client_ip": "198.51.100.99"},
        headers,
    )
    return acc, zone, resp


def test_threshold_crossing_hit_creates_provisional_block(api):
    """PRD section 3.5: "When a triggering rule's action is BLOCK and no live
    block exists for that client_ip on the zone ... the platform creates a
    PROVISIONAL IP block for the address."

    Design: Difficulty/transitive_cascade/rate_limit_trigger_creates_provisional_block
    """
    acc, zone, resp = _triggering_setup()
    data = validate_success(resp, expected_status=201)
    assert data["triggered_rule_names"] == ["rl1"]
    block_id = data["blocked_ip_block_id"]
    assert block_id, "the crossing hit must name the new provisional block"
    block = validate_success(api.get_ip_block(block_id, TRUST_SAFETY))
    assert block["status"] == "PROVISIONAL"
    assert block["ip"] == "198.51.100.99"
    assert block["zone_id"] == zone["id"]


def test_cascade_created_block_rejects_manual_duplicate(api):
    """PRD section 3.9: "Within a zone, the same ip may not be held by more than
    one live (non-released, non-expired) block; a duplicate live block is
    ERR_DUPLICATE_RESOURCE."

    Design: Difficulty/transitive_cascade/rate_limit_trigger_creates_provisional_block
    """
    acc, zone, resp = _triggering_setup()
    validate_success(resp, expected_status=201)
    dup = api.create_ip_block(
        {"zone_id": zone["id"], "ip": "198.51.100.99", "ip_version": "V4",
         "reason": "manual duplicate"},
        TRUST_SAFETY,
    )
    err = validate_error(dup, ApiErrorId.ERR_DUPLICATE_RESOURCE)
    assert err["error_id"] == "ERR_DUPLICATE_RESOURCE"


# ---------------------------------------------------------------------------
# Corner/errors/mitigation_active_freezes_rule_changes
# ---------------------------------------------------------------------------

def test_mitigation_active_freezes_rule_changes(api):
    """PRD section 3.5: "the same code rejects any zone patch that replaces
    traffic_rules while mitigation is active, and both stay frozen until every
    ACTIVATED DDoS event of the zone has ended."

    Design: Corner/errors/mitigation_active_freezes_rule_changes
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="freeze.example.com")
    make_activated_ddos_event(zone, acc, observed_rps=9000, baseline_rps=100)
    resp = api.patch_zone(
        zone["id"],
        {"traffic_rules": [firewall_rule("r1", "(true)", "ALLOW")]},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_MITIGATION_ACTIVE)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_MITIGATION_ACTIVE"
    # after the 4-hour TTL the freeze lifts
    set_clock("2026-09-01T04:00:00Z")
    ok = api.patch_zone(
        zone["id"],
        {"traffic_rules": [firewall_rule("r1", "(true)", "ALLOW")]},
        zone_headers(acc),
    )
    data = validate_success(ok)
    assert data["traffic_rules"][0]["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/clock_advances_ddos_auto_expiry
# ---------------------------------------------------------------------------

def test_clock_advances_ddos_auto_expiry_and_unfreezes_hits(api):
    """PRD section 3.7: "When the logical clock reaches an event's expires_at
    the event transitions ACTIVATED → ENDED, its version increments, and the
    zone's dos_mitigation_active recomputes — it becomes false only when no
    other event of that zone remains ACTIVATED."

    Design: Corner/cross_cutting_layers/clock_advances_ddos_auto_expiry
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="ttl.example.com")
    zone = get_success_data(api.patch_zone(
        zone["id"],
        {"traffic_rules": [
            {"name": "rl", "rule_kind": "RATE_LIMIT",
             "expression": "(p contains /x)", "action": "BLOCK",
             "rate_limit_threshold_rpm": 2, "status": "ACTIVE"},
        ]},
        zone_headers(acc),
    ))
    make_activated_ddos_event(zone, acc, observed_rps=8000, baseline_rps=100)
    # one second before expiry the zone is still frozen
    frozen = api.record_traffic_hit(
        zone["id"],
        {"occurred_at": "2026-09-01T03:59:59Z", "client_ip": "198.51.100.60"},
        zone_headers(acc),
    )
    err = validate_error(frozen, ApiErrorId.ERR_MITIGATION_ACTIVE)
    assert err["error_id"] == "ERR_MITIGATION_ACTIVE"
    # the clock reaching expires_at ends the event
    set_clock("2026-09-01T04:00:00Z")
    events, _meta = validate_paginated(
        api.list_ddos_events(ADMIN, params={"zone_id": zone["id"]})
    )
    assert events[0]["status"] == "ENDED"
    assert get_zone(zone["id"])["dos_mitigation_active"] is False
    # hits are accepted again; window count 1 is below threshold 2
    after = validate_success(api.record_traffic_hit(
        zone["id"],
        {"occurred_at": "2026-09-01T04:00:01Z", "client_ip": "198.51.100.60"},
        zone_headers(acc),
    ), expected_status=201)
    assert after["triggered_rule_names"] == []

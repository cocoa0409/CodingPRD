"""Delegation drift: the ACTIVE -> MOVED cascade and its consequences."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, zone_headers, get_zone,
    reset_clock, drift_zone_to_moved, patch_zone,
    firewall_rule, bot_band, dns_record,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Corner/state_machines/drift_cascade_disables_rules_and_bands
# ---------------------------------------------------------------------------

def test_drift_cascade_disables_rules_and_bands(api):
    """PRD section 2.9: "When an ACTIVE zone's delegation check fails —
    described fully in section 3.3 — the zone transitions ACTIVE → MOVED, and
    the transition cascades through every enforcement layer in one atomic
    reconciliation: every traffic rule whose status is ACTIVE flips to DISABLED;
    every bot score band whose status is ACTIVE flips to DISABLED."

    Design: Corner/state_machines/drift_cascade_disables_rules_and_bands
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="casc2.example.com")
    patch_zone(zone, acc, {
        "traffic_rules": [firewall_rule("r1", "(e1)", "BLOCK")],
        "bot_action_bands": [bot_band("b1", "CHALLENGE", 30, 60)],
    })
    moved = drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    assert moved["status"] == "MOVED"
    assert moved["traffic_rules"][0]["status"] == "DISABLED"
    assert moved["bot_action_bands"][0]["status"] == "DISABLED"


# ---------------------------------------------------------------------------
# Corner/consistency_model/immediate_consistency_of_cascade_side_effects
# ---------------------------------------------------------------------------

def test_immediate_consistency_of_cascade_side_effects(api):
    """PRD section 2.9: "the transition cascades through every enforcement layer
    in one atomic reconciliation: every traffic rule whose status is ACTIVE
    flips to DISABLED." PRD section 3.3: "Delegation is re-checked periodically
    as the logical clock advances."

    Design: Corner/consistency_model/immediate_consistency_of_cascade_side_effects
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="imm.example.com")
    patch_zone(zone, acc, {
        "traffic_rules": [
            firewall_rule("r1", "(p contains /a)", "BLOCK"),
            firewall_rule("r2", "(p contains /b)", "ALLOW"),
        ],
    })
    # records lose all proxied entries, then the clock advance re-checks
    patch_zone(zone, acc, {"dns_records": [
        dns_record(name="www", content="192.0.2.21", proxied=False)
    ]})
    from test_helpers import set_clock
    set_clock("2026-09-01T00:01:00Z")
    # the very next read shows the cascade complete
    after = get_zone(zone["id"])
    assert after["status"] == "MOVED"
    assert all(r["status"] == "DISABLED" for r in after["traffic_rules"]), (
        "both rules must already be DISABLED on the same read"
    )


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/delegation_drift_disables_rules_then_blocks_new_rules
# ---------------------------------------------------------------------------

def test_drift_cascade_disables_active_rule(api):
    """PRD section 3.3: "If an ACTIVE zone's records no longer satisfy those
    same delegation preconditions — a FULL zone whose dns_records no longer
    contain any proxied record — the zone transitions ACTIVE → MOVED, and the
    cascade of section 2.9 fires: all ACTIVE traffic rules and all ACTIVE bot
    score bands flip to DISABLED."

    Design: Difficulty/transitive_cascade/delegation_drift_disables_rules_then_blocks_new_rules
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="cascade.example.com")
    patch_zone(zone, acc, {
        "traffic_rules": [firewall_rule("r1", "(ip.src eq 203.0.113.0/24)",
                                        "BLOCK")],
    })
    moved = drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    assert moved["status"] == "MOVED"
    assert moved["traffic_rules"][0]["status"] == "DISABLED"


def test_moved_zone_rejects_rule_rearm(api):
    """PRD section 3.4: "The zone must be ACTIVE for any patch — attempts
    against PENDING or MOVED zones fail with ERR_INVALID_STATE."

    Design: Difficulty/transitive_cascade/delegation_drift_disables_rules_then_blocks_new_rules
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="cascade2.example.com")
    patch_zone(zone, acc, {
        "traffic_rules": [firewall_rule("r1", "(ip.src eq 203.0.113.0/24)",
                                        "BLOCK")],
    })
    drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    resp = api.patch_zone(
        zone["id"],
        {"traffic_rules": [firewall_rule("r1", "(ip.src eq 203.0.113.0/24)",
                                         "BLOCK", status="ACTIVE")]},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/zone_redelegation_cycle
# ---------------------------------------------------------------------------

def test_moved_zone_holds_disabled_rules_after_drift(api):
    """PRD section 2.9: "Re-verification later moves the zone MOVED → ACTIVE,
    but disabled rules and bands stay DISABLED — nothing re-enables
    automatically."

    Design: Difficulty/non_linear_state_machine/zone_redelegation_cycle
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="cycle.example.com")
    patch_zone(zone, acc, {
        "traffic_rules": [firewall_rule(
            "r1", '(http.request.uri.path contains "/admin")', "BLOCK"
        )],
    })
    moved = drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    assert moved["status"] == "MOVED", "cycle's first half: ACTIVE -> MOVED"
    assert moved["traffic_rules"][0]["status"] == "DISABLED", (
        "the cascade-disabled rule stays DISABLED after the drift"
    )


def test_moved_zone_rejects_configuration_patch(api):
    """PRD section 3.4: "The zone must be ACTIVE for any patch — attempts
    against PENDING or MOVED zones fail with ERR_INVALID_STATE."

    Design: Difficulty/non_linear_state_machine/zone_redelegation_cycle
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="cycle2.example.com")
    patch_zone(zone, acc, {
        "traffic_rules": [firewall_rule(
            "r1", '(http.request.uri.path contains "/admin")', "BLOCK"
        )],
    })
    drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    resp = api.patch_zone(
        zone["id"],
        {"dns_records": [dns_record(name="www", content="192.0.2.40",
                                    proxied=True)]},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"

"""Zone false-positive telemetry and the DNS record restore invariant."""
from test_helpers import (
    validate_success, get_success_data,
    api_client, TEST_USERS,
    make_account, make_active_zone, zone_headers, get_zone,
    firewall_rule, ruleset_subscription, ruleset_override, dns_record,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Corner/calculations/managed_ruleset_fp_rate_excludes_disabled_inputs
# ---------------------------------------------------------------------------

def _telemetry_zone(acc):
    zone = make_active_zone(acc, domain="fprate.example.com")
    rules = [
        firewall_rule("t1", "(e1)", "BLOCK"),
        firewall_rule("t2", "(e2)", "BLOCK"),
        firewall_rule("t3", "(e3)", "ALLOW"),
        firewall_rule("t4", "(e4)", "ALLOW"),
        firewall_rule("t5", "(e5)", "BLOCK"),
        firewall_rule("t6", "(e6)", "BLOCK"),
        firewall_rule("t7", "(e7)", "BLOCK", status="DISABLED"),
    ]
    subs = [ruleset_subscription("managed-xss", overrides=[
        ruleset_override("xss-001", "DISABLE", status="ACTIVE"),
        ruleset_override("xss-002", "DISABLE", status="ACTIVE"),
    ])]
    return get_success_data(api_client.patch_zone(
        zone["id"],
        {"traffic_rules": rules, "ruleset_subscriptions": subs},
        zone_headers(acc),
    ))


def test_fp_rate_excludes_disabled_rules_from_denominator(api):
    """PRD section 3.4: "active_rules_count is the number of traffic_rules items
    whose status is ACTIVE. disabled_managed_rules_count is the number of
    overrides whose override_action is DISABLE and whose status is ACTIVE,
    counted across only those subscriptions whose own status is ACTIVE.
    false_positive_rate_pct is zero when the sum of those two counts is zero,
    and otherwise one hundred times the disabled-managed-rules count divided by
    that sum, rounded half-up to a whole percentage. DISABLED traffic rules,
    REVERTED overrides, and UNSUBSCRIBED subscriptions contribute nothing to
    either figure."

    Design: Corner/calculations/managed_ruleset_fp_rate_excludes_disabled_inputs
    """
    acc = make_account(plan_tier="BUSINESS")
    zone = _telemetry_zone(acc)
    read = get_zone(zone["id"])
    assert read["active_rules_count"] == 6, "t7 is DISABLED and excluded"
    assert read["disabled_managed_rules_count"] == 2
    assert read["false_positive_rate_pct"] == 25, (
        "round_half_up(100 * 2 / (2 + 6)) == 25"
    )


def test_fp_rate_recomputes_after_override_revert(api):
    """PRD section 3.4: "Every read of a zone recomputes three figures." and
    "REVERTED overrides ... contribute nothing to either figure."

    Design: Corner/calculations/managed_ruleset_fp_rate_excludes_disabled_inputs
    """
    acc = make_account(plan_tier="BUSINESS")
    zone = _telemetry_zone(acc)
    # revert one override (replace-all semantics on ruleset_subscriptions)
    get_success_data(api_client.patch_zone(
        zone["id"],
        {"ruleset_subscriptions": [ruleset_subscription(
            "managed-xss", overrides=[
                ruleset_override("xss-001", "DISABLE", status="REVERTED"),
                ruleset_override("xss-002", "DISABLE", status="ACTIVE"),
            ],
        )]},
        zone_headers(acc),
    ))
    read = get_zone(zone["id"])
    assert read["disabled_managed_rules_count"] == 1
    assert read["false_positive_rate_pct"] == 14, (
        "round_half_up(100 * 1 / 7) == 14"
    )


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/dns_record_content_restore_invariant
# ---------------------------------------------------------------------------

def _restore_setup(acc):
    zone = make_active_zone(
        acc, domain="invariant.example.com",
        records=[dns_record(name="www", content="192.0.2.100", proxied=True)],
    )
    return zone


def test_dns_record_content_restored_by_compensating_patch(api):
    """PRD section 3.4: "Every array the patch mentions replaces the stored
    array wholesale; arrays not mentioned are left untouched." A forward patch
    followed by a compensating patch restores the record set exactly.

    Design: Difficulty/compensating_invariant/dns_record_content_restore_invariant
    """
    acc = make_account(plan_tier="PRO")
    zone = _restore_setup(acc)
    get_success_data(api_client.patch_zone(
        zone["id"],
        {"dns_records": [dns_record(name="www", content="192.0.2.200",
                                    proxied=True)]},
        zone_headers(acc),
    ))
    restored = get_success_data(api_client.patch_zone(
        zone["id"],
        {"dns_records": [dns_record(name="www", content="192.0.2.100",
                                    proxied=True)]},
        zone_headers(acc),
    ))
    assert restored["dns_records"][0]["content"] == "192.0.2.100"
    assert restored["dns_records"][0]["proxied"] is True


def test_zone_version_tracks_mutations_despite_value_round_trip(api):
    """PRD section 3.4: "the patch increments version even when nothing
    materially changed." PRD section 2.5: "version (integer): a system-managed
    integer that increments by 1 on every modification."

    Design: Difficulty/compensating_invariant/dns_record_content_restore_invariant
    """
    acc = make_account(plan_tier="PRO")
    zone = _restore_setup(acc)
    v_after_verify = get_zone(zone["id"])["version"]
    get_success_data(api_client.patch_zone(
        zone["id"],
        {"dns_records": [dns_record(name="www", content="192.0.2.200",
                                    proxied=True)]},
        zone_headers(acc),
    ))
    restored = get_success_data(api_client.patch_zone(
        zone["id"],
        {"dns_records": [dns_record(name="www", content="192.0.2.100",
                                    proxied=True)]},
        zone_headers(acc),
    ))
    assert restored["version"] == v_after_verify + 2, (
        "two patches advance the version by exactly 2 even though the record "
        "content round-trips"
    )

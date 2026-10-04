"""DDoS event ingestion: threshold arithmetic and auto-expiry."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, zone_headers, get_zone,
    reset_clock, set_clock, set_dos_sensitivity, make_activated_ddos_event,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/dos_threshold_three_input_sensitivity_modes
# ---------------------------------------------------------------------------

def _sensitivity_zone(acc, domain, sensitivity):
    zone = make_active_zone(acc, domain=domain)
    return set_dos_sensitivity(zone, acc, sensitivity)


def test_dos_threshold_high_sensitivity_triggers(api):
    """PRD section 3.7: "the platform computes the event's trigger_threshold_rps
    as the floor — taken once, of the full product, never per-factor — of
    baseline_rps multiplied by the automatic threshold multiplier of 20 and then
    by the sensitivity multiplier selected by the zone's dos_sensitivity at that
    moment: 0.5 for HIGH, 1.0 for DEFAULT, and 2.0 for LOW. The event's
    auto_mitigated flag is true exactly when observed_rps is at least
    trigger_threshold_rps."

    Design: Difficulty/combinatorial_formula/dos_threshold_three_input_sensitivity_modes
    """
    reset_clock()
    acc = make_account(plan_tier="BUSINESS")
    zone = _sensitivity_zone(acc, "high.example.com", "HIGH")
    resp = api.create_ddos_event(
        zone["id"], {"observed_rps": 1000, "baseline_rps": 100},
        zone_headers(acc),
    )
    data = validate_success(resp, expected_status=201)
    assert data["trigger_threshold_rps"] == 1000, (
        "floor(100 * 20 * 0.5) == 1000 under HIGH sensitivity"
    )
    assert data["auto_mitigated"] is True
    assert data["status"] == "ACTIVATED"
    assert get_zone(zone["id"])["dos_mitigation_active"] is True


def test_dos_threshold_low_sensitivity_does_not_trigger(api):
    """PRD section 3.7: "the sensitivity multiplier selected by the zone's
    dos_sensitivity at that moment: 0.5 for HIGH, 1.0 for DEFAULT, and 2.0 for
    LOW. The event's auto_mitigated flag is true exactly when observed_rps is at
    least trigger_threshold_rps."

    Design: Difficulty/combinatorial_formula/dos_threshold_three_input_sensitivity_modes
    """
    reset_clock()
    acc = make_account(plan_tier="BUSINESS")
    zone = _sensitivity_zone(acc, "low.example.com", "LOW")
    resp = api.create_ddos_event(
        zone["id"], {"observed_rps": 1000, "baseline_rps": 100},
        zone_headers(acc),
    )
    data = validate_success(resp, expected_status=201)
    assert data["trigger_threshold_rps"] == 4000, (
        "floor(100 * 20 * 2.0) == 4000 under LOW sensitivity"
    )
    assert data["auto_mitigated"] is False
    assert get_zone(zone["id"])["dos_mitigation_active"] is False


# ---------------------------------------------------------------------------
# Corner/state_machines/ddos_event_double_end_rejected
# ---------------------------------------------------------------------------

def test_ddos_event_ends_at_expiry_and_stays_ended(api):
    """PRD section 3.7: "Every ingested event starts ACTIVATED and stamps
    activated_at from the logical clock, with expires_at computed as
    activated_at plus the automatic mitigation TTL of 4 hours. When the logical
    clock reaches an event's expires_at the event transitions ACTIVATED → ENDED
    ... An ENDED event is terminal."

    Design: Corner/state_machines/ddos_event_double_end_rejected
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="ddos.example.com")
    make_activated_ddos_event(zone, acc, observed_rps=5000, baseline_rps=100)
    set_clock("2026-09-01T04:00:00Z")
    events, _ = validate_paginated(
        api.list_ddos_events(ADMIN, params={"zone_id": zone["id"]})
    )
    assert events[0]["status"] == "ENDED"
    assert get_zone(zone["id"])["dos_mitigation_active"] is False
    version_after_expiry = events[0]["version"]
    # a further clock advance changes nothing: terminal ENDED is stable
    set_clock("2026-09-01T05:00:00Z")
    events2, _ = validate_paginated(
        api.list_ddos_events(ADMIN, params={"zone_id": zone["id"]})
    )
    assert events2[0]["status"] == "ENDED"
    assert events2[0]["version"] == version_after_expiry

"""Purge operations: shield-degraded completion latency and cache freshness."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, make_pending_zone, make_pop,
    make_shielded_zone, make_purge_request, get_purge_request,
    zone_headers, get_zone, reset_clock, set_clock, parse_instant,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/purge_completion_shield_degraded_variant
# ---------------------------------------------------------------------------

def test_unshielded_purge_completes_immediately_and_stamps_zone(api):
    """PRD section 3.8: "With no shield the latency is zero and completion
    follows immediately once the clock has passed requested_at" and "when one
    completes, the zone's last_purged_at stamps the completion timestamp."

    Design: Difficulty/dual_variant_calc/purge_completion_shield_degraded_variant
    """
    reset_clock()
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone(acc, domain="plain.example.com")
    make_purge_request(zone, acc, purge_type="PURGE_ALL")
    set_clock("2026-09-01T00:00:01Z")
    stamp = get_zone(zone["id"])["last_purged_at"]
    assert stamp is not None, "unshielded PURGE_ALL completed at +1s"
    assert parse_instant(stamp) == parse_instant("2026-09-01T00:00:01Z"), (
        "the stamp is the completion timestamp (the clock value at completion)"
    )


def test_shielded_purge_waits_900_seconds_before_stamping(api):
    """PRD section 3.8: "shielded purges wait out their 900 seconds, so
    identical purge inputs complete at different times depending only on the
    shield flag" and "computes origin_shield_degraded — true when the zone had a
    non-null origin_shield_pop_code at submission."

    Design: Difficulty/dual_variant_calc/purge_completion_shield_degraded_variant
    """
    reset_clock()
    make_pop(code="SFO", capacity_baseline_gbps=200)
    acc = make_account(plan_tier="BUSINESS")
    zone = make_shielded_zone(acc, "SFO", domain="shield.example.com")
    purge = make_purge_request(zone, acc, purge_type="PURGE_ALL")
    assert purge["origin_shield_degraded"] is True
    set_clock("2026-09-01T00:00:01Z")
    mid = get_purge_request(purge["id"])
    assert mid["status"] == "IN_PROGRESS", (
        "at +1s the shielded request has left QUEUED but its 900s latency "
        "has not elapsed"
    )
    assert get_zone(zone["id"])["last_purged_at"] is None
    set_clock("2026-09-01T00:15:00Z")
    done = get_purge_request(purge["id"])
    assert done["status"] == "COMPLETED"
    stamp = get_zone(zone["id"])["last_purged_at"]
    assert parse_instant(stamp) == parse_instant("2026-09-01T00:15:00Z")


# ---------------------------------------------------------------------------
# Corner/endpoints/clock_set_advances_purge_request_states
# ---------------------------------------------------------------------------

def test_clock_set_advances_purge_request_states(api):
    """PRD section 2.4: "A single clock-set that leaps far enough may carry one
    purge request through more than one status hop; each hop is still evaluated
    in order." PRD section 3.8: "PURGE_URL completions never stamp it."

    Design: Corner/endpoints/clock_set_advances_purge_request_states
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="z.example.com")
    purge = make_purge_request(
        zone, acc, purge_type="PURGE_URL",
        urls=["https://z.example.com/x.css"],
    )
    assert purge["origin_shield_degraded"] is False
    set_clock("2026-09-01T00:00:01Z")
    after = get_purge_request(purge["id"])
    assert after["status"] == "COMPLETED", (
        "unshielded latency is zero: the request traverses QUEUED -> "
        "IN_PROGRESS -> COMPLETED within one clock-set"
    )
    assert get_zone(zone["id"])["last_purged_at"] is None, (
        "PURGE_URL completions never stamp last_purged_at"
    )


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/cache_stamp_conserved_on_unfinished_purge
# ---------------------------------------------------------------------------

def test_unfinished_shielded_purge_leaves_last_purged_at_null(api):
    """PRD section 3.8: "Freshness accounting attaches only to PURGE_ALL
    completions: when one completes, the zone's last_purged_at stamps the
    completion timestamp." A request that has not completed stamps nothing.

    Design: Difficulty/compensating_invariant/cache_stamp_conserved_on_unfinished_purge
    """
    reset_clock()
    make_pop(code="SFO", capacity_baseline_gbps=200)
    acc = make_account(plan_tier="BUSINESS")
    zone = make_shielded_zone(acc, "SFO", domain="stamp.example.com")
    make_purge_request(zone, acc, purge_type="PURGE_ALL")
    set_clock("2026-09-01T00:05:00Z")
    assert get_zone(zone["id"])["last_purged_at"] is None, (
        "the shielded request is IN_PROGRESS at +300s, so the stamp is "
        "conserved unchanged"
    )


def test_unfinished_shielded_purge_keeps_submission_facts(api):
    """PRD section 3.8: "The request is created with 201 in QUEUED status,
    stamps requested_at from the logical clock, and computes
    origin_shield_degraded — true when the zone had a non-null
    origin_shield_pop_code at submission."

    Design: Difficulty/compensating_invariant/cache_stamp_conserved_on_unfinished_purge
    """
    reset_clock()
    make_pop(code="SFO", capacity_baseline_gbps=200)
    acc = make_account(plan_tier="BUSINESS")
    zone = make_shielded_zone(acc, "SFO", domain="stamp2.example.com")
    purge = make_purge_request(zone, acc, purge_type="PURGE_ALL")
    assert purge["origin_shield_degraded"] is True
    assert parse_instant(purge["requested_at"]) == parse_instant(
        "2026-09-01T00:00:00Z"
    )
    set_clock("2026-09-01T00:05:00Z")
    mid = get_purge_request(purge["id"])
    assert mid["status"] == "IN_PROGRESS"
    assert mid["status"] != "COMPLETED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/purge_request_blocked_on_pending_zone
# ---------------------------------------------------------------------------

def test_purge_request_blocked_on_pending_zone(api):
    """PRD section 3.1: "creating any child resource — a DDoS event, a purge
    request, an IP block, an abuse report — requires both an existing account
    and an ACTIVE zone; failures surface as ERR_NOT_FOUND for unresolvable
    references and ERR_INVALID_STATE where the parent state forbids the
    operation."

    Design: Difficulty/cross_entity_state_dependency/purge_request_blocked_on_pending_zone
    """
    acc = make_account(plan_tier="PRO")
    zone = make_pending_zone(acc, domain="gated.example.com")
    resp = api.create_purge_request(
        {"zone_id": zone["id"], "purge_type": "PURGE_ALL"},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_INVALID_STATE"


def test_pending_zone_rejection_creates_no_purge_request(api):
    """PRD section 3.8: "A ZoneAdmin submits a purge against an ACTIVE zone" —
    a rejected submission persists no request.

    Design: Difficulty/cross_entity_state_dependency/purge_request_blocked_on_pending_zone
    """
    acc = make_account(plan_tier="PRO")
    zone = make_pending_zone(acc, domain="gated2.example.com")
    resp = api.create_purge_request(
        {"zone_id": zone["id"], "purge_type": "PURGE_ALL"},
        zone_headers(acc),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data, meta = validate_paginated(
        api.list_purge_requests(ADMIN, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 0
    assert data == []

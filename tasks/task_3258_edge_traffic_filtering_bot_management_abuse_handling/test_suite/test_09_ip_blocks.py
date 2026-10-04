"""IP blocks: provisional windows, confirmation, extension, live duration."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, zone_headers,
    reset_clock, set_clock, make_provisional_block, parse_instant,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST_SAFETY = TEST_USERS["trust_safety_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/ipblock_missing_reason_returns_invalid_request
# ---------------------------------------------------------------------------

def test_ipblock_missing_reason_returns_invalid_request(api):
    """PRD section 2.6: "Shape and enum membership — required fields are
    present, correctly typed, and enum values belong to their declared sets;
    failure yields ERR_INVALID_REQUEST." PRD section 3.9 lists a human-readable
    reason among the block-creation inputs.

    Design: Corner/entities/ipblock_missing_reason_returns_invalid_request
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="req.example.com")
    resp = api.create_ip_block(
        {"zone_id": zone["id"], "ip": "198.51.100.1", "ip_version": "V4"},
        TRUST_SAFETY,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    assert err["error_id"] == "ERR_INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Corner/state_machines/ipblock_provisional_expiry_without_confirmation
# ---------------------------------------------------------------------------

def test_ipblock_provisional_expiry_without_confirmation(api):
    """PRD section 3.9: "A provisional block never confirmed expires
    automatically when the clock reaches its expires_at, moving PROVISIONAL →
    EXPIRED." and "EXPIRED is terminal."

    Design: Corner/state_machines/ipblock_provisional_expiry_without_confirmation
    """
    reset_clock()
    set_clock("2026-09-01T12:00:00Z")
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="expiry.example.com")
    block = make_provisional_block(zone, ip="198.51.100.77", reason="scraping")
    # provisional window is 900 seconds: expires at 12:15
    assert parse_instant(block["expires_at"]) == parse_instant(
        "2026-09-01T12:15:00Z"
    )
    set_clock("2026-09-01T12:16:00Z")
    after = validate_success(api.get_ip_block(block["id"], TRUST_SAFETY))
    assert after["status"] == "EXPIRED"
    resp = api.confirm_ip_block(block["id"], TRUST_SAFETY)
    err = validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_ALREADY_TERMINAL"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/block_duration_single_rounding_order
# ---------------------------------------------------------------------------

def _extended_block_setup():
    reset_clock()
    set_clock("2026-09-01T11:55:00Z")
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone(acc, domain="biz.example.com")
    block = make_provisional_block(zone, ip="198.51.100.7")
    set_clock("2026-09-01T12:00:00Z")
    confirmed = get_success_data(
        api_client.confirm_ip_block(block["id"], TRUST_SAFETY)
    )
    set_clock("2026-09-01T12:30:00Z")
    extended = get_success_data(api_client.extend_ip_block(
        block["id"], {"extend": True}, TRUST_SAFETY
    ))
    set_clock("2026-09-01T12:50:00Z")
    return zone, block, confirmed, extended


def test_block_duration_rounds_once_on_full_product(api):
    """PRD section 3.9: "While a block is CONFIRMED, every read computes
    blocked_seconds_total live against the logical clock: the elapsed seconds
    from confirmed_at to now, discounted by a 2.5 percent grace fraction — that
    is, the elapsed time multiplied by 0.975 — with round-half-up applied once
    to the full product, never per-term."

    Design: Difficulty/combinatorial_formula/block_duration_single_rounding_order
    """
    zone, block, confirmed, _extended = _extended_block_setup()
    data, _meta = validate_paginated(api.list_ip_blocks(
        TRUST_SAFETY, params={"zone_id": zone["id"], "ip": "198.51.100.7"}
    ))
    row = data[0]
    assert row["status"] == "CONFIRMED"
    # confirmed at 12:00, read at 12:50: round_half_up(3000 * 0.975) == 2925
    assert row["blocked_seconds_total"] == 2925


def test_block_extension_reanchors_expiry_never_shortens(api):
    """PRD section 3.9: "Extension recomputes expires_at as the latest of three
    candidates — the current expires_at, confirmed_at plus 3600 seconds, and the
    present logical time plus 3600 seconds — so extension never shortens the
    remaining life."

    Design: Difficulty/combinatorial_formula/block_duration_single_rounding_order
    """
    zone, block, confirmed, extended = _extended_block_setup()
    # confirmed at 12:00 -> 13:00; extended at 12:30 -> max(13:00, 13:00, 13:30)
    assert parse_instant(extended["expires_at"]) == parse_instant(
        "2026-09-01T13:30:00Z"
    )
    data, _meta = validate_paginated(api.list_ip_blocks(
        TRUST_SAFETY, params={"zone_id": zone["id"], "ip": "198.51.100.7"}
    ))
    assert parse_instant(data[0]["expires_at"]) == parse_instant(
        "2026-09-01T13:30:00Z"
    )

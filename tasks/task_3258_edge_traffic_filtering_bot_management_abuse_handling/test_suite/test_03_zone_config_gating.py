"""Zone configuration: plan gating, shield references, band overlap, OCC."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, make_pop, zone_headers, get_zone,
    rate_limit_rule, bot_band, set_dos_sensitivity,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Corner/validations/plan_feature_gate_blocks_rate_limit_on_free
# ---------------------------------------------------------------------------

def test_plan_feature_gate_blocks_rate_limit_on_free(api):
    """PRD section 2.7: "Attempting to use a gated feature the account's tier
    does not include — adding a RATE_LIMIT traffic rule without rate limiting,
    ... — is rejected with ERR_PLAN_FEATURE_UNAVAILABLE (HTTP 402)."

    Design: Corner/validations/plan_feature_gate_blocks_rate_limit_on_free
    """
    acc_free = make_account(plan_tier="FREE")
    zone_f = make_active_zone(acc_free, domain="free.example.com")
    resp = api.patch_zone(
        zone_f["id"],
        {"traffic_rules": [rate_limit_rule(
            "rl", "(path contains /api)", "BLOCK", 100
        )]},
        zone_headers(acc_free),
    )
    err = validate_error(resp, ApiErrorId.ERR_PLAN_FEATURE_UNAVAILABLE)
    assert resp.status_code == 402
    assert err["error_id"] == "ERR_PLAN_FEATURE_UNAVAILABLE"


def test_plan_feature_gate_allows_rate_limit_on_pro(api):
    """PRD section 2.7: "PRO unlocks rate limiting, bot classification, managed
    rulesets, DoS sensitivity tuning, and origin shield — but not cache
    reserve."

    Design: Corner/validations/plan_feature_gate_blocks_rate_limit_on_free
    """
    acc_pro = make_account(plan_tier="PRO")
    zone_p = make_active_zone(acc_pro, domain="pro.example.com")
    resp = api.patch_zone(
        zone_p["id"],
        {"traffic_rules": [rate_limit_rule(
            "rl", "(path contains /api)", "BLOCK", 100
        )]},
        zone_headers(acc_pro),
    )
    data = validate_success(resp)
    assert data["traffic_rules"][0]["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/errors/shield_reference_to_unknown_pop_returns_not_found
# ---------------------------------------------------------------------------

def test_shield_reference_to_unknown_pop_returns_not_found(api):
    """PRD section 3.4: "Setting origin_shield_pop_code to a non-null value
    requires it to equal the code of an existing ACTIVE PoP (an unmatched code
    is ERR_NOT_FOUND) and requires the origin-shield plan feature; setting it to
    null clears the shield."

    Design: Corner/errors/shield_reference_to_unknown_pop_returns_not_found
    """
    make_pop(code="ORD", capacity_baseline_gbps=300)
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone(acc, domain="shield2.example.com")
    resp = api.patch_zone(
        zone["id"], {"origin_shield_pop_code": "XXX"}, zone_headers(acc)
    )
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert err["error_id"] == "ERR_NOT_FOUND"
    ok = api.patch_zone(
        zone["id"], {"origin_shield_pop_code": "ORD"}, zone_headers(acc)
    )
    data = validate_success(ok)
    assert data["origin_shield_pop_code"] == "ORD"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/bot_band_closed_interval_overlap_semantics
# ---------------------------------------------------------------------------

def _zone_with_low_band(acc):
    zone = make_active_zone(acc, domain="bands.example.com")
    return get_success_data(api_client.patch_zone(
        zone["id"],
        {"bot_action_bands": [bot_band("low-block", "BLOCK", 1, 20)]},
        zone_headers(acc),
    ))


def test_bot_band_shared_score_rejected(api):
    """PRD section 3.4: "The closed bands of ACTIVE items must never intersect:
    a new band conflicts with an existing ACTIVE band whenever the new minimum
    is at or below the existing maximum and the existing minimum is at or below
    the new maximum ... An intersecting write is rejected with
    ERR_BAND_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/bot_band_closed_interval_overlap_semantics
    """
    acc = make_account(plan_tier="PRO")
    _zone_with_low_band(acc)
    zone = get_zone_by_domain(acc, "bands.example.com")
    resp = api.patch_zone(
        zone["id"],
        {"bot_action_bands": [
            bot_band("low-block", "BLOCK", 1, 20),
            bot_band("mid-challenge", "CHALLENGE", 20, 40),
        ]},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_BAND_OVERLAP)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_BAND_OVERLAP"


def test_bot_band_adjacent_at_max_plus_one_permitted(api):
    """PRD section 3.4: "merely adjacent bands — the new minimum exactly one
    above the existing maximum — are permitted."

    Design: Difficulty/resource_temporal_overlap/bot_band_closed_interval_overlap_semantics
    """
    acc = make_account(plan_tier="PRO")
    _zone_with_low_band(acc)
    zone = get_zone_by_domain(acc, "bands.example.com")
    resp = api.patch_zone(
        zone["id"],
        {"bot_action_bands": [
            bot_band("low-block", "BLOCK", 1, 20),
            bot_band("mid-challenge", "CHALLENGE", 21, 40),
        ]},
        zone_headers(acc),
    )
    data = validate_success(resp)
    assert len(data["bot_action_bands"]) == 2, (
        "adjacent band at existing max + 1 must be accepted"
    )


def get_zone_by_domain(account, domain):
    """Helper: locate a zone of the account by listing and matching domain."""
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(
        api_client.list_zones(ADMIN, params={"account_id": account["id"]})
    )
    matches = [z for z in data if z["domain_name"] == domain]
    assert matches, f"zone {domain} not found"
    return matches[0]


# ---------------------------------------------------------------------------
# Corner/validations/stale_zone_version_occ_conflict
# ---------------------------------------------------------------------------

def test_stale_zone_version_occ_conflict_rejected(api):
    """PRD section 2.8: "If the supplied value does not equal the zone's current
    version — because verification, a records replace, or an earlier sensitivity
    change has advanced the zone since the client last read it — the request is
    rejected with ERR_STALE_VERSION (HTTP 412), and the zone is left untouched."

    Design: Corner/validations/stale_zone_version_occ_conflict
    """
    from test_helpers import make_active_zone_ref
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone_ref(acc, domain="occ.example.com")
    v_verified = zone["version"]
    # an intervening write advances the zone version
    get_success_data(api.patch_zone(
        zone["id"], {"bot_fight_mode": True}, zone_headers(acc)
    ))
    resp = api.patch_zone(
        zone["id"],
        {"dos_sensitivity": "HIGH", "expected_zone_version": v_verified},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412
    assert err["error_id"] == "ERR_STALE_VERSION"


def test_fresh_zone_version_occ_write_succeeds(api):
    """PRD section 2.8: "The zone's patch operation accepts an optional
    expected_zone_version field. It is required — non-optional — whenever the
    request body contains a dos_sensitivity change: the client must state the
    zone version it last observed."

    Design: Corner/validations/stale_zone_version_occ_conflict
    """
    acc = make_account(plan_tier="BUSINESS")
    zone = make_active_zone(acc, domain="occ2.example.com")
    get_success_data(api.patch_zone(
        zone["id"], {"bot_fight_mode": True}, zone_headers(acc)
    ))
    current = get_zone(zone["id"])
    resp = api.patch_zone(
        zone["id"],
        {"dos_sensitivity": "HIGH",
         "expected_zone_version": current["version"]},
        zone_headers(acc),
    )
    data = validate_success(resp)
    assert data["dos_sensitivity"] == "HIGH"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/
# state_beats_plan_feature_on_dos_sensitivity
# ---------------------------------------------------------------------------

def test_state_check_beats_plan_feature_on_deleted_zone(api):
    """PRD section 2.6: "The pipeline runs in this exact order: ... 6. State
    admissibility — the target resource is in a state that permits the
    operation; failure yields ERR_INVALID_STATE. 7. Terminal-state guard — the
    target is not already in a terminal state; failure yields
    ERR_ALREADY_TERMINAL. ... 9. Business constraints — proxy eligibility,
    delegation preconditions, plan gating, ..." and "earlier checks mask later
    ones."

    PRD does not uniquely determine which of stage 6 / stage 7 fires for a
    patch against a DELETED zone (section 3.4 names only PENDING/MOVED for
    ERR_INVALID_STATE, while section 2.9 ties ERR_ALREADY_TERMINAL to DELETED
    zones) — both readings are PRD-faithful, and both precede stage 9. What is
    uniquely derivable: the response is a 409 state/terminal rejection, never
    the stage-9 ERR_PLAN_FEATURE_UNAVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_plan_feature_on_dos_sensitivity
    """
    acc = make_account(plan_tier="FREE")
    zone = make_active_zone(acc, domain="conflict.example.com")
    get_success_data(api.delete_zone(zone["id"], zone_headers(acc)))
    current = get_zone(zone["id"])
    resp = api.patch_zone(
        zone["id"],
        {"dos_sensitivity": "HIGH",
         "expected_zone_version": current["version"]},
        zone_headers(acc),
    )
    error_id = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
    )
    assert resp.status_code == 409
    assert error_id != ApiErrorId.ERR_PLAN_FEATURE_UNAVAILABLE


def test_state_check_beats_plan_feature_on_moved_zone(api):
    """PRD section 3.4: "The zone must be ACTIVE for any patch — attempts
    against PENDING or MOVED zones fail with ERR_INVALID_STATE." PRD section
    2.6: "earlier checks mask later ones — a client must never observe a
    business-rule rejection for a request whose authentication was already
    defective."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_plan_feature_on_dos_sensitivity
    """
    from test_helpers import drift_zone_to_moved, set_clock, reset_clock
    reset_clock()
    acc = make_account(plan_tier="FREE")
    zone = make_active_zone(acc, domain="conflict2.example.com")
    moved = drift_zone_to_moved(zone, acc, "2026-09-01T00:01:00Z")
    assert moved["status"] == "MOVED"
    resp = api.patch_zone(
        zone["id"],
        {"dos_sensitivity": "HIGH",
         "expected_zone_version": moved["version"]},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert err["error_id"] == "ERR_INVALID_STATE"
    assert err["error_id"] != "ERR_PLAN_FEATURE_UNAVAILABLE"

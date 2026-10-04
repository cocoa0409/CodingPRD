"""Zone onboarding: creation defaults, verification, references, terminality."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, api_client, TEST_USERS,
    make_account, make_pending_zone, make_active_zone, zone_headers,
    create_zone_payload, dns_record,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/zone_create_defaults_and_pending_initial_state
# ---------------------------------------------------------------------------

def test_zone_create_defaults_and_pending_initial_state(api):
    """PRD section 3.3: "A new zone starts in PENDING and is returned with 201."
    PRD section 3.4: "the edge_ttl_seconds cache lifetime (a positive integer,
    defaulting to 3600 seconds), the cache_reserve opt-in boolean (defaulting to
    false), the origin_shield_pop_code shield selector (defaulting to null), the
    bot_fight_mode boolean (defaulting to false), and the dos_sensitivity
    selector of DEFAULT, LOW, or HIGH (defaulting to DEFAULT)."

    Design: Corner/entities/zone_create_defaults_and_pending_initial_state
    """
    acc = make_account(plan_tier="PRO")
    payload = create_zone_payload(acc["id"])
    del payload["dns_records"]
    resp = api.create_zone(payload, zone_headers(acc))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"
    assert data["bot_fight_mode"] is False
    assert data["dos_sensitivity"] == "DEFAULT"
    assert data["origin_shield_pop_code"] is None
    assert data["edge_ttl_seconds"] == 3600
    assert data["dos_mitigation_active"] is False
    for field in ("dns_records", "traffic_rules", "ruleset_subscriptions",
                  "bot_action_bands", "honeypot_paths", "bot_classifications"):
        assert data[field] == [], f"{field} must default to an empty array"


# ---------------------------------------------------------------------------
# Corner/entities/zone_get_unknown_id_returns_not_found
# ---------------------------------------------------------------------------

def test_zone_get_unknown_id_returns_not_found(api):
    """PRD section 2.6: "Path existence, left to right — every identifier in a
    nested path resolves to an existing resource, validated from the outermost
    segment inward; the first unresolvable identifier fails the request with
    ERR_NOT_FOUND."

    Design: Corner/entities/zone_get_unknown_id_returns_not_found
    """
    resp = api.get_zone(NON_EXISTENT_UUID, ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert err["error_id"] == "ERR_NOT_FOUND"


# ---------------------------------------------------------------------------
# Corner/entities/dns_record_txt_proxied_true_rejected
# ---------------------------------------------------------------------------

def test_dns_record_txt_proxied_true_rejected(api):
    """PRD section 3.3: "Proxy eligibility is enforced at write time: proxied
    may be true only on A, AAAA, or CNAME records; a TXT record must always
    carry proxied false, and any violation is rejected with
    ERR_PROXY_STATUS_INVALID."

    Design: Corner/entities/dns_record_txt_proxied_true_rejected
    """
    acc = make_account(plan_tier="PRO")
    payload = create_zone_payload(
        acc["id"],
        domain_name="txt.example.com",
        dns_records=[dns_record(name="_dmarc", record_type="TXT",
                                content="v=DMARC1; p=reject", proxied=True)],
    )
    resp = api.create_zone(payload, zone_headers(acc))
    err = validate_error(resp, ApiErrorId.ERR_PROXY_STATUS_INVALID)
    assert resp.status_code == 422
    assert err["error_id"] == "ERR_PROXY_STATUS_INVALID"
    # no zone was created for this account
    data, meta = validate_paginated(
        api.list_zones(ADMIN, params={"account_id": acc["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Corner/entities/zone_creation_requires_existing_account
# ---------------------------------------------------------------------------

def test_zone_creation_requires_existing_account(api):
    """PRD section 2.6: "Reference existence — every request field carrying a
    foreign key or code reference ... resolves; failure yields ERR_NOT_FOUND."
    PRD section 3.1: "failures surface as ERR_NOT_FOUND for unresolvable
    references."

    Design: Corner/entities/zone_creation_requires_existing_account
    """
    payload = create_zone_payload(NON_EXISTENT_UUID)
    headers = {"X-User-ID": NON_EXISTENT_UUID, "X-User-Role": "ZoneAdmin"}
    resp = api.create_zone(payload, headers)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert err["error_id"] == "ERR_NOT_FOUND"


# ---------------------------------------------------------------------------
# Corner/state_machines/zone_newly_created_starts_pending
# ---------------------------------------------------------------------------

def test_zone_newly_created_starts_pending_and_rejects_hits(api):
    """PRD section 3.3: "A new zone starts in PENDING and is returned with 201."
    PRD section 3.5: "While a zone is ACTIVE and not under automatic mitigation,
    a ZoneAdmin records an observed request against it."

    Design: Corner/state_machines/zone_newly_created_starts_pending
    """
    acc = make_account(plan_tier="PRO")
    zone = make_pending_zone(acc, domain="initial.example.com")
    assert zone["status"] == "PENDING"
    resp = api.record_traffic_hit(
        zone["id"],
        {"occurred_at": "2026-09-01T00:00:00Z", "client_ip": "198.51.100.1"},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"


# ---------------------------------------------------------------------------
# Corner/state_machines/zone_deleted_is_terminal_lockdown
# ---------------------------------------------------------------------------

def test_zone_deleted_is_terminal_lockdown(api):
    """PRD section 3.3: "once DELETED the zone is terminal and further
    transitions are rejected with ERR_ALREADY_TERMINAL."

    Design: Corner/state_machines/zone_deleted_is_terminal_lockdown
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="terminal.example.com")
    get_success_data(api.delete_zone(zone["id"], zone_headers(acc)))
    # verify is a lifecycle transition; on a DELETED zone it must be rejected
    # by the terminal-state guard.
    resp = api.verify_zone(zone["id"], zone_headers(acc))
    err = validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert err["error_id"] == "ERR_ALREADY_TERMINAL"
    after = validate_success(api.get_zone(zone["id"], ADMIN))
    assert after["status"] == "DELETED"


# ---------------------------------------------------------------------------
# Corner/validations/verification_precondition_partial_cname_suffix
# ---------------------------------------------------------------------------

def test_partial_zone_cname_suffix_verification_fails_then_passes(api):
    """PRD section 3.3: "For a PARTIAL zone, the zone must own at least one
    proxied A, AAAA, or CNAME record, and every proxied CNAME record must have
    content ending with the suffix .cdn.example.net. Failing either precondition
    rejects the verification with ERR_ZONE_VERIFICATION_FAILED."

    Design: Corner/validations/verification_precondition_partial_cname_suffix
    """
    acc = make_account(plan_tier="PRO")
    zone = make_pending_zone(
        acc, domain="partial.example.com", onboarding_type="PARTIAL",
        records=[dns_record(name="app", record_type="CNAME",
                            content="example.herokuapp.com", proxied=True)],
    )
    resp = api.verify_zone(zone["id"], zone_headers(acc))
    err = validate_error(resp, ApiErrorId.ERR_ZONE_VERIFICATION_FAILED)
    assert resp.status_code == 422
    assert err["error_id"] == "ERR_ZONE_VERIFICATION_FAILED"
    # a PARTIAL zone whose proxied CNAME carries the compliant suffix verifies
    good = make_pending_zone(
        acc, domain="partial-ok.example.com", onboarding_type="PARTIAL",
        records=[dns_record(name="app", record_type="CNAME",
                            content="app.cdn.example.net", proxied=True)],
    )
    ok = api.verify_zone(good["id"], zone_headers(acc))
    data = validate_success(ok)
    assert data["status"] == "ACTIVE"

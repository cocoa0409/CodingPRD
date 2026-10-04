"""Role-based access control: exclusive operations denied to other roles."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_account, make_active_zone, make_pending_zone, zone_headers,
    create_zone_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
TRUST_SAFETY = TEST_USERS["trust_safety_headers"]


# ---------------------------------------------------------------------------
# Corner/rbac/anonymous_cannot_create_zones
# ---------------------------------------------------------------------------

def test_anonymous_cannot_create_zones(api):
    """PRD section 2.1: "When X-User-Role is Anonymous, X-User-ID is an opaque
    identifier for an unauthenticated member of the public; this role may only
    file abuse reports and nothing else." PRD section 2.6: "Authorization — the
    acting role is permitted for the endpoint per the role matrix; failure
    yields ERR_UNAUTHORIZED."

    Design: Corner/rbac/anonymous_cannot_create_zones
    """
    acc = make_account(plan_tier="PRO")
    resp = api.create_zone(
        create_zone_payload(acc["id"], domain_name="denied.example.com"),
        ANON,
    )
    err = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    assert err["error_id"] == "ERR_UNAUTHORIZED"
    data, meta = validate_paginated(
        api.list_zones(ADMIN, params={"account_id": acc["id"]})
    )
    assert meta["total_count"] == 0, "no zone was created"


# ---------------------------------------------------------------------------
# Corner/rbac/zone_admin_cannot_manage_ip_blocks
# ---------------------------------------------------------------------------

def test_zone_admin_cannot_manage_ip_blocks(api):
    """PRD section 4: POST /api/ip-blocks lists TrustSafetyAnalyst as its only
    authorized role. PRD section 2.6: "Authorization — the acting role is
    permitted for the endpoint per the role matrix; failure yields
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/zone_admin_cannot_manage_ip_blocks
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="rbac.example.com")
    resp = api.create_ip_block(
        {"zone_id": zone["id"], "ip": "198.51.100.200", "ip_version": "V4",
         "reason": "self-help block"},
        zone_headers(acc),
    )
    err = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    assert err["error_id"] == "ERR_UNAUTHORIZED"
    data, meta = validate_paginated(
        api.list_ip_blocks(TRUST_SAFETY, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Corner/rbac/network_planner_cannot_verify_zones
# ---------------------------------------------------------------------------

def test_network_planner_cannot_verify_zones(api):
    """PRD section 4: POST /api/zones/{id}/verify lists ZoneAdmin as its only
    authorized role. PRD section 2.1: "A request whose role is declared but not
    permitted for the targeted endpoint is rejected with ERR_UNAUTHORIZED (HTTP
    403)."

    Design: Corner/rbac/network_planner_cannot_verify_zones
    """
    acc = make_account(plan_tier="PRO")
    zone = make_pending_zone(acc, domain="np.example.com")
    resp = api.verify_zone(zone["id"], PLANNER)
    err = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    assert err["error_id"] == "ERR_UNAUTHORIZED"
    after = validate_success(api.get_zone(zone["id"], ADMIN))
    assert after["status"] == "PENDING"

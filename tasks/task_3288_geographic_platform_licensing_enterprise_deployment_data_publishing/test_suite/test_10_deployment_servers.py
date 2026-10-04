"""Deployment servers: registration gating, authorize side effects, upgrades,
version compatibility rules, portal protection, and decommissioning."""
from test_helpers import (
    ApiErrorId,
    get_grant,
    get_success_data,
    setup_base_chain,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    activate_grant,
    activate_org,
    authorize_server,
    create_compat_rule,
    get_org_version,
    register_server,
    set_clock,
    setup_grant,
    setup_org,
    setup_product,
    setup_server_org,
    transition_server,
)
from test_helpers.factories import create_credit_pool_payload, create_deployment_server_payload
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
DA_HEADERS = TEST_USERS["deployment_admin_headers"]


def test_server_registration_against_named_user_grant_rejected(api):
    """PRD section 3.10: "The grant must be a `DEPLOYMENT_SERVER`-kind grant
    of the same organization, else `ERR_GRANT_KIND_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/server_authorize_gated_by_grant_and_org
    """
    base = setup_base_chain()  # base grant is NAMED_USER-kind
    resp = api.create_deployment_server(
        create_deployment_server_payload(
            base["org"]["id"], base["grant"]["id"],
            hostname="gis1.meridian.example", role="GIS_SERVER", cores_allocated=4),
        DA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_GRANT_KIND_MISMATCH)
    rows = api.list_deployment_servers(
        DA_HEADERS, params={"organization_id": base["org"]["id"]}).json()["data"]
    assert rows == [], f"no server row must persist; got {rows}"


def test_server_registration_against_deployment_grant_accepted(api):
    """PRD section 3.10: "The grant must be a `DEPLOYMENT_SERVER`-kind grant
    of the same organization, else `ERR_GRANT_KIND_MISMATCH`. The server is
    born `REGISTERED`."

    Design: Difficulty/cross_entity_state_dependency/server_authorize_gated_by_grant_and_org
    """
    ctx = setup_server_org(grant_cores=16)
    srv = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis1.meridian.example", cores=4)
    assert srv["status"] == "REGISTERED"


def test_authorize_allocates_cores_and_decommission_releases(api):
    """PRD section 3.10: "On success the grant's `seats_in_use` increases by
    `cores_allocated`."
    PRD section 3.10: "Decommissioning releases capacity: the grant's
    `seats_in_use` decreases by the server's `cores_allocated`."

    Design: Corner/state_machines/server_authorize_side_effect_allocates_cores
    """
    ctx = setup_server_org(grant_cores=16)
    srv = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis1.meridian.example", cores=4)
    data = authorize_server(srv["id"])
    assert data["status"] == "AUTHORIZED"
    assert get_grant(ctx["grant"]["id"])["seats_in_use"] == 4
    data = get_success_data(transition_server(srv["id"], "DECOMMISSIONED"))
    assert data["status"] == "DECOMMISSIONED"
    assert get_grant(ctx["grant"]["id"])["seats_in_use"] == 0


def test_authorize_version_lock_rejects_mismatched_major(api):
    """PRD section 3.10: "Authorization also enforces a version lock: the
    grant's product's `major_version` must equal the server's
    `installed_major_version` (else `ERR_VERSION_INCOMPATIBLE`)."

    Design: Corner/state_machines/server_authorize_side_effect_allocates_cores
    """
    ctx = setup_server_org(product_major=11, grant_cores=16)
    srv = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis2.meridian.example", cores=4, installed_major_version=12)
    resp = transition_server(srv["id"], "AUTHORIZED")
    validate_error(resp, ApiErrorId.ERR_VERSION_INCOMPATIBLE)
    assert get_grant(ctx["grant"]["id"])["seats_in_use"] == 0


def test_portal_decommission_blocked_while_siblings_active(api):
    """PRD section 3.10: "a `PORTAL`-role server cannot be decommissioned
    while any other DeploymentServer of the same organization is `AUTHORIZED`
    or `UPGRADING` (else `ERR_PORTAL_IN_USE`) — the portal is the coordination
    point the others depend on."

    Design: Corner/validations/portal_decommission_blocked_while_siblings_active
    """
    ctx = setup_server_org(grant_cores=32)
    portal = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                             "portal.meridian.example", role="PORTAL", cores=4, auth_mode="OIDC")
    authorize_server(portal["id"])
    gis = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis.meridian.example", role="GIS_SERVER", cores=8)
    authorize_server(gis["id"])

    resp = transition_server(portal["id"], "DECOMMISSIONED")
    validate_error(resp, ApiErrorId.ERR_PORTAL_IN_USE)

    get_success_data(transition_server(gis["id"], "DECOMMISSIONED"))
    data = get_success_data(transition_server(portal["id"], "DECOMMISSIONED"))
    assert data["status"] == "DECOMMISSIONED"
    assert get_grant(ctx["grant"]["id"])["seats_in_use"] == 0


def test_portal_decommission_alone_succeeds(api):
    """PRD section 3.10: "a `PORTAL`-role server cannot be decommissioned
    while any other DeploymentServer of the same organization is `AUTHORIZED`
    or `UPGRADING` (else `ERR_PORTAL_IN_USE`)".

    Design: Corner/validations/portal_decommission_blocked_while_siblings_active
    """
    ctx = setup_server_org(grant_cores=32)
    portal = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                             "portal.meridian.example", role="PORTAL", cores=4, auth_mode="OIDC")
    authorize_server(portal["id"])
    data = get_success_data(transition_server(portal["id"], "DECOMMISSIONED"))
    assert data["status"] == "DECOMMISSIONED"


def test_upgrade_completion_without_compat_rule_rejected(api):
    """PRD section 3.10: "Rule lookup: there must exist at least one
    VersionCompatibilityRule whose `consumer_role` equals this server's `role`
    and whose `consumer_major_version` equals the `target_major_version` —
    otherwise `ERR_NO_COMPAT_RULE`."

    Design: Corner/calculations/version_compat_missing_rule_blocks_even_without_peers
    """
    ctx = setup_server_org(grant_cores=32)
    gis = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis.meridian.example", role="GIS_SERVER", cores=8)
    authorize_server(gis["id"])
    get_success_data(transition_server(gis["id"], "UPGRADING", target_major_version=12))
    resp = transition_server(gis["id"], "AUTHORIZED")
    validate_error(resp, ApiErrorId.ERR_NO_COMPAT_RULE)
    after = get_success_data(api.get_deployment_server(gis["id"], DA_HEADERS))
    assert after["status"] == "UPGRADING"
    assert after["installed_major_version"] == 11


def test_upgrade_requires_target_greater_than_installed(api):
    """PRD section 3.10: "a `DeploymentAdmin` moves an `AUTHORIZED` server to
    `UPGRADING`, supplying a `target_major_version` that must be strictly
    greater than the `installed_major_version` (else
    `ERR_INVALID_TARGET_VERSION`)".

    Design: Corner/calculations/version_compat_missing_rule_blocks_even_without_peers
    """
    ctx = setup_server_org(grant_cores=32)
    gis = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis.meridian.example", role="GIS_SERVER", cores=8)
    authorize_server(gis["id"])
    resp = transition_server(gis["id"], "UPGRADING", target_major_version=11)
    validate_error(resp, ApiErrorId.ERR_INVALID_TARGET_VERSION)


def test_non_strict_rule_warns_but_completes_and_cascades(api):
    """PRD section 3.10: "If any peer's `installed_major_version` is not a
    member of the rule's `allowed_dependency_major_versions`, a strict rule
    (`strict` true) rejects the completion with `ERR_VERSION_INCOMPATIBLE`; a
    non-strict rule records a warning, which is returned in the response
    `meta`, and evaluation continues."
    PRD section 3.10: "if the new `installed_major_version` exceeds the
    grant's product's `major_version`, that grant is moved from `ACTIVE` to
    `SUSPENDED` as a cross-entity cascade, revoking its extension grants per
    §3.4."

    Design: Corner/calculations/version_compat_non_strict_rule_warns_but_passes
    """
    ctx = setup_server_org(product_major=11, grant_cores=32)
    portal = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                             "portal.meridian.example", role="PORTAL", cores=4, auth_mode="OIDC")
    authorize_server(portal["id"])
    gis = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis.meridian.example", role="GIS_SERVER", cores=8)
    authorize_server(gis["id"])
    create_compat_rule("GIS_SERVER", 12, "PORTAL", [12], strict=False)
    get_success_data(transition_server(gis["id"], "UPGRADING", target_major_version=12))
    data = get_success_data(transition_server(gis["id"], "AUTHORIZED"))
    assert data["installed_major_version"] == 12
    assert data["status"] == "AUTHORIZED"
    # Post-upgrade cascade: 12 > product major 11 -> grant SUSPENDED
    assert get_grant(ctx["grant"]["id"])["status"] == "SUSPENDED"


def test_strict_rule_rejects_upgrade_completion(api):
    """PRD section 3.10: "If any peer's `installed_major_version` is not a
    member of the rule's `allowed_dependency_major_versions`, a strict rule
    (`strict` true) rejects the completion with `ERR_VERSION_INCOMPATIBLE`".

    Design: Corner/calculations/version_compat_non_strict_rule_warns_but_passes
    """
    ctx = setup_server_org(product_major=11, grant_cores=32)
    portal = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                             "portal.meridian.example", role="PORTAL", cores=4, auth_mode="OIDC")
    authorize_server(portal["id"])
    gis = register_server(ctx["org"]["id"], ctx["grant"]["id"],
                          "gis.meridian.example", role="GIS_SERVER", cores=8)
    authorize_server(gis["id"])
    create_compat_rule("GIS_SERVER", 12, "PORTAL", [12], strict=True)
    get_success_data(transition_server(gis["id"], "UPGRADING", target_major_version=12))
    resp = transition_server(gis["id"], "AUTHORIZED")
    validate_error(resp, ApiErrorId.ERR_VERSION_INCOMPATIBLE)
    after = get_success_data(api.get_deployment_server(gis["id"], DA_HEADERS))
    assert after["installed_major_version"] == 11

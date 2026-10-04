"""LicenseGrant lifecycle: invalid transitions, OCC, validity windows,
revocation blockers, and role gating."""
from test_helpers import (
    ApiErrorId,
    LA_HEADERS,
    PA_HEADERS,
    get_grant,
    get_org,
    get_org_version,
    get_success_data,
    setup_base_chain,
    setup_with_user,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    activate_grant,
    activate_org,
    invite_user,
    accept_user,
    set_clock,
    setup_grant,
    setup_org,
    setup_product,
)
from test_helpers.factories import create_credit_pool_payload
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
DA_HEADERS = TEST_USERS["deployment_admin_headers"]


def _grant_transition(api, grant_id, target, org_version, headers=LA_HEADERS):
    return api.transition_license_grant(
        grant_id,
        {"target_status": target, "expected_organization_version": org_version},
        headers,
    )


def test_grant_activate_from_active_rejected(api):
    """PRD section 3.4: "The grant must currently be `PENDING_ACTIVATION` or
    `SUSPENDED` (otherwise `ERR_GRANT_NOT_PENDING`)."

    Design: Corner/state_machines/grant_activate_from_active_rejected
    """
    base = setup_base_chain()
    grant = base["grant"]
    assert grant["status"] == "ACTIVE"
    # Fresh version: OCC passes and the state check fires.
    resp = _grant_transition(api, grant["id"], "ACTIVE", get_org_version(base["org"]["id"]))
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_PENDING)
    assert get_grant(grant["id"])["status"] == "ACTIVE"


def test_grant_activate_from_active_does_not_consume_seats(api):
    """PRD section 3.4: "The grant must currently be `PENDING_ACTIVATION` or
    `SUSPENDED` (otherwise `ERR_GRANT_NOT_PENDING`)."
    PRD section 3.4: "The grant is born in `PENDING_ACTIVATION` with
    `seats_in_use` at 0."

    Design: Corner/state_machines/grant_activate_from_active_rejected
    """
    base = setup_base_chain()
    grant = base["grant"]
    _grant_transition(api, grant["id"], "ACTIVE", get_org_version(base["org"]["id"]))
    after = get_grant(grant["id"])
    assert after["status"] == "ACTIVE"
    assert after["seats_in_use"] == 0


def test_grant_suspend_from_pending_rejected(api):
    """PRD section 3.4: "Suspending a grant moves it from `ACTIVE` to
    `SUSPENDED` and has four triggers: a `LicenseAdmin` requesting it directly
    (which requires the grant to be `ACTIVE`, else `ERR_GRANT_NOT_ACTIVE`)".

    Design: Corner/state_machines/grant_suspend_from_pending_rejected
    """
    set_clock()
    org = setup_org()
    get_success_data(api.create_credit_pool(create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product()
    grant = setup_grant(org["id"], product["id"])
    activate_org(org["id"])
    resp = _grant_transition(api, grant["id"], "SUSPENDED", get_org_version(org["id"]))
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)
    assert get_grant(grant["id"])["status"] == "PENDING_ACTIVATION"


def test_grant_occ_roundtrip_activate_then_stale_suspend(api):
    """PRD section 2.9: "grant activations themselves increment the
    Organization's `version` by 1, so a second sequential activation carrying
    the first call's observed version fails."
    PRD section 2.9: "If the value does not match the Organization's current
    `version` — because, for instance, an earlier grant activation has already
    incremented it — the request is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_layers/grant_transition_occ_roundtrip
    """
    set_clock()
    org = setup_org()
    get_success_data(api.create_credit_pool(create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product()
    grant = setup_grant(org["id"], product["id"])
    activate_org(org["id"])
    observed_v = get_org_version(org["id"])

    resp = _grant_transition(api, grant["id"], "ACTIVE", observed_v)
    validate_success(resp)
    org_after = get_org(org["id"])
    assert org_after["version"] == observed_v + 1

    # Replay the stale observed version -> 412
    resp = _grant_transition(api, grant["id"], "SUSPENDED", observed_v)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # Fresh version succeeds
    resp = _grant_transition(api, grant["id"], "SUSPENDED", get_org_version(org["id"]))
    data = validate_success(resp)
    assert data["status"] == "SUSPENDED"


def test_grant_occ_stale_suspend_leaves_grant_active(api):
    """PRD section 2.9: "If the value does not match the Organization's
    current `version` — because, for instance, an earlier grant activation has
    already incremented it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/grant_transition_occ_roundtrip
    """
    base = setup_base_chain()
    grant = base["grant"]
    resp = _grant_transition(api, grant["id"], "SUSPENDED", base["org_v0"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_grant(grant["id"])["status"] == "ACTIVE"


def test_deployment_admin_cannot_transition_grants(api):
    """PRD section 2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD section 4 endpoint table: "| POST | /geo-orgs/license-grants/{id}/transition
    | Grant lifecycle: activate, re-activate, suspend, revoke; OCC on
    Organization.version | LicenseAdmin |".

    Design: Corner/roles/deployment_admin_cannot_manage_grants
    """
    set_clock()
    org = setup_org()
    org_v0 = org["version"]
    get_success_data(api.create_credit_pool(create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product()
    grant = setup_grant(org["id"], product["id"])
    activate_org(org["id"])
    resp = _grant_transition(api, grant["id"], "ACTIVE", org_v0, headers=DA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert get_grant(grant["id"])["status"] == "PENDING_ACTIVATION"


def test_deployment_admin_cannot_create_grants(api):
    """PRD section 2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD section 4 endpoint table: "| POST | /geo-orgs/license-grants | Create a
    LicenseGrant (PENDING_ACTIVATION) | LicenseAdmin |".

    Design: Corner/roles/deployment_admin_cannot_manage_grants
    """
    from test_helpers.factories import create_license_grant_payload
    set_clock()
    org = setup_org()
    product = setup_product()
    resp = api.create_license_grant(
        create_license_grant_payload(org["id"], product["id"]), DA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_revoke_grant_blocked_by_active_named_user(api):
    """PRD section 3.4: "Revocation moves an `ACTIVE` grant to `REVOKED` at a
    `LicenseAdmin`'s request. The grant must be `ACTIVE` (else
    `ERR_GRANT_NOT_ACTIVE`), no named user whose `home_license_grant_id`
    references this grant may currently be `ACTIVE` (else
    `ERR_NAMED_USERS_STILL_ASSIGNED`)".

    Design: Corner/validations/revoke_grant_blocked_by_active_users_and_servers
    """
    base = setup_with_user()
    grant = base["grant"]
    resp = _grant_transition(api, grant["id"], "REVOKED", get_org_version(base["org"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NAMED_USERS_STILL_ASSIGNED)
    after = get_grant(grant["id"])
    assert after["status"] == "ACTIVE"
    assert after["seats_in_use"] == 1


def test_revoke_grant_succeeds_once_users_gone(api):
    """PRD section 3.4: "no named user whose `home_license_grant_id`
    references this grant may currently be `ACTIVE` (else
    `ERR_NAMED_USERS_STILL_ASSIGNED`)".
    PRD section 3.4: "Revocation, like expiry, revokes the extension grants
    and releases in-use seats to zero."

    Design: Corner/validations/revoke_grant_blocked_by_active_users_and_servers
    """
    base = setup_with_user()
    grant = base["grant"]
    user = base["user"]
    get_success_data(api.transition_named_user(
        user["id"], {"target_status": "DEACTIVATED"}, LA_HEADERS))
    resp = _grant_transition(api, grant["id"], "REVOKED", get_org_version(base["org"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "REVOKED"
    after = get_grant(grant["id"])
    assert after["seats_in_use"] == 0


def test_grant_activation_before_valid_from_rejected(api):
    """PRD section 3.4: "The organization's `current_period_index` must be at
    least `valid_from_period` (otherwise `ERR_GRANT_NOT_YET_VALID`)".

    Design: Difficulty/resource_temporal_overlap/grant_validity_window_brackets_period
    """
    set_clock()
    org = setup_org()
    get_success_data(api.create_credit_pool(create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product()
    grant = setup_grant(org["id"], product["id"], valid_from_period=5, valid_to_period=8)
    activate_org(org["id"])
    resp = _grant_transition(api, grant["id"], "ACTIVE", get_org_version(org["id"]))
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_YET_VALID)
    assert get_grant(grant["id"])["status"] == "PENDING_ACTIVATION"


def test_grant_validity_window_inclusive_left_exclusive_right(api):
    """PRD section 2.5: "a grant's `valid_from_period` is the first period,
    inclusive, in which the grant may activate, and its `valid_to_period` is
    the period, exclusive, at which the grant auto-expires."
    PRD section 2.5: "every LicenseGrant in `ACTIVE` status whose
    `valid_to_period` has been reached — that is, whose `valid_to_period` is
    less than or equal to the new period index — flips to `EXPIRED`".

    Design: Difficulty/resource_temporal_overlap/grant_validity_window_brackets_period
    """
    set_clock()
    org = setup_org()
    get_success_data(api.create_credit_pool(create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product()
    grant = setup_grant(org["id"], product["id"], valid_from_period=5, valid_to_period=8)
    activate_org(org["id"])

    # Advance to period 5 (2026-09-06) — inclusive left boundary
    set_clock("2026-09-06T00:00:00Z")
    resp = _grant_transition(api, grant["id"], "ACTIVE", get_org_version(org["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"

    # Period 7 (2026-09-08): still ACTIVE
    set_clock("2026-09-08T00:00:00Z")
    assert get_grant(grant["id"])["status"] == "ACTIVE"

    # Period 8 (2026-09-09): auto-expired
    set_clock("2026-09-09T00:00:00Z")
    assert get_grant(grant["id"])["status"] == "EXPIRED"

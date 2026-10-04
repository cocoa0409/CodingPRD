"""API keys: settle charging, per-key credit cap revocation boundary, and
tenant-scoped uniqueness."""
from test_helpers import (
    ApiErrorId,
    get_pool,
    get_success_data,
    make_named_user_headers,
    setup_base_chain,
    setup_with_key,
    setup_with_user,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    activate_grant,
    activate_org,
    create_batch,
    invite_user,
    issue_key,
    list_keys,
    set_clock,
    settle_batch,
    setup_grant,
    setup_org,
)
from test_helpers.factories import create_credit_pool_payload, create_named_user_payload
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
LA_HEADERS = TEST_USERS["license_admin_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def test_settle_charges_key_and_revokes_past_cap(api):
    """PRD section 3.7: "For client batches, the key's `credits_consumed`
    increases by the `settled_credits`, and if the key's `per_key_credit_cap`
    is greater than zero and its `credits_consumed` now exceeds that cap, the
    key itself is moved to `REVOKED`".

    Design: Corner/endpoints/settle_charges_api_key_and_cap_revokes
    """
    base = setup_with_user()
    user_id, org_id = base["user"]["id"], base["org"]["id"]
    headers = make_named_user_headers(user_id)
    key = issue_key(user_id, org_id, label="capped", cap=440, service_kinds=["GEOCODE"])

    b1 = get_success_data(create_batch(org_id, key["id"], "GEOCODE", 100, "cap-1", headers=headers))
    set_clock("2026-09-02T00:00:00Z")
    pool = get_pool(org_id)
    get_success_data(settle_batch(b1["id"], pool["version"]))
    keys = list_keys(user_id)
    assert keys[0]["credits_consumed"] == 440
    # 440 > 440 is false — at exactly the cap the key stays ACTIVE
    assert keys[0]["status"] == "ACTIVE"

    b2 = get_success_data(create_batch(org_id, key["id"], "GEOCODE", 10, "cap-2", headers=headers))
    set_clock("2026-09-03T00:00:00Z")
    pool = get_pool(org_id)
    get_success_data(settle_batch(b2["id"], pool["version"]))
    keys = list_keys(user_id)
    # round(40*1.1)=44 -> 440+44=484 > 440 -> revoked
    assert keys[0]["credits_consumed"] == 484
    assert keys[0]["status"] == "REVOKED"


def test_revoked_key_rejects_new_batches(api):
    """PRD section 3.7: "The initiating API key must be `ACTIVE` (else
    `ERR_API_KEY_REVOKED`)".
    PRD section 3.7: "if the key's `per_key_credit_cap` is greater than zero
    and its `credits_consumed` now exceeds that cap, the key itself is moved
    to `REVOKED`".

    Design: Corner/endpoints/settle_charges_api_key_and_cap_revokes
    """
    base = setup_with_user()
    user_id, org_id = base["user"]["id"], base["org"]["id"]
    headers = make_named_user_headers(user_id)
    key = issue_key(user_id, org_id, label="capped", cap=440, service_kinds=["GEOCODE"])
    b1 = get_success_data(create_batch(org_id, key["id"], "GEOCODE", 100, "cap-1", headers=headers))
    set_clock("2026-09-02T00:00:00Z")
    pool = get_pool(org_id)
    get_success_data(settle_batch(b1["id"], pool["version"]))
    b2 = get_success_data(create_batch(org_id, key["id"], "GEOCODE", 10, "cap-2", headers=headers))
    set_clock("2026-09-03T00:00:00Z")
    pool = get_pool(org_id)
    get_success_data(settle_batch(b2["id"], pool["version"]))
    resp = create_batch(org_id, key["id"], "GEOCODE", 5, "cap-3", headers=headers)
    validate_error(resp, ApiErrorId.ERR_API_KEY_REVOKED)


def test_duplicate_username_rejected_within_org(api):
    """PRD section 3.6: "A `LicenseAdmin` invites a named user by supplying
    the `organization_id`, a `username` and `email` (each unique within the
    organization; a collision is rejected with `ERR_DUPLICATE_VALUE`)".

    Design: Corner/cross_cutting_layers/duplicate_username_within_org_rejected
    """
    base = setup_base_chain()
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    invite_user(org_id, grant_id, username="ada", email="ada@meridian.example")
    resp = api.create_named_user(
        create_named_user_payload(org_id, grant_id, username="ada", email="ada2@meridian.example"),
        LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE)


def test_duplicate_username_allowed_across_orgs(api):
    """PRD section 3.6: "a `username` and `email` (each unique within the
    organization; a collision is rejected with `ERR_DUPLICATE_VALUE`)" —
    uniqueness is within the organization.

    Design: Corner/cross_cutting_layers/duplicate_username_within_org_rejected
    """
    base = setup_base_chain()
    invite_user(base["org"]["id"], base["grant"]["id"], username="ada",
                email="ada@meridian.example")

    org2 = setup_org(name="Other Org", home_region="CA")
    org2_v0 = org2["version"]
    get_success_data(api.create_credit_pool(
        create_credit_pool_payload(org2["id"], capacity_credits=100), BA_HEADERS))
    grant2 = setup_grant(org2["id"], base["product"]["id"], seats_allocated=5)
    activate_org(org2["id"])
    activate_grant(grant2["id"], org2["id"])
    resp = api.create_named_user(
        create_named_user_payload(org2["id"], grant2["id"], username="ada",
                                  email="ada@other.example"),
        LA_HEADERS)
    validate_success(resp, expected_status=201)

"""Composite setup helpers.

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch via the public endpoints. All helpers use
get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ALL_SERVICE_KINDS, TEST_DEFAULTS
from .factories import (
    create_api_key_payload,
    create_content_item_payload,
    create_credit_batch_payload,
    create_credit_pool_payload,
    create_deployment_server_payload,
    create_ev_payload,
    create_license_grant_payload,
    create_license_product_payload,
    create_named_user_payload,
    create_org_payload,
)
from .test_users import TEST_USERS, make_compliance_officer_headers, make_named_user_headers

PA_HEADERS = TEST_USERS["platform_admin_headers"]
LA_HEADERS = TEST_USERS["license_admin_headers"]
DA_HEADERS = TEST_USERS["deployment_admin_headers"]
BA_HEADERS = TEST_USERS["billing_admin_headers"]
CM_HEADERS = TEST_USERS["content_moderator_headers"]
CO_HEADERS = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=TEST_DEFAULTS["CLOCK_T0"]):
    return get_success_data(api_client.set_clock(to_iso8601, PA_HEADERS))


def get_org(org_id):
    return get_success_data(api_client.get_org(org_id, PA_HEADERS))


def get_org_version(org_id):
    return get_org(org_id)["version"]


def get_pool_for_org(org_id):
    data, _meta = _list_pool_rows(org_id)
    assert len(data) == 1, f"expected exactly one pool for org {org_id}"
    return data[0]


def _list_pool_rows(org_id=None):
    params = {"organization_id": org_id} if org_id else None
    resp = api_client.list_credit_pools(BA_HEADERS, params=params)
    body = get_success_data(resp)
    # list endpoint returns an array payload
    if isinstance(body, list):
        return body, {}
    return body.get("data", body) if isinstance(body, dict) else body, {}


def _pool_rows(org_id=None):
    params = {"organization_id": org_id} if org_id else {}
    resp = api_client.list_credit_pools(BA_HEADERS, params=params)
    import json
    payload = resp.json()
    return payload["data"]


def get_pool(org_id=None):
    rows = _pool_rows(org_id)
    assert rows, "expected at least one credit pool"
    return rows[0]


def get_grant(grant_id):
    return get_success_data(api_client.get_license_grant(grant_id, LA_HEADERS))


def get_user(user_id):
    return get_success_data(api_client.get_named_user(user_id, LA_HEADERS))


def get_item(item_id, headers=None):
    return get_success_data(api_client.get_content_item(item_id, headers or PA_HEADERS))


def get_batch(batch_id):
    return get_success_data(api_client.get_credit_batch(batch_id, BA_HEADERS))


def list_batches(org_id=None, **filters):
    params = dict(filters)
    if org_id:
        params["organization_id"] = org_id
    resp = api_client.list_credit_batches(BA_HEADERS, params=params)
    return resp.json()["data"]


def list_keys(user_id, headers=None):
    resp = api_client.list_api_keys(user_id, headers or LA_HEADERS)
    return resp.json()["data"]


def list_evs(org_id=None, headers=None, **filters):
    params = dict(filters)
    if org_id:
        params["organization_id"] = org_id
    resp = api_client.list_eligibility_verifications(headers or CO_HEADERS, params=params)
    return resp.json()["data"]


def list_extension_grants(grant_id):
    resp = api_client.list_extension_grants(grant_id, LA_HEADERS)
    return resp.json()["data"]


def activate_grant(grant_id, org_id):
    """Activate a grant, threading the parent org's current version."""
    return get_success_data(api_client.transition_license_grant(
        grant_id,
        {"target_status": "ACTIVE", "expected_organization_version": get_org_version(org_id)},
        LA_HEADERS,
    ))


# ---------------------------------------------------------------------------
# Tier 1/2: the canonical base chain
# ---------------------------------------------------------------------------

def setup_org(org_kind="COMMERCIAL", name="Meridian GIS Co", home_region="US"):
    """Clock at the default instant plus a fresh PROVISIONING org."""
    set_clock()
    org = get_success_data(api_client.create_org(
        create_org_payload(name=name, org_kind=org_kind, home_region=home_region), PA_HEADERS))
    return org


def setup_org_with_pool(org=None, capacity=TEST_DEFAULTS["POOL_CAPACITY"], pool_overrides=None):
    """Org plus its CreditPool. Returns (org, pool)."""
    if org is None:
        org = setup_org()
    pool_kwargs = dict(pool_overrides or {})
    pool = get_success_data(api_client.create_credit_pool(
        create_credit_pool_payload(org["id"], capacity_credits=capacity, **pool_kwargs), BA_HEADERS))
    return org, pool


def setup_product(product_code=TEST_DEFAULTS["PRODUCT_CODE_NAMED"], **overrides):
    return get_success_data(api_client.create_license_product(
        create_license_product_payload(product_code=product_code, **overrides), PA_HEADERS))


def setup_grant(org_id, product_id, **overrides):
    return get_success_data(api_client.create_license_grant(
        create_license_grant_payload(org_id, product_id, **overrides), LA_HEADERS))


def activate_org(org_id):
    return get_success_data(api_client.transition_org(org_id, {"target_status": "ACTIVE"}, PA_HEADERS))


def setup_base_chain(
    org_kind="COMMERCIAL",
    capacity=TEST_DEFAULTS["POOL_CAPACITY"],
    pool_overrides=None,
    product_code=TEST_DEFAULTS["PRODUCT_CODE_NAMED"],
    product_overrides=None,
    grant_overrides=None,
):
    """Canonical chain: clock, org, pool, product, grant, org ACTIVE, grant ACTIVE.

    Returns a dict with org (post-activation), pool, product, grant (ACTIVE),
    and org_v0 (the org's version as returned at creation).
    """
    org = setup_org(org_kind=org_kind)
    org_v0 = org["version"]
    pool_kwargs = dict(pool_overrides or {})
    pool = get_success_data(api_client.create_credit_pool(
        create_credit_pool_payload(org["id"], capacity_credits=capacity, **pool_kwargs), BA_HEADERS))
    product = setup_product(product_code=product_code, **(product_overrides or {}))
    grant = setup_grant(org["id"], product["id"], **(grant_overrides or {}))
    org = activate_org(org["id"])
    grant = activate_grant(grant["id"], org["id"])
    return {
        "org": org,
        "org_v0": org_v0,
        "pool": pool,
        "product": product,
        "grant": grant,
    }


def invite_user(org_id, grant_id, username="ada", email="ada@meridian.example", level="PROFESSIONAL"):
    return get_success_data(api_client.create_named_user(
        create_named_user_payload(org_id, grant_id, username=username, email=email, named_user_level=level),
        LA_HEADERS,
    ))


def accept_user(user_id):
    return get_success_data(api_client.transition_named_user(
        user_id, {"target_status": "ACTIVE"}, make_named_user_headers(user_id)))


def setup_with_user(base=None, username="ada", email="ada@meridian.example", level="PROFESSIONAL"):
    """Base chain plus an accepted (ACTIVE) named user on the base grant."""
    if base is None:
        base = setup_base_chain()
    user = invite_user(base["org"]["id"], base["grant"]["id"], username=username, email=email, level=level)
    user = accept_user(user["id"])
    base["user"] = user
    return base


def issue_key(user_id, org_id, label="dev-key", cap=0, service_kinds=None):
    return get_success_data(api_client.create_api_key(
        create_api_key_payload(
            user_id, org_id,
            label=label,
            allowed_service_kinds=list(service_kinds or ALL_SERVICE_KINDS),
            per_key_credit_cap=cap,
        ),
        make_named_user_headers(user_id),
    ))


def setup_with_key(base=None, **key_kwargs):
    """Base chain plus ACTIVE user and that user's all-services key."""
    if base is None:
        base = setup_with_user()
    elif "user" not in base:
        base = setup_with_user(base)
    base["key"] = issue_key(base["user"]["id"], base["org"]["id"], **key_kwargs)
    return base


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_item(org_id, owner_id, title="Trailheads", item_kind="FEATURE_LAYER",
                      storage_bytes=0, **overrides):
    return get_success_data(api_client.create_content_item(
        create_content_item_payload(
            org_id, title=title, item_kind=item_kind, storage_bytes=storage_bytes, **overrides),
        make_named_user_headers(owner_id),
    ))


def publish_item(item_id, owner_id):
    return get_success_data(api_client.transition_content_item(
        item_id, {"target_status": "PUBLISHED"}, make_named_user_headers(owner_id)))


def create_published_item(org_id, owner_id, **kwargs):
    item = create_draft_item(org_id, owner_id, **kwargs)
    return publish_item(item["id"], owner_id)


def share_item(item_id, owner_id, target_level, expected_version):
    return get_success_data(api_client.share_content_item(
        item_id,
        {"target_sharing_level": target_level, "expected_content_item_version": expected_version},
        make_named_user_headers(owner_id),
    ))


def create_batch(org_id, key_id, service_kind, units, idem_key, headers=None, extension_code=None):
    payload = create_credit_batch_payload(
        org_id, key_id,
        service_kind=service_kind,
        requested_units=units,
        idempotency_key=idem_key,
    )
    if extension_code is not None:
        payload["extension_code"] = extension_code
    return api_client.create_credit_batch(payload, headers or BA_HEADERS)


def settle_batch(batch_id, pool_version):
    return api_client.transition_credit_batch(
        batch_id,
        {"target_status": "SETTLED", "expected_credit_pool_version": pool_version},
        BA_HEADERS,
    )


def reverse_batch(batch_id, pool_version):
    return api_client.transition_credit_batch(
        batch_id,
        {"target_status": "REVERSED", "expected_credit_pool_version": pool_version},
        BA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Tier 2 variants: education org with approved EV
# ---------------------------------------------------------------------------

def setup_education_org(grant_kind="EDUCATION_PROGRAM", product_overrides=None):
    """EDUCATION org, ACTIVE, with a STANDARD named-user grant ACTIVE hosting
    an ACTIVE user (the EV submitter), plus a program-kind grant still
    PENDING_ACTIVATION. Returns a context dict where "grant" is the
    program-kind grant and "std_grant" hosts the user."""
    set_clock()
    org = get_success_data(api_client.create_org(
        create_org_payload(name="State College GIS", org_kind="EDUCATION", home_region="US"), PA_HEADERS))
    org_v0 = org["version"]
    pool = get_success_data(api_client.create_credit_pool(
        create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product(**(product_overrides or {}))
    std_grant = setup_grant(org["id"], product["id"], grant_kind="STANDARD")
    grant = setup_grant(org["id"], product["id"], grant_kind=grant_kind)
    org = activate_org(org["id"])
    std_grant = activate_grant(std_grant["id"], org["id"])
    user = invite_user(org["id"], std_grant["id"])
    user = accept_user(user["id"])
    return {
        "org": org, "org_v0": org_v0, "pool": pool, "product": product,
        "grant": grant, "std_grant": std_grant, "user": user,
    }


def submit_ev(org_id, submitter_id, program_kind="EDUCATION_PROGRAM", evidence="doc-v1"):
    return get_success_data(api_client.create_eligibility_verification(
        create_ev_payload(org_id, program_kind=program_kind, evidence_document_ref=evidence),
        make_named_user_headers(submitter_id),
    ))


def review_ev(ev_id, officer_id="co-1"):
    return get_success_data(api_client.transition_eligibility_verification(
        ev_id, {"target_status": "UNDER_REVIEW"}, make_compliance_officer_headers(officer_id)))


def decide_ev(ev_id, target_status, rationale, officer_id="co-1"):
    return api_client.transition_eligibility_verification(
        ev_id,
        {"target_status": target_status, "decision_rationale": rationale},
        make_compliance_officer_headers(officer_id),
    )


def approve_ev(ev_id, officer_id="co-1", rationale="Accredited institution verified"):
    resp = decide_ev(ev_id, "APPROVED", rationale, officer_id=officer_id)
    return get_success_data(resp)


def setup_education_org_with_approved_ev(**kwargs):
    """Education org with an APPROVED EV (valid_through_period = current + 12)."""
    ctx = setup_education_org(**kwargs)
    ev = submit_ev(ctx["org"]["id"], ctx["user"]["id"])
    review_ev(ev["id"])
    ev = approve_ev(ev["id"])
    ctx["ev"] = ev
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 variant: concurrent-use org (for overage metering)
# ---------------------------------------------------------------------------

def setup_concurrent_use_org(seats_allocated=1):
    """Org ACTIVE with a CONCURRENT_USE grant ACTIVE. Returns context dict."""
    set_clock()
    org = get_success_data(api_client.create_org(create_org_payload(), PA_HEADERS))
    pool = get_success_data(api_client.create_credit_pool(
        create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product(
        product_code="DESKTOP-CC-11",
        license_kind="CONCURRENT_USE",
        edition="STANDARD",
        supports_offline=False,
        allows_derivative_works=False,
    )
    grant = setup_grant(org["id"], product["id"], seats_allocated=seats_allocated)
    org = activate_org(org["id"])
    grant = activate_grant(grant["id"], org["id"])
    return {"org": org, "pool": pool, "product": product, "grant": grant}


def add_user_on_grant(org_id, grant_id, username, email, level="VIEWER"):
    user = invite_user(org_id, grant_id, username=username, email=email, level=level)
    return accept_user(user["id"])


# ---------------------------------------------------------------------------
# Tier 2 variant: deployment-server org
# ---------------------------------------------------------------------------

def setup_server_org(product_major=11, grant_cores=32, product_code="SRV-11"):
    """Org ACTIVE with a DEPLOYMENT_SERVER grant ACTIVE. Returns context dict."""
    set_clock()
    org = get_success_data(api_client.create_org(create_org_payload(), PA_HEADERS))
    pool = get_success_data(api_client.create_credit_pool(
        create_credit_pool_payload(org["id"]), BA_HEADERS))
    product = setup_product(
        product_code=product_code,
        license_kind="DEPLOYMENT_SERVER",
        edition="STANDARD",
        major_version=product_major,
        base_seat_count=grant_cores,
        supports_offline=False,
        allows_derivative_works=False,
    )
    grant = setup_grant(org["id"], product["id"], seats_allocated=grant_cores)
    org = activate_org(org["id"])
    grant = activate_grant(grant["id"], org["id"])
    return {"org": org, "pool": pool, "product": product, "grant": grant}


def register_server(org_id, grant_id, hostname, role="GIS_SERVER", cores=4,
                    installed_major_version=11, auth_mode="SAML"):
    return get_success_data(api_client.create_deployment_server(
        create_deployment_server_payload(
            org_id, grant_id,
            hostname=hostname, role=role, cores_allocated=cores,
            installed_major_version=installed_major_version, auth_mode=auth_mode,
        ),
        DA_HEADERS,
    ))


def transition_server(server_id, target_status, **extra):
    payload = {"target_status": target_status}
    payload.update(extra)
    return api_client.transition_deployment_server(server_id, payload, DA_HEADERS)


def authorize_server(server_id):
    return get_success_data(transition_server(server_id, "AUTHORIZED"))


def create_compat_rule(consumer_role, consumer_major, dependency_role, allowed, strict):
    return get_success_data(api_client.create_version_compatibility_rule(
        {
            "consumer_role": consumer_role,
            "consumer_major_version": consumer_major,
            "dependency_role": dependency_role,
            "allowed_dependency_major_versions": allowed,
            "strict": strict,
        },
        PA_HEADERS,
    ))


# ---------------------------------------------------------------------------
# Tier 2 variant: analytics product with extension module
# ---------------------------------------------------------------------------

def add_analytics_grant_with_extension(org_id, ext_code="SPATIAL_ANALYST", ext_rate=3,
                                       seats=5, min_edition="STANDARD"):
    """Create an ANALYTICS-SUITE CONCURRENT_USE product, grant, activate it, and
    attach an ACTIVE extension grant. Returns (product, grant, ext_grant)."""
    product = setup_product(
        product_code="ANALYTICS-SUITE-11",
        license_kind="CONCURRENT_USE",
        edition="ADVANCED",
        supports_offline=False,
        allows_derivative_works=True,
        extension_modules=[{
            "extension_code": ext_code,
            "additional_credit_rate_per_op": ext_rate,
            "required_min_edition": min_edition,
        }],
    )
    grant = setup_grant(org_id, product["id"], seats_allocated=seats)
    grant = activate_grant(grant["id"], org_id)
    ext = get_success_data(api_client.create_extension_grant(
        {"license_grant_id": grant["id"], "extension_code": ext_code, "seats_allocated": seats},
        LA_HEADERS,
    ))
    return product, grant, ext

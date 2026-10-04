"""Cross-entity cascades: settle-driven org suspension and org termination
compensation."""
from test_helpers import (
    ApiErrorId,
    get_batch,
    get_grant,
    get_org,
    get_pool,
    get_success_data,
    get_user,
    make_named_user_headers,
    setup_base_chain,
    setup_with_key,
    setup_with_user,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    add_analytics_grant_with_extension,
    create_batch,
    list_batches,
    list_extension_grants,
    list_keys,
    set_clock,
    settle_batch,
    setup_org,
)
from test_helpers.factories import create_credit_pool_payload
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def _setup_overdraw_scenario():
    """Org ACTIVE, pool 1320; NAMED_USER grant with ACTIVE user+key; an
    ANALYTICS CONCURRENT_USE grant with an ACTIVE extension grant; two PENDING
    ROUTING batches of 100 units each; clock advanced one day.

    Capacity 1320 keeps the pool at LOW_CREDIT (available 20) rather than
    EXHAUSTED (available 0) after both reservations, so the §3.7 settle gate
    (refuses only while EXHAUSTED or OVERDRAWN) lets the first settle through
    and the chronological late fee then pushes available negative."""
    base = setup_base_chain(capacity=1320)
    org_id = base["org"]["id"]
    _prod, grant_an, ext = add_analytics_grant_with_extension(org_id)
    from test_helpers.fixtures import accept_user, invite_user, issue_key
    user = invite_user(org_id, base["grant"]["id"])
    user = accept_user(user["id"])
    key = issue_key(user["id"], org_id)
    headers = make_named_user_headers(user["id"])
    b1 = get_success_data(create_batch(org_id, key["id"], "ROUTING", 100, "rt-1", headers=headers))
    b2 = get_success_data(create_batch(org_id, key["id"], "ROUTING", 100, "rt-2", headers=headers))
    set_clock("2026-09-02T00:00:00Z")
    base.update({"user": user, "key": key, "b1": b1, "b2": b2,
                 "grant_an": grant_an, "ext": ext})
    return base


def test_settle_overdraw_suspends_org(api):
    """PRD section 3.7: "Because the two variants round differently and the
    late fee compounds divergence, a settle can push available credits
    negative even when creation passed the `ERR_INSUFFICIENT_CREDITS` check —
    which is exactly how the `OVERDRAWN` posture, and its organization
    cascade, become reachable."
    PRD section 3.7: "if the posture has become `OVERDRAWN`, the organization
    itself is moved to `SUSPENDED`".

    Design: Difficulty/transitive_cascade/settle_overdraw_suspends_org_and_cascades
    """
    base = _setup_overdraw_scenario()
    pool = get_pool(base["org"]["id"])
    data = get_success_data(settle_batch(base["b1"]["id"], pool["version"]))
    # routing 100 units raw: 50*8 + 50*5 = 650; one period late fee -> round(650*1.1)=715
    assert data["settled_credits"] == 715
    pool = get_pool(base["org"]["id"])
    assert pool["consumed_credits"] == 715
    assert pool["reserved_credits"] == 650
    # available = 1300 - 715 - 650 = -65 -> OVERDRAWN
    assert pool["posture"] == "OVERDRAWN"
    org = get_org(base["org"]["id"])
    assert org["status"] == "SUSPENDED"


def test_settle_overdraw_cascades_to_grants_users_keys(api):
    """PRD section 3.1: "Every named user of the organization who is
    currently `ACTIVE` is moved to `DISABLED`; each such user releases its
    seat (its home grant's `seats_in_use` is decremented by 1), every API key
    that user owns is moved to `REVOKED`, and every ContentItem that user owns
    which is `PUBLISHED` with sharing level `PUBLIC` is demoted to sharing
    level `ORGANIZATION`. In parallel, every LicenseGrant of the organization
    in `ACTIVE` status is moved to `SUSPENDED` — and because a grant
    suspension revokes that grant's extension grants, the full chain from
    organization to grant to extension grant spans three levels."

    Design: Difficulty/transitive_cascade/settle_overdraw_suspends_org_and_cascades
    """
    base = _setup_overdraw_scenario()
    pool = get_pool(base["org"]["id"])
    get_success_data(settle_batch(base["b1"]["id"], pool["version"]))

    assert get_grant(base["grant"]["id"])["status"] == "SUSPENDED"
    assert get_grant(base["grant_an"]["id"])["status"] == "SUSPENDED"
    exts = list_extension_grants(base["grant_an"]["id"])
    assert all(e["status"] == "REVOKED" for e in exts)
    user = get_user(base["user"]["id"])
    assert user["status"] == "DISABLED"
    assert get_grant(base["grant"]["id"])["seats_in_use"] == 0
    keys = list_keys(base["user"]["id"])
    assert keys and all(k["status"] == "REVOKED" for k in keys)
    # The still-pending second batch is left in place.
    assert get_batch(base["b2"]["id"])["status"] == "PENDING"


def test_org_terminate_reverses_pending_batches(api):
    """PRD section 3.1: "When termination proceeds, every `PENDING` credit
    batch of the organization is moved to `REVERSED`, releasing its reserved
    credits as compensation."

    Design: Corner/state_machines/org_terminate_reverses_pending_batches_compensation
    """
    base = setup_with_key()
    headers = make_named_user_headers(base["user"]["id"])
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 10, "gc-t", headers=headers))
    pool = get_pool(base["org"]["id"])
    assert pool["reserved_credits"] == 40
    resp = api.transition_org(base["org"]["id"], {"target_status": "TERMINATED"}, PA_HEADERS)
    data = validate_success(resp)
    assert data["status"] == "TERMINATED"
    pool = get_pool(base["org"]["id"])
    assert pool["reserved_credits"] == 0
    assert pool["consumed_credits"] == 0
    assert get_batch(batch["id"])["status"] == "REVERSED"


def test_org_terminate_blocked_by_published_content(api):
    """PRD section 3.1: "Termination is blocked while any ContentItem of the
    organization is in `PUBLISHED` or `FLAGGED` status — the attempt fails
    with `ERR_PUBLISHED_CONTENT_REMAINS` — because published content has
    visibility obligations that must be unwound first."

    Design: Corner/state_machines/org_terminate_reverses_pending_batches_compensation
    """
    from test_helpers.fixtures import create_published_item
    base = setup_with_user()
    create_published_item(base["org"]["id"], base["user"]["id"], title="Pub",
                          item_kind="WEB_MAP", storage_bytes=0)
    resp = api.transition_org(base["org"]["id"], {"target_status": "TERMINATED"}, PA_HEADERS)
    err = validate_error(resp, ApiErrorId.ERR_PUBLISHED_CONTENT_REMAINS)
    assert get_org(base["org"]["id"])["status"] == "ACTIVE"

"""Listing pagination, not-found behavior, and content visibility."""
from test_helpers import (
    ApiErrorId,
    LA_HEADERS,
    PA_HEADERS,
    get_success_data,
    make_named_user_headers,
    setup_base_chain,
    setup_with_user,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    accept_user,
    activate_grant,
    activate_org,
    create_draft_item,
    invite_user,
    set_clock,
    setup_grant,
    setup_org,
    setup_product,
)
from test_helpers.factories import create_credit_pool_payload
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]


def test_license_grants_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned: it defaults to 10, accepts a minimum of 1, and is capped at a
    maximum of 100. The `offset` parameter specifies how many items to skip
    and defaults to 0."
    PRD section 2.3: "List responses carry four pagination fields in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/license_grants_list_paginates_with_total_count_and_has_more
    """
    base = setup_base_chain()
    org_id = base["org"]["id"]
    setup_grant(org_id, base["product"]["id"], seats_allocated=3, valid_to_period=100)
    setup_grant(org_id, base["product"]["id"], seats_allocated=4, valid_to_period=100)

    resp = api.list_license_grants(LA_HEADERS, params={"organization_id": org_id, "limit": 2, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    resp = api.list_license_grants(LA_HEADERS, params={"organization_id": org_id, "limit": 2, "offset": 2})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_license_grants_list_defaults_to_limit_10(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned: it defaults to 10, accepts a minimum of 1, and is capped at a
    maximum of 100. The `offset` parameter specifies how many items to skip
    and defaults to 0."

    Design: Corner/entities/license_grants_list_paginates_with_total_count_and_has_more
    """
    base = setup_base_chain()
    org_id = base["org"]["id"]
    setup_grant(org_id, base["product"]["id"], seats_allocated=3, valid_to_period=100)
    setup_grant(org_id, base["product"]["id"], seats_allocated=4, valid_to_period=100)
    resp = api.list_license_grants(LA_HEADERS, params={"organization_id": org_id})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_content_item_get_unknown_id_returns_item_not_found(api):
    """PRD section 2.6: "Single-resource endpoints likewise resolve their path
    id first and return the entity-specific not-found error —
    `ERR_ORG_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`,
    `ERR_SERVER_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_KEY_NOT_FOUND`, `ERR_EV_NOT_FOUND`, or `ERR_PRODUCT_NOT_FOUND` — when
    it does not exist (all HTTP 404)."

    Design: Corner/entities/content_item_get_unknown_id_returns_item_not_found
    """
    set_clock()
    resp = api.get_content_item("00000000-0000-4000-8000-000000000000", PA_HEADERS)
    err = validate_error(resp, ApiErrorId.ERR_ITEM_NOT_FOUND)
    assert err.get("message"), "error payload must carry a human-readable message"


def test_private_item_invisible_to_other_named_user(api):
    """PRD section 3.9: "`PRIVATE` items are visible only to their owner,
    `PlatformAdmin`, and `ContentModerator`".
    PRD section 3.9: "Reading an item the caller cannot see answers
    `ERR_ITEM_NOT_FOUND` as if it did not exist."

    Design: Corner/roles/private_item_invisible_to_other_named_user
    """
    base = setup_with_user()
    org_id = base["org"]["id"]
    grant_id = base["grant"]["id"]
    owner = base["user"]
    dana = invite_user(org_id, grant_id, username="dana", email="dana@meridian.example", level="VIEWER")
    dana = accept_user(dana["id"])
    item = create_draft_item(org_id, owner["id"], title="Secret", item_kind="WEB_MAP", storage_bytes=0)

    resp = api.get_content_item(item["id"], make_named_user_headers(dana["id"]))
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_FOUND)

    resp = api.get_content_item(item["id"], make_named_user_headers(owner["id"]))
    validate_success(resp)

    rows = api.list_content_items(
        make_named_user_headers(dana["id"]), params={"organization_id": org_id}).json()["data"]
    assert rows == [], f"PRIVATE items must not appear in another user's list; got {rows}"


def test_private_item_visible_to_platform_admin(api):
    """PRD section 3.9: "`PRIVATE` items are visible only to their owner,
    `PlatformAdmin`, and `ContentModerator`".

    Design: Corner/roles/private_item_invisible_to_other_named_user
    """
    base = setup_with_user()
    item = create_draft_item(base["org"]["id"], base["user"]["id"], title="Secret2",
                             item_kind="WEB_MAP", storage_bytes=0)
    resp = api.get_content_item(item["id"], PA_HEADERS)
    data = validate_success(resp)
    assert data["id"] == item["id"]

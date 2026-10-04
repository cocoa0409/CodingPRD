"""Account creation defaults, envelope shape, not-found, and validation basics."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    admin_headers,
    assert_account,
    assert_member,
    create_account,
    create_account_payload,
    create_account_with_assigned_slot,
    get_success_data,
    make_extra_member_headers,
    validate_error,
    validate_paginated,
)


def test_success_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format in their JSON body" with meta.api_request_id,
    meta.api_request_timestamp, response_type ("object" for a single resource),
    and the resource under data.

    Design: Corner/endpoints/success_envelope_shape
    """
    account = get_success_data(
        api.create_account(
            create_account_payload(email="corner-env@x.com", region_code="LATAM", plan_tier="BASIC"),
            admin_headers(),
        )
    )
    resp = api.get_account(account["id"], admin_headers())
    body = resp.json()
    assert resp.status_code == 200
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert body["data"]["id"] == account["id"]


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" with response_type "error" and data.error_id / data.message.

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, admin_headers())
    body = resp.json()
    assert body["response_type"] == "error"
    error_data = validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_account_creation_defaults(api):
    """PRD §3.1: "A new account begins with `status` `ACTIVE` and
    `verification_posture` `VERIFIED`, and its three fiscal counters
    `extra_member_billed_cents`, `extra_member_credit_cents`, and
    `extra_member_net_revenue_cents` all read zero." PRD §3.1: "it records
    `billing_anchor_day` as the creation day-of-month clamped into the range 1
    through 28" and "creates the account's first `Member` with `member_role`
    `OWNER`, status `ACTIVE`". PRD §2.8: "the logical clock reads exactly
    2026-09-01T00:00:00Z".

    Design: Corner/entities/account_creation_defaults
    """
    account = get_success_data(
        api.create_account(
            create_account_payload(email="corner-acct@x.com", region_code="APAC", plan_tier="STANDARD"),
            admin_headers(),
        )
    )
    assert_account(account)
    assert account["status"] == "ACTIVE"
    assert account["verification_posture"] == "VERIFIED"
    assert account["version"] == 1
    assert account["billing_anchor_day"] == 1
    assert account["extra_member_billed_cents"] == 0
    assert account["extra_member_credit_cents"] == 0
    assert account["extra_member_net_revenue_cents"] == 0

    owner = get_success_data(api.get_member(account["owner_member_id"], admin_headers()))
    assert_member(owner)
    assert owner["member_role"] == "OWNER"
    assert owner["status"] == "ACTIVE"
    assert owner["account_id"] == account["id"]


def test_account_not_found_returns_404(api):
    """PRD §2.5: "a missing account yields `ERR_ACCOUNT_NOT_FOUND`".

    Design: Corner/entities/account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, admin_headers())
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)


def test_member_create_missing_required_field_rejected(api):
    """PRD §2.3: "every request that carries a body must be well-formed — all
    required fields present, enum values within their declared sets, and datetime
    fields parsing as ISO 8601; a malformed body is rejected with `ERR_VALIDATION`
    (HTTP 400)". PRD §3.3: "the `AccountOwner` adds household profiles by supplying
    a `display_name`".

    Design: Corner/entities/member_create_missing_required_field_rejected
    """
    account, owner_h = create_account(email="corner-req@x.com")
    resp = api.create_member(account["id"], {}, owner_h)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    data, meta = validate_paginated(api.list_members(account["id"], owner_h))
    assert meta["total_count"] == 1, "only the auto-created OWNER member should exist"


def test_member_list_pagination(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and `offset`"
    and "The `meta` object of every list response includes the four pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/member_list_pagination
    """
    account, owner_h = create_account(email="corner-page@x.com")
    get_success_data(api.create_member(account["id"], {"display_name": "Pat"}, owner_h))
    get_success_data(api.create_member(account["id"], {"display_name": "Sam"}, owner_h))

    data1, meta1 = validate_paginated(
        api.list_members(account["id"], owner_h, params={"limit": 2, "offset": 0})
    )
    assert len(data1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_members(account["id"], owner_h, params={"limit": 2, "offset": 2})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, carrying an undeclared role
    value, or carrying an entity-backed id that does not resolve is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    account, _ = create_account(email="corner-auth@x.com")
    resp = api.get_account(account["id"], {"X-User-ID": "x", "X-User-Role": "NoSuchRole"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_extra_member_cannot_add_member_forbidden(api):
    """PRD §2.1: "A request whose role is not listed for the endpoint ... is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: member creation
    (`POST /hv/accounts/{id}/members`) is authorized for AccountOwner only.

    Design: Corner/validations/extra_member_cannot_add_member_forbidden
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="corner-rbac1@x.com", extra_email="extra-rbac1@x.com"
    )
    extra_h = make_extra_member_headers(extra_id)
    resp = api.create_member(account["id"], {"display_name": "Nope"}, extra_h)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    data, meta = validate_paginated(api.list_members(account["id"], owner_h))
    assert meta["total_count"] == 2, "owner + one extra member"


def test_invalid_enum_plan_tier_rejected(api):
    """PRD §3.1: "A `PlatformAdmin` opens an account by supplying its `email`,
    `region_code` (one of `NA`, `LATAM`, `EMEA`, `APAC`), and `plan_tier` (one of
    `BASIC`, `STANDARD`, `PREMIUM`)". PRD §2.3: "enum values within their declared
    sets ... a malformed body is rejected with `ERR_VALIDATION` (HTTP 400)".

    Design: Corner/validations/invalid_enum_plan_tier_rejected
    """
    resp = api.create_account(
        {"email": "corner-enum@x.com", "region_code": "NA", "plan_tier": "GOLD"},
        admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

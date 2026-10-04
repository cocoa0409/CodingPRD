"""Entity shape, field constraints, and envelope tests (corner design: entities)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_app_payload,
    create_developer,
    create_developer_payload,
    make_admin_headers,
    make_developer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_developer_creation_missing_required_field_returns_400(api):
    """PRD §3.1: "A `PlatformAdmin` onboards a developer by registering a
    `DeveloperAccount` with the developer's legal `company_name`, a primary
    `contact_email`, and a `payout_currency` chosen from `USD`, `EUR`, or
    `GBP`."

    Design: Corner/entities/developer_creation_missing_required_field_returns_400
    """
    resp = api.create_developer(
        {"company_name": "NoEmail", "payout_currency": "USD"}, make_admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_developer_status_defaults_to_active(api):
    """PRD §3.1: "A new developer account is created in `ACTIVE` status and
    with a `lifetime_gross_cents` of zero."

    Design: Corner/entities/developer_status_defaults_to_active
    """
    resp = api.create_developer(
        create_developer_payload(
            company_name="Fresh", contact_email="fresh-status@example.com",
            payout_currency="EUR",
        ),
        make_admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["lifetime_gross_cents"] == 0, (
        f"expected lifetime_gross_cents 0, got {data['lifetime_gross_cents']}"
    )
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_app_system_fields_input_ignored(api):
    """PRD §3.1: "New apps are created in `DRAFT` status with `listing_status`
    `UNLISTED`, `performance_state` `COMPLIANT`, and `submitted_at` null."
    PRD §2.12: "A developer whose lifetime gross is at most 100000000 cents
    (one million dollars) is in tier `T0` — the platform takes zero revenue
    share."

    Design: Corner/entities/app_system_fields_input_ignored
    """
    developer = create_developer(company_name="SysFieldsDev")
    resp = api.create_app(
        create_app_payload(developer["id"], name="SysFields", category="PRODUCTIVITY"),
        make_developer_headers(developer["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["listing_status"] == "UNLISTED", (
        f"expected UNLISTED, got {data['listing_status']}"
    )
    assert data["revenue_share_tier"] == "T0", (
        f"expected T0, got {data['revenue_share_tier']}"
    )


def test_entity_not_found_returns_404(api):
    """PRD §2.7: "Existence — every `id` in path and body references an
    existing resource, validated left-to-right through the path
    (`ERR_NOT_FOUND`)."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_app(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_app_invalid_enum_category_rejected(api):
    """PRD §3.1: "a `Developer` creates an app by providing the `developer_id`
    of their own account, the app's public `name`, and a primary `category`
    chosen from `PRODUCTIVITY`, `MARKETING`, `FULFILLMENT`, `ANALYTICS`, or
    `FINANCE`."

    Design: Corner/entities/app_invalid_enum_category_rejected
    """
    developer = create_developer(company_name="BadEnumDev")
    resp = api.create_app(
        create_app_payload(developer["id"], name="BadEnum", category="GAMES"),
        make_developer_headers(developer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_app_list_pagination_envelope(api):
    """PRD §2.3: "The response envelope's `meta` object always carries the
    four pagination fields `limit`, `offset`, `total_count`, and `has_more`
    on list responses, regardless of whether the client supplied explicit
    pagination parameters."

    Design: Corner/entities/app_list_pagination_envelope
    """
    developer = create_developer(company_name="PgDev")
    dev_headers = make_developer_headers(developer["id"])
    api.create_app(
        create_app_payload(developer["id"], name="PgOne", category="MARKETING"),
        dev_headers,
    )
    api.create_app(
        create_app_payload(developer["id"], name="PgTwo", category="FINANCE"),
        dev_headers,
    )
    resp = api.list_apps(
        make_admin_headers(),
        params={"developer_id": developer["id"], "limit": 1, "offset": 0},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more true, got {meta['has_more']}"


def test_computed_lifetime_gross_ignores_input(api):
    """PRD §2.12: "Each developer account carries a computed
    `lifetime_gross_cents`, defined as the sum of `final_amount_cents` over
    every charge across all apps owned by that developer whose status is
    `INVOICED` or `SETTLED`."
    PRD §3.1: "A new developer account is created in `ACTIVE` status and with
    a `lifetime_gross_cents` of zero."

    Design: Corner/entities/computed_lifetime_gross_ignores_input
    """
    payload = create_developer_payload(
        company_name="Comp", contact_email="comp-gross@example.com", payout_currency="GBP"
    )
    payload["lifetime_gross_cents"] = 999999
    resp = api.create_developer(payload, make_admin_headers())
    data = validate_success(resp, expected_status=201)
    assert data["lifetime_gross_cents"] == 0, (
        f"expected lifetime_gross_cents 0, got {data['lifetime_gross_cents']}"
    )

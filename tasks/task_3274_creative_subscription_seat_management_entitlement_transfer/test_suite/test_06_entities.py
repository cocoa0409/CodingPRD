"""Entity creation, defaults, computed-field, listing, and FK filter tests
(breadth queue B, entities section)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_active_subscription,
    create_organization_payload,
    create_plan_payload,
    validate_success,
    validate_error,
    validate_paginated,
)


def test_organization_create_returns_201_and_defaults(api):
    """PRD: "An organization is born in `ACTIVE` status" and PRD: "Alongside
    its input fields the organization carries two computed aggregates:
    `storage_pool_gb`, the aggregate storage entitlement in gigabytes derived
    from its active subscriptions and add-ons, and `compliance_posture`,
    starting at `COMPLIANT`."

    Design: Corner/entities/organization_create_returns_201_and_defaults
    """
    b0, ba0 = bootstrap_org_and_admin()
    resp = api.create_organization(
        create_organization_payload(name="OC1", org_type="ENTERPRISE",
                                    primary_admin_id=ba0["id"]),
        SYS)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["compliance_posture"] == "COMPLIANT"


def test_organization_get_not_found_returns_404(api):
    """PRD: "Path-resource existence, validated left-to-right along the URL
    (`ERR_NOT_FOUND`)."

    Design: Corner/entities/organization_get_not_found_returns_404
    """
    bootstrap_org_and_admin()
    resp = api.get_organization(NON_EXISTENT_UUID, SYS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_plan_create_missing_required_field_returns_400(api):
    """PRD: "Required-field presence and typing (`ERR_INVALID_REQUEST`)." — a
    plan payload omitting the required `etf_rate_pct` is rejected.

    Design: Corner/entities/plan_create_missing_required_field_returns_400
    """
    payload = create_plan_payload(code="PX")
    payload.pop("etf_rate_pct")
    resp = api.create_plan(payload, SYS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_plan_defaults_max_devices_applied(api):
    """PRD: "`max_devices_per_seat` (the device activation cap per seat,
    defaulting to 2 when omitted)"

    Design: Corner/entities/plan_defaults_max_devices_applied
    """
    payload = create_plan_payload(code="PD")
    payload.pop("max_devices_per_seat")
    resp = api.create_plan(payload, SYS)
    data = validate_success(resp, expected_status=201)
    assert data["max_devices_per_seat"] == 2, (
        f"Expected default max_devices_per_seat 2, got "
        f"{data['max_devices_per_seat']}")


def test_computed_fields_input_ignored(api):
    """PRD: "Alongside its input fields the organization carries two computed
    aggregates: `storage_pool_gb`, the aggregate storage entitlement in
    gigabytes derived from its active subscriptions and add-ons"

    A client-supplied storage_pool_gb on creation is not honored; with no
    active subscriptions the computed pool is 0.

    Design: Corner/entities/computed_fields_input_ignored
    """
    b0, ba0 = bootstrap_org_and_admin()
    payload = create_organization_payload(name="OC2", org_type="TEAM",
                                          primary_admin_id=ba0["id"])
    payload["storage_pool_gb"] = 9999
    resp = api.create_organization(payload, SYS)
    data = validate_success(resp, expected_status=201)
    assert data["storage_pool_gb"] == 0, (
        f"Computed storage_pool_gb must be 0 at creation, got "
        f"{data['storage_pool_gb']}")


def test_admin_list_pagination_envelope(api):
    """PRD: "Paginated list-based responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/admin_list_pagination_envelope
    """
    bootstrap_org_and_admin()
    resp = api.list_admins(SYS, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_subscription_fk_reverse_reachable_via_filtered_list(api):
    """PRD: "| GET | `/licensing/subscriptions` | List subscriptions,
    filterable by org/plan/reseller/status" — filtering by org_id returns
    exactly that organization's subscriptions.

    Design: Corner/entities/subscription_fk_reverse_reachable_via_filtered_list
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="OC4", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@oc4.com", full_name="Org Admin")
    plan = create_plan(code="PX4", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    resp = api.list_subscriptions(SYS, params={"org_id": org["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert all(item["org_id"] == org["id"] for item in data)

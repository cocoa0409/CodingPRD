"""Authentication and role-authorization denials."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    get_success_data,
    validate_success,
    create_brand_owner,
    create_territory,
    create_territory_transfer,
    valuate_transfer,
    set_clock_default,
    seed_active_agreement,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]
BO = TEST_USERS["bottler_ops_headers"]
CM = TEST_USERS["customer_manager_headers"]


def test_bottler_ops_cannot_create_product_line(api):
    """PRD §2.1: "When the presented role is not on the endpoint's authorized
    list, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4 endpoint table: "POST | `/bottler/product-lines` | Create a product
    line | BrandOwnerAdmin".

    Design: Corner/rbac/bottler_ops_cannot_create_product_line
    """
    set_clock_default()
    bo = create_brand_owner()
    r = api_client.create_product_line(
        {
            "brand_owner_id": bo["id"],
            "line_code": "SNEAK-01",
            "concentrate_base_price_per_gallon": 1.0,
            "is_mandatory": False,
        },
        BO,
    )
    err = validate_error(r, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    assert r.status_code == 403


def test_customer_manager_cannot_approve_transfer(api):
    """PRD §2.1: "When the presented role is not on the endpoint's authorized
    list, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4 endpoint table: "POST | `/bottler/territory-transfers/{id}/approve` |
    Approve a VALUED transfer; blocked while any customer is DISPUTED |
    BrandOwnerAdmin".

    Design: Corner/rbac/customer_manager_cannot_approve_transfer
    """
    set_clock_default()
    bo = create_brand_owner()
    ter = create_territory(bo["id"])
    env = {"bo": bo, "territory": ter}
    tt = create_territory_transfer(env, reported_ebitda_cents=400000000)
    valuated = valuate_transfer(tt["id"], tt["version"])
    assert valuated["status"] == "VALUED"
    r = api_client.approve_transfer(tt["id"], CM)
    err = validate_error(r, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    after = get_success_data(api_client.get_territory_transfer(tt["id"], PA))
    assert after["status"] == "VALUED", "transfer status must be unchanged by denied call"


def test_create_brand_owner_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/create_brand_owner_missing_auth_header_unauthenticated
    """
    r = api_client.create_brand_owner(
        {"name": "NoAuth Inc", "home_country": "US"},
        headers={"Content-Type": "application/json"},
    )
    err = validate_error(r, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert r.status_code == 401

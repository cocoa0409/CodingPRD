"""Scoop shop lifecycle and ShopOperator ownership (PRD §3.8, §2.1)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_scoop_shop_payload, create_supply_order_payload,
    make_shop, make_site_approved_shop, make_operating_shop,
    make_shop_operator_headers,
)

FA = TEST_USERS["franchise_admin_headers"]


def test_shop_reject_site_closes_application(api):
    """PRD §3.8: "Site adjudication belongs to the `FranchiseAdmin`: approving
    moves the shop from `SITE_REVIEW` to `SITE_APPROVED`; rejecting moves it
    straight to the terminal `CLOSED`."
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/shop_reject_site_closes_application
    """
    shop = make_shop(name="Rejected Corner", credit_limit_cents=100000)
    rejected = validate_success(api.reject_site(shop["id"], FA))
    assert rejected["status"] == "CLOSED"
    resp = api.approve_site(shop["id"], FA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_shop_suspend_reopen_cycle(api):
    """PRD §3.8: "An operating shop cycles between `OPERATING` and `SUSPENDED`
    under the `FranchiseAdmin`'s suspend and reopen actions."

    Design: Corner/state_machines/shop_suspend_reopen_cycle
    """
    shop = make_operating_shop(name="YoYo Scoops", credit_limit_cents=100000)
    assert shop["status"] == "OPERATING"
    suspended = validate_success(api.suspend_shop(shop["id"], FA))
    assert suspended["status"] == "SUSPENDED"
    reopened = validate_success(api.reopen_shop(shop["id"], FA))
    assert reopened["status"] == "OPERATING"
    assert reopened["credit_limit_cents"] == 100000


def test_partner_shop_open_requires_verification(api):
    """PRD §3.8: "opening requires either a `FRANCHISEE` operator type or a
    verified nonprofit flag, failing with
    `ERR_NONPROFIT_VERIFICATION_REQUIRED` (HTTP 422) for an unverified
    `NONPROFIT_PARTNER`."

    Design: Corner/state_machines/partner_shop_open_requires_verification
    """
    shop = make_shop(name="Unverified Partner", operator_type="NONPROFIT_PARTNER",
                     nonprofit_verified=False, credit_limit_cents=100000)
    approved = validate_success(api.approve_site(shop["id"], FA))
    assert approved["status"] == "SITE_APPROVED"
    resp = api.open_shop(shop["id"], FA)
    validate_error(resp, ApiErrorId.ERR_NONPROFIT_VERIFICATION_REQUIRED)


def test_shop_operator_reads_own_shop(api):
    """PRD §2.1: "When `X-User-Role` is `ShopOperator`, `X-User-ID` is the `id`
    of the acting `ScoopShop`; ownership checks on any resource that references
    a `ScoopShop` compare the resource's foreign-key field (or the path's
    scoop-shop identifier) to `X-User-ID`."

    Design: Corner/rbac/shop_operator_reads_own_shop
    """
    shop = make_shop(name="Self Read", credit_limit_cents=100000)
    data = validate_success(api.get_scoop_shop(
        shop["id"], make_shop_operator_headers(shop["id"])))
    assert data["id"] == shop["id"]
    assert data["status"] == "SITE_REVIEW"


def test_shop_operator_cannot_touch_other_shop(api):
    """PRD §3.8: "A `ShopOperator` places an order for their own shop — the
    caller's `X-User-ID` must equal the scoop-shop identifier in the path,
    failing with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)".
    PRD §2.6: "a `ShopOperator` may only touch their own shop and its orders, and an audit may only be completed by the auditor who started it (`ERR_FORBIDDEN_OWNERSHIP`)".

    Design: Corner/validations/shop_operator_cannot_touch_other_shop
    """
    shop_a = make_shop(name="Shop A", credit_limit_cents=100000)
    shop_b = make_shop(name="Shop B", credit_limit_cents=100000)
    # Ownership (rung 3) fires before the nonexistent flavor id is even read.
    resp = api.create_supply_order(
        shop_b["id"],
        create_supply_order_payload(
            [{"flavor_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
              "quantity_pints": 1}]),
        make_shop_operator_headers(shop_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

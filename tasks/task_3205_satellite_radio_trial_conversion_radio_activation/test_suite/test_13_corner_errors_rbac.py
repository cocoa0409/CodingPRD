"""Corner — errors and RBAC denials."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, NON_EXISTENT_ID, factories, fixtures
from test_helpers.fixtures import ADMIN
from test_helpers.test_users import make_customer_headers, make_dealer_headers


def test_error_forbidden_owner_cross_customer_cancel(api):
    """PRD §2.1: "A customer-scoped action (cancel, suspend, resume,
    save-offer acceptance, disclosure acknowledgment, or listing one's own
    subscriptions) performed against a subscription whose `customer_id` does
    not equal the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNER`
    (HTTP 403)."

    Design: Corner/errors/error_forbidden_owner_cross_customer_cancel
    """
    owner = fixtures.create_customer(api)
    intruder = fixtures.create_customer(api)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", price_cents=3000,
        auto_renew_default=False,
    )
    sub = fixtures.create_streaming_subscription(api, owner, plan,
                                                 auto_renew=False)

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "END_OF_TERM"},
        make_customer_headers(intruder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER)

    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert sub_now["status"] == "ACTIVE"


def test_error_reference_not_found_body_fk(api):
    """PRD §2.9: "then foreign keys supplied in the request body such as
    `plan_id`, `package_tier_id`, `vehicle_id`, `automaker_id`, and
    `offer_step_id` (`ERR_REFERENCE_NOT_FOUND`)".
    PRD §5: ERR_REFERENCE_NOT_FOUND is HTTP 404.

    Design: Corner/errors/error_reference_not_found_body_fk
    """
    customer = fixtures.create_customer(api)
    resp = api.create_subscription(
        {"customer_id": customer["id"], "plan_id": NON_EXISTENT_ID,
         "auto_renew": False},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_customer_cannot_create_campaign(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /api/v1/offer-campaigns is authorized for PlatformAdmin
    only.

    Design: Corner/rbac/customer_cannot_create_campaign
    """
    customer = fixtures.create_customer(api)
    resp = api.create_offer_campaign(
        factories.create_campaign_payload(lifecycle_phase="WINBACK"),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_dealer_cannot_dispatch_signals(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /api/v1/_signals/dispatch is authorized for SystemOperator
    only.

    Design: Corner/rbac/dealer_cannot_dispatch_signals
    """
    dealer = fixtures.create_dealer(api)
    resp = api.dispatch_signals(make_dealer_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` is missing or is not one of
    these values, or whose `X-User-ID` is missing for a role whose identity
    is entity-backed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "Authentication comes first: a missing or unknown role header
    ... yields `ERR_UNAUTHENTICATED` before anything else is examined".

    A request with no role header gets 401, never a 404 leak on the unknown
    path id.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.get_automaker(
        NON_EXISTENT_ID, headers={"Content-Type": "application/json"}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

"""Corner — entities: defaults, uniqueness, format sanity, not-found, listing."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    assert_append_only_fields,
    factories,
    fixtures,
)
from test_helpers.fixtures import ADMIN
from test_helpers.test_users import ANONYMOUS_HEADERS as ANONYMOUS


def test_customer_creation_applies_household_default(api):
    """PRD §3.1: "they may declare a `household_size`, which defaults to 1,
    must be at least 1, and later drives family-discount eligibility. A
    customer's `status` begins `ACTIVE`".
    PRD §2.4: "a `version` integer that starts at creation".

    Omitting household_size yields the default; status and version start at
    their declared initial values.

    Design: Corner/entities/customer_creation_applies_household_default
    """
    resp = api.create_customer(
        {"email": factories.unique_email(), "full_name": "D One"}, ANONYMOUS
    )
    data = validate_success(resp, expected_status=201)
    assert data["household_size"] == 1
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_duplicate_vin_rejected(api):
    """PRD §2.4: "Certain string fields are unique across their entity type
    and a duplicate submission is rejected with `ERR_DUPLICATE` (HTTP 409):
    ... a vehicle's `vin`".

    Design: Corner/entities/duplicate_vin_rejected
    """
    customer = fixtures.create_customer(api)
    automaker = fixtures.create_automaker(api)
    vin = factories.unique_vin()
    get_success_data(
        api.create_vehicle(
            factories.create_vehicle_payload(automaker["id"], customer["id"],
                                             vin=vin),
            ADMIN,
        )
    )
    resp = api.create_vehicle(
        factories.create_vehicle_payload(automaker["id"], customer["id"],
                                         vin=vin, condition="USED"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_invalid_enum_hardware_generation_rejected(api):
    """PRD §3.2: "A radio is registered against a vehicle with a unique,
    non-empty `esn` (its electronic serial number), the `vehicle_id` of the
    vehicle it is installed in, and a `hardware_generation` of `GEN1`,
    `GEN2`, or `GEN3`."
    PRD §2.9: "finally field-level format sanity ... reported as
    `ERR_INVALID_REQUEST`."

    A hardware_generation outside the declared enum fails with 400.

    Design: Corner/entities/invalid_enum_hardware_generation_rejected
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(api)
    resp = api.create_radio(
        {"esn": factories.unique_esn(), "vehicle_id": vehicle["id"],
         "hardware_generation": "GEN9"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_immutable_offer_redemption_has_no_update(api):
    """PRD §2.4: "Three entity families are deliberately lighter-weight and
    carry only `id` and `created_at` — no `updated_at`, no `version`:
    `OfferRedemption`, `BillingLedgerEntry`, and `DisclosureRecord`. These are
    append-only records (a redemption, a ledger posting, a disclosure event),
    so there is nothing to mutate after creation and therefore nothing to
    version."

    A redemption created through an offer redemption carries exactly the
    append-only field set, and the campaign lookup on an unknown id returns
    ERR_NOT_FOUND (path-id existence ordering).

    Design: Corner/entities/immutable_offer_redemption_has_no_update
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=3000)
    campaign, step = fixtures.create_active_campaign(api, plan)
    redemption = validate_success(
        api.redeem_offer(
            campaign["id"],
            {"offer_step_id": step["id"], "customer_id": customer["id"]},
            fixtures.customer_headers(customer),
        ),
        expected_status=201,
    )
    assert_append_only_fields(redemption, "offer redemption")
    assert redemption["subscription_id"]
    assert redemption["redeemed_price_cents"] == 3000

    resp = api.get_offer_campaign(NON_EXISTENT_ID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_get_missing_resource_returns_not_found(api):
    """PRD §2.9: "every path-template identifier is resolved left to right
    (`ERR_NOT_FOUND`)".
    PRD §5: ERR_NOT_FOUND is HTTP 404.

    A well-formed but unknown radio id returns ERR_NOT_FOUND.

    Design: Corner/entities/get_missing_resource_returns_not_found
    """
    resp = api.get_radio(NON_EXISTENT_ID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_subscriptions_pagination_envelope(api):
    """PRD §2.3: "Every list response includes the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more` in `meta`, where
    `total_count` is the size of the unpaginated result set and `has_more`
    indicates whether further records exist beyond the current page."

    Two subscriptions, limit=1 offset=1: one item, total_count 2,
    has_more false.

    Design: Corner/entities/list_subscriptions_pagination_envelope
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=1000)
    headers = fixtures.customer_headers(customer)
    fixtures.create_streaming_subscription(api, customer, plan, auto_renew=False)
    fixtures.create_streaming_subscription(api, customer, plan, auto_renew=False)

    resp = api.list_customer_subscriptions(
        customer["id"], headers, params={"limit": 1, "offset": 1}
    )
    items, meta = validate_paginated(resp)
    assert len(items) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

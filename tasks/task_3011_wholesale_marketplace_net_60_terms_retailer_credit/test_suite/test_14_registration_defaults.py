"""Queue B (Corner/entities): registration defaults, not-found, request-shape,
listing pagination, and Payment immutability."""

from test_helpers import (
    ADMIN,
    ANON,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_payment,
    active_brand,
    brand_payload,
    get_success_data,
    make_brand_headers,
    make_retailer_headers,
    order_invoice,
    order_line,
    place_order,
    register_retailer,
    retailer_payload,
    ship_order,
    validate_error,
    validate_paginated,
    validate_success,
    verified_retailer_with_account,
)


def test_retailer_created_with_pending_defaults(api):
    """PRD §3.1: "A freshly registered retailer lands in `PENDING` with both
    document sub-states — `storefront_proof_status` and `resale_cert_status` —
    also `PENDING`, and a `verification_resubmission_count` of zero."
    PRD §2.4: "an `id` that is a server-minted UUID with no type prefix; a
    `created_at` ISO 8601 UTC timestamp with three fractional digits recording
    when the resource was created; an `updated_at` ISO 8601 UTC timestamp
    refreshed on every mutation; and a `version` integer that starts low and
    increments by one on every mutation to the resource."

    Design: Corner/entities/retailer_created_with_pending_defaults
    """
    created = validate_success(api.create_retailer(retailer_payload(), ANON), 201)
    assert created["verification_status"] == "PENDING"
    assert created["storefront_proof_status"] == "PENDING"
    assert created["resale_cert_status"] == "PENDING"
    assert created["verification_resubmission_count"] == 0
    assert created["return_rate"] == 0

    fetched = validate_success(api.get_retailer(created["id"], ADMIN))
    assert fetched["verification_status"] == "PENDING"
    assert fetched["verification_resubmission_count"] == 0


def test_brand_created_in_draft_with_referral_code(api):
    """PRD §3.2: "At creation the brand is in `DRAFT` and the server mints its
    `referral_code`, the code the brand shares with retailers it recruits to
    the platform."

    Design: Corner/entities/brand_created_in_draft_with_referral_code
    """
    created = validate_success(
        api.create_brand(brand_payload(default_case_pack_size=6, lead_time_days=3,
                                       payout_delay_days=14),
                         make_brand_headers("new-brand")),
        201,
    )
    assert created["onboarding_status"] == "DRAFT"
    assert isinstance(created["referral_code"], str) and created["referral_code"]
    assert created["payout_balance_cents"] == 0
    assert created["abuse_flags"] == 0

    fetched = validate_success(api.get_brand(created["id"], ADMIN))
    assert fetched["referral_code"] == created["referral_code"]
    assert fetched["onboarding_status"] == "DRAFT"


def test_retailer_get_not_found_returns_404(api):
    """PRD §2.6: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
    the first identifier in the path that does not resolve, and the same
    left-to-right rule applies to identifiers referenced inside a request
    body."

    Design: Corner/entities/retailer_get_not_found_returns_404
    """
    response = api.get_retailer(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, 404)


def test_retailer_registration_rejects_bad_enum(api):
    """PRD §3.1: "A prospective retail buyer joins the marketplace by
    self-registering as `Anonymous`, supplying the business's `legal_name`, its
    `store_type` (one of `BRICK_AND_MORTAR`, `ONLINE`, or `HYBRID`), the
    storefront `address` together with its geographic coordinates `lat` and
    `lng`, a `storefront_proof_url` pointing at evidence of an active
    storefront (a photo, a lease, or a live web shop), and a
    `resale_certificate_no` carrying the state resale certificate or seller's
    permit number."

    Design: Corner/entities/retailer_registration_rejects_bad_enum
    """
    response = api.create_retailer(retailer_payload(store_type="POP_UP"), ANON)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    data, meta = validate_paginated(api.list_retailers(ADMIN))
    assert data == [] and meta["total_count"] == 0


def test_retailers_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; when omitted it defaults to 10, and it accepts a minimum of 1 and
    a maximum of 100. The `offset` parameter sets how many items to skip and
    defaults to 0."
    PRD §2.3: "The `meta` object of every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/retailers_list_pagination_envelope
    """
    register_retailer(api)
    register_retailer(api)

    data, meta = validate_paginated(api.list_retailers(ADMIN, {"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(api.list_retailers(ADMIN, {"limit": 1, "offset": 1}))
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert data2[0]["id"] != data[0]["id"]


def test_payment_entity_immutable_no_version(api):
    """PRD §2.4: "The Payment resource is the single exception: because a
    payment record is an immutable ledger entry once recorded, it carries only
    `id` and `created_at`; it has neither `updated_at` nor `version`."
    PRD §3.9: "Each accepted payment creates an immutable `Payment` record
    bound to the invoice through its `invoice_id`, stamped with the
    logical-clock `paid_at`, increases the invoice's `paid_amount_cents` by the
    amount, recomputes `balance_cents` as `amount_due_cents` minus
    `paid_amount_cents`, and recomputes the credit account's
    `available_cents`."

    Design: Corner/entities/payment_entity_immutable_no_version
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 1)])
    ship_order(api, order["id"], brand["id"])
    invoice = order_invoice(api, order["id"])

    payment = validate_success(
        api.record_payment(invoice["id"], {"amount_cents": 4000},
                           make_retailer_headers(retailer["id"])),
        201,
    )
    assert payment["amount_cents"] == 4000
    assert payment["invoice_id"] == invoice["id"]
    assert_payment(payment)

    listed = get_success_data(api.list_invoice_payments(invoice["id"], ADMIN))
    assert len(listed) == 1 and listed[0]["id"] == payment["id"]

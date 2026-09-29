"""Validations: boundary instants, conditional gates and the top rungs of precedence."""

from test_helpers import (
    ADMIN_HEADERS,
    CHANNEL_KIND_DIRECT,
    CHANNEL_KIND_NDC_AGGREGATOR,
    DISTRIBUTION_MANAGER_HEADERS,
    FILING_ACTIVE,
    FULFILLMENT_RESERVED,
    NON_EXISTENT_UUID,
    OFFER_ORDERED,
    OFFER_PUBLISHED,
    PARTNER_TYPE_CORPORATE,
    PAYMENT_ACTION_CAPTURE,
    PAYMENT_AUTHORIZED,
    PRICING_ANALYST_HEADERS,
    ROLE_PLATFORM_ADMIN,
    VALIDITY_IN_EFFECT,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    headers_empty_user_id,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_BASIS = "YCORN01"
CORNER_TOTAL_CENTS = 46585
SALE_END = "2026-10-01T00:00:00.000Z"
ONE_MS_EARLIER = "2026-09-30T23:59:59.999Z"
TRAVEL_END = "2026-12-31T00:00:00.000Z"
PAST_TRAVEL_END = "2027-01-01T00:00:00.000Z"


def _corner_channel(api):
    return fx.create_ndc_channel(api, with_surcharge_rules=False)


def _corner_agency(api):
    return fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )


def _acme_corporate(api):
    return fx.create_partner(
        api,
        partner_name="Acme Corner Industries",
        partner_type=PARTNER_TYPE_CORPORATE,
        iata_code="55555552",
        home_country="DE",
    )


def _offer_count(api, channel_id):
    _rows, meta = validate_paginated(
        api.list_offers(headers=ADMIN_HEADERS, params={"channel_id": channel_id})
    )
    return meta["total_count"]


def _order_count(api):
    _rows, meta = validate_paginated(api.list_orders(headers=ADMIN_HEADERS))
    return meta["total_count"]


def test_a_capture_one_cent_short_of_the_total_moves_nothing(api):
    """PRD §3.6: "A capture advances `AUTHORIZED → PAID` and requires that `payment_amount_cents`
    equal the source offer's `total_cents` — the same figure the order froze into
    `net_revenue_cents` — with any other amount rejected as `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.6: "On success `paid_amount_cents` becomes the captured amount, the channel's
    `booking_count` increases by 1, and then, in this order: if the order names an agreement, that
    agreement's `cumulative_net_revenue_cents` increases by the order's `net_revenue_cents` and the
    incentive accrual of §3.3 re-runs and rewrites `incentive_accrued_cents` and `incentive_tier`
    (a capture can only raise the balance, so the tier may rise and `tier_downgrade_count` is left
    untouched); and finally the channel's distribution-cost figures re-run, rewriting
    `activity_cost_cents`, `cost_per_booking_flat_cents` and `cost_per_booking_activity_cents`."

    Design: Corner/validations/corner_capture_one_cent_short_of_the_offer_total_is_rejected
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    agreement = fx.create_signed_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=1000000,
        target_net_revenue_cents=5000000,
    )
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    assert order["net_revenue_cents"] == CORNER_TOTAL_CENTS

    short = api.post_order_payment(
        order["id"],
        f.payment_payload(PAYMENT_ACTION_CAPTURE, CORNER_TOTAL_CENTS - 1),
        headers=headers,
    )
    validate_error(short, ApiErrorId.PAYMENT_AMOUNT_MISMATCH)

    untouched = fx.read_order(api, order["id"], headers=headers)
    assert untouched["payment_status"] == PAYMENT_AUTHORIZED
    assert untouched["paid_amount_cents"] == 0
    assert untouched["version"] == 1

    ledger = fx.read_channel(api, channel["id"])
    assert ledger["booking_count"] == 0
    assert ledger["cost_per_booking_flat_cents"] == 0

    balance = fx.read_agreement(api, agreement["id"])
    assert balance["cumulative_net_revenue_cents"] == 0
    assert balance["incentive_accrued_cents"] == 0


def test_the_sale_window_closes_on_its_own_end_instant(api):
    """PRD §3.5: "The logical clock must sit inside the filing's half-open sale window — at or
    after `sale_from` and strictly before `sale_to` — else `ERR_FARE_SALE_WINDOW_CLOSED`."
    PRD §3.2: "Four instants define its two windows: `sale_from` and `sale_to` bound the half-open
    sale window, and `travel_from` and `travel_to` bound the closed travel window, with `sale_to`
    required to be strictly after `sale_from` and `travel_to` required to be at or after
    `travel_from`."

    Design: Corner/validations/corner_offer_construction_at_the_sale_window_end_instant_is_rejected
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])

    fx.set_clock(api, SALE_END)
    payload = f.offer_payload(
        channel["id"],
        partner["id"],
        filing["id"],
        departure_date="2026-11-15T00:00:00.000Z",
    )
    closed = api.create_offer(payload, headers=headers)
    validate_error(closed, ApiErrorId.FARE_SALE_WINDOW_CLOSED)
    # The upper bound is exclusive, not a filing-state problem.
    assert closed.json()["data"]["error_id"] != ApiErrorId.FARE_FILING_NOT_ACTIVE
    assert fx.read_filing(api, filing["id"])["status"] == FILING_ACTIVE
    assert _offer_count(api, channel["id"]) == 0

    # One millisecond earlier is still inside the half-open window.
    fx.set_clock(api, ONE_MS_EARLIER)
    inside = validate_success(
        api.create_offer(payload, headers=headers), expected_status=201
    )
    assert inside["total_cents"] == CORNER_TOTAL_CENTS
    assert _offer_count(api, channel["id"]) == 1


def test_the_travel_window_includes_its_own_end_instant(api):
    """PRD §3.5: "The requested `departure_date` must sit inside the filing's closed travel window,
    at or after `travel_from` and at or before `travel_to`, else
    `ERR_TRAVEL_DATE_OUT_OF_WINDOW`."
    PRD §3.5: "The trip itself is described by `trip_origin` and `trip_destination`, each exactly
    three uppercase letters, a `departure_date` instant, and a requested `cabin` of `ECONOMY`,
    `PREMIUM` or `BUSINESS`."

    Design: Corner/validations/corner_departure_outside_the_travel_window_is_rejected
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])

    past_end = api.create_offer(
        f.offer_payload(
            channel["id"],
            partner["id"],
            filing["id"],
            departure_date=PAST_TRAVEL_END,
        ),
        headers=headers,
    )
    validate_error(past_end, ApiErrorId.TRAVEL_DATE_OUT_OF_WINDOW)
    assert _offer_count(api, channel["id"]) == 0

    # travel_to itself is inside the closed window.
    on_the_bound = validate_success(
        api.create_offer(
            f.offer_payload(
                channel["id"], partner["id"], filing["id"], departure_date=TRAVEL_END
            ),
            headers=headers,
        ),
        expected_status=201,
    )
    assert on_the_bound["total_cents"] == CORNER_TOTAL_CENTS
    assert _offer_count(api, channel["id"]) == 1


def _acme_offer(api, traceability_required, account_code):
    channel = _corner_channel(api)
    corporate = _acme_corporate(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    contract = fx.create_contract(
        api,
        corporate["id"],
        filing["id"],
        effective_to="2026-12-31T00:00:00.000Z",
        account_code=account_code,
        max_offer_total_cents=1000000,
        traceability_required=traceability_required,
        tracking_ref_prefix="ACME-",
        min_content_tier_rank=1,
    )
    assert contract["validity_state"] == VALIDITY_IN_EFFECT
    offer = fx.construct_offer(
        api,
        channel["id"],
        corporate["id"],
        filing["id"],
        corporate_contract_id=contract["id"],
    )
    assert offer["total_cents"] == CORNER_TOTAL_CENTS
    published = fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES)
    assert published["status"] == OFFER_PUBLISHED
    return contract, published


def test_a_reference_with_the_wrong_prefix_is_its_own_distinct_failure(api):
    """PRD §3.4: "Traceability is enforced one step later, at order time: when the offer's contract
    has `traceability_required` set to true, the order request must supply `corporate_tracking_ref`,
    and omitting it is `ERR_CORPORATE_TRACKING_REF_MISSING`; when it is supplied it must begin with
    the contract's `tracking_ref_prefix`, and a reference with the wrong prefix is
    `ERR_CORPORATE_TRACKING_REF_INVALID`."
    PRD §3.4: "`tracking_ref_prefix` defaults to the literal `CORP-`, must be 1 to 12 characters,
    and pins the required leading characters of that reference."

    Design: Corner/validations/corner_tracking_ref_with_the_wrong_prefix_is_rejected
    """
    contract, offer = _acme_offer(api, True, "ACME-DE")

    wrong = api.create_order(
        f.order_payload(
            offer["id"],
            disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES,
            corporate_tracking_ref="GLOBEX-778",
        ),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(wrong, ApiErrorId.CORPORATE_TRACKING_REF_INVALID)
    # A present-but-wrong reference is not the missing-reference failure.
    assert (
        wrong.json()["data"]["error_id"] != ApiErrorId.CORPORATE_TRACKING_REF_MISSING
    )

    assert fx.read_contract(api, contract["id"])["validity_state"] == VALIDITY_IN_EFFECT
    assert fx.read_offer(api, offer["id"])["status"] == OFFER_PUBLISHED
    assert _order_count(api) == 0


def test_a_contract_that_waives_traceability_accepts_a_bare_order(api):
    """PRD §3.4: "`traceability_required` defaults to true and demands that every order placed
    under the contract carry a tracking reference."
    PRD §3.6: "And when the ordering partner's `partner_type` is `TRAVEL_AGENCY`, an agreement in
    `SIGNED` status must exist for the offer's partner-and-channel pair; without one the order is
    refused with `ERR_AGREEMENT_NOT_SIGNED`, which is the mechanism by which a suspended agency
    stops selling."
    PRD §3.6: "On creation the service copies `channel_id` and `partner_id` from the source offer —
    a client never supplies them — and resolves `agency_agreement_id` to the identifier of the
    `SIGNED` agreement for that partner-and-channel pair, leaving it null when the ordering partner
    is not a travel agency."

    Design: Corner/validations/corner_contract_without_traceability_accepts_an_order_with_no_ref
    """
    _contract, offer = _acme_offer(api, False, "ACME-OPEN")

    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES)
    assert order["payment_status"] == PAYMENT_AUTHORIZED
    assert order["fulfillment_status"] == FULFILLMENT_RESERVED
    assert order["corporate_tracking_ref"] is None
    # A CORPORATE partner needs no agency agreement at all.
    assert order["agency_agreement_id"] is None
    assert order["net_revenue_cents"] == CORNER_TOTAL_CENTS
    assert fx.read_offer(api, offer["id"])["status"] == OFFER_ORDERED


def test_authentication_then_authorization_then_shape_speak_before_lookups(api):
    """PRD §2.10: "1. **Authentication** — both context headers present and non-empty
    (`ERR_UNAUTHENTICATED`, 401)."
    PRD §2.10: "2. **Authorization** — the role is one of the six, the role is listed for the
    endpoint, and for the entity-backed roles the `X-User-ID` ownership comparison of §2.1 holds
    (`ERR_UNAUTHORIZED`, 403)."
    PRD §2.10: "3. **Request shape** — every required field present, every enum value inside its
    declared domain, every numeric and string constraint from the field definitions honoured,
    `limit` within 1 to 100 inclusive and `offset` at least 0 (`ERR_INVALID_REQUEST`, 400)."
    PRD §2.10: "28. **Channel code uniqueness** — `ERR_DUPLICATE_CHANNEL_CODE` (409), on `POST
    /channels`."

    Design: Corner/validations/corner_auth_and_shape_rungs_outrank_lookup_and_business_rungs
    """
    channel = _corner_channel(api)
    duplicate = {"channel_code": channel["channel_code"], "channel_kind": CHANNEL_KIND_DIRECT}

    # Rung 1 beats both the role check and the duplicate-code check.
    unauthenticated = api.create_channel(
        duplicate, headers=headers_empty_user_id(ROLE_PLATFORM_ADMIN)
    )
    validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED)

    # Rung 2 beats the duplicate-code check even though the code really is taken.
    unauthorized = api.create_channel(duplicate, headers=PRICING_ANALYST_HEADERS)
    validate_error(unauthorized, ApiErrorId.UNAUTHORIZED)
    assert (
        unauthorized.json()["data"]["error_id"] != ApiErrorId.DUPLICATE_CHANNEL_CODE
    )

    # Rung 3 beats path resolution: the bad enum is reported, not the ghost filing.
    malformed = api.set_fare_filing_state(
        NON_EXISTENT_UUID,
        f.filing_state_payload("NOT_A_STATE"),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(malformed, ApiErrorId.INVALID_REQUEST)
    assert malformed.json()["data"]["error_id"] != ApiErrorId.FARE_FILING_NOT_FOUND

    # None of the three refused calls touched stored state.
    reread = fx.read_channel(api, channel["id"])
    assert reread["channel_kind"] == CHANNEL_KIND_NDC_AGGREGATOR
    _rows, meta = validate_paginated(api.list_fare_filings(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0

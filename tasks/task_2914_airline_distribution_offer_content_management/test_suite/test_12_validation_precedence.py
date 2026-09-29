"""Validation precedence: which of two simultaneously broken checks is reported."""

from test_helpers import (
    ADMIN_HEADERS,
    CABIN_BUSINESS,
    CONTENT_TIER_RESTRICTED,
    CONTENT_TIER_STANDARD,
    FILING_ACTIVE,
    FILING_DRAFT,
    FILING_FILED,
    FILING_SUSPENDED,
    OFFER_ORDERED,
    OFFER_PUBLISHED,
    PARTNER_TYPE_CORPORATE,
    VALIDITY_IN_EFFECT,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)

CONTRACT_END = "2026-12-01T00:00:00.000Z"
CAP_CENTS = 100000
BIG_FARE_CENTS = 9000000


def _corporate_partner(api, iata_code="CORP-0001"):
    return fx.create_partner(
        api,
        partner_name="Zenith Industries AG",
        partner_type=PARTNER_TYPE_CORPORATE,
        iata_code=iata_code,
        home_country="CH",
    )


def _capped_contract(api, corporate_partner_id, filing_id, **overrides):
    contract = fx.create_contract(
        api,
        corporate_partner_id,
        filing_id,
        effective_to=CONTRACT_END,
        account_code="ZEN-CAP",
        max_offer_total_cents=CAP_CENTS,
        traceability_required=True,
        tracking_ref_prefix="CORP-",
        **overrides,
    )
    assert contract["validity_state"] == VALIDITY_IN_EFFECT
    return contract


def _no_offer_exists(api):
    _rows, meta = validate_paginated(api.list_offers(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_a_draft_filing_is_reported_before_the_corporate_fiscal_cap(api):
    """PRD §2.10: "Requests are validated in a strict, globally fixed precedence order, and
    the **first** failing check determines the response."
    PRD §2.10: "**Fare filing still sellable** — the referenced filing's `status` is
    `ACTIVE`, else `ERR_FARE_FILING_NOT_ACTIVE` (409). Applies to `POST /offers` and `POST
    /offers/{id}/publish`."
    PRD §2.10: "**Corporate fiscal cap** — `ERR_CONTRACT_CAP_EXCEEDED` (422), on `POST
    /offers`."
    PRD §3.4: "`max_offer_total_cents`, strictly greater than 0, is a fiscal cap: an offer
    priced under this contract may not exceed that total, and one that does is rejected with
    `ERR_CONTRACT_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/fare_filing_not_active_outranks_contract_cap_exceeded
    """
    channel = fx.create_ndc_channel(api)
    corporate = _corporate_partner(api)
    filing = fx.create_fare_filing(
        api,
        fare_basis_code="PRIV01",
        cabin=CABIN_BUSINESS,
        base_amount_cents=BIG_FARE_CENTS,
        min_content_tier_rank=2,
        refundable=True,
        is_private=True,
    )
    assert filing["status"] == FILING_DRAFT
    contract = _capped_contract(api, corporate["id"], filing["id"], min_content_tier_rank=2)
    headers = agency_headers(corporate["id"])

    payload = f.offer_payload(
        channel["id"],
        corporate["id"],
        filing["id"],
        cabin=CABIN_BUSINESS,
        corporate_contract_id=contract["id"],
    )
    refused = api.create_offer(payload, headers=headers)
    # The state check at step 8 outranks the fiscal check at step 31.
    validate_error(refused, ApiErrorId.FARE_FILING_NOT_ACTIVE)
    assert refused.json()["data"]["error_id"] != ApiErrorId.CONTRACT_CAP_EXCEEDED
    _no_offer_exists(api)
    assert fx.read_filing(api, filing["id"])["status"] == FILING_DRAFT

    # The fiscal check really was broken too: it surfaces the moment the filing sells.
    fx.drive_filing(api, filing["id"], FILING_FILED)
    activated = fx.drive_filing(api, filing["id"], FILING_ACTIVE)
    assert activated["status"] == FILING_ACTIVE

    # 9,000,000 * 1.035 = 9,315,000 plus the clamped 1,200 surcharge, against a cap of
    # 100,000.
    over_cap = api.create_offer(payload, headers=headers)
    validate_error(over_cap, ApiErrorId.CONTRACT_CAP_EXCEEDED)
    _no_offer_exists(api)


def test_the_offer_path_reports_filing_then_tier_then_cap(api):
    """PRD §2.10: "Note the consequences of this ordering on the offer-construction path in
    particular: an offer request that names a suspended filing *and* an out-of-tier channel
    *and* an over-cap total reports the filing problem first (step 8), then the tier problem
    (step 27), and only reaches the cap (step 31) once the earlier checks pass."
    PRD §2.10: "**Content access tier** — `ERR_CONTENT_TIER_INSUFFICIENT` (422), on `POST
    /offers`."
    PRD §3.1: "The content-policy revision accepts any subset of `content_tier`,
    `servicing_parity_change`, `servicing_parity_refund` and `required_disclosure_codes`,
    recomputes `content_tier_rank` from the new tier, refreshes `updated_at` and increases
    the channel's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/fare_filing_not_active_outranks_contract_cap_exceeded
    """
    channel = fx.create_full_channel(
        api,
        channel_code="CH_LOW",
        content_tier=CONTENT_TIER_RESTRICTED,
        content_markup_pct=0.0,
        required_disclosure_codes=[],
    )
    corporate = _corporate_partner(api, iata_code="CORP-0002")
    filing = fx.create_active_filing(
        api,
        fare_basis_code="PRIV03",
        cabin=CABIN_BUSINESS,
        base_amount_cents=BIG_FARE_CENTS,
        min_content_tier_rank=2,
        refundable=True,
        is_private=True,
    )
    suspended = fx.drive_filing(api, filing["id"], FILING_SUSPENDED, reason="Market pull")
    assert suspended["status"] == FILING_SUSPENDED
    contract = _capped_contract(api, corporate["id"], filing["id"], min_content_tier_rank=1)
    headers = agency_headers(corporate["id"])

    payload = f.offer_payload(
        channel["id"],
        corporate["id"],
        filing["id"],
        cabin=CABIN_BUSINESS,
        corporate_contract_id=contract["id"],
    )

    # All three are broken at once. Step 8 speaks first.
    first = api.create_offer(payload, headers=headers)
    validate_error(first, ApiErrorId.FARE_FILING_NOT_ACTIVE)

    fx.drive_filing(api, filing["id"], FILING_ACTIVE)
    # Now step 27: a RESTRICTED channel of rank 1 cannot carry rank-2 content.
    second = api.create_offer(payload, headers=headers)
    validate_error(second, ApiErrorId.CONTENT_TIER_INSUFFICIENT)
    assert second.json()["data"]["error_id"] != ApiErrorId.CONTRACT_CAP_EXCEEDED

    upgraded = fx.revise_content_policy(api, channel["id"], content_tier=CONTENT_TIER_STANDARD)
    assert upgraded["content_tier"] == CONTENT_TIER_STANDARD
    assert upgraded["content_tier_rank"] == 2

    # Only now does the request reach the fiscal cap at step 31.
    third = api.create_offer(payload, headers=headers)
    validate_error(third, ApiErrorId.CONTRACT_CAP_EXCEEDED)
    _no_offer_exists(api)


TRACE_FARE_CENTS = 45010
TRACE_TOTAL_CENTS = 46585


def _published_corporate_offer(api):
    """A published private-fare offer under a traceability-required contract."""
    channel = fx.create_ndc_channel(api)
    corporate = _corporate_partner(api, iata_code="CORP-0003")
    filing = fx.create_active_filing(
        api,
        fare_basis_code="PRIV02",
        base_amount_cents=TRACE_FARE_CENTS,
        min_content_tier_rank=2,
        refundable=True,
        is_private=True,
    )
    contract = fx.create_contract(
        api,
        corporate["id"],
        filing["id"],
        effective_to=CONTRACT_END,
        account_code="ZEN-TRACE",
        max_offer_total_cents=200000,
        traceability_required=True,
        tracking_ref_prefix="CORP-",
        min_content_tier_rank=2,
    )
    headers = agency_headers(corporate["id"])
    offer = fx.construct_offer(
        api,
        channel["id"],
        corporate["id"],
        filing["id"],
        headers=headers,
        corporate_contract_id=contract["id"],
    )
    # 45,010 * 1.035 = 46,585.35 -> 46,585, under the 200,000 cap and under the
    # ALL-scope surcharge threshold of 50,000, so no surcharge line is emitted.
    assert offer["total_cents"] == TRACE_TOTAL_CENTS
    published = fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    assert published["status"] == OFFER_PUBLISHED
    return contract, published, headers


def test_incomplete_disclosure_is_reported_before_the_missing_tracking_reference(api):
    """PRD §2.10: "**Regulatory disclosure** — the submitted acknowledgement covers the
    channel's required codes (`ERR_DISCLOSURE_INCOMPLETE`, 422), on `POST
    /offers/{id}/publish` and `POST /orders`."
    PRD §2.10: "**Traceability reference present** — `ERR_CORPORATE_TRACKING_REF_MISSING`
    (422), on `POST /orders`."
    PRD §2.11: "Crucially, **acknowledgement does not carry forward**: codes acknowledged at
    publish time are not credited to the order, so an order request must resubmit them."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_incomplete_outranks_corporate_tracking_ref_missing
    """
    _contract, offer, headers = _published_corporate_offer(api)

    both_broken = api.create_order(
        f.order_payload(offer["id"], disclosure_ack_codes=[]), headers=headers
    )
    # Step 15 outranks step 18.
    validate_error(both_broken, ApiErrorId.DISCLOSURE_INCOMPLETE)
    assert (
        both_broken.json()["data"]["error_id"]
        != ApiErrorId.CORPORATE_TRACKING_REF_MISSING
    )

    # The rejected order consumed nothing.
    unchanged = fx.read_offer(api, offer["id"], headers=headers)
    assert unchanged["status"] == OFFER_PUBLISHED
    assert unchanged["total_cents"] == TRACE_TOTAL_CENTS
    assert unchanged["version"] == offer["version"]
    _rows, meta = validate_paginated(api.list_orders(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_the_two_traceability_failures_surface_once_disclosure_is_satisfied(api):
    """PRD §3.4: "Traceability is enforced one step later, at order time: when the offer's
    contract has `traceability_required` set to true, the order request must supply
    `corporate_tracking_ref`, and omitting it is `ERR_CORPORATE_TRACKING_REF_MISSING`; when
    it is supplied it must begin with the contract's `tracking_ref_prefix`, and a reference
    with the wrong prefix is `ERR_CORPORATE_TRACKING_REF_INVALID`."
    PRD §2.10: "**Traceability reference format** — `ERR_CORPORATE_TRACKING_REF_INVALID`
    (422), on `POST /orders`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_incomplete_outranks_corporate_tracking_ref_missing
    """
    _contract, offer, headers = _published_corporate_offer(api)

    missing = api.create_order(
        f.order_payload(offer["id"], disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES),
        headers=headers,
    )
    validate_error(missing, ApiErrorId.CORPORATE_TRACKING_REF_MISSING)

    wrong_prefix = api.create_order(
        f.order_payload(
            offer["id"],
            disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES,
            corporate_tracking_ref="ZEN-9911",
        ),
        headers=headers,
    )
    validate_error(wrong_prefix, ApiErrorId.CORPORATE_TRACKING_REF_INVALID)
    _rows, meta = validate_paginated(api.list_orders(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0

    order = fx.create_order(
        api,
        offer["id"],
        fx.NDC_DISCLOSURE_CODES,
        headers=headers,
        corporate_tracking_ref="CORP-9911",
    )
    assert order["corporate_tracking_ref"] == "CORP-9911"
    assert order["net_revenue_cents"] == TRACE_TOTAL_CENTS
    assert fx.read_offer(api, offer["id"], headers=headers)["status"] == OFFER_ORDERED

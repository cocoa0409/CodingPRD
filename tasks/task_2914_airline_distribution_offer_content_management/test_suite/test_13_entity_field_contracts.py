"""Entity field contracts: declared fields, defaults, computed and system fields."""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CABIN_ECONOMY,
    CHANNEL_KIND_DIRECT,
    CHANNEL_KIND_GDS_LEGACY,
    CHANNEL_KIND_NDC_AGGREGATOR,
    CONTENT_TIER_FULL,
    CONTENT_TIER_RESTRICTED,
    CONTENT_TIER_STANDARD,
    DESTINATION_JFK,
    DISTRIBUTION_MANAGER_HEADERS,
    FILING_ACTIVE,
    FILING_DRAFT,
    ITEM_SCOPE_ALL,
    ITEM_TYPE_FARE,
    NON_EXISTENT_UUID,
    ORIGIN_FRA,
    PRICING_ANALYST_HEADERS,
    PRICING_ANALYST_USER_ID,
    REVIEW_START_REVIEW,
    TEST_CANCELLED,
    ApiErrorId,
    agency_headers,
    assert_immutable_resource,
    assert_three_fractional_digits,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    technology_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_BASIS = "YCORN01"
CORNER_BASE_CENTS = 45010


def test_fare_filing_creation_returns_every_declared_field(api):
    """PRD §3.2: "On creation the service records `filed_by_user_id` as the acting
    `X-User-ID`, sets `revision_number` to 0, leaves `base_filing_id` null, and sets `status`
    to `DRAFT`."
    PRD §2.4: "Every resource the service persists carries a server-minted `id` in UUID
    form."
    PRD §2.4: "Most resources are mutable and additionally carry `updated_at` — same ISO 8601
    UTC format with three fractional digits, refreshed on every mutation — and `version`, an
    integer that starts at 1 on creation and increases by exactly 1 on every mutation that
    the service accepts."

    Design: Corner/entities/corner_fare_filing_creation_returns_all_declared_fields
    """
    filing = fx.create_fare_filing(
        api,
        fare_basis_code=CORNER_BASIS,
        base_amount_cents=CORNER_BASE_CENTS,
        min_content_tier_rank=1,
        refundable=True,
        is_private=False,
    )

    assert is_valid_uuid(filing["id"])
    assert filing["fare_basis_code"] == CORNER_BASIS
    assert filing["origin"] == ORIGIN_FRA
    assert filing["destination"] == DESTINATION_JFK
    assert filing["cabin"] == CABIN_ECONOMY
    assert filing["base_amount_cents"] == CORNER_BASE_CENTS
    assert filing["min_content_tier_rank"] == 1
    assert filing["refundable"] is True
    assert filing["is_private"] is False
    assert filing["status"] == FILING_DRAFT
    assert filing["revision_number"] == 0
    assert filing["base_filing_id"] is None
    assert filing["filed_by_user_id"] == PRICING_ANALYST_USER_ID
    assert filing["version"] == 1
    assert is_iso8601_timestamp(filing["created_at"])
    assert is_iso8601_timestamp(filing["updated_at"])


def test_reading_a_channel_returns_the_stored_row_and_a_zeroed_ledger(api):
    """PRD §3.1: "On registration the service derives `content_tier_rank` from
    `content_tier` using the fixed mapping of §2.8, and initialises the channel's four ledger
    fields — `booking_count`, `activity_cost_cents`, `cost_per_booking_flat_cents` and
    `cost_per_booking_activity_cents` — to 0."
    PRD §3.1: "Reading a channel returns its live distribution-cost ledger — both
    cost-per-booking variants side by side — which is why the read is open to every role
    including `ComplianceAuditor`, `Agency` and `TechnologyPartner`."

    Design: Corner/entities/corner_get_channel_returns_the_stored_channel_row
    """
    created = fx.create_full_channel(
        api,
        channel_code="CORNER_NDC",
        channel_kind=CHANNEL_KIND_NDC_AGGREGATOR,
        content_tier=CONTENT_TIER_STANDARD,
        content_markup_pct=0.035,
        incentive_multiplier=1.25,
        monthly_platform_fee_cents=400000,
        per_message_cost_cents=12,
        per_segment_fee_cents=40,
        required_disclosure_codes=["DOT-FARE-INCL"],
    )

    channel = fx.read_channel(api, created["id"], headers=AUDITOR_HEADERS)
    assert channel["channel_code"] == "CORNER_NDC"
    assert channel["channel_kind"] == CHANNEL_KIND_NDC_AGGREGATOR
    assert channel["content_tier"] == CONTENT_TIER_STANDARD
    assert channel["content_tier_rank"] == 2
    assert channel["monthly_platform_fee_cents"] == 400000
    assert channel["per_message_cost_cents"] == 12
    assert channel["per_segment_fee_cents"] == 40
    assert channel["required_disclosure_codes"] == ["DOT-FARE-INCL"]
    assert channel["booking_count"] == 0
    assert channel["activity_cost_cents"] == 0
    assert channel["cost_per_booking_flat_cents"] == 0
    assert channel["cost_per_booking_activity_cents"] == 0
    assert channel["version"] == created["version"]


def test_fare_filing_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted value
    is 1, and its maximum accepted value is 100."
    PRD §2.3: "For every list response the `meta` object carries `limit` (the effective page
    size applied), `offset` (the effective starting position applied), `total_count` (the
    number of records matching the filters before pagination), and `has_more` (true when
    records remain beyond the current page)."
    PRD §3.2: "Fare filings are discoverable by `status`, by `origin`, by `destination`, by
    `cabin` and by `base_filing_id` — the last of these being how a caller walks a revision
    chain, since listing by a base filing's identifier returns the revisions filed against
    it."

    Design: Corner/entities/corner_fare_filing_list_paginates_with_total_count_and_has_more
    """
    for suffix, cents in (("01", 30000), ("02", 31000), ("03", 32000)):
        fx.create_fare_filing(
            api, fare_basis_code="YPAGE" + suffix, base_amount_cents=cents
        )

    first_page, meta = validate_paginated(
        api.list_fare_filings(
            headers=PRICING_ANALYST_HEADERS,
            params={"status": FILING_DRAFT, "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    last_page, last_meta = validate_paginated(
        api.list_fare_filings(
            headers=PRICING_ANALYST_HEADERS,
            params={"status": FILING_DRAFT, "limit": 2, "offset": 2},
        )
    )
    assert len(last_page) == 1
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False

    _none, active_meta = validate_paginated(
        api.list_fare_filings(
            headers=PRICING_ANALYST_HEADERS, params={"status": FILING_ACTIVE}
        )
    )
    assert active_meta["total_count"] == 0


def test_channel_registration_without_a_channel_kind_is_a_malformed_request(api):
    """PRD §3.1: "A `PlatformAdmin` registers one by supplying a `channel_code` — a
    human-readable identifier of 1 to 32 characters that must be unique across all channels,
    compared case-sensitively, with a reuse rejected as `ERR_DUPLICATE_CHANNEL_CODE` —
    together with a `channel_kind` naming the distribution technology behind it: `DIRECT` for
    the airline's own storefront, `NDC_AGGREGATOR` for a modern retailing connection, or
    `GDS_LEGACY` for a traditional distribution link."
    PRD §2.10: "**Request shape** — every required field present, every enum value inside its
    declared domain, every numeric and string constraint from the field definitions honoured,
    `limit` within 1 to 100 inclusive and `offset` at least 0 (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/corner_channel_creation_without_channel_kind_returns_invalid_request
    """
    refused = api.create_channel({"channel_code": "NO_KIND"}, headers=ADMIN_HEADERS)
    validate_error(refused, ApiErrorId.INVALID_REQUEST)

    # Nothing was written, so the code is still free.
    channel = fx.create_channel(
        api, channel_code="NO_KIND", channel_kind=CHANNEL_KIND_DIRECT
    )
    assert channel["channel_code"] == "NO_KIND"
    assert channel["channel_kind"] == CHANNEL_KIND_DIRECT


def test_a_bare_channel_registration_applies_every_declared_default(api):
    """PRD §3.1: "The remaining registration inputs are all optional and each has a defined
    default, because most channels are registered with a template and tuned afterwards."
    PRD §3.1: "`content_markup_pct` is the per-line distribution markup applied to every
    offer line priced through the channel; it defaults to 0, must lie between 0 and 0.25
    inclusive, and is accepted with at most four decimal places."
    PRD §3.1: "`servicing_parity_change` defaults to true and states that change requests can
    be applied through the channel; `servicing_parity_refund` also defaults to true and
    states the same for refunds."

    Design: Corner/entities/corner_channel_optional_fields_fall_back_to_declared_defaults
    """
    channel = fx.create_channel(
        api, channel_code="BARE_MIN", channel_kind=CHANNEL_KIND_DIRECT
    )

    assert channel["content_tier"] == CONTENT_TIER_STANDARD
    assert channel["content_tier_rank"] == 2
    assert channel["content_markup_pct"] == 0
    assert channel["incentive_multiplier"] == 1.0
    assert channel["monthly_platform_fee_cents"] == 0
    assert channel["per_message_cost_cents"] == 0
    assert channel["per_segment_fee_cents"] == 0
    assert channel["servicing_parity_change"] is True
    assert channel["servicing_parity_refund"] is True
    assert channel["required_disclosure_codes"] == []
    assert channel["version"] == 1


def test_content_tier_rank_is_derived_from_the_tier_on_write_and_on_revision(api):
    """PRD §2.8: "From that enum the service derives `content_tier_rank`, an integer: `FULL`
    maps to 3, `STANDARD` maps to 2, and `RESTRICTED` maps to 1."
    PRD §2.8: "`content_tier_rank` is computed by the service and is never supplied by a
    client; it is recomputed whenever the channel's content policy is revised."

    Design: Corner/entities/corner_content_tier_rank_is_computed_from_content_tier
    """
    full = fx.create_channel(
        api,
        channel_code="TIER_FULL",
        channel_kind=CHANNEL_KIND_DIRECT,
        content_tier=CONTENT_TIER_FULL,
    )
    restricted = fx.create_channel(
        api,
        channel_code="TIER_RESTR",
        channel_kind=CHANNEL_KIND_GDS_LEGACY,
        content_tier=CONTENT_TIER_RESTRICTED,
    )
    assert full["content_tier_rank"] == 3
    assert restricted["content_tier_rank"] == 1

    revised = validate_success(
        api.patch_channel_content_policy(
            restricted["id"],
            f.content_policy_payload(content_tier=CONTENT_TIER_FULL),
            headers=DISTRIBUTION_MANAGER_HEADERS,
        )
    )
    # The recomputation is already visible in the PATCH response itself.
    assert revised["content_tier"] == CONTENT_TIER_FULL
    assert revised["content_tier_rank"] == 3
    assert revised["version"] == 2
    assert fx.read_channel(api, full["id"])["content_tier_rank"] == 3


def test_every_unknown_path_identifier_names_its_own_entity(api):
    """PRD §2.10: "**Path resolution** — every identifier in the URL path resolves, validated
    strictly left to right, so an outer segment's not-found error always wins over an inner
    segment's. Depending on which segment failed, the error is `ERR_CHANNEL_NOT_FOUND`,
    `ERR_FARE_FILING_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SERVICE_REQUEST_NOT_FOUND`,
    `ERR_CERTIFICATION_NOT_FOUND`, `ERR_CONNECTIVITY_TEST_NOT_FOUND` or
    `ERR_PARTNER_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/corner_unknown_path_ids_return_entity_specific_not_found
    """
    ghost = NON_EXISTENT_UUID
    partner = fx.create_tech_partner(api, iata_code="TP555555")

    validate_error(api.get_channel(ghost, headers=ADMIN_HEADERS), ApiErrorId.CHANNEL_NOT_FOUND)
    validate_error(api.get_partner(ghost, headers=ADMIN_HEADERS), ApiErrorId.PARTNER_NOT_FOUND)
    validate_error(
        api.get_fare_filing(ghost, headers=PRICING_ANALYST_HEADERS),
        ApiErrorId.FARE_FILING_NOT_FOUND,
    )
    validate_error(
        api.get_agency_agreement(ghost, headers=DISTRIBUTION_MANAGER_HEADERS),
        ApiErrorId.AGREEMENT_NOT_FOUND,
    )
    validate_error(
        api.get_corporate_contract(ghost, headers=DISTRIBUTION_MANAGER_HEADERS),
        ApiErrorId.CONTRACT_NOT_FOUND,
    )
    validate_error(
        api.get_offer(ghost, headers=DISTRIBUTION_MANAGER_HEADERS), ApiErrorId.OFFER_NOT_FOUND
    )
    validate_error(
        api.get_order(ghost, headers=DISTRIBUTION_MANAGER_HEADERS), ApiErrorId.ORDER_NOT_FOUND
    )
    validate_error(
        api.review_service_request(
            ghost,
            f.review_payload(REVIEW_START_REVIEW),
            headers=DISTRIBUTION_MANAGER_HEADERS,
        ),
        ApiErrorId.SERVICE_REQUEST_NOT_FOUND,
    )
    validate_error(
        api.get_certification(ghost, headers=ADMIN_HEADERS), ApiErrorId.CERTIFICATION_NOT_FOUND
    )
    validate_error(
        api.post_test_outcome(
            ghost,
            f.outcome_payload(TEST_CANCELLED),
            headers=technology_partner_headers(partner["id"]),
        ),
        ApiErrorId.CONNECTIVITY_TEST_NOT_FOUND,
    )


def test_the_order_mints_its_own_identity_and_freezes_the_offer_total(api):
    """PRD §3.6: "On creation the service copies `channel_id` and `partner_id` from the source
    offer — a client never supplies them — and resolves `agency_agreement_id` to the identifier
    of the `SIGNED` agreement for that partner-and-channel pair, leaving it null when the
    ordering partner is not a travel agency."
    PRD §3.6: "`net_revenue_cents` is frozen to the offer's `total_cents` at this instant and
    never moves again; it is the quantity the agreement revenue ledger accumulates, and
    freezing it means a later policy or catalogue change cannot retroactively rewrite reported
    revenue."
    PRD §3.6: "`paid_amount_cents` and `refunded_amount_cents` both start at 0."
    PRD §3.6: "Two optional cost inputs ride along on the order because they are the raw
    material of activity-based costing: `message_count`, the number of distribution messages
    exchanged to create this order, defaulting to 1 and required to be at least 1; and
    `segment_count`, the number of booked segments, likewise defaulting to 1 and at least 1."
    PRD §2.4: "Every resource the service persists carries a server-minted `id` in UUID form."

    Design: Corner/entities/corner_order_system_fields_are_server_minted
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )
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
    # No surcharge rules on this channel, so the total is the marked-up fare alone.
    assert offer["total_cents"] == 46585
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)

    order = fx.create_order(
        api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    assert is_valid_uuid(order["id"])
    assert len(order["id"]) == 36
    assert order["version"] == 1
    assert_three_fractional_digits(order["created_at"])
    assert_three_fractional_digits(order["updated_at"])
    assert order["channel_id"] == channel["id"]
    assert order["partner_id"] == partner["id"]
    assert order["agency_agreement_id"] == agreement["id"]
    assert order["net_revenue_cents"] == 46585
    assert order["message_count"] == 1
    assert order["segment_count"] == 1
    assert order["paid_amount_cents"] == 0
    assert order["refunded_amount_cents"] == 0


def test_an_out_of_domain_cabin_and_an_inverted_sale_window_are_both_malformed(api):
    """PRD §3.2: "The filing declares its market and product — a `fare_basis_code` of 1 to 16
    characters, an `origin` and a `destination` each of exactly three uppercase letters, and a
    `cabin` of `ECONOMY`, `PREMIUM` or `BUSINESS` — plus a `base_amount_cents` strictly greater
    than 0, which is the filed base fare before any channel markup or surcharge."
    PRD §3.2: "Four instants define its two windows: `sale_from` and `sale_to` bound the
    half-open sale window, and `travel_from` and `travel_to` bound the closed travel window,
    with `sale_to` required to be strictly after `sale_from` and `travel_to` required to be at
    or after `travel_from`."
    PRD §2.10: "**Request shape** — every required field present, every enum value inside its
    declared domain, every numeric and string constraint from the field definitions honoured,
    `limit` within 1 to 100 inclusive and `offset` at least 0 (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/corner_fare_filing_with_unknown_cabin_returns_invalid_request
    """
    bad_cabin = api.create_fare_filing(
        f.fare_filing_payload(fare_basis_code="YBADCAB", base_amount_cents=30000, cabin="FIRST"),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(bad_cabin, ApiErrorId.INVALID_REQUEST)

    inverted = api.create_fare_filing(
        f.fare_filing_payload(
            fare_basis_code="YBADWIN",
            base_amount_cents=30000,
            sale_from="2026-10-01T00:00:00.000Z",
            sale_to="2026-07-01T00:00:00.000Z",
        ),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(inverted, ApiErrorId.INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.list_fare_filings(
            headers=PRICING_ANALYST_HEADERS, params={"status": FILING_DRAFT}
        )
    )
    assert meta["total_count"] == 0


def test_a_priced_line_exposes_only_id_and_created_at(api):
    """PRD §2.4: "Two resource kinds are deliberately immutable once written and therefore
    carry **only** `id` and `created_at`: a channel's surcharge rules, and an offer's priced
    lines. Neither `updated_at` nor `version` exists on those two resource kinds — they are
    absent from the response payload entirely, not present-but-null."
    PRD §3.5: "Every line carries an `item_type` of `FARE`, `ANCILLARY`, `BUNDLE_ANCILLARY` or
    `SURCHARGE`, an `item_code` holding the filing's `fare_basis_code`, the ancillary's
    `ancillary_code` or the rule's `surcharge_code` according to that type, an `offer_id` naming
    its owning offer, and a `refundable` flag copied from the source filing's `refundable` for a
    fare line and from the source ancillary product's `refundable` for either kind of ancillary
    line — surcharge lines always carry `refundable` false, without exception."
    PRD §3.5: "An offer's three terminal states are `ORDERED`, `WITHDRAWN` and `EXPIRED`.
    Whichever way it terminates, the offer's priced lines are immutable and are retained
    verbatim for audit — they are the only record of what the market was quoted — and they are
    observable only by listing an offer's lines, since they are never embedded in the offer
    payload itself."

    Design: Corner/entities/corner_offer_items_are_immutable_and_carry_no_version_field
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    offer = fx.construct_offer(api, channel["id"], partner["id"], filing["id"])
    assert offer["item_count"] == 1

    lines, meta = validate_paginated(
        api.list_offer_items(offer["id"], headers=AUDITOR_HEADERS, params={"limit": 100})
    )
    assert meta["total_count"] == 1
    line = lines[0]
    assert line["sequence"] == 1
    assert line["item_type"] == ITEM_TYPE_FARE
    assert line["item_code"] == CORNER_BASIS
    assert line["offer_id"] == offer["id"]
    assert line["list_amount_cents"] == CORNER_BASE_CENTS
    assert line["net_amount_cents"] == 46585
    assert line["refundable"] is True
    assert_immutable_resource(line)


def test_a_surcharge_rule_under_an_unknown_channel_fails_at_path_resolution(api):
    """PRD §2.10: "**Path resolution** — every identifier in the URL path resolves, validated
    strictly left to right, so an outer segment's not-found error always wins over an inner
    segment's."
    PRD §3.1: "A channel's surcharge structure is built from immutable rules, each added by a
    `PlatformAdmin` and permanently bound to one channel through its `channel_id`."

    Design: Corner/entities/corner_surcharge_rule_under_unknown_channel_returns_channel_not_found
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)

    orphan = api.create_surcharge_rule(
        NON_EXISTENT_UUID,
        f.surcharge_rule_payload(
            surcharge_code="ORPHAN",
            item_scope=ITEM_SCOPE_ALL,
            rate_pct=0.02,
            threshold_cents=0,
            min_cents=0,
            max_cents=1000,
        ),
        headers=ADMIN_HEADERS,
    )
    validate_error(orphan, ApiErrorId.CHANNEL_NOT_FOUND)

    _rules, meta = validate_paginated(
        api.list_surcharge_rules(channel["id"], headers=ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_each_unresolvable_body_reference_reports_its_own_entity(api):
    """PRD §2.10: "**Body reference resolution** — every foreign key and catalogue code carried
    in the request body resolves: `partner_id`, `channel_id`, `fare_filing_id`, `bundle_id`,
    `corporate_contract_id`, `offer_id`, `negotiated_fare_filing_id`, `corporate_partner_id`,
    and every entry of `ancillary_codes`. The reported error is `ERR_PARTNER_NOT_FOUND`,
    `ERR_CHANNEL_NOT_FOUND`, `ERR_FARE_FILING_NOT_FOUND`, `ERR_BUNDLE_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_OFFER_NOT_FOUND` or `ERR_ANCILLARY_NOT_FOUND` as
    appropriate, each HTTP 404."

    Design: Corner/entities/corner_body_foreign_keys_are_validated_before_business_rules
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])

    unknown_bundle = api.create_offer(
        f.offer_payload(
            channel["id"], partner["id"], filing["id"], bundle_id=NON_EXISTENT_UUID
        ),
        headers=headers,
    )
    validate_error(unknown_bundle, ApiErrorId.BUNDLE_NOT_FOUND)

    unknown_ancillary = api.create_offer(
        f.offer_payload(
            channel["id"], partner["id"], filing["id"], ancillary_codes=["NO_SUCH_ANC"]
        ),
        headers=headers,
    )
    validate_error(unknown_ancillary, ApiErrorId.ANCILLARY_NOT_FOUND)

    unknown_offer = api.create_order(
        f.order_payload(NON_EXISTENT_UUID, disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES),
        headers=headers,
    )
    validate_error(unknown_offer, ApiErrorId.OFFER_NOT_FOUND)

    _rows, meta = validate_paginated(
        api.list_offers(headers=ADMIN_HEADERS, params={"channel_id": channel["id"]})
    )
    assert meta["total_count"] == 0

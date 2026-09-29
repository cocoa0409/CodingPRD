"""Errors: every catalogued failure this design index names is reachable and distinct."""

from test_helpers import (
    ADMIN_HEADERS,
    CERT_ENV_A,
    CERT_ENV_B,
    CERT_STATUS_UNCERTIFIED,
    CERTIFICATION_TESTING,
    CHANNEL_KIND_DIRECT,
    CHANNEL_KIND_GDS_LEGACY,
    CHANNEL_KIND_NDC_AGGREGATOR,
    CONTENT_TIER_FULL,
    CONTENT_TIER_RESTRICTED,
    DISTRIBUTION_MANAGER_HEADERS,
    FILING_ACTIVE,
    NEGOTIATION_ACCEPT,
    NEGOTIATION_COUNTER,
    NEGOTIATION_PROPOSE,
    OFFER_CONSTRUCTED,
    OFFER_EXPIRED,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    PARTNER_TYPE_CORPORATE,
    VALIDITY_PENDING,
    ApiErrorId,
    agency_headers,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    technology_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_BASIS = "YCORN01"
CORNER_FARE_CENTS = 45010
CORNER_TOTAL_CENTS = 46585
TTL_INSTANT = "2026-08-01T00:30:00.000Z"
WINDOW_FROM = "2026-09-01T00:00:00.000Z"
WINDOW_TO = "2026-10-01T00:00:00.000Z"


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


def _tango(api):
    return fx.create_tech_partner(
        api, partner_name="Tango Corner Systems", iata_code="55555551"
    )


def _offer_total(api, **params):
    _rows, meta = validate_paginated(
        api.list_offers(headers=ADMIN_HEADERS, params=params)
    )
    return meta["total_count"]


def test_a_reused_channel_code_is_refused_and_leaves_the_first_row_alone(api):
    """PRD §3.1: "A `PlatformAdmin` registers one by supplying a `channel_code` — a human-readable
    identifier of 1 to 32 characters that must be unique across all channels, compared
    case-sensitively, with a reuse rejected as `ERR_DUPLICATE_CHANNEL_CODE` — together with a
    `channel_kind` naming the distribution technology behind it: `DIRECT` for the airline's own
    storefront, `NDC_AGGREGATOR` for a modern retailing connection, or `GDS_LEGACY` for a
    traditional distribution link."

    Design: Corner/errors/corner_error_duplicate_channel_code_is_triggerable
    """
    channel = _corner_channel(api)
    assert channel["channel_kind"] == CHANNEL_KIND_NDC_AGGREGATOR

    reused = api.create_channel(
        f.channel_payload(
            channel_code=channel["channel_code"], channel_kind=CHANNEL_KIND_DIRECT
        ),
        headers=ADMIN_HEADERS,
    )
    validate_error(reused, ApiErrorId.DUPLICATE_CHANNEL_CODE)

    survivor = fx.read_channel(api, channel["id"])
    assert survivor["channel_kind"] == CHANNEL_KIND_NDC_AGGREGATOR
    assert survivor["version"] == 1


def test_the_offer_dies_at_exactly_its_own_expiry_instant(api):
    """PRD §3.5: "`expires_at` is set to the offer's `created_at` plus thirty minutes — the offer
    time-to-live is half an hour, and it is not configurable per channel."
    PRD §3.5: "If it has and the offer sits in `CONSTRUCTED` or `PUBLISHED`, the offer's `status`
    becomes `EXPIRED` and its `version` increases by 1 *before* the targeting operation is
    evaluated."
    PRD §3.5: "The comparison is at-or-after: an operation arriving at exactly `expires_at` is too
    late."
    PRD §2.10: "**Offer expiry** — the targeted offer has not reached `expires_at`. The lazy expiry
    transition is applied first and the operation is then rejected with `ERR_OFFER_EXPIRED` (409).
    Applies to `POST /offers/{id}/publish` and `POST /orders`."

    Design: Corner/errors/corner_error_offer_expired_at_exactly_the_ttl_instant
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    assert_instant_equals(offer["expires_at"], TTL_INSTANT)

    fx.set_clock(api, TTL_INSTANT)
    too_late = api.publish_offer(
        offer["id"], f.publish_payload(fx.NDC_DISCLOSURE_CODES), headers=headers
    )
    validate_error(too_late, ApiErrorId.OFFER_EXPIRED)

    lazily_expired = fx.read_offer(api, offer["id"], headers=headers)
    assert lazily_expired["status"] == OFFER_EXPIRED
    assert lazily_expired["disclosure_complete"] is False

    ordered = api.create_order(
        f.order_payload(offer["id"], disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES),
        headers=headers,
    )
    # Step 7 outranks step 9, so expiry is reported rather than non-publication.
    validate_error(ordered, ApiErrorId.OFFER_EXPIRED)
    assert ordered.json()["data"]["error_id"] != ApiErrorId.OFFER_NOT_PUBLISHED


def test_an_unpublished_offer_is_refused_before_the_agreement_is_examined(api):
    """PRD §3.6: "The offer's `status` must be `PUBLISHED` — a constructed-but-unpublished offer, a
    withdrawn one or an already-ordered one all yield `ERR_OFFER_NOT_PUBLISHED` — and the offer must
    not have reached `expires_at`."
    PRD §2.10: "**Signed agreement present** — when the ordering partner's `partner_type` is
    `TRAVEL_AGENCY`, a signed agreement exists for the offer's partner-and-channel pair, else
    `ERR_AGREEMENT_NOT_SIGNED` (409). Applies to `POST /orders`."

    Design: Corner/errors/corner_error_offer_not_published_is_triggerable
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )

    refused = api.create_order(
        f.order_payload(offer["id"], disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES),
        headers=headers,
    )
    validate_error(refused, ApiErrorId.OFFER_NOT_PUBLISHED)
    assert refused.json()["data"]["error_id"] != ApiErrorId.AGREEMENT_NOT_SIGNED

    # The lower-priority gate really was violated too: this agency has no agreement.
    _rows, meta = validate_paginated(
        api.list_agency_agreements(
            headers=ADMIN_HEADERS, params={"partner_id": partner["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fx.read_offer(api, offer["id"], headers=headers)["status"] == OFFER_CONSTRUCTED


def test_a_second_certification_on_the_same_pair_is_refused(api):
    """PRD §3.8: "Nor may two certifications run in parallel for the same partner-and-channel pair:
    if any existing certification for that pair sits in `TESTING`, `CERTIFIED` or `SUSPENDED`, the
    request is refused with `ERR_CERTIFICATION_ALREADY_OPEN`."
    PRD §3.8: "A `TechnologyPartner` or a `PlatformAdmin` opens a certification naming the
    `partner_id` under test, the `channel_id` it is certifying against, and the `env_code` of the
    shared certification environment its tests will occupy — either `CERT_ENV_A` or `CERT_ENV_B`."

    Design: Corner/errors/corner_error_certification_already_open_is_triggerable
    """
    channel = _corner_channel(api)
    partner = _tango(api)
    first = fx.open_certification(
        api, partner["id"], channel["id"], env_code=CERT_ENV_A
    )
    assert first["status"] == CERTIFICATION_TESTING

    # A different environment does not buy a second parallel slot.
    second = api.create_certification(
        f.certification_payload(partner["id"], channel["id"], env_code=CERT_ENV_B),
        headers=technology_partner_headers(partner["id"]),
    )
    validate_error(second, ApiErrorId.CERTIFICATION_ALREADY_OPEN)

    _rows, meta = validate_paginated(
        api.list_certifications(
            headers=ADMIN_HEADERS, params={"partner_id": partner["id"]}
        )
    )
    assert meta["total_count"] == 1
    # Opening the first bumped the partner once; the refusal bumped nothing.
    assert fx.read_partner(api, partner["id"])["version"] == 2


def test_a_corporate_account_cannot_enter_connectivity_certification(api):
    """PRD §3.8: "Only partners whose `partner_type` is `TECH_PROVIDER` or `TRAVEL_AGENCY` may be
    certified; a `CORPORATE` partner is rejected with `ERR_PARTNER_TYPE_NOT_ELIGIBLE`."
    PRD §2.10: "**Partner type eligibility** — `ERR_PARTNER_TYPE_NOT_ELIGIBLE` (422), on `POST
    /agency-agreements`, `POST /corporate-contracts` and `POST /partner-certifications`."

    Design: Corner/errors/corner_error_partner_type_not_eligible_is_triggerable
    """
    channel = _corner_channel(api)
    corporate = _acme_corporate(api)
    tech = _tango(api)

    refused = api.create_certification(
        f.certification_payload(corporate["id"], channel["id"], env_code=CERT_ENV_A),
        headers=ADMIN_HEADERS,
    )
    validate_error(refused, ApiErrorId.PARTNER_TYPE_NOT_ELIGIBLE)

    unmoved = fx.read_partner(api, corporate["id"])
    assert unmoved["certification_status"] == CERT_STATUS_UNCERTIFIED
    assert unmoved["version"] == 1

    # The identical request for the eligible partner is accepted.
    accepted = validate_success(
        api.create_certification(
            f.certification_payload(tech["id"], channel["id"], env_code=CERT_ENV_A),
            headers=ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    assert accepted["status"] == CERTIFICATION_TESTING


def test_a_private_fare_cannot_be_sold_as_public_content(api):
    """PRD §3.5: "If the filing has `is_private` set to true, a `corporate_contract_id` must be
    present **and** that contract's `negotiated_fare_filing_id` must be the very filing being sold;
    a private fare offered with no contract, or under a contract that unlocks a different filing, is
    `ERR_PRIVATE_FARE_REQUIRES_CONTRACT`."
    PRD §3.2: "`is_private`, defaulting to false, which marks the filing as a negotiated fare
    sellable only under a corporate contract."

    Design: Corner/errors/corner_error_private_fare_requires_contract_is_triggerable
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_active_filing(
        api,
        fare_basis_code="YPRIV01",
        base_amount_cents=CORNER_FARE_CENTS,
        min_content_tier_rank=1,
        refundable=True,
        is_private=True,
    )

    refused = api.create_offer(
        f.offer_payload(channel["id"], partner["id"], filing["id"]),
        headers=agency_headers(partner["id"]),
    )
    validate_error(refused, ApiErrorId.PRIVATE_FARE_REQUIRES_CONTRACT)

    unmoved = fx.read_filing(api, filing["id"])
    assert unmoved["is_private"] is True
    assert unmoved["status"] == FILING_ACTIVE
    assert _offer_total(api, fare_filing_id=filing["id"]) == 0


def test_a_contract_whose_window_has_not_opened_cannot_price_an_offer(api):
    """PRD §3.4: "Offers may be priced under a contract only while it reports `IN_EFFECT`; a
    contract that is still `PENDING` or has already `LAPSED` fails offer construction with
    `ERR_CONTRACT_NOT_IN_EFFECT`."
    PRD §3.4: "Contract validity is a half-open interval bounded by `effective_from` inclusive and
    `effective_to` exclusive, with `effective_to` required to be strictly after `effective_from`."

    Design: Corner/errors/corner_error_contract_not_in_effect_is_triggerable
    """
    channel = _corner_channel(api)
    corporate = _acme_corporate(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    contract = fx.create_contract(
        api,
        corporate["id"],
        filing["id"],
        effective_from=WINDOW_FROM,
        effective_to=WINDOW_TO,
        account_code="ACME-LATE",
        max_offer_total_cents=1000000,
        traceability_required=False,
        tracking_ref_prefix="ACME-",
        min_content_tier_rank=1,
    )
    assert contract["validity_state"] == VALIDITY_PENDING

    refused = api.create_offer(
        f.offer_payload(
            channel["id"],
            corporate["id"],
            filing["id"],
            corporate_contract_id=contract["id"],
        ),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(refused, ApiErrorId.CONTRACT_NOT_IN_EFFECT)
    # The generous cap was never in question.
    assert refused.json()["data"]["error_id"] != ApiErrorId.CONTRACT_CAP_EXCEEDED
    assert _offer_total(api, corporate_contract_id=contract["id"]) == 0


def test_the_fiscal_cap_is_compared_against_the_finished_total(api):
    """PRD §3.4: "`max_offer_total_cents`, strictly greater than 0, is a fiscal cap: an offer priced
    under this contract may not exceed that total, and one that does is rejected with
    `ERR_CONTRACT_CAP_EXCEEDED`."
    PRD §3.5: "And once the total has been computed, an offer priced under a contract must not
    exceed that contract's `max_offer_total_cents`, else `ERR_CONTRACT_CAP_EXCEEDED` — the cap is
    evaluated against the finished figure, so it is necessarily the last of the seven to be
    decided."

    Design: Corner/errors/corner_error_contract_cap_exceeded_is_triggerable
    """
    channel = _corner_channel(api)
    corporate = _acme_corporate(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    tight = fx.create_contract(
        api,
        corporate["id"],
        filing["id"],
        account_code="ACME-TIGHT",
        max_offer_total_cents=CORNER_TOTAL_CENTS - 1,
        traceability_required=False,
        tracking_ref_prefix="ACME-",
        min_content_tier_rank=1,
    )

    # 45,010 * 1.035 = 46,585.35 -> 46,585, one cent over a cap of 46,584.
    over = api.create_offer(
        f.offer_payload(
            channel["id"],
            corporate["id"],
            filing["id"],
            corporate_contract_id=tight["id"],
        ),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(over, ApiErrorId.CONTRACT_CAP_EXCEEDED)
    assert _offer_total(api, corporate_contract_id=tight["id"]) == 0

    exact = fx.create_contract(
        api,
        corporate["id"],
        filing["id"],
        account_code="ACME-EXACT",
        max_offer_total_cents=CORNER_TOTAL_CENTS,
        traceability_required=False,
        tracking_ref_prefix="ACME-",
        min_content_tier_rank=1,
    )
    # "may not exceed" is inclusive at equality.
    admitted = fx.construct_offer(
        api,
        channel["id"],
        corporate["id"],
        filing["id"],
        corporate_contract_id=exact["id"],
    )
    assert admitted["total_cents"] == CORNER_TOTAL_CENTS


def test_a_restricted_channel_cannot_carry_top_tier_content(api):
    """PRD §2.8: "Four kinds of sellable content carry a minimum entitlement of their own, each in
    the field `min_content_tier_rank`, an integer between 1 and 3 inclusive: a fare filing (default
    1), an ancillary product (default 1), a bundle definition (default 1), and a corporate contract
    (default 2 — negotiated content is by policy withheld from restricted channels unless
    deliberately opened up). A channel may sell a piece of content only when its own
    `content_tier_rank` is greater than or equal to that content's `min_content_tier_rank`."
    PRD §3.5: "The channel's `content_tier_rank` must be greater than or equal to the
    `min_content_tier_rank` of *every* referenced component — the filing, each à la carte ancillary,
    the bundle if one is attached, and the corporate contract if one is named — with a single
    shortfall anywhere reported as `ERR_CONTENT_TIER_INSUFFICIENT`."

    Design: Corner/errors/corner_error_content_tier_insufficient_is_triggerable
    """
    legacy = fx.create_channel(
        api,
        channel_code="CORNER_LEGACY",
        channel_kind=CHANNEL_KIND_GDS_LEGACY,
        content_tier=CONTENT_TIER_RESTRICTED,
    )
    full = fx.create_channel(
        api,
        channel_code="CORNER_FULL",
        channel_kind=CHANNEL_KIND_DIRECT,
        content_tier=CONTENT_TIER_FULL,
    )
    assert legacy["content_tier_rank"] == 1
    assert full["content_tier_rank"] == 3

    partner = _corner_agency(api)
    filing = fx.create_active_filing(
        api,
        fare_basis_code="YTIER01",
        base_amount_cents=CORNER_FARE_CENTS,
        min_content_tier_rank=3,
    )
    headers = agency_headers(partner["id"])

    refused = api.create_offer(
        f.offer_payload(legacy["id"], partner["id"], filing["id"]), headers=headers
    )
    validate_error(refused, ApiErrorId.CONTENT_TIER_INSUFFICIENT)
    assert _offer_total(api, channel_id=legacy["id"]) == 0

    # Rank 3 against a requirement of 3 clears a >= comparison.
    admitted = fx.construct_offer(
        api, full["id"], partner["id"], filing["id"], headers=headers
    )
    assert admitted["subtotal_cents"] == CORNER_FARE_CENTS
    assert admitted["total_cents"] == CORNER_FARE_CENTS


def test_the_fourth_counter_is_refused_while_the_airline_may_always_answer(api):
    """PRD §3.3: "The service allows at most three counter rounds on any one agreement: a `COUNTER`
    is permitted only while the agreement's `negotiation_round` is strictly below 3, so the fourth
    counter is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`."
    PRD §3.3: "The airline's `PROPOSE` is bounded by the same figure but read inclusively — it is
    permitted while `negotiation_round` is at most 3 — so the airline may always answer the third
    counter, and only a further counter is refused."

    Design: Corner/errors/corner_error_negotiation_round_limit_is_triggerable
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    agreement = fx.open_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    agency = agency_headers(partner["id"])

    for counter_pct, propose_pct in ((0.030, 0.026), (0.029, 0.027), (0.028, 0.0275)):
        fx.negotiate(
            api,
            agreement["id"],
            NEGOTIATION_COUNTER,
            headers=agency,
            proposed_incentive_pct=counter_pct,
        )
        answered = fx.negotiate(
            api,
            agreement["id"],
            NEGOTIATION_PROPOSE,
            proposed_incentive_pct=propose_pct,
        )
    assert answered["negotiation_round"] == 3
    assert answered["proposed_incentive_pct"] == 0.0275

    fourth = api.create_negotiation_round(
        agreement["id"],
        f.negotiation_payload(NEGOTIATION_COUNTER, proposed_incentive_pct=0.0279),
        headers=agency,
    )
    validate_error(fourth, ApiErrorId.NEGOTIATION_ROUND_LIMIT)

    stalled = fx.read_agreement(api, agreement["id"])
    assert stalled["negotiation_round"] == 3
    assert stalled["proposed_incentive_pct"] == 0.0275

    signed = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_ACCEPT,
        headers=OTHER_DISTRIBUTION_MANAGER_HEADERS,
    )
    assert signed["agreed_incentive_pct"] == 0.0275

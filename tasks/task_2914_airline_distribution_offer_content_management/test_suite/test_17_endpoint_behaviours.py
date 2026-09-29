"""Endpoints: composed list filters, action preconditions, fan-out and computed reads."""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CERT_ENV_A,
    CERT_STATUS_CERTIFIED,
    CERTIFICATION_CERTIFIED,
    CERTIFICATION_TESTING,
    CONTENT_TIER_FULL,
    DECISION_CERTIFY,
    DISTRIBUTION_MANAGER_HEADERS,
    FILING_SUSPENDED,
    FULFILLMENT_ACTION_TICKET,
    FULFILLMENT_RESERVED,
    FULFILLMENT_TICKETED,
    OFFER_CONSTRUCTED,
    OFFER_PUBLISHED,
    OFFER_WITHDRAWN,
    PARTNER_TYPE_CORPORATE,
    PAYMENT_PAID,
    READINESS_STRICT,
    TEST_PASSED,
    VALIDITY_IN_EFFECT,
    VALIDITY_LAPSED,
    VALIDITY_PENDING,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_BASIS = "YCORN01"
CORNER_TOTAL_CENTS = 46585
OTHER_BASIS = "YOTHER1"
WINDOW_FROM = "2026-09-01T00:00:00.000Z"
WINDOW_TO = "2026-10-01T00:00:00.000Z"


def _corner_channel(api):
    return fx.create_ndc_channel(api, with_surcharge_rules=False)


def _corner_agency(api):
    return fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )


def _offers(api, **params):
    rows, meta = validate_paginated(
        api.list_offers(headers=DISTRIBUTION_MANAGER_HEADERS, params=params)
    )
    return rows, meta["total_count"]


def test_the_offer_list_applies_its_filters_conjunctively(api):
    """PRD §3.5: "Offers are discoverable by `channel_id`, `partner_id`, `fare_filing_id`,
    `bundle_id`, `corporate_contract_id` and `status`."
    PRD §2.3: "For every list response the `meta` object carries `limit` (the effective page size
    applied), `offset` (the effective starting position applied), `total_count` (the number of
    records matching the filters before pagination), and `has_more` (true when records remain beyond
    the current page)."

    Design: Corner/endpoints/corner_offer_list_filters_compose_on_channel_and_status
    """
    channel = _corner_channel(api)
    other_channel = fx.create_full_channel(
        api, channel_code="CORNER_SUR", content_markup_pct=0.035
    )
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])

    published = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, published["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    constructed = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )

    rows, total = _offers(api, channel_id=channel["id"], status=OFFER_PUBLISHED)
    assert total == 1
    assert rows[0]["id"] == published["id"]

    _rows, total = _offers(api, channel_id=channel["id"])
    assert total == 2

    rows, total = _offers(api, channel_id=channel["id"], status=OFFER_CONSTRUCTED)
    assert total == 1
    assert rows[0]["id"] == constructed["id"]

    _rows, total = _offers(api, channel_id=other_channel["id"])
    assert total == 0

    single = fx.read_offer(api, constructed["id"])
    assert single["status"] == OFFER_CONSTRUCTED


def test_ticketing_reads_the_payment_dimension_as_its_precondition(api):
    """PRD §3.6: "Ticketing advances `RESERVED → TICKETED` and is the one fulfilment move that
    reads the other dimension: it requires `payment_status` to be `PAID`, else
    `ERR_ORDER_NOT_PAID`."
    PRD §3.6: "The two status dimensions are genuinely independent: they are advanced by separate
    operations and neither is inferred from the other."

    Design: Corner/endpoints/corner_ticketing_before_capture_is_refused_by_the_action_endpoint
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    fx.create_signed_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)

    too_early = api.post_order_fulfillment(
        order["id"], f.fulfillment_payload(FULFILLMENT_ACTION_TICKET), headers=headers
    )
    validate_error(too_early, ApiErrorId.ORDER_NOT_PAID)

    unchanged = fx.read_order(api, order["id"], headers=headers)
    assert unchanged["fulfillment_status"] == FULFILLMENT_RESERVED
    assert unchanged["version"] == 1

    paid = fx.capture_payment(api, order["id"], CORNER_TOTAL_CENTS, headers=headers)
    assert paid["payment_status"] == PAYMENT_PAID

    ticketed = validate_success(
        api.post_order_fulfillment(
            order["id"],
            f.fulfillment_payload(FULFILLMENT_ACTION_TICKET),
            headers=headers,
        )
    )
    assert ticketed["fulfillment_status"] == FULFILLMENT_TICKETED
    assert ticketed["payment_status"] == PAYMENT_PAID


def test_one_suspension_call_withdraws_every_offer_on_that_filing_only(api):
    """PRD §3.2: "Suspension increases the filing's `version` by 1 and, in the same operation, sets
    every offer that references this filing and sits in `CONSTRUCTED` or `PUBLISHED` to
    `WITHDRAWN`, each such offer's `version` increasing by 1."
    PRD §3.2: "An `ACTIVE` filing may be driven to `SUSPENDED` by either a `PricingAnalyst` or a
    `DistributionManager` — this is the one filing transition the commercial side shares — with no
    precondition beyond transition legality."

    Design: Corner/endpoints/corner_one_suspension_call_withdraws_every_dependent_offer
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    other_filing = fx.create_ndc_filing(api, fare_basis_code=OTHER_BASIS)
    headers = agency_headers(partner["id"])

    published = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, published["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    constructed = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    untouched = fx.construct_offer(
        api, channel["id"], partner["id"], other_filing["id"], headers=headers
    )

    suspended = fx.drive_filing(
        api,
        filing["id"],
        FILING_SUSPENDED,
        headers=DISTRIBUTION_MANAGER_HEADERS,
        reason="bulk pull",
    )
    assert suspended["status"] == FILING_SUSPENDED

    assert fx.read_offer(api, published["id"])["status"] == OFFER_WITHDRAWN
    assert fx.read_offer(api, constructed["id"])["status"] == OFFER_WITHDRAWN
    # An offer on a different filing is outside the cascade.
    assert fx.read_offer(api, untouched["id"])["status"] == OFFER_CONSTRUCTED

    _rows, total = _offers(api, channel_id=channel["id"], status=OFFER_WITHDRAWN)
    assert total == 2


def test_the_offer_keeps_the_channel_version_it_was_priced_against(api):
    """PRD §3.5: "`priced_channel_version` records the channel's `version` as observed while
    pricing, so an auditor can later tell whether the channel's content policy has moved since the
    offer was quoted."
    PRD §3.1: "What it deliberately does **not** do is reprice or withdraw anything: offers already
    constructed keep the prices they were built with and keep their recorded
    `priced_channel_version`, and no offer changes state because the policy moved."
    PRD §3.5: "Three conditions guard it: the logical clock must be strictly before `expires_at`;
    the offer's fare filing must *still* be `ACTIVE`, because a filing that left `ACTIVE` between
    construction and publication makes the quote unsellable and yields
    `ERR_FARE_FILING_NOT_ACTIVE`; and the submitted `disclosure_ack_codes` must cover every entry of
    the channel's `required_disclosure_codes` under the set semantics of §2.11, failing with
    `ERR_DISCLOSURE_INCOMPLETE`."

    Design: Corner/endpoints/corner_offer_pins_the_channel_version_it_was_priced_against
    """
    channel = _corner_channel(api)
    assert channel["version"] == 1
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    assert offer["priced_channel_version"] == 1
    assert offer["subtotal_cents"] == CORNER_TOTAL_CENTS

    patched = fx.revise_content_policy(
        api,
        channel["id"],
        content_tier=CONTENT_TIER_FULL,
        required_disclosure_codes=["DOT-FARE-INCL", "EU-261"],
    )
    assert patched["version"] == 2
    assert patched["content_tier_rank"] == 3

    stale = fx.read_offer(api, offer["id"], headers=headers)
    # A snapshot, not a live pointer.
    assert stale["priced_channel_version"] == 1
    assert stale["subtotal_cents"] == CORNER_TOTAL_CENTS
    assert stale["status"] == OFFER_CONSTRUCTED

    # The publish call is judged against the channel's new policy, not the snapshot.
    short = api.publish_offer(
        offer["id"], f.publish_payload(["DOT-FARE-INCL"]), headers=headers
    )
    validate_error(short, ApiErrorId.DISCLOSURE_INCOMPLETE)

    published = fx.publish_offer(
        api, offer["id"], ["DOT-FARE-INCL", "EU-261"], headers=headers
    )
    assert published["status"] == OFFER_PUBLISHED
    assert published["priced_channel_version"] == 1


def test_contract_validity_is_recomputed_from_the_clock_on_every_read(api):
    """PRD §3.4: "From that interval and the logical clock the service derives `validity_state`, a
    computed field with three values: `PENDING` while the clock is strictly before `effective_from`,
    `IN_EFFECT` while the clock is at or after `effective_from` and strictly before `effective_to`,
    and `LAPSED` once the clock reaches `effective_to`."
    PRD §3.4: "Because the derivation reads the clock at request time rather than at write time, the
    same contract reports different states as the clock advances, with no mutation and no version
    bump in between."
    PRD §3.4: "Contracts are discoverable by `corporate_partner_id`, by `negotiated_fare_filing_id`
    and by `validity_state`, the last of which is evaluated against the clock at the moment the list
    is served."

    Design: Corner/endpoints/corner_contract_validity_state_is_recomputed_from_the_clock
    """
    corporate = fx.create_partner(
        api,
        partner_name="Acme Corner Industries",
        partner_type=PARTNER_TYPE_CORPORATE,
        iata_code="55555552",
        home_country="DE",
    )
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    contract = fx.create_contract(
        api,
        corporate["id"],
        filing["id"],
        effective_from=WINDOW_FROM,
        effective_to=WINDOW_TO,
        account_code="ACME-WIN",
        traceability_required=False,
        tracking_ref_prefix="ACME-",
        min_content_tier_rank=1,
    )
    # The clock still sits at startup, strictly before the window opens.
    assert contract["validity_state"] == VALIDITY_PENDING
    assert contract["version"] == 1
    before = fx.read_contract(api, contract["id"], headers=AUDITOR_HEADERS)
    assert before["validity_state"] == VALIDITY_PENDING

    fx.set_clock(api, WINDOW_FROM)
    at_open = fx.read_contract(api, contract["id"], headers=AUDITOR_HEADERS)
    # effective_from is inclusive.
    assert at_open["validity_state"] == VALIDITY_IN_EFFECT
    assert at_open["version"] == 1

    fx.set_clock(api, WINDOW_TO)
    at_close = fx.read_contract(api, contract["id"], headers=AUDITOR_HEADERS)
    # effective_to is exclusive, and the PRD's third value is LAPSED.
    assert at_close["validity_state"] == VALIDITY_LAPSED
    assert at_close["version"] == 1

    _rows, meta = validate_paginated(
        api.list_corporate_contracts(
            headers=ADMIN_HEADERS, params={"validity_state": VALIDITY_IN_EFFECT}
        )
    )
    assert meta["total_count"] == 0


def test_an_outstanding_scheduled_slot_defers_the_certification_decision(api):
    """PRD §3.8: "A `CERTIFY` decision advances `TESTING → CERTIFIED` and is doubly gated: no test
    of the certification may still be in `SCHEDULED` — an outstanding slot makes the decision
    premature and yields `ERR_INVALID_STATE_TRANSITION` — and the readiness score of the variant
    named by `readiness_variant` must be at or above 80, with anything below reported as
    `ERR_READINESS_BELOW_MINIMUM`."
    PRD §3.8: "On success `certified_variant` records which variant was used, the partner's
    `certification_status` becomes `CERTIFIED` with the `DistributionPartner`'s `version` increasing
    by 1, and every agreement of that partner-and-channel pair sitting in `SUSPENDED` returns to
    `SIGNED`."

    Design: Corner/endpoints/corner_certify_is_conditional_on_no_outstanding_scheduled_test
    """
    channel = _corner_channel(api)
    partner = fx.create_tech_partner(
        api, partner_name="Tango Corner Systems", iata_code="55555551"
    )
    certification = fx.open_certification(
        api, partner["id"], channel["id"], env_code=CERT_ENV_A
    )
    mandatory = fx.schedule_test(
        api,
        certification["id"],
        partner["id"],
        "SHOP_SEARCH",
        "2026-08-03T09:00:00.000Z",
        duration_minutes=60,
        is_mandatory=True,
    )
    optional = fx.schedule_test(
        api,
        certification["id"],
        partner["id"],
        "ORDER_CREATE",
        "2026-08-03T13:00:00.000Z",
        duration_minutes=30,
        is_mandatory=False,
    )
    fx.report_outcome(api, mandatory["id"], partner["id"], TEST_PASSED, score=90)
    assert fx.read_certification(api, certification["id"])["readiness_score_strict"] == 90

    premature = api.post_certification_decision(
        certification["id"],
        f.decision_payload(DECISION_CERTIFY, READINESS_STRICT),
        headers=ADMIN_HEADERS,
    )
    # The slot gate speaks first, even with a passing score already on file.
    validate_error(premature, ApiErrorId.INVALID_STATE_TRANSITION)
    assert premature.json()["data"]["error_id"] != ApiErrorId.READINESS_BELOW_MINIMUM

    deferred = fx.read_certification(api, certification["id"])
    assert deferred["status"] == CERTIFICATION_TESTING
    assert deferred["certified_variant"] is None

    fx.report_outcome(api, optional["id"], partner["id"], TEST_PASSED, score=68)
    certified = fx.record_decision(
        api, certification["id"], DECISION_CERTIFY, READINESS_STRICT
    )
    assert certified["status"] == CERTIFICATION_CERTIFIED
    assert certified["certified_variant"] == READINESS_STRICT
    # (90*3 + 68*1) / 4 = 84.5 -> 85, above the minimum of 80.
    assert certified["readiness_score_strict"] == 85
    assert certified["reserved_test_minutes"] == 0
    assert fx.read_partner(api, partner["id"])["certification_status"] == CERT_STATUS_CERTIFIED

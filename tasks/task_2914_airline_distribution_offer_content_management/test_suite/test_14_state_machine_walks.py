"""State machines: declared edges, initial states, terminal lockdown and side effects."""

from test_helpers import (
    ADMIN_HEADERS,
    AGREEMENT_PROPOSED,
    AGREEMENT_WITHDRAWN,
    CERTIFICATION_TESTING,
    CERT_ENV_A,
    CERT_STATUS_IN_CERTIFICATION,
    CERT_STATUS_UNCERTIFIED,
    FILING_ACTIVE,
    FILING_DRAFT,
    FILING_FILED,
    FILING_SUSPENDED,
    NEGOTIATION_ACCEPT,
    NEGOTIATION_COUNTER,
    NEGOTIATION_WITHDRAW,
    OFFER_PUBLISHED,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    OFFER_WITHDRAWN,
    PAYMENT_ACTION_CAPTURE,
    PAYMENT_PAID,
    TEST_PASSED,
    TEST_SCHEDULED,
    TIER_1,
    ApiErrorId,
    agency_headers,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    technology_partner_headers,
    validate_error,
    validate_paginated,
)

CORNER_BASIS = "YCORN01"
CORNER_TOTAL_CENTS = 46585
SLOT_START = "2026-08-03T09:00:00.000Z"
SLOT_END = "2026-08-03T10:00:00.000Z"
CODE_SHOP = "SHOP_SEARCH"


def _corner_channel(api):
    """CORNER_NDC: markup 0.035, multiplier 1.25, one disclosure code, no surcharge rules."""
    return fx.create_ndc_channel(api, with_surcharge_rules=False)


def _corner_agency(api):
    return fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )


def _corner_tech_partner(api):
    return fx.create_tech_partner(
        api, partner_name="Tango Corner Systems", iata_code="55555551"
    )


def _corner_certification_with_one_slot(api):
    channel = _corner_channel(api)
    partner = _corner_tech_partner(api)
    certification = fx.open_certification(
        api, partner["id"], channel["id"], env_code=CERT_ENV_A
    )
    test = fx.schedule_test(
        api,
        certification["id"],
        partner["id"],
        CODE_SHOP,
        SLOT_START,
        duration_minutes=60,
        is_mandatory=True,
    )
    return partner, certification, test


def _published_corner_offer(api):
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    assert offer["total_cents"] == CORNER_TOTAL_CENTS
    published = fx.publish_offer(
        api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    assert published["version"] == 2
    return channel, partner, filing, published, headers


def test_the_filing_walks_draft_to_filed_to_active_one_version_per_edge(api):
    """PRD §3.2: "A filing moves `DRAFT → FILED` once the service re-verifies that `sale_to` is
    strictly after `sale_from` and that `travel_to` is at or after `travel_from`; a filing whose
    windows are inverted at this point is rejected with `ERR_INVALID_REQUEST`. The move refreshes
    `updated_at` and increases the filing's `version` by 1."
    PRD §3.2: "`FILED → ACTIVE` is the moment the fare becomes sellable, and it is gated by the
    sale-window exclusivity rule below; once a filing is `ACTIVE`, offer construction against it
    stops failing with `ERR_FARE_FILING_NOT_ACTIVE`, and the transition increases `version` by
    1."

    Design: Corner/state_machines/corner_fare_filing_walks_draft_to_filed_to_active
    """
    filing = fx.create_fare_filing(
        api, fare_basis_code=CORNER_BASIS, base_amount_cents=45010
    )
    assert filing["status"] == FILING_DRAFT
    assert filing["version"] == 1

    filed = fx.drive_filing(api, filing["id"], FILING_FILED)
    assert filed["status"] == FILING_FILED
    assert filed["version"] == 2

    active = fx.drive_filing(api, filing["id"], FILING_ACTIVE, reason="sale open")
    assert active["status"] == FILING_ACTIVE
    assert active["version"] == 3
    # A lifecycle walk is not a revision: neither revision field moved.
    assert active["revision_number"] == 0
    assert active["base_filing_id"] is None


def test_a_pass_without_a_score_leaves_the_slot_and_the_scores_untouched(api):
    """PRD §3.8: "The `outcome` is `PASSED`, `FAILED` or `CANCELLED`; a `score` between 0 and 100
    inclusive must be present on a pass and on a failure, and its absence there is
    `ERR_INVALID_REQUEST`."
    PRD §3.8: "Every outcome decreases the certification's `reserved_test_minutes` by that
    test's `duration_minutes` and increases the certification's `version` by 1."

    Design: Corner/state_machines/corner_passed_outcome_without_score_is_refused
    """
    partner, certification, test = _corner_certification_with_one_slot(api)
    assert certification["version"] == 1

    refused = api.post_test_outcome(
        test["id"],
        f.outcome_payload(TEST_PASSED),
        headers=technology_partner_headers(partner["id"]),
    )
    validate_error(refused, ApiErrorId.INVALID_REQUEST)

    slots = fx.read_connectivity_tests(api, certification["id"])
    assert len(slots) == 1
    assert slots[0]["status"] == TEST_SCHEDULED
    assert slots[0]["score"] is None

    unchanged = fx.read_certification(api, certification["id"])
    assert unchanged["reserved_test_minutes"] == 60
    assert unchanged["readiness_score_strict"] == 0
    assert unchanged["readiness_score_provisional"] == 0
    # Create plus one accepted scheduling; the refused outcome added nothing.
    assert unchanged["version"] == 2


def test_suspending_the_filing_withdraws_its_published_offer_and_keeps_the_lines(api):
    """PRD §3.2: "Suspension increases the filing's `version` by 1 and, in the same operation,
    sets every offer that references this filing and sits in `CONSTRUCTED` or `PUBLISHED` to
    `WITHDRAWN`, each such offer's `version` increasing by 1."
    PRD §2.4: "An offer's priced lines are never repriced; when the content behind an offer is
    pulled, the offer's own state changes while its lines are retained verbatim for audit."
    PRD §2.10: "**Offer published** — the referenced offer's `status` is `PUBLISHED`, else
    `ERR_OFFER_NOT_PUBLISHED` (409). Applies to `POST /orders`."

    Design: Corner/state_machines/corner_filing_suspension_withdraws_its_published_offer
    """
    _channel, _partner, filing, offer, headers = _published_corner_offer(api)

    suspended = fx.drive_filing(
        api, filing["id"], FILING_SUSPENDED, reason="market pulled"
    )
    assert suspended["status"] == FILING_SUSPENDED
    # Create, FILED, ACTIVE, SUSPENDED.
    assert suspended["version"] == 4

    withdrawn = fx.read_offer(api, offer["id"], headers=headers)
    assert withdrawn["status"] == OFFER_WITHDRAWN
    assert withdrawn["version"] == 3

    lines, meta = validate_paginated(
        api.list_offer_items(offer["id"], headers=ADMIN_HEADERS, params={"limit": 100})
    )
    assert meta["total_count"] == 1
    assert lines[0]["net_amount_cents"] == CORNER_TOTAL_CENTS

    refused = api.create_order(
        f.order_payload(offer["id"], disclosure_ack_codes=fx.NDC_DISCLOSURE_CODES),
        headers=headers,
    )
    validate_error(refused, ApiErrorId.OFFER_NOT_PUBLISHED)


def test_a_certification_is_born_testing_and_its_first_slot_scheduled(api):
    """PRD §3.8: "A new certification opens in `TESTING` with `tested_by_user_id` recording the
    acting `X-User-ID`, `reserved_test_minutes` at 0, `readiness_score_strict` and
    `readiness_score_provisional` at 0, `mandatory_failed_count` at 0, and `certified_variant`
    null. Opening it also moves the partner's `certification_status` to `IN_CERTIFICATION` and
    increases the `DistributionPartner`'s `version` by 1."
    PRD §3.8: "The service computes `scheduled_end` as `scheduled_start` advanced by
    `duration_minutes`, and the slot the test occupies is the **closed** interval running from
    `scheduled_start` through `scheduled_end` inclusive. Scheduling increases the
    certification's `reserved_test_minutes` by `duration_minutes` and increases the
    certification's `version` by 1; the test's `score` starts null and its `status` starts at
    `SCHEDULED`, with `certification_id` bound to the owning certification."

    Design: Corner/state_machines/corner_new_certification_and_test_start_in_their_initial_states
    """
    channel = _corner_channel(api)
    partner = _corner_tech_partner(api)
    assert partner["certification_status"] == CERT_STATUS_UNCERTIFIED
    assert partner["version"] == 1

    certification = fx.open_certification(
        api, partner["id"], channel["id"], env_code=CERT_ENV_A
    )
    assert certification["status"] == CERTIFICATION_TESTING
    assert certification["certified_variant"] is None
    assert certification["mandatory_failed_count"] == 0
    assert certification["reserved_test_minutes"] == 0

    test = fx.schedule_test(
        api,
        certification["id"],
        partner["id"],
        CODE_SHOP,
        SLOT_START,
        duration_minutes=60,
        is_mandatory=True,
    )
    assert test["status"] == TEST_SCHEDULED
    assert test["score"] is None
    assert test["certification_id"] == certification["id"]
    assert_instant_equals(test["scheduled_end"], SLOT_END)

    assert fx.read_certification(api, certification["id"])["reserved_test_minutes"] == 60
    reread = fx.read_partner(api, partner["id"])
    assert reread["certification_status"] == CERT_STATUS_IN_CERTIFICATION
    assert reread["version"] == 2


def test_a_second_capture_on_a_paid_order_re_runs_none_of_the_side_effects(api):
    """PRD §2.10: "**Transition legality** — the targeted resource's current state has an
    outgoing transition for the requested trigger, else `ERR_INVALID_STATE_TRANSITION` (409)."
    PRD §3.6: "A capture advances `AUTHORIZED → PAID` and requires that `payment_amount_cents`
    equal the source offer's `total_cents` — the same figure the order froze into
    `net_revenue_cents` — with any other amount rejected as `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.3: "The ledger moves in exactly two situations: it increases by an order's
    `net_revenue_cents` when that order's payment is captured, and it decreases by the same
    figure when a refund is applied to a previously paid order."

    Design: Corner/state_machines/corner_second_capture_on_a_paid_order_is_rejected
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
    order = fx.create_order(
        api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    paid = fx.capture_payment(api, order["id"], CORNER_TOTAL_CENTS, headers=headers)
    assert paid["payment_status"] == PAYMENT_PAID

    replay = api.post_order_payment(
        order["id"],
        f.payment_payload(PAYMENT_ACTION_CAPTURE, CORNER_TOTAL_CENTS),
        headers=headers,
    )
    validate_error(replay, ApiErrorId.INVALID_STATE_TRANSITION)

    settled = fx.read_order(api, order["id"], headers=headers)
    assert settled["payment_status"] == PAYMENT_PAID
    assert settled["paid_amount_cents"] == CORNER_TOTAL_CENTS
    assert settled["version"] == 2

    assert fx.read_channel(api, channel["id"])["booking_count"] == 1
    ledger = fx.read_agreement(api, agreement["id"])
    assert ledger["cumulative_net_revenue_cents"] == CORNER_TOTAL_CENTS
    assert ledger["incentive_tier"] == TIER_1
    # 46,585 * 0.010 = 465.85, scaled by the channel's 1.25 multiplier -> 582.3125 -> 582.
    assert ledger["incentive_accrued_cents"] == 582


def test_a_withdrawn_agreement_accepts_no_further_negotiation_action(api):
    """PRD §3.3: "A `WITHDRAW` is available to a `DistributionManager` from either `PROPOSED` or
    `COUNTERED`, drives the agreement to the terminal `WITHDRAWN` state, and increases `version`
    by 1. Both `WITHDRAWN` and `SUPERSEDED` are terminal; any negotiation action against an
    agreement in either state is `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.3: "On signing, `agreed_incentive_pct` is frozen to whatever `proposed_incentive_pct`
    currently holds — the frozen figure, not the mutable one, is what the accrual calculation
    uses forever after — `signed_by_user_id` records the accepting operator, and `version`
    increases by 1."

    Design: Corner/state_machines/corner_withdrawn_agreement_refuses_every_further_round
    """
    channel = _corner_channel(api)
    partner = _corner_agency(api)
    agreement = fx.open_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    assert agreement["status"] == AGREEMENT_PROPOSED

    withdrawn = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_WITHDRAW,
        note="partner exited the program",
    )
    assert withdrawn["status"] == AGREEMENT_WITHDRAWN
    assert withdrawn["version"] == 2

    locked_accept = api.create_negotiation_round(
        agreement["id"],
        f.negotiation_payload(NEGOTIATION_ACCEPT),
        headers=OTHER_DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(locked_accept, ApiErrorId.INVALID_STATE_TRANSITION)

    locked_counter = api.create_negotiation_round(
        agreement["id"],
        f.negotiation_payload(NEGOTIATION_COUNTER, proposed_incentive_pct=0.03),
        headers=agency_headers(partner["id"]),
    )
    validate_error(locked_counter, ApiErrorId.INVALID_STATE_TRANSITION)

    final = fx.read_agreement(api, agreement["id"])
    assert final["status"] == AGREEMENT_WITHDRAWN
    assert final["agreed_incentive_pct"] is None
    assert final["version"] == 2


def test_publishing_twice_is_refused_before_the_disclosure_check_runs(api):
    """PRD §3.5: "On success the offer's `acknowledged_disclosure_codes` is set to the submitted
    codes verbatim, `disclosure_complete` becomes true, and `version` increases by 1. Publication
    is one-shot: a second publish attempt against an offer already in `PUBLISHED` is
    `ERR_INVALID_STATE_TRANSITION`."
    PRD §2.10: "Requests are validated in a strict, globally fixed precedence order, and the
    **first** failing check determines the response."

    Design: Corner/state_machines/corner_publishing_an_already_published_offer_is_not_a_silent_noop
    """
    _channel, _partner, _filing, offer, headers = _published_corner_offer(api)
    assert offer["acknowledged_disclosure_codes"] == list(fx.NDC_DISCLOSURE_CODES)
    assert offer["disclosure_complete"] is True

    republish = api.publish_offer(
        offer["id"], f.publish_payload([]), headers=headers
    )
    # Step 10 speaks before step 15, so the empty acknowledgement is never examined.
    validate_error(republish, ApiErrorId.INVALID_STATE_TRANSITION)
    assert republish.json()["data"]["error_id"] != ApiErrorId.DISCLOSURE_INCOMPLETE

    unchanged = fx.read_offer(api, offer["id"], headers=headers)
    assert unchanged["acknowledged_disclosure_codes"] == list(fx.NDC_DISCLOSURE_CODES)
    assert unchanged["disclosure_complete"] is True
    assert unchanged["status"] == OFFER_PUBLISHED
    assert unchanged["version"] == 2

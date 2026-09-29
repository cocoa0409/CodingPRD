"""Cross-cutting layers: both concurrency guards, a two-way cascade, a clamp, and immediacy."""

from test_helpers import (
    ADMIN_HEADERS,
    AGREEMENT_PROPOSED,
    AGREEMENT_SIGNED,
    AGREEMENT_SUSPENDED,
    AUDITOR_HEADERS,
    CERT_ENV_A,
    CERT_STATUS_CERTIFIED,
    CERT_STATUS_IN_CERTIFICATION,
    CERTIFICATION_CERTIFIED,
    CERTIFICATION_SUSPENDED,
    CERTIFICATION_TESTING,
    DECISION_REINSTATE,
    DECISION_SUSPEND,
    DISTRIBUTION_MANAGER_HEADERS,
    FILING_ACTIVE,
    FILING_DRAFT,
    FILING_SUPERSEDED,
    OFFER_PUBLISHED,
    OFFER_WITHDRAWN,
    PAYMENT_PAID,
    PRICING_ANALYST_HEADERS,
    TIER_1,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_BASIS = "YCORN01"
CORNER_FARE_CENTS = 45010
CORNER_TOTAL_CENTS = 46585
REVISED_FARE_CENTS = 46010


def _corner_channel(api):
    return fx.create_ndc_channel(api, with_surcharge_rules=False)


def _corner_agency(api):
    return fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )


def _agreement_total(api, partner_id):
    _rows, meta = validate_paginated(
        api.list_agency_agreements(
            headers=ADMIN_HEADERS, params={"partner_id": partner_id}
        )
    )
    return meta["total_count"]


def test_a_partner_version_observed_before_certification_is_already_stale(api):
    """PRD §2.7: "A `POST /agency-agreements` request must carry `expected_partner_version` holding
    the `version` the client last observed on the target `DistributionPartner`."
    PRD §2.7: "If `expected_partner_version` does not equal the partner's current `version`, the
    request is rejected with `ERR_STALE_PARTNER_VERSION` (HTTP 412) and nothing is written."
    PRD §3.8: "Opening it also moves the partner's `certification_status` to `IN_CERTIFICATION` and
    increases the `DistributionPartner`'s `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_partner_version_blocks_the_agreement_supersede
    """
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    cached_version = agency["version"]
    assert cached_version == 1

    certification = fx.open_certification(
        api, agency["id"], channel["id"], headers=ADMIN_HEADERS, env_code=CERT_ENV_A
    )

    stale = api.create_agency_agreement(
        f.agreement_payload(agency["id"], channel["id"], cached_version),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(stale, ApiErrorId.STALE_PARTNER_VERSION)
    assert _agreement_total(api, agency["id"]) == 0

    refreshed = fx.read_partner(api, agency["id"])
    assert refreshed["version"] == 2
    assert refreshed["certification_status"] == CERT_STATUS_IN_CERTIFICATION

    # The identical request re-quoted against the current version lands.
    retried = fx.open_agreement(
        api, agency["id"], channel["id"], refreshed["version"]
    )
    assert retried["status"] == AGREEMENT_PROPOSED
    assert _agreement_total(api, agency["id"]) == 1
    assert fx.read_certification(api, certification["id"])["status"] == CERTIFICATION_TESTING


def test_a_filing_version_observed_before_activation_is_already_stale(api):
    """PRD §2.7: "A `POST /fare-filings/{id}/revisions` request must carry
    `expected_fare_filing_version` holding the `version` the client last observed on the base filing
    named in the path."
    PRD §3.2: "A stale `expected_fare_filing_version` aborts the whole operation with
    `ERR_STALE_FARE_FILING_VERSION` — no revision is created and the base is not superseded."
    PRD §3.2: "Revision is permitted against a base filing in `ACTIVE` or in `FILED`, and both edges
    behave identically in structure: the base filing moves to `SUPERSEDED` and its `version`
    increases by 1, and a brand-new filing is created in `DRAFT` that copies the base's
    `fare_basis_code`, `origin`, `destination`, `cabin`, `travel_from`, `travel_to`,
    `min_content_tier_rank`, `refundable` and `is_private`, records `base_filing_id` as the base
    filing's identifier, and sets `revision_number` to the base's `revision_number` plus 1."
    PRD §3.2: "Fare filings are discoverable by `status`, by `origin`, by `destination`, by `cabin`
    and by `base_filing_id` — the last of these being how a caller walks a revision chain, since
    listing by a base filing's identifier returns the revisions filed against it."
    PRD §3.2: "The move refreshes `updated_at` and increases the filing's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_filing_version_blocks_the_revision_supersede
    """
    filing = fx.create_active_filing(
        api, fare_basis_code=CORNER_BASIS, base_amount_cents=CORNER_FARE_CENTS
    )
    # DRAFT -> FILED -> ACTIVE is two writes on top of creation.
    assert filing["version"] == 3

    stale = api.create_fare_filing_revision(
        filing["id"],
        f.revision_payload(1, base_amount_cents=REVISED_FARE_CENTS),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(stale, ApiErrorId.STALE_FARE_FILING_VERSION)

    unmoved = fx.read_filing(api, filing["id"])
    assert unmoved["status"] == FILING_ACTIVE
    assert unmoved["version"] == 3

    revision = fx.file_revision(
        api, filing["id"], unmoved["version"], base_amount_cents=REVISED_FARE_CENTS
    )
    assert revision["status"] == FILING_DRAFT
    assert revision["revision_number"] == 1
    assert revision["base_filing_id"] == filing["id"]
    assert revision["base_amount_cents"] == REVISED_FARE_CENTS
    assert revision["fare_basis_code"] == CORNER_BASIS

    superseded = fx.read_filing(api, filing["id"])
    assert superseded["status"] == FILING_SUPERSEDED
    assert superseded["version"] == 4

    _rows, meta = validate_paginated(
        api.list_fare_filings(
            headers=ADMIN_HEADERS, params={"base_filing_id": filing["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_suspension_walks_three_entities_down_and_reinstatement_only_two_back(api):
    """PRD §3.8: "A `SUSPEND` decision advances `CERTIFIED → SUSPENDED` with no precondition, and it
    is the destructive direction."
    PRD §3.8: "The partner's `certification_status` falls back to `IN_CERTIFICATION` and the
    partner's `version` increases by 1; every agreement of that partner-and-channel pair in `SIGNED`
    becomes `SUSPENDED`; and each such agreement's offers sitting in `CONSTRUCTED` or `PUBLISHED`
    become `WITHDRAWN`."
    PRD §3.8: "A `REINSTATE` decision advances `SUSPENDED → CERTIFIED`, restores the partner's
    `certification_status` to `CERTIFIED` with a `version` increase of 1, and returns every
    `SUSPENDED` agreement of the pair to `SIGNED` — without resurrecting the offers that were
    withdrawn."
    PRD §3.3: "Reinstatement is deliberately narrow in scope: `agreed_incentive_pct`,
    `cumulative_net_revenue_cents` and `incentive_accrued_cents` are all left exactly as the
    suspension found them, the agreement's `version` increases by 1, and the offers withdrawn during
    suspension stay withdrawn."

    Design: Corner/cross_cutting_complexity_layers/corner_certification_suspension_and_reinstatement_cascade_both_ways
    """
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    certification = fx.certify_partner(
        api, agency["id"], channel["id"], score=90, env_code=CERT_ENV_A
    )
    assert certification["status"] == CERTIFICATION_CERTIFIED

    certified = fx.read_partner(api, agency["id"])
    assert certified["certification_status"] == CERT_STATUS_CERTIFIED
    agreement = fx.create_signed_agreement(
        api, agency["id"], channel["id"], certified["version"]
    )
    assert agreement["status"] == AGREEMENT_SIGNED

    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    headers = agency_headers(agency["id"])
    offer = fx.construct_offer(
        api, channel["id"], agency["id"], filing["id"], headers=headers
    )
    published = fx.publish_offer(
        api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    assert published["status"] == OFFER_PUBLISHED
    before = fx.read_partner(api, agency["id"])["version"]

    suspended = fx.record_decision(api, certification["id"], DECISION_SUSPEND)
    assert suspended["status"] == CERTIFICATION_SUSPENDED
    fallen = fx.read_partner(api, agency["id"])
    assert fallen["certification_status"] == CERT_STATUS_IN_CERTIFICATION
    assert fallen["version"] == before + 1
    assert fx.read_agreement(api, agreement["id"])["status"] == AGREEMENT_SUSPENDED
    assert fx.read_offer(api, offer["id"])["status"] == OFFER_WITHDRAWN

    reinstated = fx.record_decision(api, certification["id"], DECISION_REINSTATE)
    assert reinstated["status"] == CERTIFICATION_CERTIFIED
    restored = fx.read_partner(api, agency["id"])
    assert restored["certification_status"] == CERT_STATUS_CERTIFIED
    assert restored["version"] == before + 2

    resigned = fx.read_agreement(api, agreement["id"])
    assert resigned["status"] == AGREEMENT_SIGNED
    assert resigned["agreed_incentive_pct"] == 0.025
    assert resigned["cumulative_net_revenue_cents"] == 0
    assert resigned["incentive_accrued_cents"] == 0
    assert resigned["tier_downgrade_count"] == 0
    # The one hop that is deliberately not walked back.
    assert fx.read_offer(api, offer["id"])["status"] == OFFER_WITHDRAWN


def test_the_incentive_cap_bites_before_the_single_rounding_step(api):
    """PRD §3.3: "3. **Cap, then round once.** The scaled figure is compared against
    `incentive_cap_cents` and the lesser of the two is taken. That capped value is then rounded half
    up to whole cents, and the result is stored in `incentive_accrued_cents`. The rounding happens
    exactly once, here, after the cap — never on the band walk and never on the multiplier."
    PRD §3.3: "The first band is the lesser of the qualifying revenue and 5,000,000 cents, and earns
    0.010."
    PRD §3.3: "4. **Label the tier.** `incentive_tier` is derived from the same qualifying revenue:
    `TIER_3` when the revenue is at or above 20,000,000 cents, otherwise `TIER_2` when it is at or
    above 5,000,000 cents, otherwise `TIER_1`."
    PRD §3.9: "First the channel's `activity_cost_cents` is assembled: for every order on the channel
    whose `payment_status` is `PAID`, the service adds the channel's `per_message_cost_cents`
    multiplied by that order's `message_count` plus the channel's `per_segment_fee_cents` multiplied
    by that order's `segment_count`; to that transaction total it adds the sum of
    `incentive_accrued_cents` over every agency agreement on this channel whose `status` is `SIGNED`."

    Design: Corner/cross_cutting_complexity_layers/corner_incentive_accrual_is_clamped_by_the_agreement_cap
    """
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    agreement = fx.create_signed_agreement(
        api,
        agency["id"],
        channel["id"],
        agency["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=400,
        target_net_revenue_cents=5000000,
    )
    headers = agency_headers(agency["id"])
    offer = fx.construct_offer(
        api, channel["id"], agency["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)

    paid = fx.capture_payment(api, order["id"], CORNER_TOTAL_CENTS, headers=headers)
    assert paid["payment_status"] == PAYMENT_PAID

    ledger = fx.read_agreement(api, agreement["id"])
    assert ledger["cumulative_net_revenue_cents"] == CORNER_TOTAL_CENTS
    # 46,585 * 0.010 * 1.25 = 582.3125, clamped to the cap of 400 before rounding.
    assert ledger["incentive_accrued_cents"] == 400
    assert ledger["incentive_tier"] == TIER_1
    assert ledger["tier_downgrade_count"] == 0

    costs = fx.read_channel(api, channel["id"])
    # 12 + 40 + the capped 400, over one paid booking.
    assert costs["activity_cost_cents"] == 452
    assert costs["cost_per_booking_activity_cents"] == 452
    assert costs["cost_per_booking_flat_cents"] == 400000
    assert costs["booking_count"] == 1


def test_the_first_read_after_the_capture_is_already_authoritative(api):
    """PRD §3.6: "On success `paid_amount_cents` becomes the captured amount, the channel's
    `booking_count` increases by 1, and then, in this order: if the order names an agreement, that
    agreement's `cumulative_net_revenue_cents` increases by the order's `net_revenue_cents` and the
    incentive accrual of §3.3 re-runs and rewrites `incentive_accrued_cents` and `incentive_tier` (a
    capture can only raise the balance, so the tier may rise and `tier_downgrade_count` is left
    untouched); and finally the channel's distribution-cost figures re-run, rewriting
    `activity_cost_cents`, `cost_per_booking_flat_cents` and `cost_per_booking_activity_cents`."
    PRD §3.9: "Reading a channel returns both figures together with the underlying
    `activity_cost_cents` and `booking_count`, which is the report a `ComplianceAuditor` or a
    `DistributionManager` uses to compare a legacy distribution link against a direct or aggregator
    connection."
    PRD §3.6: "The order's `version` increases by 1."

    Design: Corner/consistency_model/corner_capture_effects_are_visible_to_the_very_next_read
    """
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    agreement = fx.create_signed_agreement(
        api, agency["id"], channel["id"], agency["version"]
    )
    headers = agency_headers(agency["id"])
    offer = fx.construct_offer(
        api, channel["id"], agency["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)

    # The write's own response body already carries the new state.
    captured = fx.capture_payment(api, order["id"], CORNER_TOTAL_CENTS, headers=headers)
    assert captured["payment_status"] == PAYMENT_PAID
    assert captured["paid_amount_cents"] == CORNER_TOTAL_CENTS

    # And the very next reads, by a different role, need no retry or delay.
    ledger = fx.read_channel(api, channel["id"], headers=AUDITOR_HEADERS)
    assert ledger["booking_count"] == 1
    assert ledger["activity_cost_cents"] == 634
    assert ledger["cost_per_booking_flat_cents"] == 400000
    assert ledger["cost_per_booking_activity_cents"] == 634

    accrual = validate_success(
        api.get_agency_agreement(agreement["id"], headers=AUDITOR_HEADERS)
    )
    assert accrual["cumulative_net_revenue_cents"] == CORNER_TOTAL_CENTS
    assert accrual["incentive_accrued_cents"] == 582
    assert accrual["incentive_tier"] == TIER_1

    reread = validate_success(api.get_order(order["id"], headers=AUDITOR_HEADERS))
    assert reread["payment_status"] == PAYMENT_PAID
    assert reread["paid_amount_cents"] == CORNER_TOTAL_CENTS
    assert reread["version"] == 2

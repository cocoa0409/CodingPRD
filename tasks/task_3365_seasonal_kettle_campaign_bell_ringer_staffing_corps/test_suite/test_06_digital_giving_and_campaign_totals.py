"""Digital giving attribution, reversal and the campaign raised total."""
from test_helpers import (
    ApiErrorId,
    activate_kettle_location_ok,
    assert_same_instant,
    attribute_giving,
    attribute_giving_ok,
    create_collection,
    create_digital_giving,
    create_digital_giving_raw,
    deposit_collection_ok,
    get_campaign,
    get_campaign_summary,
    get_digital_giving,
    get_kettle_location,
    reverse_giving_ok,
    setup_kettle_network,
    validate_error,
    validate_success,
    verify_collection_ok,
)


def test_attribution_raises_campaign_total_before_reverse(api):
    """PRD §3.5: "Attribution stores the chosen `kettle_location_id` on the
    gift, sets `attributed_cents` to the gift's `amount_cents`, and recomputes
    both the location's `location_total_cents` and the campaign's
    `total_raised_cents`."

    Design: Difficulty/transitive_cascade/digital_giving_reverse_cascade_to_campaign_total
    """
    network = setup_kettle_network()
    gift = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                 "DG-2026-0001")
    attributed = attribute_giving_ok(gift["id"], network.location["id"])

    assert attributed["attribution_status"] == "ATTRIBUTED"
    assert attributed["attributed_cents"] == 25000
    assert get_kettle_location(network.location["id"])["location_total_cents"] == 25000
    assert get_campaign(network.campaign["id"])["total_raised_cents"] == 25000


def test_giving_reverse_removes_it_from_location_and_campaign_totals(api):
    """PRD §3.5: "Reversing a gift that had been attributed also recomputes the
    location's and the campaign's totals, because money that was counted must
    stop being counted".
    PRD §3.5: "Reversal sets the gift's `attribution_status` to `REVERSED`,
    which is terminal, stores the supplied text in `reversed_reason`, and sets
    `attributed_cents` to 0."

    Design: Difficulty/transitive_cascade/digital_giving_reverse_cascade_to_campaign_total
    """
    network = setup_kettle_network()
    gift = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                 "DG-2026-0001")
    attribute_giving_ok(gift["id"], network.location["id"])

    reversed_gift = reverse_giving_ok(gift["id"], reason="donor chargeback")
    assert reversed_gift["attribution_status"] == "REVERSED"
    assert reversed_gift["attributed_cents"] == 0
    assert reversed_gift["reversed_reason"] == "donor chargeback"
    assert get_kettle_location(network.location["id"])["location_total_cents"] == 0
    assert get_campaign(network.campaign["id"])["total_raised_cents"] == 0


def test_second_attribution_raises_campaign_total(api):
    """PRD §3.9: "The digital component sums the `attributed_cents` of gifts
    belonging to the campaign whose `attribution_status` is `ATTRIBUTED`".
    PRD §3.9: "The campaign's `total_raised_cents` is the sum of the two
    components".

    Design: Difficulty/compensating_invariant/digital_giving_reverse_conserves_campaign_raised_cents
    """
    network = setup_kettle_network()
    gift_one = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                     "DG-2026-1001")
    attribute_giving_ok(gift_one["id"], network.location["id"])
    gift_two = create_digital_giving(network.campaign["id"], network.unit["id"], 10000,
                                     "DG-2026-1002", channel="SMS",
                                     occurred_at="2026-11-14T13:00:00Z")
    baseline = get_campaign(network.campaign["id"])["total_raised_cents"]
    assert baseline == 25000

    attributed = attribute_giving_ok(gift_two["id"], network.location["id"])
    assert attributed["attributed_cents"] == 10000
    assert get_campaign(network.campaign["id"])["total_raised_cents"] == 35000


def test_reverse_conserves_campaign_total_across_two_gifts(api):
    """PRD §3.5: "Reversing a gift that had been attributed also recomputes the
    location's and the campaign's totals, because money that was counted must
    stop being counted".
    PRD §3.9: "gifts in `RECEIVED`, `UNATTRIBUTED` or `REVERSED` status are
    excluded."

    Design: Difficulty/compensating_invariant/digital_giving_reverse_conserves_campaign_raised_cents
    """
    network = setup_kettle_network()
    gift_one = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                     "DG-2026-1001")
    attribute_giving_ok(gift_one["id"], network.location["id"])
    gift_two = create_digital_giving(network.campaign["id"], network.unit["id"], 10000,
                                     "DG-2026-1002", channel="SMS",
                                     occurred_at="2026-11-14T13:00:00Z")
    total_before_second_attribution = get_campaign(network.campaign["id"])["total_raised_cents"]

    attribute_giving_ok(gift_two["id"], network.location["id"])
    reversed_gift = reverse_giving_ok(gift_two["id"], reason="duplicate processor capture")
    total_after_reverse = get_campaign(network.campaign["id"])["total_raised_cents"]

    assert reversed_gift["attributed_cents"] == 0
    assert total_after_reverse == 25000
    assert total_after_reverse - total_before_second_attribution == 0


def test_attribute_with_empty_candidate_pool_rejected(api):
    """PRD §3.5: "When the pool is empty the attribution is refused with
    `ERR_NO_ELIGIBLE_LOCATION` (HTTP 422)".
    PRD §3.5: "the candidates are the campaign's kettle locations that are
    `ACTIVE`, whose host site holds an `APPROVED` permission".

    Design: Difficulty/boundary_precision_check/digital_giving_attribution_empty_candidate_pool
    """
    network = setup_kettle_network(activate_location=False)
    gift = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                 "DG-2026-0002")

    resp = attribute_giving(gift["id"])
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_LOCATION)


def test_attribute_selects_location_once_active(api):
    """PRD §3.5: "the candidates are the campaign's kettle locations that are
    `ACTIVE`, whose host site holds an `APPROVED` permission, and whose host
    site belongs to the unit credited on the gift."
    PRD §3.5: "Candidates are ranked by `covered_minutes` descending, with ties
    broken by `created_at` ascending and never by `id`, and the top-ranked
    location receives the gift."

    Design: Difficulty/boundary_precision_check/digital_giving_attribution_empty_candidate_pool
    """
    network = setup_kettle_network(activate_location=False)
    gift = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                 "DG-2026-0002")
    validate_error(attribute_giving(gift["id"]), ApiErrorId.ERR_NO_ELIGIBLE_LOCATION)

    activate_kettle_location_ok(network.location["id"])

    attributed = attribute_giving_ok(gift["id"])
    assert attributed["attribution_status"] == "ATTRIBUTED"
    assert attributed["kettle_location_id"] == network.location["id"]
    assert get_kettle_location(network.location["id"])["location_total_cents"] == 25000


def test_campaign_total_excludes_undeposited_collections(api):
    """PRD §3.9: "The counted collections component sums the
    `counted_total_cents` of collections whose kettle location belongs to the
    campaign and whose `deposit_status` is `DEPOSITED` or `RECONCILED`".
    PRD §3.9: "The campaign's `total_raised_cents` is the sum of the two
    components".

    Design: Corner/calculations/campaign_total_raised_excludes_undeposited_and_unattributed
    """
    network = setup_kettle_network()
    deposited = create_collection(network.location["id"], "2026-11-13T18:00:00Z",
                                  declared_cents=70000, currency_cents=70000)
    verify_collection_ok(deposited["id"])
    deposit_collection_ok(deposited["id"], 69650)

    create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                      declared_cents=50000, currency_cents=50000)

    gift = create_digital_giving(network.campaign["id"], network.unit["id"], 25000,
                                 "DG-2026-2001")
    attribute_giving_ok(gift["id"], network.location["id"])

    summary = get_campaign_summary(network.campaign["id"])
    assert summary["collections_counted_cents"] == 70000, "the SUBMITTED collection is excluded"
    assert summary["digital_attributed_cents"] == 25000
    assert summary["total_raised_cents"] == 95000
    # PRD §3.9: "a single location's `location_total_cents` is the same
    # construction scoped to that location" — the DEPOSITED collection's
    # 70000 counted cents plus the 25000 attributed digital gift.
    assert get_kettle_location(network.location["id"])["location_total_cents"] == 95000


def test_digital_giving_outside_campaign_window_rejected(api, digital_giving_processor_headers):
    """PRD §3.5: "The `occurred_at` instant must fall inside the owning
    campaign's window, with both endpoints inclusive, and a gift captured
    outside the season is refused with `ERR_GIVING_OUTSIDE_CAMPAIGN_WINDOW`
    (HTTP 422)."

    Design: Corner/validations/digital_giving_outside_campaign_window_rejected
    """
    network = setup_kettle_network()
    resp = create_digital_giving_raw(network.campaign["id"], network.unit["id"], 5000,
                                     "DG-2026-3001", channel="ONLINE",
                                     occurred_at="2026-12-30T12:00:00Z")
    validate_error(resp, ApiErrorId.ERR_GIVING_OUTSIDE_CAMPAIGN_WINDOW)

    from test_helpers import count_digital_givings_for_campaign
    assert count_digital_givings_for_campaign(network.campaign["id"]) == 0


def test_digital_giving_on_campaign_end_instant_accepted(api):
    """PRD §2.7: "Every window in this system is inclusive at both of its
    endpoints unless a rule explicitly says otherwise, so an instant that falls
    exactly on `permission_starts_on`, `permission_ends_on`,
    `placement_starts_on`, `placement_ends_on`, a campaign's `starts_on` or
    `ends_on`, or a program's `intake_opens_on` or `intake_closes_on` counts as
    inside the window."

    Design: Corner/validations/digital_giving_outside_campaign_window_rejected
    """
    network = setup_kettle_network()
    gift = create_digital_giving(network.campaign["id"], network.unit["id"], 5000,
                                 "DG-2026-3002", channel="ONLINE",
                                 occurred_at="2026-12-24T23:59:59Z")
    assert gift["attribution_status"] == "RECEIVED"
    assert_same_instant(gift["occurred_at"], "2026-12-24T23:59:59Z")
    assert get_digital_giving(gift["id"])["external_ref"] == "DG-2026-3002"

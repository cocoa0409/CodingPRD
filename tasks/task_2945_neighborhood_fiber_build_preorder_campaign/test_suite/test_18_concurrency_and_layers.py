"""Concurrency guards, layered policy interactions and the read-your-writes consistency contract."""

from test_helpers import (
    CLOCK_EPOCH,
    COORDINATOR,
    PM,
    ApiErrorId,
    api_client,
    assert_account,
    assert_build_zone,
    assert_cents,
    assert_crew_load,
    assert_fallback_offer,
    assert_install_appointment,
    assert_instant_equals,
    assert_pct,
    assert_preorder,
    assert_total_count,
    install_appointment_payload,
    list_ledger_for_account,
    list_ledger_for_preorder,
    make_account,
    make_address,
    make_appointment,
    make_crew,
    make_offer,
    make_preorder,
    make_subscriber_headers,
    preorder_payload,
    read_account,
    read_crew,
    read_crew_version,
    read_preorder,
    read_zone,
    read_zone_version,
    set_clock,
    set_serviceability,
    setup_campaign_with_zone,
    setup_converted_preorder,
    setup_not_serviceable_address_with_options,
    setup_serviceable_address,
    setup_zone_with_preorders,
    threshold_payload,
    validate_error,
    validate_success,
    validate_unpaginated,
)

CLOCK_AFTER_DEADLINE = "2026-10-01T00:00:00Z"
OFFER_EXPIRY = "2026-09-01T00:00:00Z"

TIED_OPTIONS = (
    {
        "technology": "FIXED_WIRELESS",
        "min_downstream_mbps": 300,
        "monthly_price_cents": 7000,
        "max_serviceable_distance_m": 1500,
        "priority_rank": 5,
    },
    {
        "technology": "SATELLITE_PARTNER",
        "min_downstream_mbps": 300,
        "monthly_price_cents": 7000,
        "max_serviceable_distance_m": 1500,
        "priority_rank": 5,
    },
)


def test_a_sign_up_quoting_a_superseded_zone_version_must_reread_before_it_lands():
    """A neighbour signed up first, so the second client's remembered version is one behind.

    PRD 2.9: "A `POST /preorders` request must carry `expected_build_zone_version` - a non-optional
    field - holding the `version` of the target `BuildZone` as the client last observed it. If that
    number does not equal the zone's current `version`, the create is rejected with
    `ERR_STALE_BUILD_ZONE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/preorder_create_with_a_stale_zone_version_is_refused_then_succeeds_on_reread
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    first_address = make_address(zone_id, street_address="1 Elm St", distance_to_node_m=100)
    second_address = make_address(zone_id, street_address="3 Elm St", distance_to_node_m=110)
    set_serviceability(first_address["id"], "SERVICEABLE")
    set_serviceability(second_address["id"], "SERVICEABLE")
    first_account = make_account(0)
    second_account = make_account(1)
    stale_version = read_zone_version(zone_id)
    make_preorder(
        zone_id,
        second_address["id"],
        second_account["id"],
        expected_build_zone_version=stale_version,
    )

    refused = api_client.create_preorder(
        preorder_payload(
            zone_id, first_address["id"], first_account["id"], stale_version
        ),
        make_subscriber_headers(first_account["id"]),
    )

    validate_error(refused, ApiErrorId.ERR_STALE_BUILD_ZONE_VERSION, 412)
    fresh_version = read_zone_version(zone_id)
    assert fresh_version == stale_version + 1, fresh_version

    retry = validate_success(
        api_client.create_preorder(
            preorder_payload(
                zone_id, first_address["id"], first_account["id"], fresh_version
            ),
            make_subscriber_headers(first_account["id"]),
        ),
        201,
    )
    assert_preorder(retry)
    assert retry["deposit_status"] == "HELD", retry["deposit_status"]
    settled = read_zone(zone_id)
    assert_build_zone(settled)
    assert settled["provisional_qualifying_count"] == 2, settled
    assert_pct(settled["prereg_rate_pct"], 20.00, "prereg_rate_pct")
    _entries, listing = list_ledger_for_account(first_account["id"])
    assert_total_count(listing, 1)


def test_a_second_booking_quoting_the_crews_first_version_must_reread_before_it_lands():
    """The crew moved when it took the morning window, and the afternoon booking must catch up.

    PRD 2.9: "A `POST /install-appointments` request must likewise carry `expected_crew_version` -
    also non-optional - holding the `version` of the target `InstallCrew` as the client last observed
    it. A value that does not equal the crew's current `version` is rejected with
    `ERR_STALE_CREW_VERSION` (HTTP 412)."

    PRD 2.9: "Every appointment creation, every recorded outcome and every cascade cancellation on
    that crew bumps the crew's `version`, so a stale number means the client planned against
    `booked_minutes_total` and buffer geometry that have since moved."

    Design: Corner/cross_cutting_complexity_layers/appointment_create_with_a_stale_crew_version_is_refused_then_succeeds_on_reread
    """
    base = setup_converted_preorder(drop_method="BURY")
    preorder_id = base["converted"]["id"]
    crew = make_crew(name="Bury Crew 1", crew_type="BURY")
    stale_version = crew["version"]
    make_appointment(
        preorder_id,
        crew["id"],
        "2026-10-05T09:00:00Z",
        "2026-10-05T11:00:00Z",
        expected_crew_version=stale_version,
    )

    refused = api_client.create_install_appointment(
        install_appointment_payload(
            preorder_id,
            crew["id"],
            "2026-10-05T12:00:00Z",
            "2026-10-05T13:00:00Z",
            stale_version,
        ),
        COORDINATOR,
    )

    validate_error(refused, ApiErrorId.ERR_STALE_CREW_VERSION, 412)
    fresh_version = read_crew_version(crew["id"])
    assert fresh_version == stale_version + 1, fresh_version
    assert_crew_load(read_crew(crew["id"]), 150, 1)

    retry = validate_success(
        api_client.create_install_appointment(
            install_appointment_payload(
                preorder_id,
                crew["id"],
                "2026-10-05T12:00:00Z",
                "2026-10-05T13:00:00Z",
                fresh_version,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_install_appointment(retry)
    assert retry["occupied_minutes"] == 90, retry["occupied_minutes"]
    assert_crew_load(read_crew(crew["id"]), 240, 2)


def test_lowering_the_bar_to_meet_the_standing_demand_turns_a_failure_into_a_build():
    """Two of twenty-five households is 8.00% either way; only the bar moves, and the outcome flips.

    PRD 3.3: "A zone qualifies when that rounded two-decimal rate is greater than or equal to
    `threshold_pct`; sitting exactly at the bar is qualifying."

    PRD 3.4: "The resulting count and percentage are stamped onto `final_qualifying_count` and
    `final_rate_pct`, and the percentage - rounded half up to two decimal places, then compared -
    decides the outcome: greater than or equal to `threshold_pct` gives `QUALIFIED`, strictly below
    gives `NOT_QUALIFIED`."

    Design: Corner/cross_cutting_complexity_layers/lowering_the_threshold_flips_the_same_demand_to_qualified
    """
    base = setup_zone_with_preorders(
        preorder_count=2, household_count=25, threshold_pct=10.0
    )
    zone_id = base["zone"]["id"]
    at_the_old_bar = read_zone(zone_id)
    assert_pct(at_the_old_bar["prereg_rate_pct"], 8.00, "prereg_rate_pct")
    assert_pct(at_the_old_bar["threshold_pct"], 10.00, "threshold_pct")

    lowered = validate_success(
        api_client.update_build_zone_threshold(zone_id, threshold_payload(8.0), PM), 200
    )
    assert_build_zone(lowered)
    assert_pct(lowered["threshold_pct"], 8.00, "threshold_pct")
    assert_pct(lowered["prereg_rate_pct"], 8.00, "prereg_rate_pct")
    set_clock(CLOCK_AFTER_DEADLINE)

    response = api_client.qualification_run(base["campaign"]["id"], PM)

    evaluated, _meta = validate_unpaginated(response, 200)
    assert len(evaluated) == 1, evaluated
    judged = evaluated[0]
    assert_build_zone(judged)
    assert judged["campaign_status"] == "QUALIFIED", judged["campaign_status"]
    assert_pct(judged["final_rate_pct"], 8.00, "final_rate_pct")
    assert judged["final_qualifying_count"] == 2, judged["final_qualifying_count"]
    for preorder, account in zip(base["preorders"], base["accounts"]):
        settled = read_preorder(preorder["id"])
        assert_preorder(settled)
        assert settled["preorder_status"] == "QUALIFIED", settled["preorder_status"]
        assert settled["deposit_status"] == "HELD", settled["deposit_status"]
        assert_cents(
            read_account(account["id"])["deposit_held_cents"], 1000, "deposit_held_cents"
        )


def test_two_indistinguishable_options_are_separated_by_the_order_they_were_published():
    """Speed, price and preference all tie, so the earliest published option takes the offer.

    PRD 3.2: "Otherwise the winner is the candidate with the highest `min_downstream_mbps`; ties are
    broken by the lowest `monthly_price_cents`, then by the lowest `priority_rank`, then by the
    earliest `created_at`."

    PRD 3.2: "It snapshots the winner's `technology`, `min_downstream_mbps` and
    `monthly_price_cents` onto itself, so that later edits to the published option leave the standing
    offer untouched."

    Design: Corner/cross_cutting_complexity_layers/fallback_ranking_falls_through_to_created_at_when_every_other_key_ties
    """
    base = setup_not_serviceable_address_with_options(
        option_specs=TIED_OPTIONS,
        address_overrides={"street_address": "12 Quarry Rd", "distance_to_node_m": 900},
        not_serviceable_reason="EXCESSIVE_DISTANCE",
    )
    published_first, published_second = base["options"]
    assert_instant_equals(published_first["created_at"], CLOCK_EPOCH, "created_at")
    assert_instant_equals(published_second["created_at"], CLOCK_EPOCH, "created_at")

    offer = make_offer(
        base["address"]["id"], base["account"]["id"], expires_at=OFFER_EXPIRY
    )

    assert_fallback_offer(offer)
    assert offer["fallback_option_id"] == published_first["id"], offer
    assert offer["technology"] == "FIXED_WIRELESS", offer["technology"]
    assert_cents(offer["monthly_price_cents"], 7000, "monthly_price_cents")
    assert offer["min_downstream_mbps"] == 300, offer["min_downstream_mbps"]
    assert_total_count(
        api_client.list_fallback_offers(
            PM, params={"fallback_option_id": published_second["id"]}
        ),
        0,
    )


def test_the_creating_response_and_every_later_read_already_carry_the_recomputation():
    """One sign-up moves a rate, a balance and a ledger, and no second call is needed to see it.

    PRD 1: "First, **all derived state is recomputed inside the request that changes its source
    rows** - preregistration rates, ledger-backed account balances, crew occupancy, zone readiness
    posture. There is no background worker and no eventual consistency window; a caller that mutates
    a preorder sees the zone's new rate on the very next read."

    Design: Corner/consistency_model/every_recomputation_is_visible_in_the_same_request_that_caused_it
    """
    base = setup_serviceable_address(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    account = base["account"]
    version_before = read_zone_version(zone_id)
    assert_pct(read_zone(zone_id)["prereg_rate_pct"], 0.00, "prereg_rate_pct")

    response = api_client.create_preorder(
        preorder_payload(
            zone_id,
            base["address"]["id"],
            account["id"],
            version_before,
            plan_tier="GIGABIT_1000",
        ),
        make_subscriber_headers(account["id"]),
    )

    created = validate_success(response, 201)
    assert_preorder(created)
    assert created["deposit_status"] == "HELD", created["deposit_status"]
    assert_cents(created["deposit_amount_cents"], 1000, "deposit_amount_cents")
    settled_zone = read_zone(zone_id)
    assert_build_zone(settled_zone)
    assert_pct(settled_zone["prereg_rate_pct"], 10.00, "prereg_rate_pct")
    assert settled_zone["provisional_qualifying_count"] == 1, settled_zone
    assert settled_zone["version"] == version_before + 1, settled_zone["version"]
    settled_account = read_account(account["id"])
    assert_account(settled_account)
    assert_cents(settled_account["deposit_held_cents"], 1000, "deposit_held_cents")
    entries, listing = list_ledger_for_preorder(created["id"])
    assert_total_count(listing, 1)
    assert entries[0]["entry_type"] == "DEPOSIT_HELD", entries[0]
    assert_cents(entries[0]["amount_cents"], 1000, "DEPOSIT_HELD.amount_cents")

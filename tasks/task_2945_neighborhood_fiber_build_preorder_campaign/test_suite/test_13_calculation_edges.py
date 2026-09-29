"""Calculation edges: ledger replays, rate input sets, two-decimal precision and option ranking."""

from test_helpers import (
    CLOCK_EPOCH,
    api_client,
    assert_account,
    assert_build_zone,
    assert_cents,
    assert_deposit_stream_balances,
    assert_fallback_offer,
    assert_instant_equals,
    assert_instant_is_null,
    assert_pct,
    assert_preorder,
    assert_service_address,
    assert_total_count,
    assert_two_decimal_places,
    fallback_offer_response_payload,
    list_ledger_for_account,
    make_account,
    make_address,
    make_offer,
    make_preorder,
    make_subscriber_headers,
    make_zone,
    read_account,
    read_address,
    read_preorder,
    read_zone,
    set_serviceability,
    setup_campaign_with_zone,
    setup_not_serviceable_address_with_options,
    setup_serviceable_address,
    setup_zone_with_preorders,
    validate_success,
)

OFFER_EXPIRY = "2026-09-01T00:00:00Z"

FOUR_OPTIONS = (
    {
        "technology": "FIXED_WIRELESS",
        "min_downstream_mbps": 300,
        "monthly_price_cents": 7000,
        "max_serviceable_distance_m": 800,
        "priority_rank": 3,
    },
    {
        "technology": "SATELLITE_PARTNER",
        "min_downstream_mbps": 300,
        "monthly_price_cents": 6500,
        "max_serviceable_distance_m": 1500,
        "priority_rank": 9,
    },
    {
        "technology": "DSL_PARTNER",
        "min_downstream_mbps": 500,
        "monthly_price_cents": 4000,
        "max_serviceable_distance_m": 799,
        "priority_rank": 1,
    },
    {
        "technology": "FIXED_WIRELESS",
        "min_downstream_mbps": 900,
        "monthly_price_cents": 3000,
        "max_serviceable_distance_m": 5000,
        "priority_rank": 1,
        "option_status": "DISABLED",
    },
)


def test_one_accounts_held_deposits_span_two_zones_and_unwind_on_cancellation():
    """Two zones, one wallet: the balance is a replay of the stream, so a refund walks it back down.

    PRD 2.8: "Because of the sign convention, `deposit_held_cents` is always the total of the
    `deposit_amount_cents` of that account's preorders whose `deposit_status` is still `HELD`, and
    it returns to exactly its pre-preorder value once a deposit is refunded, applied or
    forfeited."

    Design: Corner/calculations/deposit_held_cents_aggregates_across_zones_and_reverses_on_cancel
    """
    base = setup_campaign_with_zone()
    alpha_id = base["zone"]["id"]
    beta = make_zone(
        base["campaign"]["id"], name="Zone Beta", zone_code="B1", household_count=10
    )
    alpha_address = make_address(alpha_id, street_address="1 Elm St", distance_to_node_m=100)
    beta_address = make_address(beta["id"], street_address="2 Fir Ln", distance_to_node_m=120)
    set_serviceability(alpha_address["id"], "SERVICEABLE")
    set_serviceability(beta_address["id"], "SERVICEABLE")
    account = make_account(0)
    first = make_preorder(alpha_id, alpha_address["id"], account["id"])
    second = make_preorder(
        beta["id"], beta_address["id"], account["id"], plan_tier="GIGABIT_1000"
    )
    assert_cents(
        read_account(account["id"])["deposit_held_cents"], 2000, "deposit_held_cents"
    )

    validate_success(
        api_client.cancel_preorder(first["id"], make_subscriber_headers(account["id"]))
    )

    settled = read_account(account["id"])
    assert_account(settled)
    assert_cents(settled["deposit_held_cents"], 1000, "deposit_held_cents")
    assert_cents(settled["credit_balance_cents"], 0, "credit_balance_cents")
    entries, listing = list_ledger_for_account(account["id"])
    assert_total_count(listing, 3)
    assert_deposit_stream_balances(entries, 1000)
    holds = [entry for entry in entries if entry["entry_type"] == "DEPOSIT_HELD"]
    refunds = [entry for entry in entries if entry["entry_type"] == "DEPOSIT_REFUNDED"]
    assert len(holds) == 2 and len(refunds) == 1, entries
    assert [entry["amount_cents"] for entry in holds] == [1000, 1000], holds
    assert_cents(refunds[0]["amount_cents"], -1000, "DEPOSIT_REFUNDED.amount_cents")
    assert read_preorder(second["id"])["deposit_status"] == "HELD"


def test_the_rate_denominator_stays_the_household_count_when_a_preorder_is_cancelled():
    """A third registered address never enters the arithmetic, and a cancelled row leaves it.

    PRD 3.3: "The denominator is always the zone's immutable `household_count` - never the number
    of registered addresses - and because `household_count` is at least 1 there is no division by
    zero."

    Design: Corner/calculations/prereg_rate_input_set_drops_cancelled_and_keeps_household_count_denominator
    """
    base = setup_zone_with_preorders(
        preorder_count=2, household_count=10, threshold_pct=10.0
    )
    zone_id = base["zone"]["id"]
    spare = make_address(zone_id, street_address="5 Elm St", distance_to_node_m=130)
    set_serviceability(spare["id"], "SERVICEABLE")
    with_two = read_zone(zone_id)
    assert_pct(with_two["prereg_rate_pct"], 20.00, "prereg_rate_pct")
    assert with_two["provisional_qualifying_count"] == 2, with_two

    validate_success(
        api_client.cancel_preorder(
            base["preorders"][0]["id"],
            make_subscriber_headers(base["accounts"][0]["id"]),
        )
    )

    with_one = read_zone(zone_id)
    assert_build_zone(with_one)
    assert_pct(with_one["prereg_rate_pct"], 10.00, "prereg_rate_pct")
    assert with_one["provisional_qualifying_count"] == 1, with_one
    assert with_one["household_count"] == 10, with_one["household_count"]
    survivor = read_preorder(base["preorders"][1]["id"])
    assert_preorder(survivor)
    assert survivor["preorder_status"] == "PENDING", survivor["preorder_status"]
    assert survivor["deposit_status"] == "HELD", survivor["deposit_status"]


def test_one_sixth_of_a_zone_rounds_up_and_two_sixths_rounds_down_to_two_decimals():
    """Six households make both rates non-terminating, so the half-up rule is visible in both.

    PRD 3.3: "The rate is that count multiplied by 100 and divided by the zone's
    `household_count`, rounded half up to two decimal places."

    Design: Corner/calculations/prereg_rate_precision_rounds_one_sixth_up_and_two_sixths_down
    """
    base = setup_serviceable_address(zone_overrides={"household_count": 6})
    zone_id = base["zone"]["id"]
    make_preorder(zone_id, base["address"]["id"], base["account"]["id"])
    one_sixth = read_zone(zone_id)
    assert_pct(one_sixth["prereg_rate_pct"], 16.67, "prereg_rate_pct")
    assert_two_decimal_places(one_sixth["prereg_rate_pct"], "prereg_rate_pct")

    second_address = make_address(zone_id, street_address="3 Elm St", distance_to_node_m=110)
    set_serviceability(second_address["id"], "SERVICEABLE")
    second_account = make_account(1)
    make_preorder(zone_id, second_address["id"], second_account["id"])

    two_sixths = read_zone(zone_id)
    assert_build_zone(two_sixths)
    assert_pct(two_sixths["prereg_rate_pct"], 33.33, "prereg_rate_pct")
    assert_two_decimal_places(two_sixths["prereg_rate_pct"], "prereg_rate_pct")
    assert two_sixths["provisional_qualifying_count"] == 2, two_sixths


def test_the_faster_reachable_option_wins_on_price_and_a_decline_bars_it_forever():
    """Four published options, one eligible pair: speed ties, price decides, and a decline is final.

    PRD 3.2: "Otherwise the winner is the candidate with the highest `min_downstream_mbps`; ties
    are broken by the lowest `monthly_price_cents`, then by the lowest `priority_rank`, then by the
    earliest `created_at`."

    Design: Corner/calculations/fallback_selection_ranks_speed_then_price_and_honours_the_inclusive_distance_edge
    """
    base = setup_not_serviceable_address_with_options(
        option_specs=FOUR_OPTIONS,
        address_overrides={"street_address": "99 Ridge Rd", "distance_to_node_m": 800},
        not_serviceable_reason="EXCESSIVE_DISTANCE",
    )
    address_id = base["address"]["id"]
    account = base["account"]
    fixed_wireless, satellite, dsl, disabled = base["options"]

    first_offer = make_offer(address_id, account["id"], expires_at=OFFER_EXPIRY)

    assert_fallback_offer(first_offer)
    assert first_offer["fallback_option_id"] == satellite["id"], first_offer
    assert first_offer["fallback_option_id"] not in (dsl["id"], disabled["id"]), first_offer
    assert first_offer["technology"] == "SATELLITE_PARTNER", first_offer["technology"]
    assert_cents(first_offer["monthly_price_cents"], 6500, "monthly_price_cents")
    assert first_offer["min_downstream_mbps"] == 300, first_offer["min_downstream_mbps"]
    assert first_offer["status"] == "OFFERED", first_offer["status"]
    assert_instant_equals(first_offer["offered_at"], CLOCK_EPOCH, "offered_at")

    declined = validate_success(
        api_client.respond_to_fallback_offer(
            first_offer["id"],
            fallback_offer_response_payload("DECLINE"),
            make_subscriber_headers(account["id"]),
        )
    )
    assert declined["status"] == "DECLINED", declined["status"]
    assert_instant_equals(declined["responded_at"], CLOCK_EPOCH, "responded_at")

    second_offer = make_offer(address_id, account["id"], expires_at=OFFER_EXPIRY)
    assert_fallback_offer(second_offer)
    assert second_offer["fallback_option_id"] == fixed_wireless["id"], second_offer
    assert second_offer["technology"] == "FIXED_WIRELESS", second_offer["technology"]
    assert_cents(second_offer["monthly_price_cents"], 7000, "monthly_price_cents")
    assert second_offer["status"] == "OFFERED", second_offer["status"]
    settled_address = read_address(address_id)
    assert_service_address(settled_address)
    assert settled_address["active_fallback_technology"] is None, settled_address
    assert_instant_is_null(second_offer["responded_at"], "responded_at")

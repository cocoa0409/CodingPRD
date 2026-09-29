"""Provisional versus final preregistration rate, and the two-decimal threshold bar."""

from test_helpers import (
    PM,
    ApiErrorId,
    CLOCK_AFTER_DEADLINE,
    api_client,
    assert_cents,
    assert_pct,
    assert_two_decimal_places,
    make_account,
    make_address,
    make_campaign,
    make_preorder,
    make_zone,
    read_account,
    read_address,
    read_preorder,
    read_zone,
    set_clock,
    set_serviceability,
    validate_error,
    validate_success,
)


def _mixed_determination_zone():
    """One zone, one SERVICEABLE address and one address left UNDETERMINED."""
    set_clock()
    campaign = make_campaign(default_threshold_pct=10.0, deposit_amount_cents=1000)
    zone = make_zone(campaign["id"], household_count=20, threshold_pct=10.0)
    resolved = make_address(zone["id"], street_address="1 Elm St", distance_to_node_m=100)
    resolved = set_serviceability(resolved["id"], "SERVICEABLE")
    unresolved = make_address(
        zone["id"], street_address="2 Elm St", distance_to_node_m=140
    )
    first_account = make_account(0)
    second_account = make_account(1)
    first = make_preorder(zone["id"], resolved["id"], first_account["id"])
    second = make_preorder(zone["id"], unresolved["id"], second_account["id"])
    return {
        "campaign": campaign,
        "zone": zone,
        "resolved": resolved,
        "unresolved": unresolved,
        "accounts": [first_account, second_account],
        "preorders": [first, second],
    }


def test_provisional_rate_admits_the_undetermined_address():
    """The live rate counts an UNDETERMINED address, reaching 10.00 on a 20-household zone.

    PRD 3.3: "The **provisional** variant is the one written to
    `provisional_qualifying_count` and `prereg_rate_pct` by all of those ordinary writes;
    it admits an address whose `serviceability` is `UNDETERMINED`, `SERVICEABLE` or
    `CONDITIONAL_MDU`, optimistically assuming an unresolved address will turn out
    buildable."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_rate_diverge_on_undetermined_address
    """
    world = _mixed_determination_zone()

    zone = read_zone(world["zone"]["id"])
    assert zone["provisional_qualifying_count"] == 2, (
        "both preorders must count provisionally, including the one at the "
        f"UNDETERMINED address: {zone['provisional_qualifying_count']}"
    )
    assert_pct(zone["prereg_rate_pct"], 10.00, "prereg_rate_pct")
    assert_two_decimal_places(zone["prereg_rate_pct"], "prereg_rate_pct")
    assert zone["final_rate_pct"] is None, (
        "final_rate_pct stays null until the qualification run stamps it, got "
        f"{zone['final_rate_pct']}"
    )
    assert zone["final_qualifying_count"] is None
    assert zone["campaign_status"] == "PREREG_OPEN", zone["campaign_status"]


def test_final_variant_drops_the_undetermined_address_and_fails_the_zone():
    """The qualification run recomputes 5.00 from one admissible address and fails the bar.

    PRD 3.4: "it admits an address whose `serviceability` is `SERVICEABLE`, and admits a
    `CONDITIONAL_MDU` address only when some MDU owner agreement for that address stands
    in status `SIGNED`. Addresses still `UNDETERMINED` are dropped entirely."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_rate_diverge_on_undetermined_address
    """
    world = _mixed_determination_zone()
    set_clock(CLOCK_AFTER_DEADLINE)

    validate_success(api_client.qualification_run(world["campaign"]["id"], PM))

    zone = read_zone(world["zone"]["id"])
    assert_pct(zone["final_rate_pct"], 5.00, "final_rate_pct")
    assert zone["final_qualifying_count"] == 1, zone["final_qualifying_count"]
    assert zone["campaign_status"] == "NOT_QUALIFIED", zone["campaign_status"]


def test_failed_zone_refunds_both_deposits_and_closes_the_address_registry():
    """A zone that failed finally lapses both preorders and rules both addresses out.

    PRD 3.4: "The second hop lapses every preorder of the zone whose `preorder_status` is
    `PENDING`, each with `lapse_reason` `ZONE_NOT_QUALIFIED`."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_rate_diverge_on_undetermined_address
    """
    world = _mixed_determination_zone()
    set_clock(CLOCK_AFTER_DEADLINE)

    validate_success(api_client.qualification_run(world["campaign"]["id"], PM))

    for preorder in world["preorders"]:
        row = read_preorder(preorder["id"])
        assert row["preorder_status"] == "LAPSED", row["preorder_status"]
        assert row["lapse_reason"] == "ZONE_NOT_QUALIFIED", row["lapse_reason"]
        assert row["deposit_status"] == "REFUNDED", row["deposit_status"]
    for account in world["accounts"]:
        assert_cents(read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents")

    unresolved = read_address(world["unresolved"]["id"])
    assert unresolved["serviceability"] == "NOT_SERVICEABLE", unresolved["serviceability"]
    assert unresolved["not_serviceable_reason"] == "BUILD_NOT_QUALIFIED", (
        unresolved["not_serviceable_reason"]
    )


def _twin_zones_at_two_over_sixteen():
    """Two sibling zones each sitting at exactly 2 preorders over 16 households."""
    set_clock()
    campaign = make_campaign(default_threshold_pct=12.5, deposit_amount_cents=1000)
    at_bar = make_zone(
        campaign["id"],
        name="Zone Alpha",
        zone_code="A1",
        household_count=16,
        threshold_pct=12.5,
    )
    above_bar = make_zone(
        campaign["id"],
        name="Zone Bravo",
        zone_code="B1",
        household_count=16,
        threshold_pct=12.51,
    )
    preorders = {"at_bar": [], "above_bar": []}
    accounts = {"at_bar": [], "above_bar": []}
    addresses = {"at_bar": [], "above_bar": []}
    plan = [
        ("at_bar", at_bar, "1 Elm St", 100, 0),
        ("at_bar", at_bar, "2 Elm St", 105, 1),
        ("above_bar", above_bar, "10 Oak Ave", 95, 2),
        ("above_bar", above_bar, "12 Oak Ave", 99, 3),
    ]
    for key, zone, street, distance, account_index in plan:
        address = make_address(
            zone["id"], street_address=street, distance_to_node_m=distance
        )
        address = set_serviceability(address["id"], "SERVICEABLE")
        account = make_account(account_index)
        preorders[key].append(
            make_preorder(zone["id"], address["id"], account["id"])
        )
        accounts[key].append(account)
        addresses[key].append(address)
    return {
        "campaign": campaign,
        "at_bar": at_bar,
        "above_bar": above_bar,
        "preorders": preorders,
        "accounts": accounts,
        "addresses": addresses,
    }


def test_rate_exactly_at_the_threshold_qualifies_the_zone():
    """12.50 over a 12.50 bar qualifies, because the comparison is greater-than-or-equal.

    PRD 3.3: "A zone qualifies when that rounded two-decimal rate is greater than or equal
    to `threshold_pct`; sitting exactly at the bar is qualifying."

    Design: Difficulty/boundary_precision_check/final_rate_exactly_at_threshold_qualifies_one_hundredth_below_does_not
    """
    world = _twin_zones_at_two_over_sixteen()
    set_clock(CLOCK_AFTER_DEADLINE)

    validate_success(api_client.qualification_run(world["campaign"]["id"], PM))

    zone = read_zone(world["at_bar"]["id"])
    assert_pct(zone["final_rate_pct"], 12.50, "final_rate_pct")
    assert_two_decimal_places(zone["final_rate_pct"], "final_rate_pct")
    assert zone["campaign_status"] == "QUALIFIED", zone["campaign_status"]
    for preorder in world["preorders"]["at_bar"]:
        row = read_preorder(preorder["id"])
        assert row["preorder_status"] == "QUALIFIED", row["preorder_status"]
        assert row["deposit_status"] == "HELD", row["deposit_status"]
    for account in world["accounts"]["at_bar"]:
        assert_cents(
            read_account(account["id"])["deposit_held_cents"], 1000, "deposit_held_cents"
        )


def test_threshold_one_hundredth_higher_fails_the_identical_rate():
    """The same 12.50 rate misses a 12.51 bar, so a one-hundredth gap is decisive.

    PRD 2.7: "Comparison against a threshold is performed on the *rounded* two-decimal
    value, so a true rate of 9.995 percent rounds to 10.00 and therefore satisfies a
    threshold of 10.00."

    Design: Difficulty/boundary_precision_check/final_rate_exactly_at_threshold_qualifies_one_hundredth_below_does_not
    """
    world = _twin_zones_at_two_over_sixteen()
    set_clock(CLOCK_AFTER_DEADLINE)

    validate_success(api_client.qualification_run(world["campaign"]["id"], PM))

    zone = read_zone(world["above_bar"]["id"])
    assert_pct(zone["final_rate_pct"], 12.50, "final_rate_pct")
    assert_pct(zone["threshold_pct"], 12.51, "threshold_pct")
    assert zone["campaign_status"] == "NOT_QUALIFIED", zone["campaign_status"]
    for preorder in world["preorders"]["above_bar"]:
        row = read_preorder(preorder["id"])
        assert row["preorder_status"] == "LAPSED", row["preorder_status"]
        assert row["deposit_status"] == "REFUNDED", row["deposit_status"]
    for account in world["accounts"]["above_bar"]:
        assert_cents(
            read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents"
        )
    ruled_out = read_address(world["addresses"]["above_bar"][0]["id"])
    assert ruled_out["serviceability"] == "NOT_SERVICEABLE", ruled_out["serviceability"]


def test_qualification_run_is_refused_while_every_zone_is_still_inside_its_window():
    """With the clock before both deadlines the run itself is refused, not silently empty.

    PRD 3.4: "but when the campaign has no still-open zone whose deadline the clock has
    reached, the run itself is refused with `ERR_PREREG_DEADLINE_NOT_REACHED`."

    Design: Difficulty/boundary_precision_check/final_rate_exactly_at_threshold_qualifies_one_hundredth_below_does_not
    """
    world = _twin_zones_at_two_over_sixteen()

    response = api_client.qualification_run(world["campaign"]["id"], PM)

    validate_error(response, ApiErrorId.ERR_PREREG_DEADLINE_NOT_REACHED)
    for key in ("at_bar", "above_bar"):
        zone = read_zone(world[key]["id"])
        assert zone["final_rate_pct"] is None, zone["final_rate_pct"]
        assert zone["campaign_status"] == "PREREG_OPEN", zone["campaign_status"]

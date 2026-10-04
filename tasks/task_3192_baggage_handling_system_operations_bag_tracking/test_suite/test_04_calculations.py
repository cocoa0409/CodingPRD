"""Calculation rules: fees, routing class, posture, outage delay and slack."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, make_flight, list_rows, get_area, get_flight,
    create_bag_payload, create_connection_payload, weigh_ok, screen_ok,
    declare_outage, create_airline_payload, create_station_payload,
    create_flight_payload,
)


def test_excess_weight_fee_flips_to_the_hold_variant_under_outage(api):
    """PRD §3.2: "When the station's `outage_active` is false at the instant of
    weighing, the fee is charged as computed. When the station is in outage
    contingency at that instant, the fee is pinned to exactly zero regardless of
    the bag's weight"

    Design: Difficulty/dual_variant_calc/excess_weight_fee_flips_with_station_outage
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=52),
        TEST_USERS["acceptance_agent_headers"]))

    weighed = weigh_ok(bag["id"], 52.4)
    assert weighed["excess_weight_fee_cents"] == 7500, \
        "the CURRENT variant charges one group for a pound-rounded 52 against a 50 lb allowance"
    assert weighed["custody_status"] == "SCREENING"

    # PRD §3.2: the HOLD variant is selected by the station's outage flag "at the
    # instant of weighing".  A bag that has already left ACCEPTED cannot be
    # weighed again, so the identical bag data is weighed fresh while the outage
    # is active.
    declare_outage(scenario)
    second = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=52,
                           passenger_ref="PNR4M1T"),
        TEST_USERS["acceptance_agent_headers"]))
    reweighed = weigh_ok(second["id"], 52.4)
    assert reweighed["excess_weight_fee_cents"] == 0, \
        "the HOLD variant pins the fee to exactly zero for identical bag data"


def test_excess_weight_fee_hold_variant_requires_the_station_outage(api):
    """PRD §3.2: "it is deferred, not waived, and the two variants therefore
    differ by the full group amount for identical bag data."

    Design: Difficulty/dual_variant_calc/excess_weight_fee_flips_with_station_outage
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=52),
        TEST_USERS["acceptance_agent_headers"]))

    charged = weigh_ok(bag["id"], 52.4)
    assert charged["excess_weight_fee_cents"] == 7500
    assert charged["scale_weight_lb"] == 52.4
    assert charged["weight_variance_lb"] == pytest.approx(0.4, abs=1e-6), \
        "weight_variance_lb is the signed difference between measured and declared weight"


def test_excess_weight_fee_group_boundary_at_the_allowance(api):
    """PRD §3.2: "If the rounded weight is at or below that threshold, the fee
    is exactly zero."
    PRD §3.2: "Otherwise the number of five-pound groups is the difference
    between the rounded weight and the threshold divided by five and rounded up
    to a whole number of groups"

    Design: Difficulty/boundary_precision_check/excess_weight_group_boundary_at_five_pounds_and_the_pound_rounding
    """
    scenario = base_scenario()
    at_threshold = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=40,
                           passenger_ref="PNR9K3L"),
        TEST_USERS["acceptance_agent_headers"]))
    over = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=40,
                           passenger_ref="PNR2W8H"),
        TEST_USERS["acceptance_agent_headers"]))

    exact = weigh_ok(at_threshold["id"], 50.0)
    assert exact["excess_weight_fee_cents"] == 0, \
        "a scale reading exactly at the allowance is at or below the threshold"

    one_group = weigh_ok(over["id"], 54.4)
    assert one_group["excess_weight_fee_cents"] == 7500, \
        "4.4 lb over the threshold rounds into one five-pound group"


def test_excess_weight_fee_rounds_the_reading_before_taking_the_ceiling(api):
    """PRD §3.2: "The measured weight is first rounded half-up to the nearest
    whole pound — this rounding happens before the grouping, never after"

    Design: Difficulty/boundary_precision_check/excess_weight_group_boundary_at_five_pounds_and_the_pound_rounding
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=40,
                           passenger_ref="PNR4M1T"),
        TEST_USERS["acceptance_agent_headers"]))

    reading = weigh_ok(bag["id"], 54.6)
    assert reading["excess_weight_fee_cents"] == 7500, \
        "the reading rounds to 55 before the ceiling, so the group count stays one"


def test_excess_weight_fee_crosses_to_a_second_group_above_fifty_five(api):
    """PRD §3.2: "the number of five-pound groups is the difference between the
    rounded weight and the threshold divided by five and rounded up to a whole
    number of groups, and the fee is that group count multiplied by 7500 cents."

    Design: Difficulty/boundary_precision_check/excess_weight_group_boundary_at_five_pounds_and_the_pound_rounding
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=40),
        TEST_USERS["acceptance_agent_headers"]))

    reading = weigh_ok(bag["id"], 55.6)
    assert reading["excess_weight_fee_cents"] == 15000, \
        "55.6 rounds to 56 before the ceiling, so the difference of 6 takes two groups"


def test_interline_routing_class_turns_manual_above_the_allowance(api):
    """PRD §3.2: "if the itinerary type is `INTERLINE` and the pound-rounded
    `scale_weight_lb` is strictly greater than the carrier's
    `max_excess_weight_lb`, the class is `MANUAL`."

    Design: Corner/calculations/interline_routing_class_manual_when_over_the_weight_threshold
    """
    scenario = base_scenario()
    over = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"],
                           itinerary_type="INTERLINE", weight_lb=50,
                           passenger_ref="PNR9K3L"),
        TEST_USERS["acceptance_agent_headers"]))
    under = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"],
                           itinerary_type="INTERLINE", weight_lb=50,
                           passenger_ref="PNR7X2Q"),
        TEST_USERS["acceptance_agent_headers"]))

    manual = weigh_ok(over["id"], 50.6)
    assert manual["routing_class"] == "MANUAL", "50.6 rounds to 51, which is above 50"
    assert manual["excess_weight_fee_cents"] == 7500

    standard = weigh_ok(under["id"], 50.4)
    assert standard["routing_class"] == "STANDARD", "50.4 rounds to 50, which is not above 50"
    assert standard["excess_weight_fee_cents"] == 0


def test_domestic_and_international_routing_classes(api):
    """PRD §3.2: "Otherwise, if the itinerary type is `INTERNATIONAL`, the class
    is `BULK_HOLD`. Otherwise the class is `STANDARD`."

    Design: Corner/calculations/interline_routing_class_manual_when_over_the_weight_threshold
    """
    scenario = base_scenario()
    domestic = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"],
                           itinerary_type="DOMESTIC", weight_lb=50),
        TEST_USERS["acceptance_agent_headers"]))
    international = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"],
                           itinerary_type="INTERNATIONAL", weight_lb=50),
        TEST_USERS["acceptance_agent_headers"]))

    assert weigh_ok(domestic["id"], 50.6)["routing_class"] == "STANDARD"
    assert weigh_ok(international["id"], 48.0)["routing_class"] == "BULK_HOLD"


def test_posture_stays_open_when_the_station_has_no_make_up_capacity(api):
    """PRD §2.6: "if the station has no active make-up capacity at all — the
    total of `capacity_slots` across its `ACTIVE` make-up areas is zero — the
    posture is `OPEN`, a guard that prevents a station with no configured make-up
    areas from ever reading as congested."

    Design: Corner/calculations/station_posture_suspends_at_capacity_and_guards_an_empty_makeup_set
    """
    set_clock()
    station = get_success_data(api.create_station(
        create_station_payload(code="HUB", name="Hub Station", sorter_capacity_bags=2),
        TEST_USERS["platform_admin_headers"]))
    api.create_bag(create_bag_payload(station["id"]), TEST_USERS["acceptance_agent_headers"])

    read = get_success_data(api.get_station(station["id"], TEST_USERS["platform_admin_headers"]))
    assert read["active_bag_count"] == 1
    assert read["posture"] == "OPEN", \
        "with zero configured make-up slots the empty-set guard short-circuits the CONGESTED test"


def test_posture_suspends_once_the_station_reaches_sorter_capacity(api):
    """PRD §2.6: "if the station's `active_bag_count` has reached or exceeded
    `sorter_capacity_bags`, the posture is `SUSPENDED`."

    Design: Corner/calculations/station_posture_suspends_at_capacity_and_guards_an_empty_makeup_set
    """
    set_clock()
    station = get_success_data(api.create_station(
        create_station_payload(code="HUB", name="Hub Station", sorter_capacity_bags=2),
        TEST_USERS["platform_admin_headers"]))
    api.create_bag(create_bag_payload(station["id"]), TEST_USERS["acceptance_agent_headers"])
    api.create_bag(create_bag_payload(station["id"], passenger_ref="PNR4M1T"),
                   TEST_USERS["acceptance_agent_headers"])

    read = get_success_data(api.get_station(station["id"], TEST_USERS["platform_admin_headers"]))
    assert read["active_bag_count"] == 2
    assert read["posture"] == "SUSPENDED", \
        "two bags on a two-capacity sorter suspends the station"


def test_posture_congests_when_free_make_up_slots_reach_the_fraction_bound(api):
    """PRD §2.6: "if the free make-up slots remaining across the station's active
    areas have fallen to fifteen percent of total capacity or below — where the
    threshold is computed as that fraction of the total rounded up to a whole
    slot, so two total slots yield a threshold of one and three total slots also
    yield a threshold of one — the posture is `CONGESTED`."

    Design: Corner/calculations/station_posture_suspends_at_capacity_and_guards_an_empty_makeup_set
    """
    scenario = base_scenario(makeup_capacity_slots=3)
    bag_one = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag_one["id"], 48.0)
    screen_ok(bag_one["id"], scenario["lane"], "2026-09-01T07:20:00Z")
    bag_two = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"],
                           passenger_ref="PNR4M1T"),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag_two["id"], 48.0)
    screen_ok(bag_two["id"], scenario["lane"], "2026-09-01T07:40:00Z")

    set_clock("2026-09-01T12:30:00Z")
    from test_helpers import create_assign_makeup_payload
    from test_helpers.fixtures import run_ops
    run_ops(scenario["st"])

    for index, bag in enumerate((bag_one, bag_two)):
        fresh = get_success_data(api.get_bag(bag["id"], TEST_USERS["sortation_agent_headers"]))
        response = api.assign_makeup(
            fresh["id"],
            create_assign_makeup_payload(fresh["version"], scenario["ma"],
                                         f"2026-09-01T13:{12 * (index + 1):02d}:00Z"),
            TEST_USERS["sortation_agent_headers"])
        validate_success(response, 200)

    station = get_success_data(api.get_station(scenario["st"],
                                               TEST_USERS["platform_admin_headers"]))
    assert station["posture"] == "CONGESTED", \
        "one free slot of a three-slot total is at or below ceil(0.15 * 3) == 1"
    assert get_area(scenario["ma"])["free_slots"] == 1


def test_outage_dwell_is_capped_while_manual_scans_are_not(api):
    """PRD §3.9: "While the outage is active it is the sum of two terms: the
    dwell from the outage's start to the current logical clock instant, in whole
    minutes truncated toward zero, capped at 45 minutes — the cap applies to the
    dwell term only — and fifteen minutes for each manual-scan capture recorded
    on the bag while the outage was active, which is an uncapped term."

    Design: Corner/calculations/outage_manual_sortation_delay_caps_the_dwell_and_stacks_manual_scans
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))
    declare_outage(scenario)

    fresh = get_success_data(api.get_bag(bag["id"], TEST_USERS["acceptance_agent_headers"]))
    assert fresh["manual_sortation_delay_minutes"] == 0, "no dwell has accumulated yet"

    set_clock("2026-09-01T09:00:00Z")
    dwell_only = get_success_data(api.get_bag(bag["id"], TEST_USERS["acceptance_agent_headers"]))
    assert dwell_only["manual_sortation_delay_minutes"] == 45, \
        "120 minutes of dwell is clamped to the 45-minute cap"

    api.add_scan(bag["id"], {"scan_point": "SORTATION"}, TEST_USERS["sortation_agent_headers"])
    with_scan = get_success_data(api.get_bag(bag["id"], TEST_USERS["acceptance_agent_headers"]))
    assert with_scan["manual_sortation_delay_minutes"] == 60, \
        "the manual-scan term is added on top of the capped dwell term"


def test_manual_sortation_delay_is_zero_without_an_active_outage(api):
    """PRD §3.9: "It is zero whenever the station's outage is not active."

    Design: Corner/calculations/outage_manual_sortation_delay_caps_the_dwell_and_stacks_manual_scans
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))
    declare_outage(scenario)
    set_clock("2026-09-01T09:00:00Z")
    api.add_scan(bag["id"], {"scan_point": "SORTATION"}, TEST_USERS["sortation_agent_headers"])
    assert get_success_data(api.get_bag(
        bag["id"], TEST_USERS["acceptance_agent_headers"]))["manual_sortation_delay_minutes"] == 60

    api.clear_outage(scenario["st"], TEST_USERS["platform_admin_headers"])
    cleared = get_success_data(api.get_bag(bag["id"], TEST_USERS["acceptance_agent_headers"]))
    assert cleared["manual_sortation_delay_minutes"] == 0


def test_connection_slack_truncates_the_departure_difference(api):
    """PRD §3.8: "The connection's derived slack, the field
    `connect_slack_minutes`, is the whole-minute difference between the onward
    flight's scheduled departure and the inbound flight's scheduled departure —
    that difference truncated toward zero before anything else is done to it —
    less the connection's `required_mct_minutes`."

    Design: Corner/calculations/connection_slack_minutes_truncates_the_departure_difference
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2",
                         scheduled_departure_utc="2026-09-01T17:32:30Z")
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], passenger_ref="PNR2W8H"),
        TEST_USERS["acceptance_agent_headers"]))

    response = api.create_connection(
        create_connection_payload(bag["id"], scenario["f1"], onward["id"],
                                  required_mct_minutes=75),
        TEST_USERS["transfer_agent_headers"])
    connection = validate_success(response, 201)
    assert connection["connect_slack_minutes"] == 77, \
        "152 truncated minutes minus the required 75, never 78"


def test_a_connection_whose_own_fields_are_satisfied_is_still_gated_by_the_bag(api):
    """PRD §3.8: "The ordinary confirmation path settles it against the minimum
    connect time: a `TransferAgent` confirms the itinerary, which requires the
    connection to be in `PENDING` or in `RUSH` (`ERR_INVALID_STATE`, 409),
    requires a slack of zero or more (`ERR_MCT_VIOLATION`, 409), and requires the
    bag's screening status to be `CLEARED` (`ERR_SCREENING_NOT_CLEARED`, 409)."

    Design: Difficulty/cross_entity_state_dependency/connection_confirmation_depends_on_the_bag_screening_state
    """
    from test_helpers import make_transfer_bag

    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward, event = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=75, alarmed=True)

    assert connection["status"] == "PENDING"
    assert connection["connect_slack_minutes"] == 75

    refused = api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)


def test_duplicate_connection_on_the_same_pair_is_rejected(api):
    """PRD §2.13: "a connection is unique on the pair of `bag_id` and
    `onward_flight_id`"
    PRD §2.13: "duplicate connections yield `ERR_DUPLICATE_CONNECTION`, both HTTP
    409."

    Design: Corner/calculations/connection_slack_minutes_truncates_the_departure_difference
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))

    payload = create_connection_payload(bag["id"], scenario["f1"], onward["id"],
                                        required_mct_minutes=75)
    api.create_connection(payload, TEST_USERS["transfer_agent_headers"])
    response = api.create_connection(payload, TEST_USERS["transfer_agent_headers"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CONNECTION, 409)
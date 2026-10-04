"""The screening axis and the custody axis: hold, clear and re-induction."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, weigh_ok, make_sorted_bag,
    make_alarmed_bag, raise_alarm, declare_outage, list_rows, make_transfer_bag,
    create_bag_payload, create_screening_payload, create_assign_makeup_payload,
)


def test_an_alarm_drops_the_bag_into_held_custody_and_alarmed_screening(api):
    """PRD §3.2: "When an `alarm_code` is supplied, the event moves to `ALARMED`
    and the bag's screening status moves to `ALARMED`; the screening axis then
    pushes the custody axis, and a bag whose custody status was `ACCEPTED` or
    `SCREENING` at that moment is dropped to `HELD` and stops advancing until the
    alarm is resolved."

    Design: Difficulty/compensating_invariant/alarm_clear_does_not_release_the_bag_from_custody
    """
    scenario = base_scenario()
    bag, event = make_alarmed_bag(scenario)

    assert bag["custody_status"] == "HELD"
    assert bag["screening_status"] == "ALARMED"
    station = get_station(scenario["st"])
    assert station["active_bag_count"] == 1, "a bag held at screening is still physically present"


def test_clearing_the_alarm_does_not_release_the_bag_from_custody(api):
    """PRD §3.2: "a bag that had already been dropped to `HELD` keeps its held
    custody, and its alarm clearance alone does not release it"
    PRD §2.6: "A bag held at screening still counts as physically present."

    Design: Difficulty/compensating_invariant/alarm_clear_does_not_release_the_bag_from_custody
    """
    scenario = base_scenario()
    bag, event = make_alarmed_bag(scenario)
    before = get_station(scenario["st"])

    resolved = validate_success(api.resolve_screening(
        event["id"], "CLEARED", TEST_USERS["screener_headers"]), 200)
    assert resolved["status"] == "CLEARED"

    after = get_bag(bag["id"])
    assert after["screening_status"] == "CLEARED"
    assert after["custody_status"] == "HELD", \
        "the clear alone does not hand custody back; re-induction does"
    assert get_station(scenario["st"])["active_bag_count"] == before["active_bag_count"], \
        "the cleared-but-held bag remains in the active population"


def test_an_outage_re_induction_weigh_releases_a_cleared_but_held_bag(api):
    """PRD §3.5: "An `AcceptanceAgent` may re-weigh a held bag, which moves its
    custody back to `ACCEPTED` and, in the same breath, resets its screening axis
    to `PENDING` and then immediately to `IN_LINE`"
    PRD §3.5: "it is refused unless one of two conditions holds: either the
    station's `outage_active` is true, or the bag's screening status is currently
    `ALARMED` or `CLEARED`."

    Design: Difficulty/compensating_invariant/alarm_clear_does_not_release_the_bag_from_custody
    """
    scenario = base_scenario()
    declare_outage(scenario)
    bag, event = make_alarmed_bag(scenario)
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])

    reinducted = weigh_ok(bag["id"], 48.0)
    assert reinducted["custody_status"] == "ACCEPTED", \
        "re-induction through weighing moves the bag back to ACCEPTED"
    assert reinducted["screening_status"] == "IN_LINE", \
        "the alarm state the bag carried is discarded and the pipeline restarts"
    assert reinducted["version"] == bag["version"] + 2, \
        "the alarm resolution and the re-induction each advanced the bag by one"


def test_re_induction_without_outage_or_qualifying_screening_status_is_refused(api):
    """PRD §3.2: "a bag in the `ACCEPTED` custody state advances to `SCREENING`
    while its screening status moves from `PENDING` to `IN_LINE`."
    PRD §3.5: "Neither condition holding yields `ERR_OUTAGE_NOT_ACTIVE` with HTTP
    409."

    Design: Difficulty/priority_pair_validation_conflict/uncleared_screening_beats_oversize_screening_envelope
    """
    scenario = base_scenario()
    # PRD §3.13: a bag left ACCEPTED through two checkpoints is moved to HELD
    # custody with a screening status of FAILED.  Neither condition of §3.5's
    # re-induction gate holds — the station outage is not active and the
    # screening status is neither ALARMED nor CLEARED — so the re-weigh is
    # refused.
    api.create_bag(create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
                   TEST_USERS["acceptance_agent_headers"])
    from test_helpers import run_ops
    run_ops(scenario["st"])
    run_ops(scenario["st"])
    run_ops(scenario["st"])

    held = get_success_data(api.list_bags(
        TEST_USERS["acceptance_agent_headers"], {"station_id": scenario["st"]}))[0]
    assert held["custody_status"] == "HELD"
    assert held["screening_status"] == "FAILED"

    response = api.weigh_bag(held["id"], 48.0, TEST_USERS["acceptance_agent_headers"])
    validate_error(response, ApiErrorId.ERR_OUTAGE_NOT_ACTIVE, 409)


def test_a_hold_on_a_bag_gates_the_connection_confirm(api):
    """PRD §3.8: "requires the bag's screening status to be `CLEARED`
    (`ERR_SCREENING_NOT_CLEARED`, 409)."
    PRD §2.13: "A bag whose screening status is `ALARMED`, `FAILED` or
    `IN_INSPECTION` may not advance past the screening stage."

    Design: Corner/RBAC/hold_on_a_bag_holds_the_entire_connection
    """
    scenario = base_scenario()
    bag, connection, onward, event = make_transfer_bag(
        scenario, required_mct_minutes=75, alarmed=True)

    denied = api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"])
    validate_error(denied, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)

    still_pending = get_success_data(api.get_connection(
        connection["id"], TEST_USERS["transfer_agent_headers"]))
    assert still_pending["status"] == "PENDING"


def test_the_screener_can_clear_the_alarm_without_freeing_the_bag(api):
    """PRD §3.3: "Clearing a task does not by itself release the bag from `HELD`
    custody; that happens only through re-induction"
    PRD §3.2: "a bag that had already been dropped to `HELD` keeps its held
    custody, and its alarm clearance alone does not release it"

    Design: Corner/RBAC/hold_on_a_bag_holds_the_entire_connection
    """
    scenario = base_scenario()
    bag, connection, onward, event = make_transfer_bag(
        scenario, required_mct_minutes=75, alarmed=True)

    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])
    after = get_bag(bag["id"])
    assert after["screening_status"] == "CLEARED"
    assert after["custody_status"] == "HELD", \
        "the screening desk's action does not restore custody on its own"

    # PRD §3.8 states the confirm requires the bag's screening status to be
    # CLEARED, and this connection is PENDING with a slack of 75, so once the
    # clear has landed the confirm is admissible even though custody is HELD.
    confirmed = validate_success(
        api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"]), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_a_re_induction_resets_the_screening_axis_and_gates_the_confirm_again(api):
    """PRD §3.5: "An `AcceptanceAgent` may re-weigh a held bag, which moves its
    custody back to `ACCEPTED` and, in the same breath, resets its screening axis
    to `PENDING` and then immediately to `IN_LINE`"
    PRD §3.8: "requires the bag's screening status to be `CLEARED`
    (`ERR_SCREENING_NOT_CLEARED`, 409)."

    Design: Corner/RBAC/hold_on_a_bag_holds_the_entire_connection
    """
    scenario = base_scenario()
    declare_outage(scenario)
    bag, connection, onward, event = make_transfer_bag(
        scenario, required_mct_minutes=75, alarmed=True)
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])
    reinducted = weigh_ok(bag["id"], 48.0)
    assert reinducted["custody_status"] == "ACCEPTED"
    assert reinducted["screening_status"] == "IN_LINE"

    response = api.confirm_connection(connection["id"],
                                      TEST_USERS["transfer_agent_headers"])
    validate_error(response, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)


def test_re_induction_recomputes_the_whole_weigh_cluster(api):
    """PRD §3.5: "The re-induction repeats the whole weigh computation:
    `scale_weight_lb` and `weight_variance_lb` are refreshed,
    `excess_weight_fee_cents` is recomputed in the variant selected by the
    station's outage flag"

    Design: Difficulty/compensating_invariant/alarm_clear_does_not_release_the_bag_from_custody
    """
    scenario = base_scenario()
    declare_outage(scenario)
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"], weight_lb=52),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 52.4)
    event = raise_alarm(bag["id"], scenario["lane"], "2026-09-01T07:20:00Z")
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])

    reinducted = weigh_ok(bag["id"], 54.0)
    assert reinducted["scale_weight_lb"] == 54.0
    assert reinducted["weight_variance_lb"] == pytest.approx(2.0, abs=1e-6)
    assert reinducted["excess_weight_fee_cents"] == 0, \
        "the outage flag selects the HOLD variant for the recomputed fee"
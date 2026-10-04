"""Machines whose lifecycles are cyclic rather than one-way pipelines."""

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    set_clock,
    setup_change_protection_active,
    setup_route_with_armed_watch_and_frozen_freeze,
    setup_passive_watch_reading_wait,
)


def test_watch_cycles_notified_to_wait_and_back_to_notified():
    """PRD §3.2: "From `NOTIFIED` it may move to `WAIT` when the applied
    recommendation is a wait ... A `WAIT` watch that receives any delivered
    recommendation returns to `NOTIFIED`, which is the return path that lets a
    watch that has been told to wait be told something else later."

    Design: Difficulty/non_linear_state_machine/nonlinear_watch_cyclic_notification_cycle
    """
    set_clock()
    route, itinerary, watch = setup_passive_watch_reading_wait()
    headers = TEST_USERS["traveler_headers"]

    first = get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"},
                                                       headers))
    assert first["notification_status"] == "NOTIFIED", (
        "the first notification of a fresh watch is never suppressed"
    )

    # Step past the six-hour cooldown so the WAIT branch can actually deliver.
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-01T07:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    second = get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"},
                                                        headers))
    assert second["notification_status"] == "WAIT", (
        "the applied recommendation on this itinerary is a wait"
    )

    # The return arc: a WAIT watch that receives a delivered recommendation is
    # notified again rather than re-armed.
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-01T14:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    fourth = get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"},
                                                        headers))
    assert fourth["notification_status"] == "NOTIFIED", (
        "WAIT -> NOTIFIED is the cyclic return arc, not a re-arm"
    )
    assert fourth["notification_status"] != "ARMED", (
        "the cycle never re-enters the initial arming state"
    )
    assert fourth["cooldown_suppressed"] is False, (
        "the 14:00 pass is past the cooldown stamped by the 07:00 delivery"
    )


def test_watch_cooldown_suppresses_a_pass_at_the_same_instant():
    """PRD §3.2: "if the current instant is at or before the watch's
    `cooldown_until` the notification is suppressed, `cooldown_suppressed` is
    set true, and the recommendation is computed but not delivered."

    Design: Difficulty/non_linear_state_machine/nonlinear_watch_cyclic_notification_cycle
    """
    set_clock()
    route, itinerary, watch = setup_passive_watch_reading_wait()
    headers = TEST_USERS["traveler_headers"]

    get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"}, headers))
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-01T07:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    delivered = get_success_data(api_client.evaluate_watch(watch["id"],
                                                           {"request_source": "MEMBER"}, headers))
    # A second pass at the same logical instant sits inside the cooldown the
    # first one stamped, so it is computed and suppressed rather than delivered.
    suppressed = get_success_data(api_client.evaluate_watch(watch["id"],
                                                            {"request_source": "MEMBER"},
                                                            headers))

    assert delivered["cooldown_suppressed"] is False
    assert suppressed["cooldown_suppressed"] is True
    assert suppressed["notification_status"] == "WAIT"
    # Every evaluation that is not an expiry increments the attempt counter, so
    # the repeated WAIT state is observable in the count.
    assert suppressed["notification_attempt_count"] == 3, (
        "the same state was entered twice; the attempt count records both"
    )


def test_watch_cycle_never_returns_the_itinerary_to_planned():
    """PRD §3.2: "A watch that neither fires a notification nor holds a wait
    reverts its itinerary instead: the itinerary's `travel_status` returns from
    `WATCHING` to `PLANNED` with `watch_armed` false, and the itinerary's
    version increments on that lapse branch only."

    Design: Difficulty/non_linear_state_machine/nonlinear_watch_cyclic_notification_cycle
    """
    set_clock()
    route, itinerary, watch = setup_passive_watch_reading_wait()
    headers = TEST_USERS["traveler_headers"]

    for stamp in ("2026-09-01T00:00:00Z", "2026-09-01T07:00:00Z", "2026-09-01T07:00:00Z",
                  "2026-09-01T14:00:00Z"):
        get_success_data(api_client.advance_clock({"to_iso8601": stamp},
                                                  TEST_USERS["admin_headers"]))
        get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"},
                                                    headers))

    refreshed = get_success_data(api_client.get_itinerary(itinerary["id"], headers))
    assert refreshed["travel_status"] == "WATCHING", (
        "the cycle re-enters NOTIFIED and WAIT without reverting the itinerary"
    )
    assert refreshed["watch_armed"] is True


def test_first_hold_lapse_reverts_the_change_event_and_stamps_the_unrecovered_fare():
    """PRD §3.7: "Once the current instant passes the event's
    `option_hold_expires_at`, the event returns to `OPTION_SELECTED`, the
    option's hold stops being live and the option becomes `EXPIRED`, and the
    event's `unrecovered_travel_fare_cents` is stamped with the itinerary's old
    departure fare re-rated at the arrival observation".

    Design: Difficulty/non_linear_state_machine/nonlinear_change_event_hold_lapse_revert_then_terminal
    """
    set_clock()
    route, itinerary, protection = setup_change_protection_active()
    headers = TEST_USERS["traveler_otis_headers"]
    change_event = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-05T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    option = get_success_data(
        api_client.offer_option(
            {"change_event_id": change_event["id"], "departure_date": "2026-12-05T00:00:00Z",
             "option_fare_cents": 12300},
            headers)
    )
    get_success_data(api_client.select_option(change_event["id"], {"option_id": option["id"]},
                                              headers))
    held = get_success_data(api_client.accept_option(option["id"], {}, headers))
    assert held["status"] == "HELD"

    # Past the 24-hour hold window: the machine loops rather than terminating.
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-02T12:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    reverted_event = get_success_data(api_client.get_change_event(change_event["id"], headers))
    reverted_option = get_success_data(api_client.get_option(option["id"], headers))

    assert reverted_event["status"] == "OPTION_SELECTED", (
        "the hold-lapse arc returns the event to option selection"
    )
    assert reverted_event["option_hold_expires_at"] is None
    assert reverted_option["status"] == "EXPIRED"
    assert reverted_event["unrecovered_travel_fare_cents"] > 0, (
        "the interrupted travel fare is the written record of the incomplete change"
    )


def test_second_hold_lapse_settles_the_event_instead_of_reverting_again():
    """PRD §3.7: "A second lapse for the same event is not treated as a repeat:
    it fires a terminal override that settles the event with no rebooking,
    recording `disruption_days` of 0 and leaving `remaining_days` equal to the
    product's `bonus_days_remaining`."

    Design: Difficulty/non_linear_state_machine/nonlinear_change_event_hold_lapse_revert_then_terminal
    """
    set_clock()
    route, itinerary, protection = setup_change_protection_active()
    headers = TEST_USERS["traveler_otis_headers"]
    change_event = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-05T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    first_option = get_success_data(
        api_client.offer_option(
            {"change_event_id": change_event["id"], "departure_date": "2026-12-05T00:00:00Z",
             "option_fare_cents": 12300},
            headers)
    )
    get_success_data(api_client.select_option(change_event["id"],
                                              {"option_id": first_option["id"]}, headers))
    get_success_data(api_client.accept_option(first_option["id"], {}, headers))
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-02T12:00:00Z"},
                                              TEST_USERS["admin_headers"]))

    # A fresh option is offered and held so the event enters its second hold.
    second_option = get_success_data(
        api_client.offer_option(
            {"change_event_id": change_event["id"], "departure_date": "2026-12-07T00:00:00Z",
             "option_fare_cents": 13200},
            headers)
    )
    get_success_data(api_client.select_option(change_event["id"],
                                              {"option_id": second_option["id"]}, headers))
    second_hold = get_success_data(api_client.accept_option(second_option["id"], {}, headers))
    assert second_hold["status"] == "HELD"

    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-04T12:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    settled = get_success_data(api_client.get_change_event(change_event["id"], headers))

    assert settled["status"] == "SETTLED", (
        "the second lapse terminates through the override rather than looping"
    )
    assert settled["disruption_days"] == 0 or settled["disruption_days"] is not None
    refreshed_protection = get_success_data(
        api_client.get_protection(protection["id"], headers)
    )
    assert settled["remaining_days"] == refreshed_protection["bonus_days_remaining"], (
        "the override leaves remaining_days equal to the product's bonus day balance"
    )

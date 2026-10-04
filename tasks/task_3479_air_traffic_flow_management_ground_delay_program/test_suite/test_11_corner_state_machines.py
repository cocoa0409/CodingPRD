"""Corner queue: state-machine initial states, valid and invalid transitions,
terminal lockdown, and cascade side effects."""

from test_helpers import (
    COMMAND_CENTER_HEADERS,
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    adjudicate_ga_request,
    assert_instant,
    at,
    cancel_flight,
    cancel_tmi,
    clear_event,
    confirm_event,
    create_airport,
    create_carrier,
    create_ga_operator,
    create_ga_request,
    expected_slot_count,
    expected_slot_time,
    file_flight,
    flight_update_payload,
    gdp_payload,
    get_flight,
    get_tmi,
    list_flights,
    list_facility_events,
    list_operator_ga_requests,
    list_tmi_slots,
    propose_gdp,
    report_constraint_event,
    run_compression,
    set_clock,
    setup_active_gdp,
    setup_ga_scenario,
    update_flight,
    validate_error,
    validate_success,
)


class TestTmiInitialState:
    def test_proposed_tmi_birth_state(self, api):
        """PRD §3.4: "A proposed TMI is born `PROPOSED`, records the proposer's
        `X-User-ID` as `proposed_by_user_id`, starts with `revision_count` 0
        and `activated_at` null, and can be listed on its facility filtered by
        `status` and `tmi_type`."

        Design: Corner/state_machines/tmi_initial_state_proposed
        """
        set_clock(api)
        facility = create_airport(api)
        resp = api.create_tmi(
            facility["id"],
            gdp_payload(
                program_start=at("13:00"), program_end=at("15:00"), controlled_rate=6
            ),
            FLOW_MANAGER_HEADERS,
        )
        tmi = validate_success(resp, 201)
        assert tmi["status"] == "PROPOSED"
        assert tmi["revision_count"] == 0
        assert tmi["activated_at"] is None
        assert tmi.get("published_by_user_id") is None
        assert tmi["proposed_by_user_id"] == "fm-1", (
            "the proposer's X-User-ID is recorded for segregation of duties"
        )


class TestTmiActivateFromProposedRejected:
    def test_activate_requires_published(self, api):
        """PRD §3.4: "A `FlowManager` activates a `PUBLISHED` initiative; from
        `REVISING` the same act applies a pending revision instead (§3.6), and
        from any other state it fails with `ERR_INVALID_STATE`."
        PRD §3.9 (slot birth): "slots are born `OPEN` at activation"

        Design: Corner/state_machines/tmi_activate_from_proposed_rejected
        """
        set_clock(api)
        facility = create_airport(api)
        tmi = propose_gdp(api, facility["id"])
        resp = api.activate_tmi(tmi["id"], FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_tmi(api, tmi["id"])["status"] == "PROPOSED"
        _, meta = list_tmi_slots(api, tmi["id"])
        assert meta["total_count"] == 0, "no slots are generated before activation"


class TestTmiTerminalLockdown:
    def test_cancelled_tmi_absorbs_every_action(self, api):
        """PRD §3.9: "Once an initiative is `CANCELLED` — or `COMPLETED` — any
        further action against it is rejected with `ERR_TMI_TERMINAL`."

        Design: Corner/state_machines/tmi_terminal_lockdown_after_cancel
        """
        set_clock(api)
        facility = create_airport(api)
        tmi = propose_gdp(api, facility["id"])
        cancel_tmi(api, tmi["id"])

        resp = api.publish_tmi(tmi["id"], COMMAND_CENTER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TMI_TERMINAL)
        resp = api.activate_tmi(tmi["id"], FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TMI_TERMINAL)
        resp = api.complete_tmi(tmi["id"], COMMAND_CENTER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TMI_TERMINAL)
        assert get_tmi(api, tmi["id"])["status"] == "CANCELLED"


class TestConstraintClearFromReported:
    def test_reported_event_can_clear_directly(self, api):
        """PRD §3.2: "Clearing is the terminal act, allowed from `REPORTED` or
        `CONFIRMED` and rejected from `CLEARED` with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/constraint_clear_from_reported_valid
        """
        facility = create_airport(api)
        event = report_constraint_event(
            api, facility["id"], event_type="WEATHER", severity=1,
            window_start=at("13:00"), window_end=at("15:00"),
        )
        cleared = clear_event(api, event["id"])
        assert cleared["status"] == "CLEARED"
        assert cleared["version"] == 2, "exactly one mutation since creation"


class TestConstraintConfirmTwiceRejected:
    def test_confirm_is_not_idempotent(self, api):
        """PRD §3.2: "Confirming a `REPORTED` event — from any other state the
        request fails with `ERR_INVALID_STATE` (HTTP 409) — moves it to
        `CONFIRMED` and fires a two-link cascade."

        Design: Corner/state_machines/constraint_confirm_twice_rejected
        """
        facility = create_airport(api)
        event = report_constraint_event(
            api, facility["id"], event_type="WEATHER", severity=1,
            window_start=at("13:00"), window_end=at("15:00"),
        )
        confirm_event(api, event["id"])
        resp = api.confirm_constraint_event(event["id"], FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        events, _ = list_facility_events(api, facility["id"])
        assert {e["id"]: e["status"] for e in events}[event["id"]] == "CONFIRMED"


class TestFlightCancelAirborneRejected:
    def test_airborne_flight_not_cancellable(self, api):
        """PRD §3.5: "Cancellation is allowed only while the flight is
        `SLOTTED`-or-not but operationally `SCHEDULED`: cancelling an
        `AIRBORNE` or `LANDED` flight is rejected with
        `ERR_FLIGHT_NOT_CANCELLABLE` (HTTP 409)."

        Design: Corner/state_machines/flight_cancel_airborne_rejected
        """
        facility = create_airport(api)
        operator, operator_headers = create_carrier(api)
        flight = file_flight(api, operator, facility["id"], scheduled_arrival=at("13:05"))
        update_flight(api, flight, new_ops_status="AIRBORNE")
        resp = api.cancel_flight(flight["id"], operator_headers)
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_CANCELLABLE)
        assert get_flight(api, flight["id"])["ops_status"] == "AIRBORNE"


class TestFlightOpsSkipRejected:
    def test_scheduled_to_landed_skip_rejected(self, api):
        """PRD §3.5: "Supplying `new_ops_status` advances the operations
        dimension along its single chain: `SCHEDULED` to `AIRBORNE`, and
        `AIRBORNE` to `LANDED`; requesting an advance from the wrong from-state
        fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/flight_ops_skip_rejected
        """
        facility = create_airport(api)
        operator, operator_headers = create_carrier(api)
        flight = file_flight(api, operator, facility["id"], scheduled_arrival=at("13:05"))
        resp = api.update_flight(
            flight["id"],
            flight_update_payload(
                expected_flight_version=flight["version"], new_ops_status="LANDED"
            ),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_flight(api, flight["id"])["ops_status"] == "SCHEDULED"


class TestSlotPoolShapeAfterActivation:
    def test_twelve_slots_two_assigned_last_reserved(self, api):
        """PRD §3.4: "The slot interval is exactly 3600 divided by the
        `controlled_rate` seconds. The number of slots is the whole number of
        such intervals that fit in the program window, and slot with
        `slot_index` k — zero-based, ascending in `slot_time` — is placed at
        `program_start` plus k interval-lengths. A reserved tail is carved out
        for general aviation: the count of reserved slots is `GA_QUOTA_PCT`
        (10) percent of the slot count rounded down, but never fewer than
        `GA_MIN_RESERVED` (1), and the last reserved-count slots carry
        `is_ga_reserved` true and are skipped by the initial carrier
        allocation."
        PRD §3.4: "Eligible flights are ranked by `scheduled_arrival` ascending
        with `created_at` ascending as the tie-break — original schedule order
        — and the j-th flight in that order takes the j-th non-reserved slot
        ascending in `slot_time`."

        Design: Corner/state_machines/slot_pool_shape_after_activation
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",),
            flight_specs=((0, "AAL1", "13:05"), (0, "AAL2", "13:10")),
        )
        f1, f2 = world["flights"]
        slots, meta = list_tmi_slots(api, world["tmi"]["id"])
        assert meta["total_count"] == expected_slot_count(at("13:00"), at("15:00"), 6) == 12
        by_index = {s["slot_index"]: s for s in slots}
        assert by_index[0]["status"] == "ASSIGNED"
        assert by_index[0]["assigned_flight_id"] == f1["id"]
        assert_instant(by_index[0]["slot_time"], at("13:00"), "slot 0 time")
        assert by_index[1]["status"] == "ASSIGNED"
        assert by_index[1]["assigned_flight_id"] == f2["id"]
        last = by_index[11]
        assert last["slot_time"] == expected_slot_time(at("13:00"), 6, 11) == at("14:50")
        assert last["is_ga_reserved"] is True
        assert last["status"] == "OPEN"
        for index in range(2, 11):
            assert by_index[index]["status"] == "OPEN"
            assert by_index[index]["is_ga_reserved"] is False


class TestGaRequestExpiresOnCancel:
    def test_pending_request_expires_with_program(self, api):
        """PRD §3.7: "Whatever their state, pending requests do not outlive the
        program: when the initiative is cancelled or completed, every
        `REQUESTED` and `WAITLISTED` request on it expires to `EXPIRED`."

        Design: Corner/state_machines/ga_request_expires_on_cancel
        """
        world = setup_ga_scenario(api, num_requests=1)
        request = world["ga_requests"][0]
        cancel_tmi(api, world["tmi"]["id"])
        requests = list_operator_ga_requests(api, world["ga_operator"]["id"])
        status_by_id = {r["id"]: r["status"] for r in requests}
        assert status_by_id[request["id"]] == "EXPIRED", (
            "the cancel cascade expired the pending request without adjudication"
        )
        assert get_tmi(api, world["tmi"]["id"])["status"] == "CANCELLED"


class TestWaitlistedGaPromotedByCompression:
    def test_compression_promotes_waitlisted_request_first(self, api):
        """PRD §3.5: "Then GA promotion happens first: `WAITLISTED`
        GAAccommodationRequests, ranked by `priority_class` with
        `HIGH_PRIORITY` before `STANDARD` and then by `created_at` ascending,
        consume reserved slots in the pool whose `slot_time` lies within each
        request's window, so long as the count of reserved slots currently
        `ASSIGNED` to GA-created flights stays below the program's
        reserved-slot count; each promotion runs the full accommodation cascade
        of §3.7 — a new flight created, the slot assigned, a `GA_ASSIGNMENT`
        transaction written."
        PRD §3.7: "a cancelled GA flight frees its quota headroom"

        Design: Corner/state_machines/waitlisted_ga_promoted_by_compression
        """
        world = setup_active_gdp(
            api, controlled_rate=12, program_start="13:00", program_end="14:00",
            carrier_names=("Alpha Air",),
            flight_specs=((0, "AAL1", "13:02"), (0, "AAL2", "13:07")),
        )
        tmi_id = world["tmi"]["id"]
        ga_operator, _ = create_ga_operator(api)
        first = create_ga_request(
            api, ga_operator, tmi_id,
            requested_window_start=at("13:30"), requested_window_end=at("14:00"),
            priority_class="STANDARD",
        )
        second = create_ga_request(
            api, ga_operator, tmi_id,
            requested_window_start=at("13:30"), requested_window_end=at("14:00"),
            priority_class="HIGH_PRIORITY",
        )
        granted = adjudicate_ga_request(api, first["id"], "ACCOMMODATE")
        assert granted["status"] == "ACCOMMODATED"
        held_out = adjudicate_ga_request(api, second["id"], "ACCOMMODATE")
        assert held_out["status"] == "WAITLISTED", "quota exhausted: the second waits"

        # cancelling the accommodated GA flight frees the reserved slot
        cancel_flight(api, get_flight(api, granted["accommodated_flight_id"]))

        run = run_compression(api, tmi_id)
        assert run["moves_made"] == 0, "the freed reserved slot went to GA promotion"
        assert run["passes_executed"] == 1
        assert second["id"] in run["promoted_ga_request_ids"]
        assert run["remaining_open_slots"] == 9, "carrier slots 13:10-13:50 stay OPEN"

        ga_flights, _ = list_flights(api, {"operator_id": ga_operator["id"]})
        slotted = [f for f in ga_flights if f["control_status"] == "SLOTTED"]
        assert len(slotted) == 1
        assert_instant(slotted[0]["controlled_arrival"], at("13:55"), "promoted CTA")
        cancelled = [f for f in ga_flights if f["ops_status"] == "CANCELLED"]
        assert len(cancelled) == 1
        assert cancelled[0]["control_status"] == "UNCONTROLLED"

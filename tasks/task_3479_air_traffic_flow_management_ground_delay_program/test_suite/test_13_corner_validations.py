"""Corner queue: validation violations mapped to their exact error ids."""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    assert_instant,
    at,
    constraint_event_payload,
    create_airport,
    ga_request_payload,
    gdp_payload,
    get_flight,
    headers_with_undeclared_role,
    set_clock,
    setup_active_gdp,
    setup_ga_scenario,
    substitution_payload,
    validate_error,
)


class TestMissingAuthHeaders:
    def test_missing_or_undeclared_credentials_rejected_first(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, declaring the role
        the principal acts in. When either header is missing, or when
        `X-User-Role` names a value outside the declared role set, the request
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6 item 1: "The `X-User-Role` and `X-User-ID`
        headers are present and the role is a declared role; failure yields
        `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        unknown = "11111111-2222-3333-4444-555555555555"
        resp = api.get_facility(unknown, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        resp = api.get_facility(unknown, headers=headers_with_undeclared_role())
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestProgramWindowInPastRejected:
    def test_program_end_before_clock_rejected(self, api):
        """PRD §2.6 item 9: "A TMI's
        `program_end` must be strictly after the current logical clock at
        propose time, and `new_program_end` strictly after it at revision time;
        failure yields `ERR_PROGRAM_WINDOW_IN_PAST` (HTTP 422)."

        Design: Corner/validations/program_window_in_past_rejected
        """
        set_clock(api)  # 12:00; the 10:00-11:00 window is well-formed but past
        facility = create_airport(api)
        resp = api.create_tmi(
            facility["id"],
            gdp_payload(
                program_start=at("10:00"), program_end=at("11:00"), controlled_rate=6
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_IN_PAST)


class TestInvalidWindowDegenerate:
    def test_start_equal_end_rejected(self, api):
        """PRD §2.6 item 8: "Every windowed create or
        extend requires start strictly before end; failure yields
        `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/invalid_window_start_not_before_end
        """
        facility = create_airport(api)
        resp = api.create_constraint_event(
            facility["id"],
            constraint_event_payload(
                event_type="WEATHER", severity=2,
                window_start=at("14:00"), window_end=at("14:00"),
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestInvalidRateSevenRejected:
    def test_rate_must_divide_3600(self, api):
        """PRD §2.6 item 15: "A ground delay program's
        `controlled_rate` must be an integer between 6 and 60 inclusive such
        that 3600 is exactly divisible by it; an airspace flow program's must
        be an integer from 1 to 60 inclusive; a ground stop's must be 0; a
        reroute's is ignored and stored as 0. Failure yields `ERR_INVALID_RATE`
        (HTTP 422)."

        Design: Corner/validations/invalid_rate_seven_rejected
        """
        set_clock(api)
        facility = create_airport(api)
        resp = api.create_tmi(
            facility["id"],
            gdp_payload(
                program_start=at("13:00"), program_end=at("15:00"), controlled_rate=7
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RATE)


class TestSubstitutionSameFlightRejected:
    def test_same_flight_pair_rejected(self, api):
        """PRD §2.6 item 18: "Evaluated in this sub-order:
        first `flight_id_1` must differ from `flight_id_2`
        (`ERR_SUBSTITUTION_SAME_FLIGHT`, HTTP 422), then both flights must hold
        `ASSIGNED` slots in this TMI (`ERR_FLIGHT_NOT_IN_PROGRAM`, HTTP 422),
        then for each flight the absolute shift between the other flight's
        slot time and this flight's `scheduled_arrival` must not exceed
        `SUBSTITUTION_MAX_SHIFT_MINUTES` (120 minutes)
        (`ERR_SUBSTITUTION_SHIFT_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/substitution_same_flight_rejected
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",), flight_specs=((0, "AAL1", "13:05"),)
        )
        flight = world["flights"][0]
        resp = api.create_substitution(
            world["tmi"]["id"],
            substitution_payload(flight["id"], flight["id"]),
            world["operator_headers"][0],
        )
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_SAME_FLIGHT)


class TestSubstitutionStaleDataRejected:
    def test_stale_eta_data_rejected(self, api):
        """PRD §2.6 item 11: "Both substitution
        flights' `last_eta_reported_at` must lie within
        `FLIGHT_DATA_FRESHNESS_SECONDS` (3600 seconds) of the current logical
        clock; failure yields `ERR_STALE_FLIGHT_DATA` (HTTP 422)."

        Design: Corner/validations/substitution_stale_data_rejected
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",),
            flight_specs=((0, "AAL1", "13:05"), (0, "AAL3", "13:20")),
        )
        f1, f3 = world["flights"]
        set_clock(api, at("13:30"))  # last ETA report was 12:00: 5400s > 3600s
        resp = api.create_substitution(
            world["tmi"]["id"],
            substitution_payload(f1["id"], f3["id"]),
            world["operator_headers"][0],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_FLIGHT_DATA)


class TestSubstitutionShiftExceededRejected:
    def test_shift_beyond_120_minutes_rejected(self, api):
        """PRD §3.5: "The shift bound protects schedule integrity: for each
        flight, the absolute difference between the other flight's `slot_time`
        and this flight's `scheduled_arrival` must not exceed
        `SUBSTITUTION_MAX_SHIFT_MINUTES` (120 minutes), else
        `ERR_SUBSTITUTION_SHIFT_EXCEEDED`."

        Design: Corner/validations/substitution_shift_exceeded_rejected
        """
        def hhmm(total_minutes):
            return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

        # f0..f13 scheduled 13:05 + 10k minutes; slots land 10 minutes apart
        specs = tuple(
            (0, f"AAL{k:02d}", hhmm(13 * 60 + 5 + 10 * k)) for k in range(14)
        )
        world = setup_active_gdp(
            api, program_start="13:00", program_end="17:00",
            carrier_names=("Alpha Air",), flight_specs=specs,
        )
        f0, f13 = world["flights"][0], world["flights"][13]
        assert_instant(
            get_flight(api, f0["id"])["controlled_arrival"], at("13:00"), "f0 CTA"
        )
        assert_instant(
            get_flight(api, f13["id"])["controlled_arrival"], at("15:10"), "f13 CTA"
        )

        resp = api.create_substitution(
            world["tmi"]["id"],
            substitution_payload(f0["id"], f13["id"]),
            world["operator_headers"][0],
        )
        # |15:10 - 13:05| = 125 > 120 for f0; |13:00 - 15:15| = 135 > 120 for f13
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_SHIFT_EXCEEDED)
        assert_instant(
            get_flight(api, f0["id"])["controlled_arrival"], at("13:00"),
            "a rejected swap leaves both CTAs untouched",
        )
        assert_instant(
            get_flight(api, f13["id"])["controlled_arrival"], at("15:10"), "f13 CTA"
        )


class TestFlightNotInProgramRejected:
    def test_uncontrolled_flight_cannot_substitute(self, api):
        """PRD §2.6 item 18: "Evaluated in this sub-order:
        first `flight_id_1` must differ from `flight_id_2`
        (`ERR_SUBSTITUTION_SAME_FLIGHT`, HTTP 422), then both flights must hold
        `ASSIGNED` slots in this TMI (`ERR_FLIGHT_NOT_IN_PROGRAM`, HTTP 422),
        then for each flight the absolute shift between the other flight's
        slot time and this flight's `scheduled_arrival` must not exceed
        `SUBSTITUTION_MAX_SHIFT_MINUTES` (120 minutes)
        (`ERR_SUBSTITUTION_SHIFT_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/flight_not_in_program_rejected
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",),
            flight_specs=((0, "AAL1", "13:05"), (0, "AAL99", "16:30")),
        )
        f1, g1 = world["flights"]
        assert get_flight(api, g1["id"])["control_status"] == "UNCONTROLLED", (
            "16:30 falls outside the 13:00-15:00 program window"
        )
        resp = api.create_substitution(
            world["tmi"]["id"],
            substitution_payload(f1["id"], g1["id"]),
            world["operator_headers"][0],
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_IN_PROGRAM)


class TestGaWindowOutsideProgramRejected:
    def test_window_overhanging_program_end_rejected(self, api):
        """PRD §2.6 item 10: "A GA accommodation
        request's window must lie entirely inside the target program window;
        failure yields `ERR_GA_WINDOW_OUTSIDE_PROGRAM` (HTTP 422)."

        Design: Corner/validations/ga_window_outside_program_rejected
        """
        world = setup_ga_scenario(api, num_requests=0)
        resp = api.create_ga_request(
            world["ga_operator"]["id"],
            ga_request_payload(
                tmi_id=world["tmi"]["id"],
                requested_window_start=at("14:00"),
                requested_window_end=at("16:00"),
                priority_class="STANDARD",
            ),
            world["ga_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GA_WINDOW_OUTSIDE_PROGRAM)


class TestFacilityNotFoundPrecedesBody:
    def test_unknown_facility_wins_over_degenerate_window(self, api):
        """PRD §2.10: "Path identifiers on nested routes resolve left to right
        — the facility before the TMI, forecast, or event beneath it; the
        operator before the flight; the GA request after its own id — and the
        first unresolvable id produces the corresponding 404 error from the
        catalogue before any business rule is consulted."

        Design: Corner/validations/facility_not_found_precedes_body
        """
        resp = api.create_tmi(
            "11111111-2222-3333-4444-555555555555",
            gdp_payload(
                program_start=at("13:00"), program_end=at("13:00"), controlled_rate=6
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND)

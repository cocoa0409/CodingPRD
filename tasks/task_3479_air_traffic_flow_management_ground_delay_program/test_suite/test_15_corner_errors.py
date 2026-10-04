"""Corner queue: the error envelope and the not-found catalogue."""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    assert_envelope_meta,
    at,
    create_carrier,
    create_ga_operator,
    create_sector,
    flight_payload,
    ga_adjudication_payload,
    ga_request_payload,
    reroute_assignment_payload,
    setup_active_tmi,
    setup_reroute_scenario,
    validate_error,
)

UNKNOWN = "11111111-2222-3333-4444-555555555555"


class TestErrorEnvelopeShape:
    def test_error_body_follows_the_fixed_envelope(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_flight(UNKNOWN, FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert_envelope_meta(body)


class TestNotFoundCatalogSpotChecks:
    def test_every_remaining_404_is_triggerable(self, api):
        """PRD §2.6 item 4: "Path-template ids resolve left to right
        — facility before tmi, forecast or event; operator before flight; then
        the GA request — and body foreign-key references (`arrival_facility_id`,
        `tmi_id`, `flight_id_1`, `flight_id_2`, `flight_id`, `via_sector_id`)
        resolve. Failure yields the specific not-found error:
        `ERR_FACILITY_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`,
        `ERR_FLIGHT_NOT_FOUND`, `ERR_TMI_NOT_FOUND`,
        `ERR_CONSTRAINT_EVENT_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`,
        `ERR_GA_REQUEST_NOT_FOUND`, or `ERR_REROUTE_ASSIGNMENT_NOT_FOUND` (all
        HTTP 404)."

        Design: Corner/errors/not_found_catalog_spot_checks
        """
        resp = api.get_operator(UNKNOWN, FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_FOUND)
        resp = api.get_tmi(UNKNOWN, FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TMI_NOT_FOUND)
        resp = api.confirm_constraint_event(UNKNOWN, FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_EVENT_NOT_FOUND)
        resp = api.publish_capacity_forecast(UNKNOWN, FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_FORECAST_NOT_FOUND)
        resp = api.adjudicate_ga_request(
            UNKNOWN, ga_adjudication_payload("DENY"), FLOW_MANAGER_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_GA_REQUEST_NOT_FOUND)
        resp = api.get_reroute_assignment(UNKNOWN, FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_REROUTE_ASSIGNMENT_NOT_FOUND)


class TestFlightToSectorRejected:
    def test_arrival_facility_must_be_airport(self, api):
        """PRD §3.5: "The arrival facility must resolve and must be of type
        `AIRPORT`; pointing a flight at an `EN_ROUTE_SECTOR` fails with
        `ERR_FACILITY_TYPE_NOT_AIRPORT` (HTTP 422)."

        Design: Corner/errors/flight_to_sector_rejected
        """
        sector = create_sector(api, ident="ZDC42", base_acceptance_rate=10)
        operator, operator_headers = create_carrier(api)
        resp = api.create_flight(
            operator["id"],
            flight_payload(
                designator="AAL1", origin="KORD",
                arrival_facility_id=sector["id"], scheduled_arrival=at("13:05"),
            ),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_TYPE_NOT_AIRPORT)


class TestGaRequestNonGdpRejected:
    def test_accommodation_only_inside_ground_delay_program(self, api):
        """PRD §3.7: "The target must be a `GROUND_DELAY_PROGRAM`, else
        `ERR_TMI_TYPE_NOT_GDP`"

        Design: Corner/errors/ga_request_non_gdp_rejected
        """
        world = setup_active_tmi(api, tmi_type="REROUTE", controlled_rate=None)
        ga_operator, ga_headers = create_ga_operator(api)
        resp = api.create_ga_request(
            ga_operator["id"],
            ga_request_payload(
                tmi_id=world["tmi"]["id"],
                requested_window_start=at("14:00"),
                requested_window_end=at("15:00"),
                priority_class="STANDARD",
            ),
            ga_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TMI_TYPE_NOT_GDP)


class TestRerouteSectorTypeRejected:
    def test_via_sector_must_be_en_route_sector(self, api):
        """PRD §3.8: "the `via_sector_id` must resolve to a facility of type
        `EN_ROUTE_SECTOR`, and pointing it at an `AIRPORT` fails with
        `ERR_REROUTE_SECTOR_TYPE` (HTTP 422)"

        Design: Corner/errors/reroute_sector_type_rejected
        """
        world = setup_reroute_scenario(api, flight_etas=("13:30",))
        flight = world["flights"][0]
        resp = api.create_reroute_assignment(
            world["tmi"]["id"],
            reroute_assignment_payload(
                flight_id=flight["id"],
                via_sector_id=world["airport"]["id"],
                assigned_route="J60",
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_REROUTE_SECTOR_TYPE)

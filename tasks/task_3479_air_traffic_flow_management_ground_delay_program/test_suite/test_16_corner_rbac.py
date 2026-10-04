"""Corner queue: role-based access control — exclusive operations, entity-
backed ownership, segregation of duties, and shared reads."""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    OPERATOR_HEADERS,
    ApiErrorId,
    at,
    create_airport,
    create_carrier,
    create_published_forecast,
    file_flight,
    gdp_payload,
    get_flight,
    get_tmi,
    make_command_center_headers,
    make_operator_headers,
    propose_gdp,
    publish_tmi,
    set_clock,
    validate_error,
    validate_success,
)


class TestOperatorCannotPublishTmi:
    def test_publish_is_exclusive_to_command_center(self, api):
        """PRD §2.1: "When the role is declared but the endpoint does not
        permit that role, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §2.1 (CommandCenterAdmin): "Its exclusive operations are `POST
        /atfm/tmis/{id}/publish`, `POST /atfm/tmis/{id}/cancel`, and `POST
        /atfm/tmis/{id}/complete`."

        Design: Corner/rbac/operator_cannot_publish_tmi
        """
        set_clock(api)
        facility = create_airport(api)
        tmi = propose_gdp(api, facility["id"])
        resp = api.publish_tmi(tmi["id"], OPERATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_tmi(api, tmi["id"])["status"] == "PROPOSED"


class TestCommandCenterCannotProposeTmi:
    def test_propose_is_exclusive_to_flow_manager(self, api):
        """PRD §2.1: "When the role is declared but the endpoint does not
        permit that role, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §2.1 (FlowManager): "Its exclusive operations are `POST
        /atfm/facilities/{id}/constraint-events`, ... `POST
        /atfm/facilities/{id}/tmis`, `POST /atfm/tmis/{id}/activate`, ..."

        Design: Corner/rbac/command_center_cannot_propose_tmi
        """
        set_clock(api)
        facility = create_airport(api)
        resp = api.create_tmi(
            facility["id"],
            gdp_payload(
                program_start=at("13:00"), program_end=at("15:00"), controlled_rate=6
            ),
            make_command_center_headers("cc-1"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestNotResourceOwnerFlightCancel:
    def test_operator_cannot_cancel_another_operators_flight(self, api):
        """PRD §2.1 (Operator): "When `X-User-Role` is `Operator`, `X-User-ID`
        is the `id` of the acting Operator; ownership checks on any resource
        that references an Operator compare the resource's operator foreign key
        to `X-User-ID`. A mismatch — a path operator id that differs from
        `X-User-ID`, a flight whose `operator_id` differs, or a substitution
        body referencing any flight owned by a different operator — is rejected
        with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/not_resource_owner_flight_cancel
        """
        facility = create_airport(api)
        op_a, op_a_headers = create_carrier(api, "Alpha Air")
        op_b, _ = create_carrier(api, "Bravo Air")
        flight = file_flight(
            api, op_b, facility["id"], designator="BAL1", scheduled_arrival=at("13:15")
        )
        resp = api.cancel_flight(flight["id"], op_a_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_flight(api, flight["id"])["ops_status"] == "SCHEDULED"


class TestSegregationOfDutiesPublishRejected:
    def test_proposer_may_not_publish_own_tmi(self, api):
        """PRD §3.4: "Publication is the command center's act, and it is
        deliberately separated from proposal: the `CommandCenterAdmin` who
        publishes must not be the principal who proposed, so a
        `published_by_user_id` equal to `proposed_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

        Design: Corner/rbac/segregation_of_duties_publish_rejected
        """
        set_clock(api)
        facility = create_airport(api)
        create_published_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        # proposed under the default FlowManager identity fm-1
        tmi = propose_gdp(api, facility["id"], proposer_headers=FLOW_MANAGER_HEADERS)

        resp = api.publish_tmi(tmi["id"], make_command_center_headers("fm-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        published = publish_tmi(api, tmi["id"], make_command_center_headers("cc-1"))
        assert published["status"] == "PUBLISHED", (
            "a different command-center id passes the segregation rule"
        )


class TestSharedReadOperatorAllowed:
    def test_operator_reads_tmi_involving_others(self, api):
        """PRD §2.1: "All four roles additionally share every read endpoint:
        `GET /atfm/facilities/{id}`, `GET /atfm/operators/{id}`, `GET
        /atfm/facilities/{id}/constraint-events`, `GET
        /atfm/facilities/{id}/capacity-forecasts`, `GET
        /atfm/facilities/{id}/tmis`, `GET /atfm/tmis/{id}`, `GET
        /atfm/tmis/{id}/revisions`, `GET /atfm/flights`, `GET
        /atfm/flights/{id}`, `GET /atfm/tmis/{id}/slots`, `GET
        /atfm/flights/{id}/slots`, `GET /atfm/tmis/{id}/compression-runs`, `GET
        /atfm/operators/{id}/ga-requests`, `GET /atfm/tmis/{id}/ga-requests`,
        `GET /atfm/reroute-assignments`, `GET /atfm/reroute-assignments/{id}`,
        `GET /atfm/operators/{id}/delay-ledgers`, `GET
        /atfm/tmis/{id}/delay-ledgers`, and `GET
        /atfm/tmis/{id}/slot-transactions`."

        Design: Corner/rbac/shared_read_operator_allowed
        """
        set_clock(api)
        facility = create_airport(api)
        operator, _ = create_carrier(api)
        tmi = propose_gdp(api, facility["id"])
        resp = api.get_tmi(tmi["id"], make_operator_headers(operator["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "PROPOSED"

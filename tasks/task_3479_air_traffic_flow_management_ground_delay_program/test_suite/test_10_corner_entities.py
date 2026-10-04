"""Corner queue: entity creation, defaults, and field discipline."""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    ApiErrorId,
    assert_facility,
    assert_flight,
    assert_instant,
    assert_tmi_revision,
    at,
    create_airport,
    create_carrier,
    facility_payload,
    flight_payload,
    ga_request_payload,
    get_tmi,
    list_operator_ga_requests,
    operator_payload,
    set_clock,
    setup_active_gdp,
    tmi_revision_payload,
    validate_error,
    validate_success,
    is_valid_uuid,
)


class TestFacilityCreationWithDefaults:
    def test_facility_born_operational_with_system_fields(self, api):
        """PRD §3.1: "A facility is born with `status` `OPERATIONAL`"
        PRD §2.4: "Every primary resource carries four system-maintained
        fields. The `id` is a server-minted UUID with no type prefix.
        `created_at` is an ISO 8601 UTC timestamp with three fractional digits,
        fixed at creation. `updated_at` uses the same format and is refreshed
        on every mutation of the resource. `version` is an integer that
        increments by exactly one on every mutation; clients read it and echo
        it back on the optimistic-concurrency-guarded writes described in
        §2.7."

        Design: Corner/entities/facility_creation_with_defaults
        """
        set_clock(api)
        resp = api.create_facility(
            facility_payload(ident="KJFK", facility_type="AIRPORT",
                             base_acceptance_rate=40),
            SYSTEM_ADMIN_HEADERS,
        )
        facility = validate_success(resp, 201)
        assert_facility(facility)
        assert facility["status"] == "OPERATIONAL"
        assert facility["version"] == 1
        assert_instant(facility["created_at"], "2026-09-15T12:00:00Z", "created_at")


class TestFacilityDuplicateIdentRejected:
    def test_duplicate_ident_rejected(self, api):
        """PRD §3.1: "The `ident` is unique across all facilities: a duplicate
        registration is rejected with `ERR_FACILITY_IDENT_CONFLICT`
        (HTTP 409)."

        Design: Corner/entities/facility_duplicate_ident_rejected
        """
        create_airport(api, ident="KEWR", base_acceptance_rate=30)
        resp = api.create_facility(
            facility_payload(ident="KEWR", facility_type="EN_ROUTE_SECTOR",
                             base_acceptance_rate=10),
            SYSTEM_ADMIN_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_IDENT_CONFLICT)


class TestFacilityCreateInputIgnored:
    def test_forged_system_fields_ignored(self, api):
        """PRD §2.4: "Every primary resource carries four system-maintained
        fields. The `id` is a server-minted UUID with no type prefix.
        `created_at` is an ISO 8601 UTC timestamp with three fractional digits,
        fixed at creation."

        Design: Corner/entities/facility_create_input_ignored
        """
        set_clock(api)
        forged_id = "00000000-0000-0000-0000-000000000000"
        resp = api.create_facility(
            facility_payload(
                ident="KORD", facility_type="AIRPORT", base_acceptance_rate=20,
                id=forged_id, created_at="2026-09-01T00:00:01Z",
            ),
            SYSTEM_ADMIN_HEADERS,
        )
        facility = validate_success(resp, 201)
        assert facility["id"] != forged_id, "the server mints its own id"
        assert is_valid_uuid(facility["id"])
        assert_instant(facility["created_at"], "2026-09-15T12:00:00Z", "created_at")


class TestOperatorInvalidEnumRejected:
    def test_unknown_operator_type_rejected(self, api):
        """PRD §2.6: "Independently of the ordered list below, a structurally
        malformed request body — a missing required field, an unknown enum
        value, or a value of the wrong type — is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "an `operator_type` of `SCHEDULED_CARRIER`,
        `GENERAL_AVIATION`, or `UNSCHEDULED_CHARTER`"

        Design: Corner/entities/operator_invalid_enum_rejected
        """
        resp = api.create_operator(
            operator_payload(name="Bad Charter", operator_type="CHARTER"),
            SYSTEM_ADMIN_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestFlightComputedFieldsInputIgnored:
    def test_system_fields_in_flight_create_ignored(self, api):
        """PRD §3.5: "A filed flight is born with `ops_status` `SCHEDULED` and
        `control_status` `UNCONTROLLED` — two independent dimensions carried on
        the same row — with `controlled_arrival` null, `is_overflow` false,
        `provisional_delay_minutes` 0, `final_delay_minutes` null, and
        `last_eta_reported_at` stamped from the logical clock at filing."
        PRD §3.5: "The operator may supply a current `estimated_arrival`; when
        omitted it defaults to `scheduled_arrival`."

        Design: Corner/entities/flight_computed_fields_input_ignored
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        operator, operator_headers = create_carrier(api)
        resp = api.create_flight(
            operator["id"],
            flight_payload(
                designator="AAL1", origin="KORD",
                arrival_facility_id=facility["id"], scheduled_arrival=at("13:05"),
                controlled_arrival=at("13:00"), provisional_delay_minutes=99,
                ops_status="LANDED",
            ),
            operator_headers,
        )
        flight = validate_success(resp, 201)
        assert_flight(flight)
        assert flight["controlled_arrival"] is None
        assert flight["ops_status"] == "SCHEDULED"
        assert flight["control_status"] == "UNCONTROLLED"
        assert flight["provisional_delay_minutes"] == 0
        assert_instant(flight["estimated_arrival"], at("13:05"), "estimated_arrival")


class TestFlightNotFound:
    def test_unknown_flight_id_returns_404(self, api):
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

        Design: Corner/entities/flight_not_found_returns_404
        """
        resp = api.get_flight(
            "11111111-2222-3333-4444-555555555555", FLOW_MANAGER_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_FOUND)


class TestTmiRevisionImmutableRecord:
    def test_revision_is_append_only(self, api):
        """PRD §2.4: "Four record-type resources are exceptions to this rule: a
        TMIRevision, a SlotTransaction, a CompressionRun, and a
        RerouteAssignment each carry only `id` and `created_at`. Both
        `updated_at` and `version` are absent from these four types — they are
        append-only records, never mutated after creation."
        PRD §3.6: "Acceptance creates the TMIRevision with origin `MANUAL`,
        `applied` false, and `revision_index` equal to the program's
        `revision_count` plus one; the record captures
        `previous_controlled_rate` and `new_controlled_rate` — both null when
        only the window changed — and `previous_program_end` and
        `new_program_end` — both null when only the rate changed."

        Design: Corner/entities/tmi_revision_immutable_record
        """
        world = setup_active_gdp(api, flight_specs=())
        tmi_id = world["tmi"]["id"]
        observed_version = get_tmi(api, tmi_id)["version"]
        resp = api.create_tmi_revision(
            tmi_id,
            tmi_revision_payload(
                expected_tmi_version=observed_version,
                new_controlled_rate=10, reason="weather improving",
            ),
            FLOW_MANAGER_HEADERS,
        )
        revision = validate_success(resp, 201)
        assert_tmi_revision(revision)  # id + created_at only, no version/updated_at
        assert revision["revision_index"] == 1
        assert revision["applied"] is False
        assert revision["origin"] == "MANUAL"
        assert revision["previous_controlled_rate"] == 6
        assert revision["new_controlled_rate"] == 10
        assert revision["previous_program_end"] is None
        assert revision["new_program_end"] is None


class TestGaRequestCarrierRejected:
    def test_scheduled_carrier_cannot_request_accommodation(self, api):
        """PRD §3.1: "The operator-type matters downstream: only
        `GENERAL_AVIATION` and `UNSCHEDULED_CHARTER` operators may request GA
        accommodation; a request from a `SCHEDULED_CARRIER` is rejected with
        `ERR_OPERATOR_TYPE_INELIGIBLE` (HTTP 422)."

        Design: Corner/entities/ga_request_carrier_rejected
        """
        world = setup_active_gdp(api, carrier_names=("Alpha Air",), flight_specs=())
        carrier = world["operators"][0]
        carrier_headers = world["operator_headers"][0]
        resp = api.create_ga_request(
            carrier["id"],
            ga_request_payload(
                tmi_id=world["tmi"]["id"],
                requested_window_start=at("14:30"),
                requested_window_end=at("15:00"),
                priority_class="STANDARD",
            ),
            carrier_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_TYPE_INELIGIBLE)
        rows = list_operator_ga_requests(api, carrier["id"])
        assert rows == [], "no request may be persisted for an ineligible operator"

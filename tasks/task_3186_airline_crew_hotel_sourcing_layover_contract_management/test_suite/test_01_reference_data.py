"""Reference data: stations, vendors, union agreements, layover creation,
common-field shape, feedback immutability, and authentication basics."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_station, assert_crew_feedback,
    TEST_USERS, make_vendor_rep_headers,
    create_station_payload, create_union_agreement_payload,
    create_hotel_vendor_payload, create_layover_payload,
    make_station, make_union_agreement, make_vendor,
    make_station_and_union, make_active_contract, make_layover,
    setup_sourced_station,
)
from test_helpers.fixtures import ADMIN, CREWOPS, SOURCING


class TestStationCreation:

    def test_station_creation_applies_fields_and_defaults(self, api):
        """PRD §2.5: "It is created by a `PlatformAdmin` with a `code` (an uppercase
        three-letter IATA code, unique across all stations), a human-readable `name`,
        an IANA `timezone`, a `min_rest_hours` (an integer between 1 and 24 inclusive,
        the minimum crew rest hours behind the hotel door the station commits to), a
        `transport_time_minutes` (an integer between 5 and 180 inclusive, the one-way
        airport-to-hotel ground transport time used in both rest and pickup math), and
        a `room_availability_commitment` (an integer of at least 0, the rooms the
        station commits to source per layover night)."
        PRD §2.7: "The `version` is a system-managed integer that increments by
        exactly 1 on every mutation, and it is the field that optimistic concurrency
        control reads."

        Design: Corner/entities/station_creation_applies_fields_and_defaults
        """
        payload = create_station_payload(
            code="BUR", name="Burbank", timezone="America/Los_Angeles",
            min_rest_hours=10, transport_time_minutes=25,
            room_availability_commitment=12)
        resp = api.create_station(payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_station(data)
        assert data["code"] == "BUR"
        assert data["version"] == 1
        assert data["created_at"] == data["updated_at"]

    def test_station_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.10: "finally request shape (required fields present, enum values
        valid, datetime ranges ordered with the end after the start,
        `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/station_missing_required_field_returns_invalid_request
        """
        payload = create_station_payload(code="BUR", name="Burbank")
        del payload["min_rest_hours"]
        resp = api.create_station(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_station_duplicate_code_rejected(self, api):
        """PRD §2.5: "It is created by a `PlatformAdmin` with a `code` (an uppercase
        three-letter IATA code, unique across all stations), a human-readable `name`,
        an IANA `timezone`, a `min_rest_hours` (an integer between 1 and 24 inclusive,
        the minimum crew rest hours behind the hotel door the station commits to), a
        `transport_time_minutes` (an integer between 5 and 180 inclusive, the one-way
        airport-to-hotel ground transport time used in both rest and pickup math), and
        a `room_availability_commitment` (an integer of at least 0, the rooms the
        station commits to source per layover night)."

        Design: Corner/entities/station_duplicate_code_rejected
        """
        api.create_station(create_station_payload(code="BUR"), ADMIN)
        resp = api.create_station(
            create_station_payload(code="BUR", name="Burbank Duplicate"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_nonexistent_station_get_returns_not_found(self, api):
        """PRD §2.10: "then existence (every identifier in the path and every
        foreign-key identifier in the body resolves to an existing entity, validated
        left-to-right, `ERR_NOT_FOUND`)".

        Design: Corner/entities/nonexistent_station_get_returns_not_found
        """
        resp = api.get_station(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestVendorDefaults:

    def test_vendor_default_status_active(self, api):
        """PRD §3.1: "A freshly registered vendor enters the system with `status` set
        to `ACTIVE`; its lifecycle thereafter spans `ACTIVE`, `SUSPENDED`, and
        `BLACKLISTED`, and only an `ACTIVE` vendor may take part in new business."

        Design: Corner/entities/vendor_default_status_active
        """
        resp = api.create_hotel_vendor(create_hotel_vendor_payload(
            name="Sunport Inn", contact_email="ops@sunport.example"), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"


class TestLayoverCreation:

    def test_layover_rest_compliant_computed_at_creation(self, api):
        """PRD §3.5: "At creation — and on every later change to `arrival_time`,
        `departure_time`, `required_rest_hours`, or `crew_type` — the system computes
        the layover's `rest_compliant` flag."

        Design: Corner/entities/layover_rest_compliant_computed_input_ignored
        """
        station = make_station(code="DRO", min_rest_hours=10, transport_time_minutes=30)
        make_union_agreement(crew_type="PILOT", min_rest_hours=10)
        resp = api.create_layover_requirement(create_layover_payload(
            station_id=station["id"], crew_type="PILOT", crew_count=2,
            arrival_time="2026-10-02T18:00:00Z", departure_time="2026-10-03T09:00:00Z",
            required_rest_hours=12), CREWOPS)
        data = validate_success(resp, expected_status=201)
        # layover 15h - 2*30min = 14.0 >= max(10, 10) -> compliant
        assert data["rest_compliant"] is True

    def test_layover_invalid_crew_type_enum_rejected(self, api):
        """PRD §3.5: "Crew operations registers a **layover requirement** for a station
        with the `station_id`, a `crew_type` of `PILOT` or `FLIGHT_ATTENDANT`, a
        `crew_count` of at least 1 (one room per crew member), the scheduled
        `arrival_time` and `departure_time` (UTC, departure strictly after arrival),
        the `required_rest_hours` (at least 1) the schedule was built to provide, and
        an optional `is_irregular_ops` flag (defaulting to false) marking layovers
        arising from irregular operations."
        PRD §2.10: "finally request shape (required fields present, enum values
        valid, datetime ranges ordered with the end after the start,
        `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/layover_invalid_crew_type_enum_rejected
        """
        station = make_station(code="DRO")
        resp = api.create_layover_requirement(create_layover_payload(
            station_id=station["id"], crew_type="MECHANIC"), CREWOPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_layover_list_filter_by_station_and_pagination(self, api):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/layover_list_filter_by_station_and_pagination
        """
        station, _union = make_station_and_union("HLN")
        other = make_station(code="GTF")
        layover = make_layover(station["id"])
        resp = api.list_layover_requirements(
            CREWOPS, params={"station_id": station["id"], "limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == layover["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestCrewFeedbackShape:

    def test_crew_feedback_immutable_no_version_field(self, api):
        """PRD §2.7: "There is one deliberate exception: **Crew Feedback** records are
        append-only operational testimony and carry only `id` and `created_at`. A
        feedback row has no `updated_at` and no `version`; it is never mutated after
        filing."

        Design: Corner/entities/crew_feedback_immutable_no_version_field
        """
        station, union, vendor, contract = setup_sourced_station("BIL")
        layover = make_layover(station["id"])
        resp = api.create_crew_feedback({
            "contract_id": contract["id"],
            "layover_requirement_id": layover["id"],
            "crew_type": "PILOT", "rating": 4,
            "category": "CLEANLINESS", "comment": "fine",
        }, CREWOPS)
        data = validate_success(resp, expected_status=201)
        assert_crew_feedback(data)
        assert data["rating"] == 4


class TestAuthentication:

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing, or whose value
        is not one of these declared role names, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        resp = api.list_stations({"X-User-ID": "nobody", "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

"""Line-of-travel sequencing and case setup."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_point,
    get_route,
    get_success_data,
    list_sequence_entries,
    reset_clock,
    setup_route_with_active_points,
    setup_unit_with_route,
    validate_error,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]
AMS = TEST_USERS["ams_headers"]


def _replace_payload(route_version: int, entries: list) -> dict:
    return {
        "expected_route_version": route_version,
        "entries": [
            {"delivery_point_id": pid, "line_of_travel_order": pos}
            for pid, pos in entries
        ],
    }


class TestCaseSetupMapping:

    def test_slot_derivation_for_four_entries(self, api):
        """PRD §3.5: "The letter case slot of an entry is one plus the floor of
        its position-minus-one divided by two — adjacent odd/even positions share
        a letter slot row side."
        PRD §3.5: "The flat case slot is one plus the floor of its
        position-minus-one divided by three — three line-of-travel positions map
        into each flat slot."

        Design: Corner/calculations/case_setup_mapping_slot_derivation
        """
        reset_clock()
        ctx = setup_route_with_active_points(4)
        entries = list_sequence_entries(ctx["unit"]["id"], ctx["route"]["id"])
        assert [e["line_of_travel_order"] for e in entries] == [1, 2, 3, 4]
        assert [e["case_slot_letters"] for e in entries] == [1, 1, 2, 2]
        assert [e["case_slot_flats"] for e in entries] == [1, 1, 1, 2]

class TestSequenceIntegrity:

    def test_duplicate_position_rejected(self, api):
        """PRD §3.5: "two entries claiming the same position are rejected with
        `ERR_SEQUENCE_DUPLICATE_POSITION` (HTTP 409)".

        Design: Corner/validations/sequence_duplicate_position_rejected
        """
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        route_id = ctx["route"]["id"]
        p1, p2 = ctx["points"]
        route = get_route(unit_id, route_id)
        resp = api.replace_sequence(
            unit_id, route_id,
            _replace_payload(route["version"], [(p1["id"], 1), (p2["id"], 1)]),
            SUP)
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_DUPLICATE_POSITION)
        entries = list_sequence_entries(unit_id, route_id)
        assert [e["delivery_point_id"] for e in entries] == [p1["id"], p2["id"]]

    def test_replace_reorders_atomically_and_bumps_version_once(self, api):
        """PRD §3.5: "A `RouteSupervisor` replaces the full sequence in one atomic
        commit" and "A successful commit also syncs each entry's point so its
        `active_route_id` references this route, and bumps the route's `version`
        by one."

        Design: Corner/endpoints/sequence_replace_action_endpoint_reorders
        """
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        route_id = ctx["route"]["id"]
        p1, p2 = ctx["points"]
        route = get_route(unit_id, route_id)
        resp = api.replace_sequence(
            unit_id, route_id,
            _replace_payload(route["version"], [(p2["id"], 1), (p1["id"], 2)]),
            SUP)
        validate_success(resp, expected_status=200)
        entries = list_sequence_entries(unit_id, route_id)
        by_point = {e["delivery_point_id"]: e for e in entries}
        assert by_point[p2["id"]]["line_of_travel_order"] == 1
        assert by_point[p1["id"]]["line_of_travel_order"] == 2
        assert [e["case_slot_letters"] for e in entries] == [1, 1]
        assert [e["case_slot_flats"] for e in entries] == [1, 1]
        route_after = get_route(unit_id, route_id)
        assert route_after["version"] == route["version"] + 1


class TestSequenceOcc:

    def test_stale_route_version_rejected(self, api):
        """PRD §2.7: "Replacing a route's full line-of-travel sequence requires
        `expected_route_version` matching the current `version` of the parent
        `CarrierRoute`. A mismatch means another writer has committed a new sequence
        that supersedes the client's intended ordering, and the write is rejected
        with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_sequence_replace_stale_route_version
        """
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        route_id = ctx["route"]["id"]
        p1, p2 = ctx["points"]
        route = get_route(unit_id, route_id)
        first = api.replace_sequence(
            unit_id, route_id,
            _replace_payload(route["version"], [(p2["id"], 1), (p1["id"], 2)]),
            SUP)
        validate_success(first, expected_status=200)
        second = api.replace_sequence(
            unit_id, route_id,
            _replace_payload(route["version"], [(p1["id"], 1), (p2["id"], 2)]),
            SUP)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)
        entries = list_sequence_entries(unit_id, route_id)
        by_point = {e["delivery_point_id"]: e for e in entries}
        assert by_point[p2["id"]]["line_of_travel_order"] == 1
        assert by_point[p1["id"]]["line_of_travel_order"] == 2

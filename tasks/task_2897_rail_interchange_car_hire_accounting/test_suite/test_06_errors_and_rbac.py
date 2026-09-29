"""The error surface and the role surface, exercised from both directions.

The first half proves the not-found family is reachable by two differently
ordered routes, that a present-but-wrong value is refused as sharply as an
absent one, and that all five status classes share one envelope.  The second
half walks the five roles across each other's exclusive operations, the
clearinghouse's exclusive operations, the shared reference reads, and the two
different 403s that guard one endpoint.
"""

from test_helpers import (
    ERR_CAR_NOT_FOUND,
    ERR_CAR_TYPE_NOT_FOUND,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_JUNCTION_NOT_FOUND,
    ERR_MOVEMENT_NOT_FOUND,
    ERR_NOT_A_PARTY_TO_RESOURCE,
    ERR_RAILROAD_NOT_FOUND,
    ERR_RECLAIM_DECISION_NOT_OWNER_ROAD,
    ERR_REPAIR_BILL_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SETTLEMENT_CYCLE_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ApiClient,
    admin_headers,
    admin_headers_without_user_id,
    assert_error_envelope,
    assert_hours,
    assert_money,
    closed_segment_world,
    exchanged_cycle,
    file_reclaim,
    headers_missing_role,
    make_car_hire_accountant_headers,
    make_fleet_owner_headers,
    make_interchange_clerk_headers,
    make_repair_billing_agent_headers,
    open_cycle,
    read_movement,
    register_railroad,
    set_clock,
    standard_world,
    validate_paginated,
    validate_success,
)
import test_helpers.factories as f

DANGLING_ID = "77777777-7777-4777-8777-777777777777"
EVENT_AT = "2026-08-25T00:00:00Z"


def _event_body(world, **overrides):
    """A well-formed CX-to-BN delivery body, overridable field by field."""
    payload = f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                      EVENT_AT, 1000, "LOADED")
    payload.update(overrides)
    return payload


def _no_events(api, world):
    rows, meta = validate_paginated(api.list_interchange_events(
        world.clerk(world.cx), params={"car_id": world.car}))
    assert rows == []
    assert meta["total_count"] == 0


class TestBodyForeignKeysAreCheckedLast:
    """A dangling body key is a 404, but only once shape and enum are clean."""

    def test_each_dangling_body_key_names_its_own_entity(self, api: ApiClient):
        """Three bodies dangling on car, junction and road give three distinct 404s.

        PRD: "Every foreign key in the request body resolves to an existing row, reported through the same not-found catalogue as step 5."

        Design: Corner/errors/body_foreign_key_not_found_is_reported_after_shape_and_enum
        """
        world = standard_world(api, bootstrap_clock=EVENT_AT)
        clerk = world.clerk(world.cx)

        bad_car = api.create_interchange_event(_event_body(world, car_id=DANGLING_ID),
                                              clerk)
        assert_error_envelope(bad_car, ERR_CAR_NOT_FOUND, 404)

        bad_junction = api.create_interchange_event(
            _event_body(world, junction_id=DANGLING_ID), clerk)
        assert_error_envelope(bad_junction, ERR_JUNCTION_NOT_FOUND, 404)

        bad_road = api.create_interchange_event(
            _event_body(world, receiving_road_id=DANGLING_ID), clerk)
        assert_error_envelope(bad_road, ERR_RAILROAD_NOT_FOUND, 404)

        bad_type = api.create_embargo_order(
            f.embargo_payload(world.cx, world.jct, "2026-08-20T00:00:00Z",
                              "2026-08-22T00:00:00Z", car_type_id=DANGLING_ID,
                              reason="Dangling car type"),
            clerk)
        assert_error_envelope(bad_type, ERR_CAR_TYPE_NOT_FOUND, 404)

        _no_events(api, world)
        orders, meta = validate_paginated(api.list_embargo_orders(clerk))
        assert orders == []
        assert meta["total_count"] == 0

    def test_a_bad_enum_and_a_missing_field_both_outrank_the_dangling_key(self, api: ApiClient):
        """The same dangling junction reports the enum error, then the shape error.

        PRD: "Body foreign keys are checked **after** shape and enum validity, so a body carrying both an invalid enum and a dangling identifier reports `ERR_INVALID_ENUM_VALUE`."

        Design: Corner/errors/body_foreign_key_not_found_is_reported_after_shape_and_enum
        """
        world = standard_world(api, bootstrap_clock=EVENT_AT)
        clerk = world.clerk(world.cx)

        enum_wins = api.create_interchange_event(
            _event_body(world, junction_id=DANGLING_ID, event_type="TRANSFER"), clerk)
        assert_error_envelope(enum_wins, ERR_INVALID_ENUM_VALUE, 422)
        assert enum_wins.json()["data"]["error_id"] != ERR_JUNCTION_NOT_FOUND

        missing = _event_body(world, junction_id=DANGLING_ID)
        missing.pop("load_status")
        shape_wins = api.create_interchange_event(missing, clerk)
        assert_error_envelope(shape_wins, ERR_INVALID_REQUEST, 400)
        assert shape_wins.json()["data"]["error_id"] != ERR_JUNCTION_NOT_FOUND

        clean = api.create_interchange_event(_event_body(world, junction_id=DANGLING_ID),
                                            clerk)
        assert_error_envelope(clean, ERR_JUNCTION_NOT_FOUND, 404)
        _no_events(api, world)


class TestMalformedFieldValuesAreRefused:
    """A present field of the wrong type, range or format is as fatal as an absent one."""

    def test_a_string_integer_a_negative_count_and_a_prose_instant_are_all_400(self, api: ApiClient):
        """odometer_miles "1000", odometer_miles -5, a prose date and -1 cents all give 400.

        PRD: "Integers presented as strings, negative cents on a non-negative field, malformed ISO 8601 instants and unparseable bodies all land here."

        Design: Corner/errors/malformed_field_values_return_invalid_request
        """
        world = standard_world(api, bootstrap_clock=EVENT_AT)
        clerk = world.clerk(world.cx)

        as_string = api.create_interchange_event(
            _event_body(world, odometer_miles="1000"), clerk)
        assert_error_envelope(as_string, ERR_INVALID_REQUEST, 400)

        negative = api.create_interchange_event(
            _event_body(world, odometer_miles=-5), clerk)
        assert_error_envelope(negative, ERR_INVALID_REQUEST, 400)

        prose = api.create_interchange_event(
            _event_body(world, interchange_at="25 August 2026"), clerk)
        assert_error_envelope(prose, ERR_INVALID_REQUEST, 400)

        negative_limit = api.create_railroad(
            {"reporting_mark": "UP", "name": "Union Pacific",
             "per_diem_credit_limit_cents": -1},
            admin_headers())
        assert_error_envelope(negative_limit, ERR_INVALID_REQUEST, 400)

        _no_events(api, world)
        roads, meta = validate_paginated(api.list_railroads(
            admin_headers(), params={"reporting_mark": "UP"}))
        assert roads == []
        assert meta["total_count"] == 0

    def test_a_mark_failing_its_pattern_is_a_shape_error_not_a_conflict(self, api: ApiClient):
        """Lowercase "bear" is 400, and the well-formed mark that follows it is 201.

        PRD: "A `ClearinghouseAdmin` admits a railroad by supplying its `reporting_mark` — the industry identifier of two to four uppercase letters, such as BNRR, which must be unique across all registered roads — together with its legal carrier `name`."

        Design: Corner/errors/malformed_field_values_return_invalid_request
        """
        refused = api.create_railroad(
            f.railroad_payload("bear", "Bear Northern Railway"), admin_headers())
        assert_error_envelope(refused, ERR_INVALID_REQUEST, 400)
        assert refused.json()["data"]["error_id"] != ERR_DUPLICATE_RESOURCE

        too_long = api.create_railroad(
            f.railroad_payload("BEARN", "Bear Northern Railway"), admin_headers())
        assert_error_envelope(too_long, ERR_INVALID_REQUEST, 400)

        accepted = validate_success(api.create_railroad(
            f.railroad_payload("BNRR", "Bear Northern Railway"), admin_headers()), 201)
        assert accepted["reporting_mark"] == "BNRR"

        roads, meta = validate_paginated(api.list_railroads(admin_headers()))
        assert meta["total_count"] == 1
        assert [row["reporting_mark"] for row in roads] == ["BNRR"]


class TestErrorEnvelopeIsUniform:
    """400, 401, 404, 409 and 422 all come back in the same two-key envelope."""

    def test_five_status_classes_share_one_error_envelope(self, api: ApiClient):
        """A conflict, an unauthenticated read, a 404, a bad enum and a bad shape all match.

        PRD: "Every error response carries the envelope of §2.2, with the identifier below in `error_id` and a human-readable `message`."

        Design: Corner/errors/error_envelope_is_uniform_across_every_status_class
        """
        cx = register_railroad(api, "CX")
        bn = register_railroad(api, "BN")
        junction = validate_success(api.create_junction(
            f.junction_payload("JCT-CHI", cx, bn), admin_headers()), 201)

        duplicate = api.create_junction(
            f.junction_payload("JCT-CHI", cx, bn, name="Chicago Interchange Again"),
            admin_headers())
        unauthenticated = api.get_junction(junction["id"], headers_missing_role())
        not_found = api.get_junction("88888888-8888-4888-8888-888888888888",
                                    admin_headers())
        bad_enum = api.create_junction(
            f.junction_payload("JCT-KC", cx, bn, name="Kansas City",
                               status="MOTHBALLED"),
            admin_headers())
        bad_shape_body = f.junction_payload("JCT-KC", cx, bn)
        bad_shape_body.pop("name")
        bad_shape = api.create_junction(bad_shape_body, admin_headers())

        assert_error_envelope(duplicate, ERR_DUPLICATE_RESOURCE, 409)
        assert_error_envelope(unauthenticated, ERR_UNAUTHENTICATED, 401)
        assert_error_envelope(not_found, ERR_JUNCTION_NOT_FOUND, 404)
        assert_error_envelope(bad_enum, ERR_INVALID_ENUM_VALUE, 422)
        assert_error_envelope(bad_shape, ERR_INVALID_REQUEST, 400)

        for response in (duplicate, unauthenticated, not_found, bad_enum, bad_shape):
            data = response.json()["data"]
            assert set(data) == {"error_id", "message"}
            assert "junction_code" not in data
            assert "road_a_id" not in data
            assert isinstance(data["message"], str) and data["message"].strip() != ""

        rows, meta = validate_paginated(api.list_junctions(admin_headers()))
        assert meta["total_count"] == 1

    def test_each_error_response_carries_its_own_request_id(self, api: ApiClient):
        """The meta of five failures holds only two keys and five distinct request ids.

        PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_is_uniform_across_every_status_class
        """
        cx = register_railroad(api, "CX")
        bn = register_railroad(api, "BN")
        junction = validate_success(api.create_junction(
            f.junction_payload("JCT-CHI", cx, bn), admin_headers()), 201)

        responses = [
            api.create_junction(f.junction_payload("JCT-CHI", cx, bn), admin_headers()),
            api.get_junction(junction["id"], headers_missing_role()),
            api.get_junction("88888888-8888-4888-8888-888888888888", admin_headers()),
            api.create_junction(f.junction_payload("JCT-KC", cx, bn,
                                                   status="MOTHBALLED"),
                                admin_headers()),
            api.create_junction({"junction_code": "JCT-KC", "road_a_id": cx,
                                 "road_b_id": bn},
                                admin_headers()),
        ]

        request_ids = []
        for response in responses:
            meta = response.json()["meta"]
            assert set(meta) == {"api_request_id", "api_request_timestamp"}
            assert meta["api_request_id"].startswith("req_")
            request_ids.append(meta["api_request_id"])

        assert len(set(request_ids)) == 5
        assert [r.status_code for r in responses] == [409, 401, 404, 422, 400]


CYCLE_CLOCK = "2026-09-01T00:00:00Z"


class TestRoadRolesCannotBorrowEachOthersOperations:
    """The four road roles are peers, and the forbidden set includes reads."""

    def test_each_road_role_is_refused_the_others_exclusive_operation(self, api: ApiClient):
        """Seven cross-role probes all come back 403 ERR_ROLE_NOT_PERMITTED.

        PRD: "The role appears on the called endpoint's authorised list — otherwise `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/road_roles_cannot_reach_another_roles_exclusive_operations
        """
        world = standard_world(api)
        cycle = open_cycle(api, world)

        owner_captures = api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     CYCLE_CLOCK, 1000, "LOADED"),
            world.owner(world.cx))
        assert_error_envelope(owner_captures, ERR_ROLE_NOT_PERMITTED, 403)

        clerk_computes = api.compute_settlement_cycle(cycle["id"], {},
                                                     world.clerk(world.cx))
        assert_error_envelope(clerk_computes, ERR_ROLE_NOT_PERMITTED, 403)

        repair_files_reclaim = api.create_reclaim_claim(
            f.reclaim_payload(DANGLING_ID, "BAD_ORDER", "2026-08-25T00:00:00Z",
                              "2026-08-26T00:00:00Z", 1),
            world.repair(world.bn))
        assert_error_envelope(repair_files_reclaim, ERR_ROLE_NOT_PERMITTED, 403)
        assert repair_files_reclaim.json()["data"]["error_id"] != ERR_MOVEMENT_NOT_FOUND

        accountant_bad_orders = api.report_bad_order(
            world.car, f.bad_order_payload(CYCLE_CLOCK), world.accountant(world.cx))
        assert_error_envelope(accountant_bad_orders, ERR_ROLE_NOT_PERMITTED, 403)

        clerk_reads_ledger = api.list_ledger_entries(world.clerk(world.bn))
        assert_error_envelope(clerk_reads_ledger, ERR_ROLE_NOT_PERMITTED, 403)

        accountant_bills = api.create_repair_bill(
            f.repair_bill_payload(world.car, world.cx, "R-114", "NORMAL_WEAR",
                                  CYCLE_CLOCK, 2.0, 1000),
            world.accountant(world.cx))
        assert_error_envelope(accountant_bills, ERR_ROLE_NOT_PERMITTED, 403)

        clerk_registers_car = api.create_car(
            f.car_payload("CX 100002", world.xm, world.cx), world.clerk(world.cx))
        assert_error_envelope(clerk_registers_car, ERR_ROLE_NOT_PERMITTED, 403)

        _no_events(api, world)
        cars, car_meta = validate_paginated(api.list_cars(
            world.owner(world.cx), params={"owner_road_id": world.cx}))
        assert car_meta["total_count"] == 1
        bills, bill_meta = validate_paginated(api.list_repair_bills(
            world.repair(world.cx)))
        assert bill_meta["total_count"] == 0
        claims, claim_meta = validate_paginated(api.list_reclaim_claims(
            world.accountant(world.bn)))
        assert claim_meta["total_count"] == 0
        standing = validate_success(api.get_settlement_cycle(cycle["id"],
                                                           world.accountant(world.cx)))
        assert standing["status"] == "OPEN"

    def test_the_same_calls_succeed_under_their_own_roles(self, api: ApiClient):
        """Each refused call is a 200 or a 201 once the correct role makes it.

        PRD: "Creation endpoints return HTTP 201 with the created resource; every other successful call returns HTTP 200 with the resource as it stands after the call, except the two sweeps and computed reads whose bespoke payloads are set out in §3.8 and §3.9."

        Design: Corner/rbac/road_roles_cannot_reach_another_roles_exclusive_operations
        """
        world = standard_world(api)

        second_car = validate_success(api.create_car(
            f.car_payload("CX 100002", world.xm, world.cx),
            world.owner(world.cx)), 201)
        assert second_car["car_mark"] == "CX 100002"

        set_clock(api, "2026-08-24T00:00:00Z", world)
        event = validate_success(api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     "2026-08-24T00:00:00Z", 1000, "LOADED"),
            world.clerk(world.cx)), 201)
        assert event["status"] == "RECORDED"

        set_clock(api, "2026-08-25T00:00:00Z", world)
        bad_ordered = validate_success(api.report_bad_order(
            world.car, f.bad_order_payload("2026-08-25T00:00:00Z"),
            world.clerk(world.bn)))
        assert bad_ordered["mechanical_status"] == "BAD_ORDER"

        draft = validate_success(api.create_repair_bill(
            f.repair_bill_payload(world.car, world.bn, "R-114", "HANDLING_DAMAGE",
                                  "2026-08-25T00:00:00Z", 2.0, 1000),
            world.repair(world.bn)), 201)
        assert draft["status"] == "DRAFT"

        cycle = open_cycle(api, world)
        computed = validate_success(api.compute_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        assert computed["status"] == "COMPUTED"

        entries = validate_success(api.list_ledger_entries(world.accountant(world.bn)))
        assert isinstance(entries, list) or "items" in entries


UNUSED_ID = "12121212-1212-4121-8121-121212121212"


class TestClearinghouseExclusiveOperations:
    """The clearinghouse's own verbs are closed to every road role, id or no id."""

    def test_no_road_role_reaches_a_clearinghouse_only_endpoint(self, api: ApiClient):
        """Seven probes on deliberately unused ids are 403, never 404.

        PRD: "They run in one fixed ascending order, and the **first** rule that fails determines the response — later violations are never reported even when several hold simultaneously."

        Design: Corner/rbac/clearinghouse_admin_exclusive_operations_are_closed_to_every_road_role
        """
        bn = register_railroad(api, "BN")
        accountant = make_car_hire_accountant_headers(bn)
        clerk = make_interchange_clerk_headers(bn)

        reopen = api.reopen_settlement_cycle(
            UNUSED_ID, {"reopen_reason": "Road roles may not reopen"}, accountant)
        assert_error_envelope(reopen, ERR_ROLE_NOT_PERMITTED, 403)
        assert reopen.json()["data"]["error_id"] != ERR_SETTLEMENT_CYCLE_NOT_FOUND

        archive = api.archive_settlement_cycle(UNUSED_ID, {}, accountant)
        assert_error_envelope(archive, ERR_ROLE_NOT_PERMITTED, 403)
        assert archive.json()["data"]["error_id"] != ERR_SETTLEMENT_CYCLE_NOT_FOUND

        settle_bill = api.settle_repair_bill(UNUSED_ID, {},
                                           make_repair_billing_agent_headers(bn))
        assert_error_envelope(settle_bill, ERR_ROLE_NOT_PERMITTED, 403)
        assert settle_bill.json()["data"]["error_id"] != ERR_REPAIR_BILL_NOT_FOUND

        sweep = api.expire_due_correction_requests({}, clerk)
        assert_error_envelope(sweep, ERR_ROLE_NOT_PERMITTED, 403)

        register_road = api.create_railroad(
            f.railroad_payload("UP", "Union Pacific"), make_fleet_owner_headers(bn))
        assert_error_envelope(register_road, ERR_ROLE_NOT_PERMITTED, 403)

        register_type = api.create_car_type(
            f.car_type_payload(car_type_code="GS", description="Gondola"), clerk)
        assert_error_envelope(register_type, ERR_ROLE_NOT_PERMITTED, 403)

        register_junction = api.create_junction(
            f.junction_payload("JCT-KC", bn, bn, name="Kansas City"), accountant)
        assert_error_envelope(register_junction, ERR_ROLE_NOT_PERMITTED, 403)

        roads, road_meta = validate_paginated(api.list_railroads(
            admin_headers(), params={"reporting_mark": "UP"}))
        assert road_meta["total_count"] == 0
        types, type_meta = validate_paginated(api.list_car_types(
            admin_headers(), params={"car_type_code": "GS"}))
        assert type_meta["total_count"] == 0

    def test_the_clearinghouse_reaches_the_same_urls_and_gets_the_lookup_error(self, api: ApiClient):
        """As admin the same three unused ids resolve to their own 404s.

        PRD: "Every identifier in the URL path resolves to an existing row of its entity, checked left to right, the error naming the entity that failed: `ERR_RAILROAD_NOT_FOUND`, `ERR_JUNCTION_NOT_FOUND`, `ERR_CAR_TYPE_NOT_FOUND`, `ERR_CAR_NOT_FOUND`, `ERR_INTERCHANGE_EVENT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_RECLAIM_CLAIM_NOT_FOUND`, `ERR_EMBARGO_ORDER_NOT_FOUND`, `ERR_REPAIR_BILL_NOT_FOUND`, `ERR_SETTLEMENT_CYCLE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CORRECTION_REQUEST_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`."

        Design: Corner/rbac/clearinghouse_admin_exclusive_operations_are_closed_to_every_road_role
        """
        register_railroad(api, "BN")

        reopen = api.reopen_settlement_cycle(
            UNUSED_ID, {"reopen_reason": "The clearinghouse may reopen"},
            admin_headers())
        assert_error_envelope(reopen, ERR_SETTLEMENT_CYCLE_NOT_FOUND, 404)

        archive = api.archive_settlement_cycle(UNUSED_ID, {}, admin_headers())
        assert_error_envelope(archive, ERR_SETTLEMENT_CYCLE_NOT_FOUND, 404)

        settle_bill = api.settle_repair_bill(UNUSED_ID, {}, admin_headers())
        assert_error_envelope(settle_bill, ERR_REPAIR_BILL_NOT_FOUND, 404)

        sweep = validate_success(api.expire_due_correction_requests({}, admin_headers()))
        assert sweep["expired_count"] == 0

        road = validate_success(api.create_railroad(
            f.railroad_payload("UP", "Union Pacific"), admin_headers()), 201)
        assert road["reporting_mark"] == "UP"


class TestSharedReferenceReads:
    """The reference registries are the one surface open to all five roles."""

    def test_all_five_roles_read_the_same_car_type(self, api: ApiClient):
        """The rate book reads XM for the clearinghouse and for each of the four roads.

        PRD: "In the authorization column, "All roles" means all five roles named in §2.1 — `ClearinghouseAdmin`, `InterchangeClerk`, `CarHireAccountant`, `RepairBillingAgent` and `FleetOwner` — and a role's presence in that column is only the first gate: the party-standing and actor rules of §2.1 and §3 still decide whether the acting railroad may perform the action on that particular resource."

        Design: Corner/rbac/every_declared_role_can_read_the_shared_reference_endpoints
        """
        world = standard_world(api)
        readers = [
            admin_headers(),
            world.clerk(world.cx),
            world.accountant(world.cx),
            world.repair(world.cx),
            world.owner(world.cx),
        ]

        codes = []
        for headers in readers:
            car_type = validate_success(api.get_car_type(world.xm, headers))
            codes.append(car_type["car_type_code"])
            assert car_type["id"] == world.xm

        assert codes == ["XM"] * 5

    def test_the_opaque_clearinghouse_needs_no_acting_railroad_header(self, api: ApiClient):
        """Without X-User-ID the admin still reads the car type, the junction and the car.

        PRD: "For the four entity-backed roles, `X-User-ID` resolves to a registered railroad — otherwise `ERR_ACTING_RAILROAD_UNKNOWN`."

        Design: Corner/rbac/every_declared_role_can_read_the_shared_reference_endpoints
        """
        world = standard_world(api)
        opaque = admin_headers_without_user_id()
        assert "X-User-ID" not in opaque

        car_type = validate_success(api.get_car_type(world.xm, opaque))
        assert car_type["car_type_code"] == "XM"
        junction = validate_success(api.get_junction(world.jct, opaque))
        assert junction["junction_code"] == "JCT-CHI"
        car = validate_success(api.get_car(world.car, opaque))
        assert car["car_mark"] == "CX 100001"

    def test_the_registries_are_open_to_a_road_that_is_not_a_party(self, api: ApiClient):
        """BN's repair agent reads JCT-CHI, but only three roles reach the exposure read.

        PRD: "A recognised role that is not on the authorised list of the endpoint being called is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/every_declared_role_can_read_the_shared_reference_endpoints
        """
        world = standard_world(api)

        junction = validate_success(api.get_junction(world.jct, world.repair(world.bn)))
        assert junction["junction_code"] == "JCT-CHI"
        car = validate_success(api.get_car(world.car, world.clerk(world.cx)))
        assert car["car_mark"] == "CX 100001"

        by_owner = validate_success(api.get_railroad_exposure(world.cx,
                                                            world.owner(world.cx)))
        by_admin = validate_success(api.get_railroad_exposure(world.cx, admin_headers()))
        assert by_owner["owned_car_count"] == 1
        assert by_admin["owned_car_count"] == 1

        by_clerk = api.get_railroad_exposure(world.cx, world.clerk(world.cx))
        assert_error_envelope(by_clerk, ERR_ROLE_NOT_PERMITTED, 403)
        by_repair = api.get_railroad_exposure(world.cx, world.repair(world.cx))
        assert_error_envelope(by_repair, ERR_ROLE_NOT_PERMITTED, 403)


class TestTwoDistinct403sOnOneEndpoint:
    """The wrong role and the wrong railroad are different refusals."""

    def test_the_wrong_role_and_the_wrong_road_report_different_errors(self, api: ApiClient):
        """A repair agent settling is a role error; NS settling is a standing error.

        PRD: "A road with no standing receives `ERR_NOT_A_PARTY_TO_RESOURCE` (HTTP 403) whether or not the action it attempted would have been legal for a party."

        Design: Corner/rbac/permitted_role_but_non_party_returns_a_different_403
        """
        world = standard_world(api, extra_roads=("NS",), register_first_car=False)
        cycle, computed, exchanged = exchanged_cycle(api, world)

        wrong_role = api.settle_settlement_cycle(cycle["id"], {},
                                               world.repair(world.bn))
        assert_error_envelope(wrong_role, ERR_ROLE_NOT_PERMITTED, 403)

        wrong_road = api.settle_settlement_cycle(cycle["id"], {},
                                                world.accountant(world.ns))
        assert_error_envelope(wrong_road, ERR_NOT_A_PARTY_TO_RESOURCE, 403)
        assert wrong_road.json()["data"]["error_id"] != ERR_ROLE_NOT_PERMITTED

        wrong_road_reads = api.get_settlement_statement(cycle["id"],
                                                       world.accountant(world.ns))
        assert_error_envelope(wrong_road_reads, ERR_NOT_A_PARTY_TO_RESOURCE, 403)

        standing = validate_success(api.get_settlement_cycle(cycle["id"],
                                                          world.accountant(world.cx)))
        assert standing["status"] == "EXCHANGED"

    def test_the_payer_settles_the_period_that_computed_to_zero(self, api: ApiClient):
        """BN, the payer, takes the empty cycle EXCHANGED to SETTLED at a net of 0.

        PRD: "The payer road — and only the payer road, never the payee — then settles, moving `EXCHANGED → SETTLED`, but only if no dispute on the cycle is still `OPEN` or `COUNTERED`; otherwise `ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT`."

        Design: Corner/rbac/permitted_role_but_non_party_returns_a_different_403
        """
        world = standard_world(api, extra_roads=("NS",), register_first_car=False)
        cycle, computed, exchanged = exchanged_cycle(api, world)
        assert computed["movement_line_count"] == 0
        assert_money(computed["pre_fee_net_cents"], 0, "pre_fee_net_cents")
        assert_money(computed["net_settlement_cents"], 0, "net_settlement_cents")

        settled = validate_success(api.settle_settlement_cycle(
            cycle["id"], {}, world.accountant(world.bn)))
        assert settled["status"] == "SETTLED"
        assert_money(settled["net_settlement_cents"], 0, "net_settlement_cents")


DETENTION_FROM = "2026-08-25T00:00:00Z"
DETENTION_TO = "2026-08-26T00:00:00Z"
NOTIFIED_AT = "2026-08-25T12:00:00Z"


def _detention_claim(api):
    """The 11464 segment carrying a 24.00-hour CUSTOMER_DETENTION claim, still FILED."""
    world, movement = closed_segment_world(api)
    claim = file_reclaim(api, world, movement, "CUSTOMER_DETENTION",
                        DETENTION_FROM, DETENTION_TO,
                        detention_notified_at=NOTIFIED_AT)
    return world, movement, claim


class TestReclaimSegregationOfDuties:
    """Allow and disallow belong to the owner; withdraw belongs to the filer."""

    def test_the_filer_cannot_decide_and_the_owner_cannot_withdraw(self, api: ApiClient):
        """Three cross-verb attempts are ERR_RECLAIM_DECISION_NOT_OWNER_ROAD and change nothing.

        PRD: "Only the owner road named in `against_road_id` may allow or disallow, and only the filing road may withdraw; the filer deciding its own claim is `ERR_RECLAIM_DECISION_NOT_OWNER_ROAD`."

        Design: Corner/rbac/segregation_of_duties_splits_allow_and_withdraw_between_the_two_roads
        """
        world, movement, claim = _detention_claim(api)
        assert_hours(claim["claimed_hours"], 24.00, "claimed_hours")
        assert claim["filed_by_road_id"] == world.bn
        assert claim["against_road_id"] == world.cx
        assert claim["status"] == "FILED"

        filer_allows = api.allow_reclaim_claim(
            claim["id"], {"decision_note": "Approving our own claim"},
            world.accountant(world.bn))
        assert_error_envelope(filer_allows, ERR_RECLAIM_DECISION_NOT_OWNER_ROAD, 403)

        filer_disallows = api.disallow_reclaim_claim(
            claim["id"], {"disallow_reason": "Denying our own claim"},
            world.accountant(world.bn))
        assert_error_envelope(filer_disallows, ERR_RECLAIM_DECISION_NOT_OWNER_ROAD, 403)

        owner_withdraws = api.withdraw_reclaim_claim(
            claim["id"], {"withdraw_reason": "Owner retracting the filer's claim"},
            world.accountant(world.cx))
        assert_error_envelope(owner_withdraws, ERR_RECLAIM_DECISION_NOT_OWNER_ROAD, 403)

        standing = validate_success(api.get_reclaim_claim(claim["id"],
                                                       world.accountant(world.cx)))
        assert standing["status"] == "FILED"
        assert_money(standing["credit_cents"], 0, "credit_cents")
        assert standing["decided_at"] is None
        assert_money(read_movement(api, world, movement["id"])["net_hire_cents"], 11464,
                     "net_hire_cents")

    def test_the_owner_road_allows_the_claim_at_the_shared_half(self, api: ApiClient):
        """CX's allowance defaults to 24.00 hours, splits at 0.5 and credits 1422.

        PRD: "The raw credit is the segment's `time_component_cents`, multiplied by the effective hours, divided by the segment's `chargeable_hours`, multiplied by the split percentage, and rounded half up — with the split multiplying **inside** that single rounding, never applied to an already-rounded full credit."

        Design: Corner/rbac/segregation_of_duties_splits_allow_and_withdraw_between_the_two_roads
        """
        world, movement, claim = _detention_claim(api)
        assert_money(movement["time_component_cents"], 10900, "time_component_cents")
        assert_hours(movement["chargeable_hours"], 92.00, "chargeable_hours")

        allowed = validate_success(api.allow_reclaim_claim(
            claim["id"], {}, world.accountant(world.cx)))
        assert allowed["status"] == "ALLOWED"
        assert_hours(allowed["allowed_hours"], 24.00, "allowed_hours")
        assert allowed["split_pct_applied"] == 0.5
        assert_money(allowed["credit_cents"], 1422, "credit_cents")
        assert allowed["decided_at"] is not None

        repriced = read_movement(api, world, movement["id"])
        assert_money(repriced["reclaim_credit_cents"], 1422, "reclaim_credit_cents")
        assert_money(repriced["net_hire_cents"], 10042, "net_hire_cents")

    def test_the_filing_road_withdraws_its_own_undecided_claim(self, api: ApiClient):
        """BN, the filer, takes its FILED claim to WITHDRAWN with a reason.

        PRD: "Withdrawal is available to the filer both as `FILED → WITHDRAWN` and as `ALLOWED → WITHDRAWN`, and requires a `withdraw_reason`."

        Design: Corner/rbac/segregation_of_duties_splits_allow_and_withdraw_between_the_two_roads
        """
        world, movement, claim = _detention_claim(api)

        withdrawn = validate_success(api.withdraw_reclaim_claim(
            claim["id"], {"withdraw_reason": "Filed against the wrong window"},
            world.accountant(world.bn)))
        assert withdrawn["status"] == "WITHDRAWN"
        assert_money(withdrawn["credit_cents"], 0, "credit_cents")

        unchanged = read_movement(api, world, movement["id"])
        assert_money(unchanged["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(unchanged["net_hire_cents"], 11464, "net_hire_cents")

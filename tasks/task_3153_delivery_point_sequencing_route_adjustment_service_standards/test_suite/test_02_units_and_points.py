"""Delivery units, the delivery point file, and occupancy tracking."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_facility,
    create_point,
    create_point_payload,
    create_unit,
    create_unit_payload,
    get_point,
    get_success_data,
    reset_clock,
    set_clock,
    setup_route_with_active_points,
    setup_unit_with_route,
    validate_error,
    validate_paginated,
    validate_success,
    activate_point,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SSA = TEST_USERS["standards_admin_headers"]
AMS = TEST_USERS["ams_headers"]
CSR = TEST_USERS["csr_headers"]


class TestDeliveryUnitCreation:

    def test_default_scan_target_and_uso_applied(self, api):
        """PRD §3.3: "optionally a `scan_compliance_target` — the required fraction
        of weekly delivery scans with a valid GPS/stop match, defaulting to 0.98".
        PRD §2.5: "Every `DeliveryUnit` carries the `universal_service_obligation`
        flag, which is always `true`, is set by the system at unit creation, and is
        immutable thereafter."

        Design: Corner/entities/delivery_unit_default_scan_target_applied
        """
        reset_clock()
        fac = create_facility()
        data = get_success_data(api.create_unit(
            create_unit_payload(fac["id"], unit_code="DU9",
                                office_name="Ninth Station"), ADMIN))
        assert data["scan_compliance_target"] == 0.98
        assert data["universal_service_obligation"] is True
        assert data["active_route_count"] == 0

    def test_case_slot_count_below_floor_rejected(self, api):
        """PRD §3.3: "a `case_slot_count_per_route` between 4 and 1000 describing
        the physical letter and flat case slots available per route".
        PRD §2.9: "then numeric ranges (`ERR_RANGE_VIOLATION`)".

        Design: Corner/entities/route_case_slot_range_enforced_at_unit_level
        """
        reset_clock()
        fac = create_facility()
        resp = api.create_unit(
            create_unit_payload(fac["id"], unit_code="DU12",
                                office_name="Tiny Station",
                                case_slot_count_per_route=3), ADMIN)
        validate_error(resp, ApiErrorId.ERR_RANGE_VIOLATION)
        rows, meta = validate_paginated(api.list_units(ADMIN, params={"limit": 100}))
        assert meta["total_count"] == 0


class TestDeliveryPointCreation:

    def test_computed_fields_ignore_client_input(self, api):
        """PRD §3.4: "New construction enters as `occupancy_status`
        `UNDER_CONSTRUCTION` with `active_route_id` null and `vacancy_days` zero".
        PRD §3.4: "it is false for `UNDER_CONSTRUCTION`".

        Design: Corner/entities/delivery_point_computed_fields_ignore_client_input
        """
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], code="DU10")
        resp = api.create_point(unit["id"],
                                create_point_payload("90230010999",
                                                     point_kind="BUSINESS"), AMS)
        data = validate_success(resp, expected_status=201)
        assert data["occupancy_status"] == "UNDER_CONSTRUCTION"
        assert data["vacancy_days"] == 0
        assert data["is_deliverable"] is False
        assert data["active_route_id"] is None

    def test_invalid_zip11_format_returns_invalid_request(self, api):
        """PRD §3.4: "an eleven-digit `zip11` delivery-point barcode key that is
        unique system-wide".
        PRD §2.9: "then request well-formedness (`ERR_INVALID_REQUEST`, 400)".

        Design: Corner/entities/delivery_point_invalid_zip11_format_returns_invalid_request
        """
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], code="DU11")
        resp = api.create_point(unit["id"],
                                create_point_payload("90230"), AMS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api.list_points(unit["id"], AMS, params={"limit": 100}))
        assert meta["total_count"] == 0

    def test_points_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/points_list_paginates_with_total_count_and_has_more
        """
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], code="DU14")
        for zip11 in ("90230010881", "90230010882", "90230010883"):
            create_point(unit["id"], zip11=zip11)
        rows, meta = validate_paginated(
            api.list_points(unit["id"], AMS, params={"limit": 2, "offset": 0}))
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        rows2, meta2 = validate_paginated(
            api.list_points(unit["id"], AMS, params={"limit": 2, "offset": 2}))
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        rows3, meta3 = validate_paginated(api.list_points(unit["id"], AMS))
        assert len(rows3) == 3

    def test_get_point_unknown_id_and_wrong_parent_are_not_found(self, api):
        """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not exist or does not belong
        to its declared parent".

        Design: Corner/entities/get_point_with_unknown_id_returns_not_found
        """
        reset_clock()
        fac = create_facility()
        unit_a = create_unit(fac["id"], code="DU15A")
        unit_b = create_unit(fac["id"], code="DU15B")
        point = create_point(unit_a["id"], zip11="90230010777")
        resp1 = api.get_point(unit_a["id"], NON_EXISTENT_UUID, AMS)
        validate_error(resp1, ApiErrorId.ERR_NOT_FOUND)
        resp2 = api.get_point(unit_b["id"], point["id"], AMS)
        validate_error(resp2, ApiErrorId.ERR_NOT_FOUND)

    def test_child_creation_requires_parent_existence(self, api):
        """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not exist or does not belong
        to its declared parent, before any later segment or business rule is
        examined."

        Design: Corner/entities/child_creation_requires_parent_existence
        """
        reset_clock()
        resp = api.create_point(NON_EXISTENT_UUID,
                                create_point_payload("90230010666"), AMS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPointOccupancyStates:

    def test_initial_state_is_under_construction(self, api):
        """PRD §3.4: "New construction enters as `occupancy_status`
        `UNDER_CONSTRUCTION` with `active_route_id` null and `vacancy_days` zero".

        Design: Corner/state_machines/point_initial_state_is_under_construction
        """
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], code="DU16")
        data = get_success_data(api.create_point(
            unit["id"], create_point_payload("90230010551"), AMS))
        assert data["occupancy_status"] == "UNDER_CONSTRUCTION"
        assert data["vacant_since_date"] is None
        assert data["vacancy_days"] == 0
        assert data["active_route_id"] is None
        assert data["version"] == 1

    def test_mark_vacant_from_under_construction_rejected(self, api):
        """PRD §3.4: "A `Carrier` who finds an address empty marks it `OCCUPIED →
        VACANT`" — the transition's source state is OCCUPIED.
        PRD §2.9: "then state preconditions on the target (`ERR_INVALID_STATE`,
        409 — with the terminal-state refinement below)".

        Design: Corner/state_machines/mark_vacant_from_under_construction_rejected
        """
        from test_helpers import create_carrier, make_carrier_headers
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], code="DU17")
        point = create_point(unit["id"], zip11="90230010552")
        car = create_carrier(unit["id"])
        resp = api.mark_vacant(unit["id"], point["id"], make_carrier_headers(car["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        point_after = get_point(unit["id"], point["id"])
        assert point_after["occupancy_status"] == "UNDER_CONSTRUCTION"

    def test_activate_appends_sequence_entry_and_counts(self, api):
        """PRD §3.4: "the point's `active_route_id` is set, the target route's
        `active_delivery_point_count` increases by one, and a sequence entry is
        appended to that route at the next line-of-travel position with its case
        slots recomputed."

        Design: Corner/state_machines/activate_side_effects_append_sequence_entry
        """
        from test_helpers import list_sequence_entries
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id = ctx["unit"]["id"]
        route_id = ctx["route"]["id"]
        p2 = create_point(unit_id)
        data = get_success_data(api.activate_point(
            unit_id, p2["id"], {"route_id": route_id}, AMS))
        assert data["occupancy_status"] == "OCCUPIED"
        assert data["active_route_id"] == route_id
        from test_helpers import get_route
        route = get_route(unit_id, route_id)
        assert route["active_delivery_point_count"] == 2
        entries = list_sequence_entries(unit_id, route_id)
        assert [e["line_of_travel_order"] for e in entries] == [1, 2]
        assert entries[1]["delivery_point_id"] == p2["id"]

    def test_discontinued_point_is_terminal(self, api):
        """PRD §3.4: "Discontinuation moves a point `VACANT → DISCONTINUED` and is
        the file's only terminal transition."
        PRD §2.9: "when the target of a state-transition endpoint is already in a
        terminal state, the rejection is `ERR_ALREADY_TERMINAL` (HTTP 409) rather
        than the generic `ERR_INVALID_STATE`."

        Design: Corner/state_machines/discontinued_point_is_terminal
        """
        from test_helpers import create_carrier, make_carrier_headers
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id = ctx["unit"]["id"]
        route_id = ctx["route"]["id"]
        point = ctx["points"][0]
        get_success_data(api.mark_vacant(
            unit_id, point["id"],
            make_carrier_headers(ctx["carrier"]["id"])))
        set_clock("2026-11-30T00:00:00Z")
        get_success_data(api.discontinue_point(unit_id, point["id"], AMS))
        resp = api.mark_occupied(unit_id, point["id"], AMS)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        point_after = get_point(unit_id, point["id"])
        assert point_after["occupancy_status"] == "DISCONTINUED"


class TestVacancyBoundary:

    def test_vacancy_89_days_keeps_deliverable_and_blocks_discontinue(self, api):
        """PRD §3.4: "It requires `vacancy_days` of at least 90 — a streak of 89
        days is rejected with `ERR_OVERRUN_BELOW_THRESHOLD` (HTTP 422)".
        PRD §3.4: "also while `VACANT` with `vacancy_days` strictly below 90".

        Design: Difficulty/boundary_precision_check/vacancy_89_vs_90_days_discontinue_and_deliverability
        """
        from test_helpers import make_carrier_headers
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id = ctx["unit"]["id"]
        point = ctx["points"][0]
        get_success_data(api.mark_vacant(
            unit_id, point["id"], make_carrier_headers(ctx["carrier"]["id"])))
        set_clock("2026-11-29T00:00:00Z")
        snap = get_point(unit_id, point["id"])
        assert snap["vacancy_days"] == 89
        assert snap["is_deliverable"] is True
        resp = api.discontinue_point(unit_id, point["id"], AMS)
        validate_error(resp, ApiErrorId.ERR_OVERRUN_BELOW_THRESHOLD)

    def test_vacancy_90_days_flips_deliverable_and_permits_discontinue(self, api):
        """PRD §3.4: "The same 90-day boundary appears twice with opposite
        inclusivity: reaching exactly 90 days makes `is_deliverable` false, and
        reaching exactly 90 days qualifies the point for discontinuation."

        Design: Difficulty/boundary_precision_check/vacancy_89_vs_90_days_discontinue_and_deliverability
        """
        from test_helpers import make_carrier_headers
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id = ctx["unit"]["id"]
        point = ctx["points"][0]
        get_success_data(api.mark_vacant(
            unit_id, point["id"], make_carrier_headers(ctx["carrier"]["id"])))
        set_clock("2026-11-30T00:00:00Z")
        snap = get_point(unit_id, point["id"])
        assert snap["vacancy_days"] == 90
        assert snap["is_deliverable"] is False
        data = get_success_data(api.discontinue_point(unit_id, point["id"], AMS))
        assert data["occupancy_status"] == "DISCONTINUED"

"""Aircraft posture derivation, maintenance windows, grounding cascades, retire."""
from test_helpers import (
    ApiErrorId,
    assign_aircraft,
    create_aircraft,
    create_document,
    create_maintenance_window,
    get_success_data,
    make_dispatcher_headers,
    reset_clock,
    setup_approved_trip,
    validate_error,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
PLANNER = TEST_USERS["planner_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestPostureDerivation:
    def test_posture_maintenance_hold_then_available_after_cancel(self, api):
        """PRD §2.7: "The posture is `MAINTENANCE_HOLD` when the aircraft is
        `GROUNDED`, when any of its maintenance windows is `IN_PROGRESS`, or when
        any `PLANNED` maintenance window's half-open interval — start inclusive,
        end exclusive — contains the current logical clock."
        PRD §2.7: "Otherwise the posture is `AVAILABLE`."
        PRD §3.8: "a planned window can also be cancelled outright. Every one of
        these mutations recomputes the parent aircraft's posture per §2.7."

        Design: Difficulty/non_linear_state_machine/aircraft_posture_compound_from_children
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N701CF")
        assert aircraft["posture"] == "AVAILABLE"
        window = create_maintenance_window(
            aircraft["id"], "2026-07-31T00:00:00Z", "2026-08-05T00:00:00Z")
        # Clock 2026-08-01 sits inside the PLANNED window (and auto-starts it).
        posture_1 = get_success_data(api.get_aircraft(aircraft["id"], DISPATCHER))["posture"]
        assert posture_1 == "MAINTENANCE_HOLD", (
            "window covering the clock forces MAINTENANCE_HOLD on an ACTIVE tail"
        )
        get_success_data(api.cancel_maintenance_window(window["id"], PLANNER))
        posture_2 = get_success_data(api.get_aircraft(aircraft["id"], DISPATCHER))["posture"]
        assert posture_2 == "AVAILABLE", "cancelling the window restores AVAILABLE"

    def test_posture_document_lapse_on_expired_airworthiness(self, api):
        """PRD §2.7: "Otherwise, the posture is `DOCUMENT_LAPSE` when any attached
        `DocumentPermit` whose `doc_kind` is `AIRWORTHINESS_CERT`, `REGISTRATION`,
        or `INSURANCE` has an `expires_at` equal to or earlier than the current
        logical clock."
        PRD §3.1: "Attaching a document recomputes the parent aircraft's posture
        immediately."

        Design: Difficulty/non_linear_state_machine/aircraft_posture_compound_from_children
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N701CF")
        create_document(aircraft["id"], doc_kind="AIRWORTHINESS_CERT",
                        identifier="AW-1", issued_at="2020-01-01T00:00:00Z",
                        expires_at="2026-07-01T00:00:00Z")
        posture = get_success_data(api.get_aircraft(aircraft["id"], DISPATCHER))["posture"]
        assert posture == "DOCUMENT_LAPSE", (
            "AIRWORTHINESS_CERT expired before the 2026-08-01 clock forces DOCUMENT_LAPSE"
        )


class TestPostureReconciliation:
    def test_posture_recomputed_after_window_cancel(self, api):
        """PRD §2.7: "Posture is recomputed on every mutation of the aircraft's
        maintenance-window or document children, whenever the logical clock
        advances, and on every read of the aircraft."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_posture_after_maintenance_window_cancel
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N9001CF")
        window = create_maintenance_window(
            aircraft["id"], "2026-07-31T00:00:00Z", "2026-08-05T00:00:00Z")
        posture_hold = get_success_data(
            api.get_aircraft(aircraft["id"], DISPATCHER))["posture"]
        assert posture_hold == "MAINTENANCE_HOLD"
        get_success_data(api.cancel_maintenance_window(window["id"], PLANNER))
        posture_avail = get_success_data(
            api.get_aircraft(aircraft["id"], DISPATCHER))["posture"]
        assert posture_avail == "AVAILABLE"


class TestGroundCascade:
    def test_ground_reverts_assigned_leg_to_planned(self, api):
        """PRD §3.8: "The cascade reaches the schedule: every flight leg holding
        that tail in `AIRCRAFT_ASSIGNED` or `CREWED` whose scheduled window
        intersects an open maintenance window is dropped back to `PLANNED` with
        its `aircraft_id` cleared, freeing the trip for a fresh assignment pass."

        Design: Difficulty/transitive_cascade/ground_aircraft_cascades_leg_back_to_planned
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N702CF")
        _bu, _pax, trip, legs = setup_approved_trip()
        assign_aircraft(trip["id"])
        leg = get_success_data(api.get_flight_leg(legs[0]["id"], DISPATCHER))
        assert leg["status"] == "AIRCRAFT_ASSIGNED"
        assert leg["aircraft_id"] == aircraft["id"]
        get_success_data(api.ground_aircraft(aircraft["id"], PLANNER))
        leg = get_success_data(api.get_flight_leg(legs[0]["id"], DISPATCHER))
        assert leg["status"] == "PLANNED", "ground cascade reverts the assignment"
        assert leg["aircraft_id"] is None, "aircraft_id is cleared"

    def test_ground_forces_maintenance_hold_posture(self, api):
        """PRD §3.8: "A `MaintenancePlanner` may ground an `ACTIVE` aircraft,
        moving it to `GROUNDED` and forcing its posture to `MAINTENANCE_HOLD`."

        Design: Difficulty/transitive_cascade/ground_aircraft_cascades_leg_back_to_planned
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N702CF")
        resp = api.ground_aircraft(aircraft["id"], PLANNER)
        grounded = get_success_data(resp)
        assert grounded["status"] == "GROUNDED"
        assert grounded["posture"] == "MAINTENANCE_HOLD"


class TestRetire:
    def test_retire_with_active_leg_rejected(self, api):
        """PRD §3.8: "A `FlightDeptManager` may retire an aircraft from `ACTIVE`
        or `GROUNDED`, but only while no flight leg holds the tail in
        `AIRCRAFT_ASSIGNED`, `CREWED`, or `RELEASED`"

        Design: Corner/state_machines/aircraft_retire_with_active_legs_rejected
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N3006CF")
        _bu, _pax, trip, _legs = setup_approved_trip()
        assign_aircraft(trip["id"])
        resp = api.retire_aircraft(aircraft["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestImmediateConsistency:
    def test_ground_visible_on_next_read(self, api):
        """PRD §3.8: "A `MaintenancePlanner` may ground an `ACTIVE` aircraft,
        moving it to `GROUNDED` and forcing its posture to `MAINTENANCE_HOLD`."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N9101CF")
        get_success_data(api.ground_aircraft(aircraft["id"], PLANNER))
        fetched = get_success_data(api.get_aircraft(aircraft["id"], DISPATCHER))
        assert fetched["status"] == "GROUNDED", "same-flow read returns the new state"


class TestMaintenanceConflictAtAssign:
    def test_assign_overlapping_maintenance_window_rejected(self, api):
        """PRD §3.3: "and any `PLANNED` or `IN_PROGRESS` maintenance window on the
        candidate tail whose half-open interval intersects the leg's own scheduled
        interval — departure inclusive through arrival exclusive — is rejected
        with `ERR_MAINTENANCE_CONFLICT` (HTTP 422)."

        Design: Corner/errors/error_maintenance_conflict_assign_aircraft_overlapping_window
        """
        reset_clock()
        aircraft = create_aircraft(tail_number="N7002CF")
        # Window 11:00-13:00 intersects the leg's 12:00-14:00 interval, but does
        # NOT cover the 2026-08-01 clock, so the tail stays AVAILABLE.
        create_maintenance_window(aircraft["id"], "2026-08-10T11:00:00Z",
                                  "2026-08-10T13:00:00Z")
        _bu, _pax, trip, _legs = setup_approved_trip()
        version = get_success_data(api.get_trip_request(trip["id"], MANAGER))["version"]
        resp = api.assign_aircraft(trip["id"], version, make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_MAINTENANCE_CONFLICT)

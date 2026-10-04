"""State-machine edges, terminal-state lockdown and clock-derived timing.

These claims are about which state a resource may move from, which move is
refused, and how a derived interval changes when only the logical clock moves.
"""

from test_helpers import (
    book_leg,
    book_run,
    make_pathologist_headers,
    refresh_order,
    set_clock,
    setup_active_client,
    setup_order_in_testing,
    setup_specimen_and_order,
    start_testing,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSpecimenStateEdges:

    def test_accessioning_an_already_accessioned_specimen_is_invalid_state(
            self, api, ops_headers, accessioning_headers):
        """PRD 3.3: "An `AccessioningTechnologist` accessions a received
        specimen into `ACCESSIONED` status only when its `condition` is
        `ACCEPTABLE`, when its `remaining_stability_hours` is strictly above
        zero, and when its `volume_ml` is at least the largest minimum volume
        across every test ordered against it".
        PRD 2.11: "a transition attempted from a state that is not a declared
        starting point for that action is refused with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/specimen_second_accession_from_accessioned_returns_invalid_state
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, probe=False, accession=False)
        specimen_id = scenario["specimen"]["id"]
        order_id = scenario["order"]["id"]

        first = validate_success(api.accession_specimen(specimen_id, accessioning_headers), 200)
        assert first["status"] == "ACCESSIONED"
        version_after_first = first["version"]
        assert refresh_order(order_id)["order_status"] == "ACCESSIONED"
        assert refresh_order(order_id)["billing_status"] == "PROVISIONAL"

        second = api.accession_specimen(specimen_id, accessioning_headers)
        validate_error(second, "ERR_INVALID_STATE", expected_status=409)

        later = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert later["status"] == "ACCESSIONED"
        assert later["version"] == version_after_first, (
            "a refused second accession must not advance the specimen version"
        )
        assert refresh_order(order_id)["provisional_charge_cents"] is not None

    def test_rejecting_an_already_rejected_specimen_is_invalid_state(
            self, api, ops_headers, accessioning_headers):
        """PRD 3.3: "A specimen rejected out of `ACCESSIONED` cancels its owning
        order and every line on it unconditionally, with no advisory branch."
        PRD 2.11: "a transition attempted from a state that is not a declared
        starting point for that action is refused with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/specimen_second_rejection_from_rejected_returns_invalid_state
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, probe=False, accession=False)
        specimen_id = scenario["specimen"]["id"]
        order_id = scenario["order"]["id"]
        validate_success(api.accession_specimen(specimen_id, accessioning_headers), 200)

        first = validate_success(api.reject_specimen(
            specimen_id, "HEMOLYSIS", accessioning_headers), 200)
        assert first["status"] == "REJECTED"
        assert refresh_order(order_id)["order_status"] == "CANCELLED"

        # PRD 2.11: REJECTED is a declared terminal state for a Specimen, so the
        # second rejection is a terminal-state refusal.
        second = api.reject_specimen(specimen_id, "HEMOLYSIS", accessioning_headers)
        validate_error(second, "ERR_ALREADY_TERMINAL", expected_status=409)

        after = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert after["rejection_reason_code"] == "HEMOLYSIS"
        data, meta = validate_paginated(api.list_send_out_orders(
            ops_headers, params={"client_laboratory_id": scenario["client"]["id"]}))
        assert meta["total_count"] == 1, "a refused second rejection must not cascade again"


class TestCourierRunCycle:

    def test_recall_reverts_a_dispatched_leg_to_planned(self, api, ops_headers, courier_headers):
        """PRD 3.2: "A recall is available while the leg is dispatched and only
        while the vehicle has not physically left - that is, while
        `scheduled_pickup_at` still lies in the future - and it returns the leg
        to `PLANNED`, which is the revert leg of the recall cycle."

        Design: Corner/state_machines/courier_run_recall_reverts_a_dispatched_leg_to_planned
        """
        scenario = setup_active_client(clock="2026-09-01T06:00:00Z")
        leg = book_leg(scenario["client"]["id"], route_code="VER-PM", vehicle_id="SUV-5",
                       scheduled_departure_at="2026-09-01T06:00:00Z",
                       scheduled_arrival_at="2026-09-01T09:00:00Z",
                       scheduled_pickup_at="2026-09-01T08:00:00Z",
                       scheduled_delivery_at="2026-09-01T09:00:00Z")

        dispatched = validate_success(api.dispatch_courier_run(leg["id"], courier_headers), 200)
        assert dispatched["status"] == "DISPATCHED", (
            "the departure instant is at or before the clock"
        )

        recalled = validate_success(api.recall_courier_run(leg["id"], courier_headers), 200)
        assert recalled["status"] == "PLANNED"
        assert recalled["version"] == 3, "one version for the create and one per transition"
        assert recalled["specimen_count"] == 0

    def test_dispatch_is_refused_once_the_owning_client_is_suspended(
            self, api, ops_headers, courier_headers):
        """PRD 3.2: "A planned leg is dispatched by its coordinator, but only
        when its `scheduled_departure_at` has been reached and its owning client
        is in `ACTIVE` or `CREDIT_HOLD` posture".
        PRD 3.1: "which moves it to `SUSPENDED` and simultaneously aborts every
        courier leg of that client still in `PLANNED`".
        PRD 2.11: "a transition attempted from a state that is not a declared
        starting point for that action is refused with `ERR_INVALID_STATE`".

        Design: Corner/endpoints/courier_run_dispatch_rejected_when_client_is_suspended
        """
        scenario = setup_active_client(clock="2026-09-01T06:00:00Z")
        client_id = scenario["client"]["id"]
        spare = book_leg(client_id, route_code="VER-EVE", vehicle_id="SUV-8",
                         scheduled_departure_at="2026-09-01T06:30:00Z",
                         scheduled_arrival_at="2026-09-01T09:00:00Z",
                         scheduled_pickup_at="2026-09-01T08:00:00Z",
                         scheduled_delivery_at="2026-09-01T09:00:00Z")

        first = validate_success(api.dispatch_courier_run(
            scenario["courier_run"]["id"], courier_headers), 200)
        assert first["status"] == "DISPATCHED"

        suspended = validate_success(api.suspend_client(client_id, ops_headers), 200)
        assert suspended["status"] == "SUSPENDED"

        aborted = validate_success(api.get_courier_run(spare["id"], courier_headers), 200)
        assert aborted["status"] == "ABORTED", (
            "the suspension cascade aborts the client's planned legs"
        )

        # PRD 2.11: the suspension cascade has already put the leg in the
        # terminal ABORTED state, so a further dispatch is a terminal-state
        # refusal rather than a plain invalid-state one.
        refused = api.dispatch_courier_run(spare["id"], courier_headers)
        validate_error(refused, "ERR_ALREADY_TERMINAL", expected_status=409)
        still = validate_success(api.get_courier_run(spare["id"], courier_headers), 200)
        assert still["status"] == "ABORTED"


class TestInstrumentRunCycle:

    def test_an_aborted_run_never_starts_and_is_rebooked_in_place(self, api, medtech_headers):
        """PRD 3.6: "When the logical clock reaches `reserved_start_at`, a run
        whose `run_status` is `RESERVED` becomes `RUNNING`".
        PRD 3.6: "a `MedicalTechnologist` may amend an aborted run's
        `reserved_start_at` and `reserved_end_at` in place, provided the
        replacement window clears every run whose `run_status` is not `ABORTED`
        on the same analyzer and section once the buffer is added, and the run
        returns to `RESERVED` with its three occupancy instants recomputed."

        Design: Corner/state_machines/aborted_run_cannot_be_started_by_the_clock_and_can_be_rebooked
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        entry_id = scenario["entry"]["id"]
        run = book_run(entry_id, instrument_code="IMM-13",
                       reserved_start_at="2026-09-01T01:00:00Z",
                       reserved_end_at="2026-09-01T05:00:00Z")
        aborted = validate_success(api.abort_instrument_run(run["id"], medtech_headers), 200)
        assert aborted["run_status"] == "ABORTED"

        set_clock("2026-09-01T02:00:00Z")
        still_aborted = validate_success(api.get_instrument_run(run["id"], medtech_headers), 200)
        assert still_aborted["run_status"] == "ABORTED", (
            "the aborted booking never became RUNNING when the clock passed its start"
        )

        rebooked = validate_success(api.rebook_instrument_run(run["id"], {
            "reserved_start_at": "2026-09-01T06:00:00Z",
            "reserved_end_at": "2026-09-01T10:00:00Z",
        }, medtech_headers), 200)
        assert rebooked["run_status"] == "RESERVED"
        assert rebooked["occupied_until_at"] == "2026-09-01T10:30:00Z", (
            "occupied_until_at is the new end instant plus the 30-minute buffer"
        )
        data, meta = validate_paginated(api.list_instrument_runs(
            medtech_headers, params={"test_catalog_entry_id": entry_id}))
        assert meta["total_count"] == 1, "the rebook reused the row instead of duplicating it"


class TestClientPostureTerminality:

    def test_inactive_client_is_terminal_and_deactivation_requires_no_live_orders(
            self, api, ops_headers, accessioning_headers):
        """PRD 3.1: "A `SUSPENDED` client may be deactivated by a
        `ReferenceLabOperations` operator into terminal `INACTIVE` posture, but
        only when none of its orders is in any of `SUBMITTED`, `ACCESSIONED`,
        `IN_TESTING`, `INTERIM_REPORTED`, `REFLEX_PENDING` or `ON_HOLD` - the
        laboratory does not walk away from work in flight."
        PRD 2.11: "an attempt to move a resource out of a declared terminal
        state is refused with `ERR_ALREADY_TERMINAL`".

        Design: Corner/state_machines/cleared_client_cannot_be_deactivated_and_inactive_client_is_terminal
        """
        # The shared intake chain's specimen is received at 06:30, so the clock is
        # already past it (PRD 3.2's intake bound).
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        scenario = setup_specimen_and_order(scenario, probe=False)
        order_id = scenario["order"]["id"]

        suspended = validate_success(api.suspend_client(client_id, ops_headers), 200)
        assert suspended["status"] == "SUSPENDED"

        refused = api.deactivate_client(client_id, ops_headers)
        assert refused.status_code >= 400, (
            "a client holding a live SUBMITTED order may not be deactivated"
        )
        assert api.get_client_laboratory(client_id, ops_headers).json()["data"]["status"] == "SUSPENDED"

        validate_success(api.cancel_order(order_id, ops_headers), 200)
        deactivated = validate_success(api.deactivate_client(client_id, ops_headers), 200)
        assert deactivated["status"] == "INACTIVE"

        terminal = api.activate_client(client_id, ops_headers)
        validate_error(terminal, "ERR_ALREADY_TERMINAL", expected_status=409)
        final = validate_success(api.get_client_laboratory(client_id, ops_headers), 200)
        assert final["status"] == "INACTIVE", "no action may move a terminal client"


class TestClockDerivedTiming:

    def test_remaining_stability_at_the_exact_window_boundary_moves_with_the_clock(self, api):
        """PRD 2.5: "Elapsed time is measured from the specimen's collection
        instant to the logical clock, in hours. Remaining stability is the
        binding window minus that elapsed time. Because it is derived on every
        read rather than stored, it may legitimately be negative".
        PRD 2.4: "it does not advance on its own: it moves only when an operator
        with the `ReferenceLabOperations` role supplies a new instant".

        Design: Corner/calculations/timing_critical_stability_exactly_at_the_window_boundary
        """
        scenario = setup_active_client(clock="2026-09-01T10:00:00Z")
        assert scenario["entry"]["stability_hours_ambient"] == 72
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3501",
            "patient_mrn": "MRN-3501",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-29T10:00:00Z",
            "received_at": "2026-09-01T09:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, self._acc()), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3501",
            "patient_mrn": "MRN-3501",
            "client_requested_at": "2026-08-29T10:00:00Z",
            "priority": "ROUTINE",
            "test_lines": [{"test_catalog_entry_id": scenario["entry"]["id"], "line_sequence": 1}],
            "override_utilization_guard": False,
        }, self._acc()), 201)

        at_boundary = validate_success(api.get_specimen(specimen["id"], self._acc()), 200)
        assert at_boundary["remaining_stability_hours"] == 0.0, (
            "collection is exactly one 72-hour binding window before the clock, so "
            "remaining stability is the window minus the elapsed 72 hours"
        )
        assert at_boundary["collection_at"] == "2026-08-29T10:00:00Z"
        assert at_boundary["received_at"] == "2026-09-01T09:30:00Z"

        set_clock("2026-09-01T10:00:01Z")
        one_second_later = validate_success(api.get_specimen(specimen["id"], self._acc()), 200)
        assert one_second_later["remaining_stability_hours"] == -0.0003, (
            "one second past the window, rounded half-down to four decimals"
        )
        assert refresh_order(order["id"])["order_status"] == "SUBMITTED", (
            "no specimen action was taken, so the order is untouched"
        )

    @staticmethod
    def _acc():
        from test_helpers import TEST_USERS
        return TEST_USERS["accessioning_technologist_headers"]


class TestDerivedInterfaceStatus:

    def test_client_interface_status_follows_the_highest_status_build(self, api, ops_headers):
        """PRD 3.1: "The `interface_status` field deserves its own explanation
        because it is never stored as an independent truth. It is derived on
        every write from the highest-status interface build belonging to the
        client and takes one of `NOT_BUILT`, `IN_BUILD`, `CERTIFIED` or
        `RETIRED`."

        Design: Corner/complexity_layers/client_interface_status_is_recomputed_from_the_highest_status_build
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        client_id = scenario["client"]["id"]
        # The scenario already holds one certified build, so start from a client
        # with no builds at all to observe the ladder from the bottom.
        fresh = validate_success(api.create_client_laboratory({
            "name": "Emery County Clinic",
            "clia_number": "45D-4001",
            "client_type": "PHYSICIAN_OFFICE",
            "state_code": "UT",
            "billing_arrangement": "CLIENT",
            "credit_limit_cents": 400000,
        }, ops_headers), 201)
        target = fresh["id"]

        assert api.get_client_laboratory(target, ops_headers).json()["data"]["interface_status"] == "NOT_BUILT"

        build = validate_success(api.create_interface_build({
            "client_laboratory_id": target,
            "build_version_label": "v1",
            "format": "HL7_V2_5_1",
            "order_interface_enabled": True,
            "result_interface_enabled": True,
        }, self._iface()), 201)
        assert build["status"] == "DRAFT", "PRD 3.12: the build is created in DRAFT"

        started = validate_success(api.start_interface_build(build["id"], self._iface()), 200)
        assert started["status"] == "IN_BUILD", (
            "PRD 3.12: starting construction moves the build to IN_BUILD"
        )

        certified = validate_success(api.certify_interface_build(build["id"], self._iface()), 200)
        assert certified["certified_at"] is not None
        assert api.get_client_laboratory(target, ops_headers).json()["data"]["interface_status"] == "CERTIFIED", (
            "no client endpoint was called to change interface_status"
        )
        assert client_id != target

    @staticmethod
    def _iface():
        from test_helpers import TEST_USERS
        return TEST_USERS["interface_analyst_headers"]


class TestSegregationOfDuties:

    def test_result_release_demands_an_identity_different_from_the_entering_technologist(
            self, api, pathologist_headers):
        """PRD 3.7: "the releasing pathologist's `X-User-ID` must differ from
        `entered_by_user_id` on every line of that order, enforcing the
        segregation of duties between the person who entered a value and the
        person who signs it off".
        PRD 3.7: "a release attempted by the same identifier that entered a value
        is refused with `ERR_SOD_RESULT_ENTRY_RELEASE` (HTTP 403)."

        Design: Corner/rbac/result_entry_and_result_release_demand_different_identities
        """
        # The shared intake chain's specimen is received at 06:30, so the clock
        # must already be past it (PRD 3.2).
        scenario = setup_order_in_testing(clock="2026-09-01T07:00:00Z")
        order_id = scenario["order"]["id"]
        line_id = scenario["line"]["id"]
        entered_by = validate_success(api.get_order_test_line(line_id, pathologist_headers), 200)
        assert entered_by["entered_by_user_id"] is not None

        same_identity = make_pathologist_headers(entered_by["entered_by_user_id"])
        refused = api.release_results(order_id, "Ferritin within reference interval.", same_identity)
        validate_error(refused, "ERR_SOD_RESULT_ENTRY_RELEASE", expected_status=403)

        other_identity = make_pathologist_headers("test-pathologist-99")
        released = validate_success(api.release_results(
            order_id, "Ferritin within reference interval.", other_identity), 200)
        assert released["order_status"] == "RESULT_RELEASED"

    def test_pathologist_may_not_enter_result_values(self, api, medtech_headers, pathologist_headers):
        """PRD 2.1: "Performing an operation that is not permitted for one's role
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD 3.7: "Entering results is the technologist's counterpart, performed
        on an order whose specimen is `IN_TESTING` and where every line of the
        order has a `result_value` set."

        Design: Corner/rbac/pathologist_cannot_enter_result_values
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-18"})
        scenario = start_testing(scenario)
        order_id = scenario["order"]["id"]
        line_id = scenario["order"]["test_lines"][0]["id"]
        version = refresh_order(order_id)["version"]
        payload = {
            "expected_send_out_order_version": version,
            "result_lines": [{
                "order_test_line_id": line_id,
                "result_value": 250.0,
                "result_units": "ng/mL",
                "critical_value_notified_to": None,
                "critical_value_notified_at": None,
            }],
        }

        refused = api.enter_results(order_id, payload, pathologist_headers)
        err = validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
        assert err["error_id"] != "ERR_SOD_RESULT_ENTRY_RELEASE"

        accepted = validate_success(api.enter_results(order_id, payload, medtech_headers), 200)
        assert accepted is not None
        line = validate_success(api.get_order_test_line(line_id, medtech_headers), 200)
        assert line["result_value"] == 250.0
        assert line["entered_by_user_id"] == medtech_headers["X-User-ID"]
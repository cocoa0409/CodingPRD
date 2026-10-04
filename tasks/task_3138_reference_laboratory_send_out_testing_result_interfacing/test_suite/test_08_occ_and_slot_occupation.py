"""Optimistic concurrency, analyzer slot reuse and the inclusive accession bound.

The three version guards are the only fields in the PRD that carry an
``expected_<parent>_version``, and each sits on a different write endpoint, so
this file observes OCC on strictly sequential calls: the first write succeeds
against the observed version, the parent's version then advances, and replaying
the older version is refused before any business rule runs.
"""
import pytest

from test_helpers import (
    queue_result_message,
    read_client,
    refresh_order,
    register_client,
    setup_active_client,
    setup_released_order,
    setup_specimen_and_order,
    start_testing,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAnalyzerSlotOccupation:

    def test_an_aborted_report_frees_its_slot_and_a_reversed_window_is_refused(
            self, api, medtech_headers):
        """PRD 2.10: "A new booking is refused with `ERR_INSTRUMENT_DOUBLE_BOOKED`
        when it would collide with an existing run that is not aborted, once the
        buffer is applied, or when its own start and end violate the strict
        ordering. Aborted bookings are excluded from the check, which is
        precisely what frees their slots for reuse."
        PRD 3.6: "which moves it to `ABORTED` and takes its window out of the
        buffer-overlap computation entirely, freeing the slot for a fresh booking."

        Design: Difficulty/resource_temporal_overlap/analyzer_buffer_overlap_on_an_exact_boundary
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        entry_id = scenario["entry"]["id"]

        reversed_window = api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-24", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T12:00:00Z",
            "reserved_end_at": "2026-09-01T07:00:00Z",
        }, medtech_headers)
        validate_error(reversed_window, "ERR_INSTRUMENT_DOUBLE_BOOKED", expected_status=409)

        blocking = validate_success(api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-24", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T08:00:00Z",
            "reserved_end_at": "2026-09-01T10:00:00Z",
        }, medtech_headers), 201)
        assert blocking["occupied_until_at"] == "2026-09-01T10:30:00Z"

        inside_buffer = api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-24", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T10:15:00Z",
            "reserved_end_at": "2026-09-01T11:00:00Z",
        }, medtech_headers)
        validate_error(inside_buffer, "ERR_INSTRUMENT_DOUBLE_BOOKED", expected_status=409)

        validate_success(api.abort_instrument_run(blocking["id"], medtech_headers), 200)
        freed = validate_success(api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-24", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T10:15:00Z",
            "reserved_end_at": "2026-09-01T11:00:00Z",
        }, medtech_headers), 201)
        assert freed["run_status"] == "RESERVED", (
            "an aborted booking no longer participates in the overlap rule"
        )

        data, meta = validate_paginated(api.list_instrument_runs(
            medtech_headers, params={"instrument_code": "IMM-24"}))
        assert meta["total_count"] == 2
        assert sorted(run["run_status"] for run in data) == ["ABORTED", "RESERVED"]


class TestInclusiveAccessionStabilityBound:

    def test_a_specimen_collected_exactly_one_window_ago_still_accessions(
            self, api, accessioning_headers):
        """PRD 3.3: "the elapsed time from the specimen's `collection_at` to the
        logical clock must not exceed the binding stability window, and the
        comparison is inclusive, so a specimen whose collection is exactly one
        full binding-window ago is still acceptable while one a moment older is
        refused with `ERR_SPECIMEN_STABILITY_EXCEEDED`."
        PRD 3.3: "An `AccessioningTechnologist` accessions a received specimen
        into `ACCESSIONED` status only when its `condition` is `ACCEPTABLE`, when
        its `remaining_stability_hours` is strictly above zero".

        Design: Difficulty/boundary_precision_check/reflex_stability_bound_is_strict_while_stability_bound_is_inclusive
        """
        scenario = setup_active_client(
            entry_overrides={"stability_hours_ambient": 12, "stability_hours_refrigerated": 24,
                             "reflex_condition": "NONE", "reflex_min_remaining_hours": 12},
            clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        entry_id = scenario["entry"]["id"]

        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-8201", "patient_mrn": "MRN-8301",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-08-31T19:00:00Z",
            "received_at": "2026-08-31T19:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-8201", "patient_mrn": "MRN-8301",
            "client_requested_at": "2026-08-31T19:05:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(entry_id, 1)], "override_utilization_guard": False,
        }, accessioning_headers), 201)

        at_boundary = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert at_boundary["remaining_stability_hours"] == pytest.approx(0.0, abs=0.001), (
            "the elapsed time exactly equals the 12-hour binding window"
        )

        accessioned = validate_success(api.accession_specimen(specimen["id"], accessioning_headers), 200)
        assert accessioned["status"] == "ACCESSIONED", (
            "equality on the stability bound passes, unlike the strict reflex bound"
        )
        assert refresh_order(order["id"])["order_status"] == "ACCESSIONED"

    def test_one_second_past_the_window_is_refused(self, api, accessioning_headers):
        """PRD 3.3: "a specimen whose collection is exactly one full
        binding-window ago is still acceptable while one a moment older is
        refused with `ERR_SPECIMEN_STABILITY_EXCEEDED`."
        PRD 2.5: "Because it is derived on every read rather than stored, it may
        legitimately be negative, and the service must report it that way rather
        than flattening it to zero."

        Design: Difficulty/boundary_precision_check/reflex_stability_bound_is_strict_while_stability_bound_is_inclusive
        """
        scenario = setup_active_client(
            entry_overrides={"stability_hours_ambient": 12, "stability_hours_refrigerated": 24,
                             "reflex_condition": "NONE", "reflex_min_remaining_hours": 12},
            clock="2026-09-01T07:00:00Z")
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-8202", "patient_mrn": "MRN-8302",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-08-31T18:59:59Z",
            "received_at": "2026-08-31T19:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"], "specimen_id": specimen["id"],
            "order_number": "REQ-8202", "patient_mrn": "MRN-8302",
            "client_requested_at": "2026-08-31T19:05:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)

        past_boundary = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert past_boundary["remaining_stability_hours"] < 0, (
            "the derived value is reported as negative rather than flattened to zero"
        )

        refused = api.accession_specimen(specimen["id"], accessioning_headers)
        validate_error(refused, "ERR_SPECIMEN_STABILITY_EXCEEDED", expected_status=422)
        assert refresh_order(order["id"])["order_status"] == "SUBMITTED"


class TestOptimisticConcurrency:

    def test_result_entry_replaying_a_stale_order_version_is_refused(
            self, api, accessioning_headers, medtech_headers):
        """PRD 2.7: "Entering or amending result values on an order requires
        `expected_send_out_order_version`, carrying the technologist's last
        observed `version` of that order."
        PRD 2.7: "When the values differ, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD 2.7: "The check runs before every business rule on the endpoint, so a
        stale request reports the version failure and never the business error it
        would otherwise have produced."

        Design: Corner/complexity_layers/result_entry_against_a_stale_order_version_returns_stale_version
        """
        # The shared intake chain's specimen is received at 06:30 and its order
        # requested at 06:35, so the clock must already be past both (PRD 3.2).
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-20"})
        scenario = start_testing(scenario)
        order_id = scenario["order"]["id"]
        line_id = scenario["order"]["test_lines"][0]["id"]

        observed = refresh_order(order_id)["version"]
        first = validate_success(api.enter_results(order_id, {
            "expected_send_out_order_version": observed,
            "result_lines": [{
                "order_test_line_id": line_id, "result_value": 250.0,
                "result_units": "ng/mL", "critical_value_notified_to": None,
                "critical_value_notified_at": None,
            }],
        }, medtech_headers), 200)
        assert first["version"] > observed, "the successful entry advanced the order's version"

        replay = api.enter_results(order_id, {
            "expected_send_out_order_version": observed,
            "result_lines": [{
                "order_test_line_id": line_id, "result_value": 300.0,
                "result_units": "ng/mL", "critical_value_notified_to": None,
                "critical_value_notified_at": None,
            }],
        }, medtech_headers)
        validate_error(replay, "ERR_STALE_VERSION", expected_status=412)

        line = validate_success(api.get_order_test_line(line_id, medtech_headers), 200)
        assert line["result_value"] == 250.0, "the stale write changed nothing"
        assert refresh_order(order_id)["version"] == first["version"]

    def test_queuing_a_message_replaying_a_stale_order_version_is_refused(
            self, api, interface_headers):
        """PRD 2.7: "Queuing an outbound interface message requires
        `expected_send_out_order_version` as well, carrying the interface
        analyst's last observed `version` of the order the message describes."
        PRD 2.7: "In each case the guard is a non-optional input: the request must
        carry the field, and the value it carries must equal the parent entity's
        current `version`."

        Design: Corner/complexity_layers/interface_message_queue_against_a_stale_order_version_returns_stale_version
        """
        scenario = setup_released_order()
        order_id = scenario["order"]["id"]
        observed = refresh_order(order_id)["version"]

        first = queue_result_message(scenario, "CTL-6001")
        assert first["status"] == "QUEUED"
        advanced = refresh_order(order_id)["version"]
        assert advanced == observed + 1, "the successful queue itself advances the order's version"

        second = api.create_interface_message({
            "send_out_order_id": order_id, "interface_build_id": scenario["build"]["id"],
            "message_type": "RESULT", "control_id": "CTL-6002",
            "expected_send_out_order_version": observed,
        }, interface_headers)
        validate_error(second, "ERR_STALE_VERSION", expected_status=412)

        data, meta = validate_paginated(api.list_interface_messages(
            interface_headers, params={"send_out_order_id": order_id}))
        assert meta["total_count"] == 1, "the stale queue created nothing"

    def test_booking_a_leg_replaying_a_stale_client_version_is_refused(
            self, api, ops_headers, courier_headers):
        """PRD 3.2: "The booking also carries `expected_client_laboratory_version`,
        the coordinator's last observed version of the client; if another writer
        has changed the client's courier configuration or a ledger-driven posture
        cascade has bumped its version since the coordinator read it, the booking
        is refused with `ERR_STALE_VERSION` (HTTP 412) rather than being applied
        against a stale understanding of the client."
        PRD 3.2: "Booking a leg also bumps the owning client's `version`, because
        the client's courier configuration has changed".

        Design: Corner/complexity_layers/courier_run_booking_stale_client_version_is_rejected_and_fresh_succeeds
        """
        client = register_client(name="Uintah Basin Clinic", clia_number="45D-3002",
                                 client_type="PHYSICIAN_OFFICE", billing_arrangement="PATIENT",
                                 credit_limit_cents=400000)
        original = read_client(client["id"])["version"]

        def _leg(route_code, vehicle_id, expected_version, departure):
            return {
                "client_laboratory_id": client["id"], "route_code": route_code,
                "origin_city": "Vernal", "destination_city": "Salt Lake City",
                "vehicle_id": vehicle_id,
                "scheduled_departure_at": departure,
                "scheduled_arrival_at": "2026-09-02T10:00:00Z",
                "scheduled_pickup_at": departure,
                "scheduled_delivery_at": "2026-09-02T10:00:00Z",
                "temperature_control_mode": "AMBIENT",
                "expected_client_laboratory_version": expected_version,
            }

        first = api.create_courier_run(
            _leg("VER-R1", "SUV-51", original, "2026-09-01T22:00:00Z"), courier_headers)
        assert first.status_code == 201, f"fresh version should book: {first.text}"
        assert first.json()["data"]["status"] == "PLANNED"

        refreshed = read_client(client["id"])["version"]
        assert refreshed == original + 1, "the booking bumped the client's version"

        second = api.create_courier_run(
            _leg("VER-R2", "SUV-52", refreshed, "2026-09-02T05:00:00Z"), courier_headers)
        assert second.status_code == 201

        replay = api.create_courier_run(
            _leg("VER-R3", "SUV-53", original, "2026-09-03T05:00:00Z"), courier_headers)
        validate_error(replay, "ERR_STALE_VERSION", expected_status=412)

        assert read_client(client["id"])["version"] == refreshed + 1
        data, meta = validate_paginated(api.list_courier_runs(
            ops_headers, params={"client_laboratory_id": client["id"]}))
        assert meta["total_count"] == 2, "the stale booking persisted nothing"
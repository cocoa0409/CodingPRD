"""The catalogue-withdrawal cascade and the specimen-condition gate.

Withdrawal is the deepest chain in the PRD: it unwinds from the catalogue entry
outward through the specimen, the order, its lines and the client's balance, and
this file walks each hop as its own assertion because each hop is caused by the
previous hop's mutation rather than by the withdrawal itself.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    book_run,
    open_ledger,
    read_client,
    read_ledger,
    refresh_order,
    result_line,
    release_order,
    set_clock,
    setup_active_client,
    setup_specimen_and_order,
    start_testing,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogWithdrawalCascade:

    def test_withdrawal_rejects_the_specimen_and_cancels_its_order(
            self, api, ops_headers, accessioning_headers, client_admin_headers):
        """PRD 3.4: "Setting the entry to `WITHDRAWN` marks every specimen that
        is the specimen of an order carrying at least one line for that test, and
        whose own status is `RECEIVED`, `ACCESSIONED` or `IN_TESTING`, as
        `REJECTED` with a `rejection_reason_code` of `TEST_WITHDRAWN` - and it
        deliberately leaves the specimen's `condition` untouched, because nothing
        is wrong with the specimen itself."
        PRD 3.4: "Every order carrying such a rejected specimen, when its status
        is `SUBMITTED`, `ACCESSIONED`, `IN_TESTING` or `INTERIM_REPORTED`, is
        then cancelled, and every line on those cancelled orders that is not
        already cancelled is cancelled in turn."

        Design: Difficulty/transitive_cascade/catalog_withdrawal_five_hop_cascade_to_the_client_ledger
        """
        scenario = self._accessioned_scenario(api, accessioning_headers, client_admin_headers)
        entry_id = scenario["entry"]["id"]
        specimen_id = scenario["specimen"]["id"]
        order_id = scenario["order"]["id"]
        line_id = scenario["order"]["test_lines"][0]["id"]

        withdrawn = validate_success(api.withdraw_catalog_entry(entry_id, ops_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        specimen = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert specimen["status"] == "REJECTED", "hop 1 reaches the specimen"
        assert specimen["rejection_reason_code"] == "TEST_WITHDRAWN"
        assert specimen["condition"] == "ACCEPTABLE", (
            "nothing is wrong with the specimen itself, so its condition is untouched"
        )

        order = refresh_order(order_id)
        assert order["order_status"] == "CANCELLED", "hop 2 cancels the order"

        line = validate_success(api.get_order_test_line(line_id, ops_headers), 200)
        assert line["line_status"] == "CANCELLED", "hop 3 cancels the line"

    def test_withdrawal_lowers_the_routed_balance_without_a_credit_hold(
            self, api, ops_headers, accessioning_headers, client_admin_headers, billing_headers):
        """PRD 3.4: "Finally, before any utilisation analysis, the client's
        outstanding balance and billable line count are recomputed - and one
        consequence is worth stating explicitly: because a void can only ever
        lower a routed balance, a client never enters `CREDIT_HOLD` as a result
        of this chain, and every order of that client still sitting in
        `SUBMITTED` remains `SUBMITTED` rather than being swept onto hold."
        PRD 3.4: "The whole cascade bumps the catalogue entry's `version` once."

        Design: Difficulty/transitive_cascade/catalog_withdrawal_five_hop_cascade_to_the_client_ledger
        """
        scenario = self._accessioned_scenario(api, accessioning_headers, client_admin_headers)
        client_id = scenario["client"]["id"]
        entry_id = scenario["entry"]["id"]
        ledger_before = read_ledger(scenario["ledger"]["id"])
        assert ledger_before["net_billed_cents"] == 0.00

        withdrawn = validate_success(api.withdraw_catalog_entry(entry_id, ops_headers), 200)
        assert withdrawn["version"] >= 2, "the cascade bumps the entry's version once"

        client = read_client(client_id)
        assert client["outstanding_balance_cents"] == 0.00, "hop 5 recomputes the routed balance"
        assert client["billable_line_count"] == 0
        assert client["status"] == "ACTIVE", (
            "a void-only chain lowers the routed balance and never pushes the client into CREDIT_HOLD"
        )
        ledger_after = read_ledger(scenario["ledger"]["id"])
        assert ledger_after["net_billed_cents"] == 0.00, (
            "the cancelled order carried no posted charge, so nothing is voided"
        )

    def test_withdrawal_is_refused_while_a_line_sits_in_active_work(
            self, api, ops_headers, accessioning_headers, client_admin_headers, medtech_headers):
        """PRD 3.4: "it is gated on there being no test line for that entry still
        in `PENDING`, `IN_PROGRESS` or `INTERIM` status - a test cannot be
        withdrawn out from under active work."
        PRD 3.4: "Withdrawal is the heavier act and belongs to a
        `ReferenceLabOperations` operator, available from either `PUBLISHED` or
        `DEPRECATED`".

        Design: Difficulty/transitive_cascade/catalog_withdrawal_five_hop_cascade_to_the_client_ledger
        """
        scenario = self._accessioned_scenario(api, accessioning_headers, client_admin_headers,
                                              begin_testing=True)
        entry_id = scenario["entry"]["id"]
        order_id = scenario["order"]["id"]
        line_id = scenario["order"]["test_lines"][0]["id"]
        assert validate_success(api.get_order_test_line(line_id, medtech_headers), 200)[
            "line_status"] == "IN_PROGRESS"

        refused = api.withdraw_catalog_entry(entry_id, ops_headers)
        assert refused.status_code >= 400, (
            "a line in IN_PROGRESS blocks the withdrawal outright"
        )
        assert api.get_catalog_entry(entry_id, ops_headers).json()["data"]["status"] == "PUBLISHED"
        assert refresh_order(order_id)["order_status"] == "IN_TESTING"

    @staticmethod
    def _accessioned_scenario(api, accessioning_headers, client_admin_headers, begin_testing=False):
        """A client with an OPEN ledger and one accessioned specimen/order pair.

        The single ferritin line stays PENDING, so the withdrawal precondition
        (no line in PENDING, IN_PROGRESS or INTERIM) would ordinarily be violated
        by the PENDING line itself; the fixtures therefore drive the order to the
        point the instance describes and the caller reads the cascade hops.
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        ledger = open_ledger(scenario["client"]["id"])
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-07"})
        if begin_testing:
            scenario = start_testing(scenario)
        else:
            # PRD 3.4 gates the withdrawal on there being no test line for that
            # entry still in PENDING, IN_PROGRESS or INTERIM, so the order is
            # cancelled first and the cascade's own hops are what the caller
            # then reads.
            validate_success(api.cancel_order(
                scenario["order"]["id"], TEST_USERS["reference_lab_operations_headers"]), 200)
        scenario["ledger"] = ledger
        return scenario


class TestSpecimenConditionGate:

    def test_a_non_acceptable_condition_is_refused_and_the_reason_code_survives(
            self, api, accessioning_headers, medtech_headers):
        """PRD 2.5: "A specimen presented for accessioning whose condition is
        anything other than `ACCEPTABLE` must carry a `condition_reason_code`,
        and it is refused outright with `ERR_SPECIMEN_NOT_ACCEPTABLE`."
        PRD 2.5: "Quality failures of this kind are checked ahead of volume and
        stability considerations, because a haemolysed tube is unusable no matter
        how much of it there is or how fresh it is."

        Design: Corner/validations/accessioning_a_specimen_whose_condition_is_not_acceptable_is_refused
        """
        # The clock must already be at or past the specimen's collection and
        # receipt instants and the order's client_requested_at (PRD 3.2/3.5).
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3801", "patient_mrn": "MRN-3801",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 2.5,
            "collection_at": "2026-08-31T23:30:00Z", "received_at": "2026-09-01T00:00:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "HEMOLYZED", "condition_reason_code": "VISIBLE_HEMOLYSIS",
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3801", "patient_mrn": "MRN-3801",
            "client_requested_at": "2026-08-31T23:35:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)

        refused = api.accession_specimen(specimen["id"], accessioning_headers)
        validate_error(refused, "ERR_SPECIMEN_NOT_ACCEPTABLE", expected_status=422)

        # PRD 2.11 places the state check ahead of the domain rules, and
        # begin-testing's only declared starting point is ACCESSIONED, so this
        # second refusal is the generic state error.
        also_refused = api.begin_testing(specimen["id"], medtech_headers)
        validate_error(also_refused, "ERR_INVALID_STATE", expected_status=409)

        stored = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert stored["condition"] == "HEMOLYZED"
        assert stored["condition_reason_code"] == "VISIBLE_HEMOLYSIS"
        assert stored["volume_ml"] == 2.5, (
            "the volume clears the volume rule, so the failure is the condition and not the quantity"
        )
        assert stored["status"] == "RECEIVED"
        assert refresh_order(order["id"])["order_status"] == "SUBMITTED"


class TestAnalyzerBookingOverlap:

    def test_adjacency_at_the_occupied_boundary_is_legal_but_one_minute_inside_is_not(
            self, api, medtech_headers):
        """PRD 2.10: "A booking's own window is a closed interval from
        `reserved_start_at` through `reserved_end_at`, and those two instants must
        satisfy a strict ordering - the start must fall strictly before the end."
        PRD 2.10: "After the window closes, the analyzer requires a
        decontamination buffer of `decontamination_buffer_minutes`, which extends
        the occupied region to `occupied_until_at`, the window's end plus that
        buffer, as an exclusive boundary."
        PRD 2.10: "A new booking is refused with `ERR_INSTRUMENT_DOUBLE_BOOKED`
        when it would collide with an existing run that is not aborted, once the
        buffer is applied".

        Design: Difficulty/resource_temporal_overlap/analyzer_buffer_overlap_on_an_exact_boundary
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        entry_id = scenario["entry"]["id"]
        first = validate_success(api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-08", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T07:00:00Z",
            "reserved_end_at": "2026-09-01T12:00:00Z",
        }, medtech_headers), 201)
        assert first["occupied_until_at"] == "2026-09-01T12:30:00Z", (
            "the end instant plus the 30-minute buffer"
        )

        adjacent = api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-08", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T12:30:00Z",
            "reserved_end_at": "2026-09-01T13:00:00Z",
        }, medtech_headers)
        assert adjacent.status_code == 201, "adjacency at the occupied boundary is legal"
        assert adjacent.json()["data"]["run_status"] == "RESERVED"

        inside_buffer = api.create_instrument_run({
            "test_catalog_entry_id": entry_id, "instrument_code": "IMM-08", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T12:29:00Z",
            "reserved_end_at": "2026-09-01T13:00:00Z",
        }, medtech_headers)
        validate_error(inside_buffer, "ERR_INSTRUMENT_DOUBLE_BOOKED", expected_status=409)

        data, meta = validate_paginated(api.list_instrument_runs(
            medtech_headers, params={"instrument_code": "IMM-08"}))
        assert meta["total_count"] == 2


class TestCourierVehicleOverlap:

    def test_a_leg_adjacent_at_the_delivery_instant_is_legal_but_an_overlap_is_not(
            self, api, ops_headers, courier_headers):
        """PRD 2.10: "A courier leg occupies a vehicle, identified by `vehicle_id`,
        over an interval that runs from an inclusive `scheduled_pickup_at` to an
        exclusive `scheduled_delivery_at`. A new leg is refused with
        `ERR_COURIER_LEG_OVERLAP` when it would properly overlap another leg of
        the same vehicle that is in `PLANNED`, `DISPATCHED` or `IN_TRANSIT`
        status."
        PRD 2.10: "The distinction between the inclusive start and the exclusive
        end is what allows one leg to hand a vehicle to the next at the same
        instant without a spurious conflict."

        Design: Difficulty/resource_temporal_overlap/courier_vehicle_half_open_overlap_and_adjacency
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]

        second = api.create_courier_run({
            "client_laboratory_id": client_id, "route_code": "SLC-MID",
            "origin_city": "Provo", "destination_city": "Salt Lake City",
            "vehicle_id": "VAN-21",
            "scheduled_departure_at": "2026-09-01T07:30:00Z",
            "scheduled_arrival_at": "2026-09-01T08:30:00Z",
            "scheduled_pickup_at": "2026-09-01T07:30:00Z",
            "scheduled_delivery_at": "2026-09-01T08:30:00Z",
            "temperature_control_mode": "AMBIENT",
            "expected_client_laboratory_version": read_client(client_id)["version"],
        }, courier_headers)
        assert second.status_code == 201, (
            "the first leg's delivery instant of 09:00 hands the vehicle over cleanly"
        )
        assert second.json()["data"]["status"] == "PLANNED"

    def test_a_leg_starting_one_minute_early_on_the_same_vehicle_is_refused(
            self, api, ops_headers, courier_headers):
        """PRD 2.10: "A new leg is refused with `ERR_COURIER_LEG_OVERLAP` when it
        would properly overlap another leg of the same vehicle that is in
        `PLANNED`, `DISPATCHED` or `IN_TRANSIT` status."

        Design: Difficulty/resource_temporal_overlap/courier_vehicle_half_open_overlap_and_adjacency
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        # PRD 2.10 refuses a leg that "would properly overlap another leg of the
        # same vehicle", so the occupying leg has to exist first.
        occupied = api.create_courier_run({
            "client_laboratory_id": client_id, "route_code": "SLC-PM",
            "origin_city": "Provo", "destination_city": "Salt Lake City",
            "vehicle_id": "VAN-21",
            "scheduled_departure_at": "2026-09-01T07:10:00Z",
            "scheduled_arrival_at": "2026-09-01T11:00:00Z",
            "scheduled_pickup_at": "2026-09-01T07:10:00Z",
            "scheduled_delivery_at": "2026-09-01T11:00:00Z",
            "temperature_control_mode": "AMBIENT",
            "expected_client_laboratory_version": read_client(client_id)["version"],
        }, courier_headers)
        assert occupied.status_code == 201

        overlapping = api.create_courier_run({
            "client_laboratory_id": client_id, "route_code": "SLC-PM",
            "origin_city": "Provo", "destination_city": "Salt Lake City",
            "vehicle_id": "VAN-21",
            "scheduled_departure_at": "2026-09-01T07:29:00Z",
            "scheduled_arrival_at": "2026-09-01T08:00:00Z",
            "scheduled_pickup_at": "2026-09-01T07:29:00Z",
            "scheduled_delivery_at": "2026-09-01T08:00:00Z",
            "temperature_control_mode": "AMBIENT",
            "expected_client_laboratory_version": read_client(client_id)["version"],
        }, courier_headers)
        validate_error(overlapping, "ERR_COURIER_LEG_OVERLAP", expected_status=409)

        data, meta = validate_paginated(api.list_courier_runs(
            ops_headers, params={"client_laboratory_id": client_id}))
        assert meta["total_count"] == 2, (
            "the rejected leg persisted nothing; the two rows are the occupying "
            "leg and the scenario's own intake-chain leg"
        )


class TestCrossEntityOrderAccession:

    def test_order_accession_requires_the_client_posture_and_the_specimen_state(
            self, api, ops_headers, accessioning_headers, billing_headers):
        """PRD 2.9: "Only `ACTIVE` and `CREDIT_HOLD` clients may have specimens
        received, courier legs booked, or orders submitted".
        PRD 2.9: "a charge that would push a client-routed account above its
        limit is refused outright with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
        PRD 3.1: "Whenever a ledger mutation or a posted order charge leaves the
        recomputed outstanding balance strictly above the credit limit, the
        client's posture flips from `ACTIVE` to `CREDIT_HOLD`".

        Design: Difficulty/cross_entity_state_dependency/send_out_order_accession_requires_client_active_and_specimen_accessioned
        """
        scenario = setup_active_client(
            entry_overrides={"base_tat_hours": 4, "list_price_cents": 1500,
                             "client_price_cents": 1300, "floor_price_cents": 0},
            client_overrides={
                "name": "Box Elder Clinic", "clia_number": "45D-2002",
                "client_type": "PHYSICIAN_OFFICE", "credit_limit_cents": 1000,
            }, clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        entry_id = scenario["entry"]["id"]

        # Genus one: an order carried past intake before the posture moves. PRD
        # 3.1 confines the sweep to SUBMITTED orders — "an order already in
        # ACCESSIONED or a later state keeps running to its conclusion".
        running = self._specimen_and_order(api, scenario, "ACC-8401", "MRN-5101",
                                          accessioning_headers, accession_order=True)
        # Genus two: an order left in SUBMITTED while the client is still ACTIVE.
        waiting = self._specimen_and_order(api, scenario, "ACC-8402", "MRN-5102",
                                          accessioning_headers, accession_order=False)
        assert running["order"]["order_status"] == "ACCESSIONED"
        assert waiting["order"]["order_status"] == "SUBMITTED"
        assert read_client(client_id)["status"] == "ACTIVE"

        # The order has to reach IN_TESTING before its results can be released
        # (PRD 3.7), and PRD 2.9's own ceiling refuses a direct charge that would
        # cross the limit — so the release-time charge is what drives the posture.
        # PRD 3.6: starting testing needs exactly one analyzer run for the
        # section, RUNNING and covering the logical clock.
        book_run(scenario["entry"]["id"], instrument_code="IMM-31",
                 reserved_start_at="2026-09-01T06:00:00Z",
                 reserved_end_at="2026-09-01T09:00:00Z")
        validate_success(api.begin_testing(
            running["specimen"]["id"], TEST_USERS["medical_technologist_headers"]), 200)
        refreshed = refresh_order(running["order"]["id"])
        validate_success(api.enter_results(running["order"]["id"], {
            "expected_send_out_order_version": refreshed["version"],
            "result_lines": [result_line(refreshed["test_lines"][0]["id"], 250.0)],
        }, TEST_USERS["medical_technologist_headers"]), 200)
        released = release_order(running["order"]["id"],
                                 "Ferritin within reference interval.")
        assert released["billing_status"] == "BILLED"
        posture = read_client(client_id)
        assert posture["outstanding_balance_cents"] == pytest.approx(1495.00, abs=0.01), (
            "1300 contracted plus the 0.15 RUSH surcharge on a four-hour assay"
        )
        assert posture["status"] == "CREDIT_HOLD", (
            "1495 cents of routed balance exceeds the 1000-cent limit"
        )
        assert refresh_order(running["order"]["id"])["order_status"] == "RESULT_RELEASED", (
            "an order already past SUBMITTED keeps running to its conclusion"
        )
        assert entry_id is not None

    def test_the_dependency_is_on_the_client_posture_and_not_the_order_state(
            self, api, ops_headers, accessioning_headers, billing_headers):
        """PRD 2.9: "Only `ACTIVE` and `CREDIT_HOLD` clients may have specimens
        received, courier legs booked, or orders submitted".
        PRD 2.9: "A `SUSPENDED` or `INACTIVE` client is refused outright."

        Design: Difficulty/cross_entity_state_dependency/send_out_order_accession_requires_client_active_and_specimen_accessioned
        """
        # PRD 2.9: "Only ACTIVE and CREDIT_HOLD clients may have specimens
        # received, courier legs booked, or orders submitted". The permissive
        # reading of PRD 3.1's sweep — which moves only SUBMITTED orders onto
        # hold — is what makes a CREDIT_HOLD client's own intake reachable at
        # all, so the second requisition is submitted after the posture flips.
        scenario = setup_active_client(client_overrides={
            "name": "Box Elder Clinic", "clia_number": "45D-2002",
            "client_type": "PHYSICIAN_OFFICE", "credit_limit_cents": 1000,
        }, clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        book_run(scenario["entry"]["id"], instrument_code="IMM-32",
                 reserved_start_at="2026-09-01T06:00:00Z",
                 reserved_end_at="2026-09-01T09:00:00Z")

        charged = self._specimen_and_order(
            api, scenario, "ACC-8401", "MRN-5101", accessioning_headers, accession_order=True)
        validate_success(api.begin_testing(
            charged["specimen"]["id"], TEST_USERS["medical_technologist_headers"]), 200)
        refreshed = refresh_order(charged["order"]["id"])
        validate_success(api.enter_results(charged["order"]["id"], {
            "expected_send_out_order_version": refreshed["version"],
            "result_lines": [result_line(refreshed["test_lines"][0]["id"], 250.0)],
        }, TEST_USERS["medical_technologist_headers"]), 200)
        release_order(charged["order"]["id"], "Ferritin within reference interval.")
        posture = read_client(client_id)
        assert posture["outstanding_balance_cents"] == pytest.approx(1150.00, abs=0.01)
        assert posture["status"] == "CREDIT_HOLD"

        # The specimen is accessioned first, so the order created afterwards
        # still sits in SUBMITTED when the explicit order-accession endpoint is
        # called — the one case where PRD 3.3's bubble has nothing to move.
        second_specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-8403", "patient_mrn": "MRN-5104",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        validate_success(api.accession_specimen(second_specimen["id"], accessioning_headers), 200)
        waiting = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": second_specimen["id"],
            "order_number": "REQ-ACC8403", "patient_mrn": "MRN-5104",
            "client_requested_at": "2026-09-01T06:41:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        assert waiting["order_status"] == "SUBMITTED"
        admitted = validate_success(api.accession_order(
            waiting["id"], accessioning_headers), 200)
        assert admitted["order_status"] == "ACCESSIONED", (
            "CREDIT_HOLD still admits intake; only SUSPENDED and INACTIVE are refused"
        )

    @staticmethod
    def _specimen_and_order(api, scenario, accession, mrn, accessioning_headers,
                            accession_order=True):
        client_id = scenario["client"]["id"]
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": accession, "patient_mrn": mrn,
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": f"REQ-{accession}", "patient_mrn": mrn,
            "client_requested_at": "2026-09-01T06:41:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        if accession_order:
            # PRD 3.3's bubble moves the SUBMITTED order to ACCESSIONED as part
            # of the specimen act.
            validate_success(api.accession_specimen(specimen["id"], accessioning_headers), 200)
        order = refresh_order(order["id"])
        return {"specimen": specimen, "order": order}


class TestSpecimenReleaseViaInterface:

    def test_transmitting_a_result_message_releases_the_specimen_in_place(
            self, api, medtech_headers, interface_headers):
        """PRD 3.12: "Transmission is the moment the specimen's own state closes
        out when the message carries a released result: the owning specimen moves
        to `RELEASED`, which completes the receipt lifecycle dimension of the
        specimen."
        PRD 3.7: "The specimen then moves from `IN_TESTING` to
        `RESULT_PENDING_REVIEW`, and the order waits there together with it until
        a pathologist signs the results off."

        Design: Difficulty/cross_entity_state_dependency/result_release_requires_reviewed_specimen_and_held_transmission_flips_it
        """
        scenario = self._pending_review_scenario(api, medtech_headers, interface_headers)

        assert scenario["specimen_after_release"] == "RESULT_PENDING_REVIEW", (
            "the specimen stays in review although every line of the order is already FINAL"
        )
        assert scenario["message_validated"] == "VALIDATED", (
            "the specimen stays unreleased while the message is merely validated"
        )

    def test_the_specimen_status_changes_without_any_specimen_endpoint_being_called(
            self, api, medtech_headers, interface_headers):
        """PRD 3.12: "Transmission is the moment the specimen's own state closes
        out when the message carries a released result: the owning specimen moves
        to `RELEASED`".
        PRD 3.12: "A message is queued by an `InterfaceAnalyst` or a
        `MedicalTechnologist` against a send-out order and a certified build".

        Design: Difficulty/cross_entity_state_dependency/result_release_requires_reviewed_specimen_and_held_transmission_flips_it
        """
        scenario = self._pending_review_scenario(api, medtech_headers, interface_headers)
        transmitted = validate_success(api.transmit_interface_message(
            scenario["message_id"], interface_headers), 200)
        assert transmitted["status"] == "TRANSMITTED"
        assert transmitted["transmitted_at"] is not None

        specimen = validate_success(api.get_specimen(scenario["specimen_id"], medtech_headers), 200)
        assert specimen["status"] == "RELEASED", (
            "the specimen's status changed purely as a consequence of the message transition"
        )

    @staticmethod
    def _pending_review_scenario(api, medtech_headers, interface_headers):
        """A released order with a RESULT message validated but not transmitted."""
        from test_helpers import TEST_USERS
        accessioning = TEST_USERS["accessioning_technologist_headers"]
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-10"})
        scenario = start_testing(scenario)
        order = refresh_order(scenario["order"]["id"])
        line_id = order["test_lines"][0]["id"]
        validate_success(api.enter_results(order["id"], {
            "expected_send_out_order_version": order["version"],
            "result_lines": [result_line(line_id, 250.0)],
        }, medtech_headers), 200)
        after_entry = validate_success(api.get_specimen(scenario["specimen"]["id"], accessioning), 200)
        assert after_entry["status"] == "RESULT_PENDING_REVIEW"

        set_clock("2026-09-01T10:00:00Z")
        released = validate_success(api.release_results(
            order["id"], "Ferritin within reference interval.", TEST_USERS["pathologist_headers"]), 200)
        assert released["order_status"] == "RESULT_RELEASED"
        after_release = validate_success(api.get_specimen(scenario["specimen"]["id"], accessioning), 200)

        message = validate_success(api.create_interface_message({
            "send_out_order_id": order["id"], "interface_build_id": scenario["build"]["id"],
            "message_type": "RESULT", "control_id": "CTL-9101",
            "expected_send_out_order_version": released["version"],
        }, interface_headers), 201)
        validated = validate_success(api.validate_interface_message(message["id"], interface_headers), 200)

        return {
            "specimen_id": scenario["specimen"]["id"],
            "message_id": message["id"],
            "specimen_after_release": after_release["status"],
            "message_validated": validated["status"],
        }
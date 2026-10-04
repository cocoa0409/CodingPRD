"""Result release side effects: reflex chaining, ledger conservation and sagas.

The release transaction is the busiest one in the PRD, and this file follows its
fan-out: the chained reflex order, the held outbound messages, the posted charge
and the compensating void/re-charge pair that must leave the routed balance
exactly where it started.
"""
import pytest

from test_helpers import (
    create_aliquot_payload,
    open_ledger,
    queue_result_message,
    read_client,
    read_ledger,
    refresh_order,
    release_order,
    result_line,
    set_clock,
    setup_active_client,
    setup_released_order,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReflexChain:

    def test_a_critical_high_result_chains_to_a_spawned_reflex_order_and_a_final_line(
            self, api, ops_headers, pathologist_headers):
        """PRD 3.8: "`RESULT_ABOVE_HIGH` is satisfied when the value falls
        strictly above the entry's `critical_value_high`".
        PRD 3.8: "When at least one line fires, the order moves to
        `REFLEX_PENDING`, a new send-out order is created to carry the chained
        test with its `reflex_source_order_id` pointing at the triggering order,
        its `order_status` set to `SUBMITTED` and its `billing_status` set to
        `UNBILLED`, holding a single test line with its `line_status` at
        `PENDING` for the reflex catalogue entry."

        Design: Difficulty/transitive_cascade/critical_high_reflex_three_hop_chain_to_held_messages
        """
        scenario = self._reflex_scenario(api, ops_headers, pathologist_headers)

        line = validate_success(api.get_order_test_line(scenario["line_id"], ops_headers), 200)
        assert line["line_status"] == "FINAL"
        assert line["result_flag"] == "CRITICAL_HIGH", "12.5 exceeds the entry's 10.0 high limit"

        order = refresh_order(scenario["order_id"])
        assert order["order_status"] == "REFLEX_PENDING", (
            "the RESULT_ABOVE_HIGH condition fires on the released value"
        )

        children, meta = validate_paginated(api.list_send_out_orders(
            ops_headers, params={"reflex_source_order_id": scenario["order_id"]}))
        assert meta["total_count"] == 1, "exactly one reflex order is spawned"
        reflex = children[0]
        assert reflex["order_status"] == "SUBMITTED"
        assert reflex["billing_status"] == "UNBILLED"
        assert reflex["reflex_source_order_id"] == scenario["order_id"]

        reflex_lines, reflex_meta = validate_paginated(api.list_order_test_lines(
            ops_headers, params={"send_out_order_id": reflex["id"]}))
        assert reflex_meta["total_count"] == 1
        assert reflex_lines[0]["line_status"] == "PENDING"
        assert reflex_lines[0]["test_catalog_entry_id"] == scenario["ft4_entry"]["id"]

    def test_the_reflex_escalation_holds_the_clients_validated_messages(
            self, api, ops_headers, interface_headers):
        """PRD 3.8: "In the same act, every outbound interface message belonging
        to that client, rendered by a certified build and sitting in `QUEUED` or
        `VALIDATED` status, is moved to `HELD` - the laboratory does not transmit
        a result whose reflex tail it is about to amend."

        Design: Difficulty/transitive_cascade/critical_high_reflex_three_hop_chain_to_held_messages
        """
        scenario = self._reflex_scenario(api, ops_headers, None)
        assert scenario["held_message_status"] == "HELD", (
            "the message sat in VALIDATED and was held by the reflex escalation"
        )
        held = validate_success(api.get_interface_message(
            scenario["message_id"], interface_headers), 200)
        assert held["status"] == "HELD"
        assert held["send_out_order_id"] == scenario["other_order_id"], (
            "the held message belongs to the other released order of the same client"
        )

        released = validate_success(api.release_hold_interface_message(
            scenario["message_id"], interface_headers), 200)
        assert released["status"] == "VALIDATED", (
            "un-holding requires a certified build, not a re-release"
        )

    @staticmethod
    def _reflex_scenario(api, ops_headers, pathologist_headers):
        """A critical-high thyrotropin order plus a second released order whose
        RESULT message sits in VALIDATED, all for one client."""
        from test_helpers import TEST_USERS
        client_admin = TEST_USERS["lab_client_admin_headers"]
        accessioning = TEST_USERS["accessioning_technologist_headers"]
        medtech = TEST_USERS["medical_technologist_headers"]
        iface = TEST_USERS["interface_analyst_headers"]

        # The reflex target must already be PUBLISHED when the shared entry is
        # published (PRD 3.4), and publishing it first also keeps the shared
        # entry's updated_at behind the certified build (PRD 2.8).
        ft4 = validate_success(api.create_catalog_entry({
            "test_code": "FT4_FREE", "test_name": "Free T4, Serum",
            "test_category": "ROUTINE", "method": "IMMUNOASSAY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 0.5, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 48, "stability_hours_refrigerated": 168,
            "stability_hours_frozen": 720, "base_tat_hours": 6,
            "list_price_cents": 1800, "client_price_cents": 1500, "floor_price_cents": 700,
            "critical_value_low": None, "critical_value_high": None,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, client_admin), 201)
        api.publish_catalog_entry(ft4["id"], client_admin)
        scenario = setup_active_client(
            entry_overrides={
                "test_code": "TSH_REFLEX", "test_name": "Thyrotropin with Reflex to Free T4",
                "base_tat_hours": 8, "list_price_cents": 2400, "client_price_cents": 2000,
                "floor_price_cents": 900, "critical_value_low": 0.01,
                "critical_value_high": 10.0, "reflex_test_code": "FT4_FREE",
                "reflex_condition": "RESULT_ABOVE_HIGH", "reflex_within_hours": 24,
                "reflex_min_remaining_hours": 6, "is_utilization_managed": False,
            },
            clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]

        # Order Q: the thyrotropin order that will fire the reflex.
        tsh_specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-6001", "patient_mrn": "MRN-9501",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning), 201)
        tsh_order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": tsh_specimen["id"],
            "order_number": "REQ-6001", "patient_mrn": "MRN-9501",
            "client_requested_at": "2026-09-01T06:35:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning), 201)
        api.create_instrument_run({
            "test_catalog_entry_id": scenario["entry"]["id"], "instrument_code": "IMM-06",
            "section": "CORE", "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T07:00:00Z", "reserved_end_at": "2026-09-01T12:00:00Z",
        }, medtech)
        validate_success(api.accession_specimen(tsh_specimen["id"], accessioning), 200)
        validate_success(api.begin_testing(tsh_specimen["id"], medtech), 200)
        tsh_order = refresh_order(tsh_order["id"])
        tsh_line = validate_success(api.get_order_test_line(
            tsh_order["test_lines"][0]["id"], medtech), 200)
        validate_success(api.enter_results(tsh_order["id"], {
            "expected_send_out_order_version": tsh_order["version"],
            "result_lines": [result_line(
                tsh_line["id"], 12.5, "mIU/L", critical_value_notified_to="Dr. A. Reyes",
                critical_value_notified_at="2026-09-01T09:45:00Z")],
        }, medtech), 200)

        # Order O: a ferritin order released and queued, sitting in VALIDATED.
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-6002", "patient_mrn": "MRN-5001",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning), 201)
        other_order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-6002", "patient_mrn": "MRN-5001",
            "client_requested_at": "2026-09-01T06:36:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning), 201)
        # The shared entry's 0.01-10.0 critical band makes 90.0 a critical-high
        # value (PRD 3.7), and every critical line must carry its critical-value
        # documentation before release (PRD 3.7).
        validate_success(api.accession_specimen(specimen["id"], accessioning), 200)
        validate_success(api.begin_testing(specimen["id"], medtech), 200)
        set_clock("2026-09-01T08:00:00Z")
        other_order = refresh_order(other_order["id"])
        other_line = validate_success(api.get_order_test_line(
            other_order["test_lines"][0]["id"], medtech), 200)
        validate_success(api.enter_results(other_order["id"], {
            "expected_send_out_order_version": other_order["version"],
            "result_lines": [result_line(
                other_line["id"], 90.0,
                critical_value_notified_to="Dr. A. Reyes",
                critical_value_notified_at="2026-09-01T07:45:00Z")],
        }, medtech), 200)
        set_clock("2026-09-01T09:00:00Z")
        release_order(other_order["id"], "Ferritin, no interpretive comment.")
        other_order = refresh_order(other_order["id"])
        message = validate_success(api.create_interface_message({
            "send_out_order_id": other_order["id"],
            "interface_build_id": scenario["build"]["id"],
            "message_type": "RESULT", "control_id": "CTL-7001",
            "expected_send_out_order_version": other_order["version"],
        }, iface), 201)
        validated = validate_success(api.validate_interface_message(message["id"], iface), 200)
        assert validated["status"] == "VALIDATED"

        set_clock("2026-09-01T10:00:00Z")
        released = release_order(tsh_order["id"], "Thyrotropin elevated; reflex free T4 ordered.")
        held = validate_success(api.get_interface_message(message["id"], iface), 200)
        return {
            "order_id": tsh_order["id"], "line_id": tsh_line["id"],
            "ft4_entry": ft4, "other_order_id": other_order["id"],
            "message_id": message["id"], "held_message_status": held["status"],
            "released_order_status": released["order_status"],
        }


class TestLedgerConservation:

    def test_void_then_recharge_restores_the_conserved_net_position(self, api, ops_headers,
                                                                   billing_headers):
        """PRD 3.10: "The conserved quantity is the ledger's net position and the
        client's routed outstanding balance together. Take any order already
        carrying a `billing_status` of `BILLED` and pair two acts: voiding that
        order's charge on the ledger with a `void_amount_cents` exactly equal to
        the order's final charge, and then posting the order's charge again."
        PRD 3.10: "the pair leaves both the ledger's net position and the
        client's outstanding balance exactly where they started."

        Design: Difficulty/compensating_invariant/void_then_recharge_leaves_net_billed_and_routed_balance_unchanged
        """
        scenario = setup_released_order()
        client_id = scenario["client"]["id"]
        order = refresh_order(scenario["order"]["id"])
        # The release already posted the charge to the client's own ledger, so the
        # fixture hands that ledger back rather than opening a second one.
        ledger = scenario["ledger"]
        assert order["order_final_charge_cents"] == pytest.approx(1150.00, abs=0.01)
        assert order["billing_status"] == "BILLED", "release bills the order"

        before_ledger = read_ledger(ledger["id"])
        before_client = read_client(client_id)
        assert before_ledger["net_billed_cents"] == pytest.approx(1150.00, abs=0.01)
        assert before_client["outstanding_balance_cents"] == pytest.approx(1150.00, abs=0.01)

        voided = validate_success(api.void_charges(
            ledger["id"], order["id"], 1150, billing_headers), 200)
        assert voided["net_billed_cents"] == pytest.approx(0.00, abs=0.01)
        after_void_client = read_client(client_id)
        assert after_void_client["outstanding_balance_cents"] == pytest.approx(0.00, abs=0.01), (
            "a voided order contributes nothing to the routed balance"
        )

        recharged = validate_success(api.charge_order(order["id"], billing_headers), 200)
        assert recharged["billing_status"] == "BILLED"
        after_ledger = read_ledger(ledger["id"])
        after_client = read_client(client_id)
        assert after_ledger["net_billed_cents"] == pytest.approx(1150.00, abs=0.01)
        assert after_client["outstanding_balance_cents"] == pytest.approx(1150.00, abs=0.01)

    def test_the_gross_totals_and_entry_count_grow_while_the_net_does_not(
            self, api, ops_headers, billing_headers):
        """PRD 3.10: "What does not return to its starting value is the ledger's
        billed total, its voided total and its charge entry count - all three
        grow across the pair by design, because the laboratory's audit trail must
        show that a charge was voided and re-posted even though the money owed is
        unchanged."
        PRD 3.10: "A void moves a billed order to voided status, and a subsequent
        charge can move it back to billed".

        Design: Difficulty/compensating_invariant/void_then_recharge_leaves_net_billed_and_routed_balance_unchanged
        """
        scenario = setup_released_order()
        order_id = scenario["order"]["id"]
        ledger = scenario["ledger"]

        mismatched = api.void_charges(ledger["id"], order_id, 1149, billing_headers)
        validate_error(mismatched, "ERR_VOID_AMOUNT_MISMATCH", expected_status=409)

        voided = validate_success(api.void_charges(
            ledger["id"], order_id, 1150, billing_headers), 200)
        assert voided["voided_cents"] == pytest.approx(1150.00, abs=0.01)
        assert refresh_order(order_id)["billing_status"] == "VOIDED"

        validate_success(api.charge_order(order_id, billing_headers), 200)
        after = read_ledger(ledger["id"])
        assert after["billed_cents"] == pytest.approx(2300.00, abs=0.01)
        assert after["voided_cents"] == pytest.approx(1150.00, abs=0.01)
        assert after["net_billed_cents"] == pytest.approx(1150.00, abs=0.01)
        assert after["charge_entry_count"] == 2, (
            "the entry count records posted-charge events and is never rewound by a void"
        )
        assert after["net_billed_cents"] == pytest.approx(
            after["billed_cents"] - after["voided_cents"], abs=0.01)


class TestAliquotConservation:

    def test_create_then_delete_returns_the_aliquot_total_and_child_count(
            self, api, accessioning_headers):
        """PRD 3.10: "The parent specimen's `total_aliquot_volume_ml` is the sum
        of the `aliquot_volume_ml` values of all tubes derived from it,
        recomputed whenever a tube is added or removed. Creating a tube raises
        the total by that tube's captured volume; deleting that tube from its
        parent lowers the total by the same amount and removes the row from the
        set."
        PRD 3.10: "The pair therefore leaves both the total volume and the number
        of derived rows exactly as they were."

        Design: Difficulty/compensating_invariant/aliquot_create_then_delete_leaves_the_stored_totals_unchanged
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-8501", "patient_mrn": "MRN-8601",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-8501", "patient_mrn": "MRN-8601",
            "client_requested_at": "2026-09-01T06:35:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        validate_success(api.accession_specimen(specimen["id"], accessioning_headers), 200)

        before = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert before["total_aliquot_volume_ml"] == 0.00

        aliquot = validate_success(api.create_aliquot(specimen["id"], create_aliquot_payload(
            aliquot_volume_ml=1.00, container_type="GOLD_SST",
            accession_number="ACC-8501-A1"), accessioning_headers), 201)
        mid = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert mid["total_aliquot_volume_ml"] == pytest.approx(1.00, abs=0.01), (
            "the create really did move the derived total"
        )

        validate_success(api.delete_aliquot(specimen["id"], aliquot["id"], accessioning_headers), 200)
        after = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert after["total_aliquot_volume_ml"] == pytest.approx(0.00, abs=0.01)
        assert after["status"] == "ACCESSIONED", (
            "the parent's own receipt state is outside the conserved quantity"
        )

        children, meta = validate_paginated(api.list_specimens(
            accessioning_headers, params={"aliquot_parent_id": specimen["id"]}))
        assert meta["total_count"] == 0
        assert children == []

    def test_overdraw_rejects_the_parent_and_is_not_undone_by_deleting_the_tube(
            self, api, accessioning_headers):
        """PRD 3.10: "Overdraw itself is an error rather than a silent
        truncation - when the running aliquot total for a parent exceeds the
        parent's own received volume, the parent specimen transitions to
        `REJECTED` with condition `INSUFFICIENT_VOLUME` and a condition reason
        code of `ALIQUOT_OVERDRAW`, and the request reports `ERR_ALIQUOT_OVERDRAW`
        (HTTP 409)."
        PRD 3.10: "if the derived tubes overdraw the parent, the overdraw
        rejection is not undone by deleting the offending tube, because the
        parent's condition has already changed."

        Design: Difficulty/compensating_invariant/aliquot_create_then_delete_leaves_the_stored_totals_unchanged
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-8502", "patient_mrn": "MRN-8602",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 2.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)

        first = validate_success(api.create_aliquot(specimen["id"], create_aliquot_payload(
            aliquot_volume_ml=1.00, accession_number="ACC-8502-A1"),
            accessioning_headers), 201)
        overdrawn = api.create_aliquot(specimen["id"], create_aliquot_payload(
            aliquot_volume_ml=1.50, accession_number="ACC-8502-A2"), accessioning_headers)
        validate_error(overdrawn, "ERR_ALIQUOT_OVERDRAW", expected_status=409)

        parent = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert parent["status"] == "REJECTED"
        assert parent["condition"] == "INSUFFICIENT_VOLUME"
        assert parent["condition_reason_code"] == "ALIQUOT_OVERDRAW"

        validate_success(api.delete_aliquot(specimen["id"], first["id"], accessioning_headers), 200)
        after_delete = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert after_delete["total_aliquot_volume_ml"] == pytest.approx(0.00, abs=0.01)
        assert after_delete["status"] == "REJECTED", (
            "the overdraw rejection is not undone by deleting the offending tube"
        )
        assert after_delete["condition"] == "INSUFFICIENT_VOLUME"


class TestCancellationSaga:

    def test_cancelling_a_provisional_order_leaves_the_ledger_untouched(
            self, api, ops_headers, accessioning_headers, billing_headers):
        """PRD 3.11: "It moves the order to `CANCELLED` and cancels every line
        whose status is `PENDING`, `IN_PROGRESS` or `INTERIM`. Where any line of
        that order had a non-zero charge, the order's `billing_status` moves to
        `VOIDED` and the ledger's voided total rises by the sum of those line
        charges".
        PRD 3.10: "`charge_entry_count` is the number of posted-charge events
        applied, which a void never decrements."

        Design: Corner/consistency_model/order_cancel_is_transactional_and_leaves_billing_provisional_not_billed
        """
        # PRD 3.2: received_at must not be later than the logical clock, and the
        # fixture's specimen is received at 03:30.
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        entry_id = scenario["entry"]["id"]  # ferritin, list price 1200
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3101", "patient_mrn": "MRN-3101",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z", "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-3101", "patient_mrn": "MRN-3101",
            "client_requested_at": "2026-08-31T20:45:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(entry_id, 1), order_line(entry_id, 2), order_line(entry_id, 3)],
            "override_utilization_guard": True,
        }, accessioning_headers), 201)
        ledger = open_ledger(client_id)
        validate_success(api.accession_specimen(specimen["id"], accessioning_headers), 200)
        accessioned = refresh_order(order["id"])
        assert accessioned["billing_status"] == "PROVISIONAL"
        assert accessioned["provisional_charge_cents"] == pytest.approx(3600.00, abs=0.01), (
            "the sum of the catalogue list prices of the order's three lines"
        )

        cancelled = validate_success(api.cancel_order(order["id"], ops_headers), 200)
        assert cancelled["order_status"] == "CANCELLED"
        assert cancelled["billing_status"] == "PROVISIONAL", (
            "no charge was ever posted, so nothing is voided"
        )

        ledger_after = read_ledger(ledger["id"])
        assert ledger_after["billed_cents"] == 0.00
        assert ledger_after["voided_cents"] == 0.00
        assert ledger_after["charge_entry_count"] == 0
        assert read_client(client_id)["outstanding_balance_cents"] == 0.00

        lines, meta = validate_paginated(api.list_order_test_lines(
            ops_headers, params={"send_out_order_id": order["id"]}))
        assert meta["total_count"] == 3
        assert all(line["line_status"] == "CANCELLED" for line in lines), (
            "the saga compensated every line without touching the ledger"
        )


class TestInterfaceMessageIntegrity:

    def test_reusing_a_control_id_within_a_client_is_refused(self, api, interface_headers):
        """PRD 3.12: "that control identifier must be unique per client, and a
        reuse is refused with `ERR_CONTROL_ID_REUSED` (HTTP 409)."
        PRD 2.7: "the request must carry the field, and the value it carries must
        equal the parent entity's current `version`."

        Design: Corner/errors/interface_message_duplicate_control_id_returns_control_id_reused
        """
        scenario = setup_released_order()
        first = queue_result_message(scenario, "CTL-5001")
        assert first["status"] == "QUEUED"

        order = refresh_order(scenario["order"]["id"])
        duplicate = api.create_interface_message({
            "send_out_order_id": order["id"],
            "interface_build_id": scenario["build"]["id"],
            "message_type": "RESULT",
            "control_id": "CTL-5001",
            "expected_send_out_order_version": order["version"],
        }, interface_headers)
        validate_error(duplicate, "ERR_CONTROL_ID_REUSED", expected_status=409)

        data, meta = validate_paginated(api.list_interface_messages(
            interface_headers, params={"send_out_order_id": order["id"]}))
        assert meta["total_count"] == 1

    def test_queueing_against_a_draft_build_is_refused(self, api, ops_headers, interface_headers):
        """PRD 3.12: "Any interface operation must reference an `InterfaceBuild`
        that is `CERTIFIED` and that belongs to the same client as the order it
        serves; otherwise the request fails with
        `ERR_INTERFACE_BUILD_NOT_CERTIFIED`."
        PRD 3.12: "A build's life runs through `DRAFT`, `IN_BUILD`, `CERTIFIED`,
        `SUPERSEDED` and `RETIRED`".

        Design: Corner/errors/interface_message_against_a_draft_build_returns_build_not_certified
        """
        scenario = setup_released_order()
        draft = validate_success(api.create_interface_build({
            "client_laboratory_id": scenario["client"]["id"],
            "build_version_label": "v2-draft", "format": "CSV_FLAT_FILE",
            "order_interface_enabled": True, "result_interface_enabled": True,
        }, interface_headers), 201)
        assert draft["status"] == "DRAFT"

        order = refresh_order(scenario["order"]["id"])
        refused = api.create_interface_message({
            "send_out_order_id": order["id"], "interface_build_id": draft["id"],
            "message_type": "RESULT", "control_id": "CTL-5101",
            "expected_send_out_order_version": order["version"],
        }, interface_headers)
        validate_error(refused, "ERR_INTERFACE_BUILD_NOT_CERTIFIED", expected_status=422)

        accepted = validate_success(api.create_interface_message({
            "send_out_order_id": order["id"], "interface_build_id": scenario["build"]["id"],
            "message_type": "RESULT", "control_id": "CTL-5102",
            "expected_send_out_order_version": order["version"],
        }, interface_headers), 201)
        assert accepted["status"] == "QUEUED"
        assert refresh_order(order["id"])["order_status"] == "RESULT_RELEASED"

    def test_a_failed_transmission_backs_off_and_saturates_at_the_ceiling(
            self, api, interface_headers):
        """PRD 2.8: "Because the counter is incremented before the offset is
        computed, the first failure produces a count of 1 and an interval of 10
        minutes; successive failures produce 20, then 40, then the ceiling of 60
        minutes, and the ceiling binds from the fourth failure onward."
        PRD 2.8: "The counter is never cleared by a successful validation hop -
        it resets to zero only when the message actually reaches the transmitted
        state."

        Design: Difficulty/non_linear_state_machine/interface_message_retry_cycle_and_backoff_cap
        """
        scenario = setup_released_order()
        message = queue_result_message(scenario, "CTL-9001")
        validate_success(api.validate_interface_message(message["id"], interface_headers), 200)

        expected = [(1, 10), (2, 20), (3, 40), (4, 60)]
        for count, offset in expected:
            failed = validate_success(api.fail_interface_message(
                message["id"], interface_headers), 200)
            assert failed["status"] == "FAILED"
            assert failed["retry_count"] == count
            assert failed["next_retry_offset_minutes"] == offset, (
                f"failure {count} backs off to {offset} minutes"
            )
            revalidated = validate_success(api.validate_interface_message(
                message["id"], interface_headers), 200)
            assert revalidated["status"] == "VALIDATED", (
                "the retry cycle returns to VALIDATED between every pair of failures"
            )

    def test_five_accumulated_failures_block_further_validation(self, api, interface_headers):
        """PRD 2.8: "A message that has accumulated five failed attempts can no
        longer be validated at all, and an attempt to do so is refused with
        `ERR_RETRY_LIMIT_REACHED`."
        PRD 2.8: "the delay before the next attempt is
        `next_retry_offset_minutes`, computed as the minimum of a base interval
        doubled once per accumulated failure and a fixed ceiling."

        Design: Difficulty/non_linear_state_machine/interface_message_retry_cycle_and_backoff_cap
        """
        scenario = setup_released_order()
        message = queue_result_message(scenario, "CTL-9002")
        validate_success(api.validate_interface_message(message["id"], interface_headers), 200)

        for _ in range(4):
            validate_success(api.fail_interface_message(message["id"], interface_headers), 200)
            validate_success(api.validate_interface_message(message["id"], interface_headers), 200)

        fifth = validate_success(api.fail_interface_message(message["id"], interface_headers), 200)
        assert fifth["status"] == "FAILED"
        assert fifth["retry_count"] == 5, "the five-failure allowance is now exhausted"

        refused = api.validate_interface_message(message["id"], interface_headers)
        validate_error(refused, "ERR_RETRY_LIMIT_REACHED", expected_status=409)
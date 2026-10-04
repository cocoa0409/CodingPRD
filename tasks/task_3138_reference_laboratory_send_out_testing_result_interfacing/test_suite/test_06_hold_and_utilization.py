"""Order hold cycles, utilisation advising and listing filters.

Two cyclic mechanisms meet here: an order that oscillates between intake and
hold as its client's posture flips, and an advisory that is delivered, re-sent
and only then escalatable.
"""
import pytest

from test_helpers import (
    acknowledge_advisory,
    resend_advisory_via_repeat_order,
    make_lab_client_admin_headers,
    raise_advisory,
    read_client,
    refresh_order,
    release_order,
    result_line,
    set_clock,
    setup_active_client,
    setup_specimen_and_order,
    start_testing,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderHoldCycle:

    def test_a_ledger_driven_posture_flip_holds_and_releases_the_same_order(
            self, api, ops_headers, billing_headers):
        """PRD 3.1: "Whenever a ledger mutation or a posted order charge leaves
        the recomputed outstanding balance strictly above the credit limit, the
        client's posture flips from `ACTIVE` to `CREDIT_HOLD`, and in the same
        act every order of that client still in `SUBMITTED` status is moved to
        `ON_HOLD`."
        PRD 3.1: "The reverse leg is settlement: a `LabBillingSpecialist` may
        apply a `settlement_amount_cents` to the client's ledger, which
        increases the ledger's voided total by that amount, recomputes the
        ledger's net position, recomputes the client's outstanding balance, and
        returns the client to ACTIVE when the recomputed balance is at or below
        the credit limit."

        Design: Difficulty/non_linear_state_machine/send_out_order_hold_cycle_returns_to_submitted
        """
        scenario = self._over_limit_scenario(api, ops_headers)
        client_id = scenario["client_id"]

        first_posture = read_client(client_id)["status"]
        assert first_posture == "CREDIT_HOLD", (
            "the release-time charge of 1150 cents exceeds the 1000-cent limit"
        )
        held = refresh_order(scenario["companion_order_id"])
        assert held["order_status"] == "ON_HOLD", (
            "PRD 3.1 sweeps every order of that client still in SUBMITTED onto hold"
        )

        settled = validate_success(api.settle_balance(client_id, 1150, billing_headers), 200)
        assert settled["status"] == "ACTIVE"

        released = validate_success(api.release_hold(scenario["companion_order_id"], billing_headers), 200)
        assert released["order_status"] == "SUBMITTED"
        assert released["billing_status"] == "UNBILLED", (
            "release-hold returns the order to intake; the companion was never charged"
        )

    def test_the_order_returns_to_hold_on_a_second_over_limit_charge(
            self, api, ops_headers, billing_headers):
        """PRD 3.1: "Because posture is nothing more than a comparison of balance
        against limit, a settled client and a freshly charged client can oscillate
        between the two postures indefinitely without any new client record being
        created."
        PRD 3.11: "An order may pass through this cycle repeatedly while its
        client's posture oscillates, which is exactly why hold and release-hold
        are separate acts rather than one toggle."

        Design: Difficulty/non_linear_state_machine/send_out_order_hold_cycle_returns_to_submitted
        """
        scenario = self._over_limit_scenario(api, ops_headers)
        client_id = scenario["client_id"]
        order_id = scenario["companion_order_id"]

        validate_success(api.settle_balance(client_id, 1150, billing_headers), 200)
        assert read_client(client_id)["status"] == "ACTIVE"
        first_release = validate_success(api.release_hold(order_id, billing_headers), 200)
        assert first_release["order_status"] == "SUBMITTED"

        manual_hold = validate_success(api.hold_order(order_id, ops_headers), 200)
        assert manual_hold["order_status"] == "ON_HOLD"

        second_release = validate_success(api.release_hold(order_id, billing_headers), 200)
        assert second_release["order_status"] == "SUBMITTED"
        assert refresh_order(order_id)["order_status"] == "SUBMITTED"

    def test_release_hold_restores_in_progress_lines_to_pending(
            self, api, ops_headers, billing_headers, medtech_headers):
        """PRD 3.11: "A `ReferenceLabOperations` operator may hold an order that
        is in `SUBMITTED`, `ACCESSIONED`, `IN_TESTING` or `INTERIM_REPORTED`
        status, moving it to `ON_HOLD` and pulling every line of that order that
        is in `IN_PROGRESS` back to `PENDING` - the revert is deliberate, because
        a held order's bench work is no longer in flight".
        PRD 3.11: "which is available only when the client is `ACTIVE` and the
        order's `billing_status` is `UNBILLED` or `PROVISIONAL`, and which
        restores the order to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/send_out_order_hold_cycle_returns_to_submitted
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-22"})
        scenario = start_testing(scenario)
        order_id = scenario["order"]["id"]
        line_id = scenario["order"]["test_lines"][0]["id"]
        assert validate_success(api.get_order_test_line(line_id, medtech_headers), 200)[
            "line_status"] == "IN_PROGRESS"

        held = validate_success(api.hold_order(order_id, ops_headers), 200)
        assert held["order_status"] == "ON_HOLD"
        assert validate_success(api.get_order_test_line(line_id, medtech_headers), 200)[
            "line_status"] == "PENDING", "bench work is pulled back out of flight"

        restored = validate_success(api.release_hold(order_id, billing_headers), 200)
        assert restored["order_status"] == "SUBMITTED"
        assert restored["billing_status"] == "PROVISIONAL"

    @staticmethod
    def _over_limit_scenario(api, ops_headers):
        """A 1000-cent client driven over its limit by a release-time charge.

        PRD 3.7 fans the release-time charge out to the ledger "with the
        possibility ... that the client's posture flips to CREDIT_HOLD if the
        routed balance exceeds the credit limit", which is the only path the PRD
        leaves open: PRD 2.9's own ceiling refuses a direct charge that "would
        push a client-routed account above its limit". A companion order is left
        in SUBMITTED so the flip's sweep — PRD 3.1's "every order of that client
        still in SUBMITTED status is moved to ON_HOLD" — is observable.
        """
        scenario = setup_active_client(client_overrides={
            "name": "Box Elder Clinic", "clia_number": "45D-2002",
            "client_type": "PHYSICIAN_OFFICE", "credit_limit_cents": 1000,
        }, clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-05"})
        companion = setup_specimen_and_order(
            scenario, accession=False, probe=False,
            specimen_overrides={"accession_number": "ACC-7101", "patient_mrn": "MRN-7101"},
            order_overrides={"order_number": "REQ-7101", "patient_mrn": "MRN-7101"})
        scenario = start_testing(scenario)
        order = refresh_order(scenario["order"]["id"])
        line_id = order["test_lines"][0]["id"]
        validate_success(api.enter_results(order["id"], {
            "expected_send_out_order_version": order["version"],
            "result_lines": [result_line(line_id, 90.0)],
        }, api_token("medical_technologist_headers")), 200)
        set_clock("2026-09-01T10:00:00Z")
        released = release_order(order["id"], "Ferritin, no interpretive comment.")
        assert released["order_final_charge_cents"] == pytest.approx(1150.00, abs=0.01)
        return {"client_id": client_id, "order_id": order["id"],
                "companion_order_id": companion["order"]["id"]}


def api_token(key):
    from test_helpers import TEST_USERS
    return TEST_USERS[key]


class TestUtilizationAdvising:

    def test_delivery_increments_the_send_count_and_escalation_needs_two_deliveries(
            self, api, ops_headers, client_admin_headers, utilization_headers):
        """PRD 3.9: "A freshly raised advisory is `OPEN`, and it may be delivered
        either by a `LabClientAdmin` recording receipt or as part of the client's
        requirement publication".
        PRD 3.9: "it requires that the advisory's `send_count` have reached at
        least two - meaning it was delivered and then re-delivered at least once,
        so an ignored advisory has demonstrably been ignored."

        Design: Corner/errors/repeated_utilization_managed_order_is_blocked_after_an_escalated_advisory
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        client_id = scenario["client"]["id"]
        entry_id = scenario["entry"]["id"]
        admin = make_lab_client_admin_headers(client_id)

        advisory = raise_advisory(client_id, entry_id)
        assert advisory["status"] == "OPEN"
        assert advisory["send_count"] == 0

        refused = api.escalate_utilization_advisory(advisory["id"], ops_headers)
        assert refused.status_code >= 400, (
            "an advisory delivered only zero times has no send count to escalate on"
        )

        delivered = validate_success(api.acknowledge_utilization_advisory(advisory["id"], admin), 200)
        assert delivered["status"] == "ACKNOWLEDGED"
        assert delivered["send_count"] == 1, (
            "the client's recorded receipt is the delivery that moves OPEN to SENT"
        )

        # PRD 3.9: "If the same client subsequently orders the same
        # utilisation-managed test again, the acknowledged advisory is re-sent
        # rather than duplicated - it returns to SENT and its send_count
        # increments a second time."
        resend_advisory_via_repeat_order(scenario, patient_mrn="MRN-9101")
        resent = validate_success(
            api.get_utilization_advisory(advisory["id"], utilization_headers), 200)
        assert resent["status"] == "SENT", "the repeat re-sent the acknowledged advisory"
        assert resent["send_count"] == 2

        escalated = validate_success(api.escalate_utilization_advisory(advisory["id"], ops_headers), 200)
        assert escalated["status"] == "ESCALATED", (
            "the send-back cycle reached a send count of two"
        )
        assert escalated["send_count"] >= 2

    def test_repeating_the_same_test_for_the_same_patient_is_blocked_once_escalated(
            self, api, ops_headers, accessioning_headers, client_admin_headers,
            utilization_headers):
        """PRD 3.5: "if an advisory for the same client and the same test already
        sits in `ESCALATED` status and the submission does not set
        `override_utilization_guard` to true, the order is refused with
        `ERR_UTILIZATION_GUARD_BLOCKED` (HTTP 409)."
        PRD 3.5: "Beyond the escalated case, any repeat of a utilisation-managed
        test for the same patient raises a `UtilizationAdvisory` of type
        `DUPLICATE_ORDER`".

        Design: Corner/errors/repeated_utilization_managed_order_is_blocked_after_an_escalated_advisory
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        client_id = scenario["client"]["id"]
        entry_id = scenario["entry"]["id"]
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-4101", "patient_mrn": "MRN-4101",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-08-31T20:40:00Z", "received_at": "2026-09-01T00:00:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        first = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-4101", "patient_mrn": "MRN-4101",
            "client_requested_at": "2026-08-31T20:45:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(entry_id, 1)], "override_utilization_guard": False,
        }, accessioning_headers), 201)

        advisory = raise_advisory(client_id, entry_id, source_order_id=first["id"])
        acknowledge_advisory(advisory["id"], client_id)
        # The acknowledgement is the delivery (send_count 1); the send-back cycle
        # for the same patient supplies the second (PRD 3.9).
        resend_advisory_via_repeat_order(scenario, entry_id=entry_id,
                                         patient_mrn="MRN-4101",
                                         accession_number="ACC-4102",
                                         order_prefix="REQ-4106")
        validate_success(api.escalate_utilization_advisory(advisory["id"], ops_headers), 200)

        blocked = api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-4102", "patient_mrn": "MRN-4101",
            "client_requested_at": "2026-08-31T20:46:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(entry_id, 1)], "override_utilization_guard": False,
        }, accessioning_headers)
        validate_error(blocked, "ERR_UTILIZATION_GUARD_BLOCKED", expected_status=409)

        # PRD 3.5: the repeat guard is scoped to the patient, so a different
        # patient_mrn is ordered against its own specimen.
        # The escalated advisory guards the original client-and-test pair (PRD
        # 3.5), so a second published assay is what shows the refusal is not
        # simply "this client may order nothing".
        second_entry = validate_success(api.create_catalog_entry({
            "test_code": "FERRITIN_ALT", "test_name": "Ferritin, Plasma",
            "test_category": "ROUTINE", "method": "IMMUNOASSAY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 1.0, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 72, "stability_hours_refrigerated": 168,
            "stability_hours_frozen": 720, "base_tat_hours": 6,
            "list_price_cents": 1200, "client_price_cents": 1000, "floor_price_cents": 450,
            "critical_value_low": None, "critical_value_high": None,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 12,
            "is_utilization_managed": False,
        }, client_admin_headers), 201)
        api.publish_catalog_entry(second_entry["id"], client_admin_headers)
        unguarded = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen["id"],
            "order_number": "REQ-4103", "patient_mrn": "MRN-4101",
            "client_requested_at": "2026-08-31T20:47:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(second_entry["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        assert unguarded["order_status"] == "SUBMITTED", (
            "the guard is scoped to the client and the test, not to the client alone"
        )

        data, meta = validate_paginated(api.list_send_out_orders(
            ops_headers, params={"client_laboratory_id": client_id}))
        assert meta["total_count"] == 4, (
            "the blocked submission persisted nothing; the four rows are the first "
            "requisition, the send-back cycle's pair, and the unguarded second assay"
        )


class TestUtilizationMetrics:

    def test_forward_and_settled_metrics_count_the_same_work_differently(
            self, api, utilization_headers, ops_headers, accessioning_headers, medtech_headers):
        """PRD 3.5: "The `forward_utilization_score` counts, over every test line
        reachable from the client, those whose line status is one of `PENDING`,
        `IN_PROGRESS`, `INTERIM`, `FINAL` or `REPEAT_REQUIRED` and whose order's
        `client_requested_at` lies inside the trailing 30 days. The
        `settled_utilization_score` counts only lines in `FINAL` status whose
        `result_released_at` is set, is at or before the logical clock, and lies
        inside that same trailing 30 days."
        PRD 3.5: "an order submitted but not yet released already counts toward
        the forward score while contributing nothing to the settled score".

        Design: Difficulty/dual_variant_calc/client_utilization_forward_vs_settled_metric_divergence
        """
        scenario = self._metric_scenario(api, accessioning_headers, medtech_headers)

        client = validate_success(api.get_client_laboratory(
            scenario["client_id"], utilization_headers), 200)
        assert client["forward_utilization_score"] == 4, (
            "three in-flight ferritin lines plus the one released thyroglobulin line"
        )
        assert client["settled_utilization_score"] == 1, (
            "only the released line has a result_released_at inside the window"
        )
        assert client["utilization_flag"] is False, (
            "one settled line does not exceed the trailing monthly band"
        )

    def test_the_divergence_is_a_dataset_difference_not_the_same_figure(
            self, api, utilization_headers, accessioning_headers, medtech_headers, ops_headers):
        """PRD 3.5: "The consequence is that an order submitted but not yet
        released already counts toward the forward score while contributing
        nothing to the settled score, so the two numbers diverge while work is in
        flight."
        PRD 3.5: "From the settled score the service derives `utilization_flag`,
        a boolean that is true when the settled score exceeds the trailing
        monthly band."

        Design: Difficulty/dual_variant_calc/client_utilization_forward_vs_settled_metric_divergence
        """
        scenario = self._metric_scenario(api, accessioning_headers, medtech_headers)
        client = validate_success(api.get_client_laboratory(
            scenario["client_id"], utilization_headers), 200)

        assert client["forward_utilization_score"] == 4
        assert client["settled_utilization_score"] == 1
        assert client["forward_utilization_score"] - client["settled_utilization_score"] == 3, (
            "the three unreleased lines are visible only to the forward variant"
        )
        assert client["forward_utilization_score"] != client["settled_utilization_score"]

    @staticmethod
    def _metric_scenario(api, accessioning_headers, medtech_headers):
        from test_helpers import TEST_USERS
        client_admin = TEST_USERS["lab_client_admin_headers"]

        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        ferritin = scenario["entry"]["id"]
        thyro = validate_success(api.create_catalog_entry({
            "test_code": "THYROGLOBULIN", "test_name": "Thyroglobulin, Serum",
            "test_category": "ROUTINE", "method": "IMMUNOASSAY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 1.0, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 72, "stability_hours_refrigerated": 168,
            "stability_hours_frozen": 720, "base_tat_hours": 6,
            "list_price_cents": 2600, "client_price_cents": 2200, "floor_price_cents": 0,
            "critical_value_low": None, "critical_value_high": None,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, client_admin), 201)
        api.publish_catalog_entry(thyro["id"], client_admin)

        specimen1 = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-1001", "patient_mrn": "MRN-5001",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order1 = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen1["id"],
            "order_number": "REQ-1001", "patient_mrn": "MRN-5001",
            "client_requested_at": "2026-09-01T06:35:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(ferritin, 1), order_line(ferritin, 2),
                           order_line(ferritin, 3)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        # PRD 3.6: the clock must reach reserved_start_at before a RESERVED run
        # becomes RUNNING, and the set clock must then be short of
        # reserved_end_at so the run is still the one live window.
        api.create_instrument_run({
            "test_catalog_entry_id": ferritin, "instrument_code": "IMM-01", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T06:00:00Z", "reserved_end_at": "2026-09-01T09:00:00Z",
        }, medtech_headers)
        validate_success(api.accession_specimen(specimen1["id"], accessioning_headers), 200)
        validate_success(api.begin_testing(specimen1["id"], medtech_headers), 200)

        specimen2 = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-1002", "patient_mrn": "MRN-5002",
            "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 3.0,
            "collection_at": "2026-09-01T06:00:00Z", "received_at": "2026-09-01T06:30:00Z",
            "transport_temperature": "AMBIENT", "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order2 = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id, "specimen_id": specimen2["id"],
            "order_number": "REQ-1002", "patient_mrn": "MRN-5002",
            "client_requested_at": "2026-09-01T06:36:00Z", "priority": "ROUTINE",
            "test_lines": [order_line(thyro["id"], 1)], "override_utilization_guard": False,
        }, accessioning_headers), 201)
        api.create_instrument_run({
            "test_catalog_entry_id": thyro["id"], "instrument_code": "IMM-02", "section": "CORE",
            "decontamination_buffer_minutes": 30,
            "reserved_start_at": "2026-09-01T09:30:00Z", "reserved_end_at": "2026-09-01T12:00:00Z",
        }, medtech_headers)
        validate_success(api.accession_specimen(specimen2["id"], accessioning_headers), 200)
        # PRD 3.6: the run advances to RUNNING only once the clock reaches its
        # reserved_start_at, so specimen 2 starts testing in its own window.
        set_clock("2026-09-01T10:00:00Z")
        validate_success(api.begin_testing(specimen2["id"], medtech_headers), 200)
        order2 = refresh_order(order2["id"])
        validate_success(api.enter_results(order2["id"], {
            "expected_send_out_order_version": order2["version"],
            "result_lines": [result_line(order2["test_lines"][0]["id"], 12.0)],
        }, medtech_headers), 200)
        set_clock("2026-09-01T10:00:00Z")
        release_order(order2["id"], "Thyroglobulin below the assay ceiling.")
        set_clock("2026-09-01T11:00:00Z")
        return {"client_id": client_id}


class TestSpecimenListingFilters:

    def test_pagination_counts_the_filtered_match_set(self, api, accessioning_headers):
        """PRD 3.1: "listing the specimens supports filtering by
        `client_laboratory_id`, `courier_run_id`, `aliquot_parent_id` and
        `status`".
        PRD 2.3: "`total_count` - the total number of resources matching the
        query, ignoring the window - and `has_more`, a boolean indicating whether
        further pages remain."

        Design: Corner/complexity_layers/specimen_listing_paginates_and_filters_by_status_together
        """
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        client_id = scenario["client"]["id"]
        courier_id = scenario["courier_run"]["id"]
        ids = []
        for index, (accession, mrn, offset, condition, reason) in enumerate([
            ("ACC-4401", "MRN-4401", 0, "ACCEPTABLE", None),
            ("ACC-4402", "MRN-4402", 1, "ACCEPTABLE", None),
            ("ACC-4403", "MRN-4403", 2, "ACCEPTABLE", None),
            ("ACC-4404", "MRN-4404", 3, "HEMOLYZED", "VISIBLE_HEMOLYSIS"),
        ]):
            specimen = validate_success(api.create_specimen({
                "client_laboratory_id": client_id, "courier_run_id": courier_id,
                "accession_number": accession, "patient_mrn": mrn,
                "specimen_type": "SERUM_SST", "container_type": "GOLD_SST", "volume_ml": 2.5,
                "collection_at": f"2026-08-31T22:{30 + offset}:00Z",
                "received_at": f"2026-09-01T00:{offset:02d}:00Z",
                "transport_temperature": "AMBIENT", "condition": condition,
                "condition_reason_code": reason,
            }, accessioning_headers), 201)
            ids.append(specimen["id"])
        validate_success(api.reject_specimen(ids[3], "HEMOLYSIS", accessioning_headers), 200)

        page1, meta1 = validate_paginated(api.list_specimens(
            accessioning_headers,
            params={"client_laboratory_id": client_id, "status": "RECEIVED", "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_specimens(
            accessioning_headers,
            params={"client_laboratory_id": client_id, "status": "RECEIVED", "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_rows, meta_all = validate_paginated(api.list_specimens(
            accessioning_headers, params={"client_laboratory_id": client_id}))
        assert len(all_rows) == 4
        assert meta_all["total_count"] == 4

        rejected, meta_rejected = validate_paginated(api.list_specimens(
            accessioning_headers, params={"client_laboratory_id": client_id, "status": "REJECTED"}))
        assert meta_rejected["total_count"] == 1
        assert rejected[0]["id"] == ids[3]

        assert validate_success(api.get_specimen(ids[0], accessioning_headers), 200)[
            "status"] == "RECEIVED"
        assert validate_success(api.get_specimen(ids[3], accessioning_headers), 200)[
            "status"] == "REJECTED"
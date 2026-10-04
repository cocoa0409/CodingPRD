"""Specimen acceptability: binding stability window, volume and transport bounds.

The stability window is the trickiest quantity in the PRD because it is derived
on every read and minimised across every test ordered against the specimen, so
this file exercises it through the endpoints that consume it rather than by
asserting a stored field.
"""
import pytest

from test_helpers import (
    add_on_payload,
    refresh_order,
    release_order,
    result_line,
    setup_active_client,
    setup_specimen_and_order,
    start_testing,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBindingWindowDerivation:

    def test_adding_a_shorter_window_test_shortens_remaining_stability(self, api, accessioning_headers):
        """PRD 2.5: "For a given specimen, the binding window is the smallest of
        these values taken over every test ordered against it, using the window
        that corresponds to the specimen's observed `transport_temperature`."
        PRD 3.5: "each new line's catalogue entry joins the set over which the
        specimen's binding window is minimised, so an add-on can only ever
        shorten the window."

        Design: Corner/calculations/remaining_stability_is_derived_from_the_binding_minimum_across_ordered_tests
        """
        scenario = self._long_and_short_pair(api, accessioning_headers)
        specimen_id = scenario["specimen"]["id"]
        order_id = scenario["order"]["id"]

        before = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert before["remaining_stability_hours"] == pytest.approx(70.5, abs=0.001), (
            "72-hour ferritin window less the 1.5 hours since collection"
        )

        added = validate_success(api.order_add_on_test(
            order_id, add_on_payload(scenario["short_entry"]["id"], 2, "2026-09-01T00:00:00Z"),
            accessioning_headers), 200)
        assert added is not None

        after = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert after["remaining_stability_hours"] == pytest.approx(0.5, abs=0.001), (
            "the two-hour lactate window now binds, less the same 1.5 elapsed hours"
        )
        assert after["version"] == before["version"], (
            "the specimen row was never written to, so the change is entirely derived"
        )
        data, meta = validate_paginated(api.list_order_test_lines(
            accessioning_headers, params={"send_out_order_id": order_id}))
        assert meta["total_count"] == 2

    def test_cancelling_the_short_window_line_restores_the_longer_window(
            self, api, ops_headers, accessioning_headers):
        """PRD 2.5: "the binding window is the smallest of these values taken
        over every test ordered against it".
        PRD 3.10: "lines in `CANCELLED` status are excluded from the count and
        contribute no charge at all."

        Design: Corner/calculations/no_portable_stability_evidence_when_an_ordered_test_is_cancelled
        """
        scenario = self._long_and_short_pair(api, accessioning_headers)
        specimen_id = scenario["specimen"]["id"]
        order_id = scenario["order"]["id"]

        # A second order on the same specimen holds the 72-hour ferritin line, so
        # the first order can be cancelled without removing every ordered test.
        # (PRD 3.4 cancels lines that are "not already cancelled", never the order
        # the withdrawal or rejection cascade is reading.)
        other = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["scenario"]["client"]["id"],
            "specimen_id": specimen_id,
            "order_number": "REQ-3402",
            "patient_mrn": "MRN-3402",
            "client_requested_at": "2026-08-31T22:36:00Z",
            "priority": "ROUTINE",
            "test_lines": [order_line(scenario["entry"]["id"], 1)],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        assert other is not None

        added = validate_success(api.order_add_on_test(
            order_id, add_on_payload(scenario["short_entry"]["id"], 2, "2026-08-31T22:36:00Z"),
            accessioning_headers), 200)
        short_line_id = [l for l in added["test_lines"]
                         if l["test_catalog_entry_id"] == scenario["short_entry"]["id"]][0]["id"]

        with_both = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert with_both["remaining_stability_hours"] == pytest.approx(0.5, abs=0.001)

        cancelled = validate_success(api.cancel_order(order_id, ops_headers), 200)
        assert cancelled["order_status"] == "CANCELLED"
        short_line = validate_success(api.get_order_test_line(short_line_id, ops_headers), 200)
        assert short_line["line_status"] == "CANCELLED"

        restored = validate_success(api.get_specimen(specimen_id, accessioning_headers), 200)
        assert restored["remaining_stability_hours"] == pytest.approx(70.5, abs=0.001), (
            "the cancelled line leaves the input set, so the ferritin window binds again"
        )
        assert restored["version"] == with_both["version"], (
            "the specimen row itself was never written to"
        )

    @staticmethod
    def _long_and_short_pair(api, accessioning_headers, both_lines_at_submit=False):
        """A 2.5 mL serum specimen ordered against a 72-hour and a 2-hour assay."""
        from test_helpers import TEST_USERS
        scenario = setup_active_client(
            entry_overrides={"stability_hours_ambient": 72, "stability_hours_refrigerated": 168},
            clock="2026-09-01T00:00:00Z")
        short = validate_success(api.create_catalog_entry({
            "test_code": "LACTATE_SERUM", "test_name": "Lactate, Serum",
            "test_category": "ROUTINE", "method": "PHOTOMETRY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 1.0, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 2, "stability_hours_refrigerated": 24,
            "stability_hours_frozen": 720, "base_tat_hours": 6,
            "list_price_cents": 1400, "client_price_cents": 1200, "floor_price_cents": 0,
            "critical_value_low": None, "critical_value_high": None,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 0.0,
            "is_utilization_managed": False,
        }, TEST_USERS["lab_client_admin_headers"]), 201)
        api.publish_catalog_entry(short["id"], TEST_USERS["lab_client_admin_headers"])

        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3401",
            "patient_mrn": "MRN-3401",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T22:30:00Z",
            "received_at": "2026-09-01T00:00:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        lines = [order_line(scenario["entry"]["id"], 1)]
        if both_lines_at_submit:
            lines.append(order_line(short["id"], 2))
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3401",
            "patient_mrn": "MRN-3401",
            "client_requested_at": "2026-08-31T22:35:00Z",
            "priority": "ROUTINE",
            "test_lines": lines,
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        return {"scenario": scenario, "entry": scenario["entry"],
                "short_entry": short, "specimen": specimen, "order": order}


class TestVolumeBound:

    def test_minimum_volume_is_inclusive_at_equality(self, api, accessioning_headers):
        """PRD 2.5: "the specimen's received volume in millilitres must be
        greater than or equal to the largest such declared minimum across every
        test ordered against it. The bound is inclusive - a specimen holding
        exactly the largest minimum passes".
        PRD 3.3: "when its `volume_ml` is at least the largest minimum volume
        across every test ordered against it, compared inclusively so that a
        specimen holding exactly the minimum passes".

        Design: Difficulty/boundary_precision_check/specimen_volume_lower_bound_is_inclusive_and_stability_crossing_is_rejected
        """
        scenario = self._volume_pair(api, accessioning_headers)
        exact = scenario["at_volume_specimen"]
        assert exact["volume_ml"] == 1.00

        accessioned = validate_success(api.accession_specimen(exact["id"], accessioning_headers), 200)
        assert accessioned["status"] == "ACCESSIONED", (
            "equality at the declared minimum passes the inclusive bound"
        )

    def test_volume_one_hundredth_below_the_minimum_is_refused(self, api, accessioning_headers):
        """PRD 2.5: "one holding less fails with
        `ERR_INSUFFICIENT_SPECIMEN_VOLUME`."
        PRD 3.5: "The order is created with its `order_status` set to
        `SUBMITTED`".

        Design: Difficulty/boundary_precision_check/specimen_volume_lower_bound_is_inclusive_and_stability_crossing_is_rejected
        """
        scenario = self._volume_pair(api, accessioning_headers)
        below = scenario["below_volume_specimen"]
        order = scenario["below_volume_order"]
        assert below["volume_ml"] == 0.99

        refused = api.accession_specimen(below["id"], accessioning_headers)
        validate_error(refused, "ERR_INSUFFICIENT_SPECIMEN_VOLUME", expected_status=422)

        assert refresh_order(order["id"])["order_status"] == "SUBMITTED", (
            "the failed accession did not bubble up, and the rejected specimen added nothing"
        )
        assert scenario["at_volume_specimen"]["volume_ml"] - below["volume_ml"] == pytest.approx(0.01), (
            "the two specimens differ by 0.01 mL only, so a zero-or-nonzero check would pass both"
        )

    @staticmethod
    def _volume_pair(api, accessioning_headers):
        scenario = setup_active_client(
            entry_overrides={"min_volume_ml": 1.0, "stability_hours_ambient": 12,
                             "stability_hours_refrigerated": 24, "reflex_condition": "NONE",
                             "reflex_min_remaining_hours": 12, "is_utilization_managed": False},
            clock="2026-09-01T07:00:00Z")
        entry_id = scenario["entry"]["id"]

        def _specimen(accession, mrn, volume):
            specimen = validate_success(api.create_specimen({
                "client_laboratory_id": scenario["client"]["id"],
                "courier_run_id": scenario["courier_run"]["id"],
                "accession_number": accession,
                "patient_mrn": mrn,
                "specimen_type": "SERUM_SST",
                "container_type": "GOLD_SST",
                "volume_ml": volume,
                "collection_at": "2026-09-01T05:00:00Z",
                "received_at": "2026-09-01T05:30:00Z",
                "transport_temperature": "AMBIENT",
                "condition": "ACCEPTABLE",
                "condition_reason_code": None,
            }, accessioning_headers), 201)
            order = validate_success(api.create_send_out_order({
                "client_laboratory_id": scenario["client"]["id"],
                "specimen_id": specimen["id"],
                "order_number": f"REQ-{accession}",
                "patient_mrn": mrn,
                "client_requested_at": "2026-09-01T05:05:00Z",
                "priority": "ROUTINE",
                "test_lines": [{"test_catalog_entry_id": entry_id, "line_sequence": 1}],
                "override_utilization_guard": False,
            }, accessioning_headers), 201)
            return specimen, order

        at_volume, order_at = _specimen("ACC-8301", "MRN-8401", 1.00)
        below_volume, order_below = _specimen("ACC-8302", "MRN-8402", 0.99)
        return {"scenario": scenario, "at_volume_specimen": at_volume, "at_volume_order": order_at,
                "below_volume_specimen": below_volume, "below_volume_order": order_below}


class TestStabilityBounds:

    def test_stability_bound_is_inclusive_while_the_reflex_bound_is_strict(self, api, accessioning_headers,
                                                                          medtech_headers,
                                                                          pathologist_headers):
        """PRD 3.3: "the elapsed time from the specimen's `collection_at` to the
        logical clock must not exceed the binding stability window, and the
        comparison is inclusive, so a specimen whose collection is exactly one
        full binding-window ago is still acceptable".
        PRD 3.8: "only when the specimen retains strictly more stability than the
        entry's `reflex_min_remaining_hours`, a bound on which equality fails,
        reported as `ERR_INSUFFICIENT_STABILITY_FOR_REFLEX`."

        Design: Difficulty/boundary_precision_check/reflex_stability_bound_is_strict_while_stability_bound_is_inclusive
        """
        scenario = self._reflex_boundary_scenario(api, accessioning_headers, medtech_headers,
                                                  pathologist_headers)
        assert scenario["accession_status"] == "ACCESSIONED", (
            "collection exactly one full 12-hour window before the clock accessions"
        )
        at_clock = validate_success(api.get_specimen(
            scenario["specimen"]["id"], accessioning_headers), 200)
        assert at_clock["collection_at"] == "2026-08-31T19:00:00Z"
        assert at_clock["remaining_stability_hours"] == pytest.approx(0.0, abs=0.001), (
            "an elapsed time exactly equal to the binding window leaves zero stability"
        )

        refused = api.order_reflex_test(scenario["order"]["id"], {
            "test_catalog_entry_id": scenario["target_entry"]["id"],
            "line_sequence": 2,
            "add_on_at": "2026-09-01T07:00:00Z",
        }, pathologist_headers)
        validate_error(refused, "ERR_INSUFFICIENT_STABILITY_FOR_REFLEX", expected_status=422)

        after = validate_success(api.get_specimen(
            scenario["specimen"]["id"], accessioning_headers), 200)
        assert after["remaining_stability_hours"] == pytest.approx(0.0, abs=0.001), (
            "the refused reflex changed nothing, and the strict bound refuses equality"
        )
        assert after["collection_at"] == "2026-08-31T19:00:00Z"

        data, meta = validate_paginated(api.list_order_test_lines(
            accessioning_headers, params={"send_out_order_id": scenario["order"]["id"]}))
        assert meta["total_count"] == 1, "the refused reflex appended no line"

    @staticmethod
    def _reflex_boundary_scenario(api, accessioning_headers, medtech_headers, pathologist_headers):
        """One specimen whose remaining stability is exactly 12.0 at the clock.

        Its order is released, the automatic reflex fires (the result is above
        the high limit), and the pending reflex is then withdrawn so the order
        sits back at RESULT_RELEASED with the triggering condition still met.
        """
        from test_helpers import TEST_USERS
        client_admin = TEST_USERS["lab_client_admin_headers"]
        # The reflex target must already be PUBLISHED when the shared entry is
        # published (PRD 3.4), and publishing it first also keeps the shared
        # entry's updated_at behind the certified build (PRD 2.8).
        target = validate_success(api.create_catalog_entry({
            "test_code": "FT4_FREE", "test_name": "Free T4, Serum",
            "test_category": "ROUTINE", "method": "IMMUNOASSAY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 0.5, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 12, "stability_hours_refrigerated": 24,
            "stability_hours_frozen": 720, "base_tat_hours": 6,
            "list_price_cents": 1800, "client_price_cents": 1500, "floor_price_cents": 700,
            "critical_value_low": None, "critical_value_high": None,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 12,
            "is_utilization_managed": False,
        }, client_admin), 201)
        api.publish_catalog_entry(target["id"], client_admin)
        scenario = setup_active_client(
            entry_overrides={
                "test_code": "TSH_REFLEX", "test_name": "Thyrotropin with Reflex to Free T4",
                "method": "IMMUNOASSAY", "stability_hours_ambient": 12,
                "stability_hours_refrigerated": 24, "base_tat_hours": 6,
                "list_price_cents": 2400, "client_price_cents": 2000, "floor_price_cents": 900,
                "critical_value_low": 0.01, "critical_value_high": 10.0,
                "reflex_test_code": "FT4_FREE", "reflex_condition": "RESULT_ABOVE_HIGH",
                "reflex_within_hours": 24, "reflex_min_remaining_hours": 12,
                "is_utilization_managed": False,
            },
            clock="2026-09-01T07:00:00Z")

        scenario = setup_specimen_and_order(
            scenario,
            specimen_overrides={
                "accession_number": "ACC-8201", "patient_mrn": "MRN-8301",
                "collection_at": "2026-08-31T19:00:00Z",
                "received_at": "2026-08-31T19:30:00Z",
            },
            run_overrides={"instrument_code": "IMM-09"})
        scenario = start_testing(scenario)
        accession_status = validate_success(api.get_specimen(
            scenario["specimen"]["id"], accessioning_headers), 200)
        assert accession_status["status"] == "IN_TESTING"
        order = refresh_order(scenario["order"]["id"])
        line_id = order["test_lines"][0]["id"]
        validate_success(api.enter_results(order["id"], {
            "expected_send_out_order_version": order["version"],
            "result_lines": [result_line(line_id, 12.5, "mIU/L",
                                         critical_value_notified_to="Dr. A. Reyes",
                                         critical_value_notified_at="2026-09-01T06:45:00Z")],
        }, medtech_headers), 200)

        released = release_order(order["id"], "Thyrotropin elevated; reflex free T4 ordered.")
        assert released["order_status"] == "REFLEX_PENDING", (
            "the result sits above the 10.0 high limit, so the reflex condition fires"
        )
        withdrawn = validate_success(api.reflex_cancel(order["id"], pathologist_headers), 200)
        assert withdrawn["order_status"] == "RESULT_RELEASED"

        return {"client": scenario["client"], "entry": scenario["entry"], "target_entry": target,
                "specimen": scenario["specimen"], "order": {"id": order["id"]},
                "accession_status": "ACCESSIONED"}


class TestTransportCondition:

    def test_transport_temperature_mismatch_is_refused_at_accessioning(self, api):
        """PRD 2.5: "Each catalogue entry declares exactly one accepted transport
        condition, drawn from `AMBIENT`, `REFRIGERATED` and `FROZEN`; the
        specimen's observed `transport_temperature` is drawn from the same three
        values and must equal the declared value for every ordered test, or the
        request fails with `ERR_TRANSPORT_TEMPERATURE_EXCEEDED`."

        Design: Corner/validations/transport_temperature_mismatch_returns_exceeded_on_accessioning
        """
        from test_helpers import TEST_USERS
        accessioning = TEST_USERS["accessioning_technologist_headers"]
        client_admin = TEST_USERS["lab_client_admin_headers"]
        scenario = setup_active_client(
            entry_overrides={
                "test_code": "LACTATE_PLASMA", "test_name": "Lactate, Plasma",
                "method": "PHOTOMETRY", "required_specimen_type": "PLASMA_LITHIUM_HEPARIN",
                "container_type": "GREEN_TOP", "transport_temperature": "REFRIGERATED",
                "stability_hours_ambient": 0.5, "stability_hours_refrigerated": 24,
                "list_price_cents": 1400, "client_price_cents": 1200, "floor_price_cents": 0,
                "critical_value_low": None, "critical_value_high": None,
                "reflex_test_code": None, "reflex_condition": "NONE",
                "reflex_min_remaining_hours": 6, "is_utilization_managed": False,
            },
            clock="2026-09-01T00:00:00Z")
        entry_id = scenario["entry"]["id"]
        assert client_admin is not None

        def _tube(accession, mrn, temperature):
            specimen = validate_success(api.create_specimen({
                "client_laboratory_id": scenario["client"]["id"],
                "courier_run_id": scenario["courier_run"]["id"],
                "accession_number": accession,
                "patient_mrn": mrn,
                "specimen_type": "PLASMA_LITHIUM_HEPARIN",
                "container_type": "GREEN_TOP",
                "volume_ml": 2.5,
                "collection_at": "2026-08-31T23:30:00Z",
                "received_at": "2026-09-01T00:00:00Z",
                "transport_temperature": temperature,
                "condition": "ACCEPTABLE",
                "condition_reason_code": None,
            }, accessioning), 201)
            order = validate_success(api.create_send_out_order({
                "client_laboratory_id": scenario["client"]["id"],
                "specimen_id": specimen["id"],
                "order_number": f"REQ-{accession}",
                "patient_mrn": mrn,
                "client_requested_at": "2026-08-31T23:35:00Z",
                "priority": "ROUTINE",
                "test_lines": [{"test_catalog_entry_id": entry_id, "line_sequence": 1}],
                "override_utilization_guard": False,
            }, accessioning), 201)
            return specimen, order

        ambient, ambient_order = _tube("ACC-3701", "MRN-3701", "AMBIENT")
        refrigerated, refrigerated_order = _tube("ACC-3702", "MRN-3702", "REFRIGERATED")

        refused = api.accession_specimen(ambient["id"], accessioning)
        validate_error(refused, "ERR_TRANSPORT_TEMPERATURE_EXCEEDED", expected_status=422)
        assert validate_success(api.get_specimen(ambient["id"], accessioning), 200)[
            "transport_temperature"] == "AMBIENT"

        accepted = validate_success(api.accession_specimen(refrigerated["id"], accessioning), 200)
        assert accepted["status"] == "ACCESSIONED", (
            "the sibling tube of the same assay arrived refrigerated and accessions cleanly"
        )
        assert refresh_order(ambient_order["id"])["order_status"] == "SUBMITTED"
        assert refresh_order(refrigerated_order["id"])["order_status"] == "ACCESSIONED"
        data, meta = validate_paginated(api.list_specimens(accessioning,
                                                          params={"status": "ACCESSIONED"}))
        assert meta["total_count"] == 1


class TestSpecimenUniqueness:

    def test_reusing_an_accession_number_is_refused(self, api, accessioning_headers):
        """PRD 3.2: "the accession number must be unique across specimens or the
        request fails with `ERR_DUPLICATE_ACCESSION_NUMBER`".

        Design: Corner/errors/specimen_create_with_a_reused_accession_number_returns_duplicate
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        body = {
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-4201",
            "patient_mrn": "MRN-4201",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T22:30:00Z",
            "received_at": "2026-09-01T00:00:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }
        first = validate_success(api.create_specimen(body, accessioning_headers), 201)

        reused = api.create_specimen(dict(
            body, patient_mrn="MRN-4202", collection_at="2026-08-31T22:35:00Z",
            received_at="2026-09-01T00:05:00Z"), accessioning_headers)
        validate_error(reused, "ERR_DUPLICATE_ACCESSION_NUMBER", expected_status=409)

        data, meta = validate_paginated(api.list_specimens(
            accessioning_headers, params={"client_laboratory_id": scenario["client"]["id"]}))
        assert meta["total_count"] == 1, "the second tube must not be stored"
        assert data[0]["patient_mrn"] == "MRN-4201"
        assert data[0]["id"] == first["id"]


class TestAliquotDerivation:

    def test_deleting_an_aliquot_under_the_wrong_parent_is_refused(self, api, accessioning_headers):
        """PRD 3.10: "Deleting a tube requires that the tube actually belongs to
        the parent named in the path, or the request fails with
        `ERR_ALIQUOT_PARENT_MISMATCH` (HTTP 409)".

        Design: Corner/endpoints/specimen_delete_of_an_aliquot_owned_by_another_parent_is_refused
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        client_id = scenario["client"]["id"]
        first_parent = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3901",
            "patient_mrn": "MRN-3901",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": client_id,
            "specimen_id": first_parent["id"],
            "order_number": "REQ-3901",
            "patient_mrn": "MRN-3901",
            "client_requested_at": "2026-08-31T20:45:00Z",
            "priority": "ROUTINE",
            "test_lines": [{"test_catalog_entry_id": scenario["entry"]["id"], "line_sequence": 1}],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)
        second_parent = validate_success(api.create_specimen({
            "client_laboratory_id": client_id,
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3902",
            "patient_mrn": "MRN-3902",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        assert order is not None
        # PRD 3.3: the specimen-level act bubbles the SUBMITTED order to
        # ACCESSIONED in the same transaction.
        validate_success(api.accession_specimen(first_parent["id"], accessioning_headers), 200)
        assert refresh_order(order["id"])["order_status"] == "ACCESSIONED"
        validate_success(api.accession_specimen(second_parent["id"], accessioning_headers), 200)

        aliquot = validate_success(api.create_aliquot(first_parent["id"], {
            "aliquot_volume_ml": 1.00,
            "container_type": "GOLD_SST",
            "accession_number": "ACC-3901-A1",
        }, accessioning_headers), 201)

        refused = api.delete_aliquot(second_parent["id"], aliquot["id"], accessioning_headers)
        validate_error(refused, "ERR_ALIQUOT_PARENT_MISMATCH", expected_status=409)

        parent = validate_success(api.get_specimen(first_parent["id"], accessioning_headers), 200)
        assert parent["total_aliquot_volume_ml"] == 1.00, "the misdirected delete moved nothing"
        other = validate_success(api.get_specimen(second_parent["id"], accessioning_headers), 200)
        assert other["total_aliquot_volume_ml"] == 0.00
        under_first, meta_first = validate_paginated(api.list_specimens(
            accessioning_headers, params={"aliquot_parent_id": first_parent["id"]}))
        under_second, meta_second = validate_paginated(api.list_specimens(
            accessioning_headers, params={"aliquot_parent_id": second_parent["id"]}))
        assert meta_first["total_count"] == len(under_first) == 1
        assert meta_second["total_count"] == len(under_second) == 0
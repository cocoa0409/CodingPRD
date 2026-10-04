"""Port congestion data collection (append-only, uniqueness, capacity
ceiling), the 400-family request-shape rules, and reverse FK listings."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_congestion_report,
    create_bond_payload,
    create_congestion_report_payload,
    create_oti_license_payload,
    file_complaint,
    file_service_contract,
    file_tariff,
    issue_invoice,
    make_alj_headers,
    make_carrier_rep_headers,
    make_counsel_headers,
    make_ombuds_officer_headers,
    make_shipper_rep_headers,
    open_dispute,
    publish_tariff,
    set_logical_clock,
    setup_carrier_shipper,
    setup_standard_billing,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


class TestCongestionReports:
    def test_congestion_report_is_append_only_without_version_fields(self):
        """PRD §2.5: "One resource family is exempt: the weekly port congestion
        report is an append-only data-collection record and carries only `id`
        and `created_at` — both `updated_at` and `version` are absent from it."
        PRD §3.9: "The triple of port, terminal, and week is unique — a
        resubmission is rejected with `ERR_DUPLICATE_CONGESTION_REPORT`
        (HTTP 409)".

        Design: Corner/entities/congestion_report_is_append_only_without_version_fields
        """
        set_logical_clock()
        payload = create_congestion_report_payload(
            port_code="USMOB", terminal_code="TERM-1",
            week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=100,
            gate_closures_hours=2, vessel_dwell_hours_avg=36.5)
        data = validate_success(api_client.create_congestion_report(payload, DOCKET), 201)
        assert_congestion_report(data)

        r2 = api_client.create_congestion_report(payload, DOCKET)
        validate_error(r2, ApiErrorId.ERR_DUPLICATE_CONGESTION_REPORT)

    def test_duplicate_congestion_report_rejected(self):
        """PRD §3.9: "The triple of port, terminal, and week is unique — a
        resubmission is rejected with `ERR_DUPLICATE_CONGESTION_REPORT`
        (HTTP 409)".

        Design: Corner/validations/duplicate_congestion_report_rejected
        """
        set_logical_clock()
        validate_success(api_client.create_congestion_report(
            create_congestion_report_payload(
                port_code="USSAV", terminal_code="TERM-1",
                week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=100,
                vessel_dwell_hours_avg=20.0), DOCKET), 201)
        r = api_client.create_congestion_report(
            create_congestion_report_payload(
                port_code="USSAV", terminal_code="TERM-1",
                week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=50,
                gate_closures_hours=1, vessel_dwell_hours_avg=22.0), DOCKET)
        validate_error(r, ApiErrorId.ERR_DUPLICATE_CONGESTION_REPORT)
        # Uniqueness is per triple: the same port/week under another terminal
        # is a different record.
        validate_success(api_client.create_congestion_report(
            create_congestion_report_payload(
                port_code="USSAV", terminal_code="TERM-2",
                week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=50,
                vessel_dwell_hours_avg=22.0), DOCKET), 201)


class TestPortCapacityCeiling:
    def test_port_week_berth_capacity_admits_exact_ceiling(self):
        """PRD §3.9: "a port's weekly berth capacity is bounded across
        terminals: the sum of `berth_occupancy_hours` over all reports sharing
        a `port_code` and `week_start` may not exceed 672 hours, or the
        submission is rejected with `ERR_PORT_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/port_week_berth_capacity_aggregate_ceiling
        """
        set_logical_clock()
        for i in range(1, 5):
            data = validate_success(api_client.create_congestion_report(
                create_congestion_report_payload(
                    port_code="USSEA", terminal_code=f"TERM-{i}",
                    week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=168,
                    vessel_dwell_hours_avg=48.0), DOCKET), 201)
            assert_congestion_report(data)
        # 4 x 168 == 672 equals the port-wide weekly capacity exactly, and
        # "may not exceed" admits equality.

    def test_port_week_berth_capacity_rejects_one_hour_over(self):
        """PRD §3.9: "the sum of `berth_occupancy_hours` over all reports sharing
        a `port_code` and `week_start` may not exceed 672 hours, or the
        submission is rejected with `ERR_PORT_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/port_week_berth_capacity_aggregate_ceiling
        """
        set_logical_clock()
        for i in range(1, 5):
            validate_success(api_client.create_congestion_report(
                create_congestion_report_payload(
                    port_code="USSEA", terminal_code=f"TERM-{i}",
                    week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=168,
                    vessel_dwell_hours_avg=48.0), DOCKET), 201)
        over = create_congestion_report_payload(
            port_code="USSEA", terminal_code="TERM-5",
            week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=1,
            vessel_dwell_hours_avg=10.0)
        r1 = api_client.create_congestion_report(over, DOCKET)
        validate_error(r1, ApiErrorId.ERR_PORT_CAPACITY_EXCEEDED)
        # The rejected report was not stored, so the identical retry hits the
        # capacity rule again — not the duplicate-triple rule.
        r2 = api_client.create_congestion_report(over, DOCKET)
        validate_error(r2, ApiErrorId.ERR_PORT_CAPACITY_EXCEEDED)


class TestRequestShape400Family:
    def test_request_shape_violations_return_400_family(self):
        """PRD §3.9: "A violation determination requires a `violation_count` of
        at least one — absent, the request fails with `ERR_INVALID_REQUEST`
        (HTTP 400)".
        PRD §3.7: "Closing with `outcome` `SETTLED` requires a
        `settlement_amount_cents` figure — absent, the request fails with
        `ERR_INVALID_REQUEST` (HTTP 400)".
        PRD §3.5: "The three dates must be coherent — availability no later than
        return, return no later than the last accrual date, and the last accrual
        date no later than the issuance instant — or the invoice is rejected with
        `ERR_INVALID_INVOICE_DATES` (HTTP 400)."
        PRD §3.9: "a `week_start` that must be the Monday of the reported week at
        midnight UTC — anything else fails with `ERR_INVALID_REQUEST`".

        Design: Corner/validations/request_shape_violations_return_400_family
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        complaint = file_complaint(env["shipper"]["id"], cid,
                                   [env["invoice"]["id"]],
                                   reparations_claimed_cents=50_000)
        validate_success(api_client.refer_ombuds(
            complaint["id"], {"ombuds_officer_id": "om-1"}, DOCKET), 200)
        proceeding = validate_success(api_client.create_proceeding(
            {"target_carrier_id": cid, "basis": "TARIFF_VIOLATION"},
            make_counsel_headers("ec-1")), 201)

        r1 = api_client.determine_proceeding(proceeding["id"],
                                             {"determination": "VIOLATION_FOUND"},
                                             make_alj_headers("alj-1"))
        validate_error(r1, ApiErrorId.ERR_INVALID_REQUEST)
        assert api_client.get_proceeding(proceeding["id"], DOCKET).json()["data"][
            "proceeding_status"] == "NOTICE_ISSUED"

        r2 = api_client.close_ombuds(complaint["id"], {"outcome": "SETTLED"},
                                     make_ombuds_officer_headers("om-1"))
        validate_error(r2, ApiErrorId.ERR_INVALID_REQUEST)
        assert api_client.get_complaint(complaint["id"], DOCKET).json()["data"][
            "complaint_status"] == "OMBUDS"

        r3 = api_client.create_invoice(cid, {
            "invoice_number": "INV-DATE-1", "charge_basis": "TARIFF",
            "tariff_id": env["tariff"]["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU9200008", "port_code": "USNYC",
            "availability_date": "2026-09-08T00:00:00Z",
            "return_date": "2026-09-04T00:00:00Z",
            "last_accrual_date": "2026-09-08T00:00:00Z"},
            make_carrier_rep_headers(cid))
        validate_error(r3, ApiErrorId.ERR_INVALID_INVOICE_DATES)

        r4 = api_client.create_congestion_report(
            create_congestion_report_payload(
                port_code="USHOU", terminal_code="TERM-1",
                week_start="2026-09-01T00:00:00Z",  # a Tuesday, not a Monday
                berth_occupancy_hours=10, vessel_dwell_hours_avg=5.0), DOCKET)
        validate_error(r4, ApiErrorId.ERR_INVALID_REQUEST)


class TestReverseListings:
    def test_fk_reverse_lists_resolve_children_from_parents(self):
        """PRD §3.4: "A carrier's licenses, with their embedded bonds and
        coverage totals, are listable by every role."
        PRD §3.5: "the listing accepts `carrier_id`, `billed_party_shipper_id`,
        `tariff_id`, and `service_contract_id` filters".
        PRD §3.3: "the listing accepts `carrier_id` and `shipper_id` filters."
        PRD §3.9: "The proceedings against a carrier are listable by every role."
        PRD §3.6: "The disputes on an invoice are listable by every role."
        PRD §3.7: "its `subject_invoice_ids` parameter carries a single invoice
        identifier and matches the complaints whose subject array contains it."

        Design: Corner/endpoints/fk_reverse_lists_resolve_children_from_parents
        """
        env = setup_carrier_shipper(org_type="NVOCC",
                                    carrier_name="Reachability NVOCC")
        carrier = env["carrier"]
        shipper = env["shipper"]
        license_ = validate_success(api_client.create_oti_license(
            carrier["id"], create_oti_license_payload(license_type="NVOCC"),
            make_carrier_rep_headers(carrier["id"])), 201)
        validate_success(api_client.append_surety_bond(license_["id"],
            create_bond_payload(bond_ref="B1", coverage_cents=7_500_000),
            make_carrier_rep_headers(carrier["id"])), 201)
        tariff = file_tariff(carrier["id"], tariff_code="DD-COR-1")
        set_logical_clock("2026-09-03T00:00:00Z")
        publish_tariff(carrier["id"], tariff["id"])
        contract = file_service_contract(carrier["id"], shipper["id"],
                                         contract_reference="SC-RT-1")
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(carrier["id"], shipper["id"],
                                tariff_id=tariff["id"])
        dispute = open_dispute(invoice["id"], shipper["id"],
                               dispute_reason="OTHER")
        complaint = file_complaint(shipper["id"], carrier["id"],
                                   [invoice["id"]], reparations_claimed_cents=50_000)
        proceeding = validate_success(api_client.create_proceeding(
            {"target_carrier_id": carrier["id"], "basis": "UNLICENSED_ACTIVITY"},
            make_counsel_headers("ec-1")), 201)

        cases = [
            (api_client.list_oti_licenses(carrier["id"], REVIEWER), license_["id"]),
            (api_client.list_invoices(REVIEWER, params={"tariff_id": tariff["id"]}),
             invoice["id"]),
            (api_client.list_service_contracts(REVIEWER,
                                               params={"shipper_id": shipper["id"]}),
             contract["id"]),
            (api_client.list_proceedings(carrier["id"], REVIEWER), proceeding["id"]),
            (api_client.list_disputes(invoice["id"], REVIEWER), dispute["id"]),
            (api_client.list_complaints(REVIEWER,
                                        params={"subject_invoice_ids": invoice["id"]}),
             complaint["id"]),
        ]
        for resp, expected_id in cases:
            rows, meta = validate_paginated(resp)
            assert meta["total_count"] == 1
            assert len(rows) == 1
            assert rows[0]["id"] == expected_id

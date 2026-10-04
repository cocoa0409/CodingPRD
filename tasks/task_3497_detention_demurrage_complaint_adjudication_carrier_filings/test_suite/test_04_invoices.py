"""Invoice issuance: required elements, defaults, computed-field discipline,
issuance window, cross-carrier references, the dual accrual variants, and the
tariff/license issuance gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_invoice,
    create_oti_license_payload,
    create_bond_payload,
    file_complaint,
    file_tariff,
    issue_invoice,
    make_carrier,
    make_carrier_rep_headers,
    publish_tariff,
    set_logical_clock,
    setup_carrier_shipper,
    setup_published_tariff,
    setup_standard_billing,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]


def _twin_tariff_env():
    """One VOCC carrier with two PUBLISHED tariffs differing only in
    accrual_method (free 4 days, 15000 cents/day), clock at 2026-09-15."""
    env = setup_carrier_shipper(carrier_name="Twin Tariff Lines")
    cid = env["carrier"]["id"]
    t_cal = file_tariff(cid, tariff_code="DD-CAL-01", charge_scope="DETENTION",
                        free_time_days=4, per_diem_rate_cents=15000,
                        accrual_method="CALENDAR")
    t_wd = file_tariff(cid, tariff_code="DD-WD-01", charge_scope="DETENTION",
                       free_time_days=4, per_diem_rate_cents=15000,
                       accrual_method="WORKING_DAY")
    set_logical_clock("2026-09-03T00:00:00Z")
    publish_tariff(cid, t_cal["id"])
    publish_tariff(cid, t_wd["id"])
    set_logical_clock("2026-09-15T00:00:00Z")
    return env, t_cal, t_wd


_TWIN_WINDOW = {
    "port_code": "USLAX",
    "availability_date": "2026-09-04T00:00:00Z",
    "return_date": "2026-09-14T12:00:00Z",
    "last_accrual_date": "2026-09-14T12:00:00Z",
}


class TestInvoiceChargeVariants:
    def test_invoice_charge_calendar_bills_seven_days_for_partial_window(self):
        """PRD §3.5: "Under `CALENDAR`, every started day bills: the elapsed
        seconds from the free-time end to `return_date` are divided by 86,400 —
        the number of seconds in a day — and the result is rounded up to a whole
        day, so any partial day bills as a full day while an exact whole-day span
        bills exactly."
        PRD §3.5: "The invoice's `amount_cents` is then `billable_days`
        multiplied by `per_diem_rate_cents`, an exact integer-cent figure."

        Design: Difficulty/dual_variant_calc/invoice_charge_calendar_vs_working_day_variants
        """
        env, t_cal, t_wd = _twin_tariff_env()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        inv_cal = issue_invoice(cid, sid, tariff_id=t_cal["id"],
                                invoice_number="INV-CAL-1",
                                container_number="MSKU1000001", **_TWIN_WINDOW)
        inv_wd = issue_invoice(cid, sid, tariff_id=t_wd["id"],
                               invoice_number="INV-WD-1",
                               container_number="MSKU1000002", **_TWIN_WINDOW)
        # CALENDAR: free_time_end 2026-09-08; 6.5 elapsed days ceil -> 7.
        assert inv_cal["billable_days"] == 7
        assert inv_cal["amount_cents"] == 105000
        # WORKING_DAY: only 2026-09-09/10/11/14 are weekdays in the window.
        assert inv_wd["billable_days"] == 4
        assert inv_wd["amount_cents"] == 60000
        assert inv_cal["amount_cents"] != inv_wd["amount_cents"], (
            "identical inputs diverge solely via accrual_method")

    def test_invoice_charge_copies_governing_tariff_fields(self):
        """PRD §3.5: "The server copies `free_time_days`, `per_diem_rate_cents`,
        and `accrual_method` from the governing document onto the invoice — the
        tariff's values under a `TARIFF` basis, the contract's negotiated values
        under a `SERVICE_CONTRACT` basis — and ignores any values the client sent
        for these three fields."
        PRD §3.5: "The invoice is stamped `issued_at` from the logical clock and
        its `invoice_status` enters `ISSUED`."

        Design: Difficulty/dual_variant_calc/invoice_charge_calendar_vs_working_day_variants
        """
        env, t_cal, t_wd = _twin_tariff_env()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        inv_cal = issue_invoice(cid, sid, tariff_id=t_cal["id"],
                                invoice_number="INV-CAL-1",
                                container_number="MSKU1000001", **_TWIN_WINDOW)
        inv_wd = issue_invoice(cid, sid, tariff_id=t_wd["id"],
                               invoice_number="INV-WD-1",
                               container_number="MSKU1000002", **_TWIN_WINDOW)
        for inv, method in ((inv_cal, "CALENDAR"), (inv_wd, "WORKING_DAY")):
            assert_invoice(inv)
            assert inv["free_time_days"] == 4
            assert inv["per_diem_rate_cents"] == 15000
            assert inv["accrual_method"] == method
            assert inv["invoice_status"] == "ISSUED"
            assert inv["issued_at"] == "2026-09-15T00:00:00Z"


class TestInvoiceCreationRules:
    def test_invoice_create_missing_container_number_returns_invalid_request(self):
        """PRD §3.5: "An invoice missing any required element — including the
        basis-conditional reference, `tariff_id` when the basis is `TARIFF` or
        `service_contract_id` when it is `SERVICE_CONTRACT` — is rejected with
        `ERR_INVOICE_MISSING_REQUIRED_ELEMENT` (HTTP 400)."

        Design: Corner/entities/invoice_create_missing_container_number_returns_invalid_request
        """
        env = setup_published_tariff()
        set_logical_clock("2026-09-10T00:00:00Z")
        carrier = env["carrier"]
        rep = make_carrier_rep_headers(carrier["id"])
        base = {
            "charge_basis": "TARIFF",
            "tariff_id": env["tariff"]["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU9000022",
            "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-08T00:00:00Z",
            "last_accrual_date": "2026-09-08T00:00:00Z",
        }
        no_container = {k: v for k, v in base.items() if k != "container_number"}
        r1 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-MISS-1", **no_container}, rep)
        validate_error(r1, ApiErrorId.ERR_INVOICE_MISSING_REQUIRED_ELEMENT)

        no_tariff = {k: v for k, v in base.items() if k != "tariff_id"}
        r2 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-MISS-2", **no_tariff}, rep)
        validate_error(r2, ApiErrorId.ERR_INVOICE_MISSING_REQUIRED_ELEMENT)

        rows, _meta = validate_paginated(api_client.list_invoices(
            DOCKET, params={"carrier_id": carrier["id"]}))
        assert rows == []

    def test_invoice_create_omitting_hold_fields_defaults_them_to_zero(self):
        """PRD §3.5: "Two optional incentive-principle factors,
        `government_hold_days` and `appointment_unavailable_days`, count days of
        the accrual window lost to government holds and to unavailable gate
        appointments; each defaults to zero and may not be negative."
        PRD §3.7: "The score starts at 100".

        Design: Corner/entities/invoice_create_omitting_hold_fields_defaults_them_to_zero
        """
        env = setup_standard_billing()
        invoice = env["invoice"]
        assert invoice["government_hold_days"] == 0
        assert invoice["appointment_unavailable_days"] == 0

        complaint = file_complaint(env["shipper"]["id"], env["carrier"]["id"],
                                   [invoice["id"]], reparations_claimed_cents=10000)
        assert complaint["incentive_principle_score"] == 100, (
            "no hold/appointment deductions and no congestion reports for USNYC")

    def test_invoice_create_client_supplied_amount_input_ignored(self):
        """PRD §3.5: "The charge itself is computed at issuance and is never
        client-supplied." and "The server copies `free_time_days`,
        `per_diem_rate_cents`, and `accrual_method` from the governing document
        onto the invoice ... and ignores any values the client sent for these
        three fields."

        Design: Corner/entities/invoice_create_client_supplied_amount_input_ignored
        """
        env = setup_published_tariff()
        set_logical_clock("2026-09-10T00:00:00Z")
        carrier = env["carrier"]
        data = validate_success(api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-CHEAT-1", "charge_basis": "TARIFF",
            "tariff_id": env["tariff"]["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU9000033", "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-08T00:00:00Z",
            "last_accrual_date": "2026-09-08T00:00:00Z",
            "amount_cents": 1, "free_time_days": 99,
            "per_diem_rate_cents": 1, "accrual_method": "WORKING_DAY"},
            make_carrier_rep_headers(carrier["id"])), 201)
        assert data["amount_cents"] == 10000, "server-computed 2 days x 5000"
        assert data["billable_days"] == 2
        assert data["free_time_days"] == 2
        assert data["per_diem_rate_cents"] == 5000
        assert data["accrual_method"] == "CALENDAR"

    def test_invoice_issued_31_days_rejected_30_exact_accepted(self):
        """PRD §3.5: "Timing is policed as well: an invoice may issue no later
        than thirty days after its `last_accrual_date`, and a later issuance is
        rejected with `ERR_LATE_INVOICE_ISSUANCE` (HTTP 422)."

        Design: Corner/validations/invoice_issued_31_days_rejected_30_exact_accepted
        """
        env = setup_published_tariff()
        carrier = env["carrier"]
        rep = make_carrier_rep_headers(carrier["id"])
        fields = {
            "charge_basis": "TARIFF",
            "tariff_id": env["tariff"]["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "port_code": "USNYC",
            "availability_date": "2026-08-28T00:00:00Z",
            "return_date": "2026-09-01T00:00:00Z",
            "last_accrual_date": "2026-09-01T00:00:00Z",
        }
        set_logical_clock("2026-10-01T00:00:00Z")
        data = validate_success(api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-ONTIME", "container_number": "MSKU9200002",
            **fields}, rep), 201)
        assert data["invoice_status"] == "ISSUED"

        set_logical_clock("2026-10-01T00:00:01Z")
        r2 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-LATE", "container_number": "MSKU9200003",
            **fields}, rep)
        validate_error(r2, ApiErrorId.ERR_LATE_INVOICE_ISSUANCE)

    def test_invoice_on_another_carriers_tariff_rejected(self):
        """PRD §3.5: "Under a `TARIFF` basis the named tariff must stand in
        `PUBLISHED` — otherwise `ERR_TARIFF_NOT_PUBLISHED` (HTTP 409) — and must
        belong to the invoicing carrier, otherwise `ERR_TARIFF_CARRIER_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/invoice_on_another_carriers_tariff_rejected
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        shipper = env["shipper"]
        carrier_b = make_carrier(org_type="VOCC", org_name="Neighbor Lines")
        t_nei = file_tariff(carrier_b["id"], tariff_code="DD-NEI-1")
        set_logical_clock("2026-09-03T00:00:00Z")
        publish_tariff(carrier_b["id"], t_nei["id"])
        set_logical_clock("2026-09-10T00:00:00Z")

        r = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-XREF-1", "charge_basis": "TARIFF",
            "tariff_id": t_nei["id"], "billed_party_shipper_id": shipper["id"],
            "container_number": "MSKU9200004", "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-08T00:00:00Z",
            "last_accrual_date": "2026-09-08T00:00:00Z"},
            make_carrier_rep_headers(carrier["id"]))
        validate_error(r, ApiErrorId.ERR_TARIFF_CARRIER_MISMATCH)
        rows, _meta = validate_paginated(api_client.list_invoices(
            DOCKET, params={"carrier_id": carrier["id"]}))
        assert rows == []


class TestAccrualEdgeCases:
    def test_calendar_accrual_ceils_one_second_past_free_time_to_a_full_day(self):
        """PRD §3.5: "the elapsed seconds from the free-time end to `return_date`
        are divided by 86,400 — the number of seconds in a day — and the result
        is rounded up to a whole day, so any partial day bills as a full day
        while an exact whole-day span bills exactly."

        Design: Corner/calculations/calendar_accrual_ceils_one_second_past_free_time_to_a_full_day
        """
        env = setup_published_tariff()
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(
            env["carrier"]["id"], env["shipper"]["id"],
            tariff_id=env["tariff"]["id"], invoice_number="INV-CEIL-1",
            container_number="MSKU9100001",
            availability_date="2026-09-04T00:00:00Z",
            return_date="2026-09-06T00:00:01Z",
            last_accrual_date="2026-09-06T00:00:01Z")
        # free_time_end is exactly 2026-09-06T00:00:00Z; one second over ceils up.
        assert invoice["billable_days"] == 1
        assert invoice["amount_cents"] == 5000

    def test_working_day_accrual_charges_zero_over_a_weekend_only_window(self):
        """PRD §3.5: "Under `WORKING_DAY`, the server enumerates the calendar
        dates strictly after the calendar date of the free-time end up to and
        including the calendar date of `return_date` and counts only those
        falling on a Monday, Tuesday, Wednesday, Thursday, or Friday; the time of
        day of `return_date` never adds a day, and identical inputs yield a count
        no larger than the calendar variant's."

        Design: Corner/calculations/working_day_accrual_charges_zero_over_a_weekend_only_window
        """
        env = setup_carrier_shipper()
        cid = env["carrier"]["id"]
        t_cal = file_tariff(cid, tariff_code="DD-COR-1", accrual_method="CALENDAR")
        t_wd = file_tariff(cid, tariff_code="DD-WD-2", charge_scope="DETENTION",
                           accrual_method="WORKING_DAY")
        set_logical_clock("2026-09-03T00:00:00Z")
        publish_tariff(cid, t_cal["id"])
        publish_tariff(cid, t_wd["id"])
        set_logical_clock("2026-09-10T00:00:00Z")

        window = {
            "port_code": "USNYC",
            "availability_date": "2026-09-02T00:00:00Z",
            "return_date": "2026-09-05T00:00:00Z",
            "last_accrual_date": "2026-09-05T00:00:00Z",
        }
        sid = env["shipper"]["id"]
        inv_wd = issue_invoice(cid, sid, tariff_id=t_wd["id"],
                               invoice_number="INV-WKD-1",
                               container_number="MSKU9100002", **window)
        inv_cal = issue_invoice(cid, sid, tariff_id=t_cal["id"],
                                invoice_number="INV-WKD-2",
                                container_number="MSKU9100003", **window)
        # free_time_end Friday 2026-09-04; the only in-window date is Saturday.
        assert inv_wd["billable_days"] == 0
        assert inv_wd["amount_cents"] == 0
        assert inv_cal["billable_days"] == 1
        assert inv_cal["amount_cents"] == 5000


class TestInvoiceIssuanceGates:
    def test_invoice_creation_requires_tariff_published_rejection(self):
        """PRD §3.5: "Under a `TARIFF` basis the named tariff must stand in
        `PUBLISHED` — otherwise `ERR_TARIFF_NOT_PUBLISHED` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_tariff_published
        """
        env = setup_carrier_shipper(carrier_name="Gatekeeper Lines")
        cid = env["carrier"]["id"]
        tariff = file_tariff(cid, tariff_code="DD-GATE-1",
                             effective_date="2026-09-02T00:00:00Z")
        set_logical_clock("2026-09-05T00:00:00Z")
        r = api_client.create_invoice(cid, {
            "invoice_number": "INV-GATE-1", "charge_basis": "TARIFF",
            "tariff_id": tariff["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU6000001", "port_code": "USNYC",
            "availability_date": "2026-09-03T00:00:00Z",
            "return_date": "2026-09-04T00:00:00Z",
            "last_accrual_date": "2026-09-04T00:00:00Z"},
            make_carrier_rep_headers(cid))
        validate_error(r, ApiErrorId.ERR_TARIFF_NOT_PUBLISHED)

    def test_invoice_creation_requires_tariff_published_then_zero_amount(self):
        """PRD §3.5: "When `return_date` falls at or before the free-time end,
        `billable_days` is zero and the charge is zero."
        PRD §3.2: "A successful publication moves `publication_status` to
        `PUBLISHED`".

        Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_tariff_published
        """
        env = setup_carrier_shipper(carrier_name="Gatekeeper Lines")
        cid = env["carrier"]["id"]
        tariff = file_tariff(cid, tariff_code="DD-GATE-1",
                             effective_date="2026-09-02T00:00:00Z")
        set_logical_clock("2026-09-05T00:00:00Z")
        r = api_client.create_invoice(cid, {
            "invoice_number": "INV-GATE-1", "charge_basis": "TARIFF",
            "tariff_id": tariff["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU6000001", "port_code": "USNYC",
            "availability_date": "2026-09-03T00:00:00Z",
            "return_date": "2026-09-04T00:00:00Z",
            "last_accrual_date": "2026-09-04T00:00:00Z"},
            make_carrier_rep_headers(cid))
        validate_error(r, ApiErrorId.ERR_TARIFF_NOT_PUBLISHED)

        publish_tariff(cid, tariff["id"])
        data = validate_success(api_client.create_invoice(cid, {
            "invoice_number": "INV-GATE-2", "charge_basis": "TARIFF",
            "tariff_id": tariff["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU6000002", "port_code": "USNYC",
            "availability_date": "2026-09-03T00:00:00Z",
            "return_date": "2026-09-05T00:00:00Z",
            "last_accrual_date": "2026-09-05T00:00:00Z"},
            make_carrier_rep_headers(cid)), 201)
        assert data["invoice_status"] == "ISSUED"
        assert data["billable_days"] == 0, "return exactly at free_time_end"
        assert data["amount_cents"] == 0

    def test_nvocc_invoice_requires_active_oti_license_absent(self):
        """PRD §3.5: "The invoicing carrier itself must be `ACTIVE` (otherwise
        `ERR_CARRIER_NOT_ACTIVE`), and an `NVOCC` or `OFF` carrier must hold an
        `ACTIVE` OTI license (otherwise `ERR_LICENSE_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/nvocc_invoice_requires_active_oti_license
        """
        env, tariff = self._unlicensed_nvocc()
        r = api_client.create_invoice(env["carrier"]["id"],
                                      self._lic_invoice(env, tariff, "INV-LIC-1",
                                                        "MSKU7000001"),
                                      make_carrier_rep_headers(env["carrier"]["id"]))
        validate_error(r, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

    def test_nvocc_invoice_requires_active_oti_license_pending_then_active(self):
        """PRD §3.5: "an `NVOCC` or `OFF` carrier must hold an `ACTIVE` OTI
        license (otherwise `ERR_LICENSE_NOT_ACTIVE`)".
        PRD §3.4: "if total available coverage has reached `required_bond_cents`
        and the license is not `ACTIVE`, it becomes `ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/nvocc_invoice_requires_active_oti_license
        """
        env, tariff = self._unlicensed_nvocc()
        cid = env["carrier"]["id"]
        rep = make_carrier_rep_headers(cid)

        r1 = api_client.create_invoice(
            cid, self._lic_invoice(env, tariff, "INV-LIC-1", "MSKU7000001"), rep)
        validate_error(r1, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

        license_ = validate_success(api_client.create_oti_license(
            cid, create_oti_license_payload(license_type="NVOCC"), rep), 201)
        assert license_["license_status"] == "PENDING_BOND"

        r2 = api_client.create_invoice(
            cid, self._lic_invoice(env, tariff, "INV-LIC-2", "MSKU7000002"), rep)
        validate_error(r2, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

        validate_success(api_client.append_surety_bond(license_["id"],
            create_bond_payload(bond_ref="B1", coverage_cents=7_500_000), rep), 201)

        data = validate_success(api_client.create_invoice(
            cid, self._lic_invoice(env, tariff, "INV-LIC-3", "MSKU7000003"), rep), 201)
        assert data["invoice_status"] == "ISSUED"

    @staticmethod
    def _unlicensed_nvocc():
        env = setup_carrier_shipper(org_type="NVOCC",
                                    carrier_name="Unlicensed Logistics")
        cid = env["carrier"]["id"]
        tariff = file_tariff(cid, tariff_code="DD-LIC-1",
                             effective_date="2026-09-02T00:00:00Z")
        set_logical_clock("2026-09-03T00:00:00Z")
        publish_tariff(cid, tariff["id"])
        set_logical_clock("2026-09-05T00:00:00Z")
        return env, tariff

    @staticmethod
    def _lic_invoice(env, tariff, number, container):
        return {
            "invoice_number": number, "charge_basis": "TARIFF",
            "tariff_id": tariff["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": container, "port_code": "USNYC",
            "availability_date": "2026-09-03T00:00:00Z",
            "return_date": "2026-09-04T00:00:00Z",
            "last_accrual_date": "2026-09-04T00:00:00Z",
        }

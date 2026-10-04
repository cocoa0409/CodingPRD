"""Service contracts: field round-trip, the 30-day filing window, the
bond-cascade gate on SERVICE_CONTRACT-basis invoicing, and the billed-party
consistency rule."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_invoice,
    assert_service_contract,
    create_service_contract_payload,
    file_service_contract,
    make_carrier_rep_headers,
    make_shipper,
    post_draw,
    set_logical_clock,
    setup_carrier_shipper,
    setup_nvocc_license,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["reviewer_headers"]
DOCKET = TEST_USERS["docket_headers"]


class TestServiceContractRetrieval:
    def test_service_contract_get_roundtrips_every_stored_field(self):
        """PRD §3.3: "A contract accepted for filing has its `contract_status`
        born `EFFECTIVE`".
        PRD §2.4: "Every timestamp the business rules consult — filing instants,
        issuance instants, decision instants, deadlines — is read from a
        server-side logical clock, never from wall-clock time."

        Design: Corner/entities/service_contract_get_roundtrips_every_stored_field
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        shipper = env["shipper"]
        set_logical_clock("2026-09-03T00:00:00Z")
        contract = file_service_contract(
            carrier["id"], shipper["id"], contract_reference="SC-RT-1",
            agreed_at="2026-09-02T00:00:00Z", duration_months=12,
            minimum_quantity_commitment=100, negotiated_free_time_days=3,
            negotiated_per_diem_rate_cents=12000,
            negotiated_accrual_method="CALENDAR")

        data = validate_success(api_client.get_service_contract(
            contract["id"], REVIEWER), 200)
        assert_service_contract(data)
        assert data["contract_reference"] == "SC-RT-1"
        assert data["shipper_id"] == shipper["id"]
        assert data["carrier_id"] == carrier["id"]
        assert data["duration_months"] == 12
        assert data["minimum_quantity_commitment"] == 100
        assert data["negotiated_free_time_days"] == 3
        assert data["negotiated_per_diem_rate_cents"] == 12000
        assert data["negotiated_accrual_method"] == "CALENDAR"
        assert data["contract_status"] == "EFFECTIVE"
        assert data["filed_at"] == "2026-09-03T00:00:00Z", (
            "filed_at renders the logical clock reading at filing")


class TestServiceContractFilingWindow:
    def test_service_contract_filed_31_days_rejected_30_exact_accepted(self):
        """PRD §3.3: "Filing is timely only within thirty days of execution: a
        filing whose `filed_at` falls later than thirty days after `agreed_at`
        is rejected with `ERR_LATE_SERVICE_CONTRACT_FILING` (HTTP 422)."

        Design: Corner/validations/service_contract_filed_31_days_rejected_30_exact_accepted
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        shipper = env["shipper"]
        rep = make_carrier_rep_headers(carrier["id"])

        set_logical_clock("2026-10-02T00:00:00Z")
        payload = create_service_contract_payload(
            shipper["id"], contract_reference="SC-ON-TIME",
            agreed_at="2026-09-02T00:00:00Z", duration_months=6,
            minimum_quantity_commitment=50)
        data = validate_success(api_client.create_service_contract(
            carrier["id"], payload, rep), 201)
        assert data["contract_status"] == "EFFECTIVE"

        set_logical_clock("2026-10-02T00:00:01Z")
        r2 = api_client.create_service_contract(carrier["id"],
            create_service_contract_payload(
                shipper["id"], contract_reference="SC-LATE",
                agreed_at="2026-09-02T00:00:00Z", duration_months=6,
                minimum_quantity_commitment=50), rep)
        validate_error(r2, ApiErrorId.ERR_LATE_SERVICE_CONTRACT_FILING)
        _rows, meta = validate_paginated(api_client.list_service_contracts(
            DOCKET, params={"carrier_id": carrier["id"]}))
        assert meta["total_count"] == 1, "the late filing stored nothing"


class TestServiceContractInvoiceGate:
    def test_suspended_contract_blocks_service_contract_invoicing(self):
        """PRD §3.5: "Under a `SERVICE_CONTRACT` basis the named contract must
        stand in `EFFECTIVE` — otherwise `ERR_CONTRACT_NOT_EFFECTIVE` (HTTP 409)".
        PRD §2.10: "When a draw leaves a license's total available coverage below
        its requirement, the license moves from `ACTIVE` to `SUSPENDED`, and every
        `EFFECTIVE` service contract of the carrier moves to `SUSPENDED` with it;
        when a reversal or a newly appended bond restores coverage up to the
        requirement, the license returns to `ACTIVE` and the suspended contracts
        return to `EFFECTIVE`."

        Design: Corner/validations/suspended_contract_blocks_service_contract_invoicing
        """
        env = setup_nvocc_license(bond_coverages=(7_500_000,),
                                  carrier_name="Gate NVOCC")
        carrier = env["carrier"]
        license_after_bond = env["license"]
        shipper = make_shipper()
        set_logical_clock("2026-09-03T00:00:00Z")
        contract = file_service_contract(carrier["id"], shipper["id"],
                                         contract_reference="SC-1")
        set_logical_clock("2026-09-10T00:00:00Z")

        drawn = post_draw(license_after_bond["id"], carrier["id"], "B1", 100,
                          license_after_bond["version"], reason="small claim")
        assert drawn["license_status"] == "SUSPENDED"

        invoice_fields = {
            "container_number": "MSKU9200010",
            "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-09T00:00:00Z",
            "last_accrual_date": "2026-09-09T00:00:00Z",
        }
        r1 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-GATED-1", "charge_basis": "SERVICE_CONTRACT",
            "service_contract_id": contract["id"],
            "billed_party_shipper_id": shipper["id"], **invoice_fields},
            make_carrier_rep_headers(carrier["id"]))
        validate_error(r1, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)

        post_draw(license_after_bond["id"], carrier["id"], "B1", -100,
                  drawn["version"], reason="claim repaid")
        data = validate_success(api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-GATED-2", "charge_basis": "SERVICE_CONTRACT",
            "service_contract_id": contract["id"],
            "billed_party_shipper_id": shipper["id"], **invoice_fields},
            make_carrier_rep_headers(carrier["id"])), 201)
        assert_invoice(data)
        assert data["amount_cents"] == 24000, (
            "3 free days from 2026-09-04 -> free_time_end 2026-09-07; "
            "return 2026-09-09 -> 2 days x 12000")

    def test_contract_basis_invoice_wrong_billed_party_rejected_then_correct_accepted(self):
        """PRD §3.5: "must belong to the invoicing carrier with the billed party
        as its contracting shipper; a contract owned by another carrier, or one
        whose `shipper_id` differs from the `billed_party_shipper_id`, is rejected
        with `ERR_BILLED_PARTY_NOT_CONTRACT_PARTY` (HTTP 422)."
        PRD §3.5: "The server copies `free_time_days`, `per_diem_rate_cents`, and
        `accrual_method` from the governing document onto the invoice".

        Design: Corner/validations/contract_basis_invoice_wrong_billed_party_rejected_then_correct_accepted
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        shipper = env["shipper"]
        shipper2 = make_shipper(company_name="Wrong Party Shippers",
                                contact_email="ops@wrong.example")
        set_logical_clock("2026-09-03T00:00:00Z")
        contract = file_service_contract(carrier["id"], shipper["id"],
                                         contract_reference="SC-RT-1")
        set_logical_clock("2026-09-10T00:00:00Z")

        invoice_fields = {
            "container_number": "MSKU9200005",
            "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-09T00:00:00Z",
            "last_accrual_date": "2026-09-09T00:00:00Z",
        }
        r1 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-SC-1", "charge_basis": "SERVICE_CONTRACT",
            "service_contract_id": contract["id"],
            "billed_party_shipper_id": shipper2["id"], **invoice_fields},
            make_carrier_rep_headers(carrier["id"]))
        validate_error(r1, ApiErrorId.ERR_BILLED_PARTY_NOT_CONTRACT_PARTY)

        data = validate_success(api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-SC-2", "charge_basis": "SERVICE_CONTRACT",
            "service_contract_id": contract["id"],
            "billed_party_shipper_id": shipper["id"], **invoice_fields},
            make_carrier_rep_headers(carrier["id"])), 201)
        assert data["amount_cents"] == 24000
        assert data["free_time_days"] == 3
        assert data["per_diem_rate_cents"] == 12000
        assert data["accrual_method"] == "CALENDAR"

"""Tests for the invoice lifecycle: dispute, resolve, pay, ledger conservation,
and the OCC patient plan update (PRD §3.7 and §2.9).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_invoice_ledger_conservation,
    create_patient,
    create_plan,
    get_invoice,
    get_patient,
    get_success_data,
    list_ledger_entries_for_invoice,
    make_ops_admin_headers,
    make_patient_headers,
    make_practice_staff_headers,
    setup_invoiced_practice,
    validate_error,
    validate_success,
)


class TestInvoiceDisputeCycleReturnsToIssued:
    def test_dispute_moves_invoice_to_disputed_and_charge_to_disputed(self, api):
        """PRD §3.7: "A valid dispute moves the invoice from `ISSUED` to `DISPUTED` and each named charge from `INVOICED` to `DISPUTED`."

        Design: Corner/state_machines/invoice_dispute_cycle_returns_to_issued
        """
        ctx = setup_invoiced_practice(num_bookings=2, copay_cents=10000)
        invoice = ctx["invoice"]
        from test_helpers import list_charges_for_invoice
        charges = list_charges_for_invoice(invoice["id"])
        c1 = charges[0]
        resp = api_client.dispute_invoice(
            invoice["id"],
            {"charge_ids": [c1["id"]], "reason": "verify attribution"},
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "DISPUTED"
        charge_after = get_success_data(api_client.get_charge(c1["id"], TEST_USERS["ops_admin_headers"]))
        assert charge_after["status"] == "DISPUTED"

    def test_keep_resolution_returns_invoice_to_issued_and_amount_unchanged(self, api):
        """PRD §3.7: "A `KEEP` returns the charge from `DISPUTED` to `INVOICED`."
        PRD §3.7: "After resolution the invoice returns to `ISSUED` and `amount_due_cents` is recomputed from the ledger."

        Design: Corner/state_machines/invoice_dispute_cycle_returns_to_issued
        """
        ctx = setup_invoiced_practice(num_bookings=2, copay_cents=10000)
        invoice = ctx["invoice"]
        from test_helpers import list_charges_for_invoice
        charges = list_charges_for_invoice(invoice["id"])
        c1 = charges[0]
        api_client.dispute_invoice(
            invoice["id"],
            {"charge_ids": [c1["id"]], "reason": "verify attribution"},
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        resp = api_client.resolve_dispute(
            invoice["id"],
            {"resolutions": [{"charge_id": c1["id"], "action": "KEEP"}]},
            TEST_USERS["ops_admin_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "ISSUED"
        assert data["amount_due_cents"] == 3000, (
            f"no credit posted for KEEP, amount_due must stay 3000, got {data['amount_due_cents']}"
        )
        charge_after = get_success_data(api_client.get_charge(c1["id"], TEST_USERS["ops_admin_headers"]))
        assert charge_after["status"] == "INVOICED"


class TestInvoiceLedgerConservationThroughDisputeCreditAndPayment:
    def _setup_two_charge_invoice(self):
        ctx = setup_invoiced_practice(num_bookings=2, copay_cents=10000)
        from test_helpers import list_charges_for_invoice
        charges = list_charges_for_invoice(ctx["invoice"]["id"])
        return ctx, charges

    def test_ledger_balance_at_every_step_and_final_zero(self, api):
        """PRD §3.7: "The invoice's `amount_due_cents` always equals the sum of the `amount_cents` values of its ledger entries and is recomputed on every ledger mutation."
        PRD §3.7: "A `REMOVE` moves the charge from `DISPUTED` to terminal `REFUNDED` and appends a `DISPUTE_CREDIT` ledger entry whose amount is the negative of that charge's `marketplace_fee_cents`."

        Design: Difficulty/compensating_invariant/invoice_ledger_conservation_through_dispute_credit_and_payment
        """
        ctx, charges = self._setup_two_charge_invoice()
        invoice = ctx["invoice"]
        c1, c2 = charges[0], charges[1]

        assert invoice["amount_due_cents"] == 3000
        entries = list_ledger_entries_for_invoice(invoice["id"])
        assert_invoice_ledger_conservation(invoice, entries)

        api_client.dispute_invoice(
            invoice["id"],
            {"charge_ids": [c1["id"]], "reason": "patient already knew us"},
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        resp = api_client.resolve_dispute(
            invoice["id"],
            {"resolutions": [{"charge_id": c1["id"], "action": "REMOVE"}]},
            TEST_USERS["ops_admin_headers"],
        )
        data = validate_success(resp)
        assert data["amount_due_cents"] == 1500, (
            f"after the -1500 DISPUTE_CREDIT, amount_due must be 1500, got {data['amount_due_cents']}"
        )
        entries = list_ledger_entries_for_invoice(invoice["id"])
        assert_invoice_ledger_conservation(data, entries)

        resp = api_client.pay_invoice(invoice["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        data = validate_success(resp)
        assert data["status"] == "PAID"
        assert data["amount_due_cents"] == 0
        entries = list_ledger_entries_for_invoice(invoice["id"])
        assert sum(e["amount_cents"] for e in entries) == 0, (
            f"ledger must sum to 0 after payment, got {sum(e['amount_cents'] for e in entries)}"
        )

        by_type = {}
        for e in entries:
            by_type.setdefault(e["entry_type"], []).append(e["amount_cents"])
        assert sorted(by_type["CHARGE_FEE"]) == [1500, 1500]
        assert by_type["DISPUTE_CREDIT"] == [-1500]
        assert by_type["PAYMENT"] == [-1500]

        c1_after = get_success_data(api_client.get_charge(c1["id"], TEST_USERS["ops_admin_headers"]))
        c2_after = get_success_data(api_client.get_charge(c2["id"], TEST_USERS["ops_admin_headers"]))
        assert c1_after["status"] == "REFUNDED"
        assert c2_after["status"] == "SETTLED"

    def test_amount_due_equals_ledger_sum_after_sweep(self, api):
        """PRD §3.7: "The sweep appends one `CHARGE_FEE` `LedgerEntry` per swept charge with `amount_cents` equal to that charge's positive `marketplace_fee_cents`, and — when `discount_cents` is greater than zero — one `TIER_DISCOUNT` entry with a negative amount equal to `discount_cents`."
        PRD §3.7: "The invoice's `amount_due_cents` always equals the sum of the `amount_cents` values of its ledger entries and is recomputed on every ledger mutation."

        Design: Difficulty/compensating_invariant/invoice_ledger_conservation_through_dispute_credit_and_payment
        """
        ctx, charges = self._setup_two_charge_invoice()
        invoice = get_invoice(ctx["invoice"]["id"])
        entries = list_ledger_entries_for_invoice(invoice["id"])
        assert_invoice_ledger_conservation(invoice, entries)
        charge_fee_entries = [e for e in entries if e["entry_type"] == "CHARGE_FEE"]
        assert len(charge_fee_entries) == 2
        for e in charge_fee_entries:
            assert e["amount_cents"] == 1500


class TestDisputeWrittenOffInvoiceExistenceBeatsState:
    def test_nonexistent_charge_on_written_off_invoice_returns_404(self, api):
        """PRD §2.7: "The first identifier that does not resolve to an existing resource short-circuits the request with the corresponding 404 error (`ERR_PRACTICE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, or `ERR_TYPE_NOT_FOUND`)."
        PRD §2.7: "No later check runs once an existence check has failed."
        PRD §3.7: "Every named charge must exist (`ERR_CHARGE_NOT_FOUND`), must belong to this invoice (`ERR_CHARGE_NOT_IN_INVOICE`), and must be `INVOICED` (otherwise `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/dispute_written_off_invoice_existence_beats_state
        """
        ctx = setup_invoiced_practice(num_bookings=1, copay_cents=10000)
        invoice = ctx["invoice"]
        # Write off the invoice so the state check (ERR_INVOICE_NOT_DISPUTABLE)
        # would also fail if it ran.
        api_client.write_off_invoice(invoice["id"], TEST_USERS["ops_admin_headers"])
        resp = api_client.dispute_invoice(
            invoice["id"],
            {"charge_ids": [NON_EXISTENT_UUID], "reason": "bogus"},
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_FOUND)

    def test_nonexistent_charge_on_issued_invoice_returns_404(self, api):
        """PRD §3.7: "Every named charge must exist (`ERR_CHARGE_NOT_FOUND`), must belong to this invoice (`ERR_CHARGE_NOT_IN_INVOICE`), and must be `INVOICED` (otherwise `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/dispute_written_off_invoice_existence_beats_state
        """
        ctx = setup_invoiced_practice(num_bookings=1, copay_cents=10000)
        invoice = ctx["invoice"]
        resp = api_client.dispute_invoice(
            invoice["id"],
            {"charge_ids": [NON_EXISTENT_UUID], "reason": "bogus"},
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_FOUND)


class TestOccPatientPlanUpdateStaleVersion:
    def test_current_version_patch_succeeds_and_bumps_version(self, api):
        """PRD §2.9: "The patient plan update requires a non-optional `expected_patient_version` field carrying the patient `version` the client last observed. A mismatch with the patient's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_patient_plan_update_stale_version_rejected
        """
        plan = create_plan()
        patient = create_patient()
        v1 = patient["version"]
        resp = api_client.update_patient(
            patient["id"],
            {"plan_id": plan["id"], "expected_patient_version": v1},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp)
        assert data["version"] == v1 + 1
        assert data["plan_id"] == plan["id"]

    def test_stale_version_patch_rejected_412_and_plan_unchanged(self, api):
        """PRD §2.9: "The patient plan update requires a non-optional `expected_patient_version` field carrying the patient `version` the client last observed. A mismatch with the patient's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Plan updates are idempotent by value but not by intent: a newer writer's plan choice must not be silently overwritten by a writer holding an older view."

        Design: Corner/cross_cutting_layers/occ_patient_plan_update_stale_version_rejected
        """
        plan = create_plan()
        patient = create_patient()
        v1 = patient["version"]
        api_client.update_patient(
            patient["id"],
            {"plan_id": plan["id"], "expected_patient_version": v1},
            make_patient_headers(patient["id"]),
        )
        resp = api_client.update_patient(
            patient["id"],
            {"plan_id": None, "expected_patient_version": v1},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        patient_after = get_patient(patient["id"])
        assert patient_after["plan_id"] == plan["id"], "stale patch must not overwrite the newer plan"

"""Corner coverage: state-machine transitions, lazy evaluation, side effects."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_delivered_order,
    create_issued_invoice,
    create_manufacturer,
    create_price_modification_payload,
    set_clock,
    setup_active_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
FIN = TEST_USERS["finance_ops_headers"]


class TestAgreementInvalidTransition:
    def test_terminate_from_draft_rejected(self, api):
        """PRD §3.9: "A ComplianceOfficer moves the agreement from ACTIVE to
        TERMINATED only when every sales report under the agreement is
        FINALIZED and every finalized report shows sb_goal_met true — a single
        unmet goal blocks termination with ERR_SB_GOAL_NOT_MET."
        PRD §2.10: "State validity — the target entity must be in a state
        from which the requested transition is valid; failure yields
        ERR_INVALID_STATE (HTTP 409). Applies to all action endpoints."

        Design: Corner/state_machines/terminate_from_draft_returns_invalid_state
        """
        manufacturer = create_manufacturer(legal_name="T Corp")
        resp = api.create_agreement(
            {
                "manufacturer_id": manufacturer["id"],
                "scope_tiers": ["FEDERAL"],
                "mfc_discount_pct": 0.20,
                "small_business_goal_pct": 0.10,
                "product_scope": ["SW-"],
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2027-01-01T00:00:00Z",
            },
            CM,
        )
        agreement = validate_success(resp, expected_status=201)
        assert agreement["status"] == "DRAFT"
        resp = api.terminate_agreement(agreement["id"], CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInvoiceLazyOverdue:
    def test_issued_invoice_flips_overdue_after_due_at(self, api):
        """PRD §3.8: "An invoice ages lazily: when the logical clock moves
        past due_at while the invoice is still ISSUED, the next read or sweep
        flips it to OVERDUE."
        PRD §3.8: "The invoice's due_at is issued_at advanced by
        payment_terms_days."

        Design: Corner/state_machines/invoice_overdue_lazy_evaluation
        """
        _, _, vehicle, price_list = setup_active_chain()
        order = create_delivered_order(vehicle["id"], price_list["id"])
        # Issued at 2026-10-01 with 30-day terms -> due 2026-10-31.
        invoice = create_issued_invoice(order["id"], period_label="2026-10",
                                        payment_terms_days=30)
        assert invoice["status"] == "ISSUED"
        set_clock("2026-11-15T00:00:00Z")
        invoice = validate_success(api.get_invoice(invoice["id"], FIN))
        assert invoice["status"] == "OVERDUE"


class TestPriceModificationApproval:
    def _setup_pending_modification(self, api):
        _, _, vehicle, price_list = setup_active_chain()
        order = create_delivered_order(
            vehicle["id"], price_list["id"], lines=[{"sku": "SW-1", "qty": 2}],
        )
        pl = validate_success(api.get_price_list(price_list["id"], CM))
        resp = api.create_price_modification(
            create_price_modification_payload(
                price_list["id"], pl["version"],
                new_offered_price_cents=9000,
            ),
            CM,
        )
        modification = validate_success(resp, expected_status=201)
        return vehicle, price_list, modification

    def test_approve_updates_line_and_prc_accumulator(self, api):
        """PRD §3.4: "On approval, the price line's offered_price_cents is
        overwritten with the new value, the vehicle's prc_accumulator_cents is
        recomputed, and both the modification's version and the list's version
        increment."
        PRD §3.4: "It is the sum, taken over each price line on the vehicle's
        currently ACTIVE list, of the line's price concession multiplied by
        the quantity sold: the concession is the greater of zero and
        basis_price_cents minus offered_price_cents, and it is multiplied by
        the line's sold_qty."

        Design: Corner/state_machines/price_modification_approve_updates_line_and_prc
        """
        vehicle, price_list, modification = self._setup_pending_modification(api)
        resp = api.approve_price_modification(modification["id"], CO)
        modification = validate_success(resp)
        assert modification["status"] == "APPROVED"
        lines, _meta = validate_paginated(api.list_price_list_lines(price_list["id"], CM))
        line = [l for l in lines if l["sku"] == "SW-1"][0]
        assert line["offered_price_cents"] == 9000
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        # concession = 20000 - 9000 = 11000; sold_qty = 2 -> 22000.
        assert vehicle["prc_accumulator_cents"] == 22000

"""Billing disputes: the ISSUED<->DISPUTED cycle, timely DENY/REDUCE/WAIVE
response branches, the exact-deadline boundary, and terminal lockdowns."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    issue_invoice,
    make_carrier_rep_headers,
    make_shipper_rep_headers,
    mark_paid,
    open_dispute,
    respond_dispute,
    set_logical_clock,
    setup_standard_billing,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]


def _two_invoice_env():
    """Standard billing plus a second identical 5000-cent invoice (window
    2026-09-04..2026-09-07 under the free-2-day, 5000/day tariff)."""
    env = setup_standard_billing()
    second = issue_invoice(
        env["carrier"]["id"], env["shipper"]["id"],
        tariff_id=env["tariff"]["id"], invoice_number="INV-DUE-B",
        container_number="MSKU5000002",
        availability_date="2026-09-04T00:00:00Z",
        return_date="2026-09-07T00:00:00Z",
        last_accrual_date="2026-09-07T00:00:00Z")
    env["invoice_b"] = second
    return env


class TestDisputeDenyReissueCycle:
    def test_dispute_deny_returns_invoice_to_issued_with_full_amount(self):
        """PRD §3.6: "A timely `DENY` must carry a `denial_justification` —
        without one the response is rejected with `ERR_JUSTIFICATION_REQUIRED`
        (HTTP 400) — and resolves the dispute as `DENIED`: `resolved_amount_cents`
        takes the invoice's full `amount_cents` and the invoice returns to
        `ISSUED`."
        PRD §3.6: "Opening the dispute moves the invoice from `ISSUED` to
        `DISPUTED`, stamps the dispute's `filed_at` from the logical clock, and
        sets `response_due_at` thirty days after filing".

        Design: Difficulty/non_linear_state_machine/invoice_dispute_deny_reissue_cycle
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        invoice = env["invoice"]
        dispute = open_dispute(invoice["id"], env["shipper"]["id"],
                               dispute_reason="CHARGE_EXCEEDS_PUBLISHED")
        mid = api_client.get_invoice(invoice["id"], DOCKET).json()["data"]
        assert mid["invoice_status"] == "DISPUTED"
        assert dispute["response_due_at"] == "2026-10-10T00:00:00Z", (
            "filed at the 2026-09-10 clock reading plus thirty days")

        resolved = respond_dispute(dispute["id"], cid, {
            "resolution": "DENY",
            "denial_justification": "Charge matches published tariff DD-COR-1"})
        assert resolved["resolution"] == "DENIED"
        assert resolved["resolved_amount_cents"] == 10000
        after = api_client.get_invoice(invoice["id"], DOCKET).json()["data"]
        assert after["invoice_status"] == "ISSUED"
        assert after["amount_cents"] == 10000

    def test_fresh_dispute_accepted_after_timely_deny(self):
        """PRD §3.6: "The billed party may contest an invoice while it stands in
        `ISSUED` status." — a timely DENY returns the invoice to `ISSUED`, so a
        fresh dispute re-enters `DISPUTED` with its own response clock.

        Design: Difficulty/non_linear_state_machine/invoice_dispute_deny_reissue_cycle
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        invoice = env["invoice"]
        d1 = open_dispute(invoice["id"], env["shipper"]["id"],
                          dispute_reason="CHARGE_EXCEEDS_PUBLISHED")
        respond_dispute(d1["id"], cid, {
            "resolution": "DENY",
            "denial_justification": "Charge matches published tariff DD-COR-1"})

        d2 = open_dispute(invoice["id"], env["shipper"]["id"],
                          dispute_reason="OTHER")
        assert d2["resolution"] == "PENDING"
        assert d2["response_due_at"] == "2026-10-10T00:00:00Z", (
            "the second dispute's clock is computed from its own filed_at")
        after = api_client.get_invoice(invoice["id"], DOCKET).json()["data"]
        assert after["invoice_status"] == "DISPUTED"


class TestDisputeResponseDeadline:
    def test_response_at_exact_deadline_is_timely_and_deny_stands(self):
        """PRD §3.6: "Timeliness is judged at the response instant: a response
        recorded on or before the deadline is timely; a response recorded at any
        instant after it is late."

        Design: Difficulty/boundary_precision_check/dispute_response_at_exact_deadline_vs_one_second_late
        """
        env = _two_invoice_env()
        set_logical_clock("2026-09-10T09:30:00Z")
        d_a = open_dispute(env["invoice"]["id"], env["shipper"]["id"],
                           dispute_reason="CHARGE_EXCEEDS_PUBLISHED")
        assert d_a["response_due_at"] == "2026-10-10T09:30:00Z"

        set_logical_clock("2026-10-10T09:30:00Z")
        resolved = respond_dispute(d_a["id"], env["carrier"]["id"], {
            "resolution": "DENY",
            "denial_justification": "Charge matches the published tariff"})
        assert resolved["resolution"] == "DENIED"
        assert resolved["response_was_late"] is False
        assert resolved["resolved_amount_cents"] == 10000, (
            "DENY takes the invoice's full amount_cents; the standard "
            "fixture invoice is 2 billable days x 5000 = 10000")
        inv = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "ISSUED"

    def test_response_one_second_late_forces_waiver_and_score_penalty(self):
        """PRD §3.6: "A late response loses the right to choose. Regardless of
        the requested resolution, a response recorded after `response_due_at`
        forces the dispute to `UPHELD_WAIVED`: `response_was_late` is set true,
        `resolved_amount_cents` becomes zero, the invoice is `VOIDED`, and the
        carrier's `compliance_score` drops by 25 points for the late response."

        Design: Difficulty/boundary_precision_check/dispute_response_at_exact_deadline_vs_one_second_late
        """
        env = _two_invoice_env()
        set_logical_clock("2026-09-10T09:30:00Z")
        d_b = open_dispute(env["invoice_b"]["id"], env["shipper"]["id"],
                           dispute_reason="CHARGE_EXCEEDS_PUBLISHED")

        set_logical_clock("2026-10-10T09:30:01Z")
        resolved = respond_dispute(d_b["id"], env["carrier"]["id"], {
            "resolution": "DENY", "denial_justification": "One second late"})
        assert resolved["resolution"] == "UPHELD_WAIVED"
        assert resolved["requested_resolution"] == "DENY"
        assert resolved["response_was_late"] is True
        assert resolved["resolved_amount_cents"] == 0
        inv = api_client.get_invoice(env["invoice_b"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "VOIDED"
        carrier = api_client.get_carrier(env["carrier"]["id"], DOCKET).json()["data"]
        assert carrier["compliance_score"] == 975, "1000 - 25 late-response penalty"


class TestDisputeStateGates:
    def test_disputed_invoice_rejects_markpaid_until_resolved(self):
        """PRD §3.6: "a `ShipperRep` whose account is the billed party marks an
        `ISSUED` invoice paid, moving it to the terminal `PAID` status; an
        invoice in any other state is rejected with `ERR_INVOICE_NOT_PAYABLE`
        (HTTP 409)."

        Design: Corner/state_machines/disputed_invoice_rejects_markpaid_until_resolved
        """
        env = setup_standard_billing()
        dispute = open_dispute(env["invoice"]["id"], env["shipper"]["id"],
                               dispute_reason="OTHER")
        resp = api_client.mark_invoice_paid(
            env["invoice"]["id"], make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)
        inv = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "DISPUTED"
        rows, _meta = validate_paginated(api_client.list_disputes(
            env["invoice"]["id"], DOCKET))
        assert rows[0]["id"] == dispute["id"]
        assert rows[0]["resolution"] == "PENDING"

    def test_respond_twice_returns_dispute_not_pending(self):
        """PRD §3.6: "a response to an already-resolved dispute is rejected with
        `ERR_DISPUTE_NOT_PENDING` (HTTP 409)".

        Design: Corner/state_machines/respond_twice_returns_dispute_not_pending
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        dispute = open_dispute(env["invoice"]["id"], env["shipper"]["id"],
                               dispute_reason="CHARGE_EXCEEDS_PUBLISHED")
        respond_dispute(dispute["id"], cid, {
            "resolution": "DENY", "denial_justification": "Matches published tariff"})
        resp = api_client.respond_to_dispute(dispute["id"], {"resolution": "WAIVE"},
                                             make_carrier_rep_headers(cid))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_PENDING)
        rows, _meta = validate_paginated(api_client.list_disputes(
            env["invoice"]["id"], DOCKET))
        assert rows[0]["resolution"] == "DENIED"
        inv = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "ISSUED"
        assert inv["amount_cents"] == 10000

    def test_voided_and_paid_invoices_reject_further_billing_actions(self):
        """PRD §3.6: "the invoice must stand in `ISSUED`, otherwise the filing is
        rejected with `ERR_INVOICE_NOT_DISPUTABLE` (HTTP 409)." and "an invoice in
        any other state is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409)."

        Design: Corner/state_machines/voided_and_paid_invoices_reject_further_billing_actions
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        inv_a = mark_paid(env["invoice"]["id"], sid)
        inv_b = issue_invoice(cid, sid, tariff_id=env["tariff"]["id"],
                              invoice_number="INV-COR-2",
                              container_number="MSKU9000002")
        d_b = open_dispute(inv_b["id"], sid, dispute_reason="INCORRECT_PARTY")
        respond_dispute(d_b["id"], cid, {"resolution": "WAIVE"})

        r1 = api_client.create_dispute(inv_a["id"], {"dispute_reason": "OTHER"},
                                       make_shipper_rep_headers(sid))
        validate_error(r1, ApiErrorId.ERR_INVOICE_NOT_DISPUTABLE)
        r2 = api_client.mark_invoice_paid(inv_b["id"], make_shipper_rep_headers(sid))
        validate_error(r2, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

        inv_a_now = api_client.get_invoice(inv_a["id"], DOCKET).json()["data"]
        inv_b_now = api_client.get_invoice(inv_b["id"], DOCKET).json()["data"]
        assert inv_a_now["invoice_status"] == "PAID"
        assert inv_b_now["invoice_status"] == "VOIDED"

    def test_reduce_not_lower_and_deny_without_justification_rejected(self):
        """PRD §3.6: "A timely `REDUCE` must carry a `reduced_amount_cents` that
        is present and strictly lower than the invoice's current `amount_cents` —
        an absent or insufficiently low figure is rejected with
        `ERR_REDUCED_AMOUNT_NOT_LOWER` (HTTP 400)". And: "A timely `DENY` must
        carry a `denial_justification` — without one the response is rejected
        with `ERR_JUSTIFICATION_REQUIRED` (HTTP 400)".

        Design: Corner/validations/reduce_not_lower_and_deny_without_justification_rejected
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        inv4 = issue_invoice(cid, sid, tariff_id=env["tariff"]["id"],
                             invoice_number="INV-COR-4",
                             container_number="MSKU9200009")
        d1 = open_dispute(env["invoice"]["id"], sid,
                          dispute_reason="CHARGE_EXCEEDS_PUBLISHED")
        d2 = open_dispute(inv4["id"], sid, dispute_reason="OTHER")
        rep = make_carrier_rep_headers(cid)

        r1 = api_client.respond_to_dispute(d1["id"], {
            "resolution": "REDUCE", "reduced_amount_cents": 10000}, rep)
        validate_error(r1, ApiErrorId.ERR_REDUCED_AMOUNT_NOT_LOWER)

        r2 = api_client.respond_to_dispute(d2["id"], {"resolution": "DENY"}, rep)
        validate_error(r2, ApiErrorId.ERR_JUSTIFICATION_REQUIRED)

        resolved = respond_dispute(d1["id"], cid, {
            "resolution": "REDUCE", "reduced_amount_cents": 4000})
        assert resolved["resolution"] == "UPHELD_REDUCED"
        assert resolved["resolved_amount_cents"] == 4000
        inv = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "ISSUED"
        assert inv["amount_cents"] == 4000, (
            "the reduced figure replaces the charge outright")

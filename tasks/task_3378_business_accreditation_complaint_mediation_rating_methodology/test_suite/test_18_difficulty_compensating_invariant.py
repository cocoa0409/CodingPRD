"""Difficulty queue — compensating invariants: a payment followed by
compensating refunds conserves the bureau's collected-dues total (PRD §3.1,
§3.3), and a complaint close followed by reopen conserves the business's
open+closed complaint count (PRD §3.4)."""

from datetime import timedelta

from test_helpers import (
    CLOCK_START_ISO,
    TEST_USERS,
    business_respond,
    consumer_accept,
    create_bureau,
    create_business,
    create_consumer,
    file_complaint,
    forward_complaint,
    get_application,
    get_business,
    get_complaint,
    ledger_entry_payload,
    make_business_rep_headers,
    parse_iso,
    run_daily_close,
    set_clock,
    setup_approved_application,
    setup_world,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def _collected(bureau_id):
    return run_daily_close(bureau_id)["dues_collected_cents"]


class TestDuesPaymentRefundConservation:
    def _setup_issued_invoice(self):
        world = setup_world(business_overrides={
            "legal_name": "Small Ledger LLC", "employee_count": 10,
            "founded_on": "2020-01-01T00:00:00Z"})
        app, invoice = setup_approved_application(world["business"])
        return world["bureau"], world["business"], app, invoice

    def test_collected_total_returns_to_zero(self, api):
        """PRD §3.1: "`dues_collected_cents`, the sum over every non-`VOID`
        dues invoice of businesses assigned to the bureau of the paid amount
        minus the refunded amount"
        PRD §3.3: "From `PARTIALLY_PAID`, a partial refund keeps the invoice
        `PARTIALLY_PAID` with the balance recomputed upward, while a refund
        equal to the net paid amount returns the invoice to `ISSUED` with the
        balance restored to the full `amount_due_cents`."

        Design: Difficulty/compensating_invariant/dues_payment_then_refunds_conserve_bureau_collected_total
        """
        bureau, business, _app, invoice = self._setup_issued_invoice()
        assert invoice["amount_due_cents"] == 64600  # 68000 * 0.95
        assert _collected(bureau["id"]) == 0
        # Full payment: ISSUED -> PAID, collected rises to the paid amount.
        paid = validate_success(api.post_ledger_entry(
            invoice["id"], ledger_entry_payload("PAYMENT", 64600),
            make_business_rep_headers(business["id"])), 201)
        assert paid["status"] == "PAID" and paid["balance_cents"] == 0
        assert _collected(bureau["id"]) == 64600
        # Partial refund: PAID -> PARTIALLY_PAID, balance recomputes upward.
        partial = validate_success(api.post_ledger_entry(
            invoice["id"], ledger_entry_payload("REFUND", 20000),
            ADMIN), 201)
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["balance_cents"] == 20000
        assert _collected(bureau["id"]) == 44600
        # Completing refund of the net paid amount: PARTIALLY_PAID -> ISSUED.
        final = validate_success(api.post_ledger_entry(
            invoice["id"], ledger_entry_payload("REFUND", 44600),
            ADMIN), 201)
        assert final["status"] == "ISSUED"
        assert final["balance_cents"] == 64600
        assert _collected(bureau["id"]) == 0, \
            "forward payment plus compensating refunds conserves the total"

    def test_refunds_never_revert_accreditation(self, api):
        """PRD §3.3: "Critically, refunds never revert the linked application
        or the business's `accreditation_status`: once a business is
        `ACCREDITED`, its standing is governed only by the suspension scan of
        §3.7."

        Design: Difficulty/compensating_invariant/dues_payment_then_refunds_conserve_bureau_collected_total
        """
        bureau, business, app, invoice = self._setup_issued_invoice()
        validate_success(api.post_ledger_entry(
            invoice["id"], ledger_entry_payload("PAYMENT", 64600),
            make_business_rep_headers(business["id"])), 201)
        assert get_application(business["id"], app["id"])["status"] == \
            "ACCREDITED"
        assert get_business(business["id"])["accreditation_status"] == \
            "ACCREDITED"
        validate_success(api.post_ledger_entry(
            invoice["id"], ledger_entry_payload("REFUND", 20000), ADMIN), 201)
        validate_success(api.post_ledger_entry(
            invoice["id"], ledger_entry_payload("REFUND", 44600), ADMIN), 201)
        assert get_application(business["id"], app["id"])["status"] == \
            "ACCREDITED", "refunds must not revert the application"
        assert get_business(business["id"])["accreditation_status"] == \
            "ACCREDITED", "refunds must not revert accreditation"
        assert _collected(bureau["id"]) == 0


class TestComplaintCloseReopenConservation:
    def _setup_two_filed(self):
        set_clock(CLOCK_START_ISO)
        create_bureau(name="Heartland Bureau",
                      territory_state_codes=["IA", "NE"],
                      local_dues_fee_cents=0)
        consumer = create_consumer(full_name="Pat Consumer",
                                   email="pat@example.com",
                                   home_state_code="IA")
        business = create_business(legal_name="BigBox Services Inc",
                                   home_state_code="IA", employee_count=250,
                                   founded_on="2018-01-01T00:00:00Z")
        c1 = file_complaint(consumer, business, category="SERVICE",
                            description="closes then reopens")
        c2 = file_complaint(consumer, business, category="BILLING",
                            description="untouched")
        return consumer, business, c1, c2

    def test_close_rebalances_open_and_closed(self, api):
        """PRD §3.4: "A `CONSUMER_ACCEPT` closes the complaint as `RESOLVED`:
        `resolution_outcome` becomes `CONSUMER_ACCEPTED`, `closed_at` is
        stamped, the business's `complaints_open_count` drops by 1 and its
        `complaints_closed_count` rises by 1, the trailing counters recompute,
        and a fresh `PROVISIONAL` rating snapshot is generated for the
        business."

        Design: Difficulty/compensating_invariant/complaint_close_then_reopen_conserves_total_filed_count
        """
        consumer, business, c1, _c2 = self._setup_two_filed()
        mirror = get_business(business["id"])
        assert mirror["complaints_open_count"] == 2
        assert mirror["complaints_closed_count"] == 0
        c1 = forward_complaint(c1)
        c1 = business_respond(c1, business, body="we fixed it")
        c1 = consumer_accept(c1, consumer, body="thanks")
        assert c1["status"] == "RESOLVED"
        assert c1["resolution_outcome"] == "CONSUMER_ACCEPTED"
        assert c1["closed_at"] is not None
        mirror = get_business(business["id"])
        assert mirror["complaints_open_count"] == 1
        assert mirror["complaints_closed_count"] == 1
        assert mirror["complaints_open_count"] + \
            mirror["complaints_closed_count"] == 2

    def test_reopen_restores_open_and_clears_closure_fields(self, api):
        """PRD §3.4: "Reopening increments `reopen_count` by 1, clears
        `resolution_outcome` and `closed_at` to null, stamps a fresh
        `forwarded_at` and a fresh 14-day `response_deadline_at`, and returns
        the complaint to `FORWARDED`; `complaints_open_count` rises by 1 and
        `complaints_closed_count` drops by 1, reopening an `UNANSWERED`
        complaint additionally reduces `complaints_unanswered_36m`, and the
        provisional rating regenerates."

        Design: Difficulty/compensating_invariant/complaint_close_then_reopen_conserves_total_filed_count
        """
        consumer, business, c1, c2 = self._setup_two_filed()
        c1 = forward_complaint(c1)
        c1 = business_respond(c1, business, body="we fixed it")
        c1 = consumer_accept(c1, consumer, body="thanks")
        resp = api.reopen_complaint(c1["id"], ADMIN)
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "FORWARDED"
        assert reopened["reopen_count"] == 1
        assert reopened["resolution_outcome"] is None
        assert reopened["closed_at"] is None
        assert parse_iso(reopened["response_deadline_at"]) == parse_iso(
            reopened["forwarded_at"]) + timedelta(days=14)
        mirror = get_business(business["id"])
        assert mirror["complaints_open_count"] == 2
        assert mirror["complaints_closed_count"] == 0
        assert mirror["complaints_open_count"] + \
            mirror["complaints_closed_count"] == 2
        assert get_complaint(c2["id"])["status"] == "RECEIVED", \
            "the sibling complaint is untouched"

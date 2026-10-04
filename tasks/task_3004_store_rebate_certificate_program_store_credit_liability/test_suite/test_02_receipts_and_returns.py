"""Receipts, tender splits, computed fields, returns, and fraud screening."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_store, create_account, create_receipt, cash_line,
    list_receipt_lines, process_return, setup_store_with_program,
    setup_issued_certificate, issue_certificate, submit_receipt,
    approve_submission, open_duplicate_receipt_flag,
    make_customer_headers, make_contractor_headers, create_job,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


def _instant(text):
    """Parse an ISO 8601 UTC timestamp for instant-level comparison."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
        timezone.utc)


class TestReceiptComputedFields:

    def test_receipt_total_cents_computed_not_accepted_from_input(self, api):
        """PRD §3.4: "From the splits, the system derives
        `certificate_tendered_cents`, the portion of the line funded by
        rebate certificates — the sum of splits of type
        `STORE_CREDIT_CERTIFICATE`."
        PRD §3.4: "The receipt's `total_cents` is the sum of line totals,
        gross of returns"

        Design: Corner/entities/receipt_total_cents_computed_not_accepted_from_input
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-ENT7")
        account = create_account(store["id"], owner_name="Ann")
        receipt = validate_success(api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-ENT7",
                "account_id": account["id"],
                "purchase_at": "2026-09-08T10:00:00Z",
                "total_cents": 999999,
                "lines": [
                    cash_line(1, "AAA", "TOOLS", 2, 5000),
                    cash_line(
                        2, "BBB", "TOOLS", 3, 2500,
                        extra_tenders=[{
                            "tender_type": "STORE_CREDIT_CERTIFICATE",
                            "amount_cents": 800,
                        }],
                    ),
                ],
            },
            GUEST,
        ), 201)
        assert receipt["total_cents"] == 17500, (
            f"total_cents must be computed as 2*5000 + 3*2500 = 17500, "
            f"got {receipt['total_cents']}"
        )
        lines = list_receipt_lines(store["id"], receipt["id"])
        by_number = {l["line_number"]: l for l in lines}
        assert by_number[1]["certificate_tendered_cents"] == 0
        assert by_number[2]["certificate_tendered_cents"] == 800

    def test_receipt_line_has_no_version_field_common_fields_false(self, api):
        """PRD §2.4: "`ReceiptLine` and `SubmissionLine` are line-level
        sub-resources that carry only `id` and `created_at`; both
        `updated_at` and `version` are absent from them."

        Design: Corner/entities/receipt_line_has_no_version_field_common_fields_false
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-ENT8")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 1000)],
            receipt_number="R-ENT8",
        )
        lines = list_receipt_lines(store["id"], receipt["id"])
        assert len(lines) == 1
        line = lines[0]
        assert line["id"] and line["created_at"]
        assert "version" not in line, "ReceiptLine must not carry version"
        assert "updated_at" not in line, "ReceiptLine must not carry updated_at"


class TestReceiptCreationRules:

    def test_clock_set_endpoint_echoes_new_time_and_defaults(self, api):
        """PRD §2.6: "Before any call has been made, the logical clock reads
        exactly `2026-09-01T00:00:00Z` as a fixed startup default. A
        `StoreAdmin`-only test-driving capability advances the logical clock
        to a supplied `to_iso8601` instant and returns the resulting
        `current_utc`; this capability exists so clients can drive
        time-dependent behavior deterministically."

        Design: Corner/endpoints/clock_set_endpoint_echoes_new_time_and_defaults
        """
        # clock never set: still at the 2026-09-01T00:00:00Z startup default
        store = create_store(store_code="S-EP6")
        account = create_account(store["id"], owner_name="Ann")
        receipt = validate_success(api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-EP6",
                "account_id": account["id"],
                # purchase exactly at the startup default instant: not "in
                # the future relative to the logical clock" (PRD §3.4)
                "purchase_at": "2026-09-01T00:00:00Z",
                "lines": [cash_line(1, "AAA", "TOOLS", 1, 1000)],
            },
            GUEST,
        ), 201)
        assert receipt["id"]
        clock = validate_success(
            api.set_logical_clock("2026-09-10T00:00:00Z", ADMIN)
        )
        # instants must match; the wire format's fractional-second spelling
        # (e.g. "…T00:00:00Z" vs "…T00:00:00.000Z") is not pinned by the PRD
        assert _instant(clock["current_utc"]) == _instant("2026-09-10T00:00:00Z")

    def test_tender_split_mismatch_rejected(self, api):
        """PRD §3.4: "the amounts across all of a line's tender splits must
        sum exactly to the line's quantity multiplied by its unit price, and
        any other total is rejected with `ERR_TENDER_SPLIT_MISMATCH` (422)."

        Design: Corner/validations/tender_split_mismatch_rejected
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-VAL1")
        account = create_account(store["id"], owner_name="Ann")
        resp = api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-VAL1",
                "account_id": account["id"],
                "purchase_at": "2026-09-08T10:00:00Z",
                "lines": [{
                    "line_number": 1, "sku": "AAA", "category": "TOOLS",
                    "quantity": 1, "unit_price_cents": 10000,
                    "tender_splits": [{"tender_type": "CASH", "amount_cents": 9900}],
                }],
            },
            GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_TENDER_SPLIT_MISMATCH)

    def test_future_receipt_rejected(self, api):
        """PRD §3.4: "The purchase timestamp must not be in the future
        relative to the logical clock, or the receipt is rejected with
        `ERR_RECEIPT_IN_FUTURE` (422)."

        Design: Corner/validations/future_receipt_rejected
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-VAL2")
        account = create_account(store["id"], owner_name="Ann")
        resp = api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-VAL2",
                "account_id": account["id"],
                "purchase_at": "2026-09-09T10:00:00Z",
                "lines": [cash_line(1, "AAA", "TOOLS", 1, 1000)],
            },
            GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_RECEIPT_IN_FUTURE)

    def test_duplicate_receipt_number_rejected(self, api):
        """PRD §3.4: "Guest service records a sale by creating a receipt with
        a register-assigned `receipt_number`, unique within the issuing store
        — reusing one is rejected with `ERR_DUPLICATE_RECEIPT_NUMBER` (409)"

        Design: Corner/validations/duplicate_receipt_number_rejected
        """
        set_clock("2026-09-08T12:00:00Z")
        s1 = create_store(store_code="S-VAL8A")
        s2 = create_store(store_code="S-VAL8B")
        account = create_account(s1["id"], owner_name="Ann")
        create_receipt(
            s1["id"], account["id"], [cash_line(1, "AAA", "TOOLS", 1, 1000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-DUP",
        )
        resp = api.create_receipt(
            s1["id"],
            {
                "receipt_number": "R-DUP",
                "account_id": account["id"],
                "purchase_at": "2026-09-08T11:00:00Z",
                "lines": [cash_line(1, "BBB", "TOOLS", 1, 500)],
            },
            GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECEIPT_NUMBER)
        other = validate_success(api.create_receipt(
            s2["id"],
            {
                "receipt_number": "R-DUP",
                "account_id": account["id"],
                "purchase_at": "2026-09-08T11:00:00Z",
                "lines": [cash_line(1, "BBB", "TOOLS", 1, 500)],
            },
            GUEST,
        ), 201)
        assert other["receipt_number"] == "R-DUP", (
            "the same receipt_number at a different store must succeed"
        )


class TestJobPurchaseRules:

    def test_job_purchase_on_retail_account_rejected(self, api):
        """PRD §3.4: "When `job_purchase_id` is present, it must reference a
        job owned by the purchasing account, that account must be a
        `CONTRACTOR` account, and the job must still be `OPEN`; any violation
        is rejected with `ERR_INVALID_JOB_PURCHASE` (422)."

        Design: Corner/validations/job_purchase_on_retail_account_rejected
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-VAL10")
        acc1 = create_account(store["id"], owner_name="Carl One",
                              account_type="CONTRACTOR")
        acc2 = create_account(store["id"], owner_name="Carl Two",
                              account_type="CONTRACTOR")
        job = create_job(store["id"], acc1["id"], job_reference="JOB-1")

        resp2 = api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-VAL10",
                "account_id": acc2["id"],
                "job_purchase_id": job["id"],
                "purchase_at": "2026-09-08T10:00:00Z",
                "lines": [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            },
            GUEST,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_JOB_PURCHASE)

    def test_job_purchase_settle_blocks_further_receipt_links(self, api):
        """PRD §3.3: "Only an `OPEN` job accepts receipt links, and only the
        owning contractor can settle a job, moving it from `OPEN` to
        `SETTLED`, after which it stops accepting new receipt links."

        Design: Corner/state_machines/job_purchase_settle_blocks_further_receipt_links
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-SM9")
        account = create_account(store["id"], owner_name="Carl Contractor",
                                 account_type="CONTRACTOR")
        job = create_job(store["id"], account["id"], job_reference="JOB-77")
        r1 = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            purchase_at="2026-09-08T10:00:00Z", job_purchase_id=job["id"],
            receipt_number="R-SM9-1",
        )
        settled = validate_success(api.settle_job(
            store["id"], job["id"], make_contractor_headers(account["id"])
        ))
        assert settled["status"] == "SETTLED"
        r1_read = validate_success(api.get_receipt(store["id"], r1["id"], GUEST))
        assert r1_read["job_purchase_id"] == job["id"], (
            "receipts created while the job was OPEN keep the link"
        )
        resp = api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-SM9-2",
                "account_id": account["id"],
                "job_purchase_id": job["id"],
                "purchase_at": "2026-09-08T11:00:00Z",
                "lines": [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            },
            GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_JOB_PURCHASE)


class TestReturns:

    def test_return_quantity_exceeding_sold_rejected(self, api):
        """PRD §3.8: "For every line, the cumulative returned quantity — the
        line's current `returned_quantity` plus this return's quantity — must
        not exceed the sold `quantity`; a return that would overshoot is
        rejected with `ERR_RETURN_QUANTITY_EXCEEDS_SOLD` (422)."

        Design: Corner/validations/return_quantity_exceeding_sold_rejected
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-VAL4")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 2, 1000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-VAL4",
        )
        process_return(store["id"], receipt["id"],
                       [{"line_number": 1, "quantity": 1}])
        resp = api.create_return(
            store["id"], receipt["id"],
            {"lines": [{"line_number": 1, "quantity": 2}]}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDS_SOLD)
        receipt_read = validate_success(
            api.get_receipt(store["id"], receipt["id"], GUEST)
        )
        assert receipt_read["status"] == "PARTIALLY_RETURNED"
        lines = list_receipt_lines(store["id"], receipt["id"])
        assert lines[0]["returned_quantity"] == 1, (
            "the earlier successful return is unaffected"
        )


class TestSplitTransactionScreening:

    def test_split_transaction_window_flags_three_receipt_cluster(self, api):
        """PRD §3.4: "When the count of those candidate receipts plus the new
        one reaches `split_txn_min_receipts`, and at least two receipts in
        the cluster share at least one SKU, the system creates a
        `SPLIT_TRANSACTION` fraud flag in `OPEN` status listing the
        cluster's receipt ids, with a machine-generated `detail` explaining
        the window edges and receipt numbers."

        Design: Difficulty/resource_temporal_overlap/split_transaction_window_half_open_left_edge
        """
        set_clock("2026-09-08T13:00:00Z")
        store = create_store(store_code="S-TO2")
        account = create_account(store["id"], owner_name="Ann")
        r_ids = []
        for i, ts in enumerate(
            ["2026-09-08T10:00:00Z", "2026-09-08T11:00:00Z", "2026-09-08T11:59:00Z"]
        ):
            r = create_receipt(
                store["id"], account["id"],
                [cash_line(1, "AAA", "TOOLS", 1, 1000)],
                purchase_at=ts, receipt_number=f"R-TO2-A{i+1}",
            )
            r_ids.append(r["id"])
        flags = get_success_data(api.list_fraud_flags(
            store["id"], FRAUD,
            params={"account_id": account["id"], "flag_type": "SPLIT_TRANSACTION"},
        ))
        assert len(flags) == 1, (
            f"expected exactly one SPLIT_TRANSACTION flag, got {len(flags)}"
        )
        flag = flags[0]
        assert flag["status"] == "OPEN"
        assert sorted(flag["receipt_ids"]) == sorted(r_ids)

    def test_split_transaction_window_excludes_open_left_edge(self, api):
        """PRD §3.4: "The split-transaction scan looks back from the new
        receipt's `purchase_at` over the account's other receipts at the same
        store, considering the half-open window that excludes the instant
        exactly `split_txn_window_hours` before the new purchase and includes
        the new receipt itself."

        Design: Difficulty/resource_temporal_overlap/split_transaction_window_half_open_left_edge
        """
        set_clock("2026-09-08T13:00:00Z")
        store = create_store(store_code="S-TO2B")
        account = create_account(store["id"], owner_name="Bob")
        # 10:00 receipt sits exactly on the 12:00 receipt's open left edge
        create_receipt(
            store["id"], account["id"], [cash_line(1, "AAA", "TOOLS", 1, 1000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-TO2-B1",
        )
        create_receipt(
            store["id"], account["id"], [cash_line(1, "AAA", "TOOLS", 1, 1000)],
            purchase_at="2026-09-08T12:00:00Z", receipt_number="R-TO2-B2",
        )
        flags = get_success_data(api.list_fraud_flags(
            store["id"], FRAUD, params={"account_id": account["id"]},
        ))
        assert flags == [], (
            f"the open left edge must exclude the 10:00 receipt, leaving a "
            f"2-receipt cluster below the 3-receipt minimum; got {flags!r}"
        )

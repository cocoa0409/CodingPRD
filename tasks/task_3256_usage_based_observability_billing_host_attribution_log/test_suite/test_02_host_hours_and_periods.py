"""Host attribution and the two billable counts (PRD §3.2), period lifecycle
gating (PRD §3.1, §3.9), and duplicate host-hour rejection."""
import math

from test_helpers import (
    ApiErrorId,
    OCT_START_UTC,
    assert_host_hour_record,
    create_host_hour_record_payload,
    get_meter_accumulator,
    post_host_hours,
    setup_account_with_period,
    setup_closed_period_with_draft_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BA, IA, PA, close_period, set_clock


def _close_and_get_period(api, account_id, period_id):
    set_clock(OCT_START_UTC)
    closed = validate_success(api.close_billing_period(account_id, period_id, BA))
    assert closed["status"] == "CLOSED"
    return closed


class TestDuplicateHostHour:
    def test_second_record_same_bucket_rejected(self, api):
        """PRD §3.2: "At most one record may exist per period per hour bucket; a
        duplicate submission for an already-recorded `hour_bucket_utc` within the
        same period is rejected with `ERR_DUPLICATE_HOST_HOUR`."

        Design: Corner/errors/duplicate_host_hour_record_rejected
        """
        account, period = setup_account_with_period(name="Dup")
        first = validate_success(
            api.create_host_hour_record(
                account["id"],
                period["id"],
                create_host_hour_record_payload(
                    infra_host_count=5, container_host_count=1,
                    serverless_invocation_count=10,
                ),
                IA,
            ),
            expected_status=201,
        )
        assert_host_hour_record(first)
        resp = api.create_host_hour_record(
            account["id"],
            period["id"],
            create_host_hour_record_payload(
                infra_host_count=99, container_host_count=0,
                serverless_invocation_count=0,
            ),
            IA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOST_HOUR.value)

    def test_same_bucket_different_period_allowed(self, api):
        """PRD §3.2: "At most one record may exist per period per hour bucket; a
        duplicate submission for an already-recorded `hour_bucket_utc` within the
        same period is rejected with `ERR_DUPLICATE_HOST_HOUR`."

        Design: Corner/errors/duplicate_host_hour_record_rejected
        """
        account, period1 = setup_account_with_period(name="DupOk")
        validate_success(
            api.create_host_hour_record(
                account["id"], period1["id"], create_host_hour_record_payload(), IA
            ),
            expected_status=201,
        )
        period2 = validate_success(
            api.create_billing_period(
                account["id"],
                {
                    "period_start_utc": "2026-10-01T00:00:00Z",
                    "period_end_utc": "2026-11-01T00:00:00Z",
                },
                BA,
            ),
            expected_status=201,
        )
        # Same bucket timestamp in a DIFFERENT period is not a duplicate.
        validate_success(
            api.create_host_hour_record(
                account["id"], period2["id"], create_host_hour_record_payload(), IA
            ),
            expected_status=201,
        )


class TestHostBillableCounts:
    def test_hwm_and_p99_diverge_charged_is_min(self, api):
        """PRD §3.2: "The **charged host count** actually billed for the period is
        the *smaller* of the two results — deliberately cheaper for the customer,
        and documented as the billing rule."
        PRD §3.9: "Close is a compound transaction with four effects. First, the
        host billable counts are computed and locked by the two algorithms of §3.2 —
        the high-water mark and the ninety-ninth percentile — and the charged host
        count is fixed as the smaller of the two."

        Design: Difficulty/dual_variant_calc/host_billable_count_hwm_vs_p99_diverge
        """
        account, period = setup_account_with_period(name="HWM vs P99")
        # 101 hour buckets: 100 hours at combined 12, plus a single spike hour at
        # combined 50. With n=101 the rank index is ceil(0.99*101)=100 (1-based),
        # so P99 is the 100th value (12) while the HWM is 50 — the two algorithms
        # diverge and the charged count is the smaller one.
        from datetime import datetime, timedelta

        base = datetime(2026, 9, 1, 0, 0, 0)
        samples = []
        for h in range(101):
            bucket = (base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if h == 50:
                samples.append((bucket, 40, 10, 100))  # combined 50 (spike)
            else:
                samples.append((bucket, 10, 2, 100))  # combined 12
        post_host_hours(account["id"], period["id"], samples)
        closed = _close_and_get_period(api, account["id"], period["id"])

        combined = sorted([12] * 100 + [50])
        rank = math.ceil(0.99 * len(combined))  # 100 (1-based)
        expected_p99 = combined[rank - 1]  # 12
        expected_hwm = 50
        assert expected_p99 == 12 and expected_hwm == 50

        lines = validate_success(
            api.list_invoices_flat(BA, params={"billing_period_id": period["id"]})
        )
        assert len(lines) == 1
        invoice_id = lines[0]["id"]
        invoice_lines = validate_success(
            api.list_invoice_lines(account["id"], invoice_id, BA)
        )
        host_lines = [l for l in invoice_lines if l["meter"] == "INFRA_HOST"]
        assert len(host_lines) == 1, "close must draft exactly one INFRA_HOST line"
        # Charged host count = min(HWM, P99) = 12, billed at the plan's
        # host_overage_rate_cents fallback (no commitment) = 1500 cents/host.
        assert host_lines[0]["rated_quantity"] == expected_p99

    def test_p99_rank_index_computation(self, api):
        """PRD §3.2: "The combined footprints are sorted in ascending order; with
        `n` records, the rank index is the number of records multiplied by 0.99 and
        rounded up to a whole number (a 1-based index); the billable count is the
        value at that rank."
        PRD §3.2: "High-water mark. The billable count is the single largest
        combined host footprint observed across all hour buckets in the period."

        Design: Difficulty/dual_variant_calc/host_billable_count_hwm_vs_p99_diverge
        """
        account, period = setup_account_with_period(name="P99 rank")
        # 4 hours: combined [7, 20, 9, 8] -> rank = ceil(3.96) = 4 -> P99 = 20 = HWM.
        samples = [
            ("2026-09-01T00:00:00Z", 5, 2, 0),
            ("2026-09-01T01:00:00Z", 15, 5, 0),
            ("2026-09-01T02:00:00Z", 7, 2, 0),
            ("2026-09-01T03:00:00Z", 6, 2, 0),
        ]
        post_host_hours(account["id"], period["id"], samples)
        _close_and_get_period(api, account["id"], period["id"])
        invoices = validate_success(
            api.list_invoices_flat(BA, params={"billing_period_id": period["id"]})
        )
        invoice_lines = validate_success(
            api.list_invoice_lines(account["id"], invoices[0]["id"], BA)
        )
        host_lines = [l for l in invoice_lines if l["meter"] == "INFRA_HOST"]
        assert host_lines[0]["rated_quantity"] == 20

    def test_empty_hour_set_charged_count_zero(self, api):
        """PRD §3.2: "Both variants treat a record's combined host footprint as the
        sum of its `infra_host_count` and `container_host_count`, and both return 0
        when no records exist".
        PRD §3.9: "a draft **Invoice** is created in `DRAFT` status with one
        **InvoiceLine** per meter whose period quantity is non-zero".

        Design: Difficulty/boundary_precision_check/hwm_empty_hour_set_yields_zero
        """
        account, period = setup_account_with_period(name="Empty Set Test")
        closed = _close_and_get_period(api, account["id"], period["id"])
        assert closed["status"] == "CLOSED"
        invoices = validate_success(
            api.list_invoices_flat(BA, params={"billing_period_id": period["id"]})
        )
        assert len(invoices) == 1
        lines = validate_success(
            api.list_invoice_lines(account["id"], invoices[0]["id"], BA)
        )
        # Charged host count is 0 (empty set); a zero-quantity meter gets no line.
        host_lines = [l for l in lines if l["meter"] == "INFRA_HOST"]
        assert host_lines == [] or all(l["rated_quantity"] == 0 for l in host_lines)

    def test_empty_hour_set_close_still_succeeds(self, api):
        """PRD §3.2: "Both variants treat a record's combined host footprint as the
        sum of its `infra_host_count` and `container_host_count`, and both return 0
        when no records exist".
        PRD §3.9: "a `BillingAdmin` may close it, moving the period from `OPEN` to
        `CLOSED`."

        Design: Difficulty/boundary_precision_check/hwm_empty_hour_set_yields_zero
        """
        account, period = setup_account_with_period(name="Empty Close")
        closed = _close_and_get_period(api, account["id"], period["id"])
        assert closed["status"] == "CLOSED"
        # The close response round-trips through a fetch of the same period.
        fetched = validate_success(
            api.get_billing_period(account["id"], period["id"], BA)
        )
        assert fetched["status"] == "CLOSED"


class TestPeriodOpenGate:
    def test_log_ingest_rejected_after_close(self, api):
        """PRD §3.1: "Every mutation that writes usage into a period — recording a
        host-hour sample, ingesting a log event, posting a usage record, reindexing
        an excluded event — requires the period to still be `OPEN`; against a
        `CLOSED` or `SETTLED` period the write is rejected with `ERR_PERIOD_CLOSED`."

        Design: Corner/validations/period_closed_rejects_log_ingest
        """
        from test_helpers import setup_period_with_retention_tier, create_log_event_payload

        account, period, tier = setup_period_with_retention_tier(name="PC")
        close_period(account["id"], period["id"])
        resp = api.ingest_log_event(
            account["id"],
            period["id"],
            create_log_event_payload(
                size_bytes=100, service_tag="x",
                ingested_at_utc="2026-10-02T00:00:00Z",
                retention_tier_id=tier["id"],
            ),
            IA,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)

    def test_host_hour_rejected_after_close(self, api):
        """PRD §3.1: "Every mutation that writes usage into a period — recording a
        host-hour sample, ingesting a log event, posting a usage record, reindexing
        an excluded event — requires the period to still be `OPEN`; against a
        `CLOSED` or `SETTLED` period the write is rejected with `ERR_PERIOD_CLOSED`."

        Design: Corner/validations/period_closed_rejects_log_ingest
        """
        account, period = setup_account_with_period(name="PC-host")
        close_period(account["id"], period["id"])
        resp = api.create_host_hour_record(
            account["id"], period["id"], create_host_hour_record_payload(), IA
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)

    def test_usage_record_rejected_after_close(self, api):
        """PRD §3.1: "Every mutation that writes usage into a period — recording a
        host-hour sample, ingesting a log event, posting a usage record, reindexing
        an excluded event — requires the period to still be `OPEN`; against a
        `CLOSED` or `SETTLED` period the write is rejected with `ERR_PERIOD_CLOSED`."

        Design: Corner/validations/period_closed_rejects_log_ingest
        """
        account, period = setup_account_with_period(name="PC-usage")
        close_period(account["id"], period["id"])
        resp = api.create_usage_record(
            account["id"], period["id"], {"meter": "TRACE", "quantity": 1}, IA
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)

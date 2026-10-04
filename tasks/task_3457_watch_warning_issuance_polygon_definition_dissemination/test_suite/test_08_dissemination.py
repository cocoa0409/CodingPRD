"""Dissemination: dispatch, retries, settlement, and record cardinality.

Records are created per eligible channel at issue time, dispatched by clock
advances while their product is ISSUED, settled through the platform
capability, and withdrawn (never deleted) on cancel (PRD §3.5, §3.6, §3.7).
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    cancel_product,
    create_alert_channel,
    get_product,
    get_record,
    list_records,
    make_admin_headers,
    set_clock,
    setup_issued_warning,
    validate_error,
    validate_success,
)

WEA_CONFIRM = {
    "channel_type": "WEA",
    "supports_levels": ["WARNING"],
    "max_message_chars": 360,
    "requires_confirmation": True,
}
EAS_AUTO = {"channel_type": "EAS", "supports_levels": ["WATCH", "WARNING"], "max_message_chars": 1800}
DATA_FEED_AUTO = {
    "channel_type": "DATA_FEED",
    "supports_levels": ["WATCH", "ADVISORY", "WARNING"],
    "max_message_chars": 4000,
}


def _instant(value):
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _settle(api, record_id, outcome):
    """Settle a record through the unprefixed PlatformAdmin capability."""
    return validate_success(
        api.settle_dissemination_record(record_id, outcome, make_admin_headers())
    )


class TestRetryCycle:
    def test_failed_settle_requeues_below_max_retries(self, api):
        """PRD §3.6: "A `FAILED` outcome increments `retry_count` by one: while
        the count remains below the three-attempt maximum the record
        immediately returns to `QUEUED` with `queued_at` refreshed, beginning
        the retry cycle again"
        PRD §3.6: "when the logical clock advances, every `QUEUED` record whose
        product is `ISSUED` transitions to `SENT` with `sent_at` stamped"

        Design: Difficulty/non_linear_state_machine/dissemination_record_retry_cycle_to_dead
        """
        bundle = setup_issued_warning(api, channels=[dict(WEA_CONFIRM, name="WEA-RETRY")])
        record = bundle.records[0]
        assert record["status"] == "QUEUED"

        set_clock(api, "2026-09-01T10:05:00Z")
        record = get_record(api, record["id"], bundle.headers)
        assert record["status"] == "SENT", "requires_confirmation holds it short of CONFIRMED"
        assert _instant(record["sent_at"]) == _instant("2026-09-01T10:05:00Z")

        settled = _settle(api, record["id"], "FAILED")
        assert settled["status"] == "QUEUED" and settled["retry_count"] == 1

        set_clock(api, "2026-09-01T10:07:00Z")
        assert get_record(api, record["id"], bundle.headers)["status"] == "SENT", (
            "the retry cycle looped back through dispatch"
        )
        settled = _settle(api, record["id"], "FAILED")
        assert settled["status"] == "QUEUED" and settled["retry_count"] == 2

    def test_third_failed_settle_terminates_dead(self, api):
        """PRD §3.6: "A `FAILED` outcome increments `retry_count` by one: while
        the count remains below the three-attempt maximum the record
        immediately returns to `QUEUED` with `queued_at` refreshed, beginning
        the retry cycle again, and at exactly three failed attempts the record
        terminates as `DEAD`."

        Design: Difficulty/non_linear_state_machine/dissemination_record_retry_cycle_to_dead
        """
        bundle = setup_issued_warning(api, channels=[dict(WEA_CONFIRM, name="WEA-RETRY")])
        record_id = bundle.records[0]["id"]
        for minute in ("2026-09-01T10:05:00Z", "2026-09-01T10:07:00Z", "2026-09-01T10:09:00Z"):
            set_clock(api, minute)
            settled = _settle(api, record_id, "FAILED")
        assert settled["status"] == "DEAD", "MAX_RETRIES reached: terminal"
        assert settled["retry_count"] == 3
        record = get_record(api, record_id, bundle.headers)
        assert record["status"] == "DEAD"
        assert record["sent_at"] is not None
        assert _instant(record["sent_at"]) == _instant("2026-09-01T10:09:00Z"), (
            "sent_at reflects the last dispatch"
        )


class TestRecordCardinalityInvariant:
    def test_issue_creates_one_record_per_eligible_channel_frozen_at_issue(self, api):
        """PRD §3.5: "One dissemination record is then created per eligible
        channel — a channel is eligible when it is `ACTIVE` and its
        `supports_levels` includes the product's level — each record starting
        `QUEUED` (§3.6)."

        Design: Difficulty/compensating_invariant/dissemination_record_cardinality_conserved_through_cancel
        """
        bundle = setup_issued_warning(
            api,
            channels=[
                dict(EAS_AUTO, name="EAS-1"),
                dict(WEA_CONFIRM, name="WEA-1"),
                dict(DATA_FEED_AUTO, name="DF-1"),
            ],
        )
        records = list_records(api, bundle.product["id"], bundle.headers)
        assert len(records) == 3, "the three issue-time-eligible channels each got a record"
        assert all(r["status"] == "QUEUED" for r in records)

        create_alert_channel(api, name="EAS-2", supports_levels=["WARNING"])
        records = list_records(api, bundle.product["id"], bundle.headers)
        assert len(records) == 3, (
            "a channel created after issue adds no record: eligibility is frozen at issue time"
        )

    def test_cancel_withdraws_queued_records_without_deleting(self, api):
        """PRD §3.7: "A forecaster may cancel an `ISSUED` product, moving it to
        the terminal `CANCELLED` status with `cancelled_at` stamped; the
        product's `window_end` recomputes, and its still-`QUEUED`
        dissemination records are withdrawn, while records already `SENT`,
        `CONFIRMED`, `FAILED`, or `DEAD` are unaffected."

        Design: Difficulty/compensating_invariant/dissemination_record_cardinality_conserved_through_cancel
        """
        bundle = setup_issued_warning(
            api,
            channels=[
                dict(EAS_AUTO, name="EAS-1"),
                dict(WEA_CONFIRM, name="WEA-1"),
                dict(DATA_FEED_AUTO, name="DF-1"),
            ],
        )
        cancel_product(api, bundle.product["id"], bundle.headers)
        product = get_product(api, bundle.product["id"], bundle.headers)
        assert product["status"] == "CANCELLED"
        assert product["window_end"] == product["cancelled_at"]

        records = list_records(api, bundle.product["id"], bundle.headers)
        assert len(records) == 3, "withdrawal compensates creation without deleting anything"
        assert all(r["status"] == "WITHDRAWN" for r in records)


class TestSettlement:
    def test_settle_queued_record_returns_not_settlable(self, api):
        """PRD §3.6: "Only a `SENT` record is settleable; settling anything
        else is rejected with `ERR_RECORD_NOT_SETTLABLE`."

        Design: Corner/state_machines/settle_queued_record_returns_not_settlable
        """
        bundle = setup_issued_warning(api, channels=[dict(WEA_CONFIRM, name="WEA-STL")])
        record = bundle.records[0]
        assert record["status"] == "QUEUED", "the clock never advanced past issue"
        resp = api.settle_dissemination_record(record["id"], "CONFIRMED", make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_SETTLABLE)
        record = get_record(api, record["id"], bundle.headers)
        assert record["status"] == "QUEUED"
        assert record["retry_count"] == 0
        assert record["sent_at"] is None

    def test_settle_confirm_after_dispatch_sets_confirmed_at(self, api):
        """PRD §3.6: "when the logical clock advances, every `QUEUED` record
        whose product is `ISSUED` transitions to `SENT` with `sent_at` stamped,
        and when the channel's `requires_confirmation` is false the record
        immediately continues to `CONFIRMED` with `confirmed_at` stamped inside
        the same advance."
        PRD §3.6: "A `CONFIRMED` outcome stamps `confirmed_at`."

        Design: Corner/endpoints/settle_confirm_after_dispatch_sets_confirmed_at
        """
        bundle = setup_issued_warning(
            api,
            channels=[dict(WEA_CONFIRM, name="WEA-C"), dict(EAS_AUTO, name="EAS-C", supports_levels=["WARNING"])],
        )
        wea_channel, eas_channel = bundle.channels
        set_clock(api, "2026-09-01T10:05:00Z")

        wea_record = list_records(
            api, bundle.product["id"], bundle.headers, channel_id=wea_channel["id"]
        )[0]
        assert wea_record["status"] == "SENT"
        assert _instant(wea_record["sent_at"]) == _instant("2026-09-01T10:05:00Z")

        settled = _settle(api, wea_record["id"], "CONFIRMED")
        assert settled["status"] == "CONFIRMED"
        assert settled["confirmed_at"] == wea_record["sent_at"], (
            "the settle stamps the current logical clock (10:05, unmoved since dispatch)"
        )

        eas_record = list_records(
            api, bundle.product["id"], bundle.headers, channel_id=eas_channel["id"]
        )[0]
        assert eas_record["status"] == "CONFIRMED", (
            "auto-confirm carried QUEUED -> SENT -> CONFIRMED inside the single advance"
        )
        assert _instant(eas_record["confirmed_at"]) == _instant("2026-09-01T10:05:00Z")

        records = list_records(api, bundle.product["id"], bundle.headers)
        assert len(records) == 2 and all(r["status"] == "CONFIRMED" for r in records)


class TestImmediateConsistency:
    def test_issue_side_effects_visible_immediately_in_same_instant(self, api):
        """PRD §2.9: "Every mutation, including every cascade it triggers,
        commits atomically within the request that caused it; there is no
        eventual consistency anywhere in the system."
        PRD §3.5: "A successful issue stamps `issued_at`, overwrites
        `effective_from` with that instant for warnings and advisories"
        PRD §3.6: "begins `QUEUED` with `queued_at` stamped and `retry_count`
        at zero"

        Design: Corner/consistency_model/issue_side_effects_visible_immediately_in_same_instant
        """
        bundle = setup_issued_warning(
            api,
            channels=[
                dict(DATA_FEED_AUTO, name="DF-IMM", supports_levels=["WARNING"]),
            ],
        )
        product = bundle.product
        assert product["status"] == "ISSUED", "the issue response itself carries the new state"
        assert _instant(product["issued_at"]) == _instant("2026-09-01T10:00:00Z")
        assert product["effective_from"] == product["issued_at"], (
            "WARNING onset is overwritten at issue"
        )

        records = list_records(api, product["id"], bundle.headers)
        assert len(records) == 1, "the very next read already shows the record"
        record = records[0]
        assert record["status"] == "QUEUED"
        assert record["queued_at"] == product["issued_at"]
        assert record["retry_count"] == 0

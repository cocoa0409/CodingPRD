"""Batch lifecycle, carrier standing, and freeze cascade tests."""
from test_helpers import (
    ApiErrorId,
    admin,
    audit_event_types_for_carrier,
    audit_event_types_for_consumer,
    compliance,
    create_carrier,
    create_consumer,
    get_success_data,
    init_exchange_rules,
    list_consumer_active_claims,
    make_claim_row,
    make_consumer_headers,
    make_data_steward_headers,
    make_underwriter_headers,
    set_clock,
    setup_active_carrier_with_report,
    submit_batch,
    submit_inquiry,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBatchLifecycle:
    def test_batch_auto_transitions_received_validated_completed_in_one_post(self, api, admin_headers, compliance_headers):
        """PRD §3.2: "The batch lifecycle is automatic once the submission is
        accepted. A batch is born in `RECEIVED` with its `submitted_at` stamped
        from the logical clock; per-claim validation runs immediately,
        `claim_count` is set to the number of rows in the payload,
        `accepted_count` and `rejected_count` are recorded, the batch moves to
        `VALIDATED`, and a `BATCH_RECEIVED` event is appended. From
        `VALIDATED`, a batch with at least one accepted claim completes"
        PRD §3.2: "the carrier's `accepted_batch_count` grows by one and its
        `accepted_claim_count` grows by the batch's `accepted_count`"

        Design: Corner/state_machines/batch_auto_transitions_received_validated_completed_in_one_post
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Alamo First", naic_code="90007")
        consumer = create_consumer(
            full_name="Ann Ames",
            date_of_birth="1991-08-14",
            address_line="22 Ash St, Austin TX",
            driver_license_number="ANN-1",
        )
        batch = submit_batch(
            carrier,
            [
                make_claim_row(consumer["id"], "A-100", loss_date="2025-05-01", paid_amount_cents=22000),
                make_claim_row(consumer["id"], "A-101", loss_date="2025-06-01", loss_type="OTHER", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT"),
            ],
        )
        assert batch["status"] == "COMPLETED"
        assert batch["claim_count"] == 2
        assert batch["accepted_count"] == 2
        assert batch["rejected_count"] == 0
        carrier_r = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert carrier_r["status"] == "ACTIVE"
        assert carrier_r["accepted_batch_count"] == 1
        assert carrier_r["accepted_claim_count"] == 2
        events = audit_event_types_for_carrier(carrier["id"])
        assert events.index("BATCH_RECEIVED") > events.index("BATCH_COMPLETED")  # most recent first

    def test_void_of_completed_batch_returns_invalid_state(self, api, compliance_headers):
        """PRD §3.2: "An `ExchangeComplianceOfficer` may void a batch that is
        still in `RECEIVED` or `VALIDATED`, moving it to `VOIDED` and appending
        `BATCH_VOIDED`; voiding a terminal batch is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/void_of_completed_batch_returns_invalid_state
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Alamo First", naic_code="90007")
        consumer = create_consumer(
            full_name="Ann Ames",
            date_of_birth="1991-08-14",
            address_line="22 Ash St, Austin TX",
            driver_license_number="ANN-1",
        )
        batch = submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "A-200", loss_date="2025-07-01", loss_type="PROPERTY", paid_amount_cents=15000)],
        )
        resp = api.void_batch(batch["id"], compliance_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_batch(batch["id"], compliance_headers))
        assert after["status"] == "COMPLETED"
        voided = audit_event_types_for_carrier(carrier["id"], event_type="BATCH_VOIDED")
        assert voided == []


class TestCarrierInitialState:
    def test_carrier_provisional_starts_and_first_accepted_batch_activates(self, api, admin_headers):
        """PRD §3.1: "When a `PROVISIONAL` carrier's first contribution batch
        completes with at least one accepted claim, the carrier transitions to
        `ACTIVE`"
        PRD §3.2: "A `VALIDATED` batch with zero accepted claims instead
        transitions to `FAILED` with a `BATCH_FAILED` event."

        Design: Corner/state_machines/carrier_provisional_starts_and_first_accepted_batch_activates
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Austin Mutual", naic_code="90008")
        assert carrier["status"] == "PROVISIONAL"
        consumer = create_consumer(
            full_name="Amy Ames",
            date_of_birth="1990-02-11",
            address_line="8 Acorn Ave, Austin TX",
            driver_license_number="AMY-1",
        )
        bad = submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "A2-1", loss_date="2025-01-01", loss_type="BOGUS_TYPE", cause_of_loss_code="bad code!", paid_amount_cents=1000)],
        )
        assert bad["status"] == "FAILED"
        mid = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert mid["status"] == "PROVISIONAL"
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "A2-2", loss_date="2025-01-02", loss_type="OTHER", cause_of_loss_code="OK1", paid_amount_cents=1000)],
        )
        final = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert final["status"] == "ACTIVE"


class TestWithdrawnCarrier:
    def test_withdrawn_carrier_is_terminal_and_rejects_new_batches_and_inquiries(self, api, compliance_headers):
        """PRD §3.1: "Withdrawal moves the carrier to `WITHDRAWN`: its claims
        remain stored but are excluded from every future report, outstanding
        inquiry reads are unaffected, and any new quote inquiry for the carrier
        is rejected."
        PRD §3.2: "A `WITHDRAWN` carrier cannot contribute; the attempt is
        rejected with `ERR_CARRIER_NOT_ACTIVE`."
        PRD §3.3: "as are the inquiries of a `WITHDRAWN` carrier."

        Design: Corner/state_machines/withdrawn_carrier_is_terminal_and_rejects_new_batches_and_inquiries
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Arrowhead General", naic_code="90009")
        consumer = create_consumer(
            full_name="Al Alder",
            date_of_birth="1988-05-05",
            address_line="6 Alder Aly, Dallas TX",
            driver_license_number="AL-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "A3-1", loss_date="2025-03-03", paid_amount_cents=8000)],
        )
        withdrawn = validate_success(api.withdraw_carrier(carrier["id"], compliance_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        batch_resp = api.create_batch(
            carrier["id"],
            {"claims": [make_claim_row(consumer["id"], "A3-2", loss_date="2025-04-04", paid_amount_cents=9000)]},
            make_data_steward_headers(carrier["id"]),
        )
        validate_error(batch_resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, 409)

        inq_resp = api.create_inquiry(
            carrier["id"],
            {
                "subject_name": "Al Alder",
                "subject_dob": "1988-05-05",
                "subject_address": "6 Alder Aly, Dallas TX",
                "subject_driver_license": "AL-1",
                "permissible_purpose": "UNDERWRITING",
            },
            make_underwriter_headers(carrier["id"]),
        )
        validate_error(inq_resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, 409)


class TestDoubleFreeze:
    def test_double_freeze_returns_invalid_state(self, api, admin_headers, compliance_headers):
        """PRD §2.9: "the target resource is in a state that permits the
        operation, failing as `ERR_INVALID_STATE`"
        PRD §3.6: "Freezing sets `file_frozen` true, sets `frozen_until` to the
        logical clock plus `data_freeze_days` days, increments the consumer's
        `version`, and appends `DATA_FREEZE_APPLIED`."

        Design: Corner/state_machines/double_freeze_returns_invalid_state
        """
        set_clock()
        init_exchange_rules()
        consumer = create_consumer(
            full_name="Cal Calloway",
            date_of_birth="1984-09-27",
            address_line="15 Cottonwood Cv, Waco TX",
            driver_license_number="CAL-1",
        )
        first = validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)
        assert first["file_frozen"] is True
        assert first["frozen_until"] == "2026-10-31T00:00:00Z"
        second = api.freeze_consumer(consumer["id"], compliance_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_consumer(consumer["id"], admin_headers))
        assert after["frozen_until"] == "2026-10-31T00:00:00Z"


class TestFreezeCascadeConditionality:
    def test_report_freeze_on_consumer_freeze_is_conditional_on_issued_status(self, api, compliance_headers):
        """PRD §3.6: "The freeze cascades immediately: every `ISSUED` report
        whose subject is the frozen consumer transitions to `FROZEN` — the
        terminal state of a report — with a `REPORT_FROZEN` event appended for
        each."
        PRD §3.6: "Frozen reports do not thaw; `FROZEN` is terminal."

        Design: Corner/state_machines/report_freeze_on_consumer_freeze_is_conditional_on_issued_status
        """
        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Dee Dahl",
                "date_of_birth": "1986-01-23",
                "address_line": "11 Daisy Dr, Irving TX",
                "driver_license_number": "DEE-1",
            },
            claim_overrides={"loss_date": "2025-08-08", "paid_amount_cents": 7000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)
        # Clock past frozen_until lifts the freeze (60 days from 2026-09-01).
        set_clock("2026-11-01T00:00:00Z")
        again = validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)
        assert again["file_frozen"] is True
        frozen_events = audit_event_types_for_consumer(consumer["id"], event_type="REPORT_FROZEN")
        assert frozen_events == ["REPORT_FROZEN"]


class TestCarrierCycle:
    def test_carrier_cycle_full_provisional_active_suspended_active(self, api, admin_headers):
        """PRD §3.1: "Standing advances automatically. When a `PROVISIONAL`
        carrier's first contribution batch completes with at least one accepted
        claim, the carrier transitions to `ACTIVE` and a `CARRIER_REACTIVATED`
        audit event is appended — the same event type the exchange uses for
        both first activation and reactivation. When a carrier's
        `contribution_lag_days` reaches the rulebook's reciprocity threshold at
        a clock evaluation, an `ACTIVE` carrier is suspended, with a
        `CARRIER_SUSPENDED` event whose `details` record the lag; when a newly
        completed batch brings the lag back below the threshold, the carrier
        returns to `ACTIVE` with a `CARRIER_REACTIVATED` event."

        Design: Difficulty/non_linear_state_machine/carrier_provisional_active_suspended_cycle
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Sentinel Casualty", naic_code="44444")
        consumer = create_consumer(
            full_name="Grace Graves",
            date_of_birth="1975-07-19",
            address_line="3 Willow Way, Waco TX",
            driver_license_number="GRACE-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "G-001", loss_date="2025-09-01", loss_type="OTHER", paid_amount_cents=1000)],
        )
        active = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert active["status"] == "ACTIVE"

        sweep = set_clock("2026-10-17T00:00:00Z")
        assert carrier["id"] in sweep["suspended_carrier_ids"]

        set_clock("2026-10-18T00:00:00Z")
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "G-002", loss_date="2026-10-01", loss_type="OTHER", paid_amount_cents=2000)],
        )
        back = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert back["status"] == "ACTIVE"
        assert back["contribution_lag_days"] == 0

        events = audit_event_types_for_carrier(carrier["id"])
        # Standing events in most-recent-first listing order:
        # reactivation (batch 2), suspension, first activation.
        standing = [e for e in events if e in ("CARRIER_REACTIVATED", "CARRIER_SUSPENDED")]
        assert standing == ["CARRIER_REACTIVATED", "CARRIER_SUSPENDED", "CARRIER_REACTIVATED"]

    def test_carrier_cycle_each_transition_appends_its_audit_event(self, api, admin_headers):
        """PRD §3.1: "When a carrier's `contribution_lag_days` reaches the
        rulebook's reciprocity threshold at a clock evaluation, an `ACTIVE`
        carrier is suspended, with a `CARRIER_SUSPENDED` event whose `details`
        record the lag; when a newly completed batch brings the lag back below
        the threshold, the carrier returns to `ACTIVE` with a
        `CARRIER_REACTIVATED` event."

        Design: Difficulty/non_linear_state_machine/carrier_provisional_active_suspended_cycle
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Sentinel Casualty", naic_code="44444")
        consumer = create_consumer(
            full_name="Grace Graves",
            date_of_birth="1975-07-19",
            address_line="3 Willow Way, Waco TX",
            driver_license_number="GRACE-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "G-001", loss_date="2025-09-01", loss_type="OTHER", paid_amount_cents=1000)],
        )
        set_clock("2026-10-17T00:00:00Z")
        suspended = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert suspended["status"] == "SUSPENDED"
        set_clock("2026-10-18T00:00:00Z")
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "G-002", loss_date="2026-10-01", loss_type="OTHER", paid_amount_cents=2000)],
        )
        back = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert back["status"] == "ACTIVE"
        assert back["contribution_lag_days"] == 0
        # The cycle is repeatable: a second lag breach suspends again.
        set_clock("2026-12-03T00:00:00Z")
        again = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert again["status"] == "SUSPENDED"
        susp_events = audit_event_types_for_carrier(carrier["id"], event_type="CARRIER_SUSPENDED")
        assert susp_events == ["CARRIER_SUSPENDED", "CARRIER_SUSPENDED"]

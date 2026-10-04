"""Report issuance gates, freezes, retention, and reciprocity tests."""
from test_helpers import (
    ApiErrorId,
    admin,
    audit_event_types_for_consumer,
    compliance,
    create_carrier,
    create_consumer,
    get_success_data,
    init_exchange_rules,
    make_claim_row,
    make_consumer_headers,
    make_underwriter_headers,
    set_clock,
    setup_active_carrier_with_report,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def _inquiry_payload(consumer, **overrides):
    payload = {
        "subject_name": consumer["full_name"],
        "subject_dob": consumer["date_of_birth"],
        "subject_address": consumer["address_line"],
        "subject_driver_license": consumer["driver_license_number"],
        "permissible_purpose": "UNDERWRITING",
    }
    payload.update(overrides)
    return payload


class TestFreezeCascade:
    def test_freeze_consumer_cascades_reports_then_obligates_notice_resolution(self, api, compliance_headers):
        """PRD §3.6: "Freezing sets `file_frozen` true, sets `frozen_until` to
        the logical clock plus `data_freeze_days` days, increments the
        consumer's `version`, and appends `DATA_FREEZE_APPLIED`. The freeze
        cascades immediately: every `ISSUED` report whose subject is the frozen
        consumer transitions to `FROZEN` — the terminal state of a report —
        with a `REPORT_FROZEN` event appended for each."
        PRD §3.8: "Sending a notice is the underwriter's act, valid only while
        the notice is `DRAFT` — sending a notice in any other state fails with
        `ERR_INVALID_STATE` — and additionally requires that the acting
        underwriter belongs to the notice's carrier, that the cited report is
        still in `ISSUED` status, and that the carrier's outstanding count is
        strictly below the cap at send time."

        Design: Difficulty/transitive_cascade/freeze_consumer_cascades_reports_then_obligates_notice_resolution
        """
        from test_helpers import create_notice_for_report

        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Ivy Ingram",
                "date_of_birth": "1995-06-30",
                "address_line": "12 Ivy Ct, Denton TX",
                "driver_license_number": "IVY-1",
            },
            claim_overrides={"loss_date": "2025-08-01", "loss_type": "COMPREHENSIVE", "paid_amount_cents": 80000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        notice = create_notice_for_report(carrier, report["id"], action_type="RATE_INCREASE")

        frozen = validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)
        assert frozen["file_frozen"] is True
        assert frozen["frozen_until"] == "2026-10-31T00:00:00Z"

        rep_after = get_success_data(api.get_report(report["id"], compliance_headers))
        assert rep_after["status"] == "FROZEN"

        send_resp = api.send_notice(notice["id"], make_underwriter_headers(carrier["id"]))
        validate_error(send_resp, ApiErrorId.ERR_INVALID_STATE, 409)

        inq = validate_success(
            api.create_inquiry(carrier["id"], _inquiry_payload(consumer), make_underwriter_headers(carrier["id"])),
            201,
        )
        assert inq["report_blocked_reason"] == "FROZEN"
        assert inq["report_id"] is None

        events = audit_event_types_for_consumer(consumer["id"])
        assert "REPORT_FROZEN" in events
        assert "DATA_FREEZE_APPLIED" in events

    def test_freeze_consumer_cascade_blocks_send_and_new_reports(self, api, compliance_headers):
        """PRD §3.6: "While the freeze is in force, two things are blocked: the
        consumer's own file-disclosure read is rejected with
        `ERR_CONSUMER_FILE_FROZEN` (HTTP 409), and report issuance on any
        inquiry resolving to that consumer is blocked as §3.5 describes."
        PRD §3.5: "When the report leg is blocked, the inquiry is still
        recorded with `report_blocked_reason` set to `FROZEN` or `RECIPROCITY`
        accordingly and `report_id` left null."

        Design: Difficulty/transitive_cascade/freeze_consumer_cascades_reports_then_obligates_notice_resolution
        """
        from test_helpers import create_notice_for_report

        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Ivy Ingram",
                "date_of_birth": "1995-06-30",
                "address_line": "12 Ivy Ct, Denton TX",
                "driver_license_number": "IVY-1",
            },
            claim_overrides={"loss_date": "2025-08-01", "loss_type": "COMPREHENSIVE", "paid_amount_cents": 80000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        notice = create_notice_for_report(carrier, report["id"], action_type="RATE_INCREASE")
        validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)

        # File disclosure is blocked while frozen.
        file_resp = api.get_consumer_file(consumer["id"], make_consumer_headers(consumer["id"]))
        validate_error(file_resp, ApiErrorId.ERR_CONSUMER_FILE_FROZEN, 409)

        # Send against a FROZEN report fails.
        send_resp = api.send_notice(notice["id"], make_underwriter_headers(carrier["id"]))
        validate_error(send_resp, ApiErrorId.ERR_INVALID_STATE, 409)

        # New inquiry resolves but with no report attached.
        inq = validate_success(
            api.create_inquiry(carrier["id"], _inquiry_payload(consumer), make_underwriter_headers(carrier["id"])),
            201,
        )
        assert inq["report_blocked_reason"] == "FROZEN"
        assert inq["report_id"] is None


class TestFreezeBlocksIssuance:
    def test_report_issuance_depends_on_consumer_freeze_state(self, api):
        """PRD §3.5: "When the report leg is blocked, the inquiry is still
        recorded with `report_blocked_reason` set to `FROZEN` or `RECIPROCITY`
        accordingly and `report_id` left null."
        PRD §3.6: "When the logical clock reaches `frozen_until`, the freeze
        lifts automatically: `file_frozen` returns to false, `frozen_until`
        clears, and `DATA_FREEZE_LIFTED` is appended."

        Design: Difficulty/cross_entity_state_dependency/report_issuance_depends_on_consumer_freeze_state
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        consumer = create_consumer(
            full_name="Olive Osgood",
            date_of_birth="1978-04-04",
            address_line="31 Oleander Dr, Odessa TX",
            driver_license_number="OLIVE-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "O-001", loss_date="2025-10-10", loss_type="PROPERTY", paid_amount_cents=55000)],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        validate_success(api.freeze_consumer(consumer["id"], compliance()), 200)

        blocked = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(consumer), uw), 201)
        assert blocked["report_id"] is None
        assert blocked["report_blocked_reason"] == "FROZEN"

        sweep = set_clock("2026-11-01T00:00:00Z")
        assert consumer["id"] in sweep["expired_freeze_consumer_ids"]

        # The carrier has not contributed for 61 days, so it is suspended too;
        # restore standing with a fresh batch before re-testing issuance.
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "O-002", loss_date="2026-09-15", loss_type="PROPERTY", paid_amount_cents=1000)],
        )
        ok = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(consumer), uw), 201)
        assert ok["report_id"] is not None
        report = get_success_data(api.get_report(ok["report_id"], uw))
        # Both Olive claims are in retention; the freeze no longer blocks.
        assert report["claim_count_reported"] == 2

    def test_report_issuance_blocked_while_frozen_and_restored_after_lift(self, api):
        """PRD §3.5: "Issuance has two gates, checked in the validation order
        of §2.9: the matched consumer's file must not be frozen (otherwise
        report issuance is blocked under `ERR_CONSUMER_FILE_FROZEN`), and the
        carrier must pass reciprocity (otherwise blocked under
        `ERR_RECIPROCITY_REQUIRED` or `ERR_CARRIER_NOT_ACTIVE` per §3.3)."
        PRD §3.6: "When the logical clock reaches `frozen_until`, the freeze
        lifts automatically: `file_frozen` returns to false, `frozen_until`
        clears, and `DATA_FREEZE_LIFTED` is appended."

        Design: Difficulty/cross_entity_state_dependency/report_issuance_depends_on_consumer_freeze_state
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        consumer = create_consumer(
            full_name="Olive Osgood",
            date_of_birth="1978-04-04",
            address_line="31 Oleander Dr, Odessa TX",
            driver_license_number="OLIVE-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "O-001", loss_date="2025-10-10", loss_type="PROPERTY", paid_amount_cents=55000)],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        validate_success(api.freeze_consumer(consumer["id"], compliance()), 200)

        blocked = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(consumer), uw), 201)
        assert blocked["report_blocked_reason"] == "FROZEN"
        assert blocked["report_id"] is None

        set_clock("2026-11-01T00:00:00Z")
        after = get_success_data(api.get_consumer(consumer["id"], compliance()))
        assert after["file_frozen"] is False
        assert after["frozen_until"] is None


class TestReciprocityThreshold:
    def test_contribution_lag_engages_reciprocity_at_inclusive_threshold(self, api):
        """PRD §3.3: "Once a carrier has completed a batch, reciprocity gating
        engages when `contribution_lag_days` reaches
        `reciprocity_lag_threshold_days`; the boundary is inclusive, so a lag
        exactly equal to the threshold suspends the carrier."
        PRD §3.3: "A carrier's `contribution_lag_days` is the number of whole
        days — floored, never negative — between its most recent `COMPLETED`
        batch's `submitted_at` and the logical clock."

        Design: Difficulty/dual_variant_calc/contribution_lag_engages_reciprocity_at_inclusive_threshold
        """
        set_clock()
        init_exchange_rules()
        c2 = create_carrier(legal_name="Meridian Indemnity", naic_code="22222")
        c3 = create_carrier(legal_name="Pioneer General", naic_code="33333")
        carol = create_consumer(
            full_name="Carol Cortez",
            date_of_birth="1990-01-01",
            address_line="5 Pine Rd, Dallas TX",
            driver_license_number="CAROL-1",
        )
        submit_batch(c2, [make_claim_row(carol["id"], "C-001", loss_date="2025-06-01", loss_type="PROPERTY", paid_amount_cents=120000)])
        submit_batch(c3, [make_claim_row(carol["id"], "C-101", loss_date="2025-07-01", loss_type="PROPERTY", paid_amount_cents=50000)])

        set_clock("2026-10-16T00:00:00Z")  # lag 44: below threshold
        inq44 = validate_success(
            api.create_inquiry(c2["id"], _inquiry_payload(carol), make_underwriter_headers(c2["id"])), 201
        )
        assert inq44["report_id"] is not None
        report = get_success_data(api.get_report(inq44["report_id"], make_underwriter_headers(c2["id"])))
        assert report["risk_score_certainty"] == 61.00

        sweep = set_clock("2026-10-17T00:00:00Z")  # lag 45: exactly at threshold
        assert c2["id"] in sweep["suspended_carrier_ids"]
        assert c3["id"] in sweep["suspended_carrier_ids"]

        inq45 = validate_success(
            api.create_inquiry(c2["id"], _inquiry_payload(carol), make_underwriter_headers(c2["id"])), 201
        )
        assert inq45["report_id"] is None
        assert inq45["report_blocked_reason"] == "RECIPROCITY"

    def test_contribution_lag_one_day_below_threshold_keeps_reports_flowing(self, api):
        """PRD §3.3: "Once a carrier has completed a batch, reciprocity gating
        engages when `contribution_lag_days` reaches
        `reciprocity_lag_threshold_days`; the boundary is inclusive, so a lag
        exactly equal to the threshold suspends the carrier."
        PRD §3.5: "When the report leg is blocked, the inquiry is still
        recorded with `report_blocked_reason` set to `FROZEN` or `RECIPROCITY`
        accordingly and `report_id` left null."

        Design: Difficulty/dual_variant_calc/contribution_lag_engages_reciprocity_at_inclusive_threshold
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Meridian Indemnity", naic_code="22222")
        carol = create_consumer(
            full_name="Carol Cortez",
            date_of_birth="1990-01-01",
            address_line="5 Pine Rd, Dallas TX",
            driver_license_number="CAROL-1",
        )
        submit_batch(carrier, [make_claim_row(carol["id"], "C-001", loss_date="2025-06-01", loss_type="PROPERTY", paid_amount_cents=120000)])
        set_clock("2026-10-16T00:00:00Z")
        c_before = get_success_data(api.get_carrier(carrier["id"], admin()))
        assert c_before["status"] == "ACTIVE"
        inq_ok = validate_success(
            api.create_inquiry(carrier["id"], _inquiry_payload(carol), make_underwriter_headers(carrier["id"])), 201
        )
        assert inq_ok["report_id"] is not None
        set_clock("2026-10-17T00:00:00Z")
        c_after = get_success_data(api.get_carrier(carrier["id"], admin()))
        assert c_after["status"] == "SUSPENDED"
        inq_blocked = validate_success(
            api.create_inquiry(carrier["id"], _inquiry_payload(carol), make_underwriter_headers(carrier["id"])), 201
        )
        assert inq_blocked["report_id"] is None
        assert inq_blocked["report_blocked_reason"] == "RECIPROCITY"


class TestBatchCompletionCascade:
    def test_batch_completion_cascades_carrier_activation_then_unlocks_report_delivery(self, api):
        """PRD §3.1: "when a newly completed batch brings the lag back below
        the threshold, the carrier returns to `ACTIVE` with a
        `CARRIER_REACTIVATED` event."
        PRD §3.3: "A `SUSPENDED` carrier's inquiries are rejected with
        `ERR_RECIPROCITY_REQUIRED` (HTTP 409) — reports are withheld until
        contribution resumes — and the corresponding blocked outcome is
        recorded on the inquiry as described in §3.5."

        Design: Difficulty/transitive_cascade/batch_completion_cascades_carrier_activation_then_unlocks_report_delivery
        """
        from test_helpers import audit_event_types_for_carrier

        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Bluebonnet Assurance", naic_code="55555")
        jake = create_consumer(
            full_name="Jake Jessup",
            date_of_birth="1983-10-10",
            address_line="44 Juniper St, Abilene TX",
            driver_license_number="JAKE-1",
        )
        submit_batch(carrier, [make_claim_row(jake["id"], "J-001", loss_date="2025-12-01", loss_type="OTHER", paid_amount_cents=3000)])
        set_clock("2026-10-17T00:00:00Z")
        uw = make_underwriter_headers(carrier["id"])

        blocked = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(jake), uw), 201)
        assert blocked["report_id"] is None
        assert blocked["report_blocked_reason"] == "RECIPROCITY"

        batch2 = submit_batch(carrier, [make_claim_row(jake["id"], "J-002", loss_date="2026-10-01", loss_type="OTHER", paid_amount_cents=4000)])
        assert batch2["status"] == "COMPLETED"
        carrier_after = get_success_data(api.get_carrier(carrier["id"], admin()))
        assert carrier_after["status"] == "ACTIVE"
        assert carrier_after["contribution_lag_days"] == 0

        ok = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(jake), uw), 201)
        assert ok["report_id"] is not None
        report = get_success_data(api.get_report(ok["report_id"], uw))
        assert report["claim_count_reported"] == 2

        events = audit_event_types_for_carrier(carrier["id"])
        # The reactivation audit event for the second batch must be present.
        assert events.count("CARRIER_REACTIVATED") == 2  # first activation + reactivation
        assert events.count("BATCH_COMPLETED") == 2

    def test_batch_completion_recomputes_lag_and_reactivates_suspended_carrier(self, api):
        """PRD §3.2: "From `VALIDATED`, a batch with at least one accepted
        claim completes: every accepted claim becomes an `ACTIVE` loss claim
        whose `retention_expires_on` is its `loss_date` plus `retention_years`
        years, the carrier's `accepted_batch_count` grows by one and its
        `accepted_claim_count` grows by the batch's `accepted_count`, the
        carrier's `contribution_lag_days` is recomputed from this batch's
        `submitted_at`, the standing cascades of §3.1 fire as applicable, and a
        `BATCH_COMPLETED` event is appended."

        Design: Difficulty/transitive_cascade/batch_completion_cascades_carrier_activation_then_unlocks_report_delivery
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Bluebonnet Assurance", naic_code="55555")
        jake = create_consumer(
            full_name="Jake Jessup",
            date_of_birth="1983-10-10",
            address_line="44 Juniper St, Abilene TX",
            driver_license_number="JAKE-1",
        )
        submit_batch(carrier, [make_claim_row(jake["id"], "J-001", loss_date="2025-12-01", loss_type="OTHER", paid_amount_cents=3000)])
        set_clock("2026-10-17T00:00:00Z")
        assert get_success_data(api.get_carrier(carrier["id"], admin()))["status"] == "SUSPENDED"
        submit_batch(carrier, [make_claim_row(jake["id"], "J-002", loss_date="2026-10-01", loss_type="OTHER", paid_amount_cents=4000)])
        refreshed = get_success_data(api.get_carrier(carrier["id"], admin()))
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["contribution_lag_days"] == 0
        assert refreshed["accepted_batch_count"] == 2
        assert refreshed["accepted_claim_count"] == 2


class TestRetentionBoundary:
    def test_retention_window_excludes_losses_exactly_at_the_boundary_date(self, api, compliance_headers):
        """PRD §3.5: "Its inclusion set is then determined: all of the matched
        consumer's loss claims whose status is `ACTIVE`, whose contributing
        carrier is not `WITHDRAWN`, and whose `loss_date` is strictly newer
        than the logical clock date minus `retention_years` years. The date
        comparison is strict — a loss exactly `retention_years` old on the
        report date is excluded."

        Design: Difficulty/resource_temporal_overlap/retention_window_excludes_losses_exactly_at_the_boundary_date
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        quinn = create_consumer(
            full_name="Quinn Quimby",
            date_of_birth="1977-03-17",
            address_line="88 Quail Run, Longview TX",
            driver_license_number="QUINN-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(quinn["id"], "Q-OLD", loss_date="2019-09-01", loss_type="OTHER", cause_of_loss_code="OLD1", paid_amount_cents=100000),
                make_claim_row(quinn["id"], "Q-NEW", loss_date="2019-09-02", loss_type="OTHER", cause_of_loss_code="NEW1", paid_amount_cents=100000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(quinn), uw), 201)
        report = get_success_data(api.get_report(inq["report_id"], uw))
        assert report["claim_count_reported"] == 1
        entries, _ = validate_paginated(api.list_report_entries_for_report(report["id"], compliance_headers))
        assert len(entries) == 1
        assert entries[0]["loss_date"] == "2019-09-02"
        assert entries[0]["cause_of_loss_code"] == "NEW1"
        # Both claims remain stored; only report inclusion is time-filtered.
        claims, _ = validate_paginated(api.list_consumer_claims(quinn["id"], compliance_headers))
        assert len(claims) == 2

    def test_retention_boundary_strict_exclusion_keeps_storage(self, api, compliance_headers):
        """PRD §3.5: "Its inclusion set is then determined: all of the matched
        consumer's loss claims whose status is `ACTIVE`, whose contributing
        carrier is not `WITHDRAWN`, and whose `loss_date` is strictly newer
        than the logical clock date minus `retention_years` years. The date
        comparison is strict — a loss exactly `retention_years` old on the
        report date is excluded."
        PRD §3.2: "`COMPLETED`, `FAILED`, and `VOIDED` are all terminal."

        Design: Difficulty/resource_temporal_overlap/retention_window_excludes_losses_exactly_at_the_boundary_date
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        quinn = create_consumer(
            full_name="Quinn Quimby",
            date_of_birth="1977-03-17",
            address_line="88 Quail Run, Longview TX",
            driver_license_number="QUINN-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(quinn["id"], "Q-OLD", loss_date="2019-09-01", loss_type="OTHER", cause_of_loss_code="OLD1", paid_amount_cents=100000),
                make_claim_row(quinn["id"], "Q-NEW", loss_date="2019-09-02", loss_type="OTHER", cause_of_loss_code="NEW1", paid_amount_cents=100000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(quinn), uw), 201)
        report = get_success_data(api.get_report(inq["report_id"], uw))
        # Exactly-at-boundary loss excluded, one-day-newer loss included.
        assert report["claim_count_reported"] == 1
        entries, _ = validate_paginated(api.list_report_entries_for_report(report["id"], compliance_headers))
        assert [e["loss_date"] for e in entries] == ["2019-09-02"]


class TestCorrectionHoldWindow:
    def test_correction_hold_window_strict_inequality_decides_carrier_suspension_on_void(self, api, compliance_headers):
        """PRD §3.7: "When a dispute is filed, its `filed_at` is compared
        against the contributing carrier's latest `COMPLETED` batch: the hold
        window is open while the gap between the batch's `submitted_at` and the
        filing is strictly less than `correction_hold_days` days — a dispute
        filed exactly `correction_hold_days` after the batch falls outside the
        window."
        PRD §3.7: "While the window is open, voiding the disputed claim's batch
        is a clean correction recorded as `BATCH_VOIDED`; once the window has
        lapsed for any open dispute on that batch's claims, voiding the batch
        additionally suspends the carrier"

        Design: Difficulty/resource_temporal_overlap/correction_hold_window_strict_inequality_decides_carrier_suspension_on_void
        """
        from test_helpers import file_dispute, list_consumer_active_claims

        set_clock()
        init_exchange_rules()
        c7 = create_carrier(legal_name="Rio Grande Mutual", naic_code="77777")
        c8 = create_carrier(legal_name="Sabine National", naic_code="88888")
        ruth = create_consumer(
            full_name="Ruth Ramey",
            date_of_birth="1981-05-25",
            address_line="14 Redbud Rd, Waco TX",
            driver_license_number="RUTH-1",
        )
        sam = create_consumer(
            full_name="Sam Sibley",
            date_of_birth="1976-09-15",
            address_line="27 Sage St, Killeen TX",
            driver_license_number="SAM-1",
        )
        b1 = submit_batch(c7, [make_claim_row(ruth["id"], "R-001", loss_date="2025-08-08", paid_amount_cents=75000)])
        b2 = submit_batch(c8, [make_claim_row(sam["id"], "S-001", loss_date="2025-08-09", paid_amount_cents=85000)])
        r_claim = list_consumer_active_claims(ruth)[0]
        s_claim = list_consumer_active_claims(sam)[0]

        set_clock("2026-09-20T00:00:00Z")  # 19 days after batch: inside window
        file_dispute(ruth, r_claim["id"])

        set_clock("2026-10-16T00:00:00Z")  # 45 days after batch: outside window
        file_dispute(sam, s_claim["id"])

        v1 = validate_success(api.void_batch(b1["id"], compliance_headers), 200)
        assert v1["status"] == "VOIDED"
        assert get_success_data(api.get_carrier(c7["id"], admin()))["status"] == "ACTIVE"

        v2 = validate_success(api.void_batch(b2["id"], compliance_headers), 200)
        assert v2["status"] == "VOIDED"
        assert get_success_data(api.get_carrier(c8["id"], admin()))["status"] == "SUSPENDED"

        from test_helpers import audit_event_types_for_carrier

        assert "CARRIER_SUSPENDED" in audit_event_types_for_carrier(c8["id"])
        assert "CARRIER_SUSPENDED" not in audit_event_types_for_carrier(c7["id"])

    def test_correction_hold_window_edge_at_exactly_45_days_suspends(self, api, compliance_headers):
        """PRD §3.7: "the hold window is open while the gap between the batch's
        `submitted_at` and the filing is strictly less than
        `correction_hold_days` days — a dispute filed exactly
        `correction_hold_days` after the batch falls outside the window."
        PRD §3.7: "While the window is open, voiding the disputed claim's batch
        is a clean correction recorded as `BATCH_VOIDED`; once the window has
        lapsed for any open dispute on that batch's claims, voiding the batch
        additionally suspends the carrier"

        Design: Difficulty/resource_temporal_overlap/correction_hold_window_strict_inequality_decides_carrier_suspension_on_void
        """
        from test_helpers import file_dispute, list_consumer_active_claims

        set_clock()
        init_exchange_rules()
        c7 = create_carrier(legal_name="Rio Grande Mutual", naic_code="77777")
        c8 = create_carrier(legal_name="Sabine National", naic_code="88888")
        ruth = create_consumer(
            full_name="Ruth Ramey",
            date_of_birth="1981-05-25",
            address_line="14 Redbud Rd, Waco TX",
            driver_license_number="RUTH-1",
        )
        sam = create_consumer(
            full_name="Sam Sibley",
            date_of_birth="1976-09-15",
            address_line="27 Sage St, Killeen TX",
            driver_license_number="SAM-1",
        )
        b1 = submit_batch(c7, [make_claim_row(ruth["id"], "R-001", loss_date="2025-08-08", paid_amount_cents=75000)])
        b2 = submit_batch(c8, [make_claim_row(sam["id"], "S-001", loss_date="2025-08-09", paid_amount_cents=85000)])
        r_claim = list_consumer_active_claims(ruth)[0]
        s_claim = list_consumer_active_claims(sam)[0]

        set_clock("2026-09-20T00:00:00Z")
        file_dispute(ruth, r_claim["id"])
        set_clock("2026-10-16T00:00:00Z")
        file_dispute(sam, s_claim["id"])

        validate_success(api.void_batch(b1["id"], compliance_headers), 200)
        # 19-day-old dispute: inside the hold window, no suspension.
        assert get_success_data(api.get_carrier(c7["id"], admin()))["status"] == "ACTIVE"

        validate_success(api.void_batch(b2["id"], compliance_headers), 200)
        # 45-day-old dispute: exactly at the boundary is outside (strict <), suspension.
        assert get_success_data(api.get_carrier(c8["id"], admin()))["status"] == "SUSPENDED"


class TestReciprocityErrorDistinction:
    def test_reciprocity_required_error_is_distinct_from_carrier_not_active(self, api):
        """PRD §3.3: "A carrier that has never completed a batch has no defined
        lag: it is simply `PROVISIONAL`, and its quote inquiries are rejected
        with `ERR_CARRIER_NOT_ACTIVE` (HTTP 409), as are the inquiries of a
        `WITHDRAWN` carrier."
        PRD §3.5: "When the report leg is blocked, the inquiry is still
        recorded with `report_blocked_reason` set to `FROZEN` or `RECIPROCITY`
        accordingly and `report_id` left null."

        Design: Corner/errors/reciprocity_required_error_is_distinct_from_carrier_not_active
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Nacogdoches Mutual", naic_code="90021")
        ned = create_consumer(
            full_name="Ned Nance",
            date_of_birth="1977-04-18",
            address_line="9 Neches St, Nacogdoches TX",
            driver_license_number="NED-1",
        )
        submit_batch(carrier, [make_claim_row(ned["id"], "N11-1", loss_date="2025-09-09", loss_type="OTHER", paid_amount_cents=6000)])
        set_clock("2026-10-17T00:00:00Z")  # lag 46 >= 45: SUSPENDED
        uw = make_underwriter_headers(carrier["id"])
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(ned), uw), 201)
        assert inq["report_id"] is None
        assert inq["report_blocked_reason"] == "RECIPROCITY"


class TestPremiumWeightCapPatch:
    def test_premium_weight_cap_constant_applied_per_claim(self, api):
        """PRD §2.6: "A `PlatformAdmin` may later update any subset of these
        tunables; all five roles may read the rulebook."
        PRD §3.5: "The severity variant, `risk_score_premium_weighted_cents`,
        first caps each included claim's `paid_amount_cents` at
        `premium_weight_cap_cents`, sums the capped amounts, multiplies by
        `risk_score_certainty`, divides by 100, and rounds half up to integer
        cents"

        Design: Corner/calculations/premium_weight_cap_constant_applied_per_claim
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        gil = create_consumer(
            full_name="Gil Gant",
            date_of_birth="1981-12-09",
            address_line="31 Grape St, Allen TX",
            driver_license_number="GIL-1",
        )
        submit_batch(carrier, [make_claim_row(gil["id"], "G3-1", loss_date="2025-06-15", loss_type="LIABILITY", paid_amount_cents=300000)])
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        inq1 = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(gil), uw), 201)
        rep1 = get_success_data(api.get_report(inq1["report_id"], uw))
        assert rep1["risk_score_premium_weighted_cents"] == 181500

        validate_success(api.patch_exchange_rules({"premium_weight_cap_cents": 100000}, admin()), 200)
        inq2 = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(gil), uw), 201)
        rep2 = get_success_data(api.get_report(inq2["report_id"], uw))
        assert rep2["risk_score_premium_weighted_cents"] == 60500

        rep1_after = get_success_data(api.get_report(rep1["id"], uw))
        assert rep1_after["risk_score_premium_weighted_cents"] == 181500

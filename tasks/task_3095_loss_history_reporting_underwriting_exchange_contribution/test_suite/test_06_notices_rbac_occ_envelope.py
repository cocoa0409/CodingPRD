"""Adverse action notices, role segregation, OCC, envelope, and clock sweep tests."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID_E,
    admin,
    compliance,
    create_carrier,
    create_consumer,
    create_notice_for_report,
    file_dispute,
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


def _setup_report_and_notice(api, cap=1, consumer_overrides=None, claim_overrides=None):
    set_clock()
    init_exchange_rules(max_outstanding_inquiries=cap)
    carrier = create_carrier()
    consumer = create_consumer(**(consumer_overrides or {}))
    submit_batch(carrier, [make_claim_row(consumer["id"], "N-001", **(claim_overrides or {}))])
    carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
    uw = make_underwriter_headers(carrier["id"])
    inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(consumer), uw), 201)
    notice = create_notice_for_report(carrier, inq["report_id"], action_type="DECLINE", notice_reason_codes=["LOSS-SEV"])
    return carrier, consumer, inq, notice, uw


class TestNoticeStateVsCapPriority:
    def test_invalid_state_beats_inquiry_cap_fiscal_on_notice_send(self, api):
        """PRD §2.9: "The order is: (1) authentication — the headers of §2.1,
        failing as `ERR_UNAUTHENTICATED`; (2) authorization — the role is
        permitted on this endpoint, failing as `ERR_UNAUTHORIZED`; (3) path
        existence — every identifier in the URL resolves, failing as
        `ERR_NOT_FOUND`; (4) body references — foreign keys declared in the
        request body resolve, failing as `ERR_REFERENCED_NOT_FOUND`; (5)
        state — the target resource is in a state that permits the operation,
        failing as `ERR_INVALID_STATE`; (6) consumer file freeze — file access
        and report issuance are blocked while a consumer file is frozen,
        failing as `ERR_CONSUMER_FILE_FROZEN`; (7) permissible purpose — the
        inquiry's declared purpose is valid, failing as
        `ERR_PERMISSIBLE_PURPOSE`; (8) contributory reciprocity — the inquiring
        carrier's standing, failing as `ERR_RECIPROCITY_REQUIRED` or
        `ERR_CARRIER_NOT_ACTIVE` as §3.3 describes; (9) standardized claim
        coding, failing as `ERR_INVALID_REQUEST`; (10) batch size and
        claim-number uniqueness, failing as `ERR_BATCH_CONSTRAINT`; (11)
        dispute timing and openness, failing as `ERR_DISPUTE_OVERDUE` or
        `ERR_DISPUTE_ALREADY_OPEN`; and (12) the outstanding adverse action
        notice cap, failing as `ERR_INQUIRY_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_inquiry_cap_fiscal_on_notice_send
        """
        carrier, consumer, inq, notice, uw = _setup_report_and_notice(api, cap=1)
        validate_success(api.send_notice(notice["id"], uw), 200)
        # outstanding == cap == 1; the notice is SENT (state check fires first).
        second = api.send_notice(notice["id"], uw)
        err = validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)
        assert err["error_id"] != "ERR_INQUIRY_CAP_EXCEEDED"
        # The cap is independently live: a fresh filing fails on it.
        fresh = api.create_notice(
            carrier["id"],
            {"report_id": inq["report_id"], "action_type": "DECLINE", "notice_reason_codes": ["LOSS-SEV"], "report_influence_rank": 1},
            uw,
        )
        validate_error(fresh, ApiErrorId.ERR_INQUIRY_CAP_EXCEEDED, 409)

    def test_state_check_precedes_fiscal_cap_on_notice_send(self, api):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed priority order, and the first failing check
        determines the error returned."
        PRD §3.8: "Sending a notice is the underwriter's act, valid only while
        the notice is `DRAFT` — sending a notice in any other state fails with
        `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_inquiry_cap_fiscal_on_notice_send
        """
        carrier, consumer, inq, notice, uw = _setup_report_and_notice(api, cap=1)
        validate_success(api.send_notice(notice["id"], uw), 200)
        second = api.send_notice(notice["id"], uw)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


class TestFreezeVsReciprocityPriority:
    def test_frozen_file_safety_beats_reciprocity_referential_on_inquiry(self, api, compliance_headers):
        """PRD §2.9: "The order is: (1) authentication — the headers of §2.1,
        failing as `ERR_UNAUTHENTICATED`; (2) authorization — the role is
        permitted on this endpoint, failing as `ERR_UNAUTHORIZED`; (3) path
        existence — every identifier in the URL resolves, failing as
        `ERR_NOT_FOUND`; (4) body references — foreign keys declared in the
        request body resolve, failing as `ERR_REFERENCED_NOT_FOUND`; (5)
        state — the target resource is in a state that permits the operation,
        failing as `ERR_INVALID_STATE`; (6) consumer file freeze — file access
        and report issuance are blocked while a consumer file is frozen,
        failing as `ERR_CONSUMER_FILE_FROZEN`; (7) permissible purpose — the
        inquiry's declared purpose is valid, failing as
        `ERR_PERMISSIBLE_PURPOSE`; (8) contributory reciprocity — the inquiring
        carrier's standing, failing as `ERR_RECIPROCITY_REQUIRED` or
        `ERR_CARRIER_NOT_ACTIVE` as §3.3 describes; (9) standardized claim
        coding, failing as `ERR_INVALID_REQUEST`; (10) batch size and
        claim-number uniqueness, failing as `ERR_BATCH_CONSTRAINT`; (11)
        dispute timing and openness, failing as `ERR_DISPUTE_OVERDUE` or
        `ERR_DISPUTE_ALREADY_OPEN`; and (12) the outstanding adverse action
        notice cap, failing as `ERR_INQUIRY_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_file_safety_beats_reciprocity_referential_on_inquiry
        """
        set_clock()
        init_exchange_rules()
        c5 = create_carrier(legal_name="Bluebonnet Assurance", naic_code="55555")
        c6 = create_carrier(legal_name="Llano National", naic_code="66666")
        kate = create_consumer(
            full_name="Kate Kellogg",
            date_of_birth="1991-09-09",
            address_line="6 Kalmia Ave, Tyler TX",
            driver_license_number="KATE-1",
        )
        submit_batch(c5, [make_claim_row(kate["id"], "K-001", loss_date="2025-04-01", loss_type="PROPERTY", paid_amount_cents=60000)])
        submit_batch(c6, [make_claim_row(kate["id"], "K-101", loss_date="2025-05-01", loss_type="PROPERTY", paid_amount_cents=70000)])
        validate_success(api.freeze_consumer(kate["id"], compliance_headers), 200)
        set_clock("2026-10-17T00:00:00Z")  # lag 46 >= 45: c5 SUSPENDED; freeze still in force
        resp = api.create_inquiry(
            c5["id"], _inquiry_payload(kate), make_underwriter_headers(c5["id"])
        )
        err = validate_error(resp, ApiErrorId.ERR_CONSUMER_FILE_FROZEN, 409)
        assert err["error_id"] != "ERR_RECIPROCITY_REQUIRED"

    def test_frozen_file_error_wins_over_reciprocity_because_safety_ranks_first(self, api, compliance_headers):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed priority order, and the first failing check
        determines the error returned."
        PRD §3.5: "Issuance has two gates, checked in the validation order of
        §2.9: the matched consumer's file must not be frozen (otherwise report
        issuance is blocked under `ERR_CONSUMER_FILE_FROZEN`), and the carrier
        must pass reciprocity (otherwise blocked under `ERR_RECIPROCITY_REQUIRED`
        or `ERR_CARRIER_NOT_ACTIVE` per §3.3)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_file_safety_beats_reciprocity_referential_on_inquiry
        """
        set_clock()
        init_exchange_rules()
        c5 = create_carrier(legal_name="Bluebonnet Assurance", naic_code="55555")
        kate = create_consumer(
            full_name="Kate Kellogg",
            date_of_birth="1991-09-09",
            address_line="6 Kalmia Ave, Tyler TX",
            driver_license_number="KATE-1",
        )
        submit_batch(c5, [make_claim_row(kate["id"], "K-001", loss_date="2025-04-01", loss_type="PROPERTY", paid_amount_cents=60000)])
        validate_success(api.freeze_consumer(kate["id"], compliance_headers), 200)
        set_clock("2026-10-17T00:00:00Z")
        resp = api.create_inquiry(
            c5["id"], _inquiry_payload(kate), make_underwriter_headers(c5["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CONSUMER_FILE_FROZEN, 409)


class TestSendDependsOnReportStatus:
    def test_adverse_action_send_depends_on_report_status(self, api, compliance_headers):
        """PRD §3.8: "Sending a notice is the underwriter's act, valid only
        while the notice is `DRAFT` — sending a notice in any other state fails
        with `ERR_INVALID_STATE` — and additionally requires that the acting
        underwriter belongs to the notice's carrier, that the cited report is
        still in `ISSUED` status, and that the carrier's outstanding count is
        strictly below the cap at send time."
        PRD §3.6: "The freeze cascades immediately: every `ISSUED` report whose
        subject is the frozen consumer transitions to `FROZEN` — the terminal
        state of a report — with a `REPORT_FROZEN` event appended for each."

        Design: Difficulty/cross_entity_state_dependency/adverse_action_send_depends_on_report_status
        """
        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Pete Parnell",
                "date_of_birth": "1982-08-18",
                "address_line": "2 Pecan Pl, San Angelo TX",
                "driver_license_number": "PETE-1",
            },
            claim_overrides={"loss_date": "2025-11-11", "loss_type": "COMPREHENSIVE", "paid_amount_cents": 65000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        notice = create_notice_for_report(carrier, report["id"], action_type="RATE_INCREASE")
        validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)

        notice_now = get_success_data(api.get_notice(notice["id"], make_underwriter_headers(carrier["id"])))
        assert notice_now["status"] == "DRAFT"
        report_now = get_success_data(api.get_report(report["id"], compliance_headers))
        assert report_now["status"] == "FROZEN"
        resp = api.send_notice(notice["id"], make_underwriter_headers(carrier["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_adverse_action_send_blocked_when_report_frozen_even_while_draft(self, api, compliance_headers):
        """PRD §3.8: "Sending a notice is the underwriter's act, valid only
        while the notice is `DRAFT` — sending a notice in any other state fails
        with `ERR_INVALID_STATE` — and additionally requires that the acting
        underwriter belongs to the notice's carrier, that the cited report is
        still in `ISSUED` status, and that the carrier's outstanding count is
        strictly below the cap at send time."
        PRD §3.6: "Frozen reports do not thaw; `FROZEN` is terminal."

        Design: Difficulty/cross_entity_state_dependency/adverse_action_send_depends_on_report_status
        """
        ctx = setup_active_carrier_with_report(
            claim_overrides={"loss_date": "2025-11-11", "paid_amount_cents": 65000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        notice = create_notice_for_report(carrier, report["id"], action_type="RATE_INCREASE")
        validate_success(api.freeze_consumer(consumer["id"], compliance_headers), 200)
        resp = api.send_notice(notice["id"], make_underwriter_headers(carrier["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        still = get_success_data(api.get_notice(notice["id"], make_underwriter_headers(carrier["id"])))
        assert still["status"] == "DRAFT"


class TestReportListingPagination:
    def test_reports_list_supports_status_filter_and_pagination(self, api):
        """PRD §2.3: "List endpoints are paginated through the `limit` and
        `offset` query parameters. `limit` defaults to 10, accepts a minimum of
        1 and a maximum of 100, and caps the number of items returned. `offset`
        defaults to 0 and skips that many items from the front of the result
        set. Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/reports_list_supports_status_filter_and_pagination
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        kip = create_consumer(full_name="Kip Kessler", date_of_birth="1982-01-15", address_line="1 King St, Austin TX", driver_license_number="KIP-1")
        kit = create_consumer(full_name="Kit Kessler", date_of_birth="1984-02-15", address_line="2 King St, Austin TX", driver_license_number="KIT-1")
        kim = create_consumer(full_name="Kim Kessler", date_of_birth="1986-03-15", address_line="3 King St, Austin TX", driver_license_number="KIM-1")
        submit_batch(
            carrier,
            [
                make_claim_row(kip["id"], "K8-1", loss_date="2025-01-10", paid_amount_cents=1000),
                make_claim_row(kit["id"], "K8-2", loss_date="2025-01-11", paid_amount_cents=1000),
                make_claim_row(kim["id"], "K8-3", loss_date="2025-01-12", paid_amount_cents=1000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        for c in (kip, kit, kim):
            validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(c), uw), 201)

        page1, meta1 = validate_paginated(
            api.list_carrier_reports(carrier["id"], uw, params={"status": "ISSUED", "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_carrier_reports(carrier["id"], uw, params={"status": "ISSUED", "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        frozen, meta3 = validate_paginated(
            api.list_carrier_reports(carrier["id"], uw, params={"status": "FROZEN"})
        )
        assert frozen == []
        assert meta3["total_count"] == 0


class TestNoticeAcknowledge:
    def test_notice_acknowledge_moves_sent_to_acknowledged(self, api):
        """PRD §3.8: "The addressed consumer — and only that consumer — may
        then acknowledge receipt, moving the notice from `SENT` to
        `ACKNOWLEDGED` with an `ADVERSE_ACTION_ACKNOWLEDGED` event"
        PRD §3.8: "Sending a notice is the underwriter's act, valid only while
        the notice is `DRAFT` — sending a notice in any other state fails with
        `ERR_INVALID_STATE`"
        PRD §3.8: "Sending stamps `disclosure_deadline` as the logical clock at
        send time plus `disclosure_window_days` days and appends
        `ADVERSE_ACTION_SENT`."

        Design: Corner/endpoints/notice_acknowledge_moves_sent_to_acknowledged
        """
        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Lou Lassiter",
                "date_of_birth": "1983-08-30",
                "address_line": "7 Live Oak Ln, Laredo TX",
                "driver_license_number": "LOU-1",
            },
            claim_overrides={"loss_date": "2025-05-20", "paid_amount_cents": 27000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        notice = create_notice_for_report(carrier, report["id"], action_type="NON_RENEWAL")

        early = api.acknowledge_notice(notice["id"], make_consumer_headers(consumer["id"]))
        validate_error(early, ApiErrorId.ERR_INVALID_STATE, 409)

        validate_success(api.send_notice(notice["id"], make_underwriter_headers(carrier["id"])), 200)
        acked = validate_success(api.acknowledge_notice(notice["id"], make_consumer_headers(consumer["id"])), 200)
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["disclosure_deadline"] == "2026-09-06T00:00:00Z"


class TestClockSweep:
    def test_clock_set_evaluates_lag_freeze_overdue_and_retention_in_one_call(self, api, compliance_headers):
        """PRD §2.4: "Advancing the clock re-evaluates, in one sweep: carrier
        suspension and reactivation from contribution lag, automatic lifting of
        consumer data freezes whose `frozen_until` has been reached,
        dispute-overdue audit events for disputes past their reinvestigation
        deadline, and retention redaction of losses that have aged out of
        reportability. The clock-advance response reports the new `current_utc`
        plus the sets `suspended_carrier_ids`, `reactivated_carrier_ids`,
        `expired_freeze_consumer_ids`, `overdue_dispute_ids`, and
        `retention_redacted_claim_ids` describing what the sweep changed."

        Design: Corner/endpoints/clock_set_evaluates_lag_freeze_overdue_and_retention_in_one_call
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        mae = create_consumer(
            full_name="Mae Mabry",
            date_of_birth="1975-05-23",
            address_line="5 Mesquite Mdw, Marble Falls TX",
            driver_license_number="MAE-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(mae["id"], "M10-1", loss_date="2025-07-01", paid_amount_cents=9000),
                make_claim_row(mae["id"], "M10-2", loss_date="2019-08-15", paid_amount_cents=9000),
            ],
        )
        claims = list_consumer_active_claims(mae)
        old_claim = next(c for c in claims if c["claim_number"] == "M10-2")
        new_claim = next(c for c in claims if c["claim_number"] == "M10-1")
        dispute, mae = file_dispute(mae, new_claim["id"], dispute_reason="WRONG_AMOUNT")
        validate_success(api.freeze_consumer(mae["id"], compliance_headers), 200)

        sweep = set_clock("2026-11-01T00:00:00Z")
        assert carrier["id"] in sweep["suspended_carrier_ids"]
        assert mae["id"] in sweep["expired_freeze_consumer_ids"]
        assert dispute["id"] in sweep["overdue_dispute_ids"]
        assert old_claim["id"] in sweep["retention_redacted_claim_ids"]
        assert new_claim["id"] not in sweep["retention_redacted_claim_ids"]

        assert get_success_data(api.get_carrier(carrier["id"], admin()))["status"] == "SUSPENDED"
        assert get_success_data(api.get_consumer(mae["id"], compliance_headers))["file_frozen"] is False


class TestExchangeRuleSingleton:
    def test_exchange_rule_singleton_second_post_returns_conflict(self, api, compliance_headers):
        """PRD §2.6: "A singleton `ExchangeRule` resource holds every tunable
        threshold of the exchange. A `PlatformAdmin` initializes it once;
        attempting initialization when the singleton already exists is rejected
        with `ERR_EXCHANGE_RULE_EXISTS` (HTTP 409). On initialization every
        field takes its declared default: `retention_years` 7 (how far back
        losses are reportable), `reinvestigation_days` 30 (the dispute
        reinvestigation deadline)"

        Design: Corner/errors/exchange_rule_singleton_second_post_returns_conflict
        """
        set_clock()
        validate_success(api.create_exchange_rules({}, admin()), 201)
        second = api.create_exchange_rules({}, admin())
        validate_error(second, ApiErrorId.ERR_EXCHANGE_RULE_EXISTS, 409)
        rules = get_success_data(api.get_exchange_rules(compliance_headers))
        assert rules["retention_years"] == 7
        assert rules["reinvestigation_days"] == 30


class TestErrorEnvelope:
    def test_error_envelope_shape_is_fixed(self, api, compliance_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape_is_fixed
        """
        set_clock()
        resp = api.get_consumer(UNKNOWN_UUID_E, compliance_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert body["data"]["message"]


class TestRoleSegregation:
    def test_data_steward_cannot_resolve_disputes(self, api, compliance_headers):
        """PRD §2.1: "The duties are deliberately segregated: the compliance
        authority that withdraws carriers, freezes files, voids batches, and
        adjudicates disputes (`ExchangeComplianceOfficer`) is a different role
        from the one that contributes data (`CarrierDataSteward`) and from the
        one that consumes reports for underwriting (`CarrierUnderwriter`)."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/roles/data_steward_cannot_resolve_disputes
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Orange Grove Mutual", naic_code="90022")
        ora = create_consumer(
            full_name="Ora Odom",
            date_of_birth="1989-09-19",
            address_line="21 Orange St, Orange TX",
            driver_license_number="ORA-1",
        )
        submit_batch(carrier, [make_claim_row(ora["id"], "O12-1", loss_date="2025-06-21", paid_amount_cents=33000)])
        claim = list_consumer_active_claims(ora)[0]
        dispute, ora = file_dispute(ora, claim["id"], dispute_reason="WRONG_DATE", dispute_statement="Wrong date")
        resp = api.resolve_dispute(
            dispute["id"],
            {"resolution_code": "VERIFIED_ACCURATE", "resolution_notes": "steward attempting"},
            make_data_steward_headers(carrier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        still = get_success_data(api.get_dispute(dispute["id"], compliance_headers))
        assert still["status"] == "FILED"

    def test_underwriter_cannot_contribute_batches(self, api, admin_headers):
        """PRD §2.1: "The duties are deliberately segregated: the compliance
        authority that withdraws carriers, freezes files, voids batches, and
        adjudicates disputes (`ExchangeComplianceOfficer`) is a different role
        from the one that contributes data (`CarrierDataSteward`) and from the
        one that consumes reports for underwriting (`CarrierUnderwriter`)."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/roles/underwriter_cannot_contribute_batches
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Palestine Mutual", naic_code="90023")
        pam = create_consumer(
            full_name="Pam Pate",
            date_of_birth="1987-12-12",
            address_line="4 Palm St, Palestine TX",
            driver_license_number="PAM-1",
        )
        resp = api.create_batch(
            carrier["id"],
            {"claims": [make_claim_row(pam["id"], "P13-1", loss_date="2025-04-25", paid_amount_cents=2000)]},
            make_underwriter_headers(carrier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        batches, _ = validate_paginated(api.list_carrier_batches(carrier["id"], admin_headers))
        assert batches == []

    def test_consumer_cannot_read_another_consumers_file(self, api):
        """PRD §2.1: "When `X-User-Role` is `Consumer`, `X-User-ID` is the `id`
        of the acting `Consumer`; file access, dispute filing, and notice
        acknowledgment compare the resource's consumer reference to
        `X-User-ID`."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/roles/consumer_cannot_read_another_consumers_file
        """
        set_clock()
        quinn = create_consumer(
            full_name="Quinn Quayle",
            date_of_birth="1981-06-06",
            address_line="8 Quince St, Austin TX",
            driver_license_number="QUINN2-1",
        )
        rae = create_consumer(
            full_name="Rae Rains",
            date_of_birth="1983-07-07",
            address_line="9 Rose St, Austin TX",
            driver_license_number="RAE-1",
        )
        resp = api.get_consumer_file(rae["id"], make_consumer_headers(quinn["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestOptimisticConcurrency:
    def test_stale_consumer_version_on_dispute_filing_returns_412(self, api, compliance_headers):
        """PRD §2.11: "Filing a dispute for a consumer requires the request to
        carry `expected_consumer_version` holding the consumer `version` the
        client last observed. Because every consumer mutation — a prior dispute
        filing, a freeze, a freeze lift — advances that version, a filing whose
        `expected_consumer_version` no longer matches the consumer's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) and no
        dispute is persisted."

        Design: Corner/cross-cutting/stale_consumer_version_on_dispute_filing_returns_412
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Seguin Mutual", naic_code="90024")
        sue = create_consumer(
            full_name="Sue Sorrell",
            date_of_birth="1986-10-29",
            address_line="13 Sage St, Seguin TX",
            driver_license_number="SUE-1",
        )
        submit_batch(carrier, [make_claim_row(sue["id"], "S14-1", loss_date="2025-08-14", paid_amount_cents=41000)])
        claim = list_consumer_active_claims(sue)[0]
        stale_version = sue["version"]
        validate_success(api.freeze_consumer(sue["id"], compliance_headers), 200)
        resp = api.create_dispute(
            sue["id"],
            {
                "loss_claim_id": claim["id"],
                "dispute_reason": "WRONG_AMOUNT",
                "dispute_statement": "stale version",
                "expected_consumer_version": stale_version,
            },
            make_consumer_headers(sue["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        disputes, _ = validate_paginated(
            api.list_consumer_disputes(sue["id"], compliance_headers)
        )
        assert disputes == []

    def test_stale_claim_version_on_amendment_returns_412(self, api, compliance_headers):
        """PRD §2.11: "Creating a replacement claim that supersedes an existing
        claim requires `expected_claim_version` holding the claim `version` the
        client last observed. If the claim's version has advanced since — for
        example because a dispute filing or an earlier amendment already bumped
        it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and no
        replacement is persisted."

        Design: Corner/cross-cutting/stale_claim_version_on_amendment_returns_412
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Temple Mutual", naic_code="90025")
        tom = create_consumer(
            full_name="Tom Tally",
            date_of_birth="1979-01-08",
            address_line="2 Tamarind Trl, Temple TX",
            driver_license_number="TOM-1",
        )
        submit_batch(carrier, [make_claim_row(tom["id"], "T15-1", loss_date="2025-05-25", loss_type="PROPERTY", paid_amount_cents=51000)])
        claim = list_consumer_active_claims(tom)[0]
        steward = make_data_steward_headers(carrier["id"])
        validate_success(
            api.create_claim_amendment(
                claim["id"],
                {
                    "loss_date": "2025-05-25",
                    "loss_type": "PROPERTY",
                    "cause_of_loss_code": claim["cause_of_loss_code"],
                    "paid_amount_cents": 52000,
                    "claim_status_code": "CLOSED_WITH_PAYMENT",
                    "expected_claim_version": claim["version"],
                },
                steward,
            ),
            201,
        )
        second = api.create_claim_amendment(
            claim["id"],
            {
                "loss_date": "2025-05-25",
                "loss_type": "PROPERTY",
                "cause_of_loss_code": claim["cause_of_loss_code"],
                "paid_amount_cents": 53000,
                "claim_status_code": "CLOSED_WITH_PAYMENT",
                "expected_claim_version": claim["version"],
            },
            steward,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_success_data(api.get_claim(claim["id"], compliance_headers))["status"] == "AMENDED"
        amendments, _ = validate_paginated(api.list_claim_amendments(claim["id"], compliance_headers))
        assert len(amendments) == 1
        assert amendments[0]["amendment_of_id"] == claim["id"]


class TestPaginationDefaults:
    def test_success_envelope_and_pagination_defaults_on_lists(self, api, compliance_headers):
        """PRD §2.3: "List endpoints are paginated through the `limit` and
        `offset` query parameters. `limit` defaults to 10, accepts a minimum of
        1 and a maximum of 100, and caps the number of items returned. `offset`
        defaults to 0 and skips that many items from the front of the result
        set. Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/cross-cutting/success_envelope_and_pagination_defaults_on_lists
        """
        set_clock()
        create_consumer(full_name="Ula Urban", date_of_birth="1990-03-03", address_line="3 Ulm St, Austin TX", driver_license_number="ULA-1")
        create_consumer(full_name="Ute Utley", date_of_birth="1991-04-04", address_line="4 Ulm St, Austin TX", driver_license_number="UTE-1")
        resp = api.list_consumers(compliance_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

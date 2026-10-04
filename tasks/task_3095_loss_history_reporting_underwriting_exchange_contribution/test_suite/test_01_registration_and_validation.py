"""Registration, creation, and validation-pipeline tests."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID_A,
    UNKNOWN_UUID_B,
    UNKNOWN_UUID_C,
    UNKNOWN_UUID_D,
    UNKNOWN_UUID_E,
    compliance,
    create_carrier,
    create_consumer,
    get_success_data,
    make_data_steward_headers,
    make_underwriter_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCarrierRegistration:
    def test_carrier_create_returns_declared_fields_and_starts_provisional(self, api, admin_headers):
        """PRD §3.1: "A new carrier begins in `PROVISIONAL` standing, with
        `accepted_batch_count` and `accepted_claim_count` at zero and its
        `contribution_lag_days` not yet defined."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/carrier_create_returns_declared_fields_and_starts_provisional
        """
        set_clock()
        resp = api.create_carrier(
            {"legal_name": "Trinity Specialty", "naic_code": "90001"}, admin_headers
        )
        data = validate_success(resp, 201)
        assert data["legal_name"] == "Trinity Specialty"
        assert data["naic_code"] == "90001"
        assert data["status"] == "PROVISIONAL"
        assert data["version"] == 1
        assert data["accepted_batch_count"] == 0
        assert data["accepted_claim_count"] == 0
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]


class TestConsumerRegistration:
    def test_consumer_create_stores_file_unfrozen(self, api, admin_headers):
        """PRD §3.6: "New files are born unfrozen: `file_frozen` false and
        `frozen_until` null."

        Design: Corner/entities/consumer_create_stores_file_unfrozen
        """
        set_clock()
        resp = api.create_consumer(
            {
                "full_name": "Victor Voss",
                "date_of_birth": "1990-07-07",
                "address_line": "1 Verbena St, Austin TX",
                "driver_license_number": "VIC-1",
            },
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["file_frozen"] is False
        assert data["frozen_until"] is None
        assert data["version"] == 1


class TestExistenceChecks:
    def test_carrier_get_with_unknown_id_returns_not_found(self, api, compliance_headers):
        """PRD §2.9: "path existence — every identifier in the URL resolves,
        failing as `ERR_NOT_FOUND`"

        Design: Corner/entities/carrier_get_with_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_carrier(UNKNOWN_UUID_A, compliance_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert err.get("message")

    def test_body_fk_checked_in_input_declaration_order(self, api, admin_headers):
        """PRD §2.10: "Path identifiers resolve left to right (a carrier before
        a consumer before a dispute before a notice), and the first identifier
        that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) without
        examining the rest."

        Design: Corner/validations/body_fk_checked_in_input_declaration_order
        """
        set_clock()
        consumer = create_consumer(
            full_name="Quinn Xylon",
            date_of_birth="1980-01-01",
            address_line="1 Xenon St, Austin TX",
            driver_license_number="QX-1",
        )
        from test_helpers import make_consumer_headers

        resp = api.create_dispute(
            UNKNOWN_UUID_B,
            {
                "loss_claim_id": UNKNOWN_UUID_C,
                "dispute_reason": "OTHER",
                "dispute_statement": "x",
                "expected_consumer_version": consumer["version"],
            },
            make_consumer_headers(consumer["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert err["error_id"] != "ERR_REFERENCED_NOT_FOUND"

    def test_existence_beats_state_when_both_fail(self, api, admin_headers):
        """PRD §2.9: "Because existence outranks state, and state outranks the
        business-safety checks, a request aimed at a nonexistent carrier always
        reports the missing resource rather than any downstream business
        violation."

        Design: Corner/validations/existence_beats_state_when_both_fail
        """
        from test_helpers import init_exchange_rules

        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Bosque Mutual", naic_code="90014")
        resp = api.send_notice(UNKNOWN_UUID_D, make_underwriter_headers(carrier["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestBatchRequiredFields:
    def test_batch_create_missing_claims_field_returns_invalid_request(self, api, admin_headers):
        """PRD §3.2: "a request that is malformed at the envelope level — a
        missing required field or a bad enum member — fails outright with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "The batch as a whole must contain between
        `min_batch_claims` and `max_batch_claims` rows inclusive, and no row
        may reuse a `claim_number` the carrier has already contributed; either
        violation is rejected with `ERR_BATCH_CONSTRAINT` (HTTP 422)."

        Design: Corner/entities/batch_create_missing_claims_field_returns_invalid_request
        """
        from test_helpers import init_exchange_rules

        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Trinity Specialty", naic_code="90001")
        resp = api.create_batch(carrier["id"], {}, make_data_steward_headers(carrier["id"]))
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        assert err["error_id"] != "ERR_BATCH_CONSTRAINT"
        batches, meta = validate_paginated(
            api.list_carrier_batches(carrier["id"], admin_headers)
        )
        assert batches == []


class TestConsumerFileDisclosure:
    def test_consumer_file_disclosure_lists_claims_disputes_and_notices(self, api):
        """PRD §3.6: "A consumer may read their own file — the file-disclosure
        view returns the `consumer` record together with their `claims`,
        `disputes`, and `adverse_action_notices`"

        Design: Corner/entities/consumer_file_disclosure_lists_claims_disputes_and_notices
        """
        from test_helpers import (
            create_notice_for_report,
            make_consumer_headers,
            setup_active_carrier_with_report,
        )

        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Wynn Wade",
                "date_of_birth": "1985-10-10",
                "address_line": "4 Wisteria Way, Frisco TX",
                "driver_license_number": "WYNN-1",
            },
            claim_overrides={
                "loss_date": "2025-03-03",
                "paid_amount_cents": 30000,
            },
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        create_notice_for_report(
            carrier, report["id"], action_type="RATE_INCREASE", report_influence_rank=2
        )
        resp = api.get_consumer_file(consumer["id"], make_consumer_headers(consumer["id"]))
        data = validate_success(resp, 200)
        assert data["consumer"]["id"] == consumer["id"]
        assert len(data["claims"]) == 1
        assert data["claims"][0]["claim_number"] is not None
        assert data["disputes"] == []
        assert len(data["adverse_action_notices"]) == 1
        assert data["adverse_action_notices"][0]["report_id"] == report["id"]


class TestReportClaimEntrySnapshot:
    def test_report_claim_entry_is_immutable_snapshot(self, api, compliance_headers):
        """PRD §3.5: "each included claim is snapshotted into a
        `ReportClaimEntry` preserving its `loss_date`, `loss_type`,
        `cause_of_loss_code`, `paid_amount_cents`, `claim_status_code`, and
        `contributing_carrier_id`"
        PRD §2.5: "Two resource kinds are immutable snapshots and therefore
        carry only `id` and `created_at` — `updated_at` and `version` are
        absent on both: the `ReportClaimEntry` rows frozen into a report at
        issuance, and the `ContributionAuditEvent` records of the audit trail."

        Design: Corner/entities/report_claim_entry_is_immutable_snapshot_with_common_fields_false
        """
        from test_helpers import (
            list_consumer_active_claims,
            make_data_steward_headers,
            setup_active_carrier_with_report,
        )

        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Xena Xavier",
                "date_of_birth": "1993-01-19",
                "address_line": "9 Xanthus Xing, Plano TX",
                "driver_license_number": "XENA-1",
            },
            claim_overrides={
                "loss_date": "2025-02-02",
                "loss_type": "PROPERTY",
                "paid_amount_cents": 50000,
            },
        )
        carrier, report = ctx["carrier"], ctx["report"]
        entries, _ = validate_paginated(
            api.list_report_entries_for_report(report["id"], compliance_headers)
        )
        assert len(entries) == 1
        entry = entries[0]
        assert "updated_at" not in entry
        assert "version" not in entry
        assert entry["entry_sequence"] == 1

        claim = list_consumer_active_claims(ctx["consumer"])[0]
        amend = api.create_claim_amendment(
            claim["id"],
            {
                "loss_date": "2025-02-02",
                "loss_type": "PROPERTY",
                "cause_of_loss_code": claim["cause_of_loss_code"],
                "paid_amount_cents": 99000,
                "claim_status_code": "CLOSED_WITH_PAYMENT",
                "expected_claim_version": claim["version"],
            },
            make_data_steward_headers(carrier["id"]),
        )
        validate_success(amend, 201)
        entries_after, _ = validate_paginated(
            api.list_report_entries_for_report(report["id"], compliance_headers)
        )
        assert len(entries_after) == 1
        assert entries_after[0]["id"] == entry["id"]
        assert entries_after[0]["paid_amount_cents"] == 50000
        assert entries_after[0]["entry_sequence"] == 1


class TestStandardizedCoding:
    def test_loss_claim_rejects_out_of_enum_loss_type(self, api, admin_headers, compliance_headers):
        """PRD §3.2: "A row whose `cause_of_loss_code` violates the format, or
        whose `loss_type` or `claim_status_code` is not a declared member of
        its enum, is rejected individually and counted toward the batch's
        `rejected_count`"
        PRD §3.2: "A `VALIDATED` batch with zero accepted claims instead
        transitions to `FAILED` with a `BATCH_FAILED` event."

        Design: Corner/entities/loss_claim_rejects_out_of_enum_loss_type
        """
        from test_helpers import init_exchange_rules, make_claim_row, submit_batch

        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Yellow Rose Indemnity", naic_code="90004")
        consumer = create_consumer(
            full_name="Yara Yates",
            date_of_birth="1987-04-21",
            address_line="17 Yucca Ct, Bryan TX",
            driver_license_number="YARA-1",
        )
        batch = submit_batch(
            carrier,
            [
                make_claim_row(
                    consumer["id"],
                    "Y-001",
                    loss_date="2025-01-01",
                    loss_type="ACT_OF_GOD",
                    paid_amount_cents=10000,
                )
            ],
        )
        assert batch["status"] == "FAILED"
        assert batch["rejected_count"] == 1
        assert batch["claim_count"] == 1
        refreshed = get_success_data(api.get_carrier(carrier["id"], admin_headers))
        assert refreshed["status"] == "PROVISIONAL"
        claims, _ = validate_paginated(
            api.list_consumer_claims(consumer["id"], compliance_headers)
        )
        assert claims == []


class TestContributionOwnership:
    def test_contribution_batch_requires_owning_carrier_and_rejects_foreign_steward(
        self, api, admin_headers
    ):
        """PRD §2.1: "When `X-User-Role` is `CarrierDataSteward`, `X-User-ID`
        is the `id` of the acting `Carrier`; ownership checks on carrier-scoped
        operations (contributing batches, amending claims) compare the target
        carrier's `id` — or the claim's contributing carrier — to `X-User-ID`."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/entities/contribution_batch_requires_owning_carrier_and_rejects_foreign_steward
        """
        from test_helpers import init_exchange_rules, make_claim_row

        set_clock()
        init_exchange_rules()
        c1 = create_carrier(legal_name="Zephyr General", naic_code="90005")
        c2 = create_carrier(legal_name="Zenith Mutual", naic_code="90006")
        consumer = create_consumer(
            full_name="Zed Zeller",
            date_of_birth="1982-02-28",
            address_line="3 Zinnia Ln, Temple TX",
            driver_license_number="ZED-1",
        )
        resp = api.create_batch(
            c2["id"],
            {"claims": [make_claim_row(consumer["id"], "Z-001", loss_date="2025-06-06", paid_amount_cents=5000)]},
            make_data_steward_headers(c1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        batches, _ = validate_paginated(api.list_carrier_batches(c2["id"], admin_headers))
        assert batches == []


class TestAuthentication:
    def test_unauthenticated_request_missing_role_header_returns_401(self, api):
        """PRD §2.1: "A request with a missing header, or an `X-User-Role`
        value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)"

        Design: Corner/validations/unauthenticated_request_missing_role_header_returns_401
        """
        set_clock()
        resp = api.list_carriers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestPermissiblePurpose:
    def test_consumer_request_purpose_must_resolve_to_acting_consumer(self, api):
        """PRD §3.4: "a `CONSUMER_REQUEST` inquiry is only lawful when the
        supplied subject identifiers resolve to the acting consumer — otherwise
        it fails with the same error."
        PRD §3.4: "The permissible purpose must be one of `UNDERWRITING`,
        `CLAIMS`, or `CONSUMER_REQUEST`; a missing or out-of-enum value is
        rejected with `ERR_PERMISSIBLE_PURPOSE` (HTTP 403)"

        Design: Corner/validations/consumer_request_purpose_must_resolve_to_acting_consumer
        """
        from test_helpers import activate_carrier, init_exchange_rules

        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Bosque Mutual", naic_code="90014")
        consumer = create_consumer(
            full_name="Hal Hales",
            date_of_birth="1978-10-02",
            address_line="40 Hawthorn Hl, Tyler TX",
            driver_license_number="HAL-1",
        )
        activate_carrier(carrier, consumer, loss_date="2025-02-14", paid_amount_cents=12000)
        resp = api.create_inquiry(
            carrier["id"],
            {
                "subject_name": "Hal Hales",
                "subject_dob": "1978-10-02",
                "subject_address": "40 Hawthorn Hl, Tyler TX",
                "subject_driver_license": "HAL-1",
                "permissible_purpose": "CONSUMER_REQUEST",
            },
            make_underwriter_headers(carrier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PERMISSIBLE_PURPOSE, 403)


class TestBatchConstraints:
    def test_duplicate_claim_number_within_carrier_rejected(self, api, compliance_headers):
        """PRD §3.2: "The batch as a whole must contain between
        `min_batch_claims` and `max_batch_claims` rows inclusive, and no row
        may reuse a `claim_number` the carrier has already contributed; either
        violation is rejected with `ERR_BATCH_CONSTRAINT` (HTTP 422)."

        Design: Corner/validations/duplicate_claim_number_within_carrier_rejected
        """
        from test_helpers import init_exchange_rules, make_claim_row, submit_batch

        set_clock()
        init_exchange_rules()
        c5 = create_carrier(legal_name="Burnet General", naic_code="90015")
        c6 = create_carrier(legal_name="Bastrop National", naic_code="90016")
        consumer = create_consumer(
            full_name="Ida Innes",
            date_of_birth="1985-11-11",
            address_line="3 Iris St, Austin TX",
            driver_license_number="IDA-1",
        )
        submit_batch(
            c5, [make_claim_row(consumer["id"], "DUP-1", loss_date="2025-01-20", paid_amount_cents=4000)]
        )
        dup = api.create_batch(
            c5["id"],
            {"claims": [make_claim_row(consumer["id"], "DUP-1", loss_date="2025-02-20", paid_amount_cents=5000)]},
            make_data_steward_headers(c5["id"]),
        )
        validate_error(dup, ApiErrorId.ERR_BATCH_CONSTRAINT, 422)
        cross = api.create_batch(
            c6["id"],
            {"claims": [make_claim_row(consumer["id"], "DUP-1", loss_date="2025-02-20", paid_amount_cents=5000)]},
            make_data_steward_headers(c6["id"]),
        )
        cross_data = validate_success(cross, 201)
        assert cross_data["status"] == "COMPLETED"


class TestDisputeAgainstNonActiveClaim:
    def test_dispute_against_withdrawn_claim_returns_invalid_state(self, api, compliance_headers):
        """PRD §3.7: "Only a consumer's own disputes may be filed under their
        identity, and the disputed claim must be `ACTIVE` — a filing against a
        claim in any other status is rejected with `ERR_INVALID_STATE`"

        Design: Corner/validations/dispute_against_withdrawn_claim_returns_invalid_state
        """
        from test_helpers import (
            file_dispute,
            init_exchange_rules,
            list_consumer_active_claims,
            make_consumer_headers,
            submit_batch,
            make_claim_row,
        )

        set_clock()
        init_exchange_rules()
        carrier = create_carrier(legal_name="Bell County Mutual", naic_code="90017")
        consumer = create_consumer(
            full_name="Jay Jarrell",
            date_of_birth="1980-07-04",
            address_line="12 Juniper Cv, Belton TX",
            driver_license_number="JAY-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(consumer["id"], "J7-1", loss_date="2025-03-15", paid_amount_cents=60000)],
        )
        claim = list_consumer_active_claims(consumer)[0]
        dispute, consumer = file_dispute(consumer, claim["id"], dispute_reason="NOT_MY_CLAIM")
        resolved = api.resolve_dispute(
            dispute["id"],
            {"resolution_code": "DELETED", "resolution_notes": "Confirmed wrong household"},
            compliance_headers,
        )
        validate_success(resolved, 200)
        resp = api.create_dispute(
            consumer["id"],
            {
                "loss_claim_id": claim["id"],
                "dispute_reason": "WRONG_AMOUNT",
                "dispute_statement": "Still wrong",
                "expected_consumer_version": consumer["version"],
            },
            make_consumer_headers(consumer["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert err["error_id"] != "ERR_DISPUTE_ALREADY_OPEN"

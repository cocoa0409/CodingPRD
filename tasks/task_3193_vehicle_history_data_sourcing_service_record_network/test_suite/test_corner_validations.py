"""Breadth tests: validation rules — auth headers, brand lexicon, future event
dates, consumer credit, idempotency, dedupe, and cross-source corroboration."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    create_consumer,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    purchase_consumer_report,
    register_source,
    setup_network,
    setup_network_with_source,
    submit_record,
    submit_title,
    validate_error,
    validate_success,
)


class TestUserContextHeader:
    def test_missing_role_header_rejected(self, api, admin_headers):
        """PRD §2.1: "A request missing either header, or presenting a role the platform does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header
        """
        headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
        resp = api.create_network({"name": "N1", "guarantee_payout_cap_cents": 5_000_000}, headers)
        validate_error(resp, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestUnknownBrandTerm:
    def test_lexicon_miss_rejected(self, api, admin_headers):
        """PRD §2.7: "A `raw_brand_text` value that has no entry in the submitting record's jurisdiction lexicon cannot be normalized and is rejected with `ERR_UNKNOWN_BRAND_TERM`."

        Design: Corner/validations/unknown_brand_term_rejected
        """
        network, source = setup_network_with_source(api)
        resp = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "TITLE_BRAND",
                "jurisdiction": "CA",
                "raw_brand_text": "totaled",
                "event_date": "2026-09-01",
                "payload_ref": "t1",
                "idempotency_key": "k-t1",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(resp, ApiErrorId.UNKNOWN_BRAND_TERM)


class TestFutureEventDate:
    def test_future_date_rejected_current_date_accepted(self, api, admin_headers):
        """PRD §3.3: "An `event_date` later than the logical clock's current date is rejected with `ERR_EVENT_IN_FUTURE`."
        PRD §2.5: "At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`"

        Design: Corner/validations/future_event_date_rejected
        """
        network, source = setup_network_with_source(api)
        resp = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-02",
                "damage_severity": 2,
                "payload_ref": "a1",
                "idempotency_key": "k-a1",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(resp, ApiErrorId.EVENT_IN_FUTURE)

        ok = submit_record(
            api, source["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=2, payload_ref="a2", idempotency_key="k-a2",
        )
        assert ok["status"] == "ACTIVE", "an event date equal to the clock date must pass"


class TestInsufficientCredit:
    def test_below_price_rejected_exact_balance_accepted(self, api, admin_headers):
        """PRD §3.11: "The first purchase for a given vehicle costs 3,999 cents"
        PRD §3.11: "The account's `credit_balance_cents` must cover the price at purchase time, otherwise the purchase is rejected with `ERR_INSUFFICIENT_CREDIT`; on success the price is debited from the balance."

        Design: Corner/validations/insufficient_credit_blocks_consumer_report
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        consumer = create_consumer(api, credit_cents=3998)
        resp = api.purchase_report(
            {"vehicle_id": title["vehicle_id"], "product": "CONSUMER_SINGLE", "buyer_consumer_id": consumer["id"]},
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.INSUFFICIENT_CREDIT)

        validate_success(api.top_up_consumer_credit(consumer["id"], {"amount_cents": 1}, make_network_admin_headers()))
        order = purchase_consumer_report(api, consumer["id"], title["vehicle_id"])
        assert order["price_cents"] == 3999


class TestIdempotency:
    def test_identical_replay_returns_original_changed_payload_conflicts(self, api, admin_headers):
        """PRD §3.3: "Before any dedupe logic runs, idempotency is honored: if the same `idempotency_key` arrives with an identical payload, the original record is returned unchanged and no new record is created. If the same `idempotency_key` arrives with a different payload, the submission is rejected with `ERR_IDEMPOTENCY_CONFLICT`."

        Design: Corner/validations/idempotent_replay_vs_conflict
        """
        network, source = setup_network_with_source(api)
        first = submit_record(
            api, source["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=2, payload_ref="a1", idempotency_key="k-1",
        )
        replay = submit_record(
            api, source["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=2, payload_ref="a1", idempotency_key="k-1",
        )
        assert replay["id"] == first["id"], "identical replay must return the original record"

        conflict = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-01",
                "damage_severity": 9,
                "payload_ref": "a1",
                "idempotency_key": "k-1",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(conflict, ApiErrorId.IDEMPOTENCY_CONFLICT)


class TestSameSourceDuplicate:
    def test_identical_content_new_key_rejected_changed_content_supersedes(self, api, admin_headers):
        """PRD §3.3: "Within a group, a new submission from the same source that matches an existing `ACTIVE` record's group is resolved by content: if the content fields — `raw_brand_text`, `damage_severity`, `odometer_reading`, and `reported_cost_cents` — are all identical to the existing record but the `idempotency_key` differs, the new submission is rejected with `ERR_DUPLICATE_RECORD`; if any content field differs, the new record supersedes the old."
        PRD §3.3: "Supersession links the two records: the old record transitions from `ACTIVE` to `SUPERSEDED`, its `superseded_by_record_id` points at the new record"

        Design: Corner/validations/duplicate_record_same_source_rejected
        """
        network, source = setup_network_with_source(api)
        first = submit_title(api, source["id"], VIN_A, "CA", "clean", idempotency_key="k-1", payload_ref="t1")
        duplicate = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "TITLE_BRAND",
                "jurisdiction": "CA",
                "raw_brand_text": "clean",
                "event_date": "2026-09-01",
                "payload_ref": "t2",
                "idempotency_key": "k-2",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_RECORD)

        replacement = submit_title(api, source["id"], VIN_A, "CA", "flood", idempotency_key="k-3", payload_ref="t3")
        assert replacement["status"] == "ACTIVE"
        from test_helpers import get_record
        old = get_record(api, first["id"])
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_record_id"] == replacement["id"]


class TestCrossSourceCorroboration:
    def test_different_source_same_day_accident_accepted_with_bonus(self, api, admin_headers):
        """PRD §3.3: "A submission from a different source in the same group is accepted as corroboration, not a duplicate."
        PRD §3.5: "Records in that set from sources of a different `source_type` contribute a cross-type bonus of 20 points each"

        Design: Corner/validations/cross_source_same_date_accident_accepted
        """
        network, mva = setup_network_with_source(api)
        ins = register_source(api, source_type="INSURER")
        first = submit_record(
            api, mva["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=2, payload_ref="a1", idempotency_key="k-a1",
        )
        second = submit_record(
            api, ins["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=2, payload_ref="a2", idempotency_key="k-a2",
        )
        assert second["id"] != first["id"]
        assert second["status"] == "ACTIVE"
        # 40 base + 20 cross-type bonus at reliability 100.
        assert second["confidence_score"] == 60, (
            f"cross-source corroboration scores 60, got {second['confidence_score']}"
        )

"""Log ingestion, exclusion filters, and reindexing (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_exclusion_filter_payload,
    create_log_event_payload,
    get_meter_accumulator,
    set_clock,
    setup_account_with_retention_tier,
    setup_excluded_log_event,
    setup_period_with_retention_tier,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BA, IA, close_period


class TestFilterDefaultsAndRetrieval:
    def test_filter_enabled_defaults_true(self, api):
        """PRD §3.3: "filters are created with their `service_tag_pattern`,
        `sample_rate_pct`, `priority`, and optional `enabled` flag (defaulting to
        true)".

        Design: Corner/entities/exclusion_filter_default_enabled_true
        """
        account, period, tier = setup_period_with_retention_tier(name="Default")
        resp = api.create_exclusion_filter(
            account["id"],
            {"service_tag_pattern": "x-*", "sample_rate_pct": 0, "priority": 1},
            BA,
        )
        data = validate_success(resp, expected_status=201)
        assert data["enabled"] is True

    def test_retention_tier_round_trips_stored_configuration(self, api):
        """PRD §3.5: "A `BillingAdmin` creates one with a `name`, the
        `retention_days` an indexed event remains queryable, and an effective window
        bounded by `effective_from_utc` (inclusive) and `effective_to_utc`
        (exclusive)". "The tier's commercial lever is `index_rate_multiplier_bp`".

        Design: Corner/entities/retention_tier_get_returns_stored_configuration
        """
        account, tier = setup_account_with_retention_tier(
            name="RT", retention_days=15, index_rate_multiplier_bp=15000
        )
        rows, meta = validate_paginated(api.list_retention_tiers(account["id"], BA))
        assert len(rows) == 1 and meta["total_count"] == 1
        assert rows[0]["index_rate_multiplier_bp"] == 15000
        assert rows[0]["retention_days"] == 15


class TestFilterSelection:
    def test_lower_priority_wins_over_higher(self, api):
        """PRD §3.3: "If candidates exist, the winner is the candidate with the
        lowest `priority` value; ties are broken by earlier `created_at`, and the
        record's `id` must never be used as a tie-breaker. When the winning filter's
        `sample_rate_pct` is 0, the event becomes `EXCLUDED`."

        Design: Corner/calculations/exclusion_filter_selection_priority_then_created_at_tiebreak
        """
        account, period, tier = setup_period_with_retention_tier(name="Filter")
        validate_success(
            api.create_exclusion_filter(
                account["id"],
                create_exclusion_filter_payload(
                    service_tag_pattern="web-*", sample_rate_pct=0, priority=2
                ),
                BA,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_exclusion_filter(
                account["id"],
                create_exclusion_filter_payload(
                    service_tag_pattern="web-*", sample_rate_pct=100, priority=1
                ),
                BA,
            ),
            expected_status=201,
        )
        event = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(
                    size_bytes=50, service_tag="web-server",
                    retention_tier_id=tier["id"],
                ),
                IA,
            ),
            expected_status=201,
        )
        # The priority=1 filter admits 100% of matched events.
        assert event["exclusion_state"] == "INDEXED"

    def test_sample_rate_zero_excludes_matched_event(self, api):
        """PRD §3.3: "When the winning filter's `sample_rate_pct` is 0, the event
        becomes `EXCLUDED`."
        PRD §3.3: "If no candidate matches, no filter applies and the event becomes
        `INDEXED`."

        Design: Corner/calculations/exclusion_filter_selection_priority_then_created_at_tiebreak
        """
        account, period, tier = setup_period_with_retention_tier(name="ZeroRate")
        validate_success(
            api.create_exclusion_filter(
                account["id"],
                create_exclusion_filter_payload(
                    service_tag_pattern="noisy-*", sample_rate_pct=0, priority=1
                ),
                BA,
            ),
            expected_status=201,
        )
        excluded = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(service_tag="noisy-a", retention_tier_id=tier["id"]),
                IA,
            ),
            expected_status=201,
        )
        assert excluded["exclusion_state"] == "EXCLUDED"
        unmatched = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(service_tag="quiet-b", retention_tier_id=tier["id"]),
                IA,
            ),
            expected_status=201,
        )
        assert unmatched["exclusion_state"] == "INDEXED"

    def test_disabled_filter_never_matches(self, api):
        """PRD §3.3: "Filters with `enabled` set to false never match."

        Design: Corner/calculations/exclusion_filter_selection_priority_then_created_at_tiebreak
        """
        account, period, tier = setup_period_with_retention_tier(name="Disabled")
        validate_success(
            api.create_exclusion_filter(
                account["id"],
                create_exclusion_filter_payload(
                    service_tag_pattern="noisy-*", sample_rate_pct=0,
                    priority=1, enabled=False,
                ),
                BA,
            ),
            expected_status=201,
        )
        event = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(service_tag="noisy-x", retention_tier_id=tier["id"]),
                IA,
            ),
            expected_status=201,
        )
        assert event["exclusion_state"] == "INDEXED"


class TestIngestIndexLegs:
    def test_provisional_ingest_leg_only_on_excluded_events(self, api):
        """PRD §3.3: "Whichever way the decision lands, the ingest leg is charged:
        the `LOG_INGEST` meter accumulator's `quantity` increases by the event's
        `size_bytes`. Only when the event lands in `INDEXED` does the `LOG_INDEX`
        accumulator's `quantity` increase by 1."

        Design: Difficulty/dual_variant_calc/log_charge_provisional_vs_final_diverge_on_reindex
        """
        account, period, tier, exclusion_filter, commitment, event1 = (
            setup_excluded_log_event(
                name="Legs", event_tag="noisy-batch", size_bytes=1_000_000_000
            )
        )
        assert event1["exclusion_state"] == "EXCLUDED"
        # A disabled filter never matches, so it does not affect the next ingest.
        validate_success(
            api.create_exclusion_filter(
                account["id"],
                create_exclusion_filter_payload(
                    service_tag_pattern="unused", sample_rate_pct=100,
                    priority=0, enabled=False,
                ),
                BA,
            ),
            expected_status=201,
        )
        event2 = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(
                    size_bytes=1_000_000_000, service_tag="noisy-batch-2",
                    ingested_at_utc="2026-09-05T13:00:00Z",
                    retention_tier_id=tier["id"],
                ),
                IA,
            ),
            expected_status=201,
        )
        assert event2["exclusion_state"] == "EXCLUDED"
        ingest_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INGEST")
        assert ingest_acc["quantity"] == 2_000_000_000
        # Excluded events must not bump LOG_INDEX: the accumulator is either
        # absent (lazily created) or present with zero quantity.
        index_rows = validate_success(
            api.list_meter_accumulators(
                account["id"], period["id"], BA, params={"meter": "LOG_INDEX"}
            )
        )
        assert all(r["quantity"] == 0 for r in index_rows)

    def test_indexed_event_bumps_both_legs(self, api):
        """PRD §3.3: "Whichever way the decision lands, the ingest leg is charged:
        the `LOG_INGEST` meter accumulator's `quantity` increases by the event's
        `size_bytes`. Only when the event lands in `INDEXED` does the `LOG_INDEX`
        accumulator's `quantity` increase by 1."

        Design: Difficulty/dual_variant_calc/log_charge_provisional_vs_final_diverge_on_reindex
        """
        account, period, tier = setup_period_with_retention_tier(name="BothLegs")
        event = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(
                    size_bytes=500, service_tag="quiet-svc",
                    retention_tier_id=tier["id"],
                ),
                IA,
            ),
            expected_status=201,
        )
        assert event["exclusion_state"] == "INDEXED"
        ingest_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INGEST")
        index_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INDEX")
        assert ingest_acc["quantity"] == 500
        assert index_acc["quantity"] == 1


class TestReindex:
    def test_reindex_cascades_to_accumulator_and_commitment(self, api):
        """PRD §3.3: "A successful reindex increments the `LOG_INDEX` accumulator's
        `quantity` by 1 and debits the account's active `LOG_INDEX` commitment by 1".
        PRD §3.4: "When `consumed_quantity` reaches `committed_quantity`, the
        commitment transitions automatically from `ACTIVE` to `EXHAUSTED`".

        Design: Difficulty/transitive_cascade/reindex_cascade_depth_3
        """
        account, period, tier, exclusion_filter, commitment, event = (
            setup_excluded_log_event(
                name="Cascade Test", event_tag="noisy-worker",
                size_bytes=500, committed_quantity=1,
            )
        )
        assert event["exclusion_state"] == "EXCLUDED"
        validate_success(
            api.disable_exclusion_filter(account["id"], exclusion_filter["id"], BA)
        )
        reindexed = validate_success(
            api.reindex_log_event(account["id"], event["id"], BA)
        )
        assert reindexed["exclusion_state"] == "INDEXED"
        index_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INDEX")
        assert index_acc["quantity"] == 1
        commitment = validate_success(
            api.get_commitment_flat(commitment["id"], BA)
        )
        assert commitment["consumed_quantity"] == 1
        assert commitment["status"] == "EXHAUSTED"

    def test_reindex_blocked_by_hard_exclusion(self, api):
        """PRD §3.3: "it is also refused when an enabled exclusion filter currently
        matches the event with a `sample_rate_pct` of 0 — such an event is under a
        hard exclusion and may not be revived."

        Design: Difficulty/transitive_cascade/reindex_cascade_depth_3
        """
        account, period, tier, exclusion_filter, commitment, event = (
            setup_excluded_log_event(name="HardExcl", event_tag="noisy-worker")
        )
        # The enabled sample_rate_pct=0 filter still matches: reindex must not
        # succeed and the event stays EXCLUDED.
        resp = api.reindex_log_event(account["id"], event["id"], BA)
        assert resp.status_code >= 400, (
            f"hard-excluded event must not reindex, got {resp.status_code}"
        )
        refreshed = validate_success(api.get_log_event_flat(event["id"], BA))
        assert refreshed["exclusion_state"] == "EXCLUDED"

    def test_reindex_rejected_when_period_closed(self, api):
        """PRD §3.3: "Reindexing is refused with `ERR_PERIOD_CLOSED` once the
        parent period is past `OPEN`; it is also refused when an enabled exclusion
        filter currently matches the event with a `sample_rate_pct` of 0".

        Design: Difficulty/cross_entity_state_dependency/log_reindex_requires_period_open
        """
        account, period, tier, exclusion_filter, commitment, event = (
            setup_excluded_log_event(
                name="Period Gate", event_tag="noisy-x", size_bytes=100
            )
        )
        close_period(account["id"], period["id"])
        resp = api.reindex_log_event(account["id"], event["id"], BA)
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)
        refreshed = validate_success(api.get_log_event_flat(event["id"], BA))
        assert refreshed["exclusion_state"] == "EXCLUDED"

    def test_reindex_rejected_without_active_log_index_commitment(self, api):
        """PRD §3.3: "when no such active commitment exists, the reindex is
        rejected with `ERR_NO_ACTIVE_COMMITMENT`."

        Design: Difficulty/cross_entity_state_dependency/log_reindex_requires_period_open
        """
        account, period, tier, exclusion_filter, commitment, event = (
            setup_excluded_log_event(
                name="NoCommit", event_tag="noisy-y",
                with_log_index_commitment=False,
            )
        )
        validate_success(
            api.disable_exclusion_filter(account["id"], exclusion_filter["id"], BA)
        )
        resp = api.reindex_log_event(account["id"], event["id"], BA)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_COMMITMENT.value)


class TestLogIngestInvariant:
    def test_ingest_bytes_conserved_through_reindex(self, api):
        """PRD §3.3: "Whichever way the decision lands, the ingest leg is charged:
        the `LOG_INGEST` meter accumulator's `quantity` increases by the event's
        `size_bytes`."
        PRD §3.3: "The index leg is charged at reindex time; the ingest leg is
        never re-charged."

        Design: Difficulty/compensating_invariant/log_ingest_equals_indexed_plus_excluded_invariant
        """
        account, period, tier, exclusion_filter, commitment, ev_a = (
            setup_excluded_log_event(
                name="Invariant Log", event_tag="noisy-a", size_bytes=100
            )
        )
        ev_b = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(
                    size_bytes=200, service_tag="quiet-b",
                    ingested_at_utc="2026-09-05T01:00:00Z",
                    retention_tier_id=tier["id"],
                ),
                IA,
            ),
            expected_status=201,
        )
        assert ev_a["exclusion_state"] == "EXCLUDED"
        assert ev_b["exclusion_state"] == "INDEXED"

        ingest_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INGEST")
        assert ingest_acc["quantity"] == 300

        validate_success(
            api.disable_exclusion_filter(account["id"], exclusion_filter["id"], BA)
        )
        validate_success(api.reindex_log_event(account["id"], ev_a["id"], BA))

        # Ingest bytes are conserved: reindex never re-charges the ingest leg.
        ingest_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INGEST")
        index_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INDEX")
        assert ingest_acc["quantity"] == 300
        assert index_acc["quantity"] == 2

        events, _meta = validate_paginated(
            api.list_log_events(account["id"], period["id"], BA)
        )
        indexed_bytes = sum(
            e["size_bytes"] for e in events if e["exclusion_state"] == "INDEXED"
        )
        excluded_bytes = sum(
            e["size_bytes"] for e in events if e["exclusion_state"] == "EXCLUDED"
        )
        assert indexed_bytes == 300
        assert excluded_bytes == 0
        assert ingest_acc["quantity"] == indexed_bytes + excluded_bytes

    def test_ingest_bytes_split_between_indexed_and_excluded(self, api):
        """PRD §3.3: "Whichever way the decision lands, the ingest leg is charged:
        the `LOG_INGEST` meter accumulator's `quantity` increases by the event's
        `size_bytes`."

        Design: Difficulty/compensating_invariant/log_ingest_equals_indexed_plus_excluded_invariant
        """
        account, period, tier, exclusion_filter, commitment, ev_a = (
            setup_excluded_log_event(
                name="Invariant Split", event_tag="noisy-a", size_bytes=100
            )
        )
        ev_b = validate_success(
            api.ingest_log_event(
                account["id"],
                period["id"],
                create_log_event_payload(
                    size_bytes=200, service_tag="quiet-b",
                    ingested_at_utc="2026-09-05T01:00:00Z",
                    retention_tier_id=tier["id"],
                ),
                IA,
            ),
            expected_status=201,
        )
        ingest_acc = get_meter_accumulator(account["id"], period["id"], "LOG_INGEST")
        events, _meta = validate_paginated(
            api.list_log_events(account["id"], period["id"], BA)
        )
        indexed_bytes = sum(
            e["size_bytes"] for e in events if e["exclusion_state"] == "INDEXED"
        )
        excluded_bytes = sum(
            e["size_bytes"] for e in events if e["exclusion_state"] == "EXCLUDED"
        )
        # Before any reindex: 100 bytes sit in EXCLUDED, 200 in INDEXED.
        assert indexed_bytes == 200
        assert excluded_bytes == 100
        assert ingest_acc["quantity"] == indexed_bytes + excluded_bytes

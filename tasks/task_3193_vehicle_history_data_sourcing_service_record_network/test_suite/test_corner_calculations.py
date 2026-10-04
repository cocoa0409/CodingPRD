"""Breadth tests: calculations — VIN matching, brand rollup, odometer
monotonicity, and the unreliable-record purge timing."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    advance_epoch,
    create_active_shop,
    get_record,
    get_vehicle,
    make_shop_operator_headers,
    make_source_operator_headers,
    register_source,
    setup_network_with_source,
    submit_inspection,
    submit_record,
    submit_service_record,
    submit_title,
    validate_error,
    validate_success,
)


class TestFuzzyVinMatch:
    def test_single_position_difference_attaches_fuzzy(self, api, admin_headers):
        """PRD §3.3: "When no exact match exists but exactly one vehicle in the network has a `vin` of the same 17-character length differing from the submitted VIN in exactly one character position, the record attaches to that vehicle with `match_method` `FUZZY_VIN`."

        Design: Corner/calculations/fuzzy_vin_single_position_match
        """
        network, source = setup_network_with_source(api)
        first = submit_inspection(api, source["id"], "1HGCM82633A004352", 10_000)
        second = submit_inspection(
            api, source["id"], "1HGCM82633A004353", 10_050, idempotency_key="k-i2", payload_ref="i2",
        )
        assert second["vehicle_id"] == first["vehicle_id"], (
            "a one-character-different VIN must attach to the existing vehicle"
        )
        assert second["match_method"] == "FUZZY_VIN"


class TestAmbiguousVinRejected:
    def test_two_distance_one_candidates_rejected(self, api, admin_headers):
        """PRD §3.3: "When more than one existing vehicle sits at that distance, the submission is rejected with `ERR_AMBIGUOUS_VIN_MATCH` rather than risk a misattribution."

        Design: Corner/calculations/ambiguous_vin_rejected
        """
        network, source = setup_network_with_source(api)
        submit_inspection(api, source["id"], "1HGCM82633A004352", 10_000)
        # Second vehicle must sit at distance >= 2 from the first (else it
        # fuzzy-attaches instead of creating a second vehicle), while both sit
        # at distance exactly 1 from the probe VIN below.
        submit_inspection(api, source["id"], "1HGCM82633A004341", 9_000, idempotency_key="k-i2", payload_ref="i2")
        resp = api.create_record(
            {
                "vin": "1HGCM82633A004342",
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-01",
                "damage_severity": 2,
                "payload_ref": "a1",
                "idempotency_key": "k-a1",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(resp, ApiErrorId.AMBIGUOUS_VIN_MATCH)


class TestBrandRollupMaxSeverity:
    def test_max_severity_wins_regardless_of_arrival_order(self, api, admin_headers):
        """PRD §3.4: "Its `canonical_brand` is the brand of highest severity among the vehicle's `ACTIVE` title-brand records — `NONE` when no such records exist, with `brand_severity` 0 — and ties are broken by earliest `event_date`, then by earliest record `created_at`. Its `brand_severity` mirrors the winning record's severity."

        Design: Corner/calculations/brand_rollup_max_severity_wins
        """
        network, source = setup_network_with_source(api)
        salvage = submit_title(
            api, source["id"], VIN_A, "TX", "salvage title",
            event_date="2026-08-01", idempotency_key="k-t1", payload_ref="t1",
        )
        # REBUILT (severity 4) arrives after SALVAGE (severity 5); the max still wins.
        submit_title(
            api, source["id"], VIN_A, "CA", "revived salvage",
            event_date="2026-08-15", idempotency_key="k-t2", payload_ref="t2",
        )
        vehicle = get_vehicle(api, salvage["vehicle_id"])
        assert vehicle["canonical_brand"] == "SALVAGE"
        assert vehicle["brand_severity"] == 5, (
            f"max severity wins over the later-ingested REBUILT, got {vehicle['brand_severity']}"
        )


class TestOdometerMonotonicity:
    def test_earlier_dated_readings_do_not_constrain_later_readings(self, api, admin_headers):
        """PRD §3.6: "Service and inspection records — from shops and external sources alike — are subject to odometer monotonicity: the submitted `odometer_reading` must be at least the maximum odometer reading across the vehicle's `ACTIVE` service and inspection records with an earlier `event_date`."

        Design: Corner/calculations/odometer_rollback_rejected
        """
        setup_network_with_source(api)
        shop = create_active_shop(api)
        # Baseline: 10,000 mi recorded on 2026-08-01.
        submit_service_record(api, shop["id"], odometer_reading=10_000, event_date="2026-08-01",
                              idempotency_key="k-s1", payload_ref="s1")
        # A later event date may carry the same odometer without rolling back.
        ok = submit_service_record(api, shop["id"], odometer_reading=10_000, event_date="2026-08-15",
                                   idempotency_key="k-s2", payload_ref="s2")
        assert ok["status"] == "ACTIVE"

    def test_rollback_below_max_of_earlier_dated_records_rejected(self, api, admin_headers):
        """PRD §3.6: "A reading below that maximum is rejected with `ERR_ODOMETER_ROLLBACK`."

        Design: Corner/calculations/odometer_rollback_rejected
        """
        setup_network_with_source(api)
        shop = create_active_shop(api)
        submit_service_record(api, shop["id"], odometer_reading=10_000, event_date="2026-08-01",
                              idempotency_key="k-s1", payload_ref="s1")
        resp = api.create_service_record(
            shop["id"],
            {
                "vin": "1HGCM82633A004352",
                "event_date": "2026-08-15",
                "odometer_reading": 9_000,
                "payload_ref": "s2",
                "idempotency_key": "k-s2",
            },
            make_shop_operator_headers(shop["id"]),
        )
        validate_error(resp, ApiErrorId.ODOMETER_ROLLBACK)


class TestConfidencePurgeTiming:
    def test_unreliable_record_survives_one_epoch_then_voided(self, api, admin_headers):
        """PRD §3.5: "The epoch advance then purges unreliable history: any `ACTIVE` accident record whose recomputed `confidence_score` is below 40 and whose `submitted_epoch_index` is at least 2 epochs behind the current `epoch_index` — that is, the submitted epoch is less than or equal to the current epoch minus 2 — transitions from `ACTIVE` to `VOIDED`, decrementing the vehicle's `active_record_count` by one and re-running the accident rollup."
        PRD §3.2: "If the count is at least one, `consecutive_missed_epochs` resets to 0 and the `reliability_score` rises by 2, never exceeding 100."

        Design: Corner/calculations/confidence_threshold_purge_timing
        """
        network, source = setup_network_with_source(api)
        # Epoch 0: an inspection submission so the 0 -> 1 sweep sees activity.
        submit_inspection(api, source["id"], "9YJSA1E26HF122339", 10, idempotency_key="k-seed", payload_ref="seed")
        advance_epoch(api, 1)  # 0 -> 1: hit, reliability stays 100 (clamped)
        advance_epoch(api, 1)  # 1 -> 2: miss, 100 -> 90

        # Accident submitted at epoch 2 with reliability 90: floor(40 * 0.9) = 36 -> UNRELIABLE.
        record = submit_record(
            api, source["id"], vin=VIN_A, record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=6, payload_ref="a1", idempotency_key="k-a1",
        )
        assert record["confidence_score"] == 36, (
            f"reliability 90 at ingest must score floor(40 * 90/100) = 36, got {record['confidence_score']}"
        )
        assert record["confidence_level"] == "UNRELIABLE"

        advance_epoch(api, 1)  # 2 -> 3: epoch 2 had the accident, so no decay; age is 1 (< 2)
        after_one = get_record(api, record["id"])
        assert after_one["status"] == "ACTIVE", (
            f"age 1 is below the 2-epoch purge threshold, got {after_one['status']}"
        )

        advance_epoch(api, 1)  # 3 -> 4: epoch 3 was a miss, 90 -> 80; recompute floor(40*0.8)=32; age 2 >= 2
        after_two = get_record(api, record["id"])
        assert after_two["status"] == "VOIDED", (
            f"age 2 with score below 40 must be voided, got {after_two['status']}"
        )

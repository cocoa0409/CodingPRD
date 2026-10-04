"""Depth tests: transitive cascades — the epoch-driven depth-3 chain and the
correction-apply depth-2 chain."""

from test_helpers import (
    VIN_A,
    VIN_B,
    advance_epoch,
    create_consumer,
    create_dealer,
    file_claim,
    get_claim,
    get_network,
    get_record,
    get_source,
    get_vehicle,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    open_correction,
    setup_enrolled_listing_with_escalation,
    setup_network_with_source,
    submit_title,
    validate_success,
)


class TestEpochCascadeSourceRecordVehicleClaim:
    def test_suspension_cascade_withdraws_records(self, api, admin_headers):
        """PRD §3.2: "The source's `suspended_epoch_index` is stamped with the current `epoch_index`, and every `ACTIVE` history record attributed to that source cascades to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/epoch_cascade_source_to_record_to_vehicle_to_claim
        """
        network, source = setup_network_with_source(api)
        record = submit_title(api, source["id"], VIN_A, "TX", "salvage title")
        # Advance 1 counts the epoch-0 submission (hit); advances 2-4 are three
        # consecutive misses -> streak 3 -> suspension.
        advance_epoch(api, 4)
        source_after = get_source(api, source["id"])
        assert source_after["status"] == "SUSPENDED", (
            f"hop 1: miss-streak auto-suspension at epoch 4, got {source_after['status']}"
        )
        record_after = get_record(api, record["id"])
        assert record_after["status"] == "WITHDRAWN", (
            f"hop 2: suspension cascade withdraws the source's ACTIVE records, got {record_after['status']}"
        )

    def test_withdrawal_rollup_denies_open_claim(self, api, admin_headers):
        """PRD §3.2: "Rollup changes may invalidate `OPEN` guarantee-claim escalations; those claims are re-evaluated during the same epoch advance's claim sweep and are moved to `DENIED` if the escalation no longer holds."
        PRD §3.10: "The epoch advance runs the claim sweep: any `OPEN` claim whose escalation no longer holds — for example because the record that produced the escalation has since been withdrawn — is moved to terminal `DENIED`."

        Design: Difficulty/transitive_cascade/epoch_cascade_source_to_record_to_vehicle_to_claim
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        # Listed vehicle enrolled at CLEAN, then escalated to SALVAGE (2 submissions so far).
        listing, vehicle_id = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], vin=VIN_A,
        )
        claim = file_claim(api, listing["id"], claimant_name="B", claim_reason="salvage")
        assert claim["status"] == "OPEN"
        # Epoch 1 counts the epoch-0 submissions (no miss); epochs 2, 3 and 4 are
        # the three consecutive misses that trigger auto-suspension.
        advance_epoch(api, 4)
        source_after = get_source(api, source["id"])
        assert source_after["status"] == "SUSPENDED"
        vehicle_after = get_vehicle(api, vehicle_id)
        # Both titles came from the suspended source, so both are WITHDRAWN and the
        # rollup drops past CLEAN to NONE (PRD §3.4: NONE when no ACTIVE titles).
        assert vehicle_after["canonical_brand"] == "NONE", (
            f"hop 3: withdrawal rollup must drop the brand to NONE, got {vehicle_after['canonical_brand']}"
        )
        claim_after = get_claim(api, claim["id"])
        assert claim_after["status"] == "DENIED", (
            f"hop 4: claim sweep must deny the claim once the escalation is gone, got {claim_after['status']}"
        )


class TestCorrectionApplyCascade:
    def test_apply_supersede_recomputes_brand_rollup(self, api, admin_headers):
        """PRD §3.7: "A supersede creates a replacement history record attributed to the target's original `source_id` carrying the corrected fields, transitions the target from `ACTIVE` to `SUPERSEDED` with `superseded_by_record_id` pointing at the replacement, and fires the supersession cascade of §3.3, including the brand rollup re-run."

        Design: Difficulty/transitive_cascade/correction_apply_cascade_record_to_vehicle_rollup
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        clean = submit_title(api, source["id"], VIN_A, "CA", "clean")
        vehicle_id, record_id = clean["vehicle_id"], clean["id"]
        listing = None
        from test_helpers import setup_enrolled_listing
        listing = setup_enrolled_listing(api, dealer["id"], vehicle_id, asking_price_cents=800_000)
        consumer = create_consumer(api)
        vehicle = get_vehicle(api, vehicle_id)
        correction = open_correction(
            api, vehicle_id, record_id, vehicle["version"],
            make_vehicle_owner_headers(consumer["id"]),
            corrected_record={"jurisdiction": "TX", "raw_brand_text": "salvage title", "event_date": "2026-09-01"},
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(source["id"])))

        applied = validate_success(api.apply_correction(
            correction["id"],
            {"resolution_action": "SUPERSEDE",
             "corrected_record": {"jurisdiction": "TX", "raw_brand_text": "salvage title", "event_date": "2026-09-01"}},
            make_network_admin_headers(),
        ))
        assert applied["status"] == "APPLIED"
        record = get_record(api, record_id)
        assert record["status"] == "SUPERSEDED"
        assert record["superseded_by_record_id"], "superseded record must point at the replacement"
        vehicle_after = get_vehicle(api, vehicle_id)
        assert vehicle_after["canonical_brand"] == "SALVAGE", (
            f"hop 2: rollup recomputed from the supersede, got {vehicle_after['canonical_brand']}"
        )
        assert vehicle_after["superseded_record_count"] == 1

    def test_enrolled_listing_count_unchanged_until_approval_voids(self, api, admin_headers):
        """PRD §3.9: "On success the listing's `guarantee_status` moves from `UNENROLLED` to `ENROLLED`, the vehicle's current `canonical_brand` is snapshotted into `enrolled_brand` as the baseline for future claims, the network's `enrolled_listing_count` increments by one, and the listing's `version` increments by one."
        PRD §3.10: "Approval computes the payout (below), stamps it into `payout_cents`, voids the listing's guarantee — `guarantee_status` moves from `ENROLLED` to `VOIDED` and the network's `enrolled_listing_count` decrements by one"

        Design: Difficulty/transitive_cascade/correction_apply_cascade_record_to_vehicle_rollup
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        clean = submit_title(api, source["id"], VIN_A, "CA", "clean")
        vehicle_id, record_id = clean["vehicle_id"], clean["id"]
        from test_helpers import setup_enrolled_listing
        listing = setup_enrolled_listing(api, dealer["id"], vehicle_id, asking_price_cents=800_000)
        assert get_network(api, network["id"])["enrolled_listing_count"] == 1

        consumer = create_consumer(api)
        vehicle = get_vehicle(api, vehicle_id)
        correction = open_correction(
            api, vehicle_id, record_id, vehicle["version"],
            make_vehicle_owner_headers(consumer["id"]),
            corrected_record={"jurisdiction": "TX", "raw_brand_text": "salvage title", "event_date": "2026-09-01"},
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(source["id"])))
        validate_success(api.apply_correction(
            correction["id"],
            {"resolution_action": "SUPERSEDE",
             "corrected_record": {"jurisdiction": "TX", "raw_brand_text": "salvage title", "event_date": "2026-09-01"}},
            make_network_admin_headers(),
        ))
        # The supersede recomputed the rollup but the enrollment count is only
        # touched by the approval's guarantee void — a different trigger.
        assert get_network(api, network["id"])["enrolled_listing_count"] == 1, (
            "enrollment count must not change at correction-apply time"
        )
        claim = file_claim(api, listing["id"], claimant_name="B", claim_reason="corrected salvage")
        approved = validate_success(api.approve_claim(claim["id"], make_guarantee_admin_headers()))
        assert approved["status"] == "APPROVED"
        assert get_network(api, network["id"])["enrolled_listing_count"] == 0, (
            "approval voids the guarantee and decrements the count"
        )

"""Depth tests: dual-variant calculations on different entity domains."""

from test_helpers import (
    ApiErrorId,
    advance_epoch,
    create_consumer,
    create_dealer,
    enroll_listing,
    file_claim,
    get_claim,
    get_record,
    get_success_data,
    get_vehicle,
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    publish_listing,
    setup_enrolled_listing_with_escalation,
    setup_network,
    setup_verified_correction,
    register_source,
    submit_title,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import VIN_A


class TestAccidentConfidenceDualVariants:
    def test_provisional_score_at_ingest_uses_submission_epoch_reliability(self, api, admin_headers):
        """PRD §3.5: "The provisional variant runs at ingest and uses the source's reliability as of the submission epoch."
        PRD §3.5: "The base of 40 plus both bonuses is then multiplied by the submitting source's `reliability_score` divided by 100 — the score clamped to the 0–100 range — and the result is rounded down to an integer."

        Design: Difficulty/dual_variant_calc/accident_confidence_provisional_vs_recomputed_variants
        """
        setup_network(api)
        source = register_source(api)
        # Drop reliability 100 -> 80 via two idle epochs (epoch-1 advance sees the
        # epoch-0 submission below; epochs 2 and 3 are misses).
        submit_title(api, source["id"], "5YJSA1E26HF122334", "CA", "clean", idempotency_key="k-seed", payload_ref="seed")
        advance_epoch(api, 1)   # epoch 0 -> 1: epoch-0 had a submission, no decay
        advance_epoch(api, 2)   # epochs 1 and 2 idle: 100 -> 90 -> 80

        resp = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-01",
                "damage_severity": 4,
                "payload_ref": "mva-1",
                "idempotency_key": "k-acc-1",
            },
            make_source_operator_headers(source["id"]),
        )
        record = validate_success(resp, expected_status=201)
        # Provisional variant: floor(40 * 80 / 100) = 32 at ingest.
        assert record["confidence_score"] == 32, (
            f"provisional variant must score floor(40 * 80/100) = 32, got {record['confidence_score']}"
        )
        assert record["confidence_level"] == "UNRELIABLE"

    def test_recomputed_variant_at_epoch_advance_uses_post_decay_reliability(self, api, admin_headers):
        """PRD §3.5: "The recomputed variant runs during each epoch advance and uses the source's post-decay reliability; a record whose recomputed score crosses below 40 becomes `UNRELIABLE`."
        PRD §3.5: "any `ACTIVE` accident record whose recomputed `confidence_score` is below 40 and whose `submitted_epoch_index` is at least 2 epochs behind the current `epoch_index` — that is, the submitted epoch is less than or equal to the current epoch minus 2 — transitions from `ACTIVE` to `VOIDED`"

        Design: Difficulty/dual_variant_calc/accident_confidence_provisional_vs_recomputed_variants
        """
        setup_network(api)
        source = register_source(api)
        submit_title(api, source["id"], "5YJSA1E26HF122334", "CA", "clean", idempotency_key="k-seed", payload_ref="seed")
        advance_epoch(api, 1)
        advance_epoch(api, 2)   # reliability now 80, source at epoch 3

        record_resp = api.create_record(            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-01",
                "damage_severity": 4,
                "payload_ref": "mva-1",
                "idempotency_key": "k-acc-1",
            },
            make_source_operator_headers(source["id"]),
        )
        record = validate_success(record_resp, expected_status=201)
        provisional_score = record["confidence_score"]
        assert provisional_score == 32

        advance_epoch(api, 1)  # epoch 3 -> 4: miss (no epoch-3 submission counted? epoch 3 had the accident) -> no, accident was epoch 3
        # Epoch 3 had a submission (the accident), so no decay at 3->4; reliability stays 80.
        # Recompute at epoch 4: floor(40 * 80/100) = 32 (unchanged because no decay occurred).
        # Advance once more with no submission: 4 -> 5 decays 80 -> 70.
        advance_epoch(api, 1)  # epoch 4 -> 5: epoch 4 was a miss, 80 -> 70

        after = get_record(api, record["id"])
        # Recomputed variant: floor(40 * 70 / 100) = 28 — same record data, decayed reliability.
        assert after["confidence_score"] == 28, (
            f"recomputed variant must score floor(40 * 70/100) = 28, got {after['confidence_score']}"
        )
        assert after["confidence_score"] != provisional_score, (
            "identical record data must diverge between the provisional and recomputed variants"
        )
        # Record submitted at epoch 3; at epoch 5 age is 2 (3 <= 5 - 2) and score 28 < 40 -> VOIDED.
        assert after["status"] == "VOIDED"


class TestGuaranteePayoutDualVariants:
    def test_uncapped_variant_pays_full_provisional_payout(self, api, admin_headers):
        """PRD §3.10: "Two variants therefore exist for identical listing and vehicle data: uncapped, when the remaining allowance covers the provisional payout in full, and capped, when earlier paid claims have drained the lifetime cap and the payout is clamped to what remains."
        PRD §3.10: "A delta of 3 or more prices the brand percentage at 100 percent"

        Design: Difficulty/dual_variant_calc/guarantee_payout_uncapped_vs_capped_variants
        """
        network = setup_network(api, cap_cents=2_000_000)
        source = register_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], vin=VIN_A, asking_price_cents=600_000,
        )
        claim = file_claim(api, listing["id"], claimant_name="Buyer A", claim_reason="salvage found")
        approved = validate_success(api.approve_claim(claim["id"], make_guarantee_admin_headers()))
        # Uncapped variant: CLEAN(1) -> SALVAGE(5) is delta 4 -> 100% of 600,000c; no prior PAID claims.
        assert approved["payout_cents"] == 600_000, (
            f"uncapped variant must pay 100% of 600,000c, got {approved['payout_cents']}"
        )

    def test_capped_variant_clamps_to_remaining_lifetime_allowance(self, api, admin_headers):
        """PRD §3.10: "The provisional payout is the base multiplied by that percentage, divided by 100, and rounded down to whole cents. The lifetime dimension then clamps: the platform sums `payout_cents` over all `PAID` claims whose listings refer to the same vehicle, subtracts that from the network's `guarantee_payout_cap_cents` (never below zero), and the final `payout_cents` is the smaller of the provisional payout and that remaining lifetime allowance."
        PRD §3.10: "And one epoch after approval, the advance moves an `APPROVED` claim to terminal `PAID`, stamping `payout_epoch_index` with the current epoch and drawing the payout against the per-vehicle lifetime cap."

        Design: Difficulty/dual_variant_calc/guarantee_payout_uncapped_vs_capped_variants
        """
        network = setup_network(api, cap_cents=2_000_000)
        source = register_source(api)
        dealer = create_dealer(api)
        listing1, vehicle_id = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], vin=VIN_A, asking_price_cents=600_000,
        )
        claim1 = file_claim(api, listing1["id"], claimant_name="Buyer A", claim_reason="salvage found")
        approved1 = validate_success(api.approve_claim(claim1["id"], make_guarantee_admin_headers()))
        assert approved1["payout_cents"] == 600_000

        # One epoch after approval the claim becomes PAID, drawing 600,000c against
        # the vehicle's 2,000,000c lifetime cap.
        advance_epoch(api, 1)
        claim1_after = get_claim(api, claim1["id"])
        assert claim1_after["status"] == "PAID", (
            f"claim must be PAID one epoch after approval, got {claim1_after['status']}"
        )

        # Second listing over the SAME vehicle. The vehicle's canonical_brand is
        # SALVAGE after the escalation, and PRD §3.9 refuses enrollment unless the
        # severity is at most 1 — so the escalation must first be withdrawn through
        # the correction workflow, restoring the brand to CLEAN.
        vehicle = get_vehicle(api, vehicle_id)
        salvage_record = [
            r for r in get_success_data(api.list_vehicle_records(vehicle_id, admin_headers))
            if r["record_type"] == "TITLE_BRAND" and r["status"] == "ACTIVE"
            and r.get("canonical_brand") == "SALVAGE"
        ][0]
        consumer = create_consumer(api)
        correction = setup_verified_correction(
            api, vehicle_id, salvage_record["id"], vehicle["version"],
            make_vehicle_owner_headers(consumer["id"]), source["id"],
        )
        validate_success(api.apply_correction(
            correction["id"], {"resolution_action": "WITHDRAW"}, make_network_admin_headers()))
        vehicle = get_vehicle(api, vehicle_id)
        assert vehicle["canonical_brand"] == "CLEAN"

        created2 = validate_success(
            api.create_listing(
                dealer["id"],
                {"vehicle_id": vehicle_id, "asking_price_cents": 2_000_000},
                make_dealer_agent_headers(dealer["id"]),
            ),
            expected_status=201,
        )
        published2 = publish_listing(api, dealer["id"], created2["id"])
        enrolled2 = enroll_listing(api, dealer["id"], published2["id"], published2["version"])
        assert enrolled2["guarantee_status"] == "ENROLLED"

        # Re-escalate: a fresh SALVAGE title restores the delta over the CLEAN baseline.
        submit_title(api, source["id"], VIN_A, "TX", "salvage title",
                     idempotency_key="k-cap-salvage2", payload_ref="cap-salvage2")

        claim2 = file_claim(api, enrolled2["id"], claimant_name="Buyer B", claim_reason="salvage still on record")
        approved2 = validate_success(api.approve_claim(claim2["id"], make_guarantee_admin_headers()))
        # Capped variant: provisional 100% of 2,000,000c clamped to 2,000,000 - 600,000 = 1,400,000c.
        assert approved2["payout_cents"] == 1_400_000, (
            f"capped variant must clamp to the remaining 1,400,000c, got {approved2['payout_cents']}"
        )
        assert approved2["payout_cents"] != 2_000_000, (
            "the two variants must diverge for identical escalation data because of prior cap drain"
        )

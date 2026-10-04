"""Difficulty rule: transitive_cascade.

Batch rejection cascades to source suspension which then blocks new batches;
edition withdrawal cascades to offer voidance which then blocks disputes.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_region, make_config, make_source, reject_n_batches, get_source,
    setup_offer_scenario, create_batch_item_payload, create_batch_payload,
    make_consumer_headers, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


class TestBatchRejectToSourceSuspensionBlocksNewBatch:
    def test_fifth_rejection_suspends_source(self, api):
        """PRD §3.2: "Rejection moves it RECEIVED -> REJECTED and increments
        the submitting source's consecutive_rejections; when that counter
        reaches 5 the source auto-suspends — whether it was PROBATION or
        ACTIVE, it lands in SUSPENDED."

        Design: Difficulty/transitive_cascade/batch_reject_to_source_suspension_blocks_new_batch
        """
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN")
        source = make_source(region["id"], source_type="DEALER",
                             external_key="src-tc1", name="TC1")
        reject_n_batches(source["id"], config["id"], region["id"], 5, "tc1")
        source = get_source(source["id"])
        assert source["status"] == "SUSPENDED"
        assert source["consecutive_rejections"] == 5

    def test_suspended_source_batch_rejected_invalid_state(self, api):
        """PRD §3.2: "A batch can only be submitted by a source that is not
        SUSPENDED — a suspended source's submissions are rejected with
        ERR_INVALID_STATE (HTTP 409)."

        Design: Difficulty/transitive_cascade/batch_reject_to_source_suspension_blocks_new_batch
        """
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN")
        source = make_source(region["id"], source_type="DEALER",
                             external_key="src-tc1b", name="TC1B")
        reject_n_batches(source["id"], config["id"], region["id"], 5, "tc1b")
        assert get_source(source["id"])["status"] == "SUSPENDED"

        res = api.create_batch(
            create_batch_payload(
                source["id"],
                [create_batch_item_payload(config["id"], region["id"])],
                submission_ref="tc1b-blocked"),
            DATAOPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestEditionWithdrawToOfferVoidToDisputeRejection:
    def test_withdrawal_voids_quoted_offer_and_withdrawn_edition_stays_listed(self, api):
        """PRD §3.4: "When a published edition can be withdrawn — all its
        offers terminal — any of its offers still QUOTED cascade to VOID in
        the same operation" and "Withdrawn editions remain listed; history is
        never erased."

        Design: Difficulty/transitive_cascade/edition_withdraw_to_offer_void_to_dispute_rejection
        """
        env = setup_offer_scenario(segment="VAN", region_code="EAST",
                                   model="Van", trim="Base", year=2020,
                                   price_cents=3040000,
                                   offer_overrides={"mileage": 20000,
                                                    "age_years": 2})
        edition = env["edition"]
        offer = env["offer"]

        withdrawn = validate_success(
            api.withdraw_valuation_edition(edition["id"], ADMIN), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        offer_after = validate_success(
            api.get_cash_offer(offer["id"], ADMIN), 200)
        assert offer_after["status"] == "VOID"

        data, meta = validate_paginated(api.list_valuation_editions(
            ADMIN, params={"series_id": env["series"]["id"],
                           "status": "WITHDRAWN"}))
        assert any(row["id"] == edition["id"] for row in data), (
            "withdrawn edition must remain listed")

    def test_dispute_against_voided_offer_rejected(self, api):
        """PRD §3.7: "A consumer who believes a redeemed offer was mis-valued
        opens a Dispute naming the offer_id" and "An adjusted resolution
        moves OPEN -> RESOLVED_ADJUSTED — permitted only when the disputed
        offer is REDEEMED". A VOID offer (cascaded by edition withdrawal) is
        not REDEEMED, so dispute creation fails the state precondition with
        ERR_INVALID_STATE.

        Design: Difficulty/transitive_cascade/edition_withdraw_to_offer_void_to_dispute_rejection
        """
        env = setup_offer_scenario(segment="VAN", region_code="EAST",
                                   model="Van", trim="Base", year=2020,
                                   price_cents=3040000,
                                   offer_overrides={"mileage": 20000,
                                                    "age_years": 2})
        edition = env["edition"]
        offer = env["offer"]
        consumer = env["consumer"]

        validate_success(api.withdraw_valuation_edition(edition["id"], ADMIN), 200)
        assert validate_success(api.get_cash_offer(offer["id"], ADMIN), 200)["status"] == "VOID"

        res = api.create_dispute(
            {"offer_id": offer["id"], "reason_code": "STALE_DATA"},
            make_consumer_headers(consumer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

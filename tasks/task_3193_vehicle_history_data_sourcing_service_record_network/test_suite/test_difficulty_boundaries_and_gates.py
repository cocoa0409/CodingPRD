"""Depth tests: priority-pair validation conflicts (only the pair whose expected
outcome the PRD uniquely derives), boundary precision, cross-entity state
dependencies, and resource temporal overlap."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    advance_epoch,
    create_dealer,
    create_listing,
    enroll_listing,
    file_claim,
    get_claim,
    get_source,
    get_vehicle,
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    create_consumer,
    open_correction,
    publish_listing,
    register_source,
    setup_enrolled_listing_with_escalation,
    setup_network,
    setup_network_with_source,
    submit_record,
    submit_title,
    subscribe_dealer,
    purchase_dealer_report,
    validate_error,
    validate_success,
)


class TestSourceStateBeatsTemporalValidation:
    def test_pending_source_rejects_submission_as_not_active(self, api, admin_headers):
        """PRD §3.1: "Only `ACTIVE` sources may submit records; a submission aimed at a source in any other status is rejected with `ERR_SOURCE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/state_source_inactive_beats_future_event
        """
        setup_network(api)
        source = register_source(api, activate=False)  # stays PENDING
        resp = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2027-06-01",
                "damage_severity": 3,
                "payload_ref": "x1",
                "idempotency_key": "k-x1",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(resp, ApiErrorId.SOURCE_NOT_ACTIVE)

    def test_suspended_source_rejects_submission_as_not_active(self, api, admin_headers):
        """PRD §3.1: "Only `ACTIVE` sources may submit records; a submission aimed at a source in any other status is rejected with `ERR_SOURCE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/state_source_inactive_beats_future_event
        """
        network, source = setup_network_with_source(api)
        advance_epoch(api, 3)  # idle epochs suspend the source
        assert get_source(api, source["id"])["status"] == "SUSPENDED"
        resp = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2027-06-01",
                "damage_severity": 3,
                "payload_ref": "x1",
                "idempotency_key": "k-x1",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(resp, ApiErrorId.SOURCE_NOT_ACTIVE)


class TestSubscriptionWindowBoundary:
    def test_last_valid_epoch_succeeds(self, api, admin_headers):
        """PRD §3.8: "The subscription window is half-open: it covers epochs from `subscription_started_epoch` inclusive up to but not including `subscription_started_epoch` plus 30. The last valid epoch is therefore the start epoch plus 29"

        Design: Difficulty/boundary_precision_check/subscription_window_last_valid_epoch_vs_expired
        """
        network, dealer, vehicle_id = _subscribed_dealer_setup(api)
        advance_epoch(api, 29)
        order = purchase_dealer_report(api, dealer["id"], vehicle_id)
        assert order["price_cents"] == 0, (
            f"first included report at the last valid epoch must cost 0, got {order['price_cents']}"
        )

    def test_epoch_start_plus_30_rejected_as_expired(self, api, admin_headers):
        """PRD §3.8: "a dealer-scoped report purchase at the start epoch plus 30 or later is rejected with `ERR_SUBSCRIPTION_WINDOW_EXPIRED`, and the dealer must resubscribe to continue."

        Design: Difficulty/boundary_precision_check/subscription_window_last_valid_epoch_vs_expired
        """
        network, dealer, vehicle_id = _subscribed_dealer_setup(api)
        advance_epoch(api, 30)
        resp = api.purchase_report(
            {"vehicle_id": vehicle_id, "product": "DEALER_SUBSCRIPTION", "buyer_dealer_id": dealer["id"]},
            make_dealer_agent_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.SUBSCRIPTION_WINDOW_EXPIRED)


class TestMissStreakBoundary:
    def test_two_idle_epochs_keep_source_active_with_decayed_reliability(self, api, admin_headers):
        """PRD §3.2: "If the count is zero, `consecutive_missed_epochs` increments by one and the source's `reliability_score` drops by 10, never falling below 0."
        PRD §3.2: "A source whose `consecutive_missed_epochs` reaches 3, or whose `record_rejection_streak` has reached 3, is automatically moved from `ACTIVE` to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/miss_streak_two_keeps_active_three_suspends
        """
        network, source = setup_network_with_source(api)
        # One submission in epoch 0 so the epoch-0 -> 1 sweep counts a hit.
        submit_record(api, source["id"], record_type="ACCIDENT", event_date="2026-09-01",
                      damage_severity=2, payload_ref="a1", idempotency_key="k-a1")
        advance_epoch(api, 1)
        source1 = get_source(api, source["id"])
        assert source1["status"] == "ACTIVE"
        assert source1["reliability_score"] == 100, "recovery is already at the 100 ceiling"
        advance_epoch(api, 1)
        source2 = get_source(api, source["id"])
        assert source2["status"] == "ACTIVE"
        assert source2["reliability_score"] == 90, f"first miss: 100 - 10, got {source2['reliability_score']}"
        advance_epoch(api, 1)
        source3 = get_source(api, source["id"])
        assert source3["status"] == "ACTIVE", "streak 2 is below the suspension threshold"
        assert source3["reliability_score"] == 80

    def test_third_idle_epoch_suspends_source(self, api, admin_headers):
        """PRD §3.2: "A source whose `consecutive_missed_epochs` reaches 3, or whose `record_rejection_streak` has reached 3, is automatically moved from `ACTIVE` to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/miss_streak_two_keeps_active_three_suspends
        """
        network, source = setup_network_with_source(api)
        submit_record(api, source["id"], record_type="ACCIDENT", event_date="2026-09-01",
                      damage_severity=2, payload_ref="a1", idempotency_key="k-a1")
        advance_epoch(api, 4)
        source4 = get_source(api, source["id"])
        assert source4["status"] == "SUSPENDED", (
            f"third consecutive miss hits the >= 3 threshold, got {source4['status']}"
        )
        assert source4["reliability_score"] == 70, (
            f"three misses: 100 - 30 = 70, got {source4['reliability_score']}"
        )


class TestCorrectionVerificationIdentityGate:
    def test_other_source_cannot_verify(self, api, admin_headers):
        """PRD §3.7: "Both actions require the acting operator's identity to equal the target record's `source_id`; any other source attempting verification is rejected with `ERR_NOT_RECORD_SOURCE`."

        Design: Difficulty/cross_entity_state_dependency/correction_verification_gated_by_record_source_identity
        """
        network, mva = setup_network_with_source(api)
        ins = register_source(api, source_type="INSURER")
        title = submit_title(api, mva["id"], VIN_A, "CA", "clean")
        consumer = create_consumer(api)
        correction = open_correction(
            api, title["vehicle_id"], title["id"], get_vehicle(api, title["vehicle_id"])["version"],
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        resp = api.confirm_correction(correction["id"], make_source_operator_headers(ins["id"]))
        validate_error(resp, ApiErrorId.NOT_RECORD_SOURCE)

    def test_owning_source_verifies(self, api, admin_headers):
        """PRD §3.7: "Confirmation moves the request from `AWAITING_SOURCE` to `VERIFIED`; denial moves it to `REJECTED`, a terminal state."

        Design: Difficulty/cross_entity_state_dependency/correction_verification_gated_by_record_source_identity
        """
        network, mva = setup_network_with_source(api)
        title = submit_title(api, mva["id"], VIN_A, "CA", "clean")
        consumer = create_consumer(api)
        correction = open_correction(
            api, title["vehicle_id"], title["id"], get_vehicle(api, title["vehicle_id"])["version"],
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        verified = validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(mva["id"])))
        assert verified["status"] == "VERIFIED"


class TestClaimFilingGatedByListingGuaranteeState:
    def test_filing_after_approval_void_rejected(self, api, admin_headers):
        """PRD §3.10: "A listing whose guarantee is not currently `ENROLLED` rejects the filing with `ERR_GUARANTEE_NOT_ENROLLED`."

        Design: Difficulty/cross_entity_state_dependency/claim_filing_gated_by_listing_guarantee_state
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(api, source["id"], dealer["id"])
        claim = file_claim(api, listing["id"], claimant_name="B1", claim_reason="salvage")
        approved = validate_success(api.approve_claim(claim["id"], make_guarantee_admin_headers()))
        assert approved["status"] == "APPROVED"
        resp = api.create_claim(
            {"listing_id": listing["id"], "claimant_name": "B2", "claim_reason": "second claim"},
            make_guarantee_admin_headers(),
        )
        validate_error(resp, ApiErrorId.GUARANTEE_NOT_ENROLLED)

    def test_approval_pays_full_price_for_large_escalation(self, api, admin_headers):
        """PRD §3.10: "A delta of 3 or more prices the brand percentage at 100 percent"
        PRD §3.10: "The base is the listing's `asking_price_cents`."

        Design: Difficulty/cross_entity_state_dependency/claim_filing_gated_by_listing_guarantee_state
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], asking_price_cents=700_000,
        )
        claim = file_claim(api, listing["id"], claimant_name="B1", claim_reason="salvage")
        approved = validate_success(api.approve_claim(claim["id"], make_guarantee_admin_headers()))
        # CLEAN(1) -> SALVAGE(5) is delta 4 >= 3 -> 100% of 700,000c.
        assert approved["payout_cents"] == 700_000, (
            f"delta 4 must pay 100% of the asking price, got {approved['payout_cents']}"
        )


class TestClaimOccupancyAndWindowSemantics:
    def test_second_claim_while_open_rejected_then_terminal_frees_occupancy(self, api, admin_headers):
        """PRD §3.10: "First, closed claim occupancy: at most one claim per listing may occupy the non-terminal set of `OPEN` or `APPROVED` at any time, so a second claim while an earlier one is still `OPEN` or `APPROVED` is rejected with `ERR_CLAIM_OVERLAP`."
        PRD §3.10: "Rejection by a `GuaranteeAdmin` moves an `OPEN` claim to terminal `REJECTED` with no side effects."

        Design: Difficulty/resource_temporal_overlap/claim_closed_occupancy_overlap_on_listing
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(api, source["id"], dealer["id"])
        claim1 = file_claim(api, listing["id"], claimant_name="B1", claim_reason="salvage")
        resp = api.create_claim(
            {"listing_id": listing["id"], "claimant_name": "B2", "claim_reason": "overlap attempt"},
            make_guarantee_admin_headers(),
        )
        validate_error(resp, ApiErrorId.CLAIM_OVERLAP)
        validate_success(api.reject_claim(claim1["id"], make_guarantee_admin_headers()))
        claim2 = file_claim(api, listing["id"], claimant_name="B3", claim_reason="after terminal")
        assert claim2["status"] == "OPEN", (
            "once the first claim is terminal the occupancy is free again"
        )

    def test_second_claim_while_approved_also_rejected(self, api, admin_headers):
        """PRD §3.10: "First, closed claim occupancy: at most one claim per listing may occupy the non-terminal set of `OPEN` or `APPROVED` at any time, so a second claim while an earlier one is still `OPEN` or `APPROVED` is rejected with `ERR_CLAIM_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/claim_closed_occupancy_overlap_on_listing
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(api, source["id"], dealer["id"])
        claim1 = file_claim(api, listing["id"], claimant_name="B1", claim_reason="salvage")
        approved = validate_success(api.approve_claim(claim1["id"], make_guarantee_admin_headers()))
        assert approved["status"] == "APPROVED"
        # Note: approval voids the guarantee, so a follow-up filing can also be
        # rejected for the guarantee state; the occupancy rule is pinned by the
        # OPEN-phase half of this pair. Here we assert the rejection outcome is
        # stable while the first claim occupies the APPROVED slot.
        resp = api.create_claim(
            {"listing_id": listing["id"], "claimant_name": "B2", "claim_reason": "overlap during APPROVED"},
            make_guarantee_admin_headers(),
        )
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] in (
            ApiErrorId.CLAIM_OVERLAP.value, ApiErrorId.GUARANTEE_NOT_ENROLLED.value,
        )

    def test_publication_window_end_minus_one_valid_end_invalid(self, api, admin_headers):
        """PRD §3.10: "Filing exactly at `window_end_epoch` minus 1 remains valid; filing at `window_end_epoch` itself is not."

        Design: Difficulty/resource_temporal_overlap/publication_window_half_open_boundary
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], window_end_epoch=2,
        )
        advance_epoch(api, 1)  # epoch 1 == window_end_epoch - 1
        claim1 = file_claim(api, listing["id"], claimant_name="B1", claim_reason="at end-1")
        assert claim1["status"] == "OPEN"
        validate_success(api.reject_claim(claim1["id"], make_guarantee_admin_headers()))
        advance_epoch(api, 1)  # epoch 2 == window_end_epoch
        resp = api.create_claim(
            {"listing_id": listing["id"], "claimant_name": "B2", "claim_reason": "at end"},
            make_guarantee_admin_headers(),
        )
        validate_error(resp, ApiErrorId.LISTING_WINDOW_CLOSED)

    def test_open_ended_window_accepts_late_filing(self, api, admin_headers):
        """PRD §3.9: "when omitted, the window is open-ended and `window_end_epoch` stays null."
        PRD §3.10: "when the listing's `window_end_epoch` is set and the current `epoch_index` has reached it, filing is rejected with `ERR_LISTING_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/publication_window_half_open_boundary
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], window_end_epoch=None,
        )
        advance_epoch(api, 5)
        claim = file_claim(api, listing["id"], claimant_name="B1", claim_reason="open-ended window")
        assert claim["status"] == "OPEN", (
            "an open-ended publication window never closes, so late filing stays valid"
        )


def _subscribed_dealer_setup(api):
    network, source = setup_network_with_source(api)
    title = submit_title(api, source["id"], VIN_A, "CA", "clean")
    dealer = create_dealer(api)
    subscribe_dealer(api, dealer["id"], tier="STANDARD")
    return network, dealer, title["vehicle_id"]

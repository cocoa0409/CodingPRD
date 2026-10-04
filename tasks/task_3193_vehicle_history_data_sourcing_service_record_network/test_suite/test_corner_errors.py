"""Breadth tests: the error catalog — every error must be triggerable."""

from test_helpers import (
    VIN_A,
    VIN_B,
    ApiErrorId,
    advance_epoch,
    create_active_shop,
    create_consumer,
    create_dealer,
    enroll_listing,
    file_claim,
    get_dealer,
    get_vehicle,
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_shop_operator_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    open_correction,
    publish_listing,
    setup_enrolled_listing,
    setup_enrolled_listing_with_escalation,
    setup_network_with_source,
    submit_service_record,
    submit_title,
    validate_error,
    validate_success,
)


class TestSourceHasActiveRecords:
    def test_terminate_active_source_with_records_refused(self, api, admin_headers):
        """PRD §3.2: "An `ACTIVE` source may be terminated by a `NetworkAdmin` only when it has no `ACTIVE` records remaining; otherwise the termination is refused with `ERR_SOURCE_HAS_ACTIVE_RECORDS`."

        Design: Corner/errors/error_source_has_active_records
        """
        network, source = setup_network_with_source(api)
        submit_title(api, source["id"], VIN_A, "CA", "clean")
        resp = api.terminate_source(source["id"], admin_headers)
        validate_error(resp, ApiErrorId.SOURCE_HAS_ACTIVE_RECORDS)


class TestNoSubscription:
    def test_dealer_report_without_subscription_rejected(self, api, admin_headers):
        """PRD §3.11: "A dealer whose `subscription_tier` is `NONE` is rejected with `ERR_NO_SUBSCRIPTION`"

        Design: Corner/errors/error_no_subscription_for_dealer_report
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        dealer = create_dealer(api)
        resp = api.purchase_report(
            {"vehicle_id": title["vehicle_id"], "product": "DEALER_SUBSCRIPTION", "buyer_dealer_id": dealer["id"]},
            make_dealer_agent_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.NO_SUBSCRIPTION)


class TestNotEnrollable:
    def test_lemon_branded_vehicle_not_enrollable(self, api, admin_headers):
        """PRD §3.9: "Enrollment requires the listing to be `PUBLISHED`, the dealer `ACTIVE`, and the vehicle's current `canonical_brand` severity to be at most 1 — that is, `NONE` or `CLEAN`; any other combination is rejected with `ERR_NOT_ENROLLABLE`."

        Design: Corner/errors/error_not_enrollable_when_brand_severity_high
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "lemon law buyback")
        dealer = create_dealer(api)
        from test_helpers import setup_published_listing
        listing = setup_published_listing(api, dealer["id"], title["vehicle_id"])
        resp = api.enroll_guarantee(
            dealer["id"], listing["id"],
            {"expected_listing_version": listing["version"]},
            make_dealer_agent_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.NOT_ENROLLABLE)


class TestBrandNotEscalated:
    def test_approve_without_escalation_rejected(self, api, admin_headers):
        """PRD §3.10: "A `GuaranteeAdmin` approves an `OPEN` claim only when three conditions hold: the listing's `guarantee_status` is still `ENROLLED` (otherwise `ERR_GUARANTEE_NOT_ENROLLED`); the vehicle's current `canonical_brand` severity is strictly greater than the `enrolled_brand` snapshot's severity (otherwise `ERR_BRAND_NOT_ESCALATED`)"

        Design: Corner/errors/error_brand_not_escalated_on_approve
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        dealer = create_dealer(api)
        listing = setup_enrolled_listing(api, dealer["id"], title["vehicle_id"])
        claim = file_claim(api, listing["id"], claim_reason="suspect")
        resp = api.approve_claim(claim["id"], make_guarantee_admin_headers())
        validate_error(resp, ApiErrorId.BRAND_NOT_ESCALATED)


class TestCorrectionPayloadRequired:
    def test_supersede_without_corrected_record_rejected(self, api, admin_headers):
        """PRD §3.7: "`SUPERSEDE` requires the `corrected_record` payload; applying a supersede without it fails with `ERR_CORRECTION_PAYLOAD_REQUIRED`."

        Design: Corner/errors/error_correction_payload_required
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        consumer = create_consumer(api)
        correction = open_correction(
            api, title["vehicle_id"], title["id"], get_vehicle(api, title["vehicle_id"])["version"],
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(source["id"])))
        resp = api.apply_correction(correction["id"], {"resolution_action": "SUPERSEDE"}, make_network_admin_headers())
        validate_error(resp, ApiErrorId.CORRECTION_PAYLOAD_REQUIRED)


class TestShopHasOpenCorrections:
    def test_terminate_blocked_until_corrections_resolve(self, api, admin_headers):
        """PRD §3.6: "Terminating an `ACTIVE` shop is refused with `ERR_SHOP_HAS_OPEN_CORRECTIONS` while any correction request naming the shop as requester remains `OPEN` or `AWAITING_SOURCE`; otherwise the shop becomes `TERMINATED`"

        Design: Corner/errors/error_shop_has_open_corrections_on_terminate
        """
        setup_network_with_source(api)
        shop = create_active_shop(api)
        record = submit_service_record(api, shop["id"], event_date="2026-08-01")
        correction = open_correction(
            api, record["vehicle_id"], record["id"], get_vehicle(api, record["vehicle_id"])["version"],
            make_shop_operator_headers(shop["id"]), reason="wrong odometer",
        )
        resp = api.terminate_shop(shop["id"], admin_headers)
        validate_error(resp, ApiErrorId.SHOP_HAS_OPEN_CORRECTIONS)

        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        validate_success(api.deny_correction(correction["id"], make_source_operator_headers(shop["data_source_id"])))
        terminated = validate_success(api.terminate_shop(shop["id"], admin_headers))
        assert terminated["status"] == "TERMINATED"


class TestDealerSuspensionBlocksPublish:
    def test_over_threshold_dealer_suspended_at_epoch_and_blocked(self, api, admin_headers):
        """PRD §3.8: "During an epoch advance, any dealer whose `invoice_balance_cents` exceeds 1,000,000 cents — ten thousand dollars — is automatically moved from `ACTIVE` to `SUSPENDED`, and suspension blocks both listing publication and guarantee enrollment: attempts at either fail with `ERR_DEALER_SUSPENDED`."
        PRD §3.10: "adds the payout amount to the owning dealer's `invoice_balance_cents`, clawing the program cost back to the dealer ledger."

        Design: Corner/errors/error_dealer_suspension_blocks_publish
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing1, vehicle1 = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], vin=VIN_A, asking_price_cents=700_000)
        claim1 = file_claim(api, listing1["id"], claimant_name="B1")
        validate_success(api.approve_claim(claim1["id"], make_guarantee_admin_headers()))
        listing2, vehicle2 = setup_enrolled_listing_with_escalation(
            api, source["id"], dealer["id"], vin=VIN_B, asking_price_cents=700_000)
        claim2 = file_claim(api, listing2["id"], claimant_name="B2")
        validate_success(api.approve_claim(claim2["id"], make_guarantee_admin_headers()))

        draft = validate_success(api.create_listing(
            dealer["id"], {"vehicle_id": vehicle1, "asking_price_cents": 500_000},
            make_dealer_agent_headers(dealer["id"])), expected_status=201)

        advance_epoch(api, 1)
        dealer_after = get_dealer(api, dealer["id"])
        assert dealer_after["invoice_balance_cents"] == 1_400_000, (
            f"two 700,000c clawbacks, got {dealer_after['invoice_balance_cents']}"
        )
        assert dealer_after["status"] == "SUSPENDED", (
            f"1,400,000 > 1,000,000 must auto-suspend, got {dealer_after['status']}"
        )
        resp = api.publish_listing(dealer["id"], draft["id"], {}, make_dealer_agent_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.DEALER_SUSPENDED)

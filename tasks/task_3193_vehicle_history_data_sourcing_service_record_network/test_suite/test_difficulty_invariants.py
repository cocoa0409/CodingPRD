"""Depth tests: compensating invariants — the network enrollment counter over
enroll/delist, and the credit-ledger plus frozen-snapshot conservation pair."""

from test_helpers import (
    VIN_A,
    advance_epoch,
    create_consumer,
    create_dealer,
    get_consumer,
    get_network,
    get_report,
    get_vehicle,
    make_dealer_agent_headers,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    open_correction,
    purchase_consumer_report,
    setup_enrolled_listing,
    setup_network_with_source,
    setup_published_listing,
    submit_title,
    enroll_listing,
    validate_success,
)


class TestEnrolledListingCountInvariant:
    def test_enroll_then_delist_restores_count_exactly(self, api, admin_headers):
        """PRD §3.9: "On success the listing's `guarantee_status` moves from `UNENROLLED` to `ENROLLED`, the vehicle's current `canonical_brand` is snapshotted into `enrolled_brand` as the baseline for future claims, the network's `enrolled_listing_count` increments by one, and the listing's `version` increments by one."
        PRD §3.9: "Otherwise delisting an enrolled listing voids the guarantee: `guarantee_status` moves from `ENROLLED` to `VOIDED` and the network's `enrolled_listing_count` decrements by one."

        Design: Difficulty/compensating_invariant/enrolled_listing_count_preserved_over_enroll_delist
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        dealer = create_dealer(api)
        listing = setup_published_listing(api, dealer["id"], title["vehicle_id"])

        count_before = get_network(api, network["id"])["enrolled_listing_count"]
        assert count_before == 0

        enrolled = enroll_listing(api, dealer["id"], listing["id"], listing["version"])
        assert enrolled["guarantee_status"] == "ENROLLED"
        assert get_network(api, network["id"])["enrolled_listing_count"] == 1

        delisted = validate_success(api.delist_listing(
            dealer["id"], listing["id"], make_dealer_agent_headers(dealer["id"])))
        assert delisted["status"] == "DELISTED"
        assert delisted["guarantee_status"] == "VOIDED"
        count_after = get_network(api, network["id"])["enrolled_listing_count"]
        assert count_after == count_before, (
            f"enroll + delist must leave the count unchanged: {count_after} != {count_before}"
        )

    def test_two_listings_count_tracks_each_forward_and_compensating_step(self, api, admin_headers):
        """PRD §3.9: "the network's `enrolled_listing_count` increments by one"
        PRD §3.9: "Otherwise delisting an enrolled listing voids the guarantee: `guarantee_status` moves from `ENROLLED` to `VOIDED` and the network's `enrolled_listing_count` decrements by one."

        Design: Difficulty/compensating_invariant/enrolled_listing_count_preserved_over_enroll_delist
        """
        network, source = setup_network_with_source(api)
        t1 = submit_title(api, source["id"], VIN_A, "CA", "clean", idempotency_key="k-1", payload_ref="p1")
        t2 = submit_title(api, source["id"], "2HGCM82633A004353", "CA", "clean", idempotency_key="k-2", payload_ref="p2")
        dealer = create_dealer(api)
        l1 = setup_enrolled_listing(api, dealer["id"], t1["vehicle_id"])
        l2 = setup_enrolled_listing(api, dealer["id"], t2["vehicle_id"])
        assert get_network(api, network["id"])["enrolled_listing_count"] == 2

        validate_success(api.delist_listing(dealer["id"], l1["id"], make_dealer_agent_headers(dealer["id"])))
        assert get_network(api, network["id"])["enrolled_listing_count"] == 1
        validate_success(api.delist_listing(dealer["id"], l2["id"], make_dealer_agent_headers(dealer["id"])))
        assert get_network(api, network["id"])["enrolled_listing_count"] == 0


class TestCreditAndSnapshotConservation:
    def test_exact_debit_and_snapshot_frozen_pre_withdrawal(self, api, admin_headers):
        """PRD §3.11: "The first purchase for a given vehicle costs 3,999 cents"
        PRD §3.11: "on success the price is debited from the balance."
        PRD §3.11: "At purchase time the platform computes a point-in-time `snapshot` of the vehicle — its `canonical_brand`, its active title, accident, service, and inspection records, and per-accident confidence — freezes it onto the order, and never mutates it afterwards"

        Design: Difficulty/compensating_invariant/consumer_credit_conserved_over_snapshot_then_withdraw
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "TX", "salvage title")
        vehicle_id, record_id = title["vehicle_id"], title["id"]
        consumer = create_consumer(api, credit_cents=3999)

        order = purchase_consumer_report(api, consumer["id"], vehicle_id)
        assert order["snapshot"]["canonical_brand"] == "SALVAGE", (
            "snapshot captured pre-withdrawal must show SALVAGE"
        )
        balance = get_consumer(api, consumer["id"])["credit_balance_cents"]
        assert balance == 0, f"3999 - 3999 must debit to exactly 0, got {balance}"

        vehicle = get_vehicle(api, vehicle_id)
        correction = open_correction(
            api, vehicle_id, record_id, vehicle["version"],
            make_vehicle_owner_headers(consumer["id"]), reason="erroneous salvage",
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(source["id"])))
        validate_success(api.apply_correction(
            correction["id"], {"resolution_action": "WITHDRAW"}, make_network_admin_headers()))

        vehicle_after = get_vehicle(api, vehicle_id)
        assert vehicle_after["canonical_brand"] == "NONE"

    def test_snapshot_and_ledger_unchanged_after_withdrawal_compensation(self, api, admin_headers):
        """PRD §3.11: "the `price_cents` charged is likewise fixed at purchase."
        PRD §3.11: "At purchase time the platform computes a point-in-time `snapshot` of the vehicle — its `canonical_brand`, its active title, accident, service, and inspection records, and per-accident confidence — freezes it onto the order, and never mutates it afterwards"

        Design: Difficulty/compensating_invariant/consumer_credit_conserved_over_snapshot_then_withdraw
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "TX", "salvage title")
        vehicle_id, record_id = title["vehicle_id"], title["id"]
        consumer = create_consumer(api, credit_cents=3999)
        order = purchase_consumer_report(api, consumer["id"], vehicle_id)

        vehicle = get_vehicle(api, vehicle_id)
        correction = open_correction(
            api, vehicle_id, record_id, vehicle["version"],
            make_vehicle_owner_headers(consumer["id"]), reason="erroneous salvage",
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(source["id"])))
        validate_success(api.apply_correction(
            correction["id"], {"resolution_action": "WITHDRAW"}, make_network_admin_headers()))

        order_after = get_report(api, order["id"])
        assert order_after["snapshot"]["canonical_brand"] == "SALVAGE", (
            "the frozen snapshot must not drift after the underlying record is withdrawn"
        )
        assert order_after["price_cents"] == 3999
        balance_after = get_consumer(api, consumer["id"])["credit_balance_cents"]
        assert balance_after == 0, (
            f"withdrawal issues no refund; the ledger stays conserved, got {balance_after}"
        )

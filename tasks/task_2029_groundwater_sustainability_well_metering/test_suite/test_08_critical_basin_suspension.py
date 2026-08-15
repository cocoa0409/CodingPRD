"""CRITICAL basin posture: market suspension, settlement gating, proposal expiry,
and curtailment (PRD §2.7, §3.4, §3.5, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_transfer,
    cancel_transfer,
    create_account,
    create_basin_snapshot,
    create_transfer_order_payload,
    get_account,
    make_well_owner_headers,
    propose_transfer,
    publish_basin_snapshot,
    record_monitoring_reading,
    setup_basin_condition,
    validate_error,
    validate_success,
)

# Readings that put 2 of 4 wells over the 100-ft threshold -> breach_pct 50.00 -> CRITICAL.
CRITICAL_DEPTHS = [130.0, 125.0, 60.0, 55.0]
# Readings that put 1 of 4 wells over the threshold -> breach_pct 25.00 -> WATCH.
WATCH_DEPTHS = [130.0, 50.0, 55.0, 60.0]


class TestCriticalPublishCascade:
    def test_critical_publish_expires_proposals_releases_reserves(self, api, water_master_headers):
        """PRD §3.5: "Critically, when a published snapshot's `condition` is `CRITICAL`, every transfer order still in `PROPOSED` immediately transitions to `EXPIRED` — a market-wide suspension — and each such expiry releases its seller's reservation by decreasing `transfer_reserved_af` by the order's `quantity_af`."

        Design: Difficulty/transitive_cascade/critical_publish_expires_proposals_releases_reserves
        """
        seller = create_account(holder_name="Seller GS", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer GB", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 20.000)
        assert get_account(seller["id"])["transfer_reserved_af"] == pytest.approx(20.000, abs=1e-9)

        basin = setup_basin_condition(CRITICAL_DEPTHS)
        published = publish_basin_snapshot(basin["snapshot"]["id"])
        assert published["condition"] == "CRITICAL"

        after = validate_success(api.get_transfer_order(order["id"], water_master_headers))
        assert after["status"] == "EXPIRED", (
            f"publishing CRITICAL must expire every PROPOSED order, got {after['status']}"
        )
        assert get_account(seller["id"])["transfer_reserved_af"] == pytest.approx(0.0, abs=1e-9), (
            "each expiry releases its seller's reservation"
        )

    def test_watch_publish_leaves_proposals_open(self, api, water_master_headers):
        """PRD §3.5: "Critically, when a published snapshot's `condition` is `CRITICAL`, every transfer order still in `PROPOSED` immediately transitions to `EXPIRED` — a market-wide suspension — and each such expiry releases its seller's reservation by decreasing `transfer_reserved_af` by the order's `quantity_af`."
        PRD §2.7: "A derived snapshot condition of `CRITICAL` suspends all settlement activity and retroactively expires every still-open proposal."

        Design: Difficulty/transitive_cascade/critical_publish_expires_proposals_releases_reserves
        """
        seller = create_account(holder_name="Seller GW", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer GW", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 20.000)

        basin = setup_basin_condition(WATCH_DEPTHS)
        published = publish_basin_snapshot(basin["snapshot"]["id"])
        assert published["condition"] == "WATCH"

        after = validate_success(api.get_transfer_order(order["id"], water_master_headers))
        assert after["status"] == "PROPOSED", (
            "the expiry cascade is conditional on CRITICAL; WATCH leaves proposals open"
        )
        assert get_account(seller["id"])["transfer_reserved_af"] == pytest.approx(20.000, abs=1e-9)


class TestSettlementGate:
    def test_settle_requires_basin_not_critical(self, api, water_master_headers):
        """PRD §3.4: "Settlement performs two preconditions before committing: the official basin condition must not be `CRITICAL` (settlement during `CRITICAL` is rejected with `ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED`), and the seller's settled-variant available water — computed with the order being settled first removed from `transfer_reserved_af`, so its own reservation does not count against it — must be at least `quantity_af`, failing which the settle is rejected with `ERR_SETTLE_INSUFFICIENT_WATER`."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_basin_not_critical
        """
        seller = create_account(holder_name="Seller LS", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer LB", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 10.000)
        accept_transfer(order["id"], buyer["id"])

        basin = setup_basin_condition(CRITICAL_DEPTHS)
        publish_basin_snapshot(basin["snapshot"]["id"])

        resp = api.settle_transfer(order["id"], water_master_headers)
        validate_error(resp, ApiErrorId.ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED)

        after = validate_success(api.get_transfer_order(order["id"], water_master_headers))
        assert after["status"] == "ACCEPTED", (
            "the CRITICAL publish expires only PROPOSED orders; the failed settlement "
            "leaves this ACCEPTED order in place"
        )

    def test_settle_recovers_after_later_normal_publish(self, api, water_master_headers):
        """PRD §2.7: "Among snapshots whose `status` is `PUBLISHED`, the selector takes the one with the greatest `computed_at`; ties break by `created_at` descending. If no snapshot has ever been published, the official condition defaults to `NORMAL`."
        PRD §3.4: "Settlement performs two preconditions before committing: the official basin condition must not be `CRITICAL` (settlement during `CRITICAL` is rejected with `ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED`), and the seller's settled-variant available water — computed with the order being settled first removed from `transfer_reserved_af`, so its own reservation does not count against it — must be at least `quantity_af`, failing which the settle is rejected with `ERR_SETTLE_INSUFFICIENT_WATER`."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_basin_not_critical
        """
        seller = create_account(holder_name="Seller LR", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer LR", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 10.000)
        accept_transfer(order["id"], buyer["id"])

        basin = setup_basin_condition(CRITICAL_DEPTHS)
        publish_basin_snapshot(basin["snapshot"]["id"])
        blocked = api.settle_transfer(order["id"], water_master_headers)
        validate_error(blocked, ApiErrorId.ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED)

        # Later readings (all below threshold) become each well's latest reading, so
        # the next snapshot computes NORMAL and its publish re-points the selector.
        for well in basin["wells"]:
            record_monitoring_reading(well["id"], 50.0, measured_at="2026-07-20T08:00:00Z")
        second = create_basin_snapshot()
        published_second = publish_basin_snapshot(second["id"])
        assert published_second["condition"] == "NORMAL"

        settled = validate_success(api.settle_transfer(order["id"], water_master_headers))
        assert settled["status"] == "SETTLED", (
            "with the latest PUBLISHED snapshot back at NORMAL, settlement resumes"
        )
        assert get_account(buyer["id"])["credit_balance_af"] == pytest.approx(10.000, abs=1e-9)


class TestStateBeatsBasinSafety:
    def test_settle_proposed_under_critical_state_beats_safety(self, api, water_master_headers):
        """PRD §2.8: "All requests pass through a consistent validation pipeline, and the order matters because earlier failures mask later ones."
        PRD §2.8: "then the target resource's from-state preconditions (the various `ERR_INVALID_*_STATE` and `ERR_*_NOT_ACTIVE` codes), and only then the business-constraint, business-safety, and business-fiscal rules described in §3."
        PRD §3.4: "Settlement and rejection are `WaterMaster` actions against `ACCEPTED` orders (any other from-state yields `ERR_INVALID_TRANSFER_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/settle_proposed_under_critical_state_beats_safety
        """
        # Publish CRITICAL first; proposals created afterwards remain PROPOSED.
        basin = setup_basin_condition(CRITICAL_DEPTHS, publish=True)
        assert basin["snapshot"]["condition"] == "CRITICAL"

        seller = create_account(holder_name="Seller HS", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer HB", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 10.000)
        assert order["status"] == "PROPOSED"

        # Settling a PROPOSED order violates both the from-state rule and the basin
        # suspension; the from-state precondition is checked earlier.
        resp = api.settle_transfer(order["id"], water_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSFER_STATE)

    def test_settle_cancelled_under_critical_state_beats_safety(self, api, water_master_headers):
        """PRD §2.8: "All requests pass through a consistent validation pipeline, and the order matters because earlier failures mask later ones."
        PRD §2.8: "then the target resource's from-state preconditions (the various `ERR_INVALID_*_STATE` and `ERR_*_NOT_ACTIVE` codes), and only then the business-constraint, business-safety, and business-fiscal rules described in §3."
        PRD §3.4: "Settlement and rejection are `WaterMaster` actions against `ACCEPTED` orders (any other from-state yields `ERR_INVALID_TRANSFER_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/settle_proposed_under_critical_state_beats_safety
        """
        seller = create_account(holder_name="Seller HS-2", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer HB-2", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 10.000)
        cancel_transfer(order["id"], seller["id"])

        basin = setup_basin_condition(CRITICAL_DEPTHS, publish=True)
        assert basin["snapshot"]["condition"] == "CRITICAL"

        # CANCELLED violates the settle from-state while the basin is CRITICAL:
        # the state error must surface, not the suspension.
        resp = api.settle_transfer(order["id"], water_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSFER_STATE)


class TestCurtailment:
    def test_critical_curtailment_reduces_effective_allocation(self, api):
        """PRD §3.8: "The effective allocation referenced throughout this document is itself a derived figure, never stored: it equals `base_allocation_af` multiplied by a curtailment factor, rounded half-up to 3 decimals. The curtailment factor is 0.80 while the official basin condition is `CRITICAL` and 1.00 otherwise, with the official condition taken from the selector of §2.7 at each point of use."
        PRD §3.4: "Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`."

        Design: Corner/calculations/critical_curtailment_reduces_effective_allocation
        """
        basin = setup_basin_condition(CRITICAL_DEPTHS, publish=True)
        assert basin["snapshot"]["condition"] == "CRITICAL"

        seller = create_account(holder_name="Seller CS", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer CB-1", base_allocation_af=50.000)

        over = api.create_transfer_order(
            create_transfer_order_payload(seller["id"], buyer["id"], quantity_af=85.000),
            make_well_owner_headers(seller["id"]),
        )
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_WATER)

        exact = propose_transfer(seller["id"], buyer["id"], 80.000)
        assert exact["status"] == "PROPOSED", (
            "effective allocation is 100.000 * 0.80 = 80.000; equality passes"
        )

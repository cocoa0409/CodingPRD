"""Corner queue — cross_cutting_layers + consistency_model sections:
optimistic concurrency on the two OCC-guarded writes, and the immediate
consistency of an apply across the write response and the next read
(PRD §2.8 and §2.10).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_cash_contract,
    create_crush_plant,
    create_crush_run,
    create_deferred_contract,
    create_pricing_election_payload,
    create_ticket,
    post_bean_quote,
    post_crush_quote_set,
    read_contract,
    read_crush_run,
    schedule_crush_run_payload,
    schedule_run,
    setup_origination_site,
    transition_run,
    validate_error,
    validate_success,
)
from conftest import parse_iso

MERCH = TEST_USERS["origination_merchandiser_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]


class TestOptimisticConcurrency:
    def test_occ_stale_contract_version_rejected(self, api):
        """PRD §2.8: "A pricing election must carry `expected_contract_version`, the `version` of the origination contract as the client last observed it. If the contract's current `version` no longer matches — because another election, or the forced-pricing sweep, has advanced the contract since that read — the election is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)". A replayed token is refused
        even though every other rule would pass.

        Design: Corner/cross_cutting_layers/occ_stale_contract_version_rejected
        """
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=1000, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        stale_version = contract["version"]
        first = api_client.create_pricing_election(
            contract["id"],
            create_pricing_election_payload(100, stale_version),
            MERCH,
        )
        updated = validate_success(first, 200)
        assert updated["version"] == stale_version + 1
        replay = api_client.create_pricing_election(
            contract["id"],
            create_pricing_election_payload(100, stale_version),
            MERCH,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_CONTRACT_VERSION)
        after = read_contract(contract["id"])
        assert float(after["priced_bushels"]) == pytest.approx(100), (
            "only the first election landed"
        )

    def test_occ_stale_run_version_rejected(self, api):
        """PRD §2.8: "Scheduling a crush run must carry `expected_run_version`, the `version` of the run as the client last observed it. A mismatch with the run's current `version` is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412)". After a schedule and a revert bump the version twice,
        replaying the creation-time token fails 412 and the run stays PLANNED.

        Design: Corner/cross_cutting_layers/occ_stale_run_version_rejected
        """
        plant = create_crush_plant()
        post_crush_quote_set("2026-11")
        run = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                               planned_bushels=1000, futures_month="2026-11")
        stale_version = run["version"]
        schedule_run(run["id"], expected_run_version=stale_version)
        transition_run(run["id"], "PLANNED")
        replay = api_client.schedule_crush_run(
            run["id"], schedule_crush_run_payload(stale_version), SCHEDULER
        )
        validate_error(replay, ApiErrorId.ERR_STALE_RUN_VERSION)
        assert read_crush_run(run["id"])["status"] == "PLANNED"


class TestImmediateConsistency:
    def test_immediate_consistency_apply_visible_on_next_read(self, api):
        """PRD §2.10: "Every such recomputation is a mutation of the owning entity: `updated_at` refreshes and `version` increments with it, and the new values are visible in the triggering request's response and in every subsequent read. Consistency is immediate — there is no caching tier and no delayed projection anywhere between a write and a read."

        Design: Corner/consistency_model/immediate_consistency_apply_visible_on_next_read
        """
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=100
        )
        ticket = create_ticket(contract["id"], gross_bushels=50)
        resp = api_client.apply_delivery_ticket(ticket["id"], MERCH)
        applied = validate_success(resp, 200)
        assert applied["status"] == "APPLIED"
        assert float(applied["net_bushels"]) == pytest.approx(50), (
            "the apply response itself carries the graded ticket"
        )
        refreshed = read_contract(contract["id"])
        assert float(refreshed["delivered_bushels"]) == pytest.approx(50)
        assert refreshed["fulfillment_status"] == "DELIVERING"
        assert refreshed["version"] == contract["version"] + 1
        assert parse_iso(refreshed["updated_at"]) >= parse_iso(
            refreshed["created_at"]
        )

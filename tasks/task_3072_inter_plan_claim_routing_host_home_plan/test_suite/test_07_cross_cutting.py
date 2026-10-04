"""Cross-cutting behaviors: adjustment supersede, derived balances, optimistic concurrency, version increments."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    ApiClient,
    create_applied_adjustment,
    create_paid_claim,
    create_propagated_adjustment,
    get_success_data,
    setup_disputed_batch_world,
    setup_paid_claim_world,
    setup_two_plan_world,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


class TestSupersede:
    def test_superseding_adjustment_rejects_prior_initiated(self, api: ApiClient):
        """PRD §3.7: "If any earlier adjustment on the same claim is still sitting in `INITIATED` status, that prior adjustment is superseded: it transitions from `INITIATED` to `REJECTED`, and the new adjustment's `supersedes_adjustment_id` records which adjustment it replaced (`null` when there was none)."

        Design: Corner/cross_cutting_complexity_layers/superseding_adjustment_rejects_prior_initiated_adjustment
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        a1 = get_success_data(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim["version"], reason="first", delta_allowed_cents=-1000),
                world["host_headers"],
            )
        )
        claim_pending = get_success_data(api.get_claim(claim["id"], world["host_headers"]))

        a2 = validate_success(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim_pending["version"], reason="second supersedes first", delta_allowed_cents=-2000),
                world["host_headers"],
            ),
            201,
        )
        assert a2["status"] == "INITIATED"
        assert a2["supersedes_adjustment_id"] == a1["id"]

        a1_after = get_success_data(api.get_adjustment(a1["id"], world["host_headers"]))
        assert a1_after["status"] == "REJECTED"

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "ADJUSTMENT_PENDING"

    def test_first_adjustment_has_null_supersedes(self, api: ApiClient):
        """PRD §3.7: "the new adjustment's `supersedes_adjustment_id` records which adjustment it replaced (`null` when there was none)"

        Design: Corner/cross_cutting_complexity_layers/superseding_adjustment_rejects_prior_initiated_adjustment
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        a1 = validate_success(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim["version"], reason="first", delta_allowed_cents=-1000),
                world["host_headers"],
            ),
            201,
        )
        assert a1["supersedes_adjustment_id"] is None
        assert a1["status"] == "INITIATED"


class TestDerivedBalances:
    def test_plan_derived_balances_track_pay_and_recovery(self, api: ApiClient):
        """PRD §2.10: "`claims_paid_balance_cents` accumulates the provider payments the plan has made in its capacity as host, and decreases only when an applied downward adjustment recovers funds on a claim the plan hosted."
        PRD §3.7: "The host plan's `claims_paid_balance_cents` is then reduced by the recovery amount; the receivables ledger is untouched by recoveries."

        Design: Corner/cross_cutting_complexity_layers/plan_derived_balances_track_pay_and_recovery
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        host_after_pay = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after_pay["claims_paid_balance_cents"] == 20000
        assert host_after_pay["fees_receivable_balance_cents"] == 1200

        create_applied_adjustment(api, world, claim, delta=-5000, reason="partial recovery")

        host_after_apply = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after_apply["claims_paid_balance_cents"] == 15000
        assert host_after_apply["fees_receivable_balance_cents"] == 1200

    def test_balances_accumulate_across_multiple_paid_claims(self, api: ApiClient):
        """PRD §2.10: "`claims_paid_balance_cents` accumulates the provider payments the plan has made in its capacity as host"
        PRD §2.10: "`fees_receivable_balance_cents` accumulates the access fees and administrative charges the plan has earned as host on routed claims"

        Design: Corner/cross_cutting_complexity_layers/plan_derived_balances_track_pay_and_recovery
        """
        world = setup_two_plan_world(api)
        create_paid_claim(api, world)
        create_paid_claim(api, world, service_date="2026-08-11")

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 40000
        assert host_after["fees_receivable_balance_cents"] == 2400


class TestVersionIncrements:
    def test_version_increments_on_every_mutation(self, api: ApiClient):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments with every modification to the resource, including mutations driven by cross-entity side effects such as a payment crediting a plan's balances."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        assert claim["version"] == 1

        priced = validate_success(api.price_claim(claim["id"], world["host_headers"]), 200)
        assert priced["version"] == 2

    def test_version_advances_through_routing(self, api: ApiClient):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments with every modification to the resource"

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
        """
        world = setup_two_plan_world(api)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        priced = get_success_data(api.price_claim(claim["id"], world["host_headers"]))
        routed = validate_success(api.route_claim(claim["id"], world["host_headers"]), 200)
        assert routed["version"] == priced["version"] + 1


class TestOptimisticConcurrency:
    def test_stale_claim_version_on_adjustment_create_returns_412(self, api: ApiClient):
        """PRD §2.7: "Creating an adjustment against a claim requires the request to carry `expected_claim_version`, a non-optional input field holding the claim `version` the client last observed. If the claim's current `version` does not match — because another writer has since created an adjustment (which legitimately supersedes the prior initiated one) or applied one (returning the claim to paid and advancing its version) — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/optimistic_concurrency_occ/stale_claim_version_on_adjustment_create_returns_412
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        stale_version = claim["version"]

        get_success_data(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(stale_version, reason="first", delta_allowed_cents=-1000),
                world["host_headers"],
            )
        )

        res = api.create_adjustment(
            claim["id"],
            f.adjustment_payload(stale_version, reason="second with stale version", delta_allowed_cents=-2000),
            world["host_headers"],
        )
        validate_error(res, "ERR_STALE_VERSION", 412)

    def test_current_claim_version_on_adjustment_create_succeeds(self, api: ApiClient):
        """PRD §2.7: "Creating an adjustment against a claim requires the request to carry `expected_claim_version`, a non-optional input field holding the claim `version` the client last observed. If the claim's current `version` does not match — because another writer has since created an adjustment (which legitimately supersedes the prior initiated one) or applied one (returning the claim to paid and advancing its version) — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        The fresh, current version is accepted.

        Design: Difficulty/optimistic_concurrency_occ/stale_claim_version_on_adjustment_create_returns_412
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        a1 = get_success_data(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim["version"], reason="first", delta_allowed_cents=-1000),
                world["host_headers"],
            )
        )
        current = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        a2 = validate_success(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(current["version"], reason="second with fresh version", delta_allowed_cents=-2000),
                world["host_headers"],
            ),
            201,
        )
        assert a2["supersedes_adjustment_id"] == a1["id"]

    def test_stale_batch_version_on_refinalize_returns_412(self, api: ApiClient):
        """PRD §2.7: "Re-finalizing a disputed settlement batch requires the request to carry `expected_settlement_batch_version`, a non-optional input field holding the batch `version` the client last observed. If the batch's current `version` does not match — because another writer has already re-finalized it or otherwise moved it out of the disputed state — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_batch_version_on_refinalize_returns_412
        """
        world = setup_disputed_batch_world(api)
        batch = world["batch"]
        stale_version = batch["version"]

        # First refinalize with the fresh version succeeds and advances the batch version.
        refinalized = validate_success(
            api.refinalize_batch(batch["id"], f.refinalize_payload(stale_version), world["host_headers"]),
            200,
        )
        get_success_data(api.dispute_batch(batch["id"], world["home_headers"]))

        res = api.refinalize_batch(batch["id"], f.refinalize_payload(stale_version), world["host_headers"])
        validate_error(res, "ERR_STALE_VERSION", 412)

    def test_fresh_batch_version_on_refinalize_succeeds(self, api: ApiClient):
        """PRD §2.7: "Re-finalizing a disputed settlement batch requires the request to carry `expected_settlement_batch_version`, a non-optional input field holding the batch `version` the client last observed."

        The version observed at the most recent dispute is accepted.

        Design: Corner/errors/stale_batch_version_on_refinalize_returns_412
        """
        world = setup_disputed_batch_world(api)
        batch = world["batch"]
        refinalized = validate_success(
            api.refinalize_batch(batch["id"], f.refinalize_payload(batch["version"]), world["host_headers"]),
            200,
        )
        assert refinalized["status"] == "FINALIZED"

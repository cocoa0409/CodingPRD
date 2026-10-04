"""Deliveries: per-cell-first fee rounding, the release/recall/reissue cycle,
the compile/reissue guard sequence, delivery-window boundary, entitlement
invariant, immediate consistency, and methodology re-pinning."""
from test_helpers import (
    ApiErrorId,
    create_active_opt_out,
    create_prescriber,
    get_success_data,
    setup_compiled_delivery,
    setup_recalled_delivery,
    setup_released_delivery,
    setup_scheduled_delivery,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PA


class TestDeliveryFeeRoundingOrder:
    def test_per_cell_rounding_before_sum_and_discount(self, api):
        """PRD §3.6: "The delivery fee obeys a pinned rounding order. The per-cell fee is
        `cell_fee_base_cents` multiplied by `cell_fee_multiplier`, rounded half-up per individual
        cell first; those per-cell amounts are then summed across the compiled cells; the
        `base_fee_cents` is added to form a subtotal; and the final fee is the subtotal multiplied
        by one minus `volume_discount_pct`, rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/delivery_fee_per_cell_rounding_order
        """
        ctx = setup_compiled_delivery(
            cells=(
                {"period_code": "2026-08", "geography_code": "G1"},
                {"period_code": "2026-08", "geography_code": "G2"},
                {"period_code": "2026-08", "geography_code": "G3"},
            ),
            product_overrides={
                "base_fee_cents": 50000,
                "cell_fee_base_cents": 1235,
                "cell_fee_multiplier": 1.5,
                "volume_discount_pct": 0.10,
            },
        )
        delivery = ctx["delivery"]
        assert len(delivery["compiled_cell_ids"]) == 3
        # per-cell-first: 1853 * 3 = 5559; + 50000 = 55559; * 0.9 = 50003.1 -> 50003.
        assert delivery["fee_cents"] == 50003, (
            f"per-cell-first rounding pins 50003 (sum-then-round would give 50002), "
            f"got {delivery['fee_cents']}"
        )
        assert delivery["status"] == "COMPILED"

    def test_compiled_delivery_carries_fee_immediately(self, api):
        """PRD §3.6: "The delivery fee obeys a pinned rounding order. The per-cell fee is
        `cell_fee_base_cents` multiplied by `cell_fee_multiplier`, rounded half-up per individual
        cell first; those per-cell amounts are then summed across the compiled cells; the
        `base_fee_cents` is added to form a subtotal; and the final fee is the subtotal multiplied
        by one minus `volume_discount_pct`, rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/delivery_fee_per_cell_rounding_order
        """
        ctx = setup_compiled_delivery()
        delivery = ctx["delivery"]
        assert delivery["fee_cents"] == 11000, (
            f"base 10000 + round(1000 * 1.0) over 1 cell must be 11000, got {delivery['fee_cents']}"
        )


class TestDeliveryCycle:
    def test_compile_release_recall_reissue_release_cycle(self, api):
        """PRD §3.6: "A `COMPILED` delivery may be released to the client, moving to `RELEASED`;
        release is also permitted from `REISSUED`, but never while `must_recompile` is true — both
        violations surface `ERR_DELIVERY_INVALID_STATE`."
        PRD §3.6: "Reissue is the recovery path: a `RECALLED` delivery may be reissued by a
        `PlatformAdmin`, and reissue re-runs the full compile gauntlet — opt-out, jurisdiction,
        window, version currency, non-empty cell set, and entitlement checks all apply with the
        same error codes, and an optional `include_prescriber_ids` may again steer the prescriber
        panel. On success `compiled_cell_ids` and `included_prescriber_ids` are recomputed exactly
        as at compile, `fee_cents` is recomputed, `must_recompile` flips back to false, and the
        client's `entitlement_cells_balance` is debited by the number of newly compiled cells."

        Design: Difficulty/non_linear_state_machine/delivery_release_recall_reissue_cycle
        """
        ctx = setup_scheduled_delivery()
        delivery_id = ctx["delivery"]["id"]
        compiled = validate_success(api.compile_delivery(delivery_id, PA))
        assert compiled["fee_cents"] == 11000
        validate_success(api.release_delivery(delivery_id, PA))
        recalled = validate_success(
            api.recall_delivery(delivery_id, PA, payload={"reason": "client request"})
        )
        assert recalled["recall_count"] == 1
        assert recalled["must_recompile"] is True
        reissued = validate_success(api.reissue_delivery(delivery_id, PA))
        assert reissued["status"] == "REISSUED"
        assert reissued["must_recompile"] is False
        released_again = validate_success(api.release_delivery(delivery_id, PA))
        assert released_again["status"] == "RELEASED"
        assert released_again["version"] == 6, (
            "create (1) + compile (2) + release (3) + recall (4) + reissue (5) + release (6)"
        )

    def test_release_blocked_while_must_recompile(self, api):
        """PRD §3.6: "A `COMPILED` delivery may be released to the client, moving to `RELEASED`;
        release is also permitted from `REISSUED`, but never while `must_recompile` is true — both
        violations surface `ERR_DELIVERY_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/delivery_release_recall_reissue_cycle
        """
        ctx = setup_recalled_delivery()
        resp = api.release_delivery(ctx["delivery"]["id"], PA)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_INVALID_STATE)


class TestCompilePriority:
    def test_safety_check_reported_before_stale_pin(self, api):
        """PRD §2.8: "Every request passes through a fixed priority cascade. Authentication and role
        checks come first, then ownership checks, then existence checks on path identifiers and
        body foreign keys (validated left to right, so the first unresolvable identifier is the
        one reported with `ERR_NOT_FOUND`), then request-body schema checks
        (`ERR_INVALID_REQUEST`), then optimistic-concurrency checks, then generic and
        domain-specific state checks, then business safety rules (re-identification prohibition,
        opt-out violation, jurisdiction restriction, QA floor), then business temporal rules
        (window overlap, delivery window, audit cooldown), then business referential rules
        (version currency, deliverable cells, duplicate opt-out), and finally fiscal rules
        (royalty budget, entitlement balance). When several rules could reject the same request,
        the earliest rule in this ordering wins."
        PRD §3.6: "the safety checks on any `include_prescriber_ids` supplied in the payload — an
        entry holding an `ACTIVE` opt-out is rejected with `ERR_PRESCRIBER_OPT_OUT_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/compile_safety_beats_referential
        """
        p1 = create_prescriber(full_name="Dr X", npi="NPI-101", state_code="TX")
        ctx = setup_scheduled_delivery(prescriber_ids=[p1["id"]])
        create_active_opt_out(p1["id"])
        validate_success(
            api.restate_methodology(
                ctx["methodology"]["id"],
                {"expected_methodology_version": ctx["methodology"]["version"]},
                PA,
            )
        )
        resp = api.compile_delivery(
            ctx["delivery"]["id"], PA, payload={"include_prescriber_ids": [p1["id"]]}
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIBER_OPT_OUT_VIOLATION)
        fetched = validate_success(api.get_delivery(ctx["delivery"]["id"], PA))
        assert fetched["status"] == "SCHEDULED"
        assert fetched["fee_cents"] is None

    def test_stale_pin_reported_when_no_safety_violation(self, api):
        """PRD §3.6: "version currency — the product's `pinned_methodology_version` must equal the
        methodology's current `version`, else `ERR_PRODUCT_VERSION_STALE`"

        Design: Difficulty/priority_pair_validation_conflict/compile_safety_beats_referential
        """
        ctx = setup_scheduled_delivery()
        validate_success(
            api.restate_methodology(
                ctx["methodology"]["id"],
                {"expected_methodology_version": ctx["methodology"]["version"]},
                PA,
            )
        )
        resp = api.compile_delivery(ctx["delivery"]["id"], PA)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_VERSION_STALE)


class TestSafetyBeatsTemporal:
    def test_opt_out_violation_reported_before_window_missed(self, api):
        """PRD §2.8: "Every request passes through a fixed priority cascade. Authentication and role
        checks come first, then ownership checks, then existence checks on path identifiers and
        body foreign keys (validated left to right, so the first unresolvable identifier is the
        one reported with `ERR_NOT_FOUND`), then request-body schema checks
        (`ERR_INVALID_REQUEST`), then optimistic-concurrency checks, then generic and
        domain-specific state checks, then business safety rules (re-identification prohibition,
        opt-out violation, jurisdiction restriction, QA floor), then business temporal rules
        (window overlap, delivery window, audit cooldown), then business referential rules
        (version currency, deliverable cells, duplicate opt-out), and finally fiscal rules
        (royalty budget, entitlement balance). When several rules could reject the same request,
        the earliest rule in this ordering wins."

        Design: Corner/validations/compile_safety_beats_temporal_priority
        """
        p1 = create_prescriber(full_name="Dr P", npi="NPI-401", state_code="TX")
        ctx = setup_scheduled_delivery(prescriber_ids=[p1["id"]])
        create_active_opt_out(p1["id"])
        get_success_data(api.set_clock("2026-08-15T00:00:00Z", PA))
        resp = api.compile_delivery(
            ctx["delivery"]["id"], PA, payload={"include_prescriber_ids": [p1["id"]]}
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIBER_OPT_OUT_VIOLATION)
        fetched = validate_success(api.get_delivery(ctx["delivery"]["id"], PA))
        assert fetched["status"] == "SCHEDULED"


class TestDeliveryWindowBoundary:
    def test_compile_before_period_end_rejected(self, api):
        """PRD §3.6: "the temporal window — the current logical date must be on or after the parent
        period's `period_end_date`, else `ERR_DELIVERY_WINDOW_MISSED`"

        Design: Difficulty/boundary_precision_check/compile_at_exact_period_end_date
        """
        ctx = setup_scheduled_delivery()
        get_success_data(api.set_clock("2026-08-30T00:00:00Z", PA))
        resp = api.compile_delivery(ctx["delivery"]["id"], PA)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_MISSED)
        fetched = validate_success(api.get_delivery(ctx["delivery"]["id"], PA))
        assert fetched["status"] == "SCHEDULED"

    def test_compile_exactly_on_period_end_succeeds(self, api):
        """PRD §3.6: "the temporal window — the current logical date must be on or after the parent
        period's `period_end_date`, else `ERR_DELIVERY_WINDOW_MISSED`"

        Design: Difficulty/boundary_precision_check/compile_at_exact_period_end_date
        """
        ctx = setup_scheduled_delivery()
        get_success_data(api.set_clock("2026-08-31T00:00:00Z", PA))
        compiled = validate_success(api.compile_delivery(ctx["delivery"]["id"], PA))
        assert compiled["status"] == "COMPILED", (
            "exactly on period_end_date meets the on-or-after window"
        )


class TestEntitlementInvariant:
    def test_recall_reissue_conserve_entitlement_balance(self, api):
        """PRD §3.6: "The entitlement ledger is thereby self-consistent: a compile followed by a
        recall of the same delivery leaves the balance unchanged, because the recall credit
        exactly reverses the compile debit."

        Design: Difficulty/compensating_invariant/recall_reissue_conserves_entitlement_balance
        """
        ctx = setup_scheduled_delivery(
            cells=(
                {"period_code": "2026-08", "geography_code": "G1"},
                {"period_code": "2026-08", "geography_code": "G2"},
                {"period_code": "2026-08", "geography_code": "G3"},
            ),
        )
        client_id = ctx["client"]["id"]
        assert ctx["client"]["entitlement_cells_balance"] == 100
        validate_success(api.compile_delivery(ctx["delivery"]["id"], PA))
        after_compile = validate_success(api.get_client(client_id, PA))
        assert after_compile["entitlement_cells_balance"] == 97, (
            f"3 cells debited: expected 97, got {after_compile['entitlement_cells_balance']}"
        )
        validate_success(api.recall_delivery(ctx["delivery"]["id"], PA))
        after_recall = validate_success(api.get_client(client_id, PA))
        assert after_recall["entitlement_cells_balance"] == 100, (
            "compile + recall of the same delivery leaves the balance unchanged"
        )
        validate_success(api.reissue_delivery(ctx["delivery"]["id"], PA))
        after_reissue = validate_success(api.get_client(client_id, PA))
        assert after_reissue["entitlement_cells_balance"] == 97, (
            f"reissue debits the recomputed 3 cells again: expected 97, "
            f"got {after_reissue['entitlement_cells_balance']}"
        )

    def test_recall_clears_compiled_cells_and_sets_flags(self, api):
        """PRD §3.6: "Every recall increments `recall_count` by 1, sets `must_recompile` true,
        credits the client's `entitlement_cells_balance` by the number of ids in
        `compiled_cell_ids`, and then clears `compiled_cell_ids` to the empty list (the ids are
        retained just long enough to compute the credit)."

        Design: Difficulty/compensating_invariant/recall_reissue_conserves_entitlement_balance
        """
        ctx = setup_scheduled_delivery(
            cells=(
                {"period_code": "2026-08", "geography_code": "G1"},
                {"period_code": "2026-08", "geography_code": "G2"},
                {"period_code": "2026-08", "geography_code": "G3"},
            ),
        )
        validate_success(api.compile_delivery(ctx["delivery"]["id"], PA))
        recalled = validate_success(api.recall_delivery(ctx["delivery"]["id"], PA))
        assert recalled["status"] == "RECALLED"
        assert recalled["recall_count"] == 1
        assert recalled["must_recompile"] is True
        assert recalled["compiled_cell_ids"] == []


class TestImmediateConsistency:
    def test_compile_response_reflects_mutation(self, api):
        """PRD §3.6: "On success, compilation selects exactly those matching `CURRENT` cells —
        sorted by `geography_code` ascending, then `specialty` ascending, then `created_at`
        ascending — into `compiled_cell_ids`; sets `included_prescriber_ids` to the product's
        `prescriber_ids` minus prescriber panel members with `ACTIVE` opt-outs minus those
        restricted by effective jurisdiction rules, or, when a valid `include_prescriber_ids` was
        supplied, exactly that supplied list; computes `fee_cents`; and debits the client's
        `entitlement_cells_balance` by the number of compiled cells."

        Design: Corner/consistency_model/compile_response_immediately_reflects_mutation
        """
        ctx = setup_scheduled_delivery()
        compiled = validate_success(api.compile_delivery(ctx["delivery"]["id"], PA))
        assert compiled["status"] == "COMPILED"
        assert compiled["fee_cents"] == 11000
        assert len(compiled["compiled_cell_ids"]) == 1
        assert compiled["version"] == 2


class TestInsufficientEntitlement:
    def test_compile_beyond_entitlement_rejected_402(self, api):
        """PRD §3.6: "and finally entitlement — the client's `entitlement_cells_balance` must be at
        least the number of cells about to be compiled, else `ERR_INSUFFICIENT_ENTITLEMENT`
        (HTTP 402)."

        Design: Corner/errors/insufficient_entitlement_on_compile_returns_402
        """
        ctx = setup_scheduled_delivery(
            cells=(
                {"period_code": "2026-08", "geography_code": "G1"},
                {"period_code": "2026-08", "geography_code": "G2"},
                {"period_code": "2026-08", "geography_code": "G3"},
            ),
            client_overrides={"entitlement_cells_total": 2},
        )
        resp = api.compile_delivery(ctx["delivery"]["id"], PA)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ENTITLEMENT)
        fetched = validate_success(api.get_delivery(ctx["delivery"]["id"], PA))
        assert fetched["status"] == "SCHEDULED"
        client = validate_success(api.get_client(ctx["client"]["id"], PA))
        assert client["entitlement_cells_balance"] == 2


class TestSyncMethodology:
    def test_sync_repins_and_compile_succeeds(self, api):
        """PRD §3.6: "When a methodology is later restated, the product's pin goes stale; a
        `PlatformAdmin` re-pins it with the sync-methodology operation, which sets
        `pinned_methodology_version` to the methodology's current `version`."

        Design: Corner/endpoints/sync_methodology_clears_stale_pin
        """
        ctx = setup_scheduled_delivery()
        validate_success(
            api.restate_methodology(
                ctx["methodology"]["id"],
                {"expected_methodology_version": ctx["methodology"]["version"]},
                PA,
            )
        )
        cell = ctx["cells"][0]
        recomputed = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_WEIGHTED"}, PA)
        )
        assert recomputed["status"] == "CURRENT"
        resp = api.compile_delivery(ctx["delivery"]["id"], PA)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_VERSION_STALE)
        synced = validate_success(api.sync_product_methodology(ctx["product"]["id"], PA))
        assert synced["pinned_methodology_version"] == ctx["methodology"]["version"] + 1
        compiled = validate_success(api.compile_delivery(ctx["delivery"]["id"], PA))
        assert compiled["status"] == "COMPILED"

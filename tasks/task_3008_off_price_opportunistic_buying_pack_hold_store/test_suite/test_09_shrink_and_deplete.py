"""Shrink valuation (traceable + high-value-sort merge), the receipt-cascade to
SOLD_OUT chain, on-hand guards, and sell-through depletion."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_lot,
    create_shrink_case_payload,
    evaluate_lot,
    make_accepted_lot,
    make_lot,
    make_lot_line,
    make_store,
    make_store_sku,
    make_ticket,
    open_season,
    setup_base,
    setup_floor_sku,
    setup_receipt_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    get_season,
)

AUDITOR = TEST_USERS["shrink_auditor_headers"]
STORE_OPS = TEST_USERS["store_ops_lead_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]


class TestReceiptShrinkCascadeToSoldOut:
    def test_shrink_confirm_drives_sku_to_sold_out(self, api):
        """PRD §3.7: "the SKU's `units_on_hand` drops by `units_lost`, and if it
        reaches zero the SKU transitions to `SOLD_OUT`."

        Design: Difficulty/transitive_cascade/receipt_complete_shrinkcase_storesku_soldout_chain
        """
        env = setup_floor_sku(
            units_on_hand=10,
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_overrides={"quantity": 40, "unit_cost_cents": 150_000,
                            "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000},
        )
        case = validate_success(
            api.create_shrink_case(
                {"store_id": env["store"]["id"], "store_sku_id": env["sku"]["id"],
                 "lot_id": env["lot"]["id"], "shrink_type": "UNSCANNED_UNIT",
                 "units_lost": 10, "units_untraceable": 0},
                AUDITOR), 201)
        confirmed = validate_success(api.confirm_shrink_case(case["id"], AUDITOR))
        sku = validate_success(api.get_store_sku(env["sku"]["id"], STORE_OPS))
        assert sku["units_on_hand"] == 0
        assert sku["status"] == "SOLD_OUT"
        assert confirmed["status"] == "CONFIRMED"

    def test_shrink_value_uses_rounded_per_unit_basis(self, api):
        """PRD §3.7: "For traced shrink, the per-unit basis is the lot's
        `landed_cost_cents` divided by its `unit_count`, rounded half-up, and
        `shrink_value_cents` is `units_lost` times that basis".

        Design: Difficulty/transitive_cascade/receipt_complete_shrinkcase_storesku_soldout_chain
        """
        env = setup_floor_sku(
            units_on_hand=10,
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_overrides={"quantity": 40, "unit_cost_cents": 150_000,
                            "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000},
        )
        case = validate_success(
            api.create_shrink_case(
                {"store_id": env["store"]["id"], "store_sku_id": env["sku"]["id"],
                 "lot_id": env["lot"]["id"], "shrink_type": "UNSCANNED_UNIT",
                 "units_lost": 10, "units_untraceable": 0},
                AUDITOR), 201)
        confirmed = validate_success(api.confirm_shrink_case(case["id"], AUDITOR))
        assert confirmed["shrink_value_cents"] == 1_537_500


class TestHighValueSortMerge:
    def test_mixed_lot_high_value_sort_merge(self, api):
        """PRD §3.7: "For untraceable shrink, the lot's lines are ordered by
        merge policy — `FIFO` by `created_at` ascending; `HIGH_VALUE_SORT` by
        `compare_at_claim_cents` descending with `created_at` ascending as the
        tie-break — and `shrink_value_cents` is the sum of each line's
        `unit_cost_cents` over the first `units_untraceable` units drawn in
        that order".

        Design: Corner/calculations/shrink_valuation_high_value_sort_merge_on_mixed_lot
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], mixed_lot=True)
        make_lot_line(lot["id"], style_code="MX-CHEAP", quantity=50,
                      unit_cost_cents=11_500, compare_at_claim_cents=15_000,
                      target_retail_cents=5_000)
        make_lot_line(lot["id"], style_code="MX-DEAR", department="HOME",
                      quantity=50, unit_cost_cents=90_000, compare_at_claim_cents=150_000,
                      target_retail_cents=50_000)
        evaluate_lot(lot["id"])
        accepted_lot = accept_lot(lot["id"], base["season"]["id"])
        store = make_store(store_code="ST-M")
        case = validate_success(
            api.create_shrink_case(
                {"store_id": store["id"], "lot_id": accepted_lot["id"],
                 "shrink_type": "MIXED_LOT_SHORTAGE", "merge_mode": "HIGH_VALUE_SORT",
                 "units_lost": 0, "units_untraceable": 3},
                AUDITOR), 201)
        confirmed = validate_success(api.confirm_shrink_case(case["id"], AUDITOR))
        assert confirmed["shrink_value_cents"] == 270_000
        assert confirmed["status"] == "CONFIRMED"

    def test_mixed_lot_merge_forced_high_value_sort(self, api):
        """PRD §3.7: "The `merge_mode` is `FIFO` by default but is forced to
        `HIGH_VALUE_SORT` whenever the underlying lot is `mixed_lot`."

        Design: Corner/calculations/shrink_valuation_high_value_sort_merge_on_mixed_lot
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], mixed_lot=True)
        make_lot_line(lot["id"], style_code="MX-CHEAP", quantity=50,
                      unit_cost_cents=11_500, compare_at_claim_cents=15_000,
                      target_retail_cents=5_000)
        make_lot_line(lot["id"], style_code="MX-DEAR", department="HOME",
                      quantity=50, unit_cost_cents=90_000, compare_at_claim_cents=150_000,
                      target_retail_cents=50_000)
        evaluate_lot(lot["id"])
        accepted_lot = accept_lot(lot["id"], base["season"]["id"])
        store = make_store(store_code="ST-M2")
        # No merge_mode supplied: the default is FIFO, but a mixed lot forces
        # HIGH_VALUE_SORT — valuation draws from the high-value line first.
        case = validate_success(
            api.create_shrink_case(
                {"store_id": store["id"], "lot_id": accepted_lot["id"],
                 "shrink_type": "MIXED_LOT_SHORTAGE",
                 "units_lost": 0, "units_untraceable": 3},
                AUDITOR), 201)
        confirmed = validate_success(api.confirm_shrink_case(case["id"], AUDITOR))
        assert confirmed["shrink_value_cents"] == 270_000


class TestShrinkExceedsOnHand:
    def test_confirm_over_on_hand_rejected(self, api):
        """PRD §2.10: "a shrink confirmation whose `units_lost` exceeds the
        referenced stock's `units_on_hand` is rejected with
        `ERR_SHRINK_EXCEEDS_ON_HAND`."

        Design: Corner/validations/shrink_confirm_exceeding_on_hand_rejected
        """
        env = setup_floor_sku(units_on_hand=5)
        case = validate_success(
            api.create_shrink_case(
                {"store_id": env["store"]["id"], "store_sku_id": env["sku"]["id"],
                 "lot_id": env["lot"]["id"], "shrink_type": "DAMAGE",
                 "units_lost": 6, "units_untraceable": 0},
                AUDITOR), 201)
        res = api.confirm_shrink_case(case["id"], AUDITOR)
        validate_error(res, ApiErrorId.ERR_SHRINK_EXCEEDS_ON_HAND)
        sku = validate_success(api.get_store_sku(env["sku"]["id"], STORE_OPS))
        assert sku["units_on_hand"] == 5
        assert sku["status"] == "ON_FLOOR"

    def test_case_stays_open_after_rejected_confirm(self, api):
        """PRD §3.7: "Confirmation (`OPEN → CONFIRMED`) by the `ShrinkAuditor`
        is blocked when the traced stock cannot absorb the loss".

        Design: Corner/validations/shrink_confirm_exceeding_on_hand_rejected
        """
        env = setup_floor_sku(units_on_hand=5)
        case = validate_success(
            api.create_shrink_case(
                {"store_id": env["store"]["id"], "store_sku_id": env["sku"]["id"],
                 "lot_id": env["lot"]["id"], "shrink_type": "DAMAGE",
                 "units_lost": 6, "units_untraceable": 0},
                AUDITOR), 201)
        validate_error(api.confirm_shrink_case(case["id"], AUDITOR),
                       ApiErrorId.ERR_SHRINK_EXCEEDS_ON_HAND)
        case_after = validate_success(api.get_shrink_case(case["id"], AUDITOR))
        assert case_after["status"] == "OPEN"


class TestShrinkCaseVoid:
    def test_confirm_after_void_is_invalid_state(self, api):
        """PRD §3.7: "Confirmation bumps the case's `version`; voiding
        (`OPEN → VOIDED`) simply closes the case with a version bump." — a
        VOIDED case is terminal.

        Design: Corner/state_machines/shrink_case_void_then_confirm_is_invalid_state
        """
        set = setup_base()
        store = make_store(store_code="ST-V", cluster_code="VALUE_RURAL")
        case = validate_success(
            api.create_shrink_case(
                {"store_id": store["id"], "shrink_type": "MIXED_LOT_OVERAGE",
                 "units_lost": 0, "units_untraceable": 5},
                AUDITOR), 201)
        validate_success(api.void_shrink_case(case["id"], AUDITOR))
        res = api.confirm_shrink_case(case["id"], AUDITOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_case_remains_voided(self, api):
        """PRD §3.7: "voiding (`OPEN → VOIDED`) simply closes the case with a
        version bump."

        Design: Corner/state_machines/shrink_case_void_then_confirm_is_invalid_state
        """
        set = setup_base()
        store = make_store(store_code="ST-V2", cluster_code="VALUE_RURAL")
        case = validate_success(
            api.create_shrink_case(
                {"store_id": store["id"], "shrink_type": "MIXED_LOT_OVERAGE",
                 "units_lost": 0, "units_untraceable": 5},
                AUDITOR), 201)
        voided = validate_success(api.void_shrink_case(case["id"], AUDITOR))
        assert voided["status"] == "VOIDED"
        validate_error(api.confirm_shrink_case(case["id"], AUDITOR),
                       ApiErrorId.ERR_INVALID_STATE)
        case_after = validate_success(api.get_shrink_case(case["id"], AUDITOR))
        assert case_after["status"] == "VOIDED"


class TestDepletion:
    def test_deplete_exactly_on_hand_reaches_sold_out(self, api):
        """PRD §3.7: "a payload of `units_sold` (positive, and never more than
        `units_on_hand`, else `ERR_NEGATIVE_ON_HAND`) reduces `units_on_hand`,
        bumps the SKU's `version`, and moves the SKU to `SOLD_OUT` exactly when
        on-hand reaches zero."

        Design: Corner/endpoints/store_sku_deplete_to_boundary_and_negative_rejection
        """
        env = setup_floor_sku(units_on_hand=4)
        depleted = validate_success(
            api.deplete_store_sku(env["sku"]["id"], {"units_sold": 4}, STORE_OPS))
        assert depleted["status"] == "SOLD_OUT"
        assert depleted["units_on_hand"] == 0

    def test_deplete_beyond_on_hand_rejected(self, api):
        """PRD §2.10: "depletion beyond on-hand is rejected with
        `ERR_NEGATIVE_ON_HAND`."

        Design: Corner/endpoints/store_sku_deplete_to_boundary_and_negative_rejection
        """
        env = setup_floor_sku(units_on_hand=4)
        res = api.deplete_store_sku(env["sku"]["id"], {"units_sold": 5}, STORE_OPS)
        validate_error(res, ApiErrorId.ERR_NEGATIVE_ON_HAND)
        sku = validate_success(api.get_store_sku(env["sku"]["id"], STORE_OPS))
        assert sku["units_on_hand"] == 4

    def test_deplete_from_sold_out_is_invalid_state(self, api):
        """PRD §3.7: "Depletion is admissible from `ON_FLOOR`, `MARKED_DOWN`, or
        `CLEARANCE` — not from terminal states."

        Design: Corner/endpoints/store_sku_deplete_to_boundary_and_negative_rejection
        """
        env = setup_floor_sku(units_on_hand=4)
        validate_success(api.deplete_store_sku(env["sku"]["id"], {"units_sold": 4}, STORE_OPS))
        res = api.deplete_store_sku(env["sku"]["id"], {"units_sold": 1}, STORE_OPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

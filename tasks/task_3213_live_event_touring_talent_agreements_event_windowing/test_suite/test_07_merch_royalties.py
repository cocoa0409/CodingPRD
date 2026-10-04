"""Merch sales and royalty statements: likeness gates, merch windows,
immutability, and the FINAL/PROVISIONAL finalize rules."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_merch_sale,
    create_talent, create_draft_agreement, create_and_activate_agreement,
    create_arena, create_event,
    lock_event, complete_event,
    create_merch_sale_payload, create_royalty_statement_payload,
)

CA = TEST_USERS["contract_admin_headers"]
TP = TEST_USERS["tour_planner_headers"]
MO = TEST_USERS["merch_ops_headers"]


class TestMerchSaleGates:
    def test_talent_without_active_likeness_agreement_rejected(self, api):
        """PRD §3.8: "First, likeness rights: the talent must have `likeness_granted` set true — which, per §3.2, means an `ACTIVE` agreement with `likeness_rights_granted` — else the sale is rejected with `ERR_LIKENESS_NOT_GRANTED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_merch_sale
        """
        talent = create_talent(ring_name="NoLikeness Nick")
        # DRAFT-only agreement: likeness_granted stays false.
        create_draft_agreement(talent["id"], likeness_rights_granted=False)
        arena = create_arena(name="Merch Arena")
        event = create_event(arena["id"], name="MHS", event_date="2026-09-05")
        resp = api.create_merch_sale(
            create_merch_sale_payload(event["id"], talent["id"]),
            MO)
        validate_error(resp, ApiErrorId.ERR_LIKENESS_NOT_GRANTED)

    def test_sale_on_completed_event_rejected(self, api):
        """PRD §3.8: "Second, the merch window: a sale against a `COMPLETED` or `CANCELLED` event is rejected with `ERR_MERCH_WINDOW_CLOSED`."

        Design: Corner/validations/merch_sale_on_completed_event_rejected
        """
        talent = create_talent(ring_name="Closed Chloe")
        create_and_activate_agreement(talent["id"], likeness_rights_granted=True)
        arena = create_arena(name="CL Arena")
        event = create_event(arena["id"], name="CE", event_date="2026-09-05")
        lock_event(event)
        complete_event(event["id"])
        resp = api.create_merch_sale(
            create_merch_sale_payload(event["id"], talent["id"],
                                      sold_at="2026-09-05T22:00:00Z"),
            MO)
        validate_error(resp, ApiErrorId.ERR_MERCH_WINDOW_CLOSED)


class TestMerchSaleLedgerShape:
    def test_merch_sale_is_immutable_ledger_entry(self, api):
        """PRD §2.5: "The single exception is the **MerchSale** line, which is an immutable ledger entry: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent."
        PRD §3.8: "Below 100,000 cents, the rate is the agreement's rate minus a 100-basis-point discount. Each line's `royalty_cents` is then the line's `quantity` times `unit_price_cents` times the applicable rate in basis points, divided by 10,000, rounded half-up to a whole cent — and this rounding happens per line, before any summation."

        Design: Corner/entities/merch_sale_immutable_no_update_endpoint
        """
        talent = create_talent(ring_name="Imm Irv")
        create_and_activate_agreement(talent["id"], likeness_rights_granted=True)
        arena = create_arena(name="Imm Arena")
        event = create_event(arena["id"], name="IME", event_date="2026-09-05")
        sale = validate_success(api.create_merch_sale(
            create_merch_sale_payload(event["id"], talent["id"], quantity=1,
                                      unit_price_cents=2500),
            MO), expected_status=201)
        assert_merch_sale(sale)
        assert "updated_at" not in sale
        assert "version" not in sale
        # Day gross 2500 < 100000 -> tier0: 2000bp - 100bp = 1900bp.
        # round_half_up(1 * 2500 * 1900 / 10000) = 475.
        assert sale["royalty_cents"] == 475
        listed, meta = validate_paginated(
            api.list_merch_sales(MO, params={"event_id": event["id"]}))
        assert meta["total_count"] == 1
        fetched = [row for row in listed if row["id"] == sale["id"]][0]
        assert "updated_at" not in fetched
        assert "version" not in fetched


class TestRoyaltyStatementFinalizeRules:
    def test_provisional_not_finalizable_and_finalized_is_read_only(self, api):
        """PRD §3.8: "Finalization is reserved for `FINAL`-basis statements: attempting to finalize a `PROVISIONAL`-basis statement is rejected with `ERR_STATEMENT_NOT_FINALIZABLE`."
        PRD §3.8: "Opening a statement performs an initial recompute immediately; a statement still `OPEN` may be recomputed on demand (recompute against a non-`OPEN` statement is rejected with `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/statement_finalize_requires_final_basis
        """
        talent = create_talent(ring_name="Stmt Sue")
        create_and_activate_agreement(talent["id"])
        provisional = validate_success(api.create_royalty_statement(
            create_royalty_statement_payload(talent["id"], basis_mode="PROVISIONAL"), CA),
            expected_status=201)
        final = validate_success(api.create_royalty_statement(
            create_royalty_statement_payload(talent["id"], basis_mode="FINAL"), CA),
            expected_status=201)
        resp = api.finalize_royalty_statement(provisional["id"], CA)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FINALIZABLE)
        finalized = validate_success(api.finalize_royalty_statement(final["id"], CA))
        assert finalized["status"] == "FINALIZED"
        recompute = api.recompute_royalty_statement(final["id"], CA)
        validate_error(recompute, ApiErrorId.ERR_INVALID_STATE)


class TestRoyaltyTieringUnreachable:
    def test_tier2_bonus_gate_is_unproven_under_prd(self, api):
        """PRD §3.8: "The royalty rate applied to a line is tiered, and the tier is chosen by the talent's **event-day gross**, not by the line's own value: the day gross is the sum of `quantity` times `unit_price_cents` across all of that talent's merch lines on the same event with the same `sold_at` calendar date. When the day gross exceeds 250,000 cents, the rate is the agreement's `royalty_rate_bp` plus a 200-basis-point bonus. When the day gross is at least 100,000 cents but does not exceed the upper threshold, the rate is the agreement's `royalty_rate_bp` unchanged. Below 100,000 cents, the rate is the agreement's rate minus a 100-basis-point discount."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Corner/calculations/royalty_base_tier_rate_applies_below_tier2_gate
        """
        # Under the PRD a fresh talent starts UNBOOKABLE at 0.00 wellness and
        # wellness rises only via fulfilled bookings, so no booking can ever
        # exist and the >250,000-cent day-gross tier gate is unreachable
        # through declared endpoints. The uniquely-derivable sub-claim is the
        # tier0 discount on a sale against a SCHEDULED event for a
        # likeness-granted talent.
        talent = create_talent(ring_name="Tier Tessa")
        create_and_activate_agreement(talent["id"], likeness_rights_granted=True,
                                      royalty_rate_bp=2000)
        arena = create_arena(name="Tier Gate Arena")
        event = create_event(arena["id"], name="TG", event_date="2026-09-05")
        sale = validate_success(api.create_merch_sale(
            create_merch_sale_payload(event["id"], talent["id"], quantity=1,
                                      unit_price_cents=100000),
            MO), expected_status=201)
        # Day gross exactly 100000 -> "at least 100,000 cents" base tier:
        # round_half_up(100000 * 2000 / 10000) = 20000.
        assert sale["royalty_cents"] == 20000

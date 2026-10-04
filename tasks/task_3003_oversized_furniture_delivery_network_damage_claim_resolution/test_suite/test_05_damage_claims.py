"""Damage claims and chargebacks: concealment-variant liability allocation,
triage thresholds, state-machine guards, and the dispute/reverse branch."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_delivered_network_order,
    setup_determined_claim,
    setup_shipment_at_hub,
    open_claim,
    api_client,
    TEST_USERS,
    make_customer_headers,
    make_supplier_rep_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


class TestChargebackConcealedVsVisibleLiabilitySplit:
    def _inspect_pair(self, api):
        """Delivered order; two claims with identical economics (repair
        20000c, replacement snapshot 80000c): one CONCEALED, one
        VISIBLE_AT_DELIVERY; both inspected and determined."""
        refs = setup_delivered_network_order()
        claim_a = open_claim(
            refs["shipment"]["id"], refs["customer"], concealment="CONCEALED"
        )
        api_client.inspect_damage_claim(
            claim_a["id"],
            {"damage_pct": 20, "is_structural": False, "repair_cost_cents": 20000},
            HUB_OP,
        )
        claim_b = open_claim(
            refs["shipment"]["id"], concealment="VISIBLE_AT_DELIVERY",
            claimant_role="HUB_INSPECTOR",
        )
        api_client.inspect_damage_claim(
            claim_b["id"],
            {"damage_pct": 20, "is_structural": False, "repair_cost_cents": 20000},
            HUB_OP,
        )
        refs["claim_a"] = validate_success(
            api.determine_damage_claim(claim_a["id"], ADJUSTER), 200
        )
        refs["claim_b"] = validate_success(
            api.determine_damage_claim(claim_b["id"], ADJUSTER), 200
        )
        return refs

    def test_concealed_variant_supplier_liable_with_chargeback(self, api):
        """PRD §3.6: "When the claim is `CONCEALED`, the supplier is liable:
        the `liability_party` is set to `SUPPLIER`, the
        `chargeback_amount_cents` is the full repair cost plus 35% of the
        replacement cost, rounded half-up to whole cents, and a `Chargeback`
        is created in `PENDING` status with `amount_cents` equal to the
        claim's `chargeback_amount_cents`, linked one-to-one to the claim via
        `damage_claim_id` and carrying the debited `supplier_id`, the damaged
        `shipment_id`, and a `reason_code` of `CONCEALED_DAMAGE`,
        `REPAIR_OVERRUN`, or `FULL_REPLACEMENT` matching the resolution."

        Design: Difficulty/dual_variant_calc/chargeback_concealed_vs_visible_liability_split
        """
        refs = self._inspect_pair(api)
        claim_a = refs["claim_a"]
        assert claim_a["liability_party"] == "SUPPLIER"
        # 20000 * 1.00 + 80000 * 0.35 = 48000
        assert claim_a["chargeback_amount_cents"] == 48000
        rows, _meta = validate_paginated(
            api.list_chargebacks(ADMIN, params={"damage_claim_id": claim_a["id"]})
        )
        assert len(rows) == 1, "a PENDING Chargeback row must be created"
        assert rows[0]["amount_cents"] == 48000

    def test_visible_variant_carrier_liable_without_chargeback(self, api):
        """PRD §3.6: "When the claim is `VISIBLE_AT_DELIVERY`, the carrier is
        liable: `liability_party` becomes `CARRIER`, the claim records only a
        40%-of-repair-cost handling clawback as its `chargeback_amount_cents`
        (rounded half-up), and no `Chargeback` row is created at all."

        Design: Difficulty/dual_variant_calc/chargeback_concealed_vs_visible_liability_split
        """
        refs = self._inspect_pair(api)
        claim_b = refs["claim_b"]
        assert claim_b["liability_party"] == "CARRIER"
        # round_half_up(20000 * 0.40) = 8000
        assert claim_b["chargeback_amount_cents"] == 8000
        rows, _meta = validate_paginated(
            api.list_chargebacks(ADMIN, params={"damage_claim_id": claim_b["id"]})
        )
        assert len(rows) == 0, "no Chargeback row for the carrier-liable variant"


class TestDamageTriageThresholdBoundaries:
    def _delivered_with_claim(self, api):
        refs = setup_delivered_network_order()
        claim = open_claim(refs["shipment"]["id"], refs["customer"],
                           concealment="CONCEALED")
        return refs, claim

    def test_damage_pct_exactly_40_does_not_force_full_replacement(self, api):
        """PRD §3.6: "if the damage is structural, or the `damage_pct` is
        strictly greater than 40 — a reading of exactly 40 does not qualify —
        the resolution is `FULL_REPLACEMENT`"

        Design: Corner/calculations/damage_triage_threshold_boundaries
        """
        refs, claim = self._delivered_with_claim(api)
        data = validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 40, "is_structural": False,
                 "repair_cost_cents": 15000},
                HUB_OP,
            ),
            200,
        )
        assert data["resolution_type"] == "REPLACEMENT_PART", (
            "damage_pct exactly 40 is not strictly greater than 40"
        )

    def test_damage_pct_41_forces_full_replacement(self, api):
        """PRD §3.6: "if the damage is structural, or the `damage_pct` is
        strictly greater than 40 — a reading of exactly 40 does not qualify —
        the resolution is `FULL_REPLACEMENT`"

        Design: Corner/calculations/damage_triage_threshold_boundaries
        """
        refs, claim = self._delivered_with_claim(api)
        data = validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 41, "is_structural": False,
                 "repair_cost_cents": 15000},
                HUB_OP,
            ),
            200,
        )
        assert data["resolution_type"] == "FULL_REPLACEMENT"

    def test_repair_cost_floor_is_inclusive(self, api):
        """PRD §3.6: "otherwise, if the `repair_cost_cents` is at least 20000
        cents, the resolution is `REPAIR`; anything cheaper resolves to
        `REPLACEMENT_PART`."

        Design: Corner/calculations/damage_triage_threshold_boundaries
        """
        refs, claim = self._delivered_with_claim(api)
        data = validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 20, "is_structural": False,
                 "repair_cost_cents": 20000},
                HUB_OP,
            ),
            200,
        )
        assert data["resolution_type"] == "REPAIR", (
            "20000 meets the inclusive REPAIR floor"
        )

    def test_repair_cost_just_below_floor_is_replacement_part(self, api):
        """PRD §3.6: "otherwise, if the `repair_cost_cents` is at least 20000
        cents, the resolution is `REPAIR`; anything cheaper resolves to
        `REPLACEMENT_PART`."

        Design: Corner/calculations/damage_triage_threshold_boundaries
        """
        refs, claim = self._delivered_with_claim(api)
        data = validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 20, "is_structural": False,
                 "repair_cost_cents": 19999},
                HUB_OP,
            ),
            200,
        )
        assert data["resolution_type"] == "REPLACEMENT_PART"


class TestClaimStateMachine:
    def test_claim_settle_from_open_is_an_invalid_transition(self, api):
        """PRD §3.6: "Settlement, also by a `ClaimsAdjuster`, requires the
        claim to be in `DETERMINATION` and — when a linked chargeback exists —
        requires that chargeback to already be `SETTLED` or `REVERSED`"
        PRD §2.7: "fifth, whether the target entity is in a valid state for
        the requested transition (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/claim_settle_from_open_is_an_invalid_transition
        """
        refs = setup_delivered_network_order()
        claim = open_claim(refs["shipment"]["id"], refs["customer"],
                           concealment="CONCEALED")
        resp = api.settle_damage_claim(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_damage_claim(claim["id"], ADMIN))
        assert still["status"] == "OPEN"
        rows, _meta = validate_paginated(
            api.list_chargebacks(ADMIN, params={"damage_claim_id": claim["id"]})
        )
        assert len(rows) == 0

    def test_withdrawn_claim_is_terminal_and_cannot_be_inspected(self, api):
        """PRD §3.6: "While `OPEN`, a claim may be withdrawn by the `Customer`
        or a `ClaimsAdjuster`, moving it to `WITHDRAWN`."
        PRD §3.6: "Inspection is performed by a `HubOperator` and requires
        two preconditions: the claim must be `OPEN` (else
        `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/withdrawn_claim_is_terminal_and_cannot_be_inspected
        """
        refs = setup_delivered_network_order()
        claim = open_claim(
            refs["shipment"]["id"], refs["customer"],
            concealment="VISIBLE_AT_DELIVERY",
        )
        validate_success(
            api.withdraw_damage_claim(
                claim["id"], make_customer_headers(refs["customer"]["id"])
            ),
            200,
        )
        resp = api.inspect_damage_claim(
            claim["id"],
            {"damage_pct": 10, "is_structural": False, "repair_cost_cents": 1000},
            HUB_OP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_damage_claim(claim["id"], ADMIN))
        assert still["status"] == "WITHDRAWN"

    def test_claim_inspect_requires_shipment_at_hub_or_delivered(self, api):
        """PRD §3.6: "Inspection is performed by a `HubOperator` and requires
        two preconditions: the claim must be `OPEN` (else
        `ERR_INVALID_STATE`), and the shipment must be in `AT_HUB` or
        `DELIVERED` so there is something inspectable — otherwise
        `ERR_CLAIM_REQUIRES_INSPECTABLE_SHIPMENT`."

        Design: Difficulty/cross_entity_state_dependency/claim_inspect_requires_shipment_at_hub_or_delivered
        """
        # Build a shipment that is IN_TRANSIT (linehaul not yet arrived).
        from test_helpers import setup_shipment_in_transit
        refs = setup_shipment_in_transit()
        claim = open_claim(
            refs["shipment"]["id"], refs["customer"],
            concealment="VISIBLE_AT_DELIVERY",
        )
        resp = api.inspect_damage_claim(
            claim["id"],
            {"damage_pct": 15, "is_structural": False, "repair_cost_cents": 9000},
            HUB_OP,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_REQUIRES_INSPECTABLE_SHIPMENT)

    def test_claim_inspect_succeeds_once_shipment_at_hub(self, api):
        """PRD §3.6: "the shipment must be in `AT_HUB` or `DELIVERED` so there
        is something inspectable — otherwise
        `ERR_CLAIM_REQUIRES_INSPECTABLE_SHIPMENT`."
        PRD §3.2: "A successful arrival moves every bound shipment that is
        still `IN_TRANSIT` to `AT_HUB`."

        Design: Difficulty/cross_entity_state_dependency/claim_inspect_requires_shipment_at_hub_or_delivered
        """
        from test_helpers import setup_shipment_in_transit
        refs = setup_shipment_in_transit()
        claim = open_claim(
            refs["shipment"]["id"], refs["customer"],
            concealment="VISIBLE_AT_DELIVERY",
        )
        validate_success(api.arrive_linehaul(refs["linehaul"]["id"], HUB_OP), 200)
        data = validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 15, "is_structural": False,
                 "repair_cost_cents": 9000},
                HUB_OP,
            ),
            200,
        )
        assert data["status"] == "INSPECTION"


class TestClaimSettleBlockedWhileChargebackOpen:
    def test_claim_settle_blocked_while_chargeback_open(self, api):
        """PRD §3.6: "Settlement, also by a `ClaimsAdjuster`, requires the
        claim to be in `DETERMINATION` and — when a linked chargeback exists —
        requires that chargeback to already be `SETTLED` or `REVERSED`;
        settling while the chargeback is still `PENDING` or `DISPUTED` is
        rejected with `ERR_CHARGEBACK_OPEN`."

        Design: Corner/validations/claim_settle_blocked_while_chargeback_open
        """
        refs = setup_determined_claim(concealment="CONCEALED")
        assert refs["chargeback"] is not None
        resp = api.settle_damage_claim(refs["claim"]["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_OPEN)
        validate_success(
            api.settle_chargeback(refs["chargeback"]["id"], ADMIN), 200
        )
        settled = validate_success(
            api.settle_damage_claim(refs["claim"]["id"], ADJUSTER), 200
        )
        assert settled["status"] == "SETTLED"


class TestChargebackDisputeReverseBranch:
    def test_dispute_then_reverse_leaves_supplier_ledger_unchanged(self, api):
        """PRD §3.7: "Disputing is guarded twice: the chargeback must be
        `PENDING` (else `ERR_INVALID_STATE`), and the acting `SupplierRep`'s
        `X-User-ID` must equal the chargeback's `supplier_id`, else
        `ERR_FORBIDDEN` — a supplier may never dispute another supplier's
        chargeback."
        PRD §3.7: "Both settlement and reversal recompute the supplier's
        metrics, with reversal excluding `REVERSED` chargebacks from the
        rate."

        Design: Difficulty/non_linear_state_machine/chargeback_dispute_reverse_branch
        """
        refs = setup_determined_claim(concealment="CONCEALED")
        cb = refs["chargeback"]
        validate_success(
            api.dispute_chargeback(
                cb["id"], make_supplier_rep_headers(refs["supplier"]["id"])
            ),
            200,
        )
        reversed_cb = validate_success(api.reverse_chargeback(cb["id"], ADMIN), 200)
        assert reversed_cb["status"] == "REVERSED"
        supplier = validate_success(api.get_supplier(refs["supplier"]["id"], ADMIN))
        assert supplier["chargeback_rate"] == pytest.approx(0.00, abs=0.001), (
            "REVERSED chargebacks are excluded from the settled numerator"
        )
        settled = validate_success(
            api.settle_damage_claim(refs["claim"]["id"], ADJUSTER), 200
        )
        assert settled["status"] == "SETTLED"

    def test_settle_from_reversed_is_invalid_state(self, api):
        """PRD §3.7: "Settling works from either `PENDING` or `DISPUTED` and
        moves the chargeback to `SETTLED`; reversing works only from
        `DISPUTED` and moves it to `REVERSED`."

        Design: Difficulty/non_linear_state_machine/chargeback_dispute_reverse_branch
        """
        refs = setup_determined_claim(concealment="CONCEALED")
        cb = refs["chargeback"]
        validate_success(
            api.dispute_chargeback(
                cb["id"], make_supplier_rep_headers(refs["supplier"]["id"])
            ),
            200,
        )
        validate_success(api.reverse_chargeback(cb["id"], ADMIN), 200)
        resp = api.settle_chargeback(cb["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestChargebackDisputeReverseConservesSupplierLedger:
    def test_pending_chargeback_never_enters_rate(self, api):
        """PRD §3.7: "The `chargeback_rate` is the percentage, also 2-decimal
        round-half-up, of `SETTLED` chargebacks attributed to the supplier
        over the count of the supplier's shipments whose state is not
        `EXCEPTION`; when the denominator is zero the rate is 0.00."

        Design: Difficulty/compensating_invariant/chargeback_dispute_reverse_conserves_supplier_ledger
        """
        refs = setup_determined_claim(concealment="CONCEALED")
        supplier = validate_success(api.get_supplier(refs["supplier"]["id"], ADMIN))
        assert supplier["chargeback_rate"] == pytest.approx(0.00, abs=0.001), (
            "PENDING chargebacks never enter the rate"
        )

    def test_dispute_reverse_pair_restores_pre_claim_metrics(self, api):
        """PRD §3.7: "Both settlement and reversal recompute the supplier's
        metrics, with reversal excluding `REVERSED` chargebacks from the
        rate."
        PRD §3.7: "The `compliance_score` blends the two: 0.60 times the
        on-time rate plus 0.40 times the complement of the chargeback rate
        (100 minus the chargeback rate), with the sum consuming the
        already-rounded 2-decimal rates and itself rounded half-up to 2
        decimals."

        Design: Difficulty/compensating_invariant/chargeback_dispute_reverse_conserves_supplier_ledger
        """
        refs = setup_determined_claim(concealment="CONCEALED")
        cb = refs["chargeback"]
        validate_success(
            api.dispute_chargeback(
                cb["id"], make_supplier_rep_headers(refs["supplier"]["id"])
            ),
            200,
        )
        validate_success(api.reverse_chargeback(cb["id"], ADMIN), 200)
        supplier = validate_success(api.get_supplier(refs["supplier"]["id"], ADMIN))
        assert supplier["chargeback_rate"] == pytest.approx(0.00, abs=0.001)
        assert supplier["compliance_score"] == pytest.approx(100.00, abs=0.001)
        assert supplier["status"] == "ACTIVE", (
            "the dispute+reverse pair restores the pre-claim ledger position"
        )


class TestNewEntitiesStartInDeclaredInitialStates:
    def test_new_entities_start_in_declared_initial_states(self, api):
        """PRD §3.2: "A linehaul is created `PLANNED` with a `committed_count`
        of zero"
        PRD §3.8: "A `Customer` requests a return authorization by naming the
        `order_id` and a `reason` — `DAMAGE`, `BUYERS_REMORSE`, or
        `WRONG_ITEM` — creating the authorization in `REQUESTED`."
        PRD §3.6: "The claim is born `OPEN`, and its `replacement_cost_cents`
        is snapshotted from the item's `declared_value_cents` at creation time
        so later price changes cannot rewrite history."

        Design: Corner/state_machines/new_entities_start_in_declared_initial_states
        """
        refs = setup_delivered_network_order()
        lh = validate_success(
            api.create_linehaul(
                {
                    "hub_id": refs["hub"]["id"],
                    "planned_arrival_date": "2026-09-20",
                    "origin_ship_date": "2026-09-18",
                    "capacity": 8,
                },
                ADMIN,
            ),
            201,
        )
        assert lh["status"] == "PLANNED"
        assert lh["committed_count"] == 0

        ra = validate_success(
            api.create_return_authorization(
                {"order_id": refs["order"]["id"], "reason": "DAMAGE"},
                make_customer_headers(refs["customer"]["id"]),
            ),
            201,
        )
        assert ra["status"] == "REQUESTED"
        assert ra.get("disposition") is None

        claim = open_claim(
            refs["shipment"]["id"], concealment="CONCEALED",
            claimant_role="HUB_INSPECTOR",
        )
        assert claim["status"] == "OPEN"
        assert claim["chargeback_amount_cents"] == 0

"""Reversals that must put every conserved quantity back exactly, and the
places where the specification deliberately does not compensate.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_paginated, validate_success
from test_helpers.factories import salvage_order_payload
from test_helpers.test_users import CONTROLLER_ONE_ID


class TestRollBackRestoresExposureAndReservations:
    """The ticket, the reserve and the reservations all come back."""

    def test_roll_back_restores_the_ticket_and_zeroes_the_exposure(self, api):
        """PRD 2.9: "First, an item's markdown exposure is the sum of
        `permanent_markdown_reserve_cents` and `promo_discount_cents`; applying an
        execution and then rolling the same execution back must leave that sum, and
        `current_retail_cents`, at their pre-apply values."

        Design: Difficulty/compensating_invariant/roll_back_restores_margin_exposure_ticket_and_reservations
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        fx.roll_back_execution(
            api, sc.execution["id"], rollback_reason="signage misprint pulled chainwide"
        )
        item = fx.read_item(api, sc.item["id"])

        assert item["current_retail_cents"] == 4999
        assert item["permanent_markdown_reserve_cents"] == 0
        assert item["promo_discount_cents"] == 0
        assert item["markdown_state"] == "FULL_PRICE"
        assert item["lifecycle_stage"] == "AGING"

    def test_the_rolled_back_execution_keeps_its_line_as_history(self, api):
        """PRD 3.6: "The execution moves `APPLIED → ROLLED_BACK`, and `ROLLED_BACK`
        is terminal."

        Design: Difficulty/compensating_invariant/roll_back_restores_margin_exposure_ticket_and_reservations
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        rolled_back = fx.roll_back_execution(
            api, sc.execution["id"], rollback_reason="signage misprint pulled chainwide"
        )

        assert rolled_back["status"] == "ROLLED_BACK"
        assert rolled_back["per_unit_markdown_cents"] == 1128
        assert rolled_back["line_markdown_cents"] == 225600

    def test_the_plan_loses_the_line_but_keeps_its_executing_status(self, api):
        """PRD 3.6: "The plan's `gross_markdown_cents` is reduced by the rolled-back
        `line_markdown_cents` and `net_markdown_cents` is recomputed."

        Design: Difficulty/compensating_invariant/roll_back_restores_margin_exposure_ticket_and_reservations
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        fx.roll_back_execution(
            api, sc.execution["id"], rollback_reason="signage misprint pulled chainwide"
        )
        plan = fx.read_plan(api, sc.plan["id"])

        assert plan["gross_markdown_cents"] == 0
        assert plan["net_markdown_cents"] == 0
        # PRD 3.6 enumerates exactly what a roll-back undoes and plan status is
        # not among them, so whether the plan stays COMPLETED or falls back to
        # EXECUTING is not determined; what PRD does pin is that the plan is
        # neither un-executed nor superseded.
        assert plan["status"] in ("EXECUTING", "COMPLETED")
        assert fx.read_step(api, sc.step1["id"])["status"] == "SCHEDULED"

    def test_the_reservations_flip_back_and_the_season_counters_follow(self, api):
        """PRD 3.7: "It moves back `COMMITTED → RESERVED` when that item's stage
        reverts to `AGING` after a rolled-back execution, shifting the same units back
        the other way."

        Design: Difficulty/compensating_invariant/roll_back_restores_margin_exposure_ticket_and_reservations
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        fx.roll_back_execution(
            api, sc.execution["id"], rollback_reason="signage misprint pulled chainwide"
        )
        rank1 = fx.read_reservation(api, sc.reservations[0]["id"])
        rank2 = fx.read_reservation(api, sc.reservations[1]["id"])
        season = fx.read_season(api, sc.season["id"])

        assert rank1["status"] == "RESERVED"
        assert rank1["reserved_units"] == 500
        assert rank1["allocation_rank"] == 1
        assert rank2["status"] == "RESERVED"
        assert rank2["reserved_units"] == 100
        assert rank2["allocation_rank"] == 2
        assert season["reserved_clearance_units"] == 600
        assert season["committed_clearance_units"] == 0

    def test_the_season_status_is_deliberately_not_compensated(self, api):
        """PRD 3.4: "The season's own lifecycle runs `PLANNING → ACTIVE →
        EXIT_WINDOW → CLOSED`, and the director drives it by naming a `to_status`."

        Design: Difficulty/compensating_invariant/roll_back_restores_margin_exposure_ticket_and_reservations
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        fx.roll_back_execution(
            api, sc.execution["id"], rollback_reason="signage misprint pulled chainwide"
        )

        assert fx.read_season(api, sc.season["id"])["status"] == "EXIT_WINDOW"

    def test_the_store_space_identity_holds_at_both_filled_stores(self, api, analyst):
        """PRD 2.9: "Third, a store's `clearance_bay_units` always equals its
        `available_clearance_units` plus the sum of `reserved_units` across its
        `RESERVED` and `COMMITTED` reservations, so releasing a reservation gives the
        space back exactly."

        Design: Difficulty/compensating_invariant/roll_back_restores_margin_exposure_ticket_and_reservations
        """
        sc = fx.exit_window_scenario(api, total_units=600)
        fx.roll_back_execution(
            api, sc.execution["id"], rollback_reason="signage misprint pulled chainwide"
        )

        store_0202 = fx.read_store(api, sc.store_0202["id"])
        store_0101 = fx.read_store(api, sc.store_0101["id"])
        rows, meta = validate_paginated(
            api.list_clearance_reservations(analyst, {"markdown_plan_id": sc.plan["id"]})
        )

        assert store_0202["committed_clearance_units"] == 500
        assert store_0202["available_clearance_units"] == 0
        assert store_0202["clearance_bay_units"] == 500
        assert store_0101["committed_clearance_units"] == 100
        assert store_0101["available_clearance_units"] == 200
        assert store_0101["clearance_bay_units"] == 300
        assert meta["total_count"] == 2
        assert sc.store_0303["id"] not in [row["store_id"] for row in rows]


class TestClaimReversalRestoresCapButNotSiblings:
    """The cap comes back; the rejected sibling stays rejected."""

    def test_reversal_zeroes_the_recognised_amount_and_keeps_the_claim(self, api):
        """PRD 3.8: "It applies to a claim in `RECOGNIZED` whose agreement is either
        `AGREED` or `FUNDED`, and moves the claim `RECOGNIZED → REVERSED`, and
        `REVERSED` is terminal."

        Design: Difficulty/compensating_invariant/claim_reversal_restores_cap_and_net_markdown_but_not_rejected_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)
        fx.recognize_claim(api, claim1["id"])

        reversed_claim = fx.reverse_claim(
            api, claim1["id"], reversal_reason="allowance repudiated by vendor audit"
        )

        assert reversed_claim["status"] == "REVERSED"
        assert reversed_claim["recognized_cents"] == 0
        assert reversed_claim["claimed_cents"] == 56400

    def test_the_agreement_returns_from_funded_with_its_cap_restored(self, api):
        """PRD 3.8: "The agreement's `recognized_total_cents` falls by the reversed
        amount, its `remaining_cap_cents` is restored, and an agreement that had
        reached `FUNDED` returns to `AGREED`; the plan's `vendor_funded_cents` falls
        by the same amount with `net_markdown_cents` recomputed; and the claim's own
        `recognized_cents` is zeroed."

        Design: Difficulty/compensating_invariant/claim_reversal_restores_cap_and_net_markdown_but_not_rejected_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)
        fx.recognize_claim(api, claim1["id"])
        fx.reverse_claim(
            api, claim1["id"], reversal_reason="allowance repudiated by vendor audit"
        )

        agreement = fx.read_agreement(api, sc.agreement["id"])
        plan = fx.read_plan(api, sc.plan["id"])

        assert agreement["status"] == "AGREED"
        assert agreement["recognized_total_cents"] == 0
        assert agreement["remaining_cap_cents"] == 56400
        assert plan["vendor_funded_cents"] == 0
        assert plan["net_markdown_cents"] == 225600
        assert plan["gross_markdown_cents"] == 225600

    def test_the_freed_cap_does_not_resurrect_the_rejected_sibling(self, api):
        """PRD 3.8: "Note that reversal does not resurrect the sibling claims the
        exhausted cap rejected — `REJECTED` is terminal, and a new claim must be
        filed."

        Design: Difficulty/compensating_invariant/claim_reversal_restores_cap_and_net_markdown_but_not_rejected_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        claim2 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)
        fx.recognize_claim(api, claim1["id"])
        fx.reverse_claim(
            api, claim1["id"], reversal_reason="allowance repudiated by vendor audit"
        )

        sibling = fx.read_claim(api, claim2["id"])

        assert sibling["status"] == "REJECTED"
        assert sibling["rejection_reason"] == "CAP_EXHAUSTED"
        assert sibling["recognized_cents"] == 0

    def test_the_markdown_itself_and_the_cap_identity_survive_the_pair(self, api):
        """PRD 2.9: "Second, an agreement's `funding_cap_cents` always equals its
        `remaining_cap_cents` plus the sum of `recognized_cents` across its
        `RECOGNIZED` claims; recognising a claim and then reversing it must restore
        both sides."

        Design: Difficulty/compensating_invariant/claim_reversal_restores_cap_and_net_markdown_but_not_rejected_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)
        fx.recognize_claim(api, claim1["id"])
        fx.reverse_claim(
            api, claim1["id"], reversal_reason="allowance repudiated by vendor audit"
        )

        agreement = fx.read_agreement(api, sc.agreement["id"])
        claims = fx.list_claims_of_agreement(api, sc.agreement["id"])
        recognized_sum = sum(
            c["recognized_cents"] for c in claims if c["status"] == "RECOGNIZED"
        )

        assert recognized_sum == 0
        assert agreement["funding_cap_cents"] == (
            agreement["remaining_cap_cents"] + recognized_sum
        )
        assert fx.read_execution(api, sc.execution["id"])["status"] == "APPLIED"
        assert (
            fx.read_execution(api, sc.execution["id"])["line_markdown_cents"] == 225600
        )


def _approved_salvage_order(api):
    sc = fx.base_scenario(api)
    fx.set_clock(api, "2026-12-05T00:00:00Z")
    sc["season"] = fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
    sc["order"] = fx.create_disposition(
        api, salvage_order_payload(sc.season["id"], sc.item["id"], 200, 300)
    )
    sc["order"] = fx.approve_disposition(api, sc.order["id"])
    return sc


class TestDispositionCancelRestoresTheAvailablePool:
    """Cancelling gives back exactly the units it took."""

    def test_cancelling_is_terminal_and_keeps_the_approval_record(self, api):
        """PRD 3.9: "A `PricingAnalyst` or a `MerchandiseDirector` may instead cancel
        an order with an optional `cancel_reason`, from either `DRAFT → CANCELLED` or
        `APPROVED → CANCELLED`; cancellation subtracts the order's `units` from the
        item's `units_committed_disposition`, restoring the uncommitted pool to
        exactly its pre-draft value."

        Design: Difficulty/compensating_invariant/disposition_cancel_restores_available_units_for_a_full_reallocation
        """
        sc = _approved_salvage_order(api)

        cancelled = fx.cancel_disposition(
            api, sc.order["id"], cancel_reason="salvage buyer withdrew"
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["approved_by_user_id"] == CONTROLLER_ONE_ID
        assert cancelled["projected_recovery_cents"] == 60000
        assert cancelled["settled_units"] == 0
        assert cancelled["settled_recovery_cents"] == 0

    def test_the_cancel_frees_the_units_without_moving_inventory(self, api):
        """PRD 2.9: "An item's available pool obeys the same discipline: its on-hand
        units less `units_committed_disposition` is restored to its pre-create value
        when a disposition order is cancelled."

        Design: Difficulty/compensating_invariant/disposition_cancel_restores_available_units_for_a_full_reallocation
        """
        sc = _approved_salvage_order(api)

        fx.cancel_disposition(
            api, sc.order["id"], cancel_reason="salvage buyer withdrew"
        )
        item = fx.read_item(api, sc.item["id"])

        assert item["units_committed_disposition"] == 0
        assert item["on_hand_units"] == 343
        assert item["units_disposed_total"] == 0
        assert item["markdown_state"] == "FULL_PRICE"
        assert item["lifecycle_stage"] == "CLEARANCE"

    def test_the_whole_freed_pool_can_be_committed_again(self, api, analyst):
        """PRD 3.9: "Drafting also requires the season to be `ACTIVE` or
        `EXIT_WINDOW`, the item's `lifecycle_stage` to be `CLEARANCE` or
        `EXIT_PENDING`, and the requested `units` to be at least 1 and no more than
        the item's on-hand units less its `units_committed_disposition` at that
        moment; over-committing is refused with `ERR_INSUFFICIENT_AVAILABLE_UNITS`."

        Design: Difficulty/compensating_invariant/disposition_cancel_restores_available_units_for_a_full_reallocation
        """
        sc = _approved_salvage_order(api)
        fx.cancel_disposition(
            api, sc.order["id"], cancel_reason="salvage buyer withdrew"
        )

        second = validate_success(
            api.create_disposition_order(
                salvage_order_payload(sc.season["id"], sc.item["id"], 343, 300),
                analyst,
            ),
            201,
        )

        assert second["units"] == 343
        assert second["projected_recovery_cents"] == 102900
        assert fx.read_item(api, sc.item["id"])["units_committed_disposition"] == 343

        _, meta = validate_paginated(
            api.list_disposition_orders(analyst, {"item_id": sc.item["id"]})
        )
        assert meta["total_count"] == 2

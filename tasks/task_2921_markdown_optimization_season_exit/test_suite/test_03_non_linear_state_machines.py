"""State machines that cycle, or that run two dimensions at once, so a linear
status ladder cannot reproduce them.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers.test_users import ANALYST_ONE_ID, DIRECTOR_ONE_ID


def _promotional_applied(api):
    sc = fx.planned_scenario(api, plan_type="PROMOTIONAL")
    sc = fx.approved_plan_scenario(api, sc)
    sc = fx.scheduled_execution_scenario(api, sc)
    sc = fx.verified_execution_scenario(api, sc)
    return fx.applied_execution_scenario(api, sc)


class TestItemDimensionsAdvanceIndependently:
    """The lifecycle dimension and the pricing dimension move on their own."""

    def test_a_promotional_apply_moves_the_ticket_without_moving_the_lifecycle(
        self, api
    ):
        """PRD 3.3: "Every item carries two independent state dimensions that never
        constrain each other's transitions: a `lifecycle_stage` describing where
        the unit sits in its selling life, and a `markdown_state` describing where
        its ticket sits." PRD 3.6 pins the promotional branch: "Under a
        `PROMOTIONAL` plan whose rung depth is below 50.00 percent, an item at
        `FULL_PRICE` moves `FULL_PRICE → PROMO_ACTIVE`; its `current_retail_cents`
        becomes the rung price, and its `promo_discount_cents` accrues the
        per-unit markdown for every unit sold on or after the execution's
        `effective_date` — contra-revenue, recognised only as the units actually
        move."

        Design: Difficulty/non_linear_state_machine/item_lifecycle_and_markdown_dimensions_advance_independently
        """
        sc = _promotional_applied(api)

        item = fx.read_item(api, sc.item["id"])

        assert item["markdown_state"] == "PROMO_ACTIVE"
        assert item["lifecycle_stage"] == "AGING"
        assert item["current_retail_cents"] == 3871
        assert item["permanent_markdown_reserve_cents"] == 0
        assert item["promo_discount_cents"] == 0

    def test_the_lifecycle_dimension_advances_while_the_ticket_stays_put(self, api):
        """PRD 3.3 rule 4: "Otherwise it is `CLEARANCE` when the item's
        `markdown_state` is either `PERM_MARKED` or `EXIT_PRICED`, or when weeks to
        exit is six or fewer."

        Design: Difficulty/non_linear_state_machine/item_lifecycle_and_markdown_dimensions_advance_independently
        """
        sc = _promotional_applied(api)

        fx.set_clock(api, "2026-12-05T00:00:00Z")
        item = fx.read_item(api, sc.item["id"])

        assert item["lifecycle_stage"] == "CLEARANCE"
        assert item["markdown_state"] == "PROMO_ACTIVE"

    def test_the_promotional_apply_still_drives_the_plan_and_the_rung(self, api):
        """PRD 3.5: "The first execution of an approved plan to reach `APPLIED`
        carries the plan `APPROVED → EXECUTING` and recomputes
        `gross_markdown_cents` and `net_markdown_cents` from its applied
        executions."

        Design: Difficulty/non_linear_state_machine/item_lifecycle_and_markdown_dimensions_advance_independently
        """
        sc = _promotional_applied(api)

        assert sc.execution["status"] == "APPLIED"
        assert sc.execution["per_unit_markdown_cents"] == 1128
        assert sc.execution["line_markdown_cents"] == 225600

        assert fx.read_plan(api, sc.plan["id"])["status"] == "COMPLETED"
        assert fx.read_step(api, sc.step1["id"])["status"] == "EXECUTED"


class TestPlanRevisionCycle:
    """Review is a cycle: a submitted plan can be pushed back to DRAFT."""

    def test_request_revision_returns_the_plan_and_counts_the_round(self, api):
        """PRD 3.5: "A director may send a submitted plan back by supplying a
        `revision_reason`, which moves it `SUBMITTED → REVISION_REQUESTED` and
        increments `revision_round` by 1."

        Design: Difficulty/non_linear_state_machine/plan_revision_cycle_returns_to_draft_and_clears_ladder
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )
        fx.submit_plan(api, sc.plan["id"])

        returned = fx.request_revision(api, sc.plan["id"])

        assert returned["status"] == "REVISION_REQUESTED"
        assert returned["revision_round"] == 1

    def test_reopening_with_clear_ladder_supersedes_the_rungs_it_clears(self, api):
        """PRD 3.5: "The analyst then reopens it, moving it `REVISION_REQUESTED →
        DRAFT`; the reopen request may carry `clear_ladder`, and when that flag is
        true every rung of the plan still in `PLANNED` moves to `SUPERSEDED` and
        `ladder_step_count` resets to 0, so the analyst re-authors the ladder from
        `step_index` 1."

        Design: Difficulty/non_linear_state_machine/plan_revision_cycle_returns_to_draft_and_clears_ladder
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )
        fx.submit_plan(api, sc.plan["id"])
        fx.request_revision(api, sc.plan["id"])

        reopened = fx.reopen_plan(api, sc.plan["id"], clear_ladder=True)

        assert reopened["status"] == "DRAFT"
        assert reopened["ladder_step_count"] == 0
        assert fx.read_step(api, sc.step1["id"])["status"] == "SUPERSEDED"

    def test_the_re_authored_ladder_starts_again_at_step_index_one(self, api):
        """PRD 3.5: "Depth is always measured off the original ticket, never off
        the live one, so the rung's `price_cents` is the item's
        `original_retail_cents` less the discount, where the discount is
        `original_retail_cents` multiplied by `depth_pct` divided by 100 and
        rounded half up to a whole cent before the subtraction."

        Design: Difficulty/non_linear_state_machine/plan_revision_cycle_returns_to_draft_and_clears_ladder
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )
        fx.submit_plan(api, sc.plan["id"])
        fx.request_revision(api, sc.plan["id"])
        fx.reopen_plan(api, sc.plan["id"], clear_ladder=True)

        step2 = fx.add_rung(api, sc.plan["id"], 1, "2026-10-26", 25.00)

        assert step2["step_index"] == 1
        assert step2["effective_date"] == "2026-10-26"
        assert step2["price_cents"] == 3749
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 1

    def test_the_cycle_ends_in_approval_with_the_revision_round_retained(self, api):
        """PRD 3.5: "Alternatively the director approves, which requires the plan
        to be `SUBMITTED`, the season to be `ACTIVE` or `EXIT_WINDOW`, and the
        approving `X-User-ID` to differ from the plan's `created_by_user_id`;
        approval stamps `approved_by_user_id`, moves the plan `SUBMITTED →
        APPROVED` and recomputes the season's `projected_exit_units`."

        Design: Difficulty/non_linear_state_machine/plan_revision_cycle_returns_to_draft_and_clears_ladder
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )
        fx.submit_plan(api, sc.plan["id"])
        fx.request_revision(api, sc.plan["id"])
        fx.reopen_plan(api, sc.plan["id"], clear_ladder=True)
        fx.add_rung(api, sc.plan["id"], 1, "2026-10-26", 25.00)
        fx.submit_plan(api, sc.plan["id"])

        approved = fx.approve_plan(api, sc.plan["id"])

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == DIRECTOR_ONE_ID
        assert approved["created_by_user_id"] == ANALYST_ONE_ID
        assert approved["revision_round"] == 1


class TestAllowanceNegotiationAlternatesOwner:
    """The offer table passes back and forth, revisiting PROPOSED."""

    def test_the_negotiation_opens_uncommitted_at_round_one(self, api):
        """PRD 3.8: "The agreement opens in `PROPOSED` with `round_index` at 1,
        `last_offer_by_role` set to `PricingAnalyst` and `last_offer_by_user_id`
        taken from `X-User-ID`, while `agreed_share_pct`, `funding_cap_cents` and
        `remaining_cap_cents` all stay null and `recognized_total_cents` sits at
        0 — nothing is committed until an offer is accepted."

        Design: Difficulty/non_linear_state_machine/allowance_negotiation_alternates_offer_owner_across_rounds
        """
        sc = fx.base_scenario(api)

        agreement = fx.create_agreement(
            api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
        )

        assert agreement["status"] == "PROPOSED"
        assert agreement["round_index"] == 1
        assert agreement["last_offer_by_role"] == "PricingAnalyst"
        assert agreement["agreed_share_pct"] is None
        assert agreement["recognized_total_cents"] == 0

    def test_countering_alternates_the_owner_and_returns_to_proposed(self, api):
        """PRD 3.8: "The two directions are symmetric and both are cyclic: a
        `VendorRep` counter moves the agreement `PROPOSED → COUNTERED`, and a
        `PricingAnalyst` counter moves it `COUNTERED → PROPOSED`, so the table can
        pass back and forth."

        Design: Difficulty/non_linear_state_machine/allowance_negotiation_alternates_offer_owner_across_rounds
        """
        sc = fx.base_scenario(api)
        agreement = fx.create_agreement(
            api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
        )

        countered = fx.counter_agreement(api, agreement["id"], 15.00, 40000)
        assert countered["status"] == "COUNTERED"
        assert countered["round_index"] == 2
        assert countered["last_offer_by_role"] == "VendorRep"
        assert countered["current_share_pct"] == pytest.approx(15.00, abs=0.001)
        assert countered["current_cap_cents"] == 40000

        recountered = fx.counter_agreement(
            api, agreement["id"], 20.00, 50000, headers=fx.ANALYST_HEADERS
        )
        assert recountered["status"] == "PROPOSED"
        assert recountered["round_index"] == 3
        assert recountered["last_offer_by_role"] == "PricingAnalyst"

    def test_acceptance_freezes_the_terms_that_were_last_on_the_table(self, api):
        """PRD 3.8: "Acceptance copies `current_share_pct` into `agreed_share_pct`
        and `current_cap_cents` into `funding_cap_cents`, sets
        `remaining_cap_cents` equal to that cap, and leaves
        `recognized_total_cents` at 0."

        Design: Difficulty/non_linear_state_machine/allowance_negotiation_alternates_offer_owner_across_rounds
        """
        sc = fx.base_scenario(api)
        agreement = fx.create_agreement(
            api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
        )
        fx.counter_agreement(api, agreement["id"], 15.00, 40000)
        fx.counter_agreement(
            api, agreement["id"], 20.00, 50000, headers=fx.ANALYST_HEADERS
        )

        agreed = fx.accept_agreement(api, agreement["id"])

        assert agreed["status"] == "AGREED"
        assert agreed["agreed_share_pct"] == pytest.approx(20.00, abs=0.001)
        assert agreed["funding_cap_cents"] == 50000
        assert agreed["remaining_cap_cents"] == 50000
        assert agreed["recognized_total_cents"] == 0
        assert agreed["round_index"] == 3

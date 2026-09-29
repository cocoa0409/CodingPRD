"""Writes on one entity that are gated by the state of a different entity
reached through a foreign key.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import salvage_order_payload, vendor_claim_payload


class TestSubmitBlockedByASupersededEstimate:
    """The plan is untouched, yet its estimate has moved underneath it."""

    def test_a_newer_certification_supersedes_the_referenced_estimate(self, api, analyst):
        """PRD 3.3: "Certification moves the estimate `DRAFT → CERTIFIED`, stamps
        `certified_at` from the logical clock, and then supersedes the field: every
        other estimate of the same item whose status is `DRAFT` or `CERTIFIED` moves
        to `SUPERSEDED`, whether it was a stale draft (which simply becomes
        uncertifiable) or the previously certified figure."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_estimate_superseded_by_newer_certification
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )

        second = fx.certified_estimate(api, sc.item["id"])

        first = validate_success(api.get_elasticity_estimate(sc.estimate["id"], analyst))
        assert first["status"] == "SUPERSEDED"
        assert second["status"] == "CERTIFIED"
        assert second["elasticity_coefficient"] == -1.9901
        assert second["confidence"] == "HIGH"

    def test_submitting_against_the_superseded_estimate_is_refused(self, api, analyst):
        """PRD 3.3: "That second case has teeth — a plan in `DRAFT` or
        `REVISION_REQUESTED` that references a now-superseded estimate can no longer
        be submitted, and the attempt is refused with
        `ERR_ELASTICITY_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_estimate_superseded_by_newer_certification
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )
        fx.certified_estimate(api, sc.item["id"])

        response = api.submit_markdown_plan(sc.plan["id"], {}, analyst)

        validate_error(response, ApiErrorId.ELASTICITY_NOT_CERTIFIED, 409)

    def test_the_refused_submission_leaves_the_plan_and_its_ladder_alone(
        self, api, analyst
    ):
        """PRD 2.7 rule 14: "Estimate certification on plan submission: the
        referenced estimate must be `CERTIFIED` and must belong to the plan's item,
        else `ERR_ELASTICITY_NOT_CERTIFIED` (409)."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_estimate_superseded_by_newer_certification
        """
        sc = fx.planned_scenario(api)
        sc["step1"] = fx.add_rung(
            api, sc.plan["id"], 1, fx.FIRST_RUNG_DATE, fx.FIRST_RUNG_DEPTH_PCT
        )
        fx.certified_estimate(api, sc.item["id"])
        api.submit_markdown_plan(sc.plan["id"], {}, analyst)

        plan = fx.read_plan(api, sc.plan["id"])

        assert plan["status"] == "DRAFT"
        assert plan["elasticity_estimate_id"] == sc.estimate["id"]
        assert plan["ladder_step_count"] == 1
        assert fx.read_step(api, sc.step1["id"])["status"] == "PLANNED"


class TestClaimCreationBlockedWhilePlanOnlyApproved:
    """Nothing has been executed, so there is nothing to claim against."""

    def test_a_merely_approved_plan_is_not_yet_claimable(self, api, analyst):
        """PRD 3.5: "Both `EXECUTING` and `COMPLETED` are claimable against a vendor
        allowance; nothing earlier is." PRD 2.7 rule 13: "Claim eligibility, on both
        vendor-claim creation and recognition: the plan's `plan_type` must be
        `PERMANENT`, else `ERR_PROMO_NOT_CLAIMABLE` (422); the plan's status must be
        `EXECUTING` or `COMPLETED`, else `ERR_PLAN_NOT_CLAIMABLE` (409); and the
        agreement's `vendor_code`, `item_category_scope` and `season_id` must equal
        the plan item's `vendor_code`, the plan item's `category` and the plan's
        `season_id` respectively, else `ERR_ALLOWANCE_SCOPE_MISMATCH` (422)."

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_while_plan_only_approved
        """
        sc = fx.approved_plan_scenario(api)
        agreement = fx.agreed_agreement(
            api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
        )

        response = api.create_vendor_claim(
            vendor_claim_payload(agreement["id"], sc.plan["id"], 10000), analyst
        )

        validate_error(response, ApiErrorId.PLAN_NOT_CLAIMABLE, 409)

    def test_the_refused_claim_leaves_the_plan_money_at_zero(self, api, analyst):
        """PRD 3.5: "A plan's money fields follow from its executions and claims:
        `gross_markdown_cents` is the sum of `line_markdown_cents` over its
        `APPLIED` executions accumulated in `created_at` ascending order,
        `vendor_funded_cents` is the sum of `recognized_cents` over its `RECOGNIZED`
        claims, `net_markdown_cents` is the gross less the vendor-funded amount, and
        `projected_exit_units` is the sum of `units_in_scope` over its executions
        that are `SCHEDULED` or `APPLIED`."

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_while_plan_only_approved
        """
        sc = fx.approved_plan_scenario(api)
        agreement = fx.agreed_agreement(
            api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
        )
        api.create_vendor_claim(
            vendor_claim_payload(agreement["id"], sc.plan["id"], 10000), analyst
        )

        plan = fx.read_plan(api, sc.plan["id"])
        _, meta = validate_paginated(
            api.list_vendor_claims(analyst, {"markdown_plan_id": sc.plan["id"]})
        )

        assert meta["total_count"] == 0
        assert plan["status"] == "APPROVED"
        assert plan["gross_markdown_cents"] == 0
        assert plan["vendor_funded_cents"] == 0
        assert plan["net_markdown_cents"] == 0
        assert fx.read_step(api, sc.step1["id"])["status"] == "PLANNED"

    def test_the_refused_claim_leaves_the_agreement_untouched(self, api, analyst):
        """PRD 3.8: "Acceptance copies `current_share_pct` into `agreed_share_pct`
        and `current_cap_cents` into `funding_cap_cents`, sets `remaining_cap_cents`
        equal to that cap, and leaves `recognized_total_cents` at 0."

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_while_plan_only_approved
        """
        sc = fx.approved_plan_scenario(api)
        agreement = fx.agreed_agreement(
            api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
        )
        api.create_vendor_claim(
            vendor_claim_payload(agreement["id"], sc.plan["id"], 10000), analyst
        )

        after = fx.read_agreement(api, agreement["id"])

        assert after["status"] == "AGREED"
        assert after["remaining_cap_cents"] == 100000
        assert after["recognized_total_cents"] == 0


def _drafted_order_in_an_active_season(api):
    sc = fx.base_scenario(api)
    fx.set_clock(api, "2026-12-05T00:00:00Z")
    sc["order"] = fx.create_disposition(
        api, salvage_order_payload(sc.season["id"], sc.item["id"], 50, 300)
    )
    return sc


class TestDispositionApproveBlockedWhileSeasonActive:
    """The order is eligible; the season it belongs to is not."""

    def test_approval_is_refused_while_the_season_is_merely_active(
        self, api, controller
    ):
        """PRD 3.9: "Approval and settlement both belong to the `Controller`, and
        both are exit-window operations: the season must be in `EXIT_WINDOW`, and an
        attempt while it is merely `ACTIVE` is refused with
        `ERR_SEASON_NOT_IN_EXIT_WINDOW`."

        Design: Difficulty/cross_entity_state_dependency/disposition_approve_blocked_while_season_still_active
        """
        sc = _drafted_order_in_an_active_season(api)

        response = api.approve_disposition_order(sc.order["id"], {}, controller)

        validate_error(response, ApiErrorId.SEASON_NOT_IN_EXIT_WINDOW, 409)
        assert fx.read_season(api, sc.season["id"])["status"] == "ACTIVE"

    def test_the_refused_order_stays_in_draft_with_no_approver(
        self, api, controller
    ):
        """PRD 3.9: "A drafted order stamps `created_by_user_id` from `X-User-ID`,
        leaves `approved_by_user_id` null, opens in `DRAFT` with `settled_units` and
        `settled_recovery_cents` at 0, computes and stores
        `projected_recovery_cents`, adds its `units` to the item's
        `units_committed_disposition` — so the item's uncommitted pool shrinks
        immediately, even before anything ships — and increments the item's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/disposition_approve_blocked_while_season_still_active
        """
        sc = _drafted_order_in_an_active_season(api)
        api.approve_disposition_order(sc.order["id"], {}, controller)

        order = fx.read_disposition(api, sc.order["id"])

        assert order["status"] == "DRAFT"
        assert order["approved_by_user_id"] is None
        assert order["projected_recovery_cents"] == 15000

    def test_the_item_is_disposition_eligible_so_only_the_season_gate_bites(
        self, api, controller
    ):
        """PRD 3.9: "For `SALVAGE`, recovery is simply the unit count multiplied by
        `unit_recovery_cents`."

        Design: Difficulty/cross_entity_state_dependency/disposition_approve_blocked_while_season_still_active
        """
        sc = _drafted_order_in_an_active_season(api)
        api.approve_disposition_order(sc.order["id"], {}, controller)

        item = fx.read_item(api, sc.item["id"])

        assert item["lifecycle_stage"] == "CLEARANCE"
        assert item["units_committed_disposition"] == 50
        assert item["on_hand_units"] == 343

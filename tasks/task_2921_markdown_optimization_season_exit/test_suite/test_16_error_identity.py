"""Error identity: the dedicated code that a dimension owns, the not-found code
that each path segment owns, and the gate that fires ahead of every other.
"""

from test_helpers import NON_EXISTENT_UUID, validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import (
    exit_review_payload,
    post_signage_payload,
    vendor_claim_payload,
)
from test_helpers.test_users import make_store_manager_headers


class TestSignageHasItsOwnRepeatGuard:
    """The signage dimension does not fall back on the generic state error."""

    def test_a_second_posting_is_refused_without_overwriting_the_first(self, api, analyst):
        """PRD 3.6: "Posting an execution whose `signage_status` is not `PENDING` is
        refused with `ERR_SIGNAGE_ALREADY_POSTED`."

        Design: Corner/errors/signage_cannot_be_posted_twice_on_one_execution
        """
        sc = fx.scheduled_execution_scenario(api, effective_date="2026-11-16")
        posted = fx.post_signage(api, sc.execution["id"], sc.store_0101["id"])
        assert posted["signage_status"] == "POSTED"
        assert posted["signage_due_date"] == "2026-11-09"
        assert posted["posted_at"] == "2026-10-10T00:00:00.000Z"

        fx.set_clock(api, "2026-10-12T00:00:00Z")
        response = api.post_signage(
            sc.execution["id"],
            post_signage_payload(),
            make_store_manager_headers(sc.store_0101["id"]),
        )
        validate_error(response, "ERR_SIGNAGE_ALREADY_POSTED", 409)

        unchanged = fx.read_execution(api, sc.execution["id"])
        assert unchanged["signage_status"] == "POSTED"
        assert unchanged["posted_at"] == "2026-10-10T00:00:00.000Z"
        assert unchanged["posted_by_user_id"] == sc.store_0101["id"]
        assert unchanged["verified_by_user_id"] is None
        assert unchanged["status"] == "SCHEDULED"

    def test_the_refused_repeat_leaves_the_dimension_usable(self, api, director):
        """PRD 3.6: "Verification is a `MerchandiseDirector` responsibility for every
        scope, including chain-wide ones: it moves the dimension `POSTED → VERIFIED` and
        stamps `verified_by_user_id`, and attempting it on an execution that is not
        `POSTED` — still `PENDING`, already `VERIFIED`, or `NON_COMPLIANT` — is refused
        with `ERR_SIGNAGE_NOT_POSTED`."

        Design: Corner/errors/signage_cannot_be_posted_twice_on_one_execution
        """
        sc = fx.scheduled_execution_scenario(api, effective_date="2026-11-16")
        fx.post_signage(api, sc.execution["id"], sc.store_0101["id"])
        fx.set_clock(api, "2026-10-12T00:00:00Z")
        validate_error(
            api.post_signage(
                sc.execution["id"],
                post_signage_payload(),
                make_store_manager_headers(sc.store_0101["id"]),
            ),
            "ERR_SIGNAGE_ALREADY_POSTED",
            409,
        )

        verified = fx.verify_signage(api, sc.execution["id"])
        assert verified["signage_status"] == "VERIFIED"
        assert verified["verified_by_user_id"] is not None
        assert verified["status"] == "SCHEDULED"


class TestEveryPathIdOwnsItsNotFoundCode:
    """Nine unknown identifiers, nine distinct codes."""

    def test_each_unknown_single_resource_reports_its_own_code(self, api, analyst):
        """PRD 2.5: "Each maps to its own not-found code: `ERR_SEASON_NOT_FOUND`,
        `ERR_ITEM_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_STEP_NOT_FOUND`,
        `ERR_ZONE_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`,
        `ERR_EXECUTION_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and
        `ERR_DISPOSITION_NOT_FOUND`, all at HTTP 404."

        Design: Corner/errors/unknown_path_ids_return_their_own_not_found_errors
        """
        sc = fx.base_scenario(api)

        reads = [
            (api.get_price_zone, "ERR_ZONE_NOT_FOUND"),
            (api.get_store, "ERR_STORE_NOT_FOUND"),
            (api.get_markdown_step, "ERR_STEP_NOT_FOUND"),
            (api.get_zone_execution, "ERR_EXECUTION_NOT_FOUND"),
            (api.get_clearance_reservation, "ERR_RESERVATION_NOT_FOUND"),
            (api.get_allowance_agreement, "ERR_AGREEMENT_NOT_FOUND"),
            (api.get_vendor_claim, "ERR_CLAIM_NOT_FOUND"),
            (api.get_disposition_order, "ERR_DISPOSITION_NOT_FOUND"),
        ]
        for read, error_id in reads:
            response = read(NON_EXISTENT_UUID, analyst)
            validate_error(response, error_id, 404)
            assert response.json()["data"]["message"]

        _rows, meta = validate_paginated(
            api.list_items(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 1

    def test_an_unknown_parent_is_reported_before_the_child_collection(self, api, analyst):
        """PRD 2.5: "Path identifiers are resolved strictly left to right, so the outer
        segment is validated before the inner one and the error reported is always the one
        belonging to the leftmost unresolvable segment."

        Design: Corner/errors/unknown_path_ids_return_their_own_not_found_errors
        """
        fx.base_scenario(api)

        response = api.list_plan_steps(NON_EXISTENT_UUID, analyst)
        validate_error(response, "ERR_PLAN_NOT_FOUND", 404)
        assert response.json()["data"]["message"]


def _promotional_plan_applied(api):
    """An ``EXECUTING`` promotional plan whose 2026-10-19 rung has been applied."""
    sc = fx.planned_scenario(api, plan_type="PROMOTIONAL")
    sc = fx.approved_plan_scenario(api, sc)
    sc = fx.scheduled_execution_scenario(api, sc)
    sc = fx.verified_execution_scenario(api, sc)
    return fx.applied_execution_scenario(api, sc)


class TestPromotionalPlansAreNeverClaimable:
    """The plan-type gate sits ahead of the status and scope gates."""

    def test_a_perfectly_scoped_agreement_cannot_rescue_a_promotional_plan(
        self, api, analyst
    ):
        """PRD 3.8: "Eligibility is checked both when the claim is filed and again when it
        is recognised: the plan's `plan_type` must be `PERMANENT`, because promotional
        contra-revenue is never vendor-funded and a promotional plan is refused with
        `ERR_PROMO_NOT_CLAIMABLE`; the plan's status must be `EXECUTING` or `COMPLETED`,
        else `ERR_PLAN_NOT_CLAIMABLE`; and the agreement's scope must match the claim's
        subject, meaning the agreement's `vendor_code` equals the plan item's
        `vendor_code`, the agreement's `item_category_scope` equals that item's
        `category`, and the agreement's `season_id` equals the plan's `season_id`, else
        `ERR_ALLOWANCE_SCOPE_MISMATCH`."

        Design: Corner/errors/promotional_plans_are_never_claimable
        """
        sc = _promotional_plan_applied(api)
        agreement = fx.agreed_agreement(api, sc.season["id"])
        assert sc.plan["status"] == "COMPLETED"
        assert sc.plan["plan_type"] == "PROMOTIONAL"

        response = api.create_vendor_claim(
            vendor_claim_payload(agreement["id"], sc.plan["id"], 56400), analyst
        )
        validate_error(response, "ERR_PROMO_NOT_CLAIMABLE", 422)

        _rows, meta = validate_paginated(
            api.list_vendor_claims(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 0
        refused_on = fx.read_agreement(api, agreement["id"])
        assert refused_on["status"] == "AGREED"
        assert refused_on["recognized_total_cents"] == 0
        assert refused_on["remaining_cap_cents"] == 100000

    def test_the_promotional_apply_booked_contra_revenue_not_a_reserve(self, api):
        """PRD 3.6: "Under a `PROMOTIONAL` plan whose rung depth is below 50.00 percent, an
        item at `FULL_PRICE` moves `FULL_PRICE → PROMO_ACTIVE`; its `current_retail_cents`
        becomes the rung price, and its `promo_discount_cents` accrues the per-unit
        markdown for every unit sold on or after the execution's `effective_date` —
        contra-revenue, recognised only as the units actually move."

        Design: Corner/errors/promotional_plans_are_never_claimable
        """
        sc = _promotional_plan_applied(api)

        item = fx.read_item(api, sc.item["id"])
        assert item["markdown_state"] == "PROMO_ACTIVE"
        assert item["current_retail_cents"] == 3871
        assert item["permanent_markdown_reserve_cents"] == 0
        assert item["promo_discount_cents"] == 0

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["gross_markdown_cents"] == 225600
        assert plan["vendor_funded_cents"] == 0


class TestPreliminaryReviewNeedsALiveSeason:
    """The season-status gate is checked before the scorecard is computed."""

    def test_a_planning_season_cannot_be_scored(self, api, director):
        """PRD 2.7: "Season status: the governing season must be `ACTIVE` or `EXIT_WINDOW`
        to create or submit or approve a plan, to schedule a zone execution, to allocate
        clearance space, to create a vendor claim and to generate a `PRELIMINARY` exit
        review — otherwise `ERR_SEASON_NOT_ACTIVE` (409)."

        Design: Corner/errors/preliminary_review_on_a_planning_season_is_rejected
        """
        fx.base_scenario(api)
        planning = fx.create_season(
            api, code="SS27-FOOTWEAR", category="FOOTWEAR", exit_units_target=300
        )
        fx.create_item(
            api,
            planning["id"],
            sku="G-7007",
            category="FOOTWEAR",
            cluster_code="CL-W9",
            units_received_total=300,
        )
        assert planning["status"] == "PLANNING"

        response = api.create_exit_review(
            planning["id"], exit_review_payload("PRELIMINARY"), director
        )
        validate_error(response, "ERR_SEASON_NOT_ACTIVE", 409)

        _rows, meta = validate_paginated(
            api.list_season_exit_reviews(planning["id"], director)
        )
        assert meta["total_count"] == 0
        assert fx.read_season(api, planning["id"])["status"] == "PLANNING"

    def test_the_identical_call_scores_the_active_season(self, api, director):
        """PRD 3.9: "The request names only a `review_type`: `PRELIMINARY`, which may be
        generated while the season is `ACTIVE` or `EXIT_WINDOW`, or `FINAL`, which requires
        the season to be in `EXIT_WINDOW`."

        Design: Corner/errors/preliminary_review_on_a_planning_season_is_rejected
        """
        sc = fx.base_scenario(api)
        planning = fx.create_season(
            api, code="SS27-FOOTWEAR", category="FOOTWEAR", exit_units_target=300
        )
        validate_error(
            api.create_exit_review(
                planning["id"], exit_review_payload("PRELIMINARY"), director
            ),
            "ERR_SEASON_NOT_ACTIVE",
            409,
        )

        review = validate_success(
            api.create_exit_review(
                sc.season["id"], exit_review_payload("PRELIMINARY"), director
            ),
            201,
        )

        assert review["review_type"] == "PRELIMINARY"
        assert review["season_id"] == sc.season["id"]
        assert review["generated_at"] == "2026-10-10T00:00:00.000Z"

        _rows, meta = validate_paginated(
            api.list_season_exit_reviews(sc.season["id"], director)
        )
        assert meta["total_count"] == 1

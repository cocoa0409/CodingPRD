"""Endpoint behaviour that the envelope, the candidate set or the governing
status decides, rather than the payload.
"""

from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.assertions import find_by
from test_helpers.factories import (
    clearance_allocation_payload,
    release_payload,
    store_patch_payload,
    vendor_claim_payload,
    zone_execution_payload,
)


class TestClearanceAllocationReturnsAnArray:
    """The only write in the system that answers with a list."""

    def test_the_allocation_answers_with_a_ranked_array_envelope(self, api, analyst):
        """PRD 2.2: "The `data` field contains the resource object or an array of resource
        objects." PRD 3.7 fixes the ranking: "The waterfall then
        walks that order, and for each store in turn takes the smaller of the store's
        `available_clearance_units` and the units still unplaced, creating one reservation
        per filled store with that quantity in `reserved_units`, with `allocation_rank`
        counting 1, 2, 3 and so on in fill order, and with `status` `RESERVED`; the walk
        stops as soon as nothing remains to place."

        Design: Corner/endpoints/clearance_allocation_returns_a_ranked_array_envelope
        """
        sc = fx.approved_plan_scenario(api)
        version = fx.read_season(api, sc.season["id"])["version"]

        response = api.create_clearance_allocation(
            sc.season["id"],
            clearance_allocation_payload(sc.plan["id"], 600, version),
            analyst,
        )
        rows = validate_success(response, 201)

        assert response.json()["response_type"] == "array"
        assert len(rows) == 2
        assert rows[0]["allocation_rank"] == 1
        assert rows[0]["store_id"] == sc.store_0202["id"]
        assert rows[0]["reserved_units"] == 500
        assert rows[1]["allocation_rank"] == 2
        assert rows[1]["store_id"] == sc.store_0101["id"]
        assert rows[1]["reserved_units"] == 100
        for row in rows:
            assert row["status"] == "RESERVED"
            assert row["markdown_plan_id"] == sc.plan["id"]
            assert row["released_at"] is None

    def test_the_two_reservations_are_readable_as_one_collection(self, api, analyst):
        """PRD 3.7: "On success each filled store's `committed_clearance_units` grows by
        its `reserved_units` with `available_clearance_units` recomputed, the season's
        `reserved_clearance_units` grows by `total_units`, and the season's `version` is
        incremented."

        Design: Corner/endpoints/clearance_allocation_returns_a_ranked_array_envelope
        """
        sc = fx.allocated_scenario(api, total_units=600)

        rows, meta = validate_paginated(
            api.list_clearance_reservations(
                analyst, {"season_id": sc.season["id"], "limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert sorted(row["id"] for row in rows) == sorted(
            row["id"] for row in sc.reservations
        )

        season = fx.read_season(api, sc.season["id"])
        assert season["reserved_clearance_units"] == 600
        assert season["committed_clearance_units"] == 0


class TestStoreStatusPatchRewritesTheCandidateSet:
    """A plain field update silently changes who wins the waterfall."""

    def test_the_patch_leaves_the_capacity_untouched(self, api, director):
        """PRD 3.2: "A director may later revise a store's `status` or its
        `clearance_bay_units`; either revision recomputes `available_clearance_units` from
        the new capacity and bumps the store's `version`."

        Design: Corner/endpoints/patch_store_status_to_remodel_removes_it_from_the_waterfall
        """
        sc = fx.approved_plan_scenario(api)

        patched = validate_success(
            api.update_store(
                sc.store_0202["id"], store_patch_payload(status="REMODEL"), director
            )
        )

        assert patched["status"] == "REMODEL"
        assert patched["clearance_bay_units"] == 500
        assert patched["available_clearance_units"] == 500
        assert patched["committed_clearance_units"] == 0

        _rows, meta = validate_paginated(api.list_stores(director, {"status": "OPEN"}))
        assert meta["total_count"] == 1

    def test_the_remodelled_store_is_skipped_by_the_next_allocation(
        self, api, analyst, director
    ):
        """PRD 3.2: "Only `OPEN` stores are candidates for clearance allocation — a store
        in `REMODEL` or `CLOSING` is skipped even when its bays are empty — and a duplicate
        `store_number`, like a duplicate `zone_code`, is refused with
        `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/endpoints/patch_store_status_to_remodel_removes_it_from_the_waterfall
        """
        sc = fx.approved_plan_scenario(api)
        validate_success(
            api.update_store(
                sc.store_0202["id"], store_patch_payload(status="REMODEL"), director
            )
        )

        reservations = fx.allocate_clearance(api, sc.season["id"], sc.plan["id"], 300)

        assert len(reservations) == 1
        assert reservations[0]["store_id"] == sc.store_0101["id"]
        assert reservations[0]["reserved_units"] == 300
        assert reservations[0]["allocation_rank"] == 1

        skipped = fx.read_store(api, sc.store_0202["id"])
        assert skipped["available_clearance_units"] == 500
        assert skipped["committed_clearance_units"] == 0

        filled = fx.read_store(api, sc.store_0101["id"])
        assert filled["available_clearance_units"] == 0
        assert filled["committed_clearance_units"] == 300


class TestReservationReleaseIsNotRepeatable:
    """A release credits exactly its own store, exactly once."""

    def test_the_release_restores_only_its_own_store(self, api, analyst):
        """PRD 3.7: "Either state may be surrendered explicitly by a `PricingAnalyst` or a
        `MerchandiseDirector`, who may supply an optional `release_reason`: `RESERVED →
        RELEASED` and `COMMITTED → RELEASED` both stamp `released_at`, both reduce the
        store's `committed_clearance_units` and restore its `available_clearance_units`, and
        each reduces whichever season counter the reservation was occupying —
        `reserved_clearance_units` for a reservation that was `RESERVED`,
        `committed_clearance_units` for one that was `COMMITTED`."

        Design: Corner/endpoints/reservation_release_restores_capacity_and_is_not_repeatable
        """
        sc = fx.allocated_scenario(api, total_units=600)
        rank_two = find_by(sc.reservations, allocation_rank=2)

        released = fx.release_reservation(
            api, rank_two["id"], release_reason="SPACE_REPLANNED"
        )

        assert released["status"] == "RELEASED"
        assert released["released_at"] == "2026-10-10T00:00:00.000Z"
        assert released["reserved_units"] == 100

        store_0101 = fx.read_store(api, sc.store_0101["id"])
        assert store_0101["available_clearance_units"] == 300
        assert store_0101["committed_clearance_units"] == 0

        rank_one = find_by(sc.reservations, allocation_rank=1)
        assert fx.read_reservation(api, rank_one["id"])["status"] == "RESERVED"
        assert fx.read_store(api, sc.store_0202["id"])["committed_clearance_units"] == 500

        season = fx.read_season(api, sc.season["id"])
        assert season["reserved_clearance_units"] == 500
        assert season["committed_clearance_units"] == 0

    def test_a_second_release_cannot_double_credit_the_store(self, api, analyst):
        """PRD 3.7: "`RELEASED` is terminal, so releasing an already-released reservation
        is refused with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/reservation_release_restores_capacity_and_is_not_repeatable
        """
        sc = fx.allocated_scenario(api, total_units=600)
        rank_two = find_by(sc.reservations, allocation_rank=2)
        fx.release_reservation(api, rank_two["id"], release_reason="SPACE_REPLANNED")

        response = api.release_clearance_reservation(
            rank_two["id"], release_payload("SPACE_REPLANNED"), analyst
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        assert fx.read_store(api, sc.store_0101["id"])["available_clearance_units"] == 300
        assert fx.read_reservation(api, rank_two["id"])["status"] == "RELEASED"


class TestVendorClaimScopeTriple:
    """A claim is filed against an agreement, but its subject is the plan's item."""

    def test_a_category_or_vendor_mismatch_refuses_the_claim(self, api, analyst):
        """PRD 3.8: "Eligibility is checked both when the claim is filed and again when it
        is recognised: the plan's `plan_type` must be `PERMANENT`, because promotional
        contra-revenue is never vendor-funded and a promotional plan is refused with
        `ERR_PROMO_NOT_CLAIMABLE`; the plan's status must be `EXECUTING` or `COMPLETED`,
        else `ERR_PLAN_NOT_CLAIMABLE`; and the agreement's scope must match the claim's
        subject, meaning the agreement's `vendor_code` equals the plan item's
        `vendor_code`, the agreement's `item_category_scope` equals that item's
        `category`, and the agreement's `season_id` equals the plan's `season_id`, else
        `ERR_ALLOWANCE_SCOPE_MISMATCH`."

        Design: Corner/endpoints/vendor_claim_requires_a_vendor_category_and_season_matched_agreement
        """
        sc = fx.applied_execution_scenario(api)
        wrong_category = fx.agreed_agreement(
            api, sc.season["id"], item_category_scope="FOOTWEAR"
        )
        wrong_vendor = fx.agreed_agreement(api, sc.season["id"], vendor_code="VN-999")

        for agreement in (wrong_category, wrong_vendor):
            response = api.create_vendor_claim(
                vendor_claim_payload(agreement["id"], sc.plan["id"], 56400), analyst
            )
            validate_error(response, "ERR_ALLOWANCE_SCOPE_MISMATCH", 422)
            assert fx.list_claims_of_agreement(api, agreement["id"]) == []

        assert fx.read_plan(api, sc.plan["id"])["vendor_funded_cents"] == 0

    def test_a_fully_matched_agreement_accepts_the_claim(self, api, analyst):
        """PRD 3.8: "It names the `allowance_agreement_id`, the `markdown_plan_id` whose
        applied markdown is being claimed and a `claimed_cents` amount of at least one
        cent, and it opens in `SUBMITTED` with `recognized_cents` at 0,
        `recognized_by_user_id` and `rejection_reason` null."

        Design: Corner/endpoints/vendor_claim_requires_a_vendor_category_and_season_matched_agreement
        """
        sc = fx.executing_plan_with_agreement(api)

        claim = validate_success(
            api.create_vendor_claim(
                vendor_claim_payload(sc.agreement["id"], sc.plan["id"], 56400), analyst
            ),
            201,
        )

        assert claim["status"] == "SUBMITTED"
        assert claim["claimed_cents"] == 56400
        assert claim["recognized_cents"] == 0
        assert claim["recognized_by_user_id"] is None
        assert claim["rejection_reason"] is None

        siblings = fx.list_claims_of_agreement(api, sc.agreement["id"])
        assert len(siblings) == 1
        assert siblings[0]["id"] == claim["id"]

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["gross_markdown_cents"] == 225600
        assert plan["vendor_funded_cents"] == 0
        assert plan["net_markdown_cents"] == 225600


class TestZoneExecutionNeedsAnApprovedPlan:
    """The identical scheduling payload is refused and then accepted, on the
    strength of the plan's status alone.
    """

    def test_a_submitted_plan_cannot_be_scheduled(self, api, analyst):
        """PRD 3.6: "Scheduling requires the plan to be `APPROVED` or `EXECUTING` —
        anything else is refused with `ERR_PLAN_NOT_APPROVED` — and the season to be
        `ACTIVE` or `EXIT_WINDOW`."

        Design: Corner/endpoints/zone_execution_creation_is_conditional_on_plan_approval
        """
        sc = fx.planned_scenario(api)
        step1 = fx.add_rung(api, sc.plan["id"], 1, "2026-10-19", 22.57)
        submitted = fx.submit_plan(api, sc.plan["id"])
        assert submitted["status"] == "SUBMITTED"

        response = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], step1["id"], sc.west_zone["id"], "ZONE", "2026-10-19", 200
            ),
            analyst,
        )
        validate_error(response, "ERR_PLAN_NOT_APPROVED", 409)

        _rows, meta = validate_paginated(
            api.list_zone_executions(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 0
        assert fx.read_step(api, step1["id"])["status"] == "PLANNED"
        assert fx.read_plan(api, sc.plan["id"])["projected_exit_units"] == 0

    def test_the_same_payload_succeeds_once_the_plan_is_approved(self, api, analyst):
        """PRD 3.6: "The new execution opens with `status` `SCHEDULED` and
        `signage_status` `PENDING`, computes its `signage_due_date` as the
        `effective_date` less the zone's `signage_lead_days`, leaves
        `per_unit_markdown_cents`, `line_markdown_cents` and `price_cents_applied` at 0
        and `applied_at`, `posted_at`, `posted_by_user_id` and `verified_by_user_id` null,
        moves the referenced rung `PLANNED → SCHEDULED`, adds its `units_in_scope` to the
        plan's `projected_exit_units`, and bumps the plan's `version`."

        Design: Corner/endpoints/zone_execution_creation_is_conditional_on_plan_approval
        """
        sc = fx.planned_scenario(api)
        step1 = fx.add_rung(api, sc.plan["id"], 1, "2026-10-19", 22.57)
        fx.submit_plan(api, sc.plan["id"])
        api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], step1["id"], sc.west_zone["id"], "ZONE", "2026-10-19", 200
            ),
            analyst,
        )
        approved = fx.approve_plan(api, sc.plan["id"])
        assert approved["status"] == "APPROVED"

        execution = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"], step1["id"], sc.west_zone["id"], "ZONE", "2026-10-19", 200
                ),
                analyst,
            ),
            201,
        )

        assert execution["status"] == "SCHEDULED"
        assert execution["signage_status"] == "PENDING"
        assert execution["signage_due_date"] == "2026-10-12"
        assert execution["per_unit_markdown_cents"] == 0
        assert execution["line_markdown_cents"] == 0
        assert execution["price_cents_applied"] == 0
        assert execution["applied_at"] is None
        assert execution["posted_at"] is None

        assert fx.read_step(api, step1["id"])["status"] == "SCHEDULED"
        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["projected_exit_units"] == 200
        assert plan["version"] > approved["version"]

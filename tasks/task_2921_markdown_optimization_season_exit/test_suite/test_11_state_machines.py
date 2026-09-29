"""Declared state machines: where each row opens, which transitions a state
declares, and what a legal transition drags along behind it.
"""

from test_helpers import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.assertions import find_by
from test_helpers.factories import (
    allowance_agreement_payload,
    apply_payload,
    elasticity_estimate_payload,
    markdown_plan_payload,
    markdown_step_payload,
    post_signage_payload,
    season_transition_payload,
    submit_payload,
    verify_signage_payload,
)
from test_helpers.test_users import (
    ANALYST_ONE_ID,
    DIRECTOR_ONE_ID,
    make_store_manager_headers,
)


class TestInitialStates:
    """Four machines open in four different declared states."""

    def test_each_create_in_the_chain_opens_in_its_own_declared_state(
        self, api, analyst
    ):
        """PRD 3.4 opens the estimate: "The estimate that comes back records which
        path actually ran in `resolved_method` — always either `OWN_HISTORY` or
        `CLUSTER_POOLED`, never `AUTO` — together with the `elasticity_coefficient`
        itself, the `sample_weeks_used`, the `peer_items_used`, a `confidence` of
        `HIGH` or `LOW`, the `estimated_at` instant taken from the logical clock, a
        null `certified_at`, and a status of `DRAFT`." PRD 3.5 opens the plan: "On
        creation the plan stamps `created_by_user_id` from `X-User-ID`, leaves
        `approved_by_user_id` null, opens in `DRAFT` with `revision_round` 0 and
        `ladder_step_count` 0, computes and stores `recommended_depth_pct`, and
        increments the item's `version`." Its ledger starts empty because "A plan's
        money fields follow from its executions and claims: `gross_markdown_cents`
        is the sum of `line_markdown_cents` over its `APPLIED` executions
        accumulated in `created_at` ascending order, `vendor_funded_cents` is the
        sum of `recognized_cents` over its `RECOGNIZED` claims, `net_markdown_cents`
        is the gross less the vendor-funded amount, and `projected_exit_units` is
        the sum of `units_in_scope` over its executions that are `SCHEDULED` or
        `APPLIED`."

        Design: Corner/state_machines/initial_states_of_the_registration_chain
        """
        sc = fx.base_scenario(api)

        estimate = validate_success(
            api.create_elasticity_estimate(
                elasticity_estimate_payload(sc.item["id"]), analyst
            ),
            201,
        )
        assert estimate["status"] == "DRAFT"
        assert estimate["estimated_at"] == "2026-10-10T00:00:00.000Z"
        assert estimate["certified_at"] is None

        item = fx.read_item(api, sc.item["id"])
        plan = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )
        assert plan["status"] == "DRAFT"
        assert plan["revision_round"] == 0
        assert plan["ladder_step_count"] == 0
        assert plan["created_by_user_id"] == ANALYST_ONE_ID
        assert plan["approved_by_user_id"] is None
        assert plan["gross_markdown_cents"] == 0
        assert plan["vendor_funded_cents"] == 0
        assert plan["net_markdown_cents"] == 0
        assert plan["projected_exit_units"] == 0

    def test_a_first_rung_opens_planned_and_tiles_to_the_plan_target(
        self, api, analyst
    ):
        """PRD 3.5: "Each new rung also fixes the ladder's occupancy calendar: a
        rung's `window_end_date_exclusive` is set to the plan's `exit_date_target`
        when it is the last rung, and appending a further rung rewrites the previous
        rung's `window_end_date_exclusive` to the new rung's `effective_date`, so
        the rungs tile the plan's calendar as half-open windows." And: "Appending a
        rung increments the plan's `ladder_step_count`, recomputes the plan's
        `projected_exit_units`, and bumps the plan's `version`. Rungs open in
        `PLANNED`." The price follows from "Depth is always measured off the
        original ticket, never off the live one, so the rung's `price_cents` is the
        item's `original_retail_cents` less the discount, where the discount is
        `original_retail_cents` multiplied by `depth_pct` divided by 100 and rounded
        half up to a whole cent before the subtraction."

        Design: Corner/state_machines/initial_states_of_the_registration_chain
        """
        sc = fx.planned_scenario(api)
        assert sc.plan["ladder_step_count"] == 0

        step = validate_success(
            api.create_markdown_step(
                sc.plan["id"], markdown_step_payload(1, "2026-10-19", 22.57), analyst
            ),
            201,
        )

        assert step["status"] == "PLANNED"
        assert step["price_cents"] == 3871
        assert step["window_end_date_exclusive"] == "2027-01-15"
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 1

    def test_the_opening_allowance_offer_commits_nothing(self, api, analyst):
        """PRD 3.8: "The agreement opens in `PROPOSED` with `round_index` at 1,
        `last_offer_by_role` set to `PricingAnalyst` and `last_offer_by_user_id`
        taken from `X-User-ID`, while `agreed_share_pct`, `funding_cap_cents` and
        `remaining_cap_cents` all stay null and `recognized_total_cents` sits at 0 —
        nothing is committed until an offer is accepted."

        Design: Corner/state_machines/initial_states_of_the_registration_chain
        """
        sc = fx.base_scenario(api)

        agreement = validate_success(
            api.create_allowance_agreement(
                allowance_agreement_payload(sc.season["id"]), analyst
            ),
            201,
        )

        assert agreement["status"] == "PROPOSED"
        assert agreement["round_index"] == 1
        assert agreement["last_offer_by_role"] == "PricingAnalyst"
        assert agreement["last_offer_by_user_id"] == ANALYST_ONE_ID
        assert agreement["agreed_share_pct"] is None
        assert agreement["funding_cap_cents"] is None
        assert agreement["remaining_cap_cents"] is None
        assert agreement["recognized_total_cents"] == 0


class TestSubmitIsNotIdempotent:
    """`SUBMITTED` declares no submit edge of its own."""

    def test_a_second_submit_on_a_submitted_plan_is_refused(self, api, analyst):
        """PRD 3.5: "Submitting requires that the plan is in `DRAFT`, that the season
        is `ACTIVE` or `EXIT_WINDOW`, that the ladder holds at least one rung — an
        empty ladder is refused with `ERR_EMPTY_LADDER` — that the referenced
        estimate is still `CERTIFIED` and still belongs to the plan's item, and that
        the item's `lifecycle_stage` is one of the three markdown-eligible stages."
        And: "Submission recomputes the plan's `projected_exit_units` from its
        scheduled executions, which is 0 while none exist, and moves the plan
        `DRAFT → SUBMITTED`." PRD 2.7 rule 8 decides the repeat: "A transition
        requested from a state that does not declare it yields `ERR_INVALID_STATE`
        (409)".

        Design: Corner/state_machines/second_submit_on_a_submitted_plan_returns_invalid_state
        """
        sc = fx.planned_scenario(api)
        step = fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)
        submitted = fx.submit_plan(api, sc.plan["id"])
        assert submitted["status"] == "SUBMITTED"

        response = api.submit_markdown_plan(sc.plan["id"], submit_payload(), analyst)
        validate_error(response, "ERR_INVALID_STATE", 409)

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["status"] == "SUBMITTED"
        assert plan["revision_round"] == 0
        assert plan["approved_by_user_id"] is None
        assert fx.read_step(api, step["id"])["status"] == "PLANNED"


class TestClosedSeasonIsTerminalTwice:
    """A closed season refuses a transition at rule 8 and a business write at
    rule 9, with two different codes."""

    def test_reviving_a_closed_season_is_an_illegal_transition(self, api, director):
        """PRD 3.1: "Any `to_status` that the season's current status does not
        declare — jumping `PLANNING` straight to `EXIT_WINDOW`, or reviving a
        `CLOSED` season — is refused with `ERR_INVALID_STATE`, and each transition
        increments the season's `version` by 1." Its own lifecycle is the ladder
        being exhausted: "The season's own lifecycle runs `PLANNING → ACTIVE →
        EXIT_WINDOW → CLOSED`, and the director drives it by naming a `to_status`."

        Design: Corner/state_machines/closed_season_rejects_transition_and_further_writes
        """
        sc = fx.certified_scenario(api)
        fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
        fx.generate_review(api, sc.season["id"], "FINAL")
        closed = fx.transition_season(api, sc.season["id"], "CLOSED")
        assert closed["status"] == "CLOSED"

        response = api.transition_season(
            sc.season["id"], season_transition_payload("ACTIVE"), director
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        assert fx.read_season(api, sc.season["id"])["status"] == "CLOSED"
        reviews, meta = validate_paginated(
            api.list_exit_reviews(director, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 1
        assert reviews[0]["review_type"] == "FINAL"

    def test_a_business_write_against_a_closed_season_reports_the_closed_code(
        self, api, analyst
    ):
        """PRD 2.7 rule 9: "A season whose status is `CLOSED` accepts no write at
        all, including another exit review, and rejects with `ERR_SEASON_CLOSED`
        (409)." PRD 3.9 closes the same loop: "After that, the season is read-only:
        any further write reports `ERR_SEASON_CLOSED`."

        Design: Corner/state_machines/closed_season_rejects_transition_and_further_writes
        """
        sc = fx.certified_scenario(api)
        fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
        fx.generate_review(api, sc.season["id"], "FINAL")
        fx.transition_season(api, sc.season["id"], "CLOSED")

        item = fx.read_item(api, sc.item["id"])
        response = api.create_markdown_plan(
            markdown_plan_payload(
                sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
            ),
            analyst,
        )
        validate_error(response, "ERR_SEASON_CLOSED", 409)

        _plans, meta = validate_paginated(
            api.list_markdown_plans(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 0


def _closable_season_with_live_reservations(api):
    """An ACTIVE season holding 600 units of reserved clearance space across two
    stores, plus an allowance offer still sitting on the table.
    """
    sc = fx.allocated_scenario(api)
    sc["agreement"] = fx.create_agreement(api, sc.season["id"])
    fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
    fx.generate_review(api, sc.season["id"], "FINAL")
    sc["season"] = fx.transition_season(api, sc.season["id"], "CLOSED")
    return sc


class TestSeasonCloseFansOut:
    """Closing the season is a fan-out write, not a status flip."""

    def test_closing_releases_every_live_reservation_back_to_its_store(
        self, api, analyst
    ):
        """PRD 3.1: "Closing then sweeps up everything left open — every allowance
        agreement of the season still in `PROPOSED` or `COUNTERED` moves to
        `EXPIRED`; every claim still in `SUBMITTED` against an agreement that just
        expired moves to `REJECTED` with its `rejection_reason` set to
        `AGREEMENT_EXPIRED`; and every clearance reservation of the season still in
        `RESERVED` or `COMMITTED` moves to `RELEASED`, giving each store's
        `available_clearance_units` back." PRD 3.7 fixes what a release does:
        "`RESERVED → RELEASED` and `COMMITTED → RELEASED` both stamp `released_at`,
        both reduce the store's `committed_clearance_units` and restore its
        `available_clearance_units`, and each reduces whichever season counter the
        reservation was occupying — `reserved_clearance_units` for a reservation that
        was `RESERVED`, `committed_clearance_units` for one that was `COMMITTED`."

        Design: Corner/state_machines/season_close_releases_reservations_and_expires_agreements
        """
        sc = _closable_season_with_live_reservations(api)

        first = find_by(sc.reservations, allocation_rank=1)
        second = find_by(sc.reservations, allocation_rank=2)
        assert first["store_id"] == sc.store_0202["id"]
        assert second["store_id"] == sc.store_0101["id"]

        released_first = fx.read_reservation(api, first["id"])
        released_second = fx.read_reservation(api, second["id"])

        assert released_first["status"] == "RELEASED"
        assert released_first["released_at"] is not None
        assert released_first["reserved_units"] == 500
        assert released_second["status"] == "RELEASED"
        assert released_second["released_at"] is not None
        assert released_second["reserved_units"] == 100

        season = fx.read_season(api, sc.season["id"])
        assert season["status"] == "CLOSED"
        assert season["reserved_clearance_units"] == 0
        assert season["committed_clearance_units"] == 0

        rows, meta = validate_paginated(
            api.list_clearance_reservations(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["RELEASED", "RELEASED"]

    def test_the_released_space_returns_to_both_stores_exactly(self, api):
        """PRD 2.9: "a store's `clearance_bay_units` always equals its
        `available_clearance_units` plus the sum of `reserved_units` across its
        `RESERVED` and `COMMITTED` reservations, so releasing a reservation gives the
        space back exactly." PRD 3.1 says the same from the store's side:
        "Thereafter `committed_clearance_units` is maintained as the sum of
        `reserved_units` across the store's reservations that are `RESERVED` or
        `COMMITTED`, and `available_clearance_units` is always the bay capacity less
        that committed sum."

        Design: Corner/state_machines/season_close_releases_reservations_and_expires_agreements
        """
        sc = _closable_season_with_live_reservations(api)

        store_0202 = fx.read_store(api, sc.store_0202["id"])
        store_0101 = fx.read_store(api, sc.store_0101["id"])

        assert store_0202["committed_clearance_units"] == 0
        assert store_0202["available_clearance_units"] == 500
        assert store_0202["clearance_bay_units"] == 500
        assert store_0101["committed_clearance_units"] == 0
        assert store_0101["available_clearance_units"] == 300
        assert store_0101["clearance_bay_units"] == 300

    def test_the_offer_still_on_the_table_expires_in_the_same_request(self, api):
        """PRD 3.8: "The other way an agreement ends is by expiry. When a season is
        closed, every agreement of that season still in `PROPOSED` or `COUNTERED`
        moves to `EXPIRED`, and every claim still in `SUBMITTED` against one of those
        agreements moves to `REJECTED` with `rejection_reason` set to
        `AGREEMENT_EXPIRED`." Nothing was ever frozen on it, because "Acceptance
        copies `current_share_pct` into `agreed_share_pct` and `current_cap_cents`
        into `funding_cap_cents`, sets `remaining_cap_cents` equal to that cap, and
        leaves `recognized_total_cents` at 0."

        Design: Corner/state_machines/season_close_releases_reservations_and_expires_agreements
        """
        sc = _closable_season_with_live_reservations(api)

        agreement = fx.read_agreement(api, sc.agreement["id"])

        assert agreement["status"] == "EXPIRED"
        assert agreement["agreed_share_pct"] is None
        assert agreement["funding_cap_cents"] is None
        assert agreement["recognized_total_cents"] == 0


class TestSignageHandshakeUnlocksApply:
    """The signage dimension is a two-actor handshake and the apply gate."""

    def test_posting_in_time_stamps_the_store_manager_and_verification_the_director(
        self, api, director
    ):
        """PRD 3.6: "The new execution opens with `status` `SCHEDULED` and
        `signage_status` `PENDING`, computes its `signage_due_date` as the
        `effective_date` less the zone's `signage_lead_days`, leaves
        `per_unit_markdown_cents`, `line_markdown_cents` and `price_cents_applied` at
        0 and `applied_at`, `posted_at`, `posted_by_user_id` and
        `verified_by_user_id` null, moves the referenced rung `PLANNED → SCHEDULED`,
        adds its `units_in_scope` to the plan's `projected_exit_units`, and bumps the
        plan's `version`." Then: "A `StoreManager` records that the signage is
        physically up; for a store-scope execution the acting `X-User-ID` must equal
        the execution's `store_id`, while chain-scope and zone-scope executions carry
        no `store_id` and may be posted by any store manager." And: "If the logical
        clock's current date is on or before the `signage_due_date`, the dimension
        moves `PENDING → POSTED`." Verification is the other half: "Verification is a
        `MerchandiseDirector` responsibility for every scope, including chain-wide
        ones: it moves the dimension `POSTED → VERIFIED` and stamps
        `verified_by_user_id`, and attempting it on an execution that is not
        `POSTED` — still `PENDING`, already `VERIFIED`, or `NON_COMPLIANT` — is
        refused with `ERR_SIGNAGE_NOT_POSTED`."

        Design: Corner/state_machines/signage_post_then_verify_stamps_actors_and_unlocks_apply
        """
        sc = fx.scheduled_execution_scenario(api)

        assert sc.execution["signage_due_date"] == "2026-10-12"
        assert sc.execution["signage_status"] == "PENDING"
        assert sc.execution["posted_at"] is None

        posted = validate_success(
            api.post_signage(
                sc.execution["id"],
                post_signage_payload(),
                make_store_manager_headers(sc.store_0101["id"]),
            )
        )
        assert posted["signage_status"] == "POSTED"
        assert posted["posted_at"] == "2026-10-10T00:00:00.000Z"
        assert posted["posted_by_user_id"] == sc.store_0101["id"]

        verified = validate_success(
            api.verify_signage(sc.execution["id"], verify_signage_payload(), director)
        )
        assert verified["signage_status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == DIRECTOR_ONE_ID

    def test_only_a_verified_execution_stamps_applied_at_and_the_money_fields(
        self, api, analyst
    ):
        """PRD 3.6: "The apply itself computes the markdown liability line and
        freezes it: `per_unit_markdown_cents` is the item's `current_retail_cents`
        less the rung's `price_cents`, `line_markdown_cents` is that per-unit amount
        multiplied by `units_in_scope`, and `price_cents_applied` records the rung
        price written onto the item. The execution moves `SCHEDULED → APPLIED` with
        `applied_at` stamped from the logical clock, and then five hops run in order.
        Hop one rewrites the item's `current_retail_cents` to the rung's `price_cents`
        and moves the rung `SCHEDULED → EXECUTED`."

        Design: Corner/state_machines/signage_post_then_verify_stamps_actors_and_unlocks_apply
        """
        sc = fx.verified_execution_scenario(api)
        fx.set_clock(api, "2026-10-19T00:00:00Z")

        applied = validate_success(
            api.apply_zone_execution(sc.execution["id"], apply_payload(), analyst)
        )

        assert applied["status"] == "APPLIED"
        assert applied["applied_at"] == "2026-10-19T00:00:00.000Z"
        assert applied["per_unit_markdown_cents"] == 1128
        assert applied["line_markdown_cents"] == 225600
        assert applied["price_cents_applied"] == 3871

        assert fx.read_item(api, sc.item["id"])["current_retail_cents"] == 3871
        assert fx.read_step(api, sc.step1["id"])["status"] == "EXECUTED"


class TestApplyWaitsForTheEffectiveDate:
    """Everything else is ready, so only the date check is left to fail."""

    def test_applying_early_is_refused_and_leaves_no_side_effect(self, api, analyst):
        """PRD 2.7 rule 8: "Preconditions of the declared transition that have no
        dedicated code further down this ladder are reported here as
        `ERR_INVALID_STATE` too — notably applying an execution before its
        `effective_date` has arrived, applying an execution whose rung price is not
        strictly below the item's `current_retail_cents`, and rolling back an
        execution while a `RECOGNIZED` vendor claim still references its plan." PRD
        3.6 lists the same precondition among the others: "Apply requires the
        execution to be `SCHEDULED`, its `signage_status` to be `VERIFIED` —
        `PENDING`, `POSTED` and `NON_COMPLIANT` all block with
        `ERR_SIGNAGE_NOT_VERIFIED` — the plan to be `APPROVED` or `EXECUTING`, the
        item's `markdown_state` to be `FULL_PRICE`, `PROMO_ACTIVE` or `PERM_MARKED`,
        the clock's current date to have reached the execution's `effective_date`, the
        `units_in_scope` not to exceed the item's on-hand units, and the rung's
        `price_cents` to sit strictly below the item's `current_retail_cents`."

        Design: Corner/state_machines/apply_before_the_execution_effective_date_returns_invalid_state
        """
        sc = fx.verified_execution_scenario(api, effective_date="2026-11-16")

        response = api.apply_zone_execution(
            sc.execution["id"], apply_payload(), analyst
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        execution = fx.read_execution(api, sc.execution["id"])
        assert execution["status"] == "SCHEDULED"
        assert execution["signage_status"] == "VERIFIED"
        assert execution["line_markdown_cents"] == 0
        assert execution["applied_at"] is None

        assert fx.read_item(api, sc.item["id"])["current_retail_cents"] == 4999
        assert fx.read_plan(api, sc.plan["id"])["status"] == "APPROVED"

    def test_advancing_the_clock_alone_lets_the_same_apply_through(self, api, analyst):
        """PRD 3.6: "The last two of those preconditions and the date check carry no
        dedicated code and are reported as `ERR_INVALID_STATE`; applying an execution
        twice reports the same code, since `SCHEDULED` is the only state that declares
        the transition." Once the date arrives the plan follows: "Alongside the
        cascade, the plan's `gross_markdown_cents` grows by `line_markdown_cents`, its
        `net_markdown_cents` is recomputed, and the plan moves `APPROVED → EXECUTING`
        on its first applied execution."

        Design: Corner/state_machines/apply_before_the_execution_effective_date_returns_invalid_state
        """
        sc = fx.verified_execution_scenario(api, effective_date="2026-11-16")
        validate_error(
            api.apply_zone_execution(sc.execution["id"], apply_payload(), analyst),
            "ERR_INVALID_STATE",
            409,
        )

        fx.set_clock(api, "2026-11-16T00:00:00Z")
        applied = validate_success(
            api.apply_zone_execution(sc.execution["id"], apply_payload(), analyst)
        )

        assert applied["status"] == "APPLIED"
        assert applied["line_markdown_cents"] == 225600

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["gross_markdown_cents"] == 225600


class TestLateSignagePostIsTerminal:
    """Posting after the due date is a legal transition to a dead end."""

    def test_a_late_post_is_recorded_as_non_compliant_rather_than_refused(self, api):
        """PRD 3.6: "If the due date has already passed, the same request instead
        moves it `PENDING → NON_COMPLIANT`: the posting is still recorded —
        `posted_at` and `posted_by_user_id` are stamped in both cases — but
        `NON_COMPLIANT` is terminal on this dimension." The due date itself is
        derived at scheduling time: "The new execution opens with `status`
        `SCHEDULED` and `signage_status` `PENDING`, computes its `signage_due_date`
        as the `effective_date` less the zone's `signage_lead_days`, leaves
        `per_unit_markdown_cents`, `line_markdown_cents` and `price_cents_applied` at
        0 and `applied_at`, `posted_at`, `posted_by_user_id` and
        `verified_by_user_id` null, moves the referenced rung `PLANNED → SCHEDULED`,
        adds its `units_in_scope` to the plan's `projected_exit_units`, and bumps the
        plan's `version`."

        Design: Corner/state_machines/late_signage_post_lands_non_compliant_and_blocks_apply
        """
        sc = fx.scheduled_execution_scenario(api, effective_date="2026-11-16")
        assert sc.execution["signage_due_date"] == "2026-11-09"

        fx.set_clock(api, "2026-11-10T00:00:00Z")
        posted = validate_success(
            api.post_signage(
                sc.execution["id"],
                post_signage_payload(),
                make_store_manager_headers(sc.store_0101["id"]),
            )
        )

        assert posted["signage_status"] == "NON_COMPLIANT"
        assert posted["posted_at"] == "2026-11-10T00:00:00.000Z"
        assert posted["posted_by_user_id"] == sc.store_0101["id"]
        assert posted["status"] == "SCHEDULED"

    def test_a_non_compliant_execution_can_never_be_verified_or_applied(
        self, api, analyst, director
    ):
        """PRD 3.6: "Such an execution can never be verified and can never be
        applied, and the analyst's only remedy is to schedule a fresh execution."
        Verification refuses first, because "attempting it on an execution that is not
        `POSTED` — still `PENDING`, already `VERIFIED`, or `NON_COMPLIANT` — is
        refused with `ERR_SIGNAGE_NOT_POSTED`." Apply refuses at PRD 2.7 rule 21:
        "Signage compliance at apply time: `signage_status` must be `VERIFIED`;
        `PENDING`, `POSTED` and `NON_COMPLIANT` all block the apply with
        `ERR_SIGNAGE_NOT_VERIFIED` (409)."

        Design: Corner/state_machines/late_signage_post_lands_non_compliant_and_blocks_apply
        """
        sc = fx.scheduled_execution_scenario(api, effective_date="2026-11-16")
        fx.set_clock(api, "2026-11-10T00:00:00Z")
        fx.post_signage(api, sc.execution["id"], sc.store_0101["id"])

        validate_error(
            api.verify_signage(sc.execution["id"], verify_signage_payload(), director),
            "ERR_SIGNAGE_NOT_POSTED",
            409,
        )

        fx.set_clock(api, "2026-11-16T00:00:00Z")
        validate_error(
            api.apply_zone_execution(sc.execution["id"], apply_payload(), analyst),
            "ERR_SIGNAGE_NOT_VERIFIED",
            409,
        )

        execution = fx.read_execution(api, sc.execution["id"])
        assert execution["status"] == "SCHEDULED"
        assert execution["signage_status"] == "NON_COMPLIANT"
        assert execution["line_markdown_cents"] == 0
        assert execution["verified_by_user_id"] is None

        assert fx.read_item(api, sc.item["id"])["current_retail_cents"] == 4999
        assert fx.read_step(api, sc.step1["id"])["status"] == "SCHEDULED"

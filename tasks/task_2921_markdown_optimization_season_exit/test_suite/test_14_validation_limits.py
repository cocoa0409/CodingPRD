"""Declared validations that count: aggregate ceilings, round ceilings, and the
gates that only open once a companion field is present.
"""

import pytest

from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import (
    accept_payload,
    certify_payload,
    counter_payload,
    donation_order_payload,
    jobber_order_payload,
    markdown_plan_payload,
    reopen_payload,
    salvage_order_payload,
    submit_payload,
    zone_execution_payload,
)
from test_helpers.test_users import VENDOR_REP_ONE_ID


class TestDispositionChannelCoherence:
    """The channel decides which money field is required and which is forbidden."""

    def test_four_incoherent_payloads_share_one_error(self, api, analyst):
        """PRD 3.9: "Salvage and jobber both recover cash per unit and therefore require
        `unit_recovery_cents` of at least one cent while forbidding `fmv_cents` entirely;
        a donation recovers a tax credit rather than cash, and therefore requires
        `fmv_cents` of at least one cent — the fair market value per unit — while
        forbidding any non-zero `unit_recovery_cents`." And: "A payload that mixes the two
        shapes, or omits the money field its channel needs, is refused with
        `ERR_DISPOSITION_CHANNEL_MISMATCH`."

        Design: Corner/validations/disposition_channel_payload_coherence_is_enforced_both_ways
        """
        sc = fx.applied_execution_scenario(api)

        # "omits the money field its channel needs" -- the key is absent, not null.
        salvage_no_money = salvage_order_payload(
            sc.season["id"], sc.item["id"], 50, 300
        )
        del salvage_no_money["unit_recovery_cents"]
        salvage_without_recovery = api.create_disposition_order(
            salvage_no_money, analyst
        )
        validate_error(
            salvage_without_recovery, "ERR_DISPOSITION_CHANNEL_MISMATCH", 422
        )

        jobber_with_fmv = api.create_disposition_order(
            jobber_order_payload(
                sc.season["id"], sc.item["id"], 50, 500, fmv_cents=1000
            ),
            analyst,
        )
        validate_error(jobber_with_fmv, "ERR_DISPOSITION_CHANNEL_MISMATCH", 422)

        donation_no_money = donation_order_payload(
            sc.season["id"], sc.item["id"], 50, 1000
        )
        del donation_no_money["fmv_cents"]
        donation_without_fmv = api.create_disposition_order(donation_no_money, analyst)
        validate_error(donation_without_fmv, "ERR_DISPOSITION_CHANNEL_MISMATCH", 422)

        donation_with_cash = api.create_disposition_order(
            donation_order_payload(
                sc.season["id"], sc.item["id"], 50, 1000, unit_recovery_cents=300
            ),
            analyst,
        )
        validate_error(donation_with_cash, "ERR_DISPOSITION_CHANNEL_MISMATCH", 422)

        _rows, meta = validate_paginated(
            api.list_disposition_orders(analyst, {"item_id": sc.item["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_coherent_jobber_payload_is_accepted(self, api, analyst):
        """PRD 3.9: "For `JOBBER`, the same product is reduced by an eight percent freight
        deduction — that is, multiplied by 92 and divided by 100 — and rounded half up to a
        whole cent." And: "A drafted order stamps `created_by_user_id` from `X-User-ID`,
        leaves `approved_by_user_id` null, opens in `DRAFT` with `settled_units` and
        `settled_recovery_cents` at 0, computes and stores `projected_recovery_cents`, adds
        its `units` to the item's `units_committed_disposition` — so the item's uncommitted
        pool shrinks immediately, even before anything ships — and increments the item's
        `version`."

        Design: Corner/validations/disposition_channel_payload_coherence_is_enforced_both_ways
        """
        sc = fx.applied_execution_scenario(api)

        order = validate_success(
            api.create_disposition_order(
                jobber_order_payload(sc.season["id"], sc.item["id"], 50, 500), analyst
            ),
            201,
        )

        assert order["channel"] == "JOBBER"
        assert order["projected_recovery_cents"] == 23000
        assert order["fmv_cents"] is None
        assert order["status"] == "DRAFT"
        assert order["approved_by_user_id"] is None

        assert fx.read_item(api, sc.item["id"])["units_committed_disposition"] == 50
        _rows, meta = validate_paginated(
            api.list_disposition_orders(analyst, {"item_id": sc.item["id"]})
        )
        assert meta["total_count"] == 1


def _plan_with_two_far_apart_rungs(api):
    """An APPROVED plan whose rungs sit 28 days apart, on 2026-11-16 and
    2026-12-14, with the clock still at 2026-10-10T00:00:00Z.
    """
    sc = fx.planned_scenario(api)
    sc["step1"] = fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)
    sc["step2"] = fx.add_rung(api, sc.plan["id"], 2, "2026-12-14", 35.00)
    fx.submit_plan(api, sc.plan["id"])
    sc["plan"] = fx.approve_plan(api, sc.plan["id"])
    return sc


class TestUnitsInScopeAggregate:
    """The on-hand ceiling is an aggregate over the item's other executions."""

    def test_two_individually_legal_executions_together_exceed_the_stock(
        self, api, analyst
    ):
        """PRD 3.6: "Finally, the physical inventory has to exist: the new execution's
        `units_in_scope` plus the `units_in_scope` of the item's other `SCHEDULED` and
        `APPLIED` executions may not exceed the item's on-hand units, else
        `ERR_ZONE_UNITS_EXCEED_ON_HAND`." PRD 2.7 rule 28 pins its status: "Units in scope
        on execution scheduling, reported as `ERR_ZONE_UNITS_EXCEED_ON_HAND` (409)."

        Design: Corner/validations/scheduled_units_aggregate_against_item_on_hand_units
        """
        sc = _plan_with_two_far_apart_rungs(api)
        assert fx.read_item(api, sc.item["id"])["on_hand_units"] == 343

        fx.schedule_execution(
            api,
            sc.plan["id"],
            sc.step1["id"],
            sc.west_zone["id"],
            "ZONE",
            "2026-11-16",
            200,
        )

        response = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"],
                sc.step2["id"],
                sc.west_zone["id"],
                "ZONE",
                "2026-12-14",
                150,
            ),
            analyst,
        )
        validate_error(response, "ERR_ZONE_UNITS_EXCEED_ON_HAND", 409)

        _rows, meta = validate_paginated(
            api.list_zone_executions(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 1

    def test_the_aggregate_ceiling_is_not_strict(self, api, analyst):
        """PRD 3.6: "Finally, the physical inventory has to exist: the new execution's
        `units_in_scope` plus the `units_in_scope` of the item's other `SCHEDULED` and
        `APPLIED` executions may not exceed the item's on-hand units, else
        `ERR_ZONE_UNITS_EXCEED_ON_HAND`." Scheduling moves no stock: "The item's
        `on_hand_units` is always its `units_received_total` less `units_sold_total` and
        less `units_disposed_total`, and it is never written directly."

        Design: Corner/validations/scheduled_units_aggregate_against_item_on_hand_units
        """
        sc = _plan_with_two_far_apart_rungs(api)
        first = fx.schedule_execution(
            api,
            sc.plan["id"],
            sc.step1["id"],
            sc.west_zone["id"],
            "ZONE",
            "2026-11-16",
            200,
        )

        second = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"],
                    sc.step2["id"],
                    sc.west_zone["id"],
                    "ZONE",
                    "2026-12-14",
                    143,
                ),
                analyst,
            ),
            201,
        )

        assert first["status"] == "SCHEDULED"
        assert second["status"] == "SCHEDULED"
        assert fx.read_plan(api, sc.plan["id"])["projected_exit_units"] == 343
        assert fx.read_item(api, sc.item["id"])["on_hand_units"] == 343


def _high_and_low_confidence_estimates(api):
    """Item ``A-1001`` holds a certified HIGH own-history estimate; sibling
    ``F-6006`` never moved its ticket, so its AUTO estimate is pooled and LOW.
    """
    sc = fx.base_scenario(api)
    sc["estimate_a"] = fx.create_estimate(api, sc.item["id"])
    sc["estimate_a"] = fx.certify_estimate(api, sc.estimate_a["id"])
    item_f = fx.create_item(
        api,
        sc.season["id"],
        sku="F-6006",
        original_retail_cents=3999,
        unit_cost_cents=1500,
        units_received_total=200,
    )
    fx.post_history(
        api,
        item_f["id"],
        [
            ("2026-09-05", 20, 3999),
            ("2026-09-12", 20, 3999),
            ("2026-09-19", 20, 3999),
            ("2026-09-26", 20, 3999),
        ],
    )
    fx.set_clock(api, "2026-10-10T00:00:00Z")
    sc["item_f"] = item_f
    sc["estimate_f"] = fx.create_estimate(api, item_f["id"])
    return sc


class TestConfidenceGateOnCertification:
    """The gate reads the estimate's own confidence, not the caller's intent."""

    def test_a_low_confidence_estimate_is_refused_without_the_acknowledgement(
        self, api, analyst
    ):
        """PRD 3.4: "A certification request applies only to an estimate still in `DRAFT` —
        attempting it on one already `CERTIFIED` or `SUPERSEDED` is refused with
        `ERR_INVALID_STATE` — and it requires either that the estimate's `confidence` is
        `HIGH` or that the request carries `override_low_confidence` set to true." And: "A
        low-confidence estimate certified without that acknowledgement is refused with
        `ERR_LOW_CONFIDENCE_NOT_OVERRIDDEN`."

        Design: Corner/validations/low_confidence_certification_requires_the_explicit_override
        """
        sc = _high_and_low_confidence_estimates(api)

        assert sc.estimate_a["confidence"] == "HIGH"
        assert sc.estimate_a["status"] == "CERTIFIED"
        assert sc.estimate_f["confidence"] == "LOW"
        assert sc.estimate_f["resolved_method"] == "CLUSTER_POOLED"

        response = api.certify_elasticity_estimate(
            sc.estimate_f["id"], certify_payload(), analyst
        )
        validate_error(response, "ERR_LOW_CONFIDENCE_NOT_OVERRIDDEN", 422)

        refused = validate_success(
            api.get_elasticity_estimate(sc.estimate_f["id"], analyst)
        )
        assert refused["status"] == "DRAFT"
        assert refused["certified_at"] is None

    def test_the_same_call_carrying_the_override_certifies(self, api, analyst, director):
        """PRD 3.4: "Certification moves the estimate `DRAFT → CERTIFIED`, stamps
        `certified_at` from the logical clock, and then supersedes the field: every other
        estimate of the same item whose status is `DRAFT` or `CERTIFIED` moves to
        `SUPERSEDED`, whether it was a stale draft (which simply becomes uncertifiable) or
        the previously certified figure."

        Design: Corner/validations/low_confidence_certification_requires_the_explicit_override
        """
        sc = _high_and_low_confidence_estimates(api)

        certified = validate_success(
            api.certify_elasticity_estimate(
                sc.estimate_f["id"],
                certify_payload(override_low_confidence=True),
                director,
            )
        )

        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"] == "2026-10-10T00:00:00.000Z"

        untouched = validate_success(
            api.get_elasticity_estimate(sc.estimate_a["id"], analyst)
        )
        assert untouched["status"] == "CERTIFIED"


class TestNegotiationRoundCeiling:
    """The ceiling counts rounds, and the create already occupies round 1."""

    def test_the_fourth_counter_is_refused(self, api, analyst, vendor_rep):
        """PRD 3.8: "A counter carries `share_pct` and `cap_cents`, which overwrite
        `current_share_pct` and `current_cap_cents`, increments `round_index` by 1, and
        records the countering party in `last_offer_by_role` and `last_offer_by_user_id`."
        And: "It cannot pass back and forth forever: a counter is permitted only while
        `round_index` is still below 4, and once four offers have been placed the next
        counter is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Corner/validations/fifth_counter_offer_is_refused_after_four_negotiation_rounds
        """
        sc = fx.base_scenario(api)
        agreement = fx.create_agreement(
            api, sc.season["id"], current_share_pct=20.00, current_cap_cents=80000
        )

        round_two = fx.counter_agreement(api, agreement["id"], 15.00, 60000)
        assert round_two["status"] == "COUNTERED"
        assert round_two["round_index"] == 2

        round_three = fx.counter_agreement(
            api, agreement["id"], 28.00, 120000, headers=fx.ANALYST_HEADERS
        )
        assert round_three["status"] == "PROPOSED"
        assert round_three["round_index"] == 3

        round_four = fx.counter_agreement(api, agreement["id"], 25.00, 100000)
        assert round_four["status"] == "COUNTERED"
        assert round_four["round_index"] == 4

        response = api.counter_allowance_agreement(
            agreement["id"], counter_payload(26.00, 110000), analyst
        )
        validate_error(response, "ERR_NEGOTIATION_ROUNDS_EXHAUSTED", 409)

        stalled = fx.read_agreement(api, agreement["id"])
        assert stalled["current_share_pct"] == pytest.approx(25.00, abs=0.001)
        assert stalled["current_cap_cents"] == 100000
        assert stalled["last_offer_by_role"] == "VendorRep"
        assert stalled["last_offer_by_user_id"] == VENDOR_REP_ONE_ID

    def test_the_exhausted_table_is_still_acceptable_by_the_other_party(
        self, api, analyst
    ):
        """PRD 3.8: "A `VendorRep` accepts an agreement in `PROPOSED`, moving it
        `PROPOSED → AGREED`; a `PricingAnalyst` accepts one in `COUNTERED`, moving it
        `COUNTERED → AGREED`." And: "Acceptance copies `current_share_pct` into
        `agreed_share_pct` and `current_cap_cents` into `funding_cap_cents`, sets
        `remaining_cap_cents` equal to that cap, and leaves `recognized_total_cents` at 0."

        Design: Corner/validations/fifth_counter_offer_is_refused_after_four_negotiation_rounds
        """
        sc = fx.base_scenario(api)
        agreement = fx.create_agreement(
            api, sc.season["id"], current_share_pct=20.00, current_cap_cents=80000
        )
        fx.counter_agreement(api, agreement["id"], 15.00, 60000)
        fx.counter_agreement(
            api, agreement["id"], 28.00, 120000, headers=fx.ANALYST_HEADERS
        )
        fx.counter_agreement(api, agreement["id"], 25.00, 100000)

        agreed = validate_success(
            api.accept_allowance_agreement(agreement["id"], accept_payload(), analyst)
        )

        assert agreed["status"] == "AGREED"
        assert agreed["agreed_share_pct"] == pytest.approx(25.00, abs=0.001)
        assert agreed["funding_cap_cents"] == 100000
        assert agreed["remaining_cap_cents"] == 100000
        assert agreed["recognized_total_cents"] == 0
        assert agreed["round_index"] == 4


def _revision_cycle(api, plan_id):
    """Author rung 1, submit, and have the director send the plan back."""
    fx.add_rung(api, plan_id, 1, "2026-11-16", 22.57)
    fx.submit_plan(api, plan_id)
    return fx.request_revision(api, plan_id)


class TestRevisionRoundCeiling:
    """Three reopens are legal and the fourth is refused."""

    def test_the_fourth_reopen_is_refused(self, api, analyst):
        """PRD 3.5: "A reopen is permitted while `revision_round` is at most 3; once it has
        gone beyond that the plan is out of revisions and the attempt is refused with
        `ERR_REVISION_ROUNDS_EXHAUSTED`." And: "A director may send a submitted plan back
        by supplying a `revision_reason`, which moves it `SUBMITTED → REVISION_REQUESTED`
        and increments `revision_round` by 1."

        Design: Corner/validations/fourth_reopen_is_refused_after_three_revision_rounds
        """
        sc = fx.planned_scenario(api)

        for expected_round in (1, 2, 3):
            sent_back = _revision_cycle(api, sc.plan["id"])
            assert sent_back["status"] == "REVISION_REQUESTED"
            assert sent_back["revision_round"] == expected_round

            reopened = fx.reopen_plan(api, sc.plan["id"], clear_ladder=True)
            assert reopened["status"] == "DRAFT"
            assert reopened["ladder_step_count"] == 0

        fourth = _revision_cycle(api, sc.plan["id"])
        assert fourth["revision_round"] == 4

        response = api.reopen_markdown_plan(
            sc.plan["id"], reopen_payload(clear_ladder=True), analyst
        )
        validate_error(response, "ERR_REVISION_ROUNDS_EXHAUSTED", 409)

    def test_every_cleared_rung_is_superseded_and_the_last_one_survives(
        self, api, analyst
    ):
        """PRD 3.5: "The analyst then reopens it, moving it `REVISION_REQUESTED → DRAFT`;
        the reopen request may carry `clear_ladder`, and when that flag is true every rung
        of the plan still in `PLANNED` moves to `SUPERSEDED` and `ladder_step_count` resets
        to 0, so the analyst re-authors the ladder from `step_index` 1."

        Design: Corner/validations/fourth_reopen_is_refused_after_three_revision_rounds
        """
        sc = fx.planned_scenario(api)
        for _cycle in range(3):
            _revision_cycle(api, sc.plan["id"])
            fx.reopen_plan(api, sc.plan["id"], clear_ladder=True)
        _revision_cycle(api, sc.plan["id"])

        validate_error(
            api.reopen_markdown_plan(
                sc.plan["id"], reopen_payload(clear_ladder=True), analyst
            ),
            "ERR_REVISION_ROUNDS_EXHAUSTED",
            409,
        )

        stranded = fx.read_plan(api, sc.plan["id"])
        assert stranded["status"] == "REVISION_REQUESTED"
        assert stranded["revision_round"] == 4
        assert stranded["ladder_step_count"] == 1

        _rows, meta = validate_paginated(
            api.list_markdown_steps(
                analyst,
                {"markdown_plan_id": sc.plan["id"], "status": "SUPERSEDED"},
            )
        )
        assert meta["total_count"] == 3


class TestSupersedeStopsAtTheFirstApply:
    """The block depends on a child execution's status, not the plan's own."""

    def test_a_second_plan_is_refused_once_an_execution_has_applied(self, api, analyst):
        """PRD 3.5: "One earlier plan cannot be swept away like this: if any execution of
        the prior plan has already reached `APPLIED`, the ticket has physically moved in a
        store and the create is refused outright with `ERR_PLAN_ALREADY_EXECUTING`." PRD
        2.7 rule 12 pins the shape: "Supersede safety on plan creation: a new plan may
        supersede the prior plan for the same season and item only while no execution of
        that prior plan has reached `APPLIED`, else `ERR_PLAN_ALREADY_EXECUTING` (409)."

        Design: Corner/validations/a_plan_with_an_applied_execution_can_no_longer_be_superseded
        """
        sc = fx.applied_execution_scenario(api)
        item = fx.read_item(api, sc.item["id"])

        response = api.create_markdown_plan(
            markdown_plan_payload(
                sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
            ),
            analyst,
        )
        validate_error(response, "ERR_PLAN_ALREADY_EXECUTING", 409)

    def test_the_refused_create_left_the_executing_plan_alone(self, api, analyst):
        """PRD 3.5: "The first execution of an approved plan to reach `APPLIED` carries the
        plan `APPROVED → EXECUTING` and recomputes `gross_markdown_cents` and
        `net_markdown_cents` from its applied executions."

        Design: Corner/validations/a_plan_with_an_applied_execution_can_no_longer_be_superseded
        """
        sc = fx.applied_execution_scenario(api)
        item = fx.read_item(api, sc.item["id"])
        validate_error(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            "ERR_PLAN_ALREADY_EXECUTING",
            409,
        )

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["superseded_by_plan_id"] is None
        assert plan["gross_markdown_cents"] == 225600

        _rows, meta = validate_paginated(
            api.list_markdown_plans(analyst, {"item_id": sc.item["id"]})
        )
        assert meta["total_count"] == 1
        assert fx.read_item(api, sc.item["id"])["current_retail_cents"] == 3871


class TestEmptyLadderIsTheLastSubmitGate:
    """Everything else about the plan is already legal."""

    def test_a_plan_with_no_rungs_cannot_be_submitted(self, api, analyst):
        """PRD 3.5: "Submitting requires that the plan is in `DRAFT`, that the season is
        `ACTIVE` or `EXIT_WINDOW`, that the ladder holds at least one rung — an empty ladder
        is refused with `ERR_EMPTY_LADDER` — that the referenced estimate is still
        `CERTIFIED` and still belongs to the plan's item, and that the item's
        `lifecycle_stage` is one of the three markdown-eligible stages."

        Design: Corner/validations/submit_with_an_empty_ladder_is_refused_then_accepted_with_one_rung
        """
        sc = fx.planned_scenario(api)
        assert sc.plan["ladder_step_count"] == 0

        response = api.submit_markdown_plan(sc.plan["id"], submit_payload(), analyst)
        validate_error(response, "ERR_EMPTY_LADDER", 409)

        assert fx.read_plan(api, sc.plan["id"])["status"] == "DRAFT"

    def test_the_identical_submit_succeeds_once_one_rung_exists(self, api, analyst):
        """PRD 3.5: "Submission recomputes the plan's `projected_exit_units` from its
        scheduled executions, which is 0 while none exist, and moves the plan `DRAFT →
        SUBMITTED`."

        Design: Corner/validations/submit_with_an_empty_ladder_is_refused_then_accepted_with_one_rung
        """
        sc = fx.planned_scenario(api)
        validate_error(
            api.submit_markdown_plan(sc.plan["id"], submit_payload(), analyst),
            "ERR_EMPTY_LADDER",
            409,
        )

        rung = fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)
        submitted = validate_success(
            api.submit_markdown_plan(sc.plan["id"], submit_payload(), analyst)
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_round"] == 0
        assert submitted["projected_exit_units"] == 0
        assert fx.read_step(api, rung["id"])["status"] == "PLANNED"

"""Nothing in this service settles late: one write, then one read, and the books balance.

Two write paths carry the whole domain's fan-out. Allocation reconciles a drop's aggregates
and the plan's ledger inside the request that spends the budget, and mailing runs a
five-hop cascade that reaches a segment's fatigue score, its contact strategy, a line on a
*different* drop, that drop's repricing and the plan's ledger — all before the mail response
is written. Every assertion below is made against the *first* read taken after the write,
and the last test repeats all five reads to show that no value is order-dependent.
"""
from test_helpers import (
    ANALYST,
    BROKER,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    PLANNER_2,
    add_contact_events,
    allocate,
    approve_plan,
    cost_plan,
    fetch_drop,
    fetch_line,
    fetch_plan,
    iso_utc,
    mail_drop,
    new_drop,
    new_housefile_line,
    new_plan,
    new_presort_batch,
    new_season,
    new_segment,
    presort_drop,
    run_merge_purge,
    set_clock,
    submit_plan,
    timestamps_equal,
    validate_paginated,
    validate_success,
)

# rfm_score 1000 -> BEST -> PREMIUM_FULL, and 30000 names to draw from.
HOT_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}
# 30 + 22 + 22 points -> rfm_score 740 -> CORE -> STANDARD, so it ranks below S_HOT.
COLD_SCORING = {
    "recency_days": 150,
    "orders_12mo": 3,
    "ltv_cents": 25000,
    "housefile_count": 15000,
    "avg_order_value_cents": 9000,
    "historical_response_rate_bps": 150,
}

FIRST_IN_HOME = iso_utc("2026-09-15")
SECOND_IN_HOME = iso_utc("2026-10-20")
MAIL_CLOCK = iso_utc("2026-09-16")
# Three MAIL touches in the 7500-bps decay band: 30 points apiece, 90 in total, one
# cascade contact short of the season's 100-point suppression threshold.
PRIMING_TOUCHES = [
    (iso_utc("2026-08-20"), "MAIL"),
    (iso_utc("2026-08-25"), "MAIL"),
    (iso_utc("2026-08-30"), "MAIL"),
]

BUDGET_CENTS = 20000000
COST_PER_BOOK_ESTIMATED = 236
HOT_LINE_COMMITTED_CENTS = 4720000
COLD_LINE_COMMITTED_CENTS = 2360000


def _two_drops_over_one_fatigue_primed_segment() -> dict:
    """An approved plan whose drop 1 is presorted and ready to mail, and whose drop 2 is
    still `PLANNED` carrying both an S_HOT line and an S_COLD line. Mailing drop 1 will
    therefore push S_HOT over the threshold and reach a line the mailing never touched."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    hot = new_segment(season["id"], segment_code="S_HOT", **HOT_SCORING)
    cold = new_segment(season["id"], segment_code="S_COLD", **COLD_SCORING)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=BUDGET_CENTS)
    run_merge_purge(plan["id"], headers=BROKER)

    first = new_drop(
        plan["id"], drop_number=1, in_home_date=FIRST_IN_HOME, page_count=64
    )
    second = new_drop(
        plan["id"], drop_number=2, in_home_date=SECOND_IN_HOME, page_count=64
    )
    committed_line = new_housefile_line(first["id"], hot["id"], requested_quantity=20000)
    doomed_line = new_housefile_line(second["id"], hot["id"], requested_quantity=20000)
    spared_line = new_housefile_line(second["id"], cold["id"], requested_quantity=10000)

    first = allocate(first["id"])
    allocated_second = allocate(second["id"])

    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan.
    first = fetch_drop(first["id"])
    new_presort_batch(first["id"], first["planned_quantity"], "FIVE_DIGIT")

    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_2)
    approve_plan(plan["id"], DIRECTOR_9)

    first = presort_drop(first["id"])

    set_clock(MAIL_CLOCK)
    add_contact_events(hot["id"], PRIMING_TOUCHES)
    return {
        "season": season,
        "hot": hot,
        "cold": cold,
        "plan": fetch_plan(plan["id"]),
        "mailing_drop": first,
        "planned_drop": fetch_drop(second["id"]),
        "allocate_response": allocated_second,
        "committed_line": fetch_line(committed_line["id"]),
        "doomed_line": fetch_line(doomed_line["id"]),
        "spared_line": fetch_line(spared_line["id"]),
    }


def _the_five_reads(api, world) -> tuple:
    """The segment, the second drop's lines, the plan, the second drop and the first drop,
    read in that order and returned verbatim."""
    segment = validate_success(api.get_segment(world["hot"]["id"], ANALYST), 200)
    lines, _ = validate_paginated(
        api.list_lines(PLANNER, params={"drop_id": world["planned_drop"]["id"]})
    )
    plan = validate_success(api.get_plan(world["plan"]["id"], PLANNER), 200)
    planned_drop = validate_success(
        api.get_drop(world["planned_drop"]["id"], PLANNER), 200
    )
    mailing_drop = validate_success(
        api.get_drop(world["mailing_drop"]["id"], PLANNER), 200
    )
    return segment, lines, plan, planned_drop, mailing_drop


class TestTheAllocateResponseIsAlreadyReconciled:
    def test_the_waterfall_returns_the_drop_with_its_aggregates_already_rederived(
        self, api
    ):
        """PRD §3.5: "Once the waterfall finishes, the consequences fan out inside the same
        request."
        PRD §3.5: "The drop's `planned_quantity` becomes the sum of `allocated_quantity`
        over its `ALLOCATED` lines."
        PRD §3.5: "The drop's cost per book is then re-derived from the new
        `planned_quantity` as described in §3.6, and every allocated line gets its
        **committed view** of demand: `forecast_orders` is the line's `mailable_quantity`
        multiplied by `effective_response_bps`, divided by ten thousand, floored, and
        `forecast_demand_cents` is that order count multiplied by the resolved average order
        value."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        allocated = world["allocate_response"]

        assert allocated["planned_quantity"] == 30000
        assert allocated["cost_per_book_cents"] == COST_PER_BOOK_ESTIMATED
        assert allocated["provisional_cost_per_book_cents"] == COST_PER_BOOK_ESTIMATED
        assert allocated["requested_quantity_total"] == 30000

    def test_the_plan_ledger_is_debited_on_the_very_next_read(self, api):
        """PRD §3.5: "The plan's `committed_cost_cents` grows by the total newly frozen,
        and `uncommitted_budget_cents` is recomputed as `budget_cents` less
        `committed_cost_cents`."
        PRD §3.5: "Once the waterfall finishes, the consequences fan out inside the same
        request."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        plan = validate_success(api.get_plan(world["plan"]["id"], PLANNER), 200)

        expected_committed = (
            HOT_LINE_COMMITTED_CENTS * 2 + COLD_LINE_COMMITTED_CENTS
        )
        assert plan["committed_cost_cents"] == expected_committed
        assert plan["uncommitted_budget_cents"] == BUDGET_CENTS - expected_committed


class TestTheMailResponseCarriesItsOwnStamp:
    def test_the_transition_and_the_instant_come_back_from_the_mail_call_itself(
        self, api
    ):
        """PRD §3.7: "Mailing takes the drop `PRESORTED → MAILED`, requires the drop's
        `in_home_date` to be at or before the logical clock's current value (an earlier
        attempt is rejected with `ERR_INVALID_DROP_STATE`), and stamps `mailed_at` with the
        logical clock's current instant."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()

        mailed = validate_success(
            api.mail_drop(world["mailing_drop"]["id"], PLANNER), 200
        )
        assert mailed["production_status"] == "MAILED"
        assert timestamps_equal(mailed["mailed_at"], MAIL_CLOCK)


class TestHopsTwoAndThreeAreVisibleOnTheFirstSegmentRead:
    def test_the_segment_is_already_scored_and_already_suppressed(self, api):
        """PRD §3.7: "**Hop two.** Because each of those contact event rows now exists, the
        contact-pressure aggregation described in §3.8 is re-run for each affected housefile
        segment, rewriting its `fatigue_score`."
        PRD §3.7: "**Hop three.** Because a recomputed `fatigue_score` may have crossed the
        line, any segment whose `fatigue_score` is now at or above the season's
        `fatigue_suppression_threshold` has its `contact_strategy` forced to `SUPPRESS_ONLY`
        and its `suppressed_at` stamped with the logical clock's current instant."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        before = validate_success(api.get_segment(world["hot"]["id"], ANALYST), 200)
        assert before["fatigue_score"] == 90
        assert before["contact_strategy"] == "PREMIUM_FULL"
        assert before["suppressed_at"] is None

        mail_drop(world["mailing_drop"]["id"])

        after = validate_success(api.get_segment(world["hot"]["id"], ANALYST), 200)
        assert after["fatigue_score"] == 130
        assert after["fatigue_score"] >= 100
        assert after["contact_strategy"] == "SUPPRESS_ONLY"
        assert timestamps_equal(after["suppressed_at"], MAIL_CLOCK)


class TestHopFourIsVisibleOnTheFirstLineRead:
    def test_the_line_on_the_other_drop_is_already_zeroed_and_its_neighbour_is_not(
        self, api
    ):
        """PRD §3.7: "**Hop four.** Because a segment has flipped to `SUPPRESS_ONLY`, every
        circulation line referencing that segment in status `PROPOSED` or `ALLOCATED` whose
        *own* parent drop has `production_status` `PLANNED` transitions to `SUPPRESSED`, with
        `allocated_quantity`, `holdout_quantity`, `mailable_quantity`,
        `forecast_demand_cents`, `gross_margin_cents`, `circulation_cost_cents` and
        `contribution_cents` all set to 0."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        mail_drop(world["mailing_drop"]["id"])

        rows, meta = validate_paginated(
            api.list_lines(PLANNER, params={"drop_id": world["planned_drop"]["id"]})
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}

        doomed = by_id[world["doomed_line"]["id"]]
        assert doomed["status"] == "SUPPRESSED"
        for field in (
            "allocated_quantity",
            "holdout_quantity",
            "mailable_quantity",
            "forecast_demand_cents",
            "gross_margin_cents",
            "circulation_cost_cents",
            "contribution_cents",
        ):
            assert doomed[field] == 0, field

        spared = by_id[world["spared_line"]["id"]]
        assert spared["status"] == "ALLOCATED"
        assert spared["allocated_quantity"] == 10000
        assert spared["committed_cost_cents"] == COLD_LINE_COMMITTED_CENTS
        assert spared["contribution_cents"] == world["spared_line"]["contribution_cents"]

    def test_the_mailed_drops_own_line_is_spared_although_its_segment_is_suppressed(
        self, api
    ):
        """PRD §3.7: "Lines on drops that are already `PRESORTED` or beyond are deliberately
        spared — those books are already committed to production and cannot be recalled."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        mail_drop(world["mailing_drop"]["id"])

        surviving = fetch_line(world["committed_line"]["id"])
        assert surviving["status"] == "ALLOCATED"
        assert surviving["allocated_quantity"] == 20000
        assert surviving["committed_cost_cents"] == HOT_LINE_COMMITTED_CENTS
        assert surviving["mailable_quantity"] == 20000


class TestHopFiveIsVisibleOnTheFirstPlanRead:
    def test_the_budget_credit_needs_no_reconciliation_pass(self, api):
        """PRD §3.7: "**Hop five.** Because each of those lines has left `ALLOCATED`, its
        `committed_cost_cents` is credited back to its plan's `committed_cost_cents` and then
        zeroed on the line, its parent drop's `requested_quantity_total` and
        `planned_quantity` are recomputed, that drop's cost per book is re-run, and the owning
        plan's three roll-up figures plus its `uncommitted_budget_cents` are recomputed —
        with a plan sitting in `COSTED` falling back to `DRAFT`."
        PRD §2.7: "At every observable moment, `budget_cents` equals `committed_cost_cents`
        plus `uncommitted_budget_cents` with no drift whatsoever."
        PRD §2.7: "Every cascade, derived-field recompute and compensating credit in this
        service completes inside the request that triggered it."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        committed_before = world["plan"]["committed_cost_cents"]
        version_before = world["plan"]["version"]
        credited_back = world["doomed_line"]["committed_cost_cents"]
        assert credited_back == HOT_LINE_COMMITTED_CENTS

        mail_drop(world["mailing_drop"]["id"])

        plan = validate_success(api.get_plan(world["plan"]["id"], PLANNER), 200)
        assert plan["committed_cost_cents"] == committed_before - credited_back
        assert plan["committed_cost_cents"] == 7080000
        assert plan["uncommitted_budget_cents"] == (
            BUDGET_CENTS - plan["committed_cost_cents"]
        )
        assert plan["version"] > version_before

    def test_the_credited_line_holds_no_commitment_of_its_own_afterwards(self, api):
        """PRD §3.7: "**Hop five.** Because each of those lines has left `ALLOCATED`, its
        `committed_cost_cents` is credited back to its plan's `committed_cost_cents` and then
        zeroed on the line, its parent drop's `requested_quantity_total` and
        `planned_quantity` are recomputed, that drop's cost per book is re-run, and the owning
        plan's three roll-up figures plus its `uncommitted_budget_cents` are recomputed —
        with a plan sitting in `COSTED` falling back to `DRAFT`."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        mail_drop(world["mailing_drop"]["id"])

        doomed = fetch_line(world["doomed_line"]["id"])
        assert doomed["committed_cost_cents"] == 0
        assert doomed["version"] == world["doomed_line"]["version"] + 1


class TestTheDropThatLostAnAudienceRepricesImmediately:
    def test_the_second_drop_is_already_re_derived_in_the_same_request(self, api):
        """PRD §3.7: "**Hop five.** Because each of those lines has left `ALLOCATED`, its
        `committed_cost_cents` is credited back to its plan's `committed_cost_cents` and then
        zeroed on the line, its parent drop's `requested_quantity_total` and
        `planned_quantity` are recomputed, that drop's cost per book is re-run, and the owning
        plan's three roll-up figures plus its `uncommitted_budget_cents` are recomputed —
        with a plan sitting in `COSTED` falling back to `DRAFT`."
        PRD §3.7: "Each suppressed line's `version` and its parent drop's `version` each
        increment by one."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        before = world["planned_drop"]
        assert before["planned_quantity"] == 30000

        mail_drop(world["mailing_drop"]["id"])

        after = validate_success(api.get_drop(before["id"], PLANNER), 200)
        assert after["planned_quantity"] == 10000
        assert after["requested_quantity_total"] == 10000
        assert after["cost_per_book_cents"] == COST_PER_BOOK_ESTIMATED
        assert after["production_status"] == "PLANNED"
        assert after["version"] == before["version"] + 1


class TestNothingSettlesLate:
    def test_repeating_all_five_reads_returns_identical_values(self, api):
        """PRD §2.7: "There is no read repair, no background reconciliation, and no eventual
        consistency: when a request returns 2xx, every downstream figure it touched has
        already been rewritten."
        PRD §2.7: "Three quantities in this domain are conserved, and the conservation is an
        invariant that must hold before and after every single request rather than something
        reconciled later."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
        """
        world = _two_drops_over_one_fatigue_primed_segment()
        mail_drop(world["mailing_drop"]["id"])

        first_pass = _the_five_reads(api, world)
        second_pass = _the_five_reads(api, world)
        assert first_pass == second_pass

        segment, lines, plan, planned_drop, mailing_drop = second_pass
        assert segment["contact_strategy"] == "SUPPRESS_ONLY"
        assert sorted(row["status"] for row in lines) == ["ALLOCATED", "SUPPRESSED"]
        assert plan["committed_cost_cents"] == 7080000
        assert planned_drop["planned_quantity"] == 10000
        assert mailing_drop["production_status"] == "MAILED"

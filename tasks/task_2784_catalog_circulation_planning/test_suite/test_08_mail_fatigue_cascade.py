"""Mailing one drop, five hops deep.

Each hop is caused by the write the hop before it made: the mail cascade
synthesizes a contact event, the new row lifts the segment's fatigue score
over the season threshold, the crossing forces suppression, the suppression
retires a still-planned line on another drop, and the retirement credits the
plan's budget back.
"""
from test_helpers import (
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    allocate,
    approve_plan,
    assert_circulation_plan,
    assert_contact_event,
    assert_instant_equals,
    assert_line_zeroed,
    assert_plan_budget_conserved,
    cost_plan,
    fetch_drop,
    fetch_line,
    fetch_plan,
    fetch_segment,
    iso_utc,
    mail_drop,
    new_contact_event,
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
    validate_paginated,
)

MAIL_CLOCK = iso_utc("2026-09-20")
DROP_ONE_IN_HOME = iso_utc("2026-09-15")


def _two_drop_world() -> dict:
    """Drop 1 presorted and ready to mail, drop 2 still PLANNED, both carrying
    an allocated line for the same segment, with the segment one mail touch
    short of the suppression threshold."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_PREMIUM")
    plan = new_plan(season["id"], plan_code="P1")
    run_merge_purge(plan["id"])

    drop_one = new_drop(plan["id"], drop_number=1, in_home_date=DROP_ONE_IN_HOME)
    line_one = new_housefile_line(
        drop_one["id"], segment["id"], requested_quantity=20000
    )
    allocate(drop_one["id"])

    drop_two = new_drop(
        plan["id"], drop_number=2, in_home_date=iso_utc("2026-10-20")
    )
    line_two = new_housefile_line(
        drop_two["id"], segment["id"], requested_quantity=5000
    )
    allocate(drop_two["id"])

    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan,
    # so the mail stream is recorded before the plan leaves DRAFT.
    new_presort_batch(drop_one["id"], 20000, "FIVE_DIGIT")

    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_1)
    approve_plan(plan["id"], DIRECTOR_9)

    presort_drop(drop_one["id"])

    set_clock(MAIL_CLOCK)
    new_contact_event(segment["id"], MAIL_CLOCK, "MAIL")
    second_event = new_contact_event(segment["id"], MAIL_CLOCK, "MAIL")

    return {
        "season": season,
        "segment": fetch_segment(segment["id"]),
        "plan": plan,
        "drop_one": drop_one,
        "drop_two": drop_two,
        "line_one": line_one,
        "line_two": line_two,
        "second_event": second_event,
    }


class TestMailCascade:
    def test_mailing_synthesizes_a_contact_event_that_forces_suppression(self, api):
        """PRD §3.7: "For every circulation line of this drop in status
        `ALLOCATED` whose `housefile_segment_id` is non-null, a contact event is
        created carrying that `housefile_segment_id`, this drop's identifier as
        its `drop_id`, a `channel` of `MAIL`, a `contact_date` equal to the drop's
        `in_home_date`, and a `source` of `DROP_MAIL_CASCADE`."

        Design: Difficulty/transitive_cascade/mail_drop_cascades_five_hops_to_plan_budget_via_fatigue_suppression
        """
        world = _two_drop_world()
        assert world["segment"]["fatigue_score"] == 80
        assert world["segment"]["contact_strategy"] == "PREMIUM_FULL"
        assert world["second_event"]["weighted_points"] == 40

        mail_drop(world["drop_one"]["id"])

        events, meta = validate_paginated(
            api.list_segment_contact_events(
                world["segment"]["id"], PLANNER, {"channel": "MAIL"}
            )
        )
        assert meta["total_count"] == 3
        cascade = [row for row in events if row["source"] == "DROP_MAIL_CASCADE"]
        assert len(cascade) == 1
        synthesized = cascade[0]
        assert_contact_event(synthesized)
        assert synthesized["channel"] == "MAIL"
        assert_instant_equals(
            synthesized["contact_date"], DROP_ONE_IN_HOME, "contact_date"
        )
        assert synthesized["drop_id"] == world["drop_one"]["id"]
        assert synthesized["channel_weight"] == 40
        assert synthesized["decay_factor_bps"] == 10000
        assert synthesized["weighted_points"] == 40

        segment = fetch_segment(world["segment"]["id"])
        assert segment["fatigue_score"] == 120
        assert segment["contact_strategy"] == "SUPPRESS_ONLY"
        assert_instant_equals(segment["suppressed_at"], MAIL_CLOCK, "suppressed_at")

    def test_the_suppression_retires_the_planned_line_and_refunds_the_budget(self):
        """PRD §3.7: "every circulation line referencing that segment in status
        `PROPOSED` or `ALLOCATED` whose *own* parent drop has `production_status`
        `PLANNED` transitions to `SUPPRESSED`, with `allocated_quantity`,
        `holdout_quantity`, `mailable_quantity`, `forecast_demand_cents`,
        `gross_margin_cents`, `circulation_cost_cents` and `contribution_cents`
        all set to 0."

        Design: Difficulty/transitive_cascade/mail_drop_cascades_five_hops_to_plan_budget_via_fatigue_suppression
        """
        world = _two_drop_world()
        mailed = mail_drop(world["drop_one"]["id"])

        line_two = fetch_line(world["line_two"]["id"])
        assert line_two["status"] == "SUPPRESSED"
        assert_line_zeroed(line_two)

        line_one = fetch_line(world["line_one"]["id"])
        assert line_one["status"] == "ALLOCATED"

        plan = fetch_plan(world["plan"]["id"])
        assert_circulation_plan(plan)
        assert plan["committed_cost_cents"] == 4720000
        assert plan["uncommitted_budget_cents"] == 15280000
        assert_plan_budget_conserved(plan)
        assert plan["planned_cost_cents"] == 4420000
        assert plan["planned_demand_cents"] == 22940000
        assert plan["planned_contribution_cents"] == 5214800
        assert plan["status"] == "APPROVED"

        drop_two = fetch_drop(world["drop_two"]["id"])
        assert drop_two["requested_quantity_total"] == 0
        assert drop_two["planned_quantity"] == 0
        assert drop_two["cost_per_book_cents"] == 236
        assert drop_two["print_rebate_bps"] == 0
        assert drop_two["production_status"] == "PLANNED"

        assert mailed["production_status"] == "MAILED"
        assert_instant_equals(mailed["mailed_at"], MAIL_CLOCK, "mailed_at")

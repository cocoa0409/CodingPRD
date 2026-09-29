"""Thresholds hit exactly, and thresholds missed by one.

Three different metrics on three different endpoints: the floored automation
share on presort, the control response rate on measurement, and the fatigue
score on contact logging. Each pair holds everything else fixed and moves the
metric across the line by the smallest step the domain allows.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    allocate,
    approve_plan,
    assert_housefile_segment,
    assert_instant_equals,
    assert_postal_presort_batch,
    assert_test_cell,
    cost_plan,
    fetch_line,
    fetch_season,
    fetch_segment,
    fetch_test_cell,
    get_success_data,
    iso_utc,
    mail_drop,
    measure_test_cell_payload,
    new_contact_event,
    new_drop,
    new_housefile_line,
    new_plan,
    new_presort_batch,
    new_season,
    new_segment,
    new_test_cell,
    presort_drop,
    run_merge_purge,
    set_clock,
    submit_plan,
    validate_paginated,
)

MAIL_CLOCK = iso_utc("2026-09-20")


def _two_approved_drops_batched_either_side_of_the_share() -> dict:
    """Two identical 20000-book drops on one approved plan, one batched with
    18000 automation pieces and one with 17999."""
    set_clock(CLOCK_START)
    season = new_season()
    seg_a = new_segment(season["id"], segment_code="S_A")
    seg_b = new_segment(season["id"], segment_code="S_B")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop_a = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line_a = new_housefile_line(drop_a["id"], seg_a["id"], requested_quantity=20000)
    allocate(drop_a["id"])

    drop_b = new_drop(
        plan["id"], drop_number=2, in_home_date=iso_utc("2026-09-16"), page_count=64
    )
    line_b = new_housefile_line(drop_b["id"], seg_b["id"], requested_quantity=20000)
    allocate(drop_b["id"])

    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan,
    # so every batch is laid down before the plan leaves DRAFT.
    batch_a_auto = new_presort_batch(drop_a["id"], 18000, "FIVE_DIGIT")
    batch_a_mixed = new_presort_batch(drop_a["id"], 2000, "MIXED_AADC")
    batch_b_auto = new_presort_batch(drop_b["id"], 17999, "FIVE_DIGIT")
    batch_b_mixed = new_presort_batch(drop_b["id"], 2001, "MIXED_AADC")

    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_1)
    approve_plan(plan["id"], DIRECTOR_9)

    return {
        "season": season,
        "plan": plan,
        "drop_a": drop_a,
        "drop_b": drop_b,
        "line_a": line_a,
        "line_b": line_b,
        "batch_a_auto": batch_a_auto,
        "batch_a_mixed": batch_a_mixed,
        "batch_b_auto": batch_b_auto,
        "batch_b_mixed": batch_b_mixed,
    }


class TestAutomationShareBoundary:
    def test_a_share_of_exactly_nine_thousand_bps_wins_the_whole_discount(self):
        """PRD §3.7: "`automation_qualified` is true exactly when
        `automation_share_bps` is 9000 or greater. The automation discount is
        all-or-nothing at exactly that line: when the drop qualifies, the discount
        is 2 cents for each automation-qualified piece, and when it does not
        qualify the discount is zero."

        Design: Difficulty/boundary_precision_check/automation_share_exactly_nine_thousand_bps_qualifies
        """
        world = _two_approved_drops_batched_either_side_of_the_share()
        assert world["drop_a"]["weight_oz_milli"] == 2560

        automation = world["batch_a_auto"]
        assert_postal_presort_batch(automation)
        assert automation["effective_tier"] == "FIVE_DIGIT"
        assert automation["rate_cents_per_piece"] == 42
        assert automation["weight_surcharge_cents_per_piece"] == 0
        assert automation["batch_postage_cents"] == 756000
        assert automation["is_automation_qualified"] is True

        mixed = world["batch_a_mixed"]
        assert mixed["batch_postage_cents"] == 116000
        assert mixed["is_automation_qualified"] is False

        presorted = presort_drop(world["drop_a"]["id"])
        assert presorted["automation_share_bps"] == 9000
        assert presorted["automation_qualified"] is True
        assert presorted["postage_total_cents"] == 836000
        assert presorted["postage_cents_per_book"] == 42
        assert presorted["cost_per_book_cents"] == 223
        assert presorted["cost_basis"] == "PRESORTED_ACTUAL"
        assert presorted["production_status"] == "PRESORTED"

        line_a = fetch_line(world["line_a"]["id"])
        assert line_a["circulation_cost_cents"] == 4460000
        assert line_a["committed_cost_cents"] == 4720000

    def test_one_automation_piece_short_floors_to_8999_and_forfeits_it(self):
        """PRD §3.7: "`automation_share_bps` is that automation piece count
        multiplied by ten thousand, divided by the drop's `planned_quantity`,
        floored."

        Design: Difficulty/boundary_precision_check/automation_share_exactly_nine_thousand_bps_qualifies
        """
        world = _two_approved_drops_batched_either_side_of_the_share()
        assert world["batch_b_auto"]["batch_postage_cents"] == 755958
        assert world["batch_b_mixed"]["batch_postage_cents"] == 116058

        qualified = presort_drop(world["drop_a"]["id"])
        forfeited = presort_drop(world["drop_b"]["id"])

        assert forfeited["automation_share_bps"] == 8999
        assert forfeited["automation_qualified"] is False
        assert forfeited["postage_total_cents"] == 872016
        assert forfeited["postage_cents_per_book"] == 44
        assert forfeited["cost_per_book_cents"] == 225
        assert forfeited["cost_basis"] == "PRESORTED_ACTUAL"
        assert forfeited["production_status"] == "PRESORTED"

        assert (
            forfeited["postage_total_cents"] - qualified["postage_total_cents"]
            == 36016
        )

        line_b = fetch_line(world["line_b"]["id"])
        assert line_b["circulation_cost_cents"] == 4500000
        assert line_b["committed_cost_cents"] == 4720000


def _mailed_drop_with_a_test_and_a_control_cell() -> dict:
    """A mailed 20000-book drop whose single line carries one TEST and one
    CONTROL cell of 5000 names each, both still PLANNED."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    allocate(drop["id"])

    test_cell = new_test_cell(
        line["id"], 5000, "TEST", cell_code="T_A", test_type="OFFER"
    )
    control_cell = new_test_cell(
        line["id"], 5000, "CONTROL", cell_code="T_C", test_type="OFFER"
    )

    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan,
    # so the mail stream is recorded before the plan leaves DRAFT.
    new_presort_batch(drop["id"], 20000, "FIVE_DIGIT")

    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_1)
    approve_plan(plan["id"], DIRECTOR_9)
    presorted = presort_drop(drop["id"])
    set_clock(MAIL_CLOCK)
    mailed = mail_drop(drop["id"])

    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "drop": mailed,
        "presorted": presorted,
        "line": line,
        "test_cell": test_cell,
        "control_cell": control_cell,
    }


class TestZeroResponderControlBoundary:
    def test_a_test_cell_measured_before_its_control_reports_no_control(self, api):
        """PRD §3.9: "The service looks for the `MEASURED` cell on the same line
        whose `cell_role` is `CONTROL`. If the cell being measured *is* the
        control, or no measured control exists on the line, or the located control
        is the cell itself, then `lift_bps` is 0 and `significance` is
        `INSUFFICIENT_CONTROL`."

        Design: Difficulty/boundary_precision_check/zero_responder_control_cell_yields_insufficient_control
        """
        world = _mailed_drop_with_a_test_and_a_control_cell()
        assert world["test_cell"]["significance"] == "UNMEASURED"
        assert world["presorted"]["cost_per_book_cents"] == 221
        assert world["drop"]["production_status"] == "MAILED"

        measured = get_success_data(
            api.measure_test_cell(
                world["test_cell"]["id"],
                measure_test_cell_payload(190, 3515000),
                ANALYST,
            )
        )
        assert_test_cell(measured)
        assert measured["status"] == "MEASURED"
        assert measured["response_rate_bps"] == 380
        assert measured["lift_bps"] == 0
        assert measured["significance"] == "INSUFFICIENT_CONTROL"
        assert measured["responders"] == 190
        assert measured["demand_cents"] == 3515000

    def test_a_control_that_drew_no_responders_leaves_the_sibling_unliftable(self, api):
        """PRD §3.9: "If a distinct measured control exists but its own
        `response_rate_bps` is 0, lift is undefined — a relative comparison
        against a zero base is neither a finite number nor an infinite one worth
        reporting — so again `lift_bps` is 0 and `significance` is
        `INSUFFICIENT_CONTROL`."

        Design: Difficulty/boundary_precision_check/zero_responder_control_cell_yields_insufficient_control
        """
        world = _mailed_drop_with_a_test_and_a_control_cell()
        test_cell_id = world["test_cell"]["id"]
        control_cell_id = world["control_cell"]["id"]

        get_success_data(
            api.measure_test_cell(
                test_cell_id, measure_test_cell_payload(190, 3515000), ANALYST
            )
        )

        control = get_success_data(
            api.measure_test_cell(
                control_cell_id, measure_test_cell_payload(0, 0), ANALYST
            )
        )
        assert_test_cell(control)
        assert control["response_rate_bps"] == 0
        assert control["lift_bps"] == 0
        assert control["significance"] == "INSUFFICIENT_CONTROL"
        assert control["status"] == "MEASURED"
        assert control["responders"] == 0
        assert control["demand_cents"] == 0

        rescored = fetch_test_cell(test_cell_id)
        assert rescored["lift_bps"] == 0
        assert rescored["significance"] == "INSUFFICIENT_CONTROL"
        assert rescored["significance"] != "SIGNIFICANT"
        assert rescored["significance"] != "NOT_SIGNIFICANT"
        assert rescored["significance"] != "INSUFFICIENT_SAMPLE"
        assert rescored["status"] == "MEASURED"

        cells, meta = validate_paginated(api.list_test_cells(world["line"]["id"], ANALYST))
        assert meta["total_count"] == 2
        assert [row["cell_code"] for row in cells] == ["T_A", "T_C"]


def _two_seasons_either_side_of_the_fatigue_line() -> dict:
    """Two seasons identical but for the suppression threshold — 92 against 93 —
    each holding one BEST segment. The 93-season's segment already carries the
    full three-touch history; the 92-season's segment is one EMAIL short."""
    set_clock(CLOCK_START)
    season_92 = new_season(season_code="FW26A", fatigue_suppression_threshold=92)
    season_93 = new_season(season_code="FW26B", fatigue_suppression_threshold=93)
    segment_92 = new_segment(season_92["id"], segment_code="S_P92")
    segment_93 = new_segment(season_93["id"], segment_code="S_P93")

    first_mail = new_contact_event(segment_92["id"], CLOCK_START, "MAIL")
    new_contact_event(segment_92["id"], CLOCK_START, "MAIL")

    new_contact_event(segment_93["id"], CLOCK_START, "MAIL")
    new_contact_event(segment_93["id"], CLOCK_START, "MAIL")
    email_93 = new_contact_event(segment_93["id"], CLOCK_START, "EMAIL")

    return {
        "season_92": season_92,
        "season_93": season_93,
        "segment_92": segment_92,
        "segment_93": segment_93,
        "first_mail": first_mail,
        "email_93": email_93,
    }


class TestFatigueThresholdBoundary:
    def test_a_score_landing_exactly_on_the_threshold_suppresses_the_segment(self, api):
        """PRD §3.8: "When a recomputed `fatigue_score` reaches or exceeds the
        season's `fatigue_suppression_threshold`, the segment's `contact_strategy`
        is forced to `SUPPRESS_ONLY` and its `suppressed_at` is stamped with the
        logical clock's current instant; creating a contact event increments the
        segment's `version` by one."

        Design: Difficulty/boundary_precision_check/fatigue_score_exactly_at_threshold_suppresses
        """
        world = _two_seasons_either_side_of_the_fatigue_line()
        segment_id = world["segment_92"]["id"]

        season = fetch_season(world["season_92"]["id"])
        assert season["fatigue_suppression_threshold"] == 92
        assert season["fatigue_window_days"] == 90

        assert_housefile_segment(world["segment_92"])
        assert world["segment_92"]["rfm_score"] == 1000
        assert world["segment_92"]["contact_strategy"] == "PREMIUM_FULL"
        assert world["segment_92"]["fatigue_score"] == 0

        assert world["first_mail"]["channel_weight"] == 40
        assert world["first_mail"]["decay_factor_bps"] == 10000
        assert world["first_mail"]["weighted_points"] == 40

        before = fetch_segment(segment_id)
        assert before["fatigue_score"] == 80
        assert before["contact_strategy"] == "PREMIUM_FULL"

        email = new_contact_event(segment_id, CLOCK_START, "EMAIL")
        assert email["channel_weight"] == 12
        assert email["weighted_points"] == 12

        suppressed = fetch_segment(segment_id)
        assert suppressed["fatigue_score"] == 92
        assert suppressed["contact_strategy"] == "SUPPRESS_ONLY"
        assert_instant_equals(
            suppressed["suppressed_at"], CLOCK_START, "suppressed_at"
        )

        _events, meta = validate_paginated(
            api.list_segment_contact_events(segment_id, PLANNER)
        )
        assert meta["total_count"] == 3

    def test_the_same_score_one_point_below_the_threshold_stays_contactable(self, api):
        """PRD §3.8: "`fatigue_score` is the exact sum of those individually
        rounded contributions."

        Design: Difficulty/boundary_precision_check/fatigue_score_exactly_at_threshold_suppresses
        """
        world = _two_seasons_either_side_of_the_fatigue_line()
        segment_id = world["segment_93"]["id"]

        season = fetch_season(world["season_93"]["id"])
        assert season["fatigue_suppression_threshold"] == 93
        assert world["email_93"]["weighted_points"] == 12

        contactable = fetch_segment(segment_id)
        assert_housefile_segment(contactable)
        assert contactable["fatigue_score"] == 92
        assert contactable["contact_strategy"] == "PREMIUM_FULL"
        assert contactable["suppressed_at"] is None

        _events, meta = validate_paginated(
            api.list_segment_contact_events(segment_id, PLANNER)
        )
        assert meta["total_count"] == 3

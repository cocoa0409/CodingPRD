"""Weekly cycle tests: lock/compute/publish, rank tie-breaks, the recurrent
sweep, holiday adjustments, week windows, and eligibility boundaries.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    activate_methodology,
    compute_week,
    create_chart,
    create_label,
    create_methodology_version,
    create_provider,
    create_recurrent_rule,
    create_title,
    create_week,
    find_entry,
    get_success_data,
    get_week,
    publish_week,
    set_clock,
    setup_locked_week_with_sales,
    setup_open_week_scenario,
    submit_report,
    submit_report_ok,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["chart_manager_headers"]
OPS = TEST_USERS["chart_ops_headers"]


class TestWeekLockPreconditions:
    def test_lock_before_close_rejected_then_succeeds(self, api):
        """PRD §3.5:"Locking requires the logical clock's current time to
        have reached the week's `closes_at` (a premature lock is rejected
        with `ERR_WEEK_NOT_CLOSED`, HTTP 409) and no active freeze on the
        chart"

    Design: Corner/state_machines/week_lock_before_close_rejected"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        set_clock("2026-09-05T00:00:00Z")
        resp = api.lock_week(week["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_WEEK_NOT_CLOSED)
        set_clock(week["closes_at"])
        locked = validate_success(api.lock_week(week["id"], MANAGER))
        assert locked["status"] == "LOCKED"

    def test_compute_without_active_methodology_rejected(self, api):
        """PRD §3.5:"Computing requires no active freeze, a non-null
        `current_methodology_version_id` whose revision is `ACTIVE`, and that
        revision's `effective_from` no later than the week's `opens_at` —
        otherwise the compute is rejected with `ERR_NO_ACTIVE_METHODOLOGY`
        (HTTP 409)"

    Design: Corner/state_machines/compute_without_active_methodology_rejected"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        create_methodology_version(chart)  # stays DRAFT, never activated
        week = create_week(chart)
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        resp = api.compute_week(week["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_METHODOLOGY)
        assert get_week(week["id"])["status"] == "LOCKED"


class TestFrozenChartBeatsWeekNotClosed:
    def test_freeze_error_wins_over_week_not_closed(self, api):
        """PRD §2.8:"then the optimistic-concurrency check where declared,
        then the chart-freeze gate, then target-state legality for the
        requested transition, then account and provider standing, then
        temporal business rules (week closed, active methodology, reporting
        cutoff, week-window overlap, availability window)". PRD §2.9:"While
        a `ChartFreeze` with status `ACTIVE` exists for a chart, five
        operations are blocked with `ERR_CHART_FROZEN` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/frozen_chart_beats_week_not_closed"""
        scenario = setup_open_week_scenario()
        chart = scenario["chart"]
        week = scenario["week"]
        set_clock("2026-09-05T00:00:00Z")  # before closes_at
        from test_helpers import freeze_chart
        freeze_chart(chart["id"])
        resp = api.lock_week(week["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHART_FROZEN)
        assert get_week(week["id"])["status"] == "OPEN"

    def test_freeze_blocks_lock_even_after_close(self, api):
        """PRD §2.9:"While a `ChartFreeze` with status `ACTIVE` exists for a
        chart, five operations are blocked with `ERR_CHART_FROZEN`
        (HTTP 409): locking a week, computing a week, publishing a week,
        accepting a consumption report, and activating a methodology
        version"

    Design: Difficulty/priority_pair_validation_conflict/frozen_chart_beats_week_not_closed"""
        scenario = setup_open_week_scenario()
        chart = scenario["chart"]
        week = scenario["week"]
        set_clock(week["closes_at"])
        from test_helpers import freeze_chart
        freeze_chart(chart["id"])
        resp = api.lock_week(week["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHART_FROZEN)


class TestWeekWindowOverlap:
    def test_adjacent_week_permitted_strict_overlap_rejected(self, api):
        """PRD §2.5:"Adjacent weeks — where a new week's `opens_at` equals
        an existing week's `closes_at` — are permitted; any strict overlap
        between two weeks of the same chart is rejected with
        `ERR_WEEK_WINDOW_OVERLAP` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/chart_week_halfopen_adjacency"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        w1 = create_week(chart, week_index=1,
                         opens_at="2026-09-04T00:00:00Z",
                         closes_at="2026-09-11T00:00:00Z")
        assert w1["status"] == "OPEN"
        adjacent = validate_success(
            api.create_chart_week(
                chart["id"],
                {"week_index": 2, "opens_at": "2026-09-11T00:00:00Z",
                 "closes_at": "2026-09-18T00:00:00Z"},
                MANAGER),
            expected_status=201)
        assert adjacent["week_index"] == 2
        resp = api.create_chart_week(
            chart["id"],
            {"week_index": 3, "opens_at": "2026-09-17T00:00:00Z",
             "closes_at": "2026-09-25T00:00:00Z"},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_WEEK_WINDOW_OVERLAP)

    def test_nested_overlap_inside_existing_week_rejected(self, api):
        """PRD §2.5:"any strict overlap between two weeks of the same chart
        is rejected with `ERR_WEEK_WINDOW_OVERLAP` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/chart_week_halfopen_adjacency"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        create_week(chart, week_index=1,
                    opens_at="2026-09-04T00:00:00Z",
                    closes_at="2026-09-11T00:00:00Z")
        resp = api.create_chart_week(
            chart["id"],
            {"week_index": 2, "opens_at": "2026-09-06T00:00:00Z",
             "closes_at": "2026-09-08T00:00:00Z"},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_WEEK_WINDOW_OVERLAP)


class TestReportingCutoffBoundary:
    def test_cutoff_instant_excluded_one_second_before_accepted(self, api):
        """PRD §3.3:"the `event_time` must fall within the half-open window
        from the week's `opens_at` up to but not including its
        `reporting_cutoff` — including after a holiday adjustment has moved
        that cutoff earlier — with a violation yielding
        `ERR_REPORTING_CUTOFF_PASSED` (HTTP 422)"

    Design: Difficulty/boundary_precision_check/reporting_cutoff_exclusive_boundary"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        adjusted = validate_success(
            api.holiday_adjust_week(
                week["id"],
                {"new_reporting_cutoff": "2026-09-10T00:00:00Z"}, MANAGER))
        assert adjusted["holiday_adjusted"] is True
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        before = submit_report(provider, scenario["title"]["id"], week["id"],
                               component_kind="SALES", quantity=10,
                               event_time="2026-09-09T23:59:59Z",
                               file_fingerprint="bc-in")
        ok_report = validate_success(before, expected_status=201)
        assert ok_report["status"] == "RECEIVED"
        at_cutoff = submit_report(provider, scenario["title"]["id"], week["id"],
                                  component_kind="SALES", quantity=10,
                                  event_time="2026-09-10T00:00:00Z",
                                  file_fingerprint="bc-edge")
        validate_error(at_cutoff, ApiErrorId.ERR_REPORTING_CUTOFF_PASSED)

    def test_event_before_opens_rejected(self, api):
        """PRD §3.3: "the `event_time` must fall within the half-open window
        from the week's `opens_at` up to but not including its
        `reporting_cutoff` — including after a holiday adjustment has moved
        that cutoff earlier — with a violation yielding
        `ERR_REPORTING_CUTOFF_PASSED` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/reporting_cutoff_exclusive_boundary"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        resp = submit_report(provider, scenario["title"]["id"], week["id"],
                             component_kind="SALES", quantity=10,
                             event_time="2026-09-03T23:59:59Z",
                             file_fingerprint="bc-before")
        validate_error(resp, ApiErrorId.ERR_REPORTING_CUTOFF_PASSED)


class TestHolidayAdjustment:
    def test_adjustment_rejects_reports_past_new_cutoff(self, api):
        """PRD §3.6:"On success the cutoff moves, `holiday_adjusted` becomes
        true, and every report of the week in `RECEIVED` or `ACCEPTED` whose
        `event_time` falls at or after the new cutoff transitions to
        `REJECTED` with `review_reason` "outside adjusted cutoff""

    Design: Corner/state_machines/holiday_adjust_rejects_reports_past_new_cutoff"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        r_keep = submit_report_ok(provider, scenario["title"]["id"], week["id"],
                                  component_kind="SALES", quantity=5,
                                  event_time="2026-09-05T00:00:00Z",
                                  file_fingerprint="s7-keep")
        r_drop = submit_report_ok(provider, scenario["title"]["id"], week["id"],
                                  component_kind="SALES", quantity=5,
                                  event_time="2026-09-10T12:00:00Z",
                                  file_fingerprint="s7-drop")
        accept_report(r_keep["id"])
        adjusted = validate_success(
            api.holiday_adjust_week(
                week["id"],
                {"new_reporting_cutoff": "2026-09-10T00:00:00Z"}, MANAGER))
        assert adjusted["holiday_adjusted"] is True
        assert adjusted["status"] == "OPEN"
        keep = get_success_data(api.get_report(r_keep["id"], OPS))
        drop = get_success_data(api.get_report(r_drop["id"], OPS))
        assert keep["status"] == "ACCEPTED", "report before cutoff untouched"
        assert drop["status"] == "REJECTED"
        assert drop["review_reason"] == "outside adjusted cutoff"

    def test_invalid_adjustment_windows_rejected(self, api):
        """PRD §3.6:"the supplied `new_reporting_cutoff` must be strictly
        earlier than the current `reporting_cutoff` and no earlier than
        `opens_at`, with violations rejected as `ERR_HOLIDAY_WINDOW_INVALID`
        (HTTP 422)"

    Design: Corner/validations/holiday_adjust_invalid_window_values"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        # new cutoff equal to current cutoff (== closes_at) is not strictly earlier
        resp = api.holiday_adjust_week(
            week["id"], {"new_reporting_cutoff": "2026-09-11T00:00:00Z"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_HOLIDAY_WINDOW_INVALID)
        # new cutoff before opens_at
        resp = api.holiday_adjust_week(
            week["id"], {"new_reporting_cutoff": "2026-09-03T00:00:00Z"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_HOLIDAY_WINDOW_INVALID)


class TestLockCascadeRejectsInflightReports:
    def test_lock_auto_rejects_received_reports(self, api):
        """PRD §3.5:"Locking slams the door on stragglers: every report of
        the week still in `RECEIVED` transitions to `REJECTED` with
        `review_reason` "late-arriving at lock", each such report's `version`
        incrementing"

    Design: Corner/state_machines/lock_auto_rejects_inflight_received_reports"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        r_acc = submit_report_ok(provider, scenario["title"]["id"], week["id"],
                                 component_kind="SALES", quantity=5,
                                 event_time="2026-09-05T00:00:00Z",
                                 file_fingerprint="s8-acc")
        r_rec = submit_report_ok(provider, scenario["title"]["id"], week["id"],
                                 component_kind="SALES", quantity=7,
                                 event_time="2026-09-06T00:00:00Z",
                                 file_fingerprint="s8-rec")
        accept_report(r_acc["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        rec = get_success_data(api.get_report(r_rec["id"], OPS))
        acc = get_success_data(api.get_report(r_acc["id"], OPS))
        assert rec["status"] == "REJECTED"
        assert rec["review_reason"] == "late-arriving at lock"
        assert acc["status"] == "ACCEPTED"


class TestPublishRanking:
    def test_rank_tiebreak_by_title_created_at(self, api):
        """PRD §3.5:"Publish assigns ranks by sorting entries on points
        descending with a tie-break on the title's `created_at` ascending,
        numbering 1 through N in that order"

    Design: Corner/state_machines/publish_assigns_rank_tiebreak_by_title_created_at"""
        label = create_label()
        t_old = create_title(label, upc="UPC-TIE-OLD", title="Old")
        t_new = create_title(label, upc="UPC-TIE-NEW", title="New")
        scenario_chart, mv, rr = __import__("test_helpers").setup_chart_with_active_methodology()
        week = create_week(scenario_chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        for title, fp in ((t_old, "s5-old"), (t_new, "s5-new")):
            report = submit_report_ok(provider, title["id"], week["id"],
                                      component_kind="SALES", quantity=10,
                                      file_fingerprint=fp)
            accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        compute_week(week["id"])
        entries = publish_week(week["id"])
        e_old = find_entry(entries, t_old["id"])
        e_new = find_entry(entries, t_new["id"])
        assert e_old["points"] == pytest.approx(10.0, abs=1e-9)
        assert e_new["points"] == pytest.approx(10.0, abs=1e-9)
        assert e_old["rank"] == 1, "earlier-created title wins the tie"
        assert e_new["rank"] == 2
        assert e_old["weeks_on_chart"] == 1
        assert e_new["weeks_on_chart"] == 1
        assert e_old["peak_rank"] == 1
        assert e_new["peak_rank"] == 2

    def test_recurrent_sweep_removes_overstay_entry(self, api):
        """PRD §3.5:"Finally, publish runs the recurrent sweep under the
        chart's recurrent rule: any entry whose `weeks_on_chart` has reached
        `max_weeks` and whose `rank` is strictly worse than `min_rank`
        (numerically greater) transitions `ACTIVE → RECURRENT_REMOVED`"

    Design: Corner/state_machines/recurrent_sweep_removes_overstay_entry"""
        rr = create_recurrent_rule(rule_code="RR-S6", max_weeks=2, min_rank=1,
                                   reentry_min_rank=1,
                                   description="aggressive")
        label = create_label()
        t_win = create_title(label, upc="UPC-S6-W", title="Win")
        t_lose = create_title(label, upc="UPC-S6-L", title="Lose")
        chart = create_chart(rr["id"], chart_code="SNG-S6", title="Singles S6")
        mv = create_methodology_version(chart)
        activate_methodology(chart, mv)
        w1 = create_week(chart, week_index=1,
                         opens_at="2026-09-04T00:00:00Z",
                         closes_at="2026-09-11T00:00:00Z")
        w2 = create_week(chart, week_index=2,
                         opens_at="2026-09-11T00:00:00Z",
                         closes_at="2026-09-18T00:00:00Z")
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")

        def play_week(week, event_time, suffix):
            for title, qty in ((t_win, 20), (t_lose, 10)):
                report = submit_report_ok(
                    provider, title["id"], week["id"],
                    component_kind="SALES", quantity=qty,
                    event_time=event_time,
                    file_fingerprint=f"s6-{suffix}-{qty}")
                accept_report(report["id"])
            set_clock(week["closes_at"])
            get_success_data(api.lock_week(week["id"], MANAGER))
            compute_week(week["id"])
            return publish_week(week["id"])

        play_week(w1, "2026-09-05T00:00:00Z", "w1")
        entries = play_week(w2, "2026-09-12T00:00:00Z", "w2")
        e_lose = find_entry(entries, t_lose["id"])
        e_win = find_entry(entries, t_win["id"])
        assert e_lose["weeks_on_chart"] == 2
        assert e_lose["rank"] == 2
        assert e_lose["entry_status"] == "RECURRENT_REMOVED", (
            "weeks_on_chart 2 >= max_weeks 2 and rank 2 > min_rank 1")
        assert e_win["weeks_on_chart"] == 2
        assert e_win["rank"] == 1
        assert e_win["entry_status"] == "ACTIVE", (
            "rank 1 > min_rank 1 is false: no removal")
        assert get_week(w2["id"])["status"] == "PUBLISHED"

    def test_provisional_vs_final_weeks_on_chart(self, api):
        """PRD §3.5:"Compute returns the entry list with provisional
        (pre-publish) fields: `rank` is not yet assigned and `weeks_on_chart`
        counts only previously published weeks, one less than the value
        publish will store"

    Design: Corner/calculations/weeks_on_chart_provisional_vs_final"""
        scenario = setup_locked_week_with_sales(sales_quantity=5)
        week = scenario["week"]
        entries = compute_week(week["id"])
        provisional = find_entry(entries, scenario["title"]["id"])
        assert provisional["weeks_on_chart"] == 0, (
            "compute response counts only previously published weeks")
        published = publish_week(week["id"])
        final = find_entry(published, scenario["title"]["id"])
        assert final["weeks_on_chart"] == 1, (
            "publish stores the count including the current week")


class TestEligibilityBoundaries:
    def test_price_floor_inclusive_boundary(self, api):
        """PRD §3.5:"its `base_price_cents` must be at least the global
        price floor of 300 cents, with the boundary inclusive so a title
        priced at exactly 300 cents passes"

    Design: Difficulty/boundary_precision_check/price_floor_inclusive_boundary"""
        label = create_label()
        t_ok = create_title(label, upc="UPC-BP-OK", base_price_cents=300)
        t_low = create_title(label, upc="UPC-BP-LOW", base_price_cents=299)
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology()
        week = create_week(chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        for title, fp in ((t_ok, "bp-ok"), (t_low, "bp-low")):
            report = submit_report_ok(provider, title["id"], week["id"],
                                      component_kind="SALES", quantity=10,
                                      file_fingerprint=fp)
            accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        entries = compute_week(week["id"])
        assert find_entry(entries, t_ok["id"]) is not None, (
            "300 cents == floor passes (inclusive)")
        assert find_entry(entries, t_low["id"]) is None, (
            "299 cents is below the floor: title skipped")

    def test_price_floor_two_ninety_nine_excluded_three_hundred_included(self, api):
        """PRD §3.5:"its `base_price_cents` must be at least the global
        price floor of 300 cents, with the boundary inclusive so a title
        priced at exactly 300 cents passes"

    Design: Difficulty/boundary_precision_check/price_floor_inclusive_boundary"""
        label = create_label()
        t_floor = create_title(label, upc="UPC-BP-FLOOR", base_price_cents=300)
        t_zero = create_title(label, upc="UPC-BP-ZERO", base_price_cents=0)
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology()
        week = create_week(chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        for title, fp in ((t_floor, "bp-f2"), (t_zero, "bp-z2")):
            report = submit_report_ok(provider, title["id"], week["id"],
                                      component_kind="SALES", quantity=10,
                                      file_fingerprint=fp)
            accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        entries = compute_week(week["id"])
        assert find_entry(entries, t_floor["id"]) is not None
        assert find_entry(entries, t_zero["id"]) is None

    def test_availability_window_exclusive_end(self, api):
        """PRD §3.5:"the week must fall inside the title's availability
        window — `available_from` no later than `opens_at`, and either
        `available_until` null or `opens_at` strictly earlier than
        `available_until`"

    Design: Difficulty/resource_temporal_overlap/availability_window_exclusive_end"""
        label = create_label()
        t_out = create_title(
            label, upc="UPC-AW-OUT",
            availability_policy={"available_from": "2026-08-01T00:00:00Z",
                                 "available_until": "2026-09-04T00:00:00Z"})
        t_in = create_title(
            label, upc="UPC-AW-IN",
            availability_policy={"available_from": "2026-08-01T00:00:00Z",
                                 "available_until": "2026-09-04T00:00:01Z"})
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology()
        week = create_week(chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        for title, fp in ((t_out, "aw-out"), (t_in, "aw-in")):
            report = submit_report_ok(provider, title["id"], week["id"],
                                      component_kind="SALES", quantity=5,
                                      file_fingerprint=fp)
            accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        entries = compute_week(week["id"])
        assert find_entry(entries, t_in["id"]) is not None, (
            "available_until one second after opens_at keeps the title eligible")
        assert find_entry(entries, t_out["id"]) is None, (
            "available_until == opens_at fails the exclusive-end test")

    def test_availability_window_before_available_from_excluded(self, api):
        """PRD §3.5:"the week must fall inside the title's availability
        window — `available_from` no later than `opens_at`, and either
        `available_until` null or `opens_at` strictly earlier than
        `available_until`"

    Design: Difficulty/resource_temporal_overlap/availability_window_exclusive_end"""
        label = create_label()
        t_late = create_title(
            label, upc="UPC-AW-LATE",
            availability_policy={"available_from": "2026-09-05T00:00:00Z",
                                 "available_until": None})
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology()
        week = create_week(chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        report = submit_report_ok(provider, t_late["id"], week["id"],
                                  component_kind="SALES", quantity=5,
                                  file_fingerprint="aw-late")
        accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        entries = compute_week(week["id"])
        assert find_entry(entries, t_late["id"]) is None, (
            "available_from after opens_at keeps the title out of the week")

    def test_genre_mismatch_excluded_from_genre_chart(self, api):
        """PRD §3.5:"Admission additionally respects chart structure: an
        `ALBUMS` chart admits only titles of `product_kind` `ALBUM`, a
        `SINGLES` chart admits only `TRACK`, and a `GENRE` chart admits only
        titles whose `genre_tag` equals the chart's `genre_tag` (a `MAIN`
        chart imposes no genre match)"

    Design: Corner/validations/genre_mismatch_excludes_title_from_genre_chart"""
        label = create_label()
        t_pop = create_title(label, upc="UPC-V3-P", genre_tag="pop")
        t_ctry = create_title(label, upc="UPC-V3-C", genre_tag="country")
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology(
            chart_scope="GENRE", genre_tag="country")
        week = create_week(chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        for title, fp in ((t_pop, "v3-p"), (t_ctry, "v3-c")):
            report = submit_report_ok(provider, title["id"], week["id"],
                                      component_kind="SALES", quantity=5,
                                      file_fingerprint=fp)
            accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        entries = compute_week(week["id"])
        assert find_entry(entries, t_pop["id"]) is None, (
            "pop title excluded from a country genre chart")
        e_ctry = find_entry(entries, t_ctry["id"])
        assert e_ctry is not None
        assert e_ctry["points"] == pytest.approx(5.0, abs=1e-9)

    def test_release_window_first_entry_gate(self, api):
        """PRD §3.5:"the week's `opens_at` must be no earlier than the
        title's `release_date` for its first chart entry"

    Design: Corner/validations/release_window_first_entry_gate"""
        label = create_label()
        t_fut = create_title(label, upc="UPC-V4-F",
                             release_date="2026-09-06T00:00:00Z")
        t_past = create_title(label, upc="UPC-V4-P",
                              release_date="2026-08-01T00:00:00Z")
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology()
        week = create_week(chart)
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        for title, fp in ((t_fut, "v4-f"), (t_past, "v4-p")):
            report = submit_report_ok(provider, title["id"], week["id"],
                                      component_kind="SALES", quantity=5,
                                      event_time="2026-09-07T00:00:00Z",
                                      file_fingerprint=fp)
            accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], MANAGER))
        entries = compute_week(week["id"])
        assert find_entry(entries, t_fut["id"]) is None, (
            "week.opens_at 2026-09-04 is earlier than release_date 2026-09-06")
        assert find_entry(entries, t_past["id"]) is not None


class TestWeekEntriesListing:
    def test_entries_empty_before_compute(self, api):
        """PRD §4: `GET /chart-weeks/{id}/entries` —"List chart entries of
        a week"
    PRD §3.5:"Compute pins the week's
        `computed_methodology_version_id` to the chart's current methodology
        and builds or refreshes one `ChartEntry` per eligible title"

    Design: Corner/endpoints/get_week_entries_subresource_listing"""
        scenario = setup_open_week_scenario()
        entries, meta = validate_paginated(
            api.list_week_entries(scenario["week"]["id"], MANAGER))
        assert entries == []
        assert meta["total_count"] == 0

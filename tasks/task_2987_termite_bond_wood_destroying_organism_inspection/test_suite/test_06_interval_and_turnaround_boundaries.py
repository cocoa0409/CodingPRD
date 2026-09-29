"""Graded metrics read at their exact edges, one second and one day either side.

Two metrics are exercised here and they disagree in unit, in rounding direction
and in strictness: a station visit gap is a whole-day count truncated downwards
and graded on two inclusive edges, while a report's turnaround is a whole-hour
count rounded upwards and graded on a strict inequality.
"""

import pytest

from test_helpers import (
    ACTIVITY_NONE,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    COMPLIANCE_LATE,
    COMPLIANCE_MISSED,
    COMPLIANCE_ON_TIME,
    CONSTRUCTION_SLAB,
    FORM_FL_DACS_13645,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PURPOSE_INITIAL,
    REPORT_ISSUED,
    STATION_INSTALLED,
    approve_plan,
    assert_instant_equals,
    assert_status,
    clean_initial_graph,
    complete_plan,
    issue_wdo_report,
    list_stations,
    next_license_number,
    open_wdo_report,
    propose_bait_plan,
    real_estate_graph,
    record_application,
    register_inspector,
    register_property,
    service_station,
    set_clock,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Metric 1 -- whole days between station visits
# ---------------------------------------------------------------------------

# 2026-08-10T00:00:00Z plus 90 days is 2026-11-08T00:00:00Z, the moment every
# freshly installed station of the plan falls due.
_STATION_EDGES = [
    ("2026-11-08T00:00:00Z", 90, COMPLIANCE_ON_TIME, "2027-02-06T00:00:00Z"),
    ("2026-11-08T23:59:59Z", 90, COMPLIANCE_ON_TIME, "2027-02-06T23:59:59Z"),
    ("2026-11-09T00:00:00Z", 91, COMPLIANCE_LATE, "2027-02-07T00:00:00Z"),
    ("2026-11-15T00:00:00Z", 97, COMPLIANCE_LATE, "2027-02-13T00:00:00Z"),
    ("2026-11-16T00:00:00Z", 98, COMPLIANCE_MISSED, "2027-02-14T00:00:00Z"),
]


def _installed_stations(api):
    """A COMPLETED bait plan whose 18 stations were all installed at one instant.

    The plan is completed at exactly 2026-08-10T00:00:00Z, so every station
    starts from the same ``last_serviced_at`` and the visit clock is the only
    variable left.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    prop = register_property(
        api,
        address_line1="22 Bay Laurel Ct",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=2000,
        linear_footage=180,
        year_built=2001,
        has_attached_structures=False,
    )
    inspector = register_inspector(
        api,
        full_name="Iris Kelso",
        license_number=next_license_number("FL"),
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR, CATEGORY_TERMITE_APPLICATOR],
        license_expires_on="2029-06-30",
    )
    graph = clean_initial_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_INITIAL,
        scheduled_start_at="2026-08-01T13:00:00Z",
        scheduled_end_at="2026-08-01T15:00:00Z",
    )
    plan = propose_bait_plan(api, prop["id"], graph["id"], inspector["id"])
    plan = approve_plan(api, plan["id"])
    record_application(
        api,
        plan["id"],
        inspector["id"],
        plan["version"],
        product_epa_number="432-9988",
        gallons_applied=0.50,
        concentration_pct=0.05,
    )
    set_clock(api, "2026-08-10T00:00:00Z")
    plan = complete_plan(api, plan["id"], inspector["id"])
    stations = list_stations(api, plan["id"], limit=100)
    return {"plan": plan, "inspector": inspector, "stations": stations}


def _quiet_visit(api, chain, station, instant):
    """Park the clock on ``instant`` and record a NONE visit at ``station``."""
    set_clock(api, instant)
    return service_station(
        api, station["id"], chain["inspector"]["id"], ACTIVITY_NONE, matrix_replaced=False
    )


class TestStationIntervalGrading:
    """POST /bait-stations/{id}/services grades a gap in whole days."""

    @pytest.mark.parametrize(
        "instant,expected_days,expected_grade",
        [(case[0], case[1], case[2]) for case in _STATION_EDGES],
        ids=["exactly_90d", "90d_plus_86399s", "91d", "exactly_97d", "98d"],
    )
    def test_the_gap_is_truncated_to_whole_days_and_graded_on_inclusive_edges(
        self, api, instant, expected_days, expected_grade
    ):
        """Both graded edges include their own value, and the partial day is discarded.

        PRD 3.9: "`days_since_last_service` is the number of whole UTC days from
        the station's `last_serviced_at` **as it stood before this visit** to
        `serviced_at`, discarding any partial day", and "a gap of exactly the
        interval is `ON_TIME` rather than `LATE`, and a gap of exactly the
        interval plus seven days is `LATE` rather than `MISSED`."

        Design: Difficulty/boundary_precision_check/station_interval_grading_whole_days_floor_both_edges_inclusive
        """
        chain = _installed_stations(api)
        station = chain["stations"][0]
        assert_instant_equals(station["next_due_at"], "2026-11-08T00:00:00Z")

        visit = _quiet_visit(api, chain, station, instant)
        assert visit["days_since_last_service"] == expected_days
        assert visit["interval_compliance"] == expected_grade
        assert_instant_equals(visit["serviced_at"], instant)

    @pytest.mark.parametrize(
        "instant,expected_next_due",
        [(case[0], case[3]) for case in _STATION_EDGES],
        ids=["exactly_90d", "90d_plus_86399s", "91d", "exactly_97d", "98d"],
    )
    def test_a_quiet_visit_keeps_the_relaxed_rhythm_from_its_own_instant(
        self, api, instant, expected_next_due
    ):
        """However the gap was graded, a NONE visit re-books 90 days from itself.

        PRD 3.9: "A `NONE` visit resets `consecutive_activity_count` to 0 and
        returns the station to `INSTALLED`", and "`next_due_at` is recomputed as
        `serviced_at` plus the interval of the station's **new** status".

        Design: Difficulty/boundary_precision_check/station_interval_grading_whole_days_floor_both_edges_inclusive
        """
        chain = _installed_stations(api)
        station = chain["stations"][0]

        _quiet_visit(api, chain, station, instant)

        current = validate_success(api.get_bait_station(station["id"], OFFICER_HEADERS))
        assert_status(current, STATION_INSTALLED, "bait station")
        assert current["consecutive_activity_count"] == 0
        assert current["service_count"] == 1
        assert_instant_equals(current["last_serviced_at"], instant)
        assert_instant_equals(current["next_due_at"], expected_next_due)

    def test_five_siblings_graded_off_one_shared_installation_instant(self, api):
        """One plan, five stations, five clocks: only the gap differs.

        PRD 3.9: `interval_compliance` "grades that gap against the interval
        belonging to the station's status **before** this visit, not after it",
        and an "`INSTALLED` station is due every 90 days".

        Design: Difficulty/boundary_precision_check/station_interval_grading_whole_days_floor_both_edges_inclusive
        """
        chain = _installed_stations(api)
        stations = chain["stations"]
        assert len(stations) == 18

        for index, (instant, expected_days, expected_grade, _) in enumerate(
            _STATION_EDGES
        ):
            station = stations[index]
            assert_instant_equals(station["last_serviced_at"], "2026-08-10T00:00:00Z")
            visit = _quiet_visit(api, chain, station, instant)
            assert visit["days_since_last_service"] == expected_days
            assert visit["interval_compliance"] == expected_grade
            assert visit["bait_station_id"] == station["id"]

        # No station ever left INSTALLED, so the escalation chain never started.
        plan = validate_success(
            api.get_treatment_plan(chain["plan"]["id"], MANAGER_HEADERS)
        )
        assert plan["escalated_station_count"] == 0
        assert plan["retreat_required"] is False


# ---------------------------------------------------------------------------
# Metric 2 -- whole hours from request to issuance
# ---------------------------------------------------------------------------

# All three filings are requested at 2026-08-03T09:00:00Z against Florida's
# 72-hour allowance, so they share the deadline 2026-08-06T09:00:00Z.
_TURNAROUND_EDGES = [
    ("2026-08-06T08:00:01Z", 72, False),
    ("2026-08-06T09:00:00Z", 72, False),
    ("2026-08-06T09:00:01Z", 73, True),
]


def _requested_report(api):
    """One DRAFT statutory report requested at 2026-08-03T09:00:00Z.

    The graph's closing date is 2026-09-30, so the 24-hour closing-lead deadline
    of 2026-09-29T00:00:00Z is far beyond every issuance instant below and
    cannot interfere with the measurement.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    prop = register_property(
        api,
        address_line1="9 Marlin Way",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=1800,
        linear_footage=160,
        year_built=1999,
        has_attached_structures=False,
    )
    inspector = register_inspector(
        api,
        full_name="Hugo Naim",
        license_number=next_license_number("FL"),
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR],
        license_expires_on="2029-06-30",
    )
    graph = real_estate_graph(
        api,
        prop["id"],
        inspector["id"],
        "2026-09-30",
        scheduled_start_at="2026-08-02T13:00:00Z",
        scheduled_end_at="2026-08-02T15:00:00Z",
    )
    set_clock(api, "2026-08-03T09:00:00Z")
    report = open_wdo_report(api, graph["id"], state_code="FL")
    return {"property": prop, "inspection": graph, "report": report}


class TestWdoTurnaroundSlaEdge:
    """POST /wdo-reports/{id}/issue measures in whole hours, rounded up."""

    @pytest.mark.parametrize(
        "issue_instant,expected_hours,expected_breached",
        _TURNAROUND_EDGES,
        ids=["71h00m01s", "exactly_72h", "72h00m01s"],
    )
    def test_a_partial_hour_counts_whole_but_the_allowance_is_only_breached_beyond_it(
        self, api, issue_instant, expected_hours, expected_breached
    ):
        """Ceil the hours, then compare strictly: 72 hours is still on time.

        PRD 3.4: "`turnaround_hours`, the number of whole hours from
        `requested_at` to `issued_at` rounded up so that any partial hour counts
        as a full one, and `sla_breached`, true exactly when `turnaround_hours`
        **strictly exceeds** the state's allowance -- a report issued in exactly
        the allowed number of hours is on time."

        Design: Difficulty/boundary_precision_check/wdo_sla_breach_ceil_hours_strict_greater_than
        """
        chain = _requested_report(api)
        draft = chain["report"]
        assert draft["form_code"] == FORM_FL_DACS_13645
        assert_instant_equals(draft["requested_at"], "2026-08-03T09:00:00Z")
        assert_instant_equals(draft["due_at"], "2026-08-06T09:00:00Z")

        set_clock(api, issue_instant)
        issued = issue_wdo_report(api, draft["id"])

        assert_status(issued, REPORT_ISSUED, "statutory report")
        assert_instant_equals(issued["issued_at"], issue_instant)
        assert issued["turnaround_hours"] == expected_hours
        assert issued["sla_breached"] is expected_breached

    def test_only_the_filing_a_second_late_is_reported_as_breached(self, api):
        """Three filings share one request instant; the collection separates them.

        PRD 3.4: "`sla_breached`, true exactly when `turnaround_hours` **strictly
        exceeds** the state's allowance"; PRD 2.3: statutory reports "may be
        filtered by `inspection_id`, `status` and `sla_breached`".

        Design: Difficulty/boundary_precision_check/wdo_sla_breach_ceil_hours_strict_greater_than
        """
        chain = _requested_report(api)
        inspection_id = chain["inspection"]["id"]
        reports = [chain["report"]]
        reports.append(open_wdo_report(api, inspection_id, state_code="FL"))
        reports.append(open_wdo_report(api, inspection_id, state_code="FL"))
        for report in reports:
            assert_instant_equals(report["requested_at"], "2026-08-03T09:00:00Z")
            assert_instant_equals(report["due_at"], "2026-08-06T09:00:00Z")

        issued = []
        for report, (instant, expected_hours, expected_breached) in zip(
            reports, _TURNAROUND_EDGES
        ):
            set_clock(api, instant)
            row = issue_wdo_report(api, report["id"])
            assert row["turnaround_hours"] == expected_hours
            assert row["sla_breached"] is expected_breached
            issued.append(row)

        rows, meta = validate_paginated(
            api.list_wdo_reports(
                OFFICER_HEADERS, inspection_id=inspection_id, sla_breached="true"
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == issued[2]["id"]

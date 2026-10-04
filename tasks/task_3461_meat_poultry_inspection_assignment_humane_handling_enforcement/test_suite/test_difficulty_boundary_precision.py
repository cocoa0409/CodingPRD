"""Depth tests: boundary precision on numeric thresholds and intervals.

The SALMONELLA positive-rate boundary (equality at the standard stays CAT_2;
one more positive crosses to CAT_3) and the half-open interval boundary on
assignment coverage (end == next start is continuous; a one-minute sliver of
overlap violates).
"""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPositiveRateBoundary:
    def _eleven_sample_world(self, api):
        base = fx.create_granted_establishment(api, species_classes=["POULTRY"], name="D12 Poultry Plant")
        inspector = fx.create_inspector(api, species_qualifications=["POULTRY"])
        samples = fx.collect_pathogen_samples(
            api, base["establishment"]["id"], inspector["id"], "SALMONELLA", 11
        )
        return base["establishment"], inspector, samples

    def _record_first_ten_one_positive(self, api, samples, inspector_id):
        fx.record_sample_result(api, samples[0]["id"], inspector_id, "POSITIVE")
        for sample in samples[1:10]:
            fx.record_sample_result(api, sample["id"], inspector_id, "NEGATIVE")

    def test_rate_exactly_at_standard_stays_cat2_then_crosses(self, api):
        """PRD §3.6: "The pathogen is a `CAT_1` candidate when its positive
        rate is at most half the standard rate for that pathogen, a `CAT_2`
        candidate when its rate is at most the standard rate, and a `CAT_3`
        candidate when its rate exceeds the standard rate. The boundaries are
        pinned: a rate exactly equal to the standard rate is `CAT_2`, never
        `CAT_3`; a rate exactly equal to half the standard is `CAT_1`."
        PRD §2.9: "Pathogen positive-rates are compared as exact rational
        numbers (positive count over resulted count) with no rounding before
        comparison; boundary equalities resolve exactly as §3.6 states."

        Design: Difficulty/boundary_precision_check/positive_rate_exactly_at_standard_stays_cat2
        """
        est, inspector, samples = self._eleven_sample_world(api)
        self._record_first_ten_one_positive(api, samples, inspector["id"])

        at_ten = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # 1/10 == 0.10 equals the SALMONELLA standard exactly: <= keeps CAT_2.
        assert at_ten["pathogen_category"] == "CAT_2", (
            f"1/10 == 0.10 must stay CAT_2, got {at_ten['pathogen_category']!r}"
        )

        fx.record_sample_result(api, samples[10]["id"], inspector["id"], "POSITIVE")

        at_eleven = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # 2/11 exceeds the standard -> CAT_3.
        assert at_eleven["pathogen_category"] == "CAT_3", (
            f"2/11 > 0.10 must cross to CAT_3, got {at_eleven['pathogen_category']!r}"
        )

    def test_crossing_fires_exactly_one_cat3_notice(self, api):
        """PRD §3.6: "Whenever a result recording causes any pathogen's
        recomputed category to transition to `CAT_3` from a different value,
        the system automatically creates an enforcement action against the
        establishment in the same request: `action_type`
        `NOTICE_OF_INTENDED_ENFORCEMENT`, `basis` `CATEGORY_3_PATHOGEN`,
        `status` `IN_EFFECT`, `auto_created` true, and `effective_at` stamped
        from the logical clock. A re-computation that lands on `CAT_3` from
        `CAT_3`, or that moves between `CAT_1` and `CAT_2`, creates nothing."

        Design: Difficulty/boundary_precision_check/positive_rate_exactly_at_standard_stays_cat2
        """
        est, inspector, samples = self._eleven_sample_world(api)
        self._record_first_ten_one_positive(api, samples, inspector["id"])
        assert fx.list_enforcement_actions(api, est["id"]) == [], (
            "sitting at the standard (CAT_2) creates nothing"
        )

        fx.record_sample_result(api, samples[10]["id"], inspector["id"], "POSITIVE")

        actions = fx.list_enforcement_actions(api, est["id"])
        assert len(actions) == 1, f"the CAT_3 transition fires exactly one notice, got {len(actions)}"
        assert actions[0]["basis"] == "CATEGORY_3_PATHOGEN"
        assert actions[0]["action_type"] == "NOTICE_OF_INTENDED_ENFORCEMENT"
        assert actions[0]["status"] == "IN_EFFECT"
        assert actions[0]["auto_created"] is True


class TestAdjacentAssignmentsZeroGap:
    def _two_adjacent_confirmed(self, api):
        """Window 06:00-14:00 (480 min, 1 line); CONFIRMED 06:00-10:00 and
        CONFIRMED 10:00-14:00 (end == next start)."""
        base = fx.setup_granted_with_window(api, species_classes=["CATTLE"], name="D13 Beef Plant")
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        window = base["window"]
        fx.create_and_confirm_assignment(
            api, window["id"], inspector["id"],
            start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T10:00:00Z",
        )
        fx.create_and_confirm_assignment(
            api, window["id"], inspector["id"],
            start_utc="2026-09-02T10:00:00Z", end_utc="2026-09-02T14:00:00Z",
        )
        return base["establishment"], inspector, window

    def test_adjacency_at_line_boundary_leaves_zero_gap(self, api):
        """PRD §3.2: "The gap algorithm runs per line: for each line number
        from 1 to `planned_line_count`, collect the window's non-`CANCELLED`
        assignments on that line, merge their half-open intervals, and measure
        the minutes of the window's own interval left uncovered; adjacent
        intervals, where one assignment's `end_utc` equals the next's
        `start_utc`, leave zero uncovered minutes between them."
        PRD §3.2: "The final gap drives the transition: a final gap of exactly
        0 moves the window to `VERIFIED_COVERED`, and a final gap greater than
        0 moves it to `COVERAGE_GAP_FLAGGED`."

        Design: Difficulty/boundary_precision_check/adjacent_assignments_zero_gap
        """
        est, inspector, window = self._two_adjacent_confirmed(api)

        verified = fx.verify_coverage(api, window["id"], inspector["id"])

        assert verified["final_gap_minutes"] == 0, "adjacency at 10:00 contributes no gap"
        assert verified["provisional_gap_minutes"] == 0
        assert verified["status"] == "VERIFIED_COVERED"
        assert fx.list_nrs(api) == [], "a fully covered window issues no auto-NR"

    def test_one_minute_sliver_of_overlap_is_rejected(self, api):
        """PRD §3.2: "On the same window and the same `line_index`, the new
        interval must not overlap any existing non-`CANCELLED` assignment's
        interval — intervals are half-open, so one assignment ending exactly
        when another begins is continuous, legal coverage — and a violation is
        rejected with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/adjacent_assignments_zero_gap
        """
        _est, _inspector, window = self._two_adjacent_confirmed(api)
        current = fx.get_shift_window(api, window["id"])

        # 09:59-10:01 overlaps both neighbours by one minute on each side.
        resp = api.create_assignment(
            window["id"],
            f.assignment_payload(
                _inspector["id"], 1,
                "2026-09-02T09:59:00Z", "2026-09-02T10:01:00Z",
                current["version"],
            ),
            PROGRAM_ADMINISTRATOR_HEADERS,
        )

        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)
        rows, _meta = validate_paginated(api.list_shift_assignments(DISTRICT_MANAGER_HEADERS))
        assert len(rows) == 2, f"the rejected sliver must not be stored, got {len(rows)}"

"""Depth tests: dual-variant calculations.

The coverage-gap computation stores two variants from the same rows
(provisional counts SCHEDULED + CONFIRMED, final counts CONFIRMED only), and
the establishment risk score likewise has a windowed/recency-weighted rolling
variant beside its unwindowed lifetime companion.
"""

from test_helpers import (
    DISTRICT_MANAGER_HEADERS,
    assert_instant,
    fixtures as fx,
    validate_success,
)


class TestCoverageGapDualVariant:
    def test_provisional_counts_scheduled_but_final_counts_confirmed_only(self, api):
        """PRD §3.2: "Two variants are computed from the same rows: the
        provisional variant counts both `SCHEDULED` and `CONFIRMED` assignments
        and is stored as `provisional_gap_minutes`, while the final variant
        counts `CONFIRMED` assignments only and is stored as
        `final_gap_minutes` — for the same assignment rows the final gap is
        always greater than or equal to the provisional gap."
        PRD §3.2: "The final gap drives the transition: a final gap of exactly
        0 moves the window to `VERIFIED_COVERED`, and a final gap greater than
        0 moves it to `COVERAGE_GAP_FLAGGED`."

        Design: Difficulty/dual_variant_calc/coverage_gap_provisional_vs_final_divergence
        """
        base = fx.create_granted_establishment(api, species_classes=["CATTLE"])
        est_id = base["establishment"]["id"]
        inspector = fx.create_inspector(
            api, species_qualifications=["CATTLE", "SWINE", "POULTRY", "SHEEP"]
        )
        window = fx.create_shift_window(api, est_id)  # SLAUGHTER 06:00-14:00, 1 line
        # One SCHEDULED-but-never-confirmed assignment covering all 480 minutes.
        fx.add_assignment(api, window["id"], inspector["id"])

        verified = fx.verify_coverage(api, window["id"], inspector["id"])

        assert verified["provisional_gap_minutes"] == 0, (
            f"SCHEDULED rows count provisionally: expected 0, got {verified['provisional_gap_minutes']}"
        )
        assert verified["final_gap_minutes"] == 480, (
            f"only CONFIRMED rows count in the final variant: expected 480, got {verified['final_gap_minutes']}"
        )
        assert verified["status"] == "COVERAGE_GAP_FLAGGED"
        # The read path reports the same stored fields.
        reread = fx.get_shift_window(api, window["id"])
        assert reread["provisional_gap_minutes"] == 0
        assert reread["final_gap_minutes"] == 480
        assert reread["status"] == "COVERAGE_GAP_FLAGGED"

    def test_flagged_slaughter_window_issues_other_family_nr(self, api):
        """PRD §3.2: "When a `SLAUGHTER` window is flagged, the system
        additionally issues a noncompliance record in the same request:
        `regulation_family` `OTHER`, `description` "inspection presence gap",
        `observed_at` at the logical clock, issued by the verifying inspector,
        in `OPEN` status."

        Design: Difficulty/dual_variant_calc/coverage_gap_provisional_vs_final_divergence
        """
        base = fx.create_granted_establishment(api, species_classes=["CATTLE"])
        est_id = base["establishment"]["id"]
        inspector = fx.create_inspector(
            api, species_qualifications=["CATTLE", "SWINE", "POULTRY", "SHEEP"]
        )
        window = fx.create_shift_window(api, est_id)
        fx.add_assignment(api, window["id"], inspector["id"])

        fx.verify_coverage(api, window["id"], inspector["id"])

        nrs = fx.list_nrs(api)
        assert len(nrs) == 1, f"exactly one auto-issued NR expected, got {len(nrs)}"
        nr = nrs[0]
        assert nr["regulation_family"] == "OTHER"
        assert nr["status"] == "OPEN"
        assert nr["description"] == "inspection presence gap"
        assert nr["establishment_id"] == est_id
        assert nr["issued_by_inspector_id"] == inspector["id"]
        assert_instant(nr["observed_at"], fx.CLOCK_START_ISO, "auto-NR observed_at")


class TestRiskScoreDualVariant:
    def _build_two_nr_history(self, api):
        """NR1 (HUMANE) issued with the clock at 2026-09-01; NR2 (HACCP) issued
        with the clock at 2026-12-10; read with the clock at 2026-12-15, so
        NR1's issued_at is 105 days old (outside the 90-day window) and NR2's
        is 5 days old (recency factor 3)."""
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        est = fx.create_establishment(
            api, name="D2 Pork Plant", species_classes=["SWINE"], slaughter_capable=True
        )
        inspector = fx.create_inspector(api, species_qualifications=["SWINE"])
        fx.issue_nr(
            api,
            est["id"],
            inspector["id"],
            regulation_family="HUMANE",
            description="stunning pen gate drag",
            observed_at="2026-08-30T10:00:00Z",
        )
        fx.set_clock(api, "2026-12-10T00:00:00Z")
        fx.issue_nr(
            api,
            est["id"],
            inspector["id"],
            regulation_family="HACCP",
            description="ccp monitoring lapse",
            observed_at="2026-12-09T10:00:00Z",
        )
        fx.set_clock(api, "2026-12-15T00:00:00Z")
        return est["id"]

    def test_rolling_risk_applies_window_and_recency_bands(self, api):
        """PRD §2.10: "`rolling_risk_score` is the establishment's current
        operational risk: the sum, over its noncompliance records in the four
        open statuses whose `issued_at` lies within the trailing 90 days of the
        logical clock, of a family weight times a recency factor."
        PRD §2.10: "Family weights are 2 for `SANITATION`, 3 for `HACCP`, 5 for
        `HUMANE`, 1 for `LABELING`, and 1 for `OTHER`. The recency factor
        depends on the record's age in days from `issued_at` to the logical
        clock: 3 when the age is at most 30 days, 2 when the age is 31 to 60
        days, and 1 when the age is 61 to 90 days; a record older than 90 days
        contributes 0."

        Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_lifetime_divergence
        """
        est_id = self._build_two_nr_history(api)

        data = validate_success(api.get_establishment(est_id, DISTRICT_MANAGER_HEADERS), 200)

        # NR1 (HUMANE, weight 5) is 105 days old -> outside the window -> 0.
        # NR2 (HACCP, weight 3) is 5 days old -> recency factor 3 -> 9.
        assert data["rolling_risk_score"] == 9, (
            f"rolling risk: expected 3*3 == 9, got {data['rolling_risk_score']}"
        )

    def test_lifetime_risk_is_unwindowed_and_unweighted(self, api):
        """PRD §2.10: "`lifetime_risk_score` is the unwindowed companion used
        for trend auditing: the sum of the family weight alone over all of the
        establishment's records whose status is not `VACATED`, with no recency
        factor and no window."
        PRD §2.10: "`open_nr_count` is the number of the establishment's
        noncompliance records whose `status` is one of `OPEN`,
        `RESPONSE_SUBMITTED`, `ESCALATED`, or `APPEALED`."

        Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_lifetime_divergence
        """
        est_id = self._build_two_nr_history(api)

        data = validate_success(api.get_establishment(est_id, DISTRICT_MANAGER_HEADERS), 200)

        # Both records count at family weight alone: 5 (HUMANE) + 3 (HACCP) == 8.
        assert data["lifetime_risk_score"] == 8, (
            f"lifetime risk: expected 5+3 == 8, got {data['lifetime_risk_score']}"
        )
        assert data["rolling_risk_score"] != data["lifetime_risk_score"]
        assert data["open_nr_count"] == 2

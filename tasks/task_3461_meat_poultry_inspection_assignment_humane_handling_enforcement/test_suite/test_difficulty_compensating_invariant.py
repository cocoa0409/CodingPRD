"""Depth tests: compensating invariants.

A create-then-cancel pair on shift assignments conserves both coverage-gap
variants, and an issue-then-vacate pair on a noncompliance record conserves
the establishment's open-record count and derived risk measures.
"""

from test_helpers import (
    DISTRICT_MANAGER_HEADERS,
    fixtures as fx,
    validate_success,
)


class TestAssignmentCreateCancelConservesCoverage:
    def _baseline_flagged_window(self, api):
        """Window 06:00-14:00 (480 min, 1 line) with one CONFIRMED 06:00-10:00
        assignment; verified once -> baseline gaps 240/240, COVERAGE_GAP_FLAGGED."""
        base = fx.setup_granted_with_window(api, species_classes=["CATTLE"], name="D18 Beef Plant")
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        fx.create_and_confirm_assignment(
            api, base["window"]["id"], inspector["id"],
            start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T10:00:00Z",
        )
        flagged = fx.verify_coverage(api, base["window"]["id"], inspector["id"])
        assert flagged["provisional_gap_minutes"] == 240
        assert flagged["final_gap_minutes"] == 240
        assert flagged["status"] == "COVERAGE_GAP_FLAGGED"
        return base, inspector

    def test_create_then_cancel_returns_gaps_to_baseline(self, api):
        """PRD §3.2: "A `ProgramAdministrator` may cancel a `SCHEDULED`
        assignment, moving it to `CANCELLED`; `CONFIRMED` and `CANCELLED` are
        terminal."
        PRD §3.2: "The gap algorithm runs per line: for each line number from 1
        to `planned_line_count`, collect the window's non-`CANCELLED`
        assignments on that line, merge their half-open intervals, and measure
        the minutes of the window's own interval left uncovered; adjacent
        intervals, where one assignment's `end_utc` equals the next's
        `start_utc`, leave zero uncovered minutes between them."
        PRD §3.2: "A flagged window can be re-verified after corrective
        scheduling and will move to `VERIFIED_COVERED` once the final gap
        reaches 0."

        Design: Difficulty/compensating_invariant/assignment_create_cancel_conserves_coverage_minutes
        """
        base, inspector = self._baseline_flagged_window(api)
        window_id = base["window"]["id"]

        created = fx.add_assignment(
            api, window_id, inspector["id"],
            start_utc="2026-09-02T10:00:00Z", end_utc="2026-09-02T14:00:00Z",
        )
        cancelled = fx.cancel_assignment(api, created["id"])
        assert cancelled["status"] == "CANCELLED", "the compensating action is recorded"

        reverify = fx.verify_coverage(api, window_id, inspector["id"])
        assert reverify["provisional_gap_minutes"] == 240, (
            "cancelled rows count in neither variant: provisional back to baseline"
        )
        assert reverify["final_gap_minutes"] == 240
        assert reverify["status"] == "COVERAGE_GAP_FLAGGED", (
            "state returns to the pre-create status, not silently advanced"
        )

    def test_unconfirmed_create_moves_only_the_provisional_variant(self, api):
        """PRD §3.2: "Two variants are computed from the same rows: the
        provisional variant counts both `SCHEDULED` and `CONFIRMED` assignments
        and is stored as `provisional_gap_minutes`, while the final variant
        counts `CONFIRMED` assignments only and is stored as
        `final_gap_minutes` — for the same assignment rows the final gap is
        always greater than or equal to the provisional gap."

        Design: Difficulty/compensating_invariant/assignment_create_cancel_conserves_coverage_minutes
        """
        base, inspector = self._baseline_flagged_window(api)
        window_id = base["window"]["id"]

        created = fx.add_assignment(
            api, window_id, inspector["id"],
            start_utc="2026-09-02T10:00:00Z", end_utc="2026-09-02T14:00:00Z",
        )
        # While the new assignment is still SCHEDULED, the provisional variant
        # sees full coverage (0) but the final variant still measures 240.
        mid = fx.verify_coverage(api, window_id, inspector["id"])
        assert mid["provisional_gap_minutes"] == 0, "SCHEDULED rows count provisionally"
        assert mid["final_gap_minutes"] == 240, "only CONFIRMED rows count finally"
        assert mid["status"] == "COVERAGE_GAP_FLAGGED"

        fx.cancel_assignment(api, created["id"])
        restored = fx.verify_coverage(api, window_id, inspector["id"])
        assert restored["provisional_gap_minutes"] == 240
        assert restored["final_gap_minutes"] == 240


class TestNrIssueThenVacateConservesOpenCount:
    def test_vacate_returns_open_count_and_risk_scores_to_baseline(self, api):
        """PRD §3.9: "A vacated record disappears from every derived measure:
        it no longer counts toward `open_nr_count`, toward escalation
        qualification, or toward either risk score."
        PRD §2.10: "`open_nr_count` is the number of the establishment's
        noncompliance records whose `status` is one of `OPEN`,
        `RESPONSE_SUBMITTED`, `ESCALATED`, or `APPEALED`."

        Design: Difficulty/compensating_invariant/nr_issue_then_vacate_conserves_open_count
        """
        est = fx.create_establishment(api, name="D19 Swine Plant", species_classes=["SWINE"])
        pair = fx.create_inspector_pair(api, ["SWINE"])
        baseline = fx.get_establishment(api, est["id"])
        assert baseline["open_nr_count"] == 0

        record = fx.issue_nr(
            api, est["id"], pair["issuer"]["id"],
            regulation_family="SANITATION", description="floor pooling in cooler",
        )
        mid = fx.get_establishment(api, est["id"])
        assert mid["open_nr_count"] == 1, "issuance raised the conserved quantity"

        appeal = fx.file_appeal(api, record["id"], est["id"], grounds="grounds-text-vac")
        fx.decide_appeal(api, appeal["id"], pair["reviewer"]["id"], "VACATE")

        after = fx.get_establishment(api, est["id"])
        assert after["open_nr_count"] == 0, "vacate compensated exactly"
        assert after["lifetime_risk_score"] == 0, "VACATED records are excluded from lifetime risk"
        assert after["rolling_risk_score"] == 0
        assert fx.get_nr(api, record["id"])["status"] == "VACATED"

    def test_vacated_record_does_not_qualify_toward_escalation(self, api):
        """PRD §3.3: "the system counts the establishment's qualifying records
        in the same `regulation_family`: those with status `OPEN`,
        `RESPONSE_SUBMITTED`, or `ESCALATED` (records in `APPEALED` or
        `VACATED` never qualify), whose `issued_at` lies within the trailing 90
        days of the logical clock inclusive of the boundary day, including the
        record that just escalated, now counted in its `ESCALATED` state. If
        that count reaches 3 — exactly at threshold fires — the system
        automatically creates an enforcement action against the establishment:
        `action_type` `SUSPENSION`, `basis` `NR_LINKAGE`, `regulation_family`
        set to the escalating record's family, `status` `PROPOSED`, and
        `auto_created` true."

        Design: Difficulty/compensating_invariant/nr_issue_then_vacate_conserves_open_count
        """
        est = fx.create_establishment(api, name="D19 Exclusion Plant", species_classes=["SWINE"])
        pair = fx.create_inspector_pair(api, ["SWINE"])

        # One genuinely ESCALATED SANITATION record.
        first = fx.issue_nr(api, est["id"], pair["issuer"]["id"], regulation_family="SANITATION",
                            description="sanitation finding one")
        fx.escalate_nr(api, first["id"], pair["issuer"]["id"])
        # One SANITATION record pushed to VACATED (drops out of qualification).
        fx.create_vacated_nr(api, est["id"], pair["issuer"]["id"], pair["reviewer"]["id"],
                             regulation_family="SANITATION")
        # A third SANITATION record escalated: qualifying count is 2, not 3.
        third = fx.issue_nr(api, est["id"], pair["issuer"]["id"], regulation_family="SANITATION",
                            description="sanitation finding three")
        fx.escalate_nr(api, third["id"], pair["issuer"]["id"])

        actions = fx.list_enforcement_actions(api, est["id"])
        assert actions == [], (
            "qualifying count is 2 (the VACATED record never qualifies) — below the threshold of 3"
        )
        data = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        assert data["open_nr_count"] == 2, "the two ESCALATED records count; the vacated one does not"

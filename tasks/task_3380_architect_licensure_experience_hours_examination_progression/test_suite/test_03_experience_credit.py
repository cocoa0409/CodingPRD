"""Experience credit tiering: 8/60-month windows, locked vs projected
variants, per-report rounding (PRD §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId, FULL_CREDIT_PCT, HALF_CREDIT_PCT, LOGICAL_CLOCK_START_ISO,
    assert_experience_report, create_active_supervisor, create_candidate,
    create_draft_report, create_jurisdiction, make_candidate_headers,
    set_clock, submit_report, validate_error, validate_success,
    verify_report,
)

J1 = "J1"


def _registry(api):
    create_jurisdiction(code=J1)
    candidate = create_candidate(home_jurisdiction_code=J1)
    supervisor = create_active_supervisor(jurisdiction_code=J1)
    return candidate, supervisor


class TestCreditTierBoundaries:
    def test_credit_tier_full_credit_at_exact_8_months(self, api):
        """PRD §3.3: "a report submitted on or before the day eight calendar
        months after its `work_period_end` locks 100 percent credit, while one
        submitted later but on or before the day sixty calendar months after
        `work_period_end` locks 50 percent."

        Design: Corner/calculations/credit_tier_full_credit_at_exact_8_months
        """
        candidate, supervisor = _registry(api)
        set_clock("2026-09-15T00:00:00Z")
        report = create_draft_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-01-02", "2026-01-15",
        )
        # work_period_end 2026-01-15 + 8 calendar months == 2026-09-15 (today).
        data = submit_report(candidate, report["id"])
        assert data["status"] == "SUBMITTED"
        assert data["credit_pct"] == FULL_CREDIT_PCT, (
            "boundary day is inside the full-credit window (inclusive)"
        )

    def test_credit_tier_half_credit_value(self, api):
        """PRD §3.3: "a report submitted on or before the day eight calendar
        months after its `work_period_end` locks 100 percent credit, while one
        submitted later but on or before the day sixty calendar months after
        `work_period_end` locks 50 percent."
        PRD §3.3: "the report's `hours` are multiplied by the locked
        `credit_pct` percentage and the product is rounded half-up to a whole
        hour, per report, before any aggregation."

        Design: Corner/calculations/credit_tier_half_credit_value
        """
        candidate, supervisor = _registry(api)
        set_clock(LOGICAL_CLOCK_START_ISO)
        report = create_draft_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2025-06-01", "2025-06-30",
        )
        # 2026-09-01 is past end+8mo (2026-02-28) but within end+60mo.
        submitted = submit_report(candidate, report["id"])
        assert submitted["credit_pct"] == HALF_CREDIT_PCT
        verified = verify_report(supervisor, report["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["credited_hours"] == 20, "round_half_up(40 * 0.5) == 20"

    def test_experience_older_than_60_months_rejected(self, api):
        """PRD §3.3: "it requires the submission date to fall no later than
        sixty calendar months after the report's `work_period_end`, else the
        report is too old to count and submission fails with
        `ERR_EXPERIENCE_TOO_OLD`."

        Design: Corner/calculations/experience_older_than_60_months_rejected
        """
        candidate, supervisor = _registry(api)
        set_clock(LOGICAL_CLOCK_START_ISO)
        boundary = create_draft_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2021-08-02", "2021-09-01",
        )
        too_old = create_draft_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2021-06-01", "2021-07-01",
        )
        # Boundary: 2021-09-01 + 60 calendar months == 2026-09-01 (today) — OK.
        data = submit_report(candidate, boundary["id"])
        assert data["status"] == "SUBMITTED"
        assert data["credit_pct"] == HALF_CREDIT_PCT
        # 2021-07-01 + 60 months == 2026-07-01 < today — rejected.
        validate_error(
            api.submit_experience_report(
                too_old["id"], make_candidate_headers(candidate["id"]),
            ),
            ApiErrorId.ERR_EXPERIENCE_TOO_OLD,
        )
        stale = validate_success(api.get_experience_report(
            too_old["id"], make_candidate_headers(candidate["id"]),
        ))
        assert stale["status"] == "DRAFT", "rejection leaves the report DRAFT"


class TestLockedVsProjectedVariants:
    def _setup_two_reports(self, api):
        """R1 PPD 40h submitted at 2026-09-15 (locks 100%); R2 PJM 40h left
        DRAFT; returns (candidate, supervisor, r1, r2)."""
        candidate, supervisor = _registry(api)
        set_clock("2026-09-15T00:00:00Z")
        r1 = create_draft_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-01-05", "2026-02-02",
        )
        submit_report(candidate, r1["id"])
        r2 = create_draft_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-02-02", "2026-03-02",
        )
        return candidate, supervisor, r1, r2

    def test_variants_diverge_before_tier_boundary(self, api):
        """PRD §3.3: "Its official fields — `total_credited_hours`,
        `locked_credited_hours`, and the per-area `area_progress` map — always
        use the tiers locked at submission time. Its
        `projected_credited_hours` field answers a different question: what
        the candidate would hold if every `DRAFT` and `SUBMITTED` report were
        submitted today and verified today, re-tiering each such report
        against the current date and adding the `VERIFIED` rows' stamped
        `credited_hours`."
        PRD §3.3: "Only `VERIFIED` reports contribute; `DRAFT`, `SUBMITTED`,
        and `RETURNED` reports each contribute exactly zero."

        Design: Difficulty/dual_variant_calc/experience_credit_locked_vs_projected
        """
        candidate, _s, _r1, _r2 = self._setup_two_reports(api)
        summary = validate_success(api.get_candidate_summary(
            candidate["id"], make_candidate_headers(candidate["id"]),
        ))
        # At 2026-09-15 both reports re-tier to 100% in the what-if view
        # (40 + 40), while the official locked figure counts only R1's
        # submission-locked tier (40).
        assert summary["projected_credited_hours"] == 80
        assert summary["locked_credited_hours"] == 40
        assert summary["total_credited_hours"] == 0, "nothing is VERIFIED yet"

    def test_variants_converge_after_clock_crosses_tier_boundary(self, api):
        """PRD §3.3: "That locked tier is permanent — a report submitted
        inside the eight-month full-credit window keeps 100 percent forever,
        even if it is verified years later."
        PRD §3.3: "Its `projected_credited_hours` field answers a different
        question: what the candidate would hold if every `DRAFT` and
        `SUBMITTED` report were submitted today and verified today, re-tiering
        each such report against the current date and adding the `VERIFIED`
        rows' stamped `credited_hours`."

        Design: Difficulty/dual_variant_calc/experience_credit_locked_vs_projected
        """
        candidate, _s, r1, _r2 = self._setup_two_reports(api)
        ch = make_candidate_headers(candidate["id"])
        set_clock("2026-12-01T00:00:00Z")
        summary = validate_success(api.get_candidate_summary(candidate["id"], ch))
        # Both reports re-tier to 50% against 2026-12-01: 20 + 20.
        assert summary["projected_credited_hours"] == 40
        # R1's locked tier survives the clock crossing.
        assert summary["locked_credited_hours"] == 40
        report = validate_success(api.get_experience_report(r1["id"], ch))
        assert_experience_report(report)
        assert report["credit_pct"] == FULL_CREDIT_PCT
        assert report["status"] == "SUBMITTED"


class TestPerReportRoundingThenSum:
    def _setup_two_half_credit_reports(self, api):
        """Two PROGRAMMING_ANALYSIS reports (7h and 9h) submitted at
        2026-09-01, both locking the 50% tier."""
        candidate, supervisor = _registry(api)
        set_clock(LOGICAL_CLOCK_START_ISO)
        r1 = create_draft_report(
            candidate, supervisor, "PROGRAMMING_ANALYSIS", 7,
            "2025-05-01", "2025-06-30",
        )
        submit_report(candidate, r1["id"])
        r2 = create_draft_report(
            candidate, supervisor, "PROGRAMMING_ANALYSIS", 9,
            "2025-03-01", "2025-04-30",
        )
        submit_report(candidate, r2["id"])
        return candidate, supervisor, r1, r2

    def test_verify_stamps_per_report_rounded_hours(self, api):
        """PRD §2.7: "Wherever a crediting calculation produces a fraction,
        the result is rounded half-up to the nearest whole hour — a value of
        3.5 becomes 4 — and the rounding is applied per individual experience
        report first; area totals and candidate totals then sum the
        already-rounded integers, never the unrounded products."

        Design: Difficulty/combinatorial_formula/experience_credit_per_report_rounding_then_sum
        """
        candidate, supervisor, r1, r2 = self._setup_two_half_credit_reports(api)
        v1 = verify_report(supervisor, r1["id"])
        v2 = verify_report(supervisor, r2["id"])
        assert v1["credit_pct"] == HALF_CREDIT_PCT and v1["credited_hours"] == 4, (
            "round_half_up(7 * 0.5) == round_half_up(3.5) == 4"
        )
        assert v2["credit_pct"] == HALF_CREDIT_PCT and v2["credited_hours"] == 5, (
            "round_half_up(9 * 0.5) == round_half_up(4.5) == 5"
        )

    def test_area_total_sums_rounded_integers(self, api):
        """PRD §2.7: "Wherever a crediting calculation produces a fraction,
        the result is rounded half-up to the nearest whole hour — a value of
        3.5 becomes 4 — and the rounding is applied per individual experience
        report first; area totals and candidate totals then sum the
        already-rounded integers, never the unrounded products."

        Design: Difficulty/combinatorial_formula/experience_credit_per_report_rounding_then_sum
        """
        candidate, supervisor, r1, r2 = self._setup_two_half_credit_reports(api)
        verify_report(supervisor, r1["id"])
        verify_report(supervisor, r2["id"])
        summary = validate_success(api.get_candidate_summary(
            candidate["id"], make_candidate_headers(candidate["id"]),
        ))
        # 4 + 5 == 9; the forbidden sum-then-round order would give
        # round_half_up(16 * 0.5) == 8.
        assert summary["area_progress"]["PROGRAMMING_ANALYSIS"] == 9
        assert summary["total_credited_hours"] == 9

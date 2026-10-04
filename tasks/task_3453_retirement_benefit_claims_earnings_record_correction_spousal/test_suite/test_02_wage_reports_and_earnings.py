"""Wage report posting: taxable-maximum headroom in created_at order, append-only
shape, and non-covered earnings exclusion."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_claim,
    assert_earnings_year,
    assert_wage_report,
    create_worker,
    earnings_year_row,
    file_claim,
    post_wage_report,
    validate_success,
)
from test_helpers import TEST_USERS

CS = TEST_USERS["claims_specialist_headers"]


class TestTaxableMaximum:
    def test_wage_report_taxable_max_chronological_cap(self, api, employer_headers):
        """PRD §3.1: "Reports for the same worker and year are credited strictly in
        `created_at` ascending order: each report's `posted_amount_cents` is the
        lesser of its reported `amount_cents` and the headroom remaining under that
        year's taxable maximum at the moment the report is reached in that
        ordering, so out-of-order creation still yields the `created_at`-ordered
        result. The taxable maximum starts at $120,000 for 1986 — that is,
        12,000,000 cents — and grows by $3,000 (300,000 cents) for each later
        year."

        Taxable maximum for 2023 = 12,000,000 + 300,000 * (2023 - 1986)
        = 23,100,000 cents; the second report posts only the 3,100,000 headroom.

        Design: Corner/entities/wage_report_taxable_max_chronological_cap
        """
        worker = create_worker(full_name="Capped Worker")
        first = post_wage_report(worker["id"], 2023, 20_000_000)
        second = post_wage_report(worker["id"], 2023, 5_000_000)
        assert_wage_report(first)
        assert_wage_report(second)
        assert first["posted_amount_cents"] == 20_000_000
        assert second["posted_amount_cents"] == 3_100_000, (
            f"second report credits only the remaining headroom, got {second['posted_amount_cents']}"
        )

        row = earnings_year_row(worker["id"], 2023)
        assert row is not None
        assert_earnings_year(row)
        assert row["posted_earnings_cents"] == 23_100_000, (
            "year caps at exactly TAXABLE_MAX(2023) = 23,100,000 cents"
        )

    def test_wage_report_immutable_common_fields_absent(self, api, employer_headers):
        """PRD §2.6: "a **wage report** is immutable once accepted, and a
        **recomputation event** is an append-only audit entry, so both carry only
        `id` and `created_at` — `updated_at` and `version` are absent from them."
        PRD §3.1: "A wage report is immutable once accepted: `POSTED` is its only
        status, and no update or delete exists."

        Design: Corner/entities/wage_report_immutable_common_fields_absent
        """
        worker = create_worker(full_name="Immutable Worker")
        post_wage_report(worker["id"], 2023, 1_000_000)

        reports = validate_success(api.list_worker_wage_reports(worker["id"], CS))
        assert len(reports) == 1
        report = reports[0]
        assert_wage_report(report)
        assert report["status"] == "POSTED"
        assert report["posted_amount_cents"] == 1_000_000


class TestNonCoveredEarnings:
    def test_noncovered_wage_report_tracked_but_never_indexed(self, api):
        """PRD §3.1: "Reports filed with `covered_employment` false do not add to
        that figure; their credited amounts accumulate into
        `noncovered_earnings_cents`, which is informational only and never enters
        the benefit computation."
        PRD §3.5: "Non-covered earnings never participate."

        Design: Corner/endpoints/noncovered_wage_report_tracked_but_never_indexed
        """
        worker = create_worker(full_name="Noncovered")
        post_wage_report(worker["id"], 2023, 900_000, covered_employment=False)

        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])
        assert entitled["aime_cents"] == 0, "non-covered earnings never enter AIME"
        assert entitled["pia_cents"] == 0

        row = earnings_year_row(worker["id"], 2023)
        assert row is not None
        assert row["posted_earnings_cents"] == 0
        assert row["noncovered_earnings_cents"] == 900_000

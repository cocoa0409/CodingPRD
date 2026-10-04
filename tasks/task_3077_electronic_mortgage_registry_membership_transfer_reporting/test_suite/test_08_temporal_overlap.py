"""Resource temporal overlap: half-open signer authority windows on a member,
and closed calendar-year equality on annual reports."""
import pytest

from test_helpers import (
    ADMIN,
    add_signer,
    api_client,
    create_active_member,
    create_member,
    create_signer_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSignerWindowOverlap:
    def test_touching_windows_are_clean_one_second_overlap_rejected(self, api):
        """PRD §3.1: "the new signer's half-open window must not intersect the
        window of any other signer of the same member, regardless of that other
        signer's status — two windows that merely touch at an endpoint, one
        closing exactly when the other opens, are clean and accepted; any
        positive-length overlap is rejected with `ERR_SIGNER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/signer_windows_touching_at_boundary_are_clean_exact_overlap_rejects
        """
        set_clock("2026-01-05T00:00:00Z")
        a = create_member(org_id="1000000")
        first = add_signer(
            a["id"],
            effective_from="2026-01-01T00:00:00Z",
            effective_until="2026-07-01T00:00:00Z",
        )

        # Adjacent: opens exactly when the first closes — clean under half-open.
        adjacent = validate_success(
            api.create_signer(
                a["id"],
                create_signer_payload(
                    effective_from="2026-07-01T00:00:00Z", role_scope="TRANSFER"
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "ACTIVE", adjacent

        # One second of overlap with the first window: rejected.
        resp = api.create_signer(
            a["id"],
            create_signer_payload(
                effective_from="2026-06-30T23:59:59Z", role_scope="TRANSFER"
            ),
            ADMIN,
        )
        assert resp.status_code == 409, resp.text
        validate_error(resp, "ERR_SIGNER_WINDOW_OVERLAP")

        reread = validate_success(api.get_signer(first["id"], ADMIN))
        assert reread["status"] == "ACTIVE", reread

    def test_open_ended_window_overlaps_any_later_window(self, api):
        """PRD §3.1: "The window is half-open: authority begins at
        `effective_from` inclusive and ends at `effective_until` exclusive, and a
        null `effective_until` means the authority is open-ended."
        PRD §3.1: "any positive-length overlap is rejected with
        `ERR_SIGNER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/signer_windows_touching_at_boundary_are_clean_exact_overlap_rejects
        """
        set_clock("2026-01-05T00:00:00Z")
        a = create_member(org_id="1000000")
        add_signer(a["id"], effective_from="2026-01-01T00:00:00Z")  # open-ended

        resp = api.create_signer(
            a["id"],
            create_signer_payload(effective_from="2026-02-01T00:00:00Z"),
            ADMIN,
        )
        assert resp.status_code == 409, resp.text
        validate_error(resp, "ERR_SIGNER_WINDOW_OVERLAP")


class TestAnnualReportYearBoundary:
    def test_adjacent_years_clean_same_year_duplicate_rejected(self, api):
        """PRD §3.6: "Exactly one `FINAL` report may exist for a given member and
        year: generating when one already exists fails with
        `ERR_DUPLICATE_ANNUAL_REPORT`."
        PRD §3.6: "`reporting_rate` is the count-based on-time transfer rate:
        ... when the member had no confirmed transfers in the year at all, the
        rate is vacuously 1.0."

        Design: Difficulty/resource_temporal_overlap/annual_report_year_boundary_adjacent_years_clean_same_year_rejects
        """
        set_clock("2026-12-31T00:00:00Z")
        a = create_active_member(org_id="1000000")

        rep26 = validate_success(
            api.create_annual_report(a["id"], {"report_year": 2026}, ADMIN),
            expected_status=201,
        )
        rep27 = validate_success(
            api.create_annual_report(a["id"], {"report_year": 2027}, ADMIN),
            expected_status=201,
        )
        assert rep27["report_year"] == 2027, rep27

        resp = api.create_annual_report(a["id"], {"report_year": 2026}, ADMIN)
        assert resp.status_code == 409, resp.text
        validate_error(resp, "ERR_DUPLICATE_ANNUAL_REPORT")

        reread = validate_success(api.get_annual_report(rep26["id"], ADMIN))
        assert reread["status"] == "FINAL", reread
        # No transfers at all: the rate is vacuously 1.0.
        assert reread["reporting_rate"] == pytest.approx(1.0), reread

    def test_distinct_members_may_each_hold_a_final_report_for_one_year(self, api):
        """PRD §3.6: "Exactly one `FINAL` report may exist for a given member and
        year: generating when one already exists fails with
        `ERR_DUPLICATE_ANNUAL_REPORT`."

        Design: Difficulty/resource_temporal_overlap/annual_report_year_boundary_adjacent_years_clean_same_year_rejects
        """
        set_clock("2026-12-31T00:00:00Z")
        a = create_active_member(org_id="1000000")
        b = create_active_member(org_id="1000001", org_id_type="LEI",
                                 member_type="INVESTOR")

        rep_a = validate_success(
            api.create_annual_report(a["id"], {"report_year": 2026}, ADMIN),
            expected_status=201,
        )
        rep_b = validate_success(
            api.create_annual_report(b["id"], {"report_year": 2026}, ADMIN),
            expected_status=201,
        )
        # The uniqueness scope is per member-year, not per year.
        assert rep_a["member_id"] == a["id"] and rep_b["member_id"] == b["id"]
        assert rep_a["id"] != rep_b["id"]

        rows, meta = validate_paginated(
            api.list_annual_reports(ADMIN, params={"report_year": 2026})
        )
        assert meta["total_count"] == 2, meta

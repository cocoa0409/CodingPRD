"""Community health index and the two-summing-readings boundary."""
import pytest

from test_helpers import (
    CLOCK_BASE,
    create_community,
    file_report,
    get_account,
    get_community,
    publish_post,
    report_rows,
    sanction_rows,
    set_clock,
    setup_restricted_community,
)


def _community_with_three_tier_one_reports():
    """One ACTIVE community holding three OPEN tier-1 reports on one post."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    post = publish_post(community_id, author_account_id="user-ap")
    for index, reason in enumerate(("SPAM", "HARASSMENT", "HATE_SPEECH")):
        file_report(community_id, content_source_type="POST", content_source_id=post["id"],
                    reporter_account_id=f"rep-{index + 1}", report_reason_code=reason,
                    resolution_tier=1)
    return community


class TestCommunityHealthIndex:

    def test_three_tier_one_reports_round_per_report(self, api):
        """PRD §3.5: "Three open tier-1 reports therefore produce an open-report
        weight of 0.99, because each contributes the rounded value of one divided
        by three, which is 0.33; summing the raw weights first and rounding the
        total once would produce 1.00, one hundredth higher, and that hundredth is
        exactly the gap that decides whether a community sitting on the 99.00
        health line stays on the right side of it."
        PRD §2.8: "the stored value is the rounded value — intermediate sums are
        not carried at full precision and then rounded once at the end unless a
        rule below says so explicitly."

        Design: Difficulty/dual_variant_calc/health_index_rounded_per_report
        """
        community = _community_with_three_tier_one_reports()
        community_id = community["id"]

        fresh = get_community(community_id)
        assert fresh["open_report_weight"] == pytest.approx(0.99, abs=0.001)
        assert fresh["health_index"] == pytest.approx(99.01, abs=0.001)
        assert fresh["health_index"] != pytest.approx(99.00, abs=0.001)
        assert fresh["state"] == "ACTIVE"

        open_reports = report_rows(community_id, params={"status": "OPEN"})
        assert len(open_reports) == 3

    def test_three_tier_one_reports_are_counted_per_report(self, api):
        """PRD §3.5: "First, for every `OPEN` report, a tier weight is selected —
        1.0 for a tier-1 report, 1.5 for tier 2 and 2.0 for tier 3 — divided by
        3, and rounded half-up to two decimal places to give that report's
        effective open-report weight; the community's `open_report_weight` is the
        sum of those per-report values. Reports that are `RESOLVED`,
        `RESOLVED_LOCKED` or `DISMISSED` are excluded".
        PRD §3.3: "The `resolution_tier` is 1, 2 or 3, and tier 3 is a sitewide
        policy floor".

        Design: Difficulty/dual_variant_calc/health_index_rounded_per_report
        """
        community = _community_with_three_tier_one_reports()
        community_id = community["id"]

        rows = report_rows(community_id, params={"status": "OPEN"})
        assert len(rows) == 3
        for row in rows:
            assert row["resolution_tier"] == 1
            assert row["status"] == "OPEN"

        community_after = get_community(community_id)
        # 100.00 - 3 * round_half_up(1.0 / 3, 2) = 100.00 - 0.99 = 99.01.
        assert community_after["open_report_weight"] == pytest.approx(0.99, abs=0.001)
        assert community_after["health_index"] == pytest.approx(99.01, abs=0.001)


class TestSanctionIndexAndPostureGate:

    def test_aged_uncounted_sanction_counts_two_thirds(self, api):
        """PRD §3.4: "The numerator counts every `AccountSanction` row for the
        subject account that is `ACTIVE` and that satisfies either of two
        disjuncts: it is counted account-wide, meaning
        `account_wide_enforcement_counted` is true; or it is not counted
        account-wide, meaning that flag is false, and at least 30 days have
        elapsed between its `sanction_date_utc` and the logical clock."
        PRD §3.4: "on an account holding three sanction rows of which one is
        counted account-wide and one is not counted but is at least 30 days old,
        the index is two thirds, which is 0.67 displayed".

        Design: Difficulty/dual_variant_calc/enforcement_tier_fractional_index
        """
        state = setup_restricted_community(account_id="u-target")
        account = get_account("u-target")

        assert account["account_sanction_index"] == pytest.approx(0.67, abs=0.001)
        assert account["account_sanction_index"] != pytest.approx(0.33, abs=0.001)
        assert state["community_id"]
        assert len(sanction_rows("u-target", params={"status": "ACTIVE"})) == 3

    def test_sanction_index_crosses_the_restriction_gate(self, api):
        """PRD §3.8: "When an account-wide sanction recomputes the sanction index
        for the decision's subject community and the recomputed index — read in
        the pinned form described in §3.4, with the unrounded ratio compared
        against the threshold rather than the displayed two-decimal value — is at
        least 0.60, the community moves from `ACTIVE` to `RESTRICTED`."
        PRD §3.4: "`karma_points` starts at 100 and loses 3 for each distinct
        community in which the account holds a `MUTE_ISSUED` or `BAN_ISSUED`
        sanction whose `status` is `ACTIVE`".

        Design: Difficulty/dual_variant_calc/enforcement_tier_fractional_index
        """
        state = setup_restricted_community(account_id="u-target")
        community = get_community(state["community_id"])

        assert community["state"] == "RESTRICTED"
        assert community["state"] != "ACTIVE"
        account = get_account("u-target")
        # One distinct community holds an ACTIVE MUTE or BAN: 100 - 3 = 97.
        assert account["karma_points"] == 97
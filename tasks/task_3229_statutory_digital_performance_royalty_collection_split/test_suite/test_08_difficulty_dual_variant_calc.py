"""Difficulty queue A: dual_variant_calc — two variants of the same rule produce
different computed amounts on the same domain."""
from test_helpers import (
    create_active_licensee,
    create_effective_schedule,
    create_report_with_lines,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_auditor_headers,
    make_royalty_ops_headers,
    open_audit_case,
    setup_march_audit_scenario,
    submit_and_accept_report,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()


def _paid_first_report(api, lic_id, perfs, period_start, period_end):
    report, _ = create_report_with_lines(
        lic_id,
        [{"isrc": "NM-A", "track_title": "a", "artist_name": "a",
          "performance_count": perfs}],
        period_start, period_end,
    )
    accepted = submit_and_accept_report(report["id"], lic_id)
    liability = validate_success(
        api.compute_liability(
            report["id"],
            {"expected_usage_report_version": accepted["version"]},
            OPS,
        ),
        expected_status=201,
    )
    validate_success(api.bill_liability(liability["id"], OPS))
    paid = validate_success(api.record_liability_payment(liability["id"], OPS))
    return report, paid


class TestMinimumFeeVariants:
    def test_first_liability_uses_per_period_minimum(self, api):
        """PRD §3.5: "If this liability is the first liability computed for this
        licensee in the calendar year of the report's `period_start`, the mode
        is PER_PERIOD_MINIMUM and `minimum_fee_cents` is the schedule's full
        annual `min_fee_cents`."
        PRD §3.5: "Step three sets `amount_due_cents` to the greater of the
        gross and the minimum fee."

        Design: Difficulty/dual_variant_calc/royalty_liability_per_period_vs_ytd_minimum_fee
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="StreamCo")
        _, paid = _paid_first_report(
            api, lic["id"], 10000,
            "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z",
        )
        assert paid["minimum_fee_cents"] == 100000
        assert paid["gross_performance_royalty_cents"] == 26
        assert paid["amount_due_cents"] == 100000
        assert paid["admin_fee_cents"] == 0
        assert paid["distributable_pool_cents"] == 100000

    def test_second_liability_uses_ytd_minimum_fee(self, api):
        """PRD §3.5: "For any subsequent liability in the same calendar year —
        including a recompute after amendment — the mode is YTD_MINIMUM_FEE and
        `minimum_fee_cents` is the schedule's `min_fee_cents` minus the
        licensee's annual minimum-fee paid-to-date accumulator for that calendar
        year, floored at zero."
        PRD §3.5: "When the gross is at least the minimum fee, `admin_fee_cents`
        is 5 percent of the gross, rounded half-up to whole cents."
        PRD §3.5: "Step five sets `distributable_pool_cents` to the amount due
        minus the admin fee."

        Design: Difficulty/dual_variant_calc/royalty_liability_per_period_vs_ytd_minimum_fee
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="StreamCo")
        _paid_first_report(
            api, lic["id"], 10000,
            "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z",
        )
        # Second report in the same calendar year: 5000 perfs -> gross 13c.
        report_b, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-B", "track_title": "b", "artist_name": "b",
              "performance_count": 5000}],
            "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z",
        )
        accepted_b = submit_and_accept_report(report_b["id"], lic["id"])
        liability_b = validate_success(
            api.compute_liability(
                report_b["id"],
                {"expected_usage_report_version": accepted_b["version"]},
                OPS,
            ),
            expected_status=201,
        )
        assert liability_b["gross_performance_royalty_cents"] == 13
        assert liability_b["minimum_fee_cents"] == 0
        assert liability_b["amount_due_cents"] == 13
        assert liability_b["admin_fee_cents"] == 1
        assert liability_b["distributable_pool_cents"] == 12


class TestAuditAssessmentComposition:
    def test_assessment_is_full_loading_not_declared_only(self, api):
        """PRD §3.8: "The declared underpayment is the sum of the positive deltas
        only — under-reporting counts, over-reporting does not offset. The final
        `assessed_underpayment_cents` is the declared underpayment plus a
        penalty of 15 percent of the declared underpayment, rounded half-up,
        plus a flat audit cost recovery of 50000 cents."

        Design: Difficulty/dual_variant_calc/audit_assessment_declared_only_vs_penalty_cost_loading
        """
        scenario = setup_march_audit_scenario(legal_name="BigStream")
        audit = scenario["audit"]
        assert audit["audit_status"] == "FINDINGS_ISSUED"
        # declared: (50M x 2600 / 1e6) - 104000 = 130000 - 104000 = 26000
        # recomputed amount due = max(130000, max(0, 100000-104000)) = 130000
        # assessment = 26000 + round_half_up(0.15 x 26000) + 50000
        #            = 26000 + 3900 + 50000 = 79900
        assert audit["assessed_underpayment_cents"] == 79900
        assert audit["assessed_underpayment_cents"] != 26000, (
            "assessment must include the penalty and cost recovery, not the "
            "declared underpayment alone"
        )

    def test_assessment_zero_delta_still_carries_cost_recovery(self, api):
        """PRD §3.8: "The declared underpayment is the sum of the positive deltas
        only — under-reporting counts, over-reporting does not offset. The final
        `assessed_underpayment_cents` is the declared underpayment plus a
        penalty of 15 percent of the declared underpayment, rounded half-up,
        plus a flat audit cost recovery of 50000 cents."

        Design: Difficulty/dual_variant_calc/audit_assessment_declared_only_vs_penalty_cost_loading
        """
        # True performances equal to reported: declared delta is zero; the
        # penalty is zero; only the flat cost recovery remains.
        scenario = setup_march_audit_scenario(
            legal_name="FlatAuditCo",
            declared_true_performances=40000000,
        )
        audit = scenario["audit"]
        assert audit["audit_status"] == "FINDINGS_ISSUED"
        assert audit["assessed_underpayment_cents"] == 50000

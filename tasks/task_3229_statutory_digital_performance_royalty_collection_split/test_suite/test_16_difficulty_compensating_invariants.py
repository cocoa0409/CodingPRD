"""Difficulty queue A: compensating_invariant — conserved quantities across
forward action + compensating action pairs."""
from test_helpers import (
    ApiErrorId,
    PAST_SCHEDULED_FOR,
    create_active_licensee,
    create_effective_schedule,
    create_pool,
    create_report_with_lines,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_auditor_headers,
    make_royalty_ops_headers,
    setup_march_audit_scenario,
    submit_and_accept_report,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()


class TestAmendRebatchConservation:
    def test_amend_reverses_planned_batch_and_recomputes_identical_liability(self, api):
        """PRD §3.4: "Amending an ACCEPTED report has two side effects: if a
        liability exists for the report, it is recomputed under the
        year-to-date minimum-fee mode described in §3.5, and when the
        recomputed `amount_due_cents` changes, the licensee's annual
        minimum-fee paid-to-date ledger is reconciled; and any distribution
        batch for the report still in PLANNED status is cancelled, flipping it
        to REVERSED, so stale splits cannot execute against amended data."
        PRD §3.6: "No funds move on a reversal, and the report may be re-batched
        after re-acceptance."

        Design: Difficulty/compensating_invariant/amend_rebatch_preserves_liability_conservation
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="ConsvCo")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-C1", "track_title": "c1", "artist_name": "c1",
              "performance_count": 5000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        pool = create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        lh = make_licensee_headers(lic["id"])
        amended = validate_success(api.amend_usage_report(report["id"], lh))
        assert amended["report_status"] == "AMENDED"
        batch_now = validate_success(api.get_distribution_batch(batch["id"], OPS))
        assert batch_now["batch_status"] == "REVERSED"
        liab_now = validate_success(
            api.get_royalty_liability(liability["id"], OPS)
        )
        assert liab_now["amount_due_cents"] == 100000
        assert liab_now["distributable_pool_cents"] == 100000
        pool_now = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_now["accrued_unmatched_cents"] == 0

    def test_amend_rejected_report_returns_to_draft_without_batch_side_effect(self, api):
        """PRD §3.4: "Rejection is not final. The Licensee may amend a REJECTED
        report, cycling it back to `DRAFT` and reopening it for edit and
        resubmission."

        Design: Difficulty/compensating_invariant/amend_rebatch_preserves_liability_conservation
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="ConsvCo2")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-C2", "track_title": "c2", "artist_name": "c2",
              "performance_count": 5000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        validate_success(api.submit_usage_report(report["id"], lh))
        rejected = validate_success(
            api.reject_usage_report(report["id"], {"reason": "incomplete"}, OPS)
        )
        assert rejected["report_status"] == "REJECTED"
        amended = validate_success(api.amend_usage_report(report["id"], lh))
        assert amended["report_status"] == "DRAFT"


class TestAuditRecoveryConservation:
    def test_recovery_over_assessment_rejected_then_exact_full_settles(self, api):
        """PRD §3.8: "The cumulative `recovered_cents` — this payment plus prior
        recoveries — must never exceed `assessed_underpayment_cents`; a payment
        that would exceed the assessment is rejected with
        `ERR_RECOVERY_EXCEEDS_ASSESSMENT` (HTTP 409)."
        PRD §3.8: "When a recovery is recorded with `final` set to true, the
        case moves `FINDINGS_ISSUED` → `SETTLED` and the settlement cascade
        fires: if the total recovered equals the assessment, the licensee is
        unaffected"

        Design: Difficulty/compensating_invariant/audit_recovery_conserves_assessment_balance
        """
        scenario = setup_march_audit_scenario(legal_name="BalCo")
        lic = scenario["licensee"]
        audit = scenario["audit"]
        assessed = audit["assessed_underpayment_cents"]
        err = api.record_audit_recovery(
            audit["id"], {"amount_cents": assessed + 1, "final": False},
            make_royalty_auditor_headers("auditor-two"),
        )
        validate_error(err, ApiErrorId.ERR_RECOVERY_EXCEEDS_ASSESSMENT.value)
        settled = validate_success(
            api.record_audit_recovery(
                audit["id"], {"amount_cents": assessed, "final": True},
                make_royalty_auditor_headers("auditor-two"),
            )
        )
        assert settled["audit_status"] == "SETTLED"
        assert settled["recovered_cents"] == assessed
        assert (
            settled["assessed_underpayment_cents"] - settled["recovered_cents"]
        ) == 0
        lic_now = validate_success(api.get_licensee(lic["id"], ADMIN))
        assert lic_now["license_status"] == "ACTIVE"

    def test_partial_recovery_keeps_case_open_and_blocks_close(self, api):
        """PRD §3.8: "The cumulative `recovered_cents` — this payment plus prior
        recoveries — must never exceed `assessed_underpayment_cents`; a payment
        that would exceed the assessment is rejected with
        `ERR_RECOVERY_EXCEEDS_ASSESSMENT` (HTTP 409)."
        PRD §3.8: "An auditor closes a FINDINGS_ISSUED case only when
        `assessed_underpayment_cents` is zero or has been fully recovered;
        otherwise the close is rejected with `ERR_AUDIT_NOT_SETTLABLE`
        (HTTP 409)."

        Design: Difficulty/compensating_invariant/audit_recovery_conserves_assessment_balance
        """
        scenario = setup_march_audit_scenario(legal_name="BalCo2")
        audit = scenario["audit"]
        assessed = audit["assessed_underpayment_cents"]
        updated = validate_success(
            api.record_audit_recovery(
                audit["id"], {"amount_cents": assessed // 2, "final": False},
                make_royalty_auditor_headers("auditor-two"),
            )
        )
        assert updated["audit_status"] == "FINDINGS_ISSUED"
        assert updated["recovered_cents"] == assessed // 2
        err = api.close_audit_case(
            audit["id"], make_royalty_auditor_headers("auditor-two"),
        )
        validate_error(err, ApiErrorId.ERR_AUDIT_NOT_SETTLABLE.value)

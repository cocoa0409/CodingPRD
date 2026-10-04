"""Corner coverage: calculations — PRC filtering, SB goal zero-guard, audit materiality."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_price_list,
    create_audit,
    create_sales_report,
    setup_active_chain,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestPrcAccumulatorFiltering:
    def test_superseded_list_lines_excluded(self, api):
        """PRD §3.4: "Lists in DRAFT, SUBMITTED, SUPERSEDED, or REJECTED
        status are excluded."
        PRD §3.3: "When the activation succeeds while a sibling list on the
        same vehicle is ACTIVE, that sibling is atomically moved to SUPERSEDED
        and the vehicle's PRC accumulator is recomputed against only the newly
        active list."

        Design: Corner/calculations/prc_accumulator_excludes_superseded_lists
        """
        _, _, vehicle, price_list = setup_active_chain()
        p2 = create_active_price_list(
            vehicle["id"],
            lines=[{"sku": "SW-1", "basis_price_cents": 20000,
                    "offered_price_cents": 11000, "origin_country": "US"}],
        )
        p1 = validate_success(api.get_price_list(price_list["id"], CM))
        assert p1["status"] == "SUPERSEDED"
        p2 = validate_success(api.get_price_list(p2["id"], CM))
        assert p2["status"] == "ACTIVE"
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        # Nothing delivered yet: (20000 - 11000) * 0 = 0.
        assert vehicle["prc_accumulator_cents"] == 0


class TestSbGoalZeroGuard:
    def test_zero_sales_trivially_meets_goal(self, api):
        """PRD §3.8: "when the report's total_sales_cents is zero,
        sb_goal_met is trivially true; otherwise sb_goal_met is true exactly
        when total_sb_subcontract_cents is at least the round-half-up
        integer-cents product of the agreement's small_business_goal_pct
        multiplied by the report's total_sales_cents."

        Design: Corner/calculations/sb_goal_attainment_zero_sales_trivially_met
        """
        _, agreement, _, _ = setup_active_chain(
            agreement_overrides={"small_business_goal_pct": 0.50},
        )
        report = create_sales_report(agreement["id"], period_label="2026-09")
        resp = api.finalize_sales_report(report["id"], FIN)
        report = validate_success(resp)
        assert report["status"] == "FINALIZED"
        assert report["total_sales_cents"] == 0
        assert report["sb_goal_met"] is True


class TestAuditMaterialityBoundary:
    def _setup_active_agreement(self, api):
        _, agreement, _, _ = setup_active_chain()
        return agreement

    def test_variance_equal_materiality_not_material(self, api):
        """PRD §3.9: "The auditor issues a finding while the audit is OPEN and
        the variance strictly exceeds the materiality threshold of 250000
        cents ($2,500.00): variance exactly equal to the threshold does not
        support a finding, and the issuance is rejected with
        ERR_AUDIT_NOT_MATERIAL."

        Design: Corner/calculations/audit_variance_materiality_boundary
        """
        agreement = self._setup_active_agreement(api)
        # No finalized reports -> disclosed 0; attestation 250000 -> variance 250000.
        audit = create_audit(agreement["id"], mfc_attestation_cents=250000)
        resp = api.issue_finding(audit["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_MATERIAL)

    def test_variance_one_cent_over_materiality_issued(self, api):
        """PRD §3.9: "The auditor issues a finding while the audit is OPEN and
        the variance strictly exceeds the materiality threshold of 250000
        cents ($2,500.00): variance exactly equal to the threshold does not
        support a finding, and the issuance is rejected with
        ERR_AUDIT_NOT_MATERIAL."
        PRD §3.9: "A successful finding moves the audit to FINDING_ISSUED and
        cascades: the agreement's status moves from ACTIVE to SUSPENDED, with
        all the downstream vehicle and teaming suspensions that implies."

        Design: Corner/calculations/audit_variance_materiality_boundary
        """
        agreement = self._setup_active_agreement(api)
        audit = create_audit(agreement["id"], mfc_attestation_cents=250001)
        resp = api.issue_finding(audit["id"], AUD)
        audit = validate_success(resp)
        assert audit["status"] == "FINDING_ISSUED"

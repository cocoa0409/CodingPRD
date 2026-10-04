"""Difficulty rule: dual_variant_calc."""
from test_helpers import (
    ADMIN,
    api_client,
    create_certification_payload,
    create_employee_payload,
    create_licensee_payload,
    get_success_data,
    make_inspector_headers,
    make_licensee_manager_headers,
    setup_active_agreement,
    setup_operating_store,
    validate_success,
)
from test_helpers.fixtures import (
    create_royalty_statement_payload,
    create_sales_report_payload,
    finalize_sales_report,
    create_sales_report,
    generate_statement,
    set_clock,
)


def _build_report_pair(store_id, lic_id):
    """R1 [09-01, 09-14] net 10000000 finalized at clock 2026-09-10;
    R2 [09-15, 09-30] net 5000000 left DRAFT until the clock moves."""
    r1 = create_sales_report(
        store_id, lic_id,
        period_start_date="2026-09-01", period_end_date="2026-09-14",
        gross_sales_cents=12000000, returns_cents=1000000,
        loyalty_redemption_cents=1000000,
    )
    finalize_sales_report(r1["id"], lic_id)
    r2 = create_sales_report(
        store_id, lic_id,
        period_start_date="2026-09-15", period_end_date="2026-09-30",
        gross_sales_cents=6000000, returns_cents=500000,
        loyalty_redemption_cents=500000,
    )
    return r1, r2


def _finalize_late_reports(r2_id, lic_id):
    """Finalize the late R2 report after its period ended (PRD §3.7: a report
    may be finalized while DRAFT; finalizing it twice would violate the
    DRAFT-only precondition)."""
    set_clock("2026-10-02T00:00:00Z")
    finalize_sales_report(r2_id, lic_id)
    set_clock("2026-10-05T00:00:00Z")


class TestRoyaltyCashVsAccrualLateReport:
    def test_accrual_recognizes_late_finalized_report(self):
        """PRD §3.7: "Under `ACCRUAL`, reports finalized at any time up to the
        generation clock count, even when finalized after the period ended;
        late-arriving truth is recognized."

        Design: Difficulty/dual_variant_calc/royalty_cash_vs_accrual_late_report
        """
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        agr_id = bundle["agreement"]["id"]
        _r1, r2 = _build_report_pair(store_id, lic_id)
        _finalize_late_reports(r2["id"], lic_id)
        stmt = generate_statement(
            agr_id, period_start_date="2026-09-01", period_end_date="2026-09-30")
        assert stmt["recognized_sales_cents"] == 15000000
        assert stmt["royalty_amount_cents"] == 450000

    def test_cash_excludes_late_finalized_report(self):
        """PRD §3.7: "Under `CASH`, only reports finalized on or before the
        statement period's final day count; a report finalized late exists at
        generation time but is excluded."

        Design: Difficulty/dual_variant_calc/royalty_cash_vs_accrual_late_report
        """
        set_clock()
        bundle = setup_operating_store(agreement_overrides={"royalty_basis": "CASH"})
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        agr_id = bundle["agreement"]["id"]
        _r1, r2 = _build_report_pair(store_id, lic_id)
        _finalize_late_reports(r2["id"], lic_id)
        stmt = generate_statement(
            agr_id, period_start_date="2026-09-01", period_end_date="2026-09-30")
        assert stmt["recognized_sales_cents"] == 10000000
        assert stmt["royalty_amount_cents"] == 300000


class TestCertificationAuditedVariantFlipsBoundaryPass:
    def _two_enrolled_certs(self):
        licensee = get_success_data(
            api_client.create_licensee(create_licensee_payload(), ADMIN))
        lic_headers = make_licensee_manager_headers(licensee["id"])
        certs = []
        for name in ("E1", "E2"):
            emp = get_success_data(api_client.create_employee(
                licensee["id"], create_employee_payload(full_name=name), lic_headers))
            cert = get_success_data(api_client.create_certification(
                emp["id"], create_certification_payload(), lic_headers))
            certs.append(cert)
        return licensee, certs

    def test_same_score_passes_raw_but_fails_audited(self):
        """PRD §3.6: "when `proctor_anomaly` is false the raw score is compared
        to 80; when true, an anomaly penalty of 5 points is subtracted first,
        and the adjusted score is compared to 80."

        Design: Difficulty/dual_variant_calc/certification_audited_variant_flips_boundary_pass
        """
        _licensee, certs = self._two_enrolled_certs()
        proctor = make_inspector_headers("insp-P")
        resp_raw = api_client.record_certification_exam(
            certs[0]["id"], {"exam_score": 82, "proctor_anomaly": False}, proctor)
        raw = validate_success(resp_raw)
        resp_audited = api_client.record_certification_exam(
            certs[1]["id"], {"exam_score": 82, "proctor_anomaly": True}, proctor)
        audited = validate_success(resp_audited)
        assert raw["status"] == "EXAM_PASSED"
        assert raw["exam_score"] == 82 and raw["exam_attempts"] == 1
        assert audited["status"] == "ENROLLED"
        assert audited["exam_score"] == 82 and audited["exam_attempts"] == 1

    def test_audited_adjusted_boundary_at_85(self):
        """PRD §3.6: "The boundary consequence is sharp: scores of 80 through
        84 pass raw but fail under the anomaly flag."

        Design: Difficulty/dual_variant_calc/certification_audited_variant_flips_boundary_pass
        """
        _licensee, certs = self._two_enrolled_certs()
        proctor = make_inspector_headers("insp-P")
        resp_84 = api_client.record_certification_exam(
            certs[0]["id"], {"exam_score": 84, "proctor_anomaly": True}, proctor)
        below = validate_success(resp_84)
        resp_85 = api_client.record_certification_exam(
            certs[1]["id"], {"exam_score": 85, "proctor_anomaly": True}, proctor)
        at_boundary = validate_success(resp_85)
        assert below["status"] == "ENROLLED"
        assert at_boundary["status"] == "EXAM_PASSED"

"""Certificate money: the cash/accrual variant split and the two independent axes."""

from test_helpers import (
    assert_certificate,
    assert_expenditure_ceiling,
)
from test_helpers.constants import ISSUANCE_CLOCK
from test_helpers.fixtures import (
    file_progress_report,
    issue_certificate,
    refresh_applicant,
    refresh_certificate,
    refresh_health_service_area,
    seed_issued_certificate,
    seed_two_application_decided_cycle,
    set_clock,
)

FIRST_PERIOD = {
    "period_end_date": "2026-10-31",
    "disbursed_cents": 600000000,
    "obligated_cents": 300000000,
    "physical_completion_pct": 20,
}
SECOND_PERIOD = {
    "period_end_date": "2026-11-30",
    "disbursed_cents": 250000000,
    "obligated_cents": 100000000,
    "physical_completion_pct": 35,
}


def _two_certificates_after_identical_reports():
    """Issue a CASH and an ACCRUAL certificate and file the same two periods."""
    world = seed_two_application_decided_cycle()
    set_clock(ISSUANCE_CLOCK)
    certificate_a = issue_certificate(
        world["application_a"], expenditure_basis="CASH"
    )
    certificate_b = issue_certificate(
        world["application_b"], expenditure_basis="ACCRUAL"
    )

    file_progress_report(certificate_a, world["applicant_a"], **FIRST_PERIOD)
    file_progress_report(certificate_b, world["applicant_b"], **FIRST_PERIOD)
    certificate_a = refresh_certificate(certificate_a["id"])
    certificate_b = refresh_certificate(certificate_b["id"])
    file_progress_report(certificate_a, world["applicant_a"], **SECOND_PERIOD)
    file_progress_report(certificate_b, world["applicant_b"], **SECOND_PERIOD)

    world["certificate_a"] = refresh_certificate(certificate_a["id"])
    world["certificate_b"] = refresh_certificate(certificate_b["id"])
    return world


class TestCashVersusAccrualVariants:
    def test_identical_reports_diverge_on_the_governing_basis(self):
        """Both variants are stored on both rows; only the governing one bites.

        PRD §3.8: "From that set, `cumulative_expenditure_cash_cents` is the sum
        of `disbursed_cents` across the contributing reports, and
        `cumulative_expenditure_accrual_cents` is the sum of `disbursed_cents`
        plus `obligated_cents` across the same reports."
        PRD §3.8: "The **governing** figure is
        `cumulative_expenditure_accrual_cents` when the certificate's
        `expenditure_basis` is `ACCRUAL` and `cumulative_expenditure_cash_cents`
        when it is `CASH`."
        PRD §3.8: "Under `CASH` only the disbursements accumulate, giving a
        governing figure of 850000000, comfortably inside the limit, so
        `expenditure_status` stays `WITHIN_LIMIT`."
        PRD §3.8: "Under `ACCRUAL` the obligations accumulate alongside, giving
        1250000000, above the ceiling, so `expenditure_status` becomes
        `LIMIT_BREACHED` and the suspension cascade fires."

        Design: Difficulty/dual_variant_calc/certificate_expenditure_cash_vs_accrual_same_reports
        """
        world = _two_certificates_after_identical_reports()
        certificate_a = world["certificate_a"]
        certificate_b = world["certificate_b"]

        assert_certificate(certificate_a)
        assert_certificate(certificate_b)
        assert certificate_a["cumulative_expenditure_cash_cents"] == 850000000
        assert certificate_a["cumulative_expenditure_accrual_cents"] == 1250000000
        assert certificate_a["expenditure_ceiling_cents"] == 1050000000
        assert certificate_a["expenditure_status"] == "WITHIN_LIMIT"
        assert certificate_a["lifecycle_status"] == "ISSUED"

        assert certificate_b["cumulative_expenditure_cash_cents"] == 850000000
        assert certificate_b["cumulative_expenditure_accrual_cents"] == 1250000000
        assert certificate_b["expenditure_status"] == "LIMIT_BREACHED"
        assert_expenditure_ceiling(certificate_b)

    def test_only_the_accrual_certificate_suspends_and_earns_a_strike(self):
        """The breach suspends the accrual row and strikes only its applicant.

        PRD §3.8: "When instead the money axis reaches `LIMIT_BREACHED` and the
        certificate's `lifecycle_status` is `ISSUED` or `IMPLEMENTED`, that
        breached value is itself the cause of a lifecycle suspension:
        `lifecycle_status_before_suspension` is set to whatever the lifecycle
        status currently is, `lifecycle_status` becomes `SUSPENDED`, the
        certificate's `version` increases by 1, and the applicant's
        `compliance_strike_count` increases by 1 — which in turn is what can flip
        that applicant's `standing` to `RESTRICTED` at 2 strikes or `BARRED` at
        4."

        Design: Difficulty/dual_variant_calc/certificate_expenditure_cash_vs_accrual_same_reports
        """
        world = _two_certificates_after_identical_reports()

        assert world["certificate_b"]["lifecycle_status"] == "SUSPENDED"
        assert world["certificate_b"]["lifecycle_status_before_suspension"] == "ISSUED"
        assert world["certificate_a"]["lifecycle_status"] == "ISSUED"
        assert refresh_applicant(world["applicant_b"]["id"])[
            "compliance_strike_count"
        ] == 1
        assert refresh_applicant(world["applicant_a"]["id"])[
            "compliance_strike_count"
        ] == 0


class TestLifecycleAndExpenditureAxesAreIndependent:
    def test_money_axis_moves_while_the_lifecycle_axis_holds(self):
        """1020000000 accrual sits inside the tolerance band, so nothing suspends.

        PRD §3.8: "The money axis is then set from a three-way comparison:
        `expenditure_status` becomes `WITHIN_LIMIT` when the governing figure is
        less than or equal to `approved_expenditure_limit_cents`;
        `OVER_LIMIT_PENDING_AMENDMENT` when it exceeds the limit but is still
        less than or equal to `expenditure_ceiling_cents`; and `LIMIT_BREACHED`
        when it exceeds the ceiling."
        PRD §3.8: "Each of those writes increases the certificate's `version` by
        1 and leaves `lifecycle_status` untouched."

        Design: Difficulty/non_linear_state_machine/certificate_lifecycle_and_expenditure_axes_evolve_independently
        """
        world = seed_issued_certificate(certificate={"expenditure_basis": "ACCRUAL"})

        file_progress_report(
            world["certificate"],
            world["applicant"],
            period_end_date="2026-11-30",
            disbursed_cents=1020000000,
            obligated_cents=0,
            physical_completion_pct=40,
        )

        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["cumulative_expenditure_accrual_cents"] == 1020000000
        assert certificate["expenditure_ceiling_cents"] == 1050000000
        assert certificate["expenditure_status"] == "OVER_LIMIT_PENDING_AMENDMENT"
        assert certificate["lifecycle_status"] == "ISSUED"
        assert certificate["version"] > world["certificate"]["version"]

    def test_lifecycle_axis_reaches_implemented_with_the_money_axis_unchanged(self):
        """100 percent completion implements the project and moves the bed books.

        PRD §3.8: "When an accepted report leaves `latest_completion_pct` at
        exactly 100 and the certificate's `lifecycle_status` is `ISSUED`, the
        implementation axis advances to `IMPLEMENTED` with the certificate's
        `version` increased by 1, and the beds move in the planning area's books:
        `approved_unimplemented_beds` is decreased by the certificate's
        `authorized_bed_count` and `existing_licensed_beds` is increased by the
        same count."
        PRD §3.8: "The money axis is untouched by this transition."

        Design: Difficulty/non_linear_state_machine/certificate_lifecycle_and_expenditure_axes_evolve_independently
        """
        world = seed_issued_certificate(certificate={"expenditure_basis": "ACCRUAL"})
        report_1 = file_progress_report(
            world["certificate"],
            world["applicant"],
            period_end_date="2026-11-30",
            disbursed_cents=1020000000,
            obligated_cents=0,
            physical_completion_pct=40,
        )
        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["lifecycle_status"] == "ISSUED"

        report_2 = file_progress_report(
            certificate,
            world["applicant"],
            period_end_date="2026-12-31",
            disbursed_cents=0,
            obligated_cents=0,
            physical_completion_pct=100,
        )

        certificate = refresh_certificate(certificate["id"])
        assert certificate["lifecycle_status"] == "IMPLEMENTED"
        assert certificate["expenditure_status"] == "OVER_LIMIT_PENDING_AMENDMENT"
        assert certificate["latest_completion_pct"] == 100
        assert report_1["status"] == "ACCEPTED"
        assert report_2["status"] == "ACCEPTED"

        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["existing_licensed_beds"] == 82

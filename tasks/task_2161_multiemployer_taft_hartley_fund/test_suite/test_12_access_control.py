"""Authentication, role authorization and entity-backed resource ownership."""

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    UNKNOWN_IDS,
    ApiErrorId,
    create_board_motion_payload,
    create_employer,
    create_fund,
    create_fund_payload,
    create_payroll_audit_payload,
    make_employer_headers,
    make_headers_with_unknown_role,
    make_trustee_headers,
    open_withdrawal,
    read_fund,
    read_report,
    read_withdrawal,
    set_clock,
    setup_two_employers_one_filed_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]
AUDITOR = TEST_USERS["payroll_auditor_headers"]


def test_missing_headers_and_an_undeclared_role_are_both_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity
    in which the caller acts. If either header is absent, or if `X-User-Role` is
    not one of the five roles below spelled exactly as shown, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The five roles are `FundAdministrator`, `ContributingEmployer`,
    `Trustee`, `PayrollAuditor`, and `Actuary`."
    PRD §2.8: "1. **Authentication.** Both headers present and `X-User-Role` one
    of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/calls_missing_auth_headers_are_rejected_as_unauthenticated
    """
    set_clock()
    fund = create_fund(name="Auth Fund", ein="36-7000001")

    validate_error(
        api.get_fund(fund["id"], NO_AUTH_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        api.get_fund(UNKNOWN_IDS["fund"], NO_AUTH_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        api.run_collections(fund["id"], make_headers_with_unknown_role()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    assert read_fund(fund["id"])["collections_run_index"] == 0, "no sweep ran"


def test_every_exclusive_operation_turns_away_the_wrong_role(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not among
    the roles the target endpoint authorizes, the request is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.8: "2. **Role authorization.** The acting role appears in the
    endpoint's authorized list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §4: "The table below lists the HTTP surface only. Request and response
    shapes are deliberately not repeated here — they are introduced in the
    section 3 narratives where the business reason for each field appears."

    Design: Corner/rbac/cross_role_calls_are_rejected_with_role_not_permitted
    """
    set_clock()
    fund = create_fund(name="Role Matrix Fund", ein="36-7000002")
    employer = create_employer(fund["id"])
    assessment = open_withdrawal(fund["id"], employer["id"])

    validate_error(
        api.create_fund(
            create_fund_payload(name="Trustee Fund Attempt", ein="36-7000003"),
            make_trustee_headers(UNKNOWN_IDS["user"]),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    validate_error(
        api.create_payroll_audit(
            create_payroll_audit_payload(employer["id"], "2026-01", "2026-06"), ADMIN
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    validate_error(
        api.certify_withdrawal_assessment(assessment["id"], ADMIN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    assert read_withdrawal(assessment["id"])["status"] == "DRAFT"

    validate_error(
        api.create_board_motion(
            create_board_motion_payload(fund["id"], "LD_WAIVER", assessment["id"]), ADMIN
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    validate_error(
        api.run_collections(fund["id"], AUDITOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    assert read_fund(fund["id"])["collections_run_index"] == 0

    validate_error(
        api.list_motion_votes(AUDITOR), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
    )

    assert read_fund(fund["id"])["allocated_uvb_cents"] == 0


def test_an_employer_may_not_remit_against_another_employers_report(api):
    """PRD §2.1: "An entity-backed actor who targets a resource belonging to a
    different employer or a different trustee is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to filing a
    contribution report, remitting against one, responding to payroll-audit
    findings, requesting review of a withdrawal assessment, and paying an
    installment."
    PRD §2.1: "When `X-User-Role` is `ContributingEmployer`, `X-User-ID` is the
    `id` of the acting `Employer`; ownership checks on any resource that
    references an employer compare that resource's foreign-key field to
    `X-User-ID`."
    PRD §3.6: "A remittance exactly equal to the outstanding balance settles the
    report: `amount_remitted_cents` becomes `total_contributions_due_cents`,
    `paid_in_full_at` is stamped with the logical clock instant, and the payment
    state becomes `PAID_IN_FULL` — this same closing move is available from
    `UNPAID`, from `PARTIAL`, and from `DELINQUENT` alike, on identical terms."

    Design: Corner/rbac/employer_cannot_remit_against_another_employers_report
    """
    base = setup_two_employers_one_filed_report()
    report_id = base["report"]["id"]

    validate_error(
        api.remit_contribution_report(
            report_id, {"amount_cents": 82_550}, make_employer_headers(base["rival"]["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    untouched = read_report(report_id)
    assert untouched["payment_status"] == "UNPAID"
    assert untouched["amount_remitted_cents"] == 0

    settled = validate_success(
        api.remit_contribution_report(
            report_id, {"amount_cents": 82_550}, make_employer_headers(base["owner"]["id"])
        )
    )
    assert settled["payment_status"] == "PAID_IN_FULL"
    assert settled["amount_remitted_cents"] == 82550

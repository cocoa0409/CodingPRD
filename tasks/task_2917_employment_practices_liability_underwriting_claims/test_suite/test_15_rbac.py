"""Role admission, counsel ownership and policyholder read scoping."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null


def test_exclusive_write_endpoints_refuse_every_other_role(api):
    """Eight writes by the wrong role: all ERR_UNAUTHORIZED, and nothing is written.

    PRD: "The caller's role admitted by the endpoint → otherwise
    `ERR_UNAUTHORIZED` (403), on every endpoint."

    PRD: "At startup the logical clock reads `2026-08-01T00:00:00.000Z`, and it
    moves only when a `PlatformAdmin` sets it."

    Design: Corner/rbac/exclusive_write_endpoints_refuse_every_other_role
    """
    S.create_jurisdiction(api, "TX")
    applicant = S.create_applicant(
        api,
        legal_name="Vantage Mills LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )

    validate_error(
        api.create_jurisdiction(F.jurisdiction("CA"), U.UNDERWRITER), E.ERR_UNAUTHORIZED, 403
    )
    validate_error(
        api.create_rate_plan(F.rate_plan(name="Rogue Plan"), U.ADJUSTER), E.ERR_UNAUTHORIZED, 403
    )
    validate_error(
        api.create_panel_firm(
            F.panel_firm(
                name="Rogue Counsel LLP",
                tier=T.TIER_LOCAL,
                jurisdiction_codes=["TX"],
                partner_rate_cents_per_hour=70000,
                associate_rate_cents_per_hour=43000,
                paralegal_rate_cents_per_hour=16000,
                capacity_open_matters=1,
            ),
            U.UNDERWRITER,
        ),
        E.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.set_clock("2026-09-01T00:00:00.000Z", U.UW_MANAGER), E.ERR_UNAUTHORIZED, 403
    )
    validate_error(
        api.create_applicant(
            F.applicant(
                legal_name="Rogue Holdings LLC",
                total_headcount=10,
                prior_year_separations=0,
                jurisdiction_headcounts=[{"code": "TX", "headcount": 10}],
                primary_jurisdiction_code="TX",
            ),
            U.ADJUSTER,
        ),
        E.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.patch_applicant(applicant["id"], {"prior_year_separations": 9}, U.UW_MANAGER),
        E.ERR_UNAUTHORIZED,
        403,
    )
    # Role admission at priority 2 precedes path resolution at priority 4, so the
    # unminted rate_plan_id never gets a chance to report ERR_RATE_PLAN_NOT_FOUND.
    validate_error(
        api.create_assessment(
            F.assessment(
                applicant["id"],
                "00000000-0000-4000-8000-000000000002",
                applicant["version"],
                requested_aggregate_limit_cents=10000000,
                requested_retention_cents=2500000,
                third_party_coverage_requested=None,
            ),
            U.UW_MANAGER,
        ),
        E.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(api.list_panel_firms(U.UNDERWRITER), E.ERR_UNAUTHORIZED, 403)

    unchanged = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(
        unchanged, {"prior_year_separations": 4, "version": applicant["version"]}
    )

    codes, _meta = validate_paginated(api.list_jurisdictions(U.ADMIN))
    assert [row["code"] for row in codes] == ["TX"]
    plans, _meta = validate_paginated(api.list_rate_plans(U.ADMIN))
    assert [row["name"] for row in plans] == []
    firms, _meta = validate_paginated(api.list_panel_firms(U.ADMIN))
    assert [row["name"] for row in firms] == []

    # The clock never moved: an equal re-set is permitted, an earlier one would not be.
    get_success_data(api.set_clock("2026-08-01T00:00:00.000Z", U.ADMIN))


def test_panel_counsel_can_only_bill_its_own_assignments(api):
    """Firm B may read the matter but may neither invoice it nor dispute firm A's bill.

    PRD: "a counsel principal may only submit or dispute invoices on defense
    assignments whose `panel_firm_id` equals its own identifier, and any other
    attempt is refused with `ERR_NOT_ASSIGNED_COUNSEL` (HTTP 403)"

    Design: Corner/rbac/panel_counsel_can_only_bill_its_own_assignments
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    firm_a = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    firm_b = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy_id = S.bind_policy(api, assessment["id"])["id"]
    claim = S.accepted_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=6000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-06T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm_a["id"],
    )

    period = {
        "period_start": "2026-08-06T00:00:00.000Z",
        "period_end": "2026-09-05T00:00:00.000Z",
        "partner_hours": None,
        "associate_hours": 10.0,
        "paralegal_hours": None,
        "block_billed_hours": None,
        "expenses_cents": None,
    }
    validate_error(
        api.submit_invoice(assignment["id"], F.invoice(**period), U.panel_counsel(firm_b["id"])),
        E.ERR_NOT_ASSIGNED_COUNSEL,
        403,
    )
    _rows, meta = validate_paginated(
        api.list_invoices(U.ADJUSTER, {"defense_assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 0, "the refused submission must not have created an invoice"

    invoice = get_success_data(
        api.submit_invoice(assignment["id"], F.invoice(**period), U.panel_counsel(firm_a["id"])),
        201,
    )
    assert invoice["status"] == T.INVOICE_SUBMITTED
    assert_null(invoice, ["billed_fees_cents", "allowed_amount_cents", "audited_by_user_id"])

    audited = get_success_data(api.audit_invoice(invoice["id"], U.ADJUSTER))
    assert_fields(
        audited,
        {
            "status": T.INVOICE_UNDER_AUDIT,
            "billed_fees_cents": 510000,
            "allowed_amount_cents": 450000,
        },
    )

    validate_error(
        api.dispute_invoice(
            invoice["id"], F.invoice_dispute(associate_hours=8.0), U.panel_counsel(firm_b["id"])
        ),
        E.ERR_NOT_ASSIGNED_COUNSEL,
        403,
    )
    still = get_success_data(api.get_invoice(invoice["id"], U.ADJUSTER))
    assert_fields(
        still, {"status": T.INVOICE_UNDER_AUDIT, "allowed_amount_cents": 450000}
    )


def test_a_policyholder_contact_sees_only_its_own_applicants_rows(api):
    """Own applicant and own policy read fine; every cross-applicant read is 403.

    PRD: "When `X-User-Role` is `PolicyholderContact`, `X-User-ID` is the `id` of
    the acting `Applicant`; every read that principal performs is scoped to rows
    belonging to that applicant, and a read of another applicant's applicant
    record, risk-management service, exposure assessment or policy is refused
    with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/a_policyholder_contact_sees_only_its_own_applicants_rows
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]

    def underwrite(legal_name):
        applicant = S.create_applicant(
            api,
            legal_name=legal_name,
            total_headcount=40,
            prior_year_separations=4,
            jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
            primary_jurisdiction_code="TX",
        )
        assessment = S.create_approved_assessment(
            api,
            applicant["id"],
            plan_id,
            requested_aggregate_limit_cents=10000000,
            requested_retention_cents=2500000,
            third_party_coverage_requested=None,
        )
        policy = S.bind_policy(api, assessment["id"])
        return applicant["id"], assessment["id"], policy["id"]

    app_a, asm_a, pol_a = underwrite("Alder Creek Dairy LLC")
    app_b, _asm_b, pol_b = underwrite("Bramble Fields Nursery LLC")
    contact_b = U.policyholder_contact(app_b)

    own = get_success_data(api.get_applicant(app_b, contact_b))
    assert own["legal_name"] == "Bramble Fields Nursery LLC"

    own_policy = get_success_data(api.get_policy(pol_b, contact_b))
    assert_fields(own_policy, {"status": T.POLICY_ACTIVE, "applicant_id": app_b})

    # 403, not 404: the rows exist, they simply belong to somebody else.
    validate_error(api.get_applicant(app_a, contact_b), E.ERR_OWNERSHIP_MISMATCH, 403)
    validate_error(api.get_assessment(asm_a, contact_b), E.ERR_OWNERSHIP_MISMATCH, 403)
    validate_error(api.get_policy(pol_a, contact_b), E.ERR_OWNERSHIP_MISMATCH, 403)

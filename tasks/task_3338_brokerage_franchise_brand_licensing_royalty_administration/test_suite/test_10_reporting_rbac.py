"""Monthly reporting, agreement liveness, termination/suspension guards, RBAC."""
from test_helpers import (
    validate_error, validate_paginated, validate_success, get_success_data,
    setup_active_agreement, setup_assessed_period, setup_deidentifying_agreement,
    open_default, submit_gci_report, assess_period,
    create_agent_count_report_payload, create_brand_payload,
    create_brokerage_payload, create_market,
    ApiErrorId, TEST_USERS, make_franchisee_admin_headers,
)

OPS = TEST_USERS["franchisor_ops_headers"]
AUDITOR = TEST_USERS["brand_auditor_headers"]


def test_agent_count_report_is_append_only_without_version(api):
    """PRD §2.4: "Three resources are deliberately lighter. `AgentCountReport`,
    `GCIReport`, and `AdFundLedgerEntry` carry only `id` and `created_at`; both
    `updated_at` and `version` are absent on these entities, because they are
    append-only records that are never modified after creation."

    Design: Corner/entities/agent_count_report_immutable_no_version_field
    """
    ctx = setup_active_agreement()
    admin = make_franchisee_admin_headers(ctx["brokerage"]["id"])
    report = validate_success(
        api.create_agent_count_report(
            ctx["agreement"]["id"],
            create_agent_count_report_payload(period_month="2027-01", active_agent_count=7),
            admin,
        ),
        expected_status=201,
    )
    assert report["id"]
    assert report["created_at"]
    assert "version" not in report
    assert "updated_at" not in report

    reports, _meta = validate_paginated(
        api.list_agent_count_reports(ctx["agreement"]["id"], admin)
    )
    assert reports[0]["id"] == report["id"]
    assert "version" not in reports[0]
    assert "updated_at" not in reports[0]


def test_gci_report_rejected_once_agreement_left_live_states(api):
    """PRD §3.4: "Reports of either kind, and royalty assessments as well, are
    only accepted while the agreement is `ACTIVE` or `SUSPENDED`; filing against
    an agreement in any other status fails with `ERR_AGREEMENT_NOT_LIVE`."

    Design: Corner/state_machines/terminated_agreement_rejects_gci_report
    """
    ctx = setup_deidentifying_agreement()
    resp = api.create_gci_report(
        ctx["agreement"]["id"], {"period_month": "2027-02", "gci_cents": 100}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_LIVE)


def test_second_gci_report_for_same_month_rejected(api):
    """PRD §3.4: "Within one agreement, each `period_month` may be reported at
    most once per report type: a second `AgentCountReport` or `GCIReport` for the
    same agreement and month is rejected with `ERR_DUPLICATE_REPORT`."

    Design: Corner/validations/duplicate_gci_report_rejected
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 5_000)
    resp = api.create_gci_report(ag_id, {"period_month": "2027-01", "gci_cents": 6_000}, OPS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)


def test_assessment_without_gci_report_rejected(api):
    """PRD §3.5: "Assessment is impossible without the report — if no `GCIReport`
    exists for the requested month, the request fails with
    `ERR_GCI_REPORT_MISSING`"

    Design: Corner/validations/assessment_without_gci_report_rejected
    """
    ctx = setup_active_agreement()
    resp = api.assess_royalty_period(
        ctx["agreement"]["id"], {"period_month": "2027-03"}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_GCI_REPORT_MISSING)


def test_waive_of_positive_due_period_rejected(api):
    """PRD §3.5: "Waiver moves it `ASSESSED` → `WAIVED`, but only when
    `royalty_due_cents` is exactly zero; waiving a period with any positive due
    is rejected with `ERR_WAIVE_REQUIRES_ZERO_DUE`."

    Design: Corner/validations/waive_nonzero_period_rejected
    """
    ctx = setup_assessed_period("2027-01", 100_000_000)
    assert ctx["period"]["royalty_due_cents"] > 0
    resp = api.waive_royalty_period(ctx["period"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_WAIVE_REQUIRES_ZERO_DUE)


def test_terminate_without_escalated_default_rejected(api):
    """PRD §3.8: "Terminating without an escalated default is rejected with
    `ERR_TERMINATION_REQUIRES_ESCALATED_DEFAULT`."

    Design: Corner/errors/terminate_without_escalated_default_rejected
    """
    ctx = setup_active_agreement()
    open_default(ctx["agreement"]["id"], "PAYMENT")  # OPEN only, not escalated
    resp = api.terminate_agreement(ctx["agreement"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_TERMINATION_REQUIRES_ESCALATED_DEFAULT)


def test_suspend_without_open_default_rejected(api):
    """PRD §3.8: "Suspending with no open default is rejected with
    `ERR_SUSPENSION_REQUIRES_OPEN_DEFAULT`."

    Design: Corner/errors/suspend_without_open_default_rejected
    """
    ctx = setup_active_agreement()
    resp = api.suspend_agreement(ctx["agreement"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_SUSPENSION_REQUIRES_OPEN_DEFAULT)


def test_franchisee_cannot_create_brand(api):
    """PRD §2.1: "A request whose role is authenticated but is not listed among
    the authorized roles for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: "POST | /franchise/brands | Create a brand | FranchisorOps"

    Design: Corner/rbac/franchisee_cannot_create_brand
    """
    market = create_market()
    brokerage = get_success_data(
        api.create_brokerage(create_brokerage_payload(market["id"]), OPS)
    )
    resp = api.create_brand(
        {"brand_code": "XX", "display_name": "Nope"},
        make_franchisee_admin_headers(brokerage["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_franchisee_cannot_complete_other_brokerages_task(api):
    """PRD §3.9: "The owning `FranchiseeAdmin` — whose `X-User-ID` must equal the
    agreement's `brokerage_id` — marks a `PENDING` task done, moving it to
    `COMPLETED`."
    PRD §2.1: "A `FranchiseeAdmin` acting on an agent, an agent-count report, a
    GCI report, or a de-identification task outside their own brokerage's scope
    is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/franchisee_cannot_complete_other_brokerages_deidentification_task
    """
    ctx = setup_deidentifying_agreement()
    task = ctx["tasks"][0]
    assert task["status"] == "PENDING"

    other = get_success_data(
        api.create_brokerage(
            create_brokerage_payload(ctx["market"]["id"], legal_name="Other Brokerage"), OPS
        )
    )
    resp = api.complete_deidentification_task(
        task["id"], make_franchisee_admin_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    tasks, _meta = validate_paginated(
        api.list_deidentification_tasks(ctx["agreement"]["id"], OPS)
    )
    assert all(t["status"] == "PENDING" for t in tasks), "rejected completion must not move the task"


def test_auditor_cannot_settle_royalty_period(api):
    """PRD §2.1: "A request whose role is authenticated but is not listed among
    the authorized roles for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: "POST | /franchise/royalty-periods/{id}/settle | Settle an assessed
    royalty period | FranchisorOps"

    Design: Corner/rbac/auditor_cannot_settle_royalty_period
    """
    ctx = setup_assessed_period("2027-01", 1_000)
    resp = api.settle_royalty_period(ctx["period"]["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_assessment_response_carries_computed_amounts_immediately(api):
    """PRD §3.5: "Step two prices each leg separately — the below-threshold
    portion multiplied by `base_royalty_rate_bps` and divided by 10000, floored
    to whole cents; the above-threshold portion multiplied by
    `volume_incentive_rate_bps` and divided by 10000, floored to whole cents —
    and the raw royalty is the sum of the two floored legs."
    PRD §3.5: "the month's GCI multiplied by `ad_fund_rate_bps` and divided by
    10000, floored to whole cents, exactly one rounding event at accrual."

    Design: Corner/consistency_model/immediate_consistency_royalty_visible_in_same_response
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 100_000_000)
    resp = api.assess_royalty_period(ag_id, {"period_month": "2027-01"}, OPS)
    data = validate_success(resp, expected_status=201)
    assert data["royalty_due_cents"] == 6_000_000
    assert data["ad_fund_due_cents"] == 2_000_000

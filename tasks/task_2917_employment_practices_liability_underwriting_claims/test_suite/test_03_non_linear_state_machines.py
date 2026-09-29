"""Non-linear lifecycles: the two policy axes and the invoice revision cycle."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_money, assert_null, assert_same_instant


def _small_tx_policy(api):
    """A single-jurisdiction TX risk with a 10,000,000-cent aggregate limit."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
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
    policy = S.bind_policy(api, assessment["id"])
    return {
        "applicant_id": applicant["id"],
        "assessment": assessment,
        "policy_id": policy["id"],
        "policy": policy,
    }


def _eroded_policy(api):
    world = _small_tx_policy(api)
    claim = S.accepted_claim(
        api,
        world["policy_id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=6000000,
    )
    payment = S.pending_payment(api, world["policy_id"], claim["id"], 4000000)
    payment = get_success_data(api.approve_payment(payment["id"], U.CLAIMS_MANAGER))
    world.update({"claim_id": claim["id"], "payment": payment})
    return world


def test_suspension_moves_the_status_axis_and_leaves_the_posture_alone(api):
    """ACTIVE -> SUSPENDED -> ACTIVE while limit_posture stays ERODED throughout.

    PRD: "A policy may legitimately be `ACTIVE` and `EXHAUSTED`, or `SUSPENDED`
    and `OPEN`; a `status` transition never inspects `limit_posture`, and a
    `limit_posture` transition never inspects `status`."

    Design: Difficulty/non_linear_state_machine/policy_status_and_limit_posture_independent_parallel_axes
    """
    world = _eroded_policy(api)
    assert_money(world["payment"]["retention_portion_cents"], 2500000, "retention_portion_cents")
    assert_money(world["payment"]["insurer_portion_cents"], 1500000, "insurer_portion_cents")

    suspended = get_success_data(
        api.suspend_policy(world["policy_id"], "Premium audit outstanding", U.UW_MANAGER)
    )
    assert_fields(
        suspended,
        {
            "status": T.POLICY_SUSPENDED,
            "limit_posture": T.POSTURE_ERODED,
            "aggregate_limit_remaining_cents": 8500000,
        },
    )
    assert_same_instant(suspended["suspended_at"], "2026-08-01T00:00:00.000Z", "suspended_at")
    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert claim["coverage_gated"] is False
    assert claim["status"] == T.CLAIM_RESOLVED

    reinstated = get_success_data(api.reinstate_policy(world["policy_id"], U.UW_MANAGER))
    assert_fields(reinstated, {"status": T.POLICY_ACTIVE, "limit_posture": T.POSTURE_ERODED})
    assert_null(reinstated, ["suspended_at", "suspension_reason"])


def test_void_moves_the_posture_axis_and_leaves_the_status_alone(api):
    """The posture runs ERODED -> OPEN backwards while status stays ACTIVE.

    PRD: "Voids run the axis backwards: `EXHAUSTED → ERODED` when a void
    restores the remainder to something greater than 0 but still less than the
    full aggregate limit, `ERODED → OPEN` when the last remaining debit is
    voided and the remainder returns to the full aggregate limit, and
    `EXHAUSTED → OPEN` when voiding the single debit that exhausted the policy
    restores the whole limit at once."

    Design: Difficulty/non_linear_state_machine/policy_status_and_limit_posture_independent_parallel_axes
    """
    world = _eroded_policy(api)
    assert_fields(
        world["assessment"], {"indicated_premium_cents": 1803600, "exposure_score_snapshot": 28.00}
    )
    assert_fields(
        world["policy"], {"third_party_coverage_elected": False, "wage_hour_sublimit_cents": 2500000}
    )
    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(
        claim, {"coverage_bucket": T.BUCKET_FIRST_PARTY, "applied_retention_cents": 2500000}
    )

    get_success_data(
        api.void_payment(world["payment"]["id"], "Settlement rescinded by the claimant", U.CLAIMS_MANAGER)
    )

    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy,
        {
            "status": T.POLICY_ACTIVE,
            "limit_posture": T.POSTURE_OPEN,
            "aggregate_limit_remaining_cents": 10000000,
            "indemnity_paid_cents": 0,
        },
    )
    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_RESOLVED


def _audit_cycle_world(api):
    """A NATIONAL firm, an accepted claim and one audited invoice on its matter."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA", "TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=25000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=5000000,
        panel_firm_id=firm["id"],
    )
    invoice = S.submit_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=12.5,
        associate_hours=40.0,
        paralegal_hours=8.0,
        block_billed_hours=15.0,
        expenses_cents=420000,
    )
    invoice = get_success_data(api.audit_invoice(invoice["id"], U.ADJUSTER))
    return {
        "firm_id": firm["id"],
        "assignment_id": assignment["id"],
        "invoice_id": invoice["id"],
        "invoice": invoice,
    }


def test_a_dispute_overwrites_the_inputs_reruns_the_audit_and_clears_the_auditor(api):
    """The first lap of the revision cycle: UNDER_AUDIT -> ADJUSTED.

    PRD: "The dispute carries a mandatory `dispute_note` and may supply revised
    `partner_hours`, `associate_hours`, `paralegal_hours`, `block_billed_hours`
    and `expenses_cents`, which **overwrite** the stored values rather than
    adding to them."

    Design: Difficulty/non_linear_state_machine/defense_invoice_audit_dispute_reaudit_cycle
    """
    world = _audit_cycle_world(api)
    assert_fields(
        world["invoice"],
        {"status": T.INVOICE_UNDER_AUDIT, "allowed_amount_cents": 2957705, "audited_by_user_id": U.ADJ_001},
    )

    note = "Block-billed entries have been re-itemised and travel expenses withdrawn"
    disputed = get_success_data(
        api.dispute_invoice(
            world["invoice_id"],
            F.invoice_dispute(note, block_billed_hours=0.0, expenses_cents=200000),
            U.panel_counsel(world["firm_id"]),
        )
    )
    assert_fields(
        disputed,
        {
            "status": T.INVOICE_ADJUSTED,
            "block_billed_hours": 0.0,
            "expenses_cents": 200000,
            "block_reduction_cents": 0,
            "expense_disallowance_cents": 0,
            "allowed_amount_cents": 3081500,
            "guideline_reduction_cents": 452500,
            "disallowed_amount_cents": 452500,
            "dispute_note": note,
        },
    )
    assert_null(disputed, ["audited_by_user_id"])


def test_the_audit_dispute_reaudit_cycle_is_lossless_and_commits_no_money(api):
    """Three laps of UNDER_AUDIT -> ADJUSTED -> UNDER_AUDIT return the same figures.

    PRD: "The pair of transitions `UNDER_AUDIT → ADJUSTED → UNDER_AUDIT` is the
    revision cycle, and it may repeat."

    Design: Difficulty/non_linear_state_machine/defense_invoice_audit_dispute_reaudit_cycle
    """
    world = _audit_cycle_world(api)
    invoice_id = world["invoice_id"]
    counsel = U.panel_counsel(world["firm_id"])

    get_success_data(
        api.dispute_invoice(
            invoice_id,
            F.invoice_dispute(
                "Block-billed entries have been re-itemised and travel expenses withdrawn",
                block_billed_hours=0.0,
                expenses_cents=200000,
            ),
            counsel,
        )
    )
    lap2 = get_success_data(api.audit_invoice(invoice_id, U.ADJUSTER_2))
    assert_fields(
        lap2,
        {
            "status": T.INVOICE_UNDER_AUDIT,
            "allowed_amount_cents": 3081500,
            "audited_by_user_id": U.ADJ_002,
        },
    )

    readjusted = get_success_data(
        api.dispute_invoice(
            invoice_id,
            F.invoice_dispute(
                "Withdrawal retracted; original block-billed entries and expenses reinstated",
                block_billed_hours=15.0,
                expenses_cents=420000,
            ),
            counsel,
        )
    )
    assert_fields(
        readjusted, {"status": T.INVOICE_ADJUSTED, "allowed_amount_cents": 2957705}
    )

    lap3 = get_success_data(api.audit_invoice(invoice_id, U.ADJUSTER))
    assert_fields(
        lap3,
        {
            "status": T.INVOICE_UNDER_AUDIT,
            "audited_by_user_id": U.ADJ_001,
            "billed_fees_cents": 3334000,
            "rate_cap_excess_cents": 452500,
            "block_reduction_cents": 142884,
            "expense_disallowance_cents": 200911,
            "allowed_amount_cents": 2957705,
        },
    )

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(
        assignment, {"budget_spent_cents": 0, "status": T.ASSIGNMENT_ACTIVE}
    )

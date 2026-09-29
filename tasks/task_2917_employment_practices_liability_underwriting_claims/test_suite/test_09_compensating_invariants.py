"""Voids and closures restore exactly what they consumed."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null


def _paid_small_policy(api):
    """A 10,000,000-cent policy with one APPROVED 4,000,000-cent settlement."""
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
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=4500000,
    )
    payment = S.approved_payment(api, policy["id"], claim["id"], 4000000)
    return {
        "policy_id": policy["id"],
        "claim_id": claim["id"],
        "payment_id": payment["id"],
    }


def test_voiding_a_payment_restores_the_policy_ledger_exactly(api):
    """The aggregate limit is the conserved quantity across approve then void.

    PRD: "Voiding an `APPROVED` payment restores precisely what it took: the
    claim's `retention_satisfied_cents` by exactly `retention_portion_cents` and
    its `indemnity_paid_cents` by exactly `insurer_portion_cents`; the group's
    `retention_paid_cents` by exactly `retention_portion_cents` when the claim
    is a group member, possibly unlocking the group `LOCKED → OPEN`; and the
    policy's `indemnity_paid_cents`, the applicable sublimit remainder and
    `aggregate_limit_remaining_cents` by exactly `insurer_portion_cents`,
    possibly regressing the posture."

    Design: Difficulty/compensating_invariant/payment_void_restores_policy_indemnity_capital_exactly
    """
    world = _paid_small_policy(api)
    before = get_success_data(api.get_limit_ledger(world["policy_id"], U.CLAIMS_MANAGER))
    assert_fields(
        before,
        {
            "indemnity_paid_cents": 1500000,
            "aggregate_limit_remaining_cents": 8500000,
            "defense_spend_cents": 0,
            "limit_posture": T.POSTURE_ERODED,
        },
    )
    assert before["aggregate_limit_cents"] == (
        before["aggregate_limit_remaining_cents"]
        + before["indemnity_paid_cents"]
        + before["defense_spend_cents"]
    )

    get_success_data(
        api.void_payment(
            world["payment_id"], "Settlement agreement rescinded before disbursement", U.CLAIMS_MANAGER
        )
    )

    after = get_success_data(api.get_limit_ledger(world["policy_id"], U.CLAIMS_MANAGER))
    assert_fields(
        after,
        {
            "indemnity_paid_cents": 0,
            "aggregate_limit_remaining_cents": 10000000,
            "defense_spend_cents": 0,
            "limit_posture": T.POSTURE_OPEN,
            "wage_hour_sublimit_remaining_cents": 2500000,
            "third_party_sublimit_remaining_cents": 4000000,
        },
    )
    assert after["aggregate_limit_cents"] == (
        after["aggregate_limit_remaining_cents"]
        + after["indemnity_paid_cents"]
        + after["defense_spend_cents"]
    )


def test_the_voided_payment_keeps_its_split_and_the_claim_stays_resolved(api):
    """The audit trail of the reversal survives and the lifecycle is not rolled back.

    PRD: "One thing is deliberately not undone: a claim that reached `RESOLVED`
    on the strength of that payment is **not** rolled back out of `RESOLVED`."

    Design: Difficulty/compensating_invariant/payment_void_restores_policy_indemnity_capital_exactly
    """
    world = _paid_small_policy(api)
    voided = get_success_data(
        api.void_payment(
            world["payment_id"], "Settlement agreement rescinded before disbursement", U.CLAIMS_MANAGER
        )
    )
    assert_fields(
        voided,
        {
            "status": T.PAYMENT_VOIDED,
            "void_reason": "Settlement agreement rescinded before disbursement",
            "retention_portion_cents": 2500000,
            "insurer_portion_cents": 1500000,
        },
    )

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(
        claim,
        {
            "retention_satisfied_cents": 0,
            "indemnity_paid_cents": 0,
            "status": T.CLAIM_RESOLVED,
        },
    )


def _approved_invoice_world(api):
    """A matter whose 2,957,705-cent invoice has been approved against a 3,000,000 cap."""
    world = S.defended_claim(
        api,
        firm_overrides={
            "name": "Ashford & Vance LLP",
            "tier": T.TIER_NATIONAL,
            "jurisdiction_codes": ["CA", "TX"],
            "partner_rate_cents_per_hour": 92000,
            "associate_rate_cents_per_hour": 51000,
            "paralegal_rate_cents_per_hour": 18000,
            "capacity_open_matters": 3,
        },
        claim_overrides={
            "claim_type": T.CLAIM_TYPE_RETALIATION,
            "claimant_class": T.CLAIMANT_EMPLOYEE,
            "notice_type": T.NOTICE_LAWSUIT,
            "alleged_damages_cents": 22000000,
        },
        assignment_overrides={
            "engagement_from": "2026-08-01T00:00:00.000Z",
            "engagement_to": "2026-11-01T00:00:00.000Z",
            "budget_cap_cents": 3000000,
        },
    )
    invoice = S.audited_invoice(
        api,
        world["assignment_id"],
        world["firm_id"],
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=12.5,
        associate_hours=40.0,
        paralegal_hours=8.0,
        block_billed_hours=15.0,
        expenses_cents=420000,
    )
    payment = S.approved_payment(api, world["policy_id"], world["claim_id"], 5000000)
    invoice = get_success_data(api.approve_invoice(invoice["id"], U.ADJUSTER_2))
    world.update({"invoice_id": invoice["id"], "payment_id": payment["id"]})
    return world


def test_voiding_an_approved_invoice_restores_the_matter_budget_exactly(api):
    """The matter's defense budget is the conserved quantity.

    PRD: "Voiding an approved invoice belongs to the `ClaimsManager` and is the
    exact compensating action: only an `APPROVED` invoice may be voided
    (otherwise `ERR_INVOICE_NOT_VOIDABLE`), a mandatory `void_reason` is
    recorded, the status becomes `VOIDED`, and the assignment's
    `budget_spent_cents` and `budget_remaining_cents` along with the claim's
    `defense_paid_cents` and the policy's `defense_spend_cents` and
    `aggregate_limit_remaining_cents` are all restored by exactly
    `allowed_amount_cents` — possibly regressing the policy's erosion posture."

    Design: Difficulty/compensating_invariant/invoice_void_restores_matter_budget_exactly
    """
    world = _approved_invoice_world(api)
    before = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(
        before, {"budget_spent_cents": 2957705, "budget_remaining_cents": 42295}
    )
    assert before["budget_cap_cents"] == (
        before["budget_spent_cents"] + before["budget_remaining_cents"]
    )
    claim_before = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert claim_before["defense_paid_cents"] == 2957705
    policy_before = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy_before,
        {
            "defense_spend_cents": 2957705,
            "aggregate_limit_remaining_cents": 197042295,
            "limit_posture": T.POSTURE_ERODED,
        },
    )

    get_success_data(
        api.void_invoice(
            world["invoice_id"],
            "Duplicate billing discovered during quarterly panel reconciliation",
            U.CLAIMS_MANAGER,
        )
    )

    after = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(
        after,
        {
            "budget_spent_cents": 0,
            "budget_remaining_cents": 3000000,
            "status": T.ASSIGNMENT_ACTIVE,
        },
    )
    claim_after = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert claim_after["defense_paid_cents"] == 0
    policy_after = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy_after,
        {
            "defense_spend_cents": 0,
            "aggregate_limit_remaining_cents": 200000000,
            "limit_posture": T.POSTURE_OPEN,
        },
    )


def test_the_voided_invoice_preserves_its_audit_result_verbatim(api):
    """Only the defense ledger moves; the audit figures and the payment are untouched.

    PRD: "Restoring the posture does **not** resurrect what the exhaustion
    cascade destroyed: assignments it closed stay `CLOSED` and invoices it
    rejected stay `REJECTED`. Only the posture and the ledger come back."

    Design: Difficulty/compensating_invariant/invoice_void_restores_matter_budget_exactly
    """
    world = _approved_invoice_world(api)
    voided = get_success_data(
        api.void_invoice(
            world["invoice_id"],
            "Duplicate billing discovered during quarterly panel reconciliation",
            U.CLAIMS_MANAGER,
        )
    )
    assert_fields(
        voided,
        {
            "status": T.INVOICE_VOIDED,
            "void_reason": "Duplicate billing discovered during quarterly panel reconciliation",
            "allowed_amount_cents": 2957705,
            "disallowed_amount_cents": 796295,
            "rate_cap_excess_cents": 452500,
            "block_reduction_cents": 142884,
            "expense_disallowance_cents": 200911,
        },
    )

    payment = get_success_data(api.get_payment(world["payment_id"], U.CLAIMS_MANAGER))
    assert_fields(
        payment,
        {
            "status": T.PAYMENT_APPROVED,
            "retention_portion_cents": 5000000,
            "insurer_portion_cents": 0,
        },
    )


def _three_matters_one_firm(api):
    """One REGIONAL firm holding three concurrent matters on the same policy."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=3,
    )
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    assignments = []
    claims = []
    for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
        claim = S.accepted_claim(
            api,
            policy["id"],
            claim_type=T.CLAIM_TYPE_HARASSMENT,
            claimant_class=T.CLAIMANT_EMPLOYEE,
            notice_type=T.NOTICE_LAWSUIT,
            first_notice_at=f"{day}T00:00:00.000Z",
            alleged_damages_cents=8000000,
        )
        claims.append(claim)
        assignments.append(
            S.create_assignment(
                api,
                claim["id"],
                engagement_from="2026-08-01T00:00:00.000Z",
                engagement_to="2026-11-01T00:00:00.000Z",
                budget_cap_cents=3000000,
                panel_firm_id=firm["id"],
            )
        )
    return {
        "firm_id": firm["id"],
        "policy_id": policy["id"],
        "claim_ids": [c["id"] for c in claims],
        "assignment_ids": [a["id"] for a in assignments],
    }


def test_open_matter_count_survives_a_suspend_and_reinstate_round_trip(api):
    """SUSPENDED_FUNDING matters still occupy the firm, and reinstatement restores them.

    PRD: "The firm's `open_matter_count` starts at 0 and thereafter always equals
    the number of defense assignments naming that firm whose status is `ACTIVE`
    or `SUSPENDED_FUNDING`."

    Design: Difficulty/compensating_invariant/assignment_close_conserves_panel_open_matter_count
    """
    world = _three_matters_one_firm(api)
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADJUSTER))
    assert firm["open_matter_count"] == 3

    get_success_data(
        api.suspend_policy(world["policy_id"], "Audit hold pending premium reconciliation", U.UW_MANAGER)
    )
    for assignment_id in world["assignment_ids"]:
        assignment = get_success_data(api.get_assignment(assignment_id, U.ADJUSTER))
        assert_fields(
            assignment,
            {
                "status": T.ASSIGNMENT_SUSPENDED_FUNDING,
                "hold_reason": T.HOLD_POLICY_SUSPENDED,
            },
        )
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADJUSTER))
    assert firm["open_matter_count"] == 3

    get_success_data(api.reinstate_policy(world["policy_id"], U.UW_MANAGER))
    for assignment_id in world["assignment_ids"]:
        assignment = get_success_data(api.get_assignment(assignment_id, U.ADJUSTER))
        assert assignment["status"] == T.ASSIGNMENT_ACTIVE
        assert_null(assignment, ["hold_reason", "funding_ceased_at"])
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADJUSTER))
    assert firm["open_matter_count"] == 3


def test_each_close_decrements_once_and_a_repeat_close_is_refused(api):
    """Three closures drop the count to zero and a fourth cannot go negative.

    PRD: "Closing an assignment is an adjuster action available from `ACTIVE` and
    from `SUSPENDED_FUNDING`; an assignment already `CLOSED` is
    `ERR_ASSIGNMENT_NOT_CLOSABLE`."

    Design: Difficulty/compensating_invariant/assignment_close_conserves_panel_open_matter_count
    """
    world = _three_matters_one_firm(api)
    first, second, third = world["assignment_ids"]

    closed = get_success_data(api.close_assignment(second, U.ADJUSTER))
    assert closed["status"] == T.ASSIGNMENT_CLOSED
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADJUSTER))
    assert firm["open_matter_count"] == 2

    get_success_data(api.close_assignment(first, U.ADJUSTER))
    get_success_data(api.close_assignment(third, U.ADJUSTER))
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADJUSTER))
    assert firm["open_matter_count"] == 0

    validate_error(
        api.close_assignment(second, U.ADJUSTER), E.ERR_ASSIGNMENT_NOT_CLOSABLE, 409
    )
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADJUSTER))
    assert firm["open_matter_count"] == 0

    for claim_id in world["claim_ids"]:
        claim = get_success_data(api.get_claim(claim_id, U.ADJUSTER))
        assert claim["status"] == T.CLAIM_DEFENSE_OPEN

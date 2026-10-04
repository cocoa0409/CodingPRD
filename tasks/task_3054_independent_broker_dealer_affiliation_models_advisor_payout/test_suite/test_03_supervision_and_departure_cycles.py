"""Cyclic lifecycles: the advisor suspension cycle, the branch supervision gate
and the payout-period reopen/re-post cycle."""

from test_helpers import (
    api_client, get_success_data, validate_error, ApiErrorId,
    refresh_advisor, refresh_branch, setup_suspended_advisor, suspend_advisor,
    reinstate_advisor, setup_advisor_on_unsupervised_branch,
    setup_funded_period, advance_period, true_up_period,
    enroll_supervisor, create_advisor_link,
    PLATFORM_ADMIN, BRANCH_MANAGER, COMPLIANCE_OFFICER,
)


def _open_account_statuses(ctx):
    """The status of every account the fixture opened for the advisor."""
    expected = ctx.get("account_numbers", [])
    rows = get_success_data(api_client.list_accounts(
        PLATFORM_ADMIN, {"advisor_code": ctx["advisor"]["advisor_code"]}))
    statuses = [row["status"] for row in rows if row["account_number"] in expected]
    return sorted(statuses)


# ─── non_linear_state_machine ─────────────────────────

def test_suspension_freezes_the_advisors_open_accounts():
    """PRD §3.7: "Suspension freezes every `OPEN` account of the advisor."

    Design: Difficulty/non_linear_state_machine/advisor_suspension_freeze_unfreeze_cycle
    """
    ctx = setup_suspended_advisor(advisor_code="A-5001")
    advisor_id = ctx["advisor"]["id"]

    suspended = get_success_data(suspend_advisor(advisor_id))
    assert suspended["status"] == "SUSPENDED"
    assert _open_account_statuses(ctx) == ["FROZEN", "FROZEN"]


def test_reinstatement_reopens_the_frozen_accounts():
    """PRD §3.7: "Reinstatement from `SUSPENDED` to `ACTIVE` requires the same branch-level
    supervision, and it returns every `FROZEN` account to `OPEN`".

    Design: Difficulty/non_linear_state_machine/advisor_suspension_freeze_unfreeze_cycle
    """
    ctx = setup_suspended_advisor(advisor_code="A-5002")
    advisor_id = ctx["advisor"]["id"]

    suspend_advisor(advisor_id)
    reinstated = get_success_data(reinstate_advisor(advisor_id))
    assert reinstated["status"] == "ACTIVE"
    assert _open_account_statuses(ctx) == ["OPEN", "OPEN"]


def test_active_suspended_active_suspended_is_a_reachable_cycle():
    """PRD §3.7: "because reinstatement releases the freeze that suspension applied, the
    pair `SUSPENDED` and `ACTIVE` forms a reachable cycle."

    Design: Difficulty/non_linear_state_machine/advisor_suspension_freeze_unfreeze_cycle
    """
    ctx = setup_suspended_advisor(advisor_code="A-5003")
    advisor_id = ctx["advisor"]["id"]
    version_before = refresh_advisor(advisor_id)["version"]

    first = get_success_data(suspend_advisor(advisor_id))
    assert first["status"] == "SUSPENDED"
    middle = get_success_data(reinstate_advisor(advisor_id))
    assert middle["status"] == "ACTIVE"
    last = get_success_data(suspend_advisor(advisor_id))
    assert last["status"] == "SUSPENDED"
    assert _open_account_statuses(ctx) == ["FROZEN", "FROZEN"]

    final = refresh_advisor(advisor_id)
    assert final["version"] == version_before + 3
    assert final["status"] == "SUSPENDED"


# ─── cross_entity_state_dependency ────────────────────

def test_suspension_is_refused_while_the_branch_is_unsupervised():
    """PRD §3.7: "Moving an advisor from `ACTIVE` to `SUSPENDED` requires that the
    advisor's primary branch has `state` `SUPERVISED` and that no revenue entry of the
    advisor is still `DRAFT`; either condition failing yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/advisor_suspension_requires_supervised_branch
    """
    ctx = setup_advisor_on_unsupervised_branch(branch_code="SOLO-1",
                                               advisor_code="A-5004")
    assert ctx["branch"]["state"] == "UNSUPERVISED"

    response = api_client.set_advisor_state(
        ctx["advisor"]["id"],
        {"to_status": "SUSPENDED",
         "expected_advisor_version": ctx["advisor"]["version"]},
        COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert refresh_advisor(ctx["advisor"]["id"])["status"] == "ACTIVE"


def test_suspension_succeeds_once_a_supervisor_enrollment_escalates_the_branch():
    """PRD §3.7: "it sets the branch's `state` to `SUPERVISED`, its `osj_enabled` to true,
    and its `status` to `ACTIVE`".
    PRD §2.4: "when the first supervisor becomes enrolled, `osj_enabled` flips to true and
    `status` becomes `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/advisor_suspension_requires_supervised_branch
    """
    ctx = setup_advisor_on_unsupervised_branch(branch_code="SOLO-1",
                                               advisor_code="A-5005",
                                               supervisor_code="A-5006")
    advisor_id = ctx["advisor"]["id"]
    # Re-escalate the existing branch with a fresh supervisor enrollment.
    enrollment = enroll_supervisor("SOLO-1", "A-5006")
    branch = refresh_branch(ctx["branch"]["id"])
    assert branch["state"] == "SUPERVISED"
    assert branch["osj_enabled"] is True

    suspended = get_success_data(api_client.set_advisor_state(
        advisor_id,
        {"to_status": "SUSPENDED",
         "expected_advisor_version": refresh_advisor(advisor_id)["version"]},
        COMPLIANCE_OFFICER))
    assert suspended["status"] == "SUSPENDED"
    assert enrollment["status"] == "ENROLLED"


def test_ordinary_advisor_links_never_escalate_the_branch():
    """PRD §2.4: "Only supervisor enrollments escalate a branch. Ordinary advisor
    assignments — a plain link with `is_supervisor` false — never move supervision."

    Design: Difficulty/cross_entity_state_dependency/advisor_suspension_requires_supervised_branch
    """
    ctx = setup_advisor_on_unsupervised_branch(branch_code="SOLO-2",
                                               advisor_code="A-5007",
                                               supervisor_code="A-5008")
    create_advisor_link(ctx["advisor"], "SOLO-2", is_supervisor=False)
    branch = refresh_branch(ctx["branch"]["id"])
    assert branch["state"] == "UNSUPERVISED", (
        "a non-supervisory link does not make the office of supervisory jurisdiction active")
    assert branch["supervising_advisor_count"] == 0


# ─── non_linear_state_machine: period reopen cycle ────

def _reopen_fixture(advisor_code="A-5009"):
    """An advisor with a loan and a September entry that true-ups to -300,000."""
    ctx = setup_funded_period(
        advisor_code=advisor_code, projected_annual_production_cents=100_000_000,
        principal_cents=1_000_000, amortization_rate_bps=1000,
        forgiveness_milestone_pct=99,
        entries=((1_000_000, "2026-09-03", "EQUITY"),),
        release=True)
    return ctx


def test_posting_releases_the_draft_line_and_amortizes_the_loan():
    """PRD §3.3: "releases every draft line of the period at its provisional rate,
    computing the line's `release_amount_cents` with no true-up applied".
    PRD §3.2: "the draw is the line's `release_amount_cents` multiplied by the loan's
    `amortization_rate_bps` and divided by 10000".

    Design: Difficulty/non_linear_state_machine/payout_period_reopen_repost_cycle_compensates_true_up
    """
    ctx = _reopen_fixture("A-5009")
    advance_period(ctx["period"]["id"], "CLOSED", ctx["branch"]["branch_code"])
    advance_period(ctx["period"]["id"], "PAID", ctx["branch"]["branch_code"])

    line = get_success_data(api_client.list_period_payout_lines(
        ctx["period"]["id"], BRANCH_MANAGER))[0]
    assert line["release_amount_cents"] == 800_000, (
        "1,000,000 at the 8,000 basis points of the projected 100,000,000 basis")
    assert line["status"] == "RELEASED"

    loan = get_success_data(api_client.get_payout_loan(ctx["loan"]["id"], PLATFORM_ADMIN))
    assert loan["remaining_balance_cents"] == 1_000_000 - 80_000
    assert loan["status"] == "AMORTIZING"


def test_the_true_up_amortization_row_reads_void_after_the_reopen():
    """PRD §3.3: "every loan amortization entry posted by the period is voided and its
    balance restored".
    PRD §3.3: "Going `PAID` and then `REOPENED` and then `PAID` again is a reachable
    cycle."

    Design: Difficulty/non_linear_state_machine/payout_period_reopen_repost_cycle_compensates_true_up
    """
    ctx = _reopen_fixture("A-5011")
    advance_period(ctx["period"]["id"], "CLOSED", ctx["branch"]["branch_code"])
    advance_period(ctx["period"]["id"], "PAID", ctx["branch"]["branch_code"])
    true_up_period(ctx["period"]["id"])
    advance_period(ctx["period"]["id"], "REOPENED", ctx["branch"]["branch_code"],
                   role_headers=COMPLIANCE_OFFICER)

    rows = get_success_data(api_client.list_loan_amortization_entries(
        ctx["loan"]["id"], PLATFORM_ADMIN))
    true_up_rows = [row for row in rows if row["amortization_amount_cents"] < 0]
    assert true_up_rows, "the true-up posted a signed amortization row"
    assert all(row["status"] == "VOID" for row in true_up_rows)
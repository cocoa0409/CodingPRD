"""Cross-entity cascades: affiliation, departure, the retention contest and its cap."""
from test_helpers import (
    api_client, get_success_data, validate_error, ApiErrorId,
    refresh_advisor, refresh_branch, setup_active_advisor, open_transition,
    setup_retention_scenario, open_account, open_period, setup_advisor_on_branch,
    contest_account, list_retention_rows, lose_retention,
    start_departure, book_entry, create_advisor_link,
    make_advisor_ops_headers, confirm_transfer, retire_loan,
    PLATFORM_ADMIN, BRANCH_MANAGER, COMPLIANCE_OFFICER,
)


def _accounts_of(advisor_code):
    rows = get_success_data(api_client.list_accounts(
        PLATFORM_ADMIN, {"advisor_code": advisor_code}))
    return rows


# ─── transitive_cascade ───────────────────────────────

def test_affiliation_cascades_the_requested_loan_to_active():
    """PRD §3.1: "Activation sets the advisor's `status` to `ACTIVE`, resets
    `retention_status` to `NOT_AT_RISK`, and cascades every transition assistance loan of
    that advisor from `REQUESTED` to `ACTIVE`."

    Design: Difficulty/transitive_cascade/affiliate_link_cascade_escalates_branch_then_freezes_accounts
    """
    ctx = setup_active_advisor(advisor_code="A-6001")
    assert ctx["advisor"]["status"] == "ACTIVE"
    assert ctx["advisor"]["retention_status"] == "NOT_AT_RISK"
    assert ctx["loan"]["status"] == "ACTIVE", (
        "the affiliation cascaded the REQUESTED loan forward")


def test_the_supervisor_count_reflects_only_supervisory_links():
    """PRD §2.4: "The `supervising_advisor_count` is derived from the advisor-to-branch
    links on the branch whose `is_supervisor` flag is true, and `current_payout_period_id`
    points at the payout period currently tagged to the branch".
    PRD §2.4: "Ordinary advisor assignments — a plain link with `is_supervisor` false —
    never move supervision."

    Design: Difficulty/transitive_cascade/affiliate_link_cascade_escalates_branch_then_freezes_accounts
    """
    supervisor = setup_active_advisor(advisor_code="A-6002", own_supervisor=True)
    branch = refresh_branch(supervisor["branch"]["id"])
    assert branch["state"] == "SUPERVISED"
    assert branch["supervising_advisor_count"] == 1

    # A colleague joins the branch that is already escalated by A-6002; the
    # branch is created once, so this second advisor is added on top of it.
    other = setup_advisor_on_branch("A-6003", branch["branch_code"])
    before = refresh_branch(branch["id"])["supervising_advisor_count"]
    create_advisor_link(other["advisor"], branch["branch_code"], is_supervisor=False)
    after = refresh_branch(branch["id"])["supervising_advisor_count"]
    assert after == before, "a non-supervisory link must not raise the supervisor count"


def test_a_supervised_branch_is_what_lets_the_suspension_freeze_the_accounts():
    """PRD §3.7: "Moving an advisor from `ACTIVE` to `SUSPENDED` requires that the
    advisor's primary branch has `state` `SUPERVISED`".
    PRD §3.7: "Suspension freezes every `OPEN` account of the advisor."

    Design: Difficulty/transitive_cascade/affiliate_link_cascade_escalates_branch_then_freezes_accounts
    """
    ctx = setup_active_advisor(advisor_code="A-6004")
    advisor = ctx["advisor"]
    open_account(advisor, "A-6004-1", balance_cents=10_000_000)
    open_account(advisor, "A-6004-2", balance_cents=20_000_000)

    suspended = get_success_data(api_client.set_advisor_state(
        advisor["id"],
        {"to_status": "SUSPENDED",
         "expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        COMPLIANCE_OFFICER))
    assert suspended["status"] == "SUSPENDED"

    rows = [row["status"] for row in _accounts_of(advisor["advisor_code"])
            if row["account_number"] in ("A-6004-1", "A-6004-2")]
    assert rows == ["FROZEN", "FROZEN"]


def test_departure_freezes_the_book_and_releases_every_draft_entry():
    """PRD §3.7: "Departure freezes every `OPEN` account of the advisor, releases every
    `DRAFT` revenue entry of the advisor so that frozen books still earn".

    Design: Difficulty/transitive_cascade/departure_cascade_freezes_accounts_releases_entries_then_voids_them
    """
    ctx = setup_active_advisor(advisor_code="A-6005", crd_number="2234571",
                               full_name="Departure Cascade Advisor",
                               ingested_book_total_cents=200_000_000,
                               book_transferred_cents=160_000_000)
    advisor = ctx["advisor"]
    accounts = [open_account(advisor, "A-6005-1", balance_cents=4_000_000),
                open_account(advisor, "A-6005-2", balance_cents=6_000_000)]
    scratch = open_account(advisor, "A-6005-RP", balance_cents=1_000_000)
    book_entry(advisor, accounts[0]["id"], 1_000_000, "2026-09-03")
    book_entry(advisor, accounts[1]["id"], 2_000_000, "2026-09-09")
    retire_loan(advisor, scratch)
    departed = start_departure(advisor)
    open_period()
    assert departed["status"] == "DEPARTING"

    opened = [row["status"] for row in _accounts_of(advisor["advisor_code"])
              if row["account_number"] in ("A-6005-1", "A-6005-2")]
    assert opened == ["FROZEN", "FROZEN"]
    released = get_success_data(api_client.list_revenue_entries(
        PLATFORM_ADMIN, {"advisor_code": advisor["advisor_code"],
                         "status": "RELEASED"}))
    released_accounts = {entry["account_id"] for entry in released}
    assert {account["id"] for account in accounts} <= released_accounts, (
        "the departure released the whole draft book")


def test_contesting_a_frozen_account_credits_the_book_and_counts_the_contest():
    """PRD §3.8: "it starts at `CONTESTED` when the advisor's `status` is `DEPARTING` and
    the advisor has at least one account in `FROZEN`, `PENDING_TRANSFER`, or
    `RETENTION_CONTESTED` status".
    PRD §3.8: "the balance multiplied by the rate and divided by 10000, rounded half up".

    Design: Difficulty/transitive_cascade/departure_cascade_freezes_accounts_releases_entries_then_voids_them
    """
    ctx = setup_retention_scenario(
        advisor_code="A-6006",
        account_numbers=("A-6006-1", "A-6006-2"),
        account_balances=(4_000_000, 6_000_000))
    transition = ctx["transition"]
    retention = get_success_data(contest_account(transition["id"],
                                                 ctx["accounts"][0]["id"], 500))
    assert retention["credit_amount_cents"] == 200_000, (
        "500 basis points of the 4,000,000 account balance")
    assert retention["status"] == "POSTED"

    reread = get_success_data(api_client.get_transition(transition["id"],
                                                        BRANCH_MANAGER))
    assert reread["settled_amount_cents"] == 200_000


# ─── dual_variant_calc: retention credit cap waterfall ─

def _cap_waterfall_fixture(advisor_code, balances, contest_count):
    """A DEPARTING advisor whose 450,000 retention credit cap is swept by account.

    book_transferred_cents is 22,500,000, so 200 basis points gives a 450,000
    cap: the three contests below consume it exactly (200,000 + 150,000 +
    100,000), which is what leaves the next contest refused.
    """
    ctx = setup_retention_scenario(
        advisor_code=advisor_code,
        account_numbers=tuple(f"A-{3001 + i}" for i in range(len(balances))),
        account_balances=balances,
        book_transferred_cents=22_500_000)
    accounts = ctx["accounts"]
    period = ctx["period"]
    transition = ctx["transition"]
    posted = [get_success_data(contest_account(transition["id"], account["id"], 500))
              for account in accounts[:contest_count]]
    return {"ctx": ctx, "accounts": accounts, "period": period,
            "transition": transition, "posted": posted}


def test_retention_credit_cap_is_swept_as_an_account_ordered_waterfall():
    """PRD §3.8: "it is consumed as a running watermark in ascending `account_number`
    order".
    PRD §3.8: "the balance multiplied by the rate and divided by 10000, rounded half up,
    and then clipped by whatever remains of the book's retention credit cap."

    Design: Difficulty/dual_variant_calc/retention_credit_cap_sweep_is_an_account_ordered_waterfall
    """
    fx = _cap_waterfall_fixture("A-6007",
                                (4_000_000, 3_000_000, 2_000_000), 3)
    rows = get_success_data(list_retention_rows(fx["transition"]["id"]))
    assert len(rows) == 3
    total = sum(row["credit_amount_cents"] for row in rows)
    assert total == 450_000, "the watermark clips only what the cap cannot absorb"
    assert total != 300_000, "a per-row clip would have summed to 300,000"

    reread = get_success_data(api_client.get_transition(fx["transition"]["id"],
                                                        BRANCH_MANAGER))
    assert reread["settled_amount_cents"] == 450_000


def test_the_watermark_leaves_the_capped_slot_to_the_final_account():
    """PRD §3.8: "the balance multiplied by the rate and divided by 10000, rounded half up,
    and then clipped by whatever remains of the book's retention credit cap."
    PRD §3.8: "The cap is 200 basis points of the advisor's `book_transferred_cents`".

    Design: Difficulty/dual_variant_calc/retention_credit_cap_sweep_is_an_account_ordered_waterfall
    """
    fx = _cap_waterfall_fixture("A-6008",
                                (4_000_000, 3_000_000, 2_000_000, 3_000_000), 3)
    rows = get_success_data(list_retention_rows(fx["transition"]["id"]))
    assert [row["credit_amount_cents"] for row in rows] == [200_000, 150_000,
                                                            100_000]

    fourth = contest_account(fx["transition"]["id"], fx["accounts"][3]["id"], 500)
    validate_error(fourth, ApiErrorId.ERR_RETENTION_CREDIT_EXHAUSTED)

    rows = get_success_data(list_retention_rows(fx["transition"]["id"]))
    assert len(rows) == 3, "the exhausted watermark posts no further row"
    assert sum(row["credit_amount_cents"] for row in rows) == 450_000


# ─── compensating_invariant: retention cap exhaustion ─

def _exhausted_cap_fixture(advisor_code):
    """A DEPARTING advisor whose 1,600,000 cap is consumed by two contests.

    The book carries seven accounts in the transfer window so that the losing
    leg, which submits two losses, stays inside the PRD shortfall of 10,000 minus
    7,000 basis points (two of seven is 2,857).
    """
    ctx = setup_retention_scenario(
        advisor_code=advisor_code,
        account_numbers=("A-4001", "A-4002", "A-4003", "A-4004", "A-4005",
                         "A-4006", "A-4007"),
        account_balances=(20_000_000, 16_000_000, 20_000_000, 1_000_000,
                          1_000_000, 1_000_000, 1_000_000),
        book_transferred_cents=80_000_000,
        with_transition=False)
    period = open_period(period_index=2)
    transition = open_transition(ctx["advisor"], period["id"])
    ctx["period"] = period
    ctx["transition"] = transition
    first = get_success_data(contest_account(transition["id"],
                                             ctx["accounts"][0]["id"], 500))
    second = get_success_data(contest_account(transition["id"],
                                              ctx["accounts"][1]["id"], 500))
    return {"advisor": ctx["advisor"], "accounts": ctx["accounts"],
            "period": ctx["period"], "transition": transition,
            "first": first, "second": second}


def test_the_watermark_never_over_commits_the_book_cap():
    """PRD §3.8: "When the watermark has already reached the cap, no further account can be
    contested and the attempt is refused with `ERR_RETENTION_CREDIT_EXHAUSTED` at HTTP 409,
    with no row posted."

    Design: Difficulty/compensating_invariant/retention_sweep_reversal_reconciles_to_zero_drift
    """
    fx = _exhausted_cap_fixture("A-6009")
    assert fx["first"]["credit_amount_cents"] == 1_000_000
    assert fx["second"]["credit_amount_cents"] == 600_000, (
        "800,000 clipped to the 600,000 that remains of the 1,600,000 cap")
    assert fx["first"]["credit_amount_cents"] + fx["second"]["credit_amount_cents"] == 1_600_000

    third = contest_account(fx["transition"]["id"], fx["accounts"][2]["id"], 500)
    validate_error(third, ApiErrorId.ERR_RETENTION_CREDIT_EXHAUSTED)

    rows = get_success_data(list_retention_rows(fx["transition"]["id"]))
    assert len(rows) == 2
    assert sum(row["credit_amount_cents"] for row in rows) == 1_600_000


def test_the_losing_leg_leaves_settled_amount_exactly_at_the_posted_credits():
    """PRD §3.8: "The transition's `settled_amount_cents` is the sum of credit amounts
    over its `POSTED`, `RETAINED`, and `LOST` rows, with `VOID` rows excluded".

    Design: Difficulty/compensating_invariant/retention_sweep_reversal_reconciles_to_zero_drift
    """
    fx = _exhausted_cap_fixture("A-6010")
    loss = lose_retention(fx["transition"]["id"],
                          [fx["accounts"][0]["id"], fx["accounts"][1]["id"]],
                          fx["advisor"])
    settled = get_success_data(loss)
    assert settled["status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 1_600_000, (
        "exactly the sum of the posted credits")

    rows = get_success_data(list_retention_rows(fx["transition"]["id"]))
    assert sum(row["credit_amount_cents"] for row in rows) - \
        settled["settled_amount_cents"] == 0, "the losing leg left no drift"
    assert {row["status"] for row in rows} <= {"LOST", "RETAINED"}


# ─── resource_temporal_overlap ────────────────────────

def _overlap_fixture(advisor_code):
    """DEPARTING advisor; two accounts contested and one already transferred out."""
    ctx = setup_retention_scenario(
        advisor_code=advisor_code,
        account_numbers=("A-1307-1", "A-1307-2", "A-1307-3"),
        account_balances=(10_000_000, 10_000_000, 10_000_000))
    transition = ctx["transition"]
    contest_account(transition["id"], ctx["accounts"][0]["id"], 500)
    contest_account(transition["id"], ctx["accounts"][1]["id"], 500)
    confirm_transfer(ctx["accounts"][2]["id"])
    return ctx, transition


def test_a_second_contest_for_the_same_account_in_the_open_period_is_refused():
    """PRD §3.8: "an account already contested, already retained, or already
    `TRANSFERRED_OUT` cannot be contested again within the same period".
    PRD §3.8: "A contest may only be opened for an account whose status is
    `PENDING_TRANSFER`".

    Design: Difficulty/resource_temporal_overlap/one_contest_per_open_period_and_account
    """
    ctx, transition = _overlap_fixture("A-6011")
    repeat = contest_account(transition["id"], ctx["accounts"][0]["id"], 500)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE)

    rows = get_success_data(list_retention_rows(transition["id"]))
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"POSTED"}


def test_the_contested_and_transferred_accounts_both_leave_the_transfer_window():
    """PRD §3.8: "Contesting an account grants it a retention credit and moves it to
    `RETENTION_CONTESTED`."
    PRD §3.8: "Confirming moves the account to `TRANSFERRED_OUT`".

    Design: Difficulty/resource_temporal_overlap/one_contest_per_open_period_and_account
    """
    ctx, transition = _overlap_fixture("A-6012")
    accounts = {row["account_number"]: get_success_data(
        api_client.get_account(row["id"], PLATFORM_ADMIN))["status"]
        for row in ctx["accounts"]}
    assert accounts["A-1307-1"] == "RETENTION_CONTESTED"
    assert accounts["A-1307-2"] == "RETENTION_CONTESTED"
    assert accounts["A-1307-3"] == "TRANSFERRED_OUT"


# ─── resource_temporal_overlap: transfer confirmation ──

def _transferred_account_fixture(advisor_code):
    ctx = setup_retention_scenario(advisor_code=advisor_code,
                                   account_numbers=("A-1308-1",),
                                   account_balances=(10_000_000,))
    # pending_transfer_at was stamped at the startup default, so advancing to the
    # next day clears the twenty-four-hour hold without moving the clock again.
    confirm_transfer(ctx["accounts"][0]["id"])
    return ctx


def test_a_consumed_transfer_window_cannot_be_confirmed_again():
    """PRD §3.8: "An account in `PENDING_TRANSFER` may only be confirmed once the logical
    clock is at or after its `pending_transfer_at` plus twenty-four hours".
    PRD §3.8: "Confirmation also requires an active office of supervisory jurisdiction".

    Design: Difficulty/resource_temporal_overlap/one_transfer_confirmation_per_account_and_the_thaw_gap
    """
    ctx = _transferred_account_fixture("A-6013")
    account = get_success_data(api_client.get_account(ctx["accounts"][0]["id"],
                                                     PLATFORM_ADMIN))
    assert account["status"] == "TRANSFERRED_OUT"

    replay = api_client.confirm_transfer(ctx["accounts"][0]["id"], COMPLIANCE_OFFICER)
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE)


def test_the_transferred_account_leaves_the_transfer_queue_permanently():
    """PRD §3.8: "sets its `fee_levelized` flag, and voids the owning advisor's draft
    revenue entries so that an account that has left can no longer earn against the firm."

    Design: Difficulty/resource_temporal_overlap/one_transfer_confirmation_per_account_and_the_thaw_gap
    """
    ctx = _transferred_account_fixture("A-6014")
    account = get_success_data(api_client.get_account(ctx["accounts"][0]["id"],
                                                     PLATFORM_ADMIN))
    assert account["fee_levelized"] is True

    booking = api_client.create_revenue_entry(
        {"advisor_code": ctx["advisor"]["advisor_code"],
         "account_id": ctx["accounts"][0]["id"],
         "product_type": "EQUITY",
         "gross_commission_cents": 1_000_000,
         "production_date": "2026-09-03"},
        make_advisor_ops_headers(ctx["advisor"]["id"]))
    validate_error(booking, ApiErrorId.ERR_INVALID_STATE)
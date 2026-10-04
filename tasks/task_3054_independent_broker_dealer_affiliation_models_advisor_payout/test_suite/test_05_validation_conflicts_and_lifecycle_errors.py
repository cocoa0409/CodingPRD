"""Validation precedence and the lifecycle rejection catalogue."""
from test_helpers import (
    api_client, get_success_data, validate_error, ApiErrorId,
    refresh_advisor, refresh_branch, setup_active_advisor,
    setup_funded_period, setup_departing_advisor, setup_retention_scenario,
    open_account, open_period, contest_account, lose_retention,
    start_book_transfer, book_entry, release_entry,
    make_advisor_ops_headers, set_clock, confirm_transfer,
    advance_period,
    PLATFORM_ADMIN, BRANCH_MANAGER, COMPLIANCE_OFFICER,
)


# ─── priority_pair_validation_conflict ────────────────

def test_a_second_levelization_sweep_in_the_same_year_is_refused():
    """PRD §3.6: "When every eligible advisory account of the advisor has already been
    levelized for the calendar year, the sweep is refused with `ERR_YEAR_ALREADY_LEVELIZED`
    at HTTP 409."
    PRD §2.10: "the period a retention contest or book transfer consumes must not be
    already `PAID` or `VOID`, otherwise `ERR_PERIOD_ALREADY_POSTED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/advisory_levelization_when_year_already_swept_prefers_fiscal_over_safety
    """
    ctx = setup_active_advisor(advisor_code="A-7005")
    advisor = ctx["advisor"]
    open_account(advisor, "A-7005-ADV", account_type="ADVISORY",
                 balance_cents=20_000_000, annual_fee_cents=2_000_000)
    period = open_period()

    headers = make_advisor_ops_headers(advisor["id"])
    first = get_success_data(api_client.levelize_advisory_splits(
        {"advisor_code": advisor["advisor_code"], "payout_period_id": period["id"]},
        headers))
    assert len(first) == 1

    limited = get_success_data(api_client.patch_advisor(
        advisor["id"],
        {"eo_coverage_level": "LIMITED",
         "expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        headers))
    assert limited["eo_coverage_level"] == "LIMITED"

    second = api_client.levelize_advisory_splits(
        {"advisor_code": advisor["advisor_code"], "payout_period_id": period["id"]},
        headers)
    validate_error(second, ApiErrorId.ERR_YEAR_ALREADY_LEVELIZED)


def test_the_refused_second_sweep_creates_no_duplicate_split():
    """PRD §3.6: "The account's `annual_fee_cents` is then rewritten to the base fee plus
    the delta, so that a second sweep within the same calendar year finds the account
    already levelized and leaves it untouched."

    Design: Difficulty/priority_pair_validation_conflict/advisory_levelization_when_year_already_swept_prefers_fiscal_over_safety
    """
    ctx = setup_active_advisor(advisor_code="A-7006")
    advisor = ctx["advisor"]
    account = open_account(advisor, "A-7006-ADV", account_type="ADVISORY",
                           balance_cents=20_000_000, annual_fee_cents=170_000)
    period = open_period()

    headers = make_advisor_ops_headers(advisor["id"])
    first = get_success_data(api_client.levelize_advisory_splits(
        {"advisor_code": advisor["advisor_code"], "payout_period_id": period["id"]},
        headers))
    assert first[0]["status"] == "POSTED"
    assert first[0]["levelization_delta_cents"] == 0, (
        "170,000 of a 20,000,000 balance is already the 85 basis point target")

    api_client.levelize_advisory_splits(
        {"advisor_code": advisor["advisor_code"], "payout_period_id": period["id"]},
        headers)
    splits = get_success_data(api_client.list_advisory_splits(
        PLATFORM_ADMIN, {"account_id": account["id"]}))
    assert len(splits) == 1


# ─── boundary_precision_check: loan milestone ─────────

def _milestone_fixture(advisor_code):
    """An advisor with a 1,000,000 loan at a 90 percent milestone and a 10 percent
    amortization rate, plus one released entry of 899,999 cents.

    The milestone threshold is the principal multiplied by the percentage and
    divided by 100, rounded half up, so 90 percent of 1,000,000 is 900,000 and
    the single entry sits one cent below it.
    """
    ctx = setup_funded_period(
        advisor_code=advisor_code, projected_annual_production_cents=100_000_000,
        principal_cents=1_000_000, amortization_rate_bps=1000,
        forgiveness_milestone_pct=90, period_index=1,
        entries=((899_999, "2026-07-02", "EQUITY"),), period_month=7)
    advisor = ctx["advisor"]
    release_entry(ctx["entries"][0], advisor)
    return ctx


def test_the_forgiveness_milestone_is_refused_one_cent_below_the_threshold():
    """PRD §3.2: "The milestone threshold is the `principal_cents` multiplied by the
    `forgiveness_milestone_pct` and divided by 100, rounded half up. When
    `milestone_progress_cents` reaches that threshold, `forgiveness_amount_cents` is the
    `principal_cents` multiplied by the milestone percentage using integer floor division
    by 100".

    Design: Difficulty/boundary_precision_check/loan_milestone_and_transfer_hold_boundaries
    """
    ctx = _milestone_fixture("A-7007")
    advisor = ctx["advisor"]

    response = api_client.forgive_loan(
        ctx["loan"]["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_the_forgiveness_milestone_clears_at_exactly_the_threshold():
    """PRD §3.2: "When `milestone_progress_cents` reaches that threshold,
    `forgiveness_amount_cents` is the `principal_cents` multiplied by the milestone
    percentage using integer floor division by 100 — this division is floor-divided and is
    not rounded — clipped so that it never exceeds the remaining balance".
    PRD §3.2: "When `milestone_progress_cents` reaches that threshold,
    `forgiveness_amount_cents` is the `principal_cents` multiplied by the milestone
    percentage using integer floor division by 100 — this division is floor-divided and is
    not rounded — clipped so that it never exceeds the remaining balance".

    Design: Difficulty/boundary_precision_check/loan_milestone_and_transfer_hold_boundaries
    """
    ctx = _milestone_fixture("A-7008")
    advisor = ctx["advisor"]

    extra = book_entry(advisor, ctx["account"]["id"], 1, "2026-08-04")
    release_entry(extra, advisor)

    forgiven = get_success_data(api_client.forgive_loan(
        ctx["loan"]["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"])))
    assert forgiven["status"] == "FORGIVEN"
    assert forgiven["principal_cents"] - forgiven["remaining_balance_cents"] \
        >= 100_000, "the milestone booked the floor of 10 percent of the principal"


def test_the_amortization_draw_rounds_the_release_amount_once():
    """PRD §3.2: "the draw is the line's `release_amount_cents` multiplied by the loan's
    `amortization_rate_bps` and divided by 10000, rounded half up to whole cents, and then
    clipped to whatever balance remains."
    PRD §3.4: "A line's `release_amount_cents` is not a rounded total; it is the sum of
    per-entry rounded amounts."

    Design: Difficulty/boundary_precision_check/loan_milestone_and_transfer_hold_boundaries
    """
    ctx = setup_funded_period(
        advisor_code="A-7009", projected_annual_production_cents=100_000_000,
        principal_cents=1_000_000, amortization_rate_bps=1000,
        forgiveness_milestone_pct=10,
        entries=((899_999, "2026-09-02", "EQUITY"),
                 (1, "2026-09-04", "EQUITY")),
        release=True)
    advance_period(ctx["period"]["id"], "CLOSED", ctx["branch"]["branch_code"])
    advance_period(ctx["period"]["id"], "PAID", ctx["branch"]["branch_code"])

    # The line pays each entry at the 8,000-basis-point provisional rate and sums
    # the rounded contributions: 719,999 + 1 = 720,000.
    line = get_success_data(api_client.get_payout_line(ctx["line"]["id"], PLATFORM_ADMIN))
    assert line["release_amount_cents"] == 720_000

    loan = get_success_data(api_client.get_payout_loan(ctx["loan"]["id"], PLATFORM_ADMIN))
    assert loan["remaining_balance_cents"] == 1_000_000 - 72_000, (
        "the draw is round(720,000 at 1,000 basis points) == 72,000")


def test_a_transfer_confirmation_inside_the_hold_window_is_refused():
    """PRD §3.8: "An account in `PENDING_TRANSFER` may only be confirmed once the logical
    clock is at or after its `pending_transfer_at` plus twenty-four hours — exactly
    twenty-four hours having passed is sufficient — and a confirmation attempted earlier is
    refused with `ERR_TRANSFER_HOLD_PERIOD` at HTTP 409."

    Design: Difficulty/boundary_precision_check/loan_milestone_and_transfer_hold_boundaries
    """
    ctx = setup_departing_advisor(advisor_code="A-7010",
                                  account_numbers=("A-7010-1",),
                                  account_balances=(10_000_000,))
    start_book_transfer(ctx["advisor"])

    early = api_client.confirm_transfer(ctx["accounts"][0]["id"], COMPLIANCE_OFFICER)
    validate_error(early, ApiErrorId.ERR_TRANSFER_HOLD_PERIOD)


def test_a_transfer_confirmation_at_exactly_twenty_four_hours_succeeds():
    """PRD §3.8: "exactly twenty-four hours having passed is sufficient".
    PRD §3.8: "Confirming moves the account to `TRANSFERRED_OUT`, sets its `fee_levelized`
    flag".

    Design: Difficulty/boundary_precision_check/loan_milestone_and_transfer_hold_boundaries
    """
    ctx = setup_departing_advisor(advisor_code="A-7011",
                                  account_numbers=("A-7011-1",),
                                  account_balances=(10_000_000,))
    start_book_transfer(ctx["advisor"])
    set_clock("2026-09-02T00:00:00Z")

    confirmed = confirm_transfer(ctx["accounts"][0]["id"])
    assert confirmed["status"] == "TRANSFERRED_OUT"
    assert confirmed["fee_levelized"] is True


# ─── corner: errors ───────────────────────────────────

def test_a_duplicate_payout_period_for_the_same_slot_is_refused():
    """PRD §3.3: "The combination of branch, year, month, and index may exist only once; a
    duplicate is refused with `ERR_PERIOD_ALREADY_EXISTS` at HTTP 409."

    Design: Corner/errors/duplicate_payout_period_returns_already_exists
    """
    from test_helpers import create_branch
    create_branch()
    open_period(period_index=1)

    duplicate = api_client.create_payout_period(
        {"branch_code": "SUP-1", "year": 2026, "month": 9, "period_index": 1},
        BRANCH_MANAGER)
    validate_error(duplicate, ApiErrorId.ERR_PERIOD_ALREADY_EXISTS)


def test_the_period_uniqueness_key_includes_the_period_index():
    """PRD §3.3: "five periods are permitted within a calendar month".
    PRD §3.3: "The combination of branch, year, month, and index may exist only once".

    Design: Corner/errors/duplicate_payout_period_returns_already_exists
    """
    from test_helpers import create_branch
    create_branch()
    open_period(period_index=1)
    open_period(period_index=2)

    rows = get_success_data(api_client.list_payout_periods(
        PLATFORM_ADMIN, {"branch_code": "SUP-1"}))
    assert len(rows) == 2, "the uniqueness key includes the period index"

    beyond = api_client.create_payout_period(
        {"branch_code": "SUP-1", "year": 2026, "month": 9, "period_index": 6},
        BRANCH_MANAGER)
    validate_error(beyond, ApiErrorId.ERR_INVALID_REQUEST)


def test_affiliation_is_refused_while_the_branch_is_not_active():
    """PRD §3.1: "a `primary_branch_code` whose branch has `status` `ACTIVE` (otherwise
    `ERR_BRANCH_NOT_ACTIVE` at HTTP 409)".

    Design: Corner/errors/branch_inactive_blocks_advisor_activation
    """
    from test_helpers import create_branch, create_advisor, create_loan, enroll_advisor
    create_branch(branch_code="SOLO-1", name="Solo Practice",
                  transmittal_account="TA-9001", osj_name="Solo OSJ")
    advisor = create_advisor("A-7012", "1234582", "Tess Oyelaran",
                             primary_branch_code="SOLO-1",
                             ingested_book_total_cents=500_000_000,
                             book_transferred_cents=300_000_000,
                             protocol_eligible=True)
    create_loan(advisor, principal_cents=500_000, forgiveness_milestone_pct=90)
    enrolled = enroll_advisor(advisor)
    assert enrolled["status"] == "ONBOARDING"

    response = api_client.affiliate_advisor(
        advisor["id"],
        {"affiliation_model": "IC",
         "expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_BRANCH_NOT_ACTIVE)
    assert refresh_advisor(advisor["id"])["status"] == "ONBOARDING"


def test_the_retention_cap_refusal_is_reported_on_the_next_contest():
    """PRD §3.8: "When the watermark has already reached the cap, no further account can be
    contested and the attempt is refused with `ERR_RETENTION_CREDIT_EXHAUSTED` at HTTP 409,
    with no row posted."
    PRD §3.8: "The cap is 200 basis points of the advisor's `book_transferred_cents`".

    Design: Corner/errors/retention_credit_exhausted_is_reported_on_the_next_contest
    """
    ctx = setup_retention_scenario(
        advisor_code="A-7013",
        account_numbers=("A-5001", "A-5002", "A-5003"),
        account_balances=(5_000_000, 25_000_000, 5_000_000),
        book_transferred_cents=1_000_000)
    transition = ctx["transition"]
    accounts = ctx["accounts"]

    first = get_success_data(contest_account(transition["id"], accounts[0]["id"], 200))
    assert first["credit_amount_cents"] == 20_000, (
        "200 basis points of the 5,000,000 account, inside the 20,000 cap")

    second = contest_account(transition["id"], accounts[1]["id"], 200)
    # 200 basis points of the 25,000,000 account is 500,000, entirely absorbed by
    # the 20,000 cap, so this second contest is refused outright.
    validate_error(second, ApiErrorId.ERR_RETENTION_CREDIT_EXHAUSTED)

    third = contest_account(transition["id"], accounts[2]["id"], 200)
    validate_error(third, ApiErrorId.ERR_RETENTION_CREDIT_EXHAUSTED)

    rows = get_success_data(api_client.list_transition_retention_rows(
        transition["id"], BRANCH_MANAGER))
    assert len(rows) == 1, "the refused contests posted no further row"
    reread = get_success_data(api_client.get_transition(transition["id"],
                                                        BRANCH_MANAGER))
    assert reread["settled_amount_cents"] == 20_000


def test_settling_a_departure_before_the_transition_settles_is_refused():
    """PRD §3.7: "Moving an advisor from `DEPARTING` to `DEPARTED` requires that the
    advisor's transition record has reached `SETTLED` — otherwise
    `ERR_TRANSITION_NOT_SETTLED` at HTTP 409".

    Design: Corner/errors/settling_before_the_transition_settles_returns_not_settled
    """
    ctx = setup_retention_scenario(advisor_code="A-7014")
    advisor, transition = ctx["advisor"], ctx["transition"]
    assert transition["status"] == "CONTESTED"

    response = api_client.settle_departure(
        advisor["id"], {"expected_advisor_version": advisor["version"]},
        COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.ERR_TRANSITION_NOT_SETTLED)


def test_settling_succeeds_once_the_transition_has_settled():
    """PRD §3.7: "Settlement sets the advisor to `DEPARTED`".
    PRD §3.8: "On success the transition becomes `SETTLED`; every submitted account and
    its retention row become `RETAINED`".

    Design: Corner/errors/settling_before_the_transition_settles_returns_not_settled
    """
    from test_helpers import settle_retention
    ctx = setup_retention_scenario(
        advisor_code="A-7015",
        account_numbers=("A-7015-1", "A-7015-2", "A-7015-3", "A-7015-4"),
        account_balances=(10_000_000, 10_000_000, 10_000_000, 10_000_000))
    advisor, transition = ctx["advisor"], ctx["transition"]
    for account in ctx["accounts"]:
        contest_account(transition["id"], account["id"], 500)

    closed = settle_retention(transition["id"],
                              [account["id"] for account in ctx["accounts"]],
                              advisor)
    assert get_success_data(closed)["status"] == "SETTLED"

    settled = get_success_data(api_client.settle_departure(
        advisor["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        COMPLIANCE_OFFICER))
    assert settled["status"] == "DEPARTED"
    assert settled["retention_status"] == "DEPARTED_CONFIRMED"
    assert settled["outstanding_loan_balance_cents"] == 0


def test_contesting_onto_a_transition_that_is_not_contested_is_refused():
    """PRD §3.8: "a contest is refused with `ERR_TRANSITION_NOT_CONTESTED` at HTTP 409 when
    the transition it targets is not in `CONTESTED` status."

    Design: Corner/errors/contest_on_a_transition_that_is_not_contested_returns_not_contested
    """
    ctx = setup_retention_scenario(
        advisor_code="A-7016",
        account_numbers=("A-7016-1", "A-7016-2", "A-7016-3", "A-7016-4"),
        account_balances=(10_000_000, 10_000_000, 10_000_000, 10_000_000))
    advisor = ctx["advisor"]
    accounts = ctx["accounts"]
    transition = ctx["transition"]
    assert transition["status"] == "CONTESTED"

    for account in accounts:
        contest_account(transition["id"], account["id"], 500)

    # Closing the contest as lost settles the transition, so it is no longer in
    # CONTESTED status while its lost account returns to the transfer window.
    closed = get_success_data(lose_retention(transition["id"],
                                             [accounts[0]["id"]], advisor))
    assert closed["status"] == "SETTLED"

    contested = api_client.contest_retention(
        transition["id"],
        {"account_id": accounts[0]["id"], "retention_rate_bps": 500},
        BRANCH_MANAGER)
    validate_error(contested, ApiErrorId.ERR_TRANSITION_NOT_CONTESTED)

    rows = get_success_data(api_client.list_transition_retention_rows(
        transition["id"], BRANCH_MANAGER))
    assert len(rows) == 4, "the refused contest created no fifth row"


# ─── corner: validations ──────────────────────────────

def test_coverage_outranks_the_transfer_hold_window():
    """PRD §3.8: "Confirmation also requires an active office of supervisory jurisdiction,
    so an advisor with `LIMITED` coverage or a branch that is not supervised is refused
    with `ERR_EO_COVERAGE_INSUFFICIENT` at HTTP 403."
    PRD §2.10: "Coverage: the advisor's errors-and-omissions coverage must not be `LIMITED`
    and the relevant branch's office of supervisory jurisdiction must be active, otherwise
    `ERR_EO_COVERAGE_INSUFFICIENT` (403)."

    Design: Corner/validations/coverage_and_supervision_beat_the_transfer_hold_window
    """
    ctx = setup_departing_advisor(advisor_code="A-7017",
                                  account_numbers=("A-7017-1",),
                                  account_balances=(10_000_000,),
                                  open_caller_period=False)
    advisor = ctx["advisor"]
    # The branch can only be demoted once it holds no OPEN or REOPENED period, so
    # this scenario leaves the branch with none; the book is then released into
    # the transfer window with the clock still at the hold's opening instant.
    from test_helpers import demote_branch
    demote_branch(advisor["primary_branch_code"],
                  enrollment_id=ctx["supervisor_enrollment"]["id"],
                  link_id=ctx["supervisor_link"]["id"])
    assert refresh_branch(ctx["branch"]["id"])["state"] == "UNSUPERVISED"

    response = api_client.confirm_transfer(ctx["accounts"][0]["id"],
                                          COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.ERR_EO_COVERAGE_INSUFFICIENT)

    account = get_success_data(api_client.get_account(ctx["accounts"][0]["id"],
                                                     PLATFORM_ADMIN))
    assert account["status"] == "PENDING_TRANSFER"


def test_the_unknown_branch_is_reported_before_the_payload_range_check():
    """PRD §2.10: "Existence of the branch named by `branch_code`, otherwise
    `ERR_BRANCH_NOT_FOUND` (404)."
    PRD §3.3: "a `period_index` from 1 through 5 — five periods are permitted within a
    calendar month."

    Design: Corner/validations/unknown_branch_is_reported_before_the_period_index_range_check
    """
    response = api_client.create_payout_period(
        {"branch_code": "GHOST-9", "year": 2026, "month": 9, "period_index": 9},
        BRANCH_MANAGER)
    validate_error(response, ApiErrorId.ERR_BRANCH_NOT_FOUND)

    rows = get_success_data(api_client.list_payout_periods(PLATFORM_ADMIN))
    assert len(rows) == 0
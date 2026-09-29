"""Quarterly funding runs: the front-loaded slice, the checkpoint and the skips."""

from test_helpers import (
    AWARD_BAND_B_IEP,
    BALANCE_AFTER_TWO_QUARTERS,
    LIFETIME_ADMIN_FEE_TWO_QUARTERS,
    LIFETIME_DISBURSED_TWO_QUARTERS,
    PA,
    Q1_ADMIN_FEE_CENTS,
    Q1_GROSS_CENTS,
    Q1_NET_CENTS,
    Q2_GROSS_CENTS,
    Q2_NET_CENTS,
    ApiErrorId,
    assert_append_only_record,
    assert_disbursement,
    assert_iso_millis,
    assert_ledger_identity,
    create_program_year,
    open_window,
    read_account,
    read_program_year,
    run_disbursement,
    setup_accepted_award,
    setup_funded_account,
    suspend_account,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestQuarterlySlice:
    """The indivisible remainder rides on the first disbursement only."""

    def test_first_quarter_carries_the_whole_remainder(self, api):
        """PRD §3.5: "`gross_amount_cents` is the even slice, plus the indivisible
        remainder if and only if this is the account's very first disbursement, meaning
        its `disbursement_count` was 0 when the pass reached it. The remainder is
        front-loaded onto the first disbursement only; it is never spread across quarters
        and never appended to the last one."

        PRD §3.5: "A `final_award_cents` of 932663 over four quarters therefore pays
        233168, then 233165, then 233165, then 233165, with a fee of 4080 on each."

        Design: Corner/calculations/quarterly_slice_front_loads_the_whole_remainder
        """
        env = setup_accepted_award()
        assert env.account["final_award_cents"] == AWARD_BAND_B_IEP, (
            f"the account funds a 932663 award, got {env.account['final_award_cents']}"
        )

        first = validate_success(api.run_disbursement(env.program_year_id, 1, PA))
        assert first["total_gross_cents"] == Q1_GROSS_CENTS, (
            f"the first quarter pays 233168, got {first['total_gross_cents']}"
        )
        assert first["total_admin_fee_cents"] == Q1_ADMIN_FEE_CENTS, (
            f"with a fee of 4080, got {first['total_admin_fee_cents']}"
        )
        assert first["total_net_credited_cents"] == Q1_NET_CENTS, (
            f"leaving 229088 credited, got {first['total_net_credited_cents']}"
        )

        second = validate_success(api.run_disbursement(env.program_year_id, 2, PA))
        assert second["total_gross_cents"] == Q2_GROSS_CENTS, (
            "the second quarter pays the even slice of 233165 with no remainder, got "
            f"{second['total_gross_cents']}"
        )
        assert second["total_net_credited_cents"] == Q2_NET_CENTS, (
            f"leaving 229085 credited, got {second['total_net_credited_cents']}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
            f"the two net credits sum to 458173, got {account['balance_cents']}"
        )
        assert account["lifetime_disbursed_cents"] == LIFETIME_DISBURSED_TWO_QUARTERS, (
            f"the two gross amounts sum to 466333, got "
            f"{account['lifetime_disbursed_cents']}"
        )
        assert account["lifetime_admin_fee_cents"] == LIFETIME_ADMIN_FEE_TWO_QUARTERS, (
            f"the two fees sum to 8160, got {account['lifetime_admin_fee_cents']}"
        )
        assert account["disbursement_count"] == 2, (
            f"two disbursements have been credited, got {account['disbursement_count']}"
        )

        rows, meta = validate_paginated(
            api.list_account_disbursements(env.account_id, PA)
        )
        assert meta["total_count"] == 2, (
            f"one row is appended per credited quarter, got {meta['total_count']}"
        )
        assert [row["quarter"] for row in rows] == [1, 2], (
            f"the rows read oldest quarter first, got {rows!r}"
        )
        assert rows[0]["remainder_applied_cents"] == Q1_GROSS_CENTS - Q2_GROSS_CENTS, (
            "the amount folded in is recorded on the first row, got "
            f"{rows[0]['remainder_applied_cents']}"
        )
        assert rows[1]["remainder_applied_cents"] == 0, (
            "remainder_applied_cents is 0 on every disbursement after the first, got "
            f"{rows[1]['remainder_applied_cents']}"
        )
        assert rows[0]["quarters_left_at_issue"] == 4, (
            "the quarters still owed when the first row issued was 4, got "
            f"{rows[0]['quarters_left_at_issue']}"
        )
        assert rows[1]["quarters_left_at_issue"] == 3, (
            f"and 3 when the second issued, got {rows[1]['quarters_left_at_issue']}"
        )
        assert read_program_year(env.program_year_id)["current_quarter"] == 2, (
            "the year's checkpoint stands at the quarter last funded"
        )

    def test_suspended_account_is_named_rather_than_silently_ignored(self, api):
        """PRD §3.5: "Accounts that are skipped are named rather than silently ignored:
        an account whose status is `SUSPENDED` or `CLOSED`, or whose `disbursement_count`
        has already reached its `quarters_remaining_at_award`, receives nothing and is
        listed in `skipped_account_ids`."

        PRD §3.5: "A successful run leaves the year in `ACTIVE` — it is a self-loop, not
        a lifecycle advance — sets `current_quarter` to the supplied `quarter`, and raises
        the year's `version` by 1."

        Design: Corner/calculations/disbursement_run_skips_suspended_accounts
        """
        env = setup_accepted_award()
        suspended = suspend_account(env.account_id)
        assert suspended["status"] == "SUSPENDED", (
            f"the account is suspended before the run, got {suspended['status']!r}"
        )

        run = validate_success(api.run_disbursement(env.program_year_id, 1, PA))

        assert run["disbursement_count"] == 0, (
            "no disbursement row was issued by this run, got "
            f"{run['disbursement_count']}"
        )
        assert run["total_gross_cents"] == 0, (
            f"no money left the programme, got {run['total_gross_cents']}"
        )
        assert run["total_net_credited_cents"] == 0, (
            f"and nothing was credited, got {run['total_net_credited_cents']}"
        )
        assert env.account_id in run["skipped_account_ids"], (
            "the skipped account is named in skipped_account_ids, got "
            f"{run['skipped_account_ids']!r}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == 0, (
            f"the suspended account receives nothing, got {account['balance_cents']}"
        )
        assert account["lifetime_disbursed_cents"] == 0, (
            f"and its lifetime counter stays at 0, got "
            f"{account['lifetime_disbursed_cents']}"
        )
        assert account["disbursement_count"] == 0, (
            f"and no disbursement is counted against it, got "
            f"{account['disbursement_count']}"
        )
        _, meta = validate_paginated(api.list_account_disbursements(env.account_id, PA))
        assert meta["total_count"] == 0, (
            f"no row was appended for the skipped account, got {meta['total_count']}"
        )

        year = read_program_year(env.program_year_id)
        assert year["current_quarter"] == 1, (
            "the run still sets current_quarter to the supplied quarter, got "
            f"{year['current_quarter']}"
        )
        assert year["status"] == "ACTIVE", (
            f"the run is a self-loop and leaves the year ACTIVE, got {year['status']!r}"
        )


class TestAccountTotals:
    """The account read reconciles exactly with its disbursement rows."""

    def test_totals_after_two_runs_reconcile_with_the_rows(self, api):
        """PRD §2.11: "An ESA account is a small ledger, and its fields are related by
        identities that must hold after every operation."

        PRD §2.11: "`lifetime_disbursed_cents` accumulates the gross entitlement credited
        by disbursement runs, `lifetime_admin_fee_cents` accumulates the administration fee
        withheld from those credits, `lifetime_spent_cents` accumulates settled spend net
        of reversals, and `lifetime_clawed_back_cents` accumulates amounts recovered by
        clawback net of reversals. `disbursement_count` counts the disbursement rows issued
        to the account."

        PRD §2.3: "Unless a specific endpoint states otherwise, every list is ordered by
        `created_at` ascending — oldest record first."

        Design: Corner/endpoints/account_totals_are_a_computed_read_after_two_runs
        """
        env = setup_funded_account(quarters=2)

        account = validate_success(api.get_account(env.account_id, env.guardian))
        assert account["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
            f"the balance after two runs is 458173, got {account['balance_cents']}"
        )
        assert account["lifetime_disbursed_cents"] == LIFETIME_DISBURSED_TWO_QUARTERS, (
            f"lifetime_disbursed_cents is 466333, got "
            f"{account['lifetime_disbursed_cents']}"
        )
        assert account["lifetime_admin_fee_cents"] == LIFETIME_ADMIN_FEE_TWO_QUARTERS, (
            f"lifetime_admin_fee_cents is 8160, got "
            f"{account['lifetime_admin_fee_cents']}"
        )
        assert account["disbursement_count"] == 2, (
            f"disbursement_count is 2, got {account['disbursement_count']}"
        )
        assert account["encumbered_cents"] == 0 and account["lifetime_spent_cents"] == 0, (
            f"nothing has been committed or spent yet, got {account!r}"
        )
        assert_ledger_identity(account)

        rows, meta = validate_paginated(
            api.list_account_disbursements(env.account_id, env.guardian)
        )
        assert meta["total_count"] == 2, (
            f"the disbursements list returns the two rows, got {meta['total_count']}"
        )
        assert rows[0]["quarter"] == 1, (
            f"oldest record first, so quarter 1 leads, got {rows[0]['quarter']}"
        )
        assert sum(row["gross_amount_cents"] for row in rows) == account[
            "lifetime_disbursed_cents"
        ], f"the row grosses reconcile with lifetime_disbursed_cents, got {rows!r}"
        assert sum(row["admin_fee_cents"] for row in rows) == account[
            "lifetime_admin_fee_cents"
        ], f"the row fees reconcile with lifetime_admin_fee_cents, got {rows!r}"
        assert sum(row["net_credited_cents"] for row in rows) == account[
            "balance_cents"
        ], f"the row net credits reconcile with the balance, got {rows!r}"


class TestDisbursementRowShape:
    """Disbursement rows are append-only evidence with no version at all."""

    def test_row_carries_only_the_append_only_system_fields(self, api):
        """PRD §2.4: "Four record types are append-only event evidence rather than mutable
        state, and they deliberately carry **only** `id` and `created_at` — they have no
        `updated_at` and no `version` field at all. Those four are the eligibility
        determination, the fraud screening, the disbursement, and the clawback ledger
        entry."

        Design: Corner/entities/disbursement_rows_are_immutable_and_carry_no_version
        """
        env = setup_funded_account(quarters=1)

        response = api.list_account_disbursements(env.account_id, env.guardian)
        assert response.status_code == 200, (
            f"the listing succeeds, got HTTP {response.status_code}"
        )
        assert response.json()["response_type"] == "array", (
            "a list of resources is reported with response_type array, got "
            f"{response.json()['response_type']!r}"
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (
            f"one quarter has been credited, got {meta['total_count']}"
        )

        row = rows[0]
        assert_disbursement(row)
        assert_append_only_record(row, "disbursement")
        assert "version" not in row, (
            f"a disbursement row has no version field at all, got {sorted(row)!r}"
        )
        assert "updated_at" not in row, (
            f"and no updated_at either, got {sorted(row)!r}"
        )
        assert_iso_millis(row["created_at"], "disbursement.created_at")

        assert row["quarter"] == 1, f"the row funds quarter 1, got {row['quarter']}"
        assert row["gross_amount_cents"] == Q1_GROSS_CENTS, (
            f"the gross is 233168, got {row['gross_amount_cents']}"
        )
        assert row["admin_fee_cents"] == Q1_ADMIN_FEE_CENTS, (
            f"the fee is 4080, got {row['admin_fee_cents']}"
        )
        assert row["net_credited_cents"] == Q1_NET_CENTS, (
            f"the net credited is 229088, got {row['net_credited_cents']}"
        )
        assert row["account_id"] == env.account_id, (
            f"the row records the account_id, got {row['account_id']!r}"
        )
        assert row["program_year_id"] == env.program_year_id, (
            f"and the program_year_id, got {row['program_year_id']!r}"
        )

        year_rows, year_meta = validate_paginated(
            api.list_program_year_disbursements(env.program_year_id, PA)
        )
        assert year_meta["total_count"] == 1, (
            "the same row is the whole programme year's ledger, got "
            f"{year_meta['total_count']}"
        )
        assert year_rows[0]["id"] == row["id"], (
            f"and it is the very same row, got {year_rows[0]!r}"
        )


class TestDisbursementGating:
    """Money moves only in an ACTIVE year and only one quarter at a time."""

    def test_run_against_a_window_open_year_is_refused(self, api):
        """PRD §3.5: "The year must be `ACTIVE`, or the run is refused with
        `ERR_PROGRAM_YEAR_NOT_ACTIVE`, and the supplied `quarter` must be exactly one more
        than the year's `current_quarter`, or the run is refused with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/errors/disbursement_run_before_the_year_is_active_returns_conflict
        """
        year = create_program_year()
        open_window(year["id"])

        response = api.run_disbursement(year["id"], 1, PA)
        validate_error(response, ApiErrorId.PROGRAM_YEAR_NOT_ACTIVE.value, 409)

        after = read_program_year(year["id"])
        assert after["status"] == "WINDOW_OPEN", (
            f"the year is untouched by the refused run, got {after['status']!r}"
        )
        assert after["current_quarter"] == 0, (
            "the checkpoint is not consumed by a refused run, got "
            f"{after['current_quarter']}"
        )
        _, meta = validate_paginated(
            api.list_program_year_disbursements(year["id"], PA)
        )
        assert meta["total_count"] == 0, (
            f"no disbursement row exists, got {meta['total_count']}"
        )

    def test_checkpoint_refuses_a_replay_and_a_skip_but_accepts_the_next_quarter(
        self, api
    ):
        """PRD §3.5: "Quarters therefore cannot be skipped, repeated, or run out of
        order."

        PRD §3.5: "the supplied `quarter` must be exactly one more than the year's
        `current_quarter`, or the run is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/cross_cutting_complexity_layers/disbursement_checkpoint_advances_and_refuses_replay_or_skip
        """
        env = setup_accepted_award()
        assert read_program_year(env.program_year_id)["current_quarter"] == 0, (
            "the checkpoint starts at 0"
        )

        first = run_disbursement(env.program_year_id, 1)
        assert first["total_net_credited_cents"] == Q1_NET_CENTS, (
            f"quarter 1 credits 229088, got {first['total_net_credited_cents']}"
        )
        assert read_program_year(env.program_year_id)["current_quarter"] == 1, (
            "the checkpoint advanced to 1"
        )

        replay = api.run_disbursement(env.program_year_id, 1, PA)
        validate_error(replay, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        skip = api.run_disbursement(env.program_year_id, 3, PA)
        validate_error(skip, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        mid = read_account(env.account_id)
        assert mid["disbursement_count"] == 1, (
            "neither refused run credited anything, got "
            f"{mid['disbursement_count']} disbursements"
        )
        assert mid["balance_cents"] == Q1_NET_CENTS, (
            f"and the balance still shows the single credit, got {mid['balance_cents']}"
        )

        second = run_disbursement(env.program_year_id, 2)
        assert second["total_net_credited_cents"] == Q2_NET_CENTS, (
            f"quarter 2 credits 229085, got {second['total_net_credited_cents']}"
        )

        year = read_program_year(env.program_year_id)
        assert year["current_quarter"] == 2, (
            f"the checkpoint stands at 2, got {year['current_quarter']}"
        )
        assert year["status"] == "ACTIVE", (
            f"the year stayed ACTIVE throughout, got {year['status']!r}"
        )
        account = read_account(env.account_id)
        assert account["disbursement_count"] == 2, (
            f"exactly two credits landed, got {account['disbursement_count']}"
        )
        assert account["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
            "the quarterly ledger was neither double-credited nor gapped, got "
            f"{account['balance_cents']}"
        )

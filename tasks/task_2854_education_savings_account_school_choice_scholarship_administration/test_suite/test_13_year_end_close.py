"""Year-end close: the rollover cap sits on a half-cent, and the comparison is strict."""

from test_helpers import (
    AWARD_BAND_B_IEP,
    BALANCE_AFTER_TWO_QUARTERS,
    DEFAULT_ROLLOVER_CAP_PCT,
    LIFETIME_ADMIN_FEE_TWO_QUARTERS,
    LIFETIME_DISBURSED_TWO_QUARTERS,
    PA,
    assert_account,
    assert_ledger_identity,
    assert_version_advanced_by,
    read_account,
    read_application,
    read_program_year,
    setup_purchase_environment,
    setup_settled_purchase_request,
    validate_success,
)

# A quarter of the 932663 award is 233165.75 cents, so the cap is only 233166 when the
# reduction rounds half up; a truncating cap would land on 233165.
ROLLOVER_CAP_CENTS = 233166


def _account_spent_down_to(target_balance_cents):
    """Two funded quarters spent down through TUITION to an exact balance."""
    env = setup_purchase_environment(
        quarters=2, provider_flags=[], provider_codes=("TUITION",)
    )
    account = read_account(env.account_id)
    assert account["final_award_cents"] == AWARD_BAND_B_IEP, (
        f"four quarters remained at acceptance so the annual figure carries through "
        f"untouched, got {account['final_award_cents']}"
    )
    assert account["quarters_remaining_at_award"] == 4, (
        f"the award was stamped before any quarter had run, got "
        f"{account['quarters_remaining_at_award']}"
    )
    assert account["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
        f"the first two quarters credited 229088 and 229085 net, got "
        f"{account['balance_cents']}"
    )
    assert account["lifetime_disbursed_cents"] == LIFETIME_DISBURSED_TWO_QUARTERS, (
        f"grossing 233168 then 233165, got {account['lifetime_disbursed_cents']}"
    )
    assert account["lifetime_admin_fee_cents"] == LIFETIME_ADMIN_FEE_TWO_QUARTERS, (
        f"with a fee of 4080 withheld from each, got "
        f"{account['lifetime_admin_fee_cents']}"
    )

    spend_cents = BALANCE_AFTER_TWO_QUARTERS - target_balance_cents
    env = setup_settled_purchase_request(
        env,
        category_key="tuition",
        amount_cents=spend_cents,
        claimed_amount_cents=spend_cents,
    )
    spent_down = read_account(env.account_id)
    assert spent_down["balance_cents"] == target_balance_cents, (
        f"a tuition purchase of {spend_cents} invoiced in full leaves exactly "
        f"{target_balance_cents}, got {spent_down['balance_cents']}"
    )
    assert spent_down["encumbered_cents"] == 0, (
        f"settlement emptied the hold, got {spent_down['encumbered_cents']}"
    )
    assert spent_down["lifetime_spent_cents"] == spend_cents, (
        f"and recorded the invoiced portion as spend, got "
        f"{spent_down['lifetime_spent_cents']}"
    )
    env["account"] = spent_down
    return env


class TestRolloverCapBoundary:
    """The cap is a rounded half-cent and the forfeiture test is strictly greater."""

    def test_a_balance_exactly_at_the_cap_carries_whole_and_forfeits_nothing(self, api):
        """PRD §3.9: "The cap is the account's `final_award_cents` multiplied by the
        year's `rollover_cap_pct`, rounded half up to whole cents. When `balance_cents` is
        **strictly greater** than that cap, `rollover_carried_cents` is set to the cap and
        `forfeited_cents` is set to `balance_cents` less the cap; otherwise
        `rollover_carried_cents` is set to the whole `balance_cents` and `forfeited_cents`
        is set to 0. In either case `balance_cents` is then set to
        `rollover_carried_cents`."

        PRD §3.9: "against a `final_award_cents` of 932663 the cap is exactly 233166,
        because a quarter of that award is 233165.75 and rounds half up, so a balance of
        exactly 233166 forfeits nothing while a balance of 233167 forfeits exactly 1 cent
        — the smallest non-zero forfeiture the programme can produce."

        PRD §3.9: "Each such account's application moves `ACCEPTED → COMPLETED`, provided
        the year was `ACTIVE` at the start of the close."

        PRD §3.9: "The close reports `program_year_status`, a `closed_account_count`
        giving the number of active accounts it processed, the aggregate
        `total_rolled_cents` and `total_forfeited_cents`, and `resolved_misuse_case_ids`
        naming the cases it swept to `RESOLVED`."

        Design: Difficulty/boundary_precision_check/rollover_balance_exactly_equal_to_cap_forfeits_zero
        """
        env = _account_spent_down_to(ROLLOVER_CAP_CENTS)
        before = env.account
        year_before = read_program_year(env.program_year_id)
        assert year_before["status"] == "ACTIVE", (
            f"the year is still funding when the close is called, got "
            f"{year_before['status']!r}"
        )
        assert year_before["rollover_cap_pct"] == DEFAULT_ROLLOVER_CAP_PCT, (
            f"and carries the default quarter cap, got "
            f"{year_before['rollover_cap_pct']}"
        )
        assert before["balance_cents"] == ROLLOVER_CAP_CENTS, (
            f"the balance sits on the cap itself, not above it, got "
            f"{before['balance_cents']}"
        )

        summary = validate_success(api.close_year(env.program_year_id, PA), 200)
        assert summary["program_year_status"] == "CLOSED", (
            f"the close moves the year to CLOSED, got "
            f"{summary['program_year_status']!r}"
        )
        assert summary["closed_account_count"] == 1, (
            f"one active account was processed, got {summary['closed_account_count']}"
        )
        assert summary["total_rolled_cents"] == ROLLOVER_CAP_CENTS, (
            f"whose whole balance of {ROLLOVER_CAP_CENTS} was carried, got "
            f"{summary['total_rolled_cents']}"
        )
        assert summary["total_forfeited_cents"] == 0, (
            "a balance equal to the cap is not strictly greater than it, so nothing is "
            f"forfeited, got {summary['total_forfeited_cents']}"
        )
        assert summary["resolved_misuse_case_ids"] == [], (
            f"and no misuse case existed to sweep, got "
            f"{summary['resolved_misuse_case_ids']!r}"
        )

        after = read_account(env.account_id)
        assert_account(after)
        assert after["rollover_carried_cents"] == ROLLOVER_CAP_CENTS, (
            f"the account carried the whole balance rather than the cap by coincidence "
            f"of them being equal, got {after['rollover_carried_cents']}"
        )
        assert after["forfeited_cents"] == 0, (
            "and a truncated cap of 233165 or a non-strict comparison would have taken "
            f"a cent, got {after['forfeited_cents']}"
        )
        assert after["balance_cents"] == ROLLOVER_CAP_CENTS, (
            f"the balance is then set to the carried amount, got "
            f"{after['balance_cents']}"
        )
        assert after["encumbered_cents"] == 0, (
            f"and the close touches no encumbrance, got {after['encumbered_cents']}"
        )
        assert_version_advanced_by(before["version"], after["version"], 1, "account")
        assert_ledger_identity(after)

        application = read_application(env.application_id)
        assert application["status"] == "COMPLETED", (
            f"the funded application is finished, got {application['status']!r}"
        )
        year_after = read_program_year(env.program_year_id)
        assert year_after["status"] == "CLOSED", (
            f"as is the year itself, got {year_after['status']!r}"
        )
        assert_version_advanced_by(
            year_before["version"], year_after["version"], 1, "program_year"
        )

    def test_a_balance_one_cent_above_the_cap_forfeits_exactly_one_cent(self, api):
        """PRD §2.6: "Round half up is used for the income-scaled base component of an
        award, for each individual category add-on component, for the proration of an
        award across the quarters that remain, for the administration fee withheld from a
        disbursement, for the rollover cap at year-end close, for the penalty component of
        a clawback, and for the decayed screening term of a provider's surveillance score."

        PRD §3.9: "When `balance_cents` is **strictly greater** than that cap,
        `rollover_carried_cents` is set to the cap and `forfeited_cents` is set to
        `balance_cents` less the cap"

        PRD §3.9: "so a balance of exactly 233166 forfeits nothing while a balance of
        233167 forfeits exactly 1 cent — the smallest non-zero forfeiture the programme can
        produce."

        PRD §2.6: "settling it removes `amount_cents` from `encumbered_cents`, records the
        invoiced portion as spend and returns only the unspent difference to
        `balance_cents`."

        Design: Difficulty/boundary_precision_check/rollover_balance_exactly_equal_to_cap_forfeits_zero
        """
        env = _account_spent_down_to(ROLLOVER_CAP_CENTS + 1)
        before = env.account
        assert before["balance_cents"] == ROLLOVER_CAP_CENTS + 1, (
            f"one cent less was spent, so the balance clears the cap by exactly a cent, "
            f"got {before['balance_cents']}"
        )

        summary = validate_success(api.close_year(env.program_year_id, PA), 200)
        assert summary["closed_account_count"] == 1, (
            f"the one active account is processed, got {summary['closed_account_count']}"
        )
        assert summary["total_rolled_cents"] == ROLLOVER_CAP_CENTS, (
            f"carrying the cap rather than the balance, got "
            f"{summary['total_rolled_cents']}"
        )
        assert summary["total_forfeited_cents"] == 1, (
            "and forfeiting the smallest non-zero amount the programme can produce, got "
            f"{summary['total_forfeited_cents']}"
        )

        after = read_account(env.account_id)
        assert after["rollover_carried_cents"] == ROLLOVER_CAP_CENTS, (
            f"the carried amount is capped at 233166, got "
            f"{after['rollover_carried_cents']}"
        )
        assert after["forfeited_cents"] == 1, (
            f"the excess cent is forfeited, got {after['forfeited_cents']}"
        )
        assert after["balance_cents"] == ROLLOVER_CAP_CENTS, (
            f"and the balance is reduced to the carried amount, got "
            f"{after['balance_cents']}"
        )
        assert (
            after["rollover_carried_cents"] + after["forfeited_cents"]
            == before["balance_cents"]
        ), (
            "carried plus forfeited accounts for every cent that was unspent: "
            f"{after['rollover_carried_cents']} + {after['forfeited_cents']} != "
            f"{before['balance_cents']}"
        )
        assert (
            after["lifetime_spent_cents"]
            == BALANCE_AFTER_TWO_QUARTERS - ROLLOVER_CAP_CENTS - 1
        ), (
            f"the settled spend is untouched by the close, got "
            f"{after['lifetime_spent_cents']}"
        )
        assert_version_advanced_by(before["version"], after["version"], 1, "account")
        assert_ledger_identity(after)

        assert read_application(env.application_id)["status"] == "COMPLETED", (
            "the funded application is finished"
        )
        assert read_program_year(env.program_year_id)["status"] == "CLOSED", (
            "and the year is closed"
        )

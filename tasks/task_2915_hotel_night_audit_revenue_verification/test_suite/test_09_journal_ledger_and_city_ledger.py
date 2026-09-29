"""The append-only journal, ledger accounts and the city-ledger sweep.

Covers PRD section 2.8 (the append-only journal and its charge classes), PRD
section 2.6 (money, signs and rounding) and the city-ledger sweep step of PRD
section 3.8.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_row_count,
    single,
)
from test_helpers.test_users import AUDITOR, CONTROLLER, FRONT_DESK


def _city_ledger_scenario(api):
    """Three departed DIRECT_BILL folios owing 210.00, 77.77 and 101.67."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    account = fx.create_ledger_account(
        api,
        prop["id"],
        "CITY_LEDGER",
        account_code="CL-001",
        gl_account_code="1230",
        opening_balance_amount=0.00,
        credit_limit_amount=100000.00,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folios = []
    for index, (code, name, room, amount) in enumerate(
        [
            ("CF-4001", "Fay Quon", "401", 210.00),
            ("CF-4002", "Gus Roy", "402", 77.77),
            ("CF-4003", "Hana Sim", "403", 101.67),
        ]
    ):
        folio = fx.create_folio(
            api,
            prop["id"],
            bd["id"],
            confirmation_code=code,
            guest_name=name,
            room_number=room,
            contracted_rate_amount=200.00,
            rate_plan_code="CORP",
            market_segment="CORPORATE",
            settlement_method="DIRECT_BILL",
        )
        fx.check_in(api, folio["id"])
        folios.append((folio, amount))
    for folio, amount in folios:
        fx.post_journal_line(
            api,
            bd["id"],
            "MISC_CHARGE",
            amount,
            folio_id=folio["id"],
            memo="Incidentals billed to the company account",
        )
    for folio, _amount in folios:
        fx.check_out(api, folio["id"], bd["id"])
    fx.post_room_and_tax(api, bd["id"])
    return prop, bd, account, [folio for folio, _ in folios]


def test_city_ledger_fee_is_rounded_per_folio_before_it_is_summed(api):
    """The 1.5% fee is rounded on each folio and only then added up.

    PRD section 3.8 applies the city-ledger fee percentage once per swept folio and
    rounds it there, so the three balances 210.00, 77.77 and 101.67 contribute 3.15,
    1.17 and 1.53 for a total of 5.85. Rounding a single 1.5% of the summed 389.44
    would produce 5.84.

    Design: Difficulty/combinatorial_formula/city_ledger_fee_rounded_per_folio_then_summed
    """
    _prop, bd, _account, folios = _city_ledger_scenario(api)

    swept = validate_success(api.city_ledger_sweep(bd["id"], AUDITOR))
    assert_int(swept["city_ledger_swept_folio_count"], 3, "city_ledger_swept_folio_count")
    assert_money_fields(
        swept,
        {
            "city_ledger_transferred_balance_total_amount": 389.44,
            "city_ledger_fee_total_amount": 5.85,
        },
    )

    for folio, expected_fee in zip(folios, [3.15, 1.17, 1.53]):
        rows = validate_success(
            api.list_journal_postings(
                AUDITOR, folio_id=folio["id"], charge_type="CITY_LEDGER_FEE"
            )
        )
        assert_row_count(rows, 1, "CITY_LEDGER_FEE rows")
        assert_money(single(rows)["amount"], expected_fee, "per-folio city ledger fee")


def test_the_sweep_transfers_each_folio_and_leaves_the_control_total_at_zero(api):
    """Swept folios go flat and terminal, the ledger account absorbs balance plus fee.

    PRD section 3.8 transfers each departed direct-bill debtor to the city ledger
    with a balanced pair of LEDGER_TRANSFER lines, so the day's ledger control total
    stays 0.00, each folio ends at balance 0.00 in the terminal settlement state
    TRANSFERRED_TO_CITY_LEDGER, and the account carries the transferred balances plus
    the fees. A second sweep finds no candidates left.

    Design: Difficulty/combinatorial_formula/city_ledger_fee_rounded_per_folio_then_summed
    """
    _prop, bd, account, folios = _city_ledger_scenario(api)

    swept = validate_success(api.city_ledger_sweep(bd["id"], AUDITOR))
    assert_money(swept["ledger_control_amount"], 0.00, "ledger_control_amount")

    for folio in folios:
        row = validate_success(api.get_folio(folio["id"], FRONT_DESK))
        assert_fields(row, {"settlement_status": "TRANSFERRED_TO_CITY_LEDGER"})
        assert_money(row["balance_amount"], 0.00, "balance_amount")

    account_row = validate_success(api.get_ledger_account(account["id"], CONTROLLER))
    assert_money(account_row["current_balance_amount"], 395.29, "current_balance_amount")

    again = validate_success(api.city_ledger_sweep(bd["id"], AUDITOR))
    assert_int(again["city_ledger_swept_folio_count"], 0, "city_ledger_swept_folio_count")
    assert_money_fields(
        again,
        {
            "city_ledger_transferred_balance_total_amount": 0.00,
            "city_ledger_fee_total_amount": 0.00,
        },
    )


def _one_sided_ledger_transfer_awaiting_repair(api):
    """A day in SETTLEMENT_REVIEW carrying a single hand-posted one-sided transfer."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    account = fx.create_ledger_account(
        api,
        prop["id"],
        "CITY_LEDGER",
        CONTROLLER,
        account_code="CL-900",
        gl_account_code="1230",
        opening_balance_amount=0.00,
        credit_limit_amount=100000.00,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    line = fx.post_journal_line(
        api,
        bd["id"],
        "LEDGER_TRANSFER",
        -125.00,
        AUDITOR,
        ledger_account_id=account["id"],
        memo="One-sided transfer awaiting its pair",
    )
    fx.drive_to_settlement_review(api, bd["id"])
    return prop, account, bd, line


def test_a_one_sided_transfer_pushes_the_control_total_off_zero_and_blocks_the_balance(api):
    """The lone transfer is the only thing that can unbalance the control figure.

    PRD section 3.8 defines `ledger_control_amount` as the rounded sum of every
    LEDGER_TRANSFER and DEPOSIT_APPLIED line of the day across both sides, so a single
    hand-posted −125.00 leaves it at −125.00, and balancing is refused with
    ERR_LEDGERS_OUT_OF_BALANCE (HTTP 409) while the day stays in SETTLEMENT_REVIEW.

    Design: Difficulty/compensating_invariant/one_sided_ledger_transfer_reversal_returns_control_total_to_zero
    """
    _prop, account, bd, _line = _one_sided_ledger_transfer_awaiting_repair(api)

    day = fx.read_business_date(api, bd["id"])
    assert_money(day["ledger_control_amount"], -125.00, "ledger_control_amount")
    assert_money(
        fx.read_ledger_account(api, account["id"])["current_balance_amount"],
        -125.00,
        "current_balance_amount",
    )

    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_LEDGERS_OUT_OF_BALANCE
    )
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "SETTLEMENT_REVIEW"})


def test_reversing_the_transfer_returns_the_control_total_to_exactly_zero(api):
    """The repair is an appended mirror line, and it may not be posted by the poster twice.

    PRD section 2.8 has reversal append a line negating the original and copying its
    `folio_id`, `ledger_account_id`, `business_date_id` and `charge_type`, answering 201
    because it mints a row; the original is never mutated. PRD section 3.8 then reads
    `ledger_control_amount` back at exactly 0.00, so the day balances. A second reversal is
    refused with ERR_POSTING_ALREADY_REVERSED (HTTP 409) and the poster reversing their own
    line is refused with ERR_SELF_REVERSAL_FORBIDDEN (HTTP 403).

    Design: Difficulty/compensating_invariant/one_sided_ledger_transfer_reversal_returns_control_total_to_zero
    """
    _prop, account, bd, line = _one_sided_ledger_transfer_awaiting_repair(api)

    validate_error(
        api.reverse_journal_posting(line["id"], AUDITOR), E.ERR_SELF_REVERSAL_FORBIDDEN
    )

    mirror = validate_success(
        api.reverse_journal_posting(line["id"], CONTROLLER), 201
    )
    assert_money(mirror["amount"], 125.00, "the reversing amount")
    assert_fields(
        mirror,
        {
            "charge_type": "LEDGER_TRANSFER",
            "ledger_account_id": account["id"],
            "folio_id": None,
            "business_date_id": bd["id"],
            "reverses_posting_id": line["id"],
        },
    )

    untouched = validate_success(api.get_journal_posting(line["id"], AUDITOR))
    assert_money(untouched["amount"], -125.00, "the original amount")
    assert_fields(untouched, {"reverses_posting_id": None})

    assert_money(
        fx.read_business_date(api, bd["id"])["ledger_control_amount"],
        0.00,
        "ledger_control_amount",
    )
    assert_money(
        fx.read_ledger_account(api, account["id"])["current_balance_amount"],
        0.00,
        "current_balance_amount",
    )

    validate_error(
        api.reverse_journal_posting(line["id"], CONTROLLER), E.ERR_POSTING_ALREADY_REVERSED
    )
    balanced = validate_success(api.balance_business_date(bd["id"], AUDITOR))
    assert_fields(balanced, {"status": "BALANCED"})

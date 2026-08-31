"""The payment waterfall, delinquency declaration and account billing ageing."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_installment_schedule,
    create_confirmed_order,
    create_order,
    create_plan_order_payload,
    pay_order,
    read_account,
    read_order,
    read_seat,
    run_ops,
    set_clock,
    setup_four_seat_zone_c_world,
    setup_selling_world,
    setup_written_off_account_world,
    setup_zone_d_world,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
)


def test_partial_payment_moves_only_the_payment_dimension():
    """PRD 3.7: "Application is a waterfall. The payment is poured into the instalments ordered by `due_date_utc` ascending, with ties broken by `index` ascending, filling each instalment's remaining amount before spilling into the next. The order's `amount_paid_cents` is then the sum of `paid_cents` across all instalments. `payment_status` becomes `PAID_IN_FULL` when `amount_paid_cents` has reached or passed `final_total_cents` — reaching it exactly is sufficient — and otherwise becomes `PARTIALLY_PAID` whenever `amount_paid_cents` is greater than 0."

    Design: Difficulty/non_linear_state_machine/plan_order_order_status_and_payment_status_advance_independently
    """
    world = setup_four_seat_zone_c_world()
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], world["seat_ids"],
        world["rep_headers"], installment_count=3,
    )
    assert order["final_total_cents"] == 38430

    paid = pay_order(order["id"], world["rep_headers"], 5000)

    assert paid["payment_status"] == "PARTIALLY_PAID"
    assert paid["order_status"] == "CONFIRMED", "the fulfilment dimension does not move"
    assert paid["installments"][0]["amount_cents"] == 12810
    assert paid["installments"][0]["paid_cents"] == 5000
    assert_installment_schedule(paid)


def test_delinquency_moves_the_payment_dimension_and_the_account_only():
    """PRD 3.7: "During its payment phase, a confirmed order whose `payment_status` is `SCHEDULED` or `PARTIALLY_PAID` moves to `DELINQUENT` when the current instant has reached or passed the due date of its earliest unpaid instalment plus a ten-day grace period. That move drags the account with it: an account whose `billing_status` is `CURRENT` becomes `PAST_DUE` with `past_due_since_utc` stamped at the current instant, the account's `churn_risk_rolling` is recomputed, and both the order's and the account's `version` increment by 1."

    Design: Difficulty/non_linear_state_machine/plan_order_order_status_and_payment_status_advance_independently
    """
    world = setup_four_seat_zone_c_world()
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], world["seat_ids"],
        world["rep_headers"], installment_count=3,
    )
    pay_order(order["id"], world["rep_headers"], 5000)

    set_clock("2026-08-12T00:00:00Z")
    run_ops(world["season_id"])

    delinquent = read_order(order["id"])
    assert delinquent["payment_status"] == "DELINQUENT"
    assert delinquent["order_status"] == "CONFIRMED", (
        "the fulfilment dimension is untouched by the payment dimension"
    )
    account = read_account(world["account_id"])
    assert account["billing_status"] == "PAST_DUE"
    assert account["past_due_since_utc"] == "2026-08-12T00:00:00.000Z"


def test_payment_reaching_the_exact_balance_sets_paid_in_full():
    """PRD 3.7: "`payment_status` becomes `PAID_IN_FULL` when `amount_paid_cents` has reached or passed `final_total_cents` — reaching it exactly is sufficient — and otherwise becomes `PARTIALLY_PAID` whenever `amount_paid_cents` is greater than 0."

    Design: Corner/calculations/calc_payment_reaching_the_exact_balance_sets_paid_in_full
    """
    world = setup_zone_d_world()
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], installment_count=1,
    )
    assert order["final_total_cents"] == 5942

    almost = pay_order(order["id"], world["account_headers"], 5941)
    assert almost["payment_status"] == "PARTIALLY_PAID"
    assert almost["amount_paid_cents"] == 5941

    settled = pay_order(order["id"], world["account_headers"], 1)

    assert settled["payment_status"] == "PAID_IN_FULL"
    assert settled["amount_paid_cents"] == 5942
    assert settled["installments"][0]["paid_cents"] == 5942
    assert read_account(world["account_id"])["billing_status"] == "CURRENT"


def test_payment_above_the_outstanding_balance_is_rejected():
    """PRD 3.7: "It is accepted only while `payment_status` is `SCHEDULED`, `PARTIALLY_PAID` or `DELINQUENT`, and the amount may not exceed the outstanding balance — that is, `final_total_cents` minus `amount_paid_cents`. An overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/val_payment_above_the_outstanding_balance_rejected
    """
    world = setup_zone_d_world()
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], installment_count=1,
    )

    response = api_client.pay_plan_order(
        order["id"], {"amount_cents": 5943}, world["account_headers"]
    )

    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, 422)
    unchanged = read_order(order["id"])
    assert unchanged["amount_paid_cents"] == 0
    assert unchanged["payment_status"] == "SCHEDULED"


def test_account_holder_cannot_pay_another_accounts_order():
    """PRD 2.1: "Concretely, an `AccountHolder` may act only on an order whose `account_id` equals `X-User-ID`, and may request a transfer only against an order it owns; a mismatch is `ERR_NOT_ORDER_OWNER` (HTTP 403)."
    PRD 2.9: "**Account-holder ownership.** An `AccountHolder` caller's `X-User-ID` equals the owning account id of the target resource — the order's `account_id`, or the `account_id` of the order behind a transfer request — otherwise `ERR_NOT_ORDER_OWNER` (403). This guards three operations: order confirmation, payment application and transfer requests."

    Design: Corner/validations/val_account_holder_paying_another_accounts_order_rejected
    """
    from test_helpers import create_account, make_account_holder_headers

    world = setup_zone_d_world(account={"account_name": "Acct A"})
    other_account = create_account(account_name="Acct B")
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], installment_count=1,
    )

    response = api_client.pay_plan_order(
        order["id"],
        {"amount_cents": 1000},
        make_account_holder_headers(other_account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_ORDER_OWNER.value, 403)
    unchanged = read_order(order["id"])
    assert unchanged["amount_paid_cents"] == 0
    assert unchanged["payment_status"] == "SCHEDULED"


def test_write_off_cancels_open_orders_and_spares_the_confirmed_one():
    """PRD 3.7: "During its billing-ageing phase, the ops checkpoint moves an account from `PAST_DUE` to `LAPSED` once 45 days have elapsed since `past_due_since_utc`, and from `LAPSED` to `WRITTEN_OFF` once 90 days have elapsed since that same `past_due_since_utc`."
    PRD 3.7: "The write-off carries a four-part cascade: every `ACTIVE` hold of that account becomes `RELEASED` with `released_reason` recorded as `ACCOUNT_WRITTEN_OFF`; every order of that account whose `order_status` is `DRAFT`, `PENDING_APPROVAL` or `APPROVED` becomes `CANCELLED` with `cancelled_reason` recorded as `ACCOUNT_WRITTEN_OFF`; every hospitality package of that account whose `package_status` is `HELD` becomes `RELEASED` and its game's `hospitality_booked_headcount` decreases by that package's `headcount`; and the seat census is recomputed."
    PRD 2.11: "The response is a summary object rather than an entity: it reports `ops_run_at_utc`, the resulting `season_status`, and eight counters — `expired_hold_count`, `played_game_count`, `released_package_count`, `settled_package_count`, `delinquent_order_count`, `at_risk_account_count`, `churned_account_count` and `written_off_account_count` — each counting the rows that phase actually changed during this run."

    Design: Corner/state_machines/sm_written_off_account_cascade_cancels_its_open_orders
    """
    world = setup_written_off_account_world()

    assert world["account_past_due"]["billing_status"] == "PAST_DUE"
    assert world["account_past_due"]["past_due_since_utc"] == "2026-08-12T00:00:00.000Z"
    assert world["account"]["billing_status"] == "WRITTEN_OFF"
    assert world["draft_order"]["order_status"] == "CANCELLED"
    assert world["draft_order"]["cancelled_reason"] == "ACCOUNT_WRITTEN_OFF"
    assert world["confirmed_order"]["order_status"] == "CONFIRMED"
    assert world["confirmed_order"]["payment_status"] == "DELINQUENT"
    assert read_seat(world["seat_ids"][0])["seat_status"] == "ASSIGNED"
    assert world["ops_summary"]["written_off_account_count"] == 1


def test_order_creation_for_a_written_off_account_is_rejected():
    """PRD 2.9: "**Account status gate,** HTTP 409. Every account-touching write requires the account's `billing_status` not to be `WRITTEN_OFF`, and order confirmation additionally requires it not to be `LAPSED`; violations are `ERR_ACCOUNT_WRITTEN_OFF`."
    PRD 3.7: "The write-off carries a four-part cascade: every `ACTIVE` hold of that account becomes `RELEASED` with `released_reason` recorded as `ACCOUNT_WRITTEN_OFF`; every order of that account whose `order_status` is `DRAFT`, `PENDING_APPROVAL` or `APPROVED` becomes `CANCELLED` with `cancelled_reason` recorded as `ACCOUNT_WRITTEN_OFF`; every hospitality package of that account whose `package_status` is `HELD` becomes `RELEASED` and its game's `hospitality_booked_headcount` decreases by that package's `headcount`; and the seat census is recomputed."

    Design: Corner/errors/err_order_creation_for_a_written_off_account_rejected
    """
    world = setup_written_off_account_world()
    fresh_seat = world["seat_ids"][2]

    response = api_client.create_plan_order(
        create_plan_order_payload(world["account_id"], world["plan_id"], [fresh_seat]),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_WRITTEN_OFF.value, 409)
    assert read_account(world["account_id"])["billing_status"] == "WRITTEN_OFF"
    assert read_seat(fresh_seat)["seat_status"] == "AVAILABLE"

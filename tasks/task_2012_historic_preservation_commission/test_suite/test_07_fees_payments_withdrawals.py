"""Fee payments, overpayment guard, and the stage-based withdrawal refund
schedule with its hearing cascade (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_owner,
    create_property,
    get_application,
    get_meeting,
    make_applicant_headers,
    pay_fee,
    setup_hearing_open,
    setup_staff_track_accepted,
    submit_application,
    validate_error,
    validate_success,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]


def test_overpayment_rejected(api):
    """PRD §3.5: "A payment that exceeds the outstanding `fee_balance_cents` is
    rejected with `ERR_OVERPAYMENT` — partial payment of the exact remaining
    balance is the intended final installment."

    Design: Corner/endpoints/overpayment_rejected
    """
    ctx = setup_staff_track_accepted()  # assessed fee 10400
    app_id = ctx["application"]["id"]
    owner_id = ctx["owner"]["id"]

    pay_fee(app_id, owner_id, 5000)
    response = api.record_fee_payment(
        app_id, {"amount_cents": 5401}, make_applicant_headers(owner_id)
    )
    validate_error(response, ApiErrorId.ERR_OVERPAYMENT)

    application = get_application(app_id)
    assert application["paid_fee_cents"] == 5000
    assert application["fee_balance_cents"] == 5400


def test_withdrawal_at_accepted_refunds_half(api):
    """PRD §3.5: "Withdrawal moves the application to `WITHDRAWN` and settles
    the fee account by a stage-based refund schedule: withdrawal from
    `SUBMITTED`, `UNDER_STAFF_REVIEW`, or `INCOMPLETE` refunds one hundred
    percent of `paid_fee_cents`; withdrawal from `ACCEPTED`,
    `HEARING_SCHEDULED`, or `HEARING_DEFERRED` refunds fifty percent;
    withdrawal from `HEARING_OPEN` refunds nothing."
    PRD §3.5: "The `refunded_fee_cents` is the paid amount multiplied by the
    stage's percentage, rounded half-up to a whole cent, and after the refund
    the `fee_balance_cents` is forced to zero — any unpaid assessed balance is
    forgiven, and the retained revenue is exactly `paid_fee_cents` minus
    `refunded_fee_cents`."

    Design: Corner/calculations/refund_fifty_percent_at_accepted_stage
    """
    ctx = setup_staff_track_accepted()  # assessed fee 10400
    app_id = ctx["application"]["id"]
    owner_id = ctx["owner"]["id"]
    pay_fee(app_id, owner_id, 10400)

    withdrawn = validate_success(
        api.withdraw_application(app_id, make_applicant_headers(owner_id))
    )
    assert withdrawn["status"] == "WITHDRAWN"
    # round_half_up(10400 * 0.50) = 5200.
    assert withdrawn["refunded_fee_cents"] == 5200
    assert withdrawn["fee_balance_cents"] == 0


def test_withdrawal_at_hearing_open_refunds_nothing(api):
    """PRD §3.5: "withdrawal from `HEARING_OPEN` refunds nothing."
    PRD §3.5: "Withdrawing from `HEARING_SCHEDULED` or `HEARING_OPEN` moves the
    application's `SCHEDULED` or `OPENED` hearing to `WITHDRAWN` and decrements
    the meeting's `scheduled_hearing_count` by one, freeing the agenda slot."

    Design: Corner/state_machines/withdraw_at_hearing_open_zero_refund
    """
    ctx = setup_hearing_open(verified_cost_cents=1100000)  # assessed 55500
    app_id = ctx["application"]["id"]
    owner_id = ctx["owner"]["id"]
    pay_fee(app_id, owner_id, 55500)
    assert get_meeting(ctx["meeting"]["id"])["scheduled_hearing_count"] == 1

    withdrawn = validate_success(
        api.withdraw_application(app_id, make_applicant_headers(owner_id))
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["refunded_fee_cents"] == 0
    assert withdrawn["fee_balance_cents"] == 0

    hearing = validate_success(api.get_hearing(ctx["hearing"]["id"], STAFF))
    assert hearing["status"] == "WITHDRAWN"
    assert get_meeting(ctx["meeting"]["id"])["scheduled_hearing_count"] == 0


def test_applicant_cannot_withdraw_others_application(api):
    """PRD §3.5: "An applicant may withdraw an application at any point before
    it reaches a decision terminal state, provided the caller's `X-User-ID`
    equals the application's `owner_id` (otherwise `ERR_FORBIDDEN_ROLE`)."

    Design: Corner/rbac/applicant_cannot_withdraw_others_application
    """
    owner1 = create_owner()
    owner2 = create_owner()
    prop = create_property(owner1["id"])
    submitted = submit_application(
        prop["id"], owner1["id"], work_items=[work_item("SITE_WORK", "wall", 200000)]
    )

    response = api.withdraw_application(
        submitted["id"], make_applicant_headers(owner2["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_application(submitted["id"])["status"] == "SUBMITTED"

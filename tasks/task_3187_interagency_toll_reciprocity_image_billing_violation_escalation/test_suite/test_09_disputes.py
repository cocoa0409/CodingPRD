"""Disputes: cycle, repricing cascade, auto-reject, window (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_days,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    file_classification_dispute,
    get_account,
    get_success_data,
    make_account_holder_headers,
    setup_agency_pair,
    setup_account_with_plan,
    setup_classification_dispute_under_review,
    validate_error,
)

VO = TEST_USERS["violations_officer_headers"]
AO = TEST_USERS["agency_ops_headers"]


def _get_txn(txn_id):
    return get_success_data(api_client.get_toll_transaction(txn_id, AO))


def _get_dispute(dispute_id):
    return get_success_data(api_client.get_dispute(dispute_id, VO))


def test_dispute_cycle_review_reject_refire():
    """PRD §3.8: "The holder may withdraw a dispute from either `FILED` or
    `UNDER_REVIEW`, moving it to `WITHDRAWN`; for a classification dispute the
    transaction likewise returns from `DISPUTED` to `POSTED` unchanged."
    PRD §3.8: "Filing a classification dispute has an immediate bookkeeping
    effect: the named toll transaction moves from `POSTED` to `DISPUTED`, and
    while `DISPUTED` it is excluded from settlement sweeps."

    Design: Difficulty/non_linear_state_machine/dispute_cycle_review_reject_refire
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P3", vehicle_class="CLASS_5",
                         base_rate_cents=475, axle_multiplier=2.5)
    create_rate_schedule(away["id"], plaza_code="P3", vehicle_class="CLASS_2",
                         base_rate_cents=300, axle_multiplier=1.0)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(
        home["id"], plan["id"], holder_name="Gus Class", holder_email="gus@example.com",
        opening_balance_cents=100000,
    )
    create_transponder(account["id"], tag_number="TAG-V", vehicle_class="CLASS_5",
                       plate_number="CLS500")
    txn = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-V", "away_agency_id": away["id"], "plaza_code": "P3",
             "trip_timestamp": "2026-09-05T09:00:00Z", "is_peak": False,
             "idempotency_key": "v1"}, AO,
        )
    )
    holder = make_account_holder_headers(account["id"])

    d1 = file_classification_dispute(account["id"], txn["id"], "CLASS_2")
    assert _get_txn(txn["id"])["status"] == "DISPUTED"
    get_success_data(api_client.withdraw_dispute(d1["id"], holder))
    assert _get_dispute(d1["id"])["status"] == "WITHDRAWN"
    assert _get_txn(txn["id"])["status"] == "POSTED"

    # Cycle: a NEW dispute on the same transaction POSTED -> DISPUTED again.
    d2 = file_classification_dispute(account["id"], txn["id"], "CLASS_2")
    assert _get_dispute(d2["id"])["status"] == "FILED"
    txn_now = _get_txn(txn["id"])
    assert txn_now["status"] == "DISPUTED"
    assert txn_now["charged_amount_cents"] == 1188


def test_upheld_classification_dispute_repricing_cascade():
    """PRD §3.8: "Upholding a classification dispute re-prices the transaction
    at the `claimed_vehicle_class`: `billed_vehicle_class`,
    `gross_amount_cents`, `discount_amount_cents`, and `charged_amount_cents`
    are recomputed, the account's `balance_cents` is credited the difference
    between the old and new charged amounts, and the transaction returns to
    `POSTED` with the corrected class."

    Design: Difficulty/transitive_cascade/upheld_classification_dispute_repricing_cascade (depth 2)
    """
    ctx = setup_classification_dispute_under_review(
        tag_number="TAG-X", opening_balance=100000
    )
    account = ctx["account"]
    txn = ctx["txn"]
    dispute = ctx["dispute"]
    assert get_account(account["id"])["balance_cents"] == 98812

    get_success_data(api_client.uphold_dispute(dispute["id"], VO))

    assert _get_dispute(dispute["id"])["status"] == "UPHOLD"
    txn_now = _get_txn(txn["id"])
    assert txn_now["status"] == "POSTED"
    assert txn_now["billed_vehicle_class"] == "CLASS_2"
    assert txn_now["charged_amount_cents"] == 300
    assert get_account(account["id"])["balance_cents"] == 99700  # 98812 + 888


def test_dispute_auto_reject_after_thirty_days_unreviewed():
    """PRD §3.8: "The day-advancement sweep auto-rejects any dispute still in
    `FILED` once 30 days have passed since `filed_day` without a review having
    begun, moving it to `REJECTED`, and the classification bookkeeping unwinds
    exactly as for a manual rejection."
    PRD §3.8: "Rejecting a classification dispute moves the dispute to
    `REJECTED` and returns the transaction from `DISPUTED` to `POSTED`
    unchanged."

    Design: Corner/state_machines/dispute_auto_reject_after_thirty_days_unreviewed
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P3", vehicle_class="CLASS_5",
                         base_rate_cents=475, axle_multiplier=2.5,
                         effective_to="2027-01-01T00:00:00Z")
    create_rate_schedule(away["id"], plaza_code="P3", vehicle_class="CLASS_2",
                         base_rate_cents=300, axle_multiplier=1.0,
                         effective_to="2027-01-01T00:00:00Z")
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(
        home["id"], plan["id"], holder_name="Ann Auto", holder_email="ann@example.com",
        opening_balance_cents=50000,
    )
    create_transponder(account["id"], tag_number="TAG-D", vehicle_class="CLASS_5",
                       plate_number="AUT100")
    txn = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-D", "away_agency_id": away["id"], "plaza_code": "P3",
             "trip_timestamp": "2026-09-02T09:00:00Z", "is_peak": False,
             "idempotency_key": "d1"}, AO,
        )
    )
    dispute = file_classification_dispute(account["id"], txn["id"], "CLASS_2")

    advance_days(30)

    assert _get_dispute(dispute["id"])["status"] == "REJECTED"
    txn_now = _get_txn(txn["id"])
    assert txn_now["status"] == "POSTED"
    assert txn_now["billed_vehicle_class"] == "CLASS_5"
    assert txn_now["charged_amount_cents"] == 1188
    assert get_account(account["id"])["balance_cents"] == 48812


def test_dispute_filed_after_window_closed():
    """PRD §3.8: "Every filing is stamped with the current epoch day in
    `filed_day`, starts in `FILED`, and must arrive within 90 days of the trip:
    a filing whose current epoch day is more than 90 days past the trip is
    rejected with `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Corner/validations/dispute_filed_after_window_closed
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800,
                         effective_to="2027-01-01T00:00:00Z")
    create_rate_schedule(away["id"], vehicle_class="CLASS_5", base_rate_cents=900,
                         axle_multiplier=2.5, effective_to="2027-01-01T00:00:00Z")
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(
        home["id"], plan["id"], holder_name="Win Dow", holder_email="win@example.com",
        opening_balance_cents=50000,
    )
    create_transponder(account["id"], tag_number="TAG-W2", plate_number="WIN100")
    txn = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-W2", "away_agency_id": away["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-01T09:00:00Z", "is_peak": False,
             "idempotency_key": "w91"}, AO,
        )
    )
    advance_days(91)

    resp = api_client.create_dispute(
        {
            "account_id": account["id"],
            "dispute_type": "VEHICLE_CLASSIFICATION",
            "toll_transaction_id": txn["id"],
            "claimed_vehicle_class": "CLASS_5",
        },
        make_account_holder_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
    assert _get_txn(txn["id"])["status"] == "POSTED"

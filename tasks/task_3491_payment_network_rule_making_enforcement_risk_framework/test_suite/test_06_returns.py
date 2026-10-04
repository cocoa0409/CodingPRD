"""Returns: reason-class derivation, the banking-day window, the self-return
bar, and the return cascade — PRD §3.7.
"""

from test_helpers import (
    REASON_CLASS_BY_CODE,
    ApiErrorId,
    assert_return_record,
    create_and_settle_entry,
    create_payment_entry,
    create_return_payload,
    get_originator,
    get_payment_entry,
    make_participant_officer_headers,
    return_entry,
    run_settlement,
    set_clock,
    setup_origination_stack,
    validate_error,
    validate_paginated,
)


def test_return_cascades_entry_status_then_exposure_release(api, admin_headers):
    """PRD §3.7: "An accepted return creates an immutable **ReturnRecord** whose
    `payment_entry_id` identifies the returned entry, whose
    `returning_participant_id` is taken from the acting officer's `X-User-ID`,
    and whose `returned_at` is stamped from the logical clock; the entry moves
    to `RETURNED` (terminal), its amount leaves the returnable set so the
    originator's `contingent_exposure_cents` decreases by `amount_cents`, and
    both the entry's and the originator's `version` advance by one."

    Design: Difficulty/transitive_cascade/return_cascades_entry_status_then_exposure_release
    """
    stack = setup_origination_stack()
    originator = stack["originator"]
    receiver = stack["receiver"]

    entry = create_and_settle_entry(
        originator, stack["transaction_code"], stack["window"], amount_cents=40000000
    )
    mid = get_originator(originator["id"])
    assert mid["contingent_exposure_cents"] == 40000000

    record = return_entry(
        entry, receiver, "INVALID_ACCOUNT", at_iso="2026-09-02T10:00:00Z"
    )
    assert record["reason_class"] == "ADMINISTRATIVE"
    assert record["reason_class"] == REASON_CLASS_BY_CODE["INVALID_ACCOUNT"]

    entry_after = get_payment_entry(entry["id"])
    assert entry_after["status"] == "RETURNED"

    originator_after = get_originator(originator["id"])
    assert originator_after["contingent_exposure_cents"] == 0
    assert originator_after["committed_exposure_cents"] == 0


def test_return_record_reason_class_is_computed(api, admin_headers):
    """PRD §3.7: "The return's `reason_class` is derived, never supplied:
    `UNAUTHORIZED_DEBIT` and `AUTHORIZATION_REVOKED` map to `UNAUTHORIZED`,
    `INSUFFICIENT_FUNDS` and `INVALID_ACCOUNT` map to `ADMINISTRATIVE`, and
    `STOP_PAYMENT` maps to `OTHER`."
    PRD §3.7: "An accepted return creates an immutable **ReturnRecord** whose
    `payment_entry_id` identifies the returned entry, whose
    `returning_participant_id` is taken from the acting officer's `X-User-ID`,
    and whose `returned_at` is stamped from the logical clock"
    PRD §4: "Operations that create a new resource return `201 Created`"

    Design: Corner/entities/return_record_reason_class_is_computed
    """
    stack = setup_origination_stack()
    receiver = stack["receiver"]
    entry = create_and_settle_entry(
        stack["originator"], stack["transaction_code"], stack["window"], amount_cents=5000
    )

    record = return_entry(entry, receiver, "STOP_PAYMENT", at_iso="2026-09-02T10:00:00Z")
    assert_return_record(record)
    assert record["reason_class"] == "OTHER"
    assert record["returning_participant_id"] == receiver["id"]
    assert record["payment_entry_id"] == entry["id"]


def test_return_on_already_returned_entry_rejected(api, admin_headers):
    """PRD §3.7: "The guard chain runs in this order: the returning participant
    must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`); the entry must be in
    `SETTLED` status — a rule that also covers a second return attempt on an
    already-`RETURNED` entry (`ERR_ENTRY_NOT_SETTLED`); the returning
    participant must differ from the entry's originator side, so an `X-User-ID`
    equal to the entry's `originating_participant_id` is refused with
    `ERR_RETURN_PARTICIPANT_CONFLICT`; and the return must arrive inside the
    entry class's window — the count of banking days (Monday through Friday, no
    holiday calendar) from the entry's `settled_date` to the current logical
    date must not exceed the code's `return_timeframe_banking_days`, otherwise
    `ERR_RETURN_WINDOW_EXPIRED`."
    PRD §3.7: "The returns filed against a single entry (at most one) and the
    returns filed by a participant as the receiving side can both be listed
    with pagination."

    Design: Corner/state_machines/return_on_already_returned_entry_rejected
    """
    stack = setup_origination_stack()
    receiver = stack["receiver"]
    entry = create_and_settle_entry(
        stack["originator"], stack["transaction_code"], stack["window"], amount_cents=5000
    )
    return_entry(entry, receiver, "INSUFFICIENT_FUNDS", at_iso="2026-09-02T10:00:00Z")

    second = api.create_return(
        entry["id"],
        create_return_payload("UNAUTHORIZED_DEBIT"),
        make_participant_officer_headers(receiver["id"]),
    )
    validate_error(second, ApiErrorId.ERR_ENTRY_NOT_SETTLED)

    records, meta = validate_paginated(api.list_entry_returns(entry["id"], admin_headers))
    assert len(records) == 1 and meta["total_count"] == 1


def test_return_within_banking_day_window_ok_then_expired(api, admin_headers):
    """The settled_date is Friday 2026-09-04 and the class allows 2 banking
    days: Monday 2026-09-07 is day 1, Tuesday 2026-09-08 is day 2 (accepted),
    Wednesday 2026-09-09 is day 3 (expired).

    PRD §3.7: "The guard chain runs in this order: the returning participant
    must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`); the entry must be in
    `SETTLED` status — a rule that also covers a second return attempt on an
    already-`RETURNED` entry (`ERR_ENTRY_NOT_SETTLED`); the returning
    participant must differ from the entry's originator side, so an `X-User-ID`
    equal to the entry's `originating_participant_id` is refused with
    `ERR_RETURN_PARTICIPANT_CONFLICT`; and the return must arrive inside the
    entry class's window — the count of banking days (Monday through Friday, no
    holiday calendar) from the entry's `settled_date` to the current logical
    date must not exceed the code's `return_timeframe_banking_days`, otherwise
    `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_within_banking_day_window_ok_then_expired
    """
    stack = setup_origination_stack(
        clock_iso="2026-09-04T09:00:00Z",
        code_overrides={
            "code": "TEL",
            "authorization_requirement": "ORAL_RECORDED",
            "return_timeframe_banking_days": 2,
        },
    )
    originator = stack["originator"]
    receiver = stack["receiver"]
    code = stack["transaction_code"]
    window = stack["window"]

    entry1 = create_payment_entry(
        originator, code, amount_cents=5000, authorization_type="ORAL_RECORDED"
    )
    entry2 = create_payment_entry(
        originator, code, amount_cents=5000, authorization_type="ORAL_RECORDED"
    )
    run_settlement(window["id"], at_iso="2026-09-04T18:00:00Z")

    accepted = return_entry(
        entry1, receiver, "AUTHORIZATION_REVOKED", at_iso="2026-09-08T10:00:00Z"
    )
    assert accepted["reason_class"] == "UNAUTHORIZED"

    # The second return is attempted one banking day past the window.
    set_clock("2026-09-09T10:00:00Z")
    expired = api.create_return(
        entry2["id"],
        create_return_payload("AUTHORIZATION_REVOKED"),
        make_participant_officer_headers(receiver["id"]),
    )
    validate_error(expired, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)

    entry2_after = get_payment_entry(entry2["id"])
    assert entry2_after["status"] == "SETTLED"


def test_return_by_originating_participant_rejected(api, admin_headers):
    """PRD §3.7: "The guard chain runs in this order: the returning participant
    must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`); the entry must be in
    `SETTLED` status — a rule that also covers a second return attempt on an
    already-`RETURNED` entry (`ERR_ENTRY_NOT_SETTLED`); the returning
    participant must differ from the entry's originator side, so an `X-User-ID`
    equal to the entry's `originating_participant_id` is refused with
    `ERR_RETURN_PARTICIPANT_CONFLICT`; and the return must arrive inside the
    entry class's window — the count of banking days (Monday through Friday, no
    holiday calendar) from the entry's `settled_date` to the current logical
    date must not exceed the code's `return_timeframe_banking_days`, otherwise
    `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_by_originating_participant_rejected
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    entry = create_and_settle_entry(
        stack["originator"], stack["transaction_code"], stack["window"], amount_cents=5000
    )

    resp = api.create_return(
        entry["id"],
        create_return_payload("UNAUTHORIZED_DEBIT"),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_PARTICIPANT_CONFLICT)

    records, meta = validate_paginated(api.list_entry_returns(entry["id"], admin_headers))
    assert records == [] and meta["total_count"] == 0

    entry_after = get_payment_entry(entry["id"])
    assert entry_after["status"] == "SETTLED"

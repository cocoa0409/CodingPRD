"""Entry admission: same-day windows, settlement-run timing, account
validation, and authorization matching — PRD §2.8, §3.5, §3.6.
"""

from test_helpers import (
    ApiErrorId,
    compute_entry_fee_cents,
    compute_validated_until,
    create_account_validation,
    create_and_settle_entry,
    create_payment_entry,
    create_payment_entry_payload,
    date_add_days,
    get_payment_entry,
    iso_on_date,
    make_participant_officer_headers,
    set_clock,
    setup_origination_stack,
    validate_create_success,
    validate_error,
    validate_success,
)

_WEB_CODE_OVERRIDES = {
    "code": "WEB",
    "authorization_requirement": "ORAL_RECORDED",
    "account_validation_required": True,
}


def test_same_day_entry_limit_equal_allowed_exceeding_rejected(api, admin_headers):
    """PRD §3.5: "The entry's `amount_cents` must not exceed the window's
    `per_entry_limit_cents`, though an amount exactly equal to the limit is
    allowed, otherwise `ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/same_day_entry_limit_equal_allowed_exceeding_rejected
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]
    assert window["per_entry_limit_cents"] == 100000000

    set_clock("2026-09-01T16:00:00Z")
    headers = make_participant_officer_headers(participant["id"])

    equal = validate_create_success(
        api.create_payment_entry(
            create_payment_entry_payload(
                originator["id"], code["id"],
                amount_cents=100000000,
                same_day=True, settlement_window_id=window["id"],
            ),
            headers,
        )
    )
    assert equal["status"] == "ORIGINATED"
    assert equal["settlement_window_id"] == window["id"]

    over = api.create_payment_entry(
        create_payment_entry_payload(
            originator["id"], code["id"],
            amount_cents=100000001,
            same_day=True, settlement_window_id=window["id"],
        ),
        headers,
    )
    validate_error(over, ApiErrorId.ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED)


def test_entry_cancel_after_settle_rejected(api, admin_headers):
    """PRD §3.6: "An entry still in `ORIGINATED` may instead be cancelled by the
    `ParticipantOfficer` of the originating participant (a mismatch between
    `X-User-ID` and the entry's `originating_participant_id` is
    `ERR_FORBIDDEN`), moving it to `CANCELLED`"
    PRD §2.8: "State-machine legality of the requested transition — the target
    entity must be in a state that permits it (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/entry_cancel_after_settle_rejected
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    entry = create_and_settle_entry(
        stack["originator"], stack["transaction_code"], stack["window"],
        amount_cents=15000000,
    )
    assert entry["status"] == "SETTLED"

    resp = api.cancel_payment_entry(
        entry["id"], make_participant_officer_headers(participant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_payment_entry(entry["id"])
    assert after["status"] == "SETTLED"
    assert after["entry_fee_cents"] == compute_entry_fee_cents(15000000)


def test_run_settlement_before_cutoff_rejected(api, admin_headers):
    """PRD §3.6: "A `PlatformAdmin` runs a window once the window has closed for
    the day — the logical time must be at or after the window's
    `cutoff_time_utc` on the current logical date, and a run invoked earlier is
    rejected with `ERR_WINDOW_NOT_CLOSED`."

    Design: Corner/validations/run_settlement_before_cutoff_rejected
    """
    stack = setup_origination_stack(with_receiver=False)
    entry = create_payment_entry(
        stack["originator"], stack["transaction_code"], amount_cents=1000
    )

    set_clock("2026-09-01T16:00:00Z")
    resp = api.run_settlement(stack["window"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CLOSED)

    after = get_payment_entry(entry["id"])
    assert after["status"] == "ORIGINATED"
    assert after["settled_at"] is None


def test_same_day_entry_at_exact_cutoff_rejected(api, admin_headers):
    """PRD §3.5: "The requested window's `cutoff_time_utc` must be strictly
    later than the current logical time — a window whose cutoff has already
    passed today yields `ERR_WINDOW_CUTOFF_PASSED`."

    Design: Corner/validations/same_day_entry_at_exact_cutoff_rejected
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    set_clock("2026-09-01T17:00:00Z")

    resp = api.create_payment_entry(
        create_payment_entry_payload(
            stack["originator"]["id"], stack["transaction_code"]["id"],
            amount_cents=1000,
            same_day=True, settlement_window_id=stack["window"]["id"],
        ),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CUTOFF_PASSED)


def test_window_capacity_exactly_at_cap_allowed_then_over(api, admin_headers):
    """PRD §3.5: "And the participant's running same-day aggregate in that
    window — the sum of `amount_cents` over its entries assigned to that
    window, created on the current logical date, and still in `ORIGINATED` or
    `SETTLED` status — plus the new amount must not exceed the window's
    `odfi_window_cap_cents`, with a total landing exactly on the cap allowed,
    otherwise `ERR_WINDOW_CAPACITY_EXCEEDED`."

    Design: Corner/validations/window_capacity_exactly_at_cap_allowed_then_over
    """
    stack = setup_origination_stack(
        with_receiver=False,
        window_overrides={
            "per_entry_limit_cents": 2000000000,
            "odfi_window_cap_cents": 2500000000,
        },
        originator_overrides={"exposure_limit_cents": 10000000000},
    )
    participant = stack["participant"]
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]

    set_clock("2026-09-01T16:00:00Z")
    headers = make_participant_officer_headers(participant["id"])
    for amount in (1250000000, 1250000000):
        created = validate_create_success(
            api.create_payment_entry(
                create_payment_entry_payload(
                    originator["id"], code["id"],
                    amount_cents=amount,
                    same_day=True, settlement_window_id=window["id"],
                ),
                headers,
            )
        )
        assert created["status"] == "ORIGINATED"

    over = api.create_payment_entry(
        create_payment_entry_payload(
            originator["id"], code["id"],
            amount_cents=1000,
            same_day=True, settlement_window_id=window["id"],
        ),
        headers,
    )
    validate_error(over, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED)


def test_web_entry_with_valid_validation_passes(api, admin_headers):
    """PRD §3.5: "Third, when the transaction code's
    `account_validation_required` flag is true, a `VALID` **AccountValidation**
    must exist for the pair of `originator_id` and
    `receiver_account_number_hash` — one whose `validated_until` date is on or
    after the current logical date — otherwise the entry is rejected with
    `ERR_ACCOUNT_VALIDATION_REQUIRED`."
    PRD §3.5: "its `validated_until` is computed as the creation date plus 365
    days, and its `status` is derived against the logical clock on every read —
    `VALID` while the logical date is on or before `validated_until`, `EXPIRED`
    thereafter."

    Design: Corner/validations/web_entry_with_valid_validation_passes
    """
    stack = setup_origination_stack(with_receiver=False, code_overrides=_WEB_CODE_OVERRIDES)
    originator = stack["originator"]
    code = stack["transaction_code"]

    validation = create_account_validation(originator, "acct-web-1", method="MICRO_DEPOSIT")
    assert validation["validated_until"] == compute_validated_until("2026-09-01")
    assert validation["status"] == "VALID"

    entry = create_payment_entry(
        originator, code,
        amount_cents=2000,
        receiver_account_number_hash="acct-web-1",
        authorization_type="ORAL_RECORDED",
    )
    assert entry["status"] == "ORIGINATED"


def test_web_entry_with_expired_validation_rejected(api, admin_headers):
    """PRD §3.5: "its `validated_until` is computed as the creation date plus
    365 days, and its `status` is derived against the logical clock on every
    read — `VALID` while the logical date is on or before `validated_until`,
    `EXPIRED` thereafter."
    PRD §3.5: "Third, when the transaction code's `account_validation_required`
    flag is true, a `VALID` **AccountValidation** must exist for the pair of
    `originator_id` and `receiver_account_number_hash` — one whose
    `validated_until` date is on or after the current logical date — otherwise
    the entry is rejected with `ERR_ACCOUNT_VALIDATION_REQUIRED`."

    Design: Corner/validations/web_entry_with_expired_validation_rejected
    """
    stack = setup_origination_stack(with_receiver=False, code_overrides=_WEB_CODE_OVERRIDES)
    participant = stack["participant"]
    originator = stack["originator"]
    code = stack["transaction_code"]

    validation = create_account_validation(originator, "acct-web-9", method="PRENOTE")
    set_clock(iso_on_date(date_add_days(validation["validated_until"], 1), "09:00:00"))

    read_back = validate_success(api.get_account_validation(validation["id"], admin_headers))
    assert read_back["status"] == "EXPIRED"

    resp = api.create_payment_entry(
        create_payment_entry_payload(
            originator["id"], code["id"],
            amount_cents=2000,
            receiver_account_number_hash="acct-web-9",
            authorization_type="ORAL_RECORDED",
        ),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_VALIDATION_REQUIRED)


def test_web_entry_wrong_authorization_type_rejected(api, admin_headers):
    """PRD §3.5: "Fourth, the `authorization_type` must exactly equal the
    transaction code's `authorization_requirement` — except that a requirement
    of `NONE` accepts any authorization type — otherwise
    `ERR_AUTHORIZATION_REQUIREMENT_VIOLATION`."

    Design: Corner/validations/web_entry_wrong_authorization_type_rejected
    """
    stack = setup_origination_stack(with_receiver=False, code_overrides=_WEB_CODE_OVERRIDES)
    participant = stack["participant"]
    originator = stack["originator"]
    code = stack["transaction_code"]

    create_account_validation(originator, "acct-web-2", method="COMMERCIAL_SERVICE")

    resp = api.create_payment_entry(
        create_payment_entry_payload(
            originator["id"], code["id"],
            amount_cents=2000,
            receiver_account_number_hash="acct-web-2",
            authorization_type="WRITTEN_SIGNED",
        ),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_REQUIREMENT_VIOLATION)


def test_safety_gate_beats_constraint_gate_on_web_entry(api, admin_headers):
    """PRD §3.5: "Admission runs the checks of §2.8 in their fixed order, and
    the entry-specific gates are evaluated in this sequence. First, the
    originator's owning participant must be `ACTIVE`, otherwise
    `ERR_PARTICIPANT_NOT_ACTIVE`. Second, the originator itself must be
    `APPROVED`, otherwise `ERR_ORIGINATOR_NOT_APPROVED`. Third, when the
    transaction code's `account_validation_required` flag is true, a `VALID`
    **AccountValidation** must exist for the pair of `originator_id` and
    `receiver_account_number_hash` — one whose `validated_until` date is on or
    after the current logical date — otherwise the entry is rejected with
    `ERR_ACCOUNT_VALIDATION_REQUIRED`."
    PRD §2.8: "Business-safety rules (`ERR_ACCOUNT_VALIDATION_REQUIRED`,
    `ERR_SEGREGATION_OF_DUTIES`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_gate_beats_constraint_gate_on_web_entry
    """
    stack = setup_origination_stack(with_receiver=False, code_overrides=_WEB_CODE_OVERRIDES)
    participant = stack["participant"]

    resp = api.create_payment_entry(
        create_payment_entry_payload(
            stack["originator"]["id"], stack["transaction_code"]["id"],
            amount_cents=1000,
            receiver_account_number_hash="acct-web-none",
            authorization_type="WRITTEN_SIGNED",
        ),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_VALIDATION_REQUIRED)

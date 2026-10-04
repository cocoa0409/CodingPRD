"""Difficulty coverage: validation priority pairs, threshold boundaries,
and cross-entity state dependencies (PRD §2.8, §3.2, §3.5, §3.7, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    activate_contract,
    block_recipient,
    cancel_session,
    close_account,
    confirm_session,
    connect_and_end_call,
    create_contract,
    create_facility_raw,
    create_rate_schedule,
    create_regulatory_cap,
    create_session,
    create_verified_recipient,
    deposit,
    get_account,
    get_ledger,
    get_success_data,
    make_account_holder_headers,
    setup_account_with_confirmed_session,
    setup_call_ready_account,
    setup_funded_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Priority pair: safety (tier 7) beats fiscal (tier 10) on call connect
# ---------------------------------------------------------------------------


def test_blocked_recipient_error_beats_insufficient_balance(
    api, facility_staff_headers
):
    """PRD §2.8: "When a called number is both blocked and unaffordable, the rejection is `ERR_NUMBER_BLOCKED`, because consent and protection (tier 7) precede fiscal checks (tier 10)."
    PRD §3.5: "Finally, the account must be able to afford at least the applied connection fee plus one minute at the applied per-minute rate, or the attempt fails with `ERR_INSUFFICIENT_BALANCE`; when a number is both blocked and unaffordable, the block is the error reported, per the ordering in §2.8."

    Design: Difficulty/priority_pair_validation_conflict/call_blocked_number_beats_insufficient_balance
    """
    env = setup_funded_account(deposit_amount=0)  # balance 0
    account, inmate = env["account"], env["inmate"]
    blocked = create_verified_recipient(account["id"], label="R1")
    block_recipient(blocked, reason="do not call")

    resp = api.create_call(
        {
            "account_id": account["id"],
            "inmate_id": inmate["id"],
            "recipient_number_id": blocked["id"],
            "call_type": "LOCAL",
        },
        facility_staff_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NUMBER_BLOCKED)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_BALANCE

    _rows, meta = validate_paginated(
        api.list_calls(facility_staff_headers, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 0


def test_unblocked_recipient_empty_balance_reports_insufficient_balance(
    api, facility_staff_headers
):
    """PRD §3.5: "Finally, the account must be able to afford at least the applied connection fee plus one minute at the applied per-minute rate, or the attempt fails with `ERR_INSUFFICIENT_BALANCE`; when a number is both blocked and unaffordable, the block is the error reported, per the ordering in §2.8."

    Design: Difficulty/priority_pair_validation_conflict/call_blocked_number_beats_insufficient_balance
    """
    env = setup_funded_account(deposit_amount=0)  # balance 0
    account, inmate = env["account"], env["inmate"]
    recipient = create_verified_recipient(account["id"], label="R2")

    resp = api.create_call(
        {
            "account_id": account["id"],
            "inmate_id": inmate["id"],
            "recipient_number_id": recipient["id"],
            "call_type": "LOCAL",
        },
        facility_staff_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)
    assert resp.status_code == 402, (
        "the fiscal check fires once safety passes: 0 balance cannot cover "
        "the 200 connection fee plus one 18-cent minute"
    )

    _rows, meta = validate_paginated(
        api.list_calls(facility_staff_headers, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Priority pair: temporal overlap (tier 8) beats capacity/daily (tier 9)
# ---------------------------------------------------------------------------


def _overlap_env():
    """Facility (booths 5, daily limit 2) with one funded account whose
    inmate already holds CONFIRMED sessions 08:30-09:00 and 09:00-09:30."""
    env = setup_funded_account(
        deposit_amount=2025,
        facility_overrides={"video_booth_count": 5},
    )
    first = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-15T08:30:00Z",
        scheduled_end="2026-09-15T09:00:00Z",
    )
    confirm_session(first["id"])
    second = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-15T09:00:00Z",
        scheduled_end="2026-09-15T09:30:00Z",
    )
    confirm_session(second["id"])
    assert get_account(env["account"]["id"])["balance_cents"] == 1000
    return env


def test_overlap_error_beats_daily_limit_on_conflict(api, facility_staff_headers):
    """PRD §2.8: "And when a proposed video session would simultaneously overlap another of the inmate's sessions, exceed booth capacity, and break the daily limit, the rejection is `ERR_INMATE_SESSION_OVERLAP`, because temporal rules (tier 8) precede capacity rules (tier 9)."
    PRD §3.7: "When several of these fail together, the overlap error is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/video_inmate_overlap_beats_daily_limit
    """
    env = _overlap_env()
    third = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-15T08:45:00Z",
        scheduled_end="2026-09-15T09:15:00Z",
    )

    resp = api.confirm_video_session(third["id"], facility_staff_headers)
    validate_error(resp, ApiErrorId.ERR_INMATE_SESSION_OVERLAP)
    assert resp.json()["data"]["error_id"] != (
        ApiErrorId.ERR_DAILY_SESSION_LIMIT_EXCEEDED
    ), "temporal rules (tier 8) precede capacity rules (tier 9)"

    reread = get_success_data(api.get_video_session(third["id"], facility_staff_headers))
    assert reread["status"] == "REQUESTED"
    assert get_account(env["account"]["id"])["balance_cents"] == 1000, (
        "a rejected confirm charges nothing"
    )


def test_third_session_same_day_hits_daily_limit_when_not_overlapping(
    api, facility_staff_headers
):
    """PRD §3.7: "Third, the inmate's confirmed sessions starting on the same UTC date must number fewer than the facility's `daily_session_limit_per_inmate`, otherwise `ERR_DAILY_SESSION_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/video_inmate_overlap_beats_daily_limit
    """
    env = _overlap_env()
    third = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-15T10:00:00Z",
        scheduled_end="2026-09-15T10:30:00Z",
    )

    resp = api.confirm_video_session(third["id"], facility_staff_headers)
    validate_error(resp, ApiErrorId.ERR_DAILY_SESSION_LIMIT_EXCEEDED)

    reread = get_success_data(api.get_video_session(third["id"], facility_staff_headers))
    assert reread["status"] == "REQUESTED"
    assert get_account(env["account"]["id"])["balance_cents"] == 1000


# ---------------------------------------------------------------------------
# Boundary: schedule rates exactly at the cap vs one cent over
# ---------------------------------------------------------------------------


def test_schedule_rates_exactly_at_cap_activate(api, platform_admin_headers):
    """PRD §3.2: "Every price on the schedule is re-validated against the jurisdiction's caps at this moment: each per-minute rate must not exceed `max_per_minute_cents`, the `connection_fee_cents` must not exceed `max_connection_fee_cents`, and both `message_price_cents` and `video_session_fee_cents` must not exceed `max_ancillary_fee_cents`, with a price exactly equal to its cap allowed; any breach fails with `ERR_RATE_EXCEEDS_CAP`."
    PRD §2.7: "Activation supersedes whichever schedule is currently active on that contract and advances the contract's `version` by one"

    Design: Difficulty/boundary_precision_check/schedule_rate_exactly_at_cap_activates_one_cent_over_fails
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="Boundary Facility")
    contract = create_contract(facility["id"])
    activate_contract(contract["id"])
    contract = get_success_data(api.get_contract(contract["id"], platform_admin_headers))

    at_cap = create_rate_schedule(
        contract["id"],
        local_per_minute_cents=25,
        intrastate_per_minute_cents=25,
        interstate_per_minute_cents=25,
        international_per_minute_cents=25,
        connection_fee_cents=300,
        message_price_cents=500,
        video_session_fee_cents=500,
    )
    version_before = contract["version"]
    activated = validate_success(
        api.activate_rate_schedule(at_cap["id"], version_before, platform_admin_headers)
    )
    assert activated["status"] == "ACTIVE", "a price exactly equal to its cap is allowed"

    after = get_success_data(api.get_contract(contract["id"], platform_admin_headers))
    assert after["version"] == version_before + 1


def test_schedule_one_cent_over_cap_rejected(api, platform_admin_headers):
    """PRD §3.2: "Every price on the schedule is re-validated against the jurisdiction's caps at this moment: each per-minute rate must not exceed `max_per_minute_cents`, the `connection_fee_cents` must not exceed `max_connection_fee_cents`, and both `message_price_cents` and `video_session_fee_cents` must not exceed `max_ancillary_fee_cents`, with a price exactly equal to its cap allowed; any breach fails with `ERR_RATE_EXCEEDS_CAP`."

    Design: Difficulty/boundary_precision_check/schedule_rate_exactly_at_cap_activates_one_cent_over_fails
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="Boundary Facility")
    contract = create_contract(facility["id"])
    activate_contract(contract["id"])
    contract = get_success_data(api.get_contract(contract["id"], platform_admin_headers))

    at_cap = create_rate_schedule(
        contract["id"],
        local_per_minute_cents=25,
        intrastate_per_minute_cents=25,
        interstate_per_minute_cents=25,
        international_per_minute_cents=25,
        connection_fee_cents=300,
        message_price_cents=500,
        video_session_fee_cents=500,
    )
    over_cap = create_rate_schedule(
        contract["id"],
        local_per_minute_cents=25,
        intrastate_per_minute_cents=25,
        interstate_per_minute_cents=26,
        international_per_minute_cents=25,
        connection_fee_cents=300,
        message_price_cents=500,
        video_session_fee_cents=500,
    )
    validate_success(
        api.activate_rate_schedule(
            at_cap["id"], contract["version"], platform_admin_headers
        )
    )
    fresh = get_success_data(api.get_contract(contract["id"], platform_admin_headers))

    rejected = api.activate_rate_schedule(
        over_cap["id"], fresh["version"], platform_admin_headers
    )
    validate_error(rejected, ApiErrorId.ERR_RATE_EXCEEDS_CAP)
    assert rejected.status_code == 409

    assert get_success_data(
        api.get_rate_schedule(over_cap["id"], platform_admin_headers)
    )["status"] == "DRAFT", "the failed activation leaves the schedule DRAFT"
    assert get_success_data(
        api.get_rate_schedule(at_cap["id"], platform_admin_headers)
    )["status"] == "ACTIVE", "the failed activation supersedes nothing"


# ---------------------------------------------------------------------------
# Boundary: refundable exactly zero vs one cent on account closure
# ---------------------------------------------------------------------------


def _zero_boundary_env(deposit_amount):
    """Funded account driven to an exact closure balance via two INTERSTATE
    calls (60s -> 225, 61s -> 250)."""
    env = setup_call_ready_account(deposit_amount=0)
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    deposit(account, deposit_amount)
    connect_and_end_call(account, inmate, recipient, 60, "INTERSTATE")
    connect_and_end_call(account, inmate, recipient, 61, "INTERSTATE")
    return env


def test_close_with_zero_refundable_creates_no_refund_request(
    api, compliance_officer_headers
):
    """PRD §3.8: "When the refundable amount is zero, there is nothing to adjudicate: no request is created, a single `CLOSURE_FEE` debit of the entire snapshot zeroes the balance, and the full snapshot becomes the account's `retained_fees_cents`."

    Design: Difficulty/boundary_precision_check/account_close_refundable_exactly_zero_creates_no_refund_request
    """
    env = _zero_boundary_env(600)  # 575 - 225 - 250 = 100 == closure fee
    account = env["account"]
    assert get_account(account["id"])["balance_cents"] == 100

    closed = close_account(account)
    assert closed["status"] == "CLOSED"
    assert closed["balance_at_closure_cents"] == 100
    assert closed["refundable_computed_cents"] == 0
    assert closed["latest_refund_request_id"] is None, (
        "at the zero boundary no RefundRequest is created"
    )

    _rows, meta = validate_paginated(
        api.list_refund_requests(
            compliance_officer_headers, params={"account_id": account["id"]}
        )
    )
    assert meta["total_count"] == 0

    final = get_account(account["id"])
    assert final["balance_cents"] == 0
    assert final["retained_fees_cents"] == 100
    fees = [r for r in get_ledger(account["id"]) if r["type"] == "CLOSURE_FEE"]
    assert len(fees) == 1 and fees[0]["amount_cents"] == -100


def test_close_with_one_cent_refundable_creates_refund_request(
    api, compliance_officer_headers
):
    """PRD §3.8: "When it is positive, a **RefundRequest** is created with `source` `CLOSURE` and status `REQUESTED`, its `requested_amount_cents` equal to the full closure snapshot; the balance stays frozen on the ledger, `latest_refund_request_id` is set on the account, and `requested_by_user_id` with `requested_by_role` record who closed it ('system' for the auto-close)."

    Design: Difficulty/boundary_precision_check/account_close_refundable_exactly_zero_creates_no_refund_request
    """
    env = _zero_boundary_env(601)  # 576 - 225 - 250 = 101 -> refundable 1
    account = env["account"]
    assert get_account(account["id"])["balance_cents"] == 101

    closed = close_account(account)
    assert closed["status"] == "CLOSED"
    assert closed["balance_at_closure_cents"] == 101
    assert closed["refundable_computed_cents"] == 1, (
        "one cent over the closure fee flips the fork: a request is created"
    )
    refund_request_id = closed["latest_refund_request_id"]
    assert refund_request_id

    refund_request = validate_success(
        api.get_refund_request(refund_request_id, compliance_officer_headers)
    )
    assert refund_request["source"] == "CLOSURE"
    assert refund_request["status"] == "REQUESTED"
    assert refund_request["requested_amount_cents"] == 101


# ---------------------------------------------------------------------------
# Cross-entity state dependency: schedule activation requires ACTIVE contract
# ---------------------------------------------------------------------------


def test_schedule_activation_rejected_while_contract_draft(
    api, platform_admin_headers
):
    """PRD §3.2: "A `PlatformAdmin` activates a `DRAFT` schedule under the contract-version guard of §2.7 — the request carries `expected_contract_version` and is rejected with `ERR_STALE_VERSION` (HTTP 412) when that view is stale — and only while the parent contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/schedule_activation_requires_contract_active
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="Gate Facility")
    contract = create_contract(facility["id"])  # left DRAFT
    schedule = create_rate_schedule(contract["id"])

    resp = api.activate_rate_schedule(
        schedule["id"], contract["version"], platform_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
    assert resp.status_code == 409

    reread = get_success_data(
        api.get_rate_schedule(schedule["id"], platform_admin_headers)
    )
    assert reread["status"] == "DRAFT"


def test_schedule_activation_succeeds_after_contract_activation(
    api, platform_admin_headers
):
    """PRD §3.2: "Activation, by a `PlatformAdmin`, moves the contract from `DRAFT` to `ACTIVE`, and it is where commercial terms meet regulation."
    PRD §3.2: "only while the parent contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/schedule_activation_requires_contract_active
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="Gate Facility")
    contract = create_contract(facility["id"])
    schedule = create_rate_schedule(contract["id"])

    blocked = api.activate_rate_schedule(
        schedule["id"], contract["version"], platform_admin_headers
    )
    validate_error(blocked, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    validate_success(api.activate_contract(contract["id"], platform_admin_headers))
    fresh = get_success_data(api.get_contract(contract["id"], platform_admin_headers))

    activated = validate_success(
        api.activate_rate_schedule(schedule["id"], fresh["version"], platform_admin_headers)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] is not None


# ---------------------------------------------------------------------------
# Cross-entity state dependency: account close vs live confirmed session
# ---------------------------------------------------------------------------


def test_account_close_rejected_with_future_confirmed_session(api):
    """PRD §3.8: "Three guards protect in-flight business: the account must have no `CONNECTED` call (`ERR_ACCOUNT_HAS_ACTIVE_CALLS`), no `CONFIRMED` video session whose `scheduled_end` is still in the future (`ERR_ACCOUNT_HAS_ACTIVE_SESSIONS`), and no message still `PENDING_REVIEW` (`ERR_ACCOUNT_HAS_PENDING_MESSAGES`)."

    Design: Difficulty/cross_entity_state_dependency/account_close_blocked_until_confirmed_session_cancelled
    """
    env = setup_account_with_confirmed_session()
    account = env["account"]
    assert account["balance_cents"] == 500

    resp = api.close_account(
        account["id"], make_account_holder_headers(account["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_ACTIVE_SESSIONS)
    assert resp.status_code == 409
    assert get_account(account["id"])["status"] == "ACTIVE"


def test_account_close_succeeds_after_session_cancelled(api):
    """PRD §3.7: "A successful confirmed cancellation appends a `VIDEO_REFUND` credit of the full `charge_cents`, recomputes the balance, and restores the session's booth-minutes to the facility's bookable pool exactly, as the booth-minutes invariant requires."
    PRD §3.8: "The closure fee is zero for the release auto-close, and otherwise the lesser of the contract's `closure_fee_cents` and the jurisdiction's `max_ancillary_fee_cents` at close time"

    Design: Difficulty/cross_entity_state_dependency/account_close_blocked_until_confirmed_session_cancelled
    """
    env = setup_account_with_confirmed_session()
    account, session = env["account"], env["session"]

    cancelled = cancel_session(session, account=account)
    assert cancelled["status"] == "CANCELLED"
    assert get_account(account["id"])["balance_cents"] == 1000, (
        "the cancellation refunds the 500-cent video fee"
    )

    closed = close_account(account)
    assert closed["status"] == "CLOSED"
    assert closed["refundable_computed_cents"] == 900, (
        "1000 - 100 closure fee under SIMPLE_BALANCE"
    )

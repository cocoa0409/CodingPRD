"""Composite setup helpers for the correctional-comm-services test suite.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints only (the harness restarts the server before every test, so no
state carries over). Setup calls use the lenient get_success_data()
validator so a broken setup surfaces as a clear setup error.

Identity threading: AccountHolder calls always use
make_account_holder_headers(account["id"]) and RecipientParty calls use
make_recipient_party_headers(recipient["id"]) — never the shared constants.

Clock discipline: every environment pins the logical clock to the PRD §2.4
default (2026-09-01T00:00:00Z) first; all scheduled dates are computed as
offsets from that instant and are therefore always reachable by advancing
the clock. No date before the default start is ever emitted.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    create_account_payload,
    create_call_payload,
    create_complaint_payload,
    create_contract_payload,
    create_facility_payload,
    create_inmate_payload,
    create_message_payload,
    create_rate_schedule_payload,
    create_recipient_number_payload,
    create_regulatory_cap_payload,
    create_video_session_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
    make_compliance_officer_headers,
    make_facility_staff_headers,
    make_recipient_party_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_REGULATOR = TEST_USERS["state_regulator_headers"]
_STAFF = TEST_USERS["facility_staff_headers"]
_OFFICER = TEST_USERS["compliance_officer_headers"]
_OFFICER_ALT = TEST_USERS["compliance_officer_alt_headers"]


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------


def _parse_instant(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _format_instant(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(current_utc=CLOCK_DEFAULT_UTC) -> dict:
    """Set the server logical clock (PlatformAdmin-only, unprefixed path)."""
    return get_success_data(api_client.set_clock(current_utc, _ADMIN))


def iso_days_after(base_iso: str, days: int) -> str:
    """The instant exactly `days` after base_iso (base may be CLOCK_DEFAULT_UTC
    or any timestamp the server stamped, e.g. unclaimed_since)."""
    return _format_instant(_parse_instant(base_iso) + timedelta(days=days))


def advance_clock_to(iso: str) -> dict:
    return set_clock(iso)


def advance_clock_days(days: int, base_iso: str = CLOCK_DEFAULT_UTC) -> str:
    """Advance the logical clock `days` past base_iso; returns the new instant."""
    target = iso_days_after(base_iso, days)
    set_clock(target)
    return target


def future_session_window(days_ahead=10, start_minute=600, duration_minutes=30):
    """A (start, end) ISO pair on the UTC date CLOCK_DEFAULT + days_ahead,
    `start_minute` after 00:00 UTC (default 10:00), lasting duration_minutes.
    Defaults sit inside the default visiting window 480-1200 and satisfy the
    15-minute minimum; start is strictly in the future for days_ahead >= 1."""
    day = (_parse_instant(CLOCK_DEFAULT_UTC) + timedelta(days=days_ahead)).date()
    start = datetime(
        day.year, day.month, day.day, tzinfo=timezone.utc
    ) + timedelta(minutes=start_minute)
    end = start + timedelta(minutes=duration_minutes)
    return _format_instant(start), _format_instant(end)


def date_string(days_ahead=10) -> str:
    """The 'YYYY-MM-DD' date of CLOCK_DEFAULT_UTC + days_ahead."""
    day = (_parse_instant(CLOCK_DEFAULT_UTC) + timedelta(days=days_ahead)).date()
    return day.isoformat()


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------


def create_regulatory_cap(**overrides) -> dict:
    return get_success_data(
        api_client.create_regulatory_cap(create_regulatory_cap_payload(**overrides), _REGULATOR)
    )


def create_facility_raw(**overrides) -> dict:
    """Create a facility (born ONBOARDING; not yet bookable)."""
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), _ADMIN)
    )


def create_contract(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(create_contract_payload(facility_id, **overrides), _ADMIN)
    )


def activate_contract(contract_id) -> dict:
    return get_success_data(api_client.activate_contract(contract_id, _ADMIN))


def create_rate_schedule(contract_id, **overrides) -> dict:
    """Create a DRAFT rate schedule on a contract."""
    return get_success_data(
        api_client.create_rate_schedule(
            contract_id, create_rate_schedule_payload(**overrides), _ADMIN
        )
    )


def activate_rate_schedule(schedule_id, expected_contract_version) -> dict:
    return get_success_data(
        api_client.activate_rate_schedule(schedule_id, expected_contract_version, _ADMIN)
    )


def activate_facility(facility_id) -> dict:
    return get_success_data(api_client.activate_facility(facility_id, _ADMIN))


def book_inmate(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_inmate(create_inmate_payload(facility_id, **overrides), _STAFF)
    )


def open_account(facility_id, inmate_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_account(
            create_account_payload(facility_id, inmate_id, **overrides), _STAFF
        )
    )


def deposit(account, amount_cents, as_staff=False) -> dict:
    """Deposit into an account; returns the updated account. Holder identity
    is the account id unless as_staff routes the call through FacilityStaff."""
    headers = _STAFF if as_staff else make_account_holder_headers(account["id"])
    return get_success_data(api_client.create_deposit(account["id"], amount_cents, headers))


def get_account(account_id, headers=None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or _STAFF))


def get_ledger(account_id, entry_type=None, headers=None) -> list:
    params = {"type": entry_type, "limit": 100} if entry_type else {"limit": 100}
    data, _meta = validate_paginated(
        api_client.get_account_ledger(account_id, headers or _STAFF, params=params)
    )
    return data


def create_recipient(account_id, as_staff=False, **overrides) -> dict:
    """Register a recipient number (VERIFICATION_SENT; response carries the
    server-generated verification_code)."""
    headers = _STAFF if as_staff else make_account_holder_headers(account_id)
    return get_success_data(
        api_client.create_recipient_number(
            create_recipient_number_payload(account_id, **overrides), headers
        )
    )


def verify_recipient(recipient, code=None, consent=True) -> dict:
    """Verify a recipient number as the RecipientParty (entity-backed id)."""
    return get_success_data(
        api_client.verify_recipient_number(
            recipient["id"],
            code if code is not None else recipient["verification_code"],
            consent,
            make_recipient_party_headers(recipient["id"]),
        )
    )


def create_verified_recipient(account_id, **overrides) -> dict:
    """Create + verify a recipient number; returns the VERIFIED record (the
    returned dict still carries verification_code for later re-verify)."""
    recipient = create_recipient(account_id, **overrides)
    verified = verify_recipient(recipient)
    verified["verification_code"] = recipient["verification_code"]
    return verified


def block_recipient(recipient, reason="do not call") -> dict:
    return get_success_data(
        api_client.request_block(
            recipient["id"],
            make_recipient_party_headers(recipient["id"]),
            reason=reason,
        )
    )


def decide_privilege(recipient_number_id, decision, note=None, officer_id=None) -> dict:
    headers = (
        make_compliance_officer_headers(officer_id) if officer_id else _OFFICER
    )
    return get_success_data(
        api_client.privilege_decision(recipient_number_id, decision, headers, note=note)
    )


def connect_call(account, inmate, recipient, call_type="LOCAL") -> dict:
    return get_success_data(
        api_client.create_call(
            create_call_payload(
                account["id"], inmate["id"], recipient["id"], call_type=call_type
            ),
            _STAFF,
        )
    )


def connect_and_end_call(
    account, inmate, recipient, duration_seconds=60, call_type="LOCAL"
) -> dict:
    call = connect_call(account, inmate, recipient, call_type=call_type)
    return get_success_data(api_client.end_call(call["id"], duration_seconds, _STAFF))


def create_session(facility, inmate, account, as_staff=False, **overrides) -> dict:
    """Create a REQUESTED video session. scheduled_start/scheduled_end may be
    passed explicitly or via days_ahead/start_minute/duration_minutes."""
    start = overrides.pop("scheduled_start", None)
    end = overrides.pop("scheduled_end", None)
    if start is None or end is None:
        start, end = future_session_window(
            days_ahead=overrides.pop("days_ahead", 10),
            start_minute=overrides.pop("start_minute", 600),
            duration_minutes=overrides.pop("duration_minutes", 30),
        )
    headers = _STAFF if as_staff else make_account_holder_headers(account["id"])
    return get_success_data(
        api_client.create_video_session(
            create_video_session_payload(
                facility["id"], inmate["id"], account["id"], start, end, **overrides
            ),
            headers,
        )
    )


def confirm_session(session_id) -> dict:
    return get_success_data(api_client.confirm_video_session(session_id, _STAFF))


def create_and_confirm_session(facility, inmate, account, **overrides) -> dict:
    session = create_session(facility, inmate, account, **overrides)
    return confirm_session(session["id"])


def cancel_session(session, as_staff=False, account=None) -> dict:
    if as_staff:
        headers = _STAFF
    else:
        owner_id = (account or {}).get("id") or session["account_id"]
        headers = make_account_holder_headers(owner_id)
    return get_success_data(api_client.cancel_video_session(session["id"], headers))


def create_message(account, inmate, body_text="hello") -> dict:
    """Create a PENDING_REVIEW tablet message (AccountHolder-only endpoint)."""
    return get_success_data(
        api_client.create_message(
            create_message_payload(account["id"], inmate["id"], body_text),
            make_account_holder_headers(account["id"]),
        )
    )


def review_message(message_id, decision="APPROVE", review_note=None) -> dict:
    return get_success_data(
        api_client.review_message(message_id, decision, _STAFF, review_note=review_note)
    )


def close_account(account, as_staff=False, staff_id=None) -> dict:
    """Close an account; returns the CLOSED account (with closure snapshots)."""
    if as_staff:
        headers = make_facility_staff_headers(staff_id) if staff_id else _STAFF
    else:
        headers = make_account_holder_headers(account["id"])
    return get_success_data(api_client.close_account(account["id"], headers))


def decide_refund(refund_request_id, decision="APPROVE", officer_id=None,
                  denial_reason=None) -> dict:
    headers = (
        make_compliance_officer_headers(officer_id) if officer_id else _OFFICER
    )
    return get_success_data(
        api_client.decide_refund_request(
            refund_request_id, decision, headers, denial_reason=denial_reason
        )
    )


def mark_refund_paid(refund_request_id, officer_id=None) -> dict:
    """Disburse an APPROVED refund. Defaults to the ALT officer so payer differs
    from the default decider (segregation of duties, PRD §3.8)."""
    headers = (
        make_compliance_officer_headers(officer_id) if officer_id else _OFFICER_ALT
    )
    return get_success_data(api_client.mark_refund_paid(refund_request_id, headers))


def release_inmate(inmate_id) -> dict:
    return get_success_data(api_client.release_inmate(inmate_id, _STAFF))


def get_video_availability(facility_id, date, headers=None) -> dict:
    return get_success_data(
        api_client.get_video_availability(facility_id, date, headers or _STAFF)
    )


def get_regulatory_summary(facility_id, period_start, period_end, headers=None) -> dict:
    return get_success_data(
        api_client.get_regulatory_summary(
            facility_id, period_start, period_end, headers or _OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: composite environment builders
# ---------------------------------------------------------------------------


def setup_active_facility(
    facility_overrides=None,
    cap_overrides=None,
    contract_overrides=None,
    schedule_overrides=None,
    pin_clock=True,
) -> dict:
    """The standard bookable environment: regulatory cap row, facility, an
    ACTIVE contract, and an ACTIVE rate schedule, with the facility itself
    ACTIVE. Pins the logical clock to the PRD default first.

    Returns {"cap", "facility", "contract", "schedule"}. `contract` is the
    refreshed record AFTER schedule activation (its version has advanced).

    OCC note: the contract version used for schedule activation is re-read
    after contract activation, so the fixture is correct regardless of
    whether contract activation itself advances the version."""
    if pin_clock:
        set_clock(CLOCK_DEFAULT_UTC)
    cap = create_regulatory_cap(**(cap_overrides or {}))
    facility = create_facility_raw(**(facility_overrides or {}))
    contract = create_contract(facility["id"], **(contract_overrides or {}))
    activate_contract(contract["id"])
    contract = get_success_data(api_client.get_contract(contract["id"], _ADMIN))
    schedule = create_rate_schedule(contract["id"], **(schedule_overrides or {}))
    activate_rate_schedule(schedule["id"], contract["version"])
    schedule = get_success_data(api_client.get_rate_schedule(schedule["id"], _ADMIN))
    facility = activate_facility(facility["id"])
    contract = get_success_data(api_client.get_contract(contract["id"], _ADMIN))
    return {
        "cap": cap,
        "facility": facility,
        "contract": contract,
        "schedule": schedule,
    }


def setup_funded_account(
    deposit_amount=1025,
    funding_model="PREPAID",
    deposit_as_staff=False,
    env=None,
    **env_kwargs,
) -> dict:
    """Active-facility environment + one IN_CUSTODY inmate + one account with
    one deposit applied. Default deposit 1025 against the default 25-cent
    deposit fee lands the balance at 1000 cents.

    Returns the env dict plus "inmate" and "account" (post-deposit)."""
    if env is None:
        env = setup_active_facility(**env_kwargs)
    inmate = book_inmate(env["facility"]["id"])
    account = open_account(
        env["facility"]["id"], inmate["id"], funding_model=funding_model
    )
    if deposit_amount:
        account = deposit(account, deposit_amount, as_staff=deposit_as_staff)
    return {**env, "inmate": inmate, "account": account}


def setup_call_ready_account(deposit_amount=1025, **kwargs) -> dict:
    """Funded account plus one VERIFIED recipient on its contact list —
    everything call/message/session creation needs. Adds "recipient"."""
    env = setup_funded_account(deposit_amount=deposit_amount, **kwargs)
    recipient = create_verified_recipient(env["account"]["id"])
    return {**env, "recipient": recipient}


def setup_account_with_confirmed_session(
    deposit_amount=1025, session_kwargs=None, **kwargs
) -> dict:
    """Funded account with one CONFIRMED video session (fee charged). Adds
    "session". Default funding leaves balance 500 after the 500-cent video
    fee against the standard environment."""
    env = setup_funded_account(deposit_amount=deposit_amount, **kwargs)
    session = create_and_confirm_session(
        env["facility"], env["inmate"], env["account"], **(session_kwargs or {})
    )
    account = get_account(env["account"]["id"])
    return {**env, "session": session, "account": account}


# ---------------------------------------------------------------------------
# Tier 3: closure / refund / escheat lifecycle builders
# ---------------------------------------------------------------------------


def setup_closed_account_with_refund(deposit_amount=1025, close_as_staff=False,
                                     **kwargs) -> dict:
    """Funded account closed by its holder (or staff). Default geometry:
    deposit 1025, fee 25 -> balance 1000; closure fee 100 -> refundable 900
    under the default SIMPLE_BALANCE jurisdiction, so a RefundRequest in
    REQUESTED exists. Adds "closed_account" and "refund_request" (the latter
    is None when the refundable amount was exactly zero)."""
    env = setup_funded_account(deposit_amount=deposit_amount, **kwargs)
    closed = close_account(env["account"], as_staff=close_as_staff)
    refund_request = None
    if closed.get("latest_refund_request_id"):
        refund_request = get_success_data(
            api_client.get_refund_request(closed["latest_refund_request_id"], _OFFICER)
        )
    return {**env, "account": closed, "closed_account": closed,
            "refund_request": refund_request}


def setup_denied_refund_account(deposit_amount=1025, officer_id=None, **kwargs) -> dict:
    """Closed account whose refund request was DENIED — the computed payout is
    now the account's unclaimed balance (escheat-eligible, escheat_status
    still NONE until the dormancy scan). Adds "decision"."""
    env = setup_closed_account_with_refund(deposit_amount=deposit_amount, **kwargs)
    rr = env["refund_request"]
    assert rr is not None, "denied-refund setup requires a RefundRequest to exist"
    decision = decide_refund(
        rr["id"], decision="DENY", officer_id=officer_id,
        denial_reason="owner could not be located",
    )
    account = get_account(env["account"]["id"])
    return {**env, "account": account, "decision": decision}


def setup_dormant_account(scan_at_exact_boundary=True, **kwargs) -> dict:
    """Denied-refund account advanced to unclaimed_since + dormancy_days and
    flagged DORMANT by the dormancy scan (boundary: exactly equal qualifies).
    With scan_at_exact_boundary=False the clock stops one day short and the
    scan flags nothing. Adds "scan_result" (the {accounts_flagged} payload)."""
    env = setup_denied_refund_account(**kwargs)
    account = env["account"]
    dormancy_days = env["cap"]["dormancy_days"]
    offset = dormancy_days if scan_at_exact_boundary else dormancy_days - 1
    advance_clock_to(iso_days_after(account["unclaimed_since"], offset))
    scan_result = get_success_data(
        api_client.run_dormancy_scan(env["facility"]["id"], _ADMIN)
    )
    account = get_account(account["id"])
    return {**env, "account": account, "scan_result": scan_result}


def setup_notice_sent_account(**kwargs) -> dict:
    """Dormant account with the escheat notice sent (escheat_status
    NOTICE_SENT; escheat_notice_sent_at stamped at the dormancy boundary)."""
    env = setup_dormant_account(**kwargs)
    account = get_success_data(
        api_client.send_escheat_notice(env["account"]["id"], _OFFICER)
    )
    return {**env, "account": account}


def setup_remitted_account(**kwargs) -> dict:
    """Notice-sent account remitted at exactly notice + claim_window_days
    (boundary allows remittance). Ends REMITTED with ledger balance zero."""
    env = setup_notice_sent_account(**kwargs)
    account = env["account"]
    claim_window_days = env["cap"]["claim_window_days"]
    advance_clock_to(
        iso_days_after(account["escheat_notice_sent_at"], claim_window_days)
    )
    account = get_success_data(api_client.remit_escheat(account["id"], _OFFICER))
    return {**env, "account": account}


def setup_claimed_account(**kwargs) -> dict:
    """Dormant account whose holder claims the unclaimed balance: escheat
    status CLAIMED and an auto-APPROVED ESCHEAT_CLAIM RefundRequest created.
    Adds "claim_refund_request"."""
    env = setup_dormant_account(**kwargs)
    account = get_success_data(
        api_client.claim_unclaimed(
            env["account"]["id"], make_account_holder_headers(env["account"]["id"])
        )
    )
    claim_rr = None
    if account.get("latest_refund_request_id"):
        claim_rr = get_success_data(
            api_client.get_refund_request(account["latest_refund_request_id"], _OFFICER)
        )
    return {**env, "account": account, "claim_refund_request": claim_rr}


def setup_paid_refund_account(**kwargs) -> dict:
    """Closed account whose refund request was APPROVED then PAID (default
    decider and payer are distinct officers, satisfying the SoD pairing).
    Adds "decision" and "payment"."""
    env = setup_closed_account_with_refund(**kwargs)
    rr = env["refund_request"]
    assert rr is not None, "paid-refund setup requires a RefundRequest to exist"
    decision = decide_refund(rr["id"], decision="APPROVE")
    payment = mark_refund_paid(rr["id"])
    account = get_account(env["account"]["id"])
    return {**env, "account": account, "decision": decision, "payment": payment}


# ---------------------------------------------------------------------------
# Tier 4: complaint lifecycle builders
# ---------------------------------------------------------------------------


def file_complaint(facility, account=None, as_staff=False, **overrides) -> dict:
    """File a complaint (FILED). When an account is supplied and as_staff is
    False, the complaint is filed by the AccountHolder with the account as
    the ownership anchor (subject_account_id defaults to that account)."""
    if account is not None and "subject_account_id" not in overrides:
        overrides["subject_account_id"] = account["id"]
    if as_staff:
        headers = _STAFF
    elif account is not None:
        headers = make_account_holder_headers(account["id"])
    else:
        headers = _STAFF
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(facility["id"], **overrides), headers
        )
    )


def setup_complaint_under_review(**kwargs) -> dict:
    """Facility environment + one complaint moved FILED -> UNDER_REVIEW by a
    ComplianceOfficer. Returns env plus "complaint"."""
    env = setup_funded_account(**kwargs)
    complaint = file_complaint(env["facility"], account=env["account"])
    complaint = get_success_data(
        api_client.start_complaint_review(complaint["id"], _OFFICER)
    )
    return {**env, "complaint": complaint}


__all__ = [
    "set_clock",
    "iso_days_after",
    "advance_clock_to",
    "advance_clock_days",
    "future_session_window",
    "date_string",
    "create_regulatory_cap",
    "create_facility_raw",
    "create_contract",
    "activate_contract",
    "create_rate_schedule",
    "activate_rate_schedule",
    "activate_facility",
    "book_inmate",
    "open_account",
    "deposit",
    "get_account",
    "get_ledger",
    "create_recipient",
    "verify_recipient",
    "create_verified_recipient",
    "block_recipient",
    "decide_privilege",
    "connect_call",
    "connect_and_end_call",
    "create_session",
    "confirm_session",
    "create_and_confirm_session",
    "cancel_session",
    "create_message",
    "review_message",
    "close_account",
    "decide_refund",
    "mark_refund_paid",
    "release_inmate",
    "get_video_availability",
    "get_regulatory_summary",
    "setup_active_facility",
    "setup_funded_account",
    "setup_call_ready_account",
    "setup_account_with_confirmed_session",
    "setup_closed_account_with_refund",
    "setup_denied_refund_account",
    "setup_dormant_account",
    "setup_notice_sent_account",
    "setup_remitted_account",
    "setup_claimed_account",
    "setup_paid_refund_account",
    "file_complaint",
    "setup_complaint_under_review",
]

"""Composite setup helpers that walk the public API to a wanted state.

The harness restarts the server before every test, so each test starts
against an empty database and must build its world through the API alone.
These helpers perform that walking and return the created resources with
their fresh versions.

The default logical clock reads 2026-09-01T00:00:00Z on a fresh deployment;
every default settlement date below is chosen so deposits can settle at that
instant and land inside the trailing ninety-day scoring window. OCC-carrying
writes always re-read the parent first so the expected version is fresh.

Setup calls use the lenient success reader so a failure inside a fixture is
reported as a setup failure rather than as a confusing assertion error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .test_users import TEST_USERS, make_member_headers

PROGRAM_OPS = TEST_USERS["program_ops"]
SPONSOR_BANK_OPS = TEST_USERS["sponsor_bank_ops"]
DISPUTES_AGENT = TEST_USERS["disputes_agent"]

# Settlement dates for seeded qualifying deposits: weekly spacing keeps the
# same-originator in-flight buffer clear, and every date settles at the
# default clock.
SEED_SETTLEMENT_DATES = [
    "2026-08-05T00:00:00Z",
    "2026-08-12T00:00:00Z",
    "2026-08-19T00:00:00Z",
    "2026-08-26T00:00:00Z",
    "2026-08-06T00:00:00Z",
    "2026-08-13T00:00:00Z",
]


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), PROGRAM_OPS))


def create_member(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_member(f.member_payload(**overrides), PROGRAM_OPS))


def get_member(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_member(member_id, PROGRAM_OPS))


def open_account(api: ApiClient, member_id: str, account_type: str = "SPENDING") -> Dict[str, Any]:
    return get_success_data(
        api.create_account(member_id, f.account_payload(account_type=account_type), SPONSOR_BANK_OPS)
    )


def get_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_account(account_id, PROGRAM_OPS))


def register_deposit(api: ApiClient, account_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_deposit(account_id, f.deposit_payload(**overrides), SPONSOR_BANK_OPS)
    )


def settle_deposit(api: ApiClient, deposit_id: str) -> Dict[str, Any]:
    return get_success_data(api.settle_deposit(deposit_id, {}, SPONSOR_BANK_OPS))


def post_early(api: ApiClient, deposit_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_early(deposit_id, {}, PROGRAM_OPS))


def return_deposit(api: ApiClient, deposit_id: str, return_code: str = "R01_INSUFFICIENT") -> Dict[str, Any]:
    return get_success_data(
        api.return_deposit(deposit_id, f.deposit_return_payload(return_code=return_code), SPONSOR_BANK_OPS)
    )


def evaluate(api: ApiClient, member_id: str, mode: str = "BATCH") -> Dict[str, Any]:
    """Run an eligibility evaluation with a freshly read member version."""
    member = get_member(api, member_id)
    return get_success_data(
        api.create_eligibility_evaluation(
            member_id,
            f.evaluation_payload(member["version"], evaluation_mode=mode),
            PROGRAM_OPS,
        )
    )


def record_abuse_event(
    api: ApiClient, member_id: str, event_type: str, evidence_note: Optional[str] = None
) -> Dict[str, Any]:
    """Record an abuse event with a freshly read member version."""
    member = get_member(api, member_id)
    payload: Dict[str, Any] = {"event_type": event_type}
    if evidence_note is not None:
        payload["evidence_note"] = evidence_note
    return get_success_data(
        api.create_abuse_event(
            member_id,
            f.abuse_event_payload(member["version"], **payload),
            PROGRAM_OPS,
        )
    )


def draw_advance(
    api: ApiClient,
    account_id: str,
    member_id: str,
    amount_cents: int,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Draw a cushion advance as the owning member with a fresh account version."""
    account = get_account(api, account_id)
    overrides: Dict[str, Any] = {"amount_cents": amount_cents}
    if idempotency_key is not None:
        overrides["idempotency_key"] = idempotency_key
    return get_success_data(
        api.create_advance(
            account_id,
            f.advance_payload(account["version"], **overrides),
            make_member_headers(member_id),
        )
    )


def spend(
    api: ApiClient, account_id: str, member_id: str, amount_cents: int, merchant_ref: str = "store-1"
) -> Dict[str, Any]:
    """Place a debit as the owning member with a fresh account version."""
    account = get_account(api, account_id)
    return get_success_data(
        api.create_debit(
            account_id,
            f.debit_payload(account["version"], amount_cents=amount_cents, merchant_ref=merchant_ref),
            make_member_headers(member_id),
        )
    )


def list_advances(api: ApiClient, account_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_advances(account_id, PROGRAM_OPS, params=params))
    return data


def list_allocations_for_advance(api: ApiClient, advance_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api.list_advance_repayment_allocations(advance_id, PROGRAM_OPS)
    )
    return data


def list_allocations_for_deposit(api: ApiClient, deposit_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api.list_deposit_repayment_allocations(deposit_id, PROGRAM_OPS)
    )
    return data


def list_ledger_entries(api: ApiClient, account_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api.list_account_ledger_entries(account_id, PROGRAM_OPS, params=params)
    )
    return data


def list_early_postings(api: ApiClient, deposit_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_deposit_early_postings(deposit_id, PROGRAM_OPS))
    return data


def list_returns(api: ApiClient, deposit_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_deposit_returns(deposit_id, PROGRAM_OPS))
    return data


def list_limit_adjustments(api: ApiClient, member_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_limit_adjustments(member_id, PROGRAM_OPS))
    return data


def list_profiles(api: ApiClient, member_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_eligibility_profiles(member_id, PROGRAM_OPS, params=params))
    return data


def setup_eligible_member(
    api: ApiClient,
    external_ref: str,
    enrolled_at: str = "2025-09-01T00:00:00Z",
    num_deposits: int = 2,
    deposit_amount_cents: int = 10000,
    settlement_dates: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Member + SPENDING account + N settled qualifying payroll deposits + one
    BATCH evaluation. With the defaults (two deposits, one year of tenure) the
    member lands ELIGIBLE with a 2000-cent limit.

    ``settlement_dates`` overrides the per-deposit settlement dates; successive
    groups of four deposits rotate the originator so the same-originator
    in-flight buffer never bites even at tight spacing (every deposit is
    settled immediately after registration anyway).

    Returns a dict with the member, the account, the settled deposits, and
    the evaluation profile.
    """
    member = create_member(api, external_ref=external_ref, enrolled_at=enrolled_at)
    account = open_account(api, member["id"])
    dates = settlement_dates or SEED_SETTLEMENT_DATES
    deposits = []
    for i in range(num_deposits):
        originator = f"EMP-{external_ref}-{chr(ord('A') + i // 4)}"
        dep = register_deposit(
            api,
            account["id"],
            originator_id=originator,
            originator_type="PAYROLL",
            amount_cents=deposit_amount_cents,
            settlement_date=dates[i],
        )
        settle_deposit(api, dep["id"])
        deposits.append(dep)
    profile = evaluate(api, member["id"], mode="BATCH")
    return {"member": member, "account": account, "deposits": deposits, "profile": profile}


def repay_with_qualifying_deposit(
    api: ApiClient,
    account_id: str,
    originator_id: str,
    amount_cents: int = 10000,
    settlement_date: str = "2026-09-01T00:00:00Z",
    trace_suffix: str = "repay",
) -> Dict[str, Any]:
    """Register and immediately settle a deposit, returning the settled deposit.

    The settle runs automatic repayment against the account's open advances.
    """
    dep = register_deposit(
        api,
        account_id,
        originator_id=originator_id,
        amount_cents=amount_cents,
        settlement_date=settlement_date,
        trace_id=f"{originator_id}-{trace_suffix}",
    )
    settle_deposit(api, dep["id"])
    return dep

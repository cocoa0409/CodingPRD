"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server against an empty database
before each test.  Setup calls use the lenient `get_success_data` validator so
a broken precondition surfaces as a clear "Setup step failed".
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import plus_days
from .constants import DEFAULT_LOGICAL_CLOCK_UTC
from .factories import (
    access_review_payload,
    adjudicate_referral_payload,
    create_account_link_payload,
    create_account_payload,
    create_bsa_referral_payload,
    create_charge_off_payload,
    create_customer_payload,
    create_deposit_item_payload,
    create_fraud_case_payload,
    create_funding_source_payload,
    create_override_review_payload,
    create_subpoena_payload,
    decide_review_payload,
    disposition_payload,
    recovery_posting_payload,
    set_clock_payload,
    settle_payload,
    verification_attempt_payload,
)
from .test_users import TEST_USERS, make_account_holder_headers

OPS = TEST_USERS["ops_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
SUPERVISOR_2 = TEST_USERS["supervisor_2_headers"]
BSA = TEST_USERS["bsa_officer_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
COUNSEL_2 = TEST_USERS["counsel_2_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> str:
    """Move the logical clock and return its reported new value."""
    data = get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), OPS))
    return data["current_utc"]


def new_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), OPS)
    )


def new_account(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_account(create_account_payload(customer_id, **overrides), OPS)
    )


def declare_funding_source(account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_funding_source(
            account_id, create_funding_source_payload(**overrides), OPS
        )
    )


def submit_verification(funding_source_id: str, micro_deposit_cents: int) -> dict:
    return get_success_data(
        api_client.submit_verification_attempt(
            funding_source_id, verification_attempt_payload(micro_deposit_cents), OPS
        )
    )


def read_account(account_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or ANALYST))


def account_version(account_id: str) -> int:
    return read_account(account_id)["version"]


def read_check_hold(hold_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_check_hold(hold_id, headers or ANALYST))


def read_review(review_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_override_review(review_id, headers or ANALYST))


def read_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_fraud_case(case_id, headers or ANALYST))


def read_charge_off(charge_off_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_charge_off(charge_off_id, headers or ANALYST))


def read_subpoena(subpoena_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_subpoena(subpoena_id, headers or COUNSEL))


def read_customer(customer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ANALYST))


# ---------------------------------------------------------------------------
# Tier 1 — state progression: an account funded all the way to ACTIVE
# ---------------------------------------------------------------------------
def fund_and_activate(account_id: str) -> dict:
    """Declare a funding source, echo the minted secret, and return the source.

    Reaching VERIFIED drives the owning account PENDING_FUNDING -> ACTIVE.
    """
    source = declare_funding_source(account_id)
    return submit_verification(source["id"], source["micro_deposit_cents"])


def create_active_account(**account_overrides) -> dict:
    """One Customer plus one DepositAccount funded through to ACTIVE.

    Customer-side inputs are passed through `customer` keyword overrides:
    kyc_tier, watchlist_hit, tin_last4, legal_name.
    """
    customer_overrides = {
        key: account_overrides.pop(key)
        for key in ("kyc_tier", "watchlist_hit", "tin_last4", "legal_name")
        if key in account_overrides
    }
    customer = new_customer(**customer_overrides)
    account = new_account(customer["id"], **account_overrides)
    funding_source = fund_and_activate(account["id"])
    return {
        "customer": customer,
        "account": read_account(account["id"]),
        "funding_source": funding_source,
        "account_id": account["id"],
        "customer_id": customer["id"],
        "holder_headers": make_account_holder_headers(customer["id"]),
    }


def create_pending_funding_account(**account_overrides) -> dict:
    """One Customer plus one DepositAccount left in PENDING_FUNDING."""
    customer_overrides = {
        key: account_overrides.pop(key)
        for key in ("kyc_tier", "watchlist_hit", "tin_last4", "legal_name")
        if key in account_overrides
    }
    customer = new_customer(**customer_overrides)
    account = new_account(customer["id"], **account_overrides)
    return {
        "customer": customer,
        "account": account,
        "account_id": account["id"],
        "customer_id": customer["id"],
        "holder_headers": make_account_holder_headers(customer["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2 — deposits and the holds they mint
# ---------------------------------------------------------------------------
def take_deposit(account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_deposit_item(
            account_id, create_deposit_item_payload(**overrides), OPS
        )
    )


def settle_item(item_id: str, outcome: str, return_reason: str = None) -> dict:
    return get_success_data(
        api_client.settle_deposit_item(item_id, settle_payload(outcome, return_reason), OPS)
    )


def holds_for_item(item_id: str, headers=None) -> list:
    return get_success_data(api_client.list_item_holds(item_id, headers or ANALYST))


def first_hold(item_id: str, headers=None) -> dict:
    rows = holds_for_item(item_id, headers)
    assert rows, f"Setup step failed: deposited item {item_id} minted no check hold"
    return rows[0]


def setup_account_with_hold(amount_cents: int = 30000, **account_overrides) -> dict:
    """Active account + one CHECK deposit + the ACTIVE hold it minted.

    With the default 30000-cent item the split is 22500 immediate / 7500 held.
    """
    scenario = create_active_account(**account_overrides)
    item = take_deposit(scenario["account_id"], amount_cents=amount_cents)
    hold = first_hold(item["id"])
    scenario.update(
        {
            "item": item,
            "item_id": item["id"],
            "hold": hold,
            "hold_id": hold["id"],
            "hold_version": hold["version"],
            "account": read_account(scenario["account_id"]),
        }
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — early-release review lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_override_review(hold_id: str, expected_version: int, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_override_review(
            hold_id, create_override_review_payload(expected_version, **overrides), headers or ANALYST
        )
    )


def submit_override_review(review_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.submit_override_review(review_id, headers or ANALYST)
    )


def decide_override_review(review_id: str, decision: str, note: str = None, headers=None) -> dict:
    return get_success_data(
        api_client.decide_override_review(
            review_id, decide_review_payload(decision, note), headers or SUPERVISOR
        )
    )


def execute_override_review(review_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.execute_override_review(review_id, headers or SUPERVISOR)
    )


def setup_draft_review(amount_cents: int = 30000, requested_release_cents: int = 7500,
                       **account_overrides) -> dict:
    """Active account + hold + a DRAFT early-release review prepared by analyst-1."""
    scenario = setup_account_with_hold(amount_cents=amount_cents, **account_overrides)
    review = open_override_review(
        scenario["hold_id"],
        scenario["hold_version"],
        requested_release_cents=requested_release_cents,
    )
    scenario.update({"review": review, "review_id": review["id"]})
    return scenario


def setup_submitted_review(amount_cents: int = 30000, requested_release_cents: int = 7500,
                           **account_overrides) -> dict:
    """As setup_draft_review, then submitted to the supervisor queue."""
    scenario = setup_draft_review(
        amount_cents=amount_cents,
        requested_release_cents=requested_release_cents,
        **account_overrides,
    )
    scenario["review"] = submit_override_review(scenario["review_id"])
    return scenario


def setup_approved_review(amount_cents: int = 30000, requested_release_cents: int = 7500,
                          **account_overrides) -> dict:
    """As setup_submitted_review, then APPROVED by sup-1 (analyst-1 prepared it)."""
    scenario = setup_submitted_review(
        amount_cents=amount_cents,
        requested_release_cents=requested_release_cents,
        **account_overrides,
    )
    scenario["review"] = decide_override_review(
        scenario["review_id"], "APPROVE", "Within delegated authority"
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — fraud case lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_case(account_id: str, case_type: str = "MULE", headers=None) -> dict:
    return get_success_data(
        api_client.create_fraud_case(
            create_fraud_case_payload(account_id, case_type), headers or ANALYST
        )
    )


def advance_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.advance_fraud_case(case_id, headers or ANALYST))


def dispose_case(case_id: str, decision: str, note: str = None, headers=None) -> dict:
    return get_success_data(
        api_client.dispose_fraud_case(
            case_id, disposition_payload(decision, note), headers or SUPERVISOR
        )
    )


def close_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.close_fraud_case(case_id, headers or SUPERVISOR))


def setup_investigating_case(account_id: str, case_type: str = "MULE") -> dict:
    case = open_case(account_id, case_type)
    return advance_case(case["id"])


def setup_substantiated_case(account_id: str, case_type: str = "MULE",
                             note: str = "Third-party funds moved through the account") -> dict:
    case = open_case(account_id, case_type)
    advance_case(case["id"])
    return dispose_case(case["id"], "SUBSTANTIATE", note)


# ---------------------------------------------------------------------------
# Tier 4b — BSA referral lifecycle shortcuts
# ---------------------------------------------------------------------------
def draft_referral(case_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_bsa_referral(
            case_id, create_bsa_referral_payload(**overrides), headers or ANALYST
        )
    )


def submit_referral(referral_id: str, headers=None) -> dict:
    return get_success_data(api_client.submit_bsa_referral(referral_id, headers or ANALYST))


def adjudicate_referral(referral_id: str, decision: str, return_reason: str = None,
                        headers=None) -> dict:
    return get_success_data(
        api_client.adjudicate_bsa_referral(
            referral_id, adjudicate_referral_payload(decision, return_reason), headers or BSA
        )
    )


def setup_accepted_referral(case_id: str, **overrides) -> dict:
    referral = draft_referral(case_id, **overrides)
    submit_referral(referral["id"])
    return adjudicate_referral(referral["id"], "ACCEPT")


# ---------------------------------------------------------------------------
# Tier 5 — terminal states: an account driven all the way to CLOSED
# ---------------------------------------------------------------------------
def setup_closed_account(**account_overrides) -> dict:
    """Active account -> MULE case -> SUBSTANTIATED -> accepted referral -> closed.

    Leaves the DepositAccount in lifecycle_status CLOSED, which is the
    precondition for booking a charge-off against it.
    """
    scenario = create_active_account(**account_overrides)
    case = setup_substantiated_case(scenario["account_id"], "MULE", "Mule activity confirmed")
    referral = setup_accepted_referral(case["id"])
    closed_case = close_case(case["id"])
    scenario.update(
        {
            "case": closed_case,
            "case_id": case["id"],
            "referral": referral,
            "referral_id": referral["id"],
            "account": read_account(scenario["account_id"]),
        }
    )
    return scenario


def propose_charge_off(account_id: str, expected_version: int = None, headers=None,
                       **overrides) -> dict:
    version = expected_version if expected_version is not None else account_version(account_id)
    return get_success_data(
        api_client.create_charge_off(
            account_id, create_charge_off_payload(version, **overrides), headers or ANALYST
        )
    )


def approve_charge_off(charge_off_id: str, headers=None) -> dict:
    return get_success_data(api_client.approve_charge_off(charge_off_id, headers or SUPERVISOR))


def book_charge_off(charge_off_id: str, headers=None) -> dict:
    return get_success_data(api_client.book_charge_off(charge_off_id, headers or OPS))


def post_recovery(charge_off_id: str, amount_cents: int, headers=None) -> dict:
    return get_success_data(
        api_client.create_recovery_posting(
            charge_off_id, recovery_posting_payload(amount_cents), headers or OPS
        )
    )


def setup_approved_charge_off(gross_loss_cents: int = 120000,
                              collateral_offset_cents: int = 20000,
                              **account_overrides) -> dict:
    """Closed account carrying an APPROVED ChargeOff, ready to be booked."""
    scenario = setup_closed_account(**account_overrides)
    charge_off = propose_charge_off(
        scenario["account_id"],
        gross_loss_cents=gross_loss_cents,
        collateral_offset_cents=collateral_offset_cents,
    )
    scenario.update(
        {
            "charge_off": approve_charge_off(charge_off["id"]),
            "charge_off_id": charge_off["id"],
        }
    )
    return scenario


def setup_booked_charge_off(gross_loss_cents: int = 120000,
                            collateral_offset_cents: int = 20000,
                            **account_overrides) -> dict:
    """As setup_approved_charge_off, then booked against the closed account."""
    scenario = setup_approved_charge_off(
        gross_loss_cents=gross_loss_cents,
        collateral_offset_cents=collateral_offset_cents,
        **account_overrides,
    )
    scenario["charge_off"] = book_charge_off(scenario["charge_off_id"])
    scenario["account"] = read_account(scenario["account_id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 6 — association links, access reviews, kiting graphs, subpoenas
# ---------------------------------------------------------------------------
def link_accounts(from_account_id: str, to_account_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_account_link(
            create_account_link_payload(from_account_id, to_account_id, **overrides),
            headers or ANALYST,
        )
    )


def record_access_review(account_id: str, indicator_codes, reset_posture: bool = None,
                         headers=None) -> dict:
    return get_success_data(
        api_client.record_access_review(
            account_id, access_review_payload(indicator_codes, reset_posture), headers or ANALYST
        )
    )


def setup_two_account_kiting_ring(item_amount_cents: int = 30000, item_count: int = 4) -> dict:
    """Two ACTIVE accounts under one customer, circulating on-us CHECK items.

    Items alternate direction, starting with one deposited into B drawn on A,
    so with an even `item_count` each direction carries `item_count / 2` items
    and the pair forms a two-account directed cycle.
    """
    customer = new_customer(kyc_tier="TIER_2", watchlist_hit=False)
    account_a = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    fund_and_activate(account_a["id"])
    account_b = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    fund_and_activate(account_b["id"])

    items = []
    for index in range(item_count):
        into_b = index % 2 == 0
        target = account_b["id"] if into_b else account_a["id"]
        drawee = account_a["id"] if into_b else account_b["id"]
        items.append(
            take_deposit(
                target,
                item_type="CHECK",
                amount_cents=item_amount_cents,
                drawee_account_id=drawee,
            )
        )
    return {
        "customer": customer,
        "customer_id": customer["id"],
        "account_a": account_a,
        "account_a_id": account_a["id"],
        "account_b": account_b,
        "account_b_id": account_b["id"],
        "items": items,
    }


def new_subpoena(customer_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_subpoena(
            customer_id, create_subpoena_payload(**overrides), headers or COUNSEL
        )
    )


def legal_review_subpoena(subpoena_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.legal_review_subpoena(subpoena_id, headers or COUNSEL)
    )


def setup_subpoena_under_review(customer_id: str, **overrides) -> dict:
    subpoena = new_subpoena(customer_id, **overrides)
    return legal_review_subpoena(subpoena["id"])


__all__ = [
    "OPS", "ANALYST", "SUPERVISOR", "SUPERVISOR_2", "BSA", "COUNSEL", "COUNSEL_2",
    "DEFAULT_LOGICAL_CLOCK_UTC", "plus_days",
    "set_clock", "new_customer", "new_account", "declare_funding_source",
    "submit_verification", "read_account", "account_version", "read_check_hold",
    "read_review", "read_case", "read_charge_off", "read_subpoena", "read_customer",
    "fund_and_activate", "create_active_account", "create_pending_funding_account",
    "take_deposit", "settle_item", "holds_for_item", "first_hold",
    "setup_account_with_hold", "open_override_review", "submit_override_review",
    "decide_override_review", "execute_override_review", "setup_draft_review",
    "setup_submitted_review", "setup_approved_review", "open_case", "advance_case",
    "dispose_case", "close_case", "setup_investigating_case", "setup_substantiated_case",
    "draft_referral", "submit_referral", "adjudicate_referral", "setup_accepted_referral",
    "setup_closed_account", "propose_charge_off", "approve_charge_off", "book_charge_off",
    "post_recovery", "setup_approved_charge_off", "setup_booked_charge_off",
    "link_accounts", "record_access_review", "setup_two_account_kiting_ring",
    "new_subpoena", "legal_review_subpoena", "setup_subpoena_under_review",
]

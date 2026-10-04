"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is restarted before each individual test. Setup
uses the lenient ``get_success_data`` validator so a broken precondition
surfaces as a clear "Setup failed" error rather than a confusing assertion
failure downstream.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_developer_account_payload,
    create_key_batch_payload,
    create_purchase_payload,
    create_refund_request_payload,
    create_review_payload,
    create_title_payload,
    create_user_account_payload,
    create_workshop_item_payload,
)
from .test_users import TEST_USERS, make_developer_headers, make_user_headers

OPS = TEST_USERS["platform_ops_headers"]
REVIEWER = TEST_USERS["store_reviewer_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


def _uniq_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@players.example"


# --- clock ---

def set_clock(to_iso8601: str = CLOCK_DEFAULT) -> dict:
    """Set the logical clock. Call first in tests that need temporal control."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


# --- Tier 1: single-entity creation ---

def create_developer(**overrides) -> dict:
    """Register a PENDING developer account. Returns the account."""
    overrides.setdefault("company_name", "Test Studio")
    overrides.setdefault("contact_email", _uniq_email("dev"))
    return get_success_data(
        api_client.create_developer_account(create_developer_account_payload(**overrides), OPS)
    )


def create_active_developer(**overrides) -> dict:
    """Register a developer, record fee + bank details, and activate it."""
    dev = create_developer(**overrides)
    get_success_data(
        api_client.submit_payment_info(
            dev["id"], {"pay_fee": True, "submit_bank_details": True},
            make_developer_headers(dev["id"]),
        )
    )
    return get_success_data(api_client.activate_developer(dev["id"], OPS))


def create_user(**overrides) -> dict:
    """Register an ACTIVE user account. Returns the account."""
    overrides.setdefault("email", _uniq_email("user"))
    return get_success_data(
        api_client.create_user_account(create_user_account_payload(**overrides), OPS)
    )


def create_title(developer: dict, **overrides) -> dict:
    """Register a DRAFT title owned by the given developer account."""
    return get_success_data(
        api_client.create_title(
            create_title_payload(developer["id"], **overrides),
            make_developer_headers(developer["id"]),
        )
    )


# --- Tier 2/3: title lifecycle shortcuts ---

def submit_and_get_review(title: dict, developer: dict) -> dict:
    """Submit a title for store-page review; returns the SUBMITTED review."""
    get_success_data(
        api_client.submit_title_review(title["id"], make_developer_headers(developer["id"]))
    )
    data, _meta = _list_store_page_reviews(title["id"], developer)
    return sorted(data, key=lambda r: r["submission_seq"])[-1]


def _list_store_page_reviews(title_id: str, developer: dict):
    resp = api_client.list_title_store_page_reviews(
        title_id, make_developer_headers(developer["id"])
    )
    body = resp.json()
    return body["data"], body["meta"]


def create_approved_title(developer: dict = None, **title_overrides):
    """Active developer + title approved by the store-page reviewer.
    Returns (developer, title) with the title in APPROVED."""
    if developer is None:
        developer = create_active_developer()
    title = create_title(developer, **title_overrides)
    review = submit_and_get_review(title, developer)
    get_success_data(api_client.approve_store_page_review(review["id"], REVIEWER))
    title = get_success_data(
        api_client.get_title(title["id"], make_developer_headers(developer["id"]))
    )
    return developer, title


def create_released_title(developer: dict = None, **title_overrides):
    """Active developer + title walked all the way to RELEASED.
    Returns (developer, title)."""
    developer, title = create_approved_title(developer, **title_overrides)
    title = get_success_data(
        api_client.release_now(title["id"], make_developer_headers(developer["id"]))
    )
    return developer, title


# --- Tier 4: buyers, purchases, playtime ---

def create_buyer() -> dict:
    return create_user()


def buy_title(user: dict, title: dict, currency: str = "USD") -> dict:
    """Purchase a title. Returns the COMPLETED purchase."""
    return get_success_data(
        api_client.create_purchase(
            create_purchase_payload(user["id"], title["id"], currency=currency),
            make_user_headers(user["id"]),
        )
    )


def record_playtime(purchase: dict, user: dict, minutes: int) -> dict:
    return get_success_data(
        api_client.record_playtime(
            purchase["id"], {"minutes": minutes}, make_user_headers(user["id"])
        )
    )


def read_title(title_id: str, developer: dict) -> dict:
    """Read a title as its owning developer (computed fields resolved on read)."""
    return get_success_data(
        api_client.get_title(title_id, make_developer_headers(developer["id"]))
    )


def create_n_buyers_with_purchases(title: dict, n: int):
    """Create n user accounts, each with a completed USD purchase of the title.
    Returns (users, purchases)."""
    users, purchases = [], []
    for _ in range(n):
        user = create_buyer()
        purchases.append(buy_title(user, title))
        users.append(user)
    return users, purchases


def post_review(title_id: str, user: dict, developer: dict, is_positive: bool,
                body: str = "review") -> dict:
    """Read the title's current version, then post a review carrying it (OCC)."""
    version = read_title(title_id, developer)["version"]
    return get_success_data(
        api_client.create_review(
            create_review_payload(
                title_id, user["id"], version, is_positive=is_positive, body=body
            ),
            make_user_headers(user["id"]),
        )
    )


# --- key batches ---

def create_and_approve_key_batch(title: dict, developer: dict,
                                 requested_quantity: int = 10,
                                 free_keys_in_batch: int = 0) -> dict:
    """Request a key batch on a RELEASED title and approve it (mints keys)."""
    batch = get_success_data(
        api_client.create_key_batch(
            create_key_batch_payload(
                title["id"],
                requested_quantity=requested_quantity,
                free_keys_in_batch=free_keys_in_batch,
            ),
            make_developer_headers(developer["id"]),
        )
    )
    return get_success_data(api_client.approve_key_batch(batch["id"], OPS))


def list_batch_keys(batch_id: str, developer: dict) -> list:
    data, _meta = _list_keys(batch_id, developer)
    return data


def _list_keys(batch_id: str, developer: dict):
    resp = api_client.list_batch_keys(batch_id, make_developer_headers(developer["id"]))
    body = resp.json()
    return body["data"], body["meta"]


# --- workshop ---

def create_published_workshop_item(title: dict, creator: dict,
                                   price_cents: int = 500,
                                   creator_share_bps: int = 2500) -> dict:
    """Create a workshop item and publish it (host title must be RELEASED)."""
    item = get_success_data(
        api_client.create_workshop_item(
            create_workshop_item_payload(
                title["id"], creator["id"],
                price_cents=price_cents, creator_share_bps=creator_share_bps,
            ),
            make_user_headers(creator["id"]),
        )
    )
    return get_success_data(
        api_client.publish_workshop_item(item["id"], make_user_headers(creator["id"]))
    )


# --- refunds ---

def request_refund(purchase: dict, user: dict, reason: str = "changed my mind",
                   amount_cents=None) -> dict:
    """Create a refund request. Returns the RefundRequest (any status)."""
    payload = create_refund_request_payload(purchase["id"], reason=reason)
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    return get_success_data(
        api_client.create_refund_request(payload, make_user_headers(user["id"]))
    )


def list_title_bomb_windows(title_id: str, developer: dict) -> list:
    resp = api_client.list_title_review_bomb_windows(
        title_id, make_developer_headers(developer["id"])
    )
    return resp.json()["data"]

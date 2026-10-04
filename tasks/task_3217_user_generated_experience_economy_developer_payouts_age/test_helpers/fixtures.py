"""Composite setup helpers for the experience-economy domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z unless moved).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .constants import (
    ENGAGEMENT_RATE_PER_HOUR,
    expected_credited_robux,
)
from .factories import (
    create_account_termination_payload,
    create_chat_message_payload,
    create_currency_purchase_order_payload,
    create_devex_request_payload,
    create_engagement_snapshot_payload,
    create_experience_payload,
    create_identity_verification_payload,
    create_limited_item_payload,
    create_marketplace_item_payload,
    create_parental_controls_payload,
    create_purchase_order_payload,
    create_report_payload,
    create_resale_listing_payload,
    create_tax_document_payload,
    create_user_payload,
)
from .test_users import (
    TEST_USERS,
    make_creator_headers,
    make_safety_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
MODERATOR = TEST_USERS["moderator_headers"]
SAFETY = TEST_USERS["safety_agent_headers"]
OFFICER_1 = TEST_USERS["finance_officer_headers"]
OFFICER_2 = TEST_USERS["finance_officer_2_headers"]

CLOCK_START = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: basic entities
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_user(**overrides):
    """Register a user as Anonymous. Returns the User dict."""
    return get_success_data(api.create_user(create_user_payload(**overrides), ANON))


def create_adult_user(**overrides):
    overrides.setdefault("date_of_birth", "1990-01-01")
    return create_user(**overrides)


def create_child_user(parent_id=None, **overrides):
    """Age 6 at the default 2026-09-01 clock. Optionally parent-linked."""
    overrides.setdefault("date_of_birth", "2020-01-01")
    if parent_id is not None:
        overrides.setdefault("parent_user_id", parent_id)
    return create_user(**overrides)


def get_user(user_id):
    return get_success_data(api.get_user(user_id, ADMIN))


def creator_headers_for(user):
    return make_creator_headers(user["id"])


# ---------------------------------------------------------------------------
# Tier 1: currency funding
# ---------------------------------------------------------------------------

def fund_user(user_id, fiat_amount_cents, idempotency_key=None):
    """Create + confirm a currency purchase. Returns (order, credited_robux)."""
    payload = create_currency_purchase_order_payload(fiat_amount_cents=fiat_amount_cents)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    order = get_success_data(
        api.create_currency_purchase_order(payload, make_creator_headers(user_id))
    )
    completed = get_success_data(
        api.confirm_currency_payment(order["id"], make_creator_headers(user_id))
    )
    return completed, completed["credited_robux"]


# ---------------------------------------------------------------------------
# Tier 2: experiences through moderation
# ---------------------------------------------------------------------------

def create_experience(user_id, **overrides):
    return get_success_data(
        api.create_experience(create_experience_payload(**overrides), make_creator_headers(user_id))
    )


def find_experience_submission(experience_id):
    """Locate the QUEUED moderation submission spawned by submit-for-review."""
    resp = api.list_moderation_submissions(MODERATOR, params={"subject_type": "EXPERIENCE"})
    subs, _meta = validate_paginated(resp)
    matches = [s for s in subs if s["subject_id"] == experience_id]
    assert matches, f"no moderation submission found for experience {experience_id}"
    return matches[-1]


def publish_experience(user_id, experience_id, score=0.05):
    """Submit for review and auto-approve via score injection. Returns (experience, submission)."""
    get_success_data(
        api.submit_experience_for_review(experience_id, make_creator_headers(user_id))
    )
    sub = find_experience_submission(experience_id)
    get_success_data(api.inject_moderation_score(sub["id"], score, ADMIN))
    exp = get_success_data(api.get_experience(experience_id, ADMIN))
    return exp, sub


def create_published_experience(user_id, score=0.05, **overrides):
    """DRAFT -> PENDING_REVIEW -> auto-approved PUBLISHED. Returns (experience, submission)."""
    exp = create_experience(user_id, **overrides)
    return publish_experience(user_id, exp["id"], score=score)


def submit_experience_queued(user_id, experience_id):
    """Submit for review but leave the submission QUEUED (no score injection)."""
    get_success_data(
        api.submit_experience_for_review(experience_id, make_creator_headers(user_id))
    )
    return find_experience_submission(experience_id)


# ---------------------------------------------------------------------------
# Tier 2: marketplace items through moderation
# ---------------------------------------------------------------------------

def create_marketplace_item(creator_id, **overrides):
    return get_success_data(
        api.create_marketplace_item(
            create_marketplace_item_payload(**overrides), make_creator_headers(creator_id)
        )
    )


def create_limited_item(creator_id, **overrides):
    return get_success_data(
        api.create_marketplace_item(
            create_limited_item_payload(**overrides), make_creator_headers(creator_id)
        )
    )


def find_asset_submission(item_id):
    resp = api.list_moderation_submissions(MODERATOR, params={"subject_type": "ASSET"})
    subs, _meta = validate_paginated(resp)
    matches = [s for s in subs if s["subject_id"] == item_id]
    assert matches, f"no moderation submission found for item {item_id}"
    return matches[-1]


def create_on_sale_item(creator_id, score=0.05, **overrides):
    """DRAFT -> PENDING_MODERATION -> auto-approved ON_SALE. Returns (item, submission)."""
    item = get_success_data(
        api.create_marketplace_item(
            create_marketplace_item_payload(**overrides), make_creator_headers(creator_id)
        )
    )
    get_success_data(api.submit_marketplace_item(item["id"], make_creator_headers(creator_id)))
    sub = find_asset_submission(item["id"])
    get_success_data(api.inject_moderation_score(sub["id"], score, ADMIN))
    item = get_success_data(api.get_marketplace_item(item["id"], ADMIN))
    assert item["status"] == "ON_SALE", f"item not ON_SALE after approval: {item['status']}"
    return item, sub


def create_on_sale_limited_item(creator_id, score=0.05, **overrides):
    """Same as create_on_sale_item but a LIMITED_* kind. Returns (item, submission)."""
    item = get_success_data(
        api.create_marketplace_item(
            create_limited_item_payload(**overrides), make_creator_headers(creator_id)
        )
    )
    get_success_data(api.submit_marketplace_item(item["id"], make_creator_headers(creator_id)))
    sub = find_asset_submission(item["id"])
    get_success_data(api.inject_moderation_score(sub["id"], score, ADMIN))
    item = get_success_data(api.get_marketplace_item(item["id"], ADMIN))
    assert item["status"] == "ON_SALE", f"item not ON_SALE after approval: {item['status']}"
    return item, sub


# ---------------------------------------------------------------------------
# Tier 3: purchases
# ---------------------------------------------------------------------------

def buy_item(buyer_id, item_id, price_robux, idempotency_key=None):
    """Create + confirm a MARKETPLACE_ITEM purchase. Returns the COMPLETED order."""
    payload = create_purchase_order_payload("MARKETPLACE_ITEM", item_id, price_robux)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    po = get_success_data(api.create_purchase_order(payload, make_creator_headers(buyer_id)))
    return get_success_data(api.confirm_purchase_order(po["id"], make_creator_headers(buyer_id)))


# ---------------------------------------------------------------------------
# Tier 3: resale listings
# ---------------------------------------------------------------------------

def list_for_resale(seller_id, item_id, ask_price_robux):
    """Create an ACTIVE resale listing with a fresh expected_item_version."""
    item = get_success_data(api.get_marketplace_item(item_id, ADMIN))
    payload = create_resale_listing_payload(item_id, ask_price_robux, item["version"])
    return get_success_data(api.create_resale_listing(payload, make_creator_headers(seller_id)))


# ---------------------------------------------------------------------------
# Tier 3: parental controls
# ---------------------------------------------------------------------------

def setup_parent_child(spend_limit=None, chat_mode=None, child_dob="2020-01-01"):
    """ADULT parent + linked CHILD + ParentalControls row.

    Returns (parent, child, controls).
    """
    parent = create_adult_user()
    child = create_child_user(parent_id=parent["id"], date_of_birth=child_dob)
    parent_fresh = get_user(parent["id"])
    payload = create_parental_controls_payload(child["id"], parent_fresh["version"])
    if spend_limit is not None:
        payload["monthly_spend_limit_robux"] = spend_limit
    if chat_mode is not None:
        payload["chat_mode"] = chat_mode
    controls = get_success_data(
        api.set_parental_controls(parent["id"], payload, make_creator_headers(parent["id"]))
    )
    return parent, child, controls


# ---------------------------------------------------------------------------
# Tier 4: DevEx-eligible users (identity + tax + earned Robux + account age)
# ---------------------------------------------------------------------------

def setup_devex_eligible_user(target_earned_robux=30000, form_type="W9",
                              start_clock="2026-08-01T00:00:00Z",
                              end_clock="2026-09-01T00:00:00Z"):
    """Build a fully DevEx-eligible ADULT creator.

    earned_robux_lifetime is raised via a published experience's engagement
    payout (one snapshot sized to the target, then a monthly settlement), and
    the account is aged past thirty days by moving the logical clock.

    Returns the fresh User dict (read after the clock lands at end_clock).
    """
    set_clock(start_clock)
    user = create_adult_user()
    uid = user["id"]
    headers = make_creator_headers(uid)

    iv = get_success_data(
        api.create_identity_verification(uid, create_identity_verification_payload(), headers)
    )
    get_success_data(api.verify_identity(iv["id"], ADMIN))

    tax = get_success_data(
        api.create_tax_document(uid, create_tax_document_payload(form_type=form_type), headers)
    )
    get_success_data(api.accept_tax_document(tax["id"], ADMIN))

    exp, _sub = create_published_experience(uid)
    exp = get_success_data(api.get_experience(exp["id"], ADMIN))
    rate = ENGAGEMENT_RATE_PER_HOUR[exp["age_rating"]]
    minutes = -(-target_earned_robux // rate) * 60  # ceil(target/rate) hours in minutes
    get_success_data(
        api.post_engagement_snapshot(
            exp["id"], create_engagement_snapshot_payload("2026-08-15", minutes), ADMIN
        )
    )
    get_success_data(api.settle_monthly_engagement(ADMIN))

    set_clock(end_clock)
    return get_user(uid)


def submit_devex_request(user_id, requested_robux):
    """Submit a DevEx request with the caller's current user version. Returns the request."""
    fresh = get_user(user_id)
    payload = create_devex_request_payload(requested_robux, fresh["version"])
    return get_success_data(api.create_devex_request(payload, make_creator_headers(user_id)))


# ---------------------------------------------------------------------------
# Tier 5: chat + report pipeline
# ---------------------------------------------------------------------------

def send_chat(user_id, experience_id, body_raw=None):
    payload = create_chat_message_payload()
    if body_raw is not None:
        payload["body_raw"] = body_raw
    return get_success_data(
        api.send_chat_message(experience_id, payload, make_creator_headers(user_id))
    )


def report_message(reporter_id, message_id, reason_code="HARASSMENT"):
    return get_success_data(
        api.create_report(
            message_id, create_report_payload(reason_code=reason_code),
            make_creator_headers(reporter_id),
        )
    )


def triage_report(report_id, agent_id="sa-1"):
    return get_success_data(api.triage_report(report_id, make_safety_agent_headers(agent_id)))

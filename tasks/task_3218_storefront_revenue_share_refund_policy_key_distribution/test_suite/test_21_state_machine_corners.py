"""Breadth coverage for state-machine behaviours."""
from test_helpers import (
    api_client,
    buy_title,
    create_active_developer,
    create_and_approve_key_batch,
    create_approved_title,
    create_buyer,
    create_released_title,
    create_title,
    create_user,
    get_success_data,
    list_batch_keys,
    make_developer_headers,
    make_user_headers,
    read_title,
    record_playtime,
    request_refund,
    set_clock,
    submit_and_get_review,
    validate_error,
    validate_success,
    ApiErrorId,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]
REVIEWER = TEST_USERS["store_reviewer_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


def test_scheduled_release_fires_on_clock_sweep():
    """PRD §2.4: "Setting the clock has a sweeping side effect: every title in
    `RELEASE_SCHEDULED` whose `scheduled_release_at` is at or before the new
    logical time transitions to `RELEASED`, with `released_at` recorded as the
    scheduled instant rather than the sweep instant."

    Design: Corner/state_machines/scheduled_release_fires_on_clock_sweep
    """
    developer, title = create_approved_title()
    dev_headers = make_developer_headers(developer["id"])
    get_success_data(
        api_client.schedule_release(
            title["id"], {"release_at": "2026-09-15T00:00:00Z"}, dev_headers
        )
    )

    # One second before the boundary: still scheduled.
    set_clock("2026-09-14T23:59:59Z")
    before = read_title(title["id"], developer)
    assert before["status"] == "RELEASE_SCHEDULED"

    # Exactly at the scheduled instant (inclusive): released.
    set_clock("2026-09-15T00:00:00Z")
    after = read_title(title["id"], developer)
    assert after["status"] == "RELEASED"
    assert after["released_at"] == "2026-09-15T00:00:00.000Z"


def test_early_access_schedule_requires_disclosure():
    """PRD §3.2: "a title whose `early_access` flag is true may not be scheduled
    or released while its `early_access_disclosure_text` is still null, and the
    attempt is rejected with `ERR_MISSING_DISCLOSURE` (HTTP 422)."

    Design: Corner/state_machines/early_access_schedule_requires_disclosure
    """
    developer, title = create_approved_title(
        title_name="EA Game", early_access=True
    )
    dev_headers = make_developer_headers(developer["id"])

    res = api_client.schedule_release(
        title["id"], {"release_at": "2026-09-10T00:00:00Z"}, dev_headers
    )
    validate_error(res, ApiErrorId.ERR_MISSING_DISCLOSURE)

    # The failed schedule leaves the title APPROVED, so cancel-release has no
    # valid transition.
    res = api_client.cancel_release(title["id"], dev_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_schedule_release_in_past_rejected():
    """PRD §3.2: "Scheduling a release takes a `release_at` that must lie
    strictly after the current logical time — a `release_at` at or before now
    is rejected with `ERR_INVALID_SCHEDULE` (HTTP 422) — and moves the title to
    `RELEASE_SCHEDULED` with `scheduled_release_at` recorded."

    Design: Corner/state_machines/schedule_release_in_past_rejected
    """
    set_clock("2026-09-05T00:00:00Z")
    developer, title = create_approved_title()
    dev_headers = make_developer_headers(developer["id"])

    res = api_client.schedule_release(
        title["id"], {"release_at": "2026-09-05T00:00:00Z"}, dev_headers
    )
    validate_error(res, ApiErrorId.ERR_INVALID_SCHEDULE)

    unchanged = read_title(title["id"], developer)
    assert unchanged["status"] == "APPROVED"
    assert unchanged["scheduled_release_at"] is None


def test_terminal_states_lockdown():
    """PRD §3.5: "Denial takes a `decision_reason` from the payload and moves
    the request to `DENIED`."

    Design: Corner/state_machines/terminal_states_lockdown
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    dev_headers = make_developer_headers(developer["id"])
    buyer = create_buyer()
    purchase = buy_title(buyer, title)
    record_playtime(purchase, buyer, 200)

    rr = request_refund(purchase, buyer, reason="slow")
    assert rr["status"] == "REQUESTED"  # over the playtime limit -> manual queue
    denied = get_success_data(
        api_client.deny_refund_request(
            rr["id"], {"decision_reason": "played too much"}, TRUST
        )
    )
    assert denied["status"] == "DENIED"

    # A DENIED refund request cannot be approved afterwards.
    res = api_client.approve_refund_request(rr["id"], TRUST)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    # An APPROVED store-page review cannot be rejected afterwards.
    developer2 = create_active_developer()
    title2 = create_title(developer2)
    review = submit_and_get_review(title2, developer2)
    assert review["status"] == "SUBMITTED"
    get_success_data(api_client.approve_store_page_review(review["id"], REVIEWER))
    res = api_client.reject_store_page_review(
        review["id"], {"review_notes": "too late"}, REVIEWER
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    rr_read = validate_success(
        api_client.get_refund_request(rr["id"], make_user_headers(buyer["id"]))
    )
    assert rr_read["status"] == "DENIED"
    assert rr_read["decision_reason"] == "played too much"


def test_developer_terminate_revokes_unused_keys():
    """PRD §3.1: "Termination is the terminal act: from `PENDING`, `ACTIVE`, or
    `SUSPENDED` an account moves to `TERMINATED`, every non-`DELISTED` title of
    the developer cascades to `DELISTED`, and every `UNUSED` key in every batch
    the developer owns cascades to `REVOKED`."

    Design: Corner/state_machines/developer_terminate_revokes_unused_keys
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    batch = create_and_approve_key_batch(title, developer, requested_quantity=2)
    keys = list_batch_keys(batch["id"], developer)
    key_code = keys[0]["key_code"]
    redeemer = create_user()

    get_success_data(api_client.terminate_developer(developer["id"], OPS))

    title_read = read_title(title["id"], developer)
    assert title_read["status"] == "DELISTED"

    res = api_client.redeem_key({"key_code": key_code}, make_user_headers(redeemer["id"]))
    validate_error(res, ApiErrorId.ERR_KEY_NOT_REDEEMABLE)

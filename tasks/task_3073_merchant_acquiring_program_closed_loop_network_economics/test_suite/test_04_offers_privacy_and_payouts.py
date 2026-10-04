"""Spend-insight offers: the privacy machine, the consent gates, live-window
clearance, and the funded redemption pool."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    create_industry_category,
    create_merchant,
    create_and_accept_merchant,
    create_and_activate_merchant,
    create_active_cardmember,
    create_offer,
    submit_offer_review,
    request_offer_consent,
    consent_offer,
    return_offer_to_draft,
    suspend_offer,
    create_redemption_pool,
    accept_and_approve_offer,
    finalize_batch,
    mark_merchant_dormant,
    suppress_merchant,
    get_success_data,
    set_member_spend,
    get_offer,
    get_offer_pool,
    get_merchant,
    set_clock,
)
from test_helpers.fixtures import (
    STEWARD,
    make_merchant_headers,
    make_cardmember_headers,
    setup_live_offer_with_pool,
    setup_offer_in_state,
)


def _active_offer_scenario(reward_bps=1000, min_segment_spend_cents=10000,
                           member_spend_cents=100000, pool_initial_funded_cents=500000):
    """Active merchant + active member with spend + a LIVE offer + funded pool."""
    return setup_live_offer_with_pool(
        reward_bps=reward_bps,
        min_segment_spend_cents=min_segment_spend_cents,
        member_spend_cents=member_spend_cents,
        pool_initial_funded_cents=pool_initial_funded_cents,
    )


# ═══ Difficulty: offer privacy machine revert ════════════

def test_return_to_draft_rolls_a_reviewed_offer_back_to_draft(api):
    """PRD §3.4: "Returning an offer from `PRIVACY_REVIEW` to `DRAFT` is
    permitted only when no member-spend data has been shared with the merchant,
    and it resets `audience_size` and `aggregated_spend_cents` to zero."

    Design: Difficulty/non_linear_state_machine/offer_privacy_machine_reverts_from_review_to_draft
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)
    offer = create_offer(merchant["id"])
    offer = submit_offer_review(offer["id"])
    assert offer["privacy_state"] == "PRIVACY_REVIEW"

    reverted = return_offer_to_draft(offer["id"])
    assert reverted["privacy_state"] == "DRAFT"
    assert get_offer(offer["id"])["privacy_state"] == "DRAFT"


def test_return_to_draft_zeroes_the_aggregated_audience_figures(api):
    """PRD §3.4: "Returning an offer from `PRIVACY_REVIEW` to `DRAFT` is
    permitted only when no member-spend data has been shared with the merchant,
    and it resets `audience_size` and `aggregated_spend_cents` to zero."

    Design: Difficulty/non_linear_state_machine/offer_privacy_machine_reverts_from_review_to_draft
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)
    offer = create_offer(merchant["id"])
    reviewed = submit_offer_review(offer["id"])
    assert reviewed["audience_size"] == 1
    assert reviewed["aggregated_spend_cents"] == 100000

    reverted = return_offer_to_draft(offer["id"])
    assert reverted["audience_size"] == 0
    assert reverted["aggregated_spend_cents"] == 0


def test_suspending_a_live_offer_returns_it_to_merchant_consent(api):
    """PRD §3.4: "Suspending a `LIVE` offer returns it to `MERCHANT_CONSENT`;
    acceptances already recorded stay `PENDING`, but no new acceptance may be
    recorded while the offer is suspended."

    Design: Difficulty/non_linear_state_machine/offer_privacy_machine_reverts_from_review_to_draft
    """
    set_clock()
    _, merchant, _, offer, _ = _active_offer_scenario()
    assert offer["privacy_state"] == "LIVE"

    suspended = suspend_offer(offer["id"])
    assert suspended["privacy_state"] == "MERCHANT_CONSENT"
    assert get_offer(offer["id"])["privacy_state"] == "MERCHANT_CONSENT"


# ═══ Difficulty: offer gated by merchant acceptance state ═══

def test_suppressing_the_funding_merchant_terminates_its_offer(api):
    """PRD §3.2: "all offers the merchant funds whose `privacy_state` is one of
    `DRAFT`, `PRIVACY_REVIEW`, `MERCHANT_CONSENT`, or `LIVE` are moved to
    `TERMINATED`"

    Design: Difficulty/cross_entity_state_dependency/offer_lifecycle_gated_by_merchant_acceptance_state
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)
    offer = setup_offer_in_state(merchant["id"], "MERCHANT_CONSENT")
    assert offer["privacy_state"] == "MERCHANT_CONSENT"

    get_success_data(suppress_merchant(merchant["id"]))
    assert get_offer(offer["id"])["privacy_state"] == "TERMINATED", (
        "the suppression cascade terminates every non-terminal offer the merchant funds")


def test_a_merchant_that_is_not_active_cannot_launch_an_offer(api):
    """PRD §3.4: "the funding merchant's `acceptance_status` must be `ACTIVE`,
    because a merchant that is not live on the network cannot launch a
    spend-insight offer"

    Design: Difficulty/cross_entity_state_dependency/offer_lifecycle_gated_by_merchant_acceptance_state
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)
    offer = setup_offer_in_state(merchant["id"], "MERCHANT_CONSENT")

    mark_merchant_dormant(merchant)
    assert get_merchant(merchant["id"])["acceptance_status"] == "DORMANT"

    res = api_client.consent_offer(
        offer["id"], {"expected_offer_version": offer["version"]},
        make_merchant_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ═══ Difficulty: redemption pool compensating invariant ══

def test_approve_then_reverse_returns_the_pool_to_its_prior_balance(api):
    """PRD §3.5: "Reversing moves the acceptance to `REVERSED`, subtracts that
    reversed backing from `consumed_total_cents`, and adds it back to
    `balance_cents`, so a matched approve-and-reverse pair returns the pool to
    the balance it held before the approval."

    Design: Difficulty/compensating_invariant/offer_redemption_pool_balance_invariant
    """
    set_clock()
    _, merchant, member, offer, _ = _active_offer_scenario()
    approval, pool_before, pool_after = accept_and_approve_offer(
        offer["id"], member["id"], trigger_amount_cents=100000)
    assert pool_after["consumed_total_cents"] > 0, "approval draws on the pool"

    reversed_acc = validate_success(
        api_client.reverse_offer_acceptance(approval["id"], STEWARD), 200)
    assert reversed_acc["acceptance_status"] == "REVERSED"

    pool_restored = get_offer_pool(offer["id"])
    assert pool_restored["consumed_total_cents"] == 0
    assert pool_restored["balance_cents"] == pool_before["balance_cents"]


def test_accepting_an_offer_alone_moves_no_pool_money(api):
    """PRD §3.5: "No pool money moves at acceptance: acceptance alone is a
    recorded intent, and a `PENDING` acceptance contributes nothing to the pool."

    Design: Difficulty/compensating_invariant/offer_redemption_pool_balance_invariant
    """
    set_clock()
    _, merchant, member, offer, _ = _active_offer_scenario()
    pool_before = get_offer_pool(offer["id"])

    acceptance = validate_success(api_client.accept_offer(
        offer["id"],
        {"cardmember_id": member["id"], "trigger_amount_cents": 100000},
        make_cardmember_headers(member["id"])), 201)
    assert acceptance["acceptance_status"] == "PENDING"

    pool_after = get_offer_pool(offer["id"])
    assert pool_after["consumed_total_cents"] == pool_before["consumed_total_cents"] == 0
    assert pool_after["balance_cents"] == pool_before["balance_cents"]


# ═══ Corner: offer create input validation ═══════════════

def test_offer_create_with_an_unknown_field_is_rejected(api):
    """PRD §2.10: "any malformed body, unknown field, missing required field, or
    enum or range violation yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/offer_create_with_unknown_field_returns_invalid_request
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])

    res = api_client.create_offer({
        "merchant_id": merchant["id"],
        "audience_segment": "HIGH_SPEND",
        "min_segment_spend_cents": 10000,
        "reward_bps": 1000,
        "surprise_field": "x",
    }, STEWARD)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    data = validate_success(api_client.list_offers(
        STEWARD, params={"merchant_id": merchant["id"]}), 200)
    assert data == [], "a rejected create must not mint an offer row"


# ═══ Corner: consent ownership ═══════════════════════════

def test_consent_by_a_different_merchant_is_forbidden(api):
    """PRD §2.1: "A merchant that authenticated successfully but is addressing a
    resource belonging to a different merchant receives `ERR_FORBIDDEN`, not a
    not-found error."

    Design: Corner/validations/offer_consent_by_a_different_merchant_returns_forbidden
    """
    set_clock()
    category = create_industry_category()
    merchant_a = create_and_activate_merchant(category["id"], merchant_name="Validation Merchant 3")
    merchant_b = create_and_activate_merchant(category["id"], merchant_name="Validation Merchant 4")
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)
    offer = setup_offer_in_state(merchant_a["id"], "MERCHANT_CONSENT")

    res = api_client.consent_offer(
        offer["id"], {"expected_offer_version": offer["version"]},
        make_merchant_headers(merchant_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert get_offer(offer["id"])["privacy_state"] == "MERCHANT_CONSENT"


# ═══ Corner: consent concurrency ═════════════════════════

def test_second_consent_with_the_same_observed_version_is_stale(api):
    """PRD §2.6: "When the offer's `version` has moved — because the data
    steward has advanced the offer's privacy state since the merchant last read
    it — the consent is refused with `ERR_STALE_VERSION` and HTTP 412"

    Design: Corner/errors/timestale_version_on_offer_consent_returns_stale_version
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)
    offer = create_offer(merchant["id"])
    offer = submit_offer_review(offer["id"])
    offer = request_offer_consent(offer["id"])
    observed_version = offer["version"]

    # Two writers driving the same cyclic write from the same observed view
    # (PRD §2.6): exactly one consent may be accepted; the other is refused
    # because its observation of the offer's version is now superseded.
    # The loser's error is not pinned beyond that -- a serialized loser can also
    # find the offer no longer in the state the transition requires, which the
    # PRD's precedence order reports as ERR_INVALID_STATE.
    responses = []
    for _ in range(2):
        responses.append(api_client.consent_offer(
            offer["id"], {"expected_offer_version": observed_version},
            make_merchant_headers(merchant["id"])))

    accepted = [r for r in responses if r.status_code == 200]
    rejected = [r for r in responses if r.status_code != 200]
    assert len(accepted) == 1, "exactly one consent against the same observed version wins"
    assert len(rejected) == 1, "the superseded consent is refused"

    accepted_data = validate_success(accepted[0], 200)
    assert accepted_data["privacy_state"] == "LIVE"

    validate_error_is_one_of(
        rejected[0],
        [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value])


# ═══ Difficulty: offer live-window clearance ═════════════

def test_a_live_window_within_a_day_of_an_existing_window_is_rejected(api):
    """PRD §3.4: "the requested window, supplied as `live_start_utc` and
    `live_end_utc`, must leave at least one full day of clearance from every
    existing live window funded by the same merchant. A window that overlaps
    another or that comes within a day of one is refused with
    `ERR_TEMPORAL_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/offer_live_windows_reject_on_buffer_overlap
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)

    first = create_offer(merchant["id"])
    first = submit_offer_review(first["id"])
    first = request_offer_consent(first["id"])
    live = consent_offer(first["id"], merchant["id"], expected_version=first["version"],
                         live_start_utc="2026-09-10T00:00:00Z",
                         live_end_utc="2026-09-20T00:00:00Z")
    assert live["privacy_state"] == "LIVE"

    second = create_offer(merchant["id"])
    second = submit_offer_review(second["id"])
    second = request_offer_consent(second["id"])

    # The existing window is [09-10T00:00, 09-20T00:00) and a full day of
    # clearance means the next window may not open before 09-21T00:00.  Opening
    # twelve hours after the existing end is inside the buffer.
    res = api_client.consent_offer(
        second["id"],
        {"expected_offer_version": second["version"],
         "live_start_utc": "2026-09-20T12:00:00Z",
         "live_end_utc": "2026-09-30T00:00:00Z"},
        make_merchant_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_TEMPORAL_OVERLAP.value, expected_status=409)


def test_window_inside_the_clearance_buffer_leaves_the_offer_unlaunched(api):
    """PRD §3.4: "A window that overlaps another or that comes within a day of
    one is refused with `ERR_TEMPORAL_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/offer_live_windows_reject_on_buffer_overlap
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    set_member_spend(member["id"], 100000)

    first = create_offer(merchant["id"])
    first = submit_offer_review(first["id"])
    first = request_offer_consent(first["id"])
    consent_offer(first["id"], merchant["id"], expected_version=first["version"],
                  live_start_utc="2026-09-10T00:00:00Z",
                  live_end_utc="2026-09-20T00:00:00Z")

    second = create_offer(merchant["id"])
    second = submit_offer_review(second["id"])
    second = request_offer_consent(second["id"])
    api_client.consent_offer(
        second["id"],
        {"expected_offer_version": second["version"],
         "live_start_utc": "2026-09-20T12:00:00Z",
         "live_end_utc": "2026-09-30T00:00:00Z"},
        make_merchant_headers(merchant["id"]))

    after = get_offer(second["id"])
    assert after["privacy_state"] == "MERCHANT_CONSENT", (
        "the buffered offer did not go live")
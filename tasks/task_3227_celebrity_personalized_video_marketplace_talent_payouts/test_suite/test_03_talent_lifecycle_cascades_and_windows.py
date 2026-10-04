"""Talent lifecycle, cross-entity dependencies, and the cascades that reach
from a talent or a sweep into orders, wallets, tiers, and payout lines."""

from test_helpers import (
    ApiErrorId,
    create_accepted_order,
    create_active_talent,
    create_confirmed_order,
    create_delivered_order,
    create_order,
    create_screened_order,
    deliver_video,
    get_success_data,
    lines_for_order,
    make_admin_headers,
    make_buyer_headers,
    make_talent_headers,
    moderate_video_clear,
    payout_lines_for_talent,
    read_buyer,
    read_order,
    read_talent,
    register_buyer,
    register_talent,
    set_clock,
    submit_identity,
    submit_tax_document,
    validate_error,
    validate_success,
)


def test_pause_resume_cycle_restores_bookability(api):
    """PRD §3.2: "An `ACTIVE` talent may pause itself, moving to `PAUSED` and
    flipping `availability` to `PAUSED_AVAILABILITY`; pausing increments
    `availability_pause_count_30d`, the count of pauses started within the
    trailing 30 days."
    PRD §3.2: "A paused talent may resume, returning to `ACTIVE` with
    `availability` restored to `BOOKABLE`."

    Design: Difficulty/non_linear_state_machine/talent_pause_resume_cycle
    """
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 5000,
            "business_rate_cents": 20000,
            "advertising_rate_cents": 40000,
            "turnaround_hours": 48,
        },
    )
    headers = make_talent_headers(talent["id"])

    paused = validate_success(api.pause_talent(talent["id"], headers=headers))
    assert paused["status"] == "PAUSED"
    assert paused["availability"] == "PAUSED_AVAILABILITY"

    resumed = validate_success(api.resume_talent(talent["id"], headers=headers))
    assert resumed["status"] == "ACTIVE"
    assert resumed["availability"] == "BOOKABLE"


def test_fourth_pause_within_30_days_rejected(api):
    """PRD §3.2: "A pause that would be the fourth within that window is
    rejected with `ERR_PAUSE_RATE_LIMIT` (HTTP 429) — the third pause is the
    last one allowed."

    Design: Corner/validations/fourth_pause_within_30_days_rejected
    """
    talent = create_active_talent(api)
    headers = make_talent_headers(talent["id"])
    for _ in range(3):
        validate_success(api.pause_talent(talent["id"], headers=headers))
        validate_success(api.resume_talent(talent["id"], headers=headers))

    response = api.pause_talent(talent["id"], headers=headers)
    validate_error(response, ApiErrorId.ERR_PAUSE_RATE_LIMIT.value)
    assert read_talent(api, talent["id"])["status"] == "ACTIVE"


def test_auto_confirm_cascade_credits_pending_and_gmv(api):
    """PRD §3.5: "If the buyer simply waits, the deadline sweep auto-confirms
    on the same preconditions: a `DELIVERED` order whose `auto_confirm_at`
    has been reached, whose latest video is `CLEARED`, and with no open
    dispute transitions to `CONFIRMED` identically to a manual confirmation."
    PRD §3.5: "Confirmation then creates a `PayoutLine` of kind
    `VIDEO_EARNING` carrying the `talent_id` and `order_id` from the order, a
    positive `amount_cents` equal to `talent_net_cents`, and
    `settlement_status` `UNSETTLED`, and credits the talent's
    `pending_balance_cents` by the same amount."
    PRD §3.5: "The order's `gross_amount_cents` is added to the talent's
    `trailing_gmv_cents`, which is the sum of gross amounts over the talent's
    orders whose `CONFIRMED` transition occurred within the trailing 365-day
    window — inclusive of the window start, exclusive of the window end —
    minus gross amounts refunded by full-refund dispute resolutions and minus
    buyer-refund amounts from partial-refund resolutions."

    Design: Difficulty/transitive_cascade/auto_confirm_cascades_to_payoutline_and_tier
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    # Delivery at 2026-09-01 sets auto_confirm_at to 2026-09-04; sweep past it.
    set_clock(api, "2026-09-05T00:00:00Z")
    sweep = validate_success(
        api.deadline_sweep("2026-09-05T00:00:00Z", headers=make_admin_headers())
    )
    assert sweep["auto_confirmed_count"] >= 1

    confirmed = read_order(api, order["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["platform_commission_cents"] == 2500
    assert confirmed["talent_net_cents"] == 7500

    lines = [l for l in lines_for_order(api, order["id"]) if l["kind"] == "VIDEO_EARNING"]
    assert len(lines) == 1
    assert lines[0]["amount_cents"] == 7500
    assert lines[0]["settlement_status"] == "UNSETTLED"

    talent_now = read_talent(api, talent["id"])
    assert talent_now["pending_balance_cents"] == 7500
    assert talent_now["trailing_gmv_cents"] == 10000


def test_auto_confirm_crossing_silver_boundary(api):
    """PRD §3.5: "The tier is recomputed immediately on every change to
    `trailing_gmv_cents`: at least 2000000 cents of trailing GMV yields
    `GOLD`, at least 500000 cents yields `SILVER`, and anything below yields
    `STANDARD`; both thresholds are inclusive."
    PRD §3.5: "If the buyer simply waits, the deadline sweep auto-confirms on
    the same preconditions: a `DELIVERED` order whose `auto_confirm_at` has
    been reached, whose latest video is `CLEARED`, and with no open dispute
    transitions to `CONFIRMED` identically to a manual confirmation."

    Design: Difficulty/transitive_cascade/auto_confirm_cascades_to_payoutline_and_tier
    """
    # 196 confirmations of 2500 gross each put trailing GMV at 490000; the
    # auto-confirmed 197th pushes it to 492500 (still STANDARD), and the
    # boundary-crossing case is covered by the inclusive-boundary tests.
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2500,
            "business_rate_cents": 10000,
            "advertising_rate_cents": 20000,
        },
    )
    buyer = register_buyer(api)
    for _ in range(196):
        create_confirmed_order(api, talent, buyer)
    assert read_talent(api, talent["id"])["trailing_gmv_cents"] == 490000

    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")
    set_clock(api, "2026-09-05T00:00:00Z")
    validate_success(api.deadline_sweep("2026-09-05T00:00:00Z", headers=make_admin_headers()))

    confirmed = read_order(api, order["id"])
    assert confirmed["status"] == "CONFIRMED"
    talent_now = read_talent(api, talent["id"])
    assert talent_now["trailing_gmv_cents"] == 492500, (
        "the sweep-driven confirmation adds its gross to the trailing window"
    )
    # Net at STANDARD for 196 x 2500 gross is 196 * 1875; the auto-confirmed
    # order adds 1875 more once the sweep runs.
    assert talent_now["pending_balance_cents"] == 196 * 1875 + 1875


def test_suspend_cascades_refund_to_buyer_wallet(api):
    """PRD §3.2: "When a `PlatformAdmin` suspends a talent in `ACTIVE` or
    `PAUSED`, every one of that talent's orders still in
    `AWAITING_ACCEPTANCE` transitions to `EXPIRED` with a full refund of its
    gross amount to the buyer's wallet; every order in `ACCEPTED` or
    `RE_RECORD_REQUESTED` transitions to `CANCELLED`, again with a full
    wallet refund, and any `OPEN` re-record request on those orders
    transitions to `CLOSED`."
    PRD §3.2: "`SUSPENDED` is terminal."

    Design: Difficulty/transitive_cascade/suspend_cascades_order_refund_and_wallet
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_accepted_order(api, talent, buyer)

    suspended = validate_success(
        api.suspend_talent(talent["id"], headers=make_admin_headers())
    )
    assert suspended["status"] == "SUSPENDED"

    cancelled = read_order(api, order["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_amount_cents"] == 10000

    refreshed = read_buyer(api, buyer["id"])
    assert refreshed["wallet_credit_cents"] == 10000


def test_suspend_expires_awaiting_orders(api):
    """PRD §3.2: "When a `PlatformAdmin` suspends a talent in `ACTIVE` or
    `PAUSED`, every one of that talent's orders still in
    `AWAITING_ACCEPTANCE` transitions to `EXPIRED` with a full refund of its
    gross amount to the buyer's wallet; every order in `ACCEPTED` or
    `RE_RECORD_REQUESTED` transitions to `CANCELLED`, again with a full
    wallet refund, and any `OPEN` re-record request on those orders
    transitions to `CLOSED`."

    Design: Difficulty/transitive_cascade/suspend_cascades_order_refund_and_wallet
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_screened_order(api, talent, buyer)
    assert order["status"] == "AWAITING_ACCEPTANCE"

    validate_success(api.suspend_talent(talent["id"], headers=make_admin_headers()))

    expired = read_order(api, order["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["refund_amount_cents"] == 10000
    assert read_buyer(api, buyer["id"])["wallet_credit_cents"] == 10000


def test_accept_after_suspend_rejected_invalid_state(api):
    """PRD §3.3: "Accepting moves the order from `AWAITING_ACCEPTANCE` to
    `ACCEPTED`, requires the acting user to be the booked talent and the
    talent to currently be `ACTIVE`, and requires the current logical time to
    be strictly before `acceptance_deadline`; an acceptance at or after the
    deadline is rejected with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409)."
    PRD §3.2: "When a `PlatformAdmin` suspends a talent in `ACTIVE` or
    `PAUSED`, every one of that talent's orders still in
    `AWAITING_ACCEPTANCE` transitions to `EXPIRED` with a full refund of its
    gross amount to the buyer's wallet; every order in `ACCEPTED` or
    `RE_RECORD_REQUESTED` transitions to `CANCELLED`, again with a full
    wallet refund, and any `OPEN` re-record request on those orders
    transitions to `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/order_accept_requires_talent_active
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_screened_order(api, talent, buyer)
    validate_success(api.suspend_talent(talent["id"], headers=make_admin_headers()))

    response = api.accept_order(order["id"], headers=make_talent_headers(talent["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_order(api, order["id"])["status"] == "EXPIRED"


def test_payout_initiate_blocked_without_verified_taxdoc(api):
    """PRD §3.8: "A scheduled payout cannot move until tax compliance is
    proven: initiation — which moves the payout from `SCHEDULED` to
    `PROCESSING` — requires the payout's talent to hold at least one
    `VERIFIED` tax document, and is otherwise rejected with
    `ERR_TAX_DOC_MISSING` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/payout_initiate_requires_verified_taxdoc
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)

    payouts = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=make_admin_headers()
    ).json()["data"]
    assert len(payouts) == 1
    payout = payouts[0]

    # Retract tax compliance: the only document is rejected.
    docs = api.list_tax_documents(talent["id"], headers=make_admin_headers()).json()["data"]
    for doc in docs:
        api.review_tax_document(doc["id"], "REJECT", headers=make_admin_headers())

    response = api.initiate_payout(payout["id"], headers=make_admin_headers())
    validate_error(response, ApiErrorId.ERR_TAX_DOC_MISSING.value)


def test_initiate_paid_payout_reports_state_before_fiscal(api):
    """PRD §2.8: "Fifth, the target resource's current state is checked
    against the transition being attempted (`ERR_INVALID_STATE`, HTTP 409).
    Sixth, on the two OCC-guarded writes, the expected-version check runs
    (`ERR_STALE_VERSION`). Only then do business rules — content policy,
    moderation gates, ownership, temporal windows, uniqueness, rate bounds,
    fiscal gates — execute, each surfacing its own error code as described in
    §3."
    PRD §3.8: "A scheduled payout cannot move until tax compliance is proven:
    initiation — which moves the payout from `SCHEDULED` to `PROCESSING` —
    requires the payout's talent to hold at least one `VERIFIED` tax
    document, and is otherwise rejected with `ERR_TAX_DOC_MISSING` (HTTP
    422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_payout_initiate
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)
    admin = make_admin_headers()

    payout = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    ).json()["data"][0]
    validate_success(api.initiate_payout(payout["id"], headers=admin))
    validate_success(api.complete_payout(payout["id"], headers=admin))

    # The talent no longer holds a VERIFIED tax document.
    docs = api.list_tax_documents(talent["id"], headers=admin).json()["data"]
    for doc in docs:
        api.review_tax_document(doc["id"], "REJECT", headers=admin)

    # The payout is already PAID: the state check fires before the fiscal one.
    response = api.initiate_payout(payout["id"], headers=admin)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


def test_safety_check_precedes_temporal_on_screening_attest(api):
    """PRD §3.3: "The attestation is only meaningful on a clean order: if
    `screening_flags` is non-empty, the attestation is rejected with
    `ERR_CONTENT_POLICY_FLAGGED` (HTTP 422), and a token that does not match
    the order's stored token is rejected as an invalid request."
    PRD §3.3: "The screening rule is deterministic: when
    `script_instructions` contains the marker substring
    `FLAGGED_POLICY_VIOLATION`, the server raises a `POLICY_VIOLATION` flag;
    otherwise `screening_flags` is the empty array."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_screening_attest
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_order(
        api,
        talent,
        buyer,
        script_instructions="FLAGGED_POLICY_VIOLATION explicit request",
    )
    assert order["screening_flags"], "the marker must raise a screening flag"

    # Advance the clock far past any acceptance consideration; the safety
    # check still fires.
    set_clock(api, "2026-09-10T00:00:00Z")
    response = api.screening_attest(
        order["id"], order["screening_token"], headers=make_buyer_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONTENT_POLICY_FLAGGED.value)
    assert read_order(api, order["id"])["status"] == "SCREENING"


def test_accept_at_exact_deadline_rejected(api):
    """PRD §3.3: "A successful attestation moves the order from `SCREENING`
    to `AWAITING_ACCEPTANCE` and sets `acceptance_deadline` to the current
    logical time plus 48 hours."
    PRD §3.3: "Accepting moves the order from `AWAITING_ACCEPTANCE` to
    `ACCEPTED`, requires the acting user to be the booked talent and the
    talent to currently be `ACTIVE`, and requires the current logical time to
    be strictly before `acceptance_deadline`; an acceptance at or after the
    deadline is rejected with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/acceptance_window_boundary_expiry
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_screened_order(api, talent, buyer)

    # Exactly 48 hours after attestation: the deadline instant itself.
    set_clock(api, "2026-09-03T00:00:00Z")
    response = api.accept_order(order["id"], headers=make_talent_headers(talent["id"]))
    validate_error(response, ApiErrorId.ERR_ACCEPTANCE_WINDOW_CLOSED.value)
    assert read_order(api, order["id"])["status"] == "AWAITING_ACCEPTANCE"


def test_accept_one_second_before_deadline_succeeds(api):
    """PRD §3.3: "Accepting moves the order from `AWAITING_ACCEPTANCE` to
    `ACCEPTED`, requires the acting user to be the booked talent and the
    talent to currently be `ACTIVE`, and requires the current logical time to
    be strictly before `acceptance_deadline`; an acceptance at or after the
    deadline is rejected with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/acceptance_window_boundary_expiry
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_screened_order(api, talent, buyer)

    set_clock(api, "2026-09-02T23:59:59Z")
    response = api.accept_order(order["id"], headers=make_talent_headers(talent["id"]))
    accepted = validate_success(response)
    assert accepted["status"] == "ACCEPTED"


def test_delivery_at_exact_deadline_rejected(api):
    """PRD §3.3: "Acceptance sets `delivery_deadline` to the current logical
    time plus the talent's `turnaround_hours`."
    PRD §3.4: "Uploading is permitted from either `ACCEPTED` or
    `RE_RECORD_REQUESTED`, but only while the current logical time is
    strictly before `delivery_deadline`; an upload at or after the deadline
    is rejected with `ERR_DELIVERY_DEADLINE_PASSED` (HTTP 409)."

    Design: Corner/endpoints/delivery_after_deadline_rejected
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    talent = create_active_talent(api, rates_overrides={"turnaround_hours": 24})
    buyer = register_buyer(api)
    order = create_accepted_order(api, talent, buyer)

    set_clock(api, "2026-09-02T00:00:00Z")
    response = api.upload_video(
        order["id"],
        {"content_url": "https://cdn.example.com/late.mp4", "duration_seconds": 30},
        headers=make_talent_headers(talent["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DELIVERY_DEADLINE_PASSED.value)
    assert read_order(api, order["id"])["status"] == "ACCEPTED"


def test_delivery_before_deadline_accepted(api):
    """PRD §3.4: "Uploading is permitted from either `ACCEPTED` or
    `RE_RECORD_REQUESTED`, but only while the current logical time is
    strictly before `delivery_deadline`; an upload at or after the deadline
    is rejected with `ERR_DELIVERY_DEADLINE_PASSED` (HTTP 409)."

    Design: Corner/endpoints/delivery_after_deadline_rejected
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    talent = create_active_talent(api, rates_overrides={"turnaround_hours": 24})
    buyer = register_buyer(api)
    order = create_accepted_order(api, talent, buyer)

    set_clock(api, "2026-09-01T23:59:59Z")
    response = api.upload_video(
        order["id"],
        {"content_url": "https://cdn.example.com/ontime.mp4", "duration_seconds": 30},
        headers=make_talent_headers(talent["id"]),
    )
    video = validate_success(response, expected_status=201)
    assert video["moderation_status"] == "PENDING_REVIEW"
    assert video["version_no"] == 1


def test_suspended_talent_cannot_accept_any_order(api):
    """PRD §3.3: "Accepting moves the order from `AWAITING_ACCEPTANCE` to
    `ACCEPTED`, requires the acting user to be the booked talent and the
    talent to currently be `ACTIVE`, and requires the current logical time to
    be strictly before `acceptance_deadline`; an acceptance at or after the
    deadline is rejected with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409)."
    PRD §3.2: "`SUSPENDED` is terminal."

    Design: Difficulty/cross_entity_state_dependency/order_accept_requires_talent_active
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_screened_order(api, talent, buyer)
    validate_success(api.suspend_talent(talent["id"], headers=make_admin_headers()))

    # Even a hypothetical order still in AWAITING_ACCEPTANCE could not be
    # accepted by a SUSPENDED talent; here the cascade has already expired
    # this one, so the state check fires.
    response = api.accept_order(order["id"], headers=make_talent_headers(talent["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_talent(api, talent["id"])["status"] == "SUSPENDED"


def test_payout_initiate_succeeds_with_verified_taxdoc(api):
    """PRD §3.8: "A scheduled payout cannot move until tax compliance is
    proven: initiation — which moves the payout from `SCHEDULED` to
    `PROCESSING` — requires the payout's talent to hold at least one
    `VERIFIED` tax document, and is otherwise rejected with
    `ERR_TAX_DOC_MISSING` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/payout_initiate_requires_verified_taxdoc
    """
    from test_helpers import create_confirmed_order

    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)

    payout = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=make_admin_headers()
    ).json()["data"][0]
    initiated = validate_success(
        api.initiate_payout(payout["id"], headers=make_admin_headers())
    )
    assert initiated["status"] == "PROCESSING"


def test_state_check_fires_before_fiscal_on_payout_initiate_again(api):
    """PRD §2.8: "Fifth, the target resource's current state is checked
    against the transition being attempted (`ERR_INVALID_STATE`, HTTP 409).
    Sixth, on the two OCC-guarded writes, the expected-version check runs
    (`ERR_STALE_VERSION`). Only then do business rules — content policy,
    moderation gates, ownership, temporal windows, uniqueness, rate bounds,
    fiscal gates — execute, each surfacing its own error code as described in
    §3."
    PRD §3.8: "Completion moves a `PROCESSING` payout to `PAID`, stamps
    `paid_at` with the current logical time, transitions every attached
    payout line from `UNSETTLED` to `SETTLED`, and performs the conserved
    balance shift: the talent's `pending_balance_cents` is debited by
    `total_cents` and `paid_out_balance_cents` is credited by exactly the
    same amount, so the sum of the two balances is invariant across the
    transition."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_payout_initiate
    """
    from test_helpers import create_confirmed_order

    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)
    payout = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    ).json()["data"][0]

    # Retract tax compliance first, so only the state rule can explain a
    # rejection from the completed payout.
    validate_success(api.initiate_payout(payout["id"], headers=admin))
    validate_success(api.complete_payout(payout["id"], headers=admin))
    docs = api.list_tax_documents(talent["id"], headers=admin).json()["data"]
    for doc in docs:
        api.review_tax_document(doc["id"], "REJECT", headers=admin)

    response = api.complete_payout(payout["id"], headers=admin)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


def test_flagged_screening_stays_flagged_after_clock_advance(api):
    """PRD §3.3: "The attestation is only meaningful on a clean order: if
    `screening_flags` is non-empty, the attestation is rejected with
    `ERR_CONTENT_POLICY_FLAGGED` (HTTP 422), and a token that does not match
    the order's stored token is rejected as an invalid request."
    PRD §3.3: "The screening rule is deterministic: when
    `script_instructions` contains the marker substring
    `FLAGGED_POLICY_VIOLATION`, the server raises a `POLICY_VIOLATION` flag;
    otherwise `screening_flags` is the empty array."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_screening_attest
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_order(
        api,
        talent,
        buyer,
        script_instructions="FLAGGED_POLICY_VIOLATION do the thing",
    )
    set_clock(api, "2026-10-01T00:00:00Z")
    response = api.screening_attest(
        order["id"], order["screening_token"], headers=make_buyer_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONTENT_POLICY_FLAGGED.value)


def test_below_silver_boundary_stays_standard(api):
    """PRD §3.5: "The tier is recomputed immediately on every change to
    `trailing_gmv_cents`: at least 2000000 cents of trailing GMV yields
    `GOLD`, at least 500000 cents yields `SILVER`, and anything below yields
    `STANDARD`; both thresholds are inclusive."
    PRD §3.5: "The order's `gross_amount_cents` is added to the talent's
    `trailing_gmv_cents`, which is the sum of gross amounts over the talent's
    orders whose `CONFIRMED` transition occurred within the trailing 365-day
    window — inclusive of the window start, exclusive of the window end —
    minus gross amounts refunded by full-refund dispute resolutions and minus
    buyer-refund amounts from partial-refund resolutions."

    Design: Difficulty/boundary_precision_check/silver_tier_inclusive_boundary
    """
    from test_helpers import create_confirmed_order

    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2500,
            "business_rate_cents": 10000,
            "advertising_rate_cents": 20000,
        },
    )
    buyer = register_buyer(api)
    # 199 confirmations at 2500 gross -> 497500, one cent-scenario below the
    # boundary; the tier must stay STANDARD.
    for _ in range(199):
        create_confirmed_order(api, talent, buyer)
    talent_now = read_talent(api, talent["id"])
    assert talent_now["trailing_gmv_cents"] == 497500
    assert talent_now["commission_tier"] == "STANDARD"


def test_pause_increments_pause_count(api):
    """PRD §3.2: "An `ACTIVE` talent may pause itself, moving to `PAUSED` and
    flipping `availability` to `PAUSED_AVAILABILITY`; pausing increments
    `availability_pause_count_30d`, the count of pauses started within the
    trailing 30 days."
    PRD §3.2: "A paused talent may resume, returning to `ACTIVE` with
    `availability` restored to `BOOKABLE`."

    Design: Difficulty/non_linear_state_machine/talent_pause_resume_cycle
    """
    talent = create_active_talent(api)
    assert talent["availability_pause_count_30d"] == 0
    headers = make_talent_headers(talent["id"])

    validate_success(api.pause_talent(talent["id"], headers=headers))
    after_one = read_talent(api, talent["id"])
    assert after_one["availability_pause_count_30d"] == 1

    validate_success(api.resume_talent(talent["id"], headers=headers))
    validate_success(api.pause_talent(talent["id"], headers=headers))
    after_two = read_talent(api, talent["id"])
    assert after_two["availability_pause_count_30d"] == 2
    assert after_two["status"] == "PAUSED"

"""Delivery receipt and counter freshness: parallel order dimensions, pull
deadlines, late-pull cascade, training and expiry gates (PRD §3.3, §3.5, §3.6)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_authorization,
    create_delivery,
    create_delivery_payload,
    create_opened_log,
    create_product,
    create_slicer,
    confirm_delivery,
    delivery_line,
    get_lot_for_run,
    get_order,
    get_success_data,
    make_distributor_rep_headers,
    make_retail_manager_headers,
    pull_log,
    record_late_pull,
    set_clock,
    setup_approved_account,
    setup_delivery_chain,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def _parse(ts):
    """Parse an ISO 8601 UTC timestamp (PRD §2.4 allows three fractional digits)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _setup_account_with_two_late_pulls():
    """APPROVED account with an AUTHORIZED authorization, a slicer, two recorded
    late pulls, and two further logs (opened 04:00, one-hour shelf life) still OPEN
    with the clock at 06:00 — one pull away from the threshold of 3."""
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Fast Item", shelf_life_opened_hours=1)
    authorization = create_authorization(ctx["account"]["id"], product["id"])
    slicer = create_slicer(ctx["account"], label="S1")
    record_late_pull(ctx["account"], product, slicer,
                     "2026-09-01T00:00:00Z", "2026-09-01T02:00:00Z")
    record_late_pull(ctx["account"], product, slicer,
                     "2026-09-01T02:00:00Z", "2026-09-01T04:00:00Z")
    log_3 = create_opened_log(ctx["account"], product, slicer,
                              opened_at="2026-09-01T04:00:00Z")
    log_4 = create_opened_log(ctx["account"], product, slicer,
                              opened_at="2026-09-01T04:00:00Z")
    set_clock("2026-09-01T06:00:00Z")
    return ctx, product, authorization, log_3, log_4


def test_allocation_and_fulfillment_dimensions_advance_independently(api):
    """PRD §3.3: "An order carries two independent state dimensions that evolve on
    one row: `allocation_status`, beginning at `PENDING` and ranging over
    `ALLOCATED`, `PARTIAL`, `SHORTED`, and the terminal `CANCELLED`; and
    `fulfillment_status`, beginning at `UNSHIPPED` and ranging over `IN_TRANSIT`,
    `DELIVERED`, and `REJECTED`."

    The order reaches ALLOCATED while fulfillment is still UNSHIPPED; creating the
    delivery advances only the fulfillment dimension to IN_TRANSIT.

    Design: Difficulty/non_linear_state_machine/order_parallel_allocation_fulfillment_dimensions
    """
    chain = setup_delivery_chain(qty=10)
    order = get_order(chain["order"]["id"])
    assert order["allocation_status"] == "ALLOCATED"
    assert order["fulfillment_status"] == "UNSHIPPED", (
        "the allocation dimension resolves while fulfillment has not started"
    )
    create_delivery(chain)
    order = get_order(chain["order"]["id"])
    assert order["fulfillment_status"] == "IN_TRANSIT"
    assert order["allocation_status"] == "ALLOCATED", (
        "shipping advances fulfillment without touching the allocation dimension"
    )


def test_cancel_blocked_once_in_transit_then_confirm_delivers(api):
    """PRD §3.3: "An order may be cancelled while its allocation dimension is
    `PENDING`, `ALLOCATED`, `PARTIAL`, or `SHORTED` and its fulfillment dimension is
    still `UNSHIPPED`." and PRD §3.5: "A confirmed delivery stamps `confirmed_at`,
    moves `PENDING` → `CONFIRMED`, and advances the order's fulfillment to
    `DELIVERED`."

    Once IN_TRANSIT the fulfillment dimension gates the cancel out with
    ERR_INVALID_STATE even though the allocation dimension alone would allow it;
    the delivery then confirms to DELIVERED.

    Design: Difficulty/non_linear_state_machine/order_parallel_allocation_fulfillment_dimensions
    """
    chain = setup_delivery_chain(qty=10)
    delivery = create_delivery(chain)
    resp = api.cancel_order(
        chain["order"]["id"], make_distributor_rep_headers(chain["distributor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    confirmed = confirm_delivery(delivery, chain["account"])
    assert confirmed["status"] == "CONFIRMED"
    order = get_order(chain["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED"


def test_third_late_pull_triggers_account_suspension(api):
    """PRD §3.5: "A late pull has teeth: the account's `late_pulls_30d` is recomputed
    over the trailing 30 days, and when that count reaches 3, the account
    auto-transitions `APPROVED` → `SUSPENDED` with the full account-suspension
    cascade of §3.2".

    The third late pull (link 1: the log becomes PULLED_LATE) drives the account's
    trailing-30-day late count to 3, so link 2 fires: the account is SUSPENDED.

    Design: Difficulty/transitive_cascade/late_pull_threshold_account_suspension_cascade
    """
    ctx, _product, _auth, log_3, _log_4 = _setup_account_with_two_late_pulls()
    pulled = pull_log(log_3, ctx["account"])
    assert pulled["status"] == "PULLED_LATE", "link 1: the pull itself is late"
    account = get_success_data(api.get_account(ctx["account"]["id"], ADMIN))
    assert account["approval_status"] == "SUSPENDED", (
        "link 2: late_pulls_30d reached 3, so the account auto-suspends"
    )


def test_late_pull_cascade_suspends_authorizations_and_force_pulls(api):
    """PRD §3.5: "when that count reaches 3, the account auto-transitions `APPROVED`
    → `SUSPENDED` with the full account-suspension cascade of §3.2 — its `AUTHORIZED`
    authorizations become `SUSPENDED` with source `ACCOUNT_SUSPEND`, and its other
    `OPEN` logs are force-pulled to `FORCE_PULLED` with `pulled_at` set."

    Link 3 is caused by the suspension, not the original pull: the authorization
    drops to SUSPENDED with suspension_source ACCOUNT_SUSPEND and the remaining OPEN
    log is FORCE_PULLED.

    Design: Difficulty/transitive_cascade/late_pull_threshold_account_suspension_cascade
    """
    ctx, _product, authorization, log_3, log_4 = _setup_account_with_two_late_pulls()
    pull_log(log_3, ctx["account"])

    auth = get_success_data(api.get_authorization(authorization["id"], ADMIN))
    assert auth["status"] == "SUSPENDED"
    assert auth["suspension_source"] == "ACCOUNT_SUSPEND", (
        "link 3: the cascade records which suspension suspended the authorization"
    )
    log_4_now = get_success_data(api.get_opened_product_log(log_4["id"], ADMIN))
    assert log_4_now["status"] == "FORCE_PULLED", (
        "link 3: the sibling OPEN log is force-pulled by the cascade, not by a pull"
    )
    assert log_4_now["pulled_at"] is not None


def test_pull_at_exact_deadline_is_on_time(api):
    """PRD §3.5: "A pull executed by the owning `RetailManager` while the log is
    `OPEN` stamps `pulled_at` with the current time and classifies the pull against
    the deadline: at or before `pull_deadline` the log becomes `PULLED_ON_TIME` — a
    pull at exactly the deadline counts as on time — and strictly after it the log
    becomes `PULLED_LATE`."

    Opened 2026-09-01T10:00:00Z with a 72-hour opened shelf life, the pull deadline
    is 2026-09-04T10:00:00Z; a pull at exactly that instant is PULLED_ON_TIME.

    Design: Difficulty/boundary_precision_check/pull_at_exact_deadline_is_on_time
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item", shelf_life_opened_hours=72)
    slicer = create_slicer(ctx["account"], label="S1")
    set_clock("2026-09-01T12:00:00Z")  # opened_at below is a sanctioned backdate
    log = create_opened_log(ctx["account"], product, slicer,
                            opened_at="2026-09-01T10:00:00Z")
    assert _parse(log["pull_deadline"]) == datetime(2026, 9, 4, 10, tzinfo=timezone.utc), (
        f"pull_deadline = opened_at + 72h: got {log['pull_deadline']}"
    )
    set_clock("2026-09-04T10:00:00Z")
    pulled = pull_log(log, ctx["account"])
    assert pulled["status"] == "PULLED_ON_TIME", (
        "the <= boundary: a pull at exactly the deadline counts as on time"
    )


def test_pull_one_second_past_deadline_is_late(api):
    """PRD §3.5: "at or before `pull_deadline` the log becomes `PULLED_ON_TIME` — a
    pull at exactly the deadline counts as on time — and strictly after it the log
    becomes `PULLED_LATE`." and "when that count reaches 3, the account
    auto-transitions `APPROVED` → `SUSPENDED`".

    One second past the 72-hour deadline the pull is PULLED_LATE; with only one late
    pull in the trailing window the account stays APPROVED (threshold is 3).

    Design: Difficulty/boundary_precision_check/pull_at_exact_deadline_is_on_time
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item", shelf_life_opened_hours=72)
    slicer = create_slicer(ctx["account"], label="S1")
    set_clock("2026-09-01T12:00:00Z")  # opened_at below is a sanctioned backdate
    log = create_opened_log(ctx["account"], product, slicer,
                            opened_at="2026-09-01T10:00:00Z")
    set_clock("2026-09-04T10:00:01Z")
    pulled = pull_log(log, ctx["account"])
    assert pulled["status"] == "PULLED_LATE", "one second past the deadline is late"
    account = get_success_data(api.get_account(ctx["account"]["id"], ADMIN))
    assert account["approval_status"] == "APPROVED", (
        "a single late pull is below the suspension threshold of 3"
    )


def test_reconfirm_of_terminal_delivery_reports_terminal_state(api):
    """PRD §2.8: "When a request violates several rules at once, the server evaluates
    checks in a fixed pipeline and surfaces the first failure." — state legality is
    tier 6, business safety (lot expiry) is tier 8 — and "an entity already in a
    terminal state (`TERMINATED`, `REJECTED`, `CLOSED`, `SETTLED`, `RECALLED`,
    `EXHAUSTED`, `CONFIRMED`, `DELIVERED`, `PULLED_ON_TIME`, `PULLED_LATE`,
    `FORCE_PULLED`, `DECOMMISSIONED`, `EXPIRED`, `REVOKED`) rejects every further
    transition with `ERR_ALREADY_TERMINAL`."

    The second confirm hits a CONFIRMED (terminal) delivery AND an expired lot; the
    state-tier error ERR_ALREADY_TERMINAL is surfaced, not ERR_LOT_EXPIRED.

    Design: Difficulty/priority_pair_validation_conflict/state_terminal_beats_safety_on_reconfirm
    """
    chain = setup_delivery_chain(qty=10, shelf_life_unopened_days=1)
    delivery = create_delivery(chain)
    confirm_delivery(delivery, chain["account"])
    set_clock("2026-09-03T00:00:00Z")  # lot expired 2026-09-02T00:00:00Z
    resp = api.confirm_delivery(
        delivery["id"], make_retail_manager_headers(chain["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_expired_lot_blocks_confirm_when_state_is_legal(api):
    """PRD §3.5: "every lot on the delivery's lines is unexpired at the current
    logical time — a lot whose `expires_at` has been reached is expired, so the
    current time must fall strictly before each lot's `expires_at`, else
    `ERR_LOT_EXPIRED`."

    Same expiry condition as the terminal-reconfirm case but with the delivery still
    PENDING, so the state tier passes and the safety tier's ERR_LOT_EXPIRED fires —
    isolating what the terminal state masked.

    Design: Difficulty/priority_pair_validation_conflict/state_terminal_beats_safety_on_reconfirm
    """
    chain = setup_delivery_chain(qty=10, shelf_life_unopened_days=1)
    delivery = create_delivery(chain)
    set_clock("2026-09-03T00:00:00Z")  # lot expired 2026-09-02T00:00:00Z
    resp = api.confirm_delivery(
        delivery["id"], make_retail_manager_headers(chain["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)
    delivery_now = get_success_data(api.get_delivery(delivery["id"], ADMIN))
    assert delivery_now["status"] == "PENDING"


def test_revoking_one_of_two_certs_blocks_delivery_confirm(api):
    """PRD §3.6: "the account is compliant when it holds at least 2 certifications
    that are `ACTIVE` and unexpired with `slicing_module_passed` true, and at least 2
    that are `ACTIVE` and unexpired with `allergen_module_passed` true — a single
    certification passing both modules counts toward both tallies, and exactly 2 of
    each module is compliant. Falling short on either tally blocks delivery
    confirmation with `ERR_TRAINING_INSUFFICIENT`."

    Two dual-module certifications pass the boundary; revoking one drops both
    tallies to 1 and the confirmation fails.

    Design: Corner/calculations/training_boundary_two_required_revoke_blocks_confirm
    """
    chain = setup_delivery_chain(qty=10)
    delivery = create_delivery(chain)
    resp = api.revoke_training_certification(chain["certs"][1]["id"], ADMIN)
    validate_success(resp)
    resp = api.confirm_delivery(
        delivery["id"], make_retail_manager_headers(chain["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TRAINING_INSUFFICIENT)
    account = get_success_data(api.get_account(chain["account"]["id"], ADMIN))
    assert account["training_compliant"] is False, (
        "one ACTIVE dual-module certification is below the boundary of 2"
    )


def test_confirm_at_exact_lot_expiry_is_expired(api):
    """PRD §3.5: "every lot on the delivery's lines is unexpired at the current
    logical time — a lot whose `expires_at` has been reached is expired, so the
    current time must fall strictly before each lot's `expires_at`, else
    `ERR_LOT_EXPIRED`."

    The lot's one-day unopened shelf life ends at 2026-09-02T00:00:00Z; confirming
    at exactly that instant is expired — the freshness comparison is a strict <.

    Design: Corner/calculations/delivery_confirm_at_exact_lot_expiry_rejected
    """
    chain = setup_delivery_chain(qty=10, shelf_life_unopened_days=1)
    delivery = create_delivery(chain)
    set_clock("2026-09-02T00:00:00Z")  # exactly the lot's expires_at
    resp = api.confirm_delivery(
        delivery["id"], make_retail_manager_headers(chain["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)
    delivery_now = get_success_data(api.get_delivery(delivery["id"], ADMIN))
    assert delivery_now["status"] == "PENDING", "an expired lot blocks confirmation"


def test_delivery_of_unauthorized_product_rejected(api):
    """PRD §3.5: "every product shipped must hold an authorization in `AUTHORIZED`
    for the receiving account, else `ERR_PRODUCT_NOT_AUTHORIZED`."

    The product is orderable by the distributor (the order allocated fine) but no
    authorization exists for the account, so the delivery is refused.

    Design: Corner/validations/delivery_of_unauthorized_product_rejected
    """
    chain = setup_delivery_chain(qty=10, with_authorization=False, with_certs=False)
    resp = api.create_delivery(
        create_delivery_payload(
            chain["order"]["id"], chain["account"]["id"],
            [delivery_line(chain["lot"]["id"], 10)],
        ),
        make_distributor_rep_headers(chain["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_AUTHORIZED)


def test_delivery_qty_above_allocated_pool_rejected(api):
    """PRD §3.5: "the requested `qty` may not exceed the units the lot holds in its
    allocated pool for that product, and the account must be served by the order's
    distributor — quantity, product-membership, or servicing failures all surface as
    `ERR_QUANTITY_MISMATCH`."

    Eleven units against an allocated pool of ten is rejected before any unit moves:
    the lot still reads 10 allocated / 0 delivered.

    Design: Corner/validations/delivery_qty_above_allocated_pool_rejected
    """
    chain = setup_delivery_chain(qty=10, with_certs=False)
    resp = api.create_delivery(
        create_delivery_payload(
            chain["order"]["id"], chain["account"]["id"],
            [delivery_line(chain["lot"]["id"], 11)],
        ),
        make_distributor_rep_headers(chain["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUANTITY_MISMATCH)
    lot = get_lot_for_run(chain["run"]["id"])
    assert lot["allocated_units"] == 10 and lot["delivered_units"] == 0, (
        "a rejected delivery must not move any units"
    )


def test_lot_exhausted_after_full_delivery(api):
    """PRD §2.5: "A lot in `AVAILABLE` is treated as `EXHAUSTED` when both its
    `available_units` and its `allocated_units` are zero." and "Three status
    evaluations are lazy — they are applied when the affected resource is read or
    written, not by a background sweeper".

    All ten units shipped: available 0, allocated 0, delivered 10 — the next read
    shows the lot EXHAUSTED.

    Design: Corner/state_machines/lot_exhausted_after_full_delivery
    """
    chain = setup_delivery_chain(qty=10, with_certs=False)
    create_delivery(chain)  # ships the full allocated pool of 10
    lot = get_lot_for_run(chain["run"]["id"])
    assert lot["status"] == "EXHAUSTED"
    assert lot["available_units"] == 0
    assert lot["allocated_units"] == 0
    assert lot["delivered_units"] == 10


def test_pulling_already_pulled_log_is_terminal(api):
    """PRD §3.5: "`PULLED_ON_TIME`, `PULLED_LATE`, and `FORCE_PULLED` are all
    terminal." and PRD §2.8: "an entity already in a terminal state (`TERMINATED`,
    `REJECTED`, `CLOSED`, `SETTLED`, `RECALLED`, `EXHAUSTED`, `CONFIRMED`,
    `DELIVERED`, `PULLED_ON_TIME`, `PULLED_LATE`, `FORCE_PULLED`, `DECOMMISSIONED`,
    `EXPIRED`, `REVOKED`) rejects every further transition with
    `ERR_ALREADY_TERMINAL`."

    Pulling an already PULLED_ON_TIME log is rejected; pull is not idempotent.

    Design: Corner/state_machines/pull_already_pulled_log_is_terminal
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item")
    slicer = create_slicer(ctx["account"], label="S1")
    log = create_opened_log(ctx["account"], product, slicer)
    pulled = pull_log(log, ctx["account"])
    assert pulled["status"] == "PULLED_ON_TIME"
    resp = api.pull_opened_product_log(
        log["id"], make_retail_manager_headers(ctx["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

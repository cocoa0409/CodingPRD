"""Change orders on the show floor: the review cycle, the polymorphic target
check, apply-time repricing at the tier in force right now, the optimistic
concurrency pin on the target order, and the rebill cascade that runs from an
application all the way down to a cancelled union crew."""

import pytest

from test_helpers import (
    TWO_LINE_ORDER,
    ApiErrorId,
    TEST_USERS,
    add_booth,
    apply_change_order,
    assert_change_order,
    assert_invoice,
    assert_labor_call,
    assert_posture,
    assert_service_order,
    assert_service_order_waterfall,
    create_approved_change_order,
    create_change_order_payload,
    get_booth,
    get_change_order,
    get_exhibitor,
    get_invoice,
    get_labor_call,
    get_order,
    get_show,
    order_version,
    raise_change_order,
    request_labor_call,
    review_change_order,
    set_clock,
    setup_issued_invoice,
    setup_order_ground,
    submit_change_order,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["show_operations_headers"]            # X-User-ID "ops-1"
OPS_ALT = TEST_USERS["show_operations_alt_headers"]    # X-User-ID "ops-2"

# The show floor is open and the discount deadline (2026-09-01) is long gone, so
# every tier derived from this clock position is ONSITE.
ONSITE_FLOOR_CLOCK = "2026-09-21T10:00:00Z"


# ---------------------------------------------------------------------------
# Apply-time tier versus creation-time tier
# ---------------------------------------------------------------------------

def _advance_tier_order_with_approved_change():
    """Order placed at the ADVANCE tier, clock repositioned onto the show floor,
    and an approved change order raising line 1 by two units waiting to land."""
    ground = setup_order_ground(show_status="ON_SITE", lines=TWO_LINE_ORDER)
    set_clock(ONSITE_FLOOR_CLOCK)
    ground["change_order"] = create_approved_change_order(
        ground["booth"]["id"], "SERVICE_ORDER", ground["order"]["id"],
        creator_headers=OPS, reviewer_headers=OPS_ALT)
    return ground


def test_advance_tier_order_reprices_every_line_at_the_apply_time_onsite_tier(api):
    """PRD §3.5: "Deadline tiering is decided once, at creation, from the logical
    clock alone."
    PRD §3.5: "If `ordered_at` is at or before the show's `discount_deadline`,
    the order's `deadline_tier` is `ADVANCE` and its `tier_multiplier` is 1.00."
    PRD §3.8: "On success the target order's lines are mutated according to
    `delta_kind` and `delta_qty`, and then the **entire** order is repriced —
    every line, through the same line-pricing and waterfall rules of §3.5 — but
    at the deadline tier in force at the moment of application, derived afresh
    from the logical clock rather than from the tier stored on the order."
    PRD §3.8: "An order placed at `ADVANCE` and changed on the show floor
    therefore reprices every one of its lines at the `ONSITE` multiplier."
    PRD §3.5: "`subtotal_cents` is the exact integer sum of the per-line rounded
    values."

    Design: Difficulty/dual_variant_calc/service_order_creation_tier_vs_apply_time_tier
    """
    ground = setup_order_ground(show_status="ON_SITE", lines=TWO_LINE_ORDER)
    order = ground["order"]

    assert_service_order(order)
    assert order["deadline_tier"] == "ADVANCE", (
        "An order written at 2026-08-10T09:00:00Z sits before the show's "
        f"2026-09-01 discount deadline, got tier {order['deadline_tier']}")
    assert order["tier_multiplier"] == pytest.approx(1.00, abs=0.01), (
        f"The ADVANCE multiplier is 1.00, got {order['tier_multiplier']}")
    assert order["total_cents"] == 193858, (
        f"Two ADVANCE-priced lines total 193858 cents, got {order['total_cents']}")

    set_clock(ONSITE_FLOOR_CLOCK)
    change_order = create_approved_change_order(
        ground["booth"]["id"], "SERVICE_ORDER", order["id"],
        creator_headers=OPS, reviewer_headers=OPS_ALT)

    response = api.apply_change_order(
        change_order["id"],
        {"expected_service_order_version": order_version(order["id"])},
        OPS_ALT)
    validate_success(response, 200)

    repriced = get_order(order["id"])
    assert repriced["subtotal_cents"] == 418646, (
        "Both lines reprice at the 1.65 ONSITE multiplier for a subtotal of "
        f"418646 cents, got {repriced['subtotal_cents']}")
    assert repriced["total_cents"] == 421995, (
        "The repriced waterfall lands on 421995 cents, got "
        f"{repriced['total_cents']}")
    assert_service_order_waterfall(repriced)


def test_apply_records_price_delta_against_the_pre_change_total(api):
    """PRD §3.8: "`price_delta_cents` is recorded as the repriced `total_cents`
    minus the order's pre-change `total_cents`, and the target order's `version`
    increases by one."
    PRD §3.8: "On success the target order's lines are mutated according to
    `delta_kind` and `delta_qty`, and then the **entire** order is repriced —
    every line, through the same line-pricing and waterfall rules of §3.5 — but
    at the deadline tier in force at the moment of application, derived afresh
    from the logical clock rather than from the tier stored on the order."

    Design: Difficulty/dual_variant_calc/service_order_creation_tier_vs_apply_time_tier
    """
    ground = _advance_tier_order_with_approved_change()
    order_id = ground["order"]["id"]
    version_before = order_version(order_id)

    applied = apply_change_order(ground["change_order"]["id"], order_id,
                                 expected_service_order_version=version_before,
                                 headers=OPS_ALT)

    assert_change_order(applied)
    assert applied["status"] == "APPLIED", (
        f"Apply drives the change order to APPLIED, got {applied['status']}")
    assert applied["price_delta_cents"] == 228137, (
        "421995 repriced minus 193858 pre-change is a 228137 cent delta, got "
        f"{applied['price_delta_cents']}")

    repriced = get_order(order_id)
    assert repriced["version"] == version_before + 1, (
        "Applying a change order advances the target order's version by exactly "
        f"one: expected {version_before + 1}, got {repriced['version']}")


# ---------------------------------------------------------------------------
# The rebill cascade: apply -> rebill -> balance -> posture -> hold -> crew
# ---------------------------------------------------------------------------

def _rebill_cascade_ground():
    """An invoiced 193858 cent order against a 200000 cent credit limit, one
    REQUESTED crew attached to it, and an approved change order ready to apply."""
    ground = setup_issued_invoice(
        show_status="ON_SITE",
        lines=TWO_LINE_ORDER,
        credit_limit_cents=200000,
        with_jurisdiction=True,
        jurisdiction_overrides={"crew_max_size": 6},
    )
    set_clock(ONSITE_FLOOR_CLOCK)
    ground["labor_call"] = request_labor_call(
        ground["booth"]["id"], ground["jurisdiction"]["id"],
        service_order_id=ground["order"]["id"], crew_size=4)
    ground["change_order"] = create_approved_change_order(
        ground["booth"]["id"], "SERVICE_ORDER", ground["order"]["id"],
        creator_headers=OPS, reviewer_headers=OPS_ALT)
    return ground


def test_apply_on_an_invoiced_order_rebills_the_carrying_invoice(api):
    """PRD §3.8: "When the target order's `billing_status` was already
    `INVOICED`, application also starts the billing cascade: the order moves to
    `REBILL_PENDING`, the carrying invoice's `adjustments_cents` accumulates the
    `price_delta_cents`, the invoice's `total_cents` is recomputed, and the
    exhibitor's `account_balance_cents` is recomputed from scratch."
    PRD §3.9: "`subtotal_cents` is the sum of `total_cents` across the listed
    orders as of issue time; `total_cents` is `subtotal_cents` plus
    `adjustments_cents`, where `adjustments_cents` is the running sum of applied
    change-order price deltas and refurbishment credits."

    Design: Difficulty/transitive_cascade/change_order_apply_rebills_invoice_breaches_credit_freezes_booth_cancels_labor
    """
    ground = _rebill_cascade_ground()
    order_id = ground["order"]["id"]

    exhibitor_before = get_exhibitor(ground["exhibitor"]["id"])
    assert exhibitor_before["account_balance_cents"] == 193858, (
        "The issued invoice puts exactly the order total on the balance, got "
        f"{exhibitor_before['account_balance_cents']}")
    # PRD 2.10 clause 7: the approved change order waiting to land already
    # restricts the booth; only a FROZEN booth would block the application.
    assert_posture(get_booth(ground["booth"]["id"]), "RESTRICTED",
                   "CHANGE_ORDER_APPROVED")
    assert get_order(order_id)["billing_status"] == "INVOICED", (
        "The order must be INVOICED before the application to start the rebill")

    applied = apply_change_order(ground["change_order"]["id"], order_id,
                                 headers=OPS_ALT)

    assert applied["status"] == "APPLIED", (
        f"Apply drives the change order to APPLIED, got {applied['status']}")
    assert applied["price_delta_cents"] == 228137, (
        f"The recorded delta is 228137 cents, got {applied['price_delta_cents']}")

    order = get_order(order_id)
    assert order["total_cents"] == 421995, (
        f"The repriced order totals 421995 cents, got {order['total_cents']}")
    assert order["billing_status"] == "REBILL_PENDING", (
        "An already-invoiced order moves to REBILL_PENDING on application, got "
        f"{order['billing_status']}")

    invoice = get_invoice(ground["invoice"]["id"])
    assert_invoice(invoice)
    assert invoice["adjustments_cents"] == 228137, (
        "The invoice accumulates the price delta into adjustments_cents, got "
        f"{invoice['adjustments_cents']}")
    assert invoice["total_cents"] == 421995, (
        "193858 subtotal plus 228137 adjustments is 421995 cents, got "
        f"{invoice['total_cents']}")


def test_rebill_breach_freezes_the_booth_holds_the_order_and_cancels_the_crew(api):
    """PRD §3.8: "When the target order's `billing_status` was already
    `INVOICED`, application also starts the billing cascade: the order moves to
    `REBILL_PENDING`, the carrying invoice's `adjustments_cents` accumulates the
    `price_delta_cents`, the invoice's `total_cents` is recomputed, and the
    exhibitor's `account_balance_cents` is recomputed from scratch."
    PRD §3.9: "It is the sum of `total_cents` over that exhibitor's invoices
    whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of
    `settled_cents` over those same invoices, minus the sum of
    `settlement_cents` over that exhibitor's damage claims whose `status` is
    `SETTLED`."
    PRD §2.10: "The exhibitor's `account_balance_cents` is strictly greater than
    its `credit_limit_cents` — posture `FROZEN`, reason `CREDIT_LIMIT_BREACHED`."
    PRD §3.5: "An order in `PENDING` moves to `HELD` purely as a cascade when
    its booth's posture becomes `FROZEN`, whether through exhibitor suspension
    or a credit-limit breach; that same cascade cancels every labor call on the
    order that was still `REQUESTED`, then recomputes the show's
    `cancelled_labor_call_count` and its `committed_labor_hours`."
    PRD §3.7: "Either way the show's `cancelled_labor_call_count` increases by
    one and its `committed_labor_hours` are recomputed — which releases the
    crew-hours when the call had been `DISPATCHED` and changes nothing when it
    was merely `REQUESTED`, since a requested call never contributed."

    Design: Difficulty/transitive_cascade/change_order_apply_rebills_invoice_breaches_credit_freezes_booth_cancels_labor
    """
    ground = _rebill_cascade_ground()
    order_id = ground["order"]["id"]
    call_id = ground["labor_call"]["id"]

    assert get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"] == 193858
    # PRD 2.10 clause 7: the approved change order restricts but does not freeze
    # the booth, so no credit clause is holding it yet.
    assert_posture(get_booth(ground["booth"]["id"]), "RESTRICTED",
                   "CHANGE_ORDER_APPROVED")
    assert get_labor_call(call_id)["status"] == "REQUESTED", (
        "The crew is still merely requested before the change order lands")

    applied = apply_change_order(ground["change_order"]["id"], order_id,
                                 headers=OPS_ALT)
    assert applied["price_delta_cents"] == 228137, (
        f"The recorded delta is 228137 cents, got {applied['price_delta_cents']}")

    # Link 1 and 2: the order rebills and the invoice total is rebuilt.
    order = get_order(order_id)
    assert order["billing_status"] == "REBILL_PENDING", (
        f"Expected REBILL_PENDING, got {order['billing_status']}")
    invoice = get_invoice(ground["invoice"]["id"])
    assert invoice["total_cents"] == 421995, (
        f"The rebilled invoice totals 421995 cents, got {invoice['total_cents']}")

    # Link 3: the exhibitor balance is rebuilt from the issued invoice.
    exhibitor = get_exhibitor(ground["exhibitor"]["id"])
    assert exhibitor["account_balance_cents"] == 421995, (
        "The balance is recomputed from scratch onto 421995 cents, got "
        f"{exhibitor['account_balance_cents']}")

    # Link 4: 421995 is strictly greater than the 200000 limit, so the booth freezes.
    assert_posture(get_booth(ground["booth"]["id"]), "FROZEN",
                   "CREDIT_LIMIT_BREACHED")

    # Link 5: the pending order is held by the freeze.
    assert order["fulfillment_status"] == "HELD", (
        "A PENDING order on a newly frozen booth moves to HELD, got "
        f"{order['fulfillment_status']}")

    # Link 6: the requested crew on that held order is released.
    labor_call = get_labor_call(call_id)
    assert_labor_call(labor_call)
    assert labor_call["status"] == "CANCELLED", (
        "The REQUESTED call attached to the held order is cancelled, got "
        f"{labor_call['status']}")
    show = get_show(ground["show"]["id"])
    assert show["cancelled_labor_call_count"] == 1, (
        "The cancellation lifts the show's cancelled_labor_call_count to 1, got "
        f"{show['cancelled_labor_call_count']}")


# ---------------------------------------------------------------------------
# The review cycle
# ---------------------------------------------------------------------------

def test_returned_change_order_resubmits_through_the_same_submit_endpoint(api):
    """PRD §3.8: "A `decision` of `RETURN` moves `UNDER_REVIEW → RETURNED`,
    leaving `price_delta_cents` null and re-opening the submit cycle so the
    exhibitor can resubmit."
    PRD §3.8: "Submitting moves a change order from `DRAFT` or from `RETURNED`
    into `SUBMITTED`, requires the booth not to be `FROZEN`, and bumps the
    change order's `version`."
    PRD §3.8: "The change order is born `DRAFT`, with `created_by_user_id` taken
    from the acting `X-User-ID`, `reviewed_by_user_id` null and
    `price_delta_cents` null."
    PRD §2.10: "When no clause holds, `posture` is `OPEN` and `posture_reason`
    is null."

    Design: Corner/state_machines/change_order_returned_then_resubmitted_cycle
    """
    ground = setup_order_ground(show_status="ON_SITE", lines=TWO_LINE_ORDER)
    booth_id = ground["booth"]["id"]

    change_order = raise_change_order(
        booth_id, "SERVICE_ORDER", ground["order"]["id"], actor_headers=OPS,
        delta_qty=1, reason="One more drop")
    submit_change_order(change_order["id"], OPS)
    review_change_order(change_order["id"], "START_REVIEW", headers=OPS_ALT)
    returned = review_change_order(change_order["id"], "RETURN",
                                   note="Quantify the drops", headers=OPS_ALT)
    assert returned["status"] == "RETURNED", (
        f"A RETURN decision lands on RETURNED, got {returned['status']}")

    response = api.submit_change_order(change_order["id"], OPS)
    resubmitted = validate_success(response, 200)

    assert_change_order(resubmitted)
    assert resubmitted["status"] == "SUBMITTED", (
        "A RETURNED change order re-enters SUBMITTED through the same submit "
        f"endpoint, got {resubmitted['status']}")
    assert resubmitted["price_delta_cents"] is None, (
        "price_delta_cents stays null for the whole review loop, got "
        f"{resubmitted['price_delta_cents']}")
    assert resubmitted["created_by_user_id"] == "ops-1", (
        "The creator recorded at DRAFT survives the cycle, got "
        f"{resubmitted['created_by_user_id']}")
    assert_posture(get_booth(booth_id), "OPEN", None)


# ---------------------------------------------------------------------------
# The polymorphic target check
# ---------------------------------------------------------------------------

def test_change_order_targeting_another_booths_service_order_is_rejected(api):
    """PRD §3.8: "The referenced row's own `booth_id` must equal the change
    order's `booth_id`, and a target that does not exist for its declared type,
    or that sits on a different booth, is refused with
    `ERR_CHANGE_TARGET_MISMATCH` — a check that runs both at creation and again
    at apply time."

    Design: Corner/validations/change_order_targeting_another_booths_order_rejected
    """
    ground = setup_order_ground(show_status="ON_SITE", lines=TWO_LINE_ORDER)
    other_booth = add_booth(ground, "1026", booth_type="INLINE")

    response = api.create_change_order(
        create_change_order_payload(other_booth["id"], "SERVICE_ORDER",
                                    ground["order"]["id"],
                                    delta_qty=1, reason="Wrong booth"),
        OPS)
    validate_error(response, ApiErrorId.ERR_CHANGE_TARGET_MISMATCH, 422)

    listed, meta = validate_paginated(
        api.list_change_orders(OPS, params={"booth_id": other_booth["id"]}))
    assert listed == [], (
        f"The refused change order must not have been written, got {listed}")
    assert meta["total_count"] == 0, (
        "No change order exists on booth 1026, got total_count "
        f"{meta['total_count']}")


# ---------------------------------------------------------------------------
# Optimistic concurrency on the target service order
# ---------------------------------------------------------------------------

def test_stale_expected_service_order_version_rejects_the_apply(api):
    """PRD §2.7: "Applying a change order — `POST /change-orders/{id}/apply` —
    requires `expected_service_order_version`, carrying the client's last
    observed `version` of the target `ServiceOrder`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_SERVICE_ORDER_VERSION`
    (HTTP 412)."
    PRD §2.7: "If the declared value does not equal the parent row's current
    `version` at the moment the write is processed, the write is rejected
    outright and no state changes."

    Design: Corner/cross_cutting_layers/occ_stale_service_order_version_rejects_change_order_apply
    """
    ground = setup_order_ground(show_status="ON_SITE", lines=TWO_LINE_ORDER)
    order_id = ground["order"]["id"]
    change_order = create_approved_change_order(
        ground["booth"]["id"], "SERVICE_ORDER", order_id,
        creator_headers=OPS, reviewer_headers=OPS_ALT,
        delta_qty=2, reason="Two extra drops")

    stale_version = order_version(order_id) - 1
    response = api.apply_change_order(
        change_order["id"],
        {"expected_service_order_version": stale_version},
        OPS_ALT)
    validate_error(response, ApiErrorId.ERR_STALE_SERVICE_ORDER_VERSION, 412)

    unchanged = get_change_order(change_order["id"])
    assert unchanged["status"] == "APPROVED", (
        "A rejected apply leaves the change order APPROVED, got "
        f"{unchanged['status']}")
    assert unchanged["price_delta_cents"] is None, (
        "No delta is computed when the apply is refused, got "
        f"{unchanged['price_delta_cents']}")

    order = get_order(order_id)
    assert order["total_cents"] == 193858, (
        f"The target order is untouched at 193858 cents, got {order['total_cents']}")
    assert order["deadline_tier"] == "ADVANCE", (
        "No repricing ran, so the creation-time ADVANCE tier stands, got "
        f"{order['deadline_tier']}")

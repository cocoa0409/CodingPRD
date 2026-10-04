"""Order composition: bundling, price protection, discounts and cadence advance.

Implements SCAFFOLD.yaml SS1.3 calculations `autoship_price_protection`,
`autoship_discount_cents`, `autoship_promo_reconciliation` and
`advance_item_cadence`, in the validation order fixed by PRD SS2.12.
"""

import clock
import db
import serializers
from errors import fail
from services import calculations, plans as plan_svc
from services.constants import (
    COLD_PACK_FEE_CENTS,
    EXPEDITED_SHIPPING_FEE_CENTS,
    FIRST_ORDER_DISCOUNT_RATE,
    PROMO_DISCOUNT_CENTS,
    PROMO_MIN_SUBTOTAL_CENTS,
    RECURRING_DISCOUNT_RATE,
)


def orders_of_plan(plan_id):
    return calculations.orders_of_plan(plan_id)


def has_prior_composed_order(plan_id):
    return any(
        o.get("autoship_plan_id") == plan_id for o in db.ORDERS.values()
    )


def lines_of_order(order_id):
    rows = [l for l in db.ORDER_LINES.values() if l.get("order_id") == order_id]
    return sorted(rows, key=lambda l: (l.get("line_position", 0), l.get("created_at") or ""))


def prospect_line(item, position):
    """Price one prospective line using autoship_price_protection."""
    product = db.PRODUCTS.get(item.get("product_id"))
    protected = item.get("price_protected_unit_price_cents")
    guard = serializers.protection_guard(protected)
    if protected is None:
        line_unit_price = int(item.get("unit_price_cents", 0) or 0)
    else:
        line_unit_price = min(int(item.get("unit_price_cents", 0) or 0), guard)
    quantity = int(item.get("default_quantity", 0) or 0)
    return {
        "item": item,
        "product": product,
        "quantity": quantity,
        "line_position": position,
        "line_unit_price_cents": line_unit_price,
        "line_item_subtotal_cents": line_unit_price * quantity,
        "line_requires_clinic_auth": bool(
            product and product.get("medication_scope") == "PRESCRIPTION"
        ),
    }


def prescription_of_item(item_id):
    return plan_svc.prescription_for_item(item_id)


def _rx_currency_failure(rx):
    """ERR_RX_EXPIRED trigger: EXPIRED status, past expiry, or grace exceeded."""
    from services.constants import AUTHORIZATION_GRACE_DAYS, AUTHORIZATION_VALID_DAYS

    if rx.get("rx_status") == "EXPIRED":
        return True
    expires_at = rx.get("verification_expires_at")
    if expires_at is not None:
        if clock.current() >= expires_at:
            return True
        confirmed_at = clock.add_days(expires_at, -AUTHORIZATION_VALID_DAYS)
        if clock.whole_days_between(confirmed_at, clock.current()) > AUTHORIZATION_GRACE_DAYS:
            return True
    return False


def compose(plan, promotion_code, override_code):
    """Compose an order from the plan's due items; returns the new Order row."""
    now = clock.current()
    pet = db.PETS.get(plan.get("pet_id"))

    due = calculations.due_items_for_plan(plan["id"])
    prospect = [prospect_line(item, idx + 1) for idx, item in enumerate(due)]

    # --- business ladder, in the PRD SS2.12 order ---------------------------
    # 11: prescription coverage (an EXPIRED prescription passes here).
    for line in prospect:
        if not line["line_requires_clinic_auth"]:
            continue
        rx = prescription_of_item(line["item"]["id"])
        if rx is None or rx.get("rx_status") not in ("VERIFIED", "EXPIRED"):
            fail(
                "ERR_RX_NOT_VERIFIED",
                "A prescription-scope item must carry a VERIFIED prescription "
                "before it can be composed.",
            )

    # 18: prescription currency.
    for line in prospect:
        if not line["line_requires_clinic_auth"]:
            continue
        rx = prescription_of_item(line["item"]["id"])
        if rx is None:
            continue
        if _rx_currency_failure(rx):
            fail(
                "ERR_RX_EXPIRED",
                "The prescription is expired or its authorization is outside the "
                "usable interval.",
            )

    # 22: pet must be ACTIVE.
    if pet is not None and pet.get("pet_status") != "ACTIVE":
        fail("ERR_PET_INACTIVE", "The plan's owning pet is not ACTIVE.")

    # --- discounts ----------------------------------------------------------
    first_order = not has_prior_composed_order(plan["id"])
    rate = FIRST_ORDER_DISCOUNT_RATE if first_order else RECURRING_DISCOUNT_RATE

    merchandise_subtotal_cents = sum(l["line_item_subtotal_cents"] for l in prospect)

    raw_discount = 0
    for line in prospect:
        item = line["item"]
        if item.get("price_protected_unit_price_cents") is not None:
            base = int(item.get("unit_price_cents", 0) or 0) * line["quantity"]
        else:
            base = line["line_item_subtotal_cents"]
        line["line_autoship_discount_cents"] = calculations.round_half_up(base * rate, 0)
        raw_discount += line["line_autoship_discount_cents"]

    residual_promo_discount_cents = 0
    autoship_discount_cents = raw_discount
    if promotion_code:
        if plan.get("autoship_discount_eligibility") == "INELIGIBLE":
            fail(
                "ERR_PROMO_STACKING_NOT_ALLOWED",
                "A plan whose discount eligibility is revoked accepts no promotion.",
            )
        if raw_discount > 0:
            fail(
                "ERR_PROMO_STACKING_NOT_ALLOWED",
                "A promotion never stacks on a nonzero autoship discount.",
            )
        if merchandise_subtotal_cents >= PROMO_MIN_SUBTOTAL_CENTS:
            residual_promo_discount_cents = min(
                PROMO_DISCOUNT_CENTS, merchandise_subtotal_cents - raw_discount
            )
            autoship_discount_cents = raw_discount + residual_promo_discount_cents

    cold_pack_fee_cents = (
        COLD_PACK_FEE_CENTS if any(l["product"] and l["product"].get("cold_pack_required") for l in prospect) else 0
    )
    expedited_shipping_fee_cents = 0
    for line in prospect:
        rx = prescription_of_item(line["item"]["id"])
        if rx and rx.get("drug_schedule") in ("CII", "CIII"):
            expedited_shipping_fee_cents = EXPEDITED_SHIPPING_FEE_CENTS
            break

    order_total_components_sum = (
        merchandise_subtotal_cents
        - autoship_discount_cents
        + cold_pack_fee_cents
        + expedited_shipping_fee_cents
    )

    # --- commit ------------------------------------------------------------
    order = db.mint(
        db.ORDERS,
        autoship_plan_id=plan["id"],
        order_kind="FIRST" if first_order else "RECURRING",
        order_status="PLACED",
        composed_at=clock.iso(now),
        bundle_line_count=len(prospect),
        merchandise_subtotal_cents=merchandise_subtotal_cents,
        autoship_discount_cents=autoship_discount_cents,
        residual_promo_discount_cents=residual_promo_discount_cents,
        order_total_cents=order_total_components_sum,
        order_total_components_sum=order_total_components_sum,
        cold_pack_fee_cents=cold_pack_fee_cents,
        expedited_shipping_fee_cents=expedited_shipping_fee_cents,
        promotion_code=promotion_code,
        override_code=override_code,
        cancellation_reason=None,
        refunded_amount_cents=0,
        settlement_net_cents=order_total_components_sum,
        settlement_payment_balance_cents=0,
    )

    for line in prospect:
        item = line["item"]
        db.mint(
            db.ORDER_LINES,
            order_id=order["id"],
            autoship_item_id=item["id"],
            product_id=item.get("product_id"),
            quantity=line["quantity"],
            line_position=line["line_position"],
            line_unit_price_cents=line["line_unit_price_cents"],
            line_autoship_discount_cents=line["line_autoship_discount_cents"],
            line_item_subtotal_cents=line["line_item_subtotal_cents"],
            line_requires_clinic_auth=line["line_requires_clinic_auth"],
        )
        if item.get("price_protected_unit_price_cents") is None:
            # PRD SS3.4: the protected price is written from the comparison the
            # first composed order makes, locking the item's then-current price.
            item["price_protected_unit_price_cents"] = int(item.get("unit_price_cents", 0) or 0)
        item["protection_state"] = serializers.protection_state(item)

    # advance cadence exactly once per due item
    for item in calculations.due_items_for_plan(plan["id"]):
        calculations.advance_item_cadence(item)

    for item in db.AUTOSHIP_ITEMS.values():
        if item.get("autoship_plan_id") == plan["id"]:
            plan_svc.recompute_item_projections(item)

    db.touch(plan)
    plan_svc.recompute_plan_aggregates(plan)
    return order


def apply_cadence_change(item, new_cadence, new_quantity):
    """Write the new cadence/quantity, advance the due date, recompute state."""
    if new_cadence is not None:
        item["cadence_days"] = new_cadence
    if new_quantity is not None:
        item["default_quantity"] = new_quantity
    item["autoship_item_next_due_date"] = clock.add_days(clock.current(), item["cadence_days"])
    db.touch(item)
    plan_svc.recompute_item_projections(item)
    plan = db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id"))
    if plan is not None:
        plan_svc.recompute_plan_aggregates(plan)
    return item
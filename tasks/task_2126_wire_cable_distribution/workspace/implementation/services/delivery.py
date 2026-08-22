"""The delivery cascade (PRD Section 3.8) and the reel-return cascade
(PRD Section 3.9).  Cascades are immediate and synchronous.
"""
import clock
import db
import calculations as calc
from services import allocation as allocation_svc
from services import credit, lookup, pricing


def heaviest_pick_reel_lbs(order_id):
    """Greatest reel_weight_lbs among the order's COMMITTED, PICK-mode allocations."""
    heaviest = 0
    for alloc in lookup.allocations_of_order(order_id):
        if alloc["status"] != "COMMITTED" or alloc["commit_mode"] != "PICK":
            continue
        reel = db.reels.get(alloc["reel_id"])
        if reel is None:
            continue
        product = db.products.get(reel["product_id"])
        if product is None:
            continue
        if calc.dec(product["reel_weight_lbs"]) > calc.dec(heaviest):
            heaviest = product["reel_weight_lbs"]
    return calc.as_number(heaviest)


def deliver_cascade(order):
    """Five links fire in order."""
    now = clock.now()
    stamp = clock.iso(now)

    # --- Cascade link 1: the order moves STAGED -> DELIVERED -------------
    order["fulfillment_status"] = "DELIVERED"
    order["delivered_at"] = stamp
    db.touch(order)

    # --- Cascade link 2: allocations consumed, picked reels on jobsite ----
    picked = []
    for alloc in lookup.allocations_of_order(order["id"]):
        if alloc["status"] != "COMMITTED":
            continue
        alloc["status"] = "CONSUMED"
        db.touch(alloc)
        if alloc["commit_mode"] == "PICK":
            picked.append(alloc)
            reel = db.reels.get(alloc["reel_id"])
            if reel is not None:
                reel["status"] = "ON_JOBSITE"
                reel["delivered_sales_order_id"] = order["id"]
                reel["delivered_at"] = stamp
                reel["allocated_length_ft"] = 0
                db.touch(reel)
    order["billing_status"] = "INVOICED"

    # --- Cascade link 3: repricing under the INVOICED variant -------------
    index_entry = lookup.index_entry_on_or_before(clock.date_of(now))
    if index_entry is not None:
        computed, rollup = pricing.price_order_invoiced(order, index_entry)
        variance = 0
        for item in computed:
            line = item["line"]
            line["invoiced_extended_cents"] = item["extended_cents"]
            variance += item["extended_cents"] - line["quoted_extended_cents"]
            db.touch(line)
        order["invoiced_total_cents"] = rollup["total_cents"]
        order["metal_variance_cents"] = variance

    deposit_charged = 0
    for alloc in picked:
        reel = db.reels.get(alloc["reel_id"])
        if reel is None:
            continue
        product = db.products.get(reel["product_id"])
        if product is not None:
            deposit_charged += product["reel_deposit_cents"]
    order["deposit_charged_cents"] = deposit_charged
    db.touch(order)

    # --- Cascade link 4: the customer's balance and liability rise --------
    customer = db.customers.get(order["customer_id"])
    if customer is not None:
        customer["open_balance_cents"] += (order["invoiced_total_cents"] or 0) + deposit_charged
        customer["deposit_liability_cents"] += deposit_charged
        db.touch(customer)
        # --- Cascade link 5: posture re-evaluation and its own cascades ---
        credit.apply_posture(customer)


def return_cascade(order_line, order, reel, product, condition):
    """Reel ON_JOBSITE -> IN_STOCK plus the deposit-credit cascade."""
    now = clock.now()

    reel["status"] = "IN_STOCK"
    reel["delivered_at"] = None
    # delivered_sales_order_id is deliberately RETAINED as the shipment record.
    db.touch(reel)

    delivered_at = clock.parse_dt(order["delivered_at"])
    credit_cents = calc.reel_deposit_credit(product, delivered_at, now, condition)

    # --- Cascade link 1: deposit ledger ----------------------------------
    order["deposit_credited_cents"] += credit_cents
    db.touch(order)

    customer = db.customers.get(order["customer_id"])
    if customer is not None:
        customer["deposit_liability_cents"] -= product["reel_deposit_cents"]
        customer["open_balance_cents"] -= credit_cents
        db.touch(customer)
        # --- Cascade links 2 and 3: posture, then HELD orders released ----
        credit.apply_posture(customer)

    # The money axis settles only when the last reel comes home.
    still_out = [
        r for r in db.reels.values()
        if r["delivered_sales_order_id"] == order["id"] and r["status"] == "ON_JOBSITE"
    ]
    if not still_out and order["billing_status"] == "INVOICED":
        order["billing_status"] = "CREDITED"
        db.touch(order)

    return credit_cents

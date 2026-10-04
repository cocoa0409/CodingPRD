"""Order/business services: exposure, reservations, cascades."""
import db
import errors
import helpers
from services import calc


def builder_of_order(order):
    job = helpers.get_or_404(db.jobs, order["job_id"])
    return helpers.get_or_404(db.builders, job["builder_id"]), job


def builder_exposure(builder_id):
    committed = 0
    settled = 0
    for order in db.sales_orders.values():
        job = db.jobs.get(order["job_id"])
        if not job or job["builder_id"] != builder_id:
            continue
        if order["order_status"] in ("CONFIRMED", "ON_HOLD"):
            committed += order["order_total_cents"]
        elif order["order_status"] == "DELIVERED":
            settled += order["delivered_total_cents"]
    return committed, settled


def job_exposure(job_id):
    committed = 0
    settled = 0
    for order in db.sales_orders.values():
        if order["job_id"] != job_id:
            continue
        if order["order_status"] in ("CONFIRMED", "ON_HOLD"):
            committed += order["order_total_cents"]
        elif order["order_status"] == "DELIVERED":
            settled += order["delivered_total_cents"]
    return committed, settled


def refresh_builder_exposure(builder):
    committed, settled = builder_exposure(builder["id"])
    builder["exposure_committed_cents"] = committed
    builder["exposure_settled_cents"] = settled


def refresh_job_exposure(job):
    committed, settled = job_exposure(job["id"])
    job["exposure_committed_cents"] = committed
    job["exposure_settled_cents"] = settled


def refresh_all_exposures():
    for b in db.builders.values():
        refresh_builder_exposure(b)
    for j in db.jobs.values():
        refresh_job_exposure(j)


def _lot_status(lot):
    if lot["qty_available_mbf"] > 0:
        return "ON_HAND"
    if lot["qty_reserved_mbf"] > 0:
        return "DEPLETED"
    if lot["qty_sold_mbf"] > 0:
        return "SOLD_OUT"
    return "ON_HAND"


def refresh_lot_status(lot):
    lot["lot_status"] = _lot_status(lot)
    lot["updated_at"] = helpers.stamp()
    lot["version"] += 1


def reserve_fifo(order):
    """Atomic FIFO reservation for the order's lines. Raises on shortfall."""
    # First pass: check total availability per line product
    for line in order["lines"]:
        total_avail = 0
        for lot in db.inventory_lots.values():
            if (lot["branch_id"] == order["branch_id"]
                    and lot["product_id"] == line["product_id"]):
                total_avail += lot["qty_available_mbf"]
        if total_avail < line["qty_mbf"]:
            raise errors.err_insufficient_inventory()
    # Second pass: reserve
    for line in order["lines"]:
        remaining = line["qty_mbf"]
        lots = [l for l in db.inventory_lots.values()
                if l["branch_id"] == order["branch_id"]
                and l["product_id"] == line["product_id"]
                and l["qty_available_mbf"] > 0]
        lots.sort(key=lambda l: (l["received_at"], l["created_at"], l["id"]))
        for lot in lots:
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_available_mbf"])
            lot["qty_reserved_mbf"] += take
            lot["qty_available_mbf"] -= take
            refresh_lot_status(lot)
            remaining -= take


def release_reservations(order):
    """Release this order's reserved quantities back to lots (FIFO order)."""
    for line in order["lines"]:
        remaining = line["qty_mbf"]
        lots = [l for l in db.inventory_lots.values()
                if l["branch_id"] == order["branch_id"]
                and l["product_id"] == line["product_id"]
                and l["qty_reserved_mbf"] > 0]
        lots.sort(key=lambda l: (l["received_at"], l["created_at"], l["id"]))
        for lot in lots:
            if remaining <= 0:
                break
            give_back = min(remaining, lot["qty_reserved_mbf"])
            lot["qty_reserved_mbf"] -= give_back
            lot["qty_available_mbf"] += give_back
            refresh_lot_status(lot)
            remaining -= give_back


def sell_reserved(order):
    """Convert this order's reserved qty into sold qty on the reserved lots (FIFO)."""
    for line in order["lines"]:
        remaining = line["qty_mbf"]
        lots = [l for l in db.inventory_lots.values()
                if l["branch_id"] == order["branch_id"]
                and l["product_id"] == line["product_id"]
                and l["qty_reserved_mbf"] > 0]
        lots.sort(key=lambda l: (l["received_at"], l["created_at"], l["id"]))
        for lot in lots:
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_reserved_mbf"])
            lot["qty_reserved_mbf"] -= take
            lot["qty_sold_mbf"] += take
            refresh_lot_status(lot)
            remaining -= take


def check_builder_active(builder):
    if builder["credit_status"] == "SUSPENDED":
        raise errors.err_builder_suspended()
    if builder["credit_status"] != "ACTIVE":
        raise errors.err_builder_not_active()


def confirm_order(order):
    """Runs the full confirm gauntlet; mutates order/builder/job/lots."""
    if order["order_status"] not in ("DRAFT", "ON_HOLD"):
        raise errors.err_invalid_state("Order must be DRAFT or ON_HOLD to confirm")
    builder, job = builder_of_order(order)
    check_builder_active(builder)

    # Specialty compliance
    for line in order["lines"]:
        product = helpers.get_or_404(db.products, line["product_id"])
        if product["requires_code_report"] and not order.get("code_report_reference"):
            raise errors.err_code_report_required()

    # Pricing (LOCK_AT_ACCEPT pins priced_week_start to confirm week)
    confirm_week = helpers.monday_of_week(db.clock_now())
    pricing_week = confirm_week
    total = calc.price_order(order, pricing_week)

    # Fiscal checks
    if builder["exposure_committed_cents"] + total > builder["credit_limit_cents"]:
        raise errors.err_credit_limit()
    if job["exposure_committed_cents"] + total > job["job_exposure_cap_cents"]:
        raise errors.err_job_cap()

    # FIFO reservation (atomic)
    reserve_fifo(order)

    # Commit
    order["order_total_cents"] = total
    order["priced_week_start"] = pricing_week
    order["order_status"] = "CONFIRMED"
    order["updated_at"] = helpers.stamp()
    order["version"] += 1

    builder["version"] += 1
    builder["updated_at"] = helpers.stamp()
    refresh_builder_exposure(builder)
    refresh_job_exposure(job)
    return order


def cancel_order(order):
    """Cancel from DRAFT, CONFIRMED, or ON_HOLD."""
    if order["order_status"] not in ("DRAFT", "CONFIRMED", "ON_HOLD"):
        raise errors.err_invalid_state("Order cannot be cancelled from current state")
    builder, job = builder_of_order(order)
    prev = order["order_status"]

    if prev == "CONFIRMED":
        release_reservations(order)

    order["order_status"] = "CANCELLED"
    order["updated_at"] = helpers.stamp()
    order["version"] += 1

    # Cascade deliveries
    for d in db.deliveries.values():
        if d["sales_order_id"] == order["id"] and d["delivery_status"] in ("REQUESTED", "SCHEDULED"):
            if d["delivery_status"] == "SCHEDULED" and d["truck_shift_id"]:
                shift = db.truck_shifts.get(d["truck_shift_id"])
                if shift:
                    shift["booked_drops"] = max(0, shift["booked_drops"] - 1)
                    shift["updated_at"] = helpers.stamp()
                    shift["version"] += 1
            d["delivery_status"] = "CANCELLED"
            d["updated_at"] = helpers.stamp()
            d["version"] += 1

    builder["version"] += 1
    builder["updated_at"] = helpers.stamp()
    refresh_builder_exposure(builder)
    refresh_job_exposure(job)
    return order


def deliver_order(order, completion_dt):
    """Cascade delivery completion -> order DELIVERED."""
    builder, job = builder_of_order(order)

    # FLOAT_TO_SHIP re-price before exposure accounting
    if order["pricing_week_mode"] == "FLOAT_TO_SHIP":
        week = helpers.monday_of_week(completion_dt)
        order["priced_week_start"] = week
        order["order_total_cents"] = calc.price_order(order, week)

    sell_reserved(order)

    order["delivered_total_cents"] = order["order_total_cents"]
    order["order_status"] = "DELIVERED"
    order["updated_at"] = helpers.stamp()
    order["version"] += 1

    job["last_completed_delivery_date"] = completion_dt.date().isoformat()
    job["updated_at"] = helpers.stamp()
    job["version"] += 1

    builder["version"] += 1
    builder["updated_at"] = helpers.stamp()
    refresh_builder_exposure(builder)
    refresh_job_exposure(job)
    return order


def suspend_builder_cascade(builder):
    """Move builder's CONFIRMED orders to ON_HOLD, releasing reserved lots."""
    for order in db.sales_orders.values():
        job = db.jobs.get(order["job_id"])
        if not job or job["builder_id"] != builder["id"]:
            continue
        if order["order_status"] != "CONFIRMED":
            continue
        release_reservations(order)
        order["order_status"] = "ON_HOLD"
        order["updated_at"] = helpers.stamp()
        order["version"] += 1
    # exposure_committed_cents unchanged (ON_HOLD still counts) — refresh anyway
    refresh_all_exposures()

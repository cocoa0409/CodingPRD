"""Shared mutations, cascades, and the clock sweep (PRD 2.5, 3.1, 3.5, 3.7)."""
from datetime import timedelta

import calc
from store import db, now, touch
from validation import BARRIER_RANK, RANK_DOWN


def recompute_cohort(cohort):
    """Reservation-driven recompute among HOLD / PARTIALLY_ALLOCATED /
    FULLY_ALLOCATED (PRD 3.3). Other states are left untouched."""
    st = cohort["status"]
    if st not in ("HOLD", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED"):
        return
    rm, rf = calc.cohort_reserved(cohort["id"])
    any_res = calc.cohort_has_reserved(cohort["id"])
    if not any_res:
        new = "HOLD"
    elif cohort["count_male"] - rm == 0 and cohort["count_female"] - rf == 0:
        new = "FULLY_ALLOCATED"
    else:
        new = "PARTIALLY_ALLOCATED"
    if new != st:
        cohort["status"] = new


def post_consumption_cohort(cohort):
    """post_consumption_recompute (PRD 3.3 / scaffold 1.2): after a shipment
    departure decremented the live counts."""
    if cohort["count_male"] == 0 and cohort["count_female"] == 0:
        cohort["status"] = "SHIPPED"
        return
    rm, rf = calc.cohort_reserved(cohort["id"])
    any_res = calc.cohort_has_reserved(cohort["id"])
    if cohort["count_male"] - rm == 0 and cohort["count_female"] - rf == 0 and any_res:
        cohort["status"] = "FULLY_ALLOCATED"
    elif any_res:
        cohort["status"] = "PARTIALLY_ALLOCATED"
    else:
        cohort["status"] = "HOLD"


def order_coverage(order):
    """System coverage transitions: SOURCING|BACKORDERED -> ALLOCATED when the
    RESERVED totals reach the requested quantities; ALLOCATED -> SOURCING when
    coverage is lost."""
    am, af = calc.order_allocated(order["id"])
    full = am >= order["quantity_male"] and af >= order["quantity_female"]
    if full and order["status"] in ("SOURCING", "BACKORDERED"):
        order["status"] = "ALLOCATED"
    elif not full and order["status"] == "ALLOCATED":
        order["status"] = "SOURCING"


def release_allocation(alloc):
    """Allocation RESERVED -> RELEASED with cohort/order recompute (PRD 3.7)."""
    if alloc["status"] != "RESERVED":
        return False
    alloc["status"] = "RELEASED"
    cohort = db["cohorts"].get(alloc["cohort_id"])
    if cohort is not None:
        recompute_cohort(cohort)
        touch("cohorts", cohort["id"])
    order = db["orders"].get(alloc["order_id"])
    if order is not None:
        order_coverage(order)
        touch("orders", order["id"])
    return True


def cancel_shipment(sh):
    """Shipment PLANNED|LOADED -> CANCELLED; the order falls back from
    SCHEDULED to ALLOCATED unless a cascade already forced it elsewhere."""
    if sh["status"] not in ("PLANNED", "LOADED"):
        return False
    sh["status"] = "CANCELLED"
    touch("shipments", sh["id"])
    order = db["orders"].get(sh["order_id"])
    if order is not None and order["status"] == "SCHEDULED":
        order["status"] = "ALLOCATED"
        touch("orders", order["id"])
    return True


def facility_room_ids(facility_id):
    return {r["id"] for r in db["rooms"].values() if r["facility_id"] == facility_id}


def facility_transport_cascade(facility_id):
    """Cancel every PLANNED/LOADED shipment whose order draws any allocation
    from a cohort housed in this facility's rooms (PRD 3.1)."""
    room_ids = facility_room_ids(facility_id)
    for sh in list(db["shipments"].values()):
        if sh["status"] not in ("PLANNED", "LOADED"):
            continue
        draws = False
        for a in db["allocations"].values():
            if a["order_id"] != sh["order_id"] or a["status"] != "RESERVED":
                continue
            cohort = db["cohorts"].get(a["cohort_id"])
            if cohort is None:
                continue
            colony = db["colonies"].get(cohort["colony_id"])
            if colony is not None and colony["room_id"] in room_ids:
                draws = True
                break
        if draws:
            cancel_shipment(sh)


def facility_suspend(facility, reason):
    """Facility -> SUSPENDED plus the shipment-cancellation cascade."""
    facility["registration_status"] = "SUSPENDED"
    facility["suspension_reason"] = reason
    touch("facilities", facility["id"])
    facility_transport_cascade(facility["id"])


def positive_screen_cascade(room):
    """The four-hop barrier-downgrade cascade of PRD 3.5."""
    # Hop 1: room quarantines and downgrades exactly one rank.
    room["status"] = "QUARANTINED"
    room["quarantined_at"] = now()
    room["barrier_level"] = RANK_DOWN[room["barrier_level"]]
    touch("rooms", room["id"])
    new_rank = BARRIER_RANK[room["barrier_level"]]
    room_colony_ids = {c["id"] for c in db["colonies"].values() if c["room_id"] == room["id"]}
    # Hop 2: cohorts whose health rank exceeds the new room rank downgrade.
    downgraded = set()
    for c in db["cohorts"].values():
        if c["colony_id"] in room_colony_ids and BARRIER_RANK[c["health_status"]] > new_rank:
            c["health_status"] = room["barrier_level"]
            touch("cohorts", c["id"])
            downgraded.add(c["id"])
    # Hop 3: RESERVED allocations on downgraded cohorts whose order's
    # min_health_status now exceeds the cohort's rank are released.
    affected_orders = []
    for a in list(db["allocations"].values()):
        if a["status"] != "RESERVED" or a["cohort_id"] not in downgraded:
            continue
        cohort = db["cohorts"][a["cohort_id"]]
        order = db["orders"].get(a["order_id"])
        if order is None:
            continue
        if BARRIER_RANK[order["min_health_status"]] > BARRIER_RANK[cohort["health_status"]]:
            release_allocation(a)
            if order["id"] not in affected_orders:
                affected_orders.append(order["id"])
    # Hop 4: orders whose coverage broke revert; SCHEDULED orders first lose
    # their PLANNED/LOADED shipment, then go to SOURCING.
    for oid in affected_orders:
        order = db["orders"][oid]
        am, af = calc.order_allocated(oid)
        if am >= order["quantity_male"] and af >= order["quantity_female"]:
            continue
        if order["status"] == "SCHEDULED":
            for sh in list(db["shipments"].values()):
                if sh["order_id"] == oid and sh["status"] in ("PLANNED", "LOADED"):
                    cancel_shipment(sh)
            order["status"] = "SOURCING"
            touch("orders", oid)
        elif order["status"] == "ALLOCATED":
            order["status"] = "SOURCING"
            touch("orders", oid)
        # SOURCING / BACKORDERED remain; SHIPPED / DELIVERED / CLOSED untouched.


def escalate_inspection(insp):
    """Inspection -> ESCALATED and the site cascade (PRD 3.9)."""
    insp["status"] = "ESCALATED"
    if insp["facility_id"] is not None:
        fac = db["facilities"].get(insp["facility_id"])
        if fac is not None and fac["registration_status"] in ("REGISTERED", "UNDER_INSPECTION"):
            facility_suspend(fac, "OVERDUE_CORRECTIVE_ACTION")
    elif insp["customer_id"] is not None:
        cust = db["customers"].get(insp["customer_id"])
        if cust is not None and cust["account_status"] != "SUSPENDED":
            cust["account_status"] = "SUSPENDED"
            touch("customers", cust["id"])


def clock_sweep():
    """clock_sweep_effects: the three pinned steps of PRD 2.5, all strict
    comparisons against the new logical clock."""
    n = now()
    # 1. Protocol expiry.
    for p in db["protocols"].values():
        if p["status"] == "APPROVED" and p["expiration_date"] < n:
            p["status"] = "EXPIRED"
            touch("protocols", p["id"])
    # 2. Genetic-monitoring aging.
    for co in db["colonies"].values():
        if co["genetic_status"] == "CLEAR" and n > co["last_snp_panel_at"] + timedelta(
            weeks=co["snp_panel_interval_weeks"]
        ):
            co["genetic_status"] = "PANEL_DUE"
            touch("colonies", co["id"])
    # 3. Corrective-action escalation with site cascades.
    for insp in db["inspections"].values():
        if (
            insp["status"] == "CORRECTIVE_ACTION"
            and insp["corrective_deadline"] is not None
            and insp["corrective_deadline"] < n
        ):
            escalate_inspection(insp)
